from __future__ import annotations

from contextlib import closing

from site_agent.core.chat_jobs import run_job
from site_agent.core.memory import Memory


PLAN = (
    "A profile page is the right shape.\n\n"
    "1. A page at /about/peter-abaji with the credential strip and the record.\n"
    "2. A homepage band that links to it.\n\n"
    "I'll build it once you confirm the portrait and the bio are ready."
)


def _job(tmp_path, config):
    memory = Memory(tmp_path / "memory.db")
    conversation = memory.create_conversation()
    job_id = memory.enqueue_chat_job(conversation, "should we add a profile page?")
    memory.claim_chat_job("test-worker")
    return memory, memory.get_chat_job(job_id), {
        "memory": memory, "config": config, "env": {}, "tenant_config_path": "/tmp/config.yaml",
    }


def test_the_opencode_engine_delivers_the_message_unchanged(tmp_path, monkeypatch):
    from site_agent.application import agent_tools
    from site_agent.hands import chat_agent

    config = {"site": {}, "builder": {"enabled": True}, "chat": {"engine": "opencode"}}
    memory, job, context = _job(tmp_path, config)
    with closing(memory):
        monkeypatch.setattr(chat_agent, "run_turn", lambda *a, **k: {"reply": PLAN, "session": "s1"})
        monkeypatch.setattr(agent_tools, "turn_summary", lambda *a, **k: {
            "completed_payload_effects": [], "source_build_completed": False,
            "merge_draft_id": None, "preview": None, "change": None, "changed": None, "plan": None,
        })

        result = run_job(context, job, "test-worker")

    assert result["reply"] == PLAN


def test_the_opencode_engine_carries_the_build_result_into_the_job(tmp_path, monkeypatch):
    from site_agent.application import agent_tools
    from site_agent.hands import chat_agent

    config = {"site": {}, "builder": {"enabled": True}, "chat": {"engine": "opencode"}}
    memory, job, context = _job(tmp_path, config)
    with closing(memory):
        monkeypatch.setattr(chat_agent, "run_turn", lambda *a, **k: {
            "reply": "The preview is ready.", "session": "s1"})
        monkeypatch.setattr(agent_tools, "turn_summary", lambda *a, **k: {
            "completed_payload_effects": [], "source_build_completed": True,
            "merge_draft_id": 68, "preview": {"id": "p1"}, "change": "footer", "changed": True,
            "plan": {"source_brief": "add the footer"},
        })

        result = run_job(context, job, "test-worker")

    assert result["merge_draft_id"] == 68
    assert result["preview"] == {"id": "p1"}
    assert result["changed"] is True


def test_the_default_engine_is_the_legacy_loop(tmp_path, monkeypatch):
    from site_agent.brain import editor

    config = {"site": {}}
    memory, job, context = _job(tmp_path, config)
    seen = {}

    def handle_message(*args, **kwargs):
        seen["called"] = True
        return {"reply": "legacy answer", "proposal_id": None, "merge_draft_id": None}

    with closing(memory):
        monkeypatch.setattr(editor, "handle_message", handle_message)
        result = run_job(context, job, "test-worker", adapter_factory=lambda: object())

    assert seen["called"] is True
    assert result["reply"] == "legacy answer"


SOURCE_WORKSPACE = {"site": {"clone_path": "/srv/site"}, "builder": {"enabled": True}}


def test_a_source_workspace_uses_the_opencode_engine_without_a_config_key(tmp_path, monkeypatch):
    from site_agent.application import agent_tools
    from site_agent.hands import chat_agent

    memory, job, context = _job(tmp_path, dict(SOURCE_WORKSPACE))
    with closing(memory):
        monkeypatch.setattr(chat_agent, "run_turn", lambda *a, **k: {"reply": PLAN, "session": "s1"})
        monkeypatch.setattr(agent_tools, "turn_summary", lambda *a, **k: {
            "completed_payload_effects": [], "source_build_completed": False,
            "merge_draft_id": None, "preview": None, "change": None, "changed": None, "plan": None,
        })
        result = run_job(context, job, "test-worker")

    assert result["reply"] == PLAN


def test_an_explicit_legacy_key_keeps_the_legacy_loop_on_a_source_workspace(tmp_path, monkeypatch):
    from site_agent.brain import editor

    config = {**SOURCE_WORKSPACE, "chat": {"engine": "legacy"}}
    memory, job, context = _job(tmp_path, config)
    seen = {}

    def handle_message(*args, **kwargs):
        seen["called"] = True
        return {"reply": "legacy answer", "proposal_id": None, "merge_draft_id": None}

    with closing(memory):
        monkeypatch.setattr(editor, "handle_message", handle_message)
        result = run_job(context, job, "test-worker", adapter_factory=lambda: object())

    assert seen["called"] is True
    assert result["reply"] == "legacy answer"
