from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Sequence

ROOT = Path(__file__).resolve().parent
MIN_PYTHON = (3, 10)
REQUIREMENTS = ROOT / "requirements.txt"
DEFAULT_CDP_URL = "http://localhost:9222"
DEFAULT_PROFILE = ROOT / ".chrome-linkedin-profile"

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Google\Chrome Beta\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "chrome",
    "google-chrome",
    "chromium",
)

RESET, RED, YELLOW, GREEN, DIM = "\033[0m", "\033[31m", "\033[33m", "\033[32m", "\033[2m"


def color(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if sys.stdout.isatty() else text


def say(tag: str, message: str, code: str = "") -> None:
    label = color(f"[{tag}]", code) if code else f"[{tag}]"
    print(f"{label} {message}", flush=True)


def fail(tag: str, message: str) -> None:
    say(tag, message, RED)


def warn(tag: str, message: str) -> None:
    say(tag, message, YELLOW)


def good(tag: str, message: str) -> None:
    say(tag, message, GREEN)


def python_version_ok() -> bool:
    return sys.version_info[:2] >= MIN_PYTHON


def missing_packages() -> List[str]:
    import importlib.util

    mapping = {"playwright": "playwright", "yaml": "pyyaml", "pytest": "pytest"}
    missing = []
    for module, package in mapping.items():
        if importlib.util.find_spec(module) is None:
            missing.append(package)
    return missing


def install_command() -> str:
    return f'"{sys.executable}" -m pip install -r "{REQUIREMENTS}"'


def ensure_dependencies(install: bool) -> bool:
    missing = missing_packages()
    if not missing:
        good("OK", "Dependencies installed: playwright, PyYAML, pytest.")
        return True

    warn("WARNING", f"Missing package(s): {', '.join(missing)}")
    if not install:
        fail("ERROR", "They are missing from the interpreter running this script.")
        say("INFO", f"Install them into that same interpreter:\n    {install_command()}")
        say("INFO", "Or re-run with --install and run.py will do it for you.")
        return False

    say("INFO", "Installing dependencies from requirements.txt ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        fail("ERROR", "pip install failed. Install manually with:")
        print(color(f"    {install_command()}", DIM), flush=True)
        return False

    still_missing = missing_packages()
    if still_missing:
        fail("ERROR", f"Still missing: {', '.join(still_missing)}")
        return False
    good("OK", "Dependencies installed.")
    return True


def cdp_endpoint(cdp_url: str) -> Optional[dict]:
    base = cdp_url.rstrip("/")
    for path in ("/json/version", "/json"):
        try:
            with urllib.request.urlopen(base + path, timeout=3) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            continue
    return None


def cdp_ready(cdp_url: str) -> bool:
    return cdp_endpoint(cdp_url) is not None


def find_chrome() -> Optional[str]:
    for candidate in CHROME_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
        located = shutil.which(candidate)
        if located:
            return located
    return None


def launch_chrome(cdp_url: str, profile: Path, wait: float = 12.0) -> bool:
    chrome = find_chrome()
    if not chrome:
        fail("ERROR", "Chrome/Chromium executable not found.")
        return False

    port = cdp_url.rsplit(":", 1)[-1].rstrip("/") or "9222"
    profile.mkdir(parents=True, exist_ok=True)
    say("INFO", f"Launching: {chrome} --remote-debugging-port={port}")
    try:
        subprocess.Popen(
            [chrome, f"--remote-debugging-port={port}", f"--user-data-dir={profile}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        fail("ERROR", f"Could not launch Chrome: {exc}")
        return False

    deadline = time.time() + wait
    while time.time() < deadline:
        if cdp_ready(cdp_url):
            good("OK", f"Chrome is listening on {cdp_url}")
            return True
        time.sleep(0.5)

    fail("ERROR", f"Chrome did not expose {cdp_url} in time.")
    return False


def cdp_from_args(argv: Sequence[str]) -> str:
    for index, arg in enumerate(argv):
        if arg == "--cdp-url" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--cdp-url="):
            return arg.split("=", 1)[1]
    return DEFAULT_CDP_URL


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description=(
            "One-command launcher: checks Python/deps, makes sure Chrome is "
            "listening on the CDP port, then runs main.py. Any argument is "
            "passed straight through to main.py."
        ),
        epilog=(
            "examples:\n"
            "  python run.py\n"
            "  python run.py --launch-chrome\n"
            "  python run.py --max-scrolls 2 --max-jds 3\n"
            "  python run.py --roles \"LLM Engineer,AI Developer\"\n"
            "  python run.py --dry-run\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--install", action="store_true", help="pip install -r requirements.txt when imports are missing")
    parser.add_argument("--launch-chrome", action="store_true", help="start Chrome with remote debugging if it is not listening yet")
    parser.add_argument("--no-chrome-check", action="store_true", help="skip the CDP reachability check")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help=f"Chrome user-data-dir used by --launch-chrome (default {DEFAULT_PROFILE.name})")
    return parser


def run_main(argv: List[str]) -> int:
    script = ROOT / "main.py"
    if not script.exists():
        fail("ERROR", f"main.py not found next to run.py ({ROOT})")
        return 1
    try:
        result = subprocess.run([sys.executable, str(script), *argv], cwd=str(ROOT))
    except KeyboardInterrupt:
        # Ctrl+C reaches the whole console process group, so main.py handles it
        # too: it prints every JD it already collected plus the summary and then
        # exits. Waiting here keeps that output intact and avoids a traceback
        # from this wrapper on top of it.
        print()
        good("OK", "Interrupted. Everything collected so far was printed above.")
        return 130
    return result.returncode


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    launcher = build_parser()
    options, passthrough = launcher.parse_known_args(argv)

    if not python_version_ok():
        fail(
            "ERROR",
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required, found {sys.version.split()[0]}.",
        )
        return 1

    good("OK", f"Python {sys.version.split()[0]} at {sys.executable}")

    if not ensure_dependencies(install=bool(options.install)):
        return 1

    cdp_url = cdp_from_args(passthrough)

    if not options.no_chrome_check:
        if not cdp_ready(cdp_url):
            if not options.launch_chrome:
                fail("ERROR", f"No Chrome found on {cdp_url}.")
                warn("WARNING", "Start Chrome with remote debugging, then run this again:")
                print(color(f'    "{find_chrome() or "chrome.exe"}" --remote-debugging-port=9222 '
                            f'--user-data-dir="{options.profile}"', DIM))
                say("INFO", "Or let this script do it for you: python run.py --launch-chrome")
                return 1
            if not launch_chrome(cdp_url, Path(options.profile)):
                fail("ERROR", f"Chrome is not reachable on {cdp_url}.")
                return 1
            time.sleep(1.5)
        good("OK", f"Chrome DevTools endpoint reachable on {cdp_url}")

    return run_main(passthrough)


if __name__ == "__main__":
    raise SystemExit(main())