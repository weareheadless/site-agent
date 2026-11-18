import json

import pytest

from site_agent.hands import opencode_runner as runner


def test_frozen_profile_does_not_replace_the_configured_credential_source():
    from types import SimpleNamespace
    from site_agent.core.design_contracts import canonical_hash
    from site_agent.config import resolve_secret

    quality = {"browser_required": False}
    request = SimpleNamespace(context_snapshot=SimpleNamespace(execution_profile={
        "model": "deepseek/deepseek-v4.1-flash-1017", "provider": "openrouter",
        "provider_env_name": "OPENROUTER_API_KEY", "build_profile": "next_react",
        "quality_policy": {**quality, "hash": canonical_hash(quality)},
    }))
    config = {"env": {"llm_api_key": "SITE_AGENT_LLM_API_KEY"}}
    projected = runner._typed_execution_config(config, request, SimpleNamespace(build_profile="next_react"))
    assert projected["design_engine"]["api_key_env"] == "OPENROUTER_API_KEY"
    assert projected["env"]["llm_api_key"] == "SITE_AGENT_LLM_API_KEY"
    assert resolve_secret(projected, "llm_api_key", {"SITE_AGENT_LLM_API_KEY": "selected-key"}) == "selected-key"


def rejection(kind="provider.no-route"):
    return runner.RunnerError("opencode exited 1: ", result={
        "transcript": json.dumps({"type": "error", "error": {"type": kind, "message": "temporarily unavailable"}}),
        "tool_calls": [], "usage": {"prompt_tokens": 0, "completion_tokens": 0},
    })


def test_standalone_diagnostic_logs_do_not_hide_a_pre_generation_rejection():
    failure = rejection()
    failure.result["transcript"] = (
        'timestamp=2026-10-31T23:06:52Z level=ERROR message="watcher backend not supported" role=server\n'
        + failure.result["transcript"]
        + '\ntimestamp=2026-10-31T23:06:54Z level=INFO message="watcher stopped" role=server'
    )
    assert runner._retryable_provider_rejection(failure.result) == "provider.no-route"
    failure.result["transcript"] += '\npartial model output'
    assert runner._retryable_provider_rejection(failure.result) == ""


def test_provider_rejection_retries_same_request_with_bounded_backoff(monkeypatch, tmp_path):
    calls, waits = [], []
    def turn(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) < 3:
            raise rejection()
        return {"reply": "completed"}
    monkeypatch.setattr(runner, "_run_opencode_turn_once", turn)
    monkeypatch.setattr(runner.time, "sleep", waits.append)
    result = runner.run_opencode_turn(tmp_path, "request", {}, agent_name="native-direction")
    assert result["reply"] == "completed"
    assert len(result["provider_retry_attempts"]) == 2
    assert len(calls) == 3 and calls[0] == calls[1] == calls[2]
    assert waits == [2, 5]


def test_persistent_rejection_stops_after_three_attempts_and_preserves_evidence(monkeypatch, tmp_path):
    calls, waits = [], []
    def turn(*args, **kwargs):
        calls.append(True)
        raise rejection()
    monkeypatch.setattr(runner, "_run_opencode_turn_once", turn)
    monkeypatch.setattr(runner.time, "sleep", waits.append)
    with pytest.raises(runner.RunnerError) as error:
        runner.run_opencode_turn(tmp_path, "request", {})
    assert len(calls) == 3 and waits == [2, 5]
    assert len(error.value.result["provider_retry_attempts"]) == 3
    assert "provider.no-route" in str(error.value)


@pytest.mark.parametrize("case", ["auth", "timeout", "tool", "usage", "text"])
def test_ambiguous_or_non_retryable_failure_is_not_replayed(monkeypatch, tmp_path, case):
    failure = rejection("provider.auth" if case == "auth" else "provider.no-route")
    if case == "timeout":
        failure = runner.RunnerError("opencode timed out after 60s", result={})
    elif case == "tool":
        failure.result["tool_calls"] = [{"tool": "patch"}]
    elif case == "usage":
        failure.result["usage"]["completion_tokens"] = 1
    elif case == "text":
        failure.result["transcript"] += '\n' + json.dumps({"type": "text", "part": {"text": "partial answer"}})
    calls = []
    def turn(*args, **kwargs):
        calls.append(True)
        raise failure
    monkeypatch.setattr(runner, "_run_opencode_turn_once", turn)
    monkeypatch.setattr(runner.time, "sleep", lambda _: pytest.fail("must not back off"))
    with pytest.raises(runner.RunnerError):
        runner.run_opencode_turn(tmp_path, "request", {})
    assert len(calls) == 1


def test_a_text_tool_call_retries_once_on_a_native_tool_model(tmp_path, monkeypatch):
    """DSML in a text event is a provider protocol failure, not a dead task."""
    from site_agent.hands import opencode_runner as runner

    calls = []

    def fake_once(clone, brief, config, **kwargs):
        calls.append({"brief": brief, "model": kwargs.get("model_override"), "session": kwargs.get("session_id")})
        if len(calls) == 1:
            raise runner.RunnerError(
                "opencode emitted unsupported DSML/XML instead of a native tool call: <tool",
                result={"session_id": "ses_protocol"},
            )
        return {"reply": "done", "session_id": "ses_ok"}

    monkeypatch.setattr(runner, "_run_opencode_turn_once", fake_once)
    config = {"builder": {"model": "openrouter/deepseek/deepseek-v4.1-flash"}}

    result = runner.run_opencode_turn(tmp_path, "wire the widget", config)

    assert result["reply"] == "done"
    assert len(calls) == 2
    assert calls[0]["model"] is None
    assert calls[1]["model"] == runner._PROTOCOL_FALLBACK_MODEL
    assert "native tool calls" in calls[1]["brief"]
    # A protocol failure is not an interrupted turn: it must not resume the session.
    assert calls[1]["session"] is None


def test_a_second_protocol_failure_is_reported_not_looped(tmp_path, monkeypatch):
    from site_agent.hands import opencode_runner as runner

    calls = []

    def always_dsml(clone, brief, config, **kwargs):
        calls.append(1)
        raise runner.RunnerError(
            "opencode emitted unsupported DSML/XML instead of a native tool call: <tool",
            result={},
        )

    monkeypatch.setattr(runner, "_run_opencode_turn_once", always_dsml)

    with pytest.raises(runner.RunnerError, match="cannot call tools reliably"):
        runner.run_opencode_turn(tmp_path, "brief", {"builder": {}})
    assert len(calls) == 2
