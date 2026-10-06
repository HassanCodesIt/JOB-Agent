from __future__ import annotations

import pytest

from collector import post_reader
from collector.apply_link_extractor import classify, collect_apply_urls, normalize_url
from collector.dedupe import Deduplicator
from collector.models import (
    METHOD_EMAIL,
    METHOD_EXTERNAL_APPLY,
    METHOD_LINKEDIN_JOB,
    NOT_SPECIFIED,
    Post,
    Stats,
)
from collector.pipeline import Decider, decide
from collector.printer import print_match, print_summary
from config import Config

ROLE = "Generative AI Engineer"

SPEC_POST = """We are hiring a Generative AI Engineer.

About the role:
You will work on LLM applications, RAG pipelines,
AI agents and production AI systems.

Requirements:
- Python
- LLMs
- RAG
- LangChain
- FastAPI

Location: Bangalore

Interested candidates can apply here:

https://company.com/careers/generative-ai-engineer

Please apply through the link above."""


NO_APPLY_POST = """We are hiring a Generative AI Engineer.

About the role:
You will work on LLM applications, RAG pipelines,
AI agents and production AI systems.

Requirements:
- Python
- LLMs
- RAG
- LangChain
- FastAPI

Location: Bangalore

Please share this opportunity with your network."""


def _post(text: str, **kwargs) -> Post:
    kwargs.setdefault("apply_urls", collect_apply_urls(text))
    return Post(author="Test Recruiter", text=text, **kwargs)


def _decide(post: Post, **cfg_kwargs):
    stats = Stats()
    cfg = Config(target_roles=[ROLE], **cfg_kwargs)
    return Decider(cfg, stats, Deduplicator()).decide(post), stats


# --- PATH 3: external apply link, no email ---------------------------------


def test_post_with_apply_link_and_no_email_is_collected():
    match, _ = _decide(_post(SPEC_POST))

    assert match is not None
    assert match.emails == []
    assert match.apply_url == "https://company.com/careers/generative-ai-engineer"
    assert match.job_url == ""
    assert match.methods == [METHOD_EXTERNAL_APPLY]
    assert match.application_method == "External Apply Link"


def test_missing_email_is_never_a_rejection_reason():
    match, stats = _decide(_post(SPEC_POST))

    assert match is not None
    assert stats.emails_missing == 1
    assert stats.posts_with_email == 0
    assert stats.no_application_method == 0


def test_submit_cv_without_the_word_apply_is_accepted():
    text = SPEC_POST.replace(
        "Interested candidates can apply here:",
        "Interested candidates, submit your CV here:",
    )

    match, _ = _decide(_post(text))

    assert match is not None
    assert match.apply_url == "https://company.com/careers/generative-ai-engineer"


def test_plain_careers_link_without_apply_wording_is_accepted():
    text = SPEC_POST.replace("Interested candidates can apply here:", "Details:")

    match, _ = _decide(_post(text))

    assert match is not None
    assert match.apply_url == "https://company.com/careers/generative-ai-engineer"


@pytest.mark.parametrize(
    "url",
    [
        "https://company.com/careers/generative-ai-engineer",
        "https://jobs.company.com/job/12345",
        "https://careers.company.in/jobs/ai-engineer",
        "https://forms.company.com/123",
        "https://apply.workable.com/abc123/",
        "https://boards.greenhouse.io/acme/jobs/4242",
        "https://widgets.io/hiring/2026/ai-engineer",
    ],
)
def test_known_apply_url_shapes_are_recognised(url):
    assert classify(url) is not None


# --- negatives: a random link must not qualify -----------------------------


@pytest.mark.parametrize(
    "text",
    [
        "We are hiring a Generative AI Engineer. Skills: Python, RAG, LangChain, FastAPI. "
        "Location: Bangalore. Experience: 4+ years. Responsibilities: Build agents.\n"
        "Read my latest AI article: https://example.com/article",
        "We are hiring a Generative AI Engineer. Skills: Python, RAG, LangChain, FastAPI. "
        "Location: Bangalore. Experience: 4+ years. Responsibilities: Build agents.\n"
        "Follow our company: https://company.com",
        "We are hiring a Generative AI Engineer. Skills: Python, RAG, LangChain, FastAPI. "
        "Location: Bangalore. Experience: 4+ years. Responsibilities: Build agents.\n"
        "Our website: https://company.com/about",
    ],
)
def test_non_application_links_do_not_qualify_a_post(text):
    post = _post(text)

    assert post.apply_urls == []
    match, _ = _decide(post)
    assert match is None


def test_article_short_link_is_not_an_apply_link():
    text = (
        "We are hiring a Generative AI Engineer. Skills: Python, RAG, LangChain, FastAPI. "
        "Location: Bangalore. Experience: 4+ years. Responsibilities: Build agents.\n"
        "Check out this job: https://lnkd.in/xxxxx"
    )

    # Weak phrasing in free text is not enough: it is only honoured on a real
    # anchor label, where the link is actually attached to that wording.
    assert _post(text).apply_urls == []
    assert classify("https://lnkd.in/xxxxx", "Check out this job", allow_weak=True) is not None


def test_weak_job_reference_is_accepted_on_an_anchor_label():
    element = _DomCard(
        {
            post_reader.EXTERNAL_LINK_SELECTOR: [
                _Anchor("https://lnkd.in/xxxxx", text="Check out this job")
            ]
        },
        text="We are hiring an AI Engineer in Bangalore.",
    )

    post = post_reader.read_post(element)

    assert post is not None
    assert post.apply_urls == ["https://lnkd.in/xxxxx"]


def test_company_home_page_is_rejected_even_next_to_apply_wording():
    assert classify("https://company.com", "Apply here: https://company.com") is None


def test_article_url_is_rejected_even_next_to_apply_wording():
    assert classify("https://company.com/article/ai", "Apply now") is None


def test_media_file_is_never_an_apply_link():
    assert classify("https://company.com/careers/brochure.pdf") is None


def test_short_link_needs_job_context():
    assert classify("https://lnkd.in/xxxxx", "Apply now", allow_weak=True) is not None
    assert classify("https://lnkd.in/xxxxx", "Read my latest article") is None


def test_linkedin_urls_are_never_apply_links():
    assert classify("https://www.linkedin.com/jobs/view/4473153699/", "Apply") is None
    assert classify("https://www.linkedin.com/in/someone/", "Apply") is None


# --- PATH 1 and PATH 2 still work -----------------------------------------


def test_email_only_post_is_still_collected():
    text = (
        "We are hiring a Generative AI Engineer in Bangalore.\n"
        "Skills:\n- Python\n- RAG\n- LangChain\n- FastAPI\n"
        "Responsibilities:\n- Build production AI systems\n"
        "Experience: 5+ years\n"
        "Apply: send your resume to careers@acme-ai.com"
    )

    match, _ = _decide(_post(text))

    assert match is not None
    assert match.emails == ["careers@acme-ai.com"]
    assert match.apply_url == ""
    assert match.methods == [METHOD_EMAIL]


def test_job_card_only_post_is_still_collected():
    match, _ = _decide(
        _post(NO_APPLY_POST, job_url="https://www.linkedin.com/jobs/view/4473153699/")
    )

    assert match is not None
    assert match.emails == []
    assert match.job_url == "https://www.linkedin.com/jobs/view/4473153699/"
    assert match.apply_url == ""
    assert match.methods == [METHOD_LINKEDIN_JOB]


# --- multiple methods -----------------------------------------------------


def test_premium_group_link_is_not_an_apply_link():
    """Real-world false positive: a paid Telegram group promoted with the word
    "referral" and a forward-pointing label."""
    text = (
        "Join our Premium Group to unlock full access and get referral "
        "opportunities directly.\n"
        "\U0001F517 JOIN PREMIUM GROUP:\n"
        "https://lnkd.in/gbATHcT7"
    )

    assert _post(text).apply_urls == []


def test_apply_wording_two_lines_above_a_channel_link_is_ignored():
    """Real-world false positive: 'Apply now' sat two lines above a Telegram
    channel link, so the link must not inherit that wording."""
    text = (
        "We are hiring an AI Developer. Skills: Python, RAG, LangChain. "
        "Location: Pune. Experience: 4+ years. Responsibilities: Build agents.\n"
        "\U0001F4E3 Apply now or share with your network!\n"
        "\n"
        "\U0001F916 Explore daily IT job opportunities for free! Join our channel:\n"
        "\U0001F449 https://lnkd.in/gAJNt56H"
    )

    assert _post(text).apply_urls == []


def test_genuine_apply_link_on_the_preceding_line_is_still_found():
    text = (
        "We are hiring an AI Developer. Skills: Python, RAG, LangChain. "
        "Location: Pune. Experience: 4+ years. Responsibilities: Build agents.\n"
        "\U0001F517 Apply here:\n"
        "https://lnkd.in/realApply1"
    )

    assert _post(text).apply_urls == ["https://lnkd.in/realApply1"]


def test_genuine_apply_link_on_the_same_line_is_found():
    text = (
        "We are hiring an AI Developer. Skills: Python, RAG, LangChain. "
        "Location: Pune. Experience: 4+ years. Responsibilities: Build agents.\n"
        "\U0001F517 Apply: https://lnkd.in/sameLine1"
    )

    assert _post(text).apply_urls == ["https://lnkd.in/sameLine1"]


def test_job_card_and_apply_link_are_both_collected():
    match, stats = _decide(
        _post(
            SPEC_POST + "\nApply: careers@acme-ai.com",
            job_url="https://www.linkedin.com/jobs/view/4473153699/",
        )
    )

    assert match is not None
    assert match.emails == ["careers@acme-ai.com"]
    assert match.job_url == "https://www.linkedin.com/jobs/view/4473153699/"
    assert match.apply_url == "https://company.com/careers/generative-ai-engineer"
    assert match.methods == [
        METHOD_EMAIL,
        METHOD_LINKEDIN_JOB,
        METHOD_EXTERNAL_APPLY,
    ]
    assert match.has_multiple_methods is True
    assert match.application_method.startswith("Multiple (")
    assert stats.collected_by_email == 1
    assert stats.collected_by_job_url == 1
    assert stats.collected_by_apply_url == 1
    assert stats.collected_with_multiple_methods == 1


def test_post_is_counted_once_even_with_several_methods():
    stats = Stats()
    cfg = Config(target_roles=[ROLE])
    decider = Decider(cfg, stats, Deduplicator())

    match = decider.decide(
        _post(
            SPEC_POST + "\nApply: careers@acme-ai.com",
            job_url="https://www.linkedin.com/jobs/view/4473153699/",
        )
    )
    stats.collected += 1 if match is not None else 0

    assert match is not None
    # Per-method counters may overlap, but the total must count the post once.
    assert stats.collected_by_email == 1
    assert stats.collected_by_job_url == 1
    assert stats.collected_by_apply_url == 1
    assert stats.collected_with_multiple_methods == 1
    assert stats.collected == 1


def test_several_apply_urls_are_ordered_and_deduplicated():
    text = SPEC_POST + "\nBackup form: https://forms.company.com/999"

    match, _ = _decide(_post(text))

    assert match is not None
    assert match.apply_urls == [
        "https://company.com/careers/generative-ai-engineer",
        "https://forms.company.com/999",
    ]
    assert match.additional_apply_urls == ["https://forms.company.com/999"]


# --- URL fields never merge ------------------------------------------------


def test_post_url_job_url_and_apply_url_are_three_separate_values():
    post = _post(
        SPEC_POST,
        url="https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/",
        job_url="https://www.linkedin.com/jobs/view/4473153699/",
    )

    match, _ = _decide(post)

    assert match is not None
    assert match.post.url == "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/"
    assert match.job_url == "https://www.linkedin.com/jobs/view/4473153699/"
    assert match.apply_url == "https://company.com/careers/generative-ai-engineer"
    assert len({match.post.url, match.job_url, match.apply_url}) == 3


def test_apply_url_is_not_reported_as_the_job_url_by_the_dom_reader():
    anchors = {post_reader.EXTERNAL_LINK_SELECTOR: []}
    element = _DomCard(anchors, text=SPEC_POST)

    post = post_reader.read_post(element)

    assert post is not None
    assert post.job_url == ""
    assert post.apply_urls == ["https://company.com/careers/generative-ai-engineer"]


# --- full post preservation ----------------------------------------------


def test_full_post_text_is_preserved_for_apply_link_matches():
    match, _ = _decide(_post(SPEC_POST, url="https://www.linkedin.com/feed/update/urn:li:activity:1/"))

    assert match is not None
    assert match.post.text == SPEC_POST
    assert "Please apply through the link above." in match.post.text
    assert "About the role:" in match.post.text


# --- structured output -----------------------------------------------------


def test_output_contains_every_application_field(capsys):
    match, _ = _decide(
        _post(SPEC_POST, url="https://www.linkedin.com/feed/update/urn:li:activity:789/")
    )
    assert match is not None

    print_match(1, match, Config(target_roles=[ROLE]))
    out = capsys.readouterr().out

    assert "APPLICATION METHOD: External Apply Link" in out
    assert "EMAIL: " + NOT_SPECIFIED in out
    assert "JOB URL: " + NOT_SPECIFIED in out
    assert "APPLY URL: https://company.com/careers/generative-ai-engineer" in out
    assert "LINKEDIN POST: https://www.linkedin.com/feed/update/urn:li:activity:789/" in out
    assert "FULL POST:" in out
    assert "About the role:" in out
    assert "We are hiring a Generative AI Engineer." in out
    assert "Apply link found: https://company.com/careers/generative-ai-engineer" in out
    assert "LinkedIn post URL captured:" in out
    assert "Full post preserved" in out


def test_output_lists_multiple_application_methods(capsys):
    match, _ = _decide(
        _post(
            SPEC_POST + "\nApply: careers@acme-ai.com",
            job_url="https://www.linkedin.com/jobs/view/4473153699/",
            url="https://www.linkedin.com/feed/update/urn:li:activity:5/",
        )
    )
    assert match is not None

    print_match(1, match, Config(target_roles=[ROLE]))
    out = capsys.readouterr().out

    assert "APPLICATION METHODS:" in out
    assert "  - Email" in out
    assert "  - LinkedIn Job" in out
    assert "  - External Apply Link" in out
    assert "EMAIL: careers@acme-ai.com" in out
    assert "JOB URL: https://www.linkedin.com/jobs/view/4473153699/" in out
    assert "APPLY URL: https://company.com/careers/generative-ai-engineer" in out


def test_summary_reports_each_application_method(capsys):
    stats = Stats()
    stats.roles_searched = 1
    stats.posts_processed = 12
    stats.potential_job_posts = 5
    stats.collected_by_email = 1
    stats.collected_by_job_url = 1
    stats.collected_by_apply_url = 1
    stats.collected_with_multiple_methods = 1
    stats.collected = 3

    print_summary(stats, Config())
    out = capsys.readouterr().out

    assert "Collected By Email: 1" in out
    assert "Collected By LinkedIn Job URL: 1" in out
    assert "Collected By Apply URL: 1" in out
    assert "Collected With Multiple Methods: 1" in out
    assert "Final JDs Collected: 3" in out


# --- duplicates -----------------------------------------------------------


def test_same_post_under_two_roles_is_collected_once():
    stats = Stats()
    cfg = Config(target_roles=[ROLE, "AI Engineer"])
    decider = Decider(cfg, stats, Deduplicator())
    url = "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/"

    first = decide(_post(SPEC_POST, url=url), cfg, stats, decider.deduper)
    second = decide(_post(SPEC_POST, url=url), cfg, stats, decider.deduper)

    assert first is not None
    assert second is None
    assert stats.duplicates_removed == 1


# --- helpers --------------------------------------------------------------


def test_normalize_url_cleans_punctuation_and_missing_scheme():
    assert normalize_url("https://a.com/x.") == "https://a.com/x"
    assert normalize_url("www.a.com/x") == "https://www.a.com/x"
    assert normalize_url("//a.com/x") == "https://a.com/x"
    assert normalize_url("") == ""


def test_collect_apply_urls_respects_exclude():
    urls = collect_apply_urls(
        SPEC_POST,
        anchors=[],
        exclude=["https://company.com/careers/generative-ai-engineer"],
    )

    assert urls == []


class _Anchor:
    def __init__(self, href, aria_label=None, title=None, text=""):
        self._href = href
        self._aria_label = aria_label
        self._title = title
        self._text = text

    def get_attribute(self, name):
        return {"href": self._href, "aria-label": self._aria_label, "title": self._title}.get(name)

    def inner_text(self):
        return self._text


class _DomCard:
    def __init__(self, anchors=None, urn="", text="Hiring an AI Engineer."):
        self._anchors = anchors or {}
        self._urn = urn
        self._text = text

    def query_selector_all(self, selector):
        return list(self._anchors.get(selector, []))

    def query_selector(self, selector):
        found = self.query_selector_all(selector)
        return found[0] if found else None

    def get_attribute(self, name):
        return self._urn if name in ("data-id", "data-urn") else None

    def inner_text(self):
        return self._text


def test_anchor_labelled_apply_link_is_picked_up_without_apply_text():
    element = _DomCard(
        {
            post_reader.EXTERNAL_LINK_SELECTOR: [
                _Anchor(
                    "https://acme.test/portal/abc",
                    aria_label="Submit application",
                    text="Apply",
                )
            ]
        },
        text="We are hiring an AI Engineer in Bangalore.",
    )

    post = post_reader.read_post(element)

    assert post is not None
    assert post.apply_urls == ["https://acme.test/portal/abc"]


def test_anchor_for_an_article_is_not_picked_up():
    element = _DomCard(
        {
            post_reader.EXTERNAL_LINK_SELECTOR: [
                _Anchor("https://medium.com/@acme/ai-trends", text="Read the article")
            ]
        },
        text="We are hiring an AI Engineer in Bangalore.",
    )

    post = post_reader.read_post(element)

    assert post is not None
    assert post.apply_urls == []