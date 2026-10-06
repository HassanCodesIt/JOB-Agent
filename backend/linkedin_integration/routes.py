"""HTTP surface for the LinkedIn Job Finder feature.

Kept in its own module so the feature reads as one coherent surface instead of
being scattered through ``main.py``. The factory receives the application's
template engine, DB dependency and the existing ``process_application``
pipeline so the integration reuses them instead of building a second one.
"""

from __future__ import annotations

import json
from typing import Callable, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

import models
from linkedin_integration import filter_service, modes, prompt_service, runner, url_utils

JOB_PREVIEW_CHARS = 240
PAGE_JOB_LIMIT = 60


# --------------------------------------------------------------------------- #
# Payload builders
# --------------------------------------------------------------------------- #

def _text_preview(value: Optional[str], limit: int = JOB_PREVIEW_CHARS) -> str:
    if not value:
        return ""
    collapsed = " ".join(str(value).split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def job_subcategories(job: models.LinkedInJob) -> List[str]:
    """Display categories inside the "Without Email" group."""
    subs: List[str] = []
    if url_utils.normalize(job.apply_url) or _json_list(job.additional_apply_urls):
        subs.append("apply_link")
    if url_utils.normalize(job.job_url):
        subs.append("linkedin_job")
    if job.image_based_job_post or job.has_image:
        subs.append("image_job")
    if not subs:
        subs.append("other")
    return subs


def job_payload(job: models.LinkedInJob, show_draft: bool = False) -> dict:
    """Row payload for the card partial - never the raw scraper payload."""
    jd_source = job.job_description or job.full_post or ""
    links = {
        "post": url_utils.normalize(job.linkedin_post_url),
        "job": url_utils.normalize(job.job_url),
        "apply": url_utils.normalize(job.apply_url),
        "image": url_utils.normalize(job.image_url),
        "extra_apply": url_utils.external_urls(_json_list(job.additional_apply_urls)),
    }
    return {
        "id": job.id,
        "run_id": job.linkedin_run_id,
        "role": job.role or "Untitled role",
        "company": job.company or job.author or "Company not specified",
        "location": job.location or "—",
        "experience": job.experience or "—",
        "employment_type": job.employment_type or "—",
        "salary": job.salary,
        "email": job.email,
        "preview": _text_preview(jd_source),
        "full_text": jd_source,
        "skills": _json_list(job.skills),
        "responsibilities": _json_list(job.responsibilities),
        "qualifications": _json_list(job.qualifications),
        "application_method": job.application_method,
        "methods": _json_list(job.application_methods),
        "instructions": _json_list(job.application_instructions),
        "has_image": bool(job.has_image),
        "image_based_job_post": bool(job.image_based_job_post),
        "links": links,
        "batch": job.filter_batch or filter_service.batch_for(job),
        "subs": job_subcategories(job),
        "filter_status": job.filter_status or "pending",
        "filter_error": job.filter_error,
        "filtered_at": job.filtered_at.isoformat() if job.filtered_at else None,
        "filter_model": job.filter_model,
        "filter_prompt_version": job.filter_prompt_version,
        "application_id": job.job_application_id,
        "show_draft": show_draft,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def run_payload(run: models.LinkedInRun) -> dict:
    mode = modes.MODES_BY_KEY.get(run.mode or "")
    effective = {"sort_by": run.sort_by, "date_posted": run.date_posted}
    facets = modes.facet_labels(mode, effective) if mode else []
    return {
        "id": run.id,
        "mode": run.mode,
        "mode_label": mode.label if mode else (run.mode or "LinkedIn search"),
        "role": run.role,
        "sort_by": run.sort_by,
        "date_posted": run.date_posted,
        "facets": facets,
        "status": run.status,
        "process_state": run.process_state,
        "process_id": run.process_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "exit_code": run.exit_code,
        "error_message": run.error_message,
        "collected_count": run.collected_count or 0,
        "filtered_count": run.filtered_count or 0,
        "scraper_run_number": run.scraper_run_number,
    }


def counts_payload(db: Session) -> dict:
    total = db.query(models.LinkedInJob).count()
    with_email = (
        db.query(models.LinkedInJob).filter(models.LinkedInJob.filter_batch == "email").count()
    )
    no_email = total - with_email
    accepted = (
        db.query(models.LinkedInJob).filter(models.LinkedInJob.filter_status == "accepted").count()
    )
    accepted_email = (
        db.query(models.LinkedInJob)
        .filter(
            models.LinkedInJob.filter_status == "accepted",
            models.LinkedInJob.filter_batch == "email",
        )
        .count()
    )
    pending = (
        db.query(models.LinkedInJob)
        .filter(models.LinkedInJob.filter_status.in_(["pending", "error"]))
        .count()
    )
    return {
        "collected": total,
        "with_email": with_email,
        "no_email": no_email,
        "accepted": accepted,
        "accepted_email": accepted_email,
        "accepted_no_email": accepted - accepted_email,
        "pending": pending,
        "runs": db.query(models.LinkedInRun).count(),
    }


def page_meta(db: Session) -> dict:
    search_settings = prompt_service.ensure_search_settings(db)
    filter_settings = prompt_service.ensure_settings(db)
    active = runner.active_run(db)
    recent_runs = (
        db.query(models.LinkedInRun)
        .order_by(models.LinkedInRun.started_at.desc())
        .limit(8)
        .all()
    )
    return {
        "modes": modes.modes_payload(),
        "sort_options": [{"value": value, "label": label} for value, label in modes.SORT_OPTIONS],
        "date_options": [{"value": value, "label": label} for value, label in modes.DATE_OPTIONS],
        "preset_roles": modes.load_preset_roles(),
        "search": {
            "default_role": search_settings.default_role,
            "sort_by": search_settings.sort_by or modes.SORT_RELEVANCE,
            "date_posted": search_settings.date_posted or modes.DATE_ANY,
        },
        "filter_settings": prompt_service.settings_payload(filter_settings),
        "active_run": run_payload(active) if active else None,
        "runs": [run_payload(run) for run in recent_runs],
        "counts": counts_payload(db),
        "model_label": prompt_service.MODEL_LABEL,
    }


# --------------------------------------------------------------------------- #
# Router factory
# --------------------------------------------------------------------------- #

def create_linkedin_router(
    *,
    templates,
    get_db: Callable,
    process_application: Callable,
    is_setup_complete: Callable,
) -> APIRouter:
    router = APIRouter()

    def _render(request: Request, db: Session, **context):
        meta = page_meta(db)
        payload = dict(meta)
        payload["meta"] = meta
        payload["meta_json"] = json.dumps(meta, ensure_ascii=False)
        payload.update(context)
        payload["request"] = request
        return templates.TemplateResponse("linkedin_jobs.html", payload)

    # ------------------------------ page ------------------------------ #
    @router.get("/linkedin-jobs", response_class=HTMLResponse)
    def linkedin_jobs_page(request: Request, db: Session = Depends(get_db)):
        if not is_setup_complete(db):
            return RedirectResponse(url="/setup", status_code=307)
        return _render(request, db)

    @router.get("/api/linkedin/meta")
    def linkedin_meta(db: Session = Depends(get_db)):
        return page_meta(db)

    @router.get("/api/linkedin/browser-status")
    def linkedin_browser_status():
        """Live probe of the logged-in Chrome session the scraper attaches to."""
        cdp_url = modes.load_cdp_url()
        reachable = runner.cdp_reachable(cdp_url)
        return {
            "reachable": reachable,
            "cdp_url": cdp_url,
            "message": None if reachable else runner.browser_error_message(cdp_url),
        }

    # ------------------------------ runs ------------------------------ #
    @router.get("/api/linkedin/runs")
    def list_runs(limit: int = 20, db: Session = Depends(get_db)):
        limit = max(1, min(limit, 100))
        rows = (
            db.query(models.LinkedInRun)
            .order_by(models.LinkedInRun.started_at.desc())
            .limit(limit)
            .all()
        )
        return {"runs": [run_payload(row) for row in rows], "active": bool(runner.active_run(db))}

    @router.post("/api/linkedin/runs/start")
    def start_run(
        background_tasks: BackgroundTasks,
        data: dict = None,
        db: Session = Depends(get_db),
    ):
        data = data or {}
        run = runner.start_run(
            db,
            mode_key=data.get("mode") or "standard",
            role=data.get("role") or "",
            sort_by=data.get("sort_by"),
            date_posted=data.get("date_posted"),
        )
        background_tasks.add_task(runner.watch_run, run.id)
        return {"run": run_payload(run)}

    @router.get("/api/linkedin/runs/{run_id}")
    def get_run(run_id: int, db: Session = Depends(get_db)):
        run = db.query(models.LinkedInRun).filter(models.LinkedInRun.id == run_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return {"run": run_payload(run)}

    @router.post("/api/linkedin/runs/{run_id}/stop")
    def stop_run(run_id: int, db: Session = Depends(get_db)):
        """Terminate a running search process; the watcher imports whatever it produced."""
        run = runner.stop_run(db, run_id)
        return {"run": run_payload(run)}

    # ------------------------------ jobs ------------------------------ #
    @router.get("/api/linkedin/jobs")
    def list_jobs(
        scope: str = "collected",
        batch: str = "all",
        sub: str = "all",
        run_id: Optional[int] = None,
        limit: int = PAGE_JOB_LIMIT,
        offset: int = 0,
        format: str = "html",
        db: Session = Depends(get_db),
    ):
        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        query = db.query(models.LinkedInJob)
        if run_id:
            query = query.filter(models.LinkedInJob.linkedin_run_id == run_id)
        if scope == "filtered":
            query = query.filter(models.LinkedInJob.filter_status == "accepted")
        elif scope == "rejected":
            query = query.filter(models.LinkedInJob.filter_status == "rejected")

        if batch == "email":
            query = query.filter(models.LinkedInJob.filter_batch == "email")
        elif batch == "no_email":
            query = query.filter(models.LinkedInJob.filter_batch != "email")

        rows = query.order_by(models.LinkedInJob.id.desc()).all()
        if sub != "all":
            rows = [row for row in rows if sub in job_subcategories(row)]

        page = rows[offset:offset + limit]
        show_draft = scope == "filtered"
        if format == "json":
            # Same rows as the card HTML, for API clients (the React app).
            return {
                "total": len(rows),
                "offset": offset,
                "limit": limit,
                "count": len(page),
                "has_more": offset + len(page) < len(rows),
                "items": [job_payload(row, show_draft=show_draft) for row in page],
            }
        html = "".join(
            templates.get_template("partials/linkedin_job_card.html").render(
                item=job_payload(row, show_draft=show_draft)
            )
            for row in page
        )
        return {
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "count": len(page),
            "has_more": offset + len(page) < len(rows),
            "html": html,
        }

    @router.get("/api/linkedin/jobs/{job_id}")
    def get_job(job_id: int, db: Session = Depends(get_db)):
        job = db.query(models.LinkedInJob).filter(models.LinkedInJob.id == job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        payload = job_payload(job, show_draft=True)
        payload["instructions"] = _json_list(job.application_instructions)
        payload["match_reasons"] = _json_list(job.match_reasons)
        return {"job": payload}

    # ---------------------------- search settings ----------------------- #
    @router.get("/api/linkedin/search-settings")
    def get_search_settings(db: Session = Depends(get_db)):
        settings = prompt_service.ensure_search_settings(db)
        return {
            "settings": {
                "default_role": settings.default_role,
                "sort_by": settings.sort_by or modes.SORT_RELEVANCE,
                "date_posted": settings.date_posted or modes.DATE_ANY,
            }
        }

    @router.post("/api/linkedin/search-settings")
    def save_search_settings(data: dict = None, db: Session = Depends(get_db)):
        data = data or {}
        settings = prompt_service.ensure_search_settings(db)
        if data.get("default_role") is not None:
            settings.default_role = str(data.get("default_role")).strip() or None
        if data.get("sort_by") in (value for value, _ in modes.SORT_OPTIONS):
            settings.sort_by = data.get("sort_by")
        if data.get("date_posted") in (value for value, _ in modes.DATE_OPTIONS):
            settings.date_posted = data.get("date_posted")
        db.commit()
        db.refresh(settings)
        return {
            "settings": {
                "default_role": settings.default_role,
                "sort_by": settings.sort_by or modes.SORT_RELEVANCE,
                "date_posted": settings.date_posted or modes.DATE_ANY,
            }
        }

    # ---------------------------- filtering --------------------------- #
    @router.post("/api/linkedin/filter")
    def filter_jobs(data: dict = None, db: Session = Depends(get_db)):
        data = data or {}
        summary = filter_service.run_filter(
            db,
            force=bool(data.get("force")),
            run_id=data.get("run_id"),
        )
        return {"summary": summary, "counts": counts_payload(db)}

    @router.get("/api/linkedin/filter-settings")
    def get_filter_settings(db: Session = Depends(get_db)):
        return {"settings": prompt_service.settings_payload(prompt_service.ensure_settings(db))}

    @router.post("/api/linkedin/filter-settings")
    def save_filter_settings(data: dict = None, db: Session = Depends(get_db)):
        settings = prompt_service.save_settings(db, data or {})
        return {"settings": prompt_service.settings_payload(settings)}

    # ----------------------------- handoff ---------------------------- #
    @router.post("/api/linkedin/jobs/{job_id}/draft-apply")
    def draft_and_apply(
        job_id: int,
        background_tasks: BackgroundTasks,
        data: dict = None,
        db: Session = Depends(get_db),
    ):
        data = data or {}
        job = db.query(models.LinkedInJob).filter(models.LinkedInJob.id == job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")

        existing = None
        if job.job_application_id:
            existing = (
                db.query(models.JobApplication)
                .filter(models.JobApplication.id == job.job_application_id)
                .first()
            )
        if existing is not None:
            return {
                "application_id": existing.id,
                "status": existing.status,
                "reused": True,
                "message": "This job is already in your application pipeline.",
            }

        jd_text = job.job_description or job.full_post or ""
        if not jd_text.strip():
            raise HTTPException(
                status_code=400,
                detail="This job has no job description to draft from.",
            )

        # LinkedIn source URLs never become the form-detection target; only a
        # validated external apply link can (see url_utils.safe_application_url).
        application_url = url_utils.safe_application_url(
            job.linkedin_post_url, job.job_url, job.apply_url
        )

        new_app = models.JobApplication(
            ocr_text=jd_text,
            status="processing",
            company_name=job.company,
            role=job.role,
            contact_email=job.email,
            application_url=application_url,
            platform_type="linkedin",
            source="linkedin_automation",
            linkedin_job_id=job.id,
            suggest_resume_change=bool(data.get("suggest_resume_change")),
        )
        db.add(new_app)
        db.commit()
        db.refresh(new_app)

        job.job_application_id = new_app.id
        db.commit()

        background_tasks.add_task(process_application, new_app.id)
        return {
            "application_id": new_app.id,
            "status": new_app.status,
            "reused": False,
            "has_recipient": bool(job.email),
            "message": (
                "Draft started."
                if job.email
                else "Draft started. Add a recipient before sending - this job has no e-mail."
            ),
        }

    return router
