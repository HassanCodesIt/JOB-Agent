"""Import a completed scraper run file into PostgreSQL.

The scraper's ``Scraping Run N.json`` files remain the scraper-side source of
truth. This module never rewrites or migrates them; it only reads the
``{run_info, summary, jobs}`` payload and mirrors it into ``LinkedInRun`` /
``LinkedInJob``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

from sqlalchemy.orm import Session

import models
from linkedin_integration import url_utils
from linkedin_integration.modes import SCRAPER_DIR

RUN_FILE_PREFIX = "Scraping Run "
RUN_FILE_SUFFIX = ".json"
RUN_FILE_PATTERN = re.compile(r"^Scraping Run (\d+)\.json$")


def runs_dir() -> Path:
    return SCRAPER_DIR / "data" / "scraping_runs"


def list_run_files(directory: Optional[Path] = None) -> List[Path]:
    folder = directory or runs_dir()
    if not folder.exists():
        return []
    return sorted(
        (path for path in folder.glob(f"{RUN_FILE_PREFIX}*{RUN_FILE_SUFFIX}")
         if RUN_FILE_PATTERN.match(path.name)),
        key=lambda path: int(RUN_FILE_PATTERN.match(path.name).group(1)),
    )


def snapshot_run_files(directory: Optional[Path] = None) -> Set[str]:
    return {path.name for path in list_run_files(directory)}


def find_new_run_file(before: Set[str], directory: Optional[Path] = None) -> Optional[Path]:
    """Highest-numbered run file that did not exist in *before*."""
    fresh = [path for path in list_run_files(directory) if path.name not in before]
    if not fresh:
        return None
    return fresh[-1]


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return [value]
        return parsed if isinstance(parsed, list) else [value]
    return [value]


def _dump(value) -> Optional[str]:
    return json.dumps(value, ensure_ascii=False) if value else None


def _job_field(job: dict, *names):
    for name in names:
        if job.get(name) not in (None, ""):
            return job.get(name)
    return None


def build_job_payload(job: dict) -> dict:
    """Scraper job JSON -> the LinkedInJob column mapping.

    The scraper stores the matched role as ``target_role``; the database column
    is ``role``. Every scraper URL field is kept in its own column.
    """
    post_url = _job_field(job, "linkedin_post_url")
    return {
        "linkedin_post_url": url_utils.normalize(post_url),
        "job_url": url_utils.normalize(job.get("job_url")),
        "apply_url": url_utils.normalize(job.get("apply_url")),
        "image_url": url_utils.normalize(job.get("image_url")),
        "additional_apply_urls": _dump(url_utils.external_urls(job.get("additional_apply_urls"))),
        "linkedin_post_urn": job.get("linkedin_post_urn"),
        "company": job.get("company"),
        "role": _job_field(job, "target_role", "role"),
        "author": job.get("author"),
        "location": job.get("location"),
        "experience": job.get("experience"),
        "employment_type": job.get("employment_type"),
        "salary": job.get("salary"),
        "email": job.get("email"),
        "additional_emails": _dump([e for e in _json_list(job.get("additional_emails")) if e]),
        "application_method": job.get("application_method"),
        "application_methods": _dump(_json_list(job.get("application_methods"))),
        "application_instructions": _dump(_json_list(job.get("application_instructions"))),
        "job_description": job.get("job_description") or None,
        "full_post": job.get("full_post") or None,
        "skills": _dump(_json_list(job.get("skills"))),
        "responsibilities": _dump(_json_list(job.get("responsibilities"))),
        "qualifications": _dump(_json_list(job.get("qualifications"))),
        "match_reasons": _dump(_json_list(job.get("match_reasons"))),
        "has_image": bool(job.get("has_image")),
        "image_based_job_post": bool(job.get("image_based_job_post")),
    }


def read_run_file(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or "jobs" not in data:
        raise ValueError(f"{Path(path).name} is not a scraper run file.")
    return data


def import_run(
    db: Session,
    run_file: Path,
    linkedin_run: Optional[models.LinkedInRun] = None,
) -> models.LinkedInRun:
    """Mirror *run_file* into the database and return the stored run row.

    Jobs whose ``linkedin_post_url`` is already stored (from any earlier run)
    are skipped, so re-running the same search never duplicates the collected
    list or the filtering work.
    """
    data = read_run_file(Path(run_file))
    run_info = data.get("run_info") or {}
    summary = data.get("summary") or {}
    jobs: Sequence[dict] = data.get("jobs") or []

    run = linkedin_run or models.LinkedInRun()
    run.scraper_run_number = run_info.get("run_number")
    run.mode = run.mode or run_info.get("run_mode")
    run.sort_by = run.sort_by if run.sort_by is not None else run_info.get("sort_mode")
    run.date_posted = run.date_posted if run.date_posted is not None else run_info.get("date_posted_filter")
    run.summary_json = json.dumps(summary, ensure_ascii=False) if summary else None
    if run.started_at is None:
        run.started_at = _parse_time(run_info.get("started_at"))
    run.completed_at = _parse_time(run_info.get("completed_at")) or run.completed_at
    if run.status in (None, "running"):
        run.status = "completed"

    if linkedin_run is None:
        db.add(run)
        db.flush()

    imported = 0
    for job in jobs:
        payload = build_job_payload(job)
        if not payload["linkedin_post_url"]:
            continue
        exists = (
            db.query(models.LinkedInJob.id)
            .filter(models.LinkedInJob.linkedin_post_url == payload["linkedin_post_url"])
            .first()
        )
        if exists:
            continue
        job_row = models.LinkedInJob(linkedin_run_id=run.id, filter_status="pending", **payload)
        _assign_filter_batch(job_row)
        db.add(job_row)
        imported += 1

    run.collected_count = imported
    db.commit()
    db.refresh(run)
    return run


def _assign_filter_batch(job_row: models.LinkedInJob) -> None:
    """Batch A carries an email address, batch B does not (it never gets dropped)."""
    job_row.filter_batch = "email" if job_row.email else "no_email"


def _parse_time(value):
    if not value:
        return None
    try:
        import datetime

        return datetime.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def iter_summary(run: Optional[models.LinkedInRun]) -> dict:
    if run is None or not run.summary_json:
        return {}
    try:
        parsed = json.loads(run.summary_json)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
