from __future__ import annotations

import pytest

from collector import post_reader
from collector.models import NOT_SPECIFIED
from collector.pipeline import decide
from collector.printer import print_match
from config import Config


class _Anchor:
    def __init__(self, href, aria_label=None, title=None, text=""):
        self._href = href
        self._aria_label = aria_label
        self._title = title
        self._text = text

    def get_attribute(self, name):
        return {
            "href": self._href,
            "aria-label": self._aria_label,
            "title": self._title,
        }.get(name)

    def inner_text(self):
        return self._text


class _Element:
    """Stands in for one post card; maps selectors to anchors."""

    def __init__(self, anchors=None, urn="", text="Hiring an AI Engineer. Send CV to hr@acme.com"):
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


def _card(job_href, job_text="View job", extra=None):
    anchors = {post_reader.JOB_LINK_SELECTORS[0]: [_Anchor(job_href, text=job_text)]}
    if extra:
        anchors.update(extra)
    return _Element(anchors)


# --- detection ------------------------------------------------------------


def test_linkedin_job_card_url_is_canonicalised():
    element = _card(
        "https://www.linkedin.com/jobs/view/4473153699/"
        "?trackingId=mNdj1yLORNSDXJUE%2Bq9dag%3D%3D&isJobSearch=false"
    )

    url, source = post_reader.extract_job_url(element)

    assert url == "https://www.linkedin.com/jobs/view/4473153699/"
    assert source == post_reader.JOB_URL_SOURCE_CARD


def test_relative_job_href_is_absolutised():
    element = _card("/jobs/view/123456789/")

    url, _ = post_reader.extract_job_url(element)

    assert url == "https://www.linkedin.com/jobs/view/123456789/"


def test_protocol_relative_job_href_is_absolutised():
    element = _card("//www.linkedin.com/jobs/view/987654321/")

    url, _ = post_reader.extract_job_url(element)

    assert url == "https://www.linkedin.com/jobs/view/987654321/"


def test_short_link_is_kept_verbatim_when_labelled_as_a_job():
    element = _Element(
        {
            post_reader.JOB_LINK_SELECTORS[1]: [
                _Anchor("https://lnkd.in/abcd1234", text="View job")
            ]
        }
    )

    url, source = post_reader.extract_job_url(element)

    assert url == "https://lnkd.in/abcd1234"
    assert source == post_reader.JOB_URL_SOURCE_REDIRECT


def test_short_link_for_an_article_is_not_treated_as_a_job():
    element = _Element(
        {
            post_reader.JOB_LINK_SELECTORS[1]: [
                _Anchor("https://lnkd.in/abcd1234", text="Read the full article")
            ]
        }
    )

    url, source = post_reader.extract_job_url(element)

    assert url == ""
    assert source != post_reader.JOB_URL_SOURCE_REDIRECT


def test_external_apply_link_is_used_when_it_looks_like_a_job():
    element = _Element(
        {
            post_reader.EXTERNAL_LINK_SELECTOR: [
                _Anchor(
                    "https://boards.greenhouse.io/acme/jobs/4242",
                    text="View job",
                )
            ]
        }
    )

    url, source = post_reader.extract_job_url(element)

    assert url == "https://boards.greenhouse.io/acme/jobs/4242"
    assert source == post_reader.JOB_URL_SOURCE_EXTERNAL


def test_profile_and_hashtag_links_are_never_job_urls():
    element = _Element(
        {
            post_reader.EXTERNAL_LINK_SELECTOR: [
                _Anchor("https://www.linkedin.com/in/someone/", text="Shaikh Ashfaque"),
                _Anchor(
                    "https://www.linkedin.com/search/results/all/?keywords=%23hiring",
                    aria_label="View hashtag: #hiring",
                    text="#Hiring",
                ),
                _Anchor("https://acme.com/about", text="About us"),
            ]
        }
    )

    url, source = post_reader.extract_job_url(element)

    assert url == ""
    assert source == ""


def test_post_without_job_card_reports_no_listing():
    element = _Element(
        {
            post_reader.EXTERNAL_LINK_SELECTOR: [
                _Anchor("https://www.linkedin.com/in/someone/", text="Someone")
            ]
        }
    )

    assert post_reader.extract_job_url(element) == ("", "")


def test_card_without_usable_href_is_reported_as_unresolved():
    element = _Element({post_reader.JOB_LINK_SELECTORS[0]: [_Anchor("", text="View job")]})

    url, source = post_reader.extract_job_url(element)

    assert url == ""
    assert source == post_reader.JOB_URL_SOURCE_UNRESOLVED


# --- integration ----------------------------------------------------------


def test_read_post_stores_job_url_and_keeps_post_url_separate():
    element = _Element(
        {
            post_reader.LINK_SELECTORS[0]: [
                _Anchor("https://www.linkedin.com/posts/author_hiring-activity-7123456789012345678-abc")
            ],
            post_reader.JOB_LINK_SELECTORS[0]: [
                _Anchor(
                    "https://www.linkedin.com/jobs/view/4473153699/?trackingId=xyz&isJobSearch=false",
                    text="View job",
                )
            ],
        },
        urn="urn:li:activity:7123456789012345678",
    )

    post = post_reader.read_post(element)

    assert post.job_url == "https://www.linkedin.com/jobs/view/4473153699/"
    assert post.url == "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/"
    assert post.job_url != post.url


def test_post_url_collapse_keeps_protocol_intact():
    element = _Element(
        {post_reader.LINK_SELECTORS[0]: [_Anchor("https://www.linkedin.com//posts//author_activity-1-abc")]}
    )

    post = post_reader.read_post(element)

    assert post.url == "https://www.linkedin.com/posts/author_activity-1-abc"


def test_pipeline_reports_job_url_in_reasons(capsys):
    from collector.models import Post

    cfg = Config(target_roles=["AI Developer"])
    post = Post(
        author="Shaikh Ashfaque",
        text=(
            "We are hiring an Artificial Intelligence Engineer.\n\n"
            "Company: Elbetron Technologies\n"
            "Location: Al Khobar (On-site)\n"
            "Employment type: Full-time\n"
            "Experience: 5+ years\n"
            "Salary: competitive\n\n"
            "Skills:\n- Python\n- Machine Learning\n\n"
            "Responsibilities:\n- Build AI systems\n- Partner with product teams\n\n"
            "Requirements:\n- Strong ML background\n- Hands-on RAG experience\n\n"
            "Apply: send your resume to hr@elbetron.com"
        ),
        url="https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/",
        job_url="https://www.linkedin.com/jobs/view/4473153699/",
    )

    match = decide(post, cfg)

    assert match is not None
    assert match.job_url == "https://www.linkedin.com/jobs/view/4473153699/"
    assert "Job listing detected" in match.reasons
    assert "Job URL extracted: https://www.linkedin.com/jobs/view/4473153699/" in match.reasons

    print_match(1, match, cfg)
    out = capsys.readouterr().out
    assert "JOB URL: https://www.linkedin.com/jobs/view/4473153699/" in out
    assert "LINKEDIN POST: https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/" in out


def test_job_url_is_optional_and_prints_not_found(capsys):
    from collector.models import Post

    cfg = Config(target_roles=["AI Developer"])
    post = Post(
        author="Someone",
        text=(
            "Northwind Labs is hiring an AI Engineer.\n\n"
            "Company: Northwind Labs\nLocation: Bengaluru (Hybrid)\n"
            "Employment type: Full-time\nExperience: 3-5 years\nSalary: 25-35 LPA\n\n"
            "Skills:\n- Python\n- PyTorch\n\n"
            "Responsibilities:\n- Build and ship generative AI features\n\n"
            "Requirements:\n- Strong understanding of machine learning\n\n"
            "Apply: send your resume to hr@northwindlabs.com"
        ),
        url="https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345679/",
    )

    match = decide(post, cfg)

    assert match is not None
    assert match.job_url == ""
    assert "Job listing detected" not in match.reasons

    print_match(1, match, cfg)
    out = capsys.readouterr().out
    assert "JOB URL: " + NOT_SPECIFIED in out
    assert "LINKEDIN POST: https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345679/" in out


def test_dedupe_ignores_job_url_changes():
    from collector.dedupe import Deduplicator
    from collector.models import Post

    deduper = Deduplicator()
    first = Post(text="Hiring an AI engineer, apply to hr@acme.com", job_url="https://www.linkedin.com/jobs/view/1/")
    second = Post(text="Hiring an AI engineer, apply to hr@acme.com", job_url="https://www.linkedin.com/jobs/view/2/")

    assert deduper.check_and_add(first) is False
    assert deduper.check_and_add(second) is True


@pytest.mark.parametrize(
    "href",
    [
        "https://www.linkedin.com/jobs/view/4473153699/?trackingId=abc&isJobSearch=false",
        "https://www.linkedin.com/jobs/view/4473153699/",
    ],
)
def test_same_job_id_yields_the_same_url(href):
    element = _card(href)

    url, _ = post_reader.extract_job_url(element)

    assert url == "https://www.linkedin.com/jobs/view/4473153699/"
