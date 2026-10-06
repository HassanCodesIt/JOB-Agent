"""Ctrl+C shutdown must stay quiet: no traceback, no lost output."""

from __future__ import annotations

import logging
import subprocess
import sys

import pytest

import run as runpy
from collector.browser import BrowserSession, _DropShutdownNoise, quiet_driver_shutdown


# --- shutdown noise filter -------------------------------------------------


def _record(message, exc=None):
    exc_info = None if exc is None else (type(exc), exc, None)
    return logging.LogRecord("asyncio", logging.ERROR, __file__, 1, message, (), exc_info)


class _TargetClosed(Exception):
    pass


class _TargetClosedError(Exception):
    pass


def test_filter_drops_pending_task_noise():
    noise = _DropShutdownNoise()
    assert noise.filter(_record("Task was destroyed but it is pending!")) is False


def test_filter_drops_target_closed_traceback():
    noise = _DropShutdownNoise()
    record = _record("boom", exc=_TargetClosedError("Target page, context or browser has been closed"))
    assert noise.filter(record) is False


def test_filter_keeps_real_errors():
    noise = _DropShutdownNoise()
    assert noise.filter(_record("Collection failed for role AI Engineer")) is True
    assert noise.filter(_record("boom", exc=ValueError("nope"))) is True


def test_quiet_driver_shutdown_removes_its_filters():
    asyncio_logger = logging.getLogger("asyncio")
    before = list(asyncio_logger.filters)
    with quiet_driver_shutdown():
        assert asyncio_logger.filters != before
    assert asyncio_logger.filters == before


# --- BrowserSession.disconnect --------------------------------------------


class _FakeDriver:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    def stop(self):
        self.calls += 1
        if self.error is not None:
            raise self.error


def test_disconnect_stops_driver_once():
    session = BrowserSession.__new__(BrowserSession)
    driver = _FakeDriver()
    session.playwright = driver
    session.browser = object()
    session.context = object()
    session.page = object()

    session.disconnect()
    session.disconnect()

    assert driver.calls == 1
    assert session.playwright is None
    assert (session.browser, session.context, session.page) == (None, None, None)


def test_disconnect_swallows_target_closed():
    session = BrowserSession.__new__(BrowserSession)
    session.playwright = _FakeDriver(error=_TargetClosedError("closed"))
    session.browser = session.context = session.page = None

    session.disconnect()  # must not raise

    assert session.playwright is None


# --- run.py wrapper --------------------------------------------------------


def test_run_main_returns_130_on_keyboard_interrupt(monkeypatch):
    def boom(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(runpy.subprocess, "run", boom)
    assert runpy.run_main(["--dry-run"]) == 130


def test_run_main_passes_through_exit_code(monkeypatch):
    monkeypatch.setattr(
        runpy.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0)
    )
    assert runpy.run_main(["--dry-run"]) == 0


def test_run_main_reports_missing_main(monkeypatch, tmp_path):
    monkeypatch.setattr(runpy, "ROOT", tmp_path)
    assert runpy.run_main(["--dry-run"]) == 1


def test_run_module_is_importable_without_side_effects():
    result = subprocess.run(
        [sys.executable, "-c", "import run; print(run.ROOT.name)"],
        cwd=str(runpy.ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == runpy.ROOT.name
    assert "Traceback" not in result.stderr


# --- main.run() interrupt path --------------------------------------------


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
    target_roles = ["AI Engineer"]
    max_jds = 5
    max_posts = 100
    max_scrolls = 5
    min_jd_signals = 2


def _run_with_interrupt(monkeypatch):
    import main as mainpy

    session = _FakeSession()
    monkeypatch.setattr(mainpy, "BrowserSession", lambda cfg: session)
    monkeypatch.setattr(mainpy.safety, "is_login_required", lambda page: False)
    monkeypatch.setattr(mainpy, "search_with_posts_filter", lambda *a, **k: True)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(mainpy, "process_batches", interrupt)
    monkeypatch.setattr(
        mainpy.printer, "print_header", lambda cfg, mode_label=None: None
    )
    monkeypatch.setattr(mainpy.printer, "print_match", lambda *a, **k: None)
    monkeypatch.setattr(mainpy.printer, "print_summary", lambda stats, cfg: None)
    # Run storage is a separate concern; these tests must not write real data.
    monkeypatch.setattr(mainpy, "save_scraping_run", lambda *a, **k: None)

    stats = mainpy.run(_FakeCfg())
    return stats, session


def test_interrupt_is_caught_and_reported(monkeypatch):
    stats, session = _run_with_interrupt(monkeypatch)

    assert stats.stop_reason == "interrupted by user"
    assert session.disconnects == 1


def test_interrupt_does_not_propagate(monkeypatch):
    # A raw KeyboardInterrupt escaping run() is what produced the traceback.
    try:
        _run_with_interrupt(monkeypatch)
    except KeyboardInterrupt:  # pragma: no cover - regression guard
        pytest.fail("KeyboardInterrupt escaped main.run()")
    except Exception as exc:  # pragma: no cover - regression guard
        pytest.fail(f"unexpected error escaped main.run(): {exc!r}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))