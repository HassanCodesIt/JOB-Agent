from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import logger, navigator, printer, safety, scroller  # noqa: E402
from collector import date_filter, sort_filter  # noqa: E402
from collector.apply_link_extractor import collect_apply_urls  # noqa: E402
from collector.browser import (  # noqa: E402
    BrowserError,
    BrowserSession,
    linkedin_page_kind,
    print_connection_help,
)
from collector.continuation import (  # noqa: E402
    ContinuationError,
    current_scroll_state,
    seed_deduper,
)
from collector.dedupe import Deduplicator  # noqa: E402
from collector.models import JobMatch, Post, Stats  # noqa: E402
from collector.pipeline import Decider  # noqa: E402
from collector.post_url_extractor import (  # noqa: E402
    canonical_urn,
    copy_link_via_menu,
    find_urn,
    validate_post_url,
)
from collector.run_modes import FLOW_CONTINUE, FLOW_FEED, flow, header_label  # noqa: E402
from collector.run_storage import save_scraping_run  # noqa: E402
from collector.safety import LoginRequiredError, SecurityChallengeError  # noqa: E402
from config import load_config  # noqa: E402

FEED_LABEL = "LinkedIn Feed"
CONTINUE_LABEL = "the current page"


def _stop_reason(stats: Stats, cfg) -> Optional[str]:
    if stats.collected >= cfg.max_jds:
        return f"collected {cfg.max_jds} job descriptions (max_jds)"
    if stats.posts_processed >= cfg.max_posts:
        return f"processed {cfg.max_posts} posts (max_posts)"
    return None


def _allow_clipboard_read(page) -> None:
    """Let the page read back the link it just copied.

    Reading "Copy link to post" needs the clipboard-read permission, which
    Chromium denies unless it is granted for the site. Best effort: without it
    the fallback simply reports that it found nothing.
    """
    try:
        page.context.grant_permissions(
            ["clipboard-read", "clipboard-write"],
            origin="https://www.linkedin.com",
        )
    except Exception:
        pass


def search_with_posts_filter(
    page,
    role: str,
    cfg,
    attempts: int = 2,
    apply_past_24h: bool = False,
    sort_mode: Optional[str] = None,
) -> bool:
    """Search a role and open the Posts tab, retrying once before skipping.

    The filters are applied in the order the LinkedIn Posts page expects:
    search, Posts, Date posted, then Sort by. Both filter steps verify
    themselves and raise on failure, so this function either returns True with
    every requested filter proven active, or leaves the role alone.
    """
    for attempt in range(1, attempts + 1):
        try:
            navigator.search_role(page, role, cfg)
            navigator.select_posts_filter(page, role, cfg)
            if apply_past_24h:
                date_filter.apply_past_24_hours_filter(page)
            if sort_mode:
                sort_filter.apply_sort_filter(page, sort_mode)
            return True
        except (SecurityChallengeError, LoginRequiredError, KeyboardInterrupt):
            raise
        except Exception as exc:
            logger.warn(str(exc))
            if attempt < attempts:
                logger.info(f"Retrying '{role}' once...")
                try:
                    page.wait_for_timeout(2000)
                except Exception:
                    pass
                continue
            logger.warn("Skipping current search and continuing...")
            return False
    return False


def run(
    cfg,
    run_mode: str = "standard",
    apply_past_24h: bool = False,
    sort_mode: Optional[str] = None,
) -> Stats:
    stats = Stats()
    deduper = Deduplicator()
    decider = Decider(cfg, stats, deduper)
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    collected: List[JobMatch] = []
    run_flow = flow(run_mode)

    if cfg.dry_run:
        return run_dry(cfg, decider, stats)

    session = BrowserSession(cfg)
    try:
        if run_flow == FLOW_CONTINUE:
            page = session.connect(require_linkedin=True)
        else:
            page = session.connect()
    except BrowserError as exc:
        logger.error(str(exc))
        print_connection_help()
        raise SystemExit(1)

    printer.print_header(cfg, mode_label=header_label(run_mode))
    logger.info(f"Tab title: {session.page_title()!r}")

    if safety.is_login_required(page):
        logger.warn("The attached Chrome is not logged in to LinkedIn.")
        logger.info("Log in manually in that window, then re-run the collector.")
        stats.stop_reason = "login required"
        session.disconnect()
        printer.print_summary(stats, cfg)
        return stats

    if run_flow == FLOW_CONTINUE:
        _inspect_current_page(page, session)

    try:
        if run_flow == FLOW_FEED:
            _collect_feed(_open_feed(session, cfg), cfg, decider, stats, collected)
        elif run_flow == FLOW_CONTINUE:
            _collect_continuation(page, cfg, decider, stats, collected, deduper)
        else:
            _collect_searches(
                page,
                cfg,
                decider,
                stats,
                collected,
                apply_past_24h=apply_past_24h,
                sort_mode=sort_mode,
            )
    except SecurityChallengeError:
        stats.stop_reason = "security challenge detected"
        logger.blank()
    except LoginRequiredError:
        stats.stop_reason = "login required"
        logger.blank()
    except KeyboardInterrupt:
        stats.stop_reason = "interrupted by user"
        logger.warn("Interrupted. Printing what was collected so far.")
    finally:
        session.disconnect()
        logger.info("Playwright driver stopped. Your Chrome window and login are untouched.")
        printer.print_summary(stats, cfg)
        _persist_run(cfg, stats, collected, started_at, run_mode, sort_mode)

    return stats


def _collect_searches(
    page,
    cfg,
    decider: Decider,
    stats: Stats,
    collected: List[JobMatch],
    apply_past_24h: bool = False,
    sort_mode: Optional[str] = None,
) -> None:
    """Search every target role, one keyword search at a time."""
    for index, role in enumerate(cfg.target_roles, start=1):
        reason = _stop_reason(stats, cfg)
        if reason:
            stats.stop_reason = reason
            logger.info(f"Stopping before '{role}': {reason}.")
            break

        logger.blank()
        logger.info(f"--- Role {index}/{len(cfg.target_roles)}: {role} ---")

        if not search_with_posts_filter(
            page, role, cfg, apply_past_24h=apply_past_24h, sort_mode=sort_mode
        ):
            stats.roles_skipped += 1
            continue

        stats.roles_searched += 1

        try:
            collected_here = process_batches(page, cfg, decider, stats, role, collected)
        except (SecurityChallengeError, LoginRequiredError):
            raise
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            logger.warn(f"Could not read posts for '{role}': {exc}")
            logger.warn("Skipping current search and continuing...")
            stats.roles_with_errors += 1
            continue

        logger.info(
            f"Finished '{role}': {collected_here} JD(s) collected from "
            f"{stats.posts_processed} post(s) processed so far."
        )


def _persist_run(
    cfg,
    stats: Stats,
    collected: List[JobMatch],
    started_at: str,
    run_mode: str = "standard",
    sort_mode: Optional[str] = None,
) -> None:
    """Store the finished run as one JSON file, after the terminal summary.

    A storage failure is reported but never hides the results that were already
    printed, and never changes the run's exit status.
    """
    try:
        save_scraping_run(
            collected, stats, cfg, started_at, run_mode=run_mode, sort_mode=sort_mode
        )
    except Exception as exc:
        logger.error(f"Failed to save this scraping run: {exc}")


def _obtain_post_url(page, post, cfg, decider: Decider) -> str:
    """Get the post's own URL, using the "..." menu only when the DOM has none.

    The post URL is mandatory, so this never gives up early. Anything the menu
    returns is validated before it is accepted, and rejected when it turns out
    to belong to a different post.
    """
    logger.info("Direct post URL not exposed in DOM.")

    if not getattr(cfg, "post_url_menu_fallback", True):
        logger.warn("Post menu fallback is disabled.")
        return ""

    logger.info("Using post menu fallback...")
    _allow_clipboard_read(page)
    recovered = copy_link_via_menu(page, post.element)
    if not recovered:
        return ""

    validated = validate_post_url(recovered)
    if not validated:
        logger.warn(f"Post menu returned a URL that is not a post permalink: {recovered}")
        return ""
    if not decider.deduper.belongs_to(post, validated):
        logger.warn(f"Post menu returned a URL already claimed by another post: {validated}")
        return ""

    logger.ok(f"LinkedIn post URL found from post menu: {validated}")
    return validated


def process_batches(
    page,
    cfg,
    decider: Decider,
    stats: Stats,
    role: str,
    collected: Optional[List[JobMatch]] = None,
    start_from_current_view: bool = False,
) -> int:
    collected_here = 0
    posts_seen = 0
    if start_from_current_view:
        batches = scroller.iter_post_batches(
            page, cfg, stats, start_from_current_view=True
        )
    else:
        batches = scroller.iter_post_batches(page, cfg, stats)
    for batch in batches:
        for post in batch:
            reason = _stop_reason(stats, cfg)
            if reason:
                stats.stop_reason = reason
                logger.info(f"Stopping collection: {reason}.")
                return collected_here

            stats.posts_processed += 1
            posts_seen += 1
            match = decider.decide(post)
            if match is None:
                continue

            # The LinkedIn post URL is a required field, so a qualifying JD is
            # never printed without one.
            if not match.post.url:
                match.post.url = _obtain_post_url(page, match.post, cfg, decider)
                match.post.urn = canonical_urn(find_urn(match.post.url))
                decider.deduper.remember(match.post)
                if match.post.url:
                    # decide() ran before the URL was known, so correct its note.
                    match.reasons = [
                        reason
                        for reason in match.reasons
                        if "LinkedIn post URL not exposed" not in reason
                    ]
                    match.reasons.append(
                        f"LinkedIn post URL recovered from post menu: {match.post.url}"
                    )
            if not match.post.url:
                logger.error("Could not obtain LinkedIn post URL for this post.")
                logger.info("Skipping this JD because LinkedIn post URL is mandatory.")
                stats.missing_post_url += 1
                continue

            stats.collected += 1
            collected_here += 1
            stats.duplicates_removed = decider.deduper.duplicates_removed
            printer.print_match(stats.collected, match, cfg)
            if collected is not None:
                # Keep the exact objects that were printed, for run storage.
                collected.append(match)
    if posts_seen == 0:
        logger.info(f"No posts found for {role}")
    return collected_here


def _pages_of(session) -> List:
    try:
        return list(session.context.pages)
    except Exception:
        return []


def _open_feed(session, cfg):
    """Return a page showing the LinkedIn feed, opening it only when needed.

    A tab already on the feed is used as it is, and so is another feed tab the
    session may already have open: neither is reloaded nor scrolled. Only a
    LinkedIn tab that is somewhere else is navigated to the feed, because
    starting from the feed is what a feed run is.
    """
    page = session.page
    if linkedin_page_kind(getattr(page, "url", "") or "") == "feed":
        logger.ok("Already on the LinkedIn feed; reusing this tab.")
        return page

    for candidate in _pages_of(session):
        if linkedin_page_kind(getattr(candidate, "url", "") or "") == "feed":
            session.page = candidate
            logger.ok(f"Reusing the open LinkedIn feed tab: {candidate.url}")
            return candidate

    logger.info(f"Opening the LinkedIn feed: {cfg.linkedin_feed_url}")
    safety.guard(page, "opening the LinkedIn feed")
    page.goto(cfg.linkedin_feed_url, wait_until="domcontentloaded", timeout=45000)
    session.human_delay("page")
    safety.guard(page, "opening the LinkedIn feed")
    return page


def _inspect_current_page(page, session) -> None:
    """Read the current page and scroll position before continuing.

    The continuation never navigates, reloads or scrolls back to the top, so a
    tab that is not a LinkedIn page stops the run here with a clear error
    instead of being replaced by another one.
    """
    try:
        state = current_scroll_state(page)
    except ContinuationError as exc:
        logger.error(str(exc))
        session.disconnect()
        raise SystemExit(1)

    logger.ok("Continuing from the current page position (no reload, no new search).")
    logger.info(f"Current page: {state.url}")
    logger.info(
        f"Current scroll position: {state.scroll_y}px of {state.scroll_height}px "
        f"({state.viewport_height}px viewport) on the {state.kind_label}."
    )


def _collect_source(
    page,
    cfg,
    decider: Decider,
    stats: Stats,
    source: str,
    collected: List[JobMatch],
    start_from_current_view: bool = False,
) -> int:
    """Run the shared collector over one source: the feed or the current page."""
    try:
        return process_batches(
            page,
            cfg,
            decider,
            stats,
            source,
            collected,
            start_from_current_view=start_from_current_view,
        )
    except (SecurityChallengeError, LoginRequiredError):
        raise
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        logger.warn(f"Could not read posts from {source}: {exc}")
        logger.warn("Stopping this source and continuing...")
        stats.roles_with_errors += 1
        return 0


def _collect_feed(page, cfg, decider: Decider, stats: Stats, collected: List[JobMatch]) -> None:
    """Scroll down the LinkedIn feed through the shared collection pipeline."""
    reason = _stop_reason(stats, cfg)
    if reason:
        stats.stop_reason = reason
        logger.info(f"Stopping before scrolling the feed: {reason}.")
        return

    logger.blank()
    logger.info(f"--- {FEED_LABEL}: scrolling down for matching job posts ---")
    collected_here = _collect_source(page, cfg, decider, stats, FEED_LABEL, collected)
    logger.info(
        f"Finished the {FEED_LABEL}: {collected_here} JD(s) collected from "
        f"{stats.posts_processed} post(s) processed so far."
    )


def _collect_continuation(
    page,
    cfg,
    decider: Decider,
    stats: Stats,
    collected: List[JobMatch],
    deduper: Deduplicator,
) -> None:
    """Keep collecting from the current scroll position downwards."""
    seeded = seed_deduper(deduper)
    if seeded:
        logger.info(
            f"Loaded {seeded} LinkedIn post URL(s) from earlier runs; "
            "already collected posts are skipped."
        )
    else:
        logger.info("No earlier scraping runs with collected posts were found.")

    reason = _stop_reason(stats, cfg)
    if reason:
        stats.stop_reason = reason
        logger.info(f"Stopping before continuing: {reason}.")
        return

    logger.blank()
    logger.info(f"--- {CONTINUE_LABEL}: continuing downwards from here ---")
    collected_here = _collect_source(
        page,
        cfg,
        decider,
        stats,
        CONTINUE_LABEL,
        collected,
        start_from_current_view=True,
    )
    logger.info(
        f"Finished the continuation: {collected_here} new JD(s) collected from "
        f"{stats.posts_processed} post(s) processed so far."
    )


def _load_fixture_posts(target) -> List[Post]:
    path = Path(target)
    files: List[Path] = []
    if path.is_dir():
        files = sorted(path.glob("*.txt"))
    elif path.exists():
        files = [path]
    else:
        raise SystemExit(f"[ERROR] Dry-run input not found: {path}")

    posts: List[Post] = []
    for index, file in enumerate(files, start=1):
        text = file.read_text(encoding="utf-8").strip()
        if not text:
            continue
        header, _, body = text.partition("\n")
        author = header.strip() if header and len(header.strip()) < 80 else ""
        if author.lower().startswith(("author:", "post:", "url:")):
            author = author.split(":", 1)[1].strip()
        posts.append(
            Post(
                author=author or f"fixture-{index}",
                text=body.strip() if author else text,
                url=f"file://{file.as_posix()}",
                apply_urls=collect_apply_urls(body.strip() if author else text),
            )
        )
    return posts


def run_dry(cfg, decider: Decider, stats: Stats) -> Stats:
    """Run the decision pipeline over local text files (no browser)."""
    printer.print_header(cfg)
    posts = _load_fixture_posts(cfg.dry_run)
    logger.info(f"Dry run over {len(posts)} fixture post(s) from {cfg.dry_run}")

    for post in posts:
        reason = _stop_reason(stats, cfg)
        if reason:
            stats.stop_reason = reason
            logger.info(f"Stopping collection: {reason}.")
            break

        stats.posts_processed += 1
        match = decider.decide(post)
        if match is None:
            continue
        stats.collected += 1
        stats.duplicates_removed = decider.deduper.duplicates_removed
        printer.print_match(stats.collected, match, cfg)

    printer.print_summary(stats, cfg)
    return stats


def main(
    argv: Optional[List[str]] = None,
    run_mode: str = "standard",
    apply_past_24h: bool = False,
    sort_mode: Optional[str] = None,
) -> int:
    cfg = load_config(argv)
    logger.setup(color=cfg.color, quiet=cfg.quiet)
    try:
        run(cfg, run_mode=run_mode, apply_past_24h=apply_past_24h, sort_mode=sort_mode)

    except SystemExit:
        raise
    except Exception as exc:
        logger.error(f"Unexpected failure: {exc}")
        if cfg.verbose:
            import traceback

            traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())