"""The agent's own stream decides whether a turn succeeded.

OpenCode writes its exit status after the turn is over, from its own teardown.
In 2.2.5 that status is 1 after a finished, answered turn whenever a tool it
could not complete without a client was involved: the websearch tool asks the
client to choose a provider, `run --auto` answers the question itself, and the
abandoned step leaves a non-zero status behind. The runner used to read that
status as "the turn died" and discard a complete answer, so the owner was told
"there is no result to review" about work that existed.
"""

import json

import pytest

from site_agent.hands import opencode_runner as runner


class _Process:
    """A fake CLI process: fixed stdout lines, fixed return code, no signals."""

    def __init__(self, lines, returncode):
        self.pid = 12345
        self.returncode = returncode
        self.stdout = iter([json.dumps(line) if not isinstance(line, str) else line for line in lines])

    def wait(self, timeout=None):
        return self.returncode


def _install(monkeypatch, lines, returncode):
    monkeypatch.setattr(runner, "_opencode_bin", lambda config: "opencode")
    monkeypatch.setattr(runner, "_isolated_env", lambda *a, **k: {})
    monkeypatch.setattr(
        runner.subprocess, "Popen", lambda *a, **k: _Process(lines, returncode),
    )


def _step(message_id, reason):
    return {
        "type": "step_finish",
        "part": {
            "type": "step-finish", "reason": reason, "messageID": message_id,
            "tokens": {"input": 10, "output": 5},
        },
    }


def _text(message_id, text):
    return {
        "type": "text",
        "part": {"type": "text", "text": text, "messageID": message_id},
    }


def _tool(message_id, tool="websearch", status="error"):
    return {
        "type": "tool_use",
        "part": {
            "type": "tool", "tool": tool, "messageID": message_id,
            "state": {"status": status, "error": "Web search cancelled"},
        },
    }


def test_a_finished_answer_survives_a_nonzero_cli_exit(monkeypatch, tmp_path):
    """A non-zero exit after a completed turn is teardown, not a failed turn."""
    _install(monkeypatch, [
        _tool("msg_a"),
        _step("msg_a", "tool-calls"),
        _text("msg_b", "He preparado el artículo completo como borrador."),
        _step("msg_b", "stop"),
        # The CLI then fails during its own shutdown.
    ], returncode=1)

    result = runner.run_opencode_turn(
        tmp_path, "write the article", {"builder": {"timeout_seconds": 30}},
        reply_mode="final_message",
    )

    assert result["reply"] == "He preparado el artículo completo como borrador."
    assert result["exit_code"] == 1


def test_a_finished_answer_survives_a_trailing_failed_tool(monkeypatch, tmp_path):
    """The agent already saw the failed tool and answered anyway."""
    _install(monkeypatch, [
        _tool("msg_a", "websearch", "error"),
        _text("msg_b", "I could not verify the looks, so here is what I can confirm."),
        _step("msg_b", "stop"),
    ], returncode=0)

    result = runner.run_opencode_turn(
        tmp_path, "write the article", {"builder": {"timeout_seconds": 30}},
        reply_mode="final_message",
    )

    assert result["reply"].startswith("I could not verify")


def test_an_unfinished_turn_still_fails(monkeypatch, tmp_path):
    """No finished step means no answer, whatever the text looked like."""
    _install(monkeypatch, [
        _text("msg_a", "Starting to look at the repository."),
        _tool("msg_a", "read", "completed"),
        _step("msg_a", "tool-calls"),
    ], returncode=1)
    monkeypatch.setattr(runner, "_persist_turn_failure", lambda *a, **k: None)

    with pytest.raises(runner.RunnerError, match="exited 1"):
        runner.run_opencode_turn(
            tmp_path, "write the article", {"builder": {"timeout_seconds": 30}},
            reply_mode="final_message",
        )


def test_a_finished_turn_with_no_text_still_fails(monkeypatch, tmp_path):
    """A step that claims to stop without saying anything is not an answer."""
    _install(monkeypatch, [
        _tool("msg_a", "read", "completed"),
        _step("msg_a", "stop"),
    ], returncode=1)
    monkeypatch.setattr(runner, "_persist_turn_failure", lambda *a, **k: None)

    with pytest.raises(runner.RunnerError, match="exited 1"):
        runner.run_opencode_turn(
            tmp_path, "write the article", {"builder": {"timeout_seconds": 30}},
            reply_mode="final_message",
        )


def test_a_terminal_error_after_a_finished_step_still_fails(monkeypatch, tmp_path):
    """An explicit provider error is never overridden by an earlier stop."""
    _install(monkeypatch, [
        _text("msg_a", "Working."),
        _step("msg_a", "stop"),
        {"type": "error", "error": {"type": "provider.unavailable", "message": "no route"}},
    ], returncode=1)
    monkeypatch.setattr(runner, "_persist_turn_failure", lambda *a, **k: None)

    with pytest.raises(runner.RunnerError):
        runner.run_opencode_turn(
            tmp_path, "write the article", {"builder": {"timeout_seconds": 30}},
            reply_mode="final_message",
        )


def test_the_generated_project_config_pins_the_websearch_provider(tmp_path):
    """Unpinned, the CLI asks the client, which a headless turn cannot answer."""
    runner.install_agent_files(
        tmp_path, None, "openrouter/deepseek/deepseek-v4.1-flash", "key",
        websearch_provider="tinyfish",
    )

    config = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert config["websearch"] == {"provider": "tinyfish"}
    assert config["permission"]["websearch"] == "allow"


def test_the_generated_project_config_omits_websearch_when_no_provider_is_configured(tmp_path):
    runner.install_agent_files(
        tmp_path, None, "openrouter/deepseek/deepseek-v4.1-flash", "key",
        websearch_provider="",
    )

    config = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert "websearch" not in config
