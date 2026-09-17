import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from site_agent.application.designs import DesignService
from site_agent.application.intake_lab import (
    IntakeLabError,
    IntakeLabService,
    _owner_status,
    build_intake_lab_build_environment,
    build_intake_lab_environment,
)
from site_agent.core.design_contracts import SiteIntake
from site_agent.core.memory import Memory


def _intake() -> dict:
    return {
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
    }


def _git_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    run = lambda *args: subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "test@example.test")
    run("config", "user.name", "test")
    (repo / "build.sh").write_text("#!/bin/sh\nset -eu\nmkdir -p output\nprintf '<html><body><h1>Source</h1></body></html>' > output/index.html\n")
    (repo / "index.html").write_text("source")
    run("add", "-A")
    run("commit", "-qm", "baseline")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, sha


class _Executor:
    running = True

    def __init__(self, memory):
        self.memory = memory
        self.enqueued = []

    def enqueue(self, run_id):
        run = self.memory.get_design_run(run_id)
        assert run["planning_json"]["build_request"]["run_id"] == run_id
        assert run["planning_json"]["build_target"]["push_mode"] == "none"
        self.enqueued.append(run_id)


def test_submit_persists_typed_local_job_before_enqueue(tmp_path):
    source, base_sha = _git_repo(tmp_path)
    memory = Memory(tmp_path / "data" / "intake-lab.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(source), "branch": "main", "writable_patterns": ["**/*"]},
        "design_engine": {
            "provider": "entrim",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "visual_review": {"provider": "entrim", "model": "Qwen/Qwen3.8-27B"},
        },
    }
    design = DesignService(memory, config=config)

    def prepare(run_id):
        from site_agent.core.design_contracts import PageBuildRequest

        run = memory.get_design_run(run_id)
        return PageBuildRequest.from_dict({
            "schema_version": 1,
            "run_id": run_id,
            "mode": "initial_homepage",
            "base_sha": run["base_sha"],
            "page_path": "index.html",
            "purpose": "Create a calm, precise homepage.",
            "site_intake_hash": run["intake_hash"],
            "acceptance_criteria": ["Keep the homepage accessible."],
            "content": {"creative_prompt": run["owner_request"]},
        })

    design.prepare_initial_request = prepare
    executor = _Executor(memory)
    service = IntakeLabService(
        design,
        executor,
        config=config,
        workspace=tmp_path / "lab",
        default_intake=SiteIntake.from_dict(_intake()),
        default_prompt="Create the first website design.",
    )

    result = service.submit("Make the page feel like a quiet morning studio.", _intake())

    assert result["mode"] if "mode" in result else result["push_mode"] == "none"
    assert result["publishable"] is False
    assert result["push_mode"] == "none"
    assert result["base_sha"] == base_sha
    assert result["owner_request"] == "Make the page feel like a quiet morning studio."
    assert executor.enqueued == [result["run_id"]]
    assert memory.get_design_run(result["run_id"])["mode"] == "local_experiment"
    assert memory.get_design_run(result["run_id"])["planning_json"]["build_request"]["content"]["creative_prompt"] == result["owner_request"]
    remote = subprocess.run(
        ["git", "-C", str(tmp_path / "lab" / "runs" / result["run_id"] / "repository"), "remote"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert remote == ""
    memory.close()


def test_invalid_intake_is_rejected_before_a_run_is_created(tmp_path):
    memory = Memory(tmp_path / "intake-lab.db")
    design = DesignService(memory, config={})
    executor = _Executor(memory)
    service = IntakeLabService(
        design,
        executor,
        config={},
        workspace=tmp_path / "lab",
        default_intake=SiteIntake.from_dict(_intake()),
        default_prompt="Create the first website design.",
    )

    with pytest.raises(IntakeLabError, match="business"):
        service.submit("Create a site.", {"schema_version": 1})

    assert memory.list_design_runs(limit=20) == []
    assert executor.enqueued == []
    memory.close()


def test_new_intake_uses_generic_working_room_name_not_configured_site_name(tmp_path):
    memory = Memory(tmp_path / "intake-lab.db")
    config = {"site": {"name": "oceanicvibes"}}
    service = IntakeLabService(
        DesignService(memory, config=config),
        _Executor(memory),
        config=config,
        workspace=tmp_path / "lab",
        default_intake=None,
        default_prompt="Start a new intake conversation.",
    )

    assert service.describe()["site_name"] == "New site"
    assert service.describe()["default_intake"] == {}
    memory.close()


def test_intake_lab_environment_includes_intake_advisor_provider_key(tmp_path):
    env = build_intake_lab_environment(
        {
            "env": {"llm_api_key": "IMPLEMENTATION_KEY"},
            "design_engine": {
                "intake_advisor": {"api_key_env": "OPENROUTER_API_KEY"},
            },
        },
        {
            "PATH": "/usr/bin",
            "IMPLEMENTATION_KEY": "implementation-secret",
            "OPENROUTER_API_KEY": "openrouter-secret",
        },
        tmp_path / "lab",
    )

    assert env["OPENROUTER_API_KEY"] == "openrouter-secret"
    assert env["IMPLEMENTATION_KEY"] == "implementation-secret"


def test_intake_lab_environment_is_an_allowlist(tmp_path):
    env = build_intake_lab_environment(
        {
            "env": {"llm_api_key": "IMPLEMENTATION_KEY", "vision_api_key": "VISION_KEY"},
            "design_engine": {"visual_review": {"api_key_env": "VISION_KEY"}},
        },
        {
            "PATH": "/usr/bin",
            "HOME": "/home/owner",
            "IMPLEMENTATION_KEY": "implementation-secret",
            "VISION_KEY": "vision-secret",
            "GITHUB_TOKEN": "github-secret",
            "SITE_AGENT_ADMIN_PASSWORD": "admin-secret",
            "AWS_SECRET_ACCESS_KEY": "cloud-secret",
        },
        tmp_path / "lab",
    )

    assert env["IMPLEMENTATION_KEY"] == "implementation-secret"
    assert env["VISION_KEY"] == "vision-secret"
    assert env["HOME"] == str((tmp_path / "lab" / "process-home").resolve())
    assert "GITHUB_TOKEN" not in env
    assert "SITE_AGENT_ADMIN_PASSWORD" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env

    build_env = build_intake_lab_build_environment(
        {"env": {"llm_api_key": "IMPLEMENTATION_KEY"}},
        {"PATH": "/usr/bin", "IMPLEMENTATION_KEY": "implementation-secret"},
        tmp_path / "build-lab",
    )
    assert "IMPLEMENTATION_KEY" not in build_env
    assert str(Path(sys.executable).resolve().parent) in build_env["PATH"].split(os.pathsep)


def test_intake_lab_build_environment_keeps_virtualenv_bin_before_resolved_python(tmp_path, monkeypatch):
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    interpreter = venv_bin / "python"
    interpreter.symlink_to("/usr/bin/python3")
    monkeypatch.setattr("site_agent.application.intake_lab.sys.executable", str(interpreter))

    build_env = build_intake_lab_build_environment(
        {},
        {"PATH": "/home/admin/.local/bin:/usr/bin"},
        tmp_path / "build-lab",
    )

    path_parts = build_env["PATH"].split(os.pathsep)
    assert path_parts[0] == str(venv_bin)
    assert "/usr/bin" in path_parts
    assert path_parts.index(str(venv_bin)) < path_parts.index("/usr/bin")


def test_intake_lab_build_environment_keeps_user_local_frontend_tools_available(tmp_path, monkeypatch):
    user_home = tmp_path / "user"
    user_bin = user_home / ".local" / "bin"
    user_bin.mkdir(parents=True)
    monkeypatch.setattr("site_agent.application.intake_lab.Path.home", lambda: user_home)

    build_env = build_intake_lab_build_environment({}, {"PATH": "/usr/bin"}, tmp_path / "build-lab")

    path_parts = build_env["PATH"].split(os.pathsep)
    assert path_parts[0] == str(Path(sys.executable).expanduser().parent)
    assert path_parts[1] == str(user_bin.resolve())


def test_preview_identity_allows_a_refinement_clone_shared_with_its_parent(tmp_path):
    clone = tmp_path / "runs" / "parent" / "repository"
    (clone / ".git").mkdir(parents=True)
    service = object.__new__(IntakeLabService)
    service.workspace = tmp_path.resolve()
    service.design_service = SimpleNamespace(clone_path_for_run=lambda _run_id: clone)
    service._raw_local_run = lambda _run_id: {"candidate_sha": "c" * 40}

    assert service.preview_identity("intake-lab-" + "a" * 32, "candidate") == (clone.resolve(), "c" * 40)


def test_intake_lab_projection_explains_revision_pipeline_timing_and_result(tmp_path):
    service = object.__new__(IntakeLabService)
    service.workspace = tmp_path.resolve()
    service.describe = lambda: {
        "implementation": {"provider": "entrim", "model": "builder"},
        "visual_review": {"provider": "entrim", "model": "reviewer"},
    }
    parent_id = "intake-lab-" + "a" * 32
    child_id = "intake-lab-" + "b" * 32
    intake = SiteIntake.from_dict(_intake()).to_dict()

    def event(index, stage, timestamp, message=""):
        return {
            "id": index,
            "stage": stage,
            "message": message or stage,
            "detail": {},
            "created_ts": timestamp,
        }

    parent = {
        "id": 1,
        "run_id": parent_id,
        "mode": "local_experiment",
        "status": "ready_for_review",
        "operation_kind": "initial_build",
        "parent_run_id": None,
        "source_candidate_sha": "",
        "intake_json": intake,
        "base_sha": "1" * 40,
        "candidate_sha": "2" * 40,
        "publishable": False,
        "quality_report_json": {"state": "passed", "gates": {"build": "passed"}},
        "events": [event(1, "created", "2026-01-01T00:00:00+00:00")],
        "created_ts": "2026-01-01T00:00:00+00:00",
        "updated_ts": "2026-01-01T00:00:10+00:00",
    }
    child = {
        "id": 2,
        "run_id": child_id,
        "mode": "local_experiment",
        "status": "needs_repair",
        "operation_kind": "visual_refinement",
        "parent_run_id": parent_id,
        "source_candidate_sha": "2" * 40,
        "intake_json": intake,
        "base_sha": "2" * 40,
        "candidate_sha": "3" * 40,
        "publishable": False,
        "quality_report_json": {
            "state": "passed",
            "gates": {"build": "passed", "browser": "passed"},
            "findings": [],
            "visual_critique": {
                "state": "repair",
                "model_id": "reviewer",
                "findings": [{"severity": "high", "message": "Strengthen the focal point."}],
                "repair_plan": [{"change": "Increase hero contrast."}],
            },
        },
        "events": [
            event(1, "created", "2026-01-01T00:00:00+00:00"),
            event(2, "assessing_intake", "2026-01-01T00:00:01+00:00"),
            event(3, "planning", "2026-01-01T00:00:02+00:00"),
            event(4, "building", "2026-01-01T00:00:03+00:00"),
            event(5, "candidate_ready", "2026-01-01T00:00:08+00:00"),
            event(6, "validating", "2026-01-01T00:00:09+00:00"),
            event(7, "visual_review_pending", "2026-01-01T00:00:10+00:00"),
            event(8, "needs_repair", "2026-01-01T00:00:15+00:00"),
            event(9, "visual_review", "2026-01-01T00:00:15+00:00"),
        ],
        "created_ts": "2026-01-01T00:00:00+00:00",
        "updated_ts": "2026-01-01T00:00:15+00:00",
    }

    projected = service._project(child, detail=True, related_runs=[parent, child])

    assert projected["parent_run_id"] == parent_id
    assert projected["source_candidate_sha"] == "2" * 40
    assert projected["revision"]["number"] == 2
    assert projected["revision"]["operation_kind"] == "visual_refinement"
    assert projected["revision"]["label"] == "Visual refinement"
    assert projected["revision"]["root_run_id"] == parent_id
    assert projected["revision"]["parent_run_id"] == parent_id
    assert projected["revision"]["reason"] == "Visual refinement of revision 1."
    assert projected["revision_count"] == 2
    assert [item["number"] for item in projected["revisions"]] == [1, 2]
    assert projected["duration_seconds"] == 15
    assert [item["key"] for item in projected["pipeline"]] == [
        "intake", "planning", "building", "validation", "visual_review", "result"
    ]
    assert projected["pipeline"][3]["state"] == "complete"
    assert projected["pipeline"][4]["state"] == "complete"
    assert projected["result"]["state"] == "needs_repair"
    assert "Deterministic checks passed" in projected["result"]["summary"]
    assert "visual review" in projected["result"]["summary"].lower()
    assert projected["visual_review"]["repair_plan"][0]["change"] == "Increase hero contrast."

    service.design_service = SimpleNamespace(
        list_runs=lambda **_: [child, parent],
        get_run=lambda run_id: {child_id: child, parent_id: parent}[run_id],
    )
    listed = service.list_runs(limit=2)
    assert listed[0]["revision"]["number"] == 2
    assert listed[0]["revision_count"] == 2


def test_result_projection_handles_validating_sighted_self_review():
    from site_agent.application.intake_lab import _result_projection
    from site_agent.core.design_contracts import DesignRunStatus

    projected = _result_projection(
        DesignRunStatus.VALIDATING.value,
        {"state": "passed"},
        None,
        None,
    )
    assert projected["state"] == "deterministic_valid"
    assert projected["label"] == "Deterministically valid"
    assert projected["summary"] == "Deterministic checks passed; visual review is still pending."


def test_result_projection_does_not_offer_nested_visual_refinement():
    from site_agent.application.intake_lab import _result_projection
    from site_agent.core.design_contracts import DesignRunStatus

    projected = _result_projection(
        DesignRunStatus.NEEDS_REPAIR.value,
        {"state": "passed"},
        {"state": "repair", "findings": [{"message": "Increase contrast."}]},
        None,
        operation_kind="visual_refinement",
    )

    assert projected["state"] == "needs_repair"
    assert "bounded refinement" in projected["next_action"]
    assert "owner feedback" in projected["next_action"]


def test_final_visual_refinement_with_subjective_findings_stays_blocked():
    assert _owner_status(
        "ready_for_review",
        {"state": "passed", "visual_critique": {"state": "repair"}},
        {"state": "repair"},
    ) == "blocked"

    assert _owner_status(
        "ready_for_review",
        {"state": "passed", "visual_critique": {"state": "inconclusive"}},
        {"state": "inconclusive"},
    ) == "blocked"


def test_visual_review_retry_passes_the_scoped_media_service():
    run_id = "intake-lab-" + "a" * 32
    media_service = object()
    calls = []
    service = object.__new__(IntakeLabService)
    service.media_service = media_service
    service.review_environment = {}
    service._raw_local_run = lambda _run_id: {
        "run_id": run_id,
        "mode": "local_experiment",
        "publishable": False,
    }
    service.get_run = lambda _run_id: {"run_id": run_id}
    service.design_service = SimpleNamespace(
        visual_review_run=lambda _run_id, **kwargs: calls.append(kwargs),
    )

    assert service.retry_visual_review(run_id) == {"run_id": run_id}
    assert calls == [{"env": {}, "source_media": media_service}]


def test_technical_repair_queues_a_local_child_from_owner_feedback():
    parent_id = "design-" + "a" * 32
    child_id = "design-" + "b" * 32
    request = {
        "schema_version": 1,
        "run_id": child_id,
        "mode": "initial_homepage",
        "base_sha": "2" * 40,
        "page_path": "index.html",
        "purpose": "Repair the retained homepage.",
        "acceptance_criteria": ["Preserve the existing homepage."],
    }
    target = {
        "mode": "local_experiment",
        "base_sha": "2" * 40,
        "candidate_ref": f"refs/ada-design-lab/{child_id}",
        "push_mode": "none",
        "publishable": False,
        "operation_kind": "technical_repair",
    }
    calls = []
    service = object.__new__(IntakeLabService)
    service.executor = SimpleNamespace(enqueue=lambda run_id: calls.append(("enqueue", run_id)))
    service._raw_local_run = lambda _run_id: {"run_id": parent_id, "mode": "local_experiment", "publishable": False}
    service.get_run = lambda _run_id: {"run_id": child_id, "publishable": False}
    service.design_service = SimpleNamespace(
        create_technical_repair_run=lambda parent_run_id, **kwargs: (
            calls.append(("create", parent_run_id, kwargs))
            or {"run": {"run_id": child_id}, "request": request, "target": target}
        ),
        queue_build=lambda run_id, build_request, build_target: calls.append(
            ("queue", run_id, build_request.run_id, build_target.operation_kind)
        ),
    )

    result = service.create_technical_repair(parent_id, owner_request="Add a signature GSAP reveal.")

    assert result == {"run_id": child_id, "publishable": False}
    assert calls[0][0:2] == ("create", parent_id)
    assert calls[0][2]["owner_request"] == "Add a signature GSAP reveal."
    assert calls[-2:] == [
        ("queue", child_id, child_id, "technical_repair"),
        ("enqueue", child_id),
    ]


def test_revision_summary_marks_reviewable(tmp_path):
    from site_agent.application.intake_lab import _revision_summary

    def summarize(status, candidate_sha):
        return _revision_summary({
            "run_id": "rev-x",
            "status": status,
            "candidate_sha": candidate_sha,
            "operation_kind": "initial_build",
            "created_ts": "2026-09-05T00:00:00+00:00",
            "updated_ts": "2026-09-05T00:01:00+00:00",
            "quality_report_json": {"state": "passed"},
        }, 1, "root", {}, tmp_path)

    assert summarize("ready_for_review", "c" * 40)["reviewable"] is True
    assert summarize("needs_repair", "c" * 40)["reviewable"] is False
    assert summarize("validating", "c" * 40)["reviewable"] is False
    assert summarize("ready_for_review", "")["reviewable"] is False


def test_get_run_can_project_a_child_from_the_scoped_run_graph(tmp_path):
    parent_id = "intake-lab-" + "a" * 32
    child_id = "design-" + "b" * 32
    intake = SiteIntake.from_dict(_intake()).to_dict()
    parent = {
        "run_id": parent_id,
        "mode": "local_experiment",
        "status": "validating",
        "operation_kind": "initial_build",
        "parent_run_id": None,
        "source_candidate_sha": "",
        "intake_json": intake,
        "base_sha": "1" * 40,
        "candidate_sha": "2" * 40,
        "publishable": False,
        "events": [],
        "created_ts": "2026-01-01T00:00:00+00:00",
        "updated_ts": "2026-01-01T00:00:10+00:00",
    }
    child = {
        "run_id": child_id,
        "mode": "local_experiment",
        "status": "ready_for_review",
        "operation_kind": "visual_refinement",
        "parent_run_id": parent_id,
        "source_candidate_sha": "2" * 40,
        "intake_json": intake,
        "base_sha": "2" * 40,
        "candidate_sha": "3" * 40,
        "publishable": False,
        "events": [],
        "created_ts": "2026-01-01T00:00:11+00:00",
        "updated_ts": "2026-01-01T00:00:20+00:00",
    }
    service = object.__new__(IntakeLabService)
    service.workspace = tmp_path.resolve()
    service.describe = lambda: {
        "implementation": {"provider": "entrim", "model": "builder"},
        "visual_review": {"provider": "entrim", "model": "reviewer"},
    }
    service.design_service = SimpleNamespace(
        get_run=lambda _run_id: (_ for _ in ()).throw(RuntimeError("stale direct lookup")),
        list_runs=lambda **_: [child, parent],
    )

    projected = service.get_run(child_id)

    assert projected["run_id"] == child_id
    assert projected["parent_run_id"] == parent_id
    assert projected["revision_count"] == 2
    assert projected["preferred_run_id"] == child_id


def test_projection_exposes_a_retained_candidate_even_when_quality_is_terminal(tmp_path):
    service = object.__new__(IntakeLabService)
    service.workspace = tmp_path.resolve()
    service.describe = lambda: {
        "implementation": {"provider": "entrim", "model": "builder"},
        "visual_review": {"provider": "entrim", "model": "reviewer"},
    }
    run_id = "intake-lab-" + "a" * 32
    run = {
        "run_id": run_id,
        "mode": "local_experiment",
        "status": "failed",
        "operation_kind": "initial_build",
        "intake_json": SiteIntake.from_dict(_intake()).to_dict(),
        "base_sha": "1" * 40,
        "candidate_sha": "2" * 40,
        "publishable": False,
        "quality_report_json": {"state": "incomplete"},
        "events": [],
        "created_ts": "2026-01-01T00:00:00+00:00",
        "updated_ts": "2026-01-01T00:01:00+00:00",
        "error": "worker stopped after retaining the candidate",
    }

    projected = service._project(run, detail=True, related_runs=[run])

    assert projected["candidate_available"] is True
    assert projected["preview_run_id"] == run_id
    assert projected["preferred_run_id"] == run_id
    assert projected["revisions"][0]["candidate_available"] is True
