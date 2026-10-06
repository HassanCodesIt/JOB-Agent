from __future__ import annotations

import re
from typing import Iterable, List, Optional
from urllib.parse import urlsplit

from collector import logger
from collector.apply_link_extractor import collect_apply_urls, normalize_url
from collector.models import Post
from collector.post_url_extractor import extract_post_url, permalink_for

POST_SELECTORS = (
    "[role='listitem'][componentkey^='update-card']",
    "div[data-view-name='feed-full-update']",
    "div[data-urn^='urn:li:']",
    "div[data-id^='urn:li:']",
    "div.feed-shared-update-v2",
    "article[data-id^='urn:li:']",
    "article",
)

AUTHOR_SELECTORS = (
    ".update-components-actor__name",
    ".feed-shared-actor__name",
    ".update-components-actor__title",
    "a[href*='/in/'] p span",
    "[data-id='name']",
    "a[aria-label*='profile'] span",
    "a[data-tracking-control*='actor'] span",
    "a[href*='/in/'] span[aria-hidden='true']",
)

TEXT_SELECTORS = (
    "[data-testid='expandable-text-box']",
    ".update-components-text",
    ".feed-shared-inline-show-more-text",
    ".feed-shared-update-v2__description",
    "div[data-view-name='feed-full-update'] .update-components-update-v2__commentary",
    ".update-components-update-v2__commentary",
)

LINK_SELECTORS = (
    "a[href*='/posts/']",
    "a[data-tracking-control*='post']",
    "a[href*='/feed/update/']",
    "a[href*='/pulse/']",
)

# Attached job listings are plain <a> elements; LinkedIn obfuscates every class
# name (ckylmd, ckym3l, ...), so only href/accessible-name signals are used.
JOB_LINK_SELECTORS = (
    "a[href*='/jobs/view/']",
    "a[href*='lnkd.in/']",
    "a[href^='http']",
)

EXTERNAL_LINK_SELECTOR = "a[href^='http']"

JOB_URL_SOURCE_CARD = "linkedin_job_card"
JOB_URL_SOURCE_REDIRECT = "linkedin_redirect"
JOB_URL_SOURCE_EXTERNAL = "external_job_link"
JOB_URL_SOURCE_UNRESOLVED = "unresolved"

_URN_RE = re.compile(r"urn:li:[A-Za-z]+:\d+", re.IGNORECASE)
_TRAILING_SLASHES = re.compile(r"/{2,}")
_JOB_VIEW_RE = re.compile(r"/jobs/view/(\d+)", re.IGNORECASE)
_LINKEDIN_HOST_RE = re.compile(r"(^|\.)linkedin\.com$", re.IGNORECASE)
_SHORT_LINK_HOST_RE = re.compile(r"(^|\.)lnkd\.in$", re.IGNORECASE)
_JOB_ACTION_RE = re.compile(
    r"\b(view|apply|open|see)\b[^.]{0,20}\b(job|role|position|opening|vacancy)"
    r"|\b(job|jobs)\b[^.]{0,20}\b(opening|listing|listing|post|detail|details)\b",
    re.IGNORECASE,
)
_JOB_PATH_RE = re.compile(
    r"/(job|jobs|career|careers|opening|vacancy|vacancies|position|apply)(/|$|\?)",
    re.IGNORECASE,
)


def _absolute(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return f"https://www.linkedin.com{href}"
    return href


def _collapse_slashes(href: str) -> str:
    """Tidy duplicate slashes without eating the protocol separator."""
    head, sep, tail = href.partition("://")
    if not sep:
        return _TRAILING_SLASHES.sub("/", href)
    return head + sep + _TRAILING_SLASHES.sub("/", tail)


def _first_text(element, selectors, allow_element_fallback: bool = True) -> str:
    for selector in selectors:
        try:
            node = element.query_selector(selector)
            if node is None:
                continue
            text = (node.inner_text() or "").strip()
            if text:
                return re.sub(r"[ \t]+", " ", text)
        except Exception:
            continue
    if not allow_element_fallback:
        return ""
    try:
        return (element.inner_text() or "").strip()
    except Exception:
        return ""


def _element_urn(element) -> str:
    """The post's own URN, read from the card's identifier attributes."""
    for attribute in ("data-id", "data-urn", "data-identifier"):
        try:
            value = element.get_attribute(attribute)
        except Exception:
            value = None
        if value and "urn:li:" in value:
            match = _URN_RE.search(value)
            if match:
                return match.group(0)
    return ""


def _post_url(element, urn: str) -> str:
    """Kept for callers that already know the URN; read_post uses the ordered
    extractor in post_url_extractor instead."""
    if urn:
        return permalink_for(urn)
    for selector in LINK_SELECTORS:
        try:
            anchor = element.query_selector(selector)
            if anchor is None:
                continue
            href = anchor.get_attribute("href") or ""
            href = _absolute(href)
            if href.startswith("http"):
                return _collapse_slashes(href)
        except Exception:
            continue
    return ""


def _anchor_label(anchor) -> str:
    parts: List[str] = []
    for attribute in ("aria-label", "title"):
        try:
            value = anchor.get_attribute(attribute)
        except Exception:
            value = None
        if value:
            parts.append(value)
    try:
        parts.append(anchor.inner_text() or "")
    except Exception:
        pass
    return " ".join(parts).strip()


def _anchor_job_url(anchor, exclude: Optional[frozenset] = None) -> Optional[tuple]:
    """Return (url, source) when this anchor points at a job listing."""
    try:
        href = (anchor.get_attribute("href") or "").strip()
    except Exception:
        return None
    if not href:
        return None
    href = _absolute(href)
    if not href.startswith("http"):
        return None

    match = _JOB_VIEW_RE.search(href)
    if match:
        # /jobs/view/<id> identifies the posting on its own, so LinkedIn's
        # trackingId / isJobSearch noise can be dropped safely.
        return f"https://www.linkedin.com/jobs/view/{match.group(1)}/", JOB_URL_SOURCE_CARD

    if exclude and normalize_url(href) in exclude:
        # Already reported as an external apply link; keep the two fields apart.
        return None

    try:
        parts = urlsplit(href)
        host = parts.netloc.lower()
        path = parts.path
    except Exception:
        return None

    label = _anchor_label(anchor)

    if _SHORT_LINK_HOST_RE.search(host):
        # A redirect: the destination cannot be resolved without navigating, so
        # the href LinkedIn exposes is kept verbatim.
        if _JOB_ACTION_RE.search(label):
            return href, JOB_URL_SOURCE_REDIRECT
        return None

    if _LINKEDIN_HOST_RE.search(host):
        return None

    if _JOB_ACTION_RE.search(label) or _JOB_PATH_RE.search(path):
        return href, JOB_URL_SOURCE_EXTERNAL
    return None


def extract_job_url(element, exclude: Optional[Iterable[str]] = None) -> tuple:
    """Read an attached job listing URL straight from the DOM (never clicks).

    Returns (url, source). ``url`` is empty when the post has no job listing;
    ``source`` is JOB_URL_SOURCE_UNRESOLVED when a listing was present but no
    usable destination could be read. ``exclude`` holds URLs already claimed as
    external apply links so JOB URL and APPLY URL never overlap.
    """
    blocked = frozenset(normalize_url(url) for url in (exclude or []) if url)
    for selector in JOB_LINK_SELECTORS:
        try:
            anchors = list(element.query_selector_all(selector))
        except Exception:
            continue
        if not anchors:
            continue
        for anchor in anchors:
            found = _anchor_job_url(anchor, blocked)
            if found:
                return found
        if selector != EXTERNAL_LINK_SELECTOR:
            # A job card is present but exposes no usable href.
            return "", JOB_URL_SOURCE_UNRESOLVED
    return "", ""


def extract_apply_urls(element, text: str, exclude: Optional[Iterable[str]] = None) -> List[str]:
    """External application links, read from the post text and its anchors.

    The word "apply" is never required: a careers/job-shaped URL is enough, and
    application wording around a plain URL is enough too. Company home pages,
    articles and social links are always rejected.
    """
    anchors: List = []
    try:
        anchors = list(element.query_selector_all(EXTERNAL_LINK_SELECTOR))
    except Exception:
        anchors = []
    return collect_apply_urls(text, anchors, exclude)


_TRAILING_MORE = re.compile(r"(?:\u2026|\.{3})\s*more|see more|show more", re.IGNORECASE)

# LinkedIn renders its own composer / reaction controls inside the post card.
# These labels are interface chrome, never part of the job description.
_UI_CHROME_RE = re.compile(
    r"^(?:"
    r"add (?:a )?comment.*|"
    r"add responsibilities? and qualifications.*|"
    r"clarify the application instructions.*|"
    r"write a comment.*|"
    r"post(?:ing)? (?:a )?comment.*|"
    r"\u2026\s*more|\.\.\.\s*more|see more|show more|"
    r"join|follow|connect|message|send|share|repost|reply|comment|like|more|"
    r"react|save|hide|report|block|not interested"
    r")$",
    re.IGNORECASE,
)

_ENTITIES = (
    ("&nbsp;", " "),
    ("&amp;", "&"),
    ("&lt;", "<"),
    ("&gt;", ">"),
    ("&quot;", '"'),
    ("&#39;", "'"),
    ("&apos;", "'"),
    ("&#x27;", "'"),
    ("&#47;", "/"),
)


def _decode_entities(text: str) -> str:
    """Posts frequently contain double-escaped HTML entities."""
    for entity, char in _ENTITIES:
        text = text.replace(entity, char)
    text = re.sub(r"&#(\d{1,7});", lambda m: chr(int(m.group(1))) if int(m.group(1)) < 0x110000 else m.group(0), text)
    return text


def _is_ui_chrome(line: str) -> bool:
    return bool(_UI_CHROME_RE.match(line.strip()))


def _clean_text(raw: str) -> str:
    if not raw:
        return ""
    raw = _decode_entities(raw)
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in raw.splitlines()]
    collapsed: List[str] = []
    for line in lines:
        if not line.strip():
            if collapsed and collapsed[-1] != "":
                collapsed.append("")
            continue
        stripped = line.strip()
        if _is_ui_chrome(stripped):
            continue
        collapsed.append(stripped)
    while collapsed and collapsed[-1] == "":
        collapsed.pop()
    if collapsed:
        collapsed[-1] = _TRAILING_MORE.sub("", collapsed[-1]).strip()
    return "\n".join(collapsed)


# Media wrappers that LinkedIn renders around an attached image, article,
# document or video. These are semantic-ish hooks; the profile/company anchors
# are excluded separately so avatars are never mistaken for post media.
MEDIA_CONTAINER_SELECTORS = (
    "figure",
    "[data-testid='feed-images-content']",
    "[data-testid='media']",
    ".update-components-image",
    ".update-components-article",
    ".update-components-document",
    ".update-components-media",
    ".feed-shared-image",
    ".feed-shared-article",
    ".feed-shared-media",
)

# Substrings that betray an author avatar, company/school logo or UI icon.
_PROFILE_HINTS = (
    "profile",
    "avatar",
    "presence",
    "company-logo",
    "school-logo",
    "logo",
    "icon",
    "ghost",
    "badge",
)


def _looks_like_attached_media(
    src: str,
    alt: str,
    ancestor_href: str,
    in_media_container: bool,
) -> bool:
    """Pure decision helper: is this image attached media, or an avatar/icon?

    Kept free of DOM access so the rule can be unit-tested directly.
    """
    if in_media_container:
        return True
    haystack = f"{src or ''} {alt or ''}".lower()
    if any(hint in haystack for hint in _PROFILE_HINTS):
        return False
    href = (ancestor_href or "").lower()
    if any(marker in href for marker in ("/in/", "/company/", "/school/", "/showcase/")):
        return False
    return bool((src or "").strip())


def _closest_href(element) -> str:
    """Href of the nearest wrapping anchor, or "" -- used to spot avatars."""
    try:
        return element.evaluate(
            "el => { const a = el.closest('a'); return a ? (a.getAttribute('href') || '') : ''; }"
        ) or ""
    except Exception:
        return ""


def _first_media_src(element) -> str:
    for selector in MEDIA_CONTAINER_SELECTORS:
        try:
            node = element.query_selector(selector)
        except Exception:
            continue
        if node is None:
            continue
        try:
            img = node.query_selector("img")
        except Exception:
            img = None
        if img is not None:
            try:
                src = (img.get_attribute("src") or "").strip()
            except Exception:
                src = ""
            if src:
                return src
    return ""


def _extract_image_info(element) -> tuple:
    """Detect attached media on the post card. Returns (has_image, image_url).

    Structural media containers win first; failing that, loose ``<img>`` tags
    are accepted only when they are not an avatar, logo or UI icon.
    """
    for selector in MEDIA_CONTAINER_SELECTORS:
        try:
            if element.query_selector(selector) is not None:
                return True, _first_media_src(element)
        except Exception:
            continue

    try:
        imgs = element.query_selector_all("img")
    except Exception:
        imgs = []

    for img in imgs:
        try:
            src = (img.get_attribute("src") or "").strip()
            alt = (img.get_attribute("alt") or "").strip()
        except Exception:
            continue
        if _looks_like_attached_media(src, alt, _closest_href(img), in_media_container=False):
            return True, src
    return False, ""


def read_post(element, log_post_url: bool = True) -> Optional[Post]:
    """Build a Post from a feed element; unreadable posts are skipped."""
    try:
        author = _first_text(element, AUTHOR_SELECTORS, allow_element_fallback=False)
        text = _clean_text(_first_text(element, TEXT_SELECTORS))
        if not text:
            raise ValueError("empty post text")

        if log_post_url:
            logger.info("Extracting LinkedIn post URL...")
            logger.info("Trying DOM-based post URL extraction...")
        url, urn, url_source = extract_post_url(element)
        if log_post_url and url:
            logger.ok(f"LinkedIn post URL found: {url}")
            logger.detail(f"    source: {url_source}")

        apply_urls = extract_apply_urls(element, text)
        job_url, job_source = extract_job_url(element, exclude=apply_urls)

        if job_url:
            logger.info("Job listing detected in post")
            logger.ok(f"Job URL extracted: {job_url}")
            if job_source == JOB_URL_SOURCE_REDIRECT:
                logger.detail(
                    "    -> LinkedIn redirect; destination kept as exposed "
                    "(not resolved, to avoid leaving the Posts page)"
                )
        elif job_source == JOB_URL_SOURCE_UNRESOLVED:
            logger.warn("Job listing detected but job URL could not be extracted")
        else:
            logger.detail("No attached LinkedIn job listing found")

        for apply_url in apply_urls:
            logger.info("Apply link detected in post")
            logger.ok(f"Apply URL extracted: {apply_url}")

        has_image, image_url = _extract_image_info(element)
        if has_image:
            logger.info("Image-based job post detected")
            if image_url:
                logger.detail("Attached image detected")
            else:
                logger.detail("Attached media detected")

        return Post(
            author=author,
            text=text,
            url=url,
            urn=urn,
            job_url=job_url,
            apply_urls=apply_urls,
            has_image=has_image,
            image_url=image_url,
            element=element,
        )
    except Exception as exc:
        logger.warn(f"Post cannot be read: {exc}")
        return None
