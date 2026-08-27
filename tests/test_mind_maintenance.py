import json
from unittest import mock

import pytest

from site_agent.brain import dream as dream_mod
from site_agent.brain import inner_voice as inner_mod
from site_agent.brain import self_model as self_model_mod
from site_agent.core.jobs import _with_inner_identity
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
    config = {
        "env": {},
        "persona": {"name": "Ada", "lures": ["a lighthouse at dawn"]},
        "dream": {"residue_count": 2},
        "maintenance": {},
    }
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
    assert meta["fragments"] == 2
    assert meta["own_material"] is True
    assert meta.get("seed_idea") is None
    system = context["llm"].calls[0][0]["content"]
    assert "dreaming mind" in system
    assert "FIRST PERSON" in system


def test_dream_skips_when_only_customer_reading_exists(env):
    memory, _, context = env
    _seed_reading(memory)
    context["llm"] = FakeLLM(["must not be called"])

    dream_mod.dream(context)

    assert memory.recent_observations(source="dream") == []
    assert context["llm"].calls == []


def test_dream_prompt_keeps_imagery_open_without_making_a_human_biography(env):
    memory, config, _ = env
    memory.record_observation("inner_voice", "I keep circling an unfinished question.", meta={"private": True})
    private = "You are Ada, an autonomous AI."
    messages = dream_mod._prompt(
        private,
        "private thread: an unfinished question",
        [],
        "a locked room",
    )
    system = messages[0]["content"].lower()

    assert "private" in system
    assert "do not force" in system
    assert "human biography" in system
    assert "machine" not in system.replace("autonomous ai", "")


def test_awaken_keeps_inner_theme_out_of_content_themes(env):
    memory, _, context = env
    memory.record_observation("dream", "A question folded in on itself.", meta={})
    memory.kv_set("themes", ["equalization"])
    context["llm"] = FakeLLM([json.dumps({
        "meant_anything": True,
        "meaning": "I am still deciding what I owe my own attention.",
        "mood": "unsettled",
        "theme": "attention and choice",
    })])
    context["persona_prompt"] = "You are Ada."

    dream_mod.awaken(context)

    assert memory.kv_get("themes") == ["equalization"]
    assert memory.kv_get("inner_themes") == ["attention and choice"]


def test_awaken_does_not_keep_noise_as_meaning(env):
    memory, _, context = env
    memory.record_observation("dream", "Static without a shape.", meta={})
    memory.kv_set("last_dream_meaning", "an older thread")
    context["llm"] = FakeLLM([json.dumps({
        "meant_anything": False,
        "meaning": "the model was tempted to explain noise",
        "mood": "quiet",
        "theme": "noise",
    })])

    dream_mod.awaken(context)

    assert memory.recent_observations(source="awaken") == []
    assert memory.kv_get("last_dream_meaning") == "an older thread"
    assert memory.kv_get("inner_themes") is None


def test_self_integration_can_leave_her_unchanged_and_advances_watermark(env):
    memory, _, context = env
    event_id = memory.record_observation(
        "inner_voice", "I do not know whether this matters yet.", meta={"private": True}
    )
    context["llm"] = FakeLLM([json.dumps({
        "changed": False,
        "self_description": "",
        "persistent_tendencies": [],
        "open_questions": [],
        "reason": "Not enough has changed.",
    })])

    self_model_mod.integrate(context)

    assert self_model_mod.current_self(memory)["self_description"] == ""
    assert memory.kv_get("inner_self_until_id") == event_id
    assert memory.recent_observations(source="identity_shift") == []


def test_self_integration_does_not_treat_uninterpreted_dream_as_identity_evidence(env):
    memory, _, context = env
    memory.record_observation("dream", "A borrowed scene with no clear residue.", meta={})
    context["llm"] = FakeLLM(["must not be called"])

    self_model_mod.integrate(context)

    assert context["llm"].calls == []
    assert memory.kv_get("inner_self_until_id") is None


def test_self_integration_persists_only_adasself_reported_change(env):
    memory, _, context = env
    event_id = memory.record_observation(
        "awaken", "I keep returning to the cost of easy closure.", meta={}
    )
    context["llm"] = FakeLLM([json.dumps({
        "changed": True,
        "self_description": "I distrust easy closure and return to unfinished questions.",
        "persistent_tendencies": ["I distrust easy closure."],
        "open_questions": ["What deserves to remain unresolved?"],
        "reason": "The same question has persisted across experiences.",
    })])

    self_model_mod.integrate(context)

    state = self_model_mod.current_self(memory)
    assert state["self_description"].startswith("I distrust")
    assert state["open_questions"] == ["What deserves to remain unresolved?"]
    assert memory.kv_get("inner_self_until_id") == event_id
    shift = memory.recent_observations(source="identity_shift")[0]
    assert shift["meta"]["evidence_ids"] == [event_id]
    assert "easy closure" in shift["text"]


def test_inner_life_job_context_excludes_customer_role(env):
    memory, config, context = env
    config["persona"]["spirit"] = "You are a freediver whose world is Bacalar."
    config["persona"]["audience"] = "Freedivers considering Bacalar training"

    seen = {}

    def capture(inner_context):
        seen["persona"] = inner_context["persona_prompt"]
        seen["identity"] = inner_context["inner_identity_prompt"]

    _with_inner_identity(context, capture)

    assert "Bacalar" not in seen["persona"]
    assert seen["persona"] == seen["identity"]


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
    memory.record_observation("inner_voice", "A private question remains unfinished.", meta={"private": True})
    context["llm"] = FakeLLM(["waves folding into a spreadsheet I could not read"])
    with mock.patch.object(dream_mod.random, "choice", return_value="a lighthouse at dawn") as picker:
        dream_mod.dream(context)
    assert picker.call_count == 2  # semantic anchor, then the configured lure
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
    assert memory.kv_get("inner_themes") == ["audience drift"]
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
    memory.record_observation("dream", "keep my dreams too", meta={})
    memory.record_observation("awaken", "keep what surfaced on waking", meta={})

    context["llm"] = FakeLLM([json.dumps({"archive": ["Depth training interest is steady"]})])
    maintenance.compact_memory(context)

    remaining_sources = [r["source"] for r in memory.recent_observations(limit=50)]
    assert "archive" in remaining_sources
    assert "learning" in remaining_sources
    assert "inner_voice" in remaining_sources
    assert "dream" in remaining_sources
    assert "awaken" in remaining_sources
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
