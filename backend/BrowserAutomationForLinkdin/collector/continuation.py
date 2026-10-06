"""Extending an already-running scrape from the page's current position.

``continue_run.py`` attaches to the LinkedIn tab a previous run left behind --
from ``run.py``, ``date_posted_24h_run.py``, ``latest_run.py``,
``top_match_run.py`` or ``feed_run.py`` -- and keeps going downwards from
wherever that page is right now. Nothing here navigates, reloads, resets
filters or scrolls back to the top:

* :func:`current_scroll_state` only *reads* the page, and refuses to continue
  when the tab is not a LinkedIn page, so a bad session fails with a clear
  error instead of opening LinkedIn somewhere else;
* :func:`seed_deduper` loads the LinkedIn post URLs already stored by earlier
  runs, which makes those posts duplicates from the very first decision of the
  continuation, so they are never printed or stored a second time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from collector import logger
from collector.browser import is_linkedin_url, linkedin_page_kind
from collector.dedupe import Deduplicator, canonical_url
from collector.models import Post
from collector.run_storage import existing_run_numbers, run_file_name, runs_dir


class ContinuationError(RuntimeError):
    """Raised when the open page cannot be continued from."""


@dataclass(frozen=True)
class ScrollState:
    """The current page and scroll position, read without changing either."""

    url: str
    kind: str
    scroll_y: int
    scroll_height: int
    viewport_height: int

    @property
    def kind_label(self) -> str:
        return {"search": "search results", "feed": "feed"}.get(self.kind, "LinkedIn page")


def _page_url(page) -> str:
    try:
        return getattr(page, "url", "") or ""
    except Exception:
        return ""


def _read_int(page, script: str) -> int:
    try:
        value = page.evaluate(script)
    except Exception:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def current_scroll_state(page) -> ScrollState:
    """Describe where the current LinkedIn page is, changing nothing.

    Raises :class:`ContinuationError` when the tab is not a LinkedIn page, so
    the caller can stop safely instead of navigating anywhere.
    """
    url = _page_url(page)
    if not is_linkedin_url(url):
        raise ContinuationError(
            "There is no LinkedIn page to continue from "
            f"(current tab: {url or 'no URL'}). "
            "Open the LinkedIn search results or feed you want to continue in "
            "Chrome and run continue_run.py again."
        )

    return ScrollState(
        url=url,
        kind=linkedin_page_kind(url),
        scroll_y=_read_int(page, "() => Math.max(window.scrollY || 0, window.pageYOffset || 0)"),
        scroll_height=_read_int(
            page,
            "() => (document.documentElement ? document.documentElement.scrollHeight : 0)",
        ),
        viewport_height=_read_int(page, "() => window.innerHeight || 0"),
    )


def _urls_in(payload) -> List[str]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    urls: List[str] = []
    for job in jobs or []:
        if not isinstance(job, dict):
            continue
        url = str(job.get("linkedin_post_url") or "").strip()
        if url:
            urls.append(url)
    return urls


def load_previous_post_urls(base: Optional[Path] = None) -> List[str]:
    """LinkedIn post URLs already collected by earlier scraping runs, in order."""
    directory = runs_dir(base)
    try:
        numbers = existing_run_numbers(directory)
    except OSError as exc:
        logger.warn(f"Could not list earlier scraping runs ({exc}); continuing without them.")
        return []

    urls: List[str] = []
    for number in numbers:
        path = directory / run_file_name(number)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warn(f"Could not read {path.name} ({exc}); skipping its collected URLs.")
            continue
        urls.extend(_urls_in(payload))
    return urls


def seed_deduper(deduper: Deduplicator, base: Optional[Path] = None) -> int:
    """Make every already-collected post URL a duplicate from the first decision.

    The LinkedIn post URL is the primary key, so a post collected by any
    earlier run is skipped whatever its text looks like now. Returns how many
    distinct URLs were seeded.
    """
    seeded = set()
    for url in load_previous_post_urls(base):
        deduper.remember(Post(url=url))
        key = canonical_url(url)
        if key:
            seeded.add(key)
    return len(seeded)
