from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from site_agent.application import email_management, email_bootstrap
from site_agent.application.email_management import (
    EmailManagementError,
    email_alert_settings,
    email_is_externally_managed,
    email_management_mode,
    email_settings_view,
    validate_email_settings_update,
)
from site_agent.application.tenant_environment import auto_email_provisioning_enabled
from site_agent.core import jobs


class FakeMemory:
    def __init__(self, state=None):
        self.state = dict(state or {})

    def kv_get(self, key, default=None):
        return self.state.get(key, default)

    def kv_set(self, key, value):
        self.state[key] = value


def _config(tmp_path: Path, *, mode: str = "managed", auto: bool = True):
    email = {
        "enabled": True,
        "domain": "helloada.app",
        "local_part": "demo-tenant",
        "domain_source": "helloada_platform",
        "provisioning": {"auto": auto},
    }
    if mode != "managed":
        email["management"] = {"mode": mode, "provider": "GoDaddy"}
    return {
        "data_dir": str(tmp_path / "data"),
        "display_name": "Demo",
        "site": {"custom_domain": "demo.example", "public_url": "https://demo.example/"},
        "messages": {"email": email},
    }


def test_management_mode_defaults_to_managed_and_reads_the_registered_mode(tmp_path):
    assert email_management_mode(_config(tmp_path)) == "managed"
    assert email_is_externally_managed(_config(tmp_path)) is False
    assert email_is_externally_managed(_config(tmp_path, mode="external")) is True


def test_external_tenant_never_reports_an_enabled_provisioning_policy(tmp_path):
    """The registered mode, not the DNS records, decides who owns the mail."""
    external = _config(tmp_path, mode="external", auto=True)
    assert jobs._email_provisioning_enabled(external) is False
    assert jobs._email_provisioning_enabled(_config(tmp_path, auto=True)) is True


def test_external_tenant_is_not_provisioned_by_the_registered_tenant_environment(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(_config(tmp_path, mode="external", auto=True)), encoding="utf-8")
    assert auto_email_provisioning_enabled(config_path) is False
    managed_path = tmp_path / "managed.yaml"
    managed_path.write_text(yaml.safe_dump(_config(tmp_path)), encoding="utf-8")
    assert auto_email_provisioning_enabled(managed_path) is True


def test_external_tenant_stops_before_any_provider_write(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        email_bootstrap, "prepare_email_plan",
        lambda *args, **kwargs: calls.append("plan") or {},
    )
    memory = FakeMemory()
    state, _env = email_bootstrap.auto_provision_email(
        _config(tmp_path, mode="external", auto=True),
        tenant_id="demo-tenant",
        tenant_config_path=tmp_path / "config.yaml",
        memory=memory,
        env={},
    )
    assert state["state"] == "externally_managed"
    assert calls == []
    assert memory.state["email_provisioning_state"]["state"] == "externally_managed"


def test_settings_update_rejects_unsupported_and_invalid_values():
    with pytest.raises(EmailManagementError):
        validate_email_settings_update({"mode": "managed", "unknown": 1})
    with pytest.raises(EmailManagementError):
        validate_email_settings_update({"mode": "somewhere"})
    with pytest.raises(EmailManagementError):
        validate_email_settings_update({"mode": "managed", "alerts": {"recipient": "not-an-address"}})
    with pytest.raises(EmailManagementError):
        validate_email_settings_update({"mode": "managed", "alerts": {"enabled": True, "recipient": ""}})
    # An alert with no trigger sends nothing, so it needs no recipient.
    quiet = validate_email_settings_update({
        "mode": "managed",
        "alerts": {"enabled": True, "recipient": "", "inbound": False, "external": False},
    })
    assert quiet["alerts"]["recipient"] == ""


def test_a_mode_change_keeps_the_registered_alert_configuration(tmp_path):
    """Changing who owns the mail never silently clears the owner's alerts."""
    current = _config(tmp_path, mode="managed")
    current["messages"]["email"]["alerts"] = {
        "enabled": True,
        "recipient": "owner@example.com",
        "inbound": True,
        "external": True,
    }
    requested = validate_email_settings_update({"mode": "external"}, current)
    assert requested["mode"] == "external"
    assert requested["alerts"]["recipient"] == "owner@example.com"
    assert requested["alerts"]["enabled"] is True
    assert requested["provisioning"] == {"auto": False}


def test_settings_update_registers_the_mode_and_stops_provisioning_for_external_mail():
    requested = validate_email_settings_update({
        "mode": "external",
        "provider": "GoDaddy",
        "alerts": {"enabled": True, "recipient": "owner@example.com"},
    })
    assert requested["mode"] == "external"
    assert requested["provider"] == "GoDaddy"
    assert requested["provisioning"] == {"auto": False}
    managed = validate_email_settings_update({
        "mode": "managed",
        "alerts": {"enabled": True, "recipient": "owner@example.com"},
    })
    assert managed["provisioning"] == {"auto": True}


def test_settings_view_exposes_the_registered_mailbox_and_alerts(tmp_path):
    view = email_settings_view(_config(tmp_path, mode="external"))
    assert view["mode"] == "external"
    assert view["mailbox"]["address"] == "demo-tenant@helloada.app"
    assert view["provisioning"]["auto"] is True
    assert view["alerts"]["recipient"] == ""
    assert email_alert_settings(_config(tmp_path))["inbound"] is True


def test_site_origin_change_keeps_the_registered_mailbox_of_an_external_tenant(tmp_path, monkeypatch):
    from site_agent.application import workspace as workspace_module
    from site_agent.application.workspace import ChatService, Tenant, TenantRegistry

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "site": {"preview_url": "https://demo.example/", "source_deployment": {"worker_name": "demo"}},
        "messages": {"email": {
            "enabled": True,
            "domain": "helloada.app",
            "local_part": "demo-tenant",
            "domain_source": "helloada_platform",
            "management": {"mode": "external", "provider": "GoDaddy"},
            "provisioning": {"auto": False},
        }},
    }), encoding="utf-8")
    tenant = Tenant(
        tenant_id="demo",
        config={},
        memory=None,
        runtime=None,
        context={},
        api_token="demo-token",
        config_path=str(config_path),
        api_token_env="CUSTOM_DEMO_TOKEN",
    )
    registry = TenantRegistry({"demo": tenant})
    monkeypatch.setattr(
        workspace_module, "canonical_worker_preview_url",
        lambda _config, _env: "https://demo.weareheadless.workers.dev",
    )
    registry.reload_tenant = lambda tenant_id, path, **kwargs: tenant
    registry.update_site_origin("demo", "https://www.demo.example")

    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    email = updated["messages"]["email"]
    # The domain changed. The mailbox did not: this tenant's mail is managed
    # elsewhere, so the platform never takes it over.
    assert email["domain"] == "helloada.app"
    assert email["local_part"] == "demo-tenant"
    assert email["domain_source"] == "helloada_platform"
    assert email["provisioning"]["auto"] is False
    assert email["management"] == {"mode": "external", "provider": "GoDaddy"}


def test_managed_tenant_still_derives_its_mailbox_from_the_site_origin(tmp_path, monkeypatch):
    from site_agent.application import workspace as workspace_module
    from site_agent.application.workspace import Tenant, TenantRegistry

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "site": {"preview_url": "https://demo.example/", "source_deployment": {"worker_name": "demo"}},
        "messages": {"email": {"enabled": True, "provisioning": {"auto": True}}},
    }), encoding="utf-8")
    tenant = Tenant(
        tenant_id="demo",
        config={},
        memory=None,
        runtime=None,
        context={},
        api_token="demo-token",
        config_path=str(config_path),
        api_token_env="CUSTOM_DEMO_TOKEN",
    )
    registry = TenantRegistry({"demo": tenant})
    monkeypatch.setattr(
        workspace_module, "canonical_worker_preview_url",
        lambda _config, _env: "https://demo.weareheadless.workers.dev",
    )
    registry.reload_tenant = lambda tenant_id, path, **kwargs: tenant
    registry.update_site_origin("demo", "https://www.demo.example")

    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    email = updated["messages"]["email"]
    assert email["domain"] == "www.demo.example"
    assert email["domain_source"] == "site_custom_domain"
    assert email["provisioning"]["auto"] is True


def _alert_tenant(tmp_path: Path, *, mode: str = "managed"):
    tenant_dir = tmp_path / "websites" / "demo-tenant"
    tenant_dir.mkdir(parents=True)
    config_path = tenant_dir / "config.yaml"
    config = _config(tmp_path, mode=mode)
    config["messages"]["email"]["alerts"] = {
        "enabled": True,
        "recipient": "owner@example.com",
        "inbound": True,
        "external": True,
    }
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    (tenant_dir / "tenant.env").write_text(
        "MAILFLARE_ADDRESS=demo-tenant@helloada.app\nRESEND_API_KEY=re_tenant_key\n",
        encoding="utf-8",
    )
    return config, config_path


def test_inbound_alert_uses_the_tenant_key_and_is_sent_once(tmp_path, monkeypatch):
    from site_agent.application import mail_alerts

    sent: list[dict] = []

    class FakeSender:
        def __init__(self, api_key, **_kwargs):
            assert api_key == "re_tenant_key"

        def send_message(self, **message):
            sent.append(message)
            return "provider-message-id"

    monkeypatch.setattr(mail_alerts, "ResendSender", FakeSender)
    config, config_path = _alert_tenant(tmp_path)
    memory = FakeMemory()
    service = mail_alerts.MailAlertService(
        config, tenant_id="demo-tenant", tenant_config_path=config_path, memory=memory,
    )

    receipt = service.inbound_alert(message_id="webform_abc", subject="Website enquiry")
    assert receipt["state"] == "sent"
    assert receipt["recipient"] == "owner@example.com"
    assert len(sent) == 1
    assert sent[0]["sender"] == "demo-tenant@helloada.app"
    assert sent[0]["recipient"] == "owner@example.com"
    assert "Check HelloAda" in sent[0]["text"]

    again = service.inbound_alert(message_id="webform_abc", subject="Website enquiry")
    assert again["state"] == "already_sent"
    assert len(sent) == 1


def test_external_notice_tells_the_owner_who_handles_the_mail(tmp_path, monkeypatch):
    from site_agent.application import mail_alerts

    sent: list[dict] = []

    class FakeSender:
        def __init__(self, api_key, **_kwargs):
            pass

        def send_message(self, **message):
            sent.append(message)
            return "provider-message-id"

    monkeypatch.setattr(mail_alerts, "ResendSender", FakeSender)
    config, config_path = _alert_tenant(tmp_path, mode="external")
    memory = FakeMemory()
    service = mail_alerts.MailAlertService(
        config, tenant_id="demo-tenant", tenant_config_path=config_path, memory=memory,
    )

    receipt = service.external_notice()
    assert receipt["state"] == "sent"
    assert len(sent) == 1
    assert "GoDaddy" in sent[0]["text"]
    assert "not by HelloAda" in sent[0]["text"]


def test_managed_tenant_sends_no_external_notice(tmp_path, monkeypatch):
    from site_agent.application import mail_alerts

    class FakeSender:
        def __init__(self, api_key, **_kwargs):
            raise AssertionError("a managed tenant must not send an external notice")

    monkeypatch.setattr(mail_alerts, "ResendSender", FakeSender)
    config, config_path = _alert_tenant(tmp_path)
    service = mail_alerts.MailAlertService(
        config, tenant_id="demo-tenant", tenant_config_path=config_path, memory=FakeMemory(),
    )
    assert service.external_notice()["state"] == "not_applicable"


def _registered_tenant(tmp_path: Path):
    from site_agent.core.memory import Memory
    from site_agent.application.workspace import Tenant

    tenant_dir = tmp_path / "websites" / "demo-tenant"
    tenant_dir.mkdir(parents=True)
    config_path = tenant_dir / "config.yaml"
    config = _config(tmp_path)
    config["messages"]["email"]["alerts"] = {
        "enabled": True,
        "recipient": "owner@example.com",
        "inbound": True,
        "external": True,
    }
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    (tenant_dir / "tenant.env").write_text(
        "MAILFLARE_ADDRESS=demo-tenant@helloada.app\nRESEND_API_KEY=re_tenant_key\n",
        encoding="utf-8",
    )
    tenant = Tenant(
        tenant_id="demo-tenant",
        config=config,
        memory=Memory(tmp_path / "memory.db"),
        runtime=None,
        context={},
        api_token="demo-token",
        config_path=str(config_path),
        api_token_env="CUSTOM_DEMO_TENANT_TOKEN",
    )
    return tenant, config_path


def test_settings_routes_register_the_mail_policy_and_the_owner_actor_is_required(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from site_agent.application.workspace import ChatService, TenantRegistry
    from site_agent.web.workspace import register_workspace_routes

    tenant, config_path = _registered_tenant(tmp_path)
    registry = TenantRegistry({"demo-tenant": tenant})

    def fake_reload(tenant_id, path, **kwargs):
        tenant.config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return tenant

    monkeypatch.setattr(registry, "reload_tenant", fake_reload)
    app = FastAPI()
    register_workspace_routes(app, config={}, env={}, service=ChatService(registry=registry), registry=registry)
    headers = {"Authorization": "Bearer demo-token"}
    with TestClient(app) as client:
        view = client.get("/api/workspace/settings/email", headers=headers)
        assert view.status_code == 200
        assert view.json()["mode"] == "managed"
        assert view.json()["alerts"]["recipient"] == "owner@example.com"

        anonymous = client.put("/api/workspace/settings/email", headers=headers, json={"mode": "external"})
        assert anonymous.status_code == 409

        updated = client.put(
            "/api/workspace/settings/email",
            headers={**headers, "x-helloada-owner-id": "payload:demo-tenant:owner"},
            json={
                "mode": "external",
                "provider": "GoDaddy",
                "alerts": {"enabled": True, "recipient": "owner@example.com"},
            },
        )
        assert updated.status_code == 200
        assert updated.json()["settings"]["mode"] == "external"
        assert updated.json()["settings"]["provider"] == "GoDaddy"
        assert updated.json()["settings"]["provisioning"]["auto"] is False
        stored = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert stored["messages"]["email"]["management"] == {"mode": "external", "provider": "GoDaddy"}
        assert stored["messages"]["email"]["provisioning"] == {"auto": False}


def test_mail_notification_route_sends_one_alert_for_one_reported_mail(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from site_agent.application import mail_alerts
    from site_agent.application.workspace import ChatService, TenantRegistry
    from site_agent.web.workspace import register_workspace_routes

    sent: list[dict] = []

    class FakeSender:
        def __init__(self, api_key, **_kwargs):
            pass

        def send_message(self, **message):
            sent.append(message)
            return "provider-message-id"

    monkeypatch.setattr(mail_alerts, "ResendSender", FakeSender)
    tenant, _config_path = _registered_tenant(tmp_path)
    registry = TenantRegistry({"demo-tenant": tenant})
    app = FastAPI()
    register_workspace_routes(app, config={}, env={}, service=ChatService(registry=registry), registry=registry)
    headers = {"Authorization": "Bearer demo-token"}
    with TestClient(app) as client:
        reported = client.post(
            "/api/workspace/mail/notification",
            headers=headers,
            json={"messageId": "webform_abc", "subject": "Website enquiry", "from": "visitor@example.com"},
        )
        assert reported.status_code == 200
        assert reported.json()["alert"]["state"] == "sent"
        assert len(sent) == 1
        assert sent[0]["recipient"] == "owner@example.com"

        repeated = client.post(
            "/api/workspace/mail/notification",
            headers=headers,
            json={"messageId": "webform_abc"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["alert"]["state"] == "already_sent"
        assert len(sent) == 1
