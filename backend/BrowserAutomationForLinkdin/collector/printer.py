from __future__ import annotations

from typing import List, Optional, Sequence

from collector import logger
from collector.models import NOT_SPECIFIED, POST_URL_NOT_FOUND, JobMatch, Stats

WIDTH = 60


def _label(name: str, value: str) -> str:
    if value is None or value == NOT_SPECIFIED or not str(value).strip():
        value = NOT_SPECIFIED
    return f"{name}: {value}"


def _list_block(name: str, values: Sequence[str], indent: str = "  ") -> str:
    if not values:
        return _label(name, NOT_SPECIFIED)
    body = "\n".join(f"{indent}- {value}" for value in values)
    return f"{name}:\n{body}"


def print_match(index: int, match: JobMatch, cfg=None) -> None:
    separator = logger.rule("=", WIDTH)
    color = cfg.color if cfg is not None and getattr(cfg, "color", False) else False

    def head(text: str) -> str:
        return logger.paint(text, "OK") if color else text

    print(separator)
    print(head(f"MATCH #{index:02d}"))
    print(separator)
    print(head(_label("TARGET ROLE", match.target_role)))

    variations = match.role_match.matched_variations
    print(head(_label("MATCHED ROLE VARIATIONS", ", ".join(variations) if variations else NOT_SPECIFIED)))

    others = match.other_categories
    if others:
        print(head(_label("ALSO MATCHED ROLES", ", ".join(others))))

    print(head(_label("AUTHOR", match.post.author or NOT_SPECIFIED)))
    print(head(_label("COMPANY", match.company)))
    print(head(_label("LOCATION", match.location)))
    print(head(_label("EXPERIENCE", match.experience)))
    print(head(_label("EMPLOYMENT TYPE", match.employment_type)))
    print(head(_label("SALARY", match.salary)))

    if len(match.methods) > 1:
        print(head(_list_block("APPLICATION METHODS", match.methods)))
    print(head(_label("APPLICATION METHOD", match.application_method)))

    if len(match.emails) == 1:
        print(head(_label("EMAIL", match.emails[0])))
    elif match.emails:
        print(head(_list_block("EMAILS FOUND", match.emails)))
        extra = match.additional_emails
        if extra:
            print(head(_label("ADDITIONAL EMAILS", ", ".join(extra))))
    else:
        print(head(_label("EMAIL", NOT_SPECIFIED)))

    if match.skills:
        print(head(_list_block("SKILLS", match.skills)))
    if match.responsibilities:
        print(head(_list_block("RESPONSIBILITIES", match.responsibilities)))
    if match.qualifications:
        print(head(_list_block("QUALIFICATIONS", match.qualifications)))

    print(head(_label("JOB URL", match.job_url or NOT_SPECIFIED)))
    print(head(_label("APPLY URL", match.apply_url or NOT_SPECIFIED)))
    if match.additional_apply_urls:
        print(head(_list_block("ADDITIONAL APPLY URLS", match.additional_apply_urls)))

    print(head(_label("LINKEDIN POST", match.post.url or POST_URL_NOT_FOUND)))

    print(head("FULL POST:"))
    print(logger.rule("-", WIDTH))
    print(match.post.text or NOT_SPECIFIED)
    print(logger.rule("-", WIDTH))

    if match.job_description and match.job_description.strip() != (match.post.text or "").strip():
        print(head("JOB DESCRIPTION:"))
        print(match.job_description)

    if match.application_instructions:
        print(head(_list_block("APPLICATION INSTRUCTIONS", match.application_instructions)))
    else:
        print(head(_label("APPLICATION INSTRUCTIONS", NOT_SPECIFIED)))

    if match.reasons:
        print(head(_list_block("MATCH REASONS", match.reasons)))
    print(separator)
    logger.blank()


def print_summary(stats: Stats, cfg=None) -> None:
    color = cfg.color if cfg is not None and getattr(cfg, "color", False) else False
    separator = logger.rule("=", WIDTH)

    lines: List[str] = [
        "",
        separator,
        logger.paint("COLLECTION COMPLETE", "OK") if color else "COLLECTION COMPLETE",
        separator,
        f"Target Roles Searched: {stats.roles_searched}",
    ]
    if stats.roles_skipped:
        lines.append(f"Role Searches Skipped: {stats.roles_skipped}")
    if stats.roles_with_errors:
        lines.append(f"Role Searches With Read Errors: {stats.roles_with_errors}")
    lines += [
        f"Posts Processed: {stats.posts_processed}",
        f"Potential Job Posts: {stats.potential_job_posts}",
        f"Posts With Email: {stats.posts_with_email}",
        f"Posts With Job URL: {stats.posts_with_job_url}",
        f"Posts With Apply URL: {stats.posts_with_apply_url}",
        f"Posts Without Any Application Method: {stats.no_application_method}",
        f"Collected By Email: {stats.collected_by_email}",
        f"Collected By LinkedIn Job URL: {stats.collected_by_job_url}",
        f"Collected By Apply URL: {stats.collected_by_apply_url}",
        f"Collected By Image-Based Job Post: {stats.collected_by_image}",
        f"Posts With Image: {stats.posts_with_image}",
        f"Collected With Multiple Methods: {stats.collected_with_multiple_methods}",
        f"Valid Job Matches: {stats.valid_job_matches}",
        f"Duplicates Removed: {stats.duplicates_removed}",
    ]
    if stats.unreadable_posts:
        lines.append(f"Posts Skipped (unreadable): {stats.unreadable_posts}")
    if stats.missing_post_url:
        lines.append(f"JDs Skipped (no LinkedIn post URL): {stats.missing_post_url}")
    if stats.stop_reason:
        lines.append(f"Stop Reason: {stats.stop_reason}")
    lines.append("")
    if not stats.collected:
        lines.append("(no post passed every collection criterion)")
        lines.append("")
    lines.append(f"Final JDs Collected: {stats.collected}")
    lines.append(separator)
    print("\n".join(lines), flush=True)


def print_header(cfg, mode_label: Optional[str] = None) -> None:
    """Print the start-up banner.

    ``mode_label`` names the filters this run applies, so the two sorted entry
    points say which sort they are running. It stays ``None`` for the standard
    and date-posted runs, whose banner is unchanged.
    """
    logger.blank()
    print(logger.rule("=", WIDTH))
    print("LINKEDIN JOB POST COLLECTOR")
    if mode_label:
        print(f"MODE: {mode_label}")
    print(f"Target roles ({len(cfg.target_roles)}): " + ", ".join(cfg.target_roles))
    print(
        f"Limits: max_scrolls={cfg.max_scrolls} max_posts={cfg.max_posts} "
        f"max_jds={cfg.max_jds} min_jd_signals={cfg.min_jd_signals}"
    )
    print(logger.rule("=", WIDTH))
    logger.blank()