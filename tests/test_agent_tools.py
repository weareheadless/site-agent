from __future__ import annotations

import json
from contextlib import closing

import pytest

from site_agent.application import agent_tools
from site_agent.core.memory import Memory


class FakePayload:
    def __init__(self, contract=None):
        self.contract = contract or {
            "authoring": {"collections": {"posts": ["title", "body"]}, "globals": {}},
            "enabled": {"collections": ["posts"], "globals": []},
            "locales": ["en"],
            "defaultLocale": "en",
        }

    def require_authoring_contract(self):
        return self.contract

    def list(self, collection, *, draft=True, limit=100, locale=None):
        return [
            {"id": 4, "sourceId": f"{collection}:a", "slug": "a", "title": "Article A", "published": True},
            {"id": 6, "sourceId": f"{collection}:b", "slug": "b", "title": "Article B", "published": True},
        ]


@pytest.fixture
def workspace(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        yield memory, {
            "config": {"site": {"clone_path": str(tmp_path / "site")}, "builder": {"enabled": True}},
            "memory": memory,
            "payload_gateway": FakePayload(),
        }
    finally:
        memory.close()


def test_the_catalog_leaves_file_reads_to_the_agent(workspace):
    memory, context = workspace
    names = {tool["name"] for tool in agent_tools.tool_catalog(memory, context)}

    assert "read_file" not in names
    assert "list_files" not in names
    assert "design_request" not in names


def test_the_catalog_publishes_the_workspace_tools(workspace):
    memory, context = workspace
    names = {tool["name"] for tool in agent_tools.tool_catalog(memory, context)}

    assert {"plan_website_change", "spawn_build", "get_metrics", "list_drafts",
            "list_payload_content"} <= names
    assert "create_payload_draft" in names


def test_every_published_tool_carries_an_input_schema(workspace):
    memory, context = workspace
    for tool in agent_tools.tool_catalog(memory, context):
        assert tool["inputSchema"]["type"] == "object", tool["name"]


def test_an_unknown_job_is_refused(workspace):
    memory, context = workspace
    with pytest.raises(agent_tools.AgentToolError, match="chat job"):
        agent_tools.call_tool(memory, context, 999, "list_drafts", {})


def test_an_unknown_tool_is_refused(workspace):
    memory, context = workspace
    conversation = memory.create_conversation()
    job_id = memory.enqueue_chat_job(conversation, "hello")
    with pytest.raises(agent_tools.AgentToolError, match="unknown workspace tool"):
        agent_tools.call_tool(memory, context, job_id, "drop_tables", {})


def test_a_read_tool_runs_against_the_workspace(workspace):
    memory, context = workspace
    conversation = memory.create_conversation()
    job_id = memory.enqueue_chat_job(conversation, "what is pending?")
    memory.save_draft(title="A pending change", body="", kind="merge")

    text = agent_tools.call_tool(memory, context, job_id, "list_drafts", {})

    assert "A pending change" in text


def test_the_plan_survives_a_second_tool_process(workspace):
    memory, context = workspace
    conversation = memory.create_conversation()
    job_id = memory.enqueue_chat_job(conversation, "change the footer")

    agent_tools.call_tool(memory, context, job_id, "plan_website_change", {
        "content_effects": [], "source_brief": "add the shared footer", "response_only": False,
        "source_paths": ["src/app/(frontend)/oceanic.css"],
        "acceptance_criteria": ["the footer renders on the journal"],
        "business_facts": [],
    })

    summary = agent_tools.turn_summary(memory, context, job_id)
    assert summary["plan"]["source_brief"] == "add the shared footer"


def test_listing_content_answers_from_the_canonical_store(workspace):
    memory, context = workspace
    conversation = memory.create_conversation()
    job_id = memory.enqueue_chat_job(conversation, "what is published?")

    text = agent_tools.call_tool(memory, context, job_id, "list_payload_content", {"collection": "posts"})

    assert '"title": "Article A"' in text
    assert '"slug": "b"' in text


def test_a_build_without_a_model_credential_is_refused_before_it_starts(workspace):
    memory, context = workspace
    conversation = memory.create_conversation()
    job_id = memory.enqueue_chat_job(conversation, "change the footer")

    text = agent_tools.call_tool(memory, context, job_id, "spawn_build", {"brief": "add the footer"})

    assert text.startswith("REFUSED: the build agent has no model credential")


def test_a_validated_plan_reaches_the_build_with_its_exact_brief(tmp_path, monkeypatch):
    from site_agent.hands import opencode_runner

    memory = Memory(tmp_path / "memory.db")
    clone = tmp_path / "site"
    clone.mkdir()
    context = {
        "config": {
            "site": {"clone_path": str(clone)},
            "builder": {"enabled": True},
            "env": {"llm_api_key": "TEST_LLM_KEY"},
        },
        "memory": memory,
        "payload_gateway": FakePayload(),
        "env": {"TEST_LLM_KEY": "secret"},
    }
    conversation = memory.create_conversation()
    job_id = memory.enqueue_chat_job(conversation, "add the footer")
    seen = {}

    def stage_build(ctx, brief, progress=None):
        seen["brief"] = brief
        seen["job"] = ctx.get("_chat_job_id")
        return {"reply": "built", "merge_draft_id": 70, "changed": True, "preview": {"id": "p"}}

    monkeypatch.setattr(opencode_runner, "stage_build", stage_build)
    try:
        agent_tools.call_tool(memory, context, job_id, "plan_website_change", {
            "content_effects": [], "source_brief": "add the shared footer to the journal",
            "response_only": False,
            "source_paths": ["src/app/(frontend)/oceanic.css"],
            "acceptance_criteria": ["the footer renders on the journal"],
            "business_facts": [],
        })
        text = agent_tools.call_tool(memory, context, job_id, "spawn_build", {"brief": "add the footer"})

        assert "add the shared footer to the journal" in seen["brief"]
        assert text.startswith("built")
        assert agent_tools.turn_summary(memory, context, job_id)["merge_draft_id"] == 70
    finally:
        memory.close()
