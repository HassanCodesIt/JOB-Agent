"""The FastAPI surface: page render, job lists, filtering, draft & apply handoff."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape

import models
from linkedin_integration import filter_service
from linkedin_integration import importer
from linkedin_integration import routes
from linkedin_integration import runner

from linkedin_helpers import PROJECT_ROOT, sample_job

ENTRY_POINTS = (
    "main.py",
    "latest_run.py",
    "date_posted_24h_run.py",
    "top_match_run.py",
    "feed_run.py",
    "continue_run.py",
)


class FakePipeline:
    """Records process_application calls instead of running the real pipeline."""

    def __init__(self):
        self.called = []

    def __call__(self, application_id):
        self.called.append(application_id)


@pytest.fixture()
def pipeline():
    return FakePipeline()


@pytest.fixture()
def templates():
    environment = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT / "templates")),
        autoescape=select_autoescape(["html", "xml"]),
    )

    class Templates:
        def get_template(self, name):
            return environment.get_template(name)

        def TemplateResponse(self, name, context, *args, **kwargs):
            from fastapi.responses import HTMLResponse

            return HTMLResponse(environment.get_template(name).render(context))

    return Templates()


@pytest.fixture()
def client(db, templates, pipeline):
    def get_db():
        yield db

    app = FastAPI()
    app.include_router(
        routes.create_linkedin_router(
            templates=templates,
            get_db=get_db,
            process_application=pipeline,
            is_setup_complete=lambda session: True,
        )
    )
    with TestClient(app) as test_client:
        yield test_client


def _seed(db, **overrides):
    run = models.LinkedInRun(
        scraper_run_number=1,
        mode="standard",
        entry_point="main.py",
        role="AI Developer",
        status="completed",
        collected_count=1,
    )
    db.add(run)
    db.flush()
    payload = importer.build_job_payload(sample_job(**overrides))
    job = models.LinkedInJob(linkedin_run_id=run.id, filter_status="pending", **payload)
    job.filter_batch = filter_service.batch_for(job)
    db.add(job)
    db.commit()
    return job


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def test_page_renders_with_bootstrapped_state(client, db, pipeline):
    _seed(db)
    response = client.get("/linkedin-jobs")
    assert response.status_code == 200
    html = response.text
    assert "LinkedIn Job Finder" in html
    assert "var META = {" in html, "the page must receive the API state as JSON"
    assert "linkedin-jobs" in html, "the nav must mark this page active"
    for entry in ENTRY_POINTS:
        assert entry not in html, "scraper script names must not reach the page"


def test_meta_exposes_friendly_modes_without_script_names(client):
    meta = client.get("/api/linkedin/meta").json()
    keys = [mode["key"] for mode in meta["modes"]]
    assert keys == ["standard", "latest", "date_posted_24h", "top_match", "feed", "continue"]
    blob = json.dumps(meta)
    for entry in ENTRY_POINTS:
        assert entry not in blob
    assert "AI Developer" in meta["preset_roles"]
    assert meta["counts"]["collected"] >= 0


def test_page_redirects_when_setup_is_incomplete(db, templates, pipeline):
    def get_db():
        yield db

    app = FastAPI()
    app.include_router(
        routes.create_linkedin_router(
            templates=templates,
            get_db=get_db,
            process_application=pipeline,
            is_setup_complete=lambda session: False,
        )
    )
    response = TestClient(app).get("/linkedin-jobs", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "/setup" in response.headers["location"]


# --------------------------------------------------------------------------- #
# Job listing
# --------------------------------------------------------------------------- #

def test_collected_jobs_are_listed_with_rendered_cards(client, db):
    job = _seed(db, email="jobs@acme.example")
    response = client.get("/api/linkedin/jobs").json()
    assert response["total"] == 1
    assert response["count"] == 1
    assert "Acme AI" in response["html"]
    assert "AI Developer" in response["html"]
    # Source link kept for the user, application link kept for the user.
    assert job.linkedin_post_url in response["html"] or "linkedin.com/feed" in response["html"]


def test_job_detail_never_returns_a_linkedin_application_url(client, db):
    job = _seed(db, apply_url=None)
    payload = client.get(f"/api/linkedin/jobs/{job.id}").json()["job"]
    assert payload["links"]["post"].startswith("https://www.linkedin.com/feed/")
    assert payload["links"]["apply"] is None
    assert "application_url" not in payload


def test_jobs_scope_and_batch_filters(client, db):
    accepted = _seed(db, email="jobs@acme.example", job_url="https://www.linkedin.com/jobs/view/1/")
    accepted.filter_status = "accepted"
    rejected = _seed(
        db,
        email=None,
        linkedin_post_url="https://www.linkedin.com/feed/update/urn:li:ugcPost:2/",
        job_url="https://www.linkedin.com/jobs/view/2/",
    )
    rejected.filter_status = "rejected"
    db.commit()

    filtered = client.get("/api/linkedin/jobs", params={"scope": "filtered"}).json()
    assert filtered["total"] == 1
    assert "Draft" in filtered["html"], "the filtered view must offer Draft & Apply"

    rejected_list = client.get("/api/linkedin/jobs", params={"scope": "rejected"}).json()
    assert rejected_list["total"] == 1

    no_email = client.get("/api/linkedin/jobs", params={"batch": "no_email"}).json()
    email_only = client.get("/api/linkedin/jobs", params={"batch": "email"}).json()
    assert no_email["total"] == 1
    assert email_only["total"] == 1
    # The two batches partition the collected list exactly.
    assert no_email["total"] + email_only["total"] == client.get("/api/linkedin/jobs").json()["total"]

    by_sub = client.get("/api/linkedin/jobs", params={"sub": "linkedin_job"}).json()
    assert by_sub["total"] == 2, "both jobs expose a LinkedIn job link"


def test_jobs_json_format_returns_structured_rows(client, db):
    _seed(db, email="jobs@acme.example")
    body = client.get("/api/linkedin/jobs", params={"format": "json"}).json()
    assert body["total"] == 1
    assert "html" not in body, "the JSON format must not carry markup"
    item = body["items"][0]
    assert item["role"] == "AI Developer"
    assert item["company"] == "Acme AI"
    assert item["filter_status"] == "pending"
    assert item["batch"] == "email"
    assert item["links"]["post"], "the LinkedIn post link stays its own field"
    assert item["full_text"]
    assert item["skills"] == ["Python", "LLMs"], "structured scraper fields stay available"


def test_jobs_json_format_honours_scope_and_batch(client, db):
    accepted = _seed(db, email="jobs@acme.example", job_url="https://www.linkedin.com/jobs/view/1/")
    accepted.filter_status = "accepted"
    _seed(
        db,
        email=None,
        linkedin_post_url="https://www.linkedin.com/feed/update/urn:li:ugcPost:2/",
        job_url="https://www.linkedin.com/jobs/view/2/",
    )
    db.commit()

    filtered = client.get("/api/linkedin/jobs", params={"format": "json", "scope": "filtered"}).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["filter_status"] == "accepted"
    no_email = client.get("/api/linkedin/jobs", params={"format": "json", "batch": "no_email"}).json()
    assert no_email["total"] == 1


def test_unknown_job_returns_404(client):
    assert client.get("/api/linkedin/jobs/999999").status_code == 404


# --------------------------------------------------------------------------- #
# Filtering endpoints
# --------------------------------------------------------------------------- #

def test_filter_endpoint_runs_without_a_model_call(client, db, monkeypatch):
    _seed(db)
    called = []

    def fake_call(messages, max_tokens, session):
        called.append(messages)
        job_id = messages[1]["content"].splitlines()[0]
        return f"{job_id}:Y"

    monkeypatch.setattr(filter_service, "call_model", fake_call)
    body = client.post("/api/linkedin/filter", json={}).json()
    assert body["summary"]["filtered"] == 1
    assert body["summary"]["accepted"] == 1
    assert body["counts"]["accepted"] == 1
    assert len(called) == 1


def test_filter_settings_round_trip_bumps_the_prompt_version(client, db):
    before = client.get("/api/linkedin/filter-settings").json()["settings"]
    updated = client.post(
        "/api/linkedin/filter-settings", json={"prompt": "Only accept remote roles."}
    ).json()["settings"]
    assert updated["prompt"] == "Only accept remote roles."
    assert updated["prompt_version"] > before["prompt_version"]
    assert "main.py" not in json.dumps(updated)


def test_search_settings_reject_unknown_facet_values(client, db):
    saved = client.post(
        "/api/linkedin/search-settings", json={"sort_by": "newest-first", "date_posted": "any"}
    ).json()["settings"]
    assert saved["sort_by"] == "relevance", "unknown values must not be persisted"


def test_search_settings_accept_supported_values(client, db):
    saved = client.post(
        "/api/linkedin/search-settings", json={"default_role": "ML Engineer", "sort_by": "latest", "date_posted": "past_24_hours"}
    ).json()["settings"]
    assert saved == {"default_role": "ML Engineer", "sort_by": "latest", "date_posted": "past_24_hours"}


# --------------------------------------------------------------------------- #
# Run endpoints
# --------------------------------------------------------------------------- #

def test_run_list_is_empty_and_inactive(client, db):
    body = client.get("/api/linkedin/runs").json()
    assert body == {"runs": [], "active": False}


def test_start_run_validates_before_touching_the_browser(client, db):
    response = client.post("/api/linkedin/runs/start", json={"role": ""})
    assert response.status_code == 400
    assert "role" in response.json()["detail"].lower()

    response = client.post(
        "/api/linkedin/runs/start", json={"role": "AI Developer", "sort_by": "latest", "date_posted": "any"}
    )
    assert response.status_code == 400
    assert db.query(models.LinkedInRun).count() == 0


def test_unknown_run_returns_404(client, db):
    assert client.get("/api/linkedin/runs/999999").status_code == 404
    assert client.post("/api/linkedin/runs/999999/stop").status_code == 404


def test_stop_run_requires_a_live_process(client, db):
    finished = models.LinkedInRun(mode="standard", role="AI Developer", status="completed")
    db.add(finished)
    db.commit()
    response = client.post(f"/api/linkedin/runs/{finished.id}/stop")
    assert response.status_code == 400
    assert "no longer running" in response.json()["detail"]

    orphan = models.LinkedInRun(mode="standard", role="AI Developer", status="running")
    db.add(orphan)
    db.commit()
    response = client.post(f"/api/linkedin/runs/{orphan.id}/stop")
    assert response.status_code == 400
    assert "stopped from Command" in response.json()["detail"]
    db.refresh(orphan)
    assert orphan.status == "running", "a rejected stop must not alter the run"


# --------------------------------------------------------------------------- #
# Draft & apply handoff
# --------------------------------------------------------------------------- #

def test_draft_and_apply_creates_a_traced_application(client, db, pipeline):
    job = _seed(db, email="jobs@acme.example")
    response = client.post(f"/api/linkedin/jobs/{job.id}/draft-apply", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["reused"] is False
    assert body["has_recipient"] is True

    application = db.query(models.JobApplication).one()
    assert application.id == body["application_id"]
    assert application.source == "linkedin_automation"
    assert application.linkedin_job_id == job.id
    assert application.contact_email == "jobs@acme.example"
    assert application.platform_type == "linkedin"
    assert application.application_url == job.apply_url, "external apply link becomes the form target"
    assert application.status == "processing"
    assert application.ocr_text == job.job_description

    db.refresh(job)
    assert job.job_application_id == application.id
    assert pipeline.called == [application.id]


def test_draft_and_apply_never_targets_a_linkedin_url(client, db, pipeline):
    job = _seed(db, email=None, apply_url=None)
    response = client.post(f"/api/linkedin/jobs/{job.id}/draft-apply", json={})
    assert response.status_code == 200

    application = db.query(models.JobApplication).one()
    assert application.application_url is None, "LinkedIn source links must not become form targets"
    assert application.contact_email is None
    assert response.json()["has_recipient"] is False
    assert "recipient" in response.json()["message"]


def test_draft_and_apply_rejects_a_linkedin_apply_url(client, db, pipeline):
    job = _seed(db, apply_url="https://www.linkedin.com/jobs/view/12345/")
    client.post(f"/api/linkedin/jobs/{job.id}/draft-apply", json={})
    assert db.query(models.JobApplication).one().application_url is None


def test_draft_and_apply_is_idempotent(client, db, pipeline):
    job = _seed(db)
    first = client.post(f"/api/linkedin/jobs/{job.id}/draft-apply", json={}).json()
    second = client.post(f"/api/linkedin/jobs/{job.id}/draft-apply", json={}).json()

    assert second["reused"] is True
    assert second["application_id"] == first["application_id"]
    assert db.query(models.JobApplication).count() == 1
    assert len(pipeline.called) == 1, "the pipeline must not be queued twice"


def test_draft_and_apply_requires_job_description_text(client, db, pipeline):
    job = _seed(db, job_description="", full_post="")
    response = client.post(f"/api/linkedin/jobs/{job.id}/draft-apply", json={})
    assert response.status_code == 400
    assert db.query(models.JobApplication).count() == 0
    assert pipeline.called == []


def test_draft_and_apply_unknown_job_returns_404(client, db, pipeline):
    assert client.post("/api/linkedin/jobs/999999/draft-apply", json={}).status_code == 404


def test_draft_and_apply_passes_the_opt_in_flag(client, db, pipeline):
    job = _seed(db)
    client.post(f"/api/linkedin/jobs/{job.id}/draft-apply", json={"suggest_resume_change": True})
    assert db.query(models.JobApplication).one().suggest_resume_change is True


def test_draft_and_apply_is_offered_only_for_collected_jobs(client, db):
    job = _seed(db)
    detail = client.get(f"/api/linkedin/jobs/{job.id}").json()["job"]
    assert detail["show_draft"] is True, "the detail view always exposes Draft & Apply"
    assert detail["filter_status"] == "pending"


# --------------------------------------------------------------------------- #
# Counts
# --------------------------------------------------------------------------- #

def test_counts_reflect_batches_and_decisions(client, db):
    _seed(db, email="jobs@acme.example")
    other = _seed(db, email=None, linkedin_post_url="https://www.linkedin.com/feed/update/urn:li:ugcPost:2/")
    other.filter_status = "accepted"
    db.commit()

    meta = client.get("/api/linkedin/meta").json()
    counts = meta["counts"]
    assert counts["collected"] == 2
    assert counts["with_email"] == 1
    assert counts["no_email"] == 1
    assert counts["accepted"] == 1
    assert counts["accepted_no_email"] == 1
    assert counts["accepted_email"] == 0
