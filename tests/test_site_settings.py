from __future__ import annotations

import pytest

from site_agent.application import site_domain
from site_agent.application.workspace import Tenant, TenantRegistry


class FakeMemory:
    def __init__(self, state=None):
        self.state = dict(state or {})

    def kv_get(self, key, default=None):
        return self.state.get(key, default)

    def kv_set(self, key, value):
        self.state[key] = value


def _tenant(*, public_url="https://www.demo.example/", custom="demo.example",
            worker="helloada-demo", state=None):
    return Tenant(
        tenant_id="demo",
        config={
            "display_name": "Demo",
            "site": {
                "public_url": public_url,
                "custom_domain": custom,
                "preview_url": f"https://{worker}.weareheadless.workers.dev",
                "payload": {"url": f"https://{worker}.weareheadless.workers.dev"},
                "source_deployment": {"worker_name": worker},
            },
            "messages": {"email": {
                "enabled": True,
                "domain": "helloada.app",
                "local_part": "demo",
                "domain_source": "helloada_platform",
                "management": {"mode": "external", "provider": "GoDaddy"},
                "alerts": {"recipient": "owner@example.com"},
            }},
        },
        memory=FakeMemory(state or {"seo_provisioning_state": {
            "state": "ready",
            "site_url": public_url,
            "gsc_property": "sc-domain:demo.example",
            "gsc_verified": True,
            "crawlseo": {"project_id": "project-1", "site_id": "site-1"},
        }}),
        runtime=None,
        context={},
        api_token="demo-token",
    )


def test_site_settings_reports_identity_domain_mail_and_seo(monkeypatch):
    monkeypatch.setattr(
        site_domain.SiteDomainService, "probe",
        staticmethod(lambda url: {"ok": True, "status": 200}),
    )
    tenant = _tenant()
    registry = TenantRegistry({"demo": tenant})

    settings = registry.site_settings(tenant)

    assert settings["identity"]["publicUrl"] == "https://www.demo.example/"
    assert settings["identity"]["adminUrl"] == "https://www.demo.example/admin"
    assert settings["identity"]["registeredDomain"] == "demo.example"
    assert settings["email"]["mailbox"]["address"] == "demo@helloada.app"
    assert settings["email"]["alerts"]["recipient"] == "owner@example.com"
    assert settings["seo"]["gscProperty"] == "sc-domain:demo.example"
    assert settings["seo"]["siteId"] == "site-1"
    assert settings["capabilities"]["attachDomain"] is True


def test_attach_domain_records_the_registered_domain_and_requests_a_rebuild(monkeypatch):
    tenant = _tenant(public_url="https://demo.weareheadless.workers.dev/", custom="")
    updated = _tenant()
    registry = TenantRegistry({"demo": tenant})
    monkeypatch.setattr(
        site_domain.SiteDomainService, "attach",
        lambda self, **kwargs: {
            "registeredDomain": "demo.example",
            "canonicalHost": "www.demo.example",
            "publicUrl": "https://www.demo.example/",
            "attached": ["demo.example", "www.demo.example"],
            "kept": [],
        },
    )
    monkeypatch.setattr(
        site_domain.SiteDomainService, "probe",
        staticmethod(lambda url: {"ok": True, "status": 200}),
    )
    monkeypatch.setattr(
        site_domain.SiteDomainService, "status",
        lambda self, identity: {"available": True, "serving": {"ok": True}},
    )
    monkeypatch.setattr(
        site_domain, "request_site_rebuild",
        lambda config, env: {"state": "queued", "sha": "a" * 40},
    )
    recorded: list[tuple[str, str, str]] = []

    def fake_update(tenant_id, public_url, *, custom_domain="", env=None):
        recorded.append((tenant_id, public_url, custom_domain))
        return updated

    monkeypatch.setattr(registry, "update_site_origin", fake_update)

    result = registry.attach_domain("demo", "https://www.demo.example/")

    assert recorded == [("demo", "https://www.demo.example/", "demo.example")]
    assert result["state"] == "attached"
    assert result["identity"]["registeredDomain"] == "demo.example"
    assert result["rebuild"] == {"state": "queued", "sha": "a" * 40}


def test_attach_domain_rejects_a_domain_that_does_not_cover_the_host(monkeypatch):
    tenant = _tenant()
    registry = TenantRegistry({"demo": tenant})
    monkeypatch.setattr(
        site_domain.SiteDomainService, "attach",
        lambda self, **kwargs: (_ for _ in ()).throw(
            site_domain.SiteDomainError("zone not found", status_code=409)
        ),
    )

    with pytest.raises(site_domain.SiteDomainError):
        registry.attach_domain("demo", "other.example")


def _app(registry):
    from fastapi import FastAPI
    from site_agent.application.workspace import ChatService
    from site_agent.web.workspace import register_workspace_routes

    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={},
        service=ChatService(registry=registry),
        registry=registry,
        prefix="/v1/workspace",
        control_prefix="/v1/control-plane/websites",
        control_token="control-secret",
    )
    return app


def test_settings_route_requires_the_control_token(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        site_domain.SiteDomainService, "probe",
        staticmethod(lambda url: {"ok": True, "status": 200}),
    )
    tenant = _tenant()
    registry = TenantRegistry({"demo": tenant})
    with TestClient(_app(registry)) as client:
        denied = client.get("/v1/control-plane/websites/demo/settings")
        allowed = client.get(
            "/v1/control-plane/websites/demo/settings",
            headers={"Authorization": "Bearer control-secret"},
        )
    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["identity"]["registeredDomain"] == "demo.example"


def test_domain_route_reports_a_conflict_with_its_details(monkeypatch):
    from fastapi.testclient import TestClient

    tenant = _tenant()
    registry = TenantRegistry({"demo": tenant})

    def conflict(*args, **kwargs):
        raise site_domain.SiteDomainError(
            "www.demo.example already has DNS records that would block the Worker",
            conflict=site_domain.DomainConflict(
                kind="dns_record",
                hostname="www.demo.example",
                detail="existing DNS records point somewhere else",
                records=({"type": "CNAME", "name": "www.demo.example",
                          "content": "cdn.webflow.com", "proxied": True},),
            ),
        )

    monkeypatch.setattr(registry, "attach_domain", conflict)
    with TestClient(_app(registry)) as client:
        response = client.post(
            "/v1/control-plane/websites/demo/settings/domain",
            headers={"Authorization": "Bearer control-secret"},
            json={"domain": "demo.example"},
        )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["conflict"]["kind"] == "dns_record"
    assert detail["conflict"]["records"][0]["content"] == "cdn.webflow.com"


def test_update_site_name_writes_the_tenant_record_and_reloads(tmp_path, monkeypatch):
    import yaml

    tenant = _tenant()
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"display_name": "Demo", "site": {}}), encoding="utf-8")
    tenant.config_path = str(config)
    registry = TenantRegistry({"demo": tenant})
    reloaded: list[tuple] = []
    monkeypatch.setattr(
        registry, "reload_tenant",
        lambda *args, **kwargs: (reloaded.append(args), tenant)[1],
    )

    registry.update_site_name("demo", "  Demo   Studio ")

    document = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert document["display_name"] == "Demo Studio"
    assert reloaded and reloaded[0][0] == "demo"


def test_update_site_name_rejects_an_empty_name(tmp_path):
    from site_agent.config import ConfigError

    tenant = _tenant()
    config = tmp_path / "config.yaml"
    config.write_text("display_name: Demo\n", encoding="utf-8")
    tenant.config_path = str(config)
    registry = TenantRegistry({"demo": tenant})

    with pytest.raises(ConfigError):
        registry.update_site_name("demo", "   ")


def test_settings_rename_route_updates_the_record(monkeypatch):
    from fastapi.testclient import TestClient

    tenant = _tenant()
    renamed = _tenant()
    renamed.config["display_name"] = "Demo Studio"
    registry = TenantRegistry({"demo": tenant})
    monkeypatch.setattr(registry, "update_site_name", lambda tenant_id, name: renamed)

    with TestClient(_app(registry)) as client:
        response = client.patch(
            "/v1/control-plane/websites/demo/settings",
            headers={"Authorization": "Bearer control-secret"},
            json={"name": "Demo Studio"},
        )
        slug = client.patch(
            "/v1/control-plane/websites/demo/settings",
            headers={"Authorization": "Bearer control-secret"},
            json={"slug": "demo-studio"},
        )

    assert response.status_code == 200
    assert response.json()["displayName"] == "Demo Studio"
    assert slug.status_code == 400
    assert slug.json()["detail"] == "slug_read_only"


def test_site_settings_reports_the_mail_provisioning_state_the_owner_needs(monkeypatch):
    """A blocked mailbox is a reason, not an invisible platform-domain address."""
    monkeypatch.setattr(
        site_domain.SiteDomainService, "probe",
        staticmethod(lambda url: {"ok": True, "status": 200}),
    )
    tenant = _tenant(state={
        "seo_provisioning_state": {"state": "ready"},
        "email_provisioning_state": {
            "state": "action_required",
            "address": "hello@demo.example",
            "error": "The host Cloudflare Email API credential cannot manage demo.example.",
            "lastAttemptAt": "2026-11-17T20:56:35+00:00",
        },
    })
    registry = TenantRegistry({"demo": tenant})

    settings = registry.site_settings(tenant)

    assert settings["email"]["provisioning"]["state"] == "action_required"
    assert settings["email"]["provisioning"]["address"] == "hello@demo.example"
    assert "cannot manage" in settings["email"]["provisioning"]["error"]
