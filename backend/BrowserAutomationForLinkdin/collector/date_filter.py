"""Date posted filter helpers for LinkedIn search results.

The Date posted menu was read out of the live DOM (Chrome 153 / LinkedIn) rather
than guessed at. What LinkedIn actually renders, per option, is:

    <div aria-label="Filter by Date posted"><label>Date posted</label></div>
    ... clicking that opens a popover with no role and no aria-label, holding ...
    <div>
      <div>
        <div aria-hidden="true">
          <input id="_r_XXX_" type="radio" aria-label="Past 24 hours" tabindex="0">
          <label for="_r_XXX_"></label>          <!-- empty: draws the circle -->
        </div>
        <div><p><span>Past 24 hours</span></p></div>   <!-- the only visible text -->
      </div>
      ... identical rows for "Past week" and "Past month" ...
      <hr role="presentation">
      <button type="button" disabled>Reset</button>
      <a href="...?origin=FACETED_SEARCH" aria-disabled="false">Show results</a>
    </div>

Two properties of that markup decide everything below:

* The radio input sits under ``aria-hidden="true"``, which removes it from the
  accessibility tree, so every ``get_by_role("radio", ...)`` query returns
  nothing. It is also CSS-hidden (the sibling ``<label for=...>`` paints the
  circle instead), so ``is_visible()`` is False and ``check()``/``click()``
  cannot drive it. The text is *not* in the label, and the label is empty, so
  label-based queries find nothing either. The only handles that work are the
  exact visible text and the ``<label for=...>`` bound to the input.
* Once the facet is applied LinkedIn rewrites the button to
  ``aria-label="Filter by Past 24 hours"`` and adds ``datePosted=["past-24h"]``
  to the URL. Those two are the proof that the filter is genuinely active, and
  the URL is also what carries the filter across to the next role's search.

So selection is driven by exact semantic text and confirmed by reading the
radio's checked state, and success is only ever claimed from the applied state
LinkedIn itself renders.
"""
from __future__ import annotations

import time
from typing import Callable, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlsplit

from collector import logger
from collector.safety import NavigatorError

PAST_24H_TEXT = "Past 24 hours"
SHOW_RESULTS_TEXT = "Show results"

DATE_POSTED_SELECTORS: Sequence[str] = (
    "div[aria-label='Filter by Date posted'] label",
    "label:text-is('Date posted')",
    "[aria-label='Filter by Date posted']",
    "button[aria-label*='Date posted']",
    "button:has-text('Date posted')",
    "a:has-text('Date posted')",
)

DATE_POSTED_ROLE_NAMES: Sequence[str] = ("button", "link", "tab", "menuitem")

# The radio LinkedIn binds to the option. It is inspectable (checked state is
# the reliable selection proof) but must not be clicked directly.
PAST_24H_RADIO_SELECTOR = "input[type='radio'][aria-label='Past 24 hours']"

# Roles the option could expose if LinkedIn ever stops hiding the radio.
PAST_24H_ROLE_NAMES: Sequence[str] = ("radio", "menuitemradio", "option")

SHOW_RESULTS_ROLE_NAMES: Sequence[str] = ("link", "button")

# The chip LinkedIn renders for an already-applied facet.
APPLIED_CHIP_SELECTOR = "div[aria-label='Filter by Past 24 hours']"

# Query state LinkedIn writes itself once the facet is in effect.
DATE_POSTED_PARAM = "datePosted"
DATE_POSTED_TOKEN = "past-24h"

STRATEGY_SUMMARY = (
    "exact visible text | the empty <label for> bound to the radio | role=radio"
)

CLICK_TIMEOUT_MS = 6000
SHOW_RESULTS_TIMEOUT_MS = 8000
MENU_WAIT_MS = 8000
SELECT_WAIT_MS = 5000
VERIFY_WAIT_MS = 15000
POLL_INTERVAL_MS = 150


# --- waiting -----------------------------------------------------------------


def _wait(page, millis: int) -> None:
    try:
        page.wait_for_timeout(millis)
    except Exception:
        time.sleep(millis / 1000.0)


def _poll(page, predicate: Callable[[], bool], timeout_ms: int) -> bool:
    """Re-check ``predicate`` until it holds or the budget runs out."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        _wait(page, POLL_INTERVAL_MS)


def _click(locator, timeout: int) -> Optional[Exception]:
    """Click for real, then fall back to a DOM click. Returns the last error."""
    try:
        locator.click(timeout=timeout)
        return None
    except Exception as exc:
        first = exc
    try:
        locator.evaluate("el => el.click()")
        return None
    except Exception as exc:
        return first if first is not None else exc


def _require_click(error: Optional[Exception], what: str) -> None:
    if error is not None:
        raise NavigatorError(f"{what} could not be clicked: {error}") from error


def _visible(page, locator_factory: Callable[[], object]):
    """First element of a locator chain when it is actually on screen."""
    try:
        locator = locator_factory().first
        if locator.count() and locator.is_visible():
            return locator
    except Exception:
        pass
    return None


# --- applied state -----------------------------------------------------------


def url_has_past_24h(url: str) -> bool:
    """True when the URL carries LinkedIn's own ``datePosted`` facet state."""
    if not url:
        return False
    try:
        query = parse_qs(urlsplit(url).query)
    except ValueError:
        return False
    for value in query.get(DATE_POSTED_PARAM) or []:
        if DATE_POSTED_TOKEN in str(value).casefold():
            return True
    return False


def _applied_chip_visible(page) -> bool:
    return _visible(page, lambda: page.locator(APPLIED_CHIP_SELECTOR)) is not None


def _date_posted_applied(page) -> bool:
    """Real evidence that the facet is in effect, never a found text node."""
    return url_has_past_24h(getattr(page, "url", "") or "") or _applied_chip_visible(page)


# --- "Date posted" -----------------------------------------------------------


def _find_date_posted(page):
    for selector in DATE_POSTED_SELECTORS:
        found = _visible(page, lambda s=selector: page.locator(s))
        if found is not None:
            return found
    for role_name in DATE_POSTED_ROLE_NAMES:
        found = _visible(
            page, lambda r=role_name: page.get_by_role(r, name="Date posted", exact=True)
        )
        if found is not None:
            return found
    return None


# --- "Past 24 hours" ---------------------------------------------------------


def _radio_is_checked(page) -> bool:
    """The radio's checked state: what LinkedIn itself uses to remember a pick."""
    try:
        locator = page.locator(PAST_24H_RADIO_SELECTOR).first
        if locator.count() and locator.is_checked():
            return True
    except Exception:
        pass
    try:
        return bool(page.evaluate(
            "(sel) => { const r = document.querySelector(sel); return !!r && !!r.checked; }",
            PAST_24H_RADIO_SELECTOR,
        ))
    except Exception:
        return False


def _radio_id(page) -> str:
    try:
        return page.evaluate(
            "(sel) => { const r = document.querySelector(sel); return r ? (r.id || '') : ''; }",
            PAST_24H_RADIO_SELECTOR,
        ) or ""
    except Exception:
        return ""


def _past_24h_candidates(page) -> Sequence[Tuple[str, Callable[[], object]]]:
    """Ways to reach the option, most stable first, each built on demand.

    Exact visible text leads: it is the only handle LinkedIn exposes to the
    accessibility tree, and it is scoped to "Past 24 hours" so it can never
    resolve to "Past week" or "Past month".
    """

    def by_radio_label():
        radio_id = _radio_id(page)
        if not radio_id:
            return None
        return page.locator(f"label[for='{radio_id}']")

    candidates = [
        (f'exact visible text "{PAST_24H_TEXT}"', lambda: page.get_by_text(PAST_24H_TEXT, exact=True)),
        ("the <label for> bound to the radio", by_radio_label),
    ]
    for role_name in PAST_24H_ROLE_NAMES:
        candidates.append(
            (
                f"role={role_name}",
                lambda r=role_name: page.get_by_role(r, name=PAST_24H_TEXT, exact=True),
            )
        )
    return candidates


def _option_present(page) -> bool:
    try:
        if page.get_by_text(PAST_24H_TEXT, exact=True).count():
            return True
    except Exception:
        pass
    try:
        if page.locator(PAST_24H_RADIO_SELECTOR).count():
            return True
    except Exception:
        pass
    return False


def _wait_for_option(page, timeout: int = MENU_WAIT_MS) -> bool:
    """Wait for the menu LinkedIn renders after "Date posted" is clicked."""
    return _poll(page, lambda: _option_present(page), timeout)


def _select_past_24h(page, timeout: int = SELECT_WAIT_MS) -> str:
    """Select the option and return which strategy did it.

    Every strategy is confirmed against the radio's checked state, so finding
    the text alone can never be mistaken for a selection.
    """
    failures = []
    for description, factory in _past_24h_candidates(page):
        try:
            chain = factory()
            if chain is None:
                continue
            locator = chain.first
            if not locator.count():
                continue
        except Exception as exc:
            failures.append(f"{description}: {exc}")
            continue

        logger.detail(f'    -> "{PAST_24H_TEXT}" reached by {description}')
        _click(locator, CLICK_TIMEOUT_MS)

        if _poll(page, lambda: _radio_is_checked(page), timeout):
            return description

        failures.append(f"{description}: click left the radio unchecked")

    raise NavigatorError(
        f'"{PAST_24H_TEXT}" option not found in the Date posted menu '
        f"(tried: {STRATEGY_SUMMARY})."
        + (f" Detail: {'; '.join(failures)}" if failures else "")
    )


# --- "Show results" ----------------------------------------------------------


def _show_results_candidates(page) -> Sequence[Tuple[str, Callable[[], object]]]:
    candidates = [
        (f'role={role} named "{SHOW_RESULTS_TEXT}"', lambda r=role: page.get_by_role(r, name=SHOW_RESULTS_TEXT, exact=True))
        for role in SHOW_RESULTS_ROLE_NAMES
    ]
    candidates.append(
        (f'exact visible text "{SHOW_RESULTS_TEXT}"', lambda: page.get_by_text(SHOW_RESULTS_TEXT, exact=True))
    )
    return candidates


def _find_show_results(page, timeout: int = MENU_WAIT_MS):
    """Locate "Show results", waiting briefly: selecting a facet re-renders the
    menu and LinkedIn swaps the link for a button."""
    found = {}

    def locate() -> bool:
        for description, factory in _show_results_candidates(page):
            locator = _visible(page, factory)
            if locator is not None:
                found["locator"] = locator
                found["description"] = description
                return True
        return False

    if not _poll(page, locate, timeout):
        return None

    logger.detail(f'    -> "{SHOW_RESULTS_TEXT}" reached by {found["description"]}')
    return found["locator"]


def _wait_for_results_refresh(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    _wait(page, 400)


# --- shared DOM primitives ---------------------------------------------------
#
# Nothing below this line is Date posted specific. The sibling filter helper
# (collector/sort_filter.py) drives the very same popover shape -- a facet
# label, radio options LinkedIn hides from the accessibility tree, and a
# "Show results" link -- so it reuses these helpers rather than growing its own
# copies of them.


click_element = _click
require_click = _require_click
find_visible = _visible
poll_until = _poll
find_show_results = _find_show_results
wait_for_results_refresh = _wait_for_results_refresh


# --- entry point -------------------------------------------------------------


def apply_past_24_hours_filter(page) -> None:
    """Apply Date posted -> Past 24 hours, or refuse to let scraping continue."""
    logger.info("Applying LinkedIn date filter...")

    if _date_posted_applied(page):
        # LinkedIn keeps the facet in the URL when the keywords change, so the
        # later roles of a run arrive already filtered.
        logger.info(
            f'"{PAST_24H_TEXT}" is already active on this search; '
            f"LinkedIn carried the filter over from the previous keywords."
        )
        logger.ok(f"Date posted filter applied: {PAST_24H_TEXT}")
        logger.detail(f"    -> {getattr(page, 'url', '')}")
        return

    date_btn = _find_date_posted(page)
    if date_btn is None:
        raise NavigatorError('"Date posted" filter not found.')
    logger.info('Opening "Date posted" filter...')
    _require_click(_click(date_btn, CLICK_TIMEOUT_MS), '"Date posted" filter')

    if not _wait_for_option(page):
        raise NavigatorError(
            f'"{PAST_24H_TEXT}" option not found in the Date posted menu '
            f"(tried: {STRATEGY_SUMMARY})."
        )

    logger.info(f'Selecting "{PAST_24H_TEXT}"...')
    selected_by = _select_past_24h(page)
    logger.detail(f'    -> "{PAST_24H_TEXT}" selected via {selected_by}')

    show = _find_show_results(page)
    if show is None:
        raise NavigatorError('"Show results" button not found.')
    logger.info(f'Clicking "{SHOW_RESULTS_TEXT}"...')
    _require_click(_click(show, SHOW_RESULTS_TIMEOUT_MS), '"Show results" button')

    _wait_for_results_refresh(page)

    if not _poll(page, lambda: _date_posted_applied(page), VERIFY_WAIT_MS):
        raise NavigatorError(f'Could not verify that "{PAST_24H_TEXT}" was applied.')

    logger.ok(f"Date posted filter applied: {PAST_24H_TEXT}")
    logger.detail(f"    -> {getattr(page, 'url', '')}")