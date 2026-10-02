from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import threading

import pytest

from site_agent.application import source_deployment
from site_agent.core.memory import Memory


def test_revision_marker_is_written_only_to_the_detached_worktree(tmp_path):
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path), "preview_branch": "preview"}},
    )
    try:
        marker = service._write_revision_marker(tmp_path, "A" * 40)
        assert marker.read_text(encoding="utf-8") == ("a" * 40) + "\n"
        assert marker.relative_to(tmp_path).as_posix() == "public/site-agent-revision.txt"
    finally:
        service.close()


def test_missing_repo_inventory_uses_host_owned_fallback(tmp_path):
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path), "preview_branch": "preview"}},
    )
    try:
        command = service._inventory_command(tmp_path, tmp_path)
        assert command[:2] == [sys.executable, str(source_deployment.Path(source_deployment.__file__).with_name("source_inventory.py").resolve())]
        assert command[-2:] == ["--root", str(tmp_path)]
    finally:
        service.close()


def test_source_deployment_build_environment_forces_production_mode(tmp_path):
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path), "preview_branch": "preview"}},
        env={"NODE_ENV": "development", "PATH": "/usr/bin:/bin"},
    )
    try:
        assert service._child_env()["NODE_ENV"] == "development"
        assert service._child_env(production=True)["NODE_ENV"] == "production"
    finally:
        service.close()


def test_source_deployment_prefers_configured_supported_node_runtime(tmp_path):
    node_bin = tmp_path / "node-bin"
    node_bin.mkdir()
    (node_bin / "node").touch()
    service = source_deployment.SourceDeploymentService(
        {
            "site": {
                "clone_path": str(tmp_path),
                "preview_branch": "preview",
                "source_deployment": {"node_path": str(node_bin)},
            }
        },
        env={"NODE_ENV": "development", "PATH": "/usr/bin:/bin"},
    )
    try:
        assert service._child_env()["PATH"].split(source_deployment.os.pathsep)[0] == str(node_bin)
    finally:
        service.close()


def test_public_revision_verification_requires_the_exact_commit(tmp_path):
    expected = "b" * 40

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler API
            if self.path.split("?", 1)[0] != "/site-agent-revision.txt":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write((expected + "\n").encode("utf-8"))

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    service = source_deployment.SourceDeploymentService(
        {
            "site": {"clone_path": str(tmp_path), "preview_branch": "preview"},
            "source_deployment": {"verification_timeout_seconds": 30},
        },
    )
    try:
        result = service._verify_public_revision(
            f"http://127.0.0.1:{server.server_port}",
            expected,
            label="test runtime",
        )
        assert result["ok"] is True
        assert result["commit"] == expected
    finally:
        service.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_compiled_preview_rebuilds_exact_commit_after_process_restart(monkeypatch, tmp_path):
    class Executor:
        def __init__(self, *args, **kwargs):
            self.submitted = []

        def submit(self, function, *args):
            self.submitted.append((function, args))

        def shutdown(self, **kwargs):
            return None

    monkeypatch.setattr(source_deployment, "ThreadPoolExecutor", Executor)
    memory = Memory(tmp_path / "memory.db")
    memory.kv_set(
        "source_preview_jobs",
        {
            "preview-job": {
                "id": "preview-job",
                "status": "ready",
                "ok": True,
                "branch": "preview",
                "commit": "a" * 40,
                "mode": "compiled_preview",
                "created_at": "2026-09-22T00:00:00+00:00",
                "updated_at": "2026-09-22T00:01:00+00:00",
                "runtime_path": "/old/runtime",
                "runtime_port": 34509,
            }
        },
    )

    service = source_deployment.SourceDeploymentService(
        {
            "site": {
                "repository": "owner/site",
                "branch": "main",
                "preview_branch": "preview",
                "clone_path": str(tmp_path),
            }
        },
        memory=memory,
    )

    job = service.status("preview-job")
    assert job["status"] == "queued"
    assert job["error"] == "source deployment process restarted; rebuilding the exact preview commit"
    assert "runtime_path" not in job
    assert "runtime_port" not in job
    assert len(service._executor.submitted) == 1
    function, args = service._executor.submitted[0]
    assert function == service._run_job
    assert args == ("preview-job", "preview", "a" * 40, "compiled_preview")

    service.close()
    memory.close()


def test_production_mode_requires_the_workspace_approval_boundary(tmp_path):
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path), "preview_branch": "preview"}},
    )
    try:
        with pytest.raises(source_deployment.SourceDeploymentError, match="explicit owner approval"):
            service.start({"mode": "production", "branch": "main", "commit": "a" * 40})
    finally:
        service.close()


def test_compiled_preview_completion_reconciles_pending_draft(monkeypatch, tmp_path):
    memory = Memory(tmp_path / "memory.db")
    draft_id = memory.save_draft(
        "Preview blocked: Homepage spacing",
        "diff",
        kind="merge",
        meta={
            "head_sha": "a" * 40,
            "preview": {
                "mode": "compile",
                "status": "building",
                "requires_build": True,
                "job_id": "preview-job",
                "head_sha": "a" * 40,
            },
        },
    )
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path), "preview_branch": "preview"}},
        memory=memory,
    )
    service._jobs = {
        "preview-job": {
            "id": "preview-job",
            "status": "running",
            "ok": True,
            "branch": "preview",
            "commit": "a" * 40,
            "mode": "compiled_preview",
            "draft_id": draft_id,
            "error": "stale restart notice",
        }
    }
    monkeypatch.setattr(service, "_head", lambda branch: "a" * 40)
    monkeypatch.setattr(
        service,
        "_build",
        lambda job, branch, commit, mode: {
            "ok": True,
            "status": "ready",
            "mode": "compiled_preview",
            "branch": branch,
            "commit": commit,
            "runtime_path": "/api/workspace/source/preview/preview-job/runtime",
            "preview_url": "/api/workspace/source/preview/preview-job/runtime/",
            "deployment_mode": "isolated_host_runtime",
        },
    )

    service._run_job("preview-job", "preview", "a" * 40, "compiled_preview")

    draft = memory.list_drafts(limit=10)[0]
    assert draft["title"].startswith("Preview ready:")
    assert draft["meta"]["preview"]["status"] == "ready"
    assert draft["meta"]["preview"]["requires_build"] is False
    assert draft["meta"]["preview"]["runtime_path"].endswith("/runtime")
    assert "error" not in service.status("preview-job")
    service.close()
    memory.close()


def test_compiled_preview_failure_blocks_pending_draft(monkeypatch, tmp_path):
    memory = Memory(tmp_path / "memory.db")
    draft_id = memory.save_draft(
        "Preview preparing: Homepage spacing",
        "diff",
        kind="merge",
        meta={"head_sha": "b" * 40, "preview": {"status": "building", "requires_build": True}},
    )
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path), "preview_branch": "preview"}},
        memory=memory,
    )
    service._jobs = {
        "failed-job": {
            "id": "failed-job",
            "status": "running",
            "ok": True,
            "branch": "preview",
            "commit": "b" * 40,
            "mode": "compiled_preview",
            "draft_id": draft_id,
        }
    }
    monkeypatch.setattr(service, "_head", lambda branch: "b" * 40)

    def fail(*_args):
        raise source_deployment.SourceDeploymentError("lint failed")

    monkeypatch.setattr(service, "_build", fail)
    service._run_job("failed-job", "preview", "b" * 40, "compiled_preview")

    draft = memory.list_drafts(limit=10)[0]
    assert draft["title"].startswith("Preview blocked:")
    assert draft["meta"]["preview"]["status"] == "blocked"
    assert draft["meta"]["preview"]["error"] == "lint failed"
    service.close()
    memory.close()
