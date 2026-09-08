from dataclasses import dataclass
from types import SimpleNamespace

from site_agent.core.design_contracts import BuildTarget, PageBuildRequest
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
        phase = "copy" if request.role == "copywriter" else "concept" if request.role == "concept-designer" else "creative_selection"
        variant = "primary"
        if request.role == "concept-designer":
            variant = request.prompt.split("variant ", 1)[1].split(".", 1)[0]
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
            "payload": {"idea": request.role + "-" + variant},
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

        def create_plan(self, request, target, progress=None):
            assert request == "request"
            assert target == "target"
            return SimpleNamespace(plan=plan)

    calls = []

    def fake_stage(context, request, target, progress=None, design_plan=None):
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
