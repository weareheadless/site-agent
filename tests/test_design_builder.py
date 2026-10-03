import json
import hashlib
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from site_agent.core.design_contracts import BuildTarget, DesignContextSnapshot, ExperiencePlanBundle, PageBuildRequest
from site_agent.core.memory import Memory
from site_agent.hands import opencode_runner as runner
from site_agent.hands.builder import BuilderError, OperationRoutingBuilder
from site_agent.hands.site_build import NEXT_REACT_PROFILE, SiteBuildResult
from tests.test_design_contracts import _experience_plan


def test_stage_visual_evidence_writes_downscaled_jpgs_under_opencode(tmp_path):
    source_dir = tmp_path / "media"
    source_dir.mkdir()
    big = source_dir / "logo.png"
    Image.new("RGB", (2200, 900), "red").save(big)
    clone = tmp_path / "worktree"
    clone.mkdir()

    staged = runner._stage_visual_evidence(clone, [str(big)], prefix="media", limit=4)
    assert len(staged) == 1
    target = clone / staged[0]
    assert target.is_file()
    assert ".opencode" in target.parts and "evidence" in target.parts
    with Image.open(target) as image:
        assert max(image.size) <= 1280
    assert staged[0] == ".opencode/evidence/media-00.jpg"

    staged_dedup = runner._stage_visual_evidence(clone, [str(big), str(big)], prefix="media")
    assert len(staged_dedup) == 1

    missing = runner._stage_visual_evidence(clone, [str(tmp_path / "nope.png")], prefix="media")
    assert missing == []


def test_configured_fonts_are_materialized_and_byte_locked(tmp_path):
    source = tmp_path / "owner-font.woff2"
    data = b"wOF2-owner-font-bytes"
    source.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    clone = tmp_path / "worktree"
    clone.mkdir()
    config = {
        "design_engine": {
            "fonts": [{
                "source_path": str(source),
                "destination": "public/fonts/owner.woff2",
                "sha256": digest,
                "family": "Owner Sans",
            }],
        },
    }

    paths = runner._materialize_fonts(config, clone)

    assert paths == ["public/fonts/owner.woff2"]
    assert (clone / paths[0]).read_bytes() == data
    runner._verify_materialized_fonts(config, clone, paths)
    (clone / paths[0]).write_bytes(b"wOF2-replaced")
    try:
        runner._verify_materialized_fonts(config, clone, paths)
    except runner.RunnerError as exc:
        assert "owner-provided font" in str(exc)
    else:
        raise AssertionError("changed host-provisioned font bytes were accepted")


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def _clone(tmp_path):
    clone = tmp_path / "experiment-clone"
    clone.mkdir()
    _git(clone, "init", "-q", "-b", "main")
    _git(clone, "config", "user.email", "test@example.com")
    _git(clone, "config", "user.name", "Test")
    (clone / "index.html").write_text("<html><body><h1>Baseline</h1></body></html>")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "baseline")
    base_sha = _git(clone, "rev-parse", "HEAD").stdout.strip()
    return clone, base_sha


def test_primary_implementation_local_self_check_returns_host_build_evidence(tmp_path, monkeypatch):
    observed = {}

    def fake_build(root, profile, *, npm_cache, env, timeout_seconds):
        observed.update({
            "root": root,
            "profile": profile.name,
            "npm_cache": npm_cache,
            "timeout_seconds": timeout_seconds,
        })
        return SiteBuildResult(
            profile=profile.name,
            ok=True,
            output_dir=profile.output_dir,
            commands=({"command": ["test"], "status": "passed"},),
            route_inventory=("index.html",),
        )

    monkeypatch.setattr("site_agent.hands.site_build.build_site", fake_build)
    report = runner._run_local_design_self_check(
        {
            "design_engine": {
                "build_profile": "next_react",
                "quality": {"build_timeout_seconds": 37},
            },
            "builder": {"provider_timeout_seconds": 900},
            "env": {"llm_api_key": "OPENROUTER_API_KEY"},
        },
        {"env": {}},
        tmp_path,
        tmp_path / "npm-cache",
    )

    assert report["ok"] is True
    assert report["route_inventory"] == ["index.html"]
    assert observed == {
        "root": tmp_path,
        "profile": "next_react",
        "npm_cache": tmp_path / "npm-cache",
        "timeout_seconds": 37,
    }


def test_primary_implementation_local_self_check_rejects_failed_build(tmp_path, monkeypatch):
    def fake_build(root, profile, **kwargs):
        return SiteBuildResult(
            profile=profile.name,
            ok=False,
            output_dir=profile.output_dir,
            commands=({"command": ["test"], "status": "failed", "stderr": "compiler exploded"},),
        )

    monkeypatch.setattr("site_agent.hands.site_build.build_site", fake_build)

    with pytest.raises(runner.RunnerError, match="mandatory local design self-check failed.*compiler exploded"):
        runner._run_local_design_self_check(
            {"design_engine": {"build_profile": "next_react"}},
            {"env": {}},
            tmp_path,
            tmp_path / "npm-cache",
        )


def test_native_next_finalization_accepts_the_host_approved_package_manifest(tmp_path):
    clone, _ = _clone(tmp_path)
    (clone / "package.json").write_text('{"name":"baseline"}\n')
    _git(clone, "add", "package.json")
    _git(clone, "commit", "-qm", "toolchain baseline")
    base_sha = _git(clone, "rev-parse", "HEAD").stdout.strip()

    (clone / "package.json").write_text('{"name":"candidate"}\n')
    source = clone / "src" / "components" / "site"
    source.mkdir(parents=True)
    (source / "homepage.tsx").write_text("export function HomepageContent() { return <h1>Candidate</h1> }\n")

    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "design-run-package-json",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/design-run-package-json",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": list(NEXT_REACT_PROFILE.writable_patterns),
        "build_profile": "next_react",
    })
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone)},
        "design_engine": {"quality": {}},
    }

    receipt = runner.finalize_design_target(
        {"config": config, "memory": memory},
        clone,
        clone,
        target,
        base_sha,
        request,
        session_id="design-session",
        transcript_path="design-runs/design-run-package-json/opencode.jsonl",
        host_provisioned_paths={"package.json"},
    )

    assert receipt.candidate_sha != base_sha
    assert _git(clone, "rev-parse", target.candidate_ref).stdout.strip() == receipt.candidate_sha
    memory.close()


def test_local_design_build_commits_exact_base_to_local_ref_without_push(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "builder": {"enabled": True, "validation_repair_attempts": 0},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "design-run-1",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/design-run-1",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
    })
    pushes = []

    def fake_turn(worktree, prompt, config, progress=None, session_id=None, timeout_seconds=None, **kwargs):
        assert base_sha in prompt
        (worktree / "index.html").write_text("<html><body><h1>Candidate</h1></body></html>")
        return {
            "session_id": "design-session",
            "reply": "implemented",
            "transcript": '{"type":"text","sessionID":"design-session"}\n',
        }

    original_git = runner._git

    def tracking_git(repo, *args, **kwargs):
        if args and args[0] == "push":
            pushes.append(args)
        return original_git(repo, *args, **kwargs)

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)
    monkeypatch.setattr(runner, "_git", tracking_git)

    receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)

    assert receipt.candidate_sha != base_sha
    assert _git(clone, "rev-parse", target.candidate_ref).stdout.strip() == receipt.candidate_sha
    assert _git(clone, "rev-parse", f"{receipt.candidate_sha}^").stdout.strip() == base_sha
    assert pushes == []
    assert _git(clone, "status", "--porcelain").stdout == ""
    manifest = json.loads(_git(clone, "show", f"{receipt.candidate_sha}:design/ada-design-manifest.json").stdout)
    assert manifest["host_generated"] is True
    assert manifest["source_files"] == {"changed": ["index.html"]}
    assert receipt.transcript_path == "design-runs/design-run-1/opencode.jsonl"
    assert (tmp_path / "data" / receipt.transcript_path).read_text() == '{"type":"text","sessionID":"design-session"}\n'
    memory.close()


def test_native_initial_build_persists_direction_before_writable_build(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "design_engine": {"orchestration": "native"},
        "builder": {"enabled": True},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "native-direction-build",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/native-direction-build",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
    })
    calls = []

    monkeypatch.setattr(runner, "install_agent_files", lambda *args, **kwargs: None)

    def fake_turn(worktree, prompt, config, **kwargs):
        calls.append({"agent_name": kwargs.get("agent_name"), "prompt": prompt})
        if kwargs.get("agent_name") == "native-direction":
            return {
                "session_id": "direction-session",
                "reply": "A quiet editorial threshold opens into a tactile story of the owner’s work.",
                "transcript": '{"type":"text","sessionID":"direction-session"}\n',
            }
        (worktree / "index.html").write_text("<html><body><h1>Candidate</h1></body></html>")
        return {
            "session_id": "build-session",
            "reply": "implemented",
            "transcript": '{"type":"text","sessionID":"build-session"}\n',
        }

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)

    assert [call["agent_name"] for call in calls] == ["native-direction", "build"]
    assert "A quiet editorial threshold" in calls[1]["prompt"]
    assert receipt.direction_path == "design-runs/native-direction-build/direction.md"
    assert receipt.direction_transcript_path == "design-runs/native-direction-build/direction-opencode.jsonl"
    direction_file = tmp_path / "data" / receipt.direction_path
    assert direction_file.read_text() == "A quiet editorial threshold opens into a tactile story of the owner’s work.\n"
    assert (tmp_path / "data" / receipt.direction_transcript_path).is_file()
    memory.close()


def test_creative_technical_repair_skips_new_direction_turn(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "design_engine": {"orchestration": "creative"},
        "builder": {"enabled": True},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "technical-repair-no-direction",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Repair the retained candidate.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Preserve the native implementation."],
        "content": {"technical_repair": {"parent_run_id": "parent"}},
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/technical-repair-no-direction",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
        "operation_kind": "technical_repair",
    })
    calls = []

    monkeypatch.setattr(runner, "install_agent_files", lambda *args, **kwargs: None)

    def fake_turn(worktree, prompt, config, **kwargs):
        calls.append({"agent_name": kwargs.get("agent_name"), "prompt": prompt})
        (worktree / "index.html").write_text("<html><body><h1>Candidate</h1></body></html>")
        return {
            "session_id": "repair-session",
            "reply": "implemented",
            "transcript": '{"type":"text","sessionID":"repair-session"}\n',
        }

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    runner.stage_design_build({"config": config, "memory": memory}, request, target)

    assert [call["agent_name"] for call in calls] == ["build"]
    assert "RETAINED IMPLEMENTATION PRESERVATION CONTRACT" in calls[0]["prompt"]
    memory.close()


def test_creative_direction_prompt_requires_typed_journey_shape(tmp_path):
    clone, base_sha = _clone(tmp_path)
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "creative-direction-contract",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/creative-direction-contract",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
    })

    prompt = runner._native_direction_prompt(request, target, require_experience_plan=True)

    assert "experience_journey must be a JSON object" in prompt
    assert "at least two objects" in prompt
    assert "never force a fixed scene count" in prompt
    assert "exactly two objects" not in prompt
    assert "Use id, not scene_id" in prompt
    assert "behavior_system must be an object" in prompt
    assert "asset_evidence may be an empty array" in prompt
    assert "at most three records" in prompt
    assert "top-level transfer_test field is mandatory" in prompt


def test_creative_direction_rejects_an_incomplete_visible_copy_deck(tmp_path):
    clone, base_sha = _clone(tmp_path)
    snapshot = DesignContextSnapshot.from_dict({
        "schema_version": 1,
        "captured_at": "2026-09-15T12:00:00+00:00",
        "owner_request": "Create the homepage.",
        "base_sha": base_sha,
        "site_facts": {"business": {"name": "North Star Studio"}},
        "asset_inventory": [],
        "asset_visual_evidence": [],
        "execution_profile": {},
    })
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "creative-copy-contract",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "b" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
        "context_snapshot": snapshot.to_dict(),
        "context_snapshot_hash": snapshot.content_hash,
    })
    raw_plan = _experience_plan(
        run_id=request.run_id,
        base_sha=base_sha,
        context_snapshot_hash=snapshot.content_hash,
        asset_evidence=[],
        asset_composition_plan=[],
        copy_deck={"headline": "A real headline"},
    )

    with pytest.raises(runner.RunnerError, match="copy_deck.body"):
        runner._native_direction_payload(
            {
                "reply": json.dumps({
                    "direction": "A clear threshold into the work.",
                    "experience_plan": raw_plan,
                }),
            },
            request,
            require_experience_plan=True,
        )


def test_native_direction_agent_is_primary_but_read_only(tmp_path):
    oc = tmp_path / ".opencode"

    runner._write_native_direction_agent(oc)

    definition = (oc / "agent" / "native-direction.md").read_text()
    assert "mode: primary" in definition
    assert "task: deny" in definition
    assert "edit: deny" in definition
    assert "write: deny" in definition
    assert "bash: deny" in definition


def test_native_direction_discards_subagent_warning_and_uses_final_text_event(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "design_engine": {"orchestration": "native"},
        "builder": {"enabled": True},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "native-direction-warning",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/native-direction-warning",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
    })
    direction = "# Direction\n\n" + ("Use a slow, high-contrast descent into the experience." * 8)
    warning = '!  agent "native-direction" is a subagent, not a primary agent. Falling back to default agent'

    monkeypatch.setattr(runner, "install_agent_files", lambda *args, **kwargs: None)

    def fake_turn(worktree, prompt, config, **kwargs):
        if kwargs.get("agent_name") == "native-direction":
            return {
                "reply": warning,
                "raw_tail": [warning],
                "transcript": json.dumps({"type": "text", "part": {"type": "text", "text": direction}}) + "\n",
            }
        (worktree / "index.html").write_text("<html><body><h1>Candidate</h1></body></html>")
        return {
            "session_id": "build-session",
            "reply": "implemented",
            "transcript": '{"type":"text"}\n',
        }

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)

    persisted = (tmp_path / "data" / receipt.direction_path).read_text()
    assert persisted == direction + "\n"
    assert warning not in persisted
    memory.close()


def test_creative_build_turn_receives_a_compact_hash_bound_experience_plan(
    tmp_path, monkeypatch
):
    clone, base_sha = _clone(tmp_path)
    memory = Memory(tmp_path / "data" / "memory.db")
    snapshot = DesignContextSnapshot.from_dict({
        "schema_version": 1,
        "captured_at": "2026-09-15T12:00:00+00:00",
        "owner_request": "Create the homepage.",
        "base_sha": base_sha,
        "site_facts": {"business": {"name": "North Star Studio"}},
        "asset_inventory": [],
        "asset_visual_evidence": [],
        "execution_profile": {},
    })
    raw_plan = _experience_plan(
        run_id="creative-direction-freeform",
        base_sha=base_sha,
        context_snapshot_hash=snapshot.content_hash,
        asset_evidence=[],
        asset_composition_plan=[],
    )
    memory.create_design_run(
        run_id="creative-direction-freeform",
        mode="local_experiment",
        intake_json={"schema_version": 1},
        intake_hash="b" * 64,
        base_sha=base_sha,
        candidate_ref="refs/ada-design-lab/creative-direction-freeform",
    )
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "design_engine": {"orchestration": "creative"},
        "builder": {"enabled": True},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "creative-direction-freeform",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "b" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
        "supplied_media_asset_ids": [1],
        "context_snapshot": snapshot.to_dict(),
        "context_snapshot_hash": snapshot.content_hash,
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/creative-direction-freeform",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
    })
    calls = []
    phase_calls = []

    def fake_materialize_media(_context, worktree):
        image_path = worktree / "public" / "images" / "owner.webp"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (900, 600), "#334455").save(image_path, format="WEBP")
        return ["public/images/owner.webp"]

    monkeypatch.setattr(runner, "_typed_execution_config", lambda config, request, target: config)
    monkeypatch.setattr(runner, "install_agent_files", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_materialize_media", fake_materialize_media)
    monkeypatch.setattr(runner, "_verify_materialized_media", lambda *args, **kwargs: None)
    from site_agent.application.design_orchestration import SpecialistDesignCoordinator

    monkeypatch.setattr(
        SpecialistDesignCoordinator,
        "record_implementation_phase",
        lambda self, request, target, *, plan, provider_result: phase_calls.append("implementation"),
    )
    monkeypatch.setattr(
        SpecialistDesignCoordinator,
        "run_experience_fidelity_phase",
        lambda self, request, target, *, plan, workspace, progress, image_files, **kwargs: (
            phase_calls.append("experience_fidelity")
            or SimpleNamespace(to_dict=lambda: {"state": "complete"})
        ),
    )
    monkeypatch.setattr(runner, "_journey_source_coverage", lambda *args, **kwargs: {})
    monkeypatch.setattr(runner, "_run_local_design_self_check", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(runner, "_provision_referenced_frontend_libraries", lambda *args, **kwargs: ())

    def fake_turn(worktree, prompt, config, **kwargs):
        calls.append({
            "agent_name": kwargs.get("agent_name"),
            "prompt": prompt,
            "image_files": tuple(kwargs.get("image_files") or ()),
        })
        if kwargs.get("agent_name") == "native-direction":
            direction = "A quiet threshold opens into a tactile story of the owner's work."
            text = json.dumps({"direction": direction, "experience_plan": raw_plan})
            return {
                "session_id": "direction-session",
                "reply": text,
                "transcript": json.dumps({"type": "text", "text": text}) + "\n",
            }
        (worktree / "index.html").write_text("<html><body><h1>Candidate</h1></body></html>")
        return {
            "session_id": "build-session",
            "reply": "implemented",
            "transcript": '{"type":"text","text":"implemented"}\n',
        }

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)

    assert [call["agent_name"] for call in calls] == ["native-direction", "build"]
    assert calls[0]["image_files"]
    assert calls[0]["image_files"] == calls[1]["image_files"]
    assert "public/images/owner.webp" in calls[0]["image_files"]
    assert "Return exactly one JSON object" in calls[0]["prompt"]
    assert "brand_source_map" in calls[0]["prompt"]
    assert "asset_composition_plan" in calls[0]["prompt"]
    assert "final visitor-facing homepage copy" in calls[0]["prompt"]
    assert "do not enumerate node_modules" in calls[0]["prompt"]
    assert "top-level transfer_test field is mandatory" in calls[0]["prompt"]
    assert "never pass useGSAP to gsap.registerPlugin" in calls[1]["prompt"]
    assert "signature marker is a runtime contract, not metadata" in calls[1]["prompt"]
    assert "one-shot entrance that has settled" in calls[1]["prompt"]
    assert "first visible heading, offer, and primary action never sit beneath it" in calls[1]["prompt"]
    assert "a static document wrapper such as main is not evidence" in calls[1]["prompt"]
    assert "A quiet threshold opens" in calls[1]["prompt"]
    assert "LOCKED CREATIVE PLAN" in calls[1]["prompt"]
    assert phase_calls == ["implementation", "experience_fidelity"]
    assert receipt.experience_plan["run_id"] == request.run_id
    assert receipt.experience_plan["base_sha"] == base_sha
    assert receipt.direction_path == "design-runs/creative-direction-freeform/direction.md"
    persisted = memory.get_design_run(request.run_id)
    assert persisted["planning_json"]["integrated_composition"]["state"] == "planned"
    assert persisted["planning_json"]["experience_plan_hash"] == ExperiencePlanBundle.from_dict(receipt.experience_plan).content_hash
    assert any(
        event["stage"] == "integrated_composition"
        for event in memory.list_design_run_events(request.run_id)
    )
    memory.close()


def test_initial_homepage_preserves_existing_source_for_model_inspection(tmp_path, monkeypatch):
    clone, _ = _clone(tmp_path)
    (clone / "styles.css").write_text("body { color: red; }")
    (clone / "app.js").write_text("document.body.dataset.source = 'old';")
    _git(clone, "add", "styles.css", "app.js")
    _git(clone, "commit", "-qm", "homepage entrypoints")
    base_sha = _git(clone, "rev-parse", "HEAD").stdout.strip()
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "*.css", "*.js", "design/**"]},
        "builder": {"enabled": True},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "blank-homepage-source",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/blank-homepage-source",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "*.css", "*.js", "design/**"],
    })
    observed = {}

    monkeypatch.setattr(runner, "install_agent_files", lambda *args, **kwargs: None)

    def fake_turn(worktree, prompt, config, **kwargs):
        observed["old_files_present"] = any((worktree / name).exists() for name in ("index.html", "styles.css", "app.js"))
        (worktree / "index.html").write_text("<html><body><h1>New</h1></body></html>")
        (worktree / "styles.css").write_text("body { color: blue; }")
        (worktree / "app.js").write_text("document.body.dataset.source = 'new';")
        return {"session_id": "blank-session", "reply": "implemented"}

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)

    assert observed["old_files_present"] is True
    assert receipt.candidate_sha != base_sha
    assert _git(clone, "status", "--porcelain").stdout == ""
    memory.close()


def test_design_manifest_omits_deleted_implementation_files(tmp_path, monkeypatch):
    clone, _ = _clone(tmp_path)
    for name in ("styles.css", "app.js"):
        (clone / name).write_text("old")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "homepage entrypoints")
    base_sha = _git(clone, "rev-parse", "HEAD").stdout.strip()
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "*.css", "*.js", "design/**"]},
        "builder": {"enabled": True},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "deleted-entrypoints",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/deleted-entrypoints",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "*.css", "*.js", "design/**"],
    })

    monkeypatch.setattr(runner, "install_agent_files", lambda *args, **kwargs: None)

    def fake_turn(worktree, prompt, config, **kwargs):
        (worktree / "index.html").write_text("<html><body><h1>New</h1></body></html>")
        return {"session_id": "deleted-session", "reply": "implemented"}

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)

    manifest = json.loads(_git(clone, "show", f"{receipt.candidate_sha}:design/ada-design-manifest.json").stdout)
    assert manifest["source_files"] == {"changed": ["index.html"]}
    memory.close()


def test_typed_build_uses_the_configured_provider_credential(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "design_engine": {
            "provider": "entrim",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "base_url": "https://api.entrim.ai/v1",
            "api_key_env": "VISION_KEY",
            "quality": {"browser": False, "visual_critic": False},
        },
        "env": {"llm_api_key": "IMPLEMENTATION_KEY", "vision_api_key": "VISION_KEY"},
        "builder": {"enabled": True},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "configured-provider-key",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/configured-provider-key",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
    })
    installed = {}
    called = {}

    def fake_install(*args, **kwargs):
        installed["key"] = args[3]
        installed["key_env"] = kwargs["provider_env_name"]

    def fake_turn(worktree, prompt, config, **kwargs):
        called.update(kwargs)
        (worktree / "index.html").write_text("<html><body><h1>Candidate</h1></body></html>")
        return {"session_id": "provider-key-session", "reply": "implemented"}

    monkeypatch.setattr(runner, "install_agent_files", fake_install)
    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    runner.stage_design_build(
        {"config": config, "memory": memory, "env": {"IMPLEMENTATION_KEY": "implementation-secret", "VISION_KEY": "vision-secret"}},
        request,
        target,
    )

    assert installed == {"key": "vision-secret", "key_env": "VISION_KEY"}
    assert called["api_key"] == "vision-secret"
    assert called["api_key_env"] == "VISION_KEY"
    memory.close()


def test_noop_design_turn_fails_without_hidden_continuation(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "builder": {"enabled": True, "validation_repair_attempts": 0},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "design-nudge-1",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/design-nudge-1",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
    })
    turns = []

    def fake_turn(worktree, prompt, config, progress=None, session_id=None, timeout_seconds=None, **kwargs):
        turns.append((prompt, session_id))
        return {"session_id": "design-session", "reply": "planned"}

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    import pytest

    with pytest.raises(runner.RunnerError, match="without implementation changes"):
        runner.stage_design_build({"config": config, "memory": memory}, request, target)

    assert len(turns) == 1
    assert (tmp_path / "data" / "design-runs" / "design-nudge-1" / "opencode.jsonl").is_file()
    memory.close()


def test_failed_opencode_turn_can_retain_a_safe_partial_candidate(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "builder": {"enabled": True},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "partial-design",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/partial-design",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
    })

    def failed_turn(worktree, prompt, config, **kwargs):
        (worktree / "index.html").write_text("<html><body><h1>Partial</h1></body></html>")
        raise runner.RunnerError(
            "opencode exited 1: provider stopped",
            result={"session_id": "partial-session", "reply": "partial", "transcript": "partial event\n"},
        )

    monkeypatch.setattr(runner, "run_opencode_turn", failed_turn)

    receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)

    assert receipt.build_error == "opencode exited 1: provider stopped"
    assert receipt.candidate_sha != base_sha
    assert _git(clone, "rev-parse", target.candidate_ref).stdout.strip() == receipt.candidate_sha
    assert (tmp_path / "data" / receipt.transcript_path).read_text() == "partial event\n"
    assert _git(clone, "status", "--porcelain").stdout == ""
    memory.close()


def test_specialist_timeout_after_source_authoring_runs_host_gates_before_finalizing(
    tmp_path, monkeypatch
):
    clone, base_sha = _clone(tmp_path)
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "builder": {"enabled": True},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "specialist-timeout-recovery",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/specialist-timeout-recovery",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
    })
    plan = {"experience_journey": {"scenes": [{"id": "arrival"}]}}
    calls = []

    class FidelityReport:
        def to_dict(self):
            return {"status": "passed"}

    class FakeCoordinator:
        def __init__(self, context):
            calls.append(("coordinator", context))

        def record_implementation_phase(self, request, target, *, plan, provider_result):
            calls.append(("implementation", provider_result))

        def run_experience_fidelity_phase(self, request, target, *, plan, workspace, progress, image_files):
            calls.append(("fidelity", plan))
            return FidelityReport()

    def failed_turn(worktree, prompt, config, **kwargs):
        (worktree / "index.html").write_text("<html><body><h1>Candidate</h1></body></html>")
        raise runner.RunnerError(
            "opencode timed out after 1800s",
            result={"session_id": "specialist-session", "reply": "implemented", "transcript": "timeout\n"},
        )

    monkeypatch.setattr("site_agent.application.design_orchestration.SpecialistDesignCoordinator", FakeCoordinator)
    monkeypatch.setattr(runner, "_journey_source_coverage", lambda *args, **kwargs: {})
    monkeypatch.setattr(runner, "_run_local_design_self_check", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(runner, "_provision_referenced_frontend_libraries", lambda *args, **kwargs: ())
    monkeypatch.setattr(runner, "run_opencode_turn", failed_turn)

    receipt = runner.stage_design_build(
        {"config": config, "memory": memory}, request, target, design_plan=plan
    )

    assert receipt.build_error == ""
    assert [item[0] for item in calls] == ["coordinator", "implementation", "fidelity"]
    assert calls[1][1]["provider_turn_error"] == "opencode timed out after 1800s"
    assert _git(clone, "rev-parse", target.candidate_ref).stdout.strip() == receipt.candidate_sha
    assert _git(clone, "status", "--porcelain").stdout == ""
    memory.close()


def test_creative_host_repair_timeout_runs_plan_closure_before_finalizing(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "builder": {"enabled": True},
        "design_engine": {"orchestration": "creative"},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "creative-host-timeout-recovery",
        "mode": "visual_refinement",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Repair the retained candidate.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Preserve the locked experience."],
        "content": {
            "specialist_locked_plan": _experience_plan(
                run_id="creative-host-timeout-recovery",
                base_sha=base_sha,
                context_snapshot_hash="c" * 64,
            ),
            "specialist_repair_brief": {"source": "host_deterministic_evidence"},
        },
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/creative-host-timeout-recovery",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
        "operation_kind": "visual_refinement",
    })
    calls = []

    class FidelityReport:
        def to_dict(self):
            return {"status": "passed"}

    class FakeCoordinator:
        def __init__(self, context):
            calls.append(("coordinator", context))

        def run_experience_fidelity_phase(self, request, target, *, plan, workspace, progress, image_files):
            calls.append(("fidelity", plan))
            return FidelityReport()

    def failed_turn(worktree, prompt, config, **kwargs):
        (worktree / "index.html").write_text("<html><body><h1>Repaired</h1></body></html>")
        raise runner.RunnerError(
            "opencode timed out after 900s",
            result={"session_id": "creative-host-session", "reply": "implemented", "transcript": "timeout\n"},
        )

    monkeypatch.setattr("site_agent.application.design_orchestration.SpecialistDesignCoordinator", FakeCoordinator)
    monkeypatch.setattr(runner, "_run_local_design_self_check", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(runner, "_provision_referenced_frontend_libraries", lambda *args, **kwargs: ())
    monkeypatch.setattr(runner, "run_opencode_turn", failed_turn)

    receipt = runner.stage_design_build(
        {"config": config, "memory": memory},
        request,
        target,
        design_plan=request.content["specialist_locked_plan"],
        repair_brief={"source": "host_deterministic_evidence"},
    )

    assert receipt.build_error == ""
    assert [item[0] for item in calls] == ["coordinator", "fidelity"]
    assert isinstance(calls[1][1], ExperiencePlanBundle)
    assert _git(clone, "rev-parse", target.candidate_ref).stdout.strip() == receipt.candidate_sha
    assert _git(clone, "status", "--porcelain").stdout == ""
    memory.close()


def test_initial_design_setup_excludes_site_context_but_keeps_capability_allowances(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    snapshot = DesignContextSnapshot.from_dict({
        "schema_version": 1,
        "captured_at": "2026-08-31T12:00:00+00:00",
        "owner_request": "Create an independent homepage.",
        "base_sha": base_sha,
        "effective_persona": "MUST NOT REACH INITIAL BUILDER",
        "site_digest": "SITE DIGEST MUST NOT REACH INITIAL BUILDER",
        "measured_design": {"tokens": "MEASURED DESIGN MUST NOT REACH INITIAL BUILDER"},
        "capabilities": [{"name": "gsap", "version": "3.12.5"}],
    })
    memory = object()
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone)},
        "builder": {"model": "deepseek/deepseek-v4-flash-0731"},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "initial-context-boundary",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Use the intake as the creative brief."],
        "content": {"site_intake": {"schema_version": 1}},
        "context_snapshot": snapshot.to_dict(),
        "context_snapshot_hash": snapshot.content_hash,
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/initial-context-boundary",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["index.html", "design/**"],
    })
    installed = {}

    def fake_install(*args, **kwargs):
        installed.update(kwargs)

    def fake_turn(worktree, prompt, config, **kwargs):
        (worktree / "index.html").write_text("<html><body><h1>Independent</h1></body></html>")
        return {"session_id": "design-session", "reply": "implemented"}

    monkeypatch.setattr(runner, "_typed_execution_config", lambda config, request, target: config)
    monkeypatch.setattr(runner, "install_agent_files", fake_install)
    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    runner.stage_design_build({"config": config, "memory": memory, "env": {}}, request, target)

    assert installed["context_snapshot"] is None
    assert installed["context_snapshot_hash"] == ""
    assert installed["persona"] == ""
    assert installed["site_digest"] == ""
    assert installed["template_tokens"] == ""
    assert installed["memory"] is None
    assert installed["approved_capabilities"] == snapshot.capabilities


def test_visual_refinement_setup_uses_parent_source_and_frozen_persona(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    snapshot = DesignContextSnapshot.from_dict({
        "schema_version": 1,
        "captured_at": "2026-08-31T12:00:00+00:00",
        "owner_request": "Refine the retained candidate.",
        "base_sha": base_sha,
        "effective_persona": "PARENT_PERSONA",
        "capabilities": [{"name": "gsap", "version": "3.12.5"}],
    })
    memory = object()
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone)},
        "builder": {"model": "deepseek/deepseek-v4-flash-0731"},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "visual-refinement-source",
        "mode": "visual_refinement",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Repair the retained candidate.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Preserve unaffected content."],
        "content": {"visual_refinement": {"parent_run_id": "parent", "finding": "Fix wrapping."}},
        "context_snapshot": snapshot.to_dict(),
        "context_snapshot_hash": snapshot.content_hash,
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/visual-refinement-source",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["index.html", "design/**"],
        "operation_kind": "visual_refinement",
    })
    installed = {}

    def fake_install(*args, **kwargs):
        installed.update(kwargs)

    class FakeCoordinator:
        def __init__(self, context):
            self.context = context

        def record_repair_phase(self, request, target, *, repair_brief, provider_result):
            return None

    def fake_turn(worktree, prompt, config, **kwargs):
        assert "visual refinement of the parent candidate" in prompt
        assert "Do not redesign the site from scratch" in prompt
        assert kwargs["agent_name"] == "repair-implementer"
        assert (worktree / ".opencode/agent/repair-implementer.md").is_file()
        (worktree / "index.html").write_text("<html><body><h1>Refined</h1></body></html>")
        return {"session_id": "design-session", "reply": "implemented"}

    monkeypatch.setattr(runner, "_typed_execution_config", lambda config, request, target: config)
    monkeypatch.setattr(runner, "_site_digest", lambda *args, **kwargs: "PARENT DIGEST")
    monkeypatch.setattr(runner, "_template_tokens", lambda *args, **kwargs: "PARENT TOKENS")
    monkeypatch.setattr(runner, "install_agent_files", fake_install)
    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)
    monkeypatch.setattr("site_agent.application.design_orchestration.SpecialistDesignCoordinator", FakeCoordinator)

    runner.stage_design_build(
        {"config": config, "memory": memory, "env": {}},
        request,
        target,
        repair_brief={"failed_findings": [{"code": "journey_scene_order_unobserved"}]},
    )

    assert installed["persona"] == "PARENT_PERSONA"
    assert installed["site_digest"] == "PARENT DIGEST"
    assert installed["template_tokens"] == "PARENT TOKENS"
    assert installed["memory"] is None
    assert installed["context_snapshot"] is None
    assert installed["approved_capabilities"] == snapshot.capabilities


def test_typed_design_build_commits_before_host_quality(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone)},
        "design_engine": {
            "manifest_path": "design/ada-design-manifest.json",
            "quality": {
                "build_command": None,
                "required_pages": ["index.html"],
            },
        },
        "builder": {"enabled": True, "validation_repair_attempts": 1},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "design-quality-repair",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/design-quality-repair",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["index.html", "output/**", "design/**"],
    })
    turns = []

    def fake_turn(worktree, prompt, config, progress=None, session_id=None, timeout_seconds=None, **kwargs):
        turns.append(prompt)
        (worktree / "index.html").write_text("<html><body><h1>Candidate</h1></body></html>")
        (worktree / "output").mkdir(exist_ok=True)
        (worktree / "output" / "index.html").write_text(
            '<html lang="en"><head><title>Candidate</title></head>'
            '<body><h1>Candidate</h1></body></html>'
        )
        return {"session_id": "design-session", "reply": "implemented"}

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)

    assert receipt.candidate_sha != base_sha
    assert len(turns) == 1
    assert all("Host quality gates" not in prompt for prompt in turns)
    assert _git(clone, "rev-parse", target.candidate_ref).stdout.strip() == receipt.candidate_sha
    assert _git(clone, "rev-parse", f"{receipt.candidate_sha}^").stdout.strip() == base_sha
    assert _git(clone, "status", "--porcelain").stdout == ""
    memory.close()


def test_model_manifest_is_replaced_by_host_manifest(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone)},
        "builder": {"enabled": True},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "invalid-manifest",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/invalid-manifest",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["index.html", "design/**"],
    })

    def fake_turn(worktree, prompt, config, **kwargs):
        (worktree / "index.html").write_text("<html><body><h1>Candidate</h1></body></html>")
        (worktree / "design").mkdir()
        (worktree / "design" / "ada-design-manifest.json").write_text('{"schema_version":1}')
        return {"session_id": "design-session", "reply": "implemented"}

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)

    assert receipt.candidate_sha != base_sha
    manifest = json.loads(_git(clone, "show", f"{receipt.candidate_sha}:design/ada-design-manifest.json").stdout)
    assert manifest["host_generated"] is True
    assert manifest["intake_hash"] == "a" * 64
    assert _git(clone, "status", "--porcelain").stdout == ""
    assert _git(clone, "rev-parse", target.candidate_ref).stdout.strip() == receipt.candidate_sha
    memory.close()


def test_host_manifest_maps_next_homepage_output_to_source_file(tmp_path):
    worktree = tmp_path / "next"
    (worktree / "src" / "app").mkdir(parents=True)
    (worktree / "src" / "app" / "page.tsx").write_text("export default function Page() { return <main /> }")
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "next-manifest",
        "mode": "visual_refinement",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Refine the homepage.",
        "site_intake_hash": "b" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = BuildTarget.from_dict({
        "mode": "local_experiment",
        "base_sha": "a" * 40,
        "candidate_ref": "refs/ada-design-lab/next-manifest",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(worktree),
        "allowed_paths": list(NEXT_REACT_PROFILE.writable_patterns),
        "operation_kind": "visual_refinement",
        "build_profile": "next_react",
    })

    _, _, manifest = runner._write_host_design_manifest(
        {"design_engine": {"manifest_path": "design/ada-design-manifest.json"}},
        worktree,
        request,
        target,
        "a" * 40,
        {"src/app/page.tsx"},
    )

    assert manifest["source_homepage_path"] == "src/app/page.tsx"


def test_operation_router_uses_native_builder_for_every_design_operation():
    calls = []

    class FakeNative:
        def available(self):
            return True

        def build_design(self, request, target, progress=None):
            calls.append(("native", target.operation_kind))
            return "native"

    router = OperationRoutingBuilder(
        {},
        native=FakeNative(),
    )

    assert router.build_design(
        SimpleNamespace(),
        SimpleNamespace(operation_kind="initial_build", mode="production_candidate"),
    ) == "native"
    assert router.build_design(SimpleNamespace(), SimpleNamespace(operation_kind="visual_refinement", mode="production_candidate")) == "native"
    assert router.build_design(SimpleNamespace(), SimpleNamespace(operation_kind="technical_repair", mode="production_candidate")) == "native"
    assert router.build_design(SimpleNamespace(), SimpleNamespace(operation_kind="derived_page", mode="production_candidate")) == "native"
    assert calls == [
        ("native", "initial_build"),
        ("native", "visual_refinement"),
        ("native", "technical_repair"),
        ("native", "derived_page"),
    ]

    try:
        router.build_design(SimpleNamespace(), SimpleNamespace(operation_kind="unknown"))
    except BuilderError as exc:
        assert "unsupported design operation kind" in str(exc)
    else:
        raise AssertionError("unsupported operation kind was accepted")
