import subprocess

from fastapi.testclient import TestClient

from site_agent.application.designs import DesignService
from site_agent.core.design_contracts import (
    BuildTarget,
    DesignCandidateReceipt,
    PageBuildRequest,
    SiteIntake,
    VisualCritiqueReport,
)
from site_agent.core.memory import Memory
from site_agent.hands.design_quality import QualityPolicy
from site_agent.web.server import create_app


def _intake() -> SiteIntake:
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "North Star Studio",
            "offer_summary": "Brand strategy for independent businesses.",
            "primary_services": ["Brand strategy"],
        },
        "audience": {"primary": "Independent business owners"},
        "conversion": {"primary_action": "Book a consultation", "not_available": True},
        "brand": {"voice": "Clear, thoughtful, and warm."},
        "site": {"required_pages": ["index.html"]},
    })


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "build.sh").write_text("#!/usr/bin/env bash\nset -e\n")
    (repo / "pelicanconf.py").write_text("ARTICLE_PATHS = ['articles']\n")
    (repo / "index.html").write_text("baseline")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    base_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    output = repo / "output"
    output.mkdir()
    (repo / "index.html").write_text("candidate")
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Candidate</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Candidate</h1></body></html>'
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "candidate"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, base_sha, candidate_sha


def test_design_review_is_sha_bound_and_approval_is_explicit(tmp_path, monkeypatch):
    repo, base_sha, candidate_sha = _repo(tmp_path)
    memory = Memory(tmp_path / "memory.db")

    class FakeBuilder:
        def build_design(self, request, target, progress=None):
            return DesignCandidateReceipt.from_dict({
                "run_id": request.run_id,
                "operation_kind": "initial_build",
                "base_sha": target.base_sha,
                "candidate_sha": candidate_sha,
                "candidate_ref": target.candidate_ref,
                "diff_summary": "candidate",
                "changed_paths": ["index.html", "output/index.html"],
                "manifest_path": "design/ada-design-manifest.json",
                "manifest_hash": "d" * 64,
                "opencode_session_id": "fake-session",
                "transcript_path": "artifacts/transcript.jsonl",
                "provider": "entrim",
                "model": "deepseek-ai/DeepSeek-V4-Flash",
                "publishable": True,
            })

    service = DesignService(memory, config={"site": {"clone_path": str(repo)}}, builder=FakeBuilder())
    run = service.create_run(_intake(), run_id="design-web-1", base_sha=base_sha)
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": run["run_id"],
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "production_candidate",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design/design-web-1",
        "push_mode": "none",
        "publishable": True,
    })
    service.execute_build(run["run_id"], request, target)
    service.validate_run(
        run["run_id"], repo,
        policy=QualityPolicy(
            build_command=None,
            allowed_patterns=("index.html", "output/**"),
            required_pages=("index.html",),
        ),
    )

    class FakeAdapter:
        def validate(self):
            return None

        def merge_design_candidate(self, config, reviewed_sha, reviewed_base, message):
            assert reviewed_sha == candidate_sha
            assert reviewed_base == base_sha
            return {
                "merged": True,
                "candidate_sha": reviewed_sha,
                "commit_sha": "m" * 40,
                "parent_sha": reviewed_base,
                "path": "candidate->main",
            }

    import site_agent.web.server as server_module

    original_get_adapter = server_module.get_adapter
    server_module.get_adapter = lambda name, config: FakeAdapter()
    try:
        config = {
            "env": {"admin_password": "SITE_AGENT_ADMIN_PASSWORD"},
            "site": {"clone_path": str(repo), "adapter": "fake"},
            "admin": {"host": "127.0.0.1", "port": 3011},
        }
        app = create_app({"config": config, "memory": memory, "design_service": service}, env={"SITE_AGENT_ADMIN_PASSWORD": "secret"})
        with TestClient(app, base_url="https://testserver") as client:
            assert client.post("/api/login", json={"password": "secret"}).status_code == 200

            direct = client.get(f"/api/design/runs/{run['run_id']}/review/index.html")
            assert direct.status_code == 200
            assert b"Candidate" in direct.content
            original = client.get(f"/api/design/runs/{run['run_id']}/review/index.html?variant=original")
            assert original.status_code == 200
            assert original.content == b"baseline"
            invalid_variant = client.get(f"/api/design/runs/{run['run_id']}/review/index.html?variant=other")
            assert invalid_variant.status_code == 422
            candidate_pages = client.get(f"/api/design/runs/{run['run_id']}/pages")
            assert candidate_pages.status_code == 200
            assert candidate_pages.json()["pages"] == ["index.html", "articles.html"]
            original_pages = client.get(f"/api/design/runs/{run['run_id']}/pages?variant=original")
            assert original_pages.status_code == 200
            assert original_pages.json()["ref"] == base_sha

            listed = client.get("/api/design/runs").json()["runs"]
            assert listed[0]["candidate_sha"] == candidate_sha

            created = client.post(f"/api/design/runs/{run['run_id']}/review")
            assert created.status_code == 202
            draft_id = created.json()["run"]["draft_id"]
            assert "index.html" in client.get(f"/api/pages?draft_id={draft_id}").json()["pages"]
            staged = client.get(f"/api/review/{draft_id}/index.html")
            assert staged.status_code == 200
            assert b"Candidate" in staged.content
            staged_original = client.get(f"/api/review/{draft_id}/index.html?variant=original")
            assert staged_original.status_code == 200
            assert staged_original.content == b"baseline"

            approved = client.post(f"/api/drafts/{draft_id}/approve")
            assert approved.status_code == 200
            assert approved.json()["published"]["candidate_sha"] == candidate_sha
    finally:
        server_module.get_adapter = original_get_adapter
        memory.close()


def test_design_build_endpoint_persists_typed_job_before_enqueue(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    service = DesignService(memory)
    run = service.create_run(_intake(), run_id="design-queued", base_sha="a" * 40)
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": run["run_id"],
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "production_candidate",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design/design-queued",
        "push_mode": "none",
        "publishable": True,
    })

    class FakeDesignExecutor:
        instances = []

        def __init__(self, context, service):
            self.enqueued = []
            self.__class__.instances.append(self)

        def start(self):
            return None

        def stop(self):
            return None

        def join(self, timeout=None):
            return None

        def enqueue(self, run_id):
            self.enqueued.append(run_id)

    import site_agent.application.design_jobs as jobs_module
    original_executor = jobs_module.DesignJobExecutor
    jobs_module.DesignJobExecutor = FakeDesignExecutor
    try:
        config = {
            "env": {"admin_password": "SITE_AGENT_ADMIN_PASSWORD"},
            "site": {"clone_path": str(tmp_path / "clone"), "adapter": "fake"},
            "admin": {"host": "127.0.0.1", "port": 3011},
        }
        app = create_app({"config": config, "memory": memory, "design_service": service}, env={"SITE_AGENT_ADMIN_PASSWORD": "secret"})
        with TestClient(app, base_url="https://testserver") as client:
            assert client.post("/api/login", json={"password": "secret"}).status_code == 200
            response = client.post(
                f"/api/design/runs/{run['run_id']}/build",
                json={"request": request.to_dict(), "target": target.to_dict()},
            )
            assert response.status_code == 202
            assert FakeDesignExecutor.instances[-1].enqueued == [run["run_id"]]
    finally:
        jobs_module.DesignJobExecutor = original_executor
        stored = service.get_run(run["run_id"])
        assert stored["planning_json"]["build_request"]["run_id"] == run["run_id"]
        assert stored["planning_json"]["build_target"]["push_mode"] == "none"
        assert stored["events"][-1]["stage"] == "queued"
        memory.close()


def test_design_visual_review_and_refinement_are_explicit_worker_actions(tmp_path, monkeypatch):
    repo, base_sha, candidate_sha = _repo(tmp_path)
    memory = Memory(tmp_path / "memory.db")
    run_id = "design-api-flow"
    candidate_ref = f"refs/ada-design/{run_id}"
    service = DesignService(memory, config={"site": {"clone_path": str(repo)}})
    run = service.create_run(
        _intake(),
        run_id=run_id,
        base_sha=base_sha,
        candidate_ref=candidate_ref,
    )
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": run_id,
        "mode": "initial_homepage",
        "base_sha": candidate_sha,
        "page_path": "index.html",
        "purpose": "Refine the homepage.",
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "production_candidate",
        "base_sha": candidate_sha,
        "candidate_ref": candidate_ref,
        "push_mode": "none",
        "publishable": True,
    })
    memory.update_design_run(
        run_id,
        candidate_sha=candidate_sha,
        candidate_ref=candidate_ref,
        planning_json={"build_request": request.to_dict(), "build_target": target.to_dict()},
        quality_report_json={"run_id": run_id, "candidate_sha": candidate_sha, "state": "passed", "findings": [], "evidence": {}},
    )

    def reviewer(config, **kwargs):
        return VisualCritiqueReport.from_dict({
            "run_id": kwargs["run_id"],
            "candidate_sha": kwargs["candidate_sha"],
            "model_id": "Qwen/Qwen3.8-27B",
            "state": "repair",
            "findings": [{"severity": "high", "category": "hierarchy", "message": "Strengthen the focal point."}],
            "repair_plan": [{"finding": "focal point", "change": "Increase the hero contrast."}],
        })

    class FakeDesignExecutor:
        instances = []

        def __init__(self, context, service):
            self.enqueued = []
            self.__class__.instances.append(self)

        def start(self):
            return None

        def stop(self):
            return None

        def join(self, timeout=None):
            return None

        def enqueue(self, run_id):
            self.enqueued.append(run_id)

    import site_agent.application.design_jobs as jobs_module
    original_executor = jobs_module.DesignJobExecutor
    jobs_module.DesignJobExecutor = FakeDesignExecutor
    try:
        config = {
            "env": {"admin_password": "SITE_AGENT_ADMIN_PASSWORD"},
            "site": {"clone_path": str(repo), "adapter": "fake"},
            "admin": {"host": "127.0.0.1", "port": 3011},
        }
        app = create_app({
            "config": config,
            "memory": memory,
            "design_service": service,
            "design_visual_reviewer": reviewer,
        }, env={"SITE_AGENT_ADMIN_PASSWORD": "secret"})
        with TestClient(app, base_url="https://testserver") as client:
            for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating"):
                memory.transition_design_run(run_id, status)
            assert client.post("/api/login", json={"password": "secret"}).status_code == 200

            reviewed = client.post(f"/api/design/runs/{run_id}/visual-review")
            assert reviewed.status_code == 202
            assert reviewed.json()["run"]["status"] == "needs_repair"
            assert reviewed.json()["visual_critique"]["state"] == "repair"

            preview = client.get(f"/api/design/runs/{run_id}/review/index.html")
            assert preview.status_code == 200
            assert b"Candidate" in preview.content
            preview_token = client.get(f"/api/design/runs/{run_id}/preview-token")
            assert preview_token.status_code == 200
            assert preview_token.json()["token"]

            refined = client.post(f"/api/design/runs/{run_id}/visual-refinement")
            assert refined.status_code == 202
            child = refined.json()["run"]
            assert child["parent_run_id"] == run_id
            assert child["operation_kind"] == "visual_refinement"
            assert child["source_candidate_sha"] == candidate_sha
            assert FakeDesignExecutor.instances[-1].enqueued == [child["run_id"]]
    finally:
        jobs_module.DesignJobExecutor = original_executor
        memory.close()
