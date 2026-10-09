from __future__ import annotations

import json
import os
from argparse import Namespace
from pathlib import Path

import yaml

import site_agent.main as main


def _registered_tenant(tmp_path: Path):
    root = tmp_path / "websites"
    tenant_dir = root / "demo"
    tenant_dir.mkdir(parents=True)
    data_dir = tenant_dir / "data"
    config_path = tenant_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "instance_name": "demo",
        "data_dir": str(data_dir),
        "site": {
            "custom_domain": "demo.example",
            "public_url": "https://demo.example/",
            "preview_url": "https://demo.workers.dev",
            "source_deployment": {"worker_name": "demo"},
        },
    }), encoding="utf-8")
    (tenant_dir / "tenant.env").write_text("PROVISIONED_DEMO_TOKEN=registered-token\n", encoding="utf-8")
    (root / "tenants.json").write_text(json.dumps({
        "demo": {"config_path": str(config_path), "api_token_env": "PROVISIONED_DEMO_TOKEN"},
    }), encoding="utf-8")
    host = tmp_path / "host.yaml"
    host.write_text(yaml.safe_dump({
        "data_dir": str(tmp_path / "host-data"),
        "workspace_api": {"enabled": True, "provisioned_root": str(root), "tenants": {}},
    }), encoding="utf-8")
    return host, config_path, data_dir


def _args(config_path: Path, *, apply: bool, email_domain: str = "", local_part: str = ""):
    return Namespace(
        config=str(config_path),
        tenant="demo",
        apply=apply,
        email_domain=email_domain,
        local_part=local_part,
        approve_mailgun_cutover=False,
        allow_forwarding_cutover=False,
    )


def test_email_cli_defaults_to_read_only_and_uses_registered_tenant_only(monkeypatch, tmp_path, capsys):
    host, _config_path, _data_dir = _registered_tenant(tmp_path)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cloudflare-test-token")
    private = "owner-private@example.net"
    plan = {
        "tenant": "demo", "domain": "demo.example", "address": "hello@demo.example", "worker": "demo",
        "snapshotSha256": "preflight-hash", "operations": ["route hello@demo.example to the registered Worker"],
        "snapshot": {"existingMailboxRule": {"actions": [{"type": "forward", "value": [private]}]}},
    }
    from site_agent.application import email_bootstrap
    monkeypatch.setattr(email_bootstrap, "prepare_email_plan", lambda *args, **kwargs: (plan, {}, {}))

    code = main._cmd_provision_email(_args(host, apply=False))

    output = capsys.readouterr().out
    assert code == 0
    assert "plan_only" in output
    assert private not in output
    assert not (tmp_path / "websites/demo/data/email-provisioning").exists()


def test_email_cli_apply_saves_protected_before_state_and_sanitizes_output(monkeypatch, tmp_path, capsys):
    host, config_path, data_dir = _registered_tenant(tmp_path)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cloudflare-test-token")
    private = "owner-private@example.net"
    plan = {
        "tenant": "demo", "domain": "demo.example", "address": "hello@demo.example", "worker": "demo",
        "snapshotSha256": "preflight-hash", "operations": ["route hello@demo.example to the registered Worker"],
        "snapshot": {"existingMailboxRule": {"id": "old-rule", "actions": [{"type": "forward", "value": [private]}]}},
    }
    from site_agent.application import email_bootstrap
    captured = {}

    def prepare(*args, **kwargs):
        captured.update(kwargs)
        return plan, {}, {}

    monkeypatch.setattr(email_bootstrap, "prepare_email_plan", prepare)

    def apply(config, *, tenant_id, tenant_config_path, memory, env, policy_overrides, expected_snapshot_sha256):
        assert tenant_config_path == config_path
        assert expected_snapshot_sha256 == "preflight-hash"
        return {"state": "active", "tenant": tenant_id, "domain": "demo.example", "address": "hello@demo.example", "completedAt": "2026-10-04T00:00:00+00:00"}, env

    monkeypatch.setattr(email_bootstrap, "auto_provision_email", apply)
    code = main._cmd_provision_email(_args(
        host,
        apply=True,
        email_domain="demo.example",
        local_part="hello",
    ))

    output = capsys.readouterr().out
    result = json.loads(output)
    assert code == 0
    assert private not in output
    assert result["state"] == "active"
    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert updated["messages"]["email"]["enabled"] is True
    assert updated["messages"]["email"]["domain"] == "demo.example"
    assert updated["messages"]["email"]["local_part"] == "hello"
    assert updated["messages"]["email"]["provisioning"]["auto"] is True
    assert captured["policy_overrides"]["emailDomain"] == "demo.example"
    assert captured["policy_overrides"]["localPart"] == "hello"
    receipt_path = Path(result["receiptPath"])
    assert receipt_path.is_file()
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert receipt_path.parent.stat().st_mode & 0o777 == 0o700
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["preflightSnapshot"]["existingMailboxRule"]["actions"][0]["value"] == [private]
    assert receipt["preflightSha256"] == "preflight-hash"
    assert (data_dir / "memory.db").exists()
