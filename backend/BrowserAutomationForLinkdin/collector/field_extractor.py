from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Sequence, Tuple

from collector.models import NOT_SPECIFIED, Post, RoleMatchResult

CITIES = (
    "bangalore",
    "bengaluru",
    "hyderabad",
    "pune",
    "chennai",
    "kochi",
    "coimbatore",
    "mumbai",
    "delhi",
    "new delhi",
    "noida",
    "gurugram",
    "gurgaon",
    "hyderabad",
    "ahmedabad",
    "jaipur",
    "indore",
    "kolkata",
    "trivandrum",
    "thiruvananthapuram",
    "mysuru",
    "mysore",
    "visakhapatnam",
    "bhubaneswar",
    "lucknow",
    "chandigarh",
    "goa",
    "remote",
    "hybrid",
    "on[- ]?site",
    "onsite",
    "work from home",
    "wfh",
    "anywhere in india",
)

SECTION_ALIASES: Dict[str, str] = {
    "responsibilities": "responsibilities",
    "key responsibilities": "responsibilities",
    "main responsibilities": "responsibilities",
    "your responsibilities": "responsibilities",
    "role responsibilities": "responsibilities",
    "what you will do": "responsibilities",
    "what you'll do": "responsibilities",
    "what you would do": "responsibilities",
    "about the role": "responsibilities",
    "the role": "responsibilities",
    "day to day": "responsibilities",
    "day-to-day": "responsibilities",
    "skills": "skills",
    "key skills": "skills",
    "technical skills": "skills",
    "required skills": "skills",
    "must have skills": "skills",
    "good to have": "skills",
    "good to haves": "skills",
    "nice to have": "skills",
    "nice to haves": "skills",
    "bonus points": "skills",
    "tech stack": "skills",
    "technologies": "skills",
    "requirements": "qualifications",
    "required": "qualifications",
    "must have": "qualifications",
    "must haves": "qualifications",
    "qualifications": "qualifications",
    "who we are looking for": "qualifications",
    "who we're looking for": "qualifications",
    "what we're looking for": "qualifications",
    "what they are looking for": "qualifications",
    "what they're looking for": "qualifications",
    "what you're looking for": "qualifications",
    "what you'll need": "qualifications",
    "what you need": "qualifications",
    "eligibility": "qualifications",
    "eligibility criteria": "qualifications",
    "criteria": "qualifications",
    "experience": "experience",
    "experience required": "experience",
    "apply": "apply",
    "how to apply": "apply",
    "application": "apply",
    "how to reach us": "apply",
    "contact": "apply",
    "benefits": "benefits",
    "perks": "benefits",
    "salary": "salary",
    "compensation": "salary",
}

_SECTION_NAME_CHARS = "A-Za-z &'/\u2018\u2019"
_SECTION_RE = re.compile(
    r"^\s*[\-\u2022\*\u25cf\u25aa\u00b7]?\s*(?:\d+[.)]\s*)?"
    r"(?P<name>[" + _SECTION_NAME_CHARS + r"][" + _SECTION_NAME_CHARS + r"]{1,38}?)"
    r"\s*[:\-\u2013]\s*$"
)
_HEADER_INLINE_RE = re.compile(
    r"^\s*[\-\u2022\*\u25cf\u25aa\u00b7]?\s*(?:\d+[.)]\s*)?"
    r"(?P<name>[" + _SECTION_NAME_CHARS + r"][" + _SECTION_NAME_CHARS + r"]{1,38}?)"
    r"\s*[:\-\u2013]\s+(?P<rest>\S.*)$"
)

# LinkedIn text uses typographic apostrophes ("What they\u2019re looking for"), so
# section names are normalised before the alias lookup.
_APOSTROPHES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'"})


def _normalize_section_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").translate(_APOSTROPHES).strip().lower())


_NORMALIZED_ALIASES: Dict[str, str] = {
    _normalize_section_name(key): value for key, value in SECTION_ALIASES.items()
}

STOP_SECTIONS = ("apply", "benefits", "salary", "contact")

# --- section boundaries ---------------------------------------------------
# Real posts interleave several postings, contact details and hashtags inside
# one "Skills:" block. Without these checks the splitter kept absorbing every
# following line, so location lines, e-mails and hashtags ended up listed as
# skills.

_URL_RE = re.compile(r"(?i)(?:https?://|\bwww\.|\blnkd\.in\b)")
_BARE_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
_HASHTAG_RE = re.compile(r"(?i)#\w+")

_APPLY_CTA_RE = re.compile(
    r"(?i)(?:\bapply\s*(?:$|[\s:.!)])|"
    r"\bapplications?\s+(?:are|is)\s+open\b|"
    r"\binterested\s+(?:candidates?|professionals?|applicants?|people)\b|"
    r"\binterested\?\s*share\b|"
    r"\bshare\s+(?:me\s+|us\s+|your\s+)?(?:the\s+|your\s+|updated\s+)*(?:cv|resume|profile)\b|"
    r"\bsend\s+(?:me\s+|us\s+|your\s+)?(?:the\s+|your\s+|updated\s+)*(?:cv|resume)\b|"
    r"\blast\s+date\s+to\s+apply\b|\bapply\s+by\b)"
)

_SHARE_CTA_RE = re.compile(
    r"(?i)(?:\bshare\s+(?:this|the)\s+(?:post|job|role|opportunity|listing)\b|"
    r"\btag\s+(?:someone|friends|us|them|a\s+friend|your)\b|"
    r"\breferences?\s+are\s+also\s+welcome\b|"
    r"\bfeel\s+free\s+to\s+share\b|"
    r"\bdm\s+me\s+directly\b|"
    r"\brefer\s+someone\b|"
    r"\bdo\s+you\s+know\s+someone\b|"
    r"\bplease\s+share\s+(?:this|it)\b)"
)

_FIELD_LABEL_RE = re.compile(
    r"(?i)^(?:location|experience|exposure|age|skills?|key\s+skills|required\s+skills"
    r"|requirements?|qualifications?|responsibilit(?:y|ies)|salary|ctc|stipend|compensation"
    r"|employment\s+type|work\s+mode|apply|application|contact|email|phone|notice\s+period"
    r"|duration|interview|position|role|company|department|industry"
    r"|preferred\s+industry\s+experience|suitable\s+profiles|open\s+positions"
    r"|engagement|priority|working\s+hours|office\s+visit|apply\s+by|last\s+date|job\s+title)\b"
)

_ROLE_WORD_RE = re.compile(
    r"(?i)\b(?:engineer|developer|scientist|analyst|consultant|architect|specialist|manager)\b"
)

_SYMBOL_BULLETS = "\u2022\u00b7\u25cf\u25aa\u2023\u2043*->"


def _split_leading_symbol(line: str) -> Tuple[bool, str]:
    """Strip leading emoji/bullet symbols; report whether any were present."""
    index = 0
    had_symbol = False
    while index < len(line):
        char = line[index]
        if char in _SYMBOL_BULLETS or unicodedata.category(char)[0] == "S":
            had_symbol = True
            index += 1
            continue
        if char.isspace() and had_symbol:
            index += 1
            continue
        break
    return had_symbol, line[index:].strip()


def is_section_boundary(line: str) -> bool:
    """True when a line clearly belongs to a different field, not to the
    currently open section."""
    if not line:
        return False
    stripped = line.strip()
    if not stripped:
        return False

    if _URL_RE.search(stripped):
        return True

    had_symbol, body = _split_leading_symbol(stripped)
    body = body or stripped

    if _BARE_EMAIL_RE.match(body.replace(" ", "")):
        return True
    if len(_HASHTAG_RE.findall(stripped)) >= 2:
        return True
    if _SHARE_CTA_RE.search(stripped):
        return True
    if _APPLY_CTA_RE.search(stripped):
        return True
    if had_symbol and _FIELD_LABEL_RE.match(body):
        return True
    # A new posting announced mid-post, e.g. a second role in the same thread.
    if had_symbol and ":" not in stripped and len(stripped) <= 70 and _ROLE_WORD_RE.search(stripped):
        return True
    return False

APPLY_HINTS = (
    "apply",
    "send",
    "email",
    "mail",
    "resume",
    "cv",
    "whatsapp",
    "interested",
    "reach out",
    "drop your",
    "dm ",
    "connect",
)

EMPLOYMENT_TYPES = (
    "full[- ]?time",
    "fulltime",
    "part[- ]?time",
    "intern(ship)?",
    "contract(ual)?",
    "freelance",
    "temporary",
    "permanent",
    "remote",
)


def _clean_lines(text: str) -> List[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _first_match(pattern: str, text: str, group: int = 0, flags: int = re.IGNORECASE) -> Optional[str]:
    match = re.search(pattern, text, flags)
    if not match:
        return None
    value = match.group(group) if group else match.group(0)
    value = re.sub(r"\s+", " ", value).strip(" \t-*\u2022|,:.\u2013")
    return value or None


def extract_role(text: str, role_match: Optional[RoleMatchResult] = None) -> str:
    explicit = _first_match(
        r"(?:hiring|we'?re hiring|we are hiring|looking) (?:for|an?)\s+(?:an?\s+)?([A-Za-z][A-Za-z0-9 /\-&+]{2,60})",
        text,
        1,
    )
    labelled = _first_match(
        r"\b(?:role|position|title|job title)\s*[:\-]\s*([A-Za-z][A-Za-z0-9 /\-&+]{2,60})", text, 1
    )
    for candidate in (labelled, explicit):
        if candidate and re.search(r"\b(engineer|developer|scientist|analyst|architect|manager|intern|lead)\b", candidate, re.I):
            return candidate.title() if candidate.islower() else candidate
    if role_match and role_match.matched_variations:
        return role_match.matched_variations[0].title()
    if role_match and role_match.target_role:
        return role_match.target_role
    return NOT_SPECIFIED


_NAME = r"[A-Za-z0-9][A-Za-z0-9 &'/\.\-]{1,38}"
_NAME_CASED = r"[A-Z][A-Za-z0-9 &'/\.\-]{1,38}"
_STOP = r"(?=\s+(?:is|has|are|was|for|in|at|and|with|offers?|invites?)\b|[,;:.\n]|$)"
_COMPANY_STOP_WORDS = frozenset(
    {"we", "i", "our", "us", "the", "there", "this", "who", "a", "an", "they", "it"}
)
_COMPANY_REJECT_WORDS = frozenset(
    {
        "apply",
        "candidate",
        "candidates",
        "company",
        "contact",
        "cv",
        "description",
        "email",
        "experience",
        "hello",
        "hi",
        "interview",
        "job",
        "jobs",
        "link",
        "links",
        "location",
        "mail",
        "me",
        "my",
        "note",
        "post",
        "reg",
        "regs",
        "reference",
        "references",
        "resume",
        "role",
        "salary",
        "send",
        "share",
        "skills",
        "your",
    }
)
_LEADING_STOP_WORDS = frozenset(
    {
        "we",
        "i",
        "our",
        "us",
        "the",
        "this",
        "that",
        "they",
        "a",
        "an",
        "job",
        "role",
        "company",
        "team",
        "please",
        "am",
        "are",
        "is",
        "was",
        "have",
        "has",
        "will",
        "can",
    }
)


def extract_company(text: str) -> str:
    labelled = _first_match(
        r"\b(?:company|organisation|organization|employer|firm)\s*[:\-]\s*(" + _NAME + r")",
        text,
        1,
    )
    if labelled:
        return _tidy_company(labelled)

    patterns = (
        r"\bhiring at\s+(" + _NAME_CASED + r")" + _STOP,
        r"\b(" + _NAME_CASED + r")\s+is\s+(?:hiring|looking|actively hiring)\b",
        r"\b(?:join|joining)\s+(" + _NAME_CASED + r")" + _STOP,
        r"\bat\s+(" + _NAME_CASED + r")" + _STOP,
        r"\b([A-Z][A-Za-z0-9&'\.\-]{1,30})\s+(?:is\s+)?(?:hiring|has (?:an?\s+)?open(?:ings?|ing)?|has an opening)\b",
    )
    for pattern in patterns:
        found = _first_match(pattern, text, 1, flags=0)
        if found:
            cleaned = _tidy_company(found)
            if cleaned.lower() not in _COMPANY_STOP_WORDS:
                return cleaned
    return NOT_SPECIFIED


def _tidy_company(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip(" .,;:-&/'\u2019")
    cleaned = re.sub(r"\s+(?:is|has|for|in|at|and)$", "", cleaned, flags=re.IGNORECASE)
    words = cleaned.split()
    while len(words) > 1 and words[0].lower().strip(",.") in _LEADING_STOP_WORDS:
        words.pop(0)
    if len(words) > 5:
        words = words[:5]
    cleaned = " ".join(words).strip(" .,;:-&/'\u2019")
    if not cleaned or cleaned.lower() in _COMPANY_STOP_WORDS | _LEADING_STOP_WORDS:
        return NOT_SPECIFIED
    head = cleaned.split()[0].lower().strip(".,")
    if head in {"we", "i", "our", "us", "they", "please"} or head in _COMPANY_REJECT_WORDS:
        return NOT_SPECIFIED
    return cleaned


def extract_location(text: str) -> str:
    labelled = _first_match(
        r"\b(?:location|work ?location|office|location/office)\s*[:\-]?\s*("
        r"[A-Za-z][A-Za-z0-9 ,./\-]{1,48}?)"
        r"(?=\s+(?:remote|hybrid|on[- ]?site|full[- ]?time|contract)\b|[,;\n]|$)",
        text,
        1,
    )
    if labelled:
        value = re.sub(r"\s+", " ", labelled).strip(" .,;:-")
        if len(value) >= 2:
            return _pretty(value)

    city = _first_match(r"\b(" + "|".join(CITIES) + r")\b", text, 1)
    if city:
        value = re.sub(r"-{2,}", "-", city).strip()
        if len(value) >= 2:
            if value.lower() == "wfh":
                return "Work From Home"
            if value.lower() == "on-site":
                return "On-site"
            return value.title()

    return NOT_SPECIFIED


def extract_experience(text: str) -> str:
    patterns = (
        r"\b\d+\s*(?:-|–|to)\s*\d+\+?\s*(?:years?|yrs?)",
        r"\b(?:minimum|at least)\s+\d+\+?\s*(?:years?|yrs?)",
        r"\bexperience\s*(?:of|:)?\s*\d+\s*(?:-|–|to)?\s*\d*\+?\s*(?:years?|yrs?)",
        r"\b\d+\+?\s*(?:years?|yrs?)\s+of\s+(?:hands[- ]on\s+)?experience\b",
        r"\b\d+\+?\s*(?:years?|yrs?)\b",
        r"\b(?:freshers?|entry[- ]level)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = re.sub(r"\s+", " ", match.group(0)).strip()
            value = re.sub(
                r"^(?:experience|exp)\s*(?:of|:)?\s*", "", value, flags=re.IGNORECASE
            ).strip()
            return _pretty(value) if value else NOT_SPECIFIED
    return NOT_SPECIFIED


def _pretty(value: str) -> str:
    """Title-case a value only when it is purely alphabetic."""
    if value.islower() and not re.search(r"\d", value):
        return value.title()
    return value


def extract_salary(text: str) -> str:
    patterns = (
        r"(?:₹|\$|rs\.?|inr)\s?\d[\d,.]*\s*(?:k|lakh|lakhs|lpa|lp|per annum|per month|/month|/annum|p\.a\.)?(?:\s*(?:to|-)\s*(?:₹|\$|rs\.?|inr)?\s?\d[\d,.]*\s*(?:k|lakh|lakhs|lpa|lp)?)?",
        r"\b\d+(?:\.\d+)?\s*(?:-|–|to)\s*\d+(?:\.\d+)?\s*(lpa|lakhs?|ctc)\b",
        r"\b\d+(?:\.\d+)?\s*(lpa|ctc)\b",
        r"\b(?:stipend|salary|compensation|payout|ctc|lpa)\b[^\n.;]{0,60}",
    )
    for pattern in patterns:
        found = _first_match(pattern, text, 0)
        if found:
            return found
    return NOT_SPECIFIED


def extract_employment_type(text: str) -> str:
    for pattern in EMPLOYMENT_TYPES:
        match = re.search(r"\b" + pattern + r"\b", text, re.IGNORECASE)
        if match:
            value = match.group(0).strip()
            if re.fullmatch(r"remote", value, re.IGNORECASE):
                return "Remote"
            return value.upper() if len(value) <= 4 else value.title()
    return NOT_SPECIFIED


# A header can carry a lead-in on the same line ("Preferred Skills : We Are
# Looking For"). That lead-in is a label, not content, so it must not end up as
# a skill or requirement bullet.
_LEAD_IN_RE = re.compile(
    r"^(?:who|what|we)\b[^:]{0,40}\blooking\s+for\b",
    re.IGNORECASE,
)


def _is_section_lead_in(text: str) -> bool:
    candidate = (text or "").strip()
    if not candidate or len(candidate.split()) > 7:
        return False
    if _normalize_section_name(candidate) in _NORMALIZED_ALIASES:
        return True
    return bool(_LEAD_IN_RE.match(candidate))


def _split_sections(text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    lines = text.splitlines()
    for raw in lines:
        line = raw.strip()
        if not line:
            if current:
                sections.setdefault(current, [])
            continue

        inline = _HEADER_INLINE_RE.match(line)
        plain = _SECTION_RE.match(line)
        header_name = None
        remainder = None
        if inline:
            header_name = inline.group("name").strip().lower()
            remainder = inline.group("rest").strip()
        elif plain:
            header_name = plain.group("name").strip().lower()

        if header_name:
            key = _NORMALIZED_ALIASES.get(_normalize_section_name(header_name))
            if key is None and "responsibilit" in header_name:
                key = "responsibilities"
            if key is None and ("requirement" in header_name or "qualif" in header_name):
                key = "qualifications"
            if key is None and ("skill" in header_name or "stack" in header_name or "technolog" in header_name):
                key = "skills"
            if key is None and ("apply" in header_name or "contact" in header_name):
                key = "apply"
            if key is None and ("benefit" in header_name or "perk" in header_name):
                key = "benefits"
            if key is None and ("experience" in header_name):
                key = "experience"
            if key is None and ("location" in header_name):
                key = "location"

        if header_name and key:
            current = key
            sections.setdefault(current, [])
            if remainder and not _is_section_lead_in(remainder):
                    # A lead-in remainder ("Preferred Skills : We Are Looking
                    # For") labels the list instead of belonging to it.
                    sections[current].append(remainder)
            continue

        if is_section_boundary(line):
            # Contact details, other postings and hashtags end the open section.
            current = None
            continue

        if current in STOP_SECTIONS and current != "apply":
            current = None
        if current:
            sections[current].append(re.sub(r"^[\-\u2022\*\u25cf\u00b7\)\]]+\s*", "", line))
    return sections


def _bullets(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", value).strip(" ;\t")
        if not cleaned or len(cleaned) < 2:
            continue
        if cleaned not in out:
            out.append(cleaned)
    return out


def extract_sections(text: str) -> Dict[str, List[str]]:
    sections = _split_sections(text)
    return {
        "skills": _bullets(sections.get("skills", [])),
        "responsibilities": _bullets(sections.get("responsibilities", [])),
        "qualifications": _bullets(sections.get("qualifications", [])),
    }


def extract_application_instructions(text: str, emails: Optional[Sequence[str]] = None) -> List[str]:
    instructions: List[str] = []
    sections = _split_sections(text).get("apply", [])
    for value in sections:
        if value not in instructions:
            instructions.append(value)

    for raw in _clean_lines(text):
        line = re.sub(r"^[\-\u2022\*\u25cf\u00b7\)\]]+\s*", "", raw).strip()
        if not line:
            continue
        lowered = line.lower()
        if any(hint in lowered for hint in APPLY_HINTS):
            if any(email in lowered for email in emails or []):
                if line not in instructions:
                    instructions.append(line)
            elif len(line) > 12 and line not in instructions:
                instructions.append(line)

    if emails and not any("@" in item for item in instructions):
        instructions.append("Send your resume/CV to: " + ", ".join(emails))

    cleaned = _bullets(instructions)
    return cleaned[:8]


def extract_fields(
    post: Post,
    role_match: Optional[RoleMatchResult] = None,
    emails: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    """Heuristically extract JD fields; missing values fall back to defaults."""
    text = post.text or ""
    sections = extract_sections(text)
    experience = NOT_SPECIFIED
    for candidate in sections.get("qualifications", []) + sections.get("skills", []):
        found = extract_experience(candidate)
        if found != NOT_SPECIFIED:
            experience = found
            break
    if experience == NOT_SPECIFIED:
        experience = extract_experience(text)

    return {
        "role": extract_role(text, role_match),
        "company": extract_company(text),
        "location": extract_location(text),
        "experience": experience,
        "salary": extract_salary(text),
        "employment_type": extract_employment_type(text),
        "skills": sections["skills"],
        "responsibilities": sections["responsibilities"],
        "qualifications": sections["qualifications"],
        "application_instructions": extract_application_instructions(text, emails),
        "job_description": text.strip(),
        "author": post.author.strip() or NOT_SPECIFIED,
    }