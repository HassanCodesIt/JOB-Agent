from __future__ import annotations

from collector import scroller
from collector.models import Stats
from config import Config


class _FakeElement:
    def __init__(self, key: str):
        self._key = key

    def get_attribute(self, name):
        if name == "data-id":
            return self._key
        return None


class _FakePage:
    """Minimal page double: 2 readable posts followed by 1 unreadable element."""

    def __init__(self, elements):
        self._elements = elements
        self.mouse = self

    def query_selector_all(self, selector):
        return list(self._elements)

    def wheel(self, x, y):
        return None

    def evaluate(self, script, *args):
        return None

    def wait_for_function(self, *args, **kwargs):
        return None

    def wait_for_timeout(self, ms):
        return None


def test_unreadable_posts_are_counted(monkeypatch):
    posts = [
        scroller.Post(author="A", text="Hiring an AI Engineer. Email jobs@acme.com", url="u1"),
        scroller.Post(author="B", text="We are hiring an ML Engineer. Email hr@acme.com", url="u2"),
    ]
    calls = {"index": 0}

    def fake_read_post(element):
        index = calls["index"]
        calls["index"] += 1
        return posts[index] if index < len(posts) else None

    monkeypatch.setattr(scroller, "read_post", fake_read_post)
    monkeypatch.setattr(scroller, "expand_see_more", lambda page: 0)

    page = _FakePage([_FakeElement("urn:li:activity:1"), _FakeElement("urn:li:activity:2"), _FakeElement("urn:li:activity:3")])
    stats = Stats()
    cfg = Config(max_scrolls=1, action_delay=(0.0, 0.0))

    batches = list(scroller.iter_post_batches(page, cfg, stats))

    assert len(batches) == 1
    assert len(batches[0]) == 2
    assert stats.unreadable_posts == 1


def test_iter_post_batches_stops_without_stats_argument(monkeypatch):
    posts = [scroller.Post(author="A", text="Hiring an AI Engineer. Email jobs@acme.com", url="u1")]
    monkeypatch.setattr(scroller, "read_post", lambda element: posts[0])
    monkeypatch.setattr(scroller, "expand_see_more", lambda page: 0)

    page = _FakePage([_FakeElement("urn:li:activity:1")])
    batches = list(scroller.iter_post_batches(page, Config(max_scrolls=1, action_delay=(0.0, 0.0))))

    assert len(batches) == 1
    assert batches[0] == posts