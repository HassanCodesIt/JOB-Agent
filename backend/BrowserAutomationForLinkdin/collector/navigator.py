from __future__ import annotations

import re
import time
from typing import List, Optional, Sequence
from urllib.parse import parse_qs, urlsplit

from collector import logger, safety
from collector.browser import human_delay
from collector.post_reader import POST_SELECTORS
from collector.safety import NavigatorError

SEARCH_BOX_SELECTORS: Sequence[str] = (
    "input[placeholder*='Search']",
    "input[data-id='typeahead']",
    "input[type='text'][role='combobox']",
    "input[aria-label*='Search']",
    ".search-global-typeahead input",
    "header input[type='text']",
)

RESULT_CONTAINER_SELECTORS: Sequence[str] = (
    "[data-testid='lazy-column']",
    "div.search-results",
    "section[aria-label='Primary content']",
    "main [data-id^='urn:li:']",
    "main [data-view-name='feed-full-update']",
)

POSTS_RESULT_SELECTORS: Sequence[str] = POST_SELECTORS

POSTS_FILTER_SELECTORS: Sequence[str] = (
    "div[aria-label='Filter by Posts'] label",
    "label:text-is('Posts')",
    "[aria-label='Filter by Posts']",
    "a[href*='/search/results/posts/']",
    "a[href*='/search/results/content/']",
    "button:has-text('Posts')",
    "a:has-text('Posts')",
    "[aria-label*='Posts']",
)

POSTS_FILTER_ROLE_NAMES: Sequence[str] = ("button", "link", "tab")

SEARCH_RESULTS_PREFIX = "/search/results/"
POSTS_VERTICAL_NAMES = ("content", "posts")

_SPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _SPACE_RE.sub(" ", (text or "").replace("\u00a0", " ")).strip().casefold()


def _url_keywords(url: str) -> str:
    """Read the keywords query parameter from a LinkedIn search URL."""
    try:
        query = parse_qs(urlsplit(url or "").query)
    except ValueError:
        return ""
    for key in ("keywords", "q"):
        values = query.get(key) or []
        if values:
            return _normalize(values[0])
    return ""


def search_scope(url: str) -> Optional[str]:
    """Return 'posts' or 'all' for a LinkedIn keyword-search results URL, else None."""
    try:
        path = urlsplit(url or "").path
    except ValueError:
        return None
    if not path.startswith(SEARCH_RESULTS_PREFIX):
        return None
    vertical = path[len(SEARCH_RESULTS_PREFIX):].strip("/")
    return "posts" if vertical in POSTS_VERTICAL_NAMES else "all"


def is_search_for(page, role: str) -> bool:
    """True when the tab already shows keyword results for exactly this role."""
    url = getattr(page, "url", "") or ""
    return search_scope(url) is not None and _url_keywords(url) == _normalize(role)


def available_filters(page) -> List[str]:
    """Names of the search filters LinkedIn currently offers (for diagnostics)."""
    names: List[str] = []
    try:
        nodes = page.query_selector_all("div[aria-label^='Filter by ']")
    except Exception:
        return names
    for node in nodes:
        try:
            text = (node.inner_text() or "").strip().split("\n")[0].strip()
            aria = (node.get_attribute("aria-label") or "").replace("Filter by", "").strip()
            name = text or aria
            if name and name not in names:
                names.append(name)
        except Exception:
            continue
    return names


def _report_missing_posts_filter(page) -> str:
    url = getattr(page, "url", "") or "(unknown)"
    try:
        title = page.title()
    except Exception:
        title = "(unavailable)"
    filters = available_filters(page)

    logger.warn("Could not find the LinkedIn Posts filter.")
    logger.info(f"Current URL: {url}")
    logger.info(f"Page title: {title}")
    logger.info(f"Available search filters: {', '.join(filters) if filters else '(none detected)'}")
    logger.detail(f"    tried: {' | '.join(POSTS_FILTER_SELECTORS)}")
    return f"Posts filter not found on {url}"


def _first_visible(page, selectors: Sequence[str], timeout: int = 6000):
    per_selector = max(500, timeout // max(1, len(selectors)))
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=per_selector)
            return locator
        except Exception:
            continue
    return None


def _find_posts_filter(page):
    for selector in POSTS_FILTER_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible():
                return locator
        except Exception:
            continue
    for role_name in POSTS_FILTER_ROLE_NAMES:
        try:
            locator = page.get_by_role(role_name, name="Posts", exact=True).first
            if locator.count() and locator.is_visible():
                return locator
        except Exception:
            continue
    return None


def _type_slowly(locator, text: str, per_char_ms: int = 70) -> None:
    """Type character by character; raise when no strategy worked."""
    errors = []
    for method_name in ("press_sequentially", "type"):
        method = getattr(locator, method_name, None)
        if method is None:
            continue
        try:
            method(text, delay=per_char_ms)
            return
        except Exception as exc:
            errors.append(f"{method_name}: {exc}")
    raise NavigatorError(
        "Could not type into the search box (" + "; ".join(errors) + ")"
    )


def _set_search_text(
    page, locator, role: str, use_keystrokes: bool = False
) -> None:
    """Put the role into the search box without a pointer click.

    The header search input is partially covered by the nav buttons, so a real
    click can be rejected as intercepted; fill()/keyboard focus cannot.

    ``use_keystrokes`` sends one key event per character. LinkedIn occasionally
    ignores a programmatic fill and searches for an empty query, so the submit
    helper escalates to this slower but faithful path.
    """
    if use_keystrokes:
        locator.evaluate("el => el.focus()")
        page.keyboard.press("ControlOrMeta+A")
        page.keyboard.press("Delete")
        _type_slowly(locator, role)
        return

    try:
        locator.fill(role)
        return
    except Exception as exc:
        first_error = exc
    try:
        locator.evaluate("el => el.focus()")
        page.keyboard.press("ControlOrMeta+A")
        page.keyboard.press("Delete")
        _type_slowly(locator, role)
        return
    except NavigatorError:
        raise
    except Exception as exc:
        raise NavigatorError(
            f"Could not type '{role}' into the search box ({first_error}; then {exc})"
        ) from exc


def _wait_for_keywords(page, role: str, timeout: int = 8000) -> bool:
    """Poll the address bar until it carries the requested keywords."""
    deadline = time.monotonic() + timeout / 1000.0
    while time.monotonic() < deadline:
        if is_search_for(page, role):
            return True
        try:
            page.wait_for_timeout(200)
        except Exception:
            break
    return is_search_for(page, role)


def _submit_search(page, locator, role: str, cfg, attempts: int = 3) -> None:
    """Submit the search and confirm the keywords reached the address bar.

    LinkedIn's header search sometimes drops a programmatically filled value and
    navigates to the vertical without any ``keywords`` parameter. Each retry
    escalates from ``fill()`` to per-character keystrokes.
    """
    last_url = getattr(page, "url", "") or ""
    for attempt in range(1, attempts + 1):
        _set_search_text(page, locator, role, use_keystrokes=attempt > 1)
        human_delay(page, cfg.action_delay)

        try:
            locator.press("Enter")
        except Exception as exc:
            raise NavigatorError(
                f"Could not submit the search for '{role}': {exc}"
            ) from exc

        if _wait_for_keywords(page, role):
            return

        last_url = getattr(page, "url", "") or ""
        logger.warn(
            f"Search for '{role}' reached the page without the keywords "
            f"(attempt {attempt}/{attempts}). Current URL: {last_url}"
        )

    raise NavigatorError(
        f"Search results for '{role}' did not load. Current URL: {last_url}"
    )


def _posts_filter_is_active(page) -> bool:
    if search_scope(getattr(page, "url", "") or "") == "posts":
        return True
    try:
        box = page.locator("input[aria-label='Filter by Posts']")
        if box.count() and box.first.is_checked():
            return True
    except Exception:
        pass
    return False


def search_role(page, role: str, cfg) -> None:
    """Show keyword search results for the role, reusing the tab when possible."""
    if is_search_for(page, role):
        logger.info(f'Reusing the current search results for: "{role}"')
        logger.detail(f"    -> {page.url}")
        _wait_for_results(page, timeout=10000)
        safety.guard(page, f"reusing the results for '{role}'")
        return

    logger.info(f'Searching LinkedIn for: "{role}"')

    locator = _first_visible(page, SEARCH_BOX_SELECTORS)
    if locator is None:
        raise NavigatorError("Search box not found on the current page.")

    _submit_search(page, locator, role, cfg)
    human_delay(page, cfg.page_load_delay)

    _wait_for_results(page, timeout=15000)
    safety.guard(page, f"searching for '{role}'")

    if not is_search_for(page, role):
        raise NavigatorError(
            f"Search results for '{role}' did not load. Current URL: {page.url}"
        )

    logger.info(f'Search results loaded for: "{role}"')
    logger.detail(f"    -> {page.url}")


def select_posts_filter(page, role: str = "", cfg=None) -> None:
    """Click the Posts filter and confirm Posts results are actually shown."""
    if is_search_for(page, role) and _posts_filter_is_active(page):
        logger.info("Posts filter already selected; reusing the current results.")
        logger.detail(f"    -> {page.url}")
        _verify_posts_results(page, role)
        return

    locator = _find_posts_filter(page)
    if locator is None:
        raise NavigatorError(_report_missing_posts_filter(page))

    logger.info("Posts filter found")
    logger.info("Clicking Posts filter")
    before = getattr(page, "url", "")
    try:
        locator.click(timeout=6000)
    except Exception:
        try:
            locator.evaluate("el => el.click()")
        except Exception as exc:
            raise NavigatorError(f"Posts filter could not be clicked: {exc}") from exc

    delay = tuple(cfg.action_delay) if cfg is not None else (1.0, 2.0)
    human_delay(page, delay)
    _verify_posts_results(page, role)

    if before and before != getattr(page, "url", ""):
        logger.detail(f"    -> {page.url}")


def _verify_posts_results(page, role: str) -> None:
    _wait_for_results(page, timeout=15000, require_posts=True)
    safety.guard(page, f"applying the Posts filter{f' for {role}' if role else ''}")

    if not _posts_filter_is_active(page):
        raise NavigatorError(
            "The Posts filter was clicked but Posts results are not active. "
            f"Current URL: {getattr(page, 'url', '')}"
        )

    logger.ok("Posts filter selected")
    logger.info("Posts results loaded")


def _wait_for_results(page, timeout: int = 15000, require_posts: bool = False) -> None:
    selectors = POSTS_RESULT_SELECTORS if require_posts else RESULT_CONTAINER_SELECTORS
    try:
        page.wait_for_selector(", ".join(selectors), timeout=timeout, state="attached")
    except Exception:
        safety.guard(page, "waiting for search results")
        if require_posts:
            raise NavigatorError("Posts results did not load in time.")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass