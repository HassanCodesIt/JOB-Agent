"""Every scraping entry point, described once.

``run.py``, ``date_posted_24h_run.py``, ``latest_run.py`` and ``top_match_run.py``
are not four scrapers. They are four ways of asking the same shared collector
for a run, and they differ in exactly two things:

* whether ``Date posted -> Past 24 hours`` is applied, and
* which ``Sort by`` option is applied afterwards.

``feed_run.py`` and ``continue_run.py`` join them without adding a second
scraping implementation: they describe a different *flow* (scroll the LinkedIn
feed, or keep scrolling the page a previous run left behind) while applying
neither of the two facets above.

This module is the single place that says so. ``main.py`` reads the behaviour
from it, ``printer.py`` reads the banner label from it, and ``run_storage.py``
reads the JSON metadata from it, so the entry points cannot drift apart
and a stored run always records the filters that actually produced it.

``header_label`` is ``None`` for the two pre-existing modes: their banner is
left exactly as it was before this registry existed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

STANDARD = "standard"
DATE_POSTED_24H = "date_posted_24h"
LATEST = "latest"
BEFORE = "before"
FEED = "feed"
CONTINUE = "continue"

DEFAULT_RUN_MODE = STANDARD

# The only Date posted facet any entry point applies.
PAST_24_HOURS = "past_24_hours"

SORT_LATEST = "latest"
SORT_TOP_MATCH = "top_match"

# Which collection flow a mode drives: the keyword search, the feed, or the
# continuation of whatever page is already open.
FLOW_SEARCH = "search"
FLOW_FEED = "feed"
FLOW_CONTINUE = "continue"


@dataclass(frozen=True)
class RunMode:
    """One entry point's behaviour.

    ``header_label`` is the extra line printed inside the start-up banner, or
    ``None`` to keep the banner unchanged. ``sort_mode`` is ``None`` when the
    Sort by facet is never touched, which is what keeps ``run.py`` and
    ``date_posted_24h_run.py`` byte-for-byte unchanged in their output.
    ``flow`` names the collection flow; it defaults to the keyword search, so
    the four search entry points need nothing new.
    """

    name: str
    header_label: Optional[str]
    apply_past_24h: bool
    sort_mode: Optional[str]
    flow: str = FLOW_SEARCH


RUN_MODES: Dict[str, RunMode] = {
    STANDARD: RunMode(STANDARD, None, False, None),
    DATE_POSTED_24H: RunMode(DATE_POSTED_24H, None, True, None),
    LATEST: RunMode(LATEST, "Past 24 Hours + Latest", True, SORT_LATEST),
    BEFORE: RunMode(BEFORE, "Past 24 Hours + Top Match", True, SORT_TOP_MATCH),
    FEED: RunMode(FEED, "LinkedIn Feed", False, None, FLOW_FEED),
    CONTINUE: RunMode(CONTINUE, "Continue From Current Page", False, None, FLOW_CONTINUE),
}


def get_run_mode(name: Optional[str]) -> RunMode:
    """Look a mode up by name, defaulting to the standard run.

    An unknown name falls back to the standard run rather than raising: the
    name comes from an entry-point script, and falling back keeps
    ``date_posted_24h_run.py`` working exactly as before.
    """
    return RUN_MODES.get((name or "").strip().casefold(), RUN_MODES[DEFAULT_RUN_MODE])


def header_label(run_mode: Optional[str]) -> Optional[str]:
    """The MODE banner line for this run, or ``None`` to print none."""
    return get_run_mode(run_mode).header_label


def flow(run_mode: Optional[str]) -> str:
    """The collection flow this mode drives: search, feed or continue."""
    return get_run_mode(run_mode).flow


def apply_past_24h(run_mode: Optional[str]) -> bool:
    """Whether this run mode applies Date posted -> Past 24 hours."""
    return get_run_mode(run_mode).apply_past_24h


def sort_mode(run_mode: Optional[str]) -> Optional[str]:
    """The Sort by option this run mode requires, or ``None`` for no sorting."""
    return get_run_mode(run_mode).sort_mode


def date_posted_filter(run_mode: Optional[str]) -> Optional[str]:
    """The ``date_posted_filter`` value recorded in a run's JSON metadata."""
    return PAST_24_HOURS if apply_past_24h(run_mode) else None