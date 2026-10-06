from __future__ import annotations

from typing import List, Optional

from collector import email_extractor, field_extractor, job_detector, logger, role_matcher
from collector.dedupe import Deduplicator
from collector.models import (
    METHOD_EMAIL,
    METHOD_EXTERNAL_APPLY,
    METHOD_IMAGE_JOB_POST,
    METHOD_LINKEDIN_JOB,
    JobMatch,
    Post,
    RoleMatchResult,
    Stats,
)


class Decider:
    """Applies the five collection criteria to a post, cheapest check first."""

    def __init__(self, cfg, stats: Optional[Stats] = None, deduper: Optional[Deduplicator] = None):
        self.cfg = cfg
        self.stats = stats if stats is not None else Stats()
        self.deduper = deduper if deduper is not None else Deduplicator()

    def decide(self, post: Post) -> Optional[JobMatch]:
        text = post.text or ""

        role_result = role_matcher.match_roles(text, self.cfg.target_roles)
        if role_result is None:
            self.stats.role_rejected += 1
            return None

        is_job, positives, negatives = job_detector.is_job(
            text, self.cfg.positive_signals, self.cfg.negative_signals
        )
        if not is_job:
            self.stats.not_job_posts += 1
            return None
        self.stats.potential_job_posts += 1

        has_jd, jd_score, jd_fields = job_detector.has_meaningful_jd(
            text, self.cfg.min_jd_signals
        )
        if not has_jd:
            self.stats.jd_rejected += 1
            return None

        emails = email_extractor.extract_emails(
            text, self.cfg.denied_email_domains, self.cfg.placeholder_emails
        )
        apply_urls = list(post.apply_urls or [])

        if emails:
            self.stats.posts_with_email += 1
        else:
            self.stats.emails_missing += 1
        if post.job_url:
            self.stats.posts_with_job_url += 1
        if apply_urls:
            self.stats.posts_with_apply_url += 1

        methods: List[str] = []

        if emails:
            methods.append(METHOD_EMAIL)
        if post.job_url:
            methods.append(
                METHOD_LINKEDIN_JOB
                if "linkedin.com" in post.job_url.lower()
                else METHOD_EXTERNAL_APPLY
            )
        if apply_urls:
            methods.append(METHOD_EXTERNAL_APPLY)
        if post.has_image and not job_detector.looks_like_job_roundup(text):
            # The image may carry details the caption lacks, so it is recorded
            # as an additional method without replacing any existing one. A
            # roundup listing many openings never qualifies this way.
            methods.append(METHOD_IMAGE_JOB_POST)

        if not methods:
            # No way to reach the employer: reject without penalising the post.
            self.stats.no_application_method += 1
            return None

        if self.deduper.check_and_add(post):
            self.stats.duplicates_removed = self.deduper.duplicates_removed
            return None

        if METHOD_EMAIL in methods:
            self.stats.collected_by_email += 1
        if post.job_url:
            self.stats.collected_by_job_url += 1
        if apply_urls:
            self.stats.collected_by_apply_url += 1
        if METHOD_IMAGE_JOB_POST in methods:
            self.stats.collected_by_image += 1
        if post.has_image:
            self.stats.posts_with_image += 1
        if len(methods) > 1:
            self.stats.collected_with_multiple_methods += 1

        if (
            METHOD_IMAGE_JOB_POST in methods
            and not emails
            and not post.job_url
            and not apply_urls
        ):
            logger.info("Job information may be contained in attached image")
            logger.info("No email/job/apply URL found in caption")
            logger.ok("Collecting post because it is a qualifying image-based job post")

        return self.build_match(
            post, role_result, emails, apply_urls, methods, positives, negatives, jd_score, jd_fields
        )

    def build_match(
        self,
        post: Post,
        role_result: RoleMatchResult,
        emails: List[str],
        apply_urls: List[str],
        methods: List[str],
        positives: List[str],
        negatives: List[str],
        jd_score: int,
        jd_fields: List[str],
    ) -> JobMatch:
        fields = field_extractor.extract_fields(post, role_result, emails)
        reasons: List[str] = [
            f"Target role matched: {role_result.target_role}",
        ]
        variations = role_result.matched_variations
        if variations:
            reasons.append("Role variations found: " + ", ".join(variations))
        for category in role_result.categories:
            if category != role_result.target_role:
                reasons.append(f"Also matches category: {category}")
        if positives:
            reasons.append("Job signals: " + ", ".join(positives[:5]))
        reasons.append(f"Job description sections found ({jd_score}): " + ", ".join(jd_fields))
        reasons.append("Application methods: " + ", ".join(methods))
        if emails:
            reasons.append(f"Email address found: {emails[0]}")
            if len(emails) > 1:
                reasons.append(f"Additional emails: {', '.join(emails[1:])}")
        else:
            reasons.append("No email address in post (not required)")
        if post.job_url:
            reasons.append("Job listing detected")
            reasons.append(f"Job URL extracted: {post.job_url}")
        for apply_url in apply_urls[:3]:
            reasons.append(f"Apply link found: {apply_url}")
        if len(apply_urls) > 3:
            reasons.append(f"Additional apply links: {len(apply_urls) - 3}")
        if METHOD_IMAGE_JOB_POST in methods:
            reasons.append("Image-based job post detected")
            if not emails:
                reasons.append("No email address in caption")
            if not post.job_url:
                reasons.append("No LinkedIn Job URL found")
            if not apply_urls:
                reasons.append("No external Apply URL found")
            reasons.append(
                "Collected because job application details may be "
                "contained in attached image"
            )
        if post.url:
            reasons.append(f"LinkedIn post URL captured: {post.url}")
        else:
            reasons.append("LinkedIn post URL not exposed in the feed DOM")
        reasons.append(f"Full post preserved ({len(post.text)} characters)")

        return JobMatch(
            post=post,
            role_match=role_result,
            role=str(fields["role"]),
            company=str(fields["company"]),
            location=str(fields["location"]),
            experience=str(fields["experience"]),
            salary=str(fields["salary"]),
            employment_type=str(fields["employment_type"]),
            skills=list(fields["skills"]),
            responsibilities=list(fields["responsibilities"]),
            qualifications=list(fields["qualifications"]),
            application_instructions=list(fields["application_instructions"]),
            emails=emails,
            job_description=str(fields["job_description"]),
            job_url=post.job_url,
            apply_urls=apply_urls,
            methods=methods,
            reasons=reasons,
        )


def decide(post: Post, cfg, stats: Optional[Stats] = None, deduper: Optional[Deduplicator] = None):
    """Convenience wrapper used by tests and the dry-run mode."""
    return Decider(cfg, stats, deduper).decide(post)