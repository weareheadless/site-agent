from __future__ import annotations

import json
from pathlib import Path

import yaml

import site_agent.main as main


def _registered_fleet(tmp_path: Path):
    """Two tenants with different mailbox histories, plus one with no mailbox."""
    root = tmp_path / "websites"
    specs: dict[str, dict[str, str]] = {}
    tenants = {
        # A tenant whose custom domain was registered after the platform address.
        "astrid": {
            "custom_domain": "astridrincon.com",
            "worker": "helloada-site-astridrincon",
            "email": {"enabled": True, "domain": "astridrincon.com", "local_part": "hello"},
        },
        # A tenant still on the platform domain.
        "casamigo": {
            "custom_domain": "casamigo.net",
            "worker": "helloada-casamigo",
            "email": {"enabled": True, "domain": "helloada.app", "local_part": "casamigo"},
        },
        # A registered tenant whose mailbox was never configured.
        "unconfigured": {
            "custom_domain": "",
            "worker": "helloada-unconfigured",
            "email": {},
        },
    }
    for tenant_id, spec in tenants.items():
        tenant_dir = root / tenant_id
        tenant_dir.mkdir(parents=True)
        config: dict[str, object] = {
            "instance_name": tenant_id,
            "data_dir": str(tenant_dir / "data"),
            "site": {
                "custom_domain": spec["custom_domain"],
                "source_deployment": {"worker_name": spec["worker"]},
            },
        }
        if spec["email"]:
            config["messages"] = {"email": spec["email"]}
        (tenant_dir / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        specs[tenant_id] = {
            "config_path": str(tenant_dir / "config.yaml"),
            "api_token_env": f"PROVISIONED_{tenant_id.upper()}_TOKEN",
        }
        (tenant_dir / "tenant.env").write_text(
            f"PROVISIONED_{tenant_id.upper()}_TOKEN=token-{tenant_id}\n", encoding="utf-8"
        )
    (root / "tenants.json").write_text(json.dumps(specs), encoding="utf-8")
    host = tmp_path / "host.yaml"
    host.write_text(yaml.safe_dump({
        "data_dir": str(tmp_path / "host-data"),
        "workspace_api": {"enabled": True, "provisioned_root": str(root), "tenants": {}},
    }), encoding="utf-8")
    return host, root


class _FakeZone:
    def __init__(self, hostname):
        self._hostname = hostname

    def zone(self, name):
        if name.endswith("helloada.app") or name == "helloada.app":
            return {"id": "zone-platform", "name": "helloada.app"}
        if name == "astridrincon.com":
            return {"id": "zone-astrid", "name": "astridrincon.com"}
        raise RuntimeError("zone not visible")

    def routing_rules(self, zone_id):
        return list(self._rules.get(zone_id, []))

    _rules = {
        "zone-platform": [
            {
                "id": "casamigo",
                "enabled": True,
                "matchers": [{"type": "literal", "field": "to", "value": "casamigo@helloada.app"}],
                "actions": [{"type": "worker", "value": ["helloada-casamigo"]}],
            },
            {
                "id": "astrid-alias",
                "enabled": True,
                "matchers": [{"type": "literal", "field": "to", "value": "site-ff8e9af06f56201f@helloada.app"}],
                "actions": [{"type": "worker", "value": ["helloada-site-ff8e9af06f56201f"]}],
            },
        ],
        "zone-astrid": [
            {
                "id": "astrid",
                "enabled": True,
                "matchers": [{"type": "literal", "field": "to", "value": "hello@astridrincon.com"}],
                "actions": [{"type": "worker", "value": ["helloada-site-astridrincon"]}],
            },
        ],
    }


def _install_fakes(monkeypatch):
    import site_agent.application.email_routing_fleet as fleet
    import site_agent.hands.cloudflare_email as email_hand

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a" * 32)
    for name in ("cloudflare_api_token", "cloudflare_dns_api_token", "cloudflare_email_api_token"):
        monkeypatch.setattr(main, name, lambda *a, **k: "token", raising=False)
    monkeypatch.setattr(email_hand, "CloudflareEmailClient", lambda *a, **k: _FakeZone("z"))
    # No mailbox database in this fixture: alias discovery is exercised in the
    # application tests; here the shape is the registered address plus config.
    monkeypatch.setattr(fleet, "_d1_aliases", lambda *a, **k: [])
    monkeypatch.setattr(fleet, "_worker_exists", lambda *a, **k: True)


def test_the_plan_reports_every_tenant_and_changes_nothing(monkeypatch, tmp_path, capsys):
    host, _root = _registered_fleet(tmp_path)
    _install_fakes(monkeypatch)
    assert main.main(["reconcile-email-routing", "--config", str(host)]) == 0
    out = capsys.readouterr().out
    assert "Read-only plan only" in out
    # The unconfigured tenant is named, not silently treated as fine.
    assert "unconfigured" in out
    assert "no_registered_address" in out


def test_the_json_plan_carries_tenants_attention_and_no_writes(monkeypatch, tmp_path, capsys):
    host, _root = _registered_fleet(tmp_path)
    _install_fakes(monkeypatch)
    before = json.loads(json.dumps(_FakeZone._rules))
    assert main.main(["reconcile-email-routing", "--config", str(host), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "plan_only"
    assert result["state"] == "planned"
    assert result["tenants"] == 2, "two tenants have a registered address"
    required = {item["tenantId"]: item["reason"] for item in result["actionRequired"]}
    assert required == {"unconfigured": "no_registered_address"}
    # A plan is read-only: the live rule table is untouched.
    assert _FakeZone._rules == before


def test_a_tenant_whose_zone_is_not_visible_is_reported_not_skipped(monkeypatch, tmp_path, capsys):
    host, _root = _registered_fleet(tmp_path)
    _install_fakes(monkeypatch)
    class Partial(_FakeZone):
        def zone(self, name):
            if name == "astridrincon.com":
                raise RuntimeError("not visible to this credential")
            return super().zone(name)

    monkeypatch.setattr(main, "CloudflareEmailClient", lambda *a, **k: Partial("z"), raising=False)
    monkeypatch.setattr(
        "site_agent.hands.cloudflare_email.CloudflareEmailClient", lambda *a, **k: Partial("z")
    )
    assert main.main(["reconcile-email-routing", "--config", str(host), "--json"]) in {0, 1}
    result = json.loads(capsys.readouterr().out)
    problems = {item["tenantId"]: item["reason"] for item in result["actionRequired"]}
    assert problems.get("astrid") == "zone_unavailable"
