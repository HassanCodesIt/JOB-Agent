"""Friendly run modes, role input and date/sort mapping."""

from __future__ import annotations

import pytest

from linkedin_integration import modes


# Plan: the six friendly labels must map to the six existing scraper entry points.
EXPECTED_MAPPING = {
    "standard": ("main.py", None, None),
    "date_posted_24h": ("date_posted_24h_run.py", None, "past_24_hours"),
    "latest": ("latest_run.py", "latest", "past_24_hours"),
    "top_match": ("top_match_run.py", "relevance", "past_24_hours"),
    "feed": ("feed_run.py", None, None),
    "continue": ("continue_run.py", None, None),
}


def test_all_six_friendly_modes_exist():
    assert [mode.key for mode in modes.MODES] == [
        "standard",
        "latest",
        "date_posted_24h",
        "top_match",
        "feed",
        "continue",
    ]
    labels = {mode.label for mode in modes.MODES}
    assert labels == {
        "Standard Job Search",
        "Latest Jobs",
        "Jobs Posted in Last 24 Hours",
        "Top Matches",
        "Home Feed",
        "Continue Search",
    }


def test_no_friendly_label_exposes_a_script_name():
    for mode in modes.MODES:
        for other in modes.MODES:
            assert other.entry_point not in mode.label
            assert other.entry_point not in mode.description


def test_preset_modes_map_to_existing_entry_points():
    for key, (entry, sort, date) in EXPECTED_MAPPING.items():
        mode, effective = modes.resolve_entry_point(key)
        assert mode.entry_point == entry, key
        assert effective["sort_by"] == (sort if key in ("latest", "top_match") else None), key
        assert effective["date_posted"] == date, key


def test_standard_run_uses_default_facets():
    mode, effective = modes.resolve_entry_point("standard", "relevance", "any")
    assert mode.entry_point == "main.py"
    assert effective == {"sort_by": None, "date_posted": None}


def test_standard_run_with_past_24_hours_maps_to_date_entry_point():
    mode, effective = modes.resolve_entry_point("standard", "relevance", "past_24_hours")
    assert mode.entry_point == "date_posted_24h_run.py"
    assert effective["date_posted"] == "past_24_hours"
    assert effective["sort_by"] is None


def test_standard_run_with_past_24_hours_and_latest_maps_to_latest_entry_point():
    mode, effective = modes.resolve_entry_point("standard", "latest", "past_24_hours")
    assert mode.entry_point == "latest_run.py"
    assert effective == {"sort_by": "latest", "date_posted": "past_24_hours"}


def test_unsupported_sort_without_date_is_rejected_not_invented():
    with pytest.raises(modes.UnsupportedSearch):
        modes.resolve_entry_point("standard", "latest", "any")


def test_unknown_mode_is_rejected():
    with pytest.raises(modes.UnsupportedSearch):
        modes.resolve_entry_point("definitely-not-a-mode")


def test_unknown_sort_is_rejected():
    with pytest.raises(modes.UnsupportedSearch):
        modes.resolve_entry_point("standard", "newest-first", "any")


def test_preset_mode_facets_cannot_be_overridden():
    with pytest.raises(modes.UnsupportedSearch):
        modes.resolve_entry_point("latest", "relevance", "any")


def test_facet_labels_describe_what_actually_runs():
    mode, effective = modes.resolve_entry_point("latest")
    assert modes.facet_labels(mode, effective) == ["Past 24 hours", "Most recent"]

    mode, effective = modes.resolve_entry_point("standard")
    assert modes.facet_labels(mode, effective) == ["Most relevant"]

    mode, effective = modes.resolve_entry_point("feed")
    assert modes.facet_labels(mode, effective) == ["Home feed"]


def test_preset_roles_come_from_the_scraper_configuration():
    roles = modes.load_preset_roles()
    assert roles, "expected the scraper's own preset roles"
    assert "AI Developer" in roles
    # Values must be readable from the scraper, not invented by this layer.
    scraper = modes.SCRAPER_DIR / "config.py"
    source = scraper.read_text(encoding="utf-8")
    for role in roles:
        assert f'"{role}"' in source


def test_cdp_url_comes_from_the_scraper_config():
    url = modes.load_cdp_url()
    assert url.startswith("http")
    config_file = modes.SCRAPER_DIR / "config.yaml"
    if config_file.exists() and "cdp_url" in config_file.read_text(encoding="utf-8"):
        assert "9222" in url


def test_modes_payload_has_no_entry_point_names():
    import json

    payload = json.dumps(modes.modes_payload())
    for mode in modes.MODES:
        assert mode.entry_point not in payload
