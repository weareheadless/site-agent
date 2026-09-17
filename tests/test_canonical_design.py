import json
import subprocess

import pytest

from site_agent.application.designs import DesignService
from site_agent.application.design_jobs import DesignJobExecutor
from site_agent.core.contracts import ContractError
from site_agent.core.design_contracts import (
    BuildTarget,
    DesignContextSnapshot,
    DesignRequest,
    DesignRunStatus,
    PageBuildRequest,
    QualityReport,
    SiteIntake,
    VisualCritiqueReport,
    canonical_hash,
)
from site_agent.core.memory import Memory
from site_agent.core.chat_jobs import run_job
from site_agent.hands import opencode_runner as runner
from site_agent.hands.site_build import ASTRO_REACT_PROFILE


def _intake() -> SiteIntake:
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "OceanicVibes",
            "offer_summary": "Freediving instruction and depth training.",
            "primary_services": ["AIDA 3 training"],
            "location": ["Playa del Carmen", "Bacalar"],
        },
        "audience": {"primary": "Freedivers considering structured training"},
        "conversion": {"primary_action": "Start a training conversation", "not_available": True},
        "brand": {"voice": "Calm, precise, and quietly obsessed with the sea."},
        "site": {"required_pages": ["index.html", "articles.html"]},
        "unknowns": ["No booking destination is verified."],
    })


def _snapshot(**overrides) -> dict:
    value = {
        "schema_version": 1,
        "captured_at": "2026-08-31T12:00:00+00:00",
        "conversation_id": 7,
        "source_message_id": 11,
        "chat_job_id": 13,
        "owner_request": "Redesign the homepage around depth and patient progression.",
        "conversation": [{"role": "user", "text": "Please make it feel more like the sea."}],
        "effective_persona": "You are Ada, the site's webmaster.",
        "self_model": {"version": 1, "self_description": "I distrust easy closure."},
        "approved_persona_notes": {"voice_notes": ["Prefer precise language"], "avoid": []},
        "memories": [{"id": 4, "source": "learning", "text": "Safety questions matter."}],
        "research": [{"id": 5, "source": "rss/news", "excerpt": "A grounded excerpt", "provenance": "feed"}],
        "business_knowledge": [],
        "attachments": [],
        "site_facts": {"name": "OceanicVibes", "required_pages": ["index.html"]},
        "source_repository": "owner/repository",
        "base_sha": "a" * 40,
        "site_digest": "Files (4): 2 pages, 1 stylesheet",
        "route_inventory": ["index.html", "articles.html"],
        "current_content": {"heroTitle": "Breathe deeper"},
        "asset_inventory": [{"path": "images/hero.jpg", "role": "hero"}],
        "measured_design": {"font_families": ["Manrope", "Cormorant Garamond"]},
        "verified_facts": ["Training is offered in Bacalar."],
        "unknowns": ["Pricing is not verified."],
        "prohibited_claims": ["Do not invent certifications."],
        "capabilities": [{"name": "gsap", "version": "3.12.5"}],
        "execution_profile": {
            "model": "deepseek/deepseek-v4-flash-0731",
            "repair_attempts": 2,
            "viewports": [{"name": "mobile", "width": 390, "height": 844}],
        },
    }
    value.update(overrides)
    return value


def test_context_snapshot_round_trips_and_hashes_canonically():
    snapshot = DesignContextSnapshot.from_dict(_snapshot())
    reordered = json.loads(json.dumps(_snapshot(), sort_keys=True))

    assert snapshot.content_hash == canonical_hash(reordered)
    assert snapshot.base_sha == "a" * 40
    assert snapshot.execution_profile["model"] == "deepseek/deepseek-v4-flash-0731"


def test_design_request_is_the_explicit_chat_handoff_contract():
    request = DesignRequest.from_dict({
        "intent": "redesign",
        "intake": _intake().to_dict(),
        "owner_summary": "I will prepare one reviewable redesign and keep it unpublished.",
        "source_message_id": 11,
    })

    assert request.intent == "redesign"
    assert request.intake.content_hash == _intake().content_hash
    assert request.source_message_id == 11


def test_context_snapshot_hash_mismatch_is_rejected():
    snapshot = DesignContextSnapshot.from_dict(_snapshot())
    with pytest.raises(ContractError, match="context_snapshot_hash"):
        PageBuildRequest.from_dict({
            "schema_version": 1,
            "run_id": "run-1",
            "mode": "initial_homepage",
            "base_sha": "a" * 40,
            "page_path": "index.html",
            "purpose": "Create the homepage.",
            "acceptance_criteria": ["Preserve safety."],
            "context_snapshot": snapshot.to_dict(),
            "context_snapshot_hash": "b" * 64,
        })


def test_context_capture_redacts_secret_shaped_memory_text(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    memory.record_observation("learning", "OPENAI_API_KEY=do-not-persist-this-value")
    service = DesignService(memory, config={"site": {"repository": "owner/site"}})
    run = service.create_run(_intake(), run_id="secret-run", base_sha="a" * 40)

    snapshot = service.capture_context_snapshot(run["run_id"], owner_request="Make the homepage safer.")

    serialized = json.dumps(snapshot.to_dict())
    assert "do-not-persist-this-value" not in serialized
    assert "[REDACTED]" in serialized
    memory.close()


def test_context_capture_preserves_non_secret_builder_settings(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    service = DesignService(memory, config={
        "site": {"repository": "owner/site"},
        "builder": {"output_tokens": 8192},
        "design_engine": {"max_tokens": 4096},
    })
    run = service.create_run(_intake(), run_id="builder-settings-run", base_sha="a" * 40)

    snapshot = service.capture_context_snapshot(run["run_id"], owner_request="Make the homepage clearer.")

    assert snapshot.execution_profile["builder"]["output_tokens"] == 8192
    assert snapshot.execution_profile["max_tokens"] == 4096
    assert not any(key.startswith("planner") or key.startswith("vision_planner") for key in snapshot.execution_profile)
    memory.close()


def test_context_capture_freezes_brief_content_in_quality_policy(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    service = DesignService(memory, config={"site": {"repository": "owner/site"}})
    run = service.create_run(_intake(), run_id="content-policy-run", base_sha="a" * 40)

    snapshot = service.capture_context_snapshot(run["run_id"], owner_request="Make the facts legible.")

    assert snapshot.execution_profile["quality_policy"]["required_content"] == [
        "Freediving instruction and depth training.",
        "AIDA 3 training",
    ]
    memory.close()


def test_local_experiment_uses_configured_design_provider(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    service = DesignService(memory, config={
        "site": {"repository": "owner/site"},
        "llm": {"model": "openrouter/fallback", "base_url": "https://openrouter.ai/api/v1"},
        "design_engine": {
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "provider": "entrim",
            "base_url": "https://api.entrim.ai/v1",
            "api_key_env": "SITE_AGENT_VISION_API_KEY",
        },
    })
    run = service.create_run(_intake(), mode="local_experiment", run_id="entrim-run", base_sha="a" * 40)

    snapshot = service.capture_context_snapshot(run["run_id"], owner_request="Make the homepage feel deeper.")

    assert snapshot.execution_profile["model"] == "deepseek-ai/DeepSeek-V4-Flash"
    assert snapshot.execution_profile["provider"] == "entrim"
    assert snapshot.execution_profile["provider_base_url"] == "https://api.entrim.ai/v1"
    assert snapshot.execution_profile["provider_env_name"] == "SITE_AGENT_VISION_API_KEY"
    memory.close()


def test_oversized_context_fails_before_it_can_be_persisted(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    for index in range(80):
        memory.record_observation("learning", f"record-{index} " + ("x" * 4_000))
    service = DesignService(memory, config={"site": {"repository": "owner/site"}})
    run = service.create_run(_intake(), run_id="large-run", base_sha="a" * 40)

    with pytest.raises((ContractError, ValueError), match="exceeds"):
        service.capture_context_snapshot(run["run_id"], owner_request="Capture everything.")
    assert memory.get_design_run(run["run_id"])["context_snapshot_hash"] == ""
    memory.close()


def test_visual_critique_report_requires_structured_state():
    report = VisualCritiqueReport.from_dict({
        "run_id": "run-1",
        "candidate_sha": "c" * 40,
        "model_id": "deepseek/deepseek-v4-flash-0731",
        "state": "repair",
        "findings": [{
            "severity": "blocker",
            "category": "contrast",
            "message": "Body copy is unreadable over the surface.",
            "route": "index.html",
            "viewport": "mobile",
        }],
        "strengths": ["The subject-specific image treatment is clear."],
        "generic_template_signals": ["Centered hero pattern"],
    })

    assert report.state == "repair"
    assert report.findings[0]["category"] == "contrast"


def test_visual_critique_serializes_browser_evidence(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, *args, **kwargs):
            return json.dumps({"state": "passed", "findings": [], "strengths": ["Clear hierarchy"]})

    monkeypatch.setattr("site_agent.core.llm.Client", FakeClient)
    snapshot = DesignContextSnapshot.from_dict(_snapshot())
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "run-1",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Preserve safety."],
        "context_snapshot": snapshot.to_dict(),
        "context_snapshot_hash": snapshot.content_hash,
    })
    quality = QualityReport.from_dict({
        "run_id": "run-1",
        "candidate_sha": "a" * 40,
        "state": "passed",
        "evidence": {
            "browser": {
                "viewports": [{
                    "viewport": {"name": "mobile", "width": 390, "height": 844},
                    "result": {"routes": [{
                        "route": "index.html",
                        "screenshot_path": "/tmp/index.png",
                        "screenshot_hash": "b" * 64,
                    }]},
                }],
            },
        },
    })

    critique = runner._run_visual_critique({"config": {"llm": {}}, "env": {}}, request, quality)

    assert critique.state == "passed"
    assert critique.screenshot_evidence[0]["route"] == "index.html"


def test_design_service_captures_a_frozen_context_snapshot(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    conversation_id = memory.create_conversation("OceanicVibes design")
    source_message_id = memory.add_message(conversation_id, "user", "Redesign the homepage.")
    memory.record_observation("learning", "Safety language should be concrete.", meta={"link": "memory://4"})
    memory.kv_set("inner_self", {"self_description": "I prefer patient explanations."})
    service = DesignService(memory, config={
        "persona": {"name": "Ada", "voice": "calm", "audience": "freedivers"},
        "site": {"repository": "owner/repository", "required_pages": ["index.html"]},
        "llm": {"model": "deepseek/deepseek-v4-flash-0731"},
    })
    run = service.create_run(
        _intake(),
        run_id="context-run",
        base_sha="a" * 40,
        conversation_id=conversation_id,
        source_message_id=source_message_id,
        chat_job_id=19,
    )

    snapshot = service.capture_context_snapshot(
        run["run_id"],
        owner_request="Redesign the homepage.",
        conversation_id=conversation_id,
        source_message_id=source_message_id,
        chat_job_id=19,
    )

    stored = service.get_run(run["run_id"])
    assert snapshot.content_hash == stored["context_snapshot_hash"]
    assert stored["context_snapshot"]["chat_job_id"] == 19
    assert stored["context_snapshot"]["self_model"]["self_description"] == "I prefer patient explanations."
    assert stored["context_snapshot"]["memories"][0]["source"] == "learning"
    memory.close()


def test_page_build_request_carries_context_snapshot():
    snapshot = DesignContextSnapshot.from_dict(_snapshot())
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "run-1",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Preserve safety."],
        "context_snapshot": snapshot.to_dict(),
        "context_snapshot_hash": snapshot.content_hash,
    })

    assert request.context_snapshot_hash == snapshot.content_hash
    assert request.context_snapshot is not None


def test_typed_prompt_names_the_frozen_snapshot_and_native_creative_process():
    snapshot = DesignContextSnapshot.from_dict(_snapshot())
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "run-1",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Preserve safety."],
        "context_snapshot": snapshot.to_dict(),
        "context_snapshot_hash": snapshot.content_hash,
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/run-1",
        "push_mode": "none",
        "publishable": False,
        "clone_path": "/tmp/design-clone",
    })

    prompt = runner._design_prompt(request, target)

    assert snapshot.content_hash in prompt
    assert "choose one subject-specific direction silently" in prompt
    assert "read-only" in prompt
    assert "predetermined section markup" in prompt
    assert "same primary session" in prompt
    assert "Do not start a browser, HTTP server, custom CDP harness" in prompt
    assert "that work belongs to the host" in prompt
    assert "inspect the supplied media files" in prompt
    assert "Do not inspect admin surfaces" in prompt


def test_astro_target_prompt_keeps_legacy_source_out_of_native_authoring():
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "astro-native-prompt",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Preserve safety."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/astro-native-prompt",
        "push_mode": "none",
        "publishable": False,
        "clone_path": "/tmp/design-clone",
        "allowed_paths": list(ASTRO_REACT_PROFILE.writable_patterns),
    })

    prompt = runner._design_prompt(request, target)

    assert "NATIVE ASTRO/REACT TOOLCHAIN CONTRACT" in prompt
    assert "Do not execute build.sh" in prompt
    assert "root index.html" in prompt
    assert "public/images/ada-media/" in prompt
    assert "src/pages/index.astro" in prompt
    assert "@astrojs/react@4.4.2" in prompt
    assert "Do not use ranges or newer versions" in prompt


def test_technical_repair_manifest_keeps_the_complete_intake_route_inventory():
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "repair-run",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Repair the retained candidate.",
        "acceptance_criteria": ["Preserve every public route."],
        "content": {"site_intake": _intake().to_dict()},
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/repair-run",
        "push_mode": "none",
        "publishable": False,
        "clone_path": "/tmp/design-clone",
        "operation_kind": "technical_repair",
    })

    assert runner._manifest_required_pages(request, target) == ["index.html", "articles.html"]


def test_initial_typed_prompt_does_not_expose_existing_site_context():
    snapshot = DesignContextSnapshot.from_dict(_snapshot(
        effective_persona="PERSONA_MARKER",
        site_digest="SITE_DIGEST_MARKER",
        current_content={"hero": "CURRENT_CONTENT_MARKER"},
        measured_design={"template_tokens": "MEASURED_DESIGN_MARKER"},
    ))
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "initial-intake-only",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Preserve safety."],
        "content": {"site_intake": _intake().to_dict()},
        "context_snapshot": snapshot.to_dict(),
        "context_snapshot_hash": snapshot.content_hash,
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/initial-intake-only",
        "push_mode": "none",
        "publishable": False,
        "clone_path": "/tmp/design-clone",
    })

    prompt = runner._design_prompt(request, target)

    assert "PAGE BUILD REQUEST" in prompt
    assert "SITE_DIGEST_MARKER" not in prompt
    assert "CURRENT_CONTENT_MARKER" not in prompt
    assert "MEASURED_DESIGN_MARKER" not in prompt
    assert "PERSONA_MARKER" not in prompt


def test_initial_typed_prompt_does_not_invent_an_unavailable_contact_destination():
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "initial-contact-safety",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Preserve safety."],
        "content": {"site_intake": _intake().to_dict()},
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/initial-contact-safety",
        "push_mode": "none",
        "publishable": False,
        "clone_path": "/tmp/design-clone",
    })

    prompt = runner._design_prompt(request, target)

    assert "CONVERSION SAFETY OVERRIDE" in prompt
    assert "Do not add mailto: or tel: links" in prompt
    assert "social handle" in prompt


def test_typed_prompt_does_not_author_unapproved_font_assets():
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "font-safety",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Preserve safety."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/font-safety",
        "push_mode": "none",
        "publishable": False,
        "clone_path": "/tmp/design-clone",
    })

    prompt = runner._design_prompt(request, target)

    assert "FONT ASSET SAFETY" in prompt
    assert "Do not add, download, or generate new font files" in prompt


def test_initial_typed_prompt_calls_out_verbatim_host_content_requirements():
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "initial-content-safety",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Preserve safety."],
        "content": {
            "design_brief": {
                "content_requirements": [
                    "Offer phrase",
                    "Provide the required page: articles.html",
                ],
            },
        },
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/initial-content-safety",
        "push_mode": "none",
        "publishable": False,
        "clone_path": "/tmp/design-clone",
    })

    prompt = runner._design_prompt(request, target)

    assert "HOST CONTENT GATE (verbatim visible text required)" in prompt
    assert "- Offer phrase" in prompt
    assert "articles.html" not in prompt.split("HOST CONTENT GATE", 1)[1].split("CREATIVE DESIGN PROCESS", 1)[0]


def test_visual_refinement_prompt_preserves_parent_context_and_is_not_initial_build():
    snapshot = DesignContextSnapshot.from_dict(_snapshot(
        effective_persona="PARENT_PERSONA",
        site_digest="PARENT_SITE_DIGEST",
        current_content={"hero": "PARENT_CONTENT"},
        measured_design={"tokens": "PARENT_MEASUREMENTS"},
    ))
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "visual-repair",
        "mode": "visual_refinement",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Repair the parent candidate.",
        "acceptance_criteria": ["Preserve the parent design outside the repair."],
        "content": {"visual_refinement": {"parent_run_id": "parent", "finding": "Fix wrapping."}},
        "context_snapshot": snapshot.to_dict(),
        "context_snapshot_hash": snapshot.content_hash,
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/visual-repair",
        "push_mode": "none",
        "publishable": False,
        "clone_path": "/tmp/design-clone",
        "operation_kind": "visual_refinement",
    })

    prompt = runner._design_prompt(request, target)

    assert "visual refinement of the parent candidate" in prompt
    assert "smallest focused repair" in prompt
    assert "PARENT_CONTENT" not in prompt
    assert "Do not redesign the site from scratch" in prompt
    assert "your very first repository tool call MUST edit index.html" not in prompt
    assert "the validated intake is the sole creative brief" not in prompt


def test_technical_repair_prompt_preserves_native_implementation():
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "technical-native-repair",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Repair the retained candidate.",
        "acceptance_criteria": ["Preserve the parent implementation."],
        "content": {"technical_repair": {"parent_run_id": "parent"}},
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/technical-native-repair",
        "push_mode": "none",
        "publishable": False,
        "clone_path": "/tmp/design-clone",
        "operation_kind": "technical_repair",
    })

    prompt = runner._design_prompt(request, target)

    assert "technical repair of the parent candidate" in prompt
    assert "RETAINED IMPLEMENTATION PRESERVATION CONTRACT" in prompt
    assert "React source or Astro React integration" in prompt
    assert "approved GSAP runtime usage" in prompt
    assert "animation/timeline/trigger/listener teardown path" in prompt
    assert "Never replace a React/GSAP component with CSS-only markup" in prompt
    assert "confirm the preserved React/GSAP/cleanup/reduced-motion implementation" in prompt


def test_typed_agent_setup_uses_snapshot_without_rereading_memory(tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    snapshot = DesignContextSnapshot.from_dict(_snapshot())

    runner.install_agent_files(
        clone,
        None,
        "deepseek/deepseek-v4-flash-0731",
        persona="MUTATED PERSONA MUST NOT WIN",
        site_digest="MUTATED DIGEST MUST NOT WIN",
        template_tokens="MUTATED TOKENS MUST NOT WIN",
        memory=object(),
        context_snapshot=snapshot,
        context_snapshot_hash=snapshot.content_hash,
    )

    instructions = (clone / ".opencode" / "ada-instructions.md").read_text()
    assert snapshot.effective_persona in instructions
    assert "MUTATED PERSONA MUST NOT WIN" not in instructions
    assert snapshot.site_digest in instructions
    assert "MUTATED DIGEST MUST NOT WIN" not in instructions
    assert "TYPED DESIGN CONTEXT" in instructions


def test_typed_setup_rejects_context_hash_before_worktree_creation(tmp_path, monkeypatch):
    snapshot = DesignContextSnapshot.from_dict(_snapshot())
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "run-1",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Preserve safety."],
        "context_snapshot": snapshot.to_dict(),
        "context_snapshot_hash": snapshot.content_hash,
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/run-1",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(tmp_path / "clone"),
    })
    tampered = object.__new__(PageBuildRequest)
    for field_name in request.__dataclass_fields__:
        object.__setattr__(tampered, field_name, getattr(request, field_name))
    object.__setattr__(tampered, "context_snapshot_hash", "b" * 64)
    monkeypatch.setattr(runner, "prepare_design_worktree", lambda *args, **kwargs: pytest.fail("worktree was created"))

    with pytest.raises(runner.RunnerError, match="context snapshot hash is invalid"):
        runner.stage_design_build({"config": {}, "memory": None}, tampered, target)


def test_interrupted_design_runs_are_visible_and_queued_runs_are_recoverable(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    active = memory.create_design_run(
        run_id="active-run",
        mode="production_candidate",
        intake_json=_intake().to_dict(),
        intake_hash=_intake().content_hash,
        base_sha="a" * 40,
        candidate_ref="refs/ada-design/active-run",
        publishable=True,
    )
    for status in ("assessing_intake", "planning", "building"):
        memory.transition_design_run(active["run_id"], status)
    memory.add_design_run_event(active["run_id"], "implementing", "OpenCode was editing.")

    queued = memory.create_design_run(
        run_id="queued-run",
        mode="production_candidate",
        intake_json=_intake().to_dict(),
        intake_hash=_intake().content_hash,
        base_sha="a" * 40,
        candidate_ref="refs/ada-design/queued-run",
        publishable=True,
    )
    for status in ("assessing_intake", "planning"):
        memory.transition_design_run(queued["run_id"], status)
    memory.add_design_run_event(queued["run_id"], "queued", "Waiting for the design worker.")

    assert memory.interrupt_running_design_runs() == 1
    assert memory.get_design_run("active-run")["status"] == DesignRunStatus.INTERRUPTED.value
    assert memory.get_design_run("queued-run")["status"] == DesignRunStatus.PLANNING.value
    assert memory.list_design_run_events("active-run")[-1]["stage"] == DesignRunStatus.INTERRUPTED.value
    memory.close()


def test_chat_job_handoff_queues_one_design_run_without_running_opencode(tmp_path, monkeypatch):
    repo = tmp_path / "site"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "index.html").write_text("baseline")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    memory = Memory(tmp_path / "memory.db")
    service = DesignService(memory, config={
        "site": {
            "clone_path": str(repo),
            "branch": "main",
            "repository": "owner/site",
            "writable_patterns": ["*.html", "*.css", "design/**"],
        },
        "persona": {"name": "Ada"},
        "llm": {"model": "deepseek/deepseek-v4-flash-0731"},
    })
    conversation_id = memory.create_conversation("Design")
    memory.enqueue_chat_job(conversation_id, "Redesign the homepage around depth.")
    job = memory.claim_chat_job("chat-worker")

    class Executor:
        def __init__(self):
            self.enqueued = []

        def enqueue(self, run_id):
            self.enqueued.append(run_id)

    executor = Executor()
    intake = _intake().to_dict()
    monkeypatch.setattr(
        "site_agent.brain.editor.handle_message",
        lambda *args, **kwargs: {
            "reply": "typed handoff",
            "proposal_id": None,
            "design_request": {
                "intent": "redesign",
                "intake": intake,
                "owner_summary": "I will prepare one reviewable redesign.",
                "target": {
                    "mode": "workspace",
                    "scope": "selected_page",
                    "route": {"path": "/shop", "kind": "page", "sourceId": "route-42"},
                    "preview": {"state": "draft", "url": "https://atelier.example/atelier-preview/shop"},
                    "payload": {"collection": "products", "id": "42", "sourceId": "product-source-id"},
                },
            },
        },
    )
    context = {
        "config": {**service.config, "data_dir": str(tmp_path / "data")},
        "memory": memory,
        "llm": object(),
        "design_service": DesignService(memory, config={
            **service.config,
            "data_dir": str(tmp_path / "data"),
        }),
        "design_executor": executor,
    }

    result = run_job(context, job, "chat-worker", adapter_factory=lambda: object())

    assert result["design_run_id"]
    assert result["design_status"] == "planning"
    assert executor.enqueued == [result["design_run_id"]]
    assert memory.get_chat_job(job["id"])["status"] == "done"
    assert memory.get_chat_job(job["id"])["result"]["design_run_id"] == result["design_run_id"]
    run = memory.get_design_run(result["design_run_id"])
    assert run["chat_job_id"] == job["id"]
    assert run["mode"] == "local_experiment"
    assert run["publishable"] is False
    assert run["context_snapshot"]["workspace_target"]["route"]["path"] == "/shop"
    experiment_root = next(
        event["detail"]["root"]
        for event in memory.list_design_run_events(run["run_id"])
        if event["stage"] == "experiment"
    )
    assert experiment_root != str(repo)
    remote = subprocess.run(
        ["git", "-C", experiment_root, "remote"], capture_output=True, text=True, check=True
    ).stdout.strip()
    head = subprocess.run(
        ["git", "-C", experiment_root, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert remote == ""
    assert head == run["base_sha"]
    memory.close()
