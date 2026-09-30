import pytest

from site_agent.brain.design_guidance import DesignGuidanceError, load_design_skills
from site_agent.core.design_intake_contracts import CreativeInsight, DesignIntakeDraft, IntakeTurnResult, merge_intake_turn
from site_agent.core.design_contracts import BuildTarget, DesignContextSnapshot, IncubatedCreativeContext, PageBuildRequest
from site_agent.hands import opencode_runner as runner


def test_design_skill_loader_has_one_deterministic_hash():
    first = load_design_skills()
    second = load_design_skills()

    assert first.names == (
        "design-core.md",
        "frontend-design.md",
        "high-end-visual-design.md",
        "motion-design.md",
        "web-design-guidelines.md",
        "gsap-core.md",
        "gsap-react.md",
        "gsap-scrolltrigger.md",
        "gsap-plugins.md",
        "gsap-performance.md",
    )
    assert first.content_hash == second.content_hash
    assert "Every design decision should carry the subject" in first.content


def test_design_skill_loader_fails_when_a_required_skill_is_missing(tmp_path):
    (tmp_path / "design-core.md").write_text("# core", encoding="utf-8")

    with pytest.raises(DesignGuidanceError, match="frontend-design.md"):
        load_design_skills(tmp_path)


def test_creative_insights_are_typed_bounded_and_do_not_update_owner_facts():
    insight = CreativeInsight.from_dict({
        "kind": "creative_implication",
        "summary": "A quieter opening may make the technical offer easier to trust.",
        "basis": "recommendation",
        "related_intake_paths": ["brand.voice", "audience.concerns"],
        "related_asset_ids": [7],
        "confidence": 0.6,
    })
    turn = IntakeTurnResult.from_dict({
        "schema_version": 1,
        "assistant_message": "I would make the opening quieter.",
        "creative_insights": [insight.to_dict()],
    })

    assert turn.creative_insights == (insight,)
    assert merge_intake_turn(
        DesignIntakeDraft.empty(),
        turn,
        source_message_id=1,
    ).fields == {}


def test_context_snapshot_round_trips_the_skill_receipt():
    skills = load_design_skills()
    snapshot = DesignContextSnapshot.from_dict({
        "schema_version": 1,
        "captured_at": "2026-09-03T12:00:00+00:00",
        "owner_request": "Create the first design.",
        "base_sha": "a" * 40,
        "design_skill_set": skills.to_dict(include_content=False),
    })

    assert snapshot.design_skill_set is not None
    assert snapshot.design_skill_set.content_hash == skills.content_hash
    assert snapshot.to_dict()["design_skill_set"]["names"] == list(skills.names)


def test_initial_build_prompt_keeps_incubated_context_without_old_site_context():
    skills = load_design_skills()
    context = IncubatedCreativeContext.from_dict({
        "genesis_revision": 3,
        "genesis_hash": "b" * 64,
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
        "novelty_constraints": {"patterns": ["repetitive cards"]},
        "patterns_to_avoid": ["generic gradients"],
        "design_skill_set": skills.to_dict(include_content=False),
    })
    snapshot = DesignContextSnapshot.from_dict({
        "schema_version": 1,
        "captured_at": "2026-09-03T12:00:00+00:00",
        "owner_request": "Create the first design.",
        "base_sha": "a" * 40,
        "site_digest": "OLD_SITE_CONTEXT_MUST_NOT_WIN",
        "design_skill_set": skills.to_dict(include_content=False),
    })
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "initial-context",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Preserve safety."],
        "content": {"site_intake": {"business": {"name": "Fictional studio"}}, "creative_prompt": "A calm homepage."},
        "context_snapshot": snapshot.to_dict(),
        "context_snapshot_hash": snapshot.content_hash,
        "incubated_creative_context": context.to_dict(),
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/initial-context",
        "push_mode": "none",
        "publishable": False,
        "clone_path": "/tmp/design-clone",
    })

    prompt = runner._design_prompt(request, target)

    assert "INCUBATED CREATIVE CONTEXT" in prompt
    assert "quiet editorial pacing" in prompt
    assert "careful workmanship" in prompt
    assert "Technical buyers need proof before the first conversation." in prompt
    assert "AUDIENCE AND RESEARCH CONTEXT APPLICATION" in prompt
    assert "OLD_SITE_CONTEXT_MUST_NOT_WIN" not in prompt


def test_incubated_context_roundtrips_visual_reference_notes():
    from site_agent.core.design_contracts import IncubatedCreativeContext

    skills = load_design_skills()
    context = IncubatedCreativeContext.from_dict({
        "genesis_revision": 4,
        "genesis_hash": "c" * 64,
        "research_backed_creative_implications": [],
        "cross_language_audience_insights": [],
        "novelty_constraints": {},
        "patterns_to_avoid": [],
        "design_skill_set": skills.to_dict(include_content=False),
        "visual_reference_notes": ["reference logo hero.webp; palette: #D97A35", "reference workspace.webp; tags: wood, warmth"],
    })
    assert context.visual_reference_notes[0].startswith("reference logo")
    again = IncubatedCreativeContext.from_dict(context.to_dict())
    assert again.visual_reference_notes == context.visual_reference_notes

    legacy = IncubatedCreativeContext.from_dict({
        "genesis_revision": 4,
        "genesis_hash": "c" * 64,
        "research_backed_creative_implications": [],
        "cross_language_audience_insights": [],
        "novelty_constraints": {},
        "patterns_to_avoid": [],
        "design_skill_set": skills.to_dict(include_content=False),
    })
    assert legacy.visual_reference_notes == ()


def test_design_prompt_stages_visual_evidence_without_blind_language():
    from site_agent.core.design_contracts import BuildTarget, PageBuildRequest
    from site_agent.hands import opencode_runner as runner

    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "sighted-prompt",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Preserve safety."],
        "content": {"site_intake": {"business": {"name": "Fictional studio"}}, "creative_prompt": "A calm homepage."},
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/sighted-prompt",
        "push_mode": "none",
        "publishable": False,
    })

    prompt = runner._design_prompt(
        request,
        target,
        materialized_media_paths=("images/ada-media/logo.webp",),
    )

    assert "reproduce the real logo" in prompt
    assert "you can see these images directly" in prompt
    assert "do not attempt to inspect screenshot pixels" not in prompt
    assert "pixel-level image inspection is optional" not in prompt

    refinement = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "sighted-refine",
        "mode": "visual_refinement",
        "base_sha": "b" * 40,
        "page_path": "index.html",
        "purpose": "Refine the candidate.",
        "acceptance_criteria": ["Preserve direction."],
        "content": {"visual_critique": {"candidate_sha": "b" * 40, "state": "repair"}},
    })
    refined_target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "b" * 40,
        "candidate_ref": "refs/ada-design-lab/sighted-refine",
        "operation_kind": "visual_refinement",
        "push_mode": "none",
        "publishable": False,
    })
    refined_prompt = runner._design_prompt(refinement, refined_target)
    assert "Open and visually read every" in refined_prompt
    assert "self-critique" in refined_prompt.lower()
    assert "do not attempt to inspect screenshot pixels" not in refined_prompt
