"""Load, edit and preview the LinkedIn relevance-filter prompt.

The structured controls (maximum experience, whether unspecified experience is
accepted) generate the criteria text; the editable prompt stays the final
user-adjustable instruction that is actually sent to the model. Nothing is
hard-coded past the defaults below.
"""

from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy.orm import Session

import models

MODEL_NAME = "openai/gpt-oss-120b"
MODEL_LABEL = f"Groq — {MODEL_NAME}"

DEFAULT_MAX_EXPERIENCE_YEARS = 1.0
DEFAULT_ACCEPT_UNSPECIFIED = True
DEFAULT_BATCH_SIZE = 8
DEFAULT_MAX_JD_CHARS = 4000

# The compact classifier wrapper. Kept deliberately small: it is paid for on
# every batch, and the model only has to emit one token per job.
FORMAT_INSTRUCTIONS = (
    "\nClassify each job description by the criteria above.\n"
    "Reply with one line per ID in the form ID:Y (accept) or ID:N (reject).\n"
    "No explanations."
)


def _years(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = DEFAULT_MAX_EXPERIENCE_YEARS
    if number == int(number):
        number = int(number)
    return f"{number} year" if number == 1 else f"{number} years"


def build_criteria(max_experience_years, accept_unspecified_experience) -> str:
    """Default relevance criteria, derived from the structured controls."""
    limit = _years(max_experience_years)
    lines = [
        "Accept fresher or entry-level roles only.",
        f"Accept roles requiring at most {limit} of experience.",
    ]
    if accept_unspecified_experience:
        lines.append("Accept the JD when no experience requirement is mentioned.")
    else:
        lines.append("Reject the JD when no experience requirement is mentioned.")
    lines.append(f"Reject roles that clearly require more than {limit} of experience.")
    return "\n".join(lines)


def ensure_settings(db: Session) -> models.LinkedInFilterSettings:
    settings = db.query(models.LinkedInFilterSettings).first()
    if settings is None:
        settings = models.LinkedInFilterSettings(
            prompt=build_criteria(DEFAULT_MAX_EXPERIENCE_YEARS, DEFAULT_ACCEPT_UNSPECIFIED),
            max_experience_years=DEFAULT_MAX_EXPERIENCE_YEARS,
            accept_unspecified_experience=DEFAULT_ACCEPT_UNSPECIFIED,
            batch_size=DEFAULT_BATCH_SIZE,
            max_jd_chars=DEFAULT_MAX_JD_CHARS,
            model=MODEL_NAME,
            prompt_version=1,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def ensure_search_settings(db: Session) -> models.LinkedInSearchSettings:
    settings = db.query(models.LinkedInSearchSettings).first()
    if settings is None:
        settings = models.LinkedInSearchSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def system_prompt(settings: models.LinkedInFilterSettings) -> str:
    """The complete prompt sent to the filtering model."""
    criteria = (settings.prompt or "").strip() or build_criteria(
        settings.max_experience_years, settings.accept_unspecified_experience
    )
    return criteria + FORMAT_INSTRUCTIONS


def save_settings(db: Session, payload: dict) -> models.LinkedInFilterSettings:
    """Persist filter settings; bump the prompt version when the prompt changes."""
    settings = ensure_settings(db)
    previous_prompt = (settings.prompt or "").strip()

    if payload.get("max_experience_years") is not None:
        try:
            settings.max_experience_years = max(0.0, float(payload["max_experience_years"]))
        except (TypeError, ValueError):
            pass
    if payload.get("accept_unspecified_experience") is not None:
        settings.accept_unspecified_experience = bool(payload["accept_unspecified_experience"])
    if payload.get("batch_size") is not None:
        try:
            settings.batch_size = max(1, min(64, int(payload["batch_size"])))
        except (TypeError, ValueError):
            pass
    if payload.get("max_jd_chars") is not None:
        try:
            settings.max_jd_chars = max(400, min(50000, int(payload["max_jd_chars"])))
        except (TypeError, ValueError):
            pass

    regenerate = bool(payload.get("regenerate_prompt"))
    prompt = payload.get("prompt")
    if regenerate:
        settings.prompt = build_criteria(
            settings.max_experience_years, settings.accept_unspecified_experience
        )
    elif isinstance(prompt, str) and prompt.strip():
        settings.prompt = prompt.strip()

    if (settings.prompt or "").strip() != previous_prompt:
        settings.prompt_version = (settings.prompt_version or 1) + 1
    if not settings.prompt_version:
        settings.prompt_version = 1
    settings.model = MODEL_NAME

    db.commit()
    db.refresh(settings)
    return settings


def settings_payload(settings: Optional[models.LinkedInFilterSettings]) -> dict:
    if settings is None:
        criteria = build_criteria(DEFAULT_MAX_EXPERIENCE_YEARS, DEFAULT_ACCEPT_UNSPECIFIED)
        return {
            "prompt": criteria,
            "system_prompt": criteria + FORMAT_INSTRUCTIONS,
            "format_instructions": FORMAT_INSTRUCTIONS,
            "max_experience_years": DEFAULT_MAX_EXPERIENCE_YEARS,
            "accept_unspecified_experience": DEFAULT_ACCEPT_UNSPECIFIED,
            "batch_size": DEFAULT_BATCH_SIZE,
            "max_jd_chars": DEFAULT_MAX_JD_CHARS,
            "model": MODEL_NAME,
            "model_label": MODEL_LABEL,
            "prompt_version": 1,
        }

    prompt = (settings.prompt or "").strip()
    if not prompt:
        prompt = build_criteria(
            settings.max_experience_years, settings.accept_unspecified_experience
        )
    return {
        "prompt": prompt,
        "system_prompt": prompt + FORMAT_INSTRUCTIONS,
        "format_instructions": FORMAT_INSTRUCTIONS,
        "max_experience_years": (
            DEFAULT_MAX_EXPERIENCE_YEARS
            if settings.max_experience_years is None
            else settings.max_experience_years
        ),
        "accept_unspecified_experience": (
            DEFAULT_ACCEPT_UNSPECIFIED
            if settings.accept_unspecified_experience is None
            else bool(settings.accept_unspecified_experience)
        ),
        "batch_size": settings.batch_size or DEFAULT_BATCH_SIZE,
        "max_jd_chars": settings.max_jd_chars or DEFAULT_MAX_JD_CHARS,
        "model": settings.model or MODEL_NAME,
        "model_label": MODEL_LABEL,
        "prompt_version": settings.prompt_version or 1,
    }
