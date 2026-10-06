"""Detection of external application ("apply") links inside a post.

The collector must not treat every URL in a post as an application link, so a
URL is only accepted when either

* the surrounding text shows an application intent ("apply here", "submit your
  CV", "interested candidates can apply", ...), or
* the URL itself is unmistakably an application/careers destination
  (``/careers/x``, ``/jobs/123``, ``apply.acme.com``, ``boards.greenhouse.io``).

No fixed allow-list of employers is used: the structural rules are generic
tokens plus an optional set of well-known applicant-tracking hosts, which are
only ever an *additional* signal.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

URL_RE = re.compile(r"(?i)\b((?:https?://|www\.)[^\s<>()\[\]{}\"'`]+)")

# --- text intent -----------------------------------------------------------
# Each entry is (label, pattern). A label doubles as the match reason shown to
# the user, so keep them human readable.
CONTEXT_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (
        "Apply instruction",
        r"\bapply\b|\bhow to apply\b|\bapply\s+(?:now|here|today|at|via|through|online)\b"
        r"|\bapply\s+for\s+(?:this|the)\s+\w+\b|\bapplications?\s+(?:are\s+)?open\b",
    ),
    (
        "Application submission",
        r"\bsubmit\b[^.\n]{0,40}\b(?:application|cv|resume|profile|details)\b"
        r"|\bshare\s+your\s+(?:cv|resume|profile)\b|\bsend\s+(?:your\s+)?(?:cv|resume)\b",
    ),
    (
        "Candidate invitation",
        r"\binterested\s+(?:candidates?|professionals?|applicants?|people|folks)\b"
        r"|\bcandidates?\b[^.\n]{0,25}\b(?:can|may|should|must)\s+apply\b"
        r"|\bwho\s+can\s+apply\b|\bkindly\s+apply\b",
    ),
    (
        "Application link",
        r"\bapplication\s+(?:link|url|form|portal|page)\b|\bapply\s+(?:link|url)\b"
        r"|\bjob\s+application\b|\bonline\s+application\b",
    ),
    (
        "Career page",
        r"\bcareers?\b[^.\n]{0,20}\b(?:page|portal|site|link)\b|\bcareer\s+portal\b",
    ),
    (
        "Job opening",
        r"\bjob\s*(?:s)?\s*(?:opening|openings|vacancy|vacancies|post|posts|listing|listings|alert|alerts|details?)\b"
        r"|\bvacancy\b|\bopen(?:ing|ings)?\s+(?:position|role|roles)\b",
    ),
    (
        "Recruitment link",
        r"\brecruit(?:ment|er|ing)?\b|\btalent\s+(?:portal|acquisition)\s+link\b",
    ),
    (
        "Registration",
        r"\bregister\b|\bregistration\b|\bsign\s+up\b|\benroll\b|\bfill\s+(?:out\s+)?(?:the\s+)?form\b",
    ),
)

# Phrasing that is convincing on a real link element but far too weak when it
# merely floats in post text two lines above an unrelated URL, so it is only
# honoured for anchor labels.
WEAK_CONTEXT_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (
        "Job reference",
        r"\bcheck\s+(?:out|see)\s+(?:this|the|our)\s+(?:job|role|opening|post)\b"
        r"|\bthis\s+(?:job|role|opening|vacancy)\b|\bjob\s+link\b",
    ),
)

_COMPILED_CONTEXT: Tuple[Tuple[str, re.Pattern], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE)) for label, pattern in CONTEXT_PATTERNS
)

_COMPILED_WEAK_CONTEXT: Tuple[Tuple[str, re.Pattern], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE)) for label, pattern in WEAK_CONTEXT_PATTERNS
)

# --- URL structure ---------------------------------------------------------

STRONG_PATH_RE = re.compile(
    r"(?i)/(?:careers?|jobs?|jobsearch|job-search|vacanc(?:y|ies)|openings?"
    r"|apply|applications?|apply-now|recruit(?:ment)?|positions?"
    r"|opportunit(?:y|ies)|hiring|jobopening|job-openings)(?:[/_\-.]|$)"
)

STRONG_HOST_RE = re.compile(
    r"(?i)(?:^|\.)(?:jobs?|careers?|apply|recruit(?:ment)?|vacancies|hiring|ats|boards?)\."
)

FORMS_HOST_RE = re.compile(r"(?i)(?:^|\.)forms?\.")

# Applicant-tracking platforms: an extra signal only, never a requirement.
ATS_HOST_RE = re.compile(
    r"(?i)(?:workable|greenhouse|lever\.co|ashbyhq|smartrecruiters|bamboohr|jazzhr"
    r"|taleo|icims|successfactors|jobvite|recruitee|teamtailor|personio|pinpointhq"
    r"|workday|myworkdayjobs|oraclecloud|applicantstack|recruitics|hirezoom|jobcloud"
    r"|jobspresso|givemploy|flair|jobstream|workablejobs)\."
)

BLOCKED_HOST_RE = re.compile(
    r"(?i)(?:^|\.)(?:linkedin\.com|facebook\.com|fb\.com|instagram\.com|twitter\.com"
    r"|x\.com|youtube\.com|youtu\.be|whatsapp\.com|telegram\.me|t\.me|medium\.com"
    r"|substack\.com|dev\.to|hashnode\.dev|reddit\.com|quora\.com|stackoverflow\.com"
    r"|github\.com|gitlab\.com|notion\.so|docs\.google\.com|drive\.google\.com"
    r"|dropbox\.com|calendly\.com|zoom\.us|pinterest\.com|threads\.net|mastodon\.social"
    r"|bsky\.app|glassdoor\.com|glassdoor\.co\.in)\.?$"
)

BLOCKED_PATH_RE = re.compile(
    r"(?i)/(?:articles?|blogs?|news|stories|posts?|feed|pulse|videos?|watch"
    r"|podcasts?|webinars?|events?|gallery|media|press|releases?|pdf|downloads?"
    r"|docs?|documentation|wiki|community|groups?|discussions?|courses?|training"
    r"|ebooks?|whitepapers?|reports?|surveys?|polls?|products?|pricing|features?"
    r"|about|contact|privacy|terms|cookies|legal|disclaimer|sitemap|photos?"
    r"|reviews?|ratings?)(?:[/_\-.]|$)"
)

MEDIA_EXTENSIONS = frozenset(
    {"png", "jpg", "jpeg", "gif", "bmp", "svg", "webp", "ico", "tif", "tiff", "avif", "mp4", "mp3", "pdf"}
)

_TRAILING_PUNCTUATION = ".,;:!?)]}>\"'`*|…"
_SHARE_PARAMS_RE = re.compile(
    r"(?i)[?&](?:utm_[a-z]+|sh(?:are|aring)|trackingId|midToken|trk|originalSubdomain|ref_src|encodedMidToken)="
)


def normalize_url(raw: str) -> str:
    """Strip punctuation and expand protocol-relative / www-only links."""
    if not raw:
        return ""
    url = raw.strip().strip(_TRAILING_PUNCTUATION)
    while url and url[-1] in _TRAILING_PUNCTUATION:
        url = url[:-1]
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.lower().startswith("www."):
        return "https://" + url
    return url


def _split(url: str) -> Tuple[str, str]:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "", ""
    return (parts.netloc or "").lower(), parts.path or ""


def match_context(context: str, allow_weak: bool = False) -> Optional[str]:
    """Return the label of the first application-intent phrase found."""
    if not context:
        return None
    for label, pattern in _COMPILED_CONTEXT:
        if pattern.search(context):
            return label
    if allow_weak:
        for label, pattern in _COMPILED_WEAK_CONTEXT:
            if pattern.search(context):
                return label
    return None


def _is_bare_root(path: str) -> bool:
    return path.strip("/") == ""


def classify(url: str, context: str = "", allow_weak: bool = False) -> Optional[str]:
    """Return a reason label when ``url`` is an application link, else None."""
    url = normalize_url(url)
    if not url or not url.lower().startswith(("http://", "https://")):
        return None

    host, path = _split(url)
    if not host:
        return None

    extension = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    if extension in MEDIA_EXTENSIONS:
        return None

    if BLOCKED_HOST_RE.search(host):
        return None
    if BLOCKED_PATH_RE.search(path):
        return None

    label = match_context(context, allow_weak=allow_weak)
    path_strong = bool(STRONG_PATH_RE.search(path))
    host_strong = (
        bool(STRONG_HOST_RE.search(host))
        or bool(ATS_HOST_RE.search(host))
        # A dedicated "forms." host is a form-filling destination by design.
        or bool(FORMS_HOST_RE.search(host))
    )

    if _is_bare_root(path) and not host_strong:
        # A company home page is never an application destination, even when
        # the post says "follow our company".
        return None
    if path_strong or host_strong:
        return label or "Job/Apply URL"
    if label:
        return label
    return None


def _line_context(text: str, start: int, end: int) -> str:
    """Context for a URL: its own line plus the single line above it.

    Only one preceding line is used on purpose. Wording such as "apply now" is
    frequently followed by an unrelated destination on the next line ("join our
    channel", "our website"), so pulling in two or more lines above produced
    false apply links on real posts.
    """
    if not text:
        return ""
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[max(0, line_start - 400):line_start]
    above = ""
    for line in reversed(prefix.splitlines()):
        if line.strip():
            above = line.strip()
            break
    return (above + " " if above else "") + text[line_start:end]


def extract_urls_from_text(text: str) -> List[Tuple[str, str, Optional[str]]]:
    """Return (url, reason, context) for every application link in the text."""
    found: List[Tuple[str, str, Optional[str]]] = []
    if not text:
        return found
    seen = set()
    for match in URL_RE.finditer(text):
        url = normalize_url(match.group(1))
        if not url or url in seen:
            continue
        seen.add(url)
        context = _line_context(text, match.start(), match.end())
        reason = classify(url, context)
        if reason:
            found.append((url, reason, context.strip()))
    return found


def extract_urls_from_anchors(anchors: Iterable) -> List[Tuple[str, str, Optional[str]]]:
    """Return (url, reason, context) for anchors labelled as an application link."""
    found: List[Tuple[str, str, Optional[str]]] = []
    seen = set()
    for anchor in anchors or []:
        try:
            href = anchor.get_attribute("href") or ""
        except Exception:
            continue
        url = normalize_url(_absolute(href))
        if not url or url in seen:
            continue
        seen.add(url)
        label_parts = []
        for attribute in ("aria-label", "title"):
            try:
                value = anchor.get_attribute(attribute)
            except Exception:
                value = None
            if value:
                label_parts.append(value)
        try:
            label_parts.append(anchor.inner_text() or "")
        except Exception:
            pass
        context = " ".join(part for part in label_parts if part).strip()
        reason = classify(url, context, allow_weak=True)
        if reason:
            found.append((url, reason, context))
    return found


def _absolute(href: str) -> str:
    href = (href or "").strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return f"https://www.linkedin.com{href}"
    return href


def collect_apply_urls(
    text: str,
    anchors: Optional[Sequence] = None,
    exclude: Optional[Iterable[str]] = None,
) -> List[str]:
    """All application links for a post, de-duplicated and order-preserving.

    ``exclude`` holds URLs already claimed as the LinkedIn job listing so the
    JOB URL and APPLY URL fields never overlap.
    """
    blocked = {normalize_url(url) for url in (exclude or []) if url}
    ordered: List[str] = []
    seen = set()

    for url, _reason, _context in extract_urls_from_text(text) + extract_urls_from_anchors(anchors):
        if url in blocked or url in seen:
            continue
        seen.add(url)
        ordered.append(url)
    return ordered