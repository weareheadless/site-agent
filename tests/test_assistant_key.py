"""Visitor assistant key provisioning: isolation, atomicity and secret hygiene."""
from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from site_agent.application import assistant_key  # noqa: E402
from site_agent.senses import openrouter  # noqa: E402


def _tenant_env(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "tenant.env"
    path.write_text(
        "PAYLOAD_SECRET=payload-secret\n"
        "PROVISIONED_OCEANIC_TOKEN=worker-token\n"
        f"{extra}",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _transport(existing=None):
    calls: list[tuple[str, str, bytes | None]] = []
    state = {"existing": list(existing or [])}

    def send(method, url, headers, body):
        calls.append((method, url, body))
        if method == "GET":
            return 200, json.dumps({"data": state["existing"]}).encode("utf-8")
        payload = json.loads(body.decode("utf-8"))
        created = f"sk-or-v1-{payload['name']}-secret"
        state["existing"].append({"name": payload["name"], "limit": payload["limit"], "hash": "hash"})
        return 200, json.dumps({"key": created, "data": {"name": payload["name"]}}).encode("utf-8")

    return send, calls


def test_plan_creates_when_the_provider_has_no_key(tmp_path: Path) -> None:
    env_path = _tenant_env(tmp_path)
    transport, calls = _transport()

    summary = assistant_key.plan("oceanic", env_path, limit_usd=5, token="mgmt",
                       token_env="PROVISIONED_OCEANIC_TOKEN", transport=transport)

    assert summary["action"] == "create"
    assert summary["keyName"] == "site-agent:oceanic"
    assert summary["providerKey"]["exists"] is False
    assert [call[0] for call in calls] == ["GET"]
    assert env_path.read_text(encoding="utf-8").count("HELLOADA_ASSISTANT_KEY") == 0


def test_plan_refuses_an_unregistered_tenant_environment(tmp_path: Path) -> None:
    env_path = tmp_path / "tenant.env"
    env_path.write_text("PAYLOAD_SECRET=only-half\n", encoding="utf-8")
    transport, _calls = _transport()

    with pytest.raises(assistant_key.AssistantKeyError):
        assistant_key.plan("oceanic", env_path, limit_usd=5, token="mgmt",
                       token_env="PROVISIONED_OCEANIC_TOKEN", transport=transport)


def test_plan_refuses_duplicate_provider_keys(tmp_path: Path) -> None:
    env_path = _tenant_env(tmp_path)
    transport, _calls = _transport([
        {"name": "site-agent:oceanic", "limit": 5},
        {"name": "site-agent:oceanic", "limit": 9},
    ])

    with pytest.raises(assistant_key.AssistantKeyError):
        assistant_key.plan("oceanic", env_path, limit_usd=5, token="mgmt",
                       token_env="PROVISIONED_OCEANIC_TOKEN", transport=transport)


def test_apply_stages_the_key_without_disturbing_the_rest_of_the_environment(tmp_path: Path) -> None:
    env_path = _tenant_env(tmp_path, extra="RESEND_API_KEY=resend\n")

    summary = assistant_key.apply("oceanic", env_path, limit_usd=5, token="mgmt",
                        token_env="PROVISIONED_OCEANIC_TOKEN", transport=_transport()[0])

    assert summary["action"] == "created"
    assert summary["staged"] is True
    text = env_path.read_text(encoding="utf-8")
    assert "PAYLOAD_SECRET=payload-secret" in text
    assert "RESEND_API_KEY=resend" in text
    assert "HELLOADA_ASSISTANT_KEY=sk-or-v1-site-agent:oceanic-secret" in text
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_apply_reuses_an_existing_key_and_needs_no_release(tmp_path: Path) -> None:
    env_path = _tenant_env(tmp_path)
    transport, calls = _transport([{"name": "site-agent:oceanic", "limit": 5, "usage": 1.25}])

    summary = assistant_key.apply("oceanic", env_path, limit_usd=5, token="mgmt",
                        token_env="PROVISIONED_OCEANIC_TOKEN", transport=transport)

    assert summary["action"] == "reuse"
    assert summary["staged"] is False
    assert summary["providerKey"]["usage"] == 1.25
    assert [call[0] for call in calls] == ["GET"]


def test_receipt_never_contains_the_key(tmp_path: Path) -> None:
    env_path = _tenant_env(tmp_path)
    summary = assistant_key.apply("oceanic", env_path, limit_usd=5, token="mgmt",
                        token_env="PROVISIONED_OCEANIC_TOKEN", transport=_transport()[0])
    staged = env_path.read_text(encoding="utf-8")

    path = assistant_key.write_receipt(tmp_path / "tenant", "oceanic", summary)
    receipt = path.read_text(encoding="utf-8")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "sk-or-v1" not in receipt
    assert "sk-or-v1-site-agent:oceanic-secret" in staged


def test_management_call_refuses_a_missing_credential() -> None:
    with pytest.raises(openrouter.OpenRouterError):
        openrouter.list_keys("")
