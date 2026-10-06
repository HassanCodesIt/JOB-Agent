from __future__ import annotations

import sys

_COLOR = {
    "INFO": "\033[36m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "OK": "\033[32m",
    "DIM": "\033[2m",
    "RESET": "\033[0m",
}

_state = {"color": False, "quiet": False}


def setup(color: bool = False, quiet: bool = False) -> None:
    _state["color"] = bool(color)
    _state["quiet"] = bool(quiet)
    _force_utf8()


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def paint(text: str, kind: str) -> str:
    if not _state["color"] or kind not in _COLOR:
        return text
    return f"{_COLOR[kind]}{text}{_COLOR['RESET']}"


def _emit(tag: str, message: str, kind: str) -> None:
    if _state["quiet"] and kind == "INFO":
        return
    print(f"{paint(f'[{tag}]', kind)} {message}", flush=True)


def info(message: str) -> None:
    _emit("INFO", message, "INFO")


def warn(message: str) -> None:
    _emit("WARNING", message, "WARNING")


def error(message: str) -> None:
    _emit("ERROR", message, "ERROR")


def ok(message: str) -> None:
    _emit("OK", message, "OK")


def detail(message: str) -> None:
    print(paint(message, "DIM"), flush=True)


def rule(char: str = "=", width: int = 60) -> str:
    return char * width


def blank() -> None:
    print("", flush=True)