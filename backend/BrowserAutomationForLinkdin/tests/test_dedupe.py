from __future__ import annotations

from collector.dedupe import Deduplicator, canonical_url, duplicate_of, normalize_text, text_hash
from collector.models import Post


def test_canonical_url_variants_collapse():
    links = [
        "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/?utm_source=share",
        "https://linkedin.com/feed/update/urn:li:activity:7123456789012345678/",
        "https://www.linkedin.com/posts/someone_genai-engineer-hiring-activity-7123456789012345678-abcD",
    ]
    keys = {canonical_url(link) for link in links}
    assert keys == {"urn:7123456789012345678"}


def test_canonical_url_keeps_distinct_posts_apart():
    assert canonical_url("https://www.linkedin.com/feed/update/urn:li:activity:1/") != canonical_url(
        "https://www.linkedin.com/feed/update/urn:li:activity:2/"
    )


def test_normalize_text_strips_urls_and_emoji():
    left = normalize_text("Great post! 🚀 https://linkedin.com/posts/x")
    right = normalize_text("great post")
    assert left == right
    assert text_hash(left) == text_hash(right)


def test_dedupe_by_url_across_roles():
    deduper = Deduplicator()
    first = Post(url="https://www.linkedin.com/feed/update/urn:li:activity:42/", text="a")
    second = Post(url="https://www.linkedin.com/feed/update/urn:li:activity:42/?x=1", text="completely different words here")
    assert deduper.check_and_add(first) is False
    assert deduper.check_and_add(second) is True
    assert deduper.duplicates_removed == 1


def test_dedupe_by_text_fallback_when_url_missing():
    deduper = Deduplicator()
    body = "We are hiring an AI Engineer. Apply to hr@acme.com with your resume please."
    assert deduper.check_and_add(Post(text=body)) is False
    assert deduper.check_and_add(Post(text=body.upper() + "  ")) is True
    assert deduper.duplicates_removed == 1


def test_distinct_posts_are_kept():
    deduper = Deduplicator()
    assert deduper.check_and_add(Post(url="urn:li:activity:1", text="first post")) is False
    assert deduper.check_and_add(Post(url="urn:li:activity:2", text="second post")) is False
    assert deduper.duplicates_removed == 0
    assert len(deduper) == 2


def test_duplicate_of_helper():
    a = Post(url="https://www.linkedin.com/feed/update/urn:li:activity:9/", text="hello world")
    b = Post(url="https://linkedin.com/feed/update/urn:li:activity:9", text="hello world")
    c = Post(url="urn:li:activity:10", text="something else entirely")
    assert duplicate_of(a, b) == "url"
    assert duplicate_of(a, c) is None