from __future__ import annotations

import pytest

from collector.email_extractor import extract_emails, has_email, preprocess


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Reach us at hr@acme.com", ["hr@acme.com"]),
        ("Personal: ramesh.kumar@gmail.com", ["ramesh.kumar@gmail.com"]),
        ("Mail: ramesh.kumar+ai@outlook.com.", ["ramesh.kumar+ai@outlook.com"]),
        ("Write to careers@careers.acme.co.in now", ["careers@careers.acme.co.in"]),
        ("Contact talent@peoplehire.com.au (Sydney)", ["talent@peoplehire.com.au"]),
        ("send cv to SDE_Team@Tech-Mahindra.co.uk", ["sde_team@tech-mahindra.co.uk"]),
        ("Multiple: hr@acme.com, ta@acme.com and jobs@beta.io", ["hr@acme.com", "ta@acme.com", "jobs@beta.io"]),
        ("Duplicates: HR@acme.com and hr@acme.com", ["hr@acme.com"]),
        ("Wrapped (info@acme.com)", ["info@acme.com"]),
    ],
)
def test_plain_formats(text, expected):
    assert extract_emails(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("reach us at ramesh [at] acme [dot] com", ["ramesh@acme.com"]),
        ("ramesh(at)acme.com", ["ramesh@acme.com"]),
        ("ramesh [at] acme [dot] co [dot] in", ["ramesh@acme.co.in"]),
        ("ramesh @ acme . com", ["ramesh@acme.com"]),
        ("ramesh at acme dot com", ["ramesh@acme.com"]),
        ("(at) hr(at)acme(dot)io", ["hr@acme.io"]),
    ],
)
def test_obfuscated_formats(text, expected):
    assert extract_emails(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "no address here at all",
        "example@example.com is a placeholder",
        "name@company.com is a placeholder",
        "profile image logo@2x.png should not match",
        "contact us at mailinator.com inbox",
        "user@domain.com is fake",
    ],
)
def test_placeholders_are_rejected(text):
    assert extract_emails(text) == []


def test_image_filenames_rejected():
    assert extract_emails("banner@2x.png and shot@3x.jpeg") == []


def test_preprocess_keeps_normal_text():
    assert preprocess("Contact hr@acme.com for details.") == "Contact hr@acme.com for details."


def test_has_email_helper():
    assert has_email("write to hr@acme.com") is True
    assert has_email("write to hr at acme dot com") is True
    assert has_email("nothing here") is False


def test_custom_denylist():
    text = "reach hr@acme.com or hr@other.com"
    emails = extract_emails(text, denied_domains=["acme.com"])
    assert emails == ["hr@other.com"]


def test_no_keyword_requirement():
    emails = extract_emails("ping kiran.iyer@zephyrlabs.dev")
    assert emails == ["kiran.iyer@zephyrlabs.dev"]


def test_empty_input():
    assert extract_emails("") == []