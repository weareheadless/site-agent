import json

import pytest

from site_agent.hands import opencode_provider


def test_specialist_agent_definitions_are_focused_and_read_only_where_expected(tmp_path):
    written = opencode_provider.write_specialist_agents(tmp_path, ["copywriter", "brand-source-analyst", "site-implementer"])

    assert written == (
        ".opencode/agent/copywriter.md",
        ".opencode/agent/brand-source-analyst.md",
        ".opencode/agent/site-implementer.md",
    )
    copy_prompt = (tmp_path / ".opencode/agent/copywriter.md").read_text(encoding="utf-8")
    brand_prompt = (tmp_path / ".opencode/agent/brand-source-analyst.md").read_text(encoding="utf-8")
    implementation_prompt = (tmp_path / ".opencode/agent/site-implementer.md").read_text(encoding="utf-8")
    assert "task: deny" in copy_prompt
    assert "edit: deny" in copy_prompt
    assert "bash: deny" in copy_prompt
    assert "webfetch: deny" in copy_prompt
    assert "websearch: deny" in copy_prompt
    assert "doom_loop: deny" in copy_prompt
    assert "Do not edit, write, patch, delete, or install files." in copy_prompt
    assert "You are the brand-source-analyst specialist" in brand_prompt
    assert "mode: primary" in brand_prompt
    assert "edit: deny" in brand_prompt
    assert "You may edit only the host-provided implementation worktree" in implementation_prompt
    assert "Never invoke the task tool" in implementation_prompt


def test_authoring_agent_cannot_run_a_browser_or_server_self_review(tmp_path):
    """Authoring phases can edit source and run the project's build/check
    scripts, but the host owns rendering and validation. The capability to
    launch a browser, HTTP server, or custom harness is denied so an authoring
    turn cannot enter an unbounded self-review loop."""
    opencode_provider.write_specialist_agents(tmp_path, ["site-implementer"])
    implementation_prompt = (tmp_path / ".opencode/agent/site-implementer.md").read_text(encoding="utf-8")

    assert "edit: allow" in implementation_prompt
    assert "webfetch: deny" in implementation_prompt
    assert "websearch: deny" in implementation_prompt
    assert "doom_loop: deny" in implementation_prompt
    # Catch-all deny first, then the project's own build/check commands.
    assert '    "*": deny' in implementation_prompt
    assert '    "npm *": allow' in implementation_prompt
    # The dangerous process launchers are never allowlisted.
    for command in ("node *", "python *", "chrome *", "chromium *", "npx *", "curl *", "wget *"):
        assert f'"{command}": allow' not in implementation_prompt
    assert "the host owns all rendering, browser, screenshot, interaction, motion" in implementation_prompt


def test_specialist_output_requires_one_json_object():
    prompt = opencode_provider.structured_output_prompt("Write the copy deck.", "CopyDeck")
    assert "complete DesignPhaseArtifact envelope" in prompt
    assert "schema_version must be 1" in prompt

    assert opencode_provider.decode_structured_output({"reply": '{"headline":"Into the dark"}'}) == {
        "headline": "Into the dark"
    }
    assert opencode_provider.decode_structured_output({"reply": "```json\n{\"ok\":true}\n```"}) == {"ok": True}
    assert opencode_provider.decode_structured_output({
        "reply": '"headline":"Into the dark",',
        "raw_tail": ["{", '"headline":"Into the dark",', '"ok":true', "}"],
    }) == {"headline": "Into the dark", "ok": True}
    assert opencode_provider.decode_structured_output({
        "reply": '"headline":"Into the dark",',
        "raw_output": 'planning noise\n{\n"headline":"Into the dark",\n"ok":true\n}',
    }) == {"headline": "Into the dark", "ok": True}
    assert opencode_provider.decode_structured_output({
        "raw_output": 'prefix\n{"outer":{"ok":true},"headline":"Into the dark"}\n',
    }) == {"outer": {"ok": True}, "headline": "Into the dark"}
    assert opencode_provider.decode_structured_output({
        "reply": '{"outer":{"ok":true],"headline":"Into the dark"}',
    }) == {"outer": {"ok": True}, "headline": "Into the dark"}
    assert opencode_provider.decode_structured_output({
        "transcript": '\n'.join([
            '{"type":"text","part":{"text":"{"}}',
            '{"type":"text","part":{"text":"\\\"ok\\\":true"}}',
            '{"type":"text","part":{"text":"}"}}',
        ])
    }) == {"ok": True}
    direction_response = json.dumps({
        "direction": "Follow one continuous line of light.",
        "experience_plan": {"schema_version": 1},
    }, separators=(",", ":"))
    assert opencode_provider.decode_structured_output({
        "transcript": json.dumps({
            "type": "text",
            "text": direction_response,
            "part": {"text": direction_response},
        })
    }) == json.loads(direction_response)
    assert opencode_provider.decode_structured_output({
        "reply": direction_response[:-1],
    }) == json.loads(direction_response)

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


def test_adapter_scopes_configured_output_limit_to_specialist_turn(monkeypatch, tmp_path):
    observed = {}

    def fake_run(workspace, prompt, config, **kwargs):
        observed["runtime"] = json.loads(
            (workspace / "opencode.json").read_text(encoding="utf-8")
        )
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
        config={
            "builder": {
                "model": "openrouter/deepseek/deepseek-v4.1-flash",
                "output_tokens": 65536,
                "reasoning_effort": "low",
            },
            "llm": {"base_url": "https://openrouter.ai/api/v1"},
        },
        api_key_env="OPENROUTER_API_KEY",
    )

    opencode_provider.OpenCodeSpecialistAdapter().invoke(request)

    runtime = observed["runtime"]
    assert runtime["model"] == "openrouter/deepseek/deepseek-v4.1-flash"
    model = runtime["provider"]["openrouter"]["models"]["deepseek/deepseek-v4.1-flash"]
    assert model["limit"]["output"] == 65536
    assert model["options"]["max_tokens"] == 65536
    assert not (tmp_path / "opencode.json").exists()
