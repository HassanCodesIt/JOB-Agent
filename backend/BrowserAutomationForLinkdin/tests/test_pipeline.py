from __future__ import annotations

from pathlib import Path

from collector.apply_link_extractor import collect_apply_urls
from collector.dedupe import Deduplicator
from collector.models import Post, Stats
from collector.pipeline import Decider, decide
from config import Config

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture_posts() -> list:
    posts = []
    for file in sorted(FIXTURES.glob("*.txt")):
        text = file.read_text(encoding="utf-8").strip()
        header, _, body = text.partition("\n")
        body = body.strip()
        posts.append(
            Post(
                author=header.strip(),
                text=body,
                url=file.as_uri(),
                apply_urls=collect_apply_urls(body),
            )
        )
    return posts


def test_decide_accepts_a_full_job_post():
    cfg = Config()
    post = _fixture_posts()[0]
    match = decide(post, cfg)
    assert match is not None
    assert match.target_role in cfg.target_roles
    assert match.emails == ["hr@northwindlabs.com"]
    assert match.company == "Northwind Labs"
    assert "Bengaluru" in match.location
    assert match.job_description
    assert match.reasons


def test_decide_rejects_celebration_post():
    assert decide(_fixture_posts()[1], Config()) is None


def test_decide_rejects_post_without_enough_jd_signals():
    """Fixture 03 has an apply link but only one JD section, so it is rejected
    for a thin job description rather than for a missing e-mail."""
    match = decide(_fixture_posts()[2], Config())
    assert match is None


def test_decide_collects_post_with_apply_link_and_no_email():
    """PATH 3: an application link replaces the e-mail requirement."""
    match = decide(_fixture_posts()[6], Config())
    assert match is not None
    assert match.emails == []
    assert match.apply_url == "https://vertexlabs.example/careers/generative-ai-engineer"
    assert match.job_url == ""
    assert match.application_method == "External Apply Link"


def test_decide_handles_obfuscated_email():
    match = decide(_fixture_posts()[3], Config())
    assert match is not None
    assert "hiring@talentbridge.co.in" in match.emails


def test_pipeline_over_fixtures():
    cfg = Config()
    stats = Stats()
    deduper = Deduplicator()
    decider = Decider(cfg, stats, deduper)

    collected = []
    for post in _fixture_posts():
        stats.posts_processed += 1
        match = decider.decide(post)
        if match is not None:
            stats.collected += 1
            collected.append(match)

    assert stats.posts_processed == 7
    assert stats.collected == 3
    assert stats.duplicates_removed == 1
    assert stats.potential_job_posts >= stats.collected
    assert stats.posts_with_email >= 2
    assert stats.posts_with_apply_url == 1
    assert stats.collected_by_email == 2
    assert stats.collected_by_apply_url == 1
    assert stats.valid_job_matches == stats.collected
    assert {emails[0] for match in collected if match.emails for emails in [match.emails]} == {
        "hr@northwindlabs.com",
        "arjun@talentbridge.in",
    }
    assert "hiring@talentbridge.co.in" in collected[1].emails
    assert any(m.apply_url == "https://vertexlabs.example/careers/generative-ai-engineer" for m in collected)


def test_stats_counters_increment_in_order():
    cfg = Config()
    stats = Stats()
    decider = Decider(cfg, stats, Deduplicator())
    posts = _fixture_posts()

    decider.decide(Post(text="We are hiring a marketing manager in Bengaluru. Apply now."))
    assert stats.role_rejected == 1
    assert stats.not_job_posts == 0

    decider.decide(posts[5])
    assert stats.role_rejected == 1
    assert stats.not_job_posts == 1
    assert stats.potential_job_posts == 0

    decider.decide(posts[1])
    assert stats.potential_job_posts == 0
    assert stats.not_job_posts == 2

    decider.decide(posts[2])
    assert stats.potential_job_posts == 1
    assert stats.jd_rejected == 1

    assert decider.decide(posts[0]) is not None
    assert stats.potential_job_posts == 2
    assert stats.posts_with_email == 1


def test_empty_post_is_skipped():
    assert decide(Post(text=""), Config()) is None


def test_min_jd_signals_threshold_is_enforced():
    cfg = Config(min_jd_signals=99)
    assert decide(_fixture_posts()[0], cfg) is None


def test_dry_run_mode_prints_and_returns(capsys):
    import main

    cfg = Config(dry_run=str(FIXTURES), color=False)
    stats = main.run(cfg)
    output = capsys.readouterr().out
    assert stats.collected == 3
    assert "COLLECTION COMPLETE" in output
    assert "MATCH #01" in output
    assert "Final JDs Collected: 3" in output
    assert stats.roles_searched == 0


def test_email_fallback_reuses_pre_extracted_emails():
    from collector.pipeline import Decider

    text = (
        "We are hiring an AI Engineer.\n"
        "Skills:\n- Python\n- LLM orchestration\n"
        "Responsibilities:\n- Build agents\n"
        "Contact: jobs@acme-ai.com"
    )
    match = Decider(Config(), Stats(), Deduplicator()).decide(Post(author="Ravi", text=text, url=""))
    assert match is not None
    assert any("jobs@acme-ai.com" in item for item in match.application_instructions)


def test_roles_flag_overrides_the_default_role_list():
    from config import load_config

    cfg = load_config(["--roles", "AI Developer,LLM Engineer"])
    assert cfg.target_roles == ["AI Developer", "LLM Engineer"]


def test_roles_flag_is_ignored_when_absent():
    from config import DEFAULT_ROLES, load_config

    cfg = load_config(["--dry-run"])
    assert cfg.target_roles == list(DEFAULT_ROLES)


class _FakePage:
    def __init__(self):
        self.waited = 0

    def wait_for_timeout(self, ms):
        self.waited += ms


def test_process_batches_reports_when_a_role_has_no_posts(monkeypatch, capsys):
    import main

    monkeypatch.setattr(main.scroller, "iter_post_batches", lambda page, cfg, stats: iter(()))

    stats = Stats()
    decider = Decider(Config(), stats, Deduplicator())
    assert main.process_batches(_FakePage(), Config(), decider, stats, "LLM Engineer") == 0

    output = capsys.readouterr().out
    assert "No posts found for LLM Engineer" in output
    assert stats.posts_processed == 0


def test_search_with_posts_filter_retries_once_before_skipping(monkeypatch):
    import main
    from collector.safety import NavigatorError

    calls = {"search": 0, "filter": 0}

    def fake_search(page, role, cfg):
        calls["search"] += 1
        if calls["search"] == 1:
            raise NavigatorError("Posts filter could not be found.")

    def fake_filter(page, role="", cfg=None):
        calls["filter"] += 1

    monkeypatch.setattr(main.navigator, "search_role", fake_search)
    monkeypatch.setattr(main.navigator, "select_posts_filter", fake_filter)

    page = _FakePage()
    assert main.search_with_posts_filter(page, "AI Developer", Config()) is True
    assert calls == {"search": 2, "filter": 1}
    assert page.waited == 2000


def test_search_with_posts_filter_skips_after_second_failure(monkeypatch):
    import main
    from collector.safety import NavigatorError

    calls = {"search": 0}

    def fake_search(page, role, cfg):
        calls["search"] += 1
        raise NavigatorError("Posts filter could not be found.")

    monkeypatch.setattr(main.navigator, "search_role", fake_search)

    assert main.search_with_posts_filter(_FakePage(), "AI Developer", Config()) is False
    assert calls["search"] == 2


def test_search_with_posts_filter_does_not_retry_login_wall(monkeypatch):
    import main
    from collector.safety import LoginRequiredError

    calls = {"search": 0}

    def fake_search(page, role, cfg):
        calls["search"] += 1
        raise LoginRequiredError("LinkedIn login required")

    monkeypatch.setattr(main.navigator, "search_role", fake_search)

    try:
        main.search_with_posts_filter(_FakePage(), "AI Developer", Config())
    except LoginRequiredError:
        pass
    else:
        raise AssertionError("LoginRequiredError must propagate immediately")

    assert calls["search"] == 1