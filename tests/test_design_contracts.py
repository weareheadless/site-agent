import json

import pytest

from site_agent.core.contracts import ContractError
from site_agent.core.design_contracts import (
    AssetCompositionPlan,
    AssetVisualEvidence,
    BrandBehaviorSystem,
    BrandSourceMap,
    BuildTarget,
    CopyDeck,
    CreativeConcept,
    DesignCandidateReceipt,
    DesignManifest,
    DesignPhase,
    DesignPhaseArtifact,
    DesignSourceBinding,
    DesignRunStatus,
    ExperiencePlanBundle,
    LogoCompositionRule,
    NormalizedPoint,
    NormalizedRegion,
    PageBuildRequest,
    SiteIntake,
    TemporalExperienceEvidence,
    canonical_hash,
    validate_design_run_transition,
)


def _intake(**overrides):
    value = {
        "schema_version": 1,
        "business": {
            "name": "North Star Studio",
            "offer_summary": "Brand strategy for independent businesses.",
            "primary_services": ["Brand strategy"],
        },
        "audience": {"primary": "Independent business owners"},
        "conversion": {
            "primary_action": "Book a consultation",
            "contact_destination": "mailto:hello@example.com",
        },
        "brand": {"voice": "Clear, thoughtful, and warm."},
        "site": {"required_pages": ["home", "about", "contact"]},
    }
    value.update(overrides)
    return value


def test_site_intake_round_trips_and_hashes_canonically():
    intake = SiteIntake.from_dict(_intake())
    reordered = json.loads(json.dumps(_intake(), sort_keys=True))

    assert intake.to_dict()["business"]["name"] == "North Star Studio"
    assert intake.content_hash == canonical_hash(reordered)


def test_site_intake_rejects_unknown_schema_version():
    with pytest.raises(ContractError, match="schema_version"):
        SiteIntake.from_dict(_intake(schema_version=99))


def _phase_artifact(**overrides):
    value = {
        "schema_version": 1,
        "run_id": "design-phase-test",
        "phase": "copy",
        "variant_key": "primary",
        "attempt": 1,
        "status": "completed",
        "base_sha": "a" * 40,
        "context_snapshot_hash": "b" * 64,
        "input_hashes": ["c" * 64],
        "producer": "copywriter",
        "payload": {"headline": "Into the dark"},
    }
    value.update(overrides)
    return value


def test_specialist_phase_artifacts_are_typed_and_hash_bound():
    artifact = CopyDeck.from_dict(_phase_artifact())

    assert isinstance(artifact, DesignPhaseArtifact)
    assert artifact.phase == DesignPhase.COPY.value
    assert artifact.content_hash == artifact.content_hash
    assert artifact.to_dict()["payload"]["headline"] == "Into the dark"

    with pytest.raises(ContractError, match="phase must be one"):
        CreativeConcept.from_dict(_phase_artifact())

    with pytest.raises(ContractError, match="unknown fields"):
        CopyDeck.from_dict(_phase_artifact(unexpected="nope"))


def test_site_intake_rejects_unbounded_text_and_unsupported_contact_url():
    with pytest.raises(ContractError, match="offer_summary"):
        SiteIntake.from_dict(_intake(business={
            "name": "North Star Studio",
            "offer_summary": "x" * 20001,
            "primary_services": ["Brand strategy"],
        }))

    with pytest.raises(ContractError, match="contact_destination"):
        SiteIntake.from_dict(_intake(conversion={
            "primary_action": "Book a consultation",
            "contact_destination": "javascript:alert(1)",
        }))


def test_local_experiment_target_is_non_publishable_and_never_pushes():
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/run-1",
        "push_mode": "none",
        "publishable": False,
    })

    assert target.publishable is False
    assert target.push_mode == "none"

    with pytest.raises(ContractError, match="local_experiment"):
        BuildTarget.from_dict({
            "mode": "local_experiment",
            "base_sha": "a" * 40,
            "candidate_ref": "refs/ada-design-lab/run-1",
            "push_mode": "shared_preview",
            "publishable": False,
        })


def test_manifest_binding_is_external_to_avoid_sha_cycle():
    manifest = DesignManifest.from_dict({
        "schema_version": 1,
        "source_homepage_path": "index.html",
        "design_direction_id": "quiet-tide",
        "intake_hash": "b" * 64,
        "tokens": {"accent": "#087f99"},
        "shared_regions": ["header", "footer"],
    })
    binding = DesignSourceBinding.from_dict({
        "candidate_sha": "c" * 40,
        "manifest_path": "design/ada-design-manifest.json",
        "manifest_hash": manifest.content_hash,
    })

    assert "candidate_sha" not in manifest.to_dict()
    assert binding.manifest_hash == manifest.content_hash


def test_derived_page_request_requires_design_source():
    with pytest.raises(ContractError, match="design_source"):
        PageBuildRequest.from_dict({
            "schema_version": 1,
            "run_id": "run-2",
            "mode": "derived_page",
            "base_sha": "a" * 40,
            "page_path": "about.html",
            "purpose": "Explain the studio.",
            "acceptance_criteria": ["Uses the shared navigation"],
        })


def test_visual_refinement_request_is_a_distinct_build_mode():
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "run-refinement",
        "mode": "visual_refinement",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Repair the candidate.",
        "acceptance_criteria": ["Preserve unaffected content."],
    })

    assert request.mode == "visual_refinement"


def test_candidate_lifecycle_has_explicit_preservation_states():
    assert DesignRunStatus.CANDIDATE_READY.value == "candidate_ready"
    assert DesignRunStatus.NEEDS_REPAIR.value == "needs_repair"
    assert DesignRunStatus.INCOMPLETE.value == "incomplete"
    assert "repairing" not in {status.value for status in DesignRunStatus}

    validate_design_run_transition("building", "candidate_ready")
    validate_design_run_transition("validating", "needs_repair")
    validate_design_run_transition("validating", "incomplete")


def test_candidate_receipt_is_build_only_and_has_host_identity():
    receipt = DesignCandidateReceipt.from_dict({
        "run_id": "design-run-1",
        "operation_kind": "initial_build",
        "base_sha": "a" * 40,
        "candidate_sha": "b" * 40,
        "candidate_ref": "refs/ada-design/design-run-1",
        "diff_summary": "1 file changed",
        "changed_paths": ["index.html"],
        "opencode_session_id": "session-1",
        "transcript_path": "artifacts/transcript.jsonl",
        "manifest_path": "design/ada-design-manifest.json",
        "manifest_hash": "c" * 64,
        "provider": "entrim",
        "model": "deepseek-ai/DeepSeek-V4-Flash",
        "publishable": False,
    })

    assert receipt.operation_kind == "initial_build"
    assert receipt.provider == "entrim"
    assert receipt.model == "deepseek-ai/DeepSeek-V4-Flash"
    assert not hasattr(receipt, "quality_report_hash")
    assert not hasattr(receipt, "visual_critique")


def _asset_evidence(**overrides):
    value = {
        "schema_version": 1,
        "asset_id": "asset-logo",
        "asset_sha256": "a" * 64,
        "relative_path": "public/images/logo.png",
        "media_role": "logo",
        "pixel_width": 1200,
        "pixel_height": 360,
        "aspect_ratio": 3.333333,
        "has_alpha": True,
        "optical_bounds": {"x": 0.08, "y": 0.12, "width": 0.82, "height": 0.66, "confidence": 0.98},
        "optical_center": {"x": 0.49, "y": 0.45, "confidence": 0.98},
        "visual_mass": [0.1, 0.2, 0.4, 0.2, 0.1],
        "safe_backgrounds": ["light", "dark"],
        "minimum_legible_size": 0.08,
        "dominant_colors": ["#111111", "#f6f2ea"],
        "contrast_edges": [{"background": "dark", "contrast": "safe"}],
        "focal_regions": [{"label": "wordmark", "x": 0.08, "y": 0.12, "width": 0.82, "height": 0.66, "confidence": 0.98}],
        "negative_space_regions": [{"label": "clear-space", "x": 0.0, "y": 0.0, "width": 0.08, "height": 1.0, "confidence": 0.9}],
        "semantic_description": "A horizontal wordmark with generous transparent padding.",
        "subjects": ["wordmark"],
        "materials_and_textures": ["flat ink"],
        "emotional_tone": "quiet confidence",
        "brand_signals": ["measured spacing", "high contrast"],
        "quality_constraints": ["preserve optical clear space"],
        "evidence_sources": ["deterministic", "owner note"],
        "confidence": 0.96,
        "analyzer_version": "image-evidence-v1",
        "provider_id": "host",
        "model": "",
    }
    value.update(overrides)
    return value


def test_visual_evidence_validates_normalized_geometry_and_round_trips():
    evidence = AssetVisualEvidence.from_dict(_asset_evidence())

    assert evidence.optical_bounds.width == pytest.approx(0.82)
    assert evidence.optical_center.x == pytest.approx(0.49)
    assert evidence.content_hash == canonical_hash(evidence.to_dict())

    with pytest.raises(ContractError, match="normalized"):
        NormalizedRegion.from_dict({"x": 0.9, "y": 0.1, "width": 0.2, "height": 0.2})
    with pytest.raises(ContractError, match="unknown fields"):
        AssetVisualEvidence.from_dict(_asset_evidence(unexpected="nope"))
    with pytest.raises(ContractError, match="relative_path"):
        AssetVisualEvidence.from_dict(_asset_evidence(relative_path="https://example.com/logo.png"))


def _experience_plan(**overrides):
    asset = _asset_evidence()
    source_map = {
        "schema_version": 1,
        "identity_assets": ["asset-logo"],
        "primary_brand_signals": ["measured spacing", "high contrast"],
        "geometry_vocabulary": ["wide optical margins"],
        "spacing_rhythm": ["large-to-small cadence"],
        "line_and_edge_language": ["quiet edges"],
        "color_relationships": ["ink against warm paper"],
        "type_relationship_hypotheses": ["restrained display with plain utility text"],
        "material_relationships": ["flat mark with tactile image"],
        "image_treatment_hypotheses": ["preserve focal subject and negative space"],
        "signals_to_preserve": ["optical clear space"],
        "signals_not_safe_to_infer": ["unverified secondary colors"],
        "owner_evidence_refs": ["intake.brand.voice"],
        "asset_evidence_refs": ["asset-logo"],
        "confidence_by_signal": {"geometry": 0.9, "color": 0.8},
    }
    brand_behavior = {
        "schema_version": 1,
        "thesis": "Attention follows the same measured cadence as the identity.",
        "business_relevance": "Makes the primary promise easier to understand.",
        "audience_effect": "Creates calm orientation without hiding content.",
        "evidence_refs": ["asset-logo", "intake.audience.primary"],
        "conceptual_entities": [{"id": "content", "meaning": "the visible message"}],
        "state_variables": [{"id": "attention_progress", "meaning": "how far the reader has entered the story", "range": "0..1"}],
        "input_signals": [{"id": "scroll_progress", "meaning": "bounded page progress", "maps_to": "attention_progress"}],
        "forces_and_relationships": [{"id": "cadence", "meaning": "content groups settle into the identity rhythm"}],
        "output_channels": [{"id": "emphasis", "property": "content emphasis"}],
        "scene_graph": [{"id": "arrival", "entities": ["content"], "exit_condition": "first viewport is complete"}],
        "signature_behavior": {"id": "measured-arrival", "meaning": "the identity cadence organizes attention", "acceptance_conditions": ["resting state remains complete"]},
        "utility_behaviors": [{"id": "focus", "meaning": "focus remains visible"}],
        "narrative_behaviors": [{"id": "arrival", "meaning": "one authored transition"}],
        "resting_state": {"complete": True, "critical_content_visible": True},
        "no_javascript_translation": "The complete hierarchy remains visible without JavaScript.",
        "reduced_motion_translation": "Replace spatial motion with emphasis and opacity changes only.",
        "mobile_translation": "Preserve the cadence while reducing simultaneous elements.",
        "keyboard_and_focus_behavior": "Focus order follows document order and remains visible.",
        "performance_budget": {"max_active_animations": 2, "max_layout_shift": 0.1},
        "interruption_and_resize_behavior": "Cancel and recompute transient states on resize.",
        "allowed_implementation_capabilities": ["css", "dom"],
        "prohibited_generic_effects": ["unmotivated cursor trail"],
        "observable_acceptance_conditions": ["signature marker is observable", "content is complete at rest"],
        "transfer_test": {"state": "passed", "evidence_specific_elements": ["measured cadence"], "transferable_elements": []},
    }
    composition = {
        "schema_version": 1,
        "asset_id": "asset-logo",
        "asset_sha256": "a" * 64,
        "narrative_role": "identity anchor",
        "page_regions": ["header", "hero"],
        "relationship_to_copy": "The wordmark establishes the same breathing room as the headline.",
        "relationship_to_other_assets": "No overlap with navigation or primary action.",
        "structural_contribution": ["geometry", "visual language"],
        "crop_policy": "never crop the logo",
        "focal_region_to_preserve": {"x": 0.08, "y": 0.12, "width": 0.82, "height": 0.66, "confidence": 0.98},
        "negative_space_usage": "Reserve transparent padding as clear space.",
        "layering_and_overlap_policy": "No overlap with navigation or action.",
        "background_and_contrast_policy": "Use only declared light or dark backgrounds.",
        "desktop_treatment": {"optical_scale": 0.12},
        "tablet_treatment": {"optical_scale": 0.1},
        "mobile_treatment": {"optical_scale": 0.08},
        "loading_priority": "eager",
        "accessibility_intent": "Provide meaningful alt text and preserve legibility.",
        "prohibited_uses": ["decorative crop"],
        "acceptance_conditions": ["optical bounds stay clear"],
        "evidence_refs": ["asset-logo"],
        "logo_rule": {
            "schema_version": 1,
            "asset_id": "asset-logo",
            "optical_sizing": "size by visible mark, not file box",
            "clear_space": 0.04,
            "allowed_backgrounds": ["light", "dark"],
            "navigation_relationship": "header reserves optical bounds before navigation",
            "breakpoint_treatments": {"desktop": "inline", "tablet": "inline", "mobile": "stacked"},
            "minimum_optical_size": 0.06,
            "maximum_optical_size": 0.18,
            "collision_exclusions": ["navigation", "primary_action"],
            "role": "composition_anchor",
            "evidence_refs": ["asset-logo"],
        },
    }
    value = {
        "schema_version": 1,
        "run_id": "design-experience-test",
        "base_sha": "b" * 40,
        "context_snapshot_hash": "c" * 64,
        "selected_concept_id": "concept-a",
        "copy_deck_hash": "d" * 64,
        "asset_evidence": [_asset_evidence()],
        "brand_source_map": source_map,
        "brand_source_map_hash": canonical_hash(source_map),
        "asset_composition_plan": [composition],
        "behavior_system": brand_behavior,
        "layout_and_typography_plan": {"type_scale": "restrained"},
        "responsive_composition_plan": {"mobile": "stacked"},
        "protected_strengths": ["optical clear space"],
        "variation_points": ["page-specific supporting copy"],
        "implementation_risks": ["logo clearance at narrow widths"],
        "transfer_test": {"state": "passed", "evidence_specific_elements": ["asset-logo"]},
        "review_rubric": [{"id": "logo-clearance", "condition": "logo does not collide"}],
        "input_artifact_hashes": ["e" * 64],
    }
    value.update(overrides)
    return value


def test_experience_plan_requires_evidence_backed_behavior_and_round_trips():
    plan = ExperiencePlanBundle.from_dict(_experience_plan())

    assert plan.behavior_system.signature_behavior["id"] == "measured-arrival"
    assert plan.asset_composition_plan[0].logo_rule is not None
    assert plan.content_hash == canonical_hash(plan.to_dict())

    with pytest.raises(ContractError, match="signature_behavior"):
        ExperiencePlanBundle.from_dict(_experience_plan(behavior_system={**_experience_plan()["behavior_system"], "signature_behavior": {}}))
    with pytest.raises(ContractError, match="brand_source_map_hash"):
        ExperiencePlanBundle.from_dict(_experience_plan(brand_source_map_hash="f" * 64))


def test_behavior_contract_rejects_missing_resting_or_reduced_motion_translation():
    raw = _experience_plan()["behavior_system"]
    with pytest.raises(ContractError, match="no_javascript_translation"):
        BrandBehaviorSystem.from_dict({**raw, "no_javascript_translation": ""})
    with pytest.raises(ContractError, match="reduced_motion_translation"):
        BrandBehaviorSystem.from_dict({**raw, "reduced_motion_translation": ""})


def test_temporal_evidence_hashes_local_frame_manifest_only():
    raw = {
        "schema_version": 1,
        "candidate_sha": "a" * 40,
        "experience_plan_hash": "b" * 64,
        "route": "index.html",
        "viewport": {"name": "mobile", "width": 390, "height": 844},
        "reduced_motion": True,
        "interaction_script_id": "script-arrival-v1",
        "frames": [
            {"phase": "before", "path": "artifacts/frames/before.png"},
            {"phase": "intermediate", "path": "artifacts/frames/mid.png"},
            {"phase": "after", "path": "artifacts/frames/after.png"},
        ],
        "layout_shifts": [],
        "console_errors": [],
        "network_errors": [],
        "animation_observations": [{"id": "measured-arrival", "state": "observed"}],
        "keyboard_path_observations": ["logo", "navigation", "primary-action"],
        "resting_state_observations": {"critical_content_visible": True},
    }
    raw["evidence_hash"] = canonical_hash({key: value for key, value in raw.items() if key != "evidence_hash"})
    evidence = TemporalExperienceEvidence.from_dict(raw)

    assert evidence.reduced_motion is True
    with pytest.raises(ContractError, match="safe relative path"):
        TemporalExperienceEvidence.from_dict({**raw, "frames": [{"phase": "before", "path": "https://example.com/frame.png"}]})


def test_ui_action_parsing_is_lenient():
    from site_agent.core.design_intake_contracts import IntakeTurnResult

    turn = IntakeTurnResult.from_dict({
        "schema_version": 1,
        "assistant_message": "Show the refined version.",
        "ui_action": {"action": "open_preview", "run_id": "intake-lab-deadbeef"},
    })
    assert turn.ui_action == {"action": "open_preview", "run_id": "intake-lab-deadbeef"}
    assert turn.to_dict()["ui_action"] == turn.ui_action

    fresh = IntakeTurnResult.from_dict({
        "schema_version": 1,
        "assistant_message": "Rebuilding now.",
        "ui_action": {"action": "start_build", "fresh": True},
    })
    assert fresh.ui_action == {"action": "start_build", "fresh": True}

    dropped = IntakeTurnResult.from_dict({
        "schema_version": 1,
        "assistant_message": "Notes here.",
        "ui_action": {"action": "explode", "run_id": "x"},
    })
    assert dropped.ui_action == {}

    missing = IntakeTurnResult.from_dict({
        "schema_version": 1,
        "assistant_message": "No action planned.",
    })
    assert missing.ui_action == {}
