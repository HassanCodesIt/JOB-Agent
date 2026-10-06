from __future__ import annotations

import contextlib
import logging
import random
from typing import Iterator, Optional, Sequence
from urllib.parse import urlsplit

from collector import logger

CHROME_LAUNCH_HINT = """
Chrome must already be running with remote debugging enabled.

Windows:
  chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\chrome-linkedin-profile"
macOS:
  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
    --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-linkedin-profile"
Linux:
  google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-linkedin-profile"

Then log into LinkedIn in that window and run this script again.
""".strip()

SEARCH_RESULTS_PREFIX = "/search/results/"
FEED_PATH = "/feed"


def is_linkedin_url(url: str) -> bool:
    """True for a real linkedin.com URL, checked on the host, not the string."""
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return False
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def linkedin_page_kind(url: str) -> str:
    """``'search'``, ``'feed'``, ``'other'`` for a LinkedIn page, else ``''``.

    A post permalink lives under ``/feed/update/...`` and is therefore
    ``'other'``: it is a single post, not the feed itself.
    """
    if not is_linkedin_url(url):
        return ""
    try:
        path = urlsplit(url or "").path
    except ValueError:
        return "other"
    if path.startswith(SEARCH_RESULTS_PREFIX):
        return "search"
    if path.rstrip("/") == FEED_PATH:
        return "feed"
    return "other"


class BrowserError(RuntimeError):
    """Raised when the existing Chrome session cannot be reached."""


_SHUTDOWN_NOISE = (
    "Task was destroyed but it is pending!",
    "Task was destroyed but it is pending",
    "Target page, context or browser has been closed",
)


class _DropShutdownNoise(logging.Filter):
    """Drops Playwright teardown noise produced when Ctrl+C interrupts the run.

    Interrupting mid-navigation leaves the driver's asyncio connection task
    pending, which asyncio reports as "Task was destroyed but it is pending!"
    with a TargetClosedError traceback. The browser window and the user's login
    are untouched either way, so the message is only confusing.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if any(message.startswith(noise) for noise in _SHUTDOWN_NOISE):
            return False
        if record.exc_info and record.exc_info[1] is not None:
            if "TargetClosedError" in type(record.exc_info[1]).__name__:
                return False
        return True


@contextlib.contextmanager
def quiet_driver_shutdown() -> Iterator[None]:
    noise_filter = _DropShutdownNoise()
    targets = (logging.getLogger("asyncio"), logging.getLogger("playwright"))
    for target in targets:
        target.addFilter(noise_filter)
    try:
        yield
    finally:
        for target in targets:
            target.removeFilter(noise_filter)


class BrowserSession:
    """Attaches to an already-open Chrome over CDP and never closes it."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def connect(self, *, require_linkedin: bool = False):
        """Attach to the open Chrome and return the page to work on.

        The default keeps the original behaviour: a LinkedIn tab is reused, and
        when none exists the feed is opened. ``require_linkedin=True`` is the
        opposite contract, used by ``continue_run.py``: only an already-open
        LinkedIn tab is accepted, and nothing is ever navigated, opened or
        created -- an unusable session fails with ``BrowserError`` instead.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserError(
                "Playwright is not installed. Run: pip install -r requirements.txt"
            ) from exc

        self.playwright = sync_playwright().start()
        try:
            self.browser = self.playwright.chromium.connect_over_cdp(
                self.cfg.cdp_url, timeout=20000
            )
        except Exception as exc:
            self.disconnect()
            raise BrowserError(f"Could not attach to Chrome at {self.cfg.cdp_url}: {exc}") from exc

        if require_linkedin:
            page = self._pick_existing_linkedin_page()
            if page is None:
                self.disconnect()
                raise BrowserError(
                    "No LinkedIn tab is open, so there is no page to continue from. "
                    "Open the LinkedIn search results or feed you want to continue "
                    "in Chrome and run continue_run.py again."
                )
            self.page = page
            self.context = page.context
        else:
            self.context = self._pick_context()
            self.page = self._pick_page()

        logger.ok(f"Attached to Chrome over CDP ({self.cfg.cdp_url}).")

        if not self._on_linkedin():
            if require_linkedin:
                self.disconnect()
                raise BrowserError(
                    f"The tab picked to continue from is not a LinkedIn page: {self.page.url}"
                )
            logger.info("No LinkedIn tab found, opening the feed in a new tab.")
            self.page.goto(self.cfg.linkedin_feed_url, wait_until="domcontentloaded", timeout=45000)
            self.human_delay("page")

        logger.ok(f"Using tab: {self.page.url}")
        return self.page

    def _pick_existing_linkedin_page(self):
        """The LinkedIn tab a continuation should attach to, or ``None``.

        Search results and the feed are the pages a run can be continued on, so
        they win over any other LinkedIn tab, and a tab from another site is
        never chosen.
        """
        candidates = []
        for context in self.browser.contexts:
            for page in context.pages:
                if is_linkedin_url(getattr(page, "url", "") or ""):
                    candidates.append(page)
        if not candidates:
            return None
        for kind in ("search", "feed", "other"):
            for page in candidates:
                if linkedin_page_kind(getattr(page, "url", "") or "") == kind:
                    return page
        return candidates[0]

    def _pick_context(self):
        contexts = self.browser.contexts
        for context in contexts:
            pages = [page for page in context.pages if "linkedin.com" in (page.url or "")]
            if pages:
                return context
        return contexts[0] if contexts else self.browser.new_context()

    def _pick_page(self):
        pages = list(self.context.pages)
        for page in pages:
            if "linkedin.com" in (page.url or ""):
                return page
        if pages:
            return pages[0]
        return self.context.new_page()

    def _on_linkedin(self) -> bool:
        return "linkedin.com" in (getattr(self.page, "url", "") or "")

    def page_title(self) -> str:
        try:
            return self.page.title()
        except Exception:
            return ""

    def human_delay(self, kind: str = "action") -> None:
        low, high = self.cfg.delay_for(kind)
        millis = int(random.uniform(low, high) * 1000)
        try:
            self.page.wait_for_timeout(millis)
        except Exception:
            pass

    def disconnect(self) -> None:
        """Stop only the Playwright driver: browser, context and tabs stay open."""
        if self.playwright is not None:
            driver, self.playwright = self.playwright, None
            try:
                with quiet_driver_shutdown():
                    driver.stop()
            except Exception:
                pass
        self.browser = None
        self.context = None
        self.page = None


def human_delay(page, delay_range: Sequence[float]) -> float:
    seconds = random.uniform(float(delay_range[0]), float(delay_range[-1]))
    try:
        page.wait_for_timeout(int(seconds * 1000))
    except Exception:
        pass
    return seconds


def print_connection_help(stream_message: Optional[str] = None) -> None:
    if stream_message:
        logger.error(stream_message)
    logger.info(CHROME_LAUNCH_HINT)