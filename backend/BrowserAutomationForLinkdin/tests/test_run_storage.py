"""Tests for per-run JSON storage.

Every test uses a temporary directory, so real scraping data is never touched.
"""

from __future__ import annotations

import json

import pytest

from collector.models import Post, RoleMatchResult, JobMatch, Stats
from collector.run_storage import (
    build_run_payload,
    existing_run_numbers,
    next_run_number,
    run_file_name,
    runs_dir,
    save_scraping_run,
)
from config import Config


def _match(index: int = 1, url: str = "", **overrides) -> JobMatch:
    post = Post(
        author="Ravi Kumar",
        text=(
            f"Post number {index}: we are hiring a Generative AI Engineer.\n"
            "Skills:\n- Python\n- LLM orchestration\n"
            "Responsibilities:\n- Build agentic systems\n"
            "Contact: jobs@acme-ai.com"
        ),
        url=url,
        urn="urn:li:activity:7000000000000000001",
    )
    match = JobMatch(
        post=post,
        role_match=RoleMatchResult(
            target_role="Generative AI Engineer",
            matched_variations=["genai engineer"],
            categories=["Generative AI Engineer", "AI Engineer"],
        ),
        role="Generative AI Engineer",
        company="Acme AI",
        location="Bengaluru, India",
        experience="3-5 years",
        employment_type="Full-time",
        salary="INR 30,00,000 - 45,00,000",
        skills=["Python", "LLM orchestration"],
        responsibilities=["Build agentic systems"],
        emails=["jobs@acme-ai.com"],
        job_url="https://www.linkedin.com/jobs/view/123456/",
        apply_urls=["https://acme-ai.example/apply"],
        methods=["Email", "External Apply Link"],
        reasons=["Role matched: Generative AI Engineer"],
    )
    for key, value in overrides.items():
        setattr(match, key, value)
    return match


def _valid_match(index: int = 1, **overrides) -> JobMatch:
    url = f"https://www.linkedin.com/feed/update/urn:li:activity:{7000000000000000000 + index}/"
    return _match(index, url=url, **overrides)


def _write_run(directory, number: int, payload=None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload if payload is not None else {"jobs": []})
    (directory / run_file_name(number)).write_text(text, encoding="utf-8")


# --- numbering ---------------------------------------------------------------


def test_first_run_creates_run_1(tmp_path):
    stats = Stats()
    path = save_scraping_run([_valid_match()], stats, Config(), base=tmp_path)

    assert path.name == "Scraping Run 1.json"
    assert path.parent == runs_dir(tmp_path)
    assert path.exists()


def test_second_run_creates_run_2(tmp_path):
    save_scraping_run([], Stats(), Config(), base=tmp_path)
    path = save_scraping_run([], Stats(), Config(), base=tmp_path)

    assert path.name == "Scraping Run 2.json"
    assert (tmp_path / "data" / "scraping_runs" / "Scraping Run 1.json").exists()


def test_existing_runs_are_never_overwritten(tmp_path):
    save_scraping_run([_valid_match()], Stats(), Config(), base=tmp_path)
    first = runs_dir(tmp_path) / run_file_name(1)
    original = first.read_text(encoding="utf-8")

    save_scraping_run([_valid_match(2)], Stats(), Config(), base=tmp_path)

    assert first.read_text(encoding="utf-8") == original
    assert len(existing_run_numbers(runs_dir(tmp_path))) == 2


def test_highest_existing_run_number_is_detected():
    directory = runs_dir()
    numbers = existing_run_numbers(directory)
    assert next_run_number(directory) == (numbers[-1] + 1 if numbers else 1)


def test_gaps_do_not_break_numbering(tmp_path):
    directory = runs_dir(tmp_path)
    for number in (1, 2, 5):
        _write_run(directory, number)

    assert existing_run_numbers(directory) == [1, 2, 5]
    assert next_run_number(directory) == 6
    assert save_scraping_run([], Stats(), Config(), base=tmp_path).name == "Scraping Run 6.json"


def test_unrelated_files_are_ignored(tmp_path):
    directory = runs_dir(tmp_path)
    for name in ("notes.json", "Scraping Run draft.json", "Scraping Run x.json", "README.md"):
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text("{}", encoding="utf-8")

    assert existing_run_numbers(directory) == []
    assert next_run_number(directory) == 1


def test_a_number_taken_mid_flight_moves_to_the_next_one(tmp_path, monkeypatch):
    real_open = type((tmp_path / "x")).open
    taken = runs_dir(tmp_path) / run_file_name(1)
    state = {"served": False}

    def fake_open(self, mode="r", *args, **kwargs):
        # First create attempt loses a race; the file now exists.
        if "x" in mode and not state["served"]:
            state["served"] = True
            taken.parent.mkdir(parents=True, exist_ok=True)
            taken.write_text("{}", encoding="utf-8")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(type(taken), "open", fake_open)
    path = save_scraping_run([_valid_match()], Stats(), Config(), base=tmp_path)

    assert path.name == "Scraping Run 2.json"
    assert taken.read_text(encoding="utf-8") == "{}"


# --- one run, one file -------------------------------------------------------


def test_thirty_jds_produce_one_file_with_thirty_jobs(tmp_path):
    matches = [_valid_match(index) for index in range(1, 31)]
    stats = Stats()
    stats.collected = 30

    path = save_scraping_run(matches, stats, Config(), base=tmp_path)

    files = list(runs_dir(tmp_path).glob("*.json"))
    assert len(files) == 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["jobs"]) == 30
    assert [job["company"] for job in payload["jobs"]] == ["Acme AI"] * 30


def test_a_short_run_still_produces_one_file(tmp_path):
    path = save_scraping_run([_valid_match()], Stats(), Config(), base=tmp_path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["jobs"]) == 1
    assert len(list(runs_dir(tmp_path).glob("*.json"))) == 1


def test_a_run_with_no_jds_saves_metadata_without_fake_jobs(tmp_path):
    stats = Stats()
    stats.stop_reason = "no posts found"
    path = save_scraping_run([], stats, Config(), base=tmp_path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["jobs"] == []
    assert payload["run_info"]["run_number"] == 1
    assert payload["summary"]["final_jds_collected"] == 0
    assert payload["summary"]["stop_reason"] == "no posts found"


def test_directory_is_created_automatically(tmp_path):
    target = tmp_path / "fresh"
    assert not (target / "data" / "scraping_runs").exists()

    save_scraping_run([_valid_match()], Stats(), Config(), base=target)

    assert (target / "data" / "scraping_runs" / "Scraping Run 1.json").is_file()


# --- job payload -------------------------------------------------------------


def test_full_post_text_is_preserved(tmp_path):
    match = _valid_match()
    match.post.text = "Line one\nLine two with \"quotes\" and a \\ backslash\nLine three"

    path = save_scraping_run([match], Stats(), Config(), base=tmp_path)
    job = json.loads(path.read_text(encoding="utf-8"))["jobs"][0]

    assert job["full_post"] == match.post.text
    assert "\n" in job["full_post"]
    assert '"quotes"' in job["full_post"]


def test_linkedin_post_url_is_preserved(tmp_path):
    match = _valid_match()
    path = save_scraping_run([match], Stats(), Config(), base=tmp_path)
    job = json.loads(path.read_text(encoding="utf-8"))["jobs"][0]

    assert job["linkedin_post_url"] == match.post.url
    assert job["linkedin_post_url"].startswith("https://www.linkedin.com/feed/update/urn:li:activity:")


def test_a_match_without_a_post_url_is_never_stored(tmp_path):
    """The post URL stays required on the way out, not just on the way in."""
    good = _valid_match(1)
    bad = _valid_match(2)
    bad.post.url = ""

    path = save_scraping_run([good, bad], Stats(), Config(), base=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["linkedin_post_url"] == good.post.url
    assert all(job["linkedin_post_url"] for job in payload["jobs"])


def test_application_methods_stay_separate(tmp_path):
    path = save_scraping_run([_valid_match()], Stats(), Config(), base=tmp_path)
    job = json.loads(path.read_text(encoding="utf-8"))["jobs"][0]

    assert job["email"] == "jobs@acme-ai.com"
    assert job["job_url"] == "https://www.linkedin.com/jobs/view/123456/"
    assert job["apply_url"] == "https://acme-ai.example/apply"
    assert job["linkedin_post_url"] != job["job_url"]
    assert job["application_methods"] == ["Email", "External Apply Link"]
    assert job["application_method"].startswith("Multiple")


def test_missing_data_is_serialized_as_null(tmp_path):
    match = _valid_match()
    match.company = "Not specified"
    match.location = ""
    match.salary = "Not specified"
    match.skills = []
    match.emails = []
    match.job_url = ""
    match.apply_urls = []
    match.application_instructions = []

    path = save_scraping_run([match], Stats(), Config(), base=tmp_path)
    job = json.loads(path.read_text(encoding="utf-8"))["jobs"][0]

    assert job["company"] is None
    assert job["location"] is None
    assert job["salary"] is None
    assert job["skills"] == []
    assert job["email"] is None
    assert job["job_url"] is None
    assert job["apply_url"] is None


def test_unicode_text_is_preserved(tmp_path):
    match = _valid_match()
    match.post.text = "Hiring GenAI engineers — 期待: Python, LLM, 日本語, emoji 🚀\nEmoji ✅"
    match.skills = ["Python", "日本語", "Café – naïve"]

    path = save_scraping_run([match], Stats(), Config(), base=tmp_path)
    raw = path.read_text(encoding="utf-8")
    job = json.loads(raw)["jobs"][0]

    assert "🚀" in raw
    assert "日本語" in raw
    assert job["skills"] == ["Python", "日本語", "Café – naïve"]
    assert job["full_post"].startswith("Hiring GenAI engineers —")


def test_stored_job_matches_the_printed_fields(tmp_path):
    match = _valid_match()
    path = save_scraping_run([match], Stats(), Config(), base=tmp_path)
    job = json.loads(path.read_text(encoding="utf-8"))["jobs"][0]

    assert job["target_role"] == match.target_role
    assert job["matched_role_variations"] == ["genai engineer"]
    assert job["also_matched_roles"] == ["AI Engineer"]
    assert job["author"] == "Ravi Kumar"
    assert job["experience"] == match.experience
    assert job["employment_type"] == match.employment_type
    assert job["responsibilities"] == match.responsibilities
    assert job["match_reasons"] == match.reasons
    assert job["linkedin_post_urn"] == match.post.urn


# --- run info and summary ----------------------------------------------------


def test_run_info_records_metadata_and_the_summary_matches_the_stats():
    cfg = Config()
    cfg.target_roles = ["Generative AI Engineer"]
    cfg.max_jds = 30
    stats = Stats()
    stats.roles_searched = 1
    stats.posts_processed = 49
    stats.potential_job_posts = 36
    stats.posts_with_email = 23
    stats.posts_with_job_url = 7
    stats.posts_with_apply_url = 3
    stats.no_application_method = 6
    stats.collected_by_email = 23
    stats.collected_by_job_url = 7
    stats.collected_by_apply_url = 3
    stats.collected_with_multiple_methods = 3
    stats.duplicates_removed = 0
    stats.missing_post_url = 2
    stats.collected = 30
    stats.stop_reason = "collected 30 job descriptions (max_jds)"

    payload = build_run_payload([_valid_match()], stats, cfg, 4, "2026-10-04T10:00:00+05:30")

    assert payload["run_info"]["run_number"] == 4
    assert payload["run_info"]["started_at"] == "2026-10-04T10:00:00+05:30"
    assert payload["run_info"]["completed_at"]
    assert payload["run_info"]["target_roles"] == ["Generative AI Engineer"]
    assert payload["run_info"]["max_jds"] == 30
    assert payload["summary"] == {
        "target_roles_searched": 1,
        "posts_processed": 49,
        "potential_job_posts": 36,
        "posts_with_email": 23,
        "posts_with_job_url": 7,
        "posts_with_apply_url": 3,
        "posts_without_any_application_method": 6,
        "collected_by_email": 23,
        "collected_by_linkedin_job_url": 7,
        "collected_by_apply_url": 3,
        "collected_with_multiple_methods": 3,
        "duplicates_removed": 0,
        "jds_skipped_missing_post_url": 2,
        "posts_with_image_job_info": 0,
        "collected_by_image_job_post": 0,
        "valid_job_matches": 30,
        "final_jds_collected": 30,
        "stop_reason": "collected 30 job descriptions (max_jds)",
    }


def test_completed_at_is_set_when_no_start_is_given():
    payload = build_run_payload([], Stats(), Config(), 1)
    assert payload["run_info"]["completed_at"]
    assert payload["run_info"]["started_at"] is None


# --- JSON validity and failures ----------------------------------------------


def test_output_is_valid_json_and_reloads(tmp_path):
    path = save_scraping_run([_valid_match()], Stats(), Config(), base=tmp_path)

    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert set(reloaded) == {"run_info", "summary", "jobs"}
    assert json.loads(json.dumps(reloaded)) == reloaded


def test_file_is_indented_and_utf8(tmp_path):
    path = save_scraping_run([_valid_match()], Stats(), Config(), base=tmp_path)
    raw = path.read_text(encoding="utf-8")

    assert raw.startswith("{\n  ")
    assert "\n  \"run_info\"" in raw
    assert not raw.rstrip().endswith(",\n}")


def test_save_failure_is_reported_and_raised(tmp_path, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.mkdir", boom)

    with pytest.raises(OSError):
        save_scraping_run([_valid_match()], Stats(), Config(), base=tmp_path)

    output = capsys.readouterr().out
    assert "Failed to save Scraping Run 1.json: disk full" in output
    assert "saved successfully" not in output


def test_save_failure_does_not_claim_success_on_write_error(tmp_path, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr("json.dump", boom)

    with pytest.raises(OSError):
        save_scraping_run([_valid_match()], Stats(), Config(), base=tmp_path)

    output = capsys.readouterr().out
    assert "Failed to save Scraping Run 1.json" in output
    assert "saved successfully" not in output


def test_repeated_failures_are_reported_with_the_last_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("pathlib.Path.mkdir", lambda *a, **k: True)

    def always_taken(self, mode="r", *args, **kwargs):
        raise FileExistsError("already exists")

    monkeypatch.setattr(type(tmp_path / "x"), "open", always_taken)

    with pytest.raises(RuntimeError):
        save_scraping_run([_valid_match()], Stats(), Config(), base=tmp_path)

    assert "Failed to save Scraping Run" in capsys.readouterr().out


# --- terminal output ---------------------------------------------------------


def test_saving_logs_the_expected_lines(tmp_path, capsys):
    save_scraping_run([_valid_match()], Stats(), Config(), base=tmp_path)

    output = capsys.readouterr().out
    assert "[INFO] Saving scraping run..." in output
    assert "[INFO] Scraping Run number: 1" in output
    assert "[INFO] JDs to save: 1" in output
    assert "[OK] Scraping Run 1 saved successfully." in output
    assert "Scraping Run 1.json" in output


# --- wiring into main.run() --------------------------------------------------


class _FakeSession:
    def __init__(self):
        self.disconnects = 0

    def connect(self):
        return object()

    def page_title(self):
        return "LinkedIn"

    def disconnect(self):
        self.disconnects += 1


class _FakeCfg:
    dry_run = False
    target_roles = ["Generative AI Engineer"]
    max_jds = 5
    max_posts = 100
    max_scrolls = 5
    min_jd_signals = 2


def _run_with_one_match(monkeypatch, tmp_path):
    import main as mainpy

    match = _valid_match()
    session = _FakeSession()
    monkeypatch.setattr(mainpy, "BrowserSession", lambda cfg: session)
    monkeypatch.setattr(mainpy.safety, "is_login_required", lambda page: False)
    monkeypatch.setattr(mainpy, "search_with_posts_filter", lambda *a, **k: True)

    def collect(page, cfg, decider, stats, role, collected=None):
        stats.roles_searched += 1
        stats.posts_processed += 3
        stats.potential_job_posts += 1
        stats.collected += 1
        stats.stop_reason = "collected 5 job descriptions (max_jds)"
        if collected is not None:
            collected.append(match)
        return 1

    monkeypatch.setattr(mainpy, "process_batches", collect)
    monkeypatch.setattr(
        mainpy.printer, "print_header", lambda cfg, mode_label=None: None
    )
    monkeypatch.setattr(mainpy.printer, "print_match", lambda *a, **k: None)

    monkeypatch.setattr(
        mainpy,
        "save_scraping_run",
        lambda matches, stats, cfg, started_at, **kwargs: save_scraping_run(
            matches, stats, cfg, started_at, base=tmp_path, **kwargs
        ),
    )

    stats = mainpy.run(_FakeCfg())
    return stats, match


def test_run_saves_one_file_after_the_summary(monkeypatch, tmp_path, capsys):
    stats, match = _run_with_one_match(monkeypatch, tmp_path)

    files = list(runs_dir(tmp_path).glob("*.json"))
    assert len(files) == 1
    assert files[0].name == "Scraping Run 1.json"

    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["linkedin_post_url"] == match.post.url
    assert payload["summary"]["final_jds_collected"] == stats.collected == 1
    assert payload["summary"]["posts_processed"] == 3

    output = capsys.readouterr().out
    assert "COLLECTION COMPLETE" in output
    assert "[INFO] Saving scraping run..." in output
    assert "[OK] Scraping Run 1 saved successfully." in output
    assert output.index("COLLECTION COMPLETE") < output.index("Saving scraping run...")


def test_a_storage_failure_does_not_break_the_run(monkeypatch, capsys):
    import main as mainpy

    session = _FakeSession()
    monkeypatch.setattr(mainpy, "BrowserSession", lambda cfg: session)
    monkeypatch.setattr(mainpy.safety, "is_login_required", lambda page: False)
    monkeypatch.setattr(mainpy, "search_with_posts_filter", lambda *a, **k: True)
    monkeypatch.setattr(mainpy, "process_batches", lambda *a, **k: 0)
    monkeypatch.setattr(
        mainpy.printer, "print_header", lambda cfg, mode_label=None: None
    )
    monkeypatch.setattr(mainpy.printer, "print_summary", lambda stats, cfg: None)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mainpy, "save_scraping_run", boom)

    stats = mainpy.run(_FakeCfg())

    assert stats.stop_reason == ""
    output = capsys.readouterr().out
    assert "Failed to save this scraping run: disk full" in output
    assert "saved successfully" not in output


def test_dry_run_writes_no_file(monkeypatch, tmp_path, capsys):
    import main as mainpy

    monkeypatch.setattr(
        mainpy,
        "save_scraping_run",
        lambda *a, **k: pytest.fail("dry run must not persist a scraping run"),
    )
    cfg = _FakeCfg()
    cfg.dry_run = "tests/fixtures"
    monkeypatch.setattr(mainpy, "_load_fixture_posts", lambda path: [])

    mainpy.run(cfg)

    assert not runs_dir(tmp_path).exists()