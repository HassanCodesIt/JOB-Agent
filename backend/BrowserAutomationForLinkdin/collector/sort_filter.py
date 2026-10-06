"""Sort by -> Latest / Top match helpers for LinkedIn search results.

The Sort by menu was read out of the live DOM (Chrome 153 / LinkedIn, Posts
vertical) rather than guessed at. What LinkedIn actually renders is the same
shape as the Date posted facet this project already drives, so
``date_filter``'s DOM primitives are reused instead of reimplemented:

    <div aria-label="Filter by Sort by">
      <input id="_r_XXX_" type="checkbox">      <!-- checked once a sort is on -->
      <label for="_r_XXX_">Sort by<svg caret/></label>
    </div>
    ... clicking that label opens a popover with no role and no aria-label, holding ...
    <div>
      <div>
        <div aria-hidden="true">
          <input id="_r_YYY_" type="radio" aria-label="Top Match" tabindex="0">
          <label for="_r_YYY_"></label>          <!-- empty: draws the circle -->
        </div>
        <div><p><span>Top Match</span></p></div> <!-- the only visible text -->
      </div>
      ... an identical row for "Latest" ...
      <hr role="presentation">
      <button type="button" disabled>Reset</button>
      <a href="...?origin=FACETED_SEARCH" aria-disabled="false">Show results</a>
    </div>

Four properties of that markup decide everything below.

* As with Date posted, the radio input sits under ``aria-hidden="true"``, so
  every ``get_by_role("radio", ...)`` query returns nothing, and the input is
  CSS-hidden behind its empty ``<label for=...>``. The only handles that work
  are the exact visible text and that label. The radio's ``checked`` state is
  still inspectable, which is what proves a selection actually took.
* Once a sort is applied LinkedIn rewrites the facet control to
  ``aria-label="Filter by Latest"`` / ``"Filter by Top Match"``, marks its
  checkbox ``checked``, and adds ``sortBy`` to the URL -- ``["date_posted"]``
  for Latest and ``["relevance"]`` for Top match. Those are the proofs that the
  sort is genuinely in effect, and the URL is also what carries it across to the
  next role's search.
* That rewrite is why the visible option text cannot be looked up page-wide:
  the applied chip's own label reads "Latest" too. Every text candidate is
  therefore rejected unless it sits outside the applied-filter row.
* LinkedIn capitalises the option as "Top Match" while the run is named "Top
  match", so both spellings are accepted when matching and the run's own
  spelling is what gets reported.

So selection is driven by exact semantic text scoped to the menu, confirmed by
the radio's checked state, and success is only ever claimed from the applied
state LinkedIn itself renders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlsplit

from collector import logger
from collector.date_filter import (
    SHOW_RESULTS_TEXT,
    click_element,
    find_show_results,
    find_visible,
    poll_until,
    require_click,
    wait_for_results_refresh,
)
from collector.safety import NavigatorError

SORT_BY_TEXT = "Sort by"

SORT_LATEST = "latest"
SORT_TOP_MATCH = "top_match"


@dataclass(frozen=True)
class SortOption:
    """One Sort by choice, and how LinkedIn renders it.

    ``display`` is the spelling the collector reports, which is what the run is
    called. ``visible_texts`` lists every spelling LinkedIn may paint, because
    only the visible text reaches the accessibility tree. ``url_token`` is the
    value LinkedIn itself writes into ``sortBy`` once the choice is applied.
    """

    mode: str
    display: str
    visible_texts: Tuple[str, ...]
    aria_label: str
    url_token: str

    @property
    def radio_selector(self) -> str:
        return f"input[type='radio'][aria-label='{self.aria_label}']"

    @property
    def chip_selector(self) -> str:
        return f"div[aria-label='Filter by {self.aria_label}']"


# LinkedIn's own tokens, read from the address bar after applying each choice.
SORT_OPTIONS = {
    SORT_LATEST: SortOption(
        mode=SORT_LATEST,
        display="Latest",
        visible_texts=("Latest",),
        aria_label="Latest",
        url_token="date_posted",
    ),
    SORT_TOP_MATCH: SortOption(
        mode=SORT_TOP_MATCH,
        display="Top match",
        visible_texts=("Top Match", "Top match"),
        aria_label="Top Match",
        url_token="relevance",
    ),
}

# The facet control, exactly as Date posted exposes its own.
SORT_BY_SELECTORS: Sequence[str] = (
    "div[aria-label='Filter by Sort by'] label",
    "label:text-is('Sort by')",
    "[aria-label='Filter by Sort by']",
    "button[aria-label*='Sort by']",
    "button:has-text('Sort by')",
    "a:has-text('Sort by')",
)

SORT_BY_ROLE_NAMES: Sequence[str] = ("button", "link", "tab", "menuitem")

# The facet control's own aria-label once a choice is on it. Used to *change* an
# already applied sort, which the unselected "Sort by" label cannot do on its own.
APPLIED_CHIP_SELECTORS: Sequence[str] = tuple(
    f"div[aria-label='Filter by {option.aria_label}'] label"
    for option in SORT_OPTIONS.values()
)

# Every applied facet renders as div[aria-label^='Filter by ...']. Anything inside
# one is the filter row, never the popover, so text lookups must skip it.
CHIP_ANCESTOR_SELECTOR = "div[aria-label^='Filter by ']"

# Roles the option could expose if LinkedIn ever stops hiding the radio.
OPTION_ROLE_NAMES: Sequence[str] = ("radio", "menuitemradio", "option")

# Query state LinkedIn writes itself once the sort is in effect.
SORT_PARAM = "sortBy"

STRATEGY_SUMMARY = (
    "exact visible text outside the filter row | the empty <label for> bound to the radio"
)

CLICK_TIMEOUT_MS = 6000
SHOW_RESULTS_TIMEOUT_MS = 8000
MENU_WAIT_MS = 8000
SELECT_WAIT_MS = 5000
VERIFY_WAIT_MS = 15000


# --- modes -------------------------------------------------------------------


def _normalize_mode(sort_mode: Optional[str]) -> str:
    return (sort_mode or "").strip().casefold().replace("-", "_").replace(" ", "_")


def resolve_sort_option(sort_mode: Optional[str]) -> SortOption:
    """Look up the requested sort mode, refusing an unknown one."""
    option = SORT_OPTIONS.get(_normalize_mode(sort_mode))
    if option is None:
        supported = ", ".join(sorted(SORT_OPTIONS))
        raise NavigatorError(
            f'Unknown sort mode: {sort_mode!r}. Supported modes: {supported}.'
        )
    return option


# --- applied state -----------------------------------------------------------


def url_has_sort(url: str, option: SortOption) -> bool:
    """True when the URL carries LinkedIn's own ``sortBy`` state for this option."""
    if not url:
        return False
    try:
        query = parse_qs(urlsplit(url).query)
    except ValueError:
        return False
    for value in query.get(SORT_PARAM) or []:
        if option.url_token in str(value).casefold():
            return True
    return False


def _chip_visible(page, option: SortOption) -> bool:
    return find_visible(page, lambda o=option: page.locator(o.chip_selector)) is not None


def _sort_applied(page, option: SortOption) -> bool:
    """Real evidence that the sort is in effect, never a found text node."""
    return url_has_sort(getattr(page, "url", "") or "", option) or _chip_visible(page, option)


# --- "Sort by" ---------------------------------------------------------------


def _find_sort_by(page):
    """The facet control, whether or not a sort is already on it.

    LinkedIn replaces the "Sort by" label with the applied chip once a choice is
    made, and only the chip reopens the menu. Both are checked so an already
    sorted search can still be re-sorted into the requested mode.
    """
    for selector in tuple(SORT_BY_SELECTORS) + tuple(APPLIED_CHIP_SELECTORS):
        found = find_visible(page, lambda s=selector: page.locator(s))
        if found is not None:
            return found
    for role_name in SORT_BY_ROLE_NAMES:
        found = find_visible(
            page, lambda r=role_name: page.get_by_role(r, name=SORT_BY_TEXT, exact=True)
        )
        if found is not None:
            return found
    return None


# --- the option --------------------------------------------------------------


def _fail(message: str) -> None:
    """Report the failure, then refuse to let scraping continue.

    The error line is printed here as well as raised, because these entry
    points promise a specific sort: a run that cannot reach it must say so
    loudly rather than quietly scrape unsorted results.
    """
    logger.error(message)
    raise NavigatorError(message)


def _select_failure_message(option: SortOption, failures: Sequence[str]) -> str:
    """Why selecting the option failed, led by the reported error line.

    The sort was offered by the menu but nothing proved it was chosen, which is
    exactly the unverifiable case the entry points promise never to scrape past.
    """
    detail = f" Detail: {'; '.join(failures)}" if failures else ""
    return (
        "Could not verify requested sort mode. "
        f'"{option.display}" was offered by the Sort by menu but no strategy '
        f"selected it (tried: {STRATEGY_SUMMARY}).{detail}"
    )


def _inside_chip(element) -> bool:
    """True when the element belongs to the applied-filter row, not the menu.

    An unreadable element counts as inside, so an option is only ever clicked
    when it has been positively placed in the popover. Two details matter here:
    the selector is passed in rather than interpolated, because it contains
    quotes of its own, and it arrives as the *second* argument because Playwright
    hands a locator's element to a locator script first.
    """
    try:
        return bool(
            element.evaluate("(el, sel) => !!el.closest(sel)", CHIP_ANCESTOR_SELECTOR)
        )
    except Exception:
        return True


def _outside_chip_text(page, option: SortOption):
    """The first exact-text match that is not part of the applied-filter row."""
    for text in option.visible_texts:
        try:
            chain = page.get_by_text(text, exact=True)
            total = chain.count()
        except Exception:
            continue
        for index in range(total):
            try:
                element = chain.nth(index)
                if not element.is_visible() or _inside_chip(element):
                    continue
                return element
            except Exception:
                continue
    return None


def _option_present(page, option: SortOption) -> bool:
    """Whether the menu LinkedIn renders offers this option at all."""
    try:
        if _outside_chip_text(page, option) is not None:
            return True
    except Exception:
        pass
    try:
        if page.locator(option.radio_selector).count():
            return True
    except Exception:
        pass
    return False


def _wait_for_option(page, option: SortOption, timeout: int = MENU_WAIT_MS) -> bool:
    """Wait for the menu LinkedIn renders after "Sort by" is clicked."""
    return poll_until(page, lambda: _option_present(page, option), timeout)


def _radio_id(page, option: SortOption) -> str:
    try:
        return page.evaluate(
            "(sel) => { const r = document.querySelector(sel); return r ? (r.id || '') : ''; }",
            option.radio_selector,
        ) or ""
    except Exception:
        return ""


def _radio_is_checked(page, option: SortOption) -> bool:
    """The radio's checked state: what LinkedIn itself uses to remember a pick."""
    try:
        locator = page.locator(option.radio_selector).first
        if locator.count() and locator.is_checked():
            return True
    except Exception:
        pass
    try:
        return bool(page.evaluate(
            "(sel) => { const r = document.querySelector(sel); return !!r && !!r.checked; }",
            option.radio_selector,
        ))
    except Exception:
        return False


def _option_candidates(page, option: SortOption) -> Sequence[Tuple[str, Callable[[], object]]]:
    """Ways to reach the option, most stable first, each built on demand.

    Exact visible text leads, for the same reason it does in date_filter: the
    radio is hidden from the accessibility tree, so it is the only handle that
    survives. The difference here is the scoping described in the module
    docstring, which keeps a lookup from resolving to the applied chip.
    """

    def by_radio_label():
        radio_id = _radio_id(page, option)
        if not radio_id:
            return None
        return page.locator(f"label[for='{radio_id}']")

    def by_text():
        return _outside_chip_text(page, option)

    candidates = [
        (f'exact visible text "{option.visible_texts[0]}" outside the filter row', by_text),
        ("the <label for> bound to the radio", by_radio_label),
    ]
    for role_name in OPTION_ROLE_NAMES:
        candidates.append(
            (
                f"role={role_name}",
                lambda r=role_name, o=option: page.get_by_role(
                    r, name=o.display, exact=False
                ),
            )
        )
    return candidates


def _select_option(page, option: SortOption, timeout: int = SELECT_WAIT_MS) -> str:
    """Select the option and return which strategy did it.

    Every strategy is confirmed against the radio's checked state, so finding
    the text alone can never be mistaken for a selection.
    """
    failures = []
    for description, factory in _option_candidates(page, option):
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

        logger.detail(f'    -> "{option.display}" reached by {description}')
        click_element(locator, CLICK_TIMEOUT_MS)

        if poll_until(page, lambda o=option: _radio_is_checked(page, o), timeout):
            return description

        failures.append(f"{description}: click left the radio unchecked")

    _fail(_select_failure_message(option, failures))


# --- entry point -------------------------------------------------------------


def apply_sort_filter(page, sort_mode: Optional[str] = None) -> None:
    """Apply Sort by -> the requested mode, or refuse to let scraping continue."""
    option = resolve_sort_option(sort_mode)
    logger.info("Applying LinkedIn sort filter...")

    if _sort_applied(page, option):
        # LinkedIn keeps the facet in the URL when the keywords change, so the
        # later roles of a run arrive already sorted.
        logger.info(
            f'"{option.display}" is already active on this search; '
            f"LinkedIn carried the sort over from the previous keywords."
        )
        logger.ok(f"Sort applied: {option.display}")
        logger.detail(f"    -> {getattr(page, 'url', '')}")
        return

    sort_by = _find_sort_by(page)
    if sort_by is None:
        _fail(f'"{SORT_BY_TEXT}" filter not found.')
    logger.info(f'Opening "{SORT_BY_TEXT}"...')
    require_click(click_element(sort_by, CLICK_TIMEOUT_MS), f'"{SORT_BY_TEXT}" filter')

    if not _wait_for_option(page, option):
        _fail(f'"{option.display}" sort option not found.')

    logger.info(f'Selecting "{option.display}"...')
    selected_by = _select_option(page, option)
    logger.detail(f'    -> "{option.display}" selected via {selected_by}')

    show = find_show_results(page)
    if show is None:
        _fail(f'"{SHOW_RESULTS_TEXT}" button not found.')
    logger.info(f'Clicking "{SHOW_RESULTS_TEXT}"...')
    require_click(click_element(show, SHOW_RESULTS_TIMEOUT_MS), f'"{SHOW_RESULTS_TEXT}" button')

    wait_for_results_refresh(page)

    if not poll_until(page, lambda o=option: _sort_applied(page, o), VERIFY_WAIT_MS):
        _fail("Could not verify requested sort mode.")

    logger.ok(f"Sort applied: {option.display}")
    logger.detail(f"    -> {getattr(page, 'url', '')}")