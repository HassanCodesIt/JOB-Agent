"""Minimal-token relevance filtering for imported LinkedIn jobs.

Token usage is a first-class requirement here:

* only cleaned JD text is sent - never URLs, company, location, e-mail,
  scraper metadata or database ids as semantic data,
* JDs travel in compact batches instead of one verbose call each,
* the model answers with one ``ID:Y`` / ``ID:N`` line per JD and no prose,
* the output budget is sized from the batch length, not fixed high.
"""

from __future__ import annotations

import datetime
import os
import re
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

import models
from linkedin_integration import prompt_service

# --------------------------------------------------------------------------- #
# Local JD preparation
# --------------------------------------------------------------------------- #

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_INMAIL_RE = re.compile(r"\bE-?mail\s+sent\s+to\b.*$", re.IGNORECASE)

# Deterministic LinkedIn navigation chrome. Only exact line matches are dropped
# so genuine JD content (which is rarely a single one-word line) survives.
_BOILERPLATE_LINES = {
    "like",
    "liked",
    "comment",
    "repost",
    "reposted",
    "send",
    "save",
    "follow",
    "followed",
    "share",
    "translate",
    "translated",
    "promoted",
    "see more",
    "less",
    "expand",
    "linkedin",
    "premium",
    "sign in",
    "notifications",
}
_TIMESTAMP_LINE_RE = re.compile(r"^\d+[dhwm]$")
_MARKER = "\n...\n"


def _strip_boilerplate(text: str) -> str:
    kept: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.casefold().rstrip(".")
        if lowered in _BOILERPLATE_LINES:
            continue
        if _TIMESTAMP_LINE_RE.match(lowered):
            continue
        kept.append(line)
    return "\n".join(kept)


def truncate(text: str, max_chars: int) -> str:
    """Deterministic head/tail truncation so requirement blocks at the end survive."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    budget = max_chars - len(_MARKER)
    head = int(budget * 0.6)
    tail = budget - head
    if tail <= 0:
        return text[:max_chars]
    return text[:head] + _MARKER + text[-tail:]


def clean_jd(text, max_chars: Optional[int] = None) -> str:
    """Whitespace-normalised, URL-free, boilerplate-free JD text."""
    if not text:
        return ""
    result = str(text)
    result = _URL_RE.sub(" ", result)
    result = _EMAIL_RE.sub(" ", result)
    result = _INMAIL_RE.sub(" ", result)
    result = _strip_boilerplate(result)
    result = re.sub(r"[ \t]+", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = result.strip()
    if max_chars:
        result = truncate(result, max_chars)
    return result


def job_text(job: models.LinkedInJob) -> str:
    """Smallest useful text: extracted JD first, cleaned full post only as fallback."""
    if job.job_description and job.job_description.strip():
        return job.job_description
    if job.full_post and job.full_post.strip():
        return job.full_post
    parts = [job.skills, job.responsibilities, job.qualifications, job.experience]
    joined = " ".join(part for part in parts if part)
    return joined.strip()


# --------------------------------------------------------------------------- #
# Batches
# --------------------------------------------------------------------------- #

BATCH_EMAIL = "email"
BATCH_NO_EMAIL = "no_email"


def batch_for(job: models.LinkedInJob) -> str:
    """Batch A carries an address, batch B does not. Batch B is never dropped."""
    return BATCH_EMAIL if (job.email or "").strip() else BATCH_NO_EMAIL


def split_batches(jobs: Iterable[models.LinkedInJob]) -> Dict[str, List[models.LinkedInJob]]:
    batches: Dict[str, List[models.LinkedInJob]] = {BATCH_EMAIL: [], BATCH_NO_EMAIL: []}
    for job in jobs:
        batches[batch_for(job)].append(job)
    return batches


def chunks(items: Sequence, size: int) -> List[Sequence]:
    size = max(1, int(size or 1))
    return [items[index:index + size] for index in range(0, len(items), size)]


# --------------------------------------------------------------------------- #
# Prompt building and parsing
# --------------------------------------------------------------------------- #

def build_user_prompt(items: Sequence[Tuple[int, str]]) -> str:
    """``ID\\n<JD>`` blocks - no wrapper text beyond the separators."""
    blocks = []
    for job_id, jd in items:
        blocks.append(f"{job_id}\n{jd}")
    return "\n\n".join(blocks)


def build_messages(settings: models.LinkedInFilterSettings,
                   items: Sequence[Tuple[int, str]]) -> List[dict]:
    return [
        {"role": "system", "content": prompt_service.system_prompt(settings)},
        {"role": "user", "content": build_user_prompt(items)},
    ]


OUTPUT_TOKENS_PER_JD = 8
# gpt-oss reasons before it answers: a budget of a few tokens per JD is
# consumed entirely by that internal reasoning and the reply comes back empty
# (finish_reason=length). 512 tokens of headroom is the smallest value that
# reliably returns one decision line per JD in a full batch.
OUTPUT_TOKENS_HEADROOM = 512
REASONING_EFFORT = "low"


def max_output_tokens(count: int) -> int:
    """Output budget scaled to the batch: one line per JD, plus reasoning room."""
    count = max(1, int(count or 1))
    return OUTPUT_TOKENS_PER_JD * count + OUTPUT_TOKENS_HEADROOM


_DECISION_RE = re.compile(r"^\s*(\d+)\s*[:\-]\s*([A-Za-z]+)", re.MULTILINE)
_POSITIVE = {"Y", "YES", "PASS", "KEEP", "RELEVANT", "ACCEPT", "TRUE"}
_NEGATIVE = {"N", "NO", "REJECT", "SKIP", "IRRELEVANT", "FALSE"}


def parse_decisions(raw: Optional[str], expected_ids: Sequence[int]) -> Tuple[Dict[int, bool], Set[int]]:
    """Canonical ``ID:Y`` / ``ID:N`` parser with a tolerant token fallback.

    A job with no deterministic classification token is reported as missing so
    the caller can mark it ``error`` instead of guessing from prose.
    """
    expected = {int(job_id) for job_id in expected_ids}
    decisions: Dict[int, bool] = {}
    if raw:
        for match in _DECISION_RE.finditer(raw):
            job_id = int(match.group(1))
            if job_id not in expected or job_id in decisions:
                continue
            token = match.group(2).upper()
            if token in _POSITIVE:
                decisions[job_id] = True
            elif token in _NEGATIVE:
                decisions[job_id] = False
    missing = expected - set(decisions)
    return decisions, missing


# --------------------------------------------------------------------------- #
# Model call
# --------------------------------------------------------------------------- #

_RETRYABLE_MARKERS = ("429", "rate limit", "tokens per day", "401", "invalid api key", "quota")


def _api_keys(db: Session) -> List[str]:
    keys: List[str] = []
    user = db.query(models.User).first()
    if user is not None:
        keys.extend([user.groq_api_key, user.groq_backup_api_key])
    keys.extend([os.getenv("GROQ_API_KEY"), os.getenv("GROQ_BACKUP_API_KEY")])
    seen: Set[str] = set()
    unique: List[str] = []
    for key in keys:
        if key and key.strip() and key.strip() not in seen:
            seen.add(key.strip())
            unique.append(key.strip())
    return unique


def call_model(messages: List[dict], max_tokens: int, db: Session) -> str:
    """Groq classification call. The API key is never logged or returned."""
    from groq import Groq

    keys = _api_keys(db)
    if not keys:
        raise RuntimeError("No Groq API key configured. Add one in Settings.")

    last_error: Optional[Exception] = None
    for key in keys:
        try:
            client = Groq(api_key=key)
            completion = client.chat.completions.create(
                model=prompt_service.MODEL_NAME,
                messages=messages,
                temperature=0,
                # gpt-oss reasons before answering; low effort keeps that internal
                # spend bounded so a small output budget still gets a full reply.
                reasoning_effort=REASONING_EFFORT,
                max_completion_tokens=max_tokens,
            )
            return completion.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a batch error
            last_error = exc
            text = str(exc).lower()
            if not any(marker in text for marker in _RETRYABLE_MARKERS):
                raise
    raise RuntimeError(str(last_error) if last_error else "Filtering model is unavailable.")


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #

def _needs_filter(job: models.LinkedInJob, current_version: int, force: bool) -> bool:
    if force:
        return True
    if job.filter_status in (None, "", "pending", "error"):
        return True
    if job.filter_status in ("accepted", "rejected"):
        # A decision that already reflects the active prompt is left untouched;
        # decisions made under an older prompt are refreshed on the next run.
        return (job.filter_prompt_version or 0) != current_version
    return True


def _record(job: models.LinkedInJob, status: str, settings, error: Optional[str] = None) -> None:
    job.filter_status = status
    job.filter_batch = batch_for(job)
    job.filter_model = prompt_service.MODEL_NAME
    job.filter_prompt_version = settings.prompt_version or 1
    job.filter_error = error
    job.filtered_at = datetime.datetime.utcnow()


def run_filter(
    db: Session,
    *,
    force: bool = False,
    run_id: Optional[int] = None,
) -> dict:
    """Split the collected jobs into the two batches and classify them."""
    settings = prompt_service.ensure_settings(db)

    query = db.query(models.LinkedInJob)
    if run_id:
        query = query.filter(models.LinkedInJob.linkedin_run_id == run_id)
    jobs = query.order_by(models.LinkedInJob.id.asc()).all()

    current_version = settings.prompt_version or 1
    selected = [job for job in jobs if _needs_filter(job, current_version, force)]
    skipped = len(jobs) - len(selected)

    # Keep every job's batch assignment fresh, including the skipped ones.
    for job in jobs:
        job.filter_batch = batch_for(job)

    accepted = rejected = errors = 0
    touched_runs: Set[int] = set()

    # Batch A (with e-mail) and batch B (without) are classified separately, so
    # a failure in one never affects the other.
    for batch_jobs in split_batches(selected).values():
        for group in chunks(batch_jobs, settings.batch_size):
            by_id = {job.id: job for job in group}
            items: List[Tuple[int, str]] = []
            for job in group:
                text = clean_jd(job_text(job), settings.max_jd_chars)
                if not text:
                    _record(job, "error", settings, "No job description text available.")
                    errors += 1
                    continue
                items.append((job.id, text))
            if not items:
                continue

            try:
                raw = call_model(build_messages(settings, items), max_output_tokens(len(items)), db)
                decisions, missing = parse_decisions(raw, [job_id for job_id, _ in items])
                if missing:
                    # A truncated reply is a malformed batch: retry it once with a
                    # larger budget instead of failing the jobs in it.
                    retry_raw = call_model(
                        build_messages(settings, items), max_output_tokens(len(items)) * 4, db
                    )
                    retry_decisions, missing = parse_decisions(
                        retry_raw, [job_id for job_id, _ in items]
                    )
                    decisions = {**decisions, **retry_decisions}
            except Exception as exc:  # noqa: BLE001 - one failed batch must not drop the jobs
                for job_id, _ in items:
                    _record(by_id[job_id], "error", settings, f"Filtering request failed: {exc}")
                    errors += 1
                continue

            for job_id, _ in items:
                job = by_id[job_id]
                if job_id not in decisions:
                    # Never invent a decision for an id the model did not answer.
                    _record(job, "error", settings, "Model returned no decision for this job.")
                    errors += 1
                elif decisions[job_id]:
                    _record(job, "accepted", settings)
                    accepted += 1
                else:
                    _record(job, "rejected", settings)
                    rejected += 1
                touched_runs.add(job.linkedin_run_id or 0)

    db.commit()

    for run_id_value in sorted(run_id for run_id in touched_runs if run_id):
        run = db.query(models.LinkedInRun).filter(models.LinkedInRun.id == run_id_value).first()
        if run is None:
            continue
        run.filtered_count = (
            db.query(models.LinkedInJob)
            .filter(
                models.LinkedInJob.linkedin_run_id == run.id,
                models.LinkedInJob.filter_status == "accepted",
            )
            .count()
        )
    db.commit()

    return {
        "scanned": len(jobs),
        "filtered": len(selected),
        "skipped": skipped,
        "accepted": accepted,
        "rejected": rejected,
        "errors": errors,
        "prompt_version": current_version,
        "model": prompt_service.MODEL_NAME,
    }
