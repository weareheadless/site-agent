from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from site_agent.application.shared_runtime_rollout import (
    SharedRuntimeRolloutError,
    plan_shared_runtime_rollout,
)

FINGERPRINT = "f" * 64
OLD_FINGERPRINT = "e" * 64
SHA = "a" * 40


def _receipt(root: Path, tenant: str, release_id: str, *, source_sha: str = SHA,
             fingerprint: str = OLD_FINGERPRINT, status: str = "deployed", finished: str = "2026-10-01T00:00:00Z"):
    run = root / "runs" / tenant / release_id
    run.mkdir(parents=True, exist_ok=True)
    (run / "receipt.json").write_text(json.dumps({
        "releaseId": release_id,
        "sourceSha": source_sha,
        "sharedRuntimeFingerprint": fingerprint,
        "status": status,
        "finishedAt": finished,
    }))


def _registry():
    return {"customers": {
        "oceanicvibes": {"sharedRuntimeUpdate": "canary"},
        "atelier-harmonie": {"sharedRuntimeUpdate": "automatic"},
        "northstar": {"sharedRuntimeUpdate": "automatic"},
        "legacy-test": {"sharedRuntimeUpdate": "manual"},
    }}


def _queue():
    return {"schema": 1, "releases": {}}


def test_first_step_queues_only_canary_from_last_successful_source(tmp_path):
    _receipt(tmp_path, "oceanicvibes", "oceanic-last", source_sha="1" * 40)

    plan = plan_shared_runtime_rollout(
        _registry(), _queue(), tmp_path, FINGERPRINT,
        now=datetime(2026, 10, 10, tzinfo=timezone.utc),
    )

    assert plan["state"] == "canary-queued"
    assert set(plan["queued"]) == {"oceanicvibes"}
    request = plan["queued"]["oceanicvibes"]
    assert request["sha"] == "1" * 40
    assert request["sharedRuntimeFingerprint"] == FINGERPRINT
    assert request["id"].startswith("runtime-20261010000000-")


def test_pending_canary_release_is_not_replaced(tmp_path):
    _receipt(tmp_path, "oceanicvibes", "oceanic-last")
    queue = {"releases": {"oceanicvibes": {"id": "approved-site-change", "sha": SHA}}}

    plan = plan_shared_runtime_rollout(_registry(), queue, tmp_path, FINGERPRINT)

    assert plan["state"] == "canary-pending"
    assert plan["queued"] == {}


def test_failed_canary_holds_automatic_rollout_without_retry(tmp_path):
    _receipt(tmp_path, "oceanicvibes", "oceanic-last")
    _receipt(tmp_path, "oceanicvibes", "failed-runtime", fingerprint=FINGERPRINT, status="failed")
    queue = {"releases": {"oceanicvibes": {
        "id": "failed-runtime", "sha": SHA, "sharedRuntimeFingerprint": FINGERPRINT,
    }}}

    plan = plan_shared_runtime_rollout(_registry(), queue, tmp_path, FINGERPRINT)

    assert plan == {
        "state": "canary-failed",
        "canaryTenant": "oceanicvibes",
        "queued": {},
        "blocked": ["oceanicvibes"],
    }


def test_reconciled_atomic_canary_gets_a_new_id_before_any_fanout(tmp_path):
    _receipt(tmp_path, "oceanicvibes", "oceanic-last", source_sha="1" * 40)
    release_id = "failed-runtime"
    source_sha = "2" * 40
    receipt = {
        "tenant": "oceanicvibes",
        "releaseId": release_id,
        "sourceSha": source_sha,
        "sharedRuntimeFingerprint": FINGERPRINT,
        "worker": "oceanicvibes",
        "status": "failed",
        "rolloutMode": "atomic",
        "durableObjectLifecycle": {
            "identity": "d" * 64,
            "state": "outcome-unknown",
            "strategy": "atomic",
        },
    }
    receipt_bytes = (json.dumps(receipt, indent=2) + "\n").encode()
    receipt_path = tmp_path / "runs" / "oceanicvibes" / release_id / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(receipt_bytes)
    evidence = {
        "schema": 1,
        "tenant": "oceanicvibes",
        "releaseId": release_id,
        "receiptSha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "sourceSha": source_sha,
        "sharedRuntimeFingerprint": FINGERPRINT,
        "migrationIdentity": "d" * 64,
        "pipelineSha": "e" * 40,
        "status": "verified",
        "verifiedAt": "2026-10-11T04:00:00+00:00",
        "proof": {
            "deployment": {
                "id": "deployment-new",
                "versionId": "version-new",
                "percentage": 100,
            },
            "version": {
                "id": "version-new",
                "releaseSha": source_sha,
                "tenant": "oceanicvibes",
            },
            "namespace": {
                "id": "namespace-id",
                "class": "RealtimeHub",
                "name": "oceanicvibes_RealtimeHub",
                "binding": "MAILFLARE_REALTIME",
            },
            "health": {
                "tenant": "oceanicvibes",
                "releaseSha": source_sha,
                "ok": True,
                "payloadSchema": "ready",
            },
        },
    }
    evidence_path = tmp_path / "reconciliations" / "oceanicvibes" / f"{release_id}.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(json.dumps(evidence))
    queue = {"releases": {"oceanicvibes": {
        "id": release_id,
        "sha": source_sha,
        "sharedRuntimeFingerprint": FINGERPRINT,
    }}}

    plan = plan_shared_runtime_rollout(
        _registry(), queue, tmp_path, FINGERPRINT,
        now=datetime(2026, 10, 11, 4, 1, tzinfo=timezone.utc),
    )

    request = plan["queued"]["oceanicvibes"]
    assert plan["state"] == "canary-queued"
    assert set(plan["queued"]) == {"oceanicvibes"}
    assert request["id"] != release_id
    assert request["sha"] == source_sha
    assert request["sharedRuntimeFingerprint"] == FINGERPRINT


def test_successful_canary_queues_bounded_batch_with_exact_customer_source(tmp_path):
    _receipt(tmp_path, "oceanicvibes", "oceanic-current", fingerprint=FINGERPRINT)
    _receipt(tmp_path, "atelier-harmonie", "atelier-latest", source_sha="1" * 40)
    _receipt(tmp_path, "northstar", "northstar-latest", source_sha="2" * 40)
    _receipt(tmp_path, "legacy-test", "legacy-latest", source_sha="3" * 40)

    plan = plan_shared_runtime_rollout(
        _registry(), _queue(), tmp_path, FINGERPRINT, batch_size=1,
        now=datetime(2026, 10, 10, tzinfo=timezone.utc),
    )

    assert plan["state"] == "batch-queued"
    assert set(plan["queued"]) == {"atelier-harmonie"}
    request = plan["queued"]["atelier-harmonie"]
    assert request["sha"] == "1" * 40
    assert request["sharedRuntimeFingerprint"] == FINGERPRINT


def test_successful_tenant_is_not_queued_twice_and_failed_tenant_is_reported(tmp_path):
    _receipt(tmp_path, "oceanicvibes", "oceanic-current", fingerprint=FINGERPRINT)
    _receipt(tmp_path, "atelier-harmonie", "atelier-current", fingerprint=FINGERPRINT)
    _receipt(tmp_path, "northstar", "northstar-last")
    _receipt(tmp_path, "northstar", "northstar-failed", fingerprint=FINGERPRINT, status="failed")
    queue = {"releases": {"northstar": {
        "id": "northstar-failed", "sha": SHA, "sharedRuntimeFingerprint": FINGERPRINT,
    }}}

    plan = plan_shared_runtime_rollout(_registry(), queue, tmp_path, FINGERPRINT)

    assert plan["state"] == "blocked"
    assert plan["queued"] == {}
    assert plan["blocked"] == ["northstar"]


def test_automatic_rollout_requires_exactly_one_canary(tmp_path):
    registry = {"customers": {"tenant": {"sharedRuntimeUpdate": "automatic"}}}

    with pytest.raises(SharedRuntimeRolloutError, match="exactly one"):
        plan_shared_runtime_rollout(registry, _queue(), tmp_path, FINGERPRINT)


def test_manual_only_registry_does_not_queue_any_releases(tmp_path):
    plan = plan_shared_runtime_rollout(
        {"customers": {"legacy": {"sharedRuntimeUpdate": "manual"}}},
        _queue(),
        tmp_path,
        FINGERPRINT,
    )

    assert plan["state"] == "no-automatic-tenants"
    assert plan["queued"] == {}


def test_existing_run_without_receipt_blocks_canary_retry(tmp_path):
    _receipt(tmp_path, "oceanicvibes", "oceanic-last")
    incomplete = tmp_path / "runs" / "oceanicvibes" / "runtime-incomplete"
    incomplete.mkdir(parents=True)
    queue = {"releases": {"oceanicvibes": {
        "id": "runtime-incomplete", "sha": SHA, "sharedRuntimeFingerprint": FINGERPRINT,
    }}}

    plan = plan_shared_runtime_rollout(_registry(), queue, tmp_path, FINGERPRINT)

    assert plan["state"] == "canary-failed"
    assert plan["blocked"] == ["oceanicvibes"]
    assert plan["queued"] == {}
