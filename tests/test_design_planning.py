import json

import pytest

from site_agent.brain.art_direction import hypotheses, select_direction
from site_agent.brain.design_brief import assess_intake, compile_brief
from site_agent.brain.design_guidance import load_design_skills
from site_agent.brain.page_strategy import initial_homepage_request
from site_agent.brain.react_design import DeterministicDesignPlanner, LLMDesignPlanner, _normalize_model_motion, deterministic_spec
from site_agent.core.design_contracts import IncubatedCreativeContext, SiteIntake
from site_agent.core.motion_contracts import MotionPlan


def _intake(**overrides):
    value = {
        "schema_version": 1,
        "business": {
            "name": "Tide Workshop",
            "offer_summary": "Small-batch coastal furniture and repair.",
            "primary_services": ["Furniture", "Repair"],
            "location": "North Shore",
        },
        "audience": {"primary": "People looking for durable local furniture"},
        "conversion": {"primary_action": "Request a project conversation", "not_available": True},
        "brand": {"voice": "Quiet, exact, and human."},
        "site": {"required_pages": ["index.html", "about.html"]},
    }
    value.update(overrides)
    return SiteIntake.from_dict(value)


def test_assessment_preserves_unknowns_and_blocks_only_explicit_questions():
    intake = _intake(unknowns=["Pricing is not supplied."])
    assessment = assess_intake(intake)

    assert assessment.complete_enough is True
    assert "Pricing is not supplied." in assessment.non_blocking_unknowns
    assert "A contact destination has not been supplied." in assessment.non_blocking_unknowns

    blocked = _intake(constraints={"blocking_questions": ["Confirm the service area before implementation."]})
    blocked_assessment = assess_intake(blocked)
    assert blocked_assessment.complete_enough is False
    assert blocked_assessment.blocking_questions == ("Confirm the service area before implementation.",)
    with pytest.raises(ValueError, match="not complete"):
        compile_brief(blocked, blocked_assessment)


def test_selection_records_customer_specific_alternatives():
    intake = _intake()
    brief = compile_brief(intake)
    options = hypotheses(intake, brief)
    selection = select_direction(intake, brief)

    assert len(options) == 3
    assert len({option.name for option in options}) == 3
    assert selection.selected.selected is True
    assert len(selection.rejected) == 2
    assert all(item.rejection_reason for item in selection.rejected)
    assert "Tide Workshop" in selection.selected.business_relevance


def test_initial_page_strategy_is_typed_and_pinned():
    intake = _intake()
    brief = compile_brief(intake)
    direction = select_direction(intake, brief).selected

    request = initial_homepage_request(
        intake,
        brief,
        direction,
        run_id="design-plan",
        base_sha="a" * 40,
    )

    assert request.mode == "initial_homepage"
    assert request.page_path == "index.html"
    assert request.site_intake_hash == intake.content_hash
    assert "design_brief" in request.content
    assert direction.name not in json.dumps(request.content, sort_keys=True)


def test_initial_page_strategy_keeps_art_direction_out_of_builder_content():
    intake = _intake()
    brief = compile_brief(intake)
    direction = select_direction(intake, brief).selected

    request = initial_homepage_request(
        intake,
        brief,
        direction,
        run_id="design-independent",
        base_sha="a" * 40,
    )

    assert request.content["site_intake"] == intake.to_dict()
    assert "selected_art_direction" not in request.content


def test_llm_planner_exposes_owner_design_request_as_a_visual_brief():
    intake = _intake(design_request="Make the first viewport feel like an authored editorial piece, not a course template.")
    brief = compile_brief(intake)
    direction = select_direction(intake, brief).selected
    response = json.dumps(deterministic_spec(intake, brief, direction).to_dict())

    class RecordingClient:
        def __init__(self):
            self.messages = []

        def chat(self, messages, *, json_mode):
            self.messages = messages
            return response

    client = RecordingClient()
    planned = LLMDesignPlanner(
        client,
        current_site_evidence={"leak": "CURRENT_SITE_MARKER"},
        design_guidance="Use one confident visual gesture.",
        frontend_libraries=[{"name": "gsap", "version": "3.12.5", "capabilities": ["ScrollTrigger"]}],
        initial_homepage=True,
    ).plan(intake, brief, direction)

    assert planned.site_name == "Tide Workshop"
    assert "OWNER DESIGN REQUEST" in client.messages[1]["content"]
    assert "authored editorial piece" in client.messages[1]["content"]
    assert "DESIGN SKILLS AND CAPABILITIES" in client.messages[1]["content"]
    assert "one confident visual gesture" in client.messages[1]["content"]
    assert "AVAILABLE FRONTEND LIBRARIES" in client.messages[1]["content"]
    assert "3.12.5" in client.messages[1]["content"]
    assert "CURRENT SITE EVIDENCE" not in client.messages[1]["content"]
    assert "CURRENT_SITE_MARKER" not in client.messages[1]["content"]
    assert "SELECTED DIRECTION" not in client.messages[1]["content"]
    assert "strategy exactly one of static, fade-only, or alternate" in client.messages[1]["content"]
    assert "capabilities exactly one or more of core, timeline, stagger, scrolltrigger, parallax, pin, scrub, hover, flip, observer, draggable, react, or signature" in client.messages[1]["content"]


def test_llm_planner_fails_closed_for_unrecognized_reduced_motion_strategy():
    intake = _intake()
    brief = compile_brief(intake)
    direction = select_direction(intake, brief).selected
    response = deterministic_spec(intake, brief, direction).to_dict()
    response["motion_plan"] = MotionPlan.from_routes(
        response["routes"],
        motion=response["motion"],
        signature_interaction=response["signature_gesture"],
    ).to_dict()
    response["motion_plan"]["reduced_motion"]["strategy"] = "the model's custom reduced-motion mode"

    class RecordingClient:
        def chat(self, messages, *, json_mode):
            return json.dumps(response)

    planned = LLMDesignPlanner(RecordingClient()).plan(intake, brief, direction)

    assert planned.motion_plan.reduced_motion["strategy"] == "static"


def test_llm_planner_fails_closed_for_unrecognized_motion_capability():
    intake = _intake()
    brief = compile_brief(intake)
    direction = select_direction(intake, brief).selected
    response = deterministic_spec(intake, brief, direction).to_dict()
    response["motion_plan"] = MotionPlan.from_routes(
        response["routes"],
        motion=response["motion"],
        signature_interaction=response["signature_gesture"],
    ).to_dict()
    response["motion_plan"]["capabilities"][0] = "the model's custom animation engine"

    class RecordingClient:
        def chat(self, messages, *, json_mode):
            return json.dumps(response)

    planned = LLMDesignPlanner(RecordingClient()).plan(intake, brief, direction)

    assert planned.motion_plan.capabilities[0] == "core"


def test_llm_planner_requires_incubated_context_to_shape_design_and_copy():
    intake = _intake()
    brief = compile_brief(intake)
    direction = select_direction(intake, brief).selected
    context = IncubatedCreativeContext.from_dict({
        "genesis_revision": 2,
        "genesis_hash": "d" * 64,
        "owner_confirmed_visual_preferences": ["quiet editorial pacing"],
        "owner_confirmed_visual_dislikes": ["generic gradients"],
        "research_backed_creative_implications": [{"summary": "Visitors need technical reassurance."}],
        "cross_language_audience_insights": [],
        "customer_genesis": {
            "business_world": {"values": ["careful workmanship"]},
            "creative_identity": {"principles": ["make the useful detail visible"]},
            "research_identity": {"subjects": ["technical buyers"]},
        },
        "infusion_deductions": [{
            "deduction_id": "deduction_" + "d" * 32,
            "kind": "audience_hypothesis",
            "summary": "Technical buyers need proof before the first conversation.",
            "confidence": 0.8,
            "basis": "source",
            "source_refs": ["source_public"],
            "supports_paths": ["audience.primary"],
            "citation_uris": ["pipeworx://source/public"],
        }],
        "novelty_constraints": {},
        "patterns_to_avoid": ["generic gradients"],
        "design_skill_set": load_design_skills().to_dict(include_content=False),
    })
    response = json.dumps(deterministic_spec(intake, brief, direction).to_dict())

    class RecordingClient:
        def __init__(self):
            self.messages = []

        def chat(self, messages, *, json_mode):
            self.messages = messages
            return response

    client = RecordingClient()
    LLMDesignPlanner(
        client,
        initial_homepage=True,
        incubated_creative_context=context.to_dict(),
    ).plan(intake, brief, direction)

    prompt = client.messages[1]["content"]
    assert "AUDIENCE AND RESEARCH CONTEXT APPLICATION" in prompt
    assert "shape both visual decisions and page copy" in prompt
    assert "Do not turn recommendations or hypotheses into owner facts" in prompt
    assert "Technical buyers need proof before the first conversation." in prompt


def test_llm_planner_filters_model_assets_to_the_explicit_approved_set():
    intake = _intake(assets=[
        {"id": "5", "usage": "undecided", "position": 0, "role": "unapproved reference"},
        {"id": "11", "usage": "website", "position": 1, "role": "approved hero"},
    ])
    brief = compile_brief(intake)
    direction = select_direction(intake, brief).selected
    response = deterministic_spec(intake, brief, direction).to_dict()

    class RecordingClient:
        def chat(self, messages, *, json_mode):
            return json.dumps(response)

    planned = LLMDesignPlanner(
        RecordingClient(),
        initial_homepage=True,
        approved_asset_ids=("11",),
    ).plan(intake, brief, direction)

    assert [asset.asset_id for asset in planned.assets] == ["11"]
    referenced = {
        section.props["image_asset_id"]
        for route in planned.routes
        for section in route.sections
        if "image_asset_id" in section.props
    }
    assert referenced <= {"11"}


def test_llm_planner_normalizes_provider_shape_aliases_before_strict_validation():
    intake = _intake(assets=[{"id": "images/hero.jpg", "role": "hero reference", "source": "baseline evidence"}])
    brief = compile_brief(intake)
    direction = select_direction(intake, brief).selected
    response = {
        "schema_version": 1,
        "direction_id": direction.name,
        "site_name": "Tide Workshop",
        "language": "en",
        "site_url": "",
        "intake_hash": intake.content_hash,
        "navigation": [{"label": "Home", "href": "/", "available": True}],
        "tokens": {
            "colors": {"ink": "#132a28"},
            "type": {"display": {"family": "Cormorant Garamond"}},
            "spacing": {"section_padding": "6rem"},
            "layout": {"content_max": "72rem"},
            "shape": {"radius": "0"},
        },
        "routes": [{
            "id": "index",
            "output_path": "/",
            "title": "Tide Workshop",
            "description": "A careful service.",
            "h1": "A careful service.",
            "sections": [{
                "kind": "hero",
                "props": {
                    "title": "A careful service.",
                    "body": "A useful first step.",
                    "image_asset_id": "images/hero.jpg",
                },
            }],
        }],
        "assets": [{"id": "images/hero.jpg", "source": "published repository at baseline SHA", "role": "hero reference", "alt": "Hero"}],
        "logo_asset_id": "",
        "motion": {},
        "signature_gesture": "",
        "component_inventory": {"index": ["Hero"]},
        "omissions": [],
        "unknowns": [],
        "prohibited_claims": [],
    }

    class RecordingClient:
        def chat(self, messages, *, json_mode):
            return json.dumps(response)

    planned = LLMDesignPlanner(RecordingClient()).plan(intake, brief, direction)

    assert planned.routes[0].output_path == "index.html"
    assert planned.site_url == ""
    assert planned.navigation[0].to_dict() == {"label": "Home", "href": "/"}
    assert planned.tokens["type"]["display"] == "Cormorant Garamond"
    assert planned.assets[0].source == "images/hero.jpg"
    assert planned.component_inventory == ("Hero",)


def test_llm_planner_normalizes_host_motion_and_brand_font_fallbacks():
    intake = _intake(
        brand={
            "voice": "Quiet and exact.",
            "existing_fonts": {"body": "Manrope", "display": "Cormorant Garamond"},
            "existing_palette": {"sea": "#9edbd1"},
        }
    )
    brief = compile_brief(intake)
    direction = select_direction(intake, brief).selected
    response = {
        "schema_version": 1,
        "direction_id": direction.name,
        "site_name": "Tide Workshop",
        "language": "en",
        "site_url": "",
        "intake_hash": intake.content_hash,
        "navigation": [{"label": "Home", "href": "/"}],
        "tokens": {
            "colors": {
                "ink": "#132a28",
                "ink_primary": "#e6f1eb",
                "primary_surface": "#061116",
                "text_muted": "#90a7a6",
            },
            "type": {"body_measure": "max-width: 65ch"},
            "spacing": {"section_gap": "8rem"},
            "layout": {"container_width": "72rem", "container_padding": "2rem"},
            "shape": {"border_radius": "4px"},
        },
        "routes": [{
            "id": "home",
            "output_path": "index.html",
            "title": "Tide Workshop",
            "description": "A careful service.",
            "h1": "A careful service.",
            "sections": [
                {"kind": "hero", "props": {"title": "A careful service."}},
                {"kind": "editorial", "props": {"title": "A useful point of view.", "items": []}},
            ],
        }],
        "assets": [],
        "motion": {
            "primitive": "depth-descent",
            "parameters": {"duration": "slow"},
            "frontend_libraries": [{"name": "gsap"}],
            "reduced_motion_behavior": "fade",
        },
        "signature_gesture": "",
        "component_inventory": [],
        "omissions": [],
        "unknowns": [],
        "prohibited_claims": [],
    }

    class RecordingClient:
        def chat(self, messages, *, json_mode):
            return json.dumps(response)

    planned = LLMDesignPlanner(RecordingClient()).plan(intake, brief, direction)

    assert planned.motion["signature"] == "depth-descent"
    assert planned.motion["enabled"] is True
    assert planned.motion["libraries"] == ["gsap"]
    assert planned.motion["reduced_motion"] == "fade"
    assert planned.tokens["type"] == {"body": "Manrope", "display": "Cormorant Garamond"}
    assert planned.tokens["colors"]["sea"] == "#9edbd1"
    assert planned.tokens["colors"]["paper"] == "#061116"
    assert planned.tokens["colors"]["ink"] == "#e6f1eb"
    assert planned.tokens["colors"]["muted"] == "#90a7a6"
    assert planned.tokens["spacing"]["section"] == "8rem"
    assert planned.tokens["layout"]["container"] == "72rem"
    assert planned.tokens["layout"]["gutter"] == "2rem"
    assert planned.tokens["shape"]["radius"] == "4px"
    assert planned.signature_gesture == direction.signature_gesture
    assert "items" not in planned.routes[0].sections[1].props


def test_model_tide_line_intent_maps_to_the_bounded_depth_primitive():
    intake = _intake(
        business={
            "name": "Tide Workshop",
            "offer_summary": "Freediving depth training.",
            "primary_services": ["Depth training"],
            "location": "North Shore",
        },
        brand={"voice": "Quiet and exact.", "visual_preferences": ["depth and patience"]},
    )

    motion = _normalize_model_motion(
        {"on_scroll": {"signature_gesture_trigger": "section-boundary"}},
        intake,
        "A single tide-line rule marks the descent.",
    )

    assert motion["enabled"] is True
    assert motion["signature"] == "depth-descent"


def test_initial_model_motion_normalization_does_not_apply_subject_default():
    intake = _intake(
        business={
            "name": "Tide Workshop",
            "offer_summary": "Freediving depth training.",
            "primary_services": ["Depth training"],
            "location": "North Shore",
        }
    )

    motion = _normalize_model_motion(
        {"on_scroll": {"signature_gesture_trigger": "section-boundary"}},
        intake,
        "A single tide-line rule marks the descent.",
        allow_subject_default=False,
    )

    assert motion["enabled"] is True
    assert "signature" not in motion


def test_deterministic_planner_requests_only_catalogued_runtime_libraries():
    intake = _intake()
    brief = compile_brief(intake)
    direction = select_direction(intake, brief).selected

    without_catalog = DeterministicDesignPlanner().plan(intake, brief, direction)
    with_catalog = DeterministicDesignPlanner([{"name": "GSAP"}]).plan(intake, brief, direction)

    assert without_catalog.motion["libraries"] == []
    assert with_catalog.motion["libraries"] == ["gsap"]


def test_page_strategy_supplies_only_explicit_website_images_to_the_first_design():
    intake = _intake()
    intake = SiteIntake.from_dict({
        **intake.to_dict(),
        "assets": [
            {"id": "11", "usage": "website", "position": 0},
            {"id": "22", "usage": "undecided", "position": 1},
            {"id": "33", "usage": "inspiration_only", "position": 2},
        ],
    })
    brief = compile_brief(intake)
    direction = select_direction(intake, brief).selected
    request = initial_homepage_request(
        intake, brief, direction, run_id="design-media", base_sha="a" * 40,
    )
    assert sorted(request.supplied_media_asset_ids) == [11]
