"""The brief decides why the piece exists and what still has to be found.

CrawlSEO supplies the reason. Nobody has read the subject. Those are two
different inputs and the brief keeps them apart: a news piece gets no evidence
pages, so the writing service researches the subject; an article about the
site's own work gets the site's own pages, because that is what it quotes.
"""

from __future__ import annotations

import pytest

from site_agent.application.editorial_brief import build_brief, evidence_urls

ACTION = {
    "id": "action_1",
    "revision": 4,
    "problem": "Not enough coverage of red carpet beauty",
    "recommendation": "Write about the awards looks and the products used",
    "expectedOutcome": "Readers find this site for the trend",
    "primaryQuery": "maquillaje alfombra roja",
    "target": {"canonicalUrl": ""},
    "requiredCapabilities": ["article.create"],
    "evidence": [
        {"id": "s1", "url": "https://news.example/looks"},
        {"id": "s2", "url": "https://news.example/products"},
    ],
}
BUSINESS = {"name": "Astrid", "audience": "mujeres interesadas en belleza", "topics": ["belleza", "peinados"]}


def test_a_news_piece_gets_no_evidence_pages_so_the_subject_is_researched():
    brief = build_brief(tenant="site-x", remote=ACTION, business=BUSINESS)

    assert "source_urls" not in brief["evidence"]
    assert brief["evidence"]["min_sources"] == 3
    assert brief["metadata"]["research"] == "subject"


def test_a_piece_about_the_sites_own_work_cites_its_own_pages():
    remote = {
        **ACTION,
        "target": {"canonicalUrl": "https://site.example/services"},
        "requiredCapabilities": ["content.prepare"],
        "evidence": [
            {"id": "s1", "url": "https://site.example/services"},
            {"id": "s2", "url": "https://site.example/about"},
        ],
    }

    brief = build_brief(tenant="site-x", remote=remote)

    assert brief["evidence"]["source_urls"] == [
        "https://site.example/services",
        "https://site.example/about",
    ]
    assert brief["metadata"]["research"] == "own-pages"


def test_the_reason_is_the_topic_and_nothing_is_re_measured():
    brief = build_brief(tenant="site-x", remote=ACTION, business=BUSINESS)

    assert brief["topic"]["question"] == ACTION["problem"]
    assert brief["topic"]["angle"].startswith(ACTION["recommendation"])
    assert brief["topic"]["primary_keyword"] == "maquillaje alfombra roja"
    # No demand field anywhere: the reason is the brief, not a second report.
    assert not any("volume" in str(value).lower() for value in brief.values())


def test_the_default_locale_is_written_first_because_it_is_the_original():
    brief = build_brief(
        tenant="site-x", remote=ACTION, locales=["en", "es"], default_locale="es"
    )

    assert brief["locales"] == ["es", "en"]
    assert brief["business"]["locale"] == "es"


def test_the_writing_service_never_publishes_or_approves():
    brief = build_brief(tenant="site-x", remote=ACTION)

    assert brief["policy"]["publish"] is False
    assert brief["policy"]["approval"] == "none"


def test_the_idempotency_key_is_the_action_revision():
    assert build_brief(tenant="site-x", remote=ACTION)["idempotency_key"] == (
        "crawlseo:action:action_1:rev:4"
    )


def test_an_action_with_nothing_to_say_is_refused_rather_than_invented():
    with pytest.raises(ValueError, match="no title or recommendation"):
        build_brief(tenant="site-x", remote={"id": "a", "revision": 1})


def test_a_called_link_path_is_the_only_internal_link_offered():
    brief = build_brief(tenant="site-x", remote=ACTION, must_link=["/blog", "https://elsewhere.example"])

    assert brief["requirements"]["must_link"] == ["/blog"]


def test_evidence_urls_refuses_a_targetless_article():
    assert evidence_urls(ACTION) == []


def test_evidence_urls_keeps_the_target_first():
    remote = {
        "target": {"canonicalUrl": "https://site.example/services"},
        "requiredCapabilities": ["content.prepare"],
        "evidence": [{"url": "https://site.example/about"}],
    }

    assert evidence_urls(remote)[0] == "https://site.example/services"
