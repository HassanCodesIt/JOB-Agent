from __future__ import annotations

from collector.job_detector import (
    has_meaningful_jd,
    is_job,
    jd_info_score,
    negative_flags,
    positive_score,
)

HIRING_POST = """
We are hiring an AI Engineer for our platform team.

Responsibilities:
- Build and ship LLM powered features
- Work with product and design

Requirements:
- 3+ years of experience with Python
- Strong understanding of machine learning

Location: Bengaluru (Hybrid)
Employment type: Full-time
Apply: send your resume to hr@acme.com
"""

ANNOUNCEMENT_POST = """
I joined Northwind as a Senior Machine Learning Engineer last week.
Excited to announce my new role after a long and rewarding journey.
Congratulations to everyone on the team!
"""

CONGRATS_POST = """
Congratulations to the whole team on crossing 100 customers!
Thoughts on how we should celebrate this milestone?
"""

ARTICLE_POST = """
Sharing my latest article on the state of AI infrastructure.
Here are three lessons I learned about vector databases.
"""


def test_hiring_post_is_a_job():
    is_job_post, positives, negatives = is_job(HIRING_POST)
    assert is_job_post is True
    assert positives
    assert negatives == []


def test_join_announcement_is_not_a_job():
    is_job_post, positives, negatives = is_job(ANNOUNCEMENT_POST)
    assert is_job_post is False
    assert positives == []
    assert any("joined" in flag.lower() for flag in negatives)


def test_congratulations_post_is_not_a_job():
    is_job_post, _positives, negatives = is_job(CONGRATS_POST)
    assert is_job_post is False
    assert negatives


def test_article_post_is_not_a_job():
    is_job_post, positives, _negatives = is_job(ARTICLE_POST)
    assert is_job_post is False
    assert positives == [] or not is_job_post


def test_no_positive_signal_means_not_a_job():
    is_job_post, positives, _ = is_job("We love our customers and our product.")
    assert is_job_post is False
    assert positives == []


def test_strong_apply_signal_overrides_negative():
    text = (
        "I am excited to announce that I am hiring! "
        "Apply now and send your resume, we hire fast. "
        "Responsibilities: build services. Requirements: 3 years Python."
    )
    is_job_post, positives, negatives = is_job(text)
    assert negatives
    assert len(positives) >= 2
    assert is_job_post is True


def test_negative_signal_blocks_single_positive():
    text = "We are hiring interns. I am proud to announce this myself."
    is_job_post, _positives, negatives = is_job(text)
    assert negatives
    assert is_job_post is False


def test_positive_score_counts_distinct_signals():
    text = "We are hiring! Apply now and send your resume. Walk-in interview on Monday."
    positives = positive_score(text)
    assert len(positives) >= 3


def test_overlapping_signals_are_not_double_counted():
    text = "We are hiring engineers for our team."
    positives = positive_score(text)
    assert len(positives) == 1


def test_negative_flags_detect_certification_brag():
    flags = negative_flags("I completed my AWS Machine Learning certification last week.")
    assert flags


def test_jd_info_score_counts_sections():
    score, present = jd_info_score(HIRING_POST)
    assert score >= 4
    assert "Responsibilities" in present
    assert "Requirements" in present
    assert "Apply" in present


def test_jd_info_score_low_for_small_post():
    score, _present = jd_info_score("Hiring an AI Engineer. Email hr@acme.com")
    assert score <= 2


def test_has_meaningful_jd_threshold():
    ok, score, present = has_meaningful_jd(HIRING_POST, 2)
    assert ok is True
    assert score == len(present) >= 2
    assert has_meaningful_jd("we are hiring", 2)[0] is False