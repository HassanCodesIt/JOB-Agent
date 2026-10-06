"""Scraper-shaped fixtures shared by the LinkedIn Job Finder tests.

Kept in its own module (not ``conftest``) so the tests can be collected from
either the project root or the ``tests`` folder without the scraper's own
``conftest`` module shadowing this one.
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def write_run_file(directory: Path, number: int, jobs=None, **run_info) -> Path:
    """Write a scraper-shaped run file exactly as the scraper would."""
    payload = {
        "run_info": {
            "run_number": number,
            "started_at": "2026-10-04T13:09:54+05:30",
            "completed_at": "2026-10-04T13:10:15+05:30",
            "target_roles": ["AI Developer"],
            "max_jds": 30,
            "run_mode": "standard",
            "date_posted_filter": None,
            "sort_mode": None,
            **run_info,
        },
        "summary": {
            "target_roles_searched": 1,
            "posts_processed": 4,
            "final_jds_collected": len(jobs or []),
            "stop_reason": "test",
        },
        "jobs": jobs or [],
    }
    path = Path(directory) / f"Scraping Run {number}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def sample_job(**overrides) -> dict:
    job = {
        "target_role": "AI Developer",
        "matched_role_variations": ["ai developer"],
        "also_matched_roles": [],
        "author": "Jane Recruiter",
        "company": "Acme AI",
        "location": "Remote",
        "experience": "0-1 years",
        "employment_type": "Full-time",
        "salary": None,
        "skills": ["Python", "LLMs"],
        "responsibilities": ["Build agents"],
        "qualifications": ["Fresher welcome"],
        "email": "jobs@acme.example",
        "additional_emails": [],
        "job_url": "https://www.linkedin.com/jobs/view/12345/",
        "apply_url": "https://acme.example/careers/apply",
        "additional_apply_urls": [],
        "linkedin_post_url": "https://www.linkedin.com/feed/update/urn:li:ugcPost:7512134645359009792/",
        "linkedin_post_urn": "urn:li:ugcPost:7512134645359009792",
        "application_method": "Email",
        "application_methods": ["Email", "LinkedIn Job"],
        "application_instructions": ["Send CV to jobs@acme.example"],
        "full_post": "I'm #hiring. We are looking for an AI Developer.\n\nRequirements:\n- 0-1 years\nApply at https://acme.example/careers/apply",
        "job_description": "AI Developer role. Fresher welcome. Python and LLM experience.",
        "match_reasons": ["Target role matched: AI Developer"],
        "has_image": False,
        "image_based_job_post": False,
        "image_url": None,
    }
    job.update(overrides)
    return job
