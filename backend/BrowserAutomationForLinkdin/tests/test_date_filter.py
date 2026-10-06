"""Date posted -> Past 24 hours, exercised against LinkedIn's real menu markup.

The doubles below mirror what the live Date posted menu exposes (see the
module docstring in collector/date_filter.py): the option text is a bare
``<span>`` with no role, the radio input lives under ``aria-hidden="true"`` and
is visually hidden behind an empty ``<label for=...>``, and "Show results" is a
link whose href only becomes ``origin=FACETED_SEARCH`` once a facet is picked.
"""

from __future__ import annotations

import pytest

from collector import date_filter
from collector.safety import NavigatorError


POSTS_URL = "https://www.linkedin.com/search/results/posts/?keywords=AI"
FILTERED_URL = (
    "https://www.linkedin.com/search/results/posts/?keywords=AI"
    "&origin=FACETED_SEARCH&datePosted=%5B%22past-24h%22%5D"
)


class _FakeTime:
    """Virtual clock so deadline-based waits run their real loop, instantly."""

    def __init__(self):
        self.seconds = 0.0

    def monotonic(self):
        return self.seconds

    def sleep(self, seconds):
        self.seconds += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    fake = _FakeTime()
    monkeypatch.setattr(date_filter, "time", fake)
    return fake


class Locator:
    """One matched element. ``owner`` records what the code did to it."""

    def __init__(self, owner, tag="", count=1, visible=True, checked=False):
        self._owner = owner
        self.tag = tag
        self._count = count
        self._visible = visible
        self.checked = checked

    @property
    def first(self):
        return self

    def count(self):
        return self._count

    def is_visible(self):
        return self._visible

    def is_checked(self):
        return self.checked

    def click(self, timeout=None, force=None):
        if self.tag == "past24_text":
            self._owner.select_by_text()
        elif self.tag == "past24_label":
            self._owner.select_by_text()
        elif self.tag == "date_posted":
            self._owner.menu_open = True
        elif self.tag == "show_results":
            self._owner.apply()
        else:
            raise AssertionError(f"unexpected click on {self.tag!r}")

    def evaluate(self, script):
        if "el.click" not in script:
            raise AssertionError("evaluate must only be used as a click fallback")
        self.click()

    def wait_for(self, state=None, timeout=None):
        if not self._visible:
            raise TimeoutError("not visible")


class Page:
    """A LinkedIn Posts page whose Date posted menu can be opened."""

    def __init__(self, url=POSTS_URL, has_option=True, has_show_results=True, has_date_posted=True):
        self.url = url
        self.menu_open = False
        self.has_option = has_option
        self.has_show_results = has_show_results
        self.has_date_posted = has_date_posted
        self.applied_chip = False
        self.clicks = []
        self.selection_strategy = None

    # -- helpers used by the doubles -------------------------------------

    def select_by_text(self, strategy="text"):
        self.selection_strategy = strategy
        self.clicks.append("select:Past 24 hours")
        self.radio_checked = True

    def apply(self):
        self.clicks.append("click:Show results")
        self.url = FILTERED_URL
        self.menu_open = False
        self.applied_chip = True

    # -- Playwright surface ---------------------------------------------

    def wait_for_timeout(self, millis):
        date_filter.time.sleep(millis / 1000.0)

    def wait_for_load_state(self, state, timeout=None):
        pass

    def locator(self, selector):
        if selector == date_filter.PAST_24H_RADIO_SELECTOR:
            visible = self.menu_open and self.has_option
            return Locator(self, tag="radio", count=1 if visible else 0,
                           visible=False, checked=getattr(self, "radio_checked", False))
        if selector == date_filter.APPLIED_CHIP_SELECTOR:
            return Locator(self, tag="chip", count=1 if self.applied_chip else 0)
        if selector.startswith("label[for="):
            found = self.menu_open and self.has_option
            return Locator(self, tag="past24_label", count=1 if found else 0)
        if "Date posted" in selector:
            return Locator(self, tag="date_posted", count=1 if self.has_date_posted else 0)
        return Locator(self, tag="unknown", count=0)

    def get_by_text(self, text, exact=False):
        if text == date_filter.PAST_24H_TEXT and self.menu_open and self.has_option:
            return Locator(self, tag="past24_text")
        if text == date_filter.SHOW_RESULTS_TEXT and self.menu_open and self.has_show_results:
            return Locator(self, tag="show_results")
        return Locator(self, tag="missing", count=0)

    def get_by_role(self, role, name=None, exact=None):
        if name == date_filter.PAST_24H_TEXT:
            # LinkedIn hides the radio under aria-hidden="true", so no role query
            # can ever reach the option.
            return Locator(self, tag="missing", count=0)
        if name == date_filter.SHOW_RESULTS_TEXT and role in ("link", "button"):
            if self.menu_open and self.has_show_results:
                return Locator(self, tag="show_results")
            return Locator(self, tag="missing", count=0)
        if name == "Date posted" and self.has_date_posted:
            return Locator(self, tag="date_posted")
        return Locator(self, tag="missing", count=0)

    def evaluate(self, script, arg=None):
        if "r.id" in script:
            return "_r_fake_" if (self.menu_open and self.has_option) else ""
        if "r.checked" in script:
            return bool(getattr(self, "radio_checked", False))
        raise AssertionError("unexpected page.evaluate")


@pytest.fixture
def page():
    return Page()


# --- happy path --------------------------------------------------------------


def test_filter_is_applied_and_verified(page, capsys):
    date_filter.apply_past_24_hours_filter(page)

    out = capsys.readouterr().out
    assert 'Applying LinkedIn date filter...' in out
    assert 'Opening "Date posted" filter...' in out
    assert 'Selecting "Past 24 hours"...' in out
    assert 'Clicking "Show results"...' in out
    assert "[OK] Date posted filter applied: Past 24 hours" in out
    assert page.clicks == ["select:Past 24 hours", "click:Show results"]


def test_date_posted_is_opened_before_the_option_is_selected(page):
    date_filter.apply_past_24_hours_filter(page)

    # The option only exists once the menu is open, so reaching it proves the
    # "Date posted" control was clicked.
    assert page.selection_strategy == "text"


def test_option_is_found_by_exact_visible_text(page):
    """LinkedIn exposes the option only as a bare <span>; no role sees it."""
    page.menu_open = True

    assert date_filter._select_past_24h(page).startswith("exact visible text")
    assert page.get_by_role("radio", name="Past 24 hours", exact=True).count() == 0
    assert page.get_by_role("menuitemradio", name="Past 24 hours", exact=True).count() == 0


def test_option_falls_back_to_the_label_bound_to_the_radio(monkeypatch):
    """If the text ever stops being clickable, the empty <label for> still is."""
    page = Page()
    page.menu_open = True

    original = page.get_by_text

    def no_text(text, exact=False):
        if text == date_filter.PAST_24H_TEXT:
            return Locator(page, tag="missing", count=0)
        return original(text, exact=exact)

    monkeypatch.setattr(page, "get_by_text", no_text)

    strategy = date_filter._select_past_24h(page)

    assert strategy == "the <label for> bound to the radio"
    assert page.clicks == ["select:Past 24 hours"]


def test_show_results_is_clicked_by_its_accessible_name(page):
    date_filter.apply_past_24_hours_filter(page)

    assert page.clicks[-1] == "click:Show results"


def test_exact_matching_never_selects_past_week_or_past_month(page):
    """Only "Past 24 hours" is looked for, so sibling options are unreachable."""
    assert date_filter.PAST_24H_TEXT == "Past 24 hours"
    page.menu_open = True

    assert page.get_by_text("Past 24 hours", exact=True).count() == 1
    for sibling in ("Past week", "Past month"):
        assert page.get_by_text(sibling, exact=True).count() == 0


# --- verification ------------------------------------------------------------


def test_url_state_is_read_from_the_date_posted_query_parameter():
    assert date_filter.url_has_past_24h(FILTERED_URL) is True
    assert date_filter.url_has_past_24h(
        "https://www.linkedin.com/search/results/posts/?keywords=AI&datePosted=past-24h"
    ) is True
    assert date_filter.url_has_past_24h(POSTS_URL) is False
    assert date_filter.url_has_past_24h(
        "https://www.linkedin.com/search/results/posts/?keywords=AI&datePosted=%5B%22past-week%22%5D"
    ) is False
    assert date_filter.url_has_past_24h("") is False
    assert date_filter.url_has_past_24h("not a url") is False


def test_finding_the_text_alone_is_not_success(page, monkeypatch):
    """Requirement: the option must be *selected*, not merely located."""
    page.menu_open = True

    def never_selects(self, strategy="text"):
        self.clicks.append("select:Past 24 hours")

    monkeypatch.setattr(Page, "select_by_text", never_selects)

    with pytest.raises(NavigatorError):
        date_filter.apply_past_24_hours_filter(page)


def test_success_requires_the_applied_state(page, monkeypatch, capsys):
    """A click that completes but never applies the facet must not report OK."""
    monkeypatch.setattr(
        Page,
        "apply",
        lambda self: self.clicks.append("click:Show results"),
    )

    with pytest.raises(NavigatorError):
        date_filter.apply_past_24_hours_filter(page)

    assert "[OK] Date posted filter applied" not in capsys.readouterr().out


def test_verification_failure_stops_the_run(page, monkeypatch):
    monkeypatch.setattr(
        Page,
        "apply",
        lambda self: self.clicks.append("click:Show results"),
    )

    with pytest.raises(NavigatorError, match='Could not verify that "Past 24 hours" was applied'):
        date_filter.apply_past_24_hours_filter(page)


def test_applied_state_also_accepts_linkedins_filter_chip(page):
    page.url = POSTS_URL
    page.applied_chip = True

    assert date_filter._date_posted_applied(page) is True
    assert date_filter.url_has_past_24h(page.url) is False


# --- safe failures -----------------------------------------------------------


def test_missing_date_posted_filter_fails(page, capsys):
    page.has_date_posted = False

    with pytest.raises(NavigatorError, match='"Date posted" filter not found'):
        date_filter.apply_past_24_hours_filter(page)

    assert page.clicks == []


def test_missing_option_fails_and_never_applies(page, capsys):
    page.has_option = False

    with pytest.raises(NavigatorError, match='"Past 24 hours" option not found'):
        date_filter.apply_past_24_hours_filter(page)

    assert "Show results" not in " ".join(page.clicks)
    assert "[OK]" not in capsys.readouterr().out


def test_option_absent_from_the_opened_menu_fails(page):
    """The menu opens but renders nothing selectable."""
    page.menu_open = True
    page.has_option = False

    with pytest.raises(NavigatorError, match='"Past 24 hours" option not found'):
        date_filter.apply_past_24_hours_filter(page)


def test_missing_show_results_fails(page, capsys):
    page.has_show_results = False

    with pytest.raises(NavigatorError, match='"Show results" button not found'):
        date_filter.apply_past_24_hours_filter(page)

    assert page.clicks == ["select:Past 24 hours"]
    assert "[OK]" not in capsys.readouterr().out


def test_failure_messages_report_the_strategies_tried():
    page = Page(has_option=False)
    page.menu_open = True

    with pytest.raises(NavigatorError) as info:
        date_filter.apply_past_24_hours_filter(page)

    assert "exact visible text" in str(info.value)


# --- already-applied searches (LinkedIn carries the facet across keywords) ---


def test_carried_over_filter_is_verified_not_reapplied(page, capsys):
    page.url = FILTERED_URL
    page.applied_chip = True

    date_filter.apply_past_24_hours_filter(page)

    out = capsys.readouterr().out
    assert "[OK] Date posted filter applied: Past 24 hours" in out
    assert "already active" in out
    # Nothing was clicked: the facet was already in effect for this search.
    assert page.clicks == []


# --- menu that renders late --------------------------------------------------


def test_option_is_awaited_instead_of_looked_up_once(monkeypatch):
    """The menu renders after the click, so the lookup must poll, not guess."""
    page = Page(has_option=False)
    checks = {"n": 0}

    def appears_later(text, exact=False):
        if text == date_filter.PAST_24H_TEXT:
            checks["n"] += 1
            if checks["n"] >= 3:
                page.has_option = True
                return Locator(page, tag="past24_text")
        return Locator(page, tag="missing", count=0)

    monkeypatch.setattr(page, "get_by_text", appears_later)

    assert date_filter._wait_for_option(page, timeout=5000) is True
    assert checks["n"] >= 3


def test_wait_gives_up_when_the_menu_never_renders():
    page = Page(has_option=False)

    assert date_filter._wait_for_option(page, timeout=200) is False


# --- entry-point wiring ------------------------------------------------------


class _Session:
    def connect(self):
        return object()

    def page_title(self):
        return "LinkedIn"

    def disconnect(self):
        pass


class _Cfg:
    dry_run = False
    target_roles = ["AI Engineer"]
    max_jds = 5
    max_posts = 100
    max_scrolls = 5
    min_jd_signals = 2
    color = False
    quiet = False


def test_entry_point_asks_main_for_the_date_posted_mode(monkeypatch):
    import main as mainpy

    calls = {}
    monkeypatch.setattr(mainpy, "load_config", lambda argv=None: _Cfg())
    monkeypatch.setattr(
        mainpy,
        "run",
        lambda cfg, run_mode="standard", apply_past_24h=False, sort_mode=None: calls.update(
            run_mode=run_mode, apply_past_24h=apply_past_24h
        ),
    )

    assert mainpy.main(run_mode="date_posted_24h", apply_past_24h=True) == 0
    assert calls == {"run_mode": "date_posted_24h", "apply_past_24h": True}
    # The date-posted entry point must not acquire a sort on the way.
    assert calls.get("sort_mode") is None


def test_search_with_posts_filter_applies_the_date_filter(monkeypatch):
    import main as mainpy

    events = []
    monkeypatch.setattr(mainpy.navigator, "search_role", lambda page, role, cfg: events.append(("search", role)))
    monkeypatch.setattr(mainpy.navigator, "select_posts_filter", lambda page, role="", cfg=None: events.append(("posts", role)))
    monkeypatch.setattr(mainpy.date_filter, "apply_past_24_hours_filter", lambda page: events.append(("filter",)))

    assert mainpy.search_with_posts_filter(object(), "AI Developer", None, apply_past_24h=True) is True
    assert events == [("search", "AI Developer"), ("posts", "AI Developer"), ("filter",)]


def test_standard_mode_never_touches_the_date_filter(monkeypatch):
    """run.py's standard mode must behave exactly as before."""
    import main as mainpy

    events = []
    monkeypatch.setattr(mainpy.navigator, "search_role", lambda page, role, cfg: None)
    monkeypatch.setattr(mainpy.navigator, "select_posts_filter", lambda page, role="", cfg=None: None)
    monkeypatch.setattr(mainpy.date_filter, "apply_past_24_hours_filter", lambda page: events.append("filter"))

    assert mainpy.search_with_posts_filter(object(), "AI Developer", None) is True
    assert events == []


def test_unverifiable_filter_prevents_scraping(monkeypatch):
    """A filter that cannot be verified must stop the role, not scrape it."""
    import main as mainpy

    def refuse(page):
        raise NavigatorError('Could not verify that "Past 24 hours" was applied.')

    scraped = []
    monkeypatch.setattr(mainpy, "BrowserSession", lambda cfg: _Session())
    monkeypatch.setattr(mainpy.safety, "is_login_required", lambda page: False)
    monkeypatch.setattr(mainpy.navigator, "search_role", lambda page, role, cfg: None)
    monkeypatch.setattr(mainpy.navigator, "select_posts_filter", lambda page, role="", cfg=None: None)
    monkeypatch.setattr(mainpy.date_filter, "apply_past_24_hours_filter", refuse)
    monkeypatch.setattr(mainpy, "process_batches", lambda *a, **k: scraped.append(a) or 0)
    monkeypatch.setattr(
        mainpy.printer, "print_header", lambda cfg, mode_label=None: None
    )
    monkeypatch.setattr(mainpy.printer, "print_summary", lambda stats, cfg: None)
    monkeypatch.setattr(mainpy, "save_scraping_run", lambda *a, **k: None)

    stats = mainpy.run(_Cfg(), run_mode="date_posted_24h", apply_past_24h=True)

    assert scraped == []
    assert (stats.roles_skipped, stats.roles_searched, stats.collected) == (1, 0, 0)


def test_verified_filter_lets_scraping_proceed(monkeypatch):
    import main as mainpy

    order = []
    monkeypatch.setattr(mainpy, "BrowserSession", lambda cfg: _Session())
    monkeypatch.setattr(mainpy.safety, "is_login_required", lambda page: False)
    monkeypatch.setattr(mainpy.navigator, "search_role", lambda page, role, cfg: None)
    monkeypatch.setattr(mainpy.navigator, "select_posts_filter", lambda page, role="", cfg=None: None)
    monkeypatch.setattr(mainpy.date_filter, "apply_past_24_hours_filter", lambda page: order.append("filter"))
    monkeypatch.setattr(mainpy, "process_batches", lambda *a, **k: order.append("scrape") or 0)
    monkeypatch.setattr(
        mainpy.printer, "print_header", lambda cfg, mode_label=None: None
    )
    monkeypatch.setattr(mainpy.printer, "print_summary", lambda stats, cfg: None)
    monkeypatch.setattr(mainpy, "save_scraping_run", lambda *a, **k: None)

    stats = mainpy.run(_Cfg(), run_mode="date_posted_24h", apply_past_24h=True)

    assert order == ["filter", "scrape"]
    assert stats.roles_searched == 1


def test_run_py_is_untouched_by_the_date_posted_entry_point():
    """run.py stays the plain launcher; the date mode is a separate entry point."""
    import inspect

    import date_posted_24h_run
    import run as runpy

    source = inspect.getsource(date_posted_24h_run)
    assert 'run_mode="date_posted_24h"' in source
    assert "apply_past_24h=True" in source
    # run.py must not know about the date filter at all.
    assert "apply_past_24h" not in inspect.getsource(runpy)
    assert "date_posted" not in inspect.getsource(runpy)


def test_run_py_still_runs_main_unchanged():
    import inspect

    import run as runpy

    source = inspect.getsource(runpy.run_main)
    assert 'ROOT / "main.py"' in source
    assert "subprocess.run([sys.executable, str(script), *argv], cwd=str(ROOT))" in source


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))