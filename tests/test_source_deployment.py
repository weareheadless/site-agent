from __future__ import annotations

import sys
import hashlib
import json
import subprocess
from pathlib import Path

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


def test_candidate_preview_retains_ready_result_after_a_newer_compile_fails(tmp_path):
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(tmp_path)}})
    try:
        service._jobs["preview-a"] = {
            "id": "preview-a", "design_run_id": "run-a", "mode": "compiled_preview",
            "commit": "a" * 40, "status": "ready", "preview_url": "/api/workspace/source/preview/preview-a/runtime/",
            "created_at": "2026-11-01T10:00:00+00:00",
        }
        service._jobs["failed-a"] = {
            "id": "failed-a", "design_run_id": "run-a", "mode": "compiled_preview",
            "commit": "a" * 40, "status": "failed", "created_at": "2026-11-02T10:00:00+00:00",
        }
        assert service.preview_for_candidate("run-a", "a" * 40)["id"] == "preview-a"
        del service._jobs["preview-a"]
        assert service.preview_for_candidate("run-a", "a" * 40)["id"] == "failed-a"
        assert service.preview_for_candidate("other-run", "a" * 40) == {}
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
        {"site": {"clone_path": str(repo)}, "design_engine": {"build_profile": "next_react"}},
        memory=memory,
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


def test_candidate_preview_lookup_is_read_only_and_exact(tmp_path):
    """#570: a retained candidate is viewable before its review draft exists."""
    service = source_deployment.SourceDeploymentService(
        {"site": {"clone_path": str(tmp_path), "preview_branch": "preview"}},
    )
    run_id, sha = "intake-lab-retained", "b" * 40
    try:
        service._jobs.update({
            "exact": {"id": "exact", "mode": "compiled_preview", "design_run_id": run_id,
                      "commit": sha, "status": "ready", "created_at": "2026-11-01T10:00:00+00:00"},
            "other-run": {"id": "other-run", "mode": "compiled_preview", "design_run_id": "someone-else",
                          "commit": sha, "status": "ready", "created_at": "2026-11-01T11:00:00+00:00"},
            "other-commit": {"id": "other-commit", "mode": "compiled_preview", "design_run_id": run_id,
                             "commit": "c" * 40, "status": "ready", "created_at": "2026-11-01T12:00:00+00:00"},
            "building": {"id": "building", "mode": "compiled_preview", "design_run_id": run_id,
                         "commit": sha, "status": "running", "created_at": "2026-11-01T13:00:00+00:00"},
        })
        # Read-only: the lookup returns a copy and never mutates the stored job.
        found = service.preview_for_candidate(run_id, sha)
        assert found["id"] == "exact"
        assert found is not service._jobs["exact"]
        found["status"] = "mutated"
        assert service._jobs["exact"]["status"] == "ready"
        # Each candidate resolves only its own preview, never a neighbouring one.
        assert service.preview_for_candidate(run_id, "c" * 40)["id"] == "other-commit"
        assert service.preview_for_candidate(run_id, "d" * 40) == {}
        assert service.preview_for_candidate("someone-else", sha)["id"] == "other-run"
        assert service.preview_for_candidate("unknown-run", sha) == {}
        assert service.preview_for_candidate("", sha) == {}
        assert service.preview_for_candidate(run_id, "not-a-sha") == {}
    finally:
        service.close()


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


def test_compiled_preview_navigation_is_left_to_the_next_mount():
    """Next's basePath owns route navigation; the transport must not repeat it.

    `inmersion`'s preview rendered every page, but clicking a link went to
    `<mount>/<mount>/courses` and the page went blank: the served HTML and RSC
    props carried the mount, and Next's router added it again. The mount is a
    build-time basePath, so a site route already resolves inside the preview.
    """
    mount = '/api/helloada/source/preview/exact-job/runtime'
    job = {'runtime_base_path': mount, 'public_asset_roots': []}
    for body, content_type in [
        ('<a href="/?locale=en">English</a>', 'text/html'),
        ('<a href="/work?locale=en">Work</a>', 'text/html'),
        ('{"href":"/blog"}', 'text/x-component'),
        (r'{\"href\":\"/blog\"}', 'text/html'),
    ]:
        assert source_deployment.SourceDeploymentService._rewrite_runtime_assets(
            body.encode(), content_type, job) == body.encode()
    # Root-relative public assets are not mounted by Next, so they still are.
    assets = {'public_asset_roots': ['/photos/']}
    body = b'<img src="/photos/reef.webp">'
    rewritten = source_deployment.SourceDeploymentService._rewrite_runtime_assets(
        body, 'text/html', {**job, **assets})
    assert rewritten == f'<img src="{mount}/photos/reef.webp">'.encode()


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
    assert job["error"] == "source deployment process restarted; restarting the exact compiled preview"
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



def test_content_inventory_returns_violations_as_actionable_findings(tmp_path):
    """A violation exit must still deliver the machine-readable report."""
    import json as _json
    from site_agent.hands.design_quality import _content_authority_findings
    payload = _json.dumps({"filesScanned": 2, "editableCount": 0, "bindingCount": 0, "violations": [
        {"path": "src/components/site/presentation/hero.tsx", "line": 76,
         "reason": "editable_field_needs_a_shared_binding"},
    ]})
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(tmp_path)}})
    try:
        import sys as _sys
        service._inventory_command = lambda checkout, worktree: [
            _sys.executable, "-c", f"import sys; sys.stdout.write({payload!r}); raise SystemExit(1)"]
        report = service._content_inventory(tmp_path, tmp_path, 30, "secret")
        assert report["status"] == "failed"
        evidence, findings = _content_authority_findings(report)
        assert evidence["status"] == "failed"
        assert findings[0]["code"] == "editable_field_needs_a_shared_binding"
        assert findings[0]["path"].endswith("hero.tsx")
        assert findings[0]["line"] == 76
    finally:
        service.close()


def test_for_draft_projects_the_central_release_receipt(tmp_path, monkeypatch):
    """The workspace reads for_draft, so a deployed release must not look queued."""
    from site_agent.core.memory import Memory

    memory = Memory(tmp_path / "for-draft" / "memory.db")
    draft_id = memory.save_draft("Approved candidate", "Review", kind="design")
    memory.update_draft_status(draft_id, "publishing")
    releases = tmp_path / "releases"
    (releases / "runs" / "tenant-a" / "rel-1").mkdir(parents=True)
    (releases / "runs" / "tenant-a" / "rel-1" / "receipt.json").write_text(json.dumps({
        "tenant": "tenant-a", "releaseId": "rel-1", "sourceSha": "a" * 40,
        "approvalId": draft_id, "status": "deployed", "stage": "verified",
    }))
    service = source_deployment.SourceDeploymentService({
        "instance_name": "tenant-a",
        "site": {"clone_path": str(tmp_path)},
        "deployment_pipeline": {"release_root": str(releases)},
    }, memory=memory)
    try:
        service._jobs["job-1"] = {
            "id": "job-1", "mode": "production", "status": "queued", "draft_id": draft_id,
            "commit": "a" * 40, "tenant_id": "tenant-a", "release_id": "rel-1",
            "created_at": "2026-11-03T00:00:00+00:00",
        }
        projected = service.for_draft(draft_id)
        assert projected["status"] == "deployed" and projected["ok"] is True
        assert memory.get_draft(draft_id)["status"] == "live"
    finally:
        service.close()
        memory.close()


def test_compiled_preview_resumes_from_its_existing_output(tmp_path, monkeypatch):
    worktree = tmp_path / "preview"
    (worktree / ".open-next").mkdir(parents=True)
    (worktree / ".dev.vars").write_text('PAYLOAD_SECRET="resume-secret"\n', encoding="utf-8")
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(tmp_path)}})
    commit = "a" * 40
    service._jobs["preview-1"] = {
        "id": "preview-1", "mode": "compiled_preview", "commit": commit, "status": "queued",
        "resume": True, "worktree_path": str(worktree), "checks": [{"name": "build", "ok": True}],
    }
    started = {}

    class Result:
        stdout = commit + "\n"

    monkeypatch.setattr(service, "_run", lambda *args, **kwargs: Result())
    def start_runtime(job, directory, expected=None, *, preview_secret):
        started.update({"worktree": directory, "secret": preview_secret})
        return {"runtime_port": 4321, "preview_url": "/api/workspace/source/preview/preview-1/runtime/"}

    monkeypatch.setattr(service, "_start_runtime", start_runtime)
    try:
        result = service._resume_build(service._jobs["preview-1"], "preview", commit, "compiled_preview")
        assert result["resumed"] is True
        assert result["commit"] == commit
        assert result["worktree_path"] == str(worktree)
        assert started == {"worktree": worktree, "secret": "resume-secret"}
        assert service._jobs["preview-1"]["build_step"] == "runtime"
    finally:
        service.close()


def test_compiled_preview_rebuilds_when_the_output_is_missing(tmp_path, monkeypatch):
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(tmp_path)}})
    try:
        monkeypatch.setattr(service, "_start_runtime", lambda *a, **k: pytest.fail("no output to resume"))
        job = {"id": "preview-2", "mode": "compiled_preview", "commit": "b" * 40,
               "resume": True, "worktree_path": str(tmp_path / "missing")}
        assert service._resume_build(job, "preview", "b" * 40, "compiled_preview") is None
    finally:
        service.close()


def test_the_final_message_is_the_last_completed_answer_not_a_fragment():
    from site_agent.hands.opencode_runner import _final_message_reply

    per_message = {
        "m1": {"texts": ["I'll look at the site first."], "tools": 2},
        "m2": {"texts": [], "tools": 4},
        "m3": {"texts": ["Here is the reasoning."], "tools": 1},
        "m4": {"texts": ["The answer, in full."], "tools": 0},
    }
    assert _final_message_reply(per_message) == "The answer, in full."


def test_the_final_message_skips_a_trailing_message_that_only_called_tools():
    from site_agent.hands.opencode_runner import _final_message_reply

    per_message = {
        "m1": {"texts": ["The full answer."], "tools": 0},
        "m2": {"texts": ["One more check."], "tools": 1},
    }
    assert _final_message_reply(per_message) == "The full answer."


def test_no_completed_answer_returns_empty_so_the_caller_can_fall_back():
    from site_agent.hands.opencode_runner import _final_message_reply

    assert _final_message_reply({"m1": {"texts": ["working"], "tools": 3}}) == ""


def test_a_worktree_reuses_the_installed_tree_for_its_exact_lockfile(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "package.json").write_text('{"name": "site"}', encoding="utf-8")
    (worktree / "package-lock.json").write_text('{"lockfileVersion": 3}', encoding="utf-8")
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(checkout)}})
    linked: list[str] = []
    try:
        monkeypatch.setattr(service, "_verify_toolchain", lambda cwd: "/usr/bin/npm")
        monkeypatch.setattr(
            source_deployment, "github_api_token", lambda *args, **kwargs: "token",
        )
        monkeypatch.setattr(
            "site_agent.application.release_dependencies.prepare_release_dependencies",
            lambda *args, **kwargs: [{"package": "@weareheadless/helloada-payload-core"}],
        )
        monkeypatch.setattr(
            service, "_link_cached_node_modules",
            lambda wt, key: linked.append(key) or True,
        )
        monkeypatch.setattr(
            service, "_check",
            lambda *args, **kwargs: pytest.fail("a warm cache must not install again"),
        )

        checks = service.ensure_dependencies(worktree, timeout=60, npm="/usr/bin/npm")

        assert checks == [
            {"name": "dependencies", "ok": True, "cached": True},
        ]
        assert linked == [service._node_modules_key(worktree)]
    finally:
        service.close()


def test_a_preview_is_not_reused_across_different_payload_revisions(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(checkout)}})
    try:
        service._jobs["preview-a"] = {
            "id": "preview-a", "branch": "preview", "commit": "a" * 40,
            "mode": "compiled_preview", "draft_id": 69, "design_run_id": "",
            "payload_revision_set_hash": "", "status": "ready",
        }
        service._start_locked = lambda *args, **kwargs: pytest.fail("a new content set must not reuse the old preview")
        with pytest.raises(pytest.fail.Exception):
            service.start({"branch": "preview", "commit": "a" * 40, "draft_id": 69,
                           "payload_revision_set_hash": "b" * 64})
    finally:
        service.close()


def test_the_preview_snapshot_names_the_route_of_every_page_the_candidate_saved():
    from site_agent.application.compiled_preview_content import canonical_preview_snapshot

    revision = "sha256:" + "a" * 64

    class Gateway:
        def require_authoring_contract(self):
            return {"locales": ["en"], "defaultLocale": "en", "enabled": {"collections": ["pages"]}}

        def list(self, collection, **kwargs):
            return [{"id": "2"}]

        def read(self, collection, identifier, **kwargs):
            return {"id": "2", "slug": "about", "_status": "published", "_helloadaRevision": revision}

        def read_global(self, slug, **kwargs):
            return {}

        def list_media(self, **kwargs):
            return []

    snapshot = canonical_preview_snapshot(Gateway(), [{
        "kind": "collection", "operation": "update", "target": "pages", "document_id": "2",
        "revision": revision, "locale": "en",
    }])

    assert snapshot["routes"] == ["/about"]


def test_a_preview_route_that_does_not_render_fails_the_candidate(tmp_path):
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler
            code = 200 if self.path.endswith("/ok") else 500
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b"ok" if code == 200 else b"error")

        def log_message(self, *args):
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(tmp_path)}})
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        assert service._verify_preview_routes(base, ["/ok"]) == ["/ok"]
        with pytest.raises(source_deployment.SourceDeploymentError, match="route /about returned 500"):
            service._verify_preview_routes(base, ["/ok", "/about"])
    finally:
        service.close()
        server.shutdown()


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "PATH": __import__("os").environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }

    def run(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env)

    def head():
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            capture_output=True, text=True, env=env,
        ).stdout.strip()

    run("init", "-q")
    (repo / "src/app").mkdir(parents=True)
    (repo / "src/components/site/presentation").mkdir(parents=True)
    (repo / "src/app/sitemap.ts").write_text("export default function sitemap() { return [] }\n")
    (repo / "src/components/site/presentation/Hero.tsx").write_text("export default function Hero() { return null }\n")
    (repo / "package.json").write_text('{"name": "site"}\n')
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    return repo, head(), run, head


def test_the_preview_boundary_accepts_the_crawl_files_authoring_allows(tmp_path):
    repo, base, run, head = _git_repo(tmp_path)
    (repo / "src/app/sitemap.ts").write_text("export default function sitemap() { return ['/blog'] }\n")
    (repo / "src/components/site/presentation/Hero.tsx").write_text("export default function Hero() { return null as never }\n")
    run("add", "-A")
    run("commit", "-q", "-m", "candidate")
    candidate = head()

    memory = Memory(tmp_path / "memory.db")
    try:
        draft = memory.save_draft("About", "", kind="merge", meta={
            "base_sha": base, "head_sha": candidate,
        })
        service = source_deployment.SourceDeploymentService({
            "site": {"clone_path": str(repo)},
            "design_engine": {"build_profile": "next_react"},
        }, env={}, memory=memory)
        try:
            check = service._verify_candidate_source_boundary(repo, candidate, draft)
            assert check["ok"] is True
            assert check["changed_files"] == 2
        finally:
            service.close()
    finally:
        memory.close()


def test_the_preview_boundary_still_refuses_platform_files(tmp_path):
    repo, base, run, head = _git_repo(tmp_path)
    (repo / "package.json").write_text('{"name": "site", "scripts": {}}\n')
    run("add", "-A")
    run("commit", "-q", "-m", "candidate")
    candidate = head()

    memory = Memory(tmp_path / "memory.db")
    try:
        draft = memory.save_draft("About", "", kind="merge", meta={
            "base_sha": base, "head_sha": candidate,
        })
        service = source_deployment.SourceDeploymentService({
            "site": {"clone_path": str(repo)},
            "design_engine": {"build_profile": "next_react"},
        }, env={}, memory=memory)
        try:
            with pytest.raises(source_deployment.SourceDeploymentError, match="package.json"):
                service._verify_candidate_source_boundary(repo, candidate, draft)
        finally:
            service.close()
    finally:
        memory.close()


def test_the_tab_icon_is_a_tenant_brand_asset():
    from site_agent.frontend_ownership import is_frontend_owned_path

    assert is_frontend_owned_path("public/favicon.ico")
    # The tenant's own homepage and routes are presentation source it authors.
    assert is_frontend_owned_path("src/app/(frontend)/page.tsx")
    # The shared route shell and layout remain platform-owned.
    assert not is_frontend_owned_path("src/app/(frontend)/[[...slug]]/page.tsx")
    assert not is_frontend_owned_path("src/app/(frontend)/layout.tsx")


def _preview_server(pages, files=None):
    """Serve exact documents and files, so a gate can be asked real questions."""
    import http.server
    import threading

    files = dict(files or {})

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler
            path = self.path.split("?")[0]
            if path in pages:
                body = pages[path].encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            elif path in files:
                body = files[path]
                self.send_response(200)
                self.send_header("Content-Type", "image/x-icon")
            else:
                body = b"missing"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_page_that_names_a_file_it_cannot_serve_fails_the_render_gate(tmp_path):
    # The tab icon case: the document renders, the file it names 404s. A gate
    # that only checks the document status calls this candidate ready.
    server = _preview_server({
        "/": '<html><head><link rel="icon" href="/icon-1g134v.png"></head><body>ok</body></html>',
    }, {"/icon-4usi79.png": b"icon"})
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(tmp_path)}})
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with pytest.raises(source_deployment.SourceDeploymentError, match="icon-1g134v.png"):
            service._verify_preview_routes(base, ["/"])
    finally:
        service.close()
        server.shutdown()


def test_a_page_whose_assets_all_resolve_passes_the_render_gate(tmp_path):
    server = _preview_server({
        "/": '<html><head><link rel="icon" href="/favicon.ico"></head>'
             '<body><img src="/hero.jpg" srcset="/hero.jpg 1x, /hero@2x.jpg 2x"></body></html>',
    }, {"/favicon.ico": b"icon", "/hero.jpg": b"jpg", "/hero@2x.jpg": b"jpg2"})
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(tmp_path)}})
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        assert service._verify_preview_routes(base, ["/"]) == ["/"]
    finally:
        service.close()
        server.shutdown()


def test_third_party_assets_are_not_this_previews_to_serve(tmp_path):
    server = _preview_server({
        "/": '<html><head><link rel="stylesheet" href="https://fonts.invalid/x.css"></head>'
             '<body>ok</body></html>',
    })
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(tmp_path)}})
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        # Nothing on the local server would answer that URL, so passing means
        # the cross-origin reference was recognised and left alone.
        assert service._verify_preview_routes(base, ["/"]) == ["/"]
    finally:
        service.close()
        server.shutdown()


def test_the_home_page_is_always_part_of_the_render_gate(tmp_path):
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(tmp_path)}})
    try:
        assert service._required_preview_routes(["/about"]) == ["/", "/about"]
        assert service._required_preview_routes(["/", "/about"]) == ["/", "/about"]
        assert service._required_preview_routes([]) == ["/"]
    finally:
        service.close()


def test_the_preview_mounts_the_candidates_own_media(tmp_path):
    service = source_deployment.SourceDeploymentService({"site": {"clone_path": str(tmp_path)}})
    job = {
        "runtime_base_path": "/api/helloada/source/preview/j1/runtime",
        "public_asset_roots": ["/oceanic/"],
    }
    try:
        body = (
            '<html><head><link rel="preload" as="image" href="/api/media/file/hero.jpg">'
            '<link rel="stylesheet" href="/api/helloada/source/preview/j1/runtime/app.css">'
            "</head><body><img src=\"/api/media/file/logo.jpg\"></body></html>"
        ).encode()
        out = service._rewrite_runtime_assets(body, "text/html", job).decode()
        mounted = "/api/helloada/source/preview/j1/runtime"
        assert out.count(f'{mounted}/api/media/file/') == 2
        # The platform bridge keeps its own address inside the preview.
        assert f'{mounted}/api/helloada/source/preview/j1/runtime/app.css' not in out
    finally:
        service.close()


def test_compiled_preview_generates_the_presentation_inventory_before_typecheck():
    """A candidate must compile the same committed-route declaration as the release."""
    source = (Path(__file__).resolve().parents[1] / "src/site_agent/application/source_deployment.py").read_text()
    overlay = source.index("apply_preview_runtime_overlay(")
    inventory = source.index("generate-payload-contract.mjs", overlay)
    typecheck = source.index('"typecheck"', inventory)
    build = source.index('"open_next_build"', inventory)
    assert overlay < inventory < typecheck < build
