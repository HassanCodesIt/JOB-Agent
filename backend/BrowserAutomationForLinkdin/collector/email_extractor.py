from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Optional, Sequence

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@(?:[A-Za-z0-9\-]+\.)+[A-Za-z]{2,}",
    re.IGNORECASE,
)

DEFAULT_DENIED_EMAIL_DOMAINS: Sequence[str] = (
    "example.com",
    "example.org",
    "example.net",
    "example.edu",
    "test.com",
    "testing.com",
    "company.com",
    "domain.com",
    "yourdomain.com",
    "mydomain.com",
    "email.com",
    "mailinator.com",
    "gmail.test",
    "yours.com",
    "sample.com",
    "abc.com",
)

DEFAULT_PLACEHOLDER_LOCALS: Sequence[str] = (
    "name",
    "yourname",
    "your-name",
    "your_name",
    "firstname",
    "lastname",
    "fullname",
    "first.last",
    "first.lastname",
    "email",
    "e-mail",
    "emailaddress",
    "email-address",
    "emailaddress.com",
    "user",
    "username",
    "userid",
    "user.name",
    "test",
    "testing",
    "testuser",
    "someone",
    "somebody",
    "anyone",
    "candidate",
    "applicants",
    "applicant",
    "id",
    "xxx",
    "abc",
    "xyz",
    "here",
    "namehere",
    "insert",
    "placeholder",
)

IMAGE_EXTENSIONS = frozenset(
    {"png", "jpg", "jpeg", "gif", "bmp", "svg", "webp", "ico", "tif", "tiff", "avif"}
)

_TRAILING = ".,;:)]}>\"'`*|"
_LEADING = "([{<\"'`*|"

_BRACKET_MARKERS = {
    "at": "@",
    "atsign": "@",
    "at-sign": "@",
    "commercial": ".",
    "dot": ".",
    "period": ".",
    "point": ".",
}

_ZERO_WIDTH = dict.fromkeys([0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF], None)


def preprocess(text: str) -> str:
    """Normalise unicode and undo conservative e-mail obfuscations."""
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    cleaned = cleaned.replace("\u00a0", " ")

    for word, replacement in _BRACKET_MARKERS.items():
        cleaned = re.sub(
            rf"[\(\[\{{\s]+{re.escape(word)}\s*[\)\]\}}]+\s*",
            replacement,
            cleaned,
            flags=re.IGNORECASE,
        )

    cleaned = re.sub(
        r"([A-Za-z0-9._%+\-]+)\s*[\(\[]\s*(?:at|atsign)\s*[\)\]]\s*([A-Za-z0-9\-]+)",
        r"\1@\2",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"([A-Za-z0-9._%+\-]+)\s+at\s+([A-Za-z0-9\-]+)\s+(?:dot|\.)\s*([A-Za-z]{2,})",
        r"\1@\2.\3",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"([A-Za-z0-9._%+\-]+)\s+@\s+([A-Za-z0-9\-]+(?:\s+(?:dot|\.)\s+[A-Za-z0-9\-]+)+)",
        lambda m: m.group(1) + "@" + re.sub(r"\s+(?:dot|\.)\s+", ".", m.group(2)),
        cleaned,
        flags=re.IGNORECASE,
    )

    marker = cleaned.rfind("@")
    if marker != -1:
        head, tail = cleaned[: marker + 1], cleaned[marker + 1 :]
        tail = re.sub(r"\s*\.\s*(?=[A-Za-z]{2,}(?:\b|$))", ".", tail)
        tail = re.sub(r"\s*\bdot\b\s*", ".", tail, flags=re.IGNORECASE)
        cleaned = head + tail
    return cleaned


def _is_valid(candidate: str, denied_domains: Sequence[str], placeholder_locals: Sequence[str]) -> bool:
    if not candidate or "@" not in candidate:
        return False
    local, _, domain = candidate.partition("@")
    if not local or not domain or "." not in domain:
        return False
    if len(local) > 64 or len(domain) > 255:
        return False
    if ".." in local or local.startswith(".") or local.endswith("."):
        return False
    if domain.startswith("-") or ".-" in domain or domain.endswith("-"):
        return False
    if " " in candidate or any(ch in candidate for ch in "<>|\\"):
        return False

    labels = domain.split(".")
    tld = labels[-1].lower()
    if tld in IMAGE_EXTENSIONS or tld.isdigit():
        return False
    if any(label.isdigit() for label in labels):
        return False
    if len(labels) < 2 or len(tld) < 2:
        return False

    denied = {d.lower().lstrip("@") for d in denied_domains}
    if domain.lower() in denied or tld in denied:
        return False

    placeholders = {p.lower() for p in placeholder_locals}
    if local.lower() in placeholders:
        return False
    stripped = re.sub(r"[^a-z0-9.]", "", local.lower())
    if stripped in placeholders:
        return False
    if re.fullmatch(r"(?:[0-9a-f]{8,}|x{3,})", stripped):
        return False
    return True


def extract_emails(
    text: str,
    denied_domains: Optional[Sequence[str]] = None,
    placeholder_locals: Optional[Sequence[str]] = None,
) -> List[str]:
    """Return de-duplicated e-mails, lowercase, first one is the primary."""
    if not text:
        return []
    denied = tuple(denied_domains) if denied_domains is not None else DEFAULT_DENIED_EMAIL_DOMAINS
    placeholders = (
        tuple(placeholder_locals) if placeholder_locals is not None else DEFAULT_PLACEHOLDER_LOCALS
    )

    found: List[str] = []
    seen = set()
    for raw in EMAIL_RE.findall(preprocess(text)):
        candidate = raw.strip(_LEADING).strip(_TRAILING).strip()
        while candidate and candidate[-1] in _TRAILING:
            candidate = candidate[:-1]
        candidate = candidate.lower()
        if not candidate or candidate in seen:
            continue
        if not _is_valid(candidate, denied, placeholders):
            continue
        seen.add(candidate)
        found.append(candidate)
    return found


def has_email(text: str, **kwargs: Iterable) -> bool:
    return bool(extract_emails(text, **kwargs))