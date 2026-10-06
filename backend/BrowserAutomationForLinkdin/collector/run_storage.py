"""Persistent storage for completed scraping runs.

One scraping run produces exactly one JSON file under
``data/scraping_runs/Scraping Run <n>.json``, numbered from the files already
on disk. Storage is deliberately separate from collection: the scraper hands
over the matches it already printed, and this module only serialises them.

Nothing here changes what gets collected. In particular the LinkedIn post URL
requirement is enforced again on the way out, so a record can never be stored
without the permalink the scraper already validated.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from collector import logger
from collector.models import (
    METHOD_IMAGE_JOB_POST,
    NOT_SPECIFIED,
    JobMatch,
    Stats,
)
from collector.run_modes import date_posted_filter

DATA_DIRNAME = "data"
RUNS_DIRNAME = "scraping_runs"
RUN_FILE_PREFIX = "Scraping Run "
RUN_FILE_SUFFIX = ".json"
RUN_FILE_RE = re.compile(r"^Scraping Run (\d+)\.json$")

# How many times to retry when a file appeared between choosing a number and
# creating it. Purely defensive: the exclusive create below never overwrites.
_CREATE_ATTEMPTS = 50


def project_root() -> Path:
    """Directory that holds ``data/`` -- the project, not the current shell dir."""
    return Path(__file__).resolve().parent.parent


def runs_dir(base: Optional[Path] = None) -> Path:
    root = Path(base) if base is not None else project_root()
    return root / DATA_DIRNAME / RUNS_DIRNAME


def run_file_name(run_number: int) -> str:
    return f"{RUN_FILE_PREFIX}{run_number}{RUN_FILE_SUFFIX}"


def existing_run_numbers(directory: Path) -> List[int]:
    """Run numbers already on disk. Unrelated files are ignored."""
    if not directory.is_dir():
        return []
    numbers = []
    for entry in directory.iterdir():
        match = RUN_FILE_RE.match(entry.name)
        if match and entry.is_file():
            numbers.append(int(match.group(1)))
    return sorted(numbers)


def next_run_number(directory: Path) -> int:
    """Highest existing run number plus one.

    Gaps are irrelevant: with runs 1, 2 and 5 present the next run is 6, and
    with none present it is 1.
    """
    numbers = existing_run_numbers(directory)
    return numbers[-1] + 1 if numbers else 1


def _clean(value):
    """Missing values become null instead of a placeholder string."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value or value == NOT_SPECIFIED:
            return None
    return value


def _clean_list(values: Optional[Iterable[str]]) -> List[str]:
    return [str(value).strip() for value in (values or []) if str(value).strip()]


def job_to_dict(match: JobMatch) -> dict:
    """One collected JD, using the field names the terminal already prints."""
    post = match.post
    return {
        "target_role": _clean(match.target_role),
        "matched_role_variations": _clean_list(match.role_match.matched_variations),
        "also_matched_roles": _clean_list(match.other_categories),
        "author": _clean(post.author),
        "company": _clean(match.company),
        "location": _clean(match.location),
        "experience": _clean(match.experience),
        "employment_type": _clean(match.employment_type),
        "salary": _clean(match.salary),
        "skills": _clean_list(match.skills),
        "responsibilities": _clean_list(match.responsibilities),
        "qualifications": _clean_list(match.qualifications),
        # Each application method stays its own field.
        "email": _clean(match.emails[0] if match.emails else None),
        "additional_emails": _clean_list(match.additional_emails),
        "job_url": _clean(match.job_url),
        "apply_url": _clean(match.apply_url),
        "additional_apply_urls": _clean_list(match.additional_apply_urls),
        "linkedin_post_url": _clean(post.url),
        "linkedin_post_urn": _clean(post.urn),
        "application_method": _clean(match.application_method),
        "application_methods": _clean_list(match.methods),
        "application_instructions": _clean_list(match.application_instructions),
        "full_post": post.text or "",
        "job_description": _clean(match.job_description),
        "match_reasons": _clean_list(match.reasons),
        "has_image": bool(post.has_image),
        "image_based_job_post": bool(METHOD_IMAGE_JOB_POST in match.methods),
        "image_url": _clean(post.image_url),
    }


def summary_to_dict(stats: Stats) -> dict:
    """The run summary, mirroring the terminal summary exactly."""
    return {
        "target_roles_searched": stats.roles_searched,
        "posts_processed": stats.posts_processed,
        "potential_job_posts": stats.potential_job_posts,
        "posts_with_email": stats.posts_with_email,
        "posts_with_job_url": stats.posts_with_job_url,
        "posts_with_apply_url": stats.posts_with_apply_url,
        "posts_without_any_application_method": stats.no_application_method,
        "collected_by_email": stats.collected_by_email,
        "collected_by_linkedin_job_url": stats.collected_by_job_url,
        "collected_by_apply_url": stats.collected_by_apply_url,
        "collected_with_multiple_methods": stats.collected_with_multiple_methods,
        "duplicates_removed": stats.duplicates_removed,
        "jds_skipped_missing_post_url": stats.missing_post_url,
        "posts_with_image_job_info": stats.posts_with_image,
        "collected_by_image_job_post": stats.collected_by_image,
        "valid_job_matches": stats.valid_job_matches,
        "final_jds_collected": stats.collected,
        "stop_reason": _clean(stats.stop_reason),
    }


def build_run_payload(
    matches: Sequence[JobMatch],
    stats: Stats,
    cfg,
    run_number: int,
    started_at: Optional[str] = None,
    run_mode: str = "standard",
    sort_mode: Optional[str] = None,
) -> dict:
    """Assemble the JSON document for one run.

    ``run_mode`` names the entry point that produced the run and decides the
    ``date_posted_filter`` field, while ``sort_mode`` records the Sort by option
    that was actually requested. Both are new keys added alongside the existing
    metadata, and both are ``null`` for a run that used neither filter, so runs
    stored before these entry points existed still read correctly.

    A record without a LinkedIn post URL is never stored: the post URL is a
    required field, and the storage layer does not get to relax that.
    """
    jobs = []
    for match in matches:
        if not (match.post.url or "").strip():
            logger.warn(
                "Not storing a JD without a LinkedIn post URL "
                f"(match reasons: {'; '.join(match.reasons[:1]) or 'unknown'})"
            )
            continue
        jobs.append(job_to_dict(match))

    return {
        "run_info": {
            "run_number": run_number,
            "started_at": started_at,
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "target_roles": _clean_list(getattr(cfg, "target_roles", [])),
            "max_jds": getattr(cfg, "max_jds", None),
            "run_mode": run_mode,
            "date_posted_filter": date_posted_filter(run_mode),
            "sort_mode": sort_mode,
        },
        "summary": summary_to_dict(stats),
        "jobs": jobs,
    }


def save_scraping_run(
    matches: Sequence[JobMatch],
    stats: Stats,
    cfg,
    started_at: Optional[str] = None,
    base: Optional[Path] = None,
    run_mode: str = "standard",
    sort_mode: Optional[str] = None,
) -> Path:
    """Write one run to its own JSON file and report the outcome.

    Returns the file path. Any failure is logged as an error and re-raised, so
    a run is never reported as saved when it was not.
    """
    directory = runs_dir(base)
    run_number = next_run_number(directory)

    logger.info("Saving scraping run...")
    logger.info(f"Scraping Run number: {run_number}")
    logger.info(f"JDs to save: {len(matches)}")

    payload = build_run_payload(
        matches, stats, cfg, run_number, started_at, run_mode=run_mode, sort_mode=sort_mode
    )

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.error(f"Failed to save {run_file_name(run_number)}: {exc}")
        raise

    path = _write_exclusive(directory, run_number, payload)

    logger.ok(f"Scraping Run {run_number} saved successfully.")
    logger.ok(f"File: {_display_path(path)}")
    return path


def _write_exclusive(directory: Path, run_number: int, payload: dict) -> Path:
    """Create the file, refusing to overwrite an existing run.

    ``"x"`` mode makes creation fail if the name is taken, which is what keeps
    an existing run safe even if the numbering raced.
    """
    last_error: Optional[Exception] = None
    for _ in range(_CREATE_ATTEMPTS):
        path = directory / run_file_name(run_number)
        try:
            with path.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            return path
        except FileExistsError as exc:
            # Another run took this number; move on to the next one.
            last_error = exc
            run_number += 1
            logger.info(f"Scraping Run number: {run_number}")
        except Exception as exc:
            logger.error(f"Failed to save {run_file_name(run_number)}: {exc}")
            raise

    logger.error(f"Failed to save Scraping Run {run_number}.json: {last_error}")
    raise RuntimeError("could not find a free scraping run number")


def _display_path(path: Path) -> str:
    """Show the path relative to the project when possible, as in the docs."""
    try:
        return str(path.relative_to(project_root()))
    except ValueError:
        return str(path)