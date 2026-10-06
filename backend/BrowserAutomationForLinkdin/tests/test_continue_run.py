"""Tests for the continuation entry point (continue_run.py).

A continuation attaches to the LinkedIn page a previous run left behind and
keeps scrolling downwards from the current position: no navigation, no reload,
no filter/search reset, no new browser context -- and no JD that an earlier run
already collected.
"""

from __future__ import annotations

import inspect
import json
import runpy
from pathlib import Path
from typing import List

import pytest

import continue_run
from collector import continuation, run_modes, run_storage, scroller
from collector.dedupe import Deduplicator, canonical_url
from collector.models import JobMatch, Post, RoleMatchResult, Stats
from config import Config

ROOT = Path(__file__).resolve().parent.parent

FEED_URL = "https://www.linkedin.com/feed/"
SEARCH_URL = (
    "https://www.linkedin.com/search/results/content/"
    "?keywords=Generative%20AI%20Engineer"
    "&datePosted=%5B%22past-24h%22%5D&sortBy=%5B%22relevance%22%5D"
)

JOB_TEXT = (
    "We are hiring a Generative AI Engineer (opening #{index}).\n"
    "Company: Acme AI\nLocation: Bengaluru\nExperience: 3-5 years\n"
    "Skills:\n- Python\n- LLM orchestration\n"
    "Responsibilities:\n- Build agentic systems\n"
    "Requirements:\n- RAG pipelines\n"
    "Apply: send your resume to jobs{index}@acme-ai.com"
)


def post_url(index: int) -> str:
    return f"https://www.linkedin.com/feed/update/urn:li:activity:790000000000000000{index}/"


def job_post(index: int, url: str = "") -> Post:
    return Post(
        author=f"Recruiter {index}",
        text=JOB_TEXT.format(index=index),
        url=url or post_url(index),
    )


def job_match(post: Post) -> JobMatch:
    return JobMatch(
        post=post,
        role_match=RoleMatchResult(
            target_role="Generative AI Engineer",
            matched_variations=["genai engineer"],
            categories=["Generative AI Engineer"],
        ),
        role="Generative AI Engineer",
        company="Acme AI",
        emails=["jobs1@acme-ai.com"],
        methods=["Email"],
        reasons=["Target role matched: Generative AI Engineer"],
    )


class _NoElements:
    def count(self):
        return 0

    def nth(self, index):
        raise AssertionError("no locator children are expected in these tests")


class _Element:
    def __init__(self, key: str, y: float = 100.0, height: float = 300.0):
        self._key = key
        self._y = y
        self._height = height

    def get_attribute(self, name):
        return self._key if name == "data-id" else None

    def bounding_box(self):
        return {"x": 0.0, "y": self._y, "width": 600.0, "height": self._height}

    def is_visible(self):
        return False


class _Page:
    """A page double that records every navigation and scroll it is asked to do."""

    def __init__(self, url: str = SEARCH_URL, scroll_y: int = 1500, elements=()):
        self.url = url
        self.scroll_y = scroll_y
        self.scroll_height = 8000
        self.viewport_height = 900
        self.elements: List[_Element] = list(elements)
        self.mouse = self
        self.context = None
        self.navigations: List[tuple] = []
        self.scrolled: List[int] = []
        self.evaluated: List[str] = []
        self.timeouts: List[int] = []

    def goto(self, url, **kwargs):
        self.navigations.append(("goto", url))
        self.url = url

    def reload(self, **kwargs):
        self.navigations.append(("reload", None))

    def go_back(self, **kwargs):
        self.navigations.append(("go_back", None))

    def go_forward(self, **kwargs):
        self.navigations.append(("go_forward", None))

    def query_selector_all(self, selector):
        return list(self.elements)

    def locator(self, selector):
        return _NoElements()

    def wheel(self, x, y):
        self.scrolled.append(y)

    def evaluate(self, script, *args):
        self.evaluated.append(script)
        if "window.scrollBy" in script:
            self.scrolled.append(args[0] if args else 0)
            return None
        if "scrollY" in script:
            return self.scroll_y
        if "scrollHeight" in script:
            return self.scroll_height
        if "innerHeight" in script:
            return self.viewport_height
        return ""

    def wait_for_function(self, *args, **kwargs):
        return None

    def wait_for_timeout(self, ms):
        self.timeouts.append(ms)


class _Session:
    def __init__(self, page):
        self.page = page
        self.context = type("Context", (), {"pages": [page]})()
        self.connect_kwargs = None
        self.disconnects = 0

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs
        return self.page

    def page_title(self):
        return "Search | LinkedIn"

    def human_delay(self, kind="action"):
        return None

    def disconnect(self):
        self.disconnects += 1


class _Cfg:
    dry_run = False
    target_roles = ["Generative AI Engineer"]
    max_jds = 10
    max_posts = 50
    max_scrolls = 2
    min_jd_signals = 2
    empty_scroll_limit = 2
    color = False
    quiet = False
    action_delay = (0.0, 0.0)
    page_load_delay = (0.0, 0.0)
    linkedin_feed_url = FEED_URL
    post_url_menu_fallback = False

    def delay_for(self, name):
        return (0.0, 0.0)


def _cfg(**overrides) -> Config:
    base = dict(
        action_delay=(0.0, 0.0),
        page_load_delay=(0.0, 0.0),
        max_scrolls=2,
        max_posts=50,
        max_jds=10,
        empty_scroll_limit=2,
        post_url_menu_fallback=False,
    )
    base.update(overrides)
    return Config(**base)


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


def _wire(monkeypatch, page, tmp_path, posts_by_key=None, spy=None):
    """Attach a fake session and storage; seeding is read from tmp_path only."""
    import main as mainpy

    session = _Session(page)
    monkeypatch.setattr(mainpy, "BrowserSession", lambda cfg: session)
    monkeypatch.setattr(mainpy.safety, "is_login_required", lambda p: False)
    monkeypatch.setattr(
        mainpy,
        "save_scraping_run",
        lambda matches, stats, cfg, started_at, **kwargs: run_storage.save_scraping_run(
            matches, stats, cfg, started_at, base=tmp_path, **kwargs
        ),
    )
    monkeypatch.setattr(
        mainpy,
        "seed_deduper",
        lambda deduper: continuation.seed_deduper(deduper, base=tmp_path),
    )
    if posts_by_key is not None:
        monkeypatch.setattr(
            mainpy.scroller,
            "read_post",
            lambda element: posts_by_key.get(element.get_attribute("data-id")),
        )
    if spy is not None:
        real = mainpy.process_batches

        def spy_batches(*args, **kwargs):
            spy.append(kwargs.get("start_from_current_view", False))
            return real(*args, **kwargs)

        monkeypatch.setattr(mainpy, "process_batches", spy_batches)
    return mainpy, session


def _write_previous_run(directory, number: int, urls, run_mode: str = "standard") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_info": {"run_number": number, "run_mode": run_mode},
        "summary": {},
        "jobs": [{"linkedin_post_url": url} for url in urls],
    }
    path = directory / run_storage.run_file_name(number)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _runs(tmp_path) -> List[Path]:
    return sorted(run_storage.runs_dir(tmp_path).glob("*.json"))


# --- the entry point ---------------------------------------------------------


def test_continue_run_only_asks_main_for_the_continuation_mode(monkeypatch):
    _, calls = _record_main_call(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(ROOT / "continue_run.py"), run_name="__main__")

    assert exc.value.code == 0
    assert calls == {"run_mode": "continue", "apply_past_24h": False, "sort_mode": None}


def test_continue_run_is_only_an_entry_point():
    source = inspect.getsource(continue_run)

    assert "from main import main" in source
    assert 'run_mode="continue"' in source
    assert "def run" not in source
    assert "class " not in source
    assert "process_batches" not in source
    assert "save_scraping_run" not in source
    assert "goto" not in source
    assert "reload" not in source
    assert "search_with_posts_filter" not in source


def test_registry_describes_the_continuation_mode():
    assert run_modes.flow(run_modes.CONTINUE) == "continue"
    assert run_modes.header_label("continue") is not None
    assert run_modes.apply_past_24h("continue") is False
    assert run_modes.sort_mode("continue") is None
    assert run_modes.date_posted_filter("continue") is None


# --- attaching and inspecting the current page -------------------------------


def test_continue_attaches_to_the_open_session_without_navigating(monkeypatch, tmp_path, capsys):
    page = _Page()
    mainpy, session = _wire(monkeypatch, page, tmp_path)

    mainpy.run(_cfg(max_scrolls=1), run_mode="continue")

    assert session.connect_kwargs == {"require_linkedin": True}
    assert session.disconnects == 1
    assert page.navigations == []
    assert page.url == SEARCH_URL
    assert page.scrolled and all(distance > 0 for distance in page.scrolled)
    assert not any("scrollTo" in script for script in page.evaluated)

    out = capsys.readouterr().out
    assert "MODE: Continue From Current Page" in out
    assert "no reload, no new search" in out
    assert "1500px" in out


def test_continue_reads_the_current_scroll_position():
    state = continuation.current_scroll_state(_Page())

    assert state.scroll_y == 1500
    assert state.scroll_height == 8000
    assert state.viewport_height == 900
    assert state.kind == "search"
    assert state.kind_label == "search results"


def test_continue_refuses_a_page_that_is_not_linkedin():
    from collector.continuation import ContinuationError

    with pytest.raises(ContinuationError) as exc:
        continuation.current_scroll_state(_Page(url="https://example.com/dashboard"))

    assert "no LinkedIn page to continue from" in str(exc.value)


def test_continue_never_touches_filters_search_or_sort(monkeypatch, tmp_path, capsys):
    import main as mainpy

    def fail(*args, **kwargs):
        pytest.fail("the continuation must not search or reset any filter")

    monkeypatch.setattr(mainpy, "search_with_posts_filter", fail)
    monkeypatch.setattr(mainpy.navigator, "search_role", fail)
    monkeypatch.setattr(mainpy.navigator, "select_posts_filter", fail)
    monkeypatch.setattr(mainpy.date_filter, "apply_past_24_hours_filter", fail)
    monkeypatch.setattr(mainpy.sort_filter, "apply_sort_filter", fail)

    page = _Page(url=SEARCH_URL)
    _wire(monkeypatch, page, tmp_path)

    mainpy.run(_cfg(max_scrolls=1), run_mode="continue")

    assert page.url == SEARCH_URL
    assert page.navigations == []
    assert "keywords=Generative" in page.url
    assert "past-24h" in page.url


def test_continue_starts_below_the_current_viewport(monkeypatch):
    above = _Element("urn:li:activity:1", y=-800.0, height=300.0)
    visible = _Element("urn:li:activity:2", y=100.0, height=300.0)
    page = _Page(elements=[above, visible])
    posts = {
        "urn:li:activity:1": job_post(1),
        "urn:li:activity:2": job_post(2),
    }
    monkeypatch.setattr(
        scroller, "read_post", lambda el: posts.get(el.get_attribute("data-id"))
    )
    monkeypatch.setattr(scroller, "expand_see_more", lambda page: 0)
    cfg = _cfg(max_scrolls=2)

    batches = list(scroller.iter_post_batches(page, cfg, start_from_current_view=True))
    batches_from_top = list(scroller.iter_post_batches(page, cfg))

    assert [[post.url for post in batch] for batch in batches] == [[posts["urn:li:activity:2"].url]]
    assert len(batches_from_top[0]) == 2


def test_continue_only_scrolls_downwards(monkeypatch):
    page = _Page(elements=[_Element("urn:li:activity:1")])
    monkeypatch.setattr(scroller, "read_post", lambda el: job_post(1))
    monkeypatch.setattr(scroller, "expand_see_more", lambda page: 0)

    list(scroller.iter_post_batches(page, _cfg(max_scrolls=3), start_from_current_view=True))

    assert page.scrolled
    assert all(distance > 0 for distance in page.scrolled)
    assert page.scroll_y == 1500


# --- which tab gets used -----------------------------------------------------


def test_a_linkedin_tab_is_picked_and_unrelated_tabs_are_ignored():
    from collector.browser import BrowserSession

    session = BrowserSession.__new__(BrowserSession)
    other = _Page(url="https://example.com/inbox")
    feed = _Page(url=FEED_URL)
    search = _Page(url=SEARCH_URL)
    for page in (other, feed, search):
        page.context = type("Context", (), {"pages": [page]})()
    session.browser = type("Browser", (), {"contexts": [
        type("Context", (), {"pages": [other]})(),
        type("Context", (), {"pages": [feed, search]})(),
    ]})()

    assert session._pick_existing_linkedin_page() is search

    session.browser = type("Browser", (), {"contexts": [
        type("Context", (), {"pages": [other, feed]})(),
    ]})()
    assert session._pick_existing_linkedin_page() is feed

    session.browser = type("Browser", (), {"contexts": [
        type("Context", (), {"pages": [other]})(),
    ]})()
    assert session._pick_existing_linkedin_page() is None


class _FakePageHandle:
    def __init__(self, url, context):
        self.url = url
        self.context = context


class _FakeContext:
    def __init__(self, pages):
        self.pages = pages
        self.new_page_calls = 0

    def new_page(self):
        self.new_page_calls += 1
        raise AssertionError("the continuation must not open a new tab")


class _FakeBrowser:
    def __init__(self, contexts):
        self.contexts = contexts
        self.new_context_calls = 0

    def new_context(self, **kwargs):
        self.new_context_calls += 1
        raise AssertionError("the continuation must not create a new context")


class _FakePlaywright:
    def __init__(self, browser):
        self.chromium = type("Chromium", (), {"connect_over_cdp": lambda self, url, timeout=None: browser})()
        self.stopped = 0

    def start(self):
        return self

    def stop(self):
        self.stopped += 1


def _attach(monkeypatch, pages):
    from collector.browser import BrowserSession

    context = _FakeContext(pages)
    for page in pages:
        page.context = context
    browser = _FakeBrowser([context])
    fake = _FakePlaywright(browser)
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: fake)
    session = BrowserSession(Config())
    return session, browser, context


def test_continue_does_not_create_a_context_or_a_tab(monkeypatch):
    from collector.browser import BrowserSession

    session, browser, context = _attach(monkeypatch, [_Page()])

    page = session.connect(require_linkedin=True)

    assert page.url == SEARCH_URL
    assert session.page is page
    assert session.context is context
    assert browser.new_context_calls == 0
    assert context.new_page_calls == 0


def test_continue_without_a_linkedin_tab_fails_safely(monkeypatch):
    from collector.browser import BrowserError, BrowserSession

    session, browser, context = _attach(monkeypatch, [_Page(url="https://example.com/"), _Page(url="https://mail.google.com/")])

    with pytest.raises(BrowserError) as exc:
        session.connect(require_linkedin=True)

    assert "no page to continue from" in str(exc.value)
    assert browser.new_context_calls == 0
    assert context.new_page_calls == 0
    assert all(page.navigations == [] for page in context.pages)


def test_continue_on_a_non_linkedin_page_stops_before_scraping(monkeypatch, tmp_path, capsys):
    import main as mainpy

    page = _Page(url="https://example.com/pricing")
    session = _Session(page)

    def refuse(**kwargs):
        return page

    session.connect = refuse
    monkeypatch.setattr(mainpy, "BrowserSession", lambda cfg: session)
    monkeypatch.setattr(mainpy.safety, "is_login_required", lambda p: False)
    monkeypatch.setattr(
        mainpy,
        "save_scraping_run",
        lambda *a, **k: pytest.fail("a failed continuation must not store a run"),
    )

    with pytest.raises(SystemExit) as exc:
        mainpy.run(_cfg(), run_mode="continue")

    assert exc.value.code == 1
    assert session.disconnects == 1
    assert page.navigations == []
    out = capsys.readouterr().out
    assert "no LinkedIn page to continue from" in out
    assert "MODE: Continue From Current Page" in out


# --- deduplication across runs ----------------------------------------------


def test_deduplication_uses_the_linkedin_post_url_as_the_primary_key(tmp_path):
    url = post_url(5)
    _write_previous_run(run_storage.runs_dir(tmp_path), 1, [url])
    deduper = Deduplicator()

    assert continuation.seed_deduper(deduper, base=tmp_path) == 1
    assert deduper.is_duplicate(Post(url=url, text="completely different words"))
    assert deduper.is_duplicate(Post(url=f"{url}?utm_source=share", text="something else"))
    assert not deduper.is_duplicate(Post(url=post_url(6), text="completely different words"))


def test_continue_skips_posts_collected_by_earlier_runs(monkeypatch, tmp_path, capsys):
    from collector.models import Stats

    already = job_post(1, url=post_url(1))
    fresh = job_post(2, url=post_url(2))
    run_storage.save_scraping_run(
        [job_match(already)], Stats(), Config(), base=tmp_path, run_mode="standard"
    )

    elements = [_Element("urn:li:activity:1"), _Element("urn:li:activity:2")]
    page = _Page(elements=elements)
    mainpy, _ = _wire(
        monkeypatch,
        page,
        tmp_path,
        {"urn:li:activity:1": already, "urn:li:activity:2": fresh},
    )

    stats = mainpy.run(_cfg(max_scrolls=2), run_mode="continue")

    assert stats.collected == 1
    assert stats.duplicates_removed == 1

    out = capsys.readouterr().out
    assert out.count("MATCH #01") == 1
    assert already.url not in out.split("MATCH #01", 1)[1]

    stored = _runs(tmp_path)
    assert len(stored) == 2
    jobs = json.loads(stored[-1].read_text(encoding="utf-8"))["jobs"]
    assert [job["linkedin_post_url"] for job in jobs] == [fresh.url]


@pytest.mark.parametrize(
    "previous_mode, expected_flow",
    [
        ("standard", "search"),
        ("date_posted_24h", "search"),
        ("latest", "search"),
        ("before", "search"),
        ("feed", "feed"),
    ],
)
def test_continue_works_after_any_previous_entry_point(tmp_path, previous_mode, expected_flow):
    from collector.models import Stats

    assert run_modes.flow(previous_mode) == expected_flow

    run_storage.save_scraping_run(
        [job_match(job_post(1, url=post_url(1)))],
        Stats(),
        Config(),
        base=tmp_path,
        run_mode=previous_mode,
    )
    deduper = Deduplicator()

    assert continuation.seed_deduper(deduper, base=tmp_path) == 1
    assert deduper.is_duplicate(
        Post(url="https://linkedin.com/feed/update/urn:li:activity:7900000000000000001/?x=1", text="other words")
    )
    assert not deduper.is_duplicate(Post(url=post_url(2), text="other words"))


def test_continuation_creates_the_next_sequential_run(monkeypatch, tmp_path, capsys):
    _write_previous_run(run_storage.runs_dir(tmp_path), 20, [post_url(1)])

    fresh = job_post(2, url=post_url(2))
    page = _Page(elements=[_Element("urn:li:activity:2")])
    mainpy, _ = _wire(monkeypatch, page, tmp_path, {"urn:li:activity:2": fresh})

    stats = mainpy.run(_cfg(max_scrolls=2), run_mode="continue")

    assert stats.collected == 1
    files = _runs(tmp_path)
    assert [f.name for f in files] == ["Scraping Run 20.json", "Scraping Run 21.json"]

    payload = json.loads(files[-1].read_text(encoding="utf-8"))
    assert payload["run_info"]["run_mode"] == "continue"
    assert payload["run_info"]["date_posted_filter"] is None
    assert payload["run_info"]["sort_mode"] is None
    assert [job["linkedin_post_url"] for job in payload["jobs"]] == [fresh.url]
    assert post_url(1) not in [job["linkedin_post_url"] for job in payload["jobs"]]


def test_continue_reads_the_shared_pipeline_from_the_current_view(monkeypatch, tmp_path):
    page = _Page()
    spy: List[bool] = []
    mainpy, _ = _wire(monkeypatch, page, tmp_path, spy=spy)

    mainpy.run(_cfg(max_scrolls=1), run_mode="continue")

    assert spy == [True]


def test_continue_reports_loaded_urls_from_earlier_runs(monkeypatch, tmp_path, capsys):
    _write_previous_run(run_storage.runs_dir(tmp_path), 3, [post_url(1), post_url(2)])
    mainpy, _ = _wire(monkeypatch, _Page(), tmp_path)

    mainpy.run(_cfg(max_scrolls=1), run_mode="continue")

    out = capsys.readouterr().out
    assert "Loaded 2 LinkedIn post URL(s) from earlier runs" in out


def test_continue_with_no_earlier_runs_says_so(monkeypatch, tmp_path, capsys):
    mainpy, _ = _wire(monkeypatch, _Page(), tmp_path)

    mainpy.run(_cfg(max_scrolls=1), run_mode="continue")

    assert "No earlier scraping runs with collected posts were found" in capsys.readouterr().out


# --- the pre-existing entry points stay untouched ---------------------------


def test_existing_entry_point_scripts_are_unchanged():
    for name, marker in (
        ("run.py", "run_main(passthrough)"),
        ("date_posted_24h_run.py", 'run_mode="date_posted_24h"'),
        ("latest_run.py", 'run_mode="latest"'),
        ("top_match_run.py", 'run_mode="before"'),
    ):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert marker in source
        assert "feed_run" not in source
        assert "continue_run" not in source


def test_run_signature_defaults_are_unchanged():
    import main as mainpy

    parameters = inspect.signature(mainpy.run).parameters
    assert parameters["run_mode"].default == "standard"
    assert parameters["apply_past_24h"].default is False
    assert parameters["sort_mode"].default is None


def test_unknown_run_mode_still_behaves_like_the_standard_search():
    assert run_modes.flow("nope") == "search"
    assert run_modes.header_label("nope") is None
