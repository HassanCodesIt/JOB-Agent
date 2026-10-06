"""Launch the LinkedIn scraper as an isolated background subprocess.

The Playwright/CDP lifecycle stays inside ``BrowserAutomationForLinkdin``. This
module only builds the command, captures output, tracks process state and hands
the completed run file to :mod:`linkedin_integration.importer`.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.request import Request, urlopen

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
from database import SessionLocal
from linkedin_integration import importer, modes

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs" / "linkedin"
RUN_TIMEOUT_SECONDS = 45 * 60
POLL_INTERVAL_SECONDS = 1.5
_ERROR_TAIL_LINES = 6

# Active subprocesses for this process lifetime, keyed by LinkedInRun.id.
_PROCESSES: Dict[int, "subprocess.Popen"] = {}


# --------------------------------------------------------------------------- #
# Environment / preflight
# --------------------------------------------------------------------------- #

def cdp_reachable(cdp_url: str, timeout: float = 3.0) -> bool:
    """Soft probe of the logged-in Chrome the scraper will attach to."""
    try:
        request = Request(f"{cdp_url.rstrip('/')}/json/version", method="GET")
        with urlopen(request, timeout=timeout) as response:
            return 200 <= getattr(response, "status", 200) < 300
    except Exception:
        return False


def browser_error_message(cdp_url: str) -> str:
    return (
        "LinkedIn browser connection could not be established. "
        "Make sure your logged-in Chrome session is running with the required CDP setup "
        f"({cdp_url})."
    )


def active_run(db: Session) -> Optional[models.LinkedInRun]:
    """The run that currently owns the browser, if it is really still alive."""
    rows = (
        db.query(models.LinkedInRun)
        .filter(models.LinkedInRun.status == "running")
        .order_by(models.LinkedInRun.started_at.desc())
        .all()
    )
    for row in rows:
        if _run_is_active(row):
            return row
    return None


def _run_is_active(run: models.LinkedInRun) -> bool:
    proc = _PROCESSES.get(run.id)
    if proc is not None and proc.poll() is None:
        return True
    if run.process_id:
        return _pid_status(run.process_id)[0] == "running"
    return False


# --------------------------------------------------------------------------- #
# Process probing (never uses os.kill, which would terminate on Windows)
# --------------------------------------------------------------------------- #

_STILL_ACTIVE = 259


def _pid_status(pid: int) -> tuple:
    """Return ``(state, exit_code)`` where state is ``running``/``exited``/``unknown``."""
    if not pid:
        return ("unknown", None)
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
            if not handle:
                return ("unknown", None)
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return ("unknown", None)
                value = int(code.value)
            finally:
                kernel32.CloseHandle(handle)
            if value == _STILL_ACTIVE:
                return ("running", None)
            return ("exited", value)
        except Exception:
            return ("unknown", None)

    try:
        os.kill(int(pid), 0)
        return ("running", None)
    except ProcessLookupError:
        return ("exited", None)
    except PermissionError:
        return ("running", None)
    except Exception:
        return ("unknown", None)


# --------------------------------------------------------------------------- #
# Starting a run
# --------------------------------------------------------------------------- #

def start_run(
    db: Session,
    *,
    mode_key: str,
    role: str,
    sort_by: Optional[str] = None,
    date_posted: Optional[str] = None,
) -> models.LinkedInRun:
    """Validate the request, launch the scraper and record the run."""
    role = (role or "").strip()
    if not role:
        raise HTTPException(status_code=400, detail="Choose or enter a job role before starting a search.")

    try:
        mode, effective = modes.resolve_entry_point(mode_key, sort_by, date_posted)
    except modes.UnsupportedSearch as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    existing = active_run(db)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="A LinkedIn search is already running. Wait for it to finish before starting another.",
        )

    cdp_url = modes.load_cdp_url()
    if not cdp_reachable(cdp_url):
        raise HTTPException(status_code=503, detail=browser_error_message(cdp_url))

    entry_path = modes.SCRAPER_DIR / mode.entry_point
    if not entry_path.exists():
        raise HTTPException(status_code=500, detail="The LinkedIn automation module is missing from this project.")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.datetime.utcnow()
    log_path = LOG_DIR / f"run_{started.strftime('%Y%m%d_%H%M%S')}.log"

    known_files = sorted(importer.snapshot_run_files())
    configuration = {
        "mode": mode.key,
        "label": mode.label,
        "role": role,
        "sort_by": effective.get("sort_by"),
        "date_posted": effective.get("date_posted"),
        "requested_sort_by": sort_by,
        "requested_date_posted": date_posted,
        "entry_point": mode.entry_point,
        "cdp_url": cdp_url,
        "known_run_files": known_files,
    }

    run = models.LinkedInRun(
        mode=mode.key,
        entry_point=mode.entry_point,
        role=role,
        sort_by=effective.get("sort_by"),
        date_posted=effective.get("date_posted"),
        configuration_json=json.dumps(configuration, ensure_ascii=False),
        status="running",
        process_state="started",
        started_at=started,
        log_path=str(log_path),
        collected_count=0,
        filtered_count=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    command = [
        sys.executable,
        str(entry_path),
        "--roles",
        role,
        "--cdp-url",
        cdp_url,
    ]

    try:
        handle = log_path.open("wb")
    except OSError as exc:
        _fail_early(db, run, f"Could not open the run log: {exc}")
        raise HTTPException(status_code=500, detail="Could not start the LinkedIn search log.")

    try:
        # Explicit argument list, fixed working directory, no shell: user input
        # never reaches a command string.
        process = subprocess.Popen(
            command,
            cwd=str(modes.SCRAPER_DIR),
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            shell=False,
        )
    except OSError as exc:
        handle.close()
        _fail_early(db, run, f"Could not start the LinkedIn automation process: {exc}")
        raise HTTPException(status_code=500, detail="Could not start the LinkedIn search process.")
    finally:
        handle.close()

    run.process_id = process.pid
    db.commit()
    _PROCESSES[run.id] = process
    return run


def _fail_early(db: Session, run: models.LinkedInRun, message: str) -> None:
    run.status = "failed"
    run.error_message = message
    run.completed_at = datetime.datetime.utcnow()
    db.commit()


# --------------------------------------------------------------------------- #
# Watching / finalising
# --------------------------------------------------------------------------- #

def watch_run(run_id: int) -> None:
    """Block until the subprocess exits, then import its run file.

    Run by FastAPI background tasks (threadpool) and by the startup resume path.
    """
    try:
        deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
        exit_code = _await_exit(run_id, deadline)
        finalize_run(run_id, exit_code)
    except Exception as exc:  # never let a watcher exception vanish silently
        _record_crash(run_id, exc)


def stop_run(db: Session, run_id: int) -> models.LinkedInRun:
    """Terminate the live scraper process for ``run_id`` (the Stop Search action).

    The watcher that is already watching the run notices the exit and finalises
    the record (importing any run file the process produced before exiting).
    """
    run = db.query(models.LinkedInRun).filter(models.LinkedInRun.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run.status != "running":
        raise HTTPException(status_code=400, detail="This search is no longer running.")
    proc = _PROCESSES.get(run_id)
    if proc is None or proc.poll() is not None:
        # The pid may still be alive after an app restart, but only the
        # in-process handle can be terminated through this module.
        raise HTTPException(
            status_code=400,
            detail="This search can no longer be stopped from Command.",
        )
    _terminate(run_id)
    return run


def _await_exit(run_id: int, deadline: float) -> Optional[int]:
    while True:
        proc = _PROCESSES.get(run_id)
        if proc is not None:
            code = proc.poll()
            if code is not None:
                return code
        else:
            state, code = _probe_recorded_pid(run_id)
            if state != "running":
                return code
        if time.monotonic() > deadline:
            _terminate(run_id)
            _set_error(run_id, f"LinkedIn search timed out after {RUN_TIMEOUT_SECONDS // 60} minutes.")
            return -1
        time.sleep(POLL_INTERVAL_SECONDS)


def _probe_recorded_pid(run_id: int) -> tuple:
    db = SessionLocal()
    try:
        run = db.query(models.LinkedInRun).filter(models.LinkedInRun.id == run_id).first()
        if run is None:
            return ("exited", None)
        if run.status != "running":
            return ("exited", run.exit_code)
        if not run.process_id:
            return ("exited", None)
        return _pid_status(run.process_id)
    finally:
        db.close()


def _terminate(run_id: int) -> None:
    proc = _PROCESSES.get(run_id)
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def finalize_run(run_id: int, exit_code: Optional[int]) -> None:
    """Import the new run file (when there is one) and close the run record."""
    db = SessionLocal()
    try:
        run = db.query(models.LinkedInRun).filter(models.LinkedInRun.id == run_id).first()
        if run is None:
            return

        known: Set[str] = set()
        try:
            known = set((json.loads(run.configuration_json) or {}).get("known_run_files") or [])
        except (TypeError, ValueError):
            known = set()

        new_file = importer.find_new_run_file(known)
        import_error = None
        if new_file is not None:
            try:
                importer.import_run(db, new_file, linkedin_run=run)
            except Exception as exc:
                import_error = f"Could not import {new_file.name}: {exc}"
        else:
            import_error = None

        failed = exit_code not in (0, None)
        run.exit_code = exit_code
        run.completed_at = datetime.datetime.utcnow()
        run.process_state = "imported" if new_file is not None else "exited"

        if failed:
            run.status = "failed"
            run.error_message = _log_tail(run.log_path) or (
                f"The LinkedIn search process exited with code {exit_code}."
            )
        elif new_file is None:
            run.status = "failed"
            run.error_message = (
                "The LinkedIn search finished but no new run file was created. "
                "Check the run log for details."
            )
        elif import_error:
            run.status = "failed"
            run.error_message = import_error
        else:
            run.status = "completed"
            run.error_message = None

        db.commit()
        _PROCESSES.pop(run_id, None)
    finally:
        db.close()


def _log_tail(log_path: Optional[str]) -> str:
    if not log_path:
        return ""
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-_ERROR_TAIL_LINES:])


def _set_error(run_id: int, message: str) -> None:
    db = SessionLocal()
    try:
        run = db.query(models.LinkedInRun).filter(models.LinkedInRun.id == run_id).first()
        if run is not None:
            run.error_message = message
            db.commit()
    finally:
        db.close()


def _record_crash(run_id: int, exc: Exception) -> None:
    db = SessionLocal()
    try:
        run = db.query(models.LinkedInRun).filter(models.LinkedInRun.id == run_id).first()
        if run is None:
            return
        if run.status == "running":
            run.status = "failed"
            run.completed_at = datetime.datetime.utcnow()
        run.error_message = str(exc)
        db.commit()
    finally:
        db.close()
        _PROCESSES.pop(run_id, None)


# --------------------------------------------------------------------------- #
# Startup reconciliation
# --------------------------------------------------------------------------- #

def reconcile_runs_on_startup() -> List[int]:
    """Re-attach to runs that outlived a restart; close the ones that did not.

    Returns the run ids that still need a watcher.
    """
    resume: List[int] = []
    db = SessionLocal()
    try:
        rows = (
            db.query(models.LinkedInRun)
            .filter(models.LinkedInRun.status == "running")
            .order_by(models.LinkedInRun.started_at.asc())
            .all()
        )
        for run in rows:
            if run.id in _PROCESSES and _PROCESSES[run.id].poll() is None:
                resume.append(run.id)
                continue
            state, code = _pid_status(run.process_id) if run.process_id else ("unknown", None)
            if state == "running":
                resume.append(run.id)
                continue
            if state == "unknown" and not run.process_id:
                run.status = "interrupted"
                run.error_message = "The search was interrupted by an application restart."
                run.completed_at = datetime.datetime.utcnow()
                db.commit()
                continue
            # Process is gone: import whatever it produced, then close it out.
            try:
                finalize_run(run.id, code if code is not None else run.exit_code)
            except Exception as exc:
                run.status = "interrupted"
                run.error_message = str(exc)
                db.commit()
    finally:
        db.close()
    return resume
