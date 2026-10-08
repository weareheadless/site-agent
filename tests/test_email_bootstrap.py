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
            "preview_url": "https://oceanicvibes.weareheadless.workers.dev",
            "source_deployment": {"worker_name": "oceanicvibes"},
        },
        "messages": {"email": {"enabled": True, "local_part": "contact", "provisioning": {"auto": True}}},
    }


def test_worker_readiness_uses_registered_public_origin(monkeypatch, tmp_path):
    config = _config(tmp_path)
    config["site"]["preview_url"] = "https://oceanicvibes.weareheadless.workers.dev/"
    expected = "https://oceanicvibes.com"

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size=-1):
            return bootstrap.json.dumps({
                "ok": True,
                "tenant": "oceanicvibes",
                "contentContract": "helloada-content-v3",
                "emailProvisioningVersion": 1,
            }).encode()

    def urlopen(request, timeout):
        assert request.full_url == expected + "/api/health"
        assert timeout == 12
        return Response()

    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", urlopen)
    worker, error = bootstrap._worker_readiness(config, "oceanicvibes")

    assert worker == "oceanicvibes"
    assert error == ""


def test_worker_readiness_rejects_a_public_origin_outside_the_registered_domain(monkeypatch, tmp_path):
    config = _config(tmp_path)
    config["site"]["public_url"] = "https://different.example/"
    monkeypatch.setattr(
        bootstrap.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must reject before health request")),
    )

    worker, error = bootstrap._worker_readiness(config, "oceanicvibes")

    assert worker == ""
    assert "tenant's custom domain" in error


def test_worker_readiness_uses_exact_account_qualified_origin_without_custom_domain(monkeypatch, tmp_path):
    config = _config(tmp_path)
    config["site"].pop("custom_domain")
    config["site"]["public_url"] = "https://atelier-harmonie.weareheadless.workers.dev/"
    expected = "https://atelier-harmonie.weareheadless.workers.dev"
    import site_agent.application.worker_origin as worker_origin

    monkeypatch.setattr(worker_origin, "canonical_worker_preview_url", lambda *_args: expected)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size=-1):
            return bootstrap.json.dumps({
                "ok": True,
                "tenant": "oceanicvibes",
                "contentContract": "helloada-content-v3",
                "emailProvisioningVersion": 1,
            }).encode()

    def urlopen(request, timeout):
        assert request.full_url == expected + "/api/health"
        assert timeout == 12
        return Response()

    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", urlopen)
    worker, error = bootstrap._worker_readiness(config, "oceanicvibes", {})

    assert worker == "oceanicvibes"
    assert error == ""


def test_payload_mailbox_configuration_uses_registered_public_origin(monkeypatch, tmp_path):
    config = _config(tmp_path)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size=-1):
            return bootstrap.json.dumps({
                "state": "active",
                "domain": "oceanicvibes.com",
                "address": "contact@oceanicvibes.com",
            }).encode()

    def urlopen(request, timeout):
        assert request.full_url == "https://oceanicvibes.com/api/helloada/internal/messages/configure-mailbox"
        assert request.get_method() == "POST"
        assert timeout == 20
        return Response()

    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", urlopen)
    result = bootstrap._configure_payload_mailbox(
        config,
        tenant_id="oceanicvibes",
        token="tenant-token",
        domain="oceanicvibes.com",
        address="contact@oceanicvibes.com",
    )

    assert result == {"state": "active", "domain": "oceanicvibes.com", "address": "contact@oceanicvibes.com"}


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

    monkeypatch.setattr(bootstrap, "_worker_readiness", lambda config, tenant, env=None: ("oceanicvibes", ""))
    monkeypatch.setattr(bootstrap, "cloudflare_dns_api_token", lambda config, env: "dns-token")
    monkeypatch.setattr(bootstrap, "cloudflare_email_api_token", lambda config, env: "email-token")

    class Client:
        def __init__(self, email_token, dns_token):
            assert email_token == "email-token"
            assert dns_token == "dns-token"

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


def test_prepare_plan_uses_managed_zone_apex_by_default_for_a_www_site(monkeypatch, tmp_path):
    config = _config(tmp_path)
    config["site"]["custom_domain"] = "www.oceanicvibes.com"
    seen = {}

    monkeypatch.setattr(bootstrap, "_worker_readiness", lambda config, tenant, env=None: ("oceanicvibes", ""))
    monkeypatch.setattr(bootstrap, "cloudflare_dns_api_token", lambda config, env: "dns-token")
    monkeypatch.setattr(bootstrap, "cloudflare_email_api_token", lambda config, env: "email-token")

    class Client:
        def __init__(self, email_token, dns_token):
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
    assert policy["emailDomainSetting"] == "www.oceanicvibes.com"


def test_prepare_plan_uses_registered_platform_email_domain_for_worker_site(monkeypatch, tmp_path):
    config = _config(tmp_path)
    config["site"].pop("custom_domain")
    config["site"]["public_url"] = "https://atelier-harmonie.weareheadless.workers.dev/"
    config["messages"]["email"].update(domain="helloada.app", local_part="atelier-harmonie")
    seen = {}

    monkeypatch.setattr(bootstrap, "_worker_readiness", lambda config, tenant, env=None: ("atelier-harmonie", ""))
    monkeypatch.setattr(bootstrap, "cloudflare_dns_api_token", lambda config, env: "dns-token")
    monkeypatch.setattr(bootstrap, "cloudflare_email_api_token", lambda config, env: "email-token")

    class Client:
        def __init__(self, email_token, dns_token):
            assert email_token == "email-token"
            assert dns_token == "dns-token"

        def zone(self, hostname):
            assert hostname == "helloada.app"
            return {"name": "helloada.app"}

    class Service:
        def __init__(self, client):
            pass

        def plan(self, tenant, policy):
            seen.update(tenant=tenant, policy=policy)
            return {"tenant": tenant, "domain": policy["domain"], "address": policy["address"], "snapshot": {}, "snapshotSha256": "abc", "operations": []}

    monkeypatch.setattr(bootstrap, "CloudflareEmailClient", Client)
    monkeypatch.setattr(bootstrap, "EmailProvisioningService", Service)

    plan, policy, _ = bootstrap.prepare_email_plan(config, tenant_id="atelier-harmonie", env={})

    assert plan["domain"] == "helloada.app"
    assert plan["address"] == "atelier-harmonie@helloada.app"
    assert policy["domain"] == "helloada.app"
    assert seen["tenant"] == "atelier-harmonie"


def test_prepare_plan_rejects_email_subdomain_until_routing_onboarding_is_supported(monkeypatch, tmp_path):
    config = _config(tmp_path)
    config["site"].pop("custom_domain")
    config["site"]["public_url"] = "https://atelier-harmonie.weareheadless.workers.dev/"
    config["messages"]["email"]["domain"] = "inbox.helloada.app"
    monkeypatch.setattr(bootstrap, "_worker_readiness", lambda config, tenant, env=None: ("atelier-harmonie", ""))
    monkeypatch.setattr(bootstrap, "cloudflare_dns_api_token", lambda config, env: "dns-token")
    monkeypatch.setattr(bootstrap, "cloudflare_email_api_token", lambda config, env: "email-token")

    class Client:
        def __init__(self, email_token, dns_token):
            pass

        def zone(self, hostname):
            assert hostname == "inbox.helloada.app"
            return {"name": "helloada.app"}

    monkeypatch.setattr(bootstrap, "CloudflareEmailClient", Client)

    try:
        bootstrap.prepare_email_plan(config, tenant_id="atelier-harmonie", env={})
    except bootstrap.EmailProvisioningError as exc:
        assert "zone-apex email domains only" in str(exc)
    else:
        raise AssertionError("subdomain email provisioning must not use the apex-only API path")


def test_auto_provision_accepts_platform_email_domain_without_custom_website_domain(tmp_path):
    config = _config(tmp_path)
    config["site"].pop("custom_domain")
    config["site"]["public_url"] = "https://atelier-harmonie.weareheadless.workers.dev/"
    config["messages"]["email"].update(domain="helloada.app", local_part="atelier-harmonie")
    memory = FakeMemory()

    state, _ = bootstrap.auto_provision_email(config, tenant_id="atelier-harmonie", memory=memory, env={})

    assert state["state"] == "failed"
    assert state["domain"] == "helloada.app"
    assert state["address"] == "atelier-harmonie@helloada.app"
    assert "Cloudflare DNS API token" in state["error"]


def test_auto_provision_requires_a_registered_unique_local_part_for_an_explicit_domain(tmp_path):
    config = _config(tmp_path)
    config["site"].pop("custom_domain")
    config["site"]["public_url"] = "https://atelier-harmonie.weareheadless.workers.dev/"
    config["messages"]["email"]["domain"] = "helloada.app"
    config["messages"]["email"].pop("local_part")
    memory = FakeMemory()

    state, _ = bootstrap.auto_provision_email(config, tenant_id="atelier-harmonie", memory=memory, env={})

    assert state["state"] == "failed"
    assert "tenant-unique mailbox local part" in state["error"]
    assert "address" not in state


def test_auto_provision_persists_invalid_site_origin_as_a_failure(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config["site"].pop("custom_domain")
    config["site"]["public_url"] = "https://[invalid"
    config["messages"]["email"]["domain"] = "helloada.app"
    memory = FakeMemory()
    monkeypatch.setattr(
        bootstrap,
        "prepare_email_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("invalid origin must stop before provider access")),
    )

    state, _ = bootstrap.auto_provision_email(config, tenant_id="atelier-harmonie", memory=memory, env={})

    assert state["state"] == "failed"
    assert state["error"] == "The registered website origin is invalid"
    assert memory.state["email_provisioning_state"] == state


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
    monkeypatch.setattr(bootstrap, "cloudflare_dns_api_token", lambda config, env: "dns-token")
    monkeypatch.setattr(bootstrap, "cloudflare_email_api_token", lambda config, env: "email-token")

    class Client:
        def __init__(self, email_token, dns_token):
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
