from __future__ import annotations

import argparse
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from collector.email_extractor import DEFAULT_DENIED_EMAIL_DOMAINS, DEFAULT_PLACEHOLDER_LOCALS
from collector.job_detector import DEFAULT_NEGATIVE_SIGNALS, DEFAULT_POSITIVE_SIGNALS

DEFAULT_ROLES: Tuple[str, ...] = (
    "Generative AI Engineer",
    "AI Developer",
    "LLM Engineer",
    "Applied AI Engineer",
    "Machine Learning Developer",
    "AI Agent Engineer",
    "AI Application Developer",
)

CONFIG_FILENAME = "config.yaml"


@dataclass
class Config:
    cdp_url: str = "http://localhost:9222"
    target_roles: List[str] = field(default_factory=lambda: list(DEFAULT_ROLES))
    max_scrolls: int = 10
    max_posts: int = 100
    max_jds: int = 30
    min_jd_signals: int = 2
    action_delay: Tuple[float, float] = (1.0, 2.5)
    page_load_delay: Tuple[float, float] = (2.5, 4.5)
    empty_scroll_limit: int = 3
    positive_signals: List[str] = field(default_factory=lambda: list(DEFAULT_POSITIVE_SIGNALS))
    negative_signals: List[str] = field(default_factory=lambda: list(DEFAULT_NEGATIVE_SIGNALS))
    denied_email_domains: List[str] = field(
        default_factory=lambda: list(DEFAULT_DENIED_EMAIL_DOMAINS)
    )
    placeholder_emails: List[str] = field(default_factory=lambda: list(DEFAULT_PLACEHOLDER_LOCALS))
    linkedin_feed_url: str = "https://www.linkedin.com/feed/"
    # The LinkedIn post URL is mandatory, so when the DOM yields no permalink
    # the post's own "..." menu is opened for that qualifying post. It is not
    # the first approach: DOM extraction always runs first.
    post_url_menu_fallback: bool = True
    color: bool = False
    verbose: bool = False
    quiet: bool = False
    config_file: Optional[str] = None
    dry_run: Optional[str] = None

    def delay_for(self, name: str) -> Tuple[float, float]:
        return self.action_delay if name == "action" else self.page_load_delay


def parse_delay(value: str) -> Tuple[float, float]:
    text = str(value).strip().lower()
    for separator in ("-", ","):
        if separator in text[1:]:
            left, _, right = text.partition(separator)
            try:
                low, high = float(left), float(right)
            except ValueError:
                continue
            if low > high:
                low, high = high, low
            return (max(0.0, low), max(0.0, high))
    try:
        single = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid delay: {value!r}") from exc
    return (max(0.0, single), max(0.0, single))


def parse_roles(value: str) -> List[str]:
    roles = [item.strip() for item in str(value).replace("\n", ",").split(",")]
    return [role for role in roles if role]


def _coerce(name: str, value: Any) -> Any:
    if name in {"action_delay", "page_load_delay"}:
        if isinstance(value, (list, tuple)):
            low, high = float(value[0]), float(value[-1])
            return (min(low, high), max(low, high))
        return parse_delay(str(value))
    if name in {
        "target_roles",
        "positive_signals",
        "negative_signals",
        "denied_email_domains",
        "placeholder_emails",
    }:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return list(value)
    if name in {"max_scrolls", "max_posts", "max_jds", "min_jd_signals", "empty_scroll_limit"}:
        return max(1, int(value))
    if name in {"color", "verbose", "quiet", "post_url_menu_fallback"}:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return value


def apply_overrides(cfg: Config, overrides: Dict[str, Any]) -> Config:
    known = {f.name for f in fields(Config)}
    for key, value in overrides.items():
        if key in known and value is not None:
            setattr(cfg, key, _coerce(key, value))
    return cfg


def load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit(
            "[ERROR] PyYAML is not installed. Run: pip install -r requirements.txt"
        ) from exc
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"[ERROR] {path} must contain a YAML mapping")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "Collect LinkedIn job posts for AI/ML roles from an already-open, "
            "logged-in Chrome (attaches over CDP; never closes the browser)."
        ),
    )
    parser.add_argument("--roles", dest="target_roles", type=parse_roles, help='comma separated, e.g. "LLM Engineer,AI Developer"')
    parser.add_argument("--cdp-url", dest="cdp_url", help="Chrome DevTools endpoint (default http://localhost:9222)")
    parser.add_argument("--max-scrolls", dest="max_scrolls", type=int, help="scrolls per role search (default 10)")
    parser.add_argument("--max-posts", dest="max_posts", type=int, help="hard cap on posts processed (default 100)")
    parser.add_argument("--max-jds", dest="max_jds", type=int, help="hard cap on collected JDs (default 30)")
    parser.add_argument("--min-jd-signals", dest="min_jd_signals", type=int, help="minimum JD sections required (default 2)")
    parser.add_argument("--post-url-menu-fallback", dest="post_url_menu_fallback", action="store_true", default=None, help="when a qualifying post has no permalink in its DOM, open that post's '...' menu and read 'Copy link to post' (default: on)")
    parser.add_argument("--no-post-url-menu-fallback", dest="post_url_menu_fallback", action="store_false", help="do not open the '...' menu; JDs whose post URL is absent from the DOM are then skipped")
    parser.add_argument("--action-delay", dest="action_delay", type=parse_delay, help='random delay between actions, e.g. "1.0-2.5"')
    parser.add_argument("--page-load-delay", dest="page_load_delay", type=parse_delay, help='random delay after page loads, e.g. "2.5-4.5"')
    parser.add_argument("--config", dest="config_file", help=f"path to a YAML config (default ./{CONFIG_FILENAME} when present)")
    parser.add_argument("--dry-run", dest="dry_run", nargs="?", const="tests/fixtures", help="run the decision pipeline on local .txt files instead of the browser")
    parser.add_argument("--color", action="store_true", default=None, help="enable ANSI colours")
    parser.add_argument("--no-color", dest="color", action="store_false", help="disable ANSI colours (default)")
    parser.add_argument("-v", "--verbose", action="store_true", default=None, help="verbose logging")
    parser.add_argument("-q", "--quiet", action="store_true", default=None, help="only print matches and warnings")
    return parser


def load_config(argv: Optional[Sequence[str]] = None) -> Config:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    cfg = Config()
    root = Path(__file__).resolve().parent
    yaml_path = Path(args.config_file) if args.config_file else root / CONFIG_FILENAME
    if yaml_path.exists():
        cfg.config_file = str(yaml_path)
        apply_overrides(cfg, load_yaml(yaml_path))

    cli = {key: value for key, value in vars(args).items() if key != "config_file"}
    apply_overrides(cfg, cli)

    if not cfg.target_roles:
        raise SystemExit("[ERROR] No target roles configured. Use --roles or config.yaml.")
    return cfg