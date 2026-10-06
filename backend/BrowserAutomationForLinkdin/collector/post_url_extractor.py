"""Rebuild a LinkedIn post permalink from the post's own DOM.

LinkedIn does not always render an obvious ``<a href>`` for a post, and the
absence of one says nothing about whether the post can be identified. The
lookup below therefore walks an ordered list of places where the identifier
can live, cheapest and most authoritative first:

1. a permalink anchor directly associated with the post;
2. any other anchor in the post that carries the post's own URN;
3. data attributes holding an activity/post URN (on the card and its parents);
4. any attribute value or inline script holding a LinkedIn URN;
5. accessible controls (``aria-label`` / ``data-control-name``) such as the
   "Copy link to post" item;
6. the component state LinkedIn attaches to the card's DOM nodes, where the
   post's ``stateKey`` carries the exact URN.

Two rules apply throughout:

* nothing here clicks, navigates or issues a request - it only reads what the
  page already contains;
* a URL is only ever reported when a real identifier was found. Ambiguous
  evidence yields no URL rather than a guessed one, and the caller prints
  "Not found".

The "..." menu is deliberately *not* part of this module's default path: see
:func:`copy_link_via_menu`, which is an opt-in last resort.
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Tuple
from urllib.parse import parse_qsl, unquote, urlsplit

# Reported source of a permalink, in priority order.
SOURCE_PERMALINK_LINK = "permalink link"
SOURCE_DATA_ATTRIBUTE = "data attribute"
SOURCE_ACTIVITY_ID = "activity id attribute"
SOURCE_INLINE_IDENTIFIER = "inline identifier"
SOURCE_ACCESSIBLE_CONTROL = "accessible control"
SOURCE_COMPONENT_STATE = "component state"
SOURCE_SLUG_LINK = "post slug link"
SOURCE_NOT_FOUND = "not found"

PERMALINK_BASE = "https://www.linkedin.com/feed/update/"

# LinkedIn serves the same post for urn:li:activity, urn:li:ugcPost and
# urn:li:share forms of one id; activity is the canonical permalink spelling.
_CANONICAL_KINDS = ("activity", "ugcPost", "share")

_URN_RE = re.compile(r"urn:li:(activity|share|ugcPost|fsd_update|article):(\d+)", re.IGNORECASE)
_URN_KIND_RE = re.compile(r"^urn:li:([A-Za-z]+):(\d+)$", re.IGNORECASE)
_NUMERIC_ID_RE = re.compile(r"^\d{6,25}$")
_SLASHES_RE = re.compile(r"/{2,}")
_PERMALINK_PATH_RE = re.compile(r"/feed/update/", re.IGNORECASE)
_POSTS_PATH_RE = re.compile(r"linkedin\.com/posts/[A-Za-z0-9_\-]+", re.IGNORECASE)
_JOB_VIEW_RE = re.compile(r"/jobs/view/\d+", re.IGNORECASE)

# Attributes that are known to carry a post/activity/share identifier.
_ID_ATTRIBUTES = (
    "data-urn",
    "data-id",
    "data-identifier",
    "data-entity-urn",
    "data-entity-id",
    "data-activity-urn",
    "data-activity-id",
    "data-update-urn",
    "data-update-id",
    "data-share-urn",
    "data-share-id",
    "data-trackable-id",
    "data-feed-id",
    "data-li-id",
    "data-test-id",
    "id",
)

# Attributes whose value may be a bare numeric activity id.
_NUMERIC_ID_ATTRIBUTES = (
    "data-activity-id",
    "data-entity-id",
    "data-update-id",
    "data-share-id",
    "data-trackable-id",
    "data-feed-id",
)

_PERMALINK_CONTROL_RE = re.compile(
    r"(copy link to post|copy link|post link|post permalink|permalink|link to (this )?post)",
    re.IGNORECASE,
)

PERMALINK_LINK_SELECTOR = "a[href]"
REACT_SCAN_LIMIT = 700

# One round trip collects steps 3-6. Written defensively: any single failure
# (missing property, exotic object, changed build) returns an empty bucket
# instead of breaking the read.
#
# The card arrives as the first argument (Playwright does not bind ``this``),
# and the scan limit as the second.
_SCAN_JS = r"""
function (root, limit) {
  const URN_RE = /urn:li:(activity|share|ugcPost|fsd_update|article):\d+/i;
  const NUM_RE = /^\d{6,25}$/;
  const ID_ATTRS = ["data-urn", "data-id", "data-identifier", "data-entity-urn",
    "data-entity-id", "data-activity-urn", "data-activity-id", "data-update-urn",
    "data-update-id", "data-share-urn", "data-share-id", "data-trackable-id",
    "data-feed-id", "data-li-id", "data-test-id", "id"];
  const NUM_ATTRS = ["data-activity-id", "data-entity-id", "data-update-id",
    "data-share-id", "data-trackable-id", "data-feed-id"];
  const CTRL_RE = /copy link to post|copy link|post link|post permalink|permalink|link to (this )?post/i;

  const out = { idUrns: [], numericIds: [], attrUrns: [], scriptUrns: [],
                controlUrns: [], reactTally: {} };

  // step 3 - identifier attributes on the card and its parents
  let node = root;
  let hops = 0;
  while (node && hops < 5) {
    for (const a of ID_ATTRS) {
      let v = null;
      try { v = node.getAttribute(a); } catch (e) { v = null; }
      if (!v) continue;
      const m = String(v).match(URN_RE);
      if (m) out.idUrns.push(m[0]);
      else if (NUM_ATTRS.indexOf(a) >= 0 && NUM_RE.test(String(v).trim())) {
        out.numericIds.push(String(v).trim());
      }
    }
    node = node.parentElement;
    hops++;
  }

  // steps 4 and 5 - everything inside the card
  const all = [root].concat(Array.prototype.slice.call(root.querySelectorAll('*')));
  for (const el of all) {
    for (const a of el.attributes) {
      const v = String(a.value || '');
      if (!v) continue;
      const m = v.match(URN_RE);
      if (m) out.attrUrns.push(m[0]);
    }
    const label = [el.getAttribute && el.getAttribute('aria-label'),
                   el.getAttribute && el.getAttribute('data-control-name'),
                   el.id].filter(Boolean).join(' ');
    if (label && CTRL_RE.test(label)) {
      const href = el.getAttribute && el.getAttribute('href');
      if (href) {
        const m = String(href).match(URN_RE);
        if (m) out.controlUrns.push(m[0]);
      }
      const val = el.getAttribute && el.getAttribute('data-urn');
      if (val) {
        const m = String(val).match(URN_RE);
        if (m) out.controlUrns.push(m[0]);
      }
    }
  }

  for (const s of root.querySelectorAll('script')) {
    const t = s.textContent || '';
    const m = t.match(URN_RE);
    if (m) out.scriptUrns.push(m[0]);
  }

  // step 6 - the component state LinkedIn hangs off this card's own nodes
  const tally = out.reactTally;
  const bump = (urn) => { tally[urn] = (tally[urn] || 0) + 1; };
  const seen = new WeakSet();
  let scanned = 0;
  const queue = [];
  const push = (value, depth) => {
    if (!value || typeof value !== 'object' || depth > 3 || scanned > 12000) return;
    if (seen.has(value)) return;
    seen.add(value);
    scanned++;
    for (const key of Object.keys(value)) {
      let v;
      try { v = value[key]; } catch (e) { continue; }
      if (typeof v === 'string') {
        const m = v.match(URN_RE);
        if (m) bump(m[0]);
      } else if (v && typeof v === 'object') {
        if (Array.isArray(v)) { for (const x of v.slice(0, 6)) push(x, depth + 1); }
        else if (Object.getPrototypeOf(v) === Object.prototype) push(v, depth + 1);
      }
    }
  };

  for (let i = 0; i < all.length && i < limit; i++) {
    const el = all[i];
    for (const key of Object.keys(el)) {
      if (key.indexOf('__reactProps$') === 0) push(el[key], 0);
      else if (key.indexOf('__reactFiber$') === 0) {
        const fiber = el[key];
        if (fiber) { push(fiber.memoizedProps, 1); push(fiber.pendingProps, 1); }
      }
    }
  }
  return out;
}
"""


def _absolute(href: str) -> str:
    href = (href or "").strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://www.linkedin.com" + href
    return href


def find_urn(value: str) -> str:
    """The first LinkedIn URN inside a string, or ""."""
    if not value:
        return ""
    match = _URN_RE.search(str(value))
    return match.group(0) if match else ""


def canonical_urn(urn: str) -> str:
    """Prefer the activity spelling LinkedIn uses in permalinks.

    Returns "" for anything that is not a well-formed URN, so a malformed
    value can never be turned into a URL.
    """
    match = _URN_KIND_RE.match((urn or "").strip())
    if not match or not match.group(2).isdigit():
        return ""
    kind, number = match.group(1), match.group(2)
    if kind.lower() == "activity":
        return f"urn:li:activity:{number}"
    return f"urn:li:{kind}:{number}"


def permalink_for(urn: str) -> str:
    urn = canonical_urn(urn)
    return f"{PERMALINK_BASE}{urn}/" if urn else ""


def _clean_permalink(url: str) -> str:
    """Drop tracking noise while keeping the identifier intact."""
    url = url.split("?", 1)[0].split("#", 1)[0]
    head, sep, tail = url.partition("://")
    if sep:
        tail = _SLASHES_RE.sub("/", tail)
        return f"{head}{sep}{tail}"
    return _SLASHES_RE.sub("/", url)


def _collapse_slashes(url: str) -> str:
    """Tidy duplicate slashes without eating the protocol separator."""
    head, sep, tail = url.partition("://")
    if sep:
        return head + sep + _SLASHES_RE.sub("/", tail)
    return _SLASHES_RE.sub("/", url)


def permalink_from_href(href: str) -> str:
    """A permalink when this href already identifies the post, else "".

    Job listing links are explicitly rejected: the post URL and the job URL
    must stay separate fields.
    """
    href = (href or "").strip()
    if not href or href.startswith("#") or href.lower().startswith("javascript:"):
        return ""
    absolute = _collapse_slashes(_absolute(href))
    if _JOB_VIEW_RE.search(absolute):
        return ""
    urn = find_urn(absolute)
    if urn:
        # Anything exposing the post's URN identifies it, so tracking
        # parameters can be dropped safely.
        return _clean_permalink(permalink_for(urn))
    if _POSTS_PATH_RE.search(absolute):
        return _clean_permalink(absolute)
    return ""


_POST_HOSTS = frozenset({"linkedin.com", "www.linkedin.com", "lnkd.in", "www.lnkd.in"})

# Paths that are never a post permalink. The post URL is mandatory, so a URL
# pointing at one of these must be rejected outright rather than collected.
_NOT_POST_PATH_PREFIXES = (
    "/jobs",
    "/job",
    "/in",
    "/search",
    "/company",
    "/companies",
    "/school",
    "/mynetwork",
    "/pulse",
    "/events",
    "/learning",
    "/jobs-guest",
    "/feed/interest",
    "/feed/saved",
)


def validate_post_url(url: str) -> str:
    """Accept a URL only if it really is a LinkedIn post permalink.

    This is the last gate before a post URL is trusted, so it rejects every way
    a wrong URL can creep in: the job listing, the author's profile, the search
    page, another company's page, or a bare feed. A URL that fails validation
    returns "" and the caller keeps investigating.
    """
    candidate = (url or "").strip()
    if not candidate:
        return ""

    absolute = _collapse_slashes(_absolute(candidate))
    split = urlsplit(absolute)
    if split.netloc.lower() not in _POST_HOSTS:
        return ""
    if _JOB_VIEW_RE.search(absolute):
        return ""

    path = split.path or "/"
    for prefix in _NOT_POST_PATH_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return ""

    # Must actually identify a post: either the post's URN or its slug.
    if not find_urn(absolute) and not _POSTS_PATH_RE.search(absolute):
        return ""
    return permalink_from_href(absolute)


def _anchor_hrefs(element) -> List[str]:
    hrefs: List[str] = []
    for selector in (PERMALINK_LINK_SELECTOR, "a[href*='/feed/update/']", "a[href*='/posts/']"):
        try:
            anchors = list(element.query_selector_all(selector))
        except Exception:
            continue
        for anchor in anchors:
            try:
                href = anchor.get_attribute("href") or ""
            except Exception:
                continue
            if href:
                hrefs.append(href)
        if hrefs:
            break
    return hrefs


def _scan(element) -> Dict[str, object]:
    try:
        data = element.evaluate(_SCAN_JS, REACT_SCAN_LIMIT)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _strings(value) -> List[str]:
    return [item for item in (value or []) if isinstance(item, str) and item]


def _urn_number(urn: str) -> str:
    """The numeric id of a well-formed URN, else "".

    Validating the shape here means a malformed value can never reach
    :func:`permalink_for`, so no broken URL can be produced.
    """
    match = _URN_KIND_RE.match((urn or "").strip())
    if not match or not match.group(2).isdigit():
        return ""
    return match.group(2)


def _dominant_urn(tally: Dict[str, object]) -> str:
    """The most-repeated URN, or "" when the evidence is genuinely ambiguous.

    LinkedIn repeats the post's own ``stateKey`` across many nodes, so the
    winner is normally far ahead. Two different ids with the same score mean
    two candidate posts are embedded in the card, and guessing would risk
    attributing the wrong permalink. Spellings of one id (``activity`` and
    ``ugcPost``) are the same post, so they are not treated as a conflict.
    """
    pairs = [
        (urn, int(count or 0))
        for urn, count in (tally or {}).items()
        if _urn_number(urn)
    ]
    if not pairs:
        return ""
    best = max(count for _urn, count in pairs)
    winners = [urn for urn, count in pairs if count == best]

    numbers = {_urn_number(urn) for urn in winners}
    if len(numbers) > 1:
        return ""

    for urn in winners:
        if urn.strip().lower().startswith("urn:li:activity:"):
            return canonical_urn(urn)
    return canonical_urn(winners[0])


def _own_attribute_urn(element) -> Tuple[str, str]:
    """The card's own identifier attributes, read without a JS round trip.

    Returns ``(urn, numeric_id)``; either may be empty. This is the cheapest
    and most common case, so it is checked before anything heavier.
    """
    urn = ""
    numeric = ""
    for attribute in _ID_ATTRIBUTES:
        try:
            value = element.get_attribute(attribute)
        except Exception:
            continue
        if not value:
            continue
        found = find_urn(value)
        if found and not urn:
            urn = found
            continue
        text = str(value).strip()
        if not numeric and attribute in _NUMERIC_ID_ATTRIBUTES and _NUMERIC_ID_RE.match(text):
            numeric = text
    return urn, numeric


def extract_post_url(element) -> Tuple[str, str, str]:
    """The post permalink, its URN and how it was found.

    Order of evidence, most authoritative first:

    1. an anchor that exposes the post's URN - LinkedIn's own permalink form;
    2. an identifier data attribute, numeric activity id, inline identifier or
       accessible control carrying the URN;
    3. the post's component state, where the exact URN is present;
    4. an opaque ``/posts/<slug>`` link, which identifies the post but is the
       least stable spelling, so it is only used when nothing else does.

    Returns ``("", "", SOURCE_NOT_FOUND)`` when the post cannot be identified;
    the caller then reports "Not found" instead of guessing a URL.
    """
    hrefs = _anchor_hrefs(element)

    # Step 1-2: the post's own anchors, when they expose its URN.
    for href in hrefs:
        url = permalink_from_href(href)
        if url and find_urn(url):
            return url, canonical_urn(find_urn(href)), SOURCE_PERMALINK_LINK

    # Step 3: identifier attributes on the card itself.
    urn, numeric = _own_attribute_urn(element)
    if urn:
        return permalink_for(urn), canonical_urn(urn), SOURCE_DATA_ATTRIBUTE
    if numeric:
        urn = f"urn:li:activity:{numeric}"
        return permalink_for(urn), urn, SOURCE_ACTIVITY_ID

    scan = _scan(element)

    # Steps 3-5: ancestors' identifier attributes and inline identifiers.
    for urn in _strings(scan.get("idUrns")):
        return permalink_for(urn), canonical_urn(urn), SOURCE_DATA_ATTRIBUTE

    for numeric in _strings(scan.get("numericIds")):
        if _NUMERIC_ID_RE.match(numeric.strip()):
            urn = f"urn:li:activity:{numeric.strip()}"
            return permalink_for(urn), urn, SOURCE_ACTIVITY_ID

    for bucket in ("attrUrns", "scriptUrns", "controlUrns"):
        for urn in _strings(scan.get(bucket)):
            return permalink_for(urn), canonical_urn(urn), (
                SOURCE_ACCESSIBLE_CONTROL if bucket == "controlUrns" else SOURCE_INLINE_IDENTIFIER
            )

    # Step 6: the post's component state.
    urn = _dominant_urn(scan.get("reactTally") or {})
    if urn:
        return permalink_for(urn), urn, SOURCE_COMPONENT_STATE

    # Last resort: a permalink anchor that only carries LinkedIn's opaque slug.
    for href in hrefs:
        url = permalink_from_href(href)
        if url:
            return url, "", SOURCE_SLUG_LINK

    return "", "", SOURCE_NOT_FOUND


# --- opt-in fallback -------------------------------------------------------
#
# Some cards expose no identifier at all: no permalink anchor, no id
# attribute, and nothing usable in their React props. The only remaining
# source is the post's own "..." menu, so this path is what actually recovers
# those permalinks.

MENU_MORE_SELECTORS = (
    "button[aria-label*='Open control menu for post' i]",
    "button[aria-label*='control menu' i]",
    "button[data-control-name='post_control_menu']",
    "button[aria-label*='More options' i]",
    "button[aria-label*='more' i]",
    "button[data-control-name*='more' i]",
)

MENU_ITEM_SELECTORS = (
    "[role='menu'] [role='menuitem']",
    "[role='menu'] li",
    "[role='menu'] button",
    "[role='menu'] a",
    "[role='menuitem']",
)

MENU_COPY_ITEM_RE = re.compile(r"copy link to post", re.IGNORECASE)

_SHORT_LINK_RE = re.compile(r"^https?://lnkd\.in/", re.IGNORECASE)
_HIGHLIGHTED_URN_KEY = "highlightedupdateurn"


def _first_match(root, selectors):
    for selector in selectors:
        try:
            node = root.query_selector(selector)
        except Exception:
            continue
        if node is not None:
            return node
    return None


def _menu_copy_item(page):
    """The "Copy link to post" entry, wherever it sits in the open menu."""
    for selector in MENU_ITEM_SELECTORS:
        try:
            nodes = page.query_selector_all(selector)
        except Exception:
            continue
        for node in nodes or ():
            try:
                label = node.inner_text() or ""
            except Exception:
                continue
            if MENU_COPY_ITEM_RE.search(label):
                return node
    return None


def _page_request(page):
    try:
        return page.context.request
    except Exception:
        return None


def resolve_post_link(url: str, request=None) -> str:
    """Canonicalise a copied link into the post permalink.

    "Copy link to post" now yields a short ``lnkd.in`` link rather than the
    permalink. One request resolves it to the post page, whose
    ``highlightedUpdateUrn`` parameter carries the post's own URN, so the
    result stays in the same shape as a permalink read from the DOM.
    """
    url = (url or "").strip()
    if not url:
        return ""
    direct = permalink_from_href(url)
    if direct:
        return direct
    if not _SHORT_LINK_RE.match(url) or request is None:
        return ""

    try:
        response = request.get(url, max_redirects=10, timeout=30000)
    except Exception:
        return ""
    final = getattr(response, "url", "") or ""
    if not final:
        return ""

    query = urlsplit(final).query
    for key, value in parse_qsl(query):
        if key.lower() == _HIGHLIGHTED_URN_KEY:
            candidate = permalink_for(unquote(value))
            if candidate:
                return candidate
    return _clean_permalink(final) if _POSTS_PATH_RE.search(final) else ""


def _read_clipboard(page, attempts: int = 8, wait_ms: int = 250) -> str:
    """Read the clipboard, tolerating the write landing after the click."""
    for attempt in range(attempts):
        for expression in ("navigator.clipboard.readText()", "window.clipboardData.getData('Text')"):
            try:
                value = page.evaluate(expression)
            except Exception:
                continue
            if value:
                return value
        if attempt + 1 < attempts:
            page.wait_for_timeout(wait_ms)
    return ""


def copy_link_via_menu(page, element, timeout_ms: int = 5000, attempts: int = 2) -> str:
    """Open the post's own "..." menu and read "Copy link to post".

    Used only when the post's DOM exposes no permalink, and then only for a
    post that already qualified for collection. Because the post URL is a
    required field, this keeps trying: the menu is reopened and the clipboard
    re-read before giving up, since a menu that has not rendered yet is the
    usual reason a single attempt finds nothing.
    """
    if element is None:
        return ""

    for attempt in range(1, attempts + 1):
        try:
            button = _first_match(element, MENU_MORE_SELECTORS)
            if button is None:
                return ""
            try:
                button.scroll_into_view_if_needed(timeout=timeout_ms)
            except Exception:
                pass
            button.click(timeout=timeout_ms)

            item = None
            deadline = time.monotonic() + timeout_ms / 1000.0
            while item is None and time.monotonic() < deadline:
                item = _menu_copy_item(page)
                if item is None:
                    page.wait_for_timeout(150)
            if item is None:
                _dismiss_menu(page)
                continue

            item.click(timeout=timeout_ms)
            url = resolve_post_link(_read_clipboard(page), _page_request(page))
            if url:
                return url
        except Exception:
            pass
        finally:
            _dismiss_menu(page)
    return ""


def _dismiss_menu(page) -> None:
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass