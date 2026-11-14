import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_agent.application import github_oidc, runtime_identity, tenant_environment
from site_agent.application.workspace import ChatService, Tenant, TenantRegistry
from site_agent.core.memory import Memory
from site_agent import credentials
from site_agent.web.workspace import register_workspace_routes

TENANT = "site-ff8e9af06f56201f"
REPOSITORY = "weareheadless/astrid-rincon-website"
FINGERPRINT = "a" * 64
DEPLOYED = "b" * 64
CONTROL = "c" * 40


class _Bootstrap:
    def __init__(self):
        self.activated = []

    def activate_runtime_after_health(self, tenant_id, *, release_id, source_sha, verification=None):
        self.activated.append((tenant_id, release_id, source_sha))
        return {"tenant_id": tenant_id, "release_id": release_id, "source_sha": source_sha}


def _app(tmp_path, bootstrap=None):
    tenant = Tenant(
        TENANT,
        {
            "site": {
                "repository": REPOSITORY,
                "branch": "main",
                "source_deployment": {"worker_name": "helloada-site-astridrincon"},
                "payload": {
                    "contract": {
                        "contract": "helloada-content-v4",
                        "schemaIdentity": "d" * 64,
                        "coreVersion": "0.6.5",
                        "schemaRevision": 13,
                        "migrationHead": "e" * 64,
                    },
                    "runtime_activation": {
                        "release_id": "rel-20261113203000-shared-retry-route",
                        "source_sha": "9" * 40,
                        "shared_runtime_fingerprint": DEPLOYED,
                        "control_sha": "f" * 40,
                    },
                },
            },
        },
        Memory(tmp_path / "tenant.db"),
        None,
        {},
        "tenant-token",
        config_path=str(tmp_path / "config.yaml"),
    )
    registry = TenantRegistry({TENANT: tenant})
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={},
        service=ChatService(registry=registry),
        registry=registry,
        control_prefix="/v1/control-plane/websites",
        control_token="control-secret",
        bootstrap=bootstrap,
    )
    return app


def _material(monkeypatch, *, identity=None):
    monkeypatch.setattr(
        github_oidc, "verify",
        lambda token, **kwargs: {"sha": "1" * 40, "workflow": "release-deploy.yml", "run_id": "7"},
    )
    monkeypatch.setattr(
        github_oidc, "repo_file",
        lambda repository, ref, path, token: json.dumps({"controlSha": CONTROL}).encode(),
    )
    monkeypatch.setattr(github_oidc, "verify_canonical_workflow", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_identity, "runtime_identity",
                        identity or (lambda root: {
                            "sourceSha": CONTROL, "sharedRuntimeFingerprint": FINGERPRINT}))
    monkeypatch.setattr(credentials, "github_api_token", lambda config, env: "gh-token")
    monkeypatch.setattr(credentials, "cloudflare_api_token", lambda config, env: "cf-token")
    monkeypatch.setattr(credentials, "cloudflare_env_names", lambda config: ("KEY", "ACCOUNT"))
    monkeypatch.setattr(credentials, "credential_environment", lambda config, env: {"ACCOUNT": "acct"})
    monkeypatch.setattr(tenant_environment, "tenant_environment_path",
                        lambda config_path, tenant_id: Path("/tmp/tenant.env"))
    monkeypatch.setattr(
        tenant_environment, "read_tenant_environment",
        lambda path: {"HELLOADA_TURNSTILE_SITE_KEY": "turnstile-sitekey"},
    )
    monkeypatch.setattr(tenant_environment, "worker_runtime_secrets",
                        lambda *args, **kwargs: {"PAYLOAD_SECRET": "x"})
    monkeypatch.setattr(tenant_environment, "auto_email_provisioning_enabled", lambda path: False)


def test_deploy_credentials_requires_an_oidc_token(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(f"/v1/control-plane/websites/{TENANT}/deploy-credentials")
    assert response.status_code == 401
    assert "OIDC" in response.json()["detail"]


def test_deploy_credentials_names_the_runtime_the_platform_ships(tmp_path, monkeypatch):
    from site_agent.application import release_queue

    _material(monkeypatch)
    monkeypatch.setattr(release_queue, "release_root", lambda config: tmp_path / "releases")
    receipt = tmp_path / "releases" / "runs" / TENANT / "rel-20261113203000-shared-retry-route"
    receipt.mkdir(parents=True)
    (receipt / "receipt.json").write_text(json.dumps({
        "releaseId": "rel-20261113203000-shared-retry-route",
        "durableObjectLifecycle": {"identity": "e" * 64, "state": "reused", "appliedByReleaseId": "rel-1"},
    }), encoding="utf-8")
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            f"/v1/control-plane/websites/{TENANT}/deploy-credentials",
            headers={"Authorization": "Bearer oidc-token"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sharedRuntimeFingerprint"] == FINGERPRINT
    assert body["controlSha"] == CONTROL
    assert body["deployedSharedRuntimeFingerprint"] == DEPLOYED
    assert body["worker"] == "helloada-site-astridrincon"
    assert body["identity"]["schemaRevision"] == 13
    assert body["turnstileSiteKey"] == "turnstile-sitekey"
    assert body["durableObjectLifecycle"] == {"identity": "e" * 64, "releaseId": "rel-1"}
    assert body["cloudflare"]["accountId"] == "acct"


def test_deploy_credentials_refuses_when_the_platform_cannot_name_its_runtime(tmp_path, monkeypatch):
    def missing(_root):
        raise runtime_identity.RuntimeIdentityError(
            "this platform release does not declare the shared runtime it ships; release the API again"
        )

    _material(monkeypatch, identity=missing)
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            f"/v1/control-plane/websites/{TENANT}/deploy-credentials",
            headers={"Authorization": "Bearer oidc-token"},
        )
    assert response.status_code == 409
    assert "shared runtime" in response.json()["detail"]


def test_runtime_identity_reads_the_release_it_was_installed_from(tmp_path):
    (tmp_path / "runtime-identity.json").write_text(
        json.dumps({"schema": 1, "sourceSha": CONTROL, "sharedRuntimeFingerprint": FINGERPRINT}),
        encoding="utf-8",
    )
    assert runtime_identity.runtime_identity(tmp_path) == {
        "sourceSha": CONTROL, "sharedRuntimeFingerprint": FINGERPRINT,
    }
    with pytest.raises(runtime_identity.RuntimeIdentityError):
        runtime_identity.runtime_identity(tmp_path / "absent")


def test_deploy_receipt_is_stored_and_activated(tmp_path, monkeypatch):
    from site_agent.application import deploy_receipt, release_queue

    _material(monkeypatch)
    monkeypatch.setattr(release_queue, "release_root", lambda config: tmp_path / "releases")
    bootstrap = _Bootstrap()
    app = _app(tmp_path, bootstrap=bootstrap)
    receipt = {
        "schema": 2,
        "tenant": TENANT,
        "releaseId": "ci-7-1",
        "sourceSha": "1" * 40,
        "status": "deployed",
        "stage": "awaiting-browser-verification",
        "sharedRuntimeFingerprint": FINGERPRINT,
        "health": {"ok": True, "releaseSha": "1" * 40},
        "currentVerification": {"releaseId": "ci-7-1", "sourceSha": "1" * 40},
    }
    with TestClient(app) as client:
        response = client.post(
            f"/v1/control-plane/websites/{TENANT}/deploy-receipt",
            headers={"Authorization": "Bearer oidc-token"},
            json={"receipt": receipt},
        )
    assert response.status_code == 200, response.text
    assert response.json()["releaseId"] == "ci-7-1"
    assert bootstrap.activated == [(TENANT, "ci-7-1", "1" * 40)]
    stored = json.loads(
        (tmp_path / "releases" / "runs" / TENANT / "ci-7-1" / "receipt.json").read_text(encoding="utf-8")
    )
    assert stored["currentVerification"]["releaseId"] == "ci-7-1"


def test_deploy_receipt_refuses_a_release_for_another_runtime(tmp_path, monkeypatch):
    from site_agent.application import release_queue

    _material(monkeypatch)
    monkeypatch.setattr(release_queue, "release_root", lambda config: tmp_path / "releases")
    app = _app(tmp_path, bootstrap=_Bootstrap())
    receipt = {
        "tenant": TENANT,
        "releaseId": "ci-7-1",
        "sourceSha": "1" * 40,
        "status": "deployed",
        "stage": "awaiting-browser-verification",
        "sharedRuntimeFingerprint": "d" * 64,
        "health": {"ok": True, "releaseSha": "1" * 40},
        "currentVerification": {"releaseId": "ci-7-1"},
    }
    with TestClient(app) as client:
        response = client.post(
            f"/v1/control-plane/websites/{TENANT}/deploy-receipt",
            headers={"Authorization": "Bearer oidc-token"},
            json={"receipt": receipt},
        )
    assert response.status_code == 409
    assert "shared runtime" in response.json()["detail"]
