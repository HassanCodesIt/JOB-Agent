"""Friendly run modes, search facets and the scraper entry points behind them.

Nothing user-facing ever names a script. The UI shows the six friendly labels
below; this module is the single place that maps them (plus the Sort By and
Date Posted facets) onto the scraper's existing entry points.

Only combinations the scraper already implements are resolvable. Anything else
raises :class:`UnsupportedSearch` instead of silently inventing behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRAPER_DIR = Path(__file__).resolve().parent.parent / "BrowserAutomationForLinkdin"

# Sort By facet -> (UI value, UI label, scraper sort_mode or None)
SORT_RELEVANCE = "relevance"
SORT_LATEST = "latest"

SORT_OPTIONS: Tuple[Tuple[str, str], ...] = (
    (SORT_RELEVANCE, "Most relevant"),
    (SORT_LATEST, "Most recent"),
)

# Date Posted facet -> (UI value, UI label)
DATE_ANY = "any"
DATE_PAST_24H = "past_24_hours"

DATE_OPTIONS: Tuple[Tuple[str, str], ...] = (
    (DATE_ANY, "Any time"),
    (DATE_PAST_24H, "Past 24 hours"),
)

DEFAULT_CDP_URL = "http://localhost:9222"


class UnsupportedSearch(ValueError):
    """The requested facet combination has no scraper entry point."""


@dataclass(frozen=True)
class RunMode:
    key: str
    label: str
    entry_point: str
    description: str
    fixed_date: Optional[str] = None
    fixed_sort: Optional[str] = None
    searchable: bool = True  # False for the feed/continuation flows


MODES: Tuple[RunMode, ...] = (
    RunMode(
        key="standard",
        label="Standard Job Search",
        entry_point="main.py",
        description="Search LinkedIn Posts for the selected role.",
    ),
    RunMode(
        key="latest",
        label="Latest Jobs",
        entry_point="latest_run.py",
        description="Jobs posted in the last 24 hours, newest first.",
        fixed_date=DATE_PAST_24H,
        fixed_sort=SORT_LATEST,
    ),
    RunMode(
        key="date_posted_24h",
        label="Jobs Posted in Last 24 Hours",
        entry_point="date_posted_24h_run.py",
        description="Jobs posted in the last 24 hours.",
        fixed_date=DATE_PAST_24H,
    ),
    RunMode(
        key="top_match",
        label="Top Matches",
        entry_point="top_match_run.py",
        description="Best matching jobs from the last 24 hours.",
        fixed_date=DATE_PAST_24H,
        fixed_sort=SORT_RELEVANCE,
    ),
    RunMode(
        key="feed",
        label="Home Feed",
        entry_point="feed_run.py",
        description="Collect job posts from your LinkedIn home feed.",
        searchable=False,
    ),
    RunMode(
        key="continue",
        label="Continue Search",
        entry_point="continue_run.py",
        description="Keep scrolling where the previous run stopped.",
        searchable=False,
    ),
)

MODES_BY_KEY: Dict[str, RunMode] = {mode.key: mode for mode in MODES}


def get_mode(key: Optional[str]) -> RunMode:
    mode = MODES_BY_KEY.get((key or "").strip().lower())
    if mode is None:
        raise UnsupportedSearch(f"Unknown run mode: {key!r}")
    return mode


def modes_payload() -> List[dict]:
    return [
        {
            "key": mode.key,
            "label": mode.label,
            "description": mode.description,
            "searchable": mode.searchable,
            "fixed_date": mode.fixed_date,
            "fixed_sort": mode.fixed_sort,
        }
        for mode in MODES
    ]


def _scraper_sort_value(sort_by: Optional[str]) -> Optional[str]:
    """UI sort value -> the scraper's ``sort_mode`` literal (``None`` = LinkedIn default)."""
    if sort_by in (None, "", SORT_RELEVANCE):
        return None
    if sort_by == SORT_LATEST:
        return "latest"
    raise UnsupportedSearch(f"Unknown sort option: {sort_by!r}")


def resolve_entry_point(
    mode_key: str,
    sort_by: Optional[str] = None,
    date_posted: Optional[str] = None,
) -> Tuple[RunMode, dict]:
    """Return the run mode plus the exact scraper configuration it implies.

    ``Standard Job Search`` is the only mode whose facets are configurable;
    the other five describe a fixed flow the scraper already implements.
    """
    mode = get_mode(mode_key)
    # Facet values are validated strictly: an unknown option is a client error,
    # never something to silently reinterpret.
    if sort_by not in (None, "", SORT_RELEVANCE, SORT_LATEST):
        raise UnsupportedSearch(f"Unknown sort option: {sort_by!r}")
    if date_posted not in (None, "", DATE_ANY, DATE_PAST_24H):
        raise UnsupportedSearch(f"Unknown date filter: {date_posted!r}")
    date = date_posted if date_posted in (DATE_ANY, DATE_PAST_24H) else DATE_ANY
    sort = sort_by if sort_by in (SORT_RELEVANCE, SORT_LATEST) else SORT_RELEVANCE

    effective = {
        "sort_by": mode.fixed_sort if mode.fixed_sort is not None else None,
        "date_posted": mode.fixed_date,
    }

    if not mode.searchable:
        if sort_by or date_posted:
            # Feed and Continue runs never apply these facets; ignore rather than fail.
            pass
        return mode, effective

    if mode.fixed_date is not None or mode.fixed_sort is not None:
        # Preset run: its facets are fixed by definition.
        if sort_by and mode.fixed_sort is not None and sort_by != mode.fixed_sort:
            raise UnsupportedSearch(f"{mode.label} always uses its own sort order.")
        if date_posted and mode.fixed_date is not None and date_posted != mode.fixed_date:
            raise UnsupportedSearch(f"{mode.label} always uses its own date filter.")
        return mode, effective

    # Standard Job Search: derive the entry point from the two facets.
    scraper_sort = _scraper_sort_value(sort)
    if date == DATE_ANY:
        if scraper_sort is not None:
            raise UnsupportedSearch(
                "Most recent sorting is only supported together with Date Posted: Past 24 hours."
            )
        effective = {"sort_by": None, "date_posted": None}
        return mode, effective

    if scraper_sort is None:
        resolved = MODES_BY_KEY["date_posted_24h"]
        effective = {"sort_by": None, "date_posted": DATE_PAST_24H}
        return resolved, effective

    resolved = MODES_BY_KEY["latest"]
    effective = {"sort_by": "latest", "date_posted": DATE_PAST_24H}
    return resolved, effective


def facet_labels(mode: RunMode, effective: dict) -> List[str]:
    """Short human labels for the facets a run will actually apply."""
    labels = []
    if effective.get("date_posted") == DATE_PAST_24H:
        labels.append("Past 24 hours")
    if effective.get("sort_by") == "latest":
        labels.append("Most recent")
    elif mode.searchable:
        labels.append("Most relevant")
    if mode.key == "feed":
        return ["Home feed"]
    if mode.key == "continue":
        return ["Continuation"]
    return labels


def load_preset_roles() -> List[str]:
    """Role presets come from the scraper's own configuration, never invented here."""
    try:
        import sys

        path = str(SCRAPER_DIR)
        added = path not in sys.path
        if added:
            sys.path.insert(0, path)
        try:
            import config as scraper_config  # the scraper's config module

            roles = list(getattr(scraper_config, "DEFAULT_ROLES", ()) or ())
        finally:
            if added:
                try:
                    sys.path.remove(path)
                except ValueError:
                    pass
        return [str(role).strip() for role in roles if str(role).strip()]
    except Exception:
        return []


def load_cdp_url() -> str:
    """CDP endpoint from the scraper's own config file when present."""
    try:
        import yaml

        config_file = SCRAPER_DIR / "config.yaml"
        if config_file.exists():
            data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            url = str(data.get("cdp_url") or "").strip()
            if url:
                return url
    except Exception:
        pass
    return DEFAULT_CDP_URL
