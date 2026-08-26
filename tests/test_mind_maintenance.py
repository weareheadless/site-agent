import json
from unittest import mock

import pytest

from site_agent.brain import dream as dream_mod
from site_agent.brain import inner_voice as inner_mod
from site_agent.core import maintenance
from site_agent.core.memory import Memory
from site_agent.core.scheduler import Scheduler


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        if isinstance(self.replies[0], Exception):
            raise self.replies.pop(0)
        return self.replies.pop(0)


@pytest.fixture
def env(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    config = {"env": {}, "persona": {"name": "Ada", "lures": ["a lighthouse at dawn"]}, "maintenance": {}}
    context = {"config": config, "memory": memory}
    yield memory, config, context
    memory.close()


def _seed_reading(memory, count=8):
    for i in range(count):
        memory.record_observation("reddit/freediving", f"Reading note number {i} about depth.", meta={})


def test_inner_voice_records_mood_and_thought(env):
    memory, config, context = env
    memory.record_observation("learning", "- Gear safety keeps coming up", meta={"themes": ["safety"]})
    context["llm"] = FakeLLM([json.dumps({"mood": "quietly alert", "thought": "Safety stories outnumber gear talk."})])
    context["persona_prompt"] = "You are Ada."
    inner_mod.think(context)

    notes = memory.recent_observations(source="inner_voice")
    assert len(notes) == 1
    assert notes[0]["meta"]["mood"] == "quietly alert"
    assert memory.kv_get("mood") == {"current": "quietly alert"}
    actions = [a for a in memory.recent_actions() if a["kind"] == "inner_voice"]
    assert any("quietly alert" in a["detail"] for a in actions)


def test_inner_voice_private_thought_is_tagged(env):
    memory, config, context = env
    config["inner_voice"] = {"private_chance": 1.0}
    memory.record_observation("learning", "- Depth training interest is steady", meta={})
    context["llm"] = FakeLLM([json.dumps({"mood": "hollow", "thought": "Why do I keep circling the same drowned question?"})])
    context["persona_prompt"] = "You are Ada."
    inner_mod.think(context)

    notes = memory.recent_observations(source="inner_voice")
    assert notes[0]["meta"]["private"] is True
    actions = [a for a in memory.recent_actions() if a["kind"] == "inner_voice"]
    assert "private" in actions[0]["detail"]


def test_inner_voice_skips_when_no_material(env):
    memory, _, context = env
    context["llm"] = FakeLLM(["never called"])
    inner_mod.think(context)
    actions = [a for a in memory.recent_actions() if a["kind"] == "inner_voice"]
    assert any("skipped" in a["detail"] for a in actions)
    assert context["llm"].calls == []


def test_dream_combines_own_material_and_reading_with_lure(env):
    memory, config, context = env
    _seed_reading(memory)
    memory.record_observation("learning", "- Gear safety keeps coming up", meta={"themes": ["safety"]})
    memory.record_observation("inner_voice", "So much of it comes back to depth.", meta={"mood": "quietly alert"})
    memory.kv_set("mood", {"current": "quietly alert"})
    context["llm"] = FakeLLM(["A weight belt on the seabed like an erased ledger line, and I kept diving."])
    context["persona_prompt"] = "You are Ada."
    with mock.patch.object(dream_mod.random, "choice", return_value="a ledger with one line erased"):
        dream_mod.dream(context)

    dreams = memory.recent_observations(source="dream")
    assert len(dreams) == 1
    meta = dreams[0]["meta"]
    assert meta["lure"] == "a ledger with one line erased"
    assert meta["fragments"] == 6
    assert meta["own_material"] is True
    assert meta.get("seed_idea") is None
    system = context["llm"].calls[0][0]["content"]
    assert "dreaming mind" in system
    assert "FIRST PERSON" in system


def test_dream_skips_entirely_without_any_material(env):
    memory, config, context = env
    context["llm"] = FakeLLM(["never called"])
    dream_mod.dream(context)
    actions = [a for a in memory.recent_actions() if a["kind"] == "dream"]
    assert any("skipped" in a["detail"] for a in actions)
    assert context["llm"].calls == []


def test_dream_uses_configured_lure_list(env):
    memory, config, context = env
    _seed_reading(memory, count=3)
    context["llm"] = FakeLLM(["waves folding into a spreadsheet I could not read"])
    with mock.patch.object(dream_mod.random, "choice", return_value="a lighthouse at dawn") as picker:
        dream_mod.dream(context)
    picker.assert_called_once()
    assert memory.recent_observations(source="dream")[0]["meta"]["lure"] == "a lighthouse at dawn"


def test_awaken_decides_dream_meaning_and_folds_it_back(env):
    memory, config, context = env
    memory.record_observation(
        "dream", "I kept losing my fins in a green corridor and nobody stopped.",
        meta={"lure": "the ocean"},
    )
    context["llm"] = FakeLLM([json.dumps({
        "meant_anything": True,
        "meaning": "I am afraid the site is drifting from the people it was built for.",
        "mood": "uneasy",
        "theme": "audience drift",
    })])
    context["persona_prompt"] = "You are Ada."
    dream_mod.awaken(context)

    meaning = memory.recent_observations(source="awaken")
    assert len(meaning) == 1
    assert "drifting" in meaning[0]["text"]
    assert memory.kv_get("last_dream_meaning") == "I am afraid the site is drifting from the people it was built for."
    assert memory.kv_get("mood") == {"current": "uneasy"}
    assert "audience drift" in memory.kv_get("themes")
    actions = [a for a in memory.recent_actions() if a["kind"] == "awaken"]
    assert "meaning kept" in actions[0]["detail"]


def test_awaken_skips_when_no_dream(env):
    memory, config, context = env
    context["llm"] = FakeLLM(["never called"])
    dream_mod.awaken(context)
    actions = [a for a in memory.recent_actions() if a["kind"] == "awaken"]
    assert any("no dream" in a["detail"] for a in actions)
    assert context["llm"].calls == []


def test_health_check_files_findings_without_llm(env):
    memory, _, context = env
    for i in range(6):
        memory.record_observation("reddit/freediving", "Identical duplicate headline text here.")
    memory.save_draft("Old report", "body", kind="report")
    memory.conn.execute("UPDATE drafts SET created_ts = '2026-01-01T00:00:00+00:00' WHERE kind='report'")
    memory.conn.commit()

    findings = maintenance.health_check(context)
    assert any("repeated observations" in f for f in findings)
    assert any("awaiting owner review" in f for f in findings)
    health = memory.kv_get("last_health")
    assert len(health["findings"]) >= 2


def test_health_check_reports_healthy_when_clean(env):
    memory, _, context = env
    findings = maintenance.health_check(context)
    assert findings == []
    actions = [a for a in memory.recent_actions() if a["kind"] == "health"]
    assert actions and actions[0]["detail"] == "healthy"


def test_compact_archives_old_raw_and_preserves_identity(env):
    memory, config, context = env
    config["maintenance"] = {"observation_retention_days": 30, "compact_min_batch": 5}

    for i in range(7):
        memory.conn.execute(
            "INSERT INTO observations (ts, source, text, meta) VALUES (?, ?, ?, '{}')",
            ("2026-05-01T00:00:00+00:00", "rss/news", f"old raw note {i}"),
        )
    memory.record_observation("learning", "- keep me forever", meta={})
    memory.record_observation("inner_voice", "keep me too", meta={"mood": "calm"})

    context["llm"] = FakeLLM([json.dumps({"archive": ["Depth training interest is steady"]})])
    maintenance.compact_memory(context)

    remaining_sources = [r["source"] for r in memory.recent_observations(limit=50)]
    assert "archive" in remaining_sources
    assert "learning" in remaining_sources
    assert "inner_voice" in remaining_sources
    assert not any(s.startswith("rss/") for s in remaining_sources)
    rows = memory.recent_observations(source="archive")
    meta = rows[0]["meta"]
    assert meta["compressed"] == 7
    assert meta["period"][0] == "2026-05-01"


def test_compact_skips_small_batches(env):
    memory, config, context = env
    config["maintenance"] = {"observation_retention_days": 30, "compact_min_batch": 20}
    context["llm"] = FakeLLM(["never called"])
    maintenance.compact_memory(context)
    actions = [a for a in memory.recent_actions() if a["kind"] == "compact"]
    assert any("nothing to do" in a["detail"] for a in actions)
