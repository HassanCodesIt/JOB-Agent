from __future__ import annotations

from collector import field_extractor
from collector.models import NOT_SPECIFIED, Post
from collector.role_matcher import match_roles

FULL_POST = """
Ankit Sharma
We are hiring an AI Engineer at Northwind Labs!

Company: Northwind Labs
Location: Bengaluru (Hybrid)
Employment type: Full-time
Experience: 3-5 years
Salary: 25-35 LPA

Skills:
- Python
- PyTorch
- LLM orchestration

Responsibilities:
- Build generative AI features
- Partner with product teams

Requirements:
- Strong understanding of machine learning
- Experience with vector databases

Apply: send your resume to hr@northwindlabs.com or careers@northwindlabs.co.in
"""

MINIMAL_POST = Post(author="Someone", text="We are hiring. Email us.", url="")


def test_extract_fields_from_rich_post():
    role_result = match_roles(FULL_POST)
    fields = field_extractor.extract_fields(Post(author="Ankit Sharma", text=FULL_POST), role_result)

    assert "AI Engineer" in fields["role"]
    assert fields["company"] == "Northwind Labs"
    assert "Bengaluru" in fields["location"]
    assert fields["experience"] != NOT_SPECIFIED
    assert fields["salary"] != NOT_SPECIFIED
    assert fields["employment_type"].lower() == "full-time"
    assert "Python" in fields["skills"]
    assert any("generative ai" in item.lower() for item in fields["responsibilities"])
    assert fields["qualifications"]
    assert fields["job_description"].strip() == FULL_POST.strip()


def test_missing_fields_default_to_not_specified():
    fields = field_extractor.extract_fields(MINIMAL_POST)
    assert fields["company"] == NOT_SPECIFIED
    assert fields["location"] == NOT_SPECIFIED
    assert fields["experience"] == NOT_SPECIFIED
    assert fields["salary"] == NOT_SPECIFIED
    assert fields["employment_type"] == NOT_SPECIFIED
    assert fields["skills"] == []
    assert fields["job_description"] == "We are hiring. Email us."


def test_application_instructions():
    fields = field_extractor.extract_fields(Post(text=FULL_POST))
    joined = " ".join(fields["application_instructions"]).lower()
    assert "resume" in joined or "hr@northwindlabs.com" in joined


def test_application_instructions_include_email_fallback():
    text = "We are hiring an AI Engineer. Please get in touch."
    instructions = field_extractor.extract_application_instructions(text, ["jobs@acme.com"])
    assert any("jobs@acme.com" in item for item in instructions)


def test_location_remote_and_hybrid():
    assert "Remote" in field_extractor.extract_location("Work location: Remote")
    assert "Hybrid" in field_extractor.extract_location("This role is hybrid, 3 days in office")
    assert "Bangalore" in field_extractor.extract_location("Based in Bangalore, India")


def test_company_from_hiring_sentence():
    assert field_extractor.extract_company("Acme Robotics is hiring an AI Engineer.") == "Acme Robotics"
    assert field_extractor.extract_company("Hiring at Zenith Data, apply now") == "Zenith Data"


def test_experience_variants():
    assert "fresher" in field_extractor.extract_experience("Freshers can apply").lower()
    assert "years" in field_extractor.extract_experience("3+ years of experience").lower()
    assert field_extractor.extract_experience("no numbers here") == NOT_SPECIFIED


def test_experience_range_worded_with_to():
    assert field_extractor.extract_experience("We need 3 to 5 years of experience") == "3 to 5 years"
    assert field_extractor.extract_experience("Experience: 2 to 4 yrs") == "2 to 4 yrs"
    assert field_extractor.extract_experience("Minimum 3+ years") == "Minimum 3+ years"
    assert field_extractor.extract_experience("5 years of experience required") == "5 years of experience"


def test_location_not_inferred_from_remote_wording():
    text = "Location: Bengaluru\nWork mode: Remote"
    assert field_extractor.extract_location(text) == "Bengaluru"


def test_salary_variants():
    assert "LPA" in field_extractor.extract_salary("CTC of 30 LPA").upper()
    assert "₹" in field_extractor.extract_salary(" stipend of ₹25,000 per month")
    assert field_extractor.extract_salary("no numbers") == NOT_SPECIFIED


def test_sections_parsed_until_next_header():
    text = "Skills:\n- Python\n- SQL\n\nRequirements:\n- 3 years experience"
    sections = field_extractor.extract_sections(text)
    assert sections["skills"] == ["Python", "SQL"]
    assert sections["qualifications"] == ["3 years experience"]