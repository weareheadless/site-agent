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
