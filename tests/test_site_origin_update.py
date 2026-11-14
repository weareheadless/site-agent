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
