from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from site_agent.core.design_contracts import (
    BuildTarget,
    CreativeRealizationReview,
    ExperiencePlanBundle,
    PageBuildRequest,
    canonical_hash,
)
from site_agent.core.memory import Memory
from site_agent.application.design_orchestration import DesignOrchestrationError, SpecialistDesignCoordinator
from site_agent.hands.builder import NativeOpenCodeBuilder
from tests.test_design_contracts import _experience_plan


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


def test_host_binds_specialist_payload_to_phase_identity():
    request = _request()
    target = _target()

    wrapped = SpecialistDesignCoordinator._host_phase_envelope(
        {"brand_source_map": {"schema_version": 1, "identity_assets": ["asset.1"]}},
        request=request,
        target=target,
        role="brand-source-analyst",
        phase="brand_source",
        variant_key="primary",
        attempt=1,
        input_hashes=("a" * 64,),
    )

    assert wrapped["schema_version"] == 1
    assert wrapped["run_id"] == request.run_id
    assert wrapped["phase"] == "brand_source"
    assert wrapped["payload"]["brand_source_map"]["identity_assets"] == ["asset.1"]


def test_experience_fidelity_pass_binds_sighted_evidence_and_resumes_session(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    run_id = "sighted-fidelity-binding"
    _run(memory, run_id)
    request = _request(run_id)
    plan = ExperiencePlanBundle.from_dict(_experience_plan(
        run_id=run_id,
        base_sha="a" * 40,
        context_snapshot_hash="c" * 64,
    ))
    evidence = {
        "schema_version": 1,
        "status": "failed",
        "pass": 1,
        "review_surface": "owner_iframe",
        "image_files": ["/tmp/sighted.png"],
        "viewports": [{"viewport": {"name": "desktop"}, "console_errors": []}],
    }
    condition_ids = list(plan.experience_journey.must_pass_condition_ids)
    captured = {}

    class FidelityInvoker:
        def invoke(self, invocation, progress=None):
            captured["request"] = invocation
            payload = {
                "experience_plan_hash": plan.content_hash,
                "journey_condition_ids": condition_ids,
                "condition_coverage": [
                    {
                        "condition_id": condition_id,
                        "source_location": "src/app/page.tsx",
                        "trigger": "bounded scroll",
                        "rendered_state": "visible",
                        "responsive_translation": "Readable at each viewport.",
                        "reduced_motion_translation": "Settled state is immediate.",
                        "status": "implemented",
                        "notes": "",
                    }
                    for condition_id in condition_ids
                ],
                "state": "complete",
            }
            return _Result("experience-fidelity-specialist", "continued-session", payload)

    coordinator = SpecialistDesignCoordinator(
        {"memory": memory, "config": {"design_engine": {"specialist_timeout_seconds": 300}}},
        invoker=FidelityInvoker(),
    )

    report = coordinator.run_experience_fidelity_phase(
        request,
        _target(run_id),
        plan=plan,
        workspace=tmp_path,
        session_id="build-session",
        sighted_evidence=evidence,
        image_files=("/tmp/sighted.png",),
        timeout_seconds=42,
    )

    assert report.payload["state"] == "complete"
    invocation = captured["request"]
    assert invocation.session_id == "build-session"
    assert invocation.timeout_seconds == 42
    assert invocation.image_files == ("/tmp/sighted.png",)
    assert "HOST-CAPTURED SIGHTED IMPLEMENTATION EVIDENCE" in invocation.prompt
    assert "HOST WRITABLE PATH BOUNDARY (hard)" in invocation.prompt
    assert '"src/**"' in invocation.prompt
    assert canonical_hash(evidence) in invocation.prompt
    phase = memory.list_design_phase_artifacts(run_id, phase="experience_fidelity", status="completed")[0]
    assert canonical_hash(evidence) in phase["input_hashes"]
    memory.close()


def test_experience_plan_normalizes_unambiguous_singleton_array_shapes():
    normalized = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "asset_composition_plan": {
            "page_regions": "hero",
            "structural_contribution": "focal light",
            "prohibited_uses": "do not crop the diver",
            "acceptance_conditions": "the focal light remains visible",
            "evidence_refs": "media-2",
            "logo_rule": {
                "allowed_backgrounds": "near-black",
                "collision_exclusions": "hero copy",
                "evidence_refs": "media-1",
            },
        },
        "behavior_system": {
            "evidence_refs": "media-2",
            "conceptual_entities": {"id": "aperture"},
            "signature_behavior": {"acceptance_conditions": "the aperture opens"},
        },
        "protected_strengths": "light against darkness",
        "transfer_test": "passed",
        "review_rubric": {"condition": "the offer is clear"},
    })

    composition = normalized["asset_composition_plan"][0]
    assert composition["structural_contribution"] == ["focal light"]
    assert composition["logo_rule"]["evidence_refs"] == ["media-1"]
    assert normalized["behavior_system"]["conceptual_entities"] == [{"id": "aperture"}]
    assert normalized["protected_strengths"] == ["light against darkness"]
    assert normalized["transfer_test"] == {"state": "passed"}
    assert normalized["review_rubric"] == [{"condition": "the offer is clear", "id": "rubric-1"}]


def test_experience_plan_normalizes_nested_rubric_and_behavior_text_maps():
    normalized = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "asset_composition_plan": [{
            "asset_id": "media-1",
            "logo_rule": "Keep the supplied mark unmodified.",
        }],
        "behavior_system": {
            "no_javascript_translation": {"content": "all content remains visible"},
            "scene_graph": [{"scene": "hero", "note": "show the primary action"}],
            "utility_behaviors": [{"name": "sticky action", "detail": "keep the waitlist reachable"}],
            "signature_behavior": {
                "name": "measured-arrival",
                "description": "The aperture opens as the visitor descends.",
            },
        },
        "review_rubric": {
            "schema_version": 1,
            "criteria": [{
                "name": "offer_clarity",
                "condition": "the offer is clear",
                "weight": "high",
            }],
        },
    })

    assert normalized["behavior_system"]["no_javascript_translation"] == (
        "content: all content remains visible"
    )
    assert normalized["behavior_system"]["scene_graph"] == [{
        "id": "scene-graph-1",
        "scene": "hero",
        "note": "show the primary action",
        "exit_condition": "show the primary action",
    }]
    assert normalized["behavior_system"]["signature_behavior"]["meaning"] == (
        "The aperture opens as the visitor descends."
    )
    assert normalized["behavior_system"]["utility_behaviors"][0]["meaning"] == (
        "keep the waitlist reachable"
    )
    assert normalized["asset_composition_plan"][0]["logo_rule"] is None
    assert normalized["asset_composition_plan"][0]["relationship_to_other_assets"] == (
        "Logo instruction: Keep the supplied mark unmodified."
    )
    assert normalized["review_rubric"] == [{
        "name": "offer_clarity",
        "condition": "the offer is clear",
        "weight": "high",
        "id": "offer_clarity",
    }]
    legacy_rubric = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "review_rubric": [{
            "criterion": "offer_clarity",
            "pass": "the offer is clear",
            "weight": "high",
        }],
    })
    assert legacy_rubric["review_rubric"] == [{
        "criterion": "offer_clarity",
        "pass": "the offer is clear",
        "weight": "high",
        "id": "offer_clarity",
        "condition": "the offer is clear",
    }]
    threshold_rubric = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "review_rubric": [{
            "id": "rubric-offer",
            "criterion": "offer clarity",
            "threshold": "the offer is visible",
        }],
    })
    assert threshold_rubric["review_rubric"][0]["condition"] == "the offer is visible"
    criterion_rubric = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "review_rubric": [{"criterion": "the journey transition is observable", "weight": "high"}],
    })
    assert criterion_rubric["review_rubric"] == [{
        "criterion": "the journey transition is observable",
        "weight": "high",
        "id": "the-journey-transition-is-observable",
        "condition": "the journey transition is observable",
    }]


def test_experience_plan_binds_missing_journey_metadata_from_behavior_and_scenes():
    normalized = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "selected_concept_id": "beam-descent",
        "behavior_system": {
            "thesis": "The line carries attention through the page.",
            "signature_behavior": {"id": "line-descent"},
            "evidence_refs": ["media-1"],
        },
        "experience_journey": {
            "signature_scene_id": "arrival",
            "scenes": [{"id": "arrival", "evidence_refs": ["media-2"]}],
        },
    })

    journey = normalized["experience_journey"]
    assert journey["journey_id"] == "beam-descent"
    assert journey["thesis"] == "The line carries attention through the page."
    assert journey["signature_behavior_id"] == "line-descent"
    assert journey["evidence_refs"] == ["media-1", "media-2"]


def test_experience_plan_normalizes_scalar_signature_behavior_without_inventing_meaning():
    normalized = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "behavior_system": {
            "signature_behavior": "A continuous guideline carries the light from the aperture to the CTA.",
        },
    })

    assert normalized["behavior_system"]["signature_behavior"] == {
        "id": "signature-behavior",
        "meaning": "A continuous guideline carries the light from the aperture to the CTA.",
        "acceptance_conditions": [
            "A continuous guideline carries the light from the aperture to the CTA."
        ],
    }
    bound = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "experience_journey": {"signature_behavior_id": "beam-descent"},
        "behavior_system": {"signature_behavior": "The beam carries the visitor through the descent."},
    })
    assert bound["behavior_system"]["signature_behavior"]["id"] == "beam-descent"


def test_experience_plan_normalizes_text_performance_budget_list_to_object():
    normalized = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "behavior_system": {
            "performance_budget": [
                "No animated layout properties.",
                "Keep image loading below the second viewport lazy.",
            ],
        },
    })

    assert normalized["behavior_system"]["performance_budget"] == {
        "constraints": [
            "No animated layout properties.",
            "Keep image loading below the second viewport lazy.",
        ],
    }


def test_experience_plan_normalizes_rubric_pass_condition_alias():
    normalized = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "review_rubric": [{
            "id": "offer_clarity",
            "criterion": "The offer is identifiable.",
            "pass_condition": "The hero names the exploration week.",
        }],
    })

    assert normalized["review_rubric"] == [{
        "id": "offer_clarity",
        "criterion": "The offer is identifiable.",
        "pass_condition": "The hero names the exploration week.",
        "condition": "The hero names the exploration week.",
    }]


def test_experience_plan_normalizes_scene_text_arrays():
    normalized = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "experience_journey": {
            "scenes": [{
                "content_region": ["offer", "where"],
                "mobile_translation": ["stack copy", "keep beam visible"],
            }],
        },
    })

    assert normalized["experience_journey"]["scenes"][0]["content_region"] == "offer; where"
    assert normalized["experience_journey"]["scenes"][0]["mobile_translation"] == (
        "stack copy; keep beam visible"
    )


def test_experience_plan_normalizes_duplicate_and_extra_journey_conditions():
    normalized = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "experience_journey": {
            "scenes": [
                {"id": "surface", "acceptance_condition_ids": ["facts-visible", "accent-disciplined"]},
                {"id": "descent", "acceptance_condition_ids": ["accent-disciplined", "facts-visible"]},
            ],
            "must_pass_condition_ids": ["facts-visible", "unused-condition"],
        },
    })

    scenes = normalized["experience_journey"]["scenes"]
    assert scenes[0]["acceptance_condition_ids"] == ["facts-visible", "accent-disciplined"]
    assert scenes[1]["acceptance_condition_ids"] == [
        "accent-disciplined-descent",
        "facts-visible-descent",
    ]
    assert normalized["experience_journey"]["must_pass_condition_ids"] == [
        "facts-visible",
        "accent-disciplined",
        "accent-disciplined-descent",
        "facts-visible-descent",
    ]


def test_experience_plan_normalizes_scene_order_from_array_position():
    normalized = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "experience_journey": {
            "scenes": [
                {"id": "surface", "order": 0, "acceptance_condition_ids": ["surface-ready"]},
                {"id": "descent", "order": 0, "acceptance_condition_ids": ["descent-ready"]},
            ],
        },
    })

    assert [scene["order"] for scene in normalized["experience_journey"]["scenes"]] == [1, 2]


def test_experience_plan_normalizes_behavior_record_aliases():
    normalized = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "behavior_system": {
            "state_variables": [{"id": "scroll", "owner": "scroll progress", "range": "0 to 1"}],
            "scene_graph": [{"scene_id": "surface", "next": "descent"}, {"scene_id": "descent", "next": None}],
            "utility_behaviors": [{"id": "progress", "purpose": "Show position through the journey"}],
        },
    })

    behavior = normalized["behavior_system"]
    assert behavior["state_variables"][0]["meaning"] == "owner: scroll progress; range: 0 to 1"
    assert behavior["scene_graph"] == [
        {"scene_id": "surface", "next": "descent", "id": "surface", "exit_condition": "continues to descent"},
        {
            "scene_id": "descent",
            "next": None,
            "id": "descent",
            "exit_condition": "terminal scene completes the ordered journey",
        },
    ]
    assert behavior["utility_behaviors"] == [{
        "id": "progress",
        "purpose": "Show position through the journey",
        "meaning": "Show position through the journey",
    }]


def test_experience_plan_normalizes_input_signal_source_as_meaning():
    normalized = SpecialistDesignCoordinator._normalize_experience_plan_payload({
        "behavior_system": {
            "input_signals": [
                {"name": "scroll-position", "source": "document body ScrollTrigger scrub"},
                {"name": "reduced-motion", "source": "gsap.matchMedia no-preference query"},
            ],
        },
    })

    assert normalized["behavior_system"]["input_signals"] == [
        {
            "name": "scroll-position",
            "source": "document body ScrollTrigger scrub",
            "id": "scroll-position",
            "meaning": "document body ScrollTrigger scrub",
        },
        {
            "name": "reduced-motion",
            "source": "gsap.matchMedia no-preference query",
            "id": "reduced-motion",
            "meaning": "gsap.matchMedia no-preference query",
        },
    ]


def test_brand_source_confidence_keys_are_bound_to_machine_safe_ids():
    fields = {
        "schema_version": 1,
        "identity_assets": [],
        "primary_brand_signals": ["light and darkness"],
        "geometry_vocabulary": [],
        "spacing_rhythm": [],
        "line_and_edge_language": [],
        "color_relationships": [],
        "type_relationship_hypotheses": [],
        "material_relationships": [],
        "image_treatment_hypotheses": [],
        "signals_to_preserve": [],
        "signals_not_safe_to_infer": [],
        "owner_evidence_refs": ["owner:brand"],
        "asset_evidence_refs": [],
        "confidence_by_signal": {"Light / dark contrast": 0.9},
    }

    result = SpecialistDesignCoordinator._brand_source_map(
        SimpleNamespace(payload={"brand_source_map": fields})
    )

    assert result.confidence_by_signal == {"Light-dark-contrast": 0.9}


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


def test_native_builder_uses_runtime_execution_context_for_plan_phases(monkeypatch):
    plan = object()
    coordinator_contexts = []

    class FakeCoordinator:
        def __init__(self, context):
            coordinator_contexts.append(context)

        def create_plan(self, request, target, progress=None, **kwargs):
            return SimpleNamespace(plan=plan)

    def fake_stage(context, request, target, progress=None, design_plan=None, plan_builder=None):
        assert plan_builder is not None
        design_plan = plan_builder((), {**context, "api_key": "runtime-key"})
        return design_plan

    monkeypatch.setattr(
        "site_agent.application.design_orchestration.SpecialistDesignCoordinator",
        FakeCoordinator,
    )
    monkeypatch.setattr("site_agent.hands.opencode_runner.stage_design_build", fake_stage)

    builder = NativeOpenCodeBuilder({"config": {"design_engine": {"orchestration": "specialist"}}})
    assert builder.build_design("request", "target") is plan
    assert coordinator_contexts == [{
        "config": {"design_engine": {"orchestration": "specialist"}},
        "api_key": "runtime-key",
    }]


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


def test_native_builder_forwards_a_locked_plan_without_a_specialist_repair_brief(monkeypatch):
    calls = []

    def fake_stage(context, request, target, progress=None, design_plan=None, repair_brief=None):
        calls.append((design_plan, repair_brief))
        return "receipt"

    monkeypatch.setattr("site_agent.hands.opencode_runner.stage_design_build", fake_stage)
    request = SimpleNamespace(
        content={"specialist_locked_plan": {"experience": "preserve this journey"}},
    )
    target = SimpleNamespace(operation_kind="visual_refinement")
    builder = NativeOpenCodeBuilder({"config": {"design_engine": {"orchestration": "creative"}}})

    assert builder.build_design(request, target) == "receipt"
    assert calls == [
        (
            {"experience": "preserve this journey"},
            None,
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


def test_coordinator_rejects_deferred_local_check_for_experience_plan(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    _run(memory, "design-orchestration-1")
    coordinator = SpecialistDesignCoordinator(
        {"memory": memory, "config": {"design_engine": {"model": "test"}}},
        invoker=_FakeInvoker(),
    )
    request = _request()
    target = _target()
    plan = coordinator.create_plan(request, target).plan
    fake_experience_plan = SimpleNamespace(
        content_hash="d" * 64,
        experience_journey=SimpleNamespace(must_pass_condition_ids=("journey-one",)),
    )
    monkeypatch.setattr(
        "site_agent.application.design_orchestration.ExperiencePlanBundle.from_dict",
        lambda payload: fake_experience_plan,
    )

    with pytest.raises(DesignOrchestrationError, match="passed local check"):
        coordinator.record_implementation_phase(
            request,
            target,
            plan=plan,
            provider_result={
                "session_id": "implementation-session",
                "reply": "implemented",
                "experience_plan_hash": fake_experience_plan.content_hash,
                "journey_condition_ids": ["journey-one"],
                "journey_coverage": [{"condition_id": "journey-one", "status": "implemented"}],
                "local_check_status": "deferred_to_host_build_and_browser_gates",
            },
        )
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


def test_transfer_instruction_lists_every_locked_condition():
    from site_agent.core.design_contracts import ExperiencePlanBundle
    from tests.test_design_contracts import _experience_plan

    plan = ExperiencePlanBundle.from_dict(_experience_plan())
    instruction = SpecialistDesignCoordinator._transfer_instruction(plan)

    assert plan.content_hash in instruction
    for condition in plan.experience_journey.must_pass_condition_ids:
        assert condition in instruction


def test_correction_instruction_carries_the_rejection_and_preserves_identity():
    from site_agent.core.design_contracts import ExperiencePlanBundle, TransferReview
    from tests.test_design_contracts import _experience_plan

    plan = ExperiencePlanBundle.from_dict(_experience_plan())
    transfer = TransferReview.from_dict({
        "schema_version": 1,
        "run_id": plan.run_id,
        "phase": "transfer_review",
        "variant_key": "primary",
        "attempt": 1,
        "status": "completed",
        "base_sha": plan.base_sha,
        "context_snapshot_hash": plan.context_snapshot_hash,
        "input_hashes": [],
        "producer": "transfer-critic",
        "payload": {
            "state": "rejected",
            "plan_hash": plan.content_hash,
            "journey_condition_ids": list(plan.experience_journey.must_pass_condition_ids),
            "evidence_specific_elements": ["the supplied cenote media"],
            "transferable_elements": [],
            "unsupported_metaphors": ["a generic parallax hero"],
            "required_corrections": ["tie the journey to the cave-diving evidence"],
        },
    })

    instruction = SpecialistDesignCoordinator._correction_instruction(plan, transfer)

    assert "a generic parallax hero" in instruction
    assert "tie the journey to the cave-diving evidence" in instruction
    assert plan.content_hash in instruction
    assert "preserve identity fields" in instruction


def test_specialist_reasoning_is_configured_per_phase(tmp_path):
    memory = Memory(tmp_path / "reasoning.db")
    coordinator = SpecialistDesignCoordinator(
        {
            "memory": memory,
            "config": {
                "design_engine": {
                    "specialist_reasoning_effort": "low",
                    "reasoning_by_phase": {
                        "creative_selection": "high",
                        "transfer_review": "high",
                    },
                },
                "builder": {"reasoning_effort": "medium"},
            },
        },
    )

    assert coordinator._specialist_reasoning("creative_selection", "creative-director") == "high"
    assert coordinator._specialist_reasoning("transfer_review", "transfer-critic") == "high"
    assert coordinator._specialist_reasoning("copy", "copywriter") == "low"
    assert coordinator._specialist_reasoning("concept", "concept-designer") == "low"
    memory.close()


def test_creative_orchestration_keeps_motion_in_the_integrated_build(monkeypatch):
    calls = []

    def fake_stage(context, request, target, progress=None, design_plan=None,
                   plan_builder=None, repair_brief=None):
        calls.append({
            "design_plan": design_plan,
            "repair_brief": repair_brief,
        })
        return "receipt"

    monkeypatch.setattr("site_agent.hands.opencode_runner.stage_design_build", fake_stage)

    builder = NativeOpenCodeBuilder({"config": {"design_engine": {"orchestration": "creative"}}})
    assert builder.build_design("request", "target", "progress") == "receipt"
    assert calls == [{"design_plan": None, "repair_brief": None}]
