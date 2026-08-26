import json

import pytest

from site_agent.brain.digest import learn
from site_agent.core import reflect as reflect_mod
from site_agent.core.reflect import approve_reflection, effective_persona


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if isinstance(self.replies[0], Exception):
            raise self.replies.pop(0)
        return self.replies.pop(0)


@pytest.fixture
def env(tmp_path):
    from site_agent.core.memory import Memory

    memory = Memory(tmp_path / "memory.db")
    config = {
        "env": {},
        "persona": {
            "name": "Ada",
            "voice": "calm, sea-obsessed",
            "audience": "freedivers",
            "taboo": ["politics"],
        },
        "sources": {"subreddits": ["freediving"]},
    }
    yield memory, config
    memory.close()


def _context(memory, config, llm):
    return {"config": config, "memory": memory, "llm": llm}


def test_persona_prompt_carries_identity_and_taboo(env):
    memory, config = env
    prompt = reflect_mod.effective_persona(config, memory)
    assert "You are Ada" in prompt
    assert "calm, sea-obsessed" in prompt
    assert "Never touch these topics: politics" in prompt
    assert "make up your own mind" in prompt


def test_persona_prompt_carries_spirit_and_directions(env):
    memory, config = env
    config["persona"]["spirit"] = "You dive the cenotes of the Riviera Maya; the water is your home."
    config["persona"]["directions"] = ["Depth is patience.", "  ", "Recommend like a local friend."]
    prompt = reflect_mod.effective_persona(config, memory)
    assert "cenotes of the Riviera Maya" in prompt
    assert "- Depth is patience." in prompt
    assert "- Recommend like a local friend." in prompt
    assert "-   " not in prompt  # blank entries dropped
    # spirit comes before directions come before voice
    assert prompt.index("Riviera Maya") < prompt.index("Depth is patience") < prompt.index("sea-obsessed")


def test_learn_distills_observations_into_insights(env):
    memory, config = env
    memory.record_observation("reddit/freediving", "Weight belt failure story.", meta={"link": "https://r/1"})
    memory.record_observation("rss/news", "New depth record announced.", meta={})
    llm = FakeLLM([json.dumps({"learned": ["Gear safety is a hot topic"], "themes": ["safety", "gear"]})])
    learn(_context(memory, config, llm))

    learnings = memory.recent_observations(source="learning")
    assert len(learnings) == 1
    assert "Gear safety" in learnings[0]["text"]
    assert learnings[0]["meta"]["themes"] == ["safety", "gear"]
    assert memory.kv_get("learned_until_id") == 2
    assert "themes" in json.dumps(memory.kv_get("themes")) or memory.kv_get("themes") == ["safety", "gear"]


def test_learn_skips_when_nothing_new(env):
    memory, config = env
    memory.kv_set("learned_until_id", 99)
    llm = FakeLLM(["should not be called"])
    learn(_context(memory, config, llm))
    actions = [a for a in memory.recent_actions() if a["kind"] == "learn"]
    assert any("nothing new" in a["detail"] for a in actions)
    assert llm.calls == []


def test_learn_raises_on_invalid_json(env):
    memory, config = env
    memory.record_observation("reddit/freediving", "Something happened.")
    llm = FakeLLM(["not json at all"])
    with pytest.raises(RuntimeError, match="invalid JSON"):
        learn(_context(memory, config, llm))


def test_weekly_report_saves_draft(env):
    from site_agent.brain.report import weekly_report

    memory, config = env
    memory.record_observation("learning", "- Traffic dipped on Tuesday", meta={"themes": ["seasonality"]})
    markdown = "# This week on your site\n\nTraffic was steady. I suggest a mouthfill article."
    llm = FakeLLM([markdown])
    draft_id = weekly_report(_context(memory, config, llm))

    drafts = memory.list_drafts(status="pending")
    assert len(drafts) == 1
    assert drafts[0]["kind"] == "report"
    assert "mouthfill article" in drafts[0]["body"]
    assert drafts[0]["title"].startswith("Weekly report")
    assert memory.kv_get("last_report_ts")
    system = llm.calls[0]["messages"][0]["content"]
    assert "Plain language" in system


def test_reflect_and_approve_updates_persona(env):
    memory, config = env
    memory.save_draft("Weekly report x", "body", kind="report")
    proposal = {"voice_notes": ["Lead with numbers"], "avoid": ["Em-dash overuse"]}
    llm = FakeLLM([json.dumps(proposal)])
    draft_id = reflect_mod.reflect(_context(memory, config, llm))

    assert approve_reflection(memory, draft_id) is True
    notes = reflect_mod.approved_notes(memory)
    assert notes["voice_notes"] == ["Lead with numbers"]
    prompt = effective_persona(config, memory)
    assert "Lead with numbers" in prompt
    assert "Stop doing:" in prompt

    assert approve_reflection(memory, draft_id) is False


def test_draft_article_uses_learned_material_and_saves_pending(env):
    from site_agent.brain.article import draft_article

    memory, config = env
    memory.record_observation(
        "learning", "- Everyone asks about mouthfill progressions", meta={"themes": ["equalization"]}
    )
    llm = FakeLLM([
        json.dumps({"title": "Frenzel in four sessions", "angle": "progression", "why": "top question"}),
        "# Frenzel in four sessions\n\n## Why it clicks\n\nBody here.",
        json.dumps({"problems": ["The opening is a generic template", "No sensory detail"]}),
        json.dumps({"article": "# Frenzel in four sessions\n\nRevised with feeling."}),
    ])
    draft_id = draft_article(_context(memory, config, llm))

    drafts = memory.list_drafts(status="pending")
    article = [d for d in drafts if d["kind"] == "article"][0]
    assert article["id"] == draft_id
    assert article["title"] == "Frenzel in four sessions"
    assert article["meta"]["angle"] == "progression"
    assert article["body"].endswith("Revised with feeling.")
    assert len(article["meta"]["self_edit"]) == 2
    topic_call, write_call, critique_call, revise_call = llm.calls
    assert "mouthfill" in topic_call["messages"][1]["content"].lower()
    assert "500-800 words" in write_call["messages"][1]["content"]
    assert "Body here." in critique_call["messages"][1]["content"]
    assert "generic template" in revise_call["messages"][1]["content"]
    # revision is requested as a single structured article, not commentary
    assert "editor's note" in revise_call["messages"][1]["content"].lower()


def test_draft_article_keeps_first_draft_when_self_edit_fails(env):
    from site_agent.brain.article import draft_article

    memory, config = env
    memory.record_observation(
        "learning", "- Everyone asks about mouthfill progressions", meta={"themes": ["equalization"]}
    )
    llm = FakeLLM([
        json.dumps({"title": "Frenzel in four sessions", "angle": "a", "why": "w"}),
        "# Frenzel v1\n\nFirst take.",
        RuntimeError("model down"),
    ])
    draft_id = draft_article(_context(memory, config, llm))
    article = [d for d in memory.list_drafts(status="pending") if d["kind"] == "article"][0]
    assert article["id"] == draft_id
    assert article["body"].startswith("# Frenzel v1")
    assert "self_edit" not in article["meta"]


def test_draft_article_refuses_with_no_material(env):
    from site_agent.brain.article import draft_article

    memory, config = env
    llm = FakeLLM(["never called"])
    with pytest.raises(RuntimeError, match="nothing learned yet"):
        draft_article(_context(memory, config, llm))
    assert llm.calls == []


def test_inner_voice_challenge_records_dialogue_and_returns_problems(env):
    from site_agent.brain import inner_voice

    memory, config = env
    llm = FakeLLM([json.dumps({"problems": ["The nav does not match the header", "No CTA above the fold"]})])
    ctx = _context(memory, config, llm)
    problems = inner_voice.challenge(ctx, "implementation plan", "Plan text here", "Brand: seafoam")

    assert problems == ["The nav does not match the header", "No CTA above the fold"]
    assert llm.calls[0]["timeout_seconds"] == 30
    assert llm.calls[0]["max_retries"] == 0
    assert llm.calls[0]["max_tokens"] == 700
    voice_rows = [r for r in memory.recent_observations(source="inner_voice") if (r.get("meta") or {}).get("role")]
    assert voice_rows, "the challenge should be recorded as a voice observation"
    assert "challenged her implementation plan" in voice_rows[0]["text"]


def test_inner_voice_reads_same_memory_as_ada(env):
    from site_agent.brain import inner_voice

    memory, config = env
    memory.record_observation("learning", "- Everyone asks about mouthfill progressions")
    memory.record_action("article", "draft #7 approved")
    llm = FakeLLM([json.dumps({"problems": []})])
    ctx = _context(memory, config, llm)
    inner_voice.challenge(ctx, "implementation plan", "Plan", "Brand: seafoam")

    # the challenge prompt must include her full memory (learnings + actions), not
    # just the caller's context blob — the voice sees what Ada sees
    call = llm.calls[0]["messages"][1]["content"]
    assert "mouthfill progressions" in call
    assert "draft #7 approved" in call
    assert "Her memory (the same she reads)" in call


def test_inner_voice_challenge_empty_problems_ships(env):
    from site_agent.brain import inner_voice

    memory, config = env
    llm = FakeLLM([json.dumps({"problems": []})])
    problems = inner_voice.challenge(_context(memory, config, llm), "article draft", "Good draft.")
    assert problems == []


def test_inner_voice_challenge_best_effort_on_failure(env):
    from site_agent.brain import inner_voice

    memory, config = env
    llm = FakeLLM([RuntimeError("model down")])
    problems = inner_voice.challenge(_context(memory, config, llm), "article draft", "draft")
    assert problems == []


def test_ada_planner_makes_the_plan(env):
    from site_agent.brain import planner

    memory, config = env
    llm = FakeLLM([json.dumps({
        "plan": "Keep the navigation, deepen the hero composition, and add one restrained scroll gesture.",
    })])
    plan = planner.draft(
        _context(memory, config, llm), "make the homepage feel more alive", "Brand: seafoam"
    )

    assert len(llm.calls) == 1
    assert "scroll gesture" in plan
    assert "Ada's memory" in llm.calls[0]["messages"][1]["content"]


def test_ada_planner_revises_after_inner_voice_criticism(env):
    from site_agent.brain import planner

    memory, config = env
    llm = FakeLLM([json.dumps({
        "plan": "Keep the navigation and make the hero gesture work without the missing element.",
    })])
    plan = planner.revise(
        _context(memory, config, llm),
        "make the homepage feel more alive",
        "Animate the missing breath-ring element.",
        ["The breath-ring element does not exist."],
        "Brand: seafoam",
    )

    assert len(llm.calls) == 1
    assert "missing element" in plan
    prompt = llm.calls[0]["messages"][1]["content"]
    assert "breath-ring" in prompt


def test_brand_context_includes_brand_and_persona(env):
    from site_agent.hands.opencode_runner import _brand_context

    memory, config = env
    config["site"] = {
        "brand": {"name": "OceanicVibes", "colors": {"primary": "#9edbd1"}, "nav": [["Home", "/"]]},
    }
    config["persona"]["voice"] = "calm, sea-obsessed"
    ctx = _brand_context(config)
    assert "OceanicVibes" in ctx
    assert "#9edbd1" in ctx
    assert "calm, sea-obsessed" in ctx


def test_brand_context_supports_documented_brand_keys(env):
    from site_agent.hands.opencode_runner import _brand_context

    memory, config = env
    config["site"] = {"brand": {
        "font_body": "Manrope",
        "font_display": "Fraunces",
        "logo": "https://example.com/logo.svg",
    }}
    ctx = _brand_context(config)
    assert "Manrope" in ctx
    assert "Fraunces" in ctx
    assert "logo.svg" in ctx


def test_visual_plan_prompt_requires_image_choreography_fields():
    from site_agent.brain.planner import _draft_prompt

    prompt = _draft_prompt("Ada", "redesign the image hero", "vision: focal point right")
    assert "image treatment" in prompt[0]["content"]
    assert "depth cue" in prompt[0]["content"]
    assert "mobile fallback" in prompt[0]["content"]
    assert "token-only plan" in prompt[0]["content"]
    assert "signature gesture" in prompt[0]["content"]
    assert "reduced-motion fallback" in prompt[0]["content"]
    assert "new DOM/composition" in prompt[0]["content"]
