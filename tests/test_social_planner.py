import json
from types import SimpleNamespace

import pytest

from site_agent.brain import social
from site_agent.core import jobs
from site_agent.core.jobs import register_builtin
from site_agent.core.contracts import ArtifactKind
from site_agent.core.memory import Memory
from site_agent.core.scheduler import Scheduler


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.messages = []

    def chat(self, messages, **kwargs):
        self.messages.append(messages)
        return self.response


def _context(memory, llm, service=None, **config):
    return {
        "config": {
            "persona": {
                "name": "Ada",
                "voice": "calm and practical",
                "audience": "Beginner divers",
                "taboo": ["medical claims"],
            },
            **config,
        },
        "memory": memory,
        "llm": llm,
        "persona_prompt": "Ada's grounded work persona. Never make medical claims.",
        "social_post_service": service,
    }


def _response(source_url="https://example.com/guide"):
    return json.dumps({
        "goal": "Teach one useful habit",
        "audience": "Beginner divers",
        "brief": "A calm post about equalization practice",
        "caption": "Practice gently before depth.",
        "visual_message": "Relax first. Depth follows.",
        "format": "single",
        "language": "en",
        "media_names": [],
        "animated": False,
        "source_context": [{"title": "Guide", "url": source_url}],
        "constraints": {"avoid": ["medical claims"]},
    })


def test_planner_uses_observed_sources_and_honesty_context(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    memory.record_observation(
        "rss",
        "Equalization guide. Practice before depth.",
        meta={"link": "https://example.com/guide"},
    )
    llm = FakeLLM(_response())
    challenged = []
    monkeypatch.setattr(
        social.inner_voice,
        "challenge",
        lambda context, subject, subject_blob, context_blob: challenged.append(subject_blob) or [],
    )
    brief = social.plan(_context(memory, llm))
    assert brief.caption == "Practice gently before depth."
    assert brief.source_context[0]["url"] == "https://example.com/guide"
    prompt = "\n".join(message["content"] for turn in llm.messages for message in turn)
    assert "Never invent facts" in prompt
    assert "medical claims" in prompt
    assert challenged
    memory.close()


def test_planner_rejects_unobserved_source_and_empty_material(tmp_path):
    empty = Memory(tmp_path / "empty.db")
    with pytest.raises(social.SocialPlanningError, match="no credible material"):
        social.plan(_context(empty, FakeLLM(_response())))
    empty.close()

    memory = Memory(tmp_path / "sources.db")
    memory.record_observation("rss", "A real observation", meta={"link": "https://example.com/real"})
    with pytest.raises(social.SocialPlanningError, match="source URL"):
        social.plan(_context(memory, FakeLLM(_response("https://example.com/invented"))))
    memory.close()


def test_planner_applies_format_default_and_enforces_languages(tmp_path):
    memory = Memory(tmp_path / "preferences.db")
    memory.record_observation("rss", "A real observation", meta={"link": "https://example.com/real"})
    payload = json.loads(_response())
    payload["source_context"][0]["url"] = "https://example.com/real"
    payload["format"] = None
    brief = social.plan(_context(
        memory,
        FakeLLM(json.dumps(payload)),
        social={"default_format": "carousel", "languages": ["en"]},
    ))
    assert brief.format == "carousel"

    payload["language"] = "fr"
    with pytest.raises(social.SocialPlanningError, match="social.languages"):
        social.plan(_context(
            memory,
            FakeLLM(json.dumps(payload)),
            social={"default_format": "single", "languages": ["en"]},
        ))
    memory.close()


def test_social_schedule_is_disabled_by_default_and_registered_when_enabled(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    scheduler = Scheduler(memory, tmp_path / "scheduler.lock")
    context = _context(memory, object(), object(), social={"enabled": False})
    register_builtin(scheduler, context["config"], context)
    assert "social_post" not in {name for name, _spec, _fn in scheduler.jobs}

    enabled_scheduler = Scheduler(memory, tmp_path / "enabled.lock")
    enabled = _context(memory, object(), object(), social={"enabled": True})
    register_builtin(enabled_scheduler, enabled["config"], enabled)
    assert "social_post" in {name for name, _spec, _fn in enabled_scheduler.jobs}
    memory.close()


def test_social_schedule_stops_at_pending_approval_limit(monkeypatch):
    class PendingMemory:
        def __init__(self):
            self.actions = []

        def list_approval_requests(self, **kwargs):
            return [SimpleNamespace(artifact_id=7)]

        def get_artifact(self, artifact_id):
            return SimpleNamespace(kind=ArtifactKind.SOCIAL_POST)

        def record_action(self, kind, detail):
            self.actions.append((kind, detail))

    memory = PendingMemory()
    monkeypatch.setattr(jobs.brain_social, "run", lambda _context: pytest.fail("planner should not run"))
    jobs._social_post({"config": {"social": {"max_pending": 1}}, "memory": memory})
    assert memory.actions == [("social_post", "skipped: 1 pending approval(s) reaches max_pending=1")]
