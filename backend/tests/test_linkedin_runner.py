"""Run lifecycle: validation, single-run lock, subprocess isolation, import."""

from __future__ import annotations

import json
import subprocess as real_subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import models
from linkedin_integration import importer
from linkedin_integration import runner

from linkedin_helpers import sample_job, write_run_file


class FakeProcess:
    """Stands in for the scraper child process; never touches the real machine."""

    instances = []

    def __init__(self, command=None, cwd=None, **kwargs):
        self.command = command
        self.cwd = cwd
        self.pid = 424242
        self.returncode = None
        FakeProcess.instances.append(self)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture()
def isolated_runner(scraper_dir, session_factory, monkeypatch, tmp_path):
    """runner + importer wired to a fake scraper folder and a test database."""
    FakeProcess.instances = []
    monkeypatch.setattr(runner, "SessionLocal", session_factory)
    monkeypatch.setattr(runner, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(
        runner,
        "subprocess",
        SimpleNamespace(Popen=FakeProcess, STDOUT=real_subprocess.STDOUT, DEVNULL=real_subprocess.DEVNULL),
    )
    monkeypatch.setattr(runner, "cdp_reachable", lambda url, timeout=3.0: True)
    monkeypatch.setattr(runner, "_PROCESSES", {})
    monkeypatch.setattr(runner, "POLL_INTERVAL_SECONDS", 0.01)
    yield SimpleNamespace(scraper_dir=scraper_dir, runs=scraper_dir / "data" / "scraping_runs")


def _http_error(exc):
    assert isinstance(exc.value, HTTPException)
    return exc.value


# --------------------------------------------------------------------------- #
# Validation and locking
# --------------------------------------------------------------------------- #

def test_start_run_requires_a_role(db, isolated_runner):
    with pytest.raises(HTTPException) as exc:
        runner.start_run(db, mode_key="standard", role="   ")
    assert _http_error(exc).status_code == 400
    assert db.query(models.LinkedInRun).count() == 0


def test_start_run_rejects_the_unsupported_sort_combo(db, isolated_runner):
    with pytest.raises(HTTPException) as exc:
        runner.start_run(db, mode_key="standard", role="AI Developer", sort_by="latest", date_posted="any")
    assert _http_error(exc).status_code == 400
    assert "Past 24 hours" in _http_error(exc).detail


def test_start_run_rejects_an_unknown_mode(db, isolated_runner):
    with pytest.raises(HTTPException) as exc:
        runner.start_run(db, mode_key="weekly_digest", role="AI Developer")
    assert _http_error(exc).status_code == 400


def test_start_run_fails_fast_without_the_browser(db, isolated_runner, monkeypatch):
    monkeypatch.setattr(runner, "cdp_reachable", lambda url, timeout=3.0: False)
    with pytest.raises(HTTPException) as exc:
        runner.start_run(db, mode_key="standard", role="AI Developer")
    error = _http_error(exc)
    assert error.status_code == 503
    assert "9222" in error.detail, "the message must point at the CDP endpoint"
    assert db.query(models.LinkedInRun).count() == 0, "no run row for a launch that never happened"


def test_second_start_is_rejected_while_a_run_is_active(db, isolated_runner):
    first = runner.start_run(db, mode_key="standard", role="AI Developer")
    assert first.status == "running"

    with pytest.raises(HTTPException) as exc:
        runner.start_run(db, mode_key="latest", role="ML Engineer")
    assert _http_error(exc).status_code == 409
    assert db.query(models.LinkedInRun).count() == 1


# --------------------------------------------------------------------------- #
# Launch + import
# --------------------------------------------------------------------------- #

def test_start_run_launches_the_expected_entry_point_in_the_scraper_folder(db, isolated_runner):
    run = runner.start_run(db, mode_key="latest", role="ML Engineer")

    assert run.entry_point == "latest_run.py", "the friendly mode must not invent a new script"
    assert run.mode == "latest"
    assert run.status == "running"
    assert run.process_id == 424242
    assert run.log_path.endswith(".log") and Path(run.log_path).exists()

    config = json.loads(run.configuration_json)
    assert config["entry_point"] == "latest_run.py"
    assert config["known_run_files"] == []

    process = FakeProcess.instances[-1]
    assert Path(process.cwd) == isolated_runner.scraper_dir, "cwd must be the scraper folder"
    assert process.command[0]
    assert str(isolated_runner.scraper_dir / "latest_run.py") in process.command
    assert "--roles" in process.command and "ML Engineer" in process.command
    assert "--cdp-url" in process.command
    # No shell, so the role text is passed as its own argv entry.
    assert process.command[process.command.index("--roles") + 1] == "ML Engineer"


def test_completed_run_is_imported(db, isolated_runner, session_factory):
    write_run_file(isolated_runner.runs, 1, jobs=[])  # pre-existing history
    run = runner.start_run(db, mode_key="standard", role="AI Developer")
    assert json.loads(run.configuration_json)["known_run_files"] == ["Scraping Run 1.json"]

    write_run_file(
        isolated_runner.runs,
        2,
        jobs=[sample_job(), sample_job(email=None, job_url="https://www.linkedin.com/jobs/view/999/")],
    )
    FakeProcess.instances[-1].returncode = 0

    runner.finalize_run(run.id, 0)

    session = session_factory()
    try:
        stored = session.query(models.LinkedInRun).one()
        assert stored.status == "completed"
        assert stored.exit_code == 0
        assert stored.process_state == "imported"
        assert stored.scraper_run_number == 2
        assert stored.collected_count == 2
        assert stored.error_message is None
        assert stored.completed_at is not None

        jobs = session.query(models.LinkedInJob).all()
        assert len(jobs) == 2
        assert {job.role for job in jobs} == {"AI Developer"}
        assert {job.filter_status for job in jobs} == {"pending"}
        assert {job.filter_batch for job in jobs} == {"email", "no_email"}
        # The two source URL families stay in their own columns.
        assert all(job.linkedin_post_url and job.linkedin_post_url != job.job_url for job in jobs)
    finally:
        session.close()

    assert runner._PROCESSES == {}, "the process handle must be released"


def test_run_that_writes_no_file_is_reported_as_a_failure(db, isolated_runner):
    write_run_file(isolated_runner.runs, 1, jobs=[])
    run = runner.start_run(db, mode_key="standard", role="AI Developer")
    FakeProcess.instances[-1].returncode = 1

    runner.finalize_run(run.id, 1)
    db.refresh(run)

    assert run.status == "failed"
    assert run.exit_code == 1
    assert run.process_state == "exited"
    assert run.error_message


def test_run_that_exits_zero_without_a_file_is_still_a_failure(db, isolated_runner):
    write_run_file(isolated_runner.runs, 1, jobs=[])
    run = runner.start_run(db, mode_key="standard", role="AI Developer")
    FakeProcess.instances[-1].returncode = 0

    runner.finalize_run(run.id, 0)
    db.refresh(run)

    assert run.status == "failed"
    assert "no new run file" in run.error_message


def test_finalize_of_an_unknown_run_is_harmless(db, isolated_runner):
    runner.finalize_run(999999, 0)


# --------------------------------------------------------------------------- #
# Import semantics
# --------------------------------------------------------------------------- #

def test_import_deduplicates_jobs_by_linkedin_post_url(db, scraper_dir):
    runs = scraper_dir / "data" / "scraping_runs"
    first = write_run_file(runs, 1, jobs=[sample_job(), sample_job(email=None)])
    second = write_run_file(runs, 2, jobs=[sample_job(), sample_job(email=None, job_url="https://www.linkedin.com/jobs/view/1/")])

    importer.import_run(db, first)
    db.commit()
    assert db.query(models.LinkedInJob).count() == 2

    importer.import_run(db, second)
    db.commit()
    assert db.query(models.LinkedInJob).count() == 2, "re-running the same search must not duplicate the list"
    assert db.query(models.LinkedInRun).count() == 2


def test_import_skips_jobs_without_a_post_permalink(db, scraper_dir):
    runs = scraper_dir / "data" / "scraping_runs"
    path = write_run_file(runs, 1, jobs=[sample_job(linkedin_post_url=None), sample_job()])
    run = importer.import_run(db, path)
    db.commit()
    assert run.collected_count == 1
    assert db.query(models.LinkedInJob).count() == 1


def test_import_reads_run_metadata_from_the_scraper_file(db, scraper_dir):
    runs = scraper_dir / "data" / "scraping_runs"
    path = write_run_file(
        runs,
        5,
        jobs=[sample_job()],
        run_mode="date_posted_24h",
        date_posted_filter="past_24_hours",
        target_roles=["AI Developer", "ML Engineer"],
    )
    run = importer.import_run(db, path)
    db.commit()
    assert run.scraper_run_number == 5
    assert run.mode == "date_posted_24h"
    assert run.date_posted == "past_24_hours"
    assert json.loads(run.summary_json)["final_jds_collected"] == 1


def test_import_rejects_a_file_that_is_not_a_run(db, scraper_dir, tmp_path):
    junk = tmp_path / "not_a_run.json"
    junk.write_text(json.dumps({"something": "else"}), encoding="utf-8")
    with pytest.raises(ValueError):
        importer.import_run(db, junk)


def test_snapshot_and_find_new_run_file_track_the_scraper_directory(db, scraper_dir):
    runs = scraper_dir / "data" / "scraping_runs"
    write_run_file(runs, 1, jobs=[])
    before = importer.snapshot_run_files()
    assert before == {"Scraping Run 1.json"}

    assert importer.find_new_run_file(before) is None
    write_run_file(runs, 2, jobs=[])
    found = importer.find_new_run_file(before)
    assert found is not None and found.name == "Scraping Run 2.json"
