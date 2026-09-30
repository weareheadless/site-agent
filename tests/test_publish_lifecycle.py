"""Publish lifecycle regressions: all adapters and runtimes are local fakes."""
import threading

from site_agent.application import source_deployment as deployment
from site_agent.application.workspace import ChatService
from site_agent.core.memory import Memory


class HeldExecutor:
    def __init__(self, **kwargs):
        self.submitted = []

    def submit(self, fn, *args):
        self.submitted.append((fn, args))

    def shutdown(self, **kwargs):
        pass


def make_service(tmp_path, monkeypatch, jobs=None):
    monkeypatch.setattr(deployment, "ThreadPoolExecutor", HeldExecutor)
    memory = Memory(tmp_path / "memory.db")
    draft_id = memory.save_draft("Reviewed candidate", "", kind="merge", meta={
        "preview": {"status": "ready", "job_id": "preview"},
    })
    memory.update_draft_status(draft_id, "publishing")
    if jobs:
        memory.kv_set("source_preview_jobs", jobs)
    return memory, deployment.SourceDeploymentService({}, memory=memory), draft_id


def job(status="running", **extra):
    return dict(id="publish", status=status, mode="production", branch="main",
                commit="a" * 40, draft_id=1, **extra)


def test_restart_verifies_interrupted_publish_without_redeploying(tmp_path, monkeypatch):
    memory, service, draft_id = make_service(tmp_path, monkeypatch, {"publish": job()})
    monkeypatch.setattr(service, "_runtime_url", lambda: "https://example.test")
    monkeypatch.setattr(service, "_verify_public_revision", lambda *a, **kw: {"ok": True, "commit": "a" * 40})
    assert service._executor.submitted
    for fn, args in service._executor.submitted:
        fn(*args)
    assert service.status("publish")["status"] == "deployed"
    assert memory.list_drafts()[0]["status"] == "live"
    service.close()
    # Reconciliation is safe to repeat and cannot duplicate version history.
    again = deployment.SourceDeploymentService({}, memory=memory)
    assert len(memory.list_publishes()) == 1
    again.close()
    memory.close()


def test_restart_failed_job_reconciles_stranded_publishing_draft(tmp_path, monkeypatch):
    memory, service, _ = make_service(tmp_path, monkeypatch, {"publish": job("failed", error="build failed")})
    assert memory.list_drafts()[0]["status"] == "publish_failed"
    assert not service._executor.submitted
    service.close()
    memory.close()


def test_queue_persists_publishing_before_detached_worker_and_deduplicates(tmp_path, monkeypatch):
    memory, service, draft_id = make_service(tmp_path, monkeypatch)
    memory.update_draft_status(draft_id, "pending")
    request = {"mode": "production", "branch": "main", "commit": "a" * 40, "draft_id": draft_id}
    queued = service.start(request, allow_production=True)
    assert memory.list_drafts()[0]["status"] == "publishing"
    assert memory.kv_get("source_preview_jobs")[queued["id"]]["status"] == "queued"
    assert service.start(request, allow_production=True)["id"] == queued["id"]
    assert len(service._executor.submitted) == 1
    service.close()
    memory.close()


def test_preview_selection_survives_newer_production_job(tmp_path, monkeypatch):
    memory, service, _ = make_service(tmp_path, monkeypatch)
    service._jobs = {
        "preview": {"id": "preview", "mode": "compiled_preview", "status": "ready", "updated_at": "2026-01-01"},
        "publish": job(updated_at="2026-01-02"),
    }
    assert service.latest_preview()["id"] == "preview"
    service.close()
    memory.close()


def test_job_audit_not_evicted_after_twenty_newer_jobs(tmp_path, monkeypatch):
    memory, service, _ = make_service(tmp_path, monkeypatch)
    service._jobs = {str(i): job("failed", updated_at=str(i).zfill(3)) | {"id": str(i)} for i in range(25)}
    service._persist()
    assert len(memory.kv_get("source_preview_jobs")) == 25
    service.close()
    memory.close()


def test_verification_identifies_service_instead_of_blocked_python_user_agent(tmp_path, monkeypatch):
    memory, service, _ = make_service(tmp_path, monkeypatch)

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b"a" * 40

    def open_request(request, **kwargs):
        assert request.get_header("User-agent") == "site-agent/1.0"
        return Response()

    monkeypatch.setattr(deployment.urllib.request, "urlopen", open_request)
    assert service._verify_public_revision("https://example.test", "a" * 40, label="live site")["ok"]
    service.close()
    memory.close()


def test_restart_verification_failure_is_terminal_and_keeps_preview(tmp_path, monkeypatch):
    memory, service, _ = make_service(tmp_path, monkeypatch, {"publish": job()})
    monkeypatch.setattr(service, "_runtime_url", lambda: "https://example.test")
    def fail(*args, **kwargs):
        raise deployment.SourceDeploymentError("live site verification did not confirm commit")
    monkeypatch.setattr(service, "_verify_public_revision", fail)
    for fn, args in service._executor.submitted:
        fn(*args)
    assert service.status("publish")["status"] == "failed"
    draft = memory.list_drafts()[0]
    assert draft["status"] == "publish_failed"
    assert draft["meta"]["preview"]["job_id"] == "preview"
    assert memory.list_publishes() == []
    service.close()
    memory.close()


def test_restart_resumes_queued_exact_revision(tmp_path, monkeypatch):
    memory, service, _ = make_service(tmp_path, monkeypatch, {"publish": job("queued")})
    assert service._executor.submitted == [(service._run_job, ("publish", "main", "a" * 40, "production"))]
    service.close()
    memory.close()


def test_orphaned_publish_is_terminal_after_restart(tmp_path, monkeypatch):
    memory, service, _ = make_service(tmp_path, monkeypatch)
    assert memory.list_drafts()[0]["status"] == "publish_failed"
    service.close()
    memory.close()


def test_worker_completes_after_request_returns_without_browser_polling(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    draft_id = memory.save_draft("Candidate", "", kind="merge")
    service = deployment.SourceDeploymentService({}, memory=memory)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(service, "_head", lambda branch: "a" * 40)
    def build(*args):
        entered.set()
        assert release.wait(5)
        return {"status": "deployed", "ok": True, "commit": "a" * 40, "live": True}
    monkeypatch.setattr(service, "_build", build)
    original = service._record_production_publish
    def record(*args):
        original(*args)
        finished.set()
    monkeypatch.setattr(service, "_record_production_publish", record)
    try:
        queued = service.start({"mode": "production", "branch": "main", "commit": "a" * 40, "draft_id": draft_id}, allow_production=True)
        assert entered.wait(5)
        assert queued["status"] == "queued"
        assert memory.list_drafts()[0]["status"] == "publishing"
        release.set()
        assert finished.wait(5)
        assert memory.list_drafts()[0]["status"] == "live"
        assert memory.kv_get("source_preview_jobs")[queued["id"]]["status"] == "deployed"
    finally:
        release.set()
        service.close()
        memory.close()


def test_fast_publish_cannot_be_overwritten_and_approval_retry_does_not_merge(tmp_path, monkeypatch):
    memory, deployer, draft_id = make_service(tmp_path, monkeypatch)
    memory.update_draft_status(draft_id, "pending")
    class ImmediateExecutor(HeldExecutor):
        def submit(self, fn, *args):
            fn(*args)
    deployer._executor = ImmediateExecutor()
    monkeypatch.setattr(deployer, "_head", lambda branch: "a" * 40)
    monkeypatch.setattr(deployer, "_build", lambda *args: {"status": "deployed", "commit": "a" * 40, "live": True})
    class Adapter:
        calls = 0
        def merge_preview(self, *args):
            self.calls += 1
            return {"merged": True, "commit_sha": "a" * 40}
    adapter = Adapter()
    service = ChatService(memory, object(), source_deployment=deployer)
    monkeypatch.setattr(service, "_merge_adapter", lambda tenant: adapter)
    first = service.approve_draft(draft_id)
    assert first["status"] == "live"
    assert memory.list_drafts()[0]["status"] == "live"
    assert service.approve_draft(draft_id)["idempotent"] is True
    assert adapter.calls == 1
    assert len(memory.list_publishes()) == 1
    deployer.close()
    memory.close()


def test_compiled_preview_recovery_retains_publishing_draft_status(tmp_path, monkeypatch):
    memory, service, draft_id = make_service(tmp_path, monkeypatch)
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
