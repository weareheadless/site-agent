import pytest

from site_agent.application.design_jobs import DesignJobExecutor
from site_agent.core.design_contracts import (
    BuildTarget,
    ExperiencePlanBundle,
    PageBuildRequest,
    VisualCritiqueReport,
)
from tests.test_design_contracts import _experience_plan


def _request():
    return PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "design-job",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Keep the homepage accessible."],
    })


def _target():
    return BuildTarget.from_dict({
        "mode": "production_candidate",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design/design-job",
        "push_mode": "none",
        "publishable": True,
    })


def test_design_worker_rehydrates_typed_request_and_target():
    request, target = _request(), _target()
    run = {
        "run_id": "design-job",
        "status": "planning",
        "planning_json": {
            "build_request": request.to_dict(),
            "build_target": target.to_dict(),
        },
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, run_id, stage, message, detail=None):
            self.events.append((run_id, stage, message, detail))

        def get_design_run(self, run_id):
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, run_id):
            return run

        def execute_build(self, run_id, actual_request, actual_target, progress=None):
            self.calls.append(("build", run_id, actual_request, actual_target))
            assert actual_request == request
            assert actual_target == target

        def clone_path_for_run(self, run_id):
            self.calls.append(("clone", run_id))
            return "/tmp/design-job-clone"

        def validate_run(self, run_id, clone, browser=None):
            self.calls.append(("validate", run_id, clone, browser))

    memory = Memory()
    service = Service(memory)
    executor = DesignJobExecutor({"memory": memory}, service)

    executor._run("design-job")

    assert [call[0] for call in service.calls] == ["build", "clone", "validate"]
    assert [event[1] for event in memory.events] == ["claimed"]


def test_design_worker_links_a_passing_customer_candidate_to_review():
    run = {
        "run_id": "design-customer",
        "mode": "production_candidate",
        "status": "ready_for_review",
        "draft_id": None,
    }

    class Memory:
        def add_design_run_event(self, *args):
            raise AssertionError(f"unexpected review link event: {args}")

    class Service:
        def __init__(self):
            self.calls = []

        def get_run(self, run_id):
            assert run_id == run["run_id"]
            return run

        def create_review_draft(self, run_id):
            self.calls.append(run_id)
            run["draft_id"] = 42
            return run

    service = Service()
    executor = DesignJobExecutor({"memory": Memory()}, service)

    executor._link_review_draft_if_ready(run["run_id"])

    assert service.calls == ["design-customer"]
    assert run["draft_id"] == 42


def test_design_worker_uses_a_browser_factory_for_each_run():
    request, target = _request(), _target()
    run = {
        "run_id": "design-job",
        "status": "planning",
        "planning_json": {"build_request": request.to_dict(), "build_target": target.to_dict()},
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, run_id, stage, message, detail=None):
            self.events.append((run_id, stage, message, detail))

        def get_design_run(self, run_id):
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, run_id):
            return run

        def execute_build(self, *args, **kwargs):
            self.calls.append("build")

        def clone_path_for_run(self, run_id):
            return "/tmp/design-job-clone"

        def validate_run(self, run_id, clone, browser=None):
            self.calls.append(("validate", browser))

    browser = object()
    memory = Memory()
    service = Service(memory)
    factory_calls = []
    executor = DesignJobExecutor(
        {"memory": memory, "browser_quality_factory": lambda run_id, value: factory_calls.append(run_id) or browser},
        service,
    )

    executor._run("design-job")

    assert factory_calls == ["design-job"]
    assert service.calls[-1] == ("validate", browser)


def test_design_worker_restarts_a_retained_candidate_without_rebuilding():
    run = {
        "run_id": "design-job",
        "status": "candidate_ready",
        "candidate_sha": "c" * 40,
        "quality_report_json": {},
        "events": [],
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, run_id, stage, message, detail=None):
            self.events.append((run_id, stage, message, detail))

        def get_design_run(self, run_id):
            return run

        def transition_design_run(self, run_id, status, error=None):
            run["status"] = status
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, run_id):
            return run

        def execute_build(self, *args, **kwargs):
            self.calls.append("build")
            raise AssertionError("retained candidates must not be rebuilt")

        def clone_path_for_run(self, run_id):
            self.calls.append("clone")
            return "/tmp/design-job-clone"

        def validate_run(self, run_id, clone, browser=None):
            self.calls.append(("validate", browser))
            run["status"] = "ready_for_review"

    memory = Memory()
    service = Service(memory)
    browser = object()
    executor = DesignJobExecutor(
        {"memory": memory, "browser_quality_factory": lambda run_id, value: browser},
        service,
    )

    executor._run(run["run_id"])

    assert service.calls == ["clone", ("validate", browser)]
    assert run["status"] == "ready_for_review"


def test_design_worker_restarts_validating_candidate_with_read_only_visual_review():
    run = {
        "run_id": "design-job",
        "status": "validating",
        "candidate_sha": "c" * 40,
        "quality_report_json": {"state": "passed"},
        "events": [{"stage": "visual_review_pending"}],
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def get_design_run(self, run_id):
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, run_id):
            return run

        def clone_path_for_run(self, run_id):
            return "/tmp/design-job-clone"

        def validate_run(self, *args, **kwargs):
            self.calls.append("validate")

        def visual_review_run(self, run_id, **kwargs):
            self.calls.append(("visual_review", run_id))

    memory = Memory()
    service = Service(memory)
    executor = DesignJobExecutor({"memory": memory, "env": {"HOME": "/tmp/lab"}}, service)

    executor._run(run["run_id"])

    assert service.calls == [("visual_review", "design-job")]
    assert executor._queued == set()


def test_design_worker_visual_review_service_error_is_non_fatal():
    run = {
        "run_id": "design-job",
        "status": "validating",
        "candidate_sha": "d" * 40,
        "quality_report_json": {"state": "passed"},
        "events": [{"stage": "visual_review_pending"}],
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def get_design_run(self, run_id):
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, run_id):
            return run

        def clone_path_for_run(self, run_id):
            return "/tmp/design-job-clone"

        def validate_run(self, *args, **kwargs):
            self.calls.append("validate")

        def visual_review_run(self, run_id, **kwargs):
            self.calls.append(("visual_review", run_id))
            raise RuntimeError("review provider unavailable")

    memory = Memory()
    service = Service(memory)
    executor = DesignJobExecutor({"memory": memory, "env": {"HOME": "/tmp/lab"}}, service)

    executor._run(run["run_id"])

    assert service.calls == [("visual_review", "design-job")]
    assert executor._queued == set()


def test_design_worker_keeps_actionable_visual_review_read_only():
    candidate_sha = "e" * 40
    critique = VisualCritiqueReport.from_dict({
        "run_id": "design-visual-repair",
        "candidate_sha": candidate_sha,
        "model_id": "visual-review-test",
        "state": "repair",
        "findings": [{"severity": "high", "message": "Hero contrast is too low."}],
        "repair_plan": [{"finding": "Hero contrast", "change": "Increase readable contrast."}],
    })
    run = {
        "run_id": "design-visual-repair",
        "operation_kind": "initial_build",
        "status": "validating",
        "candidate_sha": candidate_sha,
        "quality_report_json": {"state": "passed"},
        "events": [{"stage": "visual_review_pending"}],
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def list_design_run_children(self, parent_run_id, limit=500):
            return []

        def list_design_phase_artifacts(self, run_id, phase, status):
            return []

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, run_id):
            return run

        def visual_review_run(self, run_id, **kwargs):
            self.calls.append(("visual_review", run_id))
            run["status"] = "needs_repair"
            run["quality_report_json"] = {
                "state": "passed",
                "visual_critique": critique.to_dict(),
            }
            return critique

        def create_visual_refinement_run(self, parent_run_id, actual_critique, **kwargs):
            self.calls.append(("create", parent_run_id, actual_critique, kwargs))
            raise AssertionError("visual review must not auto-create a refinement child")

    memory = Memory()
    service = Service(memory)
    executor = DesignJobExecutor(
        {"memory": memory, "config": {"design_engine": {"repair_attempts": 1}}},
        service,
    )

    executor.finish_validation(run["run_id"])

    assert service.calls[0] == ("visual_review", run["run_id"])
    assert len(service.calls) == 1
    assert executor._queued == set()
    assert not any(event[1] == "visual_repair_queued" for event in memory.events)


def test_creative_repair_rehydrates_the_parent_experience_plan_from_planning_state():
    parent_id = "creative-parent"
    child_id = "creative-child"
    raw_plan = _experience_plan(
        run_id=parent_id,
        base_sha="a" * 40,
        context_snapshot_hash="c" * 64,
    )
    plan = ExperiencePlanBundle.from_dict(raw_plan)
    parent = {
        "run_id": parent_id,
        "base_sha": "a" * 40,
        "context_snapshot_hash": "c" * 64,
        "planning_json": {
            "experience_plan": plan.to_dict(),
            "experience_plan_hash": plan.content_hash,
        },
    }
    child = {
        "run_id": child_id,
        "parent_run_id": parent_id,
        "base_sha": "b" * 40,
        "planning_json": {},
    }

    class Memory:
        def get_design_run(self, run_id):
            return {parent_id: parent, child_id: child}.get(run_id)

        def list_design_phase_artifacts(self, run_id, phase, status):
            return []

    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": child_id,
        "mode": "visual_refinement",
        "base_sha": "b" * 40,
        "page_path": "index.html",
        "purpose": "Repair the retained candidate.",
        "acceptance_criteria": ["Preserve the selected experience."],
        "content": {"visual_critique": {"state": "repair"}},
    })
    executor = DesignJobExecutor(
        {
            "memory": Memory(),
            "config": {"design_engine": {"orchestration": "creative"}},
        },
        object(),
    )

    hydrated = executor._hydrate_refinement_plan(child, request)

    assert hydrated.content["specialist_locked_plan"] == plan.to_dict()
    assert hydrated.content["specialist_locked_plan_hash"] == plan.content_hash


def test_creative_repair_rehydrates_the_root_plan_across_multiple_repair_generations():
    root_id = "creative-plan-root"
    parent_id = "creative-plan-parent-child"
    child_id = "creative-plan-grandchild"
    plan = ExperiencePlanBundle.from_dict(_experience_plan(
        run_id=root_id,
        base_sha="a" * 40,
        context_snapshot_hash="c" * 64,
    ))
    rows = {
        root_id: {
            "run_id": root_id,
            "base_sha": "a" * 40,
            "context_snapshot_hash": "c" * 64,
            "planning_json": {
                "experience_plan": plan.to_dict(),
                "experience_plan_hash": plan.content_hash,
            },
        },
        parent_id: {
            "run_id": parent_id,
            "parent_run_id": root_id,
            "base_sha": "b" * 40,
            "context_snapshot_hash": "d" * 64,
            "planning_json": {},
        },
        child_id: {
            "run_id": child_id,
            "parent_run_id": parent_id,
            "base_sha": "e" * 40,
            "context_snapshot_hash": "f" * 64,
            "planning_json": {},
        },
    }

    class Memory:
        def get_design_run(self, run_id):
            return rows.get(run_id)

        def list_design_phase_artifacts(self, run_id, phase, status):
            return []

    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": child_id,
        "mode": "visual_refinement",
        "base_sha": "e" * 40,
        "page_path": "index.html",
        "purpose": "Repair the retained candidate.",
        "acceptance_criteria": ["Preserve the selected experience."],
    })
    executor = DesignJobExecutor(
        {
            "memory": Memory(),
            "config": {"design_engine": {"orchestration": "creative"}},
        },
        object(),
    )

    hydrated = executor._hydrate_refinement_plan(rows[child_id], request)

    assert hydrated.content["specialist_locked_plan"] == plan.to_dict()
    assert hydrated.content["specialist_locked_plan_hash"] == plan.content_hash


def test_creative_repair_rejects_a_missing_or_wrong_hash_bound_plan():
    parent_id = "creative-plan-parent"
    child_id = "creative-plan-child"
    raw_plan = _experience_plan(
        run_id=parent_id,
        base_sha="a" * 40,
        context_snapshot_hash="c" * 64,
    )
    plan = ExperiencePlanBundle.from_dict(raw_plan)
    rows = {
        parent_id: {
            "run_id": parent_id,
            "base_sha": "a" * 40,
            "context_snapshot_hash": "c" * 64,
            "planning_json": {
                "experience_plan": plan.to_dict(),
                "experience_plan_hash": "f" * 64,
            },
        },
        child_id: {"run_id": child_id, "parent_run_id": parent_id, "planning_json": {}},
    }

    class Memory:
        def get_design_run(self, run_id):
            return rows.get(run_id)

        def list_design_phase_artifacts(self, run_id, phase, status):
            return []

    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": child_id,
        "mode": "visual_refinement",
        "base_sha": "b" * 40,
        "page_path": "index.html",
        "purpose": "Repair the retained candidate.",
        "acceptance_criteria": ["Preserve the selected experience."],
    })
    executor = DesignJobExecutor(
        {
            "memory": Memory(),
            "config": {"design_engine": {"orchestration": "creative"}},
        },
        object(),
    )

    with pytest.raises(RuntimeError, match="hash-bound experience plan"):
        executor._hydrate_refinement_plan(rows[child_id], request)

    rows[parent_id]["planning_json"] = {}
    with pytest.raises(RuntimeError, match="hash-bound experience plan"):
        executor._hydrate_refinement_plan(rows[child_id], request)


def test_design_worker_has_no_automatic_visual_repair_queue():
    run_id = "creative-visual-parent"
    candidate_sha = "e" * 40
    plan = ExperiencePlanBundle.from_dict(_experience_plan(
        run_id=run_id,
        base_sha="a" * 40,
        context_snapshot_hash="c" * 64,
    ))
    critique = VisualCritiqueReport.from_dict({
        "run_id": run_id,
        "candidate_sha": candidate_sha,
        "model_id": "visual-review-test",
        "state": "repair",
        "findings": [{"severity": "high", "message": "The focal point is unclear."}],
        "repair_plan": [{"finding": "focal point", "change": "Restore the planned hierarchy."}],
    })
    run = {
        "run_id": run_id,
        "operation_kind": "initial_build",
        "status": "needs_repair",
        "candidate_sha": candidate_sha,
        "base_sha": "a" * 40,
        "context_snapshot_hash": "c" * 64,
        "planning_json": {
            "experience_plan": plan.to_dict(),
            "experience_plan_hash": plan.content_hash,
        },
        "quality_report_json": {
            "state": "passed",
            "visual_critique": critique.to_dict(),
        },
    }

    class Memory:
        def __init__(self):
            self.events = []

        def get_design_run(self, requested_id):
            return run if requested_id == run_id else None

        def list_design_run_children(self, parent_run_id, limit=500):
            return []

        def list_design_phase_artifacts(self, run_id, phase, status):
            return []

        def add_design_run_event(self, *args):
            self.events.append(args)

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, requested_id):
            return run

        def create_visual_refinement_run(self, parent_run_id, actual_critique, **kwargs):
            self.calls.append((parent_run_id, actual_critique, kwargs))
            return {"run": {"run_id": "creative-visual-child"}}

    memory = Memory()
    service = Service(memory)
    executor = DesignJobExecutor(
        {
            "memory": memory,
            "config": {
                "design_engine": {
                    "orchestration": "creative",
                    "repair_attempts": 1,
                },
            },
        },
        service,
    )

    assert not hasattr(executor, "_queue_visual_review_repair_if_needed")
    assert executor._queued == set()

def test_design_worker_marks_abandoned_build_interrupted_on_restart():
    run = {"run_id": "design-job", "status": "building", "events": []}

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def get_design_run(self, run_id):
            return run

        def transition_design_run(self, run_id, status, error=None):
            run["status"] = status
            run["error"] = error
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory

        def list_runs(self, limit=500):
            return [run]

    memory = Memory()
    executor = DesignJobExecutor(
        {"memory": memory, "recover_retained_candidates": True},
        Service(memory),
    )

    executor._recover_queued()

    assert run["status"] == "interrupted"
    assert any(event[1] == "interrupted" for event in memory.events)


def test_design_worker_recovers_a_persisted_planning_run_on_restart():
    request, target = _request(), _target()
    run = {
        "run_id": "design-planning-recovery",
        "status": "planning",
        "events": [{"stage": "planning"}],
        "planning_json": {
            "build_request": request.to_dict(),
            "build_target": target.to_dict(),
        },
    }

    class Memory:
        def get_design_run(self, run_id):
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory

        def list_runs(self, limit=500):
            return [run]

    executor = DesignJobExecutor({"memory": Memory()}, Service(Memory()))

    executor._recover_queued()

    assert executor._queued == {run["run_id"]}
    assert run["status"] == "planning"


def test_design_worker_interrupts_an_unrecoverable_planning_run_on_restart():
    run = {
        "run_id": "design-planning-orphan",
        "status": "planning",
        "events": [{"stage": "planning"}],
        "planning_json": {},
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def get_design_run(self, run_id):
            return run

        def transition_design_run(self, run_id, status, error=None):
            run["status"] = status
            run["error"] = error
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory

        def list_runs(self, limit=500):
            return [run]

    memory = Memory()
    executor = DesignJobExecutor({"memory": memory}, Service(memory))

    executor._recover_queued()

    assert run["status"] == "interrupted"
    assert any(event[1] == "interrupted" for event in memory.events)


def test_design_worker_records_terminal_quality_activity():
    request, target = _request(), _target()
    run = {
        "run_id": "design-job",
        "status": "planning",
        "planning_json": {"build_request": request.to_dict(), "build_target": target.to_dict()},
    }

    class Memory:
        def add_design_run_event(self, *args):
            pass

        def get_design_run(self, run_id):
            return run

    class Service:
        def __init__(self, memory):
            self.memory = memory

        def get_run(self, run_id):
            return run

        def execute_build(self, *args, **kwargs):
            run["status"] = "ready_for_review"

    class Activity:
        def __init__(self):
            self.events = []

        def record(self, **kwargs):
            self.events.append(kwargs)

    memory = Memory()
    activity = Activity()
    executor = DesignJobExecutor({"memory": memory, "activity_service": activity}, Service(memory))

    executor._run(run["run_id"])

    assert [event["kind"] for event in activity.events] == [
        "design_run_started",
        "quality_checks_completed",
    ]
    assert activity.events[-1]["category"] == "quality"
    assert activity.events[-1]["state"] == "completed"


def test_design_worker_records_restart_interruption_activity():
    run = {"run_id": "design-job", "status": "building", "events": []}

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def get_design_run(self, run_id):
            return run

        def transition_design_run(self, run_id, status, error=None):
            run["status"] = status
            return run

    class Service:
        def list_runs(self, limit=500):
            return [run]

    class Activity:
        def __init__(self):
            self.events = []

        def record(self, **kwargs):
            self.events.append(kwargs)

    memory = Memory()
    activity = Activity()
    executor = DesignJobExecutor(
        {"memory": memory, "activity_service": activity, "recover_retained_candidates": True},
        Service(),
    )

    executor._recover_queued()

    assert activity.events[-1]["kind"] == "design_run_interrupted"
    assert activity.events[-1]["state"] == "needs_attention"


def test_specialist_final_signoff_blocks_review_when_it_does_not_pass(monkeypatch):
    from types import SimpleNamespace

    run = {
        "run_id": "design-signoff",
        "mode": "production_candidate",
        "operation_kind": "initial_build",
        "status": "ready_for_review",
        "candidate_sha": "c" * 40,
        "quality_report_json": {"state": "passed", "gates": {}, "findings": []},
        "planning_json": {
            "build_request": _request().to_dict() | {"run_id": "design-signoff"},
            "build_target": _target().to_dict() | {"candidate_ref": "refs/ada-design/design-signoff"},
        },
    }

    plan = {
        "schema_version": 1,
        "run_id": "design-signoff",
        "phase": "creative_selection",
        "variant_key": "primary",
        "attempt": 1,
        "status": "completed",
        "base_sha": "a" * 40,
        "context_snapshot_hash": "",
        "input_hashes": [],
        "producer": "creative-director",
        "payload": {"state": "passed"},
    }

    class Memory:
        def __init__(self):
            self.events = []

        def list_design_phase_artifacts(self, run_id, phase, status):
            return [{"payload": plan, "session_id": "director-session"}]

        def transition_design_run(self, run_id, status, error=None):
            run["status"] = status
            run["error"] = error
            return run

        def add_design_run_event(self, *args):
            self.events.append(args)

    class Service:
        def __init__(self, memory):
            self.memory = memory

        def get_run(self, run_id):
            return run

        def _screenshot_evidence(self, quality):
            return []

    class Coordinator:
        def __init__(self, context):
            pass

        def review_candidate(self, *args, **kwargs):
            report = SimpleNamespace(payload={"state": "passed"})
            return SimpleNamespace(
                needs_repair=False,
                creative_review=report,
                experience_review=report,
                technical_review=report,
            )

        def final_signoff(self, *args, **kwargs):
            return SimpleNamespace(payload={"state": "repair"})

    monkeypatch.setattr("site_agent.application.design_orchestration.SpecialistDesignCoordinator", Coordinator)
    memory = Memory()
    executor = DesignJobExecutor(
        {"memory": memory, "config": {"design_engine": {"orchestration": "specialist"}}},
        Service(memory),
    )

    executor._run_specialist_reviews_if_ready("design-signoff")

    assert run["status"] == "needs_repair"
    assert any(event[1] == "specialist_signoff_blocked" for event in memory.events)
    completed = [event for event in memory.events if event[1] == "specialist_reviews_completed"]
    assert completed[-1][3]["needs_repair"] is True
    assert completed[-1][3]["signoff_state"] == "repair"


def _failed_fidelity_run():
    return {
        "run_id": "design-host-repair",
        "operation_kind": "initial_build",
        "mode": "production_candidate",
        "status": "needs_repair",
        "candidate_sha": "c" * 40,
        "quality_report_json": {
            "state": "failed",
            "gates": {"temporal": "failed", "browser": "passed"},
            "findings": [{
                "gate": "temporal",
                "severity": "blocker",
                "code": "signature_behavior_unobserved",
                "message": "The locked signature behavior was not observed.",
                "signature_behavior_id": "behavior-dive-lamp",
            }],
            "evidence": {
                "browser": {
                    "viewports": [{
                        "viewport": {"name": "desktop", "width": 1440, "height": 1000},
                        "result": {"routes": [{
                            "route": "index.html",
                            "screenshot_path": "/tmp/shot-desktop.png",
                            "screenshot_hash": "abc",
                        }]},
                    }],
                },
                "motion": {"status": "failed"},
                "experience_journey": {"status": "passed"},
                "temporal": {"status": "failed"},
            },
        },
    }


def test_host_evidence_defect_queues_one_bounded_ada_repair():
    run = _failed_fidelity_run()

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def list_design_run_children(self, parent_run_id, limit=50):
            return []

        def list_design_phase_artifacts(self, run_id, phase, status):
            return []

    class Service:
        def __init__(self, memory):
            self.memory = memory
            self.calls = []

        def get_run(self, run_id):
            return run

        def create_visual_refinement_run(self, parent_run_id, critique, **kwargs):
            self.calls.append((parent_run_id, critique, kwargs))
            return {"run": {"run_id": "design-host-repair-child"}}

    memory = Memory()
    service = Service(memory)
    executor = DesignJobExecutor(
        {"memory": memory, "config": {"design_engine": {"repair_attempts": 1}}},
        service,
    )

    executor._queue_host_evidence_repair_if_needed(run["run_id"])

    assert len(service.calls) == 1
    parent_run_id, critique, kwargs = service.calls[0]
    assert parent_run_id == "design-host-repair"
    assert critique.state == "repair"
    assert critique.model_id == "host-deterministic-evidence"
    assert critique.candidate_sha == "c" * 40
    assert kwargs["host_evidence_repair"] is True
    assert kwargs["repair_brief"]["failed_findings"][0]["signature_behavior_id"] == "behavior-dive-lamp"
    assert kwargs["repair_brief"]["render_status"]["screenshot_count"] == 1
    assert critique.screenshot_evidence[0]["screenshot_path"] == "/tmp/shot-desktop.png"
    assert executor._queued == {"design-host-repair-child"}
    assert any(event[1] == "host_evidence_repair_queued" for event in memory.events)


def test_host_evidence_repair_does_not_nest_or_repeat():
    run = _failed_fidelity_run()

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def list_design_run_children(self, parent_run_id, limit=50):
            return [{"operation_kind": "visual_refinement", "status": "needs_repair"}]

        def list_design_phase_artifacts(self, run_id, phase, status):
            return []

    class Service:
        def get_run(self, run_id):
            return run

        def create_visual_refinement_run(self, *args, **kwargs):
            raise AssertionError("a live repair child must block a second repair")

    memory = Memory()
    executor = DesignJobExecutor(
        {"memory": memory, "config": {"design_engine": {"repair_attempts": 1}}},
        Service(),
    )

    executor._queue_host_evidence_repair_if_needed(run["run_id"])

    assert executor._queued == set()


def test_host_evidence_repair_respects_the_configured_bound():
    run = _failed_fidelity_run()

    class Memory:
        def add_design_run_event(self, *args):
            pass

        def list_design_run_children(self, parent_run_id, limit=50):
            return []

        def list_design_phase_artifacts(self, run_id, phase, status):
            return []

    class Service:
        def get_run(self, run_id):
            return run

        def create_visual_refinement_run(self, *args, **kwargs):
            raise AssertionError("repair_attempts: 0 must not create a repair child")

    executor = DesignJobExecutor(
        {"memory": Memory(), "config": {"design_engine": {"repair_attempts": 0}}},
        Service(),
    )

    executor._queue_host_evidence_repair_if_needed(run["run_id"])

    assert executor._queued == set()


def test_required_specialist_review_crash_marks_run_incomplete():
    run = {
        "run_id": "design-crash",
        "operation_kind": "initial_build",
        "status": "candidate_ready",
        "candidate_sha": "c" * 40,
        "quality_report_json": {"state": "passed"},
        "events": [],
    }

    class Memory:
        def __init__(self):
            self.events = []

        def add_design_run_event(self, *args):
            self.events.append(args)

        def get_design_run(self, run_id):
            return run

        def transition_design_run(self, run_id, status, error=None):
            run["status"] = status
            run["error"] = error
            return run

    class Service:
        def get_run(self, run_id):
            return run

        def clone_path_for_run(self, run_id):
            return "/tmp/design-crash-clone"

        def validate_run(self, run_id, clone, browser=None):
            run["status"] = "ready_for_review"

    memory = Memory()
    executor = DesignJobExecutor({"memory": memory}, Service())

    def explode(run_id):
        raise RuntimeError("creative realization provider failed")

    executor._run_specialist_reviews_if_ready = explode

    executor._run(run["run_id"])

    assert run["status"] == "incomplete"
    assert any(event[1] == "specialist_review_incomplete" for event in memory.events)
