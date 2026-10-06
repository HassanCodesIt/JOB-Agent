"""URL validation and field separation for the LinkedIn Job Finder.

Four URL fields exist and must never be confused:

* ``linkedin_post_url`` - LinkedIn post permalink (source identity, view-only)
* ``job_url``           - LinkedIn job listing URL (view-only)
* ``apply_url``         - external application link (user action)
* ``application_url``   - AI Job Assistant form-detection target

Nothing in this module ever derives ``application_url`` from a LinkedIn source
URL; only an explicitly validated external apply link can become one.
"""

from __future__ import annotations

from typing import Iterable, List, Optional
from urllib.parse import urlparse

LINKEDIN_HOSTS = ("linkedin.com", "lnkd.in")
IMAGE_HOSTS = ("licdn.com", "linkedin.com", "dropbox.com", "imgur.com")

_MAX_URL_LENGTH = 2048


def _hostname(url: str) -> str:
    try:
        parsed = urlparse(str(url).strip())
    except ValueError:
        return ""
    return (parsed.hostname or "").lower().rstrip(".")


def is_http_url(url) -> bool:
    """True when *url* is an absolute http(s) URL we are willing to render."""
    if not url or not isinstance(url, str):
        return False
    text = url.strip()
    if not text or len(text) > _MAX_URL_LENGTH:
        return False
    try:
        parsed = urlparse(text)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return bool(parsed.netloc)


def normalize(url) -> Optional[str]:
    """Return a displayable URL, or ``None`` when it is not safe to show."""
    if not is_http_url(url):
        return None
    return str(url).strip()


def is_linkedin_url(url) -> bool:
    host = _hostname(url)
    if not host:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in LINKEDIN_HOSTS)


def is_image_url(url) -> bool:
    host = _hostname(url)
    if not host:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in IMAGE_HOSTS)


def external_urls(urls: Optional[Iterable]) -> List[str]:
    """Validated, de-duplicated non-LinkedIn links in their original order.

    LinkedIn hosts (including image hosts such as ``licdn.com``) are dropped:
    these are application links, and a LinkedIn page is never one.
    """
    seen = set()
    result: List[str] = []
    for url in urls or []:
        clean = normalize(url)
        if not clean or clean in seen:
            continue
        if is_linkedin_url(clean) or is_image_url(clean):
            continue
        seen.add(clean)
        result.append(clean)
    return result


def safe_application_url(post_url, job_url, apply_url) -> Optional[str]:
    """Resolve the only URL that may become an AI Job Assistant form target.

    Rules enforced here (never guessed from LinkedIn source URLs):

    1. ``linkedin_post_url`` and ``job_url`` are never used.
    2. Only ``apply_url`` is considered, and only after semantic validation.
    3. Any LinkedIn host (posts, jobs, Easy Apply, ``lnkd.in`` short links) is
       rejected, because those pages are not external application forms.
    """
    del post_url, job_url  # explicitly never consulted
    if not is_http_url(apply_url):
        return None
    text = str(apply_url).strip()
    if is_linkedin_url(text) or is_image_url(text):
        return None
    return text
