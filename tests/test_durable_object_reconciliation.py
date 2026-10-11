from __future__ import annotations

import json
from pathlib import Path

import pytest

from site_agent.application import durable_object_reconciliation as reconciliation


TENANT = "oceanicvibes"
RELEASE_ID = "runtime-atomic-ambiguous"
SOURCE_SHA = "a" * 40
PIPELINE_SHA = "b" * 40
FINGERPRINT = "c" * 64
MIGRATION_IDENTITY = "d" * 64
DEPLOYED_AT = "2026-10-11T03:03:28.749887Z"


def _receipt() -> dict:
    return {
        "tenant": TENANT,
        "releaseId": RELEASE_ID,
        "sourceSha": SOURCE_SHA,
        "pipelineSha": PIPELINE_SHA,
        "sharedRuntimeFingerprint": FINGERPRINT,
        "worker": TENANT,
        "status": "failed",
        "stage": "deploy-durable-object-lifecycle",
        "rolloutMode": "atomic",
        "startedAt": "2026-10-11T02:57:41.386528Z",
        "finishedAt": "2026-10-11T03:03:35.340605Z",
        "previousDeployment": {"id": "old-deployment"},
        "durableObjectLifecycle": {
            "identity": MIGRATION_IDENTITY,
            "state": "outcome-unknown",
            "strategy": "atomic",
        },
        "payloadAdmin": "0.10.9",
        "payloadCore": "0.5.7",
        "contentContract": "helloada-content-v1",
        "schemaRevision": 7,
        "schemaIdentity": "e" * 64,
        "migrationHead": "f" * 64,
    }


def _version() -> dict:
    return {
        "id": "new-version",
        "metadata": {"created_on": DEPLOYED_AT},
        "resources": {
            "script": {"last_deployed_from": "wrangler"},
            "bindings": [
                {"name": "HELLOADA_RELEASE_SHA", "type": "plain_text", "text": SOURCE_SHA},
                {"name": "HELLOADA_TENANT_ID", "type": "plain_text", "text": TENANT},
                {
                    "name": "MAILFLARE_REALTIME",
                    "type": "durable_object_namespace",
                    "class_name": "RealtimeHub",
                    "namespace_id": "namespace-1",
                },
            ],
        },
    }


def _health() -> dict:
    return {
        "ok": True,
        "tenant": TENANT,
        "releaseSha": SOURCE_SHA,
        "payloadSchema": "ready",
        "migrationHead": "f" * 64,
        "schemaIdentity": "e" * 64,
        "schemaRevision": 7,
        "payloadAdmin": "0.10.9",
        "payloadCore": "0.5.7",
        "contentContract": "helloada-content-v1",
    }


def _prepare(tmp_path: Path) -> tuple[Path, dict, bytes]:
    receipt = _receipt()
    receipt_path = tmp_path / "runs" / TENANT / RELEASE_ID / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    raw = (json.dumps(receipt, indent=2) + "\n").encode()
    receipt_path.write_bytes(raw)
    return receipt_path, receipt, raw


def _mock_cloudflare(monkeypatch: pytest.MonkeyPatch, *, current_deployment: str = "new-deployment") -> None:
    def api_result(url: str, environment):
        if url.endswith("/deployments"):
            return {
                "deployments": [{
                    "id": current_deployment,
                    "created_on": DEPLOYED_AT,
                    "source": "wrangler",
                    "versions": [{"version_id": "new-version", "percentage": 100}],
                }],
            }
        if url.endswith("/versions/new-version"):
            return _version()
        if url.endswith("/namespaces?per_page=1000"):
            return [{
                "id": "namespace-1",
                "name": f"{TENANT}_RealtimeHub",
                "class": "RealtimeHub",
            }]
        raise AssertionError(f"unexpected Cloudflare API URL: {url}")

    monkeypatch.setattr(reconciliation, "_api_result", api_result)
    monkeypatch.setattr(reconciliation, "_health_json", lambda url: _health())


def test_reconcile_records_exact_live_state_without_mutating_terminal_receipt(tmp_path, monkeypatch):
    receipt_path, receipt, original_bytes = _prepare(tmp_path)
    _mock_cloudflare(monkeypatch)

    evidence = reconciliation.reconcile_lifecycle_receipt(
        tmp_path, TENANT, receipt, {"health": "https://oceanicvibes.com/api/health"},
        {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "secret"},
        PIPELINE_SHA,
    )

    assert evidence["status"] == "verified"
    assert evidence["proof"]["deployment"] == {
        "id": "new-deployment",
        "createdAt": DEPLOYED_AT,
        "versionId": "new-version",
        "percentage": 100,
    }
    assert evidence["proof"]["namespace"]["id"] == "namespace-1"
    assert receipt_path.read_bytes() == original_bytes
    assert reconciliation.read_lifecycle_reconciliation(tmp_path, TENANT, receipt) == evidence


def test_reconcile_fails_closed_when_previous_deployment_is_still_active(tmp_path, monkeypatch):
    _, receipt, _ = _prepare(tmp_path)
    _mock_cloudflare(monkeypatch, current_deployment="old-deployment")

    with pytest.raises(reconciliation.LifecycleReconciliationError, match="exact atomic release window"):
        reconciliation.reconcile_lifecycle_receipt(
            tmp_path, TENANT, receipt, {"health": "https://oceanicvibes.com/api/health"},
            {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "secret"},
            PIPELINE_SHA,
        )


def test_reconcile_fails_closed_when_public_marker_differs(tmp_path, monkeypatch):
    _, receipt, _ = _prepare(tmp_path)
    _mock_cloudflare(monkeypatch)
    monkeypatch.setattr(reconciliation, "_health_json", lambda url: {**_health(), "releaseSha": "9" * 40})

    with pytest.raises(reconciliation.LifecycleReconciliationError, match="public health"):
        reconciliation.reconcile_lifecycle_receipt(
            tmp_path, TENANT, receipt, {"health": "https://oceanicvibes.com/api/health"},
            {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "secret"},
            PIPELINE_SHA,
        )


def test_existing_evidence_is_bound_to_exact_receipt_bytes(tmp_path, monkeypatch):
    receipt_path, receipt, _ = _prepare(tmp_path)
    _mock_cloudflare(monkeypatch)
    reconciliation.reconcile_lifecycle_receipt(
        tmp_path, TENANT, receipt, {"health": "https://oceanicvibes.com/api/health"},
        {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "secret"},
        PIPELINE_SHA,
    )
    receipt_path.write_text(receipt_path.read_text() + " ")

    with pytest.raises(reconciliation.LifecycleReconciliationError, match="immutable failed receipt"):
        reconciliation.read_lifecycle_reconciliation(tmp_path, TENANT, receipt)
