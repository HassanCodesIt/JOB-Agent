"""LLM filter: JD cleaning, batching, prompt, token budget, decision parsing."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

import models
from linkedin_integration import filter_service as fs
from linkedin_integration import importer
from linkedin_integration import prompt_service as ps
from linkedin_integration import url_utils

from linkedin_helpers import sample_job


# --------------------------------------------------------------------------- #
# URL safety
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "value",
    [
        "https://www.linkedin.com/jobs/view/12345/",
        "https://www.linkedin.com/feed/update/urn:li:ugcPost:1/",
        "https://lnkd.in/dxyz",
        "https://licdn.com/pub/x",
        "https://linkedin.com/company/acme",
        "http://www.linkedin.com/jobs/view/1",
    ],
)
def test_linkedin_urls_are_never_safe_application_urls(value):
    assert url_utils.safe_application_url(None, None, value) is None


@pytest.mark.parametrize(
    "value",
    [
        "https://acme.example/careers/apply",
        "https://boards.greenhouse.io/acme/jobs/1",
        "http://example.com/apply",
    ],
)
def test_company_urls_are_safe_application_urls(value):
    assert url_utils.safe_application_url(None, None, value) == value


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:text/html,<script>",
        "mailto:jobs@acme.example",
        "file:///etc/passwd",
        "",
        None,
        "acme.example/careers",
        123,
    ],
)
def test_invalid_application_urls_are_rejected(value):
    assert url_utils.safe_application_url(None, None, value) is None


def test_source_urls_are_never_consulted_even_when_apply_url_is_bad():
    post = "https://www.linkedin.com/feed/update/urn:li:ugcPost:1/"
    job = "https://www.linkedin.com/jobs/view/12345/"
    # The LinkedIn post/job links must not leak into application_url.
    assert url_utils.safe_application_url(post, job, "not-a-url") is None
    assert url_utils.safe_application_url(post, job, None) is None
    assert url_utils.safe_application_url(post, job, "https://acme.example/apply") == "https://acme.example/apply"


def test_job_source_link_is_preserved_but_never_reused_as_application_url():
    job = sample_job()
    assert url_utils.is_linkedin_url(job["job_url"])
    assert url_utils.safe_application_url(job["linkedin_post_url"], job["job_url"], job["job_url"]) is None
    assert url_utils.safe_application_url(job["linkedin_post_url"], job["job_url"], job["apply_url"]) == job["apply_url"]


def test_external_urls_drops_linkedin_and_duplicates():
    urls = [
        "https://acme.example/apply",
        "https://www.linkedin.com/jobs/view/1/",
        "https://acme.example/apply",
        "not-a-url",
        None,
    ]
    assert url_utils.external_urls(urls) == ["https://acme.example/apply"]


# --------------------------------------------------------------------------- #
# JD cleaning
# --------------------------------------------------------------------------- #

def test_clean_jd_strips_urls_and_noise():
    text = (
        "AI Developer role.\n"
        "Apply at https://acme.example/careers/apply\n"
        "See https://www.linkedin.com/jobs/view/12345 for details\n"
        "Email jobs@acme.example\n"
        "bullet one\n"
        "https://www.linkedin.com/feed/update/urn:li:ugcPost:1/"
    )
    cleaned = fs.clean_jd(text, 1000)
    assert "https://" not in cleaned
    assert "acme.example" not in cleaned
    assert "jobs@acme.example" not in cleaned
    assert "AI Developer role" in cleaned
    assert "bullet one" in cleaned


def test_clean_jd_honours_the_character_budget():
    assert len(fs.clean_jd("word " * 500, 100)) <= 100


def test_clean_jd_of_empty_input_is_empty():
    assert fs.clean_jd(None, 100) == ""
    assert fs.clean_jd("", 100) == ""
    assert fs.clean_jd("   \n\t ", 100) == ""


# --------------------------------------------------------------------------- #
# Job text and batching
# --------------------------------------------------------------------------- #

def test_job_text_prefers_the_job_description_and_falls_back_to_the_post():
    assert fs.job_text(models.LinkedInJob(job_description="JD text", full_post="post text")) == "JD text"
    assert fs.job_text(models.LinkedInJob(job_description="", full_post="post text")) == "post text"
    assert fs.job_text(
        models.LinkedInJob(job_description=None, full_post=None, skills="Python", experience="0-1 years")
    ) == "Python 0-1 years"


def test_jobs_split_into_email_and_no_email_batches():
    jobs = [
        models.LinkedInJob(id=1, email="a@b.example"),
        models.LinkedInJob(id=2, email=None),
        models.LinkedInJob(id=3, email="   "),
        models.LinkedInJob(id=4, email="c@d.example"),
    ]
    batches = fs.split_batches(jobs)
    assert sorted(job.id for job in batches["email"]) == [1, 4]
    assert sorted(job.id for job in batches["no_email"]) == [2, 3]


def test_split_batches_of_empty_list_is_empty():
    assert fs.split_batches([]) == {"email": [], "no_email": []}


def test_batch_for_never_reclassifies_an_addressed_job():
    assert fs.batch_for(models.LinkedInJob(email="a@b.example")) == fs.BATCH_EMAIL
    assert fs.batch_for(models.LinkedInJob(email="")) == fs.BATCH_NO_EMAIL
    assert fs.batch_for(models.LinkedInJob(email=None)) == fs.BATCH_NO_EMAIL


# --------------------------------------------------------------------------- #
# Prompt and token budget
# --------------------------------------------------------------------------- #

def test_prompt_is_generated_from_the_default_criteria_and_versioned(db):
    settings = ps.ensure_settings(db)
    assert settings.prompt, "expected a generated prompt"
    assert "1 year" in settings.prompt
    assert settings.prompt_version == 1
    assert settings.model == ps.MODEL_NAME
    assert settings.batch_size > 0 and settings.max_jd_chars > 0


def test_prompt_version_bumps_only_when_the_prompt_changes(db):
    original = ps.ensure_settings(db).prompt_version

    # save_settings returns the live row, so snapshot the numbers as we go.
    first = ps.save_settings(db, {"prompt": "Custom rule."}).prompt_version
    assert first == original + 1, "a new prompt must bump the version"

    second = ps.save_settings(db, {"prompt": "Custom rule."}).prompt_version
    assert second == first, "identical prompt must not bump the version"

    third = ps.save_settings(db, {"prompt": "Different rule."}).prompt_version
    assert third == first + 1

    fourth = ps.save_settings(db, {"regenerate_prompt": True}).prompt_version
    assert fourth == third + 1
    assert "1 year" in ps.ensure_settings(db).prompt


def test_batch_payload_is_only_ids_jds_and_the_user_prompt(db):
    settings = ps.ensure_settings(db)
    items = [(11, "Build agents"), (22, "Ship features")]
    messages = fs.build_messages(settings, items)

    assert [m["role"] for m in messages] == ["system", "user"]
    user = messages[1]["content"]
    assert user == "11\nBuild agents\n\n22\nShip features"
    assert settings.prompt in messages[0]["content"]

    blob = json.dumps(messages)
    for forbidden in ("apply_url", "linkedin_post_url", "full_post", "author", "company", "email"):
        assert f'"{forbidden}"' not in blob


def test_max_output_tokens_scales_with_batch_size_and_keeps_reasoning_room():
    # Scales with the batch (one line per JD) ...
    assert fs.max_output_tokens(1) == fs.OUTPUT_TOKENS_PER_JD * 1 + fs.OUTPUT_TOKENS_HEADROOM
    assert fs.max_output_tokens(10) == fs.OUTPUT_TOKENS_PER_JD * 10 + fs.OUTPUT_TOKENS_HEADROOM
    assert fs.max_output_tokens(0) == fs.OUTPUT_TOKENS_PER_JD + fs.OUTPUT_TOKENS_HEADROOM
    # ... but never drops to a few tokens: gpt-oss spends the budget reasoning
    # and would otherwise reply with nothing at all.
    assert fs.OUTPUT_TOKENS_HEADROOM >= 256
    for size in (1, 8, 64):
        assert fs.max_output_tokens(size) >= fs.OUTPUT_TOKENS_HEADROOM


def test_call_model_caps_reasoning_so_the_budget_survives(db, monkeypatch):
    captured: dict = {}

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content="12:Y")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class _Client:
        def __init__(self, api_key=None):
            self.chat = SimpleNamespace(completions=_Completions())

    monkeypatch.setattr("groq.Groq", _Client)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    reply = fs.call_model([{"role": "user", "content": "hi"}], 520, db)

    assert reply == "12:Y"
    assert captured["reasoning_effort"] == fs.REASONING_EFFORT == "low"
    assert captured["max_completion_tokens"] == 520
    assert captured["temperature"] == 0
    assert "test-key" not in repr(captured)


# --------------------------------------------------------------------------- #
# Decision parsing
# --------------------------------------------------------------------------- #

def test_parse_decisions_reads_id_colon_y_or_n():
    decisions, missing = fs.parse_decisions("11:Y\n12:N\n13: y\n14: no", [11, 12, 13, 14, 15])
    assert decisions[11] is True
    assert decisions[12] is False
    assert decisions[13] is True
    assert decisions[14] is False
    assert missing == {15}


def test_parse_decisions_ignores_unknown_ids_and_malformed_lines():
    decisions, missing = fs.parse_decisions("banana\n999:Y\n11:maybe", [11])
    assert decisions == {}
    assert missing == {11}


def test_parse_decisions_tolerates_prose_wrapper_and_keeps_the_first_hit():
    raw = 'Here are the results:\n"11": "Y"\n11:Y\n12:N\n'
    decisions, _ = fs.parse_decisions(raw, [11, 12])
    assert decisions == {11: True, 12: False}


def test_parse_decisions_of_empty_model_output_marks_everything_missing():
    decisions, missing = fs.parse_decisions("", [1, 2, 3])
    assert decisions == {}
    assert missing == {1, 2, 3}


# --------------------------------------------------------------------------- #
# run_filter persistence (LLM mocked out)
# --------------------------------------------------------------------------- #

def _prompt_ids(user_content: str):
    ids = []
    for block in user_content.split("\n\n"):
        first = block.splitlines()[0].strip() if block.strip() else ""
        if first.isdigit():
            ids.append(int(first))
    return ids


def _import_two_jobs(db):
    run = models.LinkedInRun(
        scraper_run_number=7,
        mode="standard",
        entry_point="main.py",
        role="AI Developer",
        status="completed",
        collected_count=2,
    )
    db.add(run)
    db.flush()
    db.add(models.LinkedInJob(linkedin_run_id=run.id, filter_status="pending", **importer.build_job_payload(sample_job(email="a@b.example"))))
    db.add(models.LinkedInJob(linkedin_run_id=run.id, filter_status="pending", **importer.build_job_payload(sample_job(email=None, job_url="https://www.linkedin.com/jobs/view/999/"))))
    db.commit()
    return run


def test_run_filter_persists_decisions_batches_and_run_counts(db, monkeypatch):
    run = _import_two_jobs(db)
    ps.ensure_settings(db)
    seen = []
    calls = {"n": 0}

    def fake_call(messages, max_tokens, session):
        ids = _prompt_ids(messages[1]["content"])
        seen.append(ids)
        token = "Y" if calls["n"] == 0 else "N"
        calls["n"] += 1
        return "\n".join(f"{job_id}:{token}" for job_id in ids)

    monkeypatch.setattr(fs, "call_model", fake_call)

    summary = fs.run_filter(db)
    assert summary["filtered"] == 2
    assert summary["accepted"] == 1
    assert summary["rejected"] == 1
    assert summary["errors"] == 0

    # Batch A and batch B are requested separately.
    assert len(seen) == 2

    jobs = db.query(models.LinkedInJob).order_by(models.LinkedInJob.id).all()
    assert sorted(job.filter_status for job in jobs) == ["accepted", "rejected"]
    assert sorted(job.filter_batch for job in jobs) == ["email", "no_email"]
    assert all(job.filter_prompt_version == 1 for job in jobs)
    assert all(job.filter_model == ps.MODEL_NAME for job in jobs)
    assert all(job.filtered_at is not None for job in jobs)
    assert all(job.filter_error is None for job in jobs)

    refreshed = db.query(models.LinkedInRun).filter(models.LinkedInRun.id == run.id).one()
    assert refreshed.filtered_count == 1


def test_run_filter_skips_jobs_already_decided_at_the_current_prompt(db, monkeypatch):
    _import_two_jobs(db)
    ps.ensure_settings(db)
    calls = []

    def answer(messages, max_tokens, session):
        calls.append(messages)
        return "\n".join(f"{job_id}:Y" for job_id in _prompt_ids(messages[1]["content"]))

    monkeypatch.setattr(fs, "call_model", answer)
    fs.run_filter(db)
    # Batch A and batch B are requested separately, so two calls.
    assert len(calls) == 2

    second = fs.run_filter(db)
    assert second["filtered"] == 0
    assert second["skipped"] == 2
    assert len(calls) == 2, "unchanged decisions must not be re-sent to the LLM"


def test_run_filter_force_reprocesses_everything(db, monkeypatch):
    _import_two_jobs(db)
    ps.ensure_settings(db)
    calls = []

    def answer(messages, max_tokens, session):
        calls.append(messages)
        return "\n".join(f"{job_id}:Y" for job_id in _prompt_ids(messages[1]["content"]))

    monkeypatch.setattr(fs, "call_model", answer)
    fs.run_filter(db)
    assert len(calls) == 2

    fs.run_filter(db, force=True)
    assert len(calls) == 4, "force must re-send every job, including decided ones"


def test_run_filter_marks_model_errors_without_inventing_decisions(db, monkeypatch):
    _import_two_jobs(db)
    ps.ensure_settings(db)

    def no_answer(messages, max_tokens, session):
        return "\n".join(f"{job_id}:X" for job_id in _prompt_ids(messages[1]["content"]))

    monkeypatch.setattr(fs, "call_model", no_answer)
    summary = fs.run_filter(db)
    assert summary["errors"] == 2
    assert summary["accepted"] == 0 and summary["rejected"] == 0

    assert {job.filter_status for job in db.query(models.LinkedInJob)} == {"error"}


def test_run_filter_retries_a_malformed_batch_with_a_bigger_budget(db, monkeypatch):
    _import_two_jobs(db)
    ps.ensure_settings(db)
    calls = []
    seen_batches = set()

    def empty_then_complete(messages, max_tokens, session):
        calls.append(max_tokens)
        key = messages[1]["content"]
        ids = _prompt_ids(key)
        if key not in seen_batches:
            # First attempt for this batch comes back unanswered.
            seen_batches.add(key)
            return ""
        return "\n".join(f"{job_id}:Y" for job_id in ids)

    monkeypatch.setattr(fs, "call_model", empty_then_complete)
    summary = fs.run_filter(db)

    assert summary["accepted"] == 2 and summary["errors"] == 0
    assert len(calls) == 4, "each of the two batches is attempted twice"
    assert calls[1] > calls[0] and calls[3] > calls[2], "retries must ask for more budget"
    assert {job.filter_status for job in db.query(models.LinkedInJob)} == {"accepted"}


def test_run_filter_survives_a_total_transport_failure(db, monkeypatch):
    _import_two_jobs(db)
    ps.ensure_settings(db)

    def boom(*args, **kwargs):
        raise ConnectionError("LLM unreachable")

    monkeypatch.setattr(fs, "call_model", boom)
    summary = fs.run_filter(db)
    assert summary["errors"] == 2

    jobs = db.query(models.LinkedInJob).all()
    assert {job.filter_status for job in jobs} == {"error"}
    assert all("LLM unreachable" in (job.filter_error or "") for job in jobs)


def test_run_filter_reprocesses_stale_prompt_decisions(db, monkeypatch):
    run = _import_two_jobs(db)
    settings = ps.ensure_settings(db)
    for job in db.query(models.LinkedInJob):
        job.filter_status = "accepted"
        job.filter_prompt_version = settings.prompt_version
    db.commit()

    ps.save_settings(db, {"prompt": "Only accept Python roles."})
    new_version = ps.ensure_settings(db).prompt_version
    assert new_version > 1

    answered = []

    def answer(messages, max_tokens, session):
        ids = _prompt_ids(messages[1]["content"])
        answered.extend(ids)
        return "\n".join(f"{job_id}:N" for job_id in ids)

    monkeypatch.setattr(fs, "call_model", answer)
    summary = fs.run_filter(db)
    assert summary["filtered"] == 2, "decisions from an older prompt must be refreshed"
    assert summary["rejected"] == 2
    assert answered

    for job in db.query(models.LinkedInJob):
        assert job.filter_prompt_version == new_version
    assert db.query(models.LinkedInRun).one().filtered_count == 0


def test_run_filter_can_target_a_single_run(db, monkeypatch):
    _import_two_jobs(db)
    ps.ensure_settings(db)
    answered = []

    def answer(messages, max_tokens, session):
        ids = _prompt_ids(messages[1]["content"])
        answered.extend(ids)
        return "\n".join(f"{job_id}:Y" for job_id in ids)

    monkeypatch.setattr(fs, "call_model", answer)
    summary = fs.run_filter(db, run_id=9999)
    assert summary["filtered"] == 0
    assert answered == []
