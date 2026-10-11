from __future__ import annotations

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
