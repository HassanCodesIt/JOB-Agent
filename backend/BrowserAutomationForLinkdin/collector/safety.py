from __future__ import annotations

from typing import Sequence

from collector import logger
from collector.post_reader import POST_SELECTORS

POST_SELECTOR = POST_SELECTORS[0]


class SecurityChallengeError(RuntimeError):
    """Raised when LinkedIn shows a CAPTCHA or account verification screen."""


class LoginRequiredError(RuntimeError):
    """Raised when the attached Chrome is not logged in to LinkedIn."""


class NavigatorError(RuntimeError):
    """Raised when a search box or the Posts filter cannot be located."""


CHALLENGE_URL_MARKERS: Sequence[str] = (
    "/checkpoint",
    "/challenge",
    "/captcha",
    "/unusual-activity",
    "/account-access",
)

LOGIN_URL_MARKERS: Sequence[str] = (
    "/authwall",
    "/uas/login",
    "/login",
    "/signup",
    "/signin",
)

BLOCKED_TEXT_MARKERS: Sequence[str] = (
    "security verification",
    "identity verification",
    "verify that you're human",
    "verify it's you",
    "verify you are human",
    "confirm you're human",
    "confirm you are human",
    "quick security check",
    "please complete the security check",
    "complete the security check to continue",
    "unusual traffic",
    "we detected unusual activity",
    "too many requests",
    "enter your password to continue",
    "your account has been temporarily",
    "please enable javascript and cookies to continue",
    "checking your browser before accessing",
)

BLOCKED_IFRAME_SELECTORS: Sequence[str] = (
    "iframe[src*='recaptcha']",
    "iframe[src*='captcha']",
    "iframe[title*='recaptcha']",
)

BLOCKED_SELECTORS: Sequence[str] = (
    "#challenge-form",
    "form[action*='checkpoint']",
    ".captcha-box",
    ".g-recaptcha",
    "[data-id='challenge-container']",
    ".cf-challenge-running",
)


def _url_is_blocked(url: str) -> bool:
    lowered = (url or "").lower()
    return any(marker in lowered for marker in CHALLENGE_URL_MARKERS)


def is_login_required(page) -> bool:
    """True when the current page is LinkedIn's sign-in / authwall screen."""
    try:
        current = getattr(page, "url", "") or ""
    except Exception:
        current = ""
    lowered = current.lower()
    if any(marker in lowered for marker in LOGIN_URL_MARKERS):
        return True
    try:
        return page.locator(
            "form[action*='login'], a[href*='/uas/login'], .authwall, #authwall"
        ).count() > 0
    except Exception:
        return False


def _post_count(page) -> int:
    try:
        return len(page.query_selector_all(", ".join(POST_SELECTORS)))
    except Exception:
        return 0


def _has_visible_captcha_iframe(page) -> bool:
    """A real challenge shows the reCAPTCHA widget; the normal badge is hidden."""
    try:
        nodes = page.query_selector_all(", ".join(BLOCKED_IFRAME_SELECTORS))
    except Exception:
        return False
    for node in nodes:
        try:
            if node.is_visible():
                return True
        except Exception:
            continue
    return False


def is_blocked(page) -> bool:
    """Cheap URL + DOM check for CAPTCHA / verification interstitials."""
    try:
        current = getattr(page, "url", "") or ""
    except Exception:
        current = ""

    if _url_is_blocked(current):
        return True

    try:
        selectors = page.locator(", ".join(BLOCKED_SELECTORS))
        if selectors.count() > 0:
            return True
    except Exception:
        pass

    if _has_visible_captcha_iframe(page):
        return True

    try:
        snippet = page.evaluate(
            "() => (document.body ? document.body.innerText.slice(0, 4000) : '')"
        )
    except Exception:
        return False

    if not snippet:
        return False
    lowered = snippet.lower()
    if not any(marker in lowered for marker in BLOCKED_TEXT_MARKERS):
        return False
    return _post_count(page) == 0


def guard(page, context: str = "") -> None:
    """Stop safely on a verification screen or a logged-out session."""
    where = f" while {context}" if context else ""

    if is_blocked(page):
        logger.warn(f"Security verification detected on LinkedIn{where}.")
        logger.info("Stopping the run safely. No CAPTCHA or verification bypass will be attempted.")
        logger.info("Complete the verification manually in your browser, then re-run the collector.")
        raise SecurityChallengeError("Security challenge detected on LinkedIn")

    if is_login_required(page):
        logger.warn(f"Not logged in to LinkedIn{where}.")
        logger.info("Log into LinkedIn in that Chrome window, then re-run the collector.")
        logger.info("No credentials are ever requested or stored by this script.")
        raise LoginRequiredError("LinkedIn login required")