from __future__ import annotations

from collector import post_reader
from collector.field_extractor import extract_experience, extract_location
from collector.models import Post, RoleMatchResult
from collector.post_reader import _clean_text, _decode_entities


class _Node:
    def __init__(self, text="", attrs=None):
        self._text = text
        self._attrs = attrs or {}

    def query_selector(self, selector):
        return self._nodes.get(selector) if hasattr(self, "_nodes") else None

    def query_selector_all(self, selector):
        return []

    def get_attribute(self, name):
        return self._attrs.get(name)

    def inner_text(self):
        return self._text


class _Card(_Node):
    """A post card whose selectable pieces are supplied up front."""

    def __init__(self, pieces, card_text="", attrs=None):
        super().__init__(card_text, attrs)
        self._nodes = pieces

    def query_selector(self, selector):
        node = self._nodes.get(selector)
        if isinstance(node, str):
            return _Node(node)
        return node

    def query_selector_all(self, selector):
        node = self.query_selector(selector)
        return [node] if node is not None else []


# --- author ---------------------------------------------------------------


def test_author_never_falls_back_to_whole_card_text():
    card = _Card({}, card_text="Feed post\nAllPro\nMubin Banu - 3rd+\n2h\nJoin")

    post = post_reader.read_post(card)

    assert post is not None
    assert post.author == ""


def test_author_is_read_from_a_profile_link():
    card = _Card({"a[href*='/in/'] p span": "Mubin Banu"}, card_text="ignored")

    post = post_reader.read_post(card)

    assert post.author == "Mubin Banu"


# --- UI chrome ------------------------------------------------------------


def test_linkedin_composer_chrome_is_removed():
    raw = (
        "Hiring AI Engineer in Pune\n"
        "Build with LangChain\n"
        "Add responsibilities and qualifications\n"
        "Clarify the application instructions\n"
        "Add a comment...\n"
        "\u2026 more"
    )

    cleaned = _clean_text(raw)

    assert cleaned == "Hiring AI Engineer in Pune\nBuild with LangChain"


def test_single_ui_button_lines_are_removed_but_content_is_kept():
    raw = "Role: AI Engineer\nJoin\nFollow\nLocation: Pune"

    cleaned = _clean_text(raw)

    assert "Join" not in cleaned
    assert "Follow" not in cleaned
    assert "Role: AI Engineer" in cleaned
    assert "Location: Pune" in cleaned


def test_real_sentences_starting_with_join_are_kept():
    assert "Join our team" in _clean_text("Join our team in Hyderabad")


# --- entities -------------------------------------------------------------


def test_double_escaped_entities_are_decoded():
    assert _decode_entities("LangChain &amp; LangGraph") == "LangChain & LangGraph"
    assert _decode_entities("R&amp;D") == "R&D"
    assert _decode_entities("a&nbsp;b") == "a b"
    assert _decode_entities("&#65;&#66;") == "AB"


def test_clean_text_decodes_entities():
    assert "&" in _clean_text("LangChain &amp; LangGraph")
    assert "amp;" not in _clean_text("LangChain &amp; LangGraph")


# --- experience -----------------------------------------------------------


def test_experience_label_is_not_duplicated():
    assert extract_experience("Experience: 3+ Years (Only Immediate)") == "3+ Years"
    assert extract_experience("Experience: 3-5 years") == "3-5 years"
    assert extract_experience("experience of 8 years") == "8 years"


# --- location -------------------------------------------------------------


def test_single_character_location_is_rejected():
    assert extract_location("Location: S\nApply: hr@acme.com") == "Not specified"


def test_valid_locations_still_extract():
    assert extract_location("Location: Hyderabad") == "Hyderabad"
    assert extract_location("Location: Remote") == "Remote"


# --- regression: post still builds ---------------------------------------


def test_post_url_and_job_url_remain_independent():
    card = _Card(
        {
            "a[href*='/posts/']": _Node(
                "", {"href": "https://www.linkedin.com/posts/a_hiring-activity-7123456789012345678-abc"}
            ),
            post_reader.JOB_LINK_SELECTORS[0]: _Node(
                "", {"href": "https://www.linkedin.com/jobs/view/4473153699/?trackingId=x"}
            ),
        },
        attrs={"data-id": "urn:li:activity:7123456789012345678"},
        card_text="Hiring an AI Engineer. Send CV to hr@acme.com",
    )

    post = post_reader.read_post(card)

    assert post.url == "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/"
    assert post.job_url == "https://www.linkedin.com/jobs/view/4473153699/"


def test_read_post_still_works_with_no_author_selector():
    card = _Card({}, card_text="Hiring an AI Engineer. Send CV to hr@acme.com")

    post = post_reader.read_post(card)

    assert post is not None
    assert post.text.startswith("Hiring an AI Engineer")
    assert RoleMatchResult is not None
    assert isinstance(post, Post)