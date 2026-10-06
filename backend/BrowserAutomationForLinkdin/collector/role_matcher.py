from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from collector.models import RoleMatchResult

SEP = r"\s*(?:[-/|&+]\s*)?"
SPACING = " - "
_SEPARATOR_CHARS = r"\-/|&+"

ROLE_PATTERNS: Dict[str, Tuple[str, ...]] = {
    "Generative AI Engineer": (
        r"gen(erative)?~ai~(engineer|developer)",
        r"generative~artificial~intelligence~(engineer|developer)",
        r"generative~ai~tech(nical)?~lead",
    ),
    "AI Developer": (
        r"\bai~(software~)?(engineer|developer)\b",
        r"artificial~intelligence~(software~)?(engineer|developer)",
        r"\b(ai|artificial~intelligence)~software~engineer\b",
    ),
    "LLM Engineer": (
        r"\b(llm|llms|large~language~models?)~(application(s)?~)?(engineer|developer|specialist)\b",
        r"\b(genai|gen~ai)~(application(s)?~)?(engineer|developer)\b",
    ),
    "Applied AI Engineer": (
        r"applied~(ai|artificial~intelligence|machine~learning|genai|gen~ai|llm|deep~learning)~(engineer|developer|specialist)",
        r"applied~ai~research(er)?",
        r"applied~scientist",
        r"applied~research~scientist",
    ),
    "Machine Learning Developer": (
        r"\b(ml|machine~learning)~(software~)?(engineer|developer)\b",
        r"\b(ai/ml|ai-ml|aiml)~(software~)?(engineer|developer)\b",
        r"\b(machine~learning|deep~learning)~engineer\b",
    ),
    "AI Agent Engineer": (
        r"\bai~agents?~(engineer|developer|architect|builder)\b",
        r"agentic~ai~?(software~)?(engineer|developer|architect)\b",
        r"\bai~automation~engineer\b",
        r"autonomous~ai~(engineer|developer)\b",
        r"agent(ic)?~-?based~systems?~engineer\b",
    ),
    "AI Application Developer": (
        r"ai~application(s)?~(developer|engineer)\b",
        r"ai~(solutions|product|platform)~engineer\b",
        r"ai~application~developer~intern",
    ),
}

AI_GUARDED_PATTERNS = frozenset(
    {
        "applied~scientist",
        "applied~research~scientist",
        "applied~ai~research(er)?",
    }
)

AI_CONTEXT_PATTERNS: Tuple[str, ...] = (
    r"\bmachine~learning\b",
    r"\bdeep~learning\b",
    r"\bnatural~language\b",
    r"\bnlp\b",
    r"\bllm",
    r"\blarge~language~models?\b",
    r"\bartificial~intelligence\b",
    r"\bai\b",
    r"\bml\b",
    r"\bgenai\b",
    r"\bneural\b",
    r"\btensorflow\b",
    r"\bpytorch\b",
    r"\bcomputer~vision\b",
)

_ZERO_WIDTH = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD], None
)


def _compile(pattern: str) -> re.Pattern:
    return re.compile(pattern.replace("~", SEP), re.IGNORECASE)


def normalize(text: str) -> str:
    """Lowercase and space out separators so role phrases match reliably."""
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    cleaned = cleaned.replace("\u00a0", " ").replace("\u2007", " ").replace("\u202f", " ")
    cleaned = re.sub(rf"[{_SEPARATOR_CHARS}]", lambda _match: SPACING, cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.lower().strip()


def _strip_separators(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(rf"[{_SEPARATOR_CHARS}]", " ", text)).strip()


def compact(text: str) -> str:
    """Normalized text with separator characters removed (hyphen-free variant)."""
    return _strip_separators(normalize(text))


def variants(text: str) -> Tuple[str, str]:
    """Return (spaced, compacted) normalized views used for matching."""
    spaced = normalize(text)
    return spaced, _strip_separators(spaced)


def has_ai_context(text: str) -> bool:
    views = variants(text)
    return any(_compile(p).search(v) for p in AI_CONTEXT_PATTERNS for v in views)


def match_roles(
    text: str,
    roles: Optional[Sequence[str]] = None,
) -> Optional[RoleMatchResult]:
    """Match a post against the configured target roles.

    Returns the first configured matching category as the target role plus every
    variation that hit, or ``None`` when the post is not about a target role.
    """
    if not text or not text.strip():
        return None

    views = variants(text)
    ai_context = has_ai_context(text)
    requested: Iterable[str] = roles if roles else ROLE_PATTERNS.keys()

    categories: List[str] = []
    variations: List[str] = []
    for category in requested:
        patterns = ROLE_PATTERNS.get(category)
        if not patterns:
            continue
        for pattern in patterns:
            regex = _compile(pattern)
            for view in views:
                match = regex.search(view)
                if not match:
                    continue
                if pattern in AI_GUARDED_PATTERNS and not ai_context:
                    continue
                categories.append(category)
                phrase = re.sub(r"\s+", " ", match.group(0)).strip(" -,|:")
                if phrase and phrase not in variations:
                    variations.append(phrase)
                break

    if not categories:
        return None

    ordered: List[str] = []
    for category in categories:
        if category not in ordered:
            ordered.append(category)

    return RoleMatchResult(
        target_role=ordered[0],
        matched_variations=variations,
        categories=ordered,
        ai_context=ai_context,
    )