"""Tests for the LinkedIn feed entry point (feed_run.py).

The feed run must open/use ``https://www.linkedin/feed/``, scroll downwards and
reuse the shared collector -- never a second scraping implementation, never the
keyword search, Date posted or Sort by filters of the pre-existing entry
points.
"""

from __future__ import annotations

import inspect
import json
import runpy
from pathlib import Path
from typing import List

import pytest

import feed_run
from collector import run_modes, run_storage
from collector.models import Post
from config import Config

ROOT = Path(__file__).resolve().parent.parent

FEED_URL = "https://www.linkedin.com/feed/"

JOB_TEXT = (
    "We are hiring a Generative AI Engineer (opening #{index}).\n"
    "Company: Acme AI\nLocation: Bengaluru\nExperience: 3-5 years\n"
    "Skills:\n- Python\n- LLM orchestration\n"
    "Responsibilities:\n- Build agentic systems\n"
    "Requirements:\n- RAG pipelines\n"
    "Apply: send your resume to jobs{index}@acme-ai.com"
)


def job_post(index: int) -> Post:
    return Post(
        author=f"Recruiter {index}",
        text=JOB_TEXT.format(index=index),
        url=f"https://www.linkedin.com/feed/update/urn:li:activity:710000000000000000{index}/",
    )


class _NoElements:
    def count(self):
        return 0

    def nth(self, index):
        raise AssertionError("no locator children are expected in these tests")


class _FakeElement:
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


class _FeedPage:
    """Just enough page double for scrolling, safety checks and navigation."""

    def __init__(self, elements=(), url: str = FEED_URL):
        self.url = url
        self.elements: List[_FakeElement] = list(elements)
        self.mouse = self
        self.context = None
        self.gotos: List[str] = []
        self.scrolled: List[int] = []
        self.evaluated: List[str] = []
        self.timeouts: List[int] = []
        self.scroll_y = 0
        self.scroll_height = 5000
        self.viewport_height = 900

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

    def goto(self, url, **kwargs):
        self.gotos.append(url)
        self.url = url

    def reload(self, **kwargs):
        raise AssertionError("the feed run must not reload the page")


class _Session:
    def __init__(self, page, pages=None):
        self.page = page
        self.connected_pages = list(pages if pages is not None else [page])
        self.context = type("Context", (), {"pages": self.connected_pages})()
        self.connect_kwargs = None
        self.disconnects = 0

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs
        return self.page

    def page_title(self):
        return "LinkedIn Feed"

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
    """Attach a fake session and storage so run() never touches Chrome/data."""
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


# --- the entry point ---------------------------------------------------------


def test_feed_run_only_asks_main_for_the_feed_mode(monkeypatch):
    _, calls = _record_main_call(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(ROOT / "feed_run.py"), run_name="__main__")

    assert exc.value.code == 0
    assert calls == {"run_mode": "feed", "apply_past_24h": False, "sort_mode": None}


def test_feed_run_is_only_an_entry_point():
    source = inspect.getsource(feed_run)

    assert "from main import main" in source
    assert 'run_mode="feed"' in source
    assert "def run" not in source
    assert "class " not in source
    assert "process_batches" not in source
    assert "save_scraping_run" not in source
    assert "search_with_posts_filter" not in source
    assert "iter_post_batches" not in source


# --- mode, banner and metadata ----------------------------------------------


def test_registry_describes_the_feed_mode():
    assert run_modes.flow(run_modes.FEED) == "feed"
    assert run_modes.header_label("feed") == "LinkedIn Feed"
    assert run_modes.apply_past_24h("feed") is False
    assert run_modes.sort_mode("feed") is None
    assert run_modes.date_posted_filter("feed") is None


def test_feed_banner_prints_the_mode(capsys):
    from collector import printer

    printer.print_header(_Cfg(), mode_label=run_modes.header_label("feed"))

    out = capsys.readouterr().out
    assert "MODE: LinkedIn Feed" in out
    assert out.index("LINKEDIN JOB POST COLLECTOR") < out.index("MODE: LinkedIn Feed")


def test_feed_url_is_the_linkedin_feed():
    assert Config().linkedin_feed_url == FEED_URL


def test_feed_run_stores_a_sequential_json_with_the_feed_mode(tmp_path):
    from collector.models import Stats

    path = run_storage.save_scraping_run(
        [], Stats(), Config(), base=tmp_path, run_mode="feed"
    )

    info = json.loads(path.read_text(encoding="utf-8"))["run_info"]
    assert info["run_mode"] == "feed"
    assert info["date_posted_filter"] is None
    assert info["sort_mode"] is None


# --- opening the feed --------------------------------------------------------


def test_feed_reuses_a_tab_already_on_the_feed():
    import main as mainpy

    page = _FeedPage()
    session = _Session(page)

    assert mainpy._open_feed(session, _cfg()) is page
    assert page.gotos == []


def test_feed_opens_the_feed_url_when_the_tab_is_elsewhere():
    import main as mainpy

    page = _FeedPage(url="https://www.linkedin.com/search/results/content/?keywords=AI")
    session = _Session(page)

    assert mainpy._open_feed(session, _cfg()) is page
    assert page.gotos == [FEED_URL]
    assert page.url == FEED_URL


def test_feed_reuses_another_open_feed_tab_instead_of_navigating():
    import main as mainpy

    search = _FeedPage(url="https://www.linkedin.com/search/results/content/?keywords=AI")
    feed = _FeedPage(url=FEED_URL)
    session = _Session(search, pages=[search, feed])

    assert mainpy._open_feed(session, _cfg()) is feed
    assert session.page is feed
    assert search.gotos == []
    assert feed.gotos == []


# --- collection --------------------------------------------------------------


def test_feed_collects_by_scrolling_the_shared_pipeline(monkeypatch, tmp_path, capsys):
    elements = [_FakeElement(f"urn:li:activity:1000{i}") for i in range(1, 4)]
    posts = {
        f"urn:li:activity:1000{i}": job_post(i) for i in range(1, 4)
    }
    page = _FeedPage(elements)
    spy: List[bool] = []
    mainpy, session = _wire(monkeypatch, page, tmp_path, posts, spy)

    stats = mainpy.run(_cfg(), run_mode="feed")

    assert stats.collected == 3
    assert spy == [False]
    assert session.connect_kwargs == {}
    assert page.scrolled and all(distance > 0 for distance in page.scrolled)
    assert page.gotos == []

    out = capsys.readouterr().out
    assert "MODE: LinkedIn Feed" in out
    assert "MATCH #01" in out
    assert "COLLECTION COMPLETE" in out

    files = list(run_storage.runs_dir(tmp_path).glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["run_info"]["run_mode"] == "feed"
    assert len(payload["jobs"]) == 3
    assert payload["summary"]["final_jds_collected"] == 3
    assert all(job["linkedin_post_url"] for job in payload["jobs"])


def test_feed_run_never_searches_or_touches_filters(monkeypatch, tmp_path):
    import main as mainpy

    touched = []
    monkeypatch.setattr(
        mainpy, "search_with_posts_filter", lambda *a, **k: touched.append("search") or True
    )
    monkeypatch.setattr(
        mainpy.navigator, "search_role", lambda *a, **k: touched.append("navigator.search_role")
    )
    monkeypatch.setattr(
        mainpy.navigator,
        "select_posts_filter",
        lambda *a, **k: touched.append("navigator.select_posts_filter"),
    )
    monkeypatch.setattr(
        mainpy.date_filter,
        "apply_past_24_hours_filter",
        lambda page: touched.append("date_filter"),
    )
    monkeypatch.setattr(
        mainpy.sort_filter, "apply_sort_filter", lambda page, mode: touched.append("sort_filter")
    )

    page = _FeedPage()
    _wire(monkeypatch, page, tmp_path)

    stats = mainpy.run(_cfg(max_scrolls=1), run_mode="feed")

    assert touched == []
    assert stats.roles_searched == 0
    assert page.url == FEED_URL
    assert page.gotos == []


def test_feed_stops_safely_on_a_security_challenge(monkeypatch, tmp_path, capsys):
    from collector.safety import SecurityChallengeError

    page = _FeedPage()
    page.url = "https://www.linkedin.com/checkpoint/challenge/"
    mainpy, session = _wire(monkeypatch, page, tmp_path)

    stats = mainpy.run(_cfg(max_scrolls=1), run_mode="feed")

    assert stats.stop_reason == "security challenge detected"
    assert session.disconnects == 1
    assert "security" in capsys.readouterr().out.lower()


# --- the pre-existing entry points stay untouched ---------------------------


def test_search_entry_points_keep_their_behaviour():
    expected = {
        "standard": (None, False, None, None),
        "date_posted_24h": (None, True, None, "past_24_hours"),
        "latest": ("Past 24 Hours + Latest", True, "latest", "past_24_hours"),
        "before": ("Past 24 Hours + Top Match", True, "top_match", "past_24_hours"),
    }
    for name, (label, past_24h, sort, date_filter_value) in expected.items():
        assert run_modes.header_label(name) == label
        assert run_modes.apply_past_24h(name) is past_24h
        assert run_modes.sort_mode(name) == sort
        assert run_modes.date_posted_filter(name) == date_filter_value
        assert run_modes.flow(name) == "search"


def test_unknown_run_mode_still_falls_back_to_standard():
    assert run_modes.header_label("nope") is None
    assert run_modes.flow("nope") == "search"


def test_standard_mode_still_searches_every_role(monkeypatch, tmp_path):
    import main as mainpy

    searched = []
    monkeypatch.setattr(
        mainpy,
        "search_with_posts_filter",
        lambda page, role, cfg, **kwargs: searched.append(role) or True,
    )
    monkeypatch.setattr(mainpy, "process_batches", lambda *a, **k: 0)
    mainpy, session = _wire(monkeypatch, _FeedPage(url="https://www.linkedin.com/search/results/content/"), tmp_path)

    cfg = _cfg()
    cfg.target_roles = ["AI Developer", "LLM Engineer"]
    mainpy.run(cfg, run_mode="standard")

    assert searched == ["AI Developer", "LLM Engineer"]
    assert session.connect_kwargs == {}


def test_run_signature_defaults_are_unchanged():
    import main as mainpy

    parameters = inspect.signature(mainpy.run).parameters
    assert parameters["run_mode"].default == "standard"
    assert parameters["apply_past_24h"].default is False
    assert parameters["sort_mode"].default is None


def test_pre_existing_entry_point_scripts_are_untouched():
    for name, marker in (
        ("run.py", 'run_main(passthrough)'),
        ("date_posted_24h_run.py", 'run_mode="date_posted_24h"'),
        ("latest_run.py", 'run_mode="latest"'),
        ("top_match_run.py", 'run_mode="before"'),
    ):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert marker in source
        assert "run_mode=\"feed\"" not in source
        assert "run_mode=\"continue\"" not in source
