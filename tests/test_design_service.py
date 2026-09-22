import json
import pytest
import subprocess

from site_agent.application.designs import DesignService, DesignServiceError, owner_review_requirements_met
from site_agent.core.design_contracts import (
    BuildTarget,
    DesignCandidateReceipt,
    DesignManifest,
    QualityReport,
    PageBuildRequest,
    PageIntake,
    SiteIntake,
    VisualCritiqueReport,
    canonical_hash,
)
from site_agent.core.memory import Memory
from site_agent.hands.design_quality import QualityPolicy
from site_agent.hands.builder import BuilderError
from site_agent.hands.site_build import (
    NEXT_REACT_PROFILE,
    NEXT_REACT_TOOLCHAIN_DEPENDENCIES,
    PELICAN_BASELINE_PROFILE,
    SiteOutputArtifactStore,
)
from tests.test_design_contracts import _experience_plan


def test_owner_review_requires_a_passing_ready_run():
    base = {
        "candidate_sha": "a" * 40,
        "quality_report_json": {"state": "passed"},
        "artifact_required": False,
    }

    assert owner_review_requirements_met({**base, "status": "ready_for_review"}) is True
    assert owner_review_requirements_met({**base, "status": "needs_repair"}) is False
    assert owner_review_requirements_met({**base, "status": "incomplete"}) is False
    assert owner_review_requirements_met({
        **base,
        "status": "ready_for_review",
        "quality_report_json": {
            "state": "passed",
            "visual_critique": {"state": "repair"},
        },
    }) is False
    assert owner_review_requirements_met({
        **base,
        "status": "ready_for_review",
        "operation_kind": "visual_refinement",
        "quality_report_json": {
            "state": "passed",
            "visual_critique": {"state": "repair"},
        },
    }) is False


def _intake() -> SiteIntake:
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "North Star Studio",
            "offer_summary": "Brand strategy for independent businesses.",
            "primary_services": ["Brand strategy"],
        },
        "audience": {"primary": "Independent business owners"},
        "conversion": {"primary_action": "Book a consultation", "not_available": True},
        "brand": {"voice": "Clear, thoughtful, and warm."},
        "site": {"required_pages": ["home", "about", "contact"]},
    })


def _browser_screenshot_evidence(*routes: tuple[str, str, str]) -> dict:
    viewports = {}
    for route, viewport, screenshot_hash in routes:
        viewports.setdefault(viewport, []).append({
            "route": route,
            "screenshot_path": f"/tmp/{viewport}-{route.replace('/', '-')}.png",
            "screenshot_hash": screenshot_hash,
        })
    return {
        "browser": {
            "viewports": [
                {
                    "viewport": {"name": name, "width": 1440 if name == "desktop" else 390, "height": 1000 if name == "desktop" else 844},
                    "result": {"routes": routes},
                }
                for name, routes in viewports.items()
            ]
        }
    }


def test_experiment_root_cannot_overlap_live_paths_before_work(tmp_path):
    live_clone = tmp_path / "live" / "clone"
    live_data = tmp_path / "live" / "data"
    service = DesignService(
        Memory(tmp_path / "service.db"),
        config={"site": {"clone_path": str(live_clone)}, "data_dir": str(live_data)},
    )

    with pytest.raises(DesignServiceError, match="live"):
        service.create_experiment(_intake(), experiment_root=live_clone / "design-lab", base_sha="a" * 40)


def test_local_experiment_strips_provider_credentials_and_is_not_publishable(tmp_path):
    live_clone = tmp_path / "live" / "clone"
    live_data = tmp_path / "live" / "data"
    experiment_root = tmp_path / "lab"
    memory = Memory(tmp_path / "service.db")
    service = DesignService(
        memory,
        config={"site": {"clone_path": str(live_clone)}, "data_dir": str(live_data)},
    )

    run = service.create_experiment(_intake(), experiment_root=experiment_root, base_sha="a" * 40)
    clean = service.experiment_environment({
        "PATH": "/bin",
        "GITHUB_TOKEN": "secret",
        "OPENROUTER_API_KEY": "provider-secret",
        "SITE_AGENT_ADMIN_PASSWORD": "password",
    })

    assert run["mode"] == "local_experiment"
    assert run["publishable"] is False
    assert run["candidate_ref"].startswith("refs/ada-design-lab/")
    assert "GITHUB_TOKEN" not in clean
    assert clean["OPENROUTER_API_KEY"] == "provider-secret"
    assert clean["PATH"] == "/bin"
    memory.close()


def test_customer_chat_candidate_is_publishable_only_through_review(tmp_path):
    repo = tmp_path / "customer-site"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "index.html").write_text("baseline")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    base_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    memory = Memory(tmp_path / "service.db")
    service = DesignService(
        memory,
        config={"site": {"clone_path": str(repo), "branch": "main"}},
    )

    run = service.create_chat_candidate(
        _intake(),
        owner_request="Redesign the homepage",
        conversation_id=None,
        source_message_id=None,
        chat_job_id=1,
    )

    assert run["mode"] == "production_candidate"
    assert run["publishable"] is True
    assert run["base_sha"] == base_sha
    assert run["candidate_ref"] == f"refs/ada-design/{run['run_id']}"
    assert subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip() == base_sha
    memory.close()


def test_prepare_initial_request_persists_assessment_without_selecting_visual_direction(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory)
    run = service.create_run(_intake(), run_id="design-plan", base_sha="a" * 40)

    request = service.prepare_initial_request(run["run_id"])
    stored = service.get_run(run["run_id"])

    assert request.mode == "initial_homepage"
    assert request.base_sha == "a" * 40
    assert stored["status"] == "planning"
    assert stored["planning_json"]["assessment"]["complete_enough"] is True
    assert "selection" not in stored["planning_json"]
    assert "directions" not in stored["planning_json"]
    assert stored["planning_json"]["source_authoring"] == {
        "builder": "native_opencode",
        "visual_direction": "model_authored",
    }
    assert stored["planning_hash"]
    policy = service.quality_policy_for_run(run["run_id"])
    assert "Brand strategy for independent businesses." in policy.required_content
    assert "Brand strategy" in policy.required_content
    assert policy.contact_destination_unavailable is True
    assert policy.required_pages == ("home",)
    memory.close()


def test_local_initial_build_uses_next_target_and_quality_profile(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(
        memory,
        config={
            "data_dir": str(tmp_path / "data"),
            "site": {"clone_path": str(tmp_path / "live" / "clone")},
        },
    )
    run = service.create_experiment(
        _intake(),
        experiment_root=tmp_path / "lab" / "clone",
        base_sha="a" * 40,
        run_id="local-next",
    )

    request = service.prepare_initial_request(run["run_id"])
    target = service.build_target_for_run(run["run_id"])
    service.queue_build(run["run_id"], request, target)
    policy = service.quality_policy_for_run(run["run_id"])

    assert target.operation_kind == "initial_build"
    assert target.mode == "local_experiment"
    assert target.push_mode == "none"
    assert target.publishable is False
    assert target.allowed_paths == NEXT_REACT_PROFILE.writable_patterns
    assert policy.output_dir == NEXT_REACT_PROFILE.output_dir
    assert policy.required_pages == ("home.html",)
    assert policy.allowed_patterns == NEXT_REACT_PROFILE.writable_patterns
    assert "package.json" in policy.allowed_hard_denied_paths
    assert {
        (item.get("package"), item.get("version"))
        for item in policy.approved_capabilities
    } >= {
        (item["package"], item["version"])
        for item in NEXT_REACT_TOOLCHAIN_DEPENDENCIES
    }
    assert policy.build_command is None
    memory.close()


def test_local_next_quality_policy_preserves_frontend_capability_details(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(
        memory,
        config={
            "data_dir": str(tmp_path / "data"),
            "site": {"clone_path": str(tmp_path / "live" / "clone")},
            "design_engine": {
                "libraries": {"gsap": {"enabled": True, "required": True}},
            },
        },
    )
    run = service.create_experiment(
        _intake(),
        experiment_root=tmp_path / "lab" / "clone",
        base_sha="a" * 40,
        run_id="local-next-capabilities",
    )
    service.prepare_initial_request(run["run_id"])

    gsap = next(
        item for item in service.quality_policy_for_run(run["run_id"]).approved_capabilities
        if item.get("package") == "gsap"
    )

    assert gsap["version"] == "3.12.5"
    assert "ScrollTrigger" in gsap["capabilities"]
    memory.close()


def test_local_technical_repair_quality_policy_covers_all_frozen_routes(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(
        memory,
        config={
            "data_dir": str(tmp_path / "data"),
            "site": {"clone_path": str(tmp_path / "live" / "clone")},
        },
    )
    parent = service.create_run(
        _intake(),
        mode="local_experiment",
        run_id="local-next-parent",
        base_sha="a" * 40,
    )
    memory.update_design_run(parent["run_id"], candidate_sha="a" * 40)
    child = service.create_run(
        _intake(),
        mode="local_experiment",
        run_id="local-next-repair",
        base_sha="b" * 40,
        candidate_ref="refs/ada-design-lab/local-next-repair",
        parent_run_id=parent["run_id"],
        operation_kind="technical_repair",
        source_candidate_sha="a" * 40,
    )
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": child["run_id"],
        "mode": "initial_homepage",
        "base_sha": child["base_sha"],
        "page_path": "index.html",
        "purpose": "Repair the retained candidate.",
        "acceptance_criteria": ["Preserve every public route."],
        "content": {
            "site_intake": _intake().to_dict(),
            "design_brief": {"required_pages": ["index.html", "articles.html"]},
        },
    })
    memory.update_design_run(
        child["run_id"],
        planning_json={"build_profile": "next_react", "build_request": request.to_dict()},
    )

    policy = service.quality_policy_for_run(child["run_id"])

    assert policy.required_pages == ("index.html", "articles.html")
    assert policy.output_dir == NEXT_REACT_PROFILE.output_dir
    assert policy.allowed_patterns == NEXT_REACT_PROFILE.writable_patterns
    memory.close()


def test_local_visual_refinement_of_technical_repair_covers_all_frozen_routes(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(
        memory,
        config={
            "data_dir": str(tmp_path / "data"),
            "site": {"clone_path": str(tmp_path / "live" / "clone")},
        },
    )
    parent = service.create_run(
        _intake(),
        mode="local_experiment",
        run_id="local-next-technical-parent",
        base_sha="a" * 40,
        operation_kind="technical_repair",
    )
    memory.update_design_run(parent["run_id"], candidate_sha="a" * 40)
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "local-next-visual-child",
        "mode": "visual_refinement",
        "base_sha": "b" * 40,
        "page_path": "index.html",
        "purpose": "Refine the retained candidate.",
        "acceptance_criteria": ["Preserve every public route."],
        "content": {"site_intake": _intake().to_dict()},
    })
    child = service.create_run(
        _intake(),
        mode="local_experiment",
        run_id="local-next-visual-child",
        base_sha="b" * 40,
        candidate_ref="refs/ada-design-lab/local-next-visual-child",
        parent_run_id=parent["run_id"],
        operation_kind="visual_refinement",
        source_candidate_sha="a" * 40,
    )
    memory.update_design_run(
        child["run_id"],
        planning_json={"build_profile": "next_react", "build_request": request.to_dict()},
    )

    policy = service.quality_policy_for_run(child["run_id"])

    assert policy.required_pages == ("home", "about", "contact")
    assert policy.output_dir == NEXT_REACT_PROFILE.output_dir
    assert policy.allowed_patterns == NEXT_REACT_PROFILE.writable_patterns
    memory.close()


def test_technical_repair_child_preserves_parent_candidate_and_workspace(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(
        memory,
        config={
            "data_dir": str(tmp_path / "data"),
            "site": {"clone_path": str(tmp_path / "live" / "clone")},
        },
    )
    parent = service.create_experiment(
        _intake(),
        experiment_root=tmp_path / "lab" / "clone",
        base_sha="a" * 40,
        run_id="repair-parent",
    )
    memory.update_design_run(
        parent["run_id"],
        candidate_sha="b" * 40,
        planning_json={"build_profile": "next_react"},
        quality_report_json={
            "visual_critique": {
                "state": "repair",
                "run_id": parent["run_id"],
                "candidate_sha": "b" * 40,
                "screenshot_evidence": [{"screenshot_path": "/tmp/parent.png"}],
                "findings": [{
                    "area": "conversion",
                    "severity": "high",
                    "observation": "Keep the action honest.",
                }],
            },
        },
    )
    memory.transition_design_run(parent["run_id"], "failed", error="quality gates failed")
    child = service.create_technical_repair_run(parent["run_id"], run_id="repair-child")

    assert child["run"]["parent_run_id"] == parent["run_id"]
    assert child["run"]["operation_kind"] == "technical_repair"
    assert child["run"]["base_sha"] == "b" * 40
    assert child["run"]["source_candidate_sha"] == "b" * 40
    assert child["run"]["status"] == "planning"
    assert child["request"]["content"]["technical_repair"]["parent_candidate_sha"] == "b" * 40
    assert child["request"]["content"]["visual_critique"]["screenshot_evidence"] == [
        {"screenshot_path": "/tmp/parent.png"},
    ]
    assert child["target"]["operation_kind"] == "technical_repair"
    assert child["target"]["allowed_paths"] == list(NEXT_REACT_PROFILE.writable_patterns)
    assert service.quality_policy_for_run(child["run"]["run_id"]).required_pages == (
        "home", "about", "contact"
    )
    memory.close()


def test_repair_quality_reuses_parent_experience_plan(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(
        memory,
        config={
            "data_dir": str(tmp_path / "data"),
            "site": {"clone_path": str(tmp_path / "live" / "clone")},
        },
    )
    parent = service.create_experiment(
        _intake(),
        experiment_root=tmp_path / "lab" / "clone",
        base_sha="a" * 40,
        run_id="plan-parent",
    )
    memory.update_design_run(parent["run_id"], candidate_sha="b" * 40)
    memory.transition_design_run(parent["run_id"], "failed", error="quality gates failed")
    phase = memory.claim_design_phase(
        parent["run_id"],
        "creative_selection",
        variant_key="primary",
        base_sha="a" * 40,
        context_snapshot_hash="c" * 64,
        input_hashes=("e" * 64,),
        provider_id="test",
        model="test",
    )
    raw_plan = _experience_plan()
    raw_plan["review_rubric"] = ["logo does not collide"]
    raw_plan["asset_composition_plan"][0]["logo_rule"] = "Keep the supplied mark unmodified."
    raw_plan["asset_composition_plan"][0]["focal_region_to_preserve"] = "preserve the visible mark"
    phase_payload = {
        "schema_version": 1,
        "run_id": parent["run_id"],
        "phase": "creative_selection",
        "variant_key": "primary",
        "attempt": 1,
        "status": "completed",
        "base_sha": "a" * 40,
        "context_snapshot_hash": "c" * 64,
        "input_hashes": ["e" * 64],
        "producer": "test",
        "payload": raw_plan,
    }
    memory.complete_design_phase(phase["id"], phase_payload)
    child = service.create_technical_repair_run(parent["run_id"], run_id="plan-child")

    inherited = service._experience_plan_for_run(child["run"]["run_id"])

    assert inherited is not None
    assert inherited.content_hash
    assert inherited.review_rubric[0]["condition"] == "logo does not collide"
    assert inherited.asset_composition_plan[0].logo_rule is None
    assert inherited.asset_composition_plan[0].focal_region_to_preserve is None
    memory.close()


def test_creative_run_reads_the_persisted_plan_from_planning_state(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(
        memory,
        config={"design_engine": {"orchestration": "creative"}},
    )
    run = service.create_run(_intake(), run_id="creative-plan-state", base_sha="a" * 40)
    raw_plan = _experience_plan(
        run_id=run["run_id"],
        base_sha="a" * 40,
        context_snapshot_hash="c" * 64,
    )
    memory.update_design_run(run["run_id"], planning_json={"experience_plan": raw_plan})

    plan = service._experience_plan_for_run(run["run_id"])

    assert plan is not None
    assert plan.run_id == run["run_id"]
    assert plan.base_sha == "a" * 40
    memory.close()


def test_creative_quality_validation_never_skips_a_missing_experience_plan(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(
        memory,
        config={"design_engine": {"orchestration": "creative"}},
    )
    run = service.create_run(_intake(), run_id="creative-plan-required", base_sha="a" * 40)
    memory.update_design_run(run["run_id"], candidate_sha="b" * 40)
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating"):
        memory.transition_design_run(run["run_id"], status)
    captured = {}

    def fake_quality(*args, **kwargs):
        captured["experience_plan"] = kwargs.get("experience_plan")
        return QualityReport.from_dict({
            "run_id": run["run_id"],
            "candidate_sha": "b" * 40,
            "state": "incomplete",
            "findings": [],
            "evidence": {},
            "gates": {},
        })

    monkeypatch.setattr("site_agent.application.designs.run_quality_gates", fake_quality)
    service.validate_run(run["run_id"], tmp_path, policy=QualityPolicy(build_command=None))

    assert captured["experience_plan"] == {}
    memory.close()


def test_creative_execute_build_rejects_a_receipt_without_the_locked_plan(tmp_path):
    memory = Memory(tmp_path / "service.db")

    class PlanlessBuilder:
        def build_design(self, request, target, progress=None):
            return DesignCandidateReceipt.from_dict({
                "run_id": request.run_id,
                "operation_kind": "initial_build",
                "base_sha": target.base_sha,
                "candidate_sha": "c" * 40,
                "candidate_ref": target.candidate_ref,
                "diff_summary": "candidate",
                "changed_paths": ["index.html"],
                "manifest_path": "design/ada-design-manifest.json",
                "manifest_hash": "d" * 64,
                "opencode_session_id": "planless-session",
                "transcript_path": "artifacts/planless.jsonl",
                "provider": "test",
                "model": "test-model",
                "publishable": False,
            })

    service = DesignService(
        memory,
        builder=PlanlessBuilder(),
        config={"design_engine": {"orchestration": "creative"}},
    )
    run = service.create_run(
        _intake(),
        mode="local_experiment",
        publishable=False,
        base_sha="a" * 40,
        run_id="creative-planless-receipt",
    )
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": run["run_id"],
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": run["candidate_ref"],
        "push_mode": "none",
        "publishable": False,
    })

    with pytest.raises(DesignServiceError, match="no hash-bound experience plan"):
        service.execute_build(run["run_id"], request, target)

    assert service.get_run(run["run_id"])["status"] == "failed"
    memory.close()


def test_quality_validation_rejects_evidence_bound_to_a_different_plan_hash(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory, config={"design_engine": {"orchestration": "creative"}})
    run = service.create_run(_intake(), run_id="creative-plan-hash", base_sha="a" * 40)
    raw_plan = _experience_plan(
        run_id=run["run_id"],
        base_sha="a" * 40,
        context_snapshot_hash="c" * 64,
    )
    memory.update_design_run(
        run["run_id"],
        candidate_sha="b" * 40,
        planning_json={"experience_plan": raw_plan},
    )
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating"):
        memory.transition_design_run(run["run_id"], status)

    monkeypatch.setattr(
        "site_agent.application.designs.run_quality_gates",
        lambda *args, **kwargs: QualityReport.from_dict({
            "run_id": run["run_id"],
            "candidate_sha": "b" * 40,
            "state": "passed",
            "findings": [],
            "evidence": {"experience_journey": {"experience_plan_hash": "e" * 64}},
            "gates": {},
        }),
    )

    report = service.validate_run(run["run_id"], tmp_path, policy=QualityPolicy(build_command=None))

    assert report.state == "incomplete"
    assert any(item["code"] == "experience_plan_identity_missing" for item in report.findings)
    memory.close()


def test_local_visual_refinement_reuses_next_target_and_quality_profile(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(
        memory,
        config={
            "data_dir": str(tmp_path / "data"),
            "site": {"clone_path": str(tmp_path / "live" / "clone")},
        },
    )
    parent = service.create_experiment(
        _intake(),
        experiment_root=tmp_path / "lab" / "clone",
        base_sha="a" * 40,
        run_id="local-next-parent",
    )
    service.prepare_initial_request(parent["run_id"])
    service.build_target_for_run(parent["run_id"])
    service.queue_build(parent["run_id"], None, service.build_target_for_run(parent["run_id"]))
    memory.update_design_run(parent["run_id"], candidate_sha="b" * 40)
    for status in ("building", "candidate_ready", "validating", "needs_repair"):
        memory.transition_design_run(parent["run_id"], status)
    critique = VisualCritiqueReport.from_dict({
        "run_id": parent["run_id"],
        "candidate_sha": "b" * 40,
        "model_id": "visual-review",
        "state": "repair",
        "findings": [{"category": "hierarchy", "message": "Strengthen the focal point."}],
        "repair_plan": [{"finding": "focal point", "change": "Increase the hero contrast."}],
    })
    memory.update_design_run(
        parent["run_id"],
        quality_report_json={"state": "passed", "visual_critique": critique.to_dict()},
    )

    child = service.create_visual_refinement_run(parent["run_id"], critique, run_id="local-next-refined")
    child_run = child["run"]
    target = service.build_target_for_run(child_run["run_id"])
    policy = service.quality_policy_for_run(child_run["run_id"])

    assert target.allowed_paths == NEXT_REACT_PROFILE.writable_patterns
    assert policy.output_dir == NEXT_REACT_PROFILE.output_dir
    assert policy.allowed_patterns == NEXT_REACT_PROFILE.writable_patterns
    assert "package.json" in policy.allowed_hard_denied_paths
    assert {
        (item.get("package"), item.get("version"))
        for item in policy.approved_capabilities
    } >= {
        (item["package"], item["version"])
        for item in NEXT_REACT_TOOLCHAIN_DEPENDENCIES
    }
    memory.transition_design_run(child_run["run_id"], "failed")
    retried = service.create_visual_refinement_run(parent["run_id"], critique, run_id="local-next-retried")
    assert retried["run"]["parent_run_id"] == parent["run_id"]
    assert retried["target"]["allowed_paths"] == list(NEXT_REACT_PROFILE.writable_patterns)
    memory.close()


def test_legacy_local_run_infers_pelican_profile_from_frozen_quality_policy(tmp_path):
    memory = Memory(tmp_path / "service.db")
    clone = tmp_path / "legacy-clone"
    (clone / ".git").mkdir(parents=True)
    service = DesignService(
        memory,
        config={
            "data_dir": str(tmp_path / "data"),
            "site": {"clone_path": str(clone)},
            "design_engine": {"quality": {"output_dir": "output"}},
        },
    )
    run = service.create_run(
        _intake(),
        mode="local_experiment",
        publishable=False,
        base_sha="a" * 40,
        run_id="legacy-pelican",
    )
    memory.add_design_run_event(run["run_id"], "experiment", "Legacy experiment clone.", {"root": str(clone)})
    service.capture_context_snapshot(run["run_id"])

    assert service.build_profile_for_run(run["run_id"]) == PELICAN_BASELINE_PROFILE.name
    memory.close()


def test_execute_build_persists_candidate_and_stops_before_quality_ready(tmp_path):
    memory = Memory(tmp_path / "service.db")

    class FakeBuilder:
        def build_design(self, request, target, progress=None):
            if progress:
                progress("OpenCode retained the design candidate")
            return DesignCandidateReceipt.from_dict({
                "run_id": request.run_id,
                "operation_kind": "initial_build",
                "base_sha": target.base_sha,
                "candidate_sha": "c" * 40,
                "candidate_ref": target.candidate_ref,
                "diff_summary": "1 file changed",
                "changed_paths": ["index.html"],
                "manifest_path": "design/ada-design-manifest.json",
                "manifest_hash": "d" * 64,
                "opencode_session_id": "fake-session",
                "transcript_path": "artifacts/transcript.jsonl",
                "provider": "entrim",
                "model": "deepseek-ai/DeepSeek-V4-Flash",
                "publishable": True,
            })

    service = DesignService(memory, builder=FakeBuilder())
    run = service.create_run(_intake(), run_id="design-run-1", base_sha="a" * 40)
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": run["run_id"],
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "production_candidate",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design/design-run-1",
        "push_mode": "none",
        "publishable": True,
    })

    receipt = service.execute_build(run["run_id"], request, target)
    stored = service.get_run(run["run_id"])

    assert receipt.candidate_sha == "c" * 40
    assert stored["status"] == "candidate_ready"
    assert stored["candidate_sha"] == "c" * 40
    assert [event["stage"] for event in stored["events"]] == [
        "created", "assessing_intake", "intake_assessment", "planning", "plan_output",
        "building", "candidate_ready", "candidate_ready",
    ]
    memory.close()


def test_partial_build_receipt_retains_candidate_but_cannot_be_reviewed(tmp_path):
    memory = Memory(tmp_path / "service.db")

    class FakeBuilder:
        def build_design(self, request, target, progress=None):
            return DesignCandidateReceipt.from_dict({
                "run_id": request.run_id,
                "operation_kind": "initial_build",
                "base_sha": target.base_sha,
                "candidate_sha": "e" * 40,
                "candidate_ref": target.candidate_ref,
                "diff_summary": "partial candidate",
                "changed_paths": ["index.html"],
                "manifest_path": "design/ada-design-manifest.json",
                "manifest_hash": "f" * 64,
                "opencode_session_id": "partial-session",
                "transcript_path": "artifacts/partial.jsonl",
                "provider": "entrim",
                "model": "deepseek-ai/DeepSeek-V4-Flash",
                "publishable": True,
                "build_error": "opencode exited 1: provider stopped",
            })

    service = DesignService(memory, builder=FakeBuilder())
    run = service.create_run(_intake(), run_id="design-partial", base_sha="a" * 40)
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": run["run_id"],
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "production_candidate",
        "base_sha": "a" * 40,
        "candidate_ref": run["candidate_ref"],
        "push_mode": "none",
        "publishable": True,
    })

    receipt = service.execute_build(run["run_id"], request, target)
    stored = service.get_run(run["run_id"])

    assert receipt.build_error
    assert stored["status"] == "failed"
    assert stored["candidate_sha"] == "e" * 40
    assert stored["transcript_path"] == "artifacts/partial.jsonl"
    with pytest.raises(DesignServiceError, match="not ready for review"):
        service.create_review_draft(run["run_id"])
    memory.close()


def test_noop_builder_failure_retains_transcript_without_candidate(tmp_path):
    memory = Memory(tmp_path / "service.db")

    class FailingBuilder:
        def build_design(self, request, target, progress=None):
            raise BuilderError(
                "design build finished without implementation changes",
                result={
                    "session_id": "noop-session",
                    "transcript_path": "design-runs/design-noop/opencode.jsonl",
                },
            )

    service = DesignService(memory, config={"data_dir": str(tmp_path / "data")}, builder=FailingBuilder())
    run = service.create_run(_intake(), run_id="design-noop", base_sha="a" * 40)
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": run["run_id"],
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "production_candidate",
        "base_sha": "a" * 40,
        "candidate_ref": run["candidate_ref"],
        "push_mode": "none",
        "publishable": True,
    })

    with pytest.raises(DesignServiceError, match="without implementation changes"):
        service.execute_build(run["run_id"], request, target)

    stored = service.get_run(run["run_id"])
    assert stored["status"] == "failed"
    assert stored["candidate_sha"] == ""
    assert stored["transcript_path"] == "design-runs/design-noop/opencode.jsonl"
    assert stored["opencode_session_id"] == "noop-session"
    assert stored["transcript_artifact_id"]
    memory.close()


def test_validate_run_persists_report_and_makes_passing_candidate_reviewable(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "index.html").write_text("baseline")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    base_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    (repo / "index.html").write_text("candidate")
    output = repo / "output"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Candidate</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Candidate</h1></body></html>'
    )
    manifest = DesignManifest.from_dict({
        "schema_version": 1,
        "source_homepage_path": "index.html",
        "design_direction_id": "test-direction",
        "intake_hash": "a" * 64,
        "tokens": {},
        "shared_regions": [],
        "source_files": {"changed": ["index.html"]},
    })
    (repo / "design").mkdir()
    (repo / "design" / "ada-design-manifest.json").write_text(json.dumps(manifest.to_dict()))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "candidate"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    memory = Memory(tmp_path / "service.db")

    class FakeBuilder:
        def build_design(self, request, target, progress=None):
            return DesignCandidateReceipt.from_dict({
                "run_id": request.run_id,
                "operation_kind": "initial_build",
                "base_sha": target.base_sha,
                "candidate_sha": candidate_sha,
                "candidate_ref": target.candidate_ref,
                "diff_summary": "1 file changed",
                "changed_paths": ["index.html", "output/index.html"],
                "manifest_path": "design/ada-design-manifest.json",
                "manifest_hash": manifest.content_hash,
                "opencode_session_id": "fake-session",
                "transcript_path": "artifacts/transcript.jsonl",
                "provider": "entrim",
                "model": "deepseek-ai/DeepSeek-V4-Flash",
                "publishable": True,
            })

    service = DesignService(memory, builder=FakeBuilder())
    run = service.create_run(_intake(), run_id="design-run-quality", base_sha=base_sha)
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": run["run_id"],
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "production_candidate",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design/design-run-quality",
        "push_mode": "none",
        "publishable": True,
    })

    service.execute_build(run["run_id"], request, target)
    assert service.get_run(run["run_id"])["planning_json"]["build_request"]["run_id"] == run["run_id"]
    report = service.validate_run(
        run["run_id"],
        repo,
        policy=QualityPolicy(
            build_command=None,
            allowed_patterns=("index.html", "output/**"),
            required_pages=("index.html",),
            manifest_path="design/ada-design-manifest.json",
        ),
    )

    stored = service.get_run(run["run_id"])
    assert report.state == "passed"
    assert stored["status"] == "ready_for_review"
    assert stored["quality_report_json"]["state"] == "passed"
    assert stored["quality_report_hash"]
    memory.close()


def test_validate_run_persists_output_identity_before_owner_surface_inspection(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "service.db")
    output = tmp_path / "authoritative-output"
    output.mkdir()
    (output / "index.html").write_text("<html><body><h1>Candidate</h1></body></html>", encoding="utf-8")
    store = SiteOutputArtifactStore(tmp_path / "output-artifacts")
    service = DesignService(memory, output_artifact_store=store)
    run = service.create_run(_intake(), run_id="design-artifact-before-browser", base_sha="a" * 40)
    memory.update_design_run(
        run["run_id"],
        candidate_sha="b" * 40,
        candidate_ref=run["candidate_ref"],
        planning_json={"build_profile": PELICAN_BASELINE_PROFILE.name},
    )
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating"):
        memory.transition_design_run(run["run_id"], status)

    class OwnerSurfaceBrowser:
        def __init__(self):
            self.bound = None

        def bind_output_artifact(self, artifact):
            self.bound = dict(artifact)

        def inspect(self, _output_dir, _viewport):
            persisted = memory.get_design_run(run["run_id"])
            assert persisted["output_artifact_id"] == self.bound["artifact_id"]
            assert persisted["output_tree_hash"] == self.bound["tree_hash"]
            return {"routes": []}

    browser = OwnerSurfaceBrowser()

    def fake_quality(*_args, **kwargs):
        published = kwargs["output_artifact_publisher"](output)
        kwargs["browser"].inspect(output, {"name": "desktop", "width": 1440, "height": 900})
        return QualityReport.from_dict({
            "run_id": run["run_id"],
            "candidate_sha": "b" * 40,
            "state": "passed",
            "findings": [],
            "evidence": {"output_artifact": {"status": "passed", **published}},
            "gates": {},
        })

    monkeypatch.setattr("site_agent.application.designs.run_quality_gates", fake_quality)

    report = service.validate_run(
        run["run_id"],
        tmp_path,
        policy=QualityPolicy(build_command=None),
        browser=browser,
    )

    assert report.state == "passed"
    assert memory.get_design_run(run["run_id"])["output_artifact_id"] == browser.bound["artifact_id"]
    memory.close()


def test_review_draft_requires_react_gsap_build_and_browser_evidence(tmp_path):
    memory = Memory(tmp_path / "service.db")
    store = SiteOutputArtifactStore(tmp_path / "output-artifacts")
    service = DesignService(memory, output_artifact_store=store)
    run = service.create_run(_intake(), run_id="design-review-requires-implementation", base_sha="a" * 40)
    memory.update_design_run(run["run_id"], candidate_sha="b" * 40, candidate_ref=run["candidate_ref"])
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating", "ready_for_review"):
        memory.transition_design_run(run["run_id"], status)

    output = tmp_path / "output"
    output.mkdir()
    (output / "index.html").write_text("<html><body><h1>Candidate</h1></body></html>", encoding="utf-8")
    published = store.publish(output, profile=PELICAN_BASELINE_PROFILE, candidate_sha="b" * 40)
    report = {
        "run_id": run["run_id"],
        "candidate_sha": "b" * 40,
        "state": "passed",
        "findings": [],
        "evidence": {
            "output_artifact": {"status": "passed", **published},
            "native_source": {"status": "skipped", "source_files": []},
            "browser": {"status": "passed"},
        },
        "gates": {"build": "passed", "output": "passed", "browser": "passed", "native_source": "skipped"},
    }
    memory.update_design_run(
        run["run_id"],
        quality_report_json=report,
        quality_report_hash=canonical_hash(report),
        output_artifact_id=published["artifact_id"],
        output_tree_hash=published["tree_hash"],
        design_manifest_path="design/ada-design-manifest.json",
        design_manifest_hash="c" * 64,
    )

    with pytest.raises(DesignServiceError, match="implementation|quality"):
        service.create_review_draft(run["run_id"])

    memory.close()


def test_validate_run_retains_large_quality_report_with_bounded_artifact_preview(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    memory = Memory(tmp_path / "service.db")
    service = DesignService(
        memory,
        config={"site": {"clone_path": str(repo)}},
    )
    run = service.create_run(_intake(), run_id="design-large-quality", base_sha="a" * 40)
    memory.update_design_run(
        run["run_id"],
        candidate_sha="c" * 40,
        candidate_ref=run["candidate_ref"],
    )
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating"):
        memory.transition_design_run(run["run_id"], status)

    large_report = QualityReport.from_dict({
        "run_id": run["run_id"],
        "candidate_sha": "c" * 40,
        "state": "passed",
        "findings": [],
        "evidence": {"browser": {"diagnostic": "x" * 120_000}},
        "gates": {"browser": "passed"},
    })
    monkeypatch.setattr(
        "site_agent.application.designs.run_quality_gates",
        lambda *args, **kwargs: large_report,
    )

    report = service.validate_run(
        run["run_id"],
        repo,
        policy=QualityPolicy(build_command=None),
    )

    stored = service.get_run(run["run_id"])
    assert report.state == "passed"
    assert stored["status"] == "ready_for_review"
    assert stored["quality_report_json"]["evidence"]["browser"]["diagnostic"] == "x" * 120_000
    assert stored["quality_report_hash"]
    artifact = memory.get_artifact(stored["build_artifact_id"])
    assert artifact is not None
    assert "quality_report" not in artifact.preview_data
    assert artifact.preview_data["quality_report_hash"] == stored["quality_report_hash"]
    memory.close()


def test_visual_review_persists_critique_and_marks_run_needs_repair(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory)
    run = service.create_run(_intake(), run_id="design-visual-review", base_sha="a" * 40)
    memory.update_design_run(run["run_id"], candidate_sha="c" * 40, candidate_ref=run["candidate_ref"])
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating"):
        memory.transition_design_run(run["run_id"], status)
    memory.update_design_run(
        run["run_id"],
        quality_report_json={"run_id": run["run_id"], "candidate_sha": "c" * 40, "state": "passed"},
    )
    critique = VisualCritiqueReport.from_dict({
        "run_id": run["run_id"],
        "candidate_sha": "c" * 40,
        "model_id": "Qwen/Qwen3.8-27B",
        "state": "repair",
        "findings": [{"severity": "blocker", "category": "hierarchy", "message": "Repair the hierarchy."}],
    })
    result = service.visual_review_run(
        run["run_id"],
        reviewer=lambda *args, **kwargs: critique,
    )

    stored = memory.get_design_run(run["run_id"])
    assert result.state == "repair"
    assert stored["status"] == "needs_repair"
    assert stored["visual_critique_hash"]
    assert stored["quality_report_json"]["visual_critique"]["candidate_sha"] == "c" * 40
    memory.close()


def test_final_visual_refinement_stays_blocked_after_visual_repair(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory)
    run = service.create_run(
        _intake(),
        run_id="design-final-visual-review",
        base_sha="a" * 40,
        operation_kind="visual_refinement",
    )
    memory.update_design_run(run["run_id"], candidate_sha="c" * 40, candidate_ref=run["candidate_ref"])
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating"):
        memory.transition_design_run(run["run_id"], status)
    memory.update_design_run(
        run["run_id"],
        quality_report_json={"run_id": run["run_id"], "candidate_sha": "c" * 40, "state": "passed"},
    )
    critique = VisualCritiqueReport.from_dict({
        "run_id": run["run_id"],
        "candidate_sha": "c" * 40,
        "model_id": "Qwen/Qwen3.8-27B",
        "state": "repair",
        "findings": [{"severity": "medium", "category": "hierarchy", "message": "Owner can review the hierarchy."}],
    })

    result = service.visual_review_run(
        run["run_id"],
        reviewer=lambda *args, **kwargs: critique,
    )

    stored = memory.get_design_run(run["run_id"])
    assert result.state == "repair"
    assert stored["status"] == "needs_repair"
    assert stored["quality_report_json"]["visual_critique"]["state"] == "repair"
    memory.close()


def test_incomplete_visual_review_can_be_retried_explicitly(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory)
    run = service.create_run(_intake(), run_id="design-visual-retry", base_sha="a" * 40)
    memory.update_design_run(run["run_id"], candidate_sha="c" * 40, candidate_ref=run["candidate_ref"])
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating"):
        memory.transition_design_run(run["run_id"], status)
    memory.update_design_run(
        run["run_id"],
        quality_report_json={"run_id": run["run_id"], "candidate_sha": "c" * 40, "state": "passed"},
    )
    inconclusive = VisualCritiqueReport.from_dict({
        "run_id": run["run_id"],
        "candidate_sha": "c" * 40,
        "model_id": "Qwen/Qwen3.8-27B",
        "state": "inconclusive",
        "findings": [{"severity": "incomplete", "category": "visual_review", "message": "Timed out."}],
    })
    passed = VisualCritiqueReport.from_dict({
        "run_id": run["run_id"],
        "candidate_sha": "c" * 40,
        "model_id": "Qwen/Qwen3.8-27B",
        "state": "passed",
        "findings": [],
    })
    responses = iter((inconclusive, passed))

    assert service.visual_review_run(run["run_id"], reviewer=lambda *args, **kwargs: next(responses)).state == "inconclusive"
    assert memory.get_design_run(run["run_id"])["status"] == "incomplete"
    assert service.visual_review_run(run["run_id"], reviewer=lambda *args, **kwargs: next(responses)).state == "passed"
    assert memory.get_design_run(run["run_id"])["status"] == "ready_for_review"
    memory.close()


def test_deterministically_ready_run_can_start_explicit_visual_review(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory)
    run = service.create_run(_intake(), run_id="design-ready-visual-review", base_sha="a" * 40)
    memory.update_design_run(run["run_id"], candidate_sha="c" * 40, candidate_ref=run["candidate_ref"])
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating", "ready_for_review"):
        memory.transition_design_run(run["run_id"], status)
    memory.update_design_run(
        run["run_id"],
        quality_report_json={"run_id": run["run_id"], "candidate_sha": "c" * 40, "state": "passed"},
    )
    critique = VisualCritiqueReport.from_dict({
        "run_id": run["run_id"],
        "candidate_sha": "c" * 40,
        "model_id": "visual-review",
        "state": "passed",
        "findings": [],
    })

    result = service.visual_review_run(
        run["run_id"],
        reviewer=lambda *args, **kwargs: critique,
    )

    assert result.state == "passed"
    assert memory.get_design_run(run["run_id"])["status"] == "ready_for_review"
    memory.close()


def test_quality_failure_keeps_candidate_and_marks_run_needs_repair(tmp_path, monkeypatch):
    from site_agent.application import designs as designs_module

    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory)
    run = service.create_run(_intake(), run_id="design-needs-repair", base_sha="a" * 40)
    memory.update_design_run(run["run_id"], candidate_sha="c" * 40, candidate_ref=run["candidate_ref"])
    for status in ("assessing_intake", "planning", "building", "candidate_ready"):
        memory.transition_design_run(run["run_id"], status)
    monkeypatch.setattr(
        designs_module,
        "run_quality_gates",
        lambda *args, **kwargs: QualityReport.from_dict({
            "run_id": run["run_id"],
            "candidate_sha": "c" * 40,
            "state": "failed",
            "findings": [{"severity": "blocker", "code": "build_failed", "message": "Build failed."}],
            "evidence": {"build": {"status": "failed"}},
            "gates": {"build": "failed"},
        }),
    )

    report = service.validate_run(run["run_id"], tmp_path, policy=QualityPolicy(build_command=None))

    stored = service.get_run(run["run_id"])
    assert report.state == "failed"
    assert stored["status"] == "needs_repair"
    assert stored["candidate_sha"] == "c" * 40
    assert stored["quality_report_json"]["findings"][0]["code"] == "build_failed"
    memory.close()


def test_visual_refinement_requires_parent_screenshot_coverage(tmp_path, monkeypatch):
    from site_agent.application import designs as designs_module

    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory)
    parent = service.create_run(_intake(), run_id="visual-parent-coverage", base_sha="a" * 40)
    memory.update_design_run(
        parent["run_id"],
        candidate_sha="b" * 40,
        quality_report_json={
            "run_id": parent["run_id"],
            "candidate_sha": "b" * 40,
            "state": "passed",
            "evidence": _browser_screenshot_evidence(
                ("index.html", "desktop", "c" * 64),
                ("index.html", "mobile", "d" * 64),
            ),
        },
    )
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating", "ready_for_review"):
        memory.transition_design_run(parent["run_id"], status)
    child = service.create_run(
        _intake(),
        run_id="visual-child-coverage",
        base_sha="b" * 40,
        parent_run_id=parent["run_id"],
        source_candidate_sha="b" * 40,
        operation_kind="visual_refinement",
    )
    memory.update_design_run(child["run_id"], candidate_sha="e" * 40)
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating"):
        memory.transition_design_run(child["run_id"], status)
    monkeypatch.setattr(
        designs_module,
        "run_quality_gates",
        lambda *args, **kwargs: QualityReport.from_dict({
            "run_id": child["run_id"],
            "candidate_sha": "e" * 40,
            "state": "passed",
            "evidence": _browser_screenshot_evidence(("index.html", "desktop", "f" * 64)),
        }),
    )

    report = service.validate_run(child["run_id"], tmp_path, policy=QualityPolicy(build_command=None))

    stored = service.get_run(child["run_id"])
    assert report.state == "incomplete"
    assert stored["status"] == "incomplete"
    comparison = report.to_dict()["evidence"]["parent_visual_comparison"]
    assert comparison["status"] == "incomplete"
    assert comparison["missing"] == [["index.html", "mobile:390x844"]]
    assert any(finding["code"] == "parent_screenshot_coverage" for finding in report.findings)
    memory.close()


def test_visual_refinement_records_parent_screenshot_delta_when_coverage_matches(tmp_path, monkeypatch):
    from site_agent.application import designs as designs_module

    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory)
    parent = service.create_run(_intake(), run_id="visual-parent-delta", base_sha="a" * 40)
    memory.update_design_run(
        parent["run_id"],
        candidate_sha="b" * 40,
        quality_report_json={
            "run_id": parent["run_id"],
            "candidate_sha": "b" * 40,
            "state": "passed",
            "evidence": _browser_screenshot_evidence(("index.html", "desktop", "c" * 64)),
        },
    )
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating", "ready_for_review"):
        memory.transition_design_run(parent["run_id"], status)
    child = service.create_run(
        _intake(),
        run_id="visual-child-delta",
        base_sha="b" * 40,
        parent_run_id=parent["run_id"],
        source_candidate_sha="b" * 40,
        operation_kind="visual_refinement",
    )
    memory.update_design_run(child["run_id"], candidate_sha="e" * 40)
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating"):
        memory.transition_design_run(child["run_id"], status)
    monkeypatch.setattr(
        designs_module,
        "run_quality_gates",
        lambda *args, **kwargs: QualityReport.from_dict({
            "run_id": child["run_id"],
            "candidate_sha": "e" * 40,
            "state": "passed",
            "evidence": _browser_screenshot_evidence(("index.html", "desktop", "f" * 64)),
        }),
    )

    report = service.validate_run(
        child["run_id"],
        tmp_path,
        policy=QualityPolicy(build_command=None, visual_critic=True),
    )

    comparison = report.to_dict()["evidence"]["parent_visual_comparison"]
    assert comparison["status"] == "passed"
    assert comparison["changed"] == [["index.html", "desktop:1440x1000"]]
    stored = service.get_run(child["run_id"])
    assert stored["status"] == "validating"
    assert any(event["stage"] == "visual_review_pending" for event in stored["events"])
    memory.close()


def test_visual_refinement_is_an_independent_child_from_parent_candidate(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory, config={"site": {"clone_path": str(tmp_path / "site")}})
    parent = service.create_run(
        _intake(),
        run_id="design-parent",
        base_sha="a" * 40,
        conversation_id=17,
        intake_session_id="intake-" + "a" * 32,
        intake_revision_id=3,
    )
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": parent["run_id"],
        "mode": "initial_homepage",
        "base_sha": parent["base_sha"],
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Keep the homepage accessible."],
        "content": {
            "design_brief": {
                "required_pages": ["index.html", "articles.html"],
                "content_requirements": ["North Star Studio", "Brand strategy"],
            },
        },
    })
    target = BuildTarget.from_dict({
        "mode": "production_candidate",
        "base_sha": parent["base_sha"],
        "candidate_ref": parent["candidate_ref"],
        "push_mode": "none",
        "publishable": True,
    })
    memory.update_design_run(
        parent["run_id"],
        candidate_sha="b" * 40,
        candidate_ref=parent["candidate_ref"],
        planning_json={"build_request": request.to_dict(), "build_target": target.to_dict()},
    )
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating", "needs_repair"):
        memory.transition_design_run(parent["run_id"], status)
    critique = VisualCritiqueReport.from_dict({
        "run_id": parent["run_id"],
        "candidate_sha": "b" * 40,
        "model_id": "Qwen/Qwen3.8-27B",
        "state": "repair",
        "findings": [{"severity": "high", "category": "hierarchy", "message": "Strengthen the focal point."}],
        "repair_plan": [{"finding": "focal point", "change": "Increase the hero contrast."}],
    })
    memory.update_design_run(
        parent["run_id"],
        quality_report_json={"state": "passed", "visual_critique": critique.to_dict()},
    )

    child = service.create_visual_refinement_run(
        parent["run_id"],
        critique,
        run_id="design-refined",
        locked_plan={"oversized_plan": "x" * 110_000},
    )

    child_run = child["run"]
    assert child_run["parent_run_id"] == parent["run_id"]
    assert child_run["operation_kind"] == "visual_refinement"
    assert child_run["base_sha"] == "b" * 40
    assert child_run["source_candidate_sha"] == "b" * 40
    assert child_run["status"] == "planning"
    assert child_run["conversation_id"] == 17
    assert child_run["intake_session_id"] == "intake-" + "a" * 32
    assert child_run["intake_revision_id"] == 3
    assert child["request"]["run_id"] == "design-refined"
    assert child["request"]["mode"] == "visual_refinement"
    assert child["request"]["base_sha"] == "b" * 40
    assert child["request"]["content"]["visual_critique"]["candidate_sha"] == "b" * 40
    assert child["request"]["content"]["specialist_locked_plan_ref"] == {
        "parent_run_id": parent["run_id"],
        "phase": "creative_selection",
    }
    assert "specialist_locked_plan" not in child["request"]["content"]
    child_policy = service.quality_policy_for_run(child_run["run_id"])
    assert child_policy.required_pages == ("index.html", "articles.html")
    assert child_policy.required_content == ("North Star Studio", "Brand strategy")
    assert child["target"]["operation_kind"] == "visual_refinement"
    with pytest.raises(DesignServiceError, match="already exists"):
        service.create_visual_refinement_run(parent["run_id"], critique, run_id="design-refined-again")
    with pytest.raises(DesignServiceError, match="cannot create another refinement"):
        service.create_visual_refinement_run(child_run["run_id"], critique)
    memory.close()


def test_sighted_self_review_creates_bound_refinement_child(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory, config={"site": {"clone_path": str(tmp_path / "site")}})
    parent = service.create_run(_intake(), run_id="design-parent", base_sha="a" * 40)
    parent_sha = "b" * 40
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": parent["run_id"],
        "mode": "initial_homepage",
        "base_sha": parent["base_sha"],
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Keep the homepage accessible."],
        "content": {"design_brief": {"required_pages": ["index.html"], "content_requirements": ["North Star Studio"]}},
    })
    target = BuildTarget.from_dict({
        "mode": "production_candidate",
        "base_sha": parent["base_sha"],
        "candidate_ref": parent["candidate_ref"],
        "push_mode": "none",
        "publishable": True,
    })
    memory.update_design_run(
        parent["run_id"],
        candidate_sha=parent_sha,
        candidate_ref=parent["candidate_ref"],
        planning_json={"build_request": request.to_dict(), "build_target": target.to_dict()},
    )
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating"):
        memory.transition_design_run(parent["run_id"], status)
    memory.update_design_run(parent["run_id"], quality_report_json={
        "state": "passed",
        "evidence": {"browser": {"viewports": [{
            "viewport": {"name": "desktop", "width": 1440},
            "result": {"routes": [{
                "route": "index.html",
                "screenshot_hash": "h" * 64,
                "screenshot_path": "/tmp/render.png",
            }]},
        }]}},
    })

    created = service.create_sighted_refinement_run(parent["run_id"])

    assert created["request"]["run_id"] == created["run"]["run_id"]
    assert created["run"]["operation_kind"] == "visual_refinement"
    assert created["run"]["source_candidate_sha"] == parent_sha
    assert created["request"]["mode"] == "visual_refinement"
    critique = created["request"]["content"]["visual_critique"]
    assert critique["model_id"] == "sighted-self-review"
    assert critique["state"] == "repair"
    assert critique["candidate_sha"] == parent_sha
    assert critique["screenshot_evidence"][0]["screenshot_path"] == "/tmp/render.png"
    again = service.create_sighted_refinement_run(parent["run_id"])
    assert again["run"]["run_id"] == created["run"]["run_id"]
    child_again = service.create_sighted_refinement_run(created["run"]["run_id"])
    assert child_again["reason"] == "already_refined"
    assert child_again["run"] is None
    with pytest.raises(DesignServiceError, match="cannot create another refinement"):
        service.create_visual_refinement_run(created["run"]["run_id"], VisualCritiqueReport.from_dict(critique))
    memory.close()


def test_sighted_self_review_guards_non_refinable_states(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory)
    parent = service.create_run(_intake(), run_id="design-parent", base_sha="a" * 40)

    result = service.create_sighted_refinement_run(parent["run_id"])
    assert result["reason"] == "not_awaiting_self_review"

    memory.update_design_run(
        parent["run_id"],
        candidate_sha="b" * 40,
        candidate_ref=parent["candidate_ref"],
    )
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating"):
        memory.transition_design_run(parent["run_id"], status)
    memory.update_design_run(parent["run_id"], quality_report_json={"state": "failed"})
    result = service.create_sighted_refinement_run(parent["run_id"])
    assert result["reason"] == "deterministic_gates_not_passed"
    memory.close()


def test_derived_page_run_pins_approved_manifest_source(tmp_path):
    memory = Memory(tmp_path / "service.db")
    service = DesignService(memory)
    intake = _intake()
    source = service.create_run(intake, run_id="homepage", base_sha="a" * 40)
    manifest = DesignManifest.from_dict({
        "schema_version": 1,
        "source_homepage_path": "index.html",
        "design_direction_id": "quiet-tide",
        "intake_hash": intake.content_hash,
        "tokens": {"accent": "#087f99"},
        "shared_regions": ["header", "footer"],
        "allowed_variation_points": ["hero-composition"],
    })
    memory.update_design_run(
        source["run_id"],
        candidate_sha="c" * 40,
        candidate_ref="refs/ada-design/homepage",
        design_manifest_path="design/ada-design-manifest.json",
        design_manifest_json=manifest.to_dict(),
        design_manifest_hash=manifest.content_hash,
        quality_report_json={"run_id": "homepage", "candidate_sha": "c" * 40, "state": "passed"},
    )
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating", "ready_for_review"):
        memory.transition_design_run(source["run_id"], status)
    draft_id = memory.save_draft(
        "Design candidate",
        "approved candidate",
        kind="design",
        meta={"run_id": "homepage", "candidate_sha": "c" * 40, "base_sha": "a" * 40},
    )
    assert memory.update_draft_status(draft_id, "approved")
    memory.update_design_run(source["run_id"], draft_id=draft_id)
    page = PageIntake.from_dict({
        "schema_version": 1,
        "page_id": "about",
        "desired_url": "about.html",
        "purpose": "Explain the studio.",
        "primary_audience_intent": "Understand the studio's approach.",
        "primary_action": "Start a conversation",
        "required_facts": ["The studio works independently."],
        "navigation_relationship": "Linked from the primary navigation.",
    })

    result = service.create_derived_page_run("homepage", page, run_id="about-run")

    assert result["request"]["mode"] == "derived_page"
    assert result["request"]["base_sha"] == "c" * 40
    assert result["request"]["design_source"]["candidate_sha"] == "c" * 40
    assert result["request"]["design_source"]["manifest_hash"] == manifest.content_hash
    assert result["request"]["allowed_variation_points"] == ["hero-composition"]
    memory.close()
