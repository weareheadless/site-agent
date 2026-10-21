"""Production approvals persist only through the central VPS release queue."""
from __future__ import annotations

import json

import pytest

from site_agent.application import source_deployment as deployment
from site_agent.application.source_deployment import SourceDeploymentError
from site_agent.application.workspace import ChatService
from site_agent.core.memory import Memory


class HeldExecutor:
    def __init__(self, **kwargs):
        self.submitted = []

    def submit(self, fn, *args):
        self.submitted.append((fn, args))

    def shutdown(self, **kwargs):
        pass


def make_service(tmp_path, monkeypatch, jobs=None, *, draft_status="publishing"):
    monkeypatch.setattr(deployment, "ThreadPoolExecutor", HeldExecutor)
    release_root = tmp_path / "release-receipts"
    release_root.mkdir(exist_ok=True)
    memory = Memory(tmp_path / "memory.db")
    draft_id = memory.save_draft("Reviewed candidate", "", kind="merge", meta={
        "preview": {"status": "ready", "job_id": "preview"},
    })
    if draft_status:
        memory.update_draft_status(draft_id, draft_status)
    if jobs:
        memory.kv_set("source_preview_jobs", jobs)
    config = {
        "instance_name": "demo",
        "deployment_pipeline": {"release_root": str(release_root)},
        "site": {"branch": "main", "preview_branch": "preview"},
    }
    return memory, deployment.SourceDeploymentService(config, env={}, memory=memory), draft_id, release_root


def release_job(draft_id, status="queued", **extra):
    return dict(
        id="publish",
        status=status,
        ok=True,
        mode="production",
        branch="main",
        commit="a" * 40,
        draft_id=draft_id,
        tenant_id="demo",
        release_id="20261004-validation-1",
        publish_summary="Reviewed candidate",
        publish_path="site",
        publish_version_type="merge",
        created_at="2026-10-04T00:00:00+00:00",
        updated_at="2026-10-04T00:00:00+00:00",
        **extra,
    )


def deployed_receipt(draft_id):
    return {
        "tenant": "demo",
        "releaseId": "20261004-validation-1",
        "sourceSha": "a" * 40,
        "approvalId": draft_id,
        "status": "deployed",
        "pipelineSha": "c" * 40,
        "uploadedVersion": "version-1",
        "connectionVerifiedAt": "2026-10-04T00:01:00+00:00",
        "finishedAt": "2026-10-04T00:01:00+00:00",
    }


def test_approval_queues_the_exact_sha_once_without_a_local_production_worker(tmp_path, monkeypatch):
    memory, service, draft_id, _release_root = make_service(tmp_path, monkeypatch, draft_status="pending")
    calls = []
    monkeypatch.setattr(service, "_head", lambda branch: "a" * 40)

    def request_release(config, env, source_sha, *, approval_id):
        calls.append((config, source_sha, approval_id))
        return {"release_id": "20261004-validation-1", "control_sha": "c" * 40}

    monkeypatch.setattr(deployment, "request_release", request_release)
    request = {"mode": "production", "branch": "main", "commit": "a" * 40, "draft_id": draft_id}

    queued = service.start(request, allow_production=True)
    repeated = service.start(request, allow_production=True)

    assert queued["status"] == "queued"
    assert queued["phase"] == "queued_on_vps"
    assert queued["commit"] == "a" * 40
    assert repeated["id"] == queued["id"]
    assert len(calls) == 1
    assert calls[0][1:] == ("a" * 40, draft_id)
    assert memory.list_drafts()[0]["status"] == "publishing"
    assert service._executor.submitted == []
    assert memory.list_publishes() == []
    service.close()
    memory.close()


def test_production_queue_rejects_a_sha_that_is_not_the_current_main_head(tmp_path, monkeypatch):
    memory, service, draft_id, _release_root = make_service(tmp_path, monkeypatch, draft_status="pending")
    called = []
    monkeypatch.setattr(service, "_head", lambda _branch: "b" * 40)
    monkeypatch.setattr(deployment, "request_release", lambda *args, **kwargs: called.append(True))
    with pytest.raises(SourceDeploymentError, match="exact main revision"):
        service.start({"mode": "production", "branch": "main", "commit": "a" * 40, "draft_id": draft_id}, allow_production=True)
    assert not called
    assert memory.list_drafts()[0]["status"] == "pending"
    service.close()
    memory.close()


def test_restart_reconciles_the_exact_central_deployment_receipt_once(tmp_path, monkeypatch):
    memory, _unused, draft_id, release_root = make_service(
        tmp_path, monkeypatch, {"publish": release_job(1)},
    )
    _unused.close()
    # Use the actual persisted draft ID in both the job and VPS receipt.
    jobs = {"publish": release_job(draft_id)}
    memory.kv_set("source_preview_jobs", jobs)
    receipt_path = release_root / "runs/demo/20261004-validation-1/receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(deployed_receipt(draft_id)))

    service = deployment.SourceDeploymentService(
        {
            "instance_name": "demo",
            "deployment_pipeline": {"release_root": str(release_root)},
        }, env={}, memory=memory,
    )
    assert service.status("publish")["status"] == "deployed"
    assert memory.list_drafts()[0]["status"] == "live"
    assert len(memory.list_publishes()) == 1
    assert service._executor.submitted == []
    service.close()

    again = deployment.SourceDeploymentService(
        {
            "instance_name": "demo",
            "deployment_pipeline": {"release_root": str(release_root)},
        }, env={}, memory=memory,
    )
    assert again.status("publish")["status"] == "deployed"
    assert len(memory.list_publishes()) == 1
    assert again._executor.submitted == []
    again.close()
    memory.close()


def test_failed_central_receipt_fails_the_review_and_preserves_preview(tmp_path, monkeypatch):
    memory, original, draft_id, release_root = make_service(
        tmp_path, monkeypatch, {"publish": release_job(1)},
    )
    original.close()
    memory.kv_set("source_preview_jobs", {"publish": release_job(draft_id)})
    path = release_root / "runs/demo/20261004-validation-1/receipt.json"
    path.parent.mkdir(parents=True)
    receipt = deployed_receipt(draft_id) | {"status": "failed", "stage": "build", "error": "typecheck failed"}
    path.write_text(json.dumps(receipt))

    service = deployment.SourceDeploymentService(
        {"instance_name": "demo", "deployment_pipeline": {"release_root": str(release_root)}},
        env={}, memory=memory,
    )
    assert service.status("publish")["status"] == "failed"
    draft = memory.list_drafts()[0]
    assert draft["status"] == "publish_failed"
    assert draft["meta"]["preview"]["job_id"] == "preview"
    assert memory.list_publishes() == []
    service.close()
    memory.close()


def test_missing_release_identity_cannot_leave_an_approval_stuck_publishing(tmp_path, monkeypatch):
    memory, service, draft_id, _release_root = make_service(
        tmp_path, monkeypatch,
        {"publish": {"id": "publish", "status": "queued", "mode": "production", "draft_id": 1}},
    )
    assert memory.list_drafts()[0]["status"] == "publish_failed"
    assert service.status("publish")["status"] == "failed"
    assert "no durable central release identity" in service.status("publish")["error"]
    service.close()
    memory.close()


def test_unmatched_publishing_draft_is_terminal_after_restart(tmp_path, monkeypatch):
    memory, service, _draft_id, _release_root = make_service(tmp_path, monkeypatch, jobs=None)
    assert memory.list_drafts()[0]["status"] == "publish_failed"
    service.close()
    memory.close()


def test_workspace_approval_retries_do_not_merge_or_queue_twice(tmp_path, monkeypatch):
    memory, deployer, draft_id, _release_root = make_service(tmp_path, monkeypatch, draft_status="pending")
    calls = []
    monkeypatch.setattr(deployer, "_head", lambda _branch: "a" * 40)
    monkeypatch.setattr(
        deployment,
        "request_release",
        lambda _config, _env, sha, *, approval_id: calls.append((sha, approval_id))
        or {"release_id": "20261004-validation-1", "control_sha": "c" * 40},
    )

    class Adapter:
        def __init__(self):
            self.calls = 0

        def merge_preview(self, *args):
            self.calls += 1
            return {"merged": True, "commit_sha": "a" * 40, "parent_sha": "b" * 40, "path": "preview->main"}

    adapter = Adapter()
    chat = ChatService(memory, object(), source_deployment=deployer)
    monkeypatch.setattr(chat, "_merge_adapter", lambda _tenant: adapter)

    first = chat.approve_draft(draft_id)
    second = chat.approve_draft(draft_id)

    assert first["status"] == "publishing"
    assert second["idempotent"] is True
    assert adapter.calls == 1
    assert calls == [("a" * 40, draft_id)]
    assert memory.list_drafts()[0]["status"] == "publishing"
    assert memory.list_publishes() == []
    assert deployer._executor.submitted == []
    deployer.close()
    memory.close()


def test_queue_failure_retains_the_approved_merge_and_retry_does_not_merge_again(tmp_path, monkeypatch):
    from site_agent.application.workspace import BridgeError
    from site_agent.application.release_queue import ReleaseQueueError
    memory, deployer, draft_id, _root = make_service(tmp_path, monkeypatch, draft_status='pending')
    monkeypatch.setattr(deployer, '_head', lambda _branch: 'a' * 40)
    calls = []
    def request_release(_config, _env, sha, *, approval_id):
        assert memory.get_draft(draft_id)['meta']['approved_release']['commit'] == sha
        calls.append((sha, approval_id))
        if len(calls) == 1:
            raise ReleaseQueueError('queue unavailable')
        return {'release_id': '20261004-validation-1', 'control_sha': 'c' * 40}
    monkeypatch.setattr(deployment, 'request_release', request_release)
    class Adapter:
        calls = 0
        def merge_preview(self, *args):
            self.calls += 1
            return {'merged': True, 'commit_sha': 'a' * 40, 'parent_sha': 'b' * 40}
    adapter = Adapter()
    chat = ChatService(memory, object(), source_deployment=deployer)
    monkeypatch.setattr(chat, '_merge_adapter', lambda _tenant: adapter)
    with pytest.raises(BridgeError, match='live deployment could not be queued'):
        chat.approve_draft(draft_id)
    assert memory.get_draft(draft_id)['status'] == 'publish_failed'
    result = chat.approve_draft(draft_id)
    assert result['status'] == 'publishing'
    assert adapter.calls == 1
    assert calls == [('a' * 40, draft_id)] * 2
    assert chat.approve_draft(draft_id)['idempotent'] is True
    assert len(calls) == 2
    with pytest.raises(BridgeError, match='cannot change'):
        chat._start_approved_release(memory, draft_id, deployer.start, {
            **memory.get_draft(draft_id)['meta']['approved_release'], 'commit': 'd' * 40,
        })
    assert memory.list_publishes() == []
    assert deployer._executor.submitted == []
    deployer.close()
    memory.close()


def test_compiled_preview_recovery_retains_publishing_draft_status(tmp_path, monkeypatch):
    memory, service, draft_id, _release_root = make_service(tmp_path, monkeypatch)
    memory.update_draft_status(draft_id, "publishing")
    service._sync_compiled_preview_draft(
        {"id": "preview", "draft_id": draft_id, "mode": "compiled_preview"},
        {"status": "ready", "commit": "a" * 40, "runtime_path": "/preview/runtime"},
    )
    draft = memory.list_drafts()[0]
    assert draft["status"] == "publishing"
    assert draft["meta"]["preview"]["runtime_path"] == "/preview/runtime"
    service.close()
    memory.close()
