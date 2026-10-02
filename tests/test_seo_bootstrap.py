from __future__ import annotations

from pathlib import Path

import site_agent.application.seo_bootstrap as bootstrap


class FakeMemory:
    def __init__(self, state=None):
        self.state = dict(state or {})

    def kv_get(self, key, default=None):
        return self.state.get(key, default)

    def kv_set(self, key, value):
        self.state[key] = value


class FakeWorker:
    def __init__(self):
        self.secrets = {}

    def put_secret(self, name, value):
        self.secrets[name] = value
        return {"name": name, "status": "written"}


def _config(tmp_path: Path):
    return {
        "data_dir": str(tmp_path / "data"),
        "display_name": "Workspace Harmonie",
        "site": {
            "preview_url": "https://workspace-harmonie.workers.dev",
            "source_deployment": {"worker_name": "workspace-harmonie"},
        },
        "seo": {
            "site_url": "https://workspace-harmonie.workers.dev/",
            "provisioning": {"auto": True, "verification_method": "meta"},
        },
        "ga": {},
    }


def test_meta_content_extracts_token_from_google_html_tag():
    assert bootstrap._meta_content('<meta name="google-site-verification" content="meta-token" />') == "meta-token"
    assert bootstrap._meta_content("google-site-verification=meta-token") == "meta-token"


def test_bootstrap_installs_verification_and_runtime_secrets(monkeypatch, tmp_path):
    memory = FakeMemory()
    worker = FakeWorker()
    calls = []

    class FakeProvisioning:
        def __init__(self, config, env):
            pass

        def provision(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return {
                    "tenant_id": "workspace-harmonie",
                    "domain": "workspace-harmonie.workers.dev",
                    "site_url": "https://workspace-harmonie.workers.dev/",
                    "gsc_property": "https://workspace-harmonie.workers.dev/",
                    "gsc_pending": True,
                    "gsc_meta_tag": "google-site-verification=meta-token",
                    "ga4_property_id": "411596330",
                    "ga4_measurement_id": "G-TEST123",
                    "provisioning_state": "awaiting_gsc_verification",
                    "token_env": "CRAWLSEO_TOKEN_WORKSPACE_HARMONIE",
                }
            return {
                "tenant_id": "workspace-harmonie",
                "domain": "workspace-harmonie.workers.dev",
                "site_url": "https://workspace-harmonie.workers.dev/",
                "gsc_property": "https://workspace-harmonie.workers.dev/",
                "gsc_verified": True,
                "gsc_verification_method": "meta",
                "ga4_property_id": kwargs["ga4_property_id"],
                "ga4_measurement_id": "G-TEST123",
                "credential_token": "crawlseo-token",
                "token_env": "CRAWLSEO_TOKEN_WORKSPACE_HARMONIE",
                "provisioning_state": "ready",
            }

    written = []
    monkeypatch.setattr(bootstrap, "SeoProvisioningService", FakeProvisioning)
    monkeypatch.setattr(bootstrap, "_worker_client", lambda config, env: worker)
    monkeypatch.setattr(bootstrap, "load_tenant_environment", lambda config, env=None: {})
    monkeypatch.setattr(bootstrap, "write_token_env", lambda directory, name, token: written.append((directory, name, token)))

    state, env = bootstrap.auto_provision_seo(
        _config(tmp_path),
        tenant_id="workspace-harmonie",
        memory=memory,
    )

    assert state["state"] == "ready"
    assert calls[1]["ga4_property_id"] == "411596330"
    assert worker.secrets == {
        "GOOGLE_SITE_VERIFICATION": "meta-token",
        "GA_MEASUREMENT_ID": "G-TEST123",
    }
    assert written == [(tmp_path, "CRAWLSEO_TOKEN_WORKSPACE_HARMONIE", "crawlseo-token")]
    assert env["CRAWLSEO_TOKEN_WORKSPACE_HARMONIE"] == "crawlseo-token"
    assert "credential_token" not in state
    assert "credential_file" in state


def test_bootstrap_reuses_property_from_a_previous_failed_attempt(monkeypatch, tmp_path):
    memory = FakeMemory({"seo_provisioning_state": {"state": "error", "ga4_property_id": "411596330"}})
    calls = []

    class FakeProvisioning:
        def __init__(self, config, env):
            pass

        def provision(self, **kwargs):
            calls.append(kwargs)
            return {
                "tenant_id": "workspace-harmonie",
                "domain": "workspace-harmonie.workers.dev",
                "gsc_property": "https://workspace-harmonie.workers.dev/",
                "gsc_verified": True,
                "ga4_property_id": kwargs["ga4_property_id"],
                "provisioning_state": "ready",
            }

    monkeypatch.setattr(bootstrap, "SeoProvisioningService", FakeProvisioning)
    monkeypatch.setattr(bootstrap, "load_tenant_environment", lambda config, env=None: {})

    state, _ = bootstrap.auto_provision_seo(
        _config(tmp_path),
        tenant_id="workspace-harmonie",
        memory=memory,
    )

    assert calls[0]["ga4_property_id"] == "411596330"
    assert state["state"] == "ready"


def test_bootstrap_reconciles_a_custom_domain_as_a_new_current_origin(monkeypatch, tmp_path):
    memory = FakeMemory({
        "seo_provisioning_state": {
            "state": "ready",
            "site_url": "https://workspace-harmonie.workers.dev/",
            "domain": "workspace-harmonie.workers.dev",
            "gsc_property": "https://workspace-harmonie.workers.dev/",
            "gsc_verified": True,
            "gsc_verified_at": "2026-10-01T00:00:00+00:00",
            "ga4_property_id": "411596330",
        }
    })
    config = _config(tmp_path)
    config["site"]["public_url"] = "https://atelier.example/"
    config["seo"]["site_url"] = "https://atelier.example/"
    calls = []

    class FakeProvisioning:
        def __init__(self, config, env):
            pass

        def provision(self, **kwargs):
            calls.append(kwargs)
            return {
                "tenant_id": "workspace-harmonie",
                "domain": "atelier.example",
                "site_url": "https://atelier.example/",
                "gsc_property": kwargs["gsc_property"],
                "gsc_verified": True,
                "gsc_verification_method": "meta",
                "ga4_property_id": kwargs["ga4_property_id"],
                "provisioning_state": "ready",
            }

    monkeypatch.setattr(bootstrap, "SeoProvisioningService", FakeProvisioning)
    monkeypatch.setattr(bootstrap, "load_tenant_environment", lambda config, env=None: {})

    state, _ = bootstrap.auto_provision_seo(
        config,
        tenant_id="workspace-harmonie",
        memory=memory,
    )

    assert calls[0]["site_url"] == "https://atelier.example/"
    assert calls[0]["gsc_property"] == "https://atelier.example/"
    assert calls[0]["ga4_property_id"] == "411596330"
    assert state["site_url"] == "https://atelier.example/"
    assert state["gsc_property"] == "https://atelier.example/"
    assert state["origin_changed"] is True
    assert state["origin_history"][0]["site_url"] == "https://workspace-harmonie.workers.dev/"


def test_enabled_seo_defaults_to_automatic_provisioning(monkeypatch, tmp_path):
    config = _config(tmp_path)
    config["seo"]["provisioning"].pop("auto", None)
    calls = []

    class FakeProvisioning:
        def __init__(self, config, env):
            pass

        def provision(self, **kwargs):
            calls.append(kwargs)
            return {
                "site_url": kwargs["site_url"],
                "gsc_property": kwargs["gsc_property"],
                "gsc_verified": True,
                "ga4_property_id": "properties/123",
                "provisioning_state": "ready",
            }

    monkeypatch.setattr(bootstrap, "SeoProvisioningService", FakeProvisioning)
    monkeypatch.setattr(bootstrap, "load_tenant_environment", lambda config, env=None: {})

    state, _ = bootstrap.auto_provision_seo(
        config,
        tenant_id="workspace-harmonie",
        memory=FakeMemory(),
    )

    assert calls
    assert state["state"] == "ready"
