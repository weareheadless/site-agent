from __future__ import annotations

from pathlib import Path

import site_agent.application.email_bootstrap as bootstrap


class FakeMemory:
    def __init__(self, state=None):
        self.state = dict(state or {})

    def kv_get(self, key, default=None):
        return self.state.get(key, default)

    def kv_set(self, key, value):
        self.state[key] = value


def _config(tmp_path: Path):
    return {
        "data_dir": str(tmp_path / "data"),
        "display_name": "OceanicVibes",
        "site": {
            "custom_domain": "oceanicvibes.com",
            "public_url": "https://oceanicvibes.com/",
            "preview_url": "https://oceanicvibes.workers.dev",
            "source_deployment": {"worker_name": "oceanicvibes"},
        },
        "messages": {"email": {"enabled": True, "local_part": "contact", "provisioning": {"auto": True}}},
    }


def test_email_bootstrap_is_not_enabled_implicitly_for_existing_tenants(monkeypatch, tmp_path):
    config = _config(tmp_path)
    config["messages"]["email"]["enabled"] = False
    memory = FakeMemory()
    monkeypatch.setattr(bootstrap, "prepare_email_plan", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not call provider")))

    state, _ = bootstrap.auto_provision_email(config, tenant_id="oceanicvibes", memory=memory, env={})

    assert state["state"] == "disabled"
    assert memory.state["email_provisioning_state"]["state"] == "disabled"


def test_prepare_plan_derives_mailbox_from_current_domain_and_local_part(monkeypatch, tmp_path):
    config = _config(tmp_path)
    config["messages"]["email"]["address"] = "stale@former-domain.test"
    seen = {}

    monkeypatch.setattr(bootstrap, "_worker_readiness", lambda config, tenant: ("oceanicvibes", ""))
    monkeypatch.setattr(bootstrap, "cloudflare_api_token", lambda config, env: "cf-token")

    class Client:
        def __init__(self, token):
            assert token == "cf-token"

        def zone(self, hostname):
            assert hostname == "oceanicvibes.com"
            return {"name": "oceanicvibes.com"}

    class Service:
        def __init__(self, client):
            pass

        def plan(self, tenant, policy):
            seen.update(tenant=tenant, policy=policy)
            return {"tenant": tenant, "domain": policy["domain"], "address": policy["address"], "snapshot": {}, "snapshotSha256": "abc", "operations": []}

    monkeypatch.setattr(bootstrap, "CloudflareEmailClient", Client)
    monkeypatch.setattr(bootstrap, "EmailProvisioningService", Service)

    plan, policy, _ = bootstrap.prepare_email_plan(config, tenant_id="oceanicvibes", env={})

    assert plan["address"] == "contact@oceanicvibes.com"
    assert policy["address"] == "contact@oceanicvibes.com"
    assert seen["tenant"] == "oceanicvibes"


def test_prepare_plan_uses_managed_zone_apex_for_a_www_site(monkeypatch, tmp_path):
    config = _config(tmp_path)
    config["site"]["custom_domain"] = "www.oceanicvibes.com"
    seen = {}

    monkeypatch.setattr(bootstrap, "_worker_readiness", lambda config, tenant: ("oceanicvibes", ""))
    monkeypatch.setattr(bootstrap, "cloudflare_api_token", lambda config, env: "cf-token")

    class Client:
        def __init__(self, token):
            pass

        def zone(self, hostname):
            assert hostname == "www.oceanicvibes.com"
            return {"name": "oceanicvibes.com"}

    class Service:
        def __init__(self, client):
            pass

        def plan(self, tenant, policy):
            seen.update(tenant=tenant, policy=policy)
            return {"tenant": tenant, "domain": policy["domain"], "address": policy["address"], "snapshot": {}, "snapshotSha256": "abc", "operations": []}

    monkeypatch.setattr(bootstrap, "CloudflareEmailClient", Client)
    monkeypatch.setattr(bootstrap, "EmailProvisioningService", Service)

    plan, policy, _ = bootstrap.prepare_email_plan(config, tenant_id="oceanicvibes", env={})

    assert plan["domain"] == "oceanicvibes.com"
    assert plan["address"] == "contact@oceanicvibes.com"
    assert policy["domain"] == "oceanicvibes.com"


def test_failed_payload_activation_preserves_cloudflare_progress_for_retry(monkeypatch, tmp_path):
    config = _config(tmp_path)
    memory = FakeMemory()
    plan = {
        "tenant": "oceanicvibes", "domain": "oceanicvibes.com", "address": "contact@oceanicvibes.com",
        "worker": "oceanicvibes", "snapshotSha256": "preflight-hash", "operations": [],
    }
    policy = {"domain": "oceanicvibes.com", "address": "contact@oceanicvibes.com", "worker": "oceanicvibes"}
    monkeypatch.setattr(bootstrap, "prepare_email_plan", lambda *args, **kwargs: (plan, policy, {"PROVISIONED_OCEANICVIBES_TOKEN": "worker-token"}))
    monkeypatch.setattr(bootstrap, "tenant_token_env", lambda tenant: "PROVISIONED_OCEANICVIBES_TOKEN")
    monkeypatch.setattr(bootstrap, "cloudflare_api_token", lambda config, env: "cf-token")

    class Client:
        def __init__(self, token):
            pass

    class Service:
        def __init__(self, client):
            pass

        def provision(self, plan, policy):
            return {"zoneId": "zone-id", "sendingDomainId": "sending-id", "routingRuleId": "rule-id", "routingStatus": "ready"}

    monkeypatch.setattr(bootstrap, "CloudflareEmailClient", Client)
    monkeypatch.setattr(bootstrap, "EmailProvisioningService", Service)
    monkeypatch.setattr(bootstrap, "_configure_payload_mailbox", lambda *args, **kwargs: (_ for _ in ()).throw(bootstrap.EmailProvisioningError("Payload timeout")))

    state, _ = bootstrap.auto_provision_email(config, tenant_id="oceanicvibes", memory=memory, env={})

    assert state["state"] == "failed"
    assert state["cloudflareRouteId"] == "rule-id"
    assert "Payload timeout" in state["error"]
    assert memory.state["email_provisioning_state"]["cloudflareRouteId"] == "rule-id"
