from __future__ import annotations

import sys
import hashlib
import json
import subprocess

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


def test_preview_inventory_uses_only_the_host_owned_implementation(tmp_path):
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path), "preview_branch": "preview"},
         "source_deployment": {"inventory_script": "customer-controlled-inventory.ts"}},
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


def test_candidate_preview_environment_never_receives_platform_or_tenant_credentials(tmp_path):
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path)}},
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp/preview-home",
            "NODE_ENV": "development",
            "CLOUDFLARE_API_TOKEN": "cloudflare-production-token",
            "CLOUDFLARE_ACCOUNT_ID": "production-account",
            "PAYLOAD_SECRET": "tenant-signing-secret",
            "PAYLOAD_GATEWAY_TOKEN": "tenant-service-token",
            "GITHUB_TOKEN": "github-write-token",
            "OPENAI_API_KEY": "model-provider-key",
            "AWS_SECRET_ACCESS_KEY": "storage-secret",
        },
    )
    try:
        preview = service._preview_env(production=True)
        assert preview["NODE_ENV"] == "production"
        assert preview["HELLOADA_PREVIEW_MODE"] == "1"
        assert preview["HOME"] != "/tmp/preview-home"
        assert preview["NPM_CONFIG_CACHE"].startswith(preview["HOME"])
        assert preview["PAYLOAD_SECRET"] != "tenant-signing-secret"
        assert len(preview["PAYLOAD_SECRET"]) >= 32
        assert not {
            "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "PAYLOAD_GATEWAY_TOKEN",
            "GITHUB_TOKEN", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY",
        } & set(preview)
    finally:
        service.close()


def test_candidate_validation_commands_use_the_restricted_preview_environment(monkeypatch, tmp_path):
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path)}},
        env={"PATH": "/usr/bin:/bin", "PAYLOAD_GATEWAY_TOKEN": "must-not-leak"},
    )
    observed = {}

    def run(command, **kwargs):
        observed.update(kwargs["env"])
        return source_deployment.subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(source_deployment.subprocess, "run", run)
    try:
        service._check(["npm", "ci"], tmp_path, "dependencies", 30)
        assert "PAYLOAD_GATEWAY_TOKEN" not in observed
        assert observed["HELLOADA_PREVIEW_MODE"] == "1"
        assert observed["PAYLOAD_SECRET"]
    finally:
        service.close()


def test_source_preview_uses_payload_revisions_from_the_persisted_review_draft(tmp_path):
    effect = {
        "kind": "collection",
        "operation": "update",
        "target": "pages",
        "document_id": "17",
        "revision": "sha256:" + "a" * 64,
        "locale": "es-MX",
        "fields": ["sections"],
        "summary": "Change the homepage copy",
    }
    encoded = json.dumps([effect], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    revision_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    memory = Memory(tmp_path / "memory.db")
    draft_id = memory.save_draft(
        "Homepage change", "diff", kind="merge",
        meta={"payload_effects": [effect], "payload_revision_set_hash": revision_hash},
    )
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path)}}, memory=memory,
    )
    try:
        effects, verified_hash = service._reviewed_payload_effects(
            draft_id,
            {"payload_effects": [effect], "payload_revision_set_hash": revision_hash},
        )
        assert effects == [effect]
        assert verified_hash == revision_hash
        with pytest.raises(source_deployment.SourceDeploymentError, match="does not match the reviewed"):
            service._reviewed_payload_effects(draft_id, {"payload_revision_set_hash": "0" * 64})
    finally:
        service.close()
        memory.close()


def test_compiled_candidate_is_checked_against_frontend_allowlist_before_build(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Site Agent Test")
    git("config", "user.email", "site-agent-test@example.invalid")
    presentation = repo / "src/components/site/presentation/Hero.tsx"
    presentation.parent.mkdir(parents=True)
    presentation.write_text("export const Hero = () => <h1>Base</h1>\n", encoding="utf-8")
    package_json = repo / "package.json"
    package_json.write_text('{"name":"tenant-site"}\n', encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "base")
    base_sha = git("rev-parse", "HEAD")

    presentation.write_text("export const Hero = () => <h1>Candidate</h1>\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "presentation change")
    candidate_sha = git("rev-parse", "HEAD")
    memory = Memory(tmp_path / "memory.db")
    draft_id = memory.save_draft(
        "Candidate", "diff", kind="merge",
        meta={"base_sha": base_sha, "candidate_sha": candidate_sha},
    )
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(repo)}}, memory=memory,
    )
    try:
        result = service._verify_candidate_source_boundary(repo, candidate_sha, draft_id)
        assert result["ok"] is True
        assert result["changed_files"] == 1

        package_json.write_text('{"name":"tenant-site","scripts":{"preinstall":"node evil.js"}}\n', encoding="utf-8")
        git("add", ".")
        git("commit", "-m", "attempt to change package scripts")
        prohibited_sha = git("rev-parse", "HEAD")
        bad_draft_id = memory.save_draft(
            "Unsafe candidate", "diff", kind="merge",
            meta={"base_sha": base_sha, "candidate_sha": prohibited_sha},
        )
        with pytest.raises(source_deployment.SourceDeploymentError, match="platform-owned or non-presentation"):
            service._verify_candidate_source_boundary(repo, prohibited_sha, bad_draft_id)
    finally:
        service.close()
        memory.close()


def test_compiled_preview_does_not_report_a_404_homepage_as_ready(tmp_path):
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path)}},
    )
    try:
        assert service._preview_root_is_ready(200) is True
        assert service._preview_root_is_ready(204) is False
        with pytest.raises(source_deployment.SourceDeploymentError, match="HTTP 404; refusing to mark"):
            service._preview_root_is_ready(404)
    finally:
        service.close()


def test_retained_design_can_supply_preview_identity_before_owner_review(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    run = {"run_id": "retained", "status": "validating", "mode": "production_candidate",
           "publishable": True, "base_sha": "a" * 40, "candidate_sha": "b" * 40,
           "candidate_ref": "refs/ada-design/retained"}
    monkeypatch.setattr(memory, "get_design_run", lambda identifier: run if identifier == "retained" else None)
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path)}}, memory=memory,
    )
    try:
        assert service._retained_design_run("retained", "b" * 40) == run
        with pytest.raises(source_deployment.SourceDeploymentError, match="exact candidate"):
            service._retained_design_run("retained", "c" * 40)
        run["publishable"] = False
        with pytest.raises(source_deployment.SourceDeploymentError, match="managed candidate"):
            service._retained_design_run("retained", "b" * 40)
    finally:
        service.close()
        memory.close()


def test_compiled_mount_keeps_public_assets_consistent_across_ssr_and_hydration(tmp_path):
    (tmp_path / "next.config.mjs").write_text("export default { reactStrictMode: true }\n")
    (tmp_path / "wrangler.jsonc").write_text(json.dumps({"name": "site", "main": "worker.ts",
        "d1_databases": [{"binding": "D1", "database_id": "local"}],
        "r2_buckets": [{"binding": "R2", "bucket_name": "local"}],
        "ai": {"binding": "AI"}, "send_email": [{"name": "EMAIL"}],
    }))
    (tmp_path / "public/assets").mkdir(parents=True)
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(tmp_path)}})
    try:
        job = {"id": "6782629d-412a-425b-99f1-1c19c8a5efbf"}
        service._prepare_preview_mount(tmp_path, job)
        mount = job["runtime_base_path"]
        local = json.loads((tmp_path / "wrangler.jsonc").read_text())
        assert local["main"] == ".open-next/worker.js"
        assert "ai" not in local and "send_email" not in local
        assert 'basePath: ' + json.dumps(mount) in (tmp_path / "next.config.mjs").read_text()
        assert (tmp_path / ".helloada-source-preview.next.mjs").read_text() == "export default { reactStrictMode: true }\n"
        samples = [
            (b'<img src="/assets/owner.webp">', "text/html", f'<img src="{mount}/assets/owner.webp">'),
            (b'const src="/assets/owner.webp";', "application/javascript", f'const src="{mount}/assets/owner.webp";'),
            (b'background:url(/assets/owner.webp)', "text/css", f'background:url({mount}/assets/owner.webp)'),
            (b'{\\"src\\":\\"/assets/owner.webp\\"}', "text/html", '{\\"src\\":\\"' + mount + '/assets/owner.webp\\"}'),
        ]
        for body, content_type, expected in samples:
            assert service._rewrite_runtime_assets(body, content_type, job).decode() == expected
        external = b'<img src="https://example.com/assets/owner.webp">'
        assert service._rewrite_runtime_assets(external, "text/html", job) == external
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


def test_source_deployment_requires_exact_shared_node_and_npm_toolchain(tmp_path, monkeypatch):
    node_bin = tmp_path / "node-bin"
    node_bin.mkdir()
    node = node_bin / "node"
    node.touch()
    node.chmod(0o755)
    npm = tmp_path / "npm"
    npm.touch()
    npm.chmod(0o755)
    service = source_deployment.SourceDeploymentService(
        {
            "source_deployment": {
                "node_path": str(node_bin),
                "node_version": "22.14.0",
                "npm_command": str(npm),
                "npm_version": "11.13.0",
            }
        },
        env={"PATH": "/usr/bin:/bin"},
    )
    calls = []

    def run(command, _cwd, *, timeout):
        calls.append((command, timeout))
        version = "v22.14.0\n" if command[-1] == "--version" and command[0] == str(node) else "11.13.0\n"
        return source_deployment.subprocess.CompletedProcess(command, 0, version, "")

    monkeypatch.setattr(service, "_run", run)
    try:
        assert service._verify_toolchain(tmp_path) == str(npm)
        assert [call[0][0] for call in calls] == [str(node), str(npm)]
        assert service._child_env()["PATH"].split(source_deployment.os.pathsep)[:2] == [
            str(tmp_path), str(node_bin)
        ]

        def mismatched_npm(command, _cwd, *, timeout):
            version = "v22.14.0\n" if command[0] == str(node) else "10.9.2\n"
            return source_deployment.subprocess.CompletedProcess(command, 0, version, "")

        monkeypatch.setattr(service, "_run", mismatched_npm)
        with pytest.raises(source_deployment.SourceDeploymentError, match="npm 11.13.0"):
            service._verify_toolchain(tmp_path)
    finally:
        service.close()


def test_source_deployment_does_not_fall_back_to_system_toolchain(tmp_path):
    service = source_deployment.SourceDeploymentService(
        {"source_deployment": {}}, env={"PATH": "/usr/bin:/bin"}
    )
    try:
        with pytest.raises(source_deployment.SourceDeploymentError, match="shared.*contract"):
            service._verify_toolchain(tmp_path)
    finally:
        service.close()


def test_public_revision_verification_requires_the_exact_commit(monkeypatch, tmp_path):
    expected = "b" * 40

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return (expected + "\n").encode("utf-8")

    requests = []

    def open_url(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(source_deployment.urllib.request, "urlopen", open_url)
    service = source_deployment.SourceDeploymentService(
        {
            "site": {"clone_path": str(tmp_path), "preview_branch": "preview"},
            "source_deployment": {"verification_timeout_seconds": 30},
        },
    )
    try:
        result = service._verify_public_revision(
            "https://tenant.example",
            expected,
            label="test runtime",
        )
        assert result["ok"] is True
        assert result["commit"] == expected
        assert len(requests) == 1
        request, timeout = requests[0]
        assert request.full_url == f"https://tenant.example/site-agent-revision.txt?revision_check={expected}"
        assert request.get_method() == "GET"
        assert request.get_header("X-site-agent-revision-check") == expected
        assert timeout == 10
    finally:
        service.close()


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


def test_content_inventory_fails_closed_when_the_tool_cannot_run(tmp_path, monkeypatch):
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(tmp_path)}})
    try:
        monkeypatch.setattr(service, "_inventory_command", lambda checkout, worktree: [sys.executable, "-c",
            "import sys; sys.stderr.write('Cannot find module typescript'); raise SystemExit(1)"])
        result = service._content_inventory(tmp_path, tmp_path, 30, "secret")
        assert result["status"] == "incomplete"
        assert "typescript" in result["error"]
    finally:
        service.close()
