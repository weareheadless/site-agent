from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from site_agent.config import ConfigError


def _registry(tmp_path: Path, monkeypatch, *, seo=None):
    from site_agent.application import workspace as workspace_module
    from site_agent.application.workspace import Tenant, TenantRegistry

    config_path = tmp_path / "config.yaml"
    document = {
        "site": {"preview_url": "https://demo.workers.dev/", "source_deployment": {"worker_name": "demo"}},
        "seo": seo or {},
    }
    config_path.write_text(yaml.safe_dump(document), encoding="utf-8")
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
        workspace_module,
        "canonical_worker_preview_url",
        lambda _config, _env: "https://demo.weareheadless.workers.dev",
    )
    registry.reload_tenant = lambda tenant_id, path, **kwargs: tenant
    return registry, config_path


def test_origin_change_records_the_registered_domain_not_the_canonical_host(tmp_path, monkeypatch):
    registry, config_path = _registry(
        tmp_path,
        monkeypatch,
        seo={"gsc_property": "sc-domain:demo.example", "provisioning": {"gsc_property": "sc-domain:demo.example"}},
    )

    registry.update_site_origin("demo", "https://www.demo.example", custom_domain="demo.example")

    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert updated["site"]["public_url"] == "https://www.demo.example/"
    assert updated["site"]["custom_domain"] == "demo.example"
    # A domain property covers the new canonical host, so it is kept.
    assert updated["seo"]["gsc_property"] == "sc-domain:demo.example"
    assert updated["seo"]["provisioning"]["gsc_property"] == "sc-domain:demo.example"
    assert updated["seo"]["provisioning"]["verification_method"] == "dns_txt"


def test_origin_change_replaces_a_url_prefix_property_of_the_old_host(tmp_path, monkeypatch):
    registry, config_path = _registry(
        tmp_path,
        monkeypatch,
        seo={"gsc_property": "https://demo.workers.dev/", "provisioning": {"gsc_property": "https://demo.workers.dev/"}},
    )

    registry.update_site_origin("demo", "https://www.demo.example", custom_domain="demo.example")

    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert updated["seo"]["gsc_property"] == "https://www.demo.example/"
    assert updated["seo"]["provisioning"]["gsc_property"] == "https://www.demo.example/"
    assert updated["seo"]["provisioning"]["verification_method"] == "meta"


def test_origin_change_rejects_a_custom_domain_that_does_not_cover_the_host(tmp_path, monkeypatch):
    registry, _config_path = _registry(tmp_path, monkeypatch)

    with pytest.raises(ConfigError):
        registry.update_site_origin("demo", "https://www.demo.example", custom_domain="other.example")


def test_a_new_tenant_derives_its_mailbox_from_its_registered_domain(tmp_path, monkeypatch):
    """Spawning is settings-first: the mail identity follows the site origin."""
    from site_agent.application import workspace as workspace_module

    registry, config_path = _registry(tmp_path, monkeypatch)
    woken = []
    monkeypatch.setattr(workspace_module, "_wake_email_provisioning", lambda tenant: woken.append(tenant.tenant_id))

    registry.update_site_origin("demo", "https://www.demo.example", custom_domain="demo.example")

    email = yaml.safe_load(config_path.read_text(encoding="utf-8"))["messages"]["email"]
    assert email == {
        "enabled": True,
        "domain": "demo.example",
        "domain_source": "site_custom_domain",
        "local_part": "hello",
        "provisioning": {"auto": True},
    }
    assert woken == ["demo"]


def test_a_platform_only_tenant_gets_a_tenant_unique_platform_mailbox(tmp_path, monkeypatch):
    from site_agent.application import workspace as workspace_module

    registry, config_path = _registry(tmp_path, monkeypatch)
    monkeypatch.setattr(workspace_module, "_wake_email_provisioning", lambda tenant: None)

    registry.update_site_origin("demo", "https://demo.weareheadless.workers.dev")

    email = yaml.safe_load(config_path.read_text(encoding="utf-8"))["messages"]["email"]
    assert email["domain"] == "helloada.app"
    assert email["domain_source"] == "helloada_platform"
    assert email["local_part"] == "demo"
    assert email["provisioning"] == {"auto": True}


def test_an_owner_registered_mailbox_domain_survives_a_domain_change(tmp_path, monkeypatch):
    from site_agent.application import workspace as workspace_module

    registry, config_path = _registry(tmp_path, monkeypatch)
    monkeypatch.setattr(workspace_module, "_wake_email_provisioning", lambda tenant: None)
    document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config_path.write_text(
        yaml.safe_dump({
            **document,
            "messages": {"email": {
                "enabled": True,
                "domain": "mail.owner.example",
                "domain_source": "owner",
                "local_part": "studio",
                "provisioning": {"auto": True},
            }},
        }),
        encoding="utf-8",
    )

    registry.update_site_origin("demo", "https://www.demo.example", custom_domain="demo.example")

    email = yaml.safe_load(config_path.read_text(encoding="utf-8"))["messages"]["email"]
    assert email["domain"] == "mail.owner.example"
    assert email["domain_source"] == "owner"
    assert email["local_part"] == "studio"
