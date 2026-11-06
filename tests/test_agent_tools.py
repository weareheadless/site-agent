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

    assert {"plan_website_change", "spawn_build", "get_metrics", "list_drafts"} <= names
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
