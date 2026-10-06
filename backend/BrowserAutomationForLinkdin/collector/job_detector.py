from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

DEFAULT_POSITIVE_SIGNALS: Tuple[str, ...] = (
    r"\bhiring\b",
    r"\bwe'?re hiring\b",
    r"\bwe are hiring\b",
    r"\bwe'?re looking\b",
    r"\bwe are looking\b",
    r"\blooking for\b",
    r"\bapply\b",
    r"\bhow to apply\b",
    r"\bapply (now|here|at|for|via|before|by)\b",
    r"\bapplications? (are |now )?(open|closed)\b",
    r"\baccepting applications\b",
    r"\bapply (before|by)\b",
    r"\blast date to apply\b",
    r"\bsend (your |us |me |me your |us your )?(resume|cv|profile)\b",
    r"\bshare your (resume|cv|profile)\b",
    r"\bemail (us|me)\b",
    r"\binterested (candidates|professionals|applicants)\b",
    r"\bimmediate(ly)? (joining|hire|hiring|opening|start|available)\b",
    r"\bwalk[- ]?in\b",
    r"\bopen(ing)? (position|role|vacancy|vacancies|job)\b",
    r"\bjob (opening|opportunity|opportunities|vacancy|vacancies|alert|alerts|post)\b",
    r"\bwe have (an? )?(opening|opportunity|vacancy|role)\b",
    r"\bvacancy\b",
    r"\bfull[- ]?time\b",
    r"\bpart[- ]?time\b",
    r"\bcontract (role|position|work|opportunity)\b",
    r"\binternship\b",
    r"\bjoin (our|the) team\b",
    r"\bregistration open\b",
    r"\breferral\b",
    r"\bapply at\b",
    r"\bcontact us\b",
    r"\brecruiting\b",
)

STRONG_APPLY_SIGNALS: Tuple[str, ...] = (
    r"\bapply (now|here|at|for|via|before|by)\b",
    r"\bhow to apply\b",
    r"\bsend (your |us |me )?(resume|cv|profile)\b",
    r"\bshare your (resume|cv|profile)\b",
    r"\bapply (before|by)\b",
    r"\binterested (candidates|professionals|applicants)\b",
    r"\bemail (us|me)\b",
    r"\bemail (your|the) (resume|cv|profile)\b",
)

DEFAULT_NEGATIVE_SIGNALS: Tuple[str, ...] = (
    r"\bi(?:'m| am| have)? joined\b",
    r"\bi just joined\b",
    r"\bexcited to announce\b",
    r"\bexcited to share (my|our)\b",
    r"\bthrilled to announce\b",
    r"\bdelighted to announce\b",
    r"\bproud to announce\b",
    r"\bpleased to announce\b",
    r"\bhappy to announce\b",
    r"\bcongratulat\w*\b",
    r"\bmy (new|latest|recent|first) (role|job|position|journey)\b",
    r"\bmy experience as\b",
    r"\bmy (latest|new) (article|post|blog|story|publication)\b",
    r"\bsalary (discussion|negotiation|transparency)\b",
    r"\bthoughts on\b",
    r"\bwhat do you think\b",
    r"\bcompleted my\b.{0,40}\bcertificat\w*\b",
    r"\bcertified (as|in)\b",
    r"\bgraduat(ed|ing) (from|with)\b",
    r"\bcheck out my\b",
    r"\bwebinar\b",
    r"\bpanel discussion\b",
    r"\blooking for (advice|feedback|recommendations|guidance)\b",
    r"\bopen to (work|opportunities)\b",
    r"\bwork anniversary\b",
    r"\bthank you for (reading|your support)\b",
    r"\blearning (about|in)\b",
    r"\bbook (a|an) (call|demo|session)\b",
)


@dataclass(frozen=True)
class JDField:
    label: str
    pattern: str


JD_FIELDS: Tuple[JDField, ...] = (
    JDField("Responsibilities", r"\b(responsibilit(y|ies)|what you'?ll do|what you will do|key duties|day[- ]to[- ]day|the role involves|your role)\b"),
    JDField("Requirements", r"\b(requirements?|must[- ]haves?|required skills|apply if you have|you should have)\b"),
    JDField("Qualifications", r"\b(qualifications?|who (we are|'re) looking for|criteria|who should apply)\b"),
    JDField("Skills", r"\b(skills?|tech(nical)? stack|proficiency|proficient|expertise|strong (knowledge|understanding) of|familiar with|stack)\b"),
    JDField("Experience", r"(\b\d+\s*[-–]?\s*\d*\+?\s*(years?|yrs?)\b|\bexperience (of|in|required|level|with)\b|\bfresher\b|\bentry[- ]level\b|\bexperienced (candidates|professionals)\b)"),
    JDField("Eligibility", r"\b(eligib\w+|work authori[sz]ation|immediately available|notice period|indefinite)\b"),
    JDField("Location", r"(\blocation\b|\bbased in\b|\bbangalore|bengaluru|hyderabad|pune|chennai|kochi|mumbai|delhi|noida|gurugram|remote|hybrid|on[- ]?site)"),
    JDField("Salary", r"(\blpa\b|\bctc\b|\blakhs?\b|₹|\$|\bsalary\b|\bstipend\b|\bpayout\b|per (annum|month|year))"),
    JDField("Apply", r"\b(apply|how to apply|interested candidates|applications?)\b"),
    JDField("Resume/CV", r"\b(resume|cv|curriculum vitae|profile)\b"),
)


def _clean(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).replace("\u00a0", " ")
    text = text.translate(dict.fromkeys([0x200B, 0x200C, 0x200D, 0xFEFF], None))
    return re.sub(r"\s+", " ", text)


def _collapse(matches: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Merge overlapping match spans so nested/duplicated hits count once."""
    ordered = sorted(matches, key=lambda m: (m[0], -(m[1] - m[0])))
    kept: List[Tuple[int, int]] = []
    for start, end in ordered:
        if end <= start:
            continue
        if kept and start < kept[-1][1]:
            kept[-1] = (kept[-1][0], max(kept[-1][1], end))
        else:
            kept.append((start, end))
    return kept


def _matched_patterns(text: str, patterns: Sequence[str]) -> List[str]:
    spans: List[Tuple[int, int]] = []
    for pattern in patterns:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            continue
        spans.extend(m.span() for m in regex.finditer(text))
    found: List[str] = []
    for start, end in _collapse(spans):
        phrase = text[start:end].strip()
        if phrase and phrase.lower() not in [p.lower() for p in found]:
            found.append(phrase)
    return found


def positive_score(
    text: str,
    signals: Optional[Sequence[str]] = None,
) -> List[str]:
    """Distinct positive hiring signals present in the text."""
    return _matched_patterns(_clean(text), tuple(signals or DEFAULT_POSITIVE_SIGNALS))


def negative_flags(
    text: str,
    signals: Optional[Sequence[str]] = None,
) -> List[str]:
    """Non-job announcements and chatter present in the text."""
    return _matched_patterns(_clean(text), tuple(signals or DEFAULT_NEGATIVE_SIGNALS))


def has_strong_apply_signal(
    text: str,
    signals: Optional[Sequence[str]] = None,
) -> bool:
    return bool(_matched_patterns(_clean(text), tuple(signals or STRONG_APPLY_SIGNALS)))


# A "roundup" advertises many different openings at once. Such posts must not be
# captured as a single JD, especially not through the image-based path.
_ROUNDUP_PHRASE_RE = re.compile(
    r"\b(?:job|jobs|opening|openings|vacancy|vacancies|position|positions|role|roles)"
    r"\s*(?:list|roundup|round-up|compilation|digest|alert|bulletin)\b"
    r"|\b(?:roundup|round-up|compilation|job\s+alert|hiring\s+alert|weekly\s+jobs|"
    r"daily\s+jobs|monthly\s+jobs|top\s+\d+\s+jobs?|best\s+\d+\s+jobs?)\b"
    r"|\b\d+\s+(?:\w+\s+){0,2}"
    r"(?:jobs|openings|vacancies|positions|roles|opportunities)\b",
    re.IGNORECASE,
)
_LIST_ITEM_RE = re.compile(r"^\s*(?:\d+[.)]|[-*\u2022])\s+\S", re.MULTILINE)
_ROLE_WORD_RE = re.compile(
    r"\b(engineer|developer|manager|analyst|scientist|architect|designer|consultant|"
    r"specialist|administrator|programmer|lead|intern)\b",
    re.IGNORECASE,
)


def looks_like_job_roundup(text: str) -> bool:
    """Heuristic: does this post advertise several different openings?

    Catches explicit "10 jobs" / roundup wording, and numbered lists that name
    several distinct role titles. Deliberately conservative: it is only used to
    withhold the image-based collection path, never to add one.
    """
    cleaned = _clean(text)
    if not cleaned:
        return False
    if _ROUNDUP_PHRASE_RE.search(cleaned):
        return True
    items = [line for line in text.splitlines() if _LIST_ITEM_RE.match(line)]
    if len(items) >= 4:
        role_lines = sum(1 for line in items if _ROLE_WORD_RE.search(line))
        if role_lines >= 3:
            return True
    return False


def is_job(
    text: str,
    positive_signals: Optional[Sequence[str]] = None,
    negative_signals: Optional[Sequence[str]] = None,
) -> Tuple[bool, List[str], List[str]]:
    positives = positive_score(text, positive_signals)
    if not positives:
        return False, [], negative_flags(text, negative_signals)

    negatives = negative_flags(text, negative_signals)
    if negatives and not (len(positives) >= 2 and has_strong_apply_signal(text)):
        return False, positives, negatives
    return True, positives, negatives


def jd_info_score(
    text: str,
    fields: Optional[Sequence[JDField]] = None,
) -> Tuple[int, List[str]]:
    """Count distinct job-description sections present in the text."""
    cleaned = _clean(text)
    present: List[str] = []
    for jd_field in fields or JD_FIELDS:
        try:
            regex = re.compile(jd_field.pattern, re.IGNORECASE)
        except re.error:
            continue
        if regex.search(cleaned):
            present.append(jd_field.label)
    return len(present), present


def has_meaningful_jd(text: str, min_signals: int, fields: Optional[Sequence[JDField]] = None) -> Tuple[bool, int, List[str]]:
    score, present = jd_info_score(text, fields)
    return score >= min_signals, score, present