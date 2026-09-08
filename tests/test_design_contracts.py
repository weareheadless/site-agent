import json

import pytest

from site_agent.core.contracts import ContractError
from site_agent.core.design_contracts import (
    BuildTarget,
    CopyDeck,
    CreativeConcept,
    DesignCandidateReceipt,
    DesignManifest,
    DesignPhase,
    DesignPhaseArtifact,
    DesignSourceBinding,
    DesignRunStatus,
    PageBuildRequest,
    SiteIntake,
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
