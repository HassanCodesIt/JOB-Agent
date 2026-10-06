from __future__ import annotations

import pytest

from collector.role_matcher import (
    ROLE_PATTERNS,
    compact,
    has_ai_context,
    match_roles,
    normalize,
)
from config import DEFAULT_ROLES


@pytest.mark.parametrize(
    "text, expected",
    [
        ("We are hiring a Generative AI Engineer in Bangalore.", "Generative AI Engineer"),
        ("Hiring: GenAI Engineer for our R&D team.", "Generative AI Engineer"),
        ("Role opening for AI Developer (Python, FastAPI).", "AI Developer"),
        ("Artificial Intelligence Software Engineer wanted.", "AI Developer"),
        ("LLM Engineer role at a Series B startup.", "LLM Engineer"),
        ("We need a Large Language Model Engineer.", "LLM Engineer"),
        ("Applied AI Engineer - remote, 3-5 years.", "Applied AI Engineer"),
        ("Applied Scientist, AI/ML research team.", "Applied AI Engineer"),
        ("Machine Learning Developer role in Hyderabad.", "Machine Learning Developer"),
        ("ML Engineer wanted for our platform team.", "Machine Learning Developer"),
        ("Hiring AI Agent Engineer - LangGraph, RAG.", "AI Agent Engineer"),
        ("Agentic AI engineer opportunity, remote.", "AI Agent Engineer"),
        ("AI Automation Engineer needed.", "AI Agent Engineer"),
        ("AI Application Developer opening in Pune.", "AI Application Developer"),
        ("AI Platform Engineer role available.", "AI Application Developer"),
        ("AI engineer wanted, apply now.", "AI Developer"),
        ("ai-engineer / ai developer (remote)", "AI Developer"),
    ],
)
def test_positive_role_variations_match(text, expected):
    result = match_roles(text)
    assert result is not None, f"no role matched for: {text}"
    assert expected in result.categories


@pytest.mark.parametrize(
    "text",
    [
        "AI-powered marketing manager wanted for our campaign team.",
        "Our new coffee machine is a machine learning masterpiece.",
        "Great read on the state of the industry.",
        "I am an AI enthusiast and love building side projects.",
        "Artificial intelligence in healthcare: a research overview.",
        "The scientist published an article about deep learning.",
        "Scientist role: we are a data-driven company hiring researchers.",
    ],
)
def test_non_role_text_does_not_match(text):
    assert match_roles(text) is None


def test_applied_scientist_requires_ai_context():
    assert match_roles("Applied Scientist wanted. Strong Java skills.") is None
    result = match_roles("Applied Scientist in Machine Learning wanted.")
    assert result is not None
    assert "Applied AI Engineer" in result.categories


def test_first_configured_role_is_the_target():
    text = "We are hiring an LLM Engineer who also works as an AI Developer."
    result = match_roles(text)
    assert result is not None
    ordered = [role for role in DEFAULT_ROLES if role in result.categories]
    assert result.target_role == ordered[0]
    assert len(result.categories) == len(ordered)
    assert result.matched_variations


def test_restricted_role_list_is_honoured():
    result = match_roles("We are hiring an LLM Engineer.", ["AI Developer"])
    assert result is None
    result = match_roles("We are hiring an AI Developer.", ["AI Developer"])
    assert result is not None and result.target_role == "AI Developer"


def test_empty_and_blank_text():
    assert match_roles("") is None
    assert match_roles("    \n  ") is None


def test_every_default_role_has_patterns():
    for role in DEFAULT_ROLES:
        assert ROLE_PATTERNS.get(role), f"no patterns for {role}"


def test_normalize_and_compact():
    assert normalize("AI/ML-Engineer") == "ai - ml - engineer"
    assert compact("AI/ML-Engineer") == "ai ml engineer"
    assert normalize("  GenAI\u200b Engineer  ") == "genai engineer"


def test_ai_context_detection():
    assert has_ai_context("we use machine learning daily") is True
    assert has_ai_context("no ml here") is True
    assert has_ai_context("accounting and bookkeeping") is False


def test_all_patterns_compile():
    for category, patterns in ROLE_PATTERNS.items():
        for pattern in patterns:
            match_roles(f"prose about {category.lower()} and machine learning")
        assert match_roles(f"hiring an {category}") is not None