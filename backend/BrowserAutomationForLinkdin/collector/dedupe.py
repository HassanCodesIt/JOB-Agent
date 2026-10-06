from __future__ import annotations

import hashlib
import re
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from collector.models import Post

_URN_IN_PATH = re.compile(r"urn:li:(?:activity|ugcPost|share):(\d+)", re.IGNORECASE)
_ACTIVITY_SUFFIX = re.compile(r"-activity-(\d+)", re.IGNORECASE)
_EMOJI = re.compile(
    "[" "\U0001f300-\U0001faff" "\U00002600-\U000027bf" "\U0001f1e6-\U0001f1ff" "\ufe0f" "]",
    flags=re.UNICODE,
)
_URL_IN_TEXT = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def canonical_url(url: str) -> str:
    """Normalise a post permalink so the same post hashes identically."""
    if not url:
        return ""
    raw = url.strip()
    urn_match = _URN_IN_PATH.search(raw)
    if urn_match:
        return f"urn:{urn_match.group(1)}"
    if raw.lower().startswith("urn:"):
        digits = re.search(r"(\d{6,})", raw)
        return f"urn:{digits.group(1)}" if digits else raw.lower()

    try:
        parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    except ValueError:
        return raw.lower().rstrip("/")

    host = (parts.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", parts.path or "")

    activity = _ACTIVITY_SUFFIX.search(path)
    if activity:
        return f"urn:{activity.group(1)}"

    path = re.sub(r"/posts/[^/]*", "/posts/-", path)
    return urlunsplit(("https", host, path, "", ""))


def normalize_text(text: str) -> str:
    """Lowercase, drop links and emoji, collapse whitespace."""
    if not text:
        return ""
    cleaned = _URL_IN_TEXT.sub(" ", text)
    cleaned = _EMOJI.sub(" ", cleaned)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().lower()


def text_hash(text: str) -> str:
    return hashlib.sha1(normalize_text(text).encode("utf-8")).hexdigest()


class Deduplicator:
    """Dedupe by canonical URL, falling back to a normalised-text hash."""

    def __init__(self) -> None:
        self.seen_urls = set()
        self.seen_hashes = set()
        self.duplicates_removed = 0
        # canonical URL -> hash of the post that claimed it, so a URL recovered
        # later can be checked against the post it is being claimed for.
        self.url_owners = {}

    def is_duplicate(self, post: Post) -> bool:
        url_key = canonical_url(post.url)
        hash_key = text_hash(post.text) if post.text else ""
        if url_key and url_key in self.seen_urls:
            self.duplicates_removed += 1
            return True
        if hash_key and hash_key in self.seen_hashes:
            self.duplicates_removed += 1
            return True
        return False

    def remember(self, post: Post) -> None:
        url_key = canonical_url(post.url)
        hash_key = text_hash(post.text) if post.text else ""
        if url_key:
            self.seen_urls.add(url_key)
            self.url_owners.setdefault(url_key, hash_key)
        if hash_key:
            self.seen_hashes.add(hash_key)

    def owner_of(self, url: str) -> Optional[str]:
        """Text hash of the post that already claimed this URL, if any."""
        if not url:
            return None
        return self.url_owners.get(canonical_url(url))

    def belongs_to(self, post: Post, url: str) -> bool:
        """Whether ``url`` is free to claim for ``post``.

        Used when a post URL is recovered after the fact: if the URL was
        already claimed by a different post, accepting it would attribute one
        post's permalink to another.
        """
        owner = self.owner_of(url)
        if not owner:
            return True
        return not post.text or owner == text_hash(post.text)

    def check_and_add(self, post: Post) -> bool:
        """Return True when the post was already seen, otherwise store it."""
        duplicate = self.is_duplicate(post)
        self.remember(post)
        return duplicate

    def __len__(self) -> int:
        return len(self.seen_hashes)


def duplicate_of(a: Post, b: Post) -> Optional[str]:
    """Explain how two posts are considered duplicates ('url' or 'text')."""
    if canonical_url(a.url) and canonical_url(a.url) == canonical_url(b.url):
        return "url"
    if a.text and text_hash(a.text) == text_hash(b.text):
        return "text"
    return None