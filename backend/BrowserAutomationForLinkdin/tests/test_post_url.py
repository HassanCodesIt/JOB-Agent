"""The ordered LinkedIn post-URL lookup.

Covers each evidence source in priority order, the separation from the job
URL, and the rule that a URL is never guessed: unidentified posts report
"Not found".
"""

from __future__ import annotations

import pytest

from collector import post_reader, post_url_extractor as ext
from collector.dedupe import Deduplicator
from collector.models import POST_URL_NOT_FOUND, Post, Stats
from collector.pipeline import decide
from collector.printer import print_match
from config import Config, apply_overrides, build_parser

ACTIVITY = "urn:li:activity:7123456789012345678"
PERMALINK = "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/"


JOB_TEXT = (
    "We are hiring an Artificial Intelligence Engineer.\n\n"
    "Company: Elbetron Technologies\n"
    "Location: Al Khobar (On-site)\n"
    "Experience: 5+ years\n\n"
    "Skills:\n- Python\n- Machine Learning\n\n"
    "Responsibilities:\n- Build AI systems\n- Partner with product teams\n\n"
    "Requirements:\n- Strong ML background\n- Hands-on RAG experience\n\n"
    "Apply: send your resume to hr@elbetron.com"
)


class _Anchor:
    def __init__(self, href, aria_label=None, data_control=None):
        self._href = href
        self._aria_label = aria_label
        self._data_control = data_control
        self.clicks = 0

    def get_attribute(self, name):
        return {
            "href": self._href,
            "aria-label": self._aria_label,
            "data-control-name": self._data_control,
        }.get(name)

    def inner_text(self):
        return ""

    def click(self, **kwargs):
        self.clicks += 1


class _Card:
    """Stands in for one post card.

    ``scan`` is what the in-page scanner reports; a fake without one models a
    card where no deeper scan is possible.
    """

    def __init__(self, anchors=None, attrs=None, scan=None, text=JOB_TEXT):
        self._anchors = anchors or {}
        self._attrs = attrs or {}
        self._scan = scan
        self._text = text

    def query_selector_all(self, selector):
        if selector == ext.PERMALINK_LINK_SELECTOR:
            found = []
            for group in self._anchors.values():
                found.extend(group)
            return found
        return list(self._anchors.get(selector, []))

    def query_selector(self, selector):
        found = self.query_selector_all(selector)
        return found[0] if found else None

    def get_attribute(self, name):
        return self._attrs.get(name)

    def inner_text(self):
        return self._text

    def evaluate(self, script, arg=None):
        if self._scan is None:
            raise RuntimeError("evaluate unsupported")
        return dict(self._scan)


EMPTY_SCAN = {
    "idUrns": [],
    "numericIds": [],
    "attrUrns": [],
    "scriptUrns": [],
    "controlUrns": [],
    "reactTally": {},
}


def _scan(**kwargs):
    scan = dict(EMPTY_SCAN)
    scan.update(kwargs)
    return scan


def _read(card):
    return post_reader.read_post(card, log_post_url=False)


# --- helpers ---------------------------------------------------------------


def test_find_urn_picks_the_first_urn():
    assert ext.find_urn("urn:li:activity:123 and urn:li:share:456") == "urn:li:activity:123"
    assert ext.find_urn("no identifier here") == ""
    assert ext.find_urn("") == ""


def test_permalink_is_canonical():
    assert ext.permalink_for(ACTIVITY) == PERMALINK
    assert ext.permalink_for("") == ""


def test_activity_spelling_is_recognised_case_insensitively():
    assert ext.canonical_urn("URN:LI:ACTIVITY:42") == "urn:li:activity:42"
    assert ext.permalink_for("urn:li:ugcPost:999") == (
        "https://www.linkedin.com/feed/update/urn:li:ugcPost:999/"
    )


def test_href_without_a_post_identifier_is_rejected():
    assert ext.permalink_from_href("https://example.com/careers/ai-engineer") == ""
    assert ext.permalink_from_href("#") == ""
    assert ext.permalink_from_href("javascript:void(0)") == ""


def test_job_links_are_never_taken_as_the_post_url():
    assert ext.permalink_from_href("https://www.linkedin.com/jobs/view/4472520328/") == ""


# --- step 1/2: the post's own anchors --------------------------------------


def test_permalink_anchor_wins():
    card = _Card(
        {ext.PERMALINK_LINK_SELECTOR: [_Anchor(f"{PERMALINK}?utm_source=feed")]},
        scan=_scan(),
    )

    assert ext.extract_post_url(card) == (PERMALINK, ACTIVITY, ext.SOURCE_PERMALINK_LINK)


def test_relative_permalink_anchor_is_absolutised():
    card = _Card({ext.PERMALINK_LINK_SELECTOR: [_Anchor(f"/feed/update/{ACTIVITY}/")]})

    assert ext.extract_post_url(card) == (PERMALINK, ACTIVITY, ext.SOURCE_PERMALINK_LINK)


def test_duplicate_slashes_are_tidied():
    card = _Card(
        {
            ext.PERMALINK_LINK_SELECTOR: [
                _Anchor(f"https://www.linkedin.com//feed//update//{ACTIVITY}/")
            ]
        }
    )

    url, _urn, _source = ext.extract_post_url(card)
    assert url == PERMALINK


# --- step 3: identifier data attributes ------------------------------------


def test_data_attribute_urn_is_used_when_no_link_exists():
    card = _Card(attrs={"data-id": ACTIVITY}, scan=_scan())

    assert ext.extract_post_url(card) == (PERMALINK, ACTIVITY, ext.SOURCE_DATA_ATTRIBUTE)


@pytest.mark.parametrize(
    "attribute", ["data-urn", "data-id", "data-identifier", "data-entity-urn"]
)
def test_every_identifier_attribute_is_read(attribute):
    card = _Card(attrs={attribute: ACTIVITY})

    assert ext.extract_post_url(card)[1] == ACTIVITY


def test_numeric_activity_id_builds_the_urn():
    card = _Card(attrs={"data-activity-id": "7123456789012345678"})

    url, urn, source = ext.extract_post_url(card)
    assert url == PERMALINK
    assert urn == ACTIVITY
    assert source == ext.SOURCE_ACTIVITY_ID


def test_ancestor_identifier_attribute_is_used():
    card = _Card(scan=_scan(idUrns=[ACTIVITY]))

    assert ext.extract_post_url(card) == (PERMALINK, ACTIVITY, ext.SOURCE_DATA_ATTRIBUTE)


# --- steps 4/5: inline identifiers and accessible controls -----------------


def test_inline_identifier_is_used():
    assert ext.extract_post_url(_Card(scan=_scan(attrUrns=[ACTIVITY])))[2] == (
        ext.SOURCE_INLINE_IDENTIFIER
    )


def test_inline_script_identifier_is_used():
    assert ext.extract_post_url(_Card(scan=_scan(scriptUrns=[ACTIVITY])))[2] == (
        ext.SOURCE_INLINE_IDENTIFIER
    )


def test_accessible_control_identifier_is_used():
    assert ext.extract_post_url(_Card(scan=_scan(controlUrns=[ACTIVITY])))[2] == (
        ext.SOURCE_ACCESSIBLE_CONTROL
    )


# --- step 6: the post's component state ------------------------------------


def test_component_state_supplies_the_urn():
    card = _Card(scan=_scan(reactTally={ACTIVITY: 10}))

    assert ext.extract_post_url(card) == (PERMALINK, ACTIVITY, ext.SOURCE_COMPONENT_STATE)


def test_component_state_accepts_the_ugcpost_spelling():
    ugc = "urn:li:ugcPost:7512192958159347713"

    url, urn, source = ext.extract_post_url(_Card(scan=_scan(reactTally={ugc: 10})))

    assert url == f"https://www.linkedin.com/feed/update/{ugc}/"
    assert (urn, source) == (ugc, ext.SOURCE_COMPONENT_STATE)


def test_dominant_component_state_wins():
    other = "urn:li:activity:7000000000000000001"

    assert ext.extract_post_url(_Card(scan=_scan(reactTally={ACTIVITY: 10, other: 2})))[1] == ACTIVITY


def test_tied_component_state_is_refused_rather_than_guessed():
    other = "urn:li:activity:7000000000000000001"
    card = _Card(scan=_scan(reactTally={ACTIVITY: 4, other: 4}))

    assert ext.extract_post_url(card) == ("", "", ext.SOURCE_NOT_FOUND)


def test_same_id_in_two_spellings_is_not_ambiguous():
    ugc = "urn:li:ugcPost:7123456789012345678"

    assert ext.extract_post_url(_Card(scan=_scan(reactTally={ACTIVITY: 6, ugc: 6})))[1] == ACTIVITY


# --- last resort and "not found" -------------------------------------------


def test_slug_link_is_used_only_when_nothing_else_exists():
    card = _Card(
        {
            ext.PERMALINK_LINK_SELECTOR: [
                _Anchor("https://www.linkedin.com/posts/author_hiring-activity-1-abc")
            ]
        },
        scan=_scan(),
    )

    url, urn, source = ext.extract_post_url(card)
    assert url == "https://www.linkedin.com/posts/author_hiring-activity-1-abc"
    assert (urn, source) == ("", ext.SOURCE_SLUG_LINK)


def test_urn_beats_an_opaque_slug_link():
    card = _Card(
        {
            ext.PERMALINK_LINK_SELECTOR: [
                _Anchor("https://www.linkedin.com/posts/author_hiring-activity-1-abc")
            ]
        },
        attrs={"data-id": ACTIVITY},
    )

    assert ext.extract_post_url(card) == (PERMALINK, ACTIVITY, ext.SOURCE_DATA_ATTRIBUTE)


def test_unidentified_post_reports_not_found():
    assert ext.extract_post_url(_Card(scan=_scan())) == ("", "", ext.SOURCE_NOT_FOUND)


def test_no_url_is_invented_without_an_identifier():
    card = _Card(scan=_scan(reactTally={"urn:li:activity:": 3}))

    assert ext.extract_post_url(card) == ("", "", ext.SOURCE_NOT_FOUND)


def test_broken_scan_is_survivable():
    class _Broken(_Card):
        def evaluate(self, script, arg=None):
            raise RuntimeError("detached")

    assert ext.extract_post_url(_Broken(attrs={"data-id": ACTIVITY}))[1] == ACTIVITY
    assert ext.extract_post_url(_Broken()) == ("", "", ext.SOURCE_NOT_FOUND)


# --- the three URL fields stay separate ------------------------------------


def test_post_job_and_apply_urls_are_three_different_values():
    card = _Card(
        {
            post_reader.JOB_LINK_SELECTORS[0]: [
                _Anchor("https://www.linkedin.com/jobs/view/4472520328/")
            ]
        },
        attrs={"data-id": ACTIVITY},
    )

    post = _read(card)

    assert post.url == PERMALINK
    assert post.job_url == "https://www.linkedin.com/jobs/view/4472520328/"
    assert post.apply_urls == []
    assert len({post.url, post.job_url}) == 2


def test_job_link_is_not_reported_as_the_post_url():
    card = _Card(
        {
            ext.PERMALINK_LINK_SELECTOR: [
                _Anchor("https://www.linkedin.com/jobs/view/4472520328/")
            ],
            post_reader.JOB_LINK_SELECTORS[0]: [
                _Anchor("https://www.linkedin.com/jobs/view/4472520328/")
            ],
        },
        scan=_scan(),
    )

    post = _read(card)

    assert post.url == ""
    assert post.job_url == "https://www.linkedin.com/jobs/view/4472520328/"


def test_printer_reports_not_found_instead_of_guessing(capsys):
    post = _read(_Card(scan=_scan()))
    cfg = Config(target_roles=["AI Developer"])
    match = decide(post, cfg)
    assert match is not None

    print_match(1, match, cfg)
    out = capsys.readouterr().out

    assert f"LINKEDIN POST: {POST_URL_NOT_FOUND}" in out
    line = [ln for ln in out.splitlines() if "LINKEDIN POST" in ln][0]
    assert "/feed/update/" not in line


def test_printer_shows_the_permalink_when_found(capsys):
    post = _read(_Card(attrs={"data-id": ACTIVITY}))
    cfg = Config(target_roles=["AI Developer"])

    print_match(1, decide(post, cfg), cfg)
    out = capsys.readouterr().out

    assert f"LINKEDIN POST: {PERMALINK}" in out


def test_read_post_logs_the_extraction_attempt(capsys):
    post_reader.read_post(_Card(attrs={"data-id": ACTIVITY}))
    out = capsys.readouterr().out

    assert "[INFO] Extracting LinkedIn post URL..." in out
    assert "[INFO] Trying DOM-based post URL extraction..." in out
    assert f"[OK] LinkedIn post URL found: {PERMALINK}" in out


# --- the "..." menu fallback ------------------------------------------------


class _MenuItem:
    def __init__(self, text):
        self._text = text
        self.clicks = 0

    def get_attribute(self, name):
        return None

    def inner_text(self):
        return self._text

    def click(self, **kwargs):
        self.clicks += 1


class _Keyboard:
    def __init__(self):
        self.pressed = []

    def press(self, key):
        self.pressed.append(key)


class _Request:
    """Stands in for the browser context's HTTP client."""

    def __init__(self, redirects=None, fail=False):
        self._redirects = redirects or {}
        self._fail = fail
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        if self._fail:
            raise RuntimeError("network down")
        final = self._redirects.get(url, url)
        return type("Response", (), {"url": final})()


class _MenuPage:
    def __init__(self, item, clipboard="", request=None):
        self._item = item
        self._clipboard = clipboard
        self.keyboard = _Keyboard()
        self.context = type("Context", (), {"request": request})()

    def wait_for_timeout(self, ms):
        return None

    def query_selector(self, selector):
        if selector in ("div[role='menuitem']", "button[role='menuitem']", "[role='menu'] span"):
            return self._item
        return None

    def query_selector_all(self, selector):
        return [self._item] if self._item is not None else []

    def evaluate(self, expression):
        return self._clipboard if "clipboard" in expression else ""


class _MenuButton(_MenuItem):
    def get_attribute(self, name):
        return {"aria-label": "More options", "data-control-name": "more"}.get(name)


class _MenuCard:
    def __init__(self, button):
        self._button = button

    def query_selector(self, selector):
        return self._button if selector in ext.MENU_MORE_SELECTORS else None

    def query_selector_all(self, selector):
        return []


def test_menu_fallback_reads_the_copied_permalink():
    button = _MenuButton("More")
    item = _MenuItem("Copy link to post")
    page = _MenuPage(item, clipboard=PERMALINK)

    assert ext.copy_link_via_menu(page, _MenuCard(button)) == PERMALINK
    assert button.clicks == 1
    assert item.clicks == 1
    assert page.keyboard.pressed  # the menu is always dismissed again


def test_menu_fallback_resolves_a_short_link_to_the_permalink():
    short = "https://lnkd.in/p/gMJcQMQh"
    resolved = (
        "https://www.linkedin.com/posts/shaikh-ashfaque_hiring-7511996926322618369-4hbN/"
        "?highlightedUpdateUrn=urn%3Ali%3Aactivity%3A7511996927295619072&utm_source=share"
    )
    request = _Request({short: resolved})
    page = _MenuPage(_MenuItem("Copy link to post"), clipboard=short, request=request)

    assert (
        ext.copy_link_via_menu(page, _MenuCard(_MenuButton("More")))
        == "https://www.linkedin.com/feed/update/urn:li:activity:7511996927295619072/"
    )
    assert request.requested == [short]


def test_menu_fallback_keeps_a_posts_slug_when_no_urn_is_offered():
    short = "https://lnkd.in/p/abc123"
    resolved = (
        "https://www.linkedin.com/posts/dhanraj_hiring-ai-engineers-7512089061466206208-FBbP/"
        "?highlightedUpdateType=SOCIAL_SHARE"
    )
    request = _Request({short: resolved})
    page = _MenuPage(_MenuItem("Copy link to post"), clipboard=short, request=request)

    assert (
        ext.copy_link_via_menu(page, _MenuCard(_MenuButton("More")))
        == "https://www.linkedin.com/posts/dhanraj_hiring-ai-engineers-7512089061466206208-FBbP/"
    )


def test_short_link_that_cannot_be_resolved_is_rejected():
    request = _Request({"https://lnkd.in/p/x": "https://www.linkedin.com/feed/"}, fail=True)

    assert ext.resolve_post_link("https://lnkd.in/p/x", request) == ""


def test_resolve_never_invents_a_url_from_a_job_link():
    assert ext.resolve_post_link("https://www.linkedin.com/jobs/view/4472520328/", _Request()) == ""


def test_menu_fallback_rejects_a_clipboard_value_that_is_not_a_post():
    page = _MenuPage(_MenuItem("Copy link to post"), clipboard="https://example.com/careers")

    assert ext.copy_link_via_menu(page, _MenuCard(_MenuButton("More"))) == ""


def test_menu_fallback_without_a_menu_button_does_nothing():
    page = _MenuPage(_MenuItem("Copy link to post"), clipboard=PERMALINK)

    assert ext.copy_link_via_menu(page, _MenuCard(None)) == ""


def test_menu_fallback_without_an_element_does_nothing():
    assert ext.copy_link_via_menu(_MenuPage(_MenuItem("Copy link to post")), None) == ""


def test_menu_fallback_survives_a_missing_copy_item():
    page = _MenuPage(_MenuItem("Report post"), clipboard=PERMALINK)

    assert ext.copy_link_via_menu(page, _MenuCard(_MenuButton("More"))) == ""


def test_menu_fallback_retries_when_the_menu_has_not_rendered_yet(monkeypatch):
    """A slow menu must not cost the post its mandatory URL."""
    item = _MenuItem("Copy link to post")
    button = _MenuButton("More")

    class SlowMenuPage(_MenuPage):
        def __init__(self):
            super().__init__(item, clipboard=PERMALINK)
            self.polls = 0

        def query_selector_all(self, selector):
            self.polls += 1
            # The menu renders late: the first look finds nothing.
            return [] if self.polls < 3 else [item]

    page = SlowMenuPage()

    assert ext.copy_link_via_menu(page, _MenuCard(button), attempts=2) == PERMALINK
    assert item.clicks == 1


def test_menu_fallback_gives_up_after_its_attempts():
    page = _MenuPage(_MenuItem("Report post"), clipboard=PERMALINK)

    assert ext.copy_link_via_menu(page, _MenuCard(_MenuButton("More")), attempts=2) == ""


def test_menu_fallback_is_on_by_default_because_the_post_url_is_mandatory():
    assert Config().post_url_menu_fallback is True


def test_menu_fallback_can_be_turned_off_from_yaml_and_cli():
    assert not apply_overrides(Config(), {"post_url_menu_fallback": False}).post_url_menu_fallback
    assert not build_parser().parse_args(["--no-post-url-menu-fallback"]).post_url_menu_fallback
    assert build_parser().parse_args(["--post-url-menu-fallback"]).post_url_menu_fallback


# --- the post URL is mandatory ---------------------------------------------

# --- validation: only a real post permalink is accepted --------------------


def test_validate_accepts_the_canonical_permalink():
    assert ext.validate_post_url(PERMALINK) == PERMALINK


def test_validate_accepts_a_resolved_posts_slug():
    assert (
        ext.validate_post_url("https://www.linkedin.com/posts/dhanraj_hiring-ai-engineers-FBbP/")
        == "https://www.linkedin.com/posts/dhanraj_hiring-ai-engineers-FBbP/"
    )


def test_validate_rejects_the_wrong_url_kinds():
    wrong = [
        "https://www.linkedin.com/jobs/view/4472520328/",
        "https://www.linkedin.com/in/shaikh-ashfaque-469220144/",
        "https://www.linkedin.com/search/results/content/?keywords=AI%20Engineer",
        "https://www.linkedin.com/company/lexsi-labs/",
        "https://www.linkedin.com/feed/",
        "https://www.linkedin.com/",
        "https://www.linkedin.com/mynetwork/",
        "https://example.com/feed/update/urn:li:activity:7123456789012345678/",
        "",
    ]
    for url in wrong:
        assert ext.validate_post_url(url) == "", url


# --- the fallback runs only for a qualifying post ---------------------------


class _Cfg:
    max_jds = 5
    max_posts = 100

    def __init__(self, fallback):
        self.post_url_menu_fallback = fallback


class _Decider:
    def __init__(self, url, text=JOB_TEXT):
        self.deduper = Deduplicator()
        self.match = decide(
            Post(
                author="Elbetron Technologies",
                text=text,
                url=url,
                element="card-handle",
            ),
            Config(target_roles=["AI Developer"]),
        )
        assert self.match is not None

    def decide(self, post):
        return self.match


def _run_batches(monkeypatch, cfg, decider):
    import main as mainpy

    stats = Stats()
    monkeypatch.setattr(
        mainpy.scroller, "iter_post_batches", lambda page, config, st: [[decider.match.post]]
    )
    monkeypatch.setattr(mainpy.printer, "print_match", lambda *a, **k: None)
    monkeypatch.setattr(mainpy, "_allow_clipboard_read", lambda page: None)
    mainpy.process_batches(None, cfg, decider, stats, "AI Engineer")
    return stats


def test_jd_without_a_post_url_is_skipped_when_the_fallback_is_disabled(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("main.copy_link_via_menu", lambda *a, **k: calls.append(a))

    decider = _Decider(url="")
    stats = _run_batches(monkeypatch, _Cfg(fallback=False), decider)
    out = capsys.readouterr().out

    assert calls == []
    assert decider.match.post.url == ""
    assert stats.collected == 0
    assert "Could not obtain LinkedIn post URL for this post." in out
    assert "Skipping this JD because LinkedIn post URL is mandatory." in out


def test_jd_is_skipped_when_the_menu_cannot_produce_a_url(monkeypatch, capsys):
    monkeypatch.setattr("main.copy_link_via_menu", lambda *a, **k: "")

    decider = _Decider(url="")
    stats = _run_batches(monkeypatch, _Cfg(fallback=True), decider)
    out = capsys.readouterr().out

    assert decider.match.post.url == ""
    assert stats.collected == 0
    assert "Could not obtain LinkedIn post URL for this post." in out
    assert "Skipping this JD because LinkedIn post URL is mandatory." in out


def test_fallback_runs_for_a_qualifying_post_when_enabled(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        "main.copy_link_via_menu",
        lambda page, element, *a, **k: (calls.append(element), PERMALINK)[1],
    )

    decider = _Decider(url="")
    stats = _run_batches(monkeypatch, _Cfg(fallback=True), decider)
    out = capsys.readouterr().out

    assert calls == ["card-handle"]
    assert decider.match.post.url == PERMALINK
    assert decider.match.post.urn == ACTIVITY
    assert stats.collected == 1
    assert "Using post menu fallback..." in out
    assert f"LinkedIn post URL found from post menu: {PERMALINK}" in out


def test_fallback_is_skipped_when_the_url_is_already_known(monkeypatch):
    calls = []
    monkeypatch.setattr("main.copy_link_via_menu", lambda *a, **k: calls.append(a))

    decider = _Decider(url=PERMALINK)
    stats = _run_batches(monkeypatch, _Cfg(fallback=True), decider)

    assert calls == []
    assert decider.match.post.url == PERMALINK
    assert stats.collected == 1


def test_a_non_post_url_from_the_menu_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(
        "main.copy_link_via_menu",
        lambda *a, **k: "https://www.linkedin.com/in/someone-else/",
    )

    decider = _Decider(url="")
    stats = _run_batches(monkeypatch, _Cfg(fallback=True), decider)
    out = capsys.readouterr().out

    assert decider.match.post.url == ""
    assert stats.collected == 0
    assert "is not a post permalink" in out
    assert "Skipping this JD because LinkedIn post URL is mandatory." in out


def test_another_posts_url_from_the_menu_is_refused(monkeypatch, capsys):
    monkeypatch.setattr("main.copy_link_via_menu", lambda *a, **k: PERMALINK)

    decider = _Decider(url="")
    # Another post already claimed that permalink.
    decider.deduper.remember(Post(text="A completely different post", url=PERMALINK))
    stats = _run_batches(monkeypatch, _Cfg(fallback=True), decider)
    out = capsys.readouterr().out

    assert decider.match.post.url == ""
    assert stats.collected == 0
    assert "already claimed by another post" in out
    assert "Skipping this JD because LinkedIn post URL is mandatory." in out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))