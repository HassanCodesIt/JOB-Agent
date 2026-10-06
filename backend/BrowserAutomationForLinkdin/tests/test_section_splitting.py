"""Regression tests for section splitting on real LinkedIn posts.

Every sample is taken verbatim from a live run, including the LinkedIn
typographic apostrophes and emoji-prefixed field labels.
"""

from __future__ import annotations

from collector.field_extractor import extract_application_instructions, extract_sections

POST_19 = (
    "\U0001F680 We\u2019re Hiring | AI/ML Engineer\n"
    "Experience: 2\u20135 Years\n"
    "Location: Delhi\n"
    "\n"
    "Key Skills:\n"
    "\u2022 Strong Python & Machine Learning\n"
    "\u2022 Scikit-learn, XGBoost, PyTorch/TensorFlow\n"
    "\u2022 Docker, Git & Cloud (AWS/GCP/Azure)\n"
    "\n"
    "Good to Have: Banking/FinTech AI, OCR/Document AI, LLM fine-tuning.\n"
    "\n"
    "\U0001F4E9 Interested candidates can share their CV at:\n"
    "archana.chaurasia@nexensus.com\n"
    "\n"
    "#Hiring #AIML #MachineLearning #GenerativeAI #LLM"
)

POST_26 = (
    "\U0001F680 We\u2019re Hiring | AI & Automation Engineer\n"
    "Key Skills:\n"
    "Python & JavaScriptAI\n"
    "Automation & Generative AI\n"
    "AI Agents & RAG\n"
    "Git/GitHub\n"
    "\n"
    "\U0001F4CD Location: Jaipur | Onsite Only\n"
    "\U0001F4BC Experience: 0\u20131 Years\n"
    "\U0001F4E9 Apply: hiring@bookkeeping.co.in\n"
    "\U0001F4DE Contact: 9509081066\n"
    "\n"
    "#Hiring #WeAreHiring #AIEngineer #JaipurJobs"
)

POST_27 = (
    "\U0001F680 WE\u2019RE HIRING | MULTIPLE OPENINGS\n"
    "\U0001F519 Senior AI Engineer \u2013 Generative AI\n"
    "\U0001F4CD Hyderabad | Ahmedabad | Indore |\n"
    "\U0001F4BC 4\u20138 Years\n"
    "Skills: Python, LLM, RAG, LangChain, LangGraph, LlamaIndex, "
    "Prompt Engineering, FastAPI/Flask, Docker, Kubernetes, OpenAI/Azure OpenAI.\n"
    "\n"
    "\U0001F519 Data Scientist \u2013 Credit Risk Modelling\n"
    "\U0001F4CD Mumbai (WFO) |\n"
    "\U0001F4BC 3\u20134 YearsSkills: Credit Risk Modelling, Predictive Statistical "
    "Modelling, Scorecard Development, SQL, Python/R, ML.\n"
    "\n"
    "\U0001F4E9 Interested? Share your updated CV: deepika.pilwan@appzime.com\n"
    "\n"
    "\U0001F501 Tag / Refer someone who could be a great fit!"
    "#Hiring #AIJobs #GenerativeAI #DataScience"
)

POST_28 = (
    "MailerMen is hiring a Generative AI / LLM Engineer (Fresher) in Indore.\n"
    "What you\u2019ll do:\n"
    "Evaluate model quality/latency/cost, build LLM-powered features.\n"
    "What they\u2019re looking for:\n"
    "\u2705 Bachelor\u2019s in CS, AI, IT, or related field\n"
    "\u2705 Python + REST APIs + Git\n"
    "\u2705 LLM fundamentals + AI application development\n"
    "Good to have: LlamaIndex, LangChain, Vector Databases, Docker, Guardrails.\n"
    "Apply here \U0001F449 https://lnkd.in/enPki58H\n"
    "#Hiring #JobAlert #GenerativeAI #LLMEngineer"
)

_NOISE = (
    "interested candidates",
    "share their",
    "apply",
    "location",
    "experience:",
    "contact",
    "#hiring",
    "https://",
    "lnkd.in",
    "data scientist",
    "mumbai",
)


def _assert_clean(values):
    joined = " ".join(values).lower()
    for needle in _NOISE:
        assert needle not in joined, f"{needle!r} leaked into {values}"


def test_post_19_skills_are_clean():
    sections = extract_sections(POST_19)

    assert sections["skills"] == [
        "Strong Python & Machine Learning",
        "Scikit-learn, XGBoost, PyTorch/TensorFlow",
        "Docker, Git & Cloud (AWS/GCP/Azure)",
        "Banking/FinTech AI, OCR/Document AI, LLM fine-tuning.",
    ]


def test_post_26_skills_are_clean():
    sections = extract_sections(POST_26)

    assert sections["skills"] == [
        "Python & JavaScriptAI",
        "Automation & Generative AI",
        "AI Agents & RAG",
        "Git/GitHub",
    ]


def test_post_27_skills_are_clean():
    sections = extract_sections(POST_27)

    assert len(sections["skills"]) == 1
    _assert_clean(sections["skills"])
    _assert_clean(sections["responsibilities"])
    _assert_clean(sections["qualifications"])


def test_post_28_sections_are_split_correctly():
    sections = extract_sections(POST_28)

    assert sections["responsibilities"] == [
        "Evaluate model quality/latency/cost, build LLM-powered features."
    ]
    assert sections["qualifications"] == [
        "\u2705 Bachelor\u2019s in CS, AI, IT, or related field",
        "\u2705 Python + REST APIs + Git",
        "\u2705 LLM fundamentals + AI application development",
    ]
    # The apply link must never appear inside a structured list.
    _assert_clean(sections["skills"])
    _assert_clean(sections["qualifications"])
    _assert_clean(sections["responsibilities"])


# --- boundary unit tests --------------------------------------------------


def test_url_ends_the_section():
    sections = extract_sections("Skills:\n- Python\nApply here: https://lnkd.in/abc")
    assert sections["skills"] == ["Python"]


def test_bare_email_ends_the_section():
    sections = extract_sections("Skills:\n- Python\njobs@acme-ai.com\n- Docker")
    assert sections["skills"] == ["Python"]


def test_hashtag_run_ends_the_section():
    sections = extract_sections("Skills:\n- Python\n#Hiring #AIJobs #Remote")
    assert sections["skills"] == ["Python"]


def test_share_cta_ends_the_section():
    sections = extract_sections("Skills:\n- Python\nPlease share this post with your network.")
    assert sections["skills"] == ["Python"]


def test_emoji_field_label_ends_the_section():
    sections = extract_sections("Skills:\n- Python\n\U0001F4CD Location: Jaipur\n- Docker")
    assert sections["skills"] == ["Python"]


def test_second_posting_heading_ends_the_section():
    sections = extract_sections("Skills:\n- Python\n\U0001F519 Data Scientist \u2013 Credit Risk")
    assert sections["skills"] == ["Python"]


def test_plain_skill_bullets_are_not_mistaken_for_boundaries():
    sections = extract_sections(
        "Skills:\n"
        "\u2705 Strong Python & Machine Learning\n"
        "\u2705 AI/ML Engineering\n"
        "\u2705 Data Science & Analytics\n"
        "- Docker & Kubernetes\n"
        "\u2022 RAG pipelines\n"
    )
    # Checkmarks stay in the value (existing behaviour); the point here is that
    # none of these bullet lines are treated as section boundaries.
    assert sections["skills"] == [
        "\u2705 Strong Python & Machine Learning",
        "\u2705 AI/ML Engineering",
        "\u2705 Data Science & Analytics",
        "Docker & Kubernetes",
        "RAG pipelines",
    ]


def test_curly_apostrophe_headers_are_recognised():
    assert extract_sections("What you\u2019ll do:\n- Build agents")["responsibilities"] == [
        "Build agents"
    ]
    assert extract_sections("Who we\u2019re looking for:\n- Python 3+")["qualifications"] == [
        "Python 3+"
    ]


def test_good_to_have_is_treated_as_skills():
    sections = extract_sections("Skills:\n- Python\n\nGood to Have:\n- Docker\n- Kubernetes")
    assert sections["skills"] == ["Python", "Docker", "Kubernetes"]


def test_standalone_good_to_have_header_does_not_drop_bullets():
    sections = extract_sections("Key Skills:\n- Python\n\nGood to Have:\n- Docker\n- Kubernetes")
    assert "Docker" in sections["skills"]
    assert "Kubernetes" in sections["skills"]

def test_header_lead_in_on_the_same_line_is_not_a_skill():
    """Regression: "Preferred Skills : We Are Looking For" leaked a label
    into SKILLS, and the real bullets were still needed."""
    sections = extract_sections(
        "Were Hiring: GenAI Engineers\n"
        "Preferred Skills : We Are Looking For\n"
        "- Python\n"
        "- Generative AI & Large Language Models (LLMs)\n"
    )

    assert sections["skills"] == ["Python", "Generative AI & Large Language Models (LLMs)"]
    assert "We Are Looking For" not in sections["skills"]


def test_inline_header_value_is_still_kept_when_it_is_real_content():
    """A header carrying genuine content must not lose it."""
    sections = extract_sections(
        "Skills: Python, PyTorch\n"
        "Apply: send your resume to hr@example.com\n"
    )

    assert sections["skills"] == ["Python, PyTorch"]
    assert any(
        "hr@example.com" in line
        for line in extract_application_instructions(
            "Apply: send your resume to hr@example.com\n"
        )
    )
