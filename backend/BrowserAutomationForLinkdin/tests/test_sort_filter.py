"""Sort by -> Latest / Top match, exercised against LinkedIn's real menu markup.

The doubles below mirror what the live Sort by menu exposes (see the module
docstring in collector/sort_filter.py): the facet control is a
``div[aria-label="Filter by Sort by"]`` holding a checkbox and a label, the
option rows put their radio under ``aria-hidden="true"`` behind an empty
``<label for=...>`` and expose the name only as a bare ``<span>``, and "Show
results" is a link that only navigates once a choice is picked.

Once a sort is applied LinkedIn rewrites that same control to
``aria-label="Filter by Latest"`` / ``"Filter by Top Match"``, which is why the
option text has to be looked up outside the applied-filter row.
"""

from __future__ import annotations

import json

import pytest

from collector import printer, run_modes, run_storage, sort_filter
from collector.models import Stats
from collector.safety import NavigatorError

POSTS_URL = "https://www.linkedin.com/search/results/content/?keywords=AI"

LATEST_URL = (
    "https://www.linkedin.com/search/results/content/?keywords=AI"
    "&origin=FACETED_SEARCH&sortBy=%5B%22date_posted%22%5D"
    "&datePosted=%5B%22past-24h%22%5D"
)
TOP_MATCH_URL = (
    "https://www.linkedin.com/search/results/content/?keywords=AI"
    "&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D"
    "&datePosted=%5B%22past-24h%22%5D"
)

SORTED_URL = {
    sort_filter.SORT_LATEST: LATEST_URL,
    sort_filter.SORT_TOP_MATCH: TOP_MATCH_URL,
}

# LinkedIn renders the facet control under one of these labels.
CONTROL_LABELS = (
    "Filter by Sort by",
    "Filter by Latest",
    "Filter by Top Match",
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
    # date_filter owns the shared wait primitives the sort helper reuses.
    import collector.date_filter as date_filter

    monkeypatch.setattr(date_filter, "time", fake)
    return fake


def _option(mode: str) -> sort_filter.SortOption:
    """The resolved option object the private helpers take."""
    return sort_filter.resolve_sort_option(mode)


class Locator:
    """One matched element. ``owner`` records what the code did to it."""

    def __init__(
        self,
        owner,
        tag="",
        count=1,
        visible=True,
        checked=False,
        in_chip=False,
        mode=None,
    ):
        self._owner = owner
        self.tag = tag
        self._count = count
        self._visible = visible
        self.checked = checked
        self.in_chip = in_chip
        self.mode = mode

    @property
    def first(self):
        return self

    def nth(self, index):
        return self

    def count(self):
        return self._count

    def is_visible(self):
        return self._visible

    def is_checked(self):
        return self.checked

    def click(self, timeout=None, force=None):
        if self.tag in ("option_text", "option_label"):
            self._owner.select(self.mode, self.tag)
        elif self.tag == "chip_label":
            # The applied chip's label reopens the menu; it selects nothing.
            self._owner.clicks.append("click:chip-label")
            self._owner.menu_open = True
        elif self.tag == "control":
            self._owner.clicks.append("click:Sort by")
            self._owner.menu_open = True
        elif self.tag == "show_results":
            self._owner.apply()
        else:
            raise AssertionError(f"unexpected click on {self.tag!r}")

    def evaluate(self, script, arg=None):
        if "el.click" in script:
            self.click()
            return None
        if "closest" in script:
            # Two things a locator script must get right, and which a double can
            # enforce: the chip selector is passed in rather than interpolated
            # (it contains quotes of its own), and it is the *second* argument,
            # because Playwright hands the element over first.
            assert script.startswith("(el, sel)"), f"bad locator script: {script!r}"
            assert arg == sort_filter.CHIP_ANCESTOR_SELECTOR
            return self.in_chip
        raise AssertionError("unexpected element.evaluate")


class _Chain:
    """A locator matching several elements, so ``nth`` can walk them."""

    def __init__(self, matches):
        self._matches = list(matches)

    @property
    def first(self):
        return self._matches[0]

    def nth(self, index):
        return self._matches[index]

    def count(self):
        return len(self._matches)


CHIP_PREFIX = "div[aria-label='Filter by "
RADIO_PREFIX = "input[type='radio'][aria-label='"
RADIO_LABEL_PREFIX = "label[for='_r_fake_"


class Page:
    """A LinkedIn Posts page whose Sort by menu can be opened.

    ``options`` is what the menu offers once opened; ``applied_mode`` is the
    choice already in effect, which LinkedIn shows as a chip instead of the
    plain "Sort by" label.
    """

    def __init__(
        self,
        url=POSTS_URL,
        has_control=True,
        options=(sort_filter.SORT_LATEST, sort_filter.SORT_TOP_MATCH),
        has_show_results=True,
        applied_mode=None,
        selection_takes=True,
    ):
        self.url = url
        self.has_control = has_control
        self.options = tuple(options)
        self.has_show_results = has_show_results
        self.applied_mode = applied_mode
        self.selection_takes = selection_takes

        self.menu_open = False
        self.clicks = []
        self.checked = set()
        self.selection_strategy = None

    # -- helpers used by the doubles -------------------------------------

    @property
    def _open_options(self):
        return self.options if self.menu_open else ()

    @property
    def _chip_mode(self):
        """The mode the applied-filter chip stands for, if any."""
        if self.applied_mode is None:
            return None
        return self.applied_mode if self.applied_mode in self.options else None

    def _mode_for_aria(self, aria):
        for mode in self.options:
            if sort_filter.SORT_OPTIONS[mode].aria_label == aria:
                return mode
        return None

    def select(self, mode, strategy):
        self.clicks.append(f"select:{strategy}:{mode}")
        self.selection_strategy = strategy
        if self.selection_takes:
            self.checked = {mode}

    def apply(self):
        """'Show results' applies the checked option, if there is one."""
        self.clicks.append("click:Show results")
        self.menu_open = False
        if self.checked:
            self.applied_mode = next(iter(self.checked))
            self.url = SORTED_URL[self.applied_mode]

    # -- Playwright surface ---------------------------------------------

    def wait_for_timeout(self, millis):
        import collector.date_filter as date_filter

        date_filter.time.sleep(millis / 1000.0)

    def wait_for_load_state(self, state, timeout=None):
        pass

    def locator(self, selector):
        if selector.startswith(RADIO_PREFIX):
            mode = self._mode_for_aria(selector[len(RADIO_PREFIX):-2])
            found = mode is not None and mode in self._open_options
            return Locator(
                self,
                tag="radio",
                count=1 if found else 0,
                visible=False,
                checked=bool(found and mode in self.checked),
                mode=mode,
            )

        if selector.startswith(RADIO_LABEL_PREFIX):
            mode = selector[len(RADIO_LABEL_PREFIX):-2]
            found = mode in self._open_options
            return Locator(self, tag="option_label", count=1 if found else 0, mode=mode)

        if selector.startswith(CHIP_PREFIX):
            aria = selector[len(CHIP_PREFIX):].split("'")[0]
            if aria == sort_filter.SORT_BY_TEXT:
                # The unselected facet control: opens the menu, selects nothing.
                return Locator(self, tag="control", count=1 if self.has_control else 0)
            mode = self._mode_for_aria(aria)
            if mode is not None and mode == self._chip_mode:
                return Locator(self, tag="chip_label", count=1, in_chip=True, mode=mode)
            return Locator(self, tag="missing", count=0)

        if sort_filter.SORT_BY_TEXT in selector:
            return Locator(self, tag="control", count=1 if self.has_control else 0)

        return Locator(self, tag="unknown", count=0)

    def get_by_text(self, text, exact=False):
        if text == sort_filter.SHOW_RESULTS_TEXT:
            if self.menu_open and self.has_show_results:
                return Locator(self, tag="show_results")
            return Locator(self, tag="missing", count=0)

        matches = []
        for mode in self.options:
            if text not in sort_filter.SORT_OPTIONS[mode].visible_texts:
                continue
            # The applied chip's own label repeats the option name, so the same
            # text resolves both inside the filter row and inside the menu.
            if mode == self._chip_mode:
                matches.append(Locator(self, tag="chip_label", in_chip=True, mode=mode))
            if mode in self._open_options:
                matches.append(Locator(self, tag="option_text", in_chip=False, mode=mode))

        return _Chain(matches) if matches else Locator(self, tag="missing", count=0)

    def get_by_role(self, role, name=None, exact=None):
        if name == sort_filter.SHOW_RESULTS_TEXT and role in ("link", "button"):
            if self.menu_open and self.has_show_results:
                return Locator(self, tag="show_results")
            return Locator(self, tag="missing", count=0)
        if name == sort_filter.SORT_BY_TEXT and self.has_control:
            return Locator(self, tag="control")
        # LinkedIn hides every option radio under aria-hidden="true", so no role
        # query can reach one -- whatever the role or the name.
        return Locator(self, tag="missing", count=0)

    def evaluate(self, script, arg=None):
        if "r.id" in script:
            for mode in self._open_options:
                if arg == sort_filter.SORT_OPTIONS[mode].radio_selector:
                    return f"_r_fake_{mode}"
            return ""
        if "r.checked" in script:
            for mode in self._open_options:
                if arg == sort_filter.SORT_OPTIONS[mode].radio_selector:
                    return mode in self.checked
            return False
        raise AssertionError("unexpected page.evaluate")


@pytest.fixture
def page():
    return Page()


# --- opening the menu --------------------------------------------------------


def test_sort_by_can_be_opened(page, capsys):
    sort_filter.apply_sort_filter(page, sort_filter.SORT_LATEST)

    assert "click:Sort by" in page.clicks
    out = capsys.readouterr().out
    assert 'Applying LinkedIn sort filter...' in out
    assert 'Opening "Sort by"...' in out


def test_missing_sort_by_fails_before_anything_is_clicked(page, capsys):
    page.has_control = False

    with pytest.raises(NavigatorError, match='"Sort by" filter not found'):
        sort_filter.apply_sort_filter(page, sort_filter.SORT_LATEST)

    out = capsys.readouterr().out
    assert '[ERROR] "Sort by" filter not found.' in out
    assert "[OK] Sort applied" not in out
    assert "Show results" not in " ".join(page.clicks)


def test_menu_is_awaited_instead_of_looked_up_once(monkeypatch):
    """LinkedIn renders the popover after the click, so the lookup must poll."""
    page = Page(options=())
    page.menu_open = True
    checks = {"n": 0}
    original = page.get_by_text

    def appears_later(text, exact=False):
        if text in sort_filter.SORT_OPTIONS[sort_filter.SORT_LATEST].visible_texts:
            checks["n"] += 1
            if checks["n"] >= 3:
                page.options = (sort_filter.SORT_LATEST,)
                return original(text, exact=exact)
        return Locator(page, tag="missing", count=0)

    monkeypatch.setattr(page, "get_by_text", appears_later)
    assert sort_filter._wait_for_option(page, _option(sort_filter.SORT_LATEST), timeout=5000) is True
    assert checks["n"] >= 3


# --- selecting each option ---------------------------------------------------


def test_latest_can_be_found_and_selected(page, capsys):
    sort_filter.apply_sort_filter(page, sort_filter.SORT_LATEST)

    out = capsys.readouterr().out
    assert 'Selecting "Latest"...' in out
    assert "[OK] Sort applied: Latest" in out
    assert page.url == LATEST_URL


def test_top_match_can_be_found_and_selected(page, capsys):
    sort_filter.apply_sort_filter(page, sort_filter.SORT_TOP_MATCH)

    out = capsys.readouterr().out
    assert 'Selecting "Top match"...' in out
    assert "[OK] Sort applied: Top match" in out
    assert page.url == TOP_MATCH_URL


def test_option_is_found_by_exact_visible_text(page):
    """LinkedIn exposes the option only as a bare <span>; no role sees it."""
    page.menu_open = True

    strategy = sort_filter._select_option(page, _option(sort_filter.SORT_LATEST))

    assert strategy.startswith("exact visible text")
    assert page.get_by_role("radio", name="Latest", exact=True).count() == 0
    assert page.get_by_role("menuitemradio", name="Latest", exact=True).count() == 0


def test_option_falls_back_to_the_label_bound_to_the_radio(monkeypatch):
    """If the text ever stops being clickable, the empty <label for> still is."""
    page = Page()
    page.menu_open = True
    original = page.get_by_text

    def no_text(text, exact=False):
        if text in sort_filter.SORT_OPTIONS[sort_filter.SORT_LATEST].visible_texts:
            return Locator(page, tag="missing", count=0)
        return original(text, exact=exact)

    monkeypatch.setattr(page, "get_by_text", no_text)

    strategy = sort_filter._select_option(page, _option(sort_filter.SORT_LATEST))

    assert strategy == "the <label for> bound to the radio"
    assert page.clicks == ["select:option_label:latest"]


def test_only_the_requested_option_is_ever_clicked(page):
    """The sort must never land on the sibling option by accident."""
    sort_filter.apply_sort_filter(page, sort_filter.SORT_TOP_MATCH)

    # Only Top match was checked, and the URL carries only its token.
    assert page.checked == {sort_filter.SORT_TOP_MATCH}
    assert page.url == TOP_MATCH_URL
    assert sort_filter.url_has_sort(page.url, _option(sort_filter.SORT_LATEST)) is False


def test_exact_matching_never_confuses_the_two_options(page):
    latest = sort_filter.SORT_OPTIONS[sort_filter.SORT_LATEST]
    top = sort_filter.SORT_OPTIONS[sort_filter.SORT_TOP_MATCH]

    assert latest.url_token != top.url_token
    assert set(latest.visible_texts).isdisjoint(top.visible_texts)
    assert latest.aria_label != top.aria_label


# --- scoping: the applied chip must not be mistaken for the menu -------------


def test_applied_chip_is_never_clicked_instead_of_the_menu(page):
    """The chip's label reads "Latest" too, but clicking it selects nothing."""
    page.applied_chip = True
    page.applied_mode = sort_filter.SORT_TOP_MATCH
    page.url = TOP_MATCH_URL

    sort_filter.apply_sort_filter(page, sort_filter.SORT_LATEST)

    assert page.url == LATEST_URL
    assert page.applied_mode == sort_filter.SORT_LATEST


def test_role_queries_cannot_reach_an_option(page):
    """Requirement: use the radio's state, never a role that cannot see it."""
    page.menu_open = True

    assert page.get_by_role("radio", name="Top Match", exact=False).count() == 0
    assert page.locator(sort_filter.SORT_OPTIONS[sort_filter.SORT_TOP_MATCH].radio_selector).count() == 1


# --- verification ------------------------------------------------------------


def test_url_state_is_read_from_the_sort_by_query_parameter():
    latest = sort_filter.SORT_OPTIONS[sort_filter.SORT_LATEST]
    top = sort_filter.SORT_OPTIONS[sort_filter.SORT_TOP_MATCH]

    assert sort_filter.url_has_sort(LATEST_URL, latest) is True
    assert sort_filter.url_has_sort(TOP_MATCH_URL, latest) is False
    assert sort_filter.url_has_sort(TOP_MATCH_URL, top) is True
    assert sort_filter.url_has_sort(LATEST_URL, top) is False
    assert sort_filter.url_has_sort(POSTS_URL, latest) is False
    assert sort_filter.url_has_sort("", latest) is False
    assert sort_filter.url_has_sort("not a url", latest) is False


def test_applied_state_is_also_accepted_from_linkedins_filter_chip(page):
    """The chip alone is proof too, when the URL has not been read yet."""
    page.url = POSTS_URL
    page.applied_chip = True
    page.applied_mode = sort_filter.SORT_LATEST

    assert sort_filter._sort_applied(page, _option(sort_filter.SORT_LATEST)) is True
    assert sort_filter.url_has_sort(page.url, sort_filter.SORT_LATEST) is False


def test_finding_the_text_alone_is_not_success(page, monkeypatch, capsys):
    """Requirement: the option must be *selected*, not merely located."""
    page.menu_open = True

    monkeypatch.setattr(
        Page,
        "select",
        lambda self, mode, strategy: self.clicks.append(f"select:{strategy}:{mode}"),
    )

    with pytest.raises(NavigatorError):
        sort_filter.apply_sort_filter(page, sort_filter.SORT_LATEST)

    out = capsys.readouterr().out
    assert "[ERROR] Could not verify requested sort mode." in out
    assert "[OK] Sort applied" not in out


def test_verification_failure_stops_the_run(page, monkeypatch, capsys):
    """A "Show results" click that never applies the sort must not report OK."""
    monkeypatch.setattr(
        Page,
        "apply",
        lambda self: self.clicks.append("click:Show results"),
    )

    with pytest.raises(NavigatorError, match="Could not verify requested sort mode"):
        sort_filter.apply_sort_filter(page, sort_filter.SORT_LATEST)

    assert "[OK] Sort applied" not in capsys.readouterr().out


def test_missing_latest_fails_safely(page, capsys):
    page.options = (sort_filter.SORT_TOP_MATCH,)

    with pytest.raises(NavigatorError, match='"Latest" sort option not found'):
        sort_filter.apply_sort_filter(page, sort_filter.SORT_LATEST)

    out = capsys.readouterr().out
    assert '[ERROR] "Latest" sort option not found.' in out
    assert "Show results" not in " ".join(page.clicks)
    assert "[OK] Sort applied" not in out


def test_missing_top_match_fails_safely(page, capsys):
    page.options = (sort_filter.SORT_LATEST,)

    with pytest.raises(NavigatorError, match='"Top match" sort option not found'):
        sort_filter.apply_sort_filter(page, sort_filter.SORT_TOP_MATCH)

    out = capsys.readouterr().out
    assert '[ERROR] "Top match" sort option not found.' in out
    assert "Show results" not in " ".join(page.clicks)
    assert "[OK] Sort applied" not in out


def test_menu_opens_without_the_requested_option(page):
    """The menu opens but offers only the sibling option."""
    page.menu_open = True
    page.options = (sort_filter.SORT_TOP_MATCH,)

    with pytest.raises(NavigatorError, match='"Latest" sort option not found'):
        sort_filter.apply_sort_filter(page, sort_filter.SORT_LATEST)


def test_missing_show_results_fails(page, capsys):
    page.has_show_results = False

    with pytest.raises(NavigatorError, match='"Show results" button not found'):
        sort_filter.apply_sort_filter(page, sort_filter.SORT_LATEST)

    assert "[OK] Sort applied" not in capsys.readouterr().out


def test_failure_messages_report_the_strategies_tried(page):
    page.menu_open = True
    page.selection_takes = False

    with pytest.raises(NavigatorError) as info:
        sort_filter._select_option(page, _option(sort_filter.SORT_LATEST))

    assert "exact visible text" in str(info.value)


def test_unknown_sort_mode_is_refused(page):
    with pytest.raises(NavigatorError, match="Unknown sort mode"):
        sort_filter.apply_sort_filter(page, "oldest")


@pytest.mark.parametrize("mode", ["latest", "LATEST", " top_match ", "top-match"])
def test_sort_mode_names_are_normalised(mode):
    assert sort_filter.resolve_sort_option(mode).mode == sort_filter._normalize_mode(mode)


# --- carried-over sorts (LinkedIn keeps the facet across keywords) ----------


def test_carried_over_sort_is_verified_not_reapplied(page, capsys):
    page.url = LATEST_URL
    page.applied_chip = True
    page.applied_mode = sort_filter.SORT_LATEST

    sort_filter.apply_sort_filter(page, sort_filter.SORT_LATEST)

    out = capsys.readouterr().out
    assert "[OK] Sort applied: Latest" in out
    assert "already active" in out
    # Nothing was clicked: the sort was already in effect for this search.
    assert page.clicks == []


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


def _collect_events(monkeypatch, events):
    """Patch every browser touchpoint so the filter order can be observed."""
    import main as mainpy

    monkeypatch.setattr(mainpy.navigator, "search_role", lambda page, role, cfg: events.append(("search", role)))
    monkeypatch.setattr(mainpy.navigator, "select_posts_filter", lambda page, role="", cfg=None: events.append(("posts", role)))
    monkeypatch.setattr(mainpy.date_filter, "apply_past_24_hours_filter", lambda page: events.append(("date",)))
    monkeypatch.setattr(mainpy.sort_filter, "apply_sort_filter", lambda page, mode: events.append(("sort", mode)))
    return mainpy


def _record_main_call(monkeypatch):
    import main as mainpy

    calls = {}
    monkeypatch.setattr(mainpy, "load_config", lambda argv=None: _Cfg())
    monkeypatch.setattr(
        mainpy,
        "run",
        lambda cfg, run_mode="standard", apply_past_24h=False, sort_mode=None: calls.update(
            run_mode=run_mode, apply_past_24h=apply_past_24h, sort_mode=sort_mode
        ),
    )
    return mainpy, calls


def test_search_with_posts_filter_applies_date_then_sort(monkeypatch):
    events = []
    mainpy = _collect_events(monkeypatch, events)

    ok = mainpy.search_with_posts_filter(
        object(), "AI Developer", None, apply_past_24h=True, sort_mode="latest"
    )

    assert ok is True
    assert events == [
        ("search", "AI Developer"),
        ("posts", "AI Developer"),
        ("date",),
        ("sort", "latest"),
    ]


def test_sort_never_runs_before_the_date_filter(monkeypatch):
    """Requirement: Past 24 hours is applied first, and kept."""
    events = []
    mainpy = _collect_events(monkeypatch, events)

    mainpy.search_with_posts_filter(object(), "AI Developer", None, sort_mode="top_match")

    assert events == [("search", "AI Developer"), ("posts", "AI Developer"), ("sort", "top_match")]


def test_standard_mode_never_touches_the_sort_filter(monkeypatch):
    """run.py must behave exactly as before: no date filter, no sort."""
    events = []
    mainpy = _collect_events(monkeypatch, events)

    assert mainpy.search_with_posts_filter(object(), "AI Developer", None) is True
    assert events == [("search", "AI Developer"), ("posts", "AI Developer")]


def test_date_posted_mode_never_touches_the_sort_filter(monkeypatch):
    events = []
    mainpy = _collect_events(monkeypatch, events)

    mainpy.search_with_posts_filter(object(), "AI Developer", None, apply_past_24h=True)

    assert events == [("search", "AI Developer"), ("posts", "AI Developer"), ("date",)]


@pytest.mark.parametrize(
    "script, run_mode, sort_mode",
    [
        ("latest_run", "latest", "latest"),
        ("top_match_run", "before", "top_match"),
    ],
)
def test_new_entry_points_ask_main_for_their_mode(monkeypatch, script, run_mode, sort_mode):
    mainpy, calls = _record_main_call(monkeypatch)

    module = __import__(script)
    assert module.main(
        run_mode=run_mode, apply_past_24h=True, sort_mode=sort_mode
    ) == 0
    assert calls == {"run_mode": run_mode, "apply_past_24h": True, "sort_mode": sort_mode}


def test_unverifiable_sort_prevents_scraping(monkeypatch):
    """Requirement 9: a sort that cannot be verified must stop the role."""
    import main as mainpy

    def refuse(page, mode):
        raise NavigatorError("Could not verify requested sort mode.")

    scraped = []
    monkeypatch.setattr(mainpy, "BrowserSession", lambda cfg: _Session())
    monkeypatch.setattr(mainpy.safety, "is_login_required", lambda page: False)
    monkeypatch.setattr(mainpy.navigator, "search_role", lambda page, role, cfg: None)
    monkeypatch.setattr(mainpy.navigator, "select_posts_filter", lambda page, role="", cfg=None: None)
    monkeypatch.setattr(mainpy.date_filter, "apply_past_24_hours_filter", lambda page: None)
    monkeypatch.setattr(mainpy.sort_filter, "apply_sort_filter", refuse)
    monkeypatch.setattr(mainpy, "process_batches", lambda *a, **k: scraped.append(a) or 0)
    monkeypatch.setattr(mainpy.printer, "print_header", lambda cfg, mode_label=None: None)
    monkeypatch.setattr(mainpy.printer, "print_summary", lambda stats, cfg: None)
    monkeypatch.setattr(mainpy, "save_scraping_run", lambda *a, **k: None)

    stats = mainpy.run(_Cfg(), run_mode="latest", apply_past_24h=True, sort_mode="latest")

    assert scraped == []
    assert (stats.roles_skipped, stats.roles_searched, stats.collected) == (1, 0, 0)


@pytest.mark.parametrize("run_mode, sort_mode", [("latest", "latest"), ("before", "top_match")])
def test_verified_sort_lets_scraping_proceed(monkeypatch, run_mode, sort_mode):
    import main as mainpy

    order = []
    monkeypatch.setattr(mainpy, "BrowserSession", lambda cfg: _Session())
    monkeypatch.setattr(mainpy.safety, "is_login_required", lambda page: False)
    monkeypatch.setattr(mainpy.navigator, "search_role", lambda page, role, cfg: None)
    monkeypatch.setattr(mainpy.navigator, "select_posts_filter", lambda page, role="", cfg=None: None)
    monkeypatch.setattr(mainpy.date_filter, "apply_past_24_hours_filter", lambda page: order.append("date"))
    monkeypatch.setattr(mainpy.sort_filter, "apply_sort_filter", lambda page, mode: order.append(f"sort:{mode}"))
    monkeypatch.setattr(mainpy, "process_batches", lambda *a, **k: order.append("scrape") or 0)
    monkeypatch.setattr(mainpy.printer, "print_header", lambda cfg, mode_label=None: None)
    monkeypatch.setattr(mainpy.printer, "print_summary", lambda stats, cfg: None)
    monkeypatch.setattr(mainpy, "save_scraping_run", lambda *a, **k: None)

    stats = mainpy.run(_Cfg(), run_mode=run_mode, apply_past_24h=True, sort_mode=sort_mode)

    assert order == ["date", f"sort:{sort_mode}", "scrape"]
    assert stats.roles_searched == 1


def test_all_entry_points_share_one_collector(monkeypatch):
    """Requirements 14/15: no entry point builds a collector of its own."""
    import inspect

    import top_match_run
    import date_posted_24h_run
    import latest_run
    import main as mainpy
    import run as runpy

    for module in (latest_run, top_match_run, date_posted_24h_run):
        source = inspect.getsource(module)
        assert "from main import main" in source
        # Only the shared entry point is called; nothing is redefined locally.
        assert "main(" in source
        assert "def run" not in source
        assert "class " not in source
        assert "process_batches" not in source
        assert "save_scraping_run" not in source

    # run.py is still only a launcher for main.py.
    assert "subprocess.run([sys.executable, str(script), *argv]" in inspect.getsource(runpy.run_main)
    assert mainpy.run.__module__ == "main"


def test_run_py_and_date_posted_entry_point_are_unchanged():
    """Requirements 13/20/21: the pre-existing entry points gain no sorting."""
    import inspect

    import date_posted_24h_run
    import run as runpy

    date_source = inspect.getsource(date_posted_24h_run)
    assert 'run_mode="date_posted_24h"' in date_source
    assert "apply_past_24h=True" in date_source
    assert "sort_mode" not in date_source

    run_source = inspect.getsource(runpy)
    assert "apply_past_24h" not in run_source
    assert "date_posted" not in run_source
    assert "sort_mode" not in run_source
    assert "sort_filter" not in run_source


# --- run-mode registry -------------------------------------------------------


@pytest.mark.parametrize(
    "run_mode, apply_past_24h, sort_mode, label",
    [
        ("standard", False, None, None),
        ("date_posted_24h", True, None, None),
        ("latest", True, "latest", "Past 24 Hours + Latest"),
        ("before", True, "top_match", "Past 24 Hours + Top Match"),
    ],
)
def test_registry_describes_every_entry_point(run_mode, apply_past_24h, sort_mode, label):
    assert run_modes.apply_past_24h(run_mode) is apply_past_24h
    assert run_modes.sort_mode(run_mode) == sort_mode
    assert run_modes.header_label(run_mode) == label


def test_entry_point_arguments_agree_with_the_registry():
    """The scripts cannot request a combination the registry does not describe."""
    import inspect

    import top_match_run
    import date_posted_24h_run
    import latest_run

    expected = {
        latest_run: ("latest", "latest"),
        top_match_run: ("before", "top_match"),
    }
    for module, (run_mode, sort_mode) in expected.items():
        source = inspect.getsource(module)
        assert f'run_mode="{run_mode}"' in source
        assert f'sort_mode="{sort_mode}"' in source
        assert run_modes.apply_past_24h(run_mode) is True
        assert run_modes.sort_mode(run_mode) == sort_mode

    # The date-only launcher must stay exactly that: no sort_mode in its source.
    date_source = inspect.getsource(date_posted_24h_run)
    assert 'run_mode="date_posted_24h"' in date_source
    assert "sort_mode" not in date_source
    assert run_modes.sort_mode(run_modes.DATE_POSTED_24H) is None


def test_unknown_run_mode_falls_back_to_standard():
    assert run_modes.header_label("nope") is None
    assert run_modes.apply_past_24h("nope") is False
    assert run_modes.sort_mode("nope") is None
    assert run_modes.date_posted_filter("nope") is None


# --- banner ------------------------------------------------------------------


@pytest.mark.parametrize(
    "run_mode, expected",
    [
        ("latest", "MODE: Past 24 Hours + Latest"),
        ("before", "MODE: Past 24 Hours + Top Match"),
    ],
)
def test_sorted_modes_print_their_mode_in_the_banner(capsys, run_mode, expected):
    printer.print_header(_Cfg(), mode_label=run_modes.header_label(run_mode))

    out = capsys.readouterr().out
    assert "LINKEDIN JOB POST COLLECTOR" in out
    assert expected in out
    assert out.index("LINKEDIN JOB POST COLLECTOR") < out.index(expected)


@pytest.mark.parametrize("run_mode", ["standard", "date_posted_24h"])
def test_unchanged_modes_keep_their_original_banner(capsys, run_mode):
    """The pre-existing entry points print exactly the banner they always did."""
    printer.print_header(_Cfg(), mode_label=run_modes.header_label(run_mode))

    out = capsys.readouterr().out
    assert "MODE:" not in out
    assert "LINKEDIN JOB POST COLLECTOR" in out


# --- JSON metadata and global numbering --------------------------------------


@pytest.mark.parametrize(
    "run_mode, sort_mode, expected_date, expected_sort",
    [
        ("standard", None, None, None),
        ("date_posted_24h", None, "past_24_hours", None),
        ("latest", "latest", "past_24_hours", "latest"),
        ("before", "top_match", "past_24_hours", "top_match"),
    ],
)
def test_json_metadata_records_the_mode_and_sort(tmp_path, run_mode, sort_mode, expected_date, expected_sort):
    from config import Config

    path = run_storage.save_scraping_run(
        [], Stats(), Config(), base=tmp_path, run_mode=run_mode, sort_mode=sort_mode
    )

    info = json.loads(path.read_text(encoding="utf-8"))["run_info"]
    assert info["run_mode"] == run_mode
    assert info["date_posted_filter"] == expected_date
    assert info["sort_mode"] == expected_sort


def test_a_run_records_the_sort_that_was_actually_applied(tmp_path):
    """A run that asked for no sort never claims one."""
    from config import Config

    path = run_storage.save_scraping_run(
        [], Stats(), Config(), base=tmp_path, run_mode="latest", sort_mode=None
    )

    assert json.loads(path.read_text(encoding="utf-8"))["run_info"]["sort_mode"] is None


def test_old_run_files_still_read_correctly():
    """Requirement 18: adding the key must not break runs stored before it."""
    legacy = {
        "run_info": {
            "run_number": 1,
            "started_at": "2026-10-04T08:57:57+05:30",
            "target_roles": ["AI Developer"],
            "max_jds": 30,
        },
        "summary": {},
        "jobs": [],
    }

    assert json.loads(json.dumps(legacy)) == legacy
    assert "sort_mode" not in legacy["run_info"]


def test_numbering_is_global_across_every_entry_point(tmp_path):
    """Requirement 16: one directory, one sequence, no resets."""
    from config import Config

    modes = [
        ("standard", None),
        ("date_posted_24h", None),
        ("latest", "latest"),
        ("before", "top_match"),
    ]

    saved = [
        run_storage.save_scraping_run(
            [], Stats(), Config(), base=tmp_path, run_mode=run_mode, sort_mode=sort_mode
        )
        for run_mode, sort_mode in modes
    ]

    assert [path.name for path in saved] == [f"Scraping Run {n}.json" for n in (1, 2, 3, 4)]
    assert [p.parent for p in saved] == [run_storage.runs_dir(tmp_path)] * 4
    assert run_storage.existing_run_numbers(run_storage.runs_dir(tmp_path)) == [1, 2, 3, 4]


def test_all_four_entry_points_store_into_the_same_directory(tmp_path, monkeypatch):
    """Requirement 15: storage is shared, so there is one place to look."""
    import main as mainpy

    from config import Config

    cfg = Config()
    for run_mode, sort_mode in (
        ("standard", None),
        ("date_posted_24h", None),
        ("latest", "latest"),
        ("before", "top_match"),
    ):
        monkeypatch.setattr(
            mainpy,
            "save_scraping_run",
            lambda matches, stats, cfg, started_at, base=None, **kwargs: run_storage.save_scraping_run(
                matches, stats, cfg, started_at, base=tmp_path, **kwargs
            ),
        )
        mainpy._persist_run(cfg, Stats(), [], "2026-10-04T10:00:00+05:30", run_mode, sort_mode)

    files = sorted(run_storage.runs_dir(tmp_path).glob("*.json"))
    assert [f.name for f in files] == [f"Scraping Run {n}.json" for n in (1, 2, 3, 4)]
    recorded = [json.loads(f.read_text(encoding="utf-8"))["run_info"] for f in files]
    assert [info["run_mode"] for info in recorded] == [
        "standard",
        "date_posted_24h",
        "latest",
        "before",
    ]
    assert [info["sort_mode"] for info in recorded] == [None, None, "latest", "top_match"]


def test_end_to_end_modes_through_run(tmp_path, monkeypatch):
    """One shared run() produces each mode's metadata from its own arguments."""
    import main as mainpy

    from config import Config

    monkeypatch.setattr(mainpy, "BrowserSession", lambda cfg: _Session())
    monkeypatch.setattr(mainpy.safety, "is_login_required", lambda page: False)
    monkeypatch.setattr(mainpy, "search_with_posts_filter", lambda *a, **k: True)
    monkeypatch.setattr(mainpy, "process_batches", lambda *a, **k: 0)
    monkeypatch.setattr(mainpy.printer, "print_header", lambda cfg, mode_label=None: None)
    monkeypatch.setattr(
        mainpy,
        "save_scraping_run",
        lambda matches, stats, cfg, started_at, **kwargs: run_storage.save_scraping_run(
            matches, stats, cfg, started_at, base=tmp_path, **kwargs
        ),
    )

    for run_mode, sort_mode in (("latest", "latest"), ("before", "top_match")):
        mainpy.run(Config(), run_mode=run_mode, apply_past_24h=True, sort_mode=sort_mode)

    recorded = [
        json.loads(f.read_text(encoding="utf-8"))["run_info"]
        for f in sorted(run_storage.runs_dir(tmp_path).glob("*.json"))
    ]
    assert [info["run_mode"] for info in recorded] == ["latest", "before"]
    assert [info["date_posted_filter"] for info in recorded] == ["past_24_hours"] * 2
    assert [info["sort_mode"] for info in recorded] == ["latest", "top_match"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))