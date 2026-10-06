"""Shared fixtures for the LinkedIn Job Finder integration tests.

Everything runs against a throwaway SQLite database and a temporary scraper
directory, so no test touches the real PostgreSQL database or the real
``BrowserAutomationForLinkdin`` run files.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _TESTS_DIR.parent
for _path in (str(_TESTS_DIR), str(PROJECT_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import models  # noqa: E402  (needs the project root on sys.path first)
from linkedin_helpers import sample_job, write_run_file  # noqa: E402,F401

__all__ = ["PROJECT_ROOT", "sample_job", "write_run_file"]


@pytest.fixture()
def engine():
    """One shared in-memory database, visible to every thread.

    SQLite hands each new connection its own empty in-memory database, while
    FastAPI runs routes in a threadpool, so a StaticPool + check_same_thread is
    required for the application code and the test to see the same tables.
    """
    eng = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    models.Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture()
def scraper_dir(tmp_path, monkeypatch):
    """A fake BrowserAutomationForLinkdin folder with an empty run directory."""
    root = tmp_path / "BrowserAutomationForLinkdin"
    runs = root / "data" / "scraping_runs"
    runs.mkdir(parents=True)

    # The six entry points the integration is allowed to launch, plus the
    # scraper's own config file, so nothing in the test reaches the real one.
    for name in (
        "main.py",
        "latest_run.py",
        "date_posted_24h_run.py",
        "top_match_run.py",
        "feed_run.py",
        "continue_run.py",
    ):
        (root / name).write_text("raise SystemExit(0)\n", encoding="utf-8")
    (root / "config.yaml").write_text("cdp_url: http://localhost:9222\n", encoding="utf-8")
    (root / "config.py").write_text('DEFAULT_ROLES = ["AI Developer"]\n', encoding="utf-8")

    from linkedin_integration import importer, modes

    monkeypatch.setattr(importer, "SCRAPER_DIR", root)
    monkeypatch.setattr(importer, "runs_dir", lambda: runs)
    monkeypatch.setattr(modes, "SCRAPER_DIR", root)
    return root
