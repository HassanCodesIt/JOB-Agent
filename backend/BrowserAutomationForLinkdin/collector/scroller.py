from __future__ import annotations

import json
import random
from typing import Iterator, List, Optional

from collector import logger, safety
from collector.browser import human_delay
from collector.models import Post
from collector.post_reader import POST_SELECTORS, read_post

SEE_MORE_SELECTORS = (
    "button[data-testid='expandable-text-button']",
    "button.feed-shared-inline-show-more-text",
    "button:has-text('see more')",
    "button:has-text('Show more')",
    "button:has-text('…more')",
    ".feed-shared-inline-show-more-text",
    "button[aria-label*='see more' i]",
)

MIN_SCROLL = 700
MAX_SCROLL = 1100


def _element_key(element, index: int) -> str:
    for attribute in ("data-id", "data-urn", "data-identifier", "componentkey", "id"):
        try:
            value = element.get_attribute(attribute)
        except Exception:
            value = None
        if value:
            return f"{attribute}:{value}"
    try:
        text = (element.inner_text() or "")[:160]
    except Exception:
        text = ""
    return f"idx:{index}:{hash(text)}"


def expand_see_more(page, limit: int = 5) -> int:
    """Click 'see more' controls so full post text becomes available."""
    expanded = 0
    for selector in SEE_MORE_SELECTORS:
        try:
            buttons = page.locator(selector)
            total = min(buttons.count(), limit)
        except Exception:
            continue
        for index in range(total):
            try:
                button = buttons.nth(index)
                if not button.is_visible():
                    continue
                button.click(timeout=1500, force=True)
                expanded += 1
            except Exception:
                continue
        if expanded:
            break
    return expanded


def _scroll_down(page, amount: Optional[int] = None) -> int:
    distance = amount or random.randint(MIN_SCROLL, MAX_SCROLL)
    try:
        page.mouse.wheel(0, distance)
    except Exception:
        try:
            page.evaluate("(y) => window.scrollBy(0, y)", distance)
        except Exception:
            return 0
    return distance


def _count_posts(page) -> int:
    try:
        return len(page.query_selector_all(POST_SELECTORS[0]))
    except Exception:
        return 0


def _above_current_view(element) -> bool:
    """True when the post card lies entirely above the current viewport.

    Bounding boxes are viewport-relative, so a card that scrolled past the top
    of the window has a negative bottom edge. Cards that are still partly on
    screen (or below it) are kept: they are what a continuation has to read.
    """
    try:
        box = element.bounding_box()
    except Exception:
        return False
    if not box:
        return False
    return float(box.get("y", 0)) + float(box.get("height", 0)) <= 0


def _wait_for_more_posts(page, previous_count: int, timeout_ms: int = 3500) -> None:
    payload = json.dumps({"selector": POST_SELECTORS[0], "previous": previous_count})
    script = """
    (payload) => {
        const { selector, previous } = JSON.parse(payload);
        return document.querySelectorAll(selector).length > previous;
    }
    """
    try:
        page.wait_for_function(script, arg=payload, timeout=timeout_ms, polling=400)
    except Exception:
        pass


def iter_post_batches(
    page, cfg, stats=None, start_from_current_view: bool = False
) -> Iterator[List[Post]]:
    """Scroll the Posts results, yielding newly seen posts batch by batch.

    ``start_from_current_view`` marks the posts that already sit above the
    current viewport as seen on the first pass, so a continuation begins at
    what is on screen now instead of re-reading the page from its top.
    """
    seen = set()
    empty_streak = 0
    first_pass = True

    for scroll_index in range(max(1, cfg.max_scrolls)):
        expand_see_more(page)
        elements = []
        for selector in POST_SELECTORS:
            try:
                elements = page.query_selector_all(selector)
                if elements:
                    break
            except Exception:
                elements = []

        fresh_elements = []
        for index, element in enumerate(elements):
            key = _element_key(element, index)
            if first_pass and start_from_current_view and _above_current_view(element):
                seen.add(key)
                continue
            if key in seen:
                continue
            seen.add(key)
            fresh_elements.append(element)
        first_pass = False

        posts: List[Post] = []
        for element in fresh_elements:
            post = read_post(element)
            if post is None:
                if stats is not None:
                    stats.unreadable_posts += 1
                continue
            posts.append(post)

        if posts:
            empty_streak = 0
            logger.detail(f"    scroll {scroll_index + 1}: +{len(posts)} new posts")
            yield posts
        else:
            empty_streak += 1
            logger.detail(f"    scroll {scroll_index + 1}: no new posts")
            if empty_streak >= max(1, cfg.empty_scroll_limit):
                logger.info("No new posts appeared after repeated scrolls, stopping this search.")
                return

        safety.guard(page, "scrolling search results")

        baseline = _count_posts(page)
        distance = _scroll_down(page)
        human_delay(page, cfg.action_delay)
        logger.detail(f"    scrolled {distance}px")
        _wait_for_more_posts(page, baseline)

    logger.detail("    max scrolls reached for this role.")