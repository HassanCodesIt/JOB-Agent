"""Image-based path regression tests."""
from collector.models import Post, Stats
from collector.pipeline import Decider
from collector.dedupe import Deduplicator
from config import Config
from collector import models


def make_post(**kwargs) -> Post:
    return Post(**kwargs)


def test_image_only_is_collected():
    text = "We're Hiring! AI/ML Engineer – Databricks & GenAI\nSkills: Python, PySpark\nLocation: Remote India"
    post = make_post(text=text, has_image=True, url="https://www.linkedin.com/feed/update/urn:li:activity:1000/")
    d = Decider(Config(), deduper=Deduplicator())
    m = d.decide(post)
    assert m is not None
    assert models.METHOD_IMAGE_JOB_POST in m.methods
    assert m.application_method.startswith("Image-Based")
    assert post.has_image is True


def test_image_without_job_signals_rejected():
    text = "Check out this cool photo!"
    post = make_post(text=text, has_image=True, url="https://www.linkedin.com/feed/update/urn:li:activity:1001/")
    d = Decider(Config(), deduper=Deduplicator())
    assert d.decide(post) is None


def test_no_image_and_no_methods_remains_rejected():
    text = "We're Hiring! AI/ML Engineer – Databricks & GenAI\nSkills: Python, PySpark\nLocation: Remote India"
    post = make_post(text=text, has_image=False, url="https://www.linkedin.com/feed/update/urn:li:activity:1002/")
    d = Decider(Config(), deduper=Deduplicator())
    assert d.decide(post) is None


def test_image_plus_email_still_has_all_methods():
    text = "We're Hiring! AI/ML Engineer – Databricks & GenAI\nSkills: Python, PySpark\nEmail: hr@acme-corp.com\nLocation: Remote India\nExperience: 3-5 years"
    post = make_post(text=text, has_image=True, url="https://www.linkedin.com/feed/update/urn:li:activity:1003/")
    d = Decider(Config(), deduper=Deduplicator())
    m = d.decide(post)
    assert m is not None
    assert models.METHOD_EMAIL in m.methods
    assert models.METHOD_IMAGE_JOB_POST in m.methods


def test_image_plus_job_url():
    text = "We're Hiring! AI/ML Engineer – Databricks & GenAI\nSkills: Python, PySpark\nLocation: Remote India"
    post = make_post(text=text, has_image=True, job_url="https://www.linkedin.com/jobs/view/123456/", url="https://www.linkedin.com/feed/update/urn:li:activity:1004/")
    d = Decider(Config(), deduper=Deduplicator())
    m = d.decide(post)
    assert m is not None
    assert models.METHOD_LINKEDIN_JOB in m.methods


def test_image_post_without_url_rejected():
    text = "We're Hiring! AI/ML Engineer – Databricks & GenAI\nSkills: Python, PySpark"
    post = make_post(text=text, has_image=True, url="")
    d = Decider(Config(), deduper=Deduplicator())
    assert d.decide(post) is None


def test_image_fields_serialized():
    from collector import run_storage
    text = "We're Hiring! AI/ML Engineer\nSkills: Python\nLocation: Remote"
    post = make_post(text=text, has_image=True, image_url="https://media.example/image.jpg", url="https://www.linkedin.com/feed/update/urn:li:activity:1005/")
    d = Decider(Config(), deduper=Deduplicator())
    m = d.decide(post)
    assert m is not None
    payload = run_storage.build_run_payload([m], d.stats, Config(), 1)
    job = payload["jobs"][0]
    assert job["has_image"] is True
    assert job["image_based_job_post"] is True
    assert job["image_url"] == "https://media.example/image.jpg"


# --- image detection (no browser) -------------------------------------------

from collector.post_reader import (  # noqa: E402
    _extract_image_info,
    _looks_like_attached_media,
)


def test_avatar_and_logo_images_are_not_attached_media():
    assert _looks_like_attached_media(
        "https://media.licdn.com/dms/image/profile-displayphoto/x.jpg", "", "", False
    ) is False
    assert _looks_like_attached_media(
        "https://media.licdn.com/dms/image/x.jpg", "Ravi Kumar", "/in/ravi-kumar/", False
    ) is False
    assert _looks_like_attached_media(
        "https://media.licdn.com/dms/image/x.jpg", "Acme logo", "/company/acme/", False
    ) is False


def test_attached_image_is_detected():
    assert _looks_like_attached_media(
        "https://media.licdn.com/dms/image/feedshare-shrink-720/hiring.jpg", "", "", False
    ) is True
    assert _looks_like_attached_media("https://example.com/poster.png", "", "", False) is True


def test_media_container_always_counts():
    assert _looks_like_attached_media("", "", "", True) is True


class _FakeImg:
    def __init__(self, src="", alt="", href=""):
        self._attrs = {"src": src, "alt": alt}
        self._href = href

    def get_attribute(self, name):
        return self._attrs.get(name)

    def evaluate(self, script):
        return self._href


class _FakeContainer:
    def __init__(self, img=None):
        self._img = img

    def query_selector(self, selector):
        return self._img


class _FakeElement:
    def __init__(self, imgs=(), containers=()):
        self._imgs = list(imgs)
        self._containers = set(containers)

    def query_selector_all(self, selector):
        return list(self._imgs) if selector == "img" else []

    def query_selector(self, selector):
        if selector in self._containers:
            return _FakeContainer(self._imgs[0] if self._imgs else None)
        return None


def test_extract_image_info_ignores_author_avatar_only():
    element = _FakeElement(imgs=[_FakeImg("https://media.licdn.com/profile-displayphoto/a.jpg", "Rio", "/in/rio/")])
    assert _extract_image_info(element) == (False, "")


def test_extract_image_info_finds_attached_image_src():
    element = _FakeElement(imgs=[
        _FakeImg("https://media.licdn.com/profile-displayphoto/a.jpg", "Rio", "/in/rio/"),
        _FakeImg("https://media.licdn.com/dms/image/feedshare-shrink-720/poster.jpg", "", ""),
    ])
    has_image, url = _extract_image_info(element)
    assert has_image is True
    assert url.endswith("poster.jpg")


def test_extract_image_info_structural_container():
    element = _FakeElement(
        imgs=[_FakeImg("https://media.licdn.com/dms/image/feedshare/x.jpg", "", "")],
        containers=["figure"],
    )
    has_image, url = _extract_image_info(element)
    assert has_image is True
    assert url.endswith("x.jpg")


# --- roundups ----------------------------------------------------------------


def test_roundup_with_image_is_not_collected():
    from collector.job_detector import looks_like_job_roundup

    text = (
        "Hiring now! Top 5 AI jobs this week:\n"
        "1. Google AI Engineer\n2. Microsoft ML Engineer\n"
        "3. Amazon LLM Engineer\n4. Meta GenAI Engineer"
    )
    assert looks_like_job_roundup(text) is True
    post = make_post(text=text, has_image=True, url="https://www.linkedin.com/feed/update/urn:li:activity:2000/")
    d = Decider(Config(), deduper=Deduplicator())
    assert d.decide(post) is None


def test_single_job_is_not_a_roundup():
    from collector.job_detector import looks_like_job_roundup

    text = "We're hiring a Generative AI Engineer. Skills: Python, LLM, RAG"
    assert looks_like_job_roundup(text) is False


# --- deduplication -----------------------------------------------------------


def test_image_post_is_deduplicated_by_url():
    text = "We're Hiring! AI/ML Engineer\nSkills: Python\nLocation: Remote India"
    deduper = Deduplicator()
    d = Decider(Config(), deduper=deduper)
    url = "https://www.linkedin.com/feed/update/urn:li:activity:3000/"

    first = d.decide(make_post(text=text, has_image=True, url=url))
    second = d.decide(make_post(text=text, has_image=True, url=url))

    assert first is not None
    assert second is None
    assert deduper.duplicates_removed == 1


# --- storage integration -----------------------------------------------------


def test_image_post_stored_in_run_json_and_caption_preserved():
    from collector import run_storage

    caption = "We're Hiring! AI/ML Engineer – Databricks & GenAI\nSkills: Python, PySpark\nLocation: Remote India"
    post = make_post(text=caption, has_image=True, image_url="https://media.licdn.com/dms/image/poster.jpg", url="https://www.linkedin.com/feed/update/urn:li:activity:4000/")
    d = Decider(Config(), deduper=Deduplicator())
    match = d.decide(post)
    assert match is not None

    payload = run_storage.build_run_payload([match], d.stats, Config(), 1)
    job = payload["jobs"][0]

    assert job["application_method"] == "Image-Based Job Post"
    assert job["application_methods"] == ["Image-Based Job Post"]
    assert job["linkedin_post_url"] == post.url
    assert job["full_post"] == caption
    assert job["email"] is None
    assert job["job_url"] is None
    assert job["apply_url"] is None
    assert job["has_image"] is True
    assert job["image_based_job_post"] is True
    assert job["image_url"] == "https://media.licdn.com/dms/image/poster.jpg"
    assert any("Image-based job post detected" in r for r in job["match_reasons"])
    assert any("contained in attached image" in r for r in job["match_reasons"])

    stats = d.stats
    assert stats.posts_with_image == 1
    assert stats.collected_by_image == 1


def test_summary_counters_reflect_image_posts():
    from collector import run_storage

    text = "We're Hiring! AI/ML Engineer\nSkills: Python\nLocation: Remote India"
    stats = Stats()
    decider = Decider(Config(), stats=stats, deduper=Deduplicator())
    match = decider.decide(make_post(text=text, has_image=True, url="https://www.linkedin.com/feed/update/urn:li:activity:5000/"))
    payload = run_storage.build_run_payload([match], stats, Config(), 1)

    assert payload["summary"]["posts_with_image_job_info"] == 1
    assert payload["summary"]["collected_by_image_job_post"] == 1


def test_non_image_behavior_unchanged():
    text = "We're Hiring! AI/ML Engineer\nSkills: Python\nLocation: Remote India"
    post = make_post(text=text, has_image=False, url="https://www.linkedin.com/feed/update/urn:li:activity:6000/")
    d = Decider(Config(), deduper=Deduplicator())
    assert d.decide(post) is None
    assert d.stats.no_application_method == 1
