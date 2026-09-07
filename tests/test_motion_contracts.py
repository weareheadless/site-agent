import copy

import pytest

from site_agent.core.contracts import ContractError
from site_agent.core.motion_contracts import MotionPlan
from site_agent.core.react_design_contracts import ReactDesignSpec
from tests.test_react_design_contracts import _spec


def _motion_plan() -> dict:
    return {
        "schema_version": 1,
        "creative_thesis": "The page reveals useful detail with a measured rhythm.",
        "audience_fit": "Technical buyers can inspect the offer without losing the next step.",
        "template_policy": "forbid",
        "reduced_motion": {
            "strategy": "static",
            "details": "All content remains visible without transform or transition effects.",
            "preserves_content": True,
        },
        "capabilities": [
            "core", "scrolltrigger", "stagger", "pin", "scrub", "hover", "flip", "observer", "draggable", "signature",
        ],
        "pages": [{
            "path": "index.html",
            "sections": [
                {
                    "id": "section-0",
                    "purpose": "Establish the offer and orient the visitor.",
                    "actions": [
                        {
                            "kind": "entrance",
                            "capability": "core",
                            "target": "section-0",
                            "from": {"opacity": 0, "y": 24},
                            "to": {"opacity": 1, "y": 0},
                            "duration": 0.8,
                            "ease": "power3.out",
                        },
                        {
                            "kind": "parallax",
                            "capability": "scrolltrigger",
                            "target": "section-0",
                            "start": "top 88%",
                            "end": "bottom 20%",
                            "scrub": 1.2,
                            "to": {"yPercent": 8},
                        },
                    ],
                },
                {
                    "id": "section-1",
                    "purpose": "Give the visitor a quiet comparison point.",
                    "actions": [{
                        "kind": "stagger",
                        "capability": "stagger",
                        "target": "section-1",
                        "stagger": {"each": 0.08, "from": "start"},
                        "to": {"opacity": 1, "y": 0},
                    }],
                },
            ],
        }],
        "signature_interaction": "A single tide-line marks the transition into action.",
        "custom_components": [],
    }


def test_motion_plan_round_trips_and_reaches_the_react_design_spec():
    value = _spec()
    value["motion_plan"] = _motion_plan()

    spec = ReactDesignSpec.from_dict(value)

    assert spec.motion_plan.to_dict() == _motion_plan()
    assert spec.motion_plan.pages[0].sections[0].actions[1].kind == "parallax"
    assert spec.motion_plan.content_hash


@pytest.mark.parametrize(
    ("strategy", "canonical"),
    [
        ("no-motion", "static"),
        ("opacity only", "fade-only"),
        ("alternative", "alternate"),
    ],
)
def test_motion_plan_canonicalizes_bounded_reduced_motion_strategy_aliases(strategy, canonical):
    value = _motion_plan()
    value["reduced_motion"]["strategy"] = strategy

    plan = MotionPlan.from_dict(value)

    assert plan.reduced_motion["strategy"] == canonical


def test_motion_plan_still_rejects_unbounded_reduced_motion_strategy():
    value = _motion_plan()
    value["reduced_motion"]["strategy"] = "invent-a-new-runtime-mode"

    with pytest.raises(ContractError, match="strategy is unsupported"):
        MotionPlan.from_dict(value)


@pytest.mark.parametrize(
    ("capability", "canonical"),
    [
        ("GSAP", "core"),
        ("Scroll Trigger", "scrolltrigger"),
        ("React component", "react"),
    ],
)
def test_motion_plan_canonicalizes_bounded_capability_aliases(capability, canonical):
    value = _motion_plan()
    value["capabilities"].append(capability)

    plan = MotionPlan.from_dict(value)

    assert canonical in plan.capabilities


def test_motion_plan_still_rejects_unbounded_capability():
    value = _motion_plan()
    value["capabilities"][0] = "invented-runtime"

    with pytest.raises(ContractError, match=r"motion_plan\.capabilities\[0\] is unsupported"):
        MotionPlan.from_dict(value)


def test_react_design_spec_derives_a_typed_plan_for_legacy_motion_data():
    spec = ReactDesignSpec.from_dict(_spec())

    assert spec.motion_plan.pages[0].path == "index.html"
    assert [section.section_id for section in spec.motion_plan.pages[0].sections] == ["section-0", "section-1"]
    assert all(section.actions[0].kind == "entrance" for section in spec.motion_plan.pages[0].sections)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["motion_plan"]["pages"][0]["sections"][0]["actions"][0].update({"target": "section-0\" onmouseover=bad"}),
        lambda value: value["motion_plan"]["pages"][0]["sections"][0]["actions"][0].update({"to": {"onComplete": "alert(1)"}}),
        lambda value: value["motion_plan"]["pages"][0]["sections"][0]["actions"][0].update({"kind": "arbitrary"}),
        lambda value: value["motion_plan"].update({"template_policy": "starter-template"}),
    ],
)
def test_motion_plan_rejects_unsafe_or_unapproved_intent(mutate):
    value = _spec()
    value["motion_plan"] = _motion_plan()
    mutate(value)

    with pytest.raises(ContractError):
        ReactDesignSpec.from_dict(value)


def test_motion_plan_rejects_page_or_section_drift():
    value = _spec()
    value["motion_plan"] = _motion_plan()
    value["motion_plan"]["pages"][0]["sections"].pop()

    with pytest.raises(ContractError, match="section"):
        ReactDesignSpec.from_dict(value)


def test_motion_plan_accepts_only_host_registered_react_components():
    value = _spec()
    plan = _motion_plan()
    plan["custom_components"] = [{
        "id": "motion-interaction",
        "path": "src/components/interactive/MotionInteraction.tsx",
        "export": "default",
        "purpose": "A bounded host-owned React motion island.",
        "capabilities": ["react"],
    }]
    plan["pages"][0]["sections"][1]["actions"][0]["custom_component_id"] = "motion-interaction"
    value["motion_plan"] = plan

    spec = ReactDesignSpec.from_dict(value)

    assert spec.motion_plan.custom_components[0].component_id == "motion-interaction"

    unsafe = copy.deepcopy(value)
    unsafe["motion_plan"]["custom_components"][0]["path"] = "src/components/interactive/Unknown.tsx"
    with pytest.raises(ContractError, match="registry"):
        ReactDesignSpec.from_dict(unsafe)
