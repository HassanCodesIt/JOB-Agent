from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

NOT_SPECIFIED = "Not specified"
POST_URL_NOT_FOUND = "Not found"


@dataclass
class RoleMatchResult:
    """Which configured role category a post matched, and how."""

    target_role: str
    matched_variations: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    ai_context: bool = False


@dataclass
class Post:
    """A single LinkedIn post, as read from the DOM."""

    author: str = ""
    text: str = ""
    url: str = ""
    urn: str = ""
    job_url: str = ""
    apply_urls: List[str] = field(default_factory=list)
    has_image: bool = False
    image_url: str = ""
    # Live handle on the post card, kept only for the opt-in "..." menu fallback.
    # Excluded from equality and repr so dedupe and logging are unaffected.
    element: Any = field(default=None, repr=False, compare=False)

    def __str__(self) -> str:
        return f"Post(author={self.author!r}, url={self.url!r}, chars={len(self.text)})"


METHOD_EMAIL = "Email"
METHOD_LINKEDIN_JOB = "LinkedIn Job"
METHOD_EXTERNAL_APPLY = "External Apply Link"
METHOD_IMAGE_JOB_POST = "Image-Based Job Post"


@dataclass
class JobMatch:
    """A post that passed every collection criterion, plus extracted fields."""

    post: Post
    role_match: RoleMatchResult
    role: str = NOT_SPECIFIED
    company: str = NOT_SPECIFIED
    location: str = NOT_SPECIFIED
    experience: str = NOT_SPECIFIED
    salary: str = NOT_SPECIFIED
    employment_type: str = NOT_SPECIFIED
    skills: List[str] = field(default_factory=list)
    responsibilities: List[str] = field(default_factory=list)
    qualifications: List[str] = field(default_factory=list)
    application_instructions: List[str] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)
    job_description: str = ""
    job_url: str = ""
    apply_urls: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    @property
    def target_role(self) -> str:
        return self.role_match.target_role

    @property
    def apply_url(self) -> str:
        """Primary application link, or an empty string when there is none."""
        return self.apply_urls[0] if self.apply_urls else ""

    @property
    def additional_apply_urls(self) -> List[str]:
        return self.apply_urls[1:]

    @property
    def application_method(self) -> str:
        """Single method name, or a combined label when several apply."""
        if not self.methods:
            return NOT_SPECIFIED
        if len(self.methods) == 1:
            return self.methods[0]
        return "Multiple (" + ", ".join(self.methods) + ")"

    @property
    def has_multiple_methods(self) -> bool:
        return len(self.methods) > 1

    @property
    def additional_emails(self) -> List[str]:
        return self.emails[1:]

    @property
    def other_categories(self) -> List[str]:
        return [c for c in self.role_match.categories if c != self.target_role]


@dataclass
class Stats:
    """Counters kept in sync by the decision pipeline."""

    roles_searched: int = 0
    posts_processed: int = 0
    role_rejected: int = 0
    potential_job_posts: int = 0
    not_job_posts: int = 0
    jd_rejected: int = 0
    posts_with_email: int = 0
    emails_missing: int = 0
    posts_with_job_url: int = 0
    posts_with_apply_url: int = 0
    no_application_method: int = 0
    collected_by_email: int = 0
    collected_by_job_url: int = 0
    collected_by_apply_url: int = 0
    collected_with_multiple_methods: int = 0
    duplicates_removed: int = 0
    # Qualifying JDs dropped because the LinkedIn post URL could not be obtained.
    missing_post_url: int = 0
    posts_with_image: int = 0
    collected_by_image: int = 0
    collected: int = 0
    unreadable_posts: int = 0
    roles_skipped: int = 0
    roles_with_errors: int = 0
    stop_reason: str = ""

    @property
    def valid_job_matches(self) -> int:
        return self.collected