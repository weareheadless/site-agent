import pytest

from site_agent.hands import opencode_provider


def test_specialist_agent_definitions_are_focused_and_read_only_where_expected(tmp_path):
    written = opencode_provider.write_specialist_agents(tmp_path, ["copywriter", "site-implementer"])

    assert written == (".opencode/agent/copywriter.md", ".opencode/agent/site-implementer.md")
    copy_prompt = (tmp_path / ".opencode/agent/copywriter.md").read_text(encoding="utf-8")
    implementation_prompt = (tmp_path / ".opencode/agent/site-implementer.md").read_text(encoding="utf-8")
    assert "task: deny" in copy_prompt
    assert "edit: deny" in copy_prompt
    assert "Do not edit, write, patch, delete, or install files." in copy_prompt
    assert "You may edit only the host-provided implementation worktree" in implementation_prompt
    assert "Never invoke the task tool" in implementation_prompt


def test_specialist_output_requires_one_json_object():
    prompt = opencode_provider.structured_output_prompt("Write the copy deck.", "CopyDeck")
    assert prompt.endswith("no Markdown fences, no commentary, and no second attempt.")

    assert opencode_provider.decode_structured_output({"reply": '{"headline":"Into the dark"}'}) == {
        "headline": "Into the dark"
    }
    assert opencode_provider.decode_structured_output({"reply": "```json\n{\"ok\":true}\n```"}) == {"ok": True}

    with pytest.raises(opencode_provider.SpecialistProviderError, match="one JSON object"):
        opencode_provider.decode_structured_output({"reply": "not json"})


def test_adapter_uses_named_specialist_agent(monkeypatch, tmp_path):
    calls = []

    def fake_run(workspace, prompt, config, **kwargs):
        calls.append({"workspace": workspace, "prompt": prompt, "agent_name": kwargs["agent_name"]})
        return {
            "session_id": "session-copy",
            "reply": '{"headline":"Into the dark"}',
            "raw_tail": [],
            "tool_calls": [],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        }

    monkeypatch.setattr("site_agent.hands.opencode_runner.run_opencode_turn", fake_run)
    request = opencode_provider.SpecialistInvocation(
        role="copywriter",
        workspace=tmp_path,
        prompt="Write the copy deck.",
        config={"builder": {"model": "openrouter/test"}},
    )
    result = opencode_provider.OpenCodeSpecialistAdapter().invoke(request)

    assert result.role == "copywriter"
    assert result.session_id == "session-copy"
    assert calls[0]["agent_name"] == "copywriter"
    assert (tmp_path / ".opencode/agent/copywriter.md").exists()
