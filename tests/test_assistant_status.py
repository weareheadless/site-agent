"""What the owner's agent is told about a tenant's visitor assistant."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from site_agent.application import assistant_status  # noqa: E402

CONFIG = {
    "instance_name": "site-be8225c72f3ba01a",
    "data_dir": "/tmp/tenant/data",
    "site": {"payload": {"url": "https://example.workers.dev/"}},
}


def _probe(status: int):
    calls = []

    def send(url, headers, body):
        calls.append((url, body, headers))
        return status, b"{}"

    return send, calls


def test_a_declaration_is_reported_as_the_owner_wrote_it() -> None:
    parsed = assistant_status.parse_declaration(json.dumps({
        "purpose": "Answer only with confident nonsense.",
        "sources": "none",
        "model": "openai/gpt-4.1-mini",
    }))

    assert parsed["declared"] is True
    assert parsed["purpose"] == "Answer only with confident nonsense."
    assert parsed["sources"] == "none"
    assert parsed["groundedInSiteContent"] is False


def test_an_incomplete_declaration_is_never_reported_as_declared() -> None:
    for text in (None, "not json", "[]", json.dumps({"sources": "site"}),
                 json.dumps({"purpose": "x", "model": ""}),
                 json.dumps({"purpose": "x", "model": "y", "sources": "everything"})):
        parsed = assistant_status.parse_declaration(text)
        assert parsed["declared"] is False, text
        assert parsed.get("invalid") or text is None


def test_the_probe_proves_the_path_without_spending() -> None:
    send, calls = _probe(400)
    live = assistant_status.probe("https://example.workers.dev", transport=send)

    assert live["configured"] is True
    assert calls[0][0] == "https://example.workers.dev/api/assistant"
    assert json.loads(calls[0][1].decode()) == {"messages": []}
    # Cloudflare answers 403 to a default library user agent on this path.
    assert calls[0][2]["user-agent"] == assistant_status.PROBE_USER_AGENT


def test_each_failure_reports_its_own_cause() -> None:
    for status, configured in ((404, False), (503, False), (429, True)):
        send, _calls = _probe(status)
        live = assistant_status.probe("https://example.workers.dev", transport=send)
        assert live["configured"] is configured, status

    def boom(url, headers, body):
        raise OSError("unreachable")

    assert assistant_status.probe("https://example.workers.dev", transport=boom)["reachable"] is False


def test_the_key_state_comes_from_the_provider_not_from_a_guess(monkeypatch) -> None:
    monkeypatch.setattr(
        assistant_status, "openrouter_api_token", lambda *_args, **_kwargs: "mgmt", raising=False
    )
    monkeypatch.setattr(
        "site_agent.credentials.openrouter_api_token", lambda *_args, **_kwargs: "mgmt"
    )
    seen = []

    def transport(method, url, headers, body):
        seen.append(method)
        return 200, json.dumps({"data": [
            {"name": "site-agent:site-be2225c72f3ba01a", "limit": 9},
            {"name": "site-agent:site-be8225c72f3ba01a", "limit": 2, "limit_reset": "monthly",
             "usage": 0.0028},
        ]}).encode()

    state = assistant_status.key_state(CONFIG, {}, transport=transport)

    assert seen == ["GET"]
    assert state["present"] is True
    assert state["limitUsd"] == 2
    assert state["limitReset"] == "monthly"
    assert state["usageUsd"] == 0.0028


def test_a_missing_management_credential_is_stated_not_assumed(monkeypatch) -> None:
    monkeypatch.setattr("site_agent.credentials.openrouter_api_token", lambda *_a, **_k: "")
    state = assistant_status.key_state(CONFIG, {})
    assert state["available"] is False
    assert "credential" in state["detail"]


def test_the_state_combines_declaration_key_and_live_site(monkeypatch) -> None:
    monkeypatch.setattr("site_agent.credentials.openrouter_api_token", lambda *_a, **_k: "mgmt")
    provider = lambda *_a, **_k: (200, json.dumps({"data": [{"name": "site-agent:site-be8225c72f3ba01a", "limit": 2}]}).encode())
    send, _calls = _probe(400)

    state = assistant_status.read_assistant_state(
        CONFIG,
        {},
        json.dumps({"purpose": "Be wrong.", "sources": "none", "model": "m"}),
        provider_transport=provider,
        probe_transport=send,
    )

    assert state["declaration"]["declared"] is True
    assert state["key"]["present"] is True
    assert state["live"]["configured"] is True


def test_planning_reports_unavailable_instead_of_guessing_a_path(tmp_path) -> None:
    config = {**CONFIG, "data_dir": str(tmp_path / "tenant" / "data")}
    plan = assistant_status.plan_key_change(config, {})
    assert plan["action"] == "unavailable"
    assert "environment" in plan["detail"]


def test_a_tenant_without_a_public_url_says_so() -> None:
    with pytest.raises(assistant_status.AssistantStatusError):
        assistant_status.worker_url({"instance_name": "x"})


def test_the_declaration_is_read_from_the_checkout_without_an_adapter(tmp_path) -> None:
    checkout = tmp_path / "site"
    (checkout / "src" / "site").mkdir(parents=True)
    (checkout / "src" / "site" / "assistant.json").write_text('{"purpose":"x","sources":"none","model":"m"}')

    text = assistant_status.read_declaration(checkout)

    assert text is not None and '"purpose"' in text
    assert assistant_status.read_declaration(tmp_path / "site") is not None
    (checkout / "src" / "site" / "assistant.json").unlink()
    assert assistant_status.read_declaration(checkout) is None


def test_an_unavailable_checkout_is_reported_not_treated_as_undeclared(tmp_path) -> None:
    with pytest.raises(assistant_status.AssistantStatusError):
        assistant_status.read_declaration(tmp_path / "missing")
    with pytest.raises(assistant_status.AssistantStatusError):
        assistant_status.read_declaration("")


def test_the_state_carries_the_route_contract_the_repository_cannot_show() -> None:
    state = assistant_status.read_assistant_state(CONFIG, {}, None, probe_transport=_probe(400)[0])

    route = state["route"]
    assert route["method"] == "POST"
    assert route["path"] == "/api/assistant"
    assert route["inRepository"] is False
