from types import SimpleNamespace
from unittest import mock

import pytest

from site_agent import senses
from site_agent.core import jobs
from site_agent.core.jobs import register_builtin
from site_agent.core.memory import Memory
from site_agent.core.scheduler import Scheduler
from site_agent.senses.base import Item, canonical_link, score_item, strip_html


def _entry(title, link="https://x/post"):
    return SimpleNamespace(
        title=title,
        summary="<p>some <b>html</b> summary</p>",
        link=link,
        published_parsed=(2026, 8, 22, 10, 0, 0, 0, 0, 0),
    )


def test_strip_html_and_canonical_link():
    assert strip_html("<p>a <b>b</b></p>") == "a b"
    dirty = "https://Site.com/path/?utm_source=x&id=2"
    clean = "https://site.com/path?id=2"
    assert canonical_link(dirty) == canonical_link(clean)
    assert len(canonical_link(clean)) == 40


def test_item_identity_matches_across_headline_variants():
    a = Item(title="Freediving record broken", summary="", link="https://a.com/x?utm_campaign=t", source="s")
    same_story = Item(title="freediving   RECORD  broken", summary="", link="https://b.com/mirror", source="other")
    other = Item(title="Completely different news", summary="", link="https://c.com/y", source="s")
    assert set(a.identity_keys) & set(same_story.identity_keys)
    assert not set(a.identity_keys) & set(other.identity_keys)


def test_score_item_keyword_overlap():
    item = Item(title="Mouthfill technique deep dive", summary="equalization tips", link="", source="s")
    score_item(item, ["mouthfill", "equalization", "wetsuits"])
    assert item.score == pytest.approx(2 / 4)
    assert sorted(item.matched) == ["equalization", "mouthfill"]


def test_fetch_subreddits_parses_feed_entries(monkeypatch):
    parsed = SimpleNamespace(entries=[_entry("Depth training basics"), _entry("New PB today")])
    seen_urls = []

    def fake_parse(url, agent=None):
        seen_urls.append(url)
        return parsed

    monkeypatch.setattr("site_agent.senses.reddit.feedparser.parse", fake_parse)
    items = senses.fetch_subreddits(["freediving"])
    assert seen_urls == ["https://www.reddit.com/r/freediving/.rss"]
    assert [i.title for i in items] == ["Depth training basics", "New PB today"]
    assert items[0].source == "reddit/freediving"
    assert items[0].clean_summary.startswith("some html")


def test_collect_combines_sources_and_scores(monkeypatch):
    monkeypatch.setattr(
        senses, "fetch_subreddits", lambda entries: [Item("Mouthfill progress", "", "https://r/1", "reddit/freediving")]
    )
    monkeypatch.setattr(
        senses, "fetch_feeds", lambda feeds: [Item("Deeper Blue newsletter", "", "https://n/1", "rss/deeperblue")]
    )
    config = {"sources": {"subreddits": ["freediving"], "rss_feeds": [{"name": "deeperblue"}], "keywords": ["mouthfill"]}}
    items = senses.collect(config)
    assert len(items) == 2
    scored = [i for i in items if i.matched]
    assert len(scored) == 1 and scored[0].source == "reddit/freediving"


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def _runtime(tmp_path, config):
    memory = Memory(tmp_path / "memory.db")
    clock = FakeClock()
    scheduler = Scheduler(memory, lock_path=tmp_path / "lock", clock=clock)
    context = {"config": config, "memory": memory}
    register_builtin(scheduler, config, context)
    return memory, clock, scheduler


def _config(**overrides):
    sources = {"subreddits": ["freediving"], "rss_feeds": [], **overrides}
    return {
        "env": {},
        "ga": {"enabled": False},
        "llm": {"base_url": "https://api.test/v1"},
        "sources": sources,
    }


def test_builtin_registry_includes_health_check(tmp_path):
    memory, _, scheduler = _runtime(tmp_path, _config(subreddits=[]))
    names = [name for name, _, _ in scheduler.jobs]
    assert "health_check" in names
    memory.close()


def test_builtin_registry_includes_private_inner_life_jobs(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    scheduler = Scheduler(memory, lock_path=tmp_path / "lock", clock=FakeClock())
    config = _config(subreddits=[])
    context = {"config": config, "memory": memory, "llm": object()}

    register_builtin(scheduler, config, context)

    names = [name for name, _, _ in scheduler.jobs]
    assert {"inner_voice", "dream", "awaken", "integrate_self"} <= set(names)
    memory.close()


def test_digest_records_new_items_then_dedupes(tmp_path):
    memory, _, scheduler = _runtime(tmp_path, _config())
    batch = [
        Item("Mouthfill breakthrough", "great session", "https://reddit.com/r/freediving/1", "reddit/freediving"),
        Item("Static apnea table", "training plan", "https://reddit.com/r/freediving/2", "reddit/freediving"),
    ]
    with mock.patch.object(jobs, "collect", return_value=batch):
        scheduler.run_once()
    obs = memory.recent_observations(source="reddit/freediving")
    assert {o["text"].split(".")[0] for o in obs} == {"Mouthfill breakthrough", "Static apnea table"}
    meta = obs[0]["meta"]
    assert meta["link"].startswith("https://")

    with mock.patch.object(jobs, "collect", return_value=batch):
        scheduler.run_once()
    assert len(memory.recent_observations(source="reddit/freediving")) == 2


def test_digest_respects_min_score_and_skips_errors(tmp_path):
    memory, _, scheduler = _runtime(tmp_path, _config(keywords=["mouthfill"], min_score=0.25))
    batch = [
        Item("Unrelated chatter", "nothing", "https://r/a", "reddit/freediving"),
        Item("Mouthfill equalization talk", "deep", "https://r/b", "reddit/freediving"),
        Item("[feed error] freediving: timeout", "", "", "error"),
    ]
    batch[0].score = 0.0
    batch[1].score = 0.5
    with mock.patch.object(jobs, "collect", return_value=batch):
        scheduler.run_once()
    obs = memory.recent_observations(source="reddit/freediving")
    assert len(obs) == 1 and "Mouthfill" in obs[0]["text"]
    errors = [a for a in memory.recent_actions() if a["kind"] == "digest"]
    assert any("feed errors" in e["detail"] for e in errors)


def test_ga_snapshot_disabled_by_default_and_enabled_when_configured(tmp_path):
    config = _config()
    config["ga"] = {"enabled": False}
    memory, clock, scheduler = _runtime(tmp_path, config)
    with mock.patch.object(senses.ga, "weekly_summary") as ga_mock:
        clock.now += 4000
        scheduler.run_once()
        ga_mock.assert_not_called()

    config["ga"] = {"enabled": True, "key_path": "/tmp/k.json", "property_id": "123"}
    memory2, clock2, scheduler2 = _runtime(tmp_path / "b", config)
    with mock.patch.object(senses.ga, "weekly_summary", return_value={"current_week": {"activeUsers": 5}}) as ga_mock:
        clock2.now += 4000
        scheduler2.run_once()
        ga_mock.assert_called_once()
    snapshot = memory2.latest_snapshot("ga4")
    assert snapshot["data"]["current_week"]["activeUsers"] == 5
