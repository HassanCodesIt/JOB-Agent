from __future__ import annotations

import pytest

from collector import navigator, safety
from collector.safety import NavigatorError, SecurityChallengeError


class _FakePage:
    url = "https://www.linkedin.com/search/results/all/?keywords=AI"

    def __init__(self):
        self.guards = 0

    def wait_for_selector(self, selector, timeout=None, state=None):
        raise TimeoutError("no results")

    def wait_for_load_state(self, state, timeout=None):
        pass


def test_result_timeout_checks_for_challenge_before_failing(monkeypatch):
    guards = {"count": 0}

    def fake_guard(page, context=""):
        guards["count"] += 1
        raise SecurityChallengeError("Security challenge detected on LinkedIn")

    monkeypatch.setattr(safety, "guard", fake_guard)

    with pytest.raises(SecurityChallengeError):
        navigator._wait_for_results(_FakePage(), require_posts=True)

    assert guards["count"] == 1


def test_posts_gate_accepts_every_container_the_reader_supports():
    from collector.post_reader import POST_SELECTORS

    assert tuple(navigator.POSTS_RESULT_SELECTORS) == tuple(POST_SELECTORS)


def test_non_post_timeout_stays_silent():
    navigator._wait_for_results(_FakePage(), require_posts=False)


class _UrlPage:
    def __init__(self, url):
        self.url = url


def test_search_scope_detects_posts_and_all_verticals():
    assert navigator.search_scope(
        "https://www.linkedin.com/search/results/content/?keywords=AI%20Developer"
    ) == "posts"
    assert navigator.search_scope(
        "https://www.linkedin.com/search/results/posts/?keywords=AI%20Developer"
    ) == "posts"
    assert navigator.search_scope(
        "https://www.linkedin.com/search/results/all/?keywords=AI%20Developer"
    ) == "all"
    assert navigator.search_scope("https://www.linkedin.com/feed/") is None


def test_is_search_for_ignores_case_and_extra_spaces():
    page = _UrlPage(
        "https://www.linkedin.com/search/results/content/?keywords=Generative%20AI%20Engineer"
    )
    assert navigator.is_search_for(page, "generative ai engineer") is True
    assert navigator.is_search_for(page, "LLM Engineer") is False


def test_is_search_for_requires_a_results_url():
    page = _UrlPage("https://www.linkedin.com/feed/")
    assert navigator.is_search_for(page, "AI Developer") is False


class _Keyboard:
    def __init__(self, owner):
        self._owner = owner

    def press(self, key):
        self._owner.pressed.append(key)


class _Recorder:
    """Minimal page double recording search-box interactions."""

    def __init__(self, url="https://www.linkedin.com/feed/"):
        self.url = url
        self.filled = []
        self.pressed = []
        self.typed = []

    def wait_for_timeout(self, ms):
        pass

    @property
    def keyboard(self):
        return _Keyboard(self)

    def wait_for_selector(self, selector, timeout=None, state=None):
        pass

    def wait_for_load_state(self, state, timeout=None):
        pass


class _FakeLocator:
    def __init__(self, owner, result_url=None, result_urls=None):
        self._owner = owner
        self._result_url = result_url
        self._result_urls = list(result_urls or [])

    def wait_for(self, state=None, timeout=None):
        pass

    def count(self):
        return 1

    def is_visible(self):
        return True

    def evaluate(self, script):
        pass

    def fill(self, value):
        self._owner.filled.append(value)

    def press_sequentially(self, value, delay=None):
        self._owner.typed.append(value)

    def click(self, timeout=None):
        self._owner.pressed.append("click")

    def press(self, key):
        self._owner.pressed.append(key)
        if key == "Enter":
            if self._result_urls:
                self._owner.url = self._result_urls.pop(0)
            elif self._result_url:
                self._owner.url = self._result_url


def test_search_role_never_clicks_the_search_input(monkeypatch):
    page = _Recorder("https://www.linkedin.com/feed/")

    monkeypatch.setattr(
        navigator,
        "_first_visible",
        lambda p, s, timeout=6000: _FakeLocator(
            p, "https://www.linkedin.com/search/results/all/?keywords=AI%20Developer&origin=GLOBAL_SEARCH_HEADER"
        ),
    )
    monkeypatch.setattr(navigator, "_wait_for_results", lambda p, timeout=15000, require_posts=False: None)
    monkeypatch.setattr(navigator, "human_delay", lambda p, d: 0)
    monkeypatch.setattr(safety, "guard", lambda p, context="": None)

    class _Cfg:
        action_delay = (0.0, 0.0)
        page_load_delay = (0.0, 0.0)

    navigator.search_role(page, "AI Developer", _Cfg())

    assert page.filled == ["AI Developer"]
    assert page.pressed == ["Enter"]


def test_search_role_retries_with_keystrokes_when_keywords_are_dropped(monkeypatch):
    """LinkedIn sometimes navigates without keywords after a programmatic fill."""
    page = _Recorder("https://www.linkedin.com/feed/")

    monkeypatch.setattr(
        navigator,
        "_first_visible",
        lambda p, s, timeout=6000: _FakeLocator(
            p,
            result_urls=[
                "https://www.linkedin.com/search/results/all/?origin=GLOBAL_SEARCH_HEADER",
                "https://www.linkedin.com/search/results/all/?keywords=AI%20Developer&origin=GLOBAL_SEARCH_HEADER",
            ],
        ),
    )
    monkeypatch.setattr(navigator, "_wait_for_results", lambda p, timeout=15000, require_posts=False: None)
    monkeypatch.setattr(navigator, "human_delay", lambda p, d: 0)
    monkeypatch.setattr(safety, "guard", lambda p, context="": None)

    class _Cfg:
        action_delay = (0.0, 0.0)
        page_load_delay = (0.0, 0.0)

    navigator.search_role(page, "AI Developer", _Cfg())

    assert page.filled == ["AI Developer"]
    assert page.typed == ["AI Developer"]
    assert page.pressed.count("Enter") == 2
    assert "keywords=AI%20Developer" in page.url


def test_search_role_gives_up_after_repeated_empty_submissions(monkeypatch):
    page = _Recorder("https://www.linkedin.com/feed/")

    monkeypatch.setattr(
        navigator,
        "_first_visible",
        lambda p, s, timeout=6000: _FakeLocator(
            p,
            result_url="https://www.linkedin.com/search/results/all/?origin=GLOBAL_SEARCH_HEADER",
        ),
    )
    monkeypatch.setattr(navigator, "human_delay", lambda p, d: 0)
    monkeypatch.setattr(safety, "guard", lambda p, context="": None)

    class _Cfg:
        action_delay = (0.0, 0.0)
        page_load_delay = (0.0, 0.0)

    with pytest.raises(NavigatorError):
        navigator.search_role(page, "AI Developer", _Cfg())

    assert page.pressed.count("Enter") == 3


def test_search_role_reuses_matching_results_without_typing(monkeypatch):
    page = _Recorder(
        "https://www.linkedin.com/search/results/content/?keywords=LLM%20Engineer&origin=SWITCH_SEARCH_VERTICAL"
    )
    monkeypatch.setattr(
        navigator, "_first_visible", lambda p, s, timeout=6000: pytest.fail("must not touch the search box")
    )
    monkeypatch.setattr(navigator, "_wait_for_results", lambda p, timeout=15000, require_posts=False: None)
    monkeypatch.setattr(safety, "guard", lambda p, context="": None)

    class _Cfg:
        action_delay = (0.0, 0.0)
        page_load_delay = (0.0, 0.0)

    navigator.search_role(page, "LLM Engineer", _Cfg())

    assert page.filled == []
    assert page.pressed == []


def test_select_posts_filter_reports_diagnostics_when_absent(monkeypatch, capsys):
    class _Page:
        url = "https://www.linkedin.com/search/results/all/?keywords=AI"

        def title(self):
            return "Search | LinkedIn"

        def query_selector_all(self, selector):
            class _Node:
                def inner_text(self_inner):
                    return "Jobs\nPeople\nCompanies"

                def get_attribute(self_inner, name):
                    return "Filter by Jobs"

            return [_Node()]

        def locator(self, selector):
            raise AssertionError("no element should be locatable")

        def get_by_role(self, role, name=None, exact=None):
            class _Empty:
                @property
                def first(self_inner):
                    return self_inner

                def count(self_inner):
                    return 0

                def is_visible(self_inner):
                    return False

            return _Empty()

    monkeypatch.setattr(navigator, "_find_posts_filter", lambda p: None)
    with pytest.raises(safety.NavigatorError):
        navigator.select_posts_filter(_Page(), "AI Developer", None)

    out = capsys.readouterr().out
    assert "Could not find the LinkedIn Posts filter." in out
    assert "Current URL:" in out
    assert "Page title: Search | LinkedIn" in out
    assert "Available search filters:" in out


def test_posts_filter_selector_prefers_the_aria_label_label():
    assert navigator.POSTS_FILTER_SELECTORS[0] == "div[aria-label='Filter by Posts'] label"
    assert "label:text-is('Posts')" in navigator.POSTS_FILTER_SELECTORS


def test_posts_filter_is_active_from_url_or_checkbox():
    page = _UrlPage("https://www.linkedin.com/search/results/content/?keywords=AI")
    assert navigator._posts_filter_is_active(page) is True
    assert navigator._posts_filter_is_active(_UrlPage("https://www.linkedin.com/search/results/all/?keywords=AI")) is False