from dataclasses import dataclass
from types import SimpleNamespace

from site_agent.core.design_contracts import (
    BuildTarget,
    CreativeRealizationReview,
    PageBuildRequest,
)
from site_agent.core.memory import Memory
from site_agent.application.design_orchestration import SpecialistDesignCoordinator
from site_agent.hands.builder import NativeOpenCodeBuilder


def _request(run_id="design-orchestration-1"):
    return PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": run_id,
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Present a cave-diving exploration week.",
        "acceptance_criteria": ["Make the offer clear."],
        "site_intake_hash": "b" * 64,
        "content": {"creative_prompt": "Create a distinctive homepage."},
    })


def _target(run_id="design-orchestration-1"):
    return BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": f"refs/ada-design-lab/{run_id}",
        "push_mode": "none",
        "publishable": False,
        "clone_path": "/tmp/design-orchestration",
        "allowed_paths": ["src/**"],
    })


def _run(memory, run_id):
    memory.create_design_run(
        run_id=run_id,
        mode="local_experiment",
        status="created",
        intake_json={"business": {"name": "Claro Oscuro"}},
        intake_hash="b" * 64,
        base_sha="a" * 40,
        publishable=False,
        candidate_ref=f"refs/ada-design-lab/{run_id}",
    )


@dataclass
class _Result:
    role: str
    session_id: str
    payload: dict

    def provider_dict(self):
        return {"reply": __import__("json").dumps(self.payload), "session_id": self.session_id, "usage": {}}


class _FakeInvoker:
    def __init__(self):
        self.calls = []

    def invoke(self, request, progress=None):
        self.calls.append(request.role)
        phase = (
            "copy"
            if request.role == "copywriter"
            else "concept"
            if request.role == "concept-designer"
            else "motion"
            if request.role == "motion-designer"
            else "creative_realization_review"
            if request.role == "creative-director" and "continuing the selection session" in request.prompt
            else "creative_final_signoff"
            if request.role == "creative-director" and "final sign-off" in request.prompt
            else "experience_review"
            if request.role == "experience-critic"
            else "technical_review"
            if request.role == "technical-critic"
            else "creative_selection"
        )
        variant = "primary"
        if request.role == "concept-designer":
            variant = request.prompt.split("variant ", 1)[1].split(".", 1)[0]
        elif request.role == "experience-critic":
            variant = "experience"
        elif request.role == "technical-critic":
            variant = "technical"
        payload = {
            "schema_version": 1,
            "run_id": "design-orchestration-1",
            "phase": phase,
            "variant_key": variant,
            "attempt": 1,
            "status": "completed",
            "base_sha": "a" * 40,
            "context_snapshot_hash": "",
            "input_hashes": [],
            "producer": request.role,
            "payload": {"idea": request.role + "-" + variant, "needs_repair": False, "state": "passed"},
        }
        return _Result(request.role, request.role + "-session", payload)


def test_coordinator_runs_three_concepts_and_one_selection(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    _run(memory, "design-orchestration-1")
    fake = _FakeInvoker()
    coordinator = SpecialistDesignCoordinator(
        {"memory": memory, "config": {"design_engine": {"model": "test"}}},
        invoker=fake,
    )

    result = coordinator.create_plan(_request(), _target())

    assert len(result.concepts) == 3
    assert result.plan.phase == "creative_selection"
    assert fake.calls.count("concept-designer") == 3
    assert fake.calls.count("copywriter") == 1
    assert fake.calls.count("creative-director") == 1
    assert len(memory.list_design_phase_artifacts("design-orchestration-1", status="completed")) == 5
    memory.close()


def test_coordinator_reuses_completed_phases_after_restart(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    _run(memory, "design-orchestration-1")
    fake = _FakeInvoker()
    coordinator = SpecialistDesignCoordinator(
        {"memory": memory, "config": {"design_engine": {"model": "test"}}},
        invoker=fake,
    )
    coordinator.create_plan(_request(), _target())
    first_call_count = len(fake.calls)

    restarted = SpecialistDesignCoordinator(
        {"memory": memory, "config": {"design_engine": {"model": "test"}}},
        invoker=fake,
    )
    restarted.create_plan(_request(), _target())

    assert len(fake.calls) == first_call_count
    memory.close()


def test_native_builder_opt_in_routes_locked_plan_to_implementation(monkeypatch):
    plan = object()

    class FakeCoordinator:
        def __init__(self, context):
            self.context = context

        def create_plan(self, request, target, progress=None, **kwargs):
            assert request == "request"
            assert target == "target"
            return SimpleNamespace(plan=plan)

    calls = []

    def fake_stage(context, request, target, progress=None, design_plan=None, plan_builder=None):
        if plan_builder is not None:
            design_plan = plan_builder(())
        calls.append((context, request, target, progress, design_plan))
        return "receipt"

    monkeypatch.setattr(
        "site_agent.application.design_orchestration.SpecialistDesignCoordinator",
        FakeCoordinator,
    )
    monkeypatch.setattr("site_agent.hands.opencode_runner.stage_design_build", fake_stage)

    builder = NativeOpenCodeBuilder({"config": {"design_engine": {"orchestration": "specialist"}}})
    assert builder.build_design("request", "target", "progress") == "receipt"
    assert calls == [
        (
            builder.context,
            "request",
            "target",
            "progress",
            plan,
        )
    ]


def test_native_builder_routes_specialist_repair_to_repair_agent(monkeypatch):
    calls = []

    def fake_stage(context, request, target, progress=None, design_plan=None, repair_brief=None):
        calls.append((design_plan, repair_brief))
        return "receipt"

    monkeypatch.setattr("site_agent.hands.opencode_runner.stage_design_build", fake_stage)
    request = SimpleNamespace(
        content={
            "specialist_repair_brief": {"scope": "repair the hero"},
            "specialist_locked_plan": {"phase": "creative_selection"},
        }
    )
    target = SimpleNamespace(operation_kind="visual_refinement")
    builder = NativeOpenCodeBuilder({"config": {"design_engine": {"orchestration": "specialist"}}})

    assert builder.build_design(request, target) == "receipt"
    assert calls == [
        (
            {"phase": "creative_selection"},
            {"scope": "repair the hero"},
        )
    ]


def test_coordinator_records_implementation_then_runs_motion_in_same_workspace(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    _run(memory, "design-orchestration-1")
    fake = _FakeInvoker()
    coordinator = SpecialistDesignCoordinator(
        {"memory": memory, "config": {"design_engine": {"model": "test"}}},
        invoker=fake,
    )
    request = _request()
    target = _target()
    plan = coordinator.create_plan(request, target).plan

    implementation = coordinator.record_implementation_phase(
        request,
        target,
        plan=plan,
        provider_result={"session_id": "implementation-session", "reply": "implemented"},
    )
    motion = coordinator.run_motion_phase(
        request,
        target,
        plan=plan,
        workspace=tmp_path,
    )

    assert implementation.phase == "implementation"
    assert motion.phase == "motion"
    assert fake.calls[-1] == "motion-designer"
    assert len(memory.list_design_phase_artifacts("design-orchestration-1", status="completed")) == 7
    memory.close()


def test_coordinator_runs_one_creative_review_and_two_independent_critics(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    _run(memory, "design-orchestration-1")
    fake = _FakeInvoker()
    coordinator = SpecialistDesignCoordinator(
        {"memory": memory, "config": {"design_engine": {"model": "test"}}},
        invoker=fake,
    )
    request = _request()
    target = _target()
    plan = coordinator.create_plan(request, target).plan

    review = coordinator.review_candidate(
        request,
        target,
        plan=plan,
        candidate_sha="c" * 40,
        screenshots=[{"route": "/", "screenshot_path": "/tmp/missing.png"}],
        quality_evidence={"state": "passed"},
    )

    assert review.needs_repair is False
    assert review.creative_review.phase == "creative_realization_review"
    assert review.experience_review.phase == "experience_review"
    assert review.technical_review.phase == "technical_review"
    assert fake.calls.count("creative-director") == 2
    assert fake.calls.count("experience-critic") == 1
    assert fake.calls.count("technical-critic") == 1
    assert len(memory.list_design_phase_artifacts("design-orchestration-1", status="completed")) == 8
    memory.close()


def test_coordinator_freezes_repair_brief_and_final_signoff_is_same_director_session(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    _run(memory, "design-orchestration-1")
    fake = _FakeInvoker()
    coordinator = SpecialistDesignCoordinator(
        {"memory": memory, "config": {"design_engine": {"model": "test"}}},
        invoker=fake,
    )
    request = _request()
    target = _target()
    plan_result = coordinator.create_plan(request, target)
    review = coordinator.review_candidate(request, target, plan=plan_result.plan, candidate_sha="c" * 40)

    repair_review = CreativeRealizationReview.from_dict({
        **review.creative_review.to_dict(),
        "payload": {"needs_repair": True, "state": "repair", "findings": [{"message": "repair"}]},
        "phase": "creative_realization_review",
        "run_id": request.run_id,
        "base_sha": target.base_sha,
        "context_snapshot_hash": "",
        "input_hashes": [],
        "producer": "creative-director",
        "variant_key": "primary",
        "attempt": 1,
        "status": "completed",
    })
    from site_agent.application.design_orchestration import DesignReviewResult

    repair_review_result = DesignReviewResult(
        creative_review=repair_review,
        experience_review=review.experience_review,
        technical_review=review.technical_review,
    )
    brief = coordinator.create_repair_brief(
        request,
        target,
        plan=plan_result.plan,
        review=repair_review_result,
    )
    assert brief is not None
    repair = coordinator.record_repair_phase(
        request,
        target,
        repair_brief=brief.payload,
        provider_result={"session_id": "repair-session", "reply": "repaired"},
    )
    assert repair.phase == "repair"

    signoff = coordinator.final_signoff(
        request,
        target,
        plan=plan_result.plan,
        review=review,
        creative_director_session_id=plan_result.creative_director_session_id,
    )
    assert signoff.phase == "creative_final_signoff"
    assert len(memory.list_design_phase_artifacts("design-orchestration-1", status="completed")) == 11
    memory.close()
