"""Single entry point for the whole application.

    python run.py

starts the FastAPI backend (backend/) and serves the built React frontend
(frontend/dist) from the same process and the same origin.

The backend keeps its resources (templates, static, uploads, posters,
screenshots, .env, email account files) as working-directory-relative paths,
so this launcher moves into backend/ before starting uvicorn and exposes
backend/ on PYTHONPATH so all existing top-level imports keep working
unchanged (main, models, linkedin_integration, ...).
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
VENV_PYTHON = BACKEND / "venv" / "Scripts" / "python.exe"


def _ensure_environment():
    """Run under the project virtualenv when the current interpreter cannot
    import the backend dependencies (e.g. plain system Python without
    psycopg2). Keeps `python run.py` sufficient from any shell.
    """
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import sqlalchemy  # noqa: F401
        import jinja2  # noqa: F401
        import psycopg2  # noqa: F401
        import dotenv  # noqa: F401
        return
    except ImportError:
        pass

    if not VENV_PYTHON.exists():
        return  # let the missing import surface with its original error

    current = Path(sys.executable).resolve() if sys.executable else None
    if current == VENV_PYTHON.resolve():
        return  # already inside the project venv; do not loop

    raise SystemExit(
        subprocess.call([str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])
    )


def _configure_paths():
    """Expose backend/ to imports and to child processes (uvicorn --reload
    re-imports main:app in a spawned child)."""
    backend_str = str(BACKEND)
    existing = os.environ.get("PYTHONPATH", "")
    if backend_str not in existing.split(os.pathsep):
        os.environ["PYTHONPATH"] = (
            backend_str + os.pathsep + existing if existing else backend_str
        )
    if backend_str not in sys.path:
        sys.path.insert(0, backend_str)
    os.chdir(backend_str)  # templates/ static/ uploads/ posters/ .env all live here


if __name__ == "__main__":
    _ensure_environment()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    _configure_paths()

    import uvicorn

    # reload=True would put uvicorn in subprocess mode, which on Windows
    # forces a SelectorEventLoop that cannot spawn processes (Playwright's
    # browser never starts). Keep reload as an explicit opt-in for development.
    reload = os.environ.get("COMMAND_DEV_RELOAD") == "1"
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=reload, loop="asyncio")
