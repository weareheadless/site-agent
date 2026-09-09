from site_agent.core.design_contracts import AssetCompositionPlan, TemporalExperienceEvidence, canonical_hash
from site_agent.hands.design_quality import evaluate_composition_plan, evaluate_temporal_evidence


def _composition(**overrides):
    value = {
        "schema_version": 1,
        "asset_id": "asset-logo",
        "asset_sha256": "a" * 64,
        "narrative_role": "identity anchor",
        "page_regions": ["header"],
        "relationship_to_copy": "Sets the page cadence.",
        "relationship_to_other_assets": "Remains clear of navigation.",
        "structural_contribution": ["geometry"],
        "crop_policy": "never crop",
        "focal_region_to_preserve": None,
        "negative_space_usage": "preserve clear space",
        "layering_and_overlap_policy": "no overlap",
        "background_and_contrast_policy": "declared backgrounds only",
        "desktop_treatment": {"scale": 1},
        "tablet_treatment": {"scale": 0.9},
        "mobile_treatment": {"scale": 0.8},
        "loading_priority": "eager",
        "accessibility_intent": "meaningful alt text",
        "prohibited_uses": [],
        "acceptance_conditions": ["logo remains clear"],
        "evidence_refs": ["asset-logo"],
        "logo_rule": {
            "schema_version": 1,
            "asset_id": "asset-logo",
            "optical_sizing": "visible mark",
            "clear_space": 0.1,
            "allowed_backgrounds": ["light"],
            "navigation_relationship": "reserve optical bounds",
            "breakpoint_treatments": {"desktop": "inline", "tablet": "inline", "mobile": "stacked"},
            "minimum_optical_size": 0.05,
            "maximum_optical_size": 0.2,
            "collision_exclusions": ["navigation", "primary_action"],
            "role": "composition_anchor",
            "evidence_refs": ["asset-logo"],
        },
    }
    value.update(overrides)
    return AssetCompositionPlan.from_dict(value)


def test_composition_gate_checks_frozen_asset_hash_and_logo_clearance():
    evidence = [{
        "route": "index.html",
        "viewport": {"name": "desktop", "width": 1200, "height": 800},
        "elements": [
            {"role": "logo", "asset_id": "asset-logo", "asset_sha256": "a" * 64, "box": {"x": 20, "y": 20, "width": 180, "height": 40}},
            {"role": "navigation", "box": {"x": 320, "y": 20, "width": 400, "height": 40}},
        ],
    }]

    report, findings = evaluate_composition_plan([_composition()], evidence)

    assert report["status"] == "passed"
    assert findings == []

    collision_evidence = [{
        **evidence[0],
        "elements": [
            evidence[0]["elements"][0],
            {"role": "navigation", "box": {"x": 150, "y": 20, "width": 400, "height": 40}},
        ],
    }]
    _, collision_findings = evaluate_composition_plan([_composition()], collision_evidence)
    assert {item["code"] for item in collision_findings} == {"logo_collision"}

    _, hash_findings = evaluate_composition_plan(
        [_composition()],
        [{**evidence[0], "elements": [{**evidence[0]["elements"][0], "asset_sha256": "b" * 64}]}],
    )
    assert any(item["code"] == "asset_hash_mismatch" for item in hash_findings)


def test_temporal_gate_requires_signature_observation_and_clean_runtime():
    raw = {
        "schema_version": 1,
        "candidate_sha": "a" * 40,
        "experience_plan_hash": "b" * 64,
        "route": "index.html",
        "viewport": {"name": "mobile", "width": 390, "height": 844},
        "reduced_motion": False,
        "interaction_script_id": "arrival-v1",
        "frames": [
            {"phase": "before", "path": "artifacts/before.png"},
            {"phase": "intermediate", "path": "artifacts/mid.png"},
            {"phase": "after", "path": "artifacts/after.png"},
        ],
        "layout_shifts": [{"value": 0.02}],
        "console_errors": [],
        "network_errors": [],
        "animation_observations": [{"id": "arrival", "state": "observed"}],
        "keyboard_path_observations": ["logo", "navigation"],
        "resting_state_observations": {"critical_content_visible": True},
    }
    raw["evidence_hash"] = canonical_hash({key: value for key, value in raw.items() if key != "evidence_hash"})
    evidence = TemporalExperienceEvidence.from_dict(raw)

    report, findings = evaluate_temporal_evidence(evidence, signature_behavior_id="arrival")
    assert report["status"] == "passed"
    assert findings == []

    failed = {**raw, "animation_observations": [], "evidence_hash": ""}
    failed["evidence_hash"] = canonical_hash({key: value for key, value in failed.items() if key != "evidence_hash"})
    failed_evidence = TemporalExperienceEvidence.from_dict(failed)
    _, failed_findings = evaluate_temporal_evidence(failed_evidence, signature_behavior_id="arrival")
    assert any(item["code"] == "signature_behavior_unobserved" for item in failed_findings)
