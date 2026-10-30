import json
import hashlib
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from site_agent.core.contracts import ContractError
from site_agent.core.design_contracts import BuildTarget, DesignContextSnapshot, ExperiencePlanBundle, PageBuildRequest
from site_agent.core.memory import Memory
from site_agent.hands import opencode_runner as runner
from site_agent.hands.builder import BuilderError, OperationRoutingBuilder
from site_agent.hands.site_build import NEXT_REACT_PROFILE, SiteBuildResult
from tests.test_design_contracts import _experience_plan


def _payload_first_request(whatsapp_url=None):
    conversion = {"primary_action": "Start a conversation", "not_available": True}
    if whatsapp_url:
        conversion = {"primary_action": "Start a conversation", "whatsapp_url": whatsapp_url}
    return PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "payload-first-home",
        "mode": "initial_homepage",
        "base_sha": "a" * 40,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "acceptance_criteria": ["Use confirmed business facts."],
        "content": {
            "site_intake": {
                "schema_version": 1,
                "business": {
                    "name": "North Star Studio",
                    "offer_summary": "Brand strategy for independent businesses.",
                    "primary_services": ["Brand strategy"],
                },
                "audience": {"primary": "Independent business owners"},
                "conversion": conversion,
                "brand": {"voice": "Clear, thoughtful, and warm."},
                "site": {"required_pages": ["home"]},
            },
        },
    })


def test_payload_first_homepage_data_is_editable_and_never_invents_a_contact_destination():
    copy_deck = {
        "eyebrow": "Independent by design",
        "headline": "Make your next move clearer.",
        "body": "Brand strategy for independent businesses.",
        "primary_action": "Start a conversation",
        "supporting_copy": ["Built around the business you are growing."],
        "meta_description": "A thoughtful brand strategy partner for independent businesses.",
    }

    linked = runner._initial_homepage_payload_data(
        _payload_first_request("https://wa.me/15551234567"),
        SimpleNamespace(copy_deck=copy_deck),
        featured_media_id=17,
    )
    entries = linked["sections"][0]["entries"]
    assert linked["title"] == "North Star Studio"
    assert linked["slug"] == "home"
    assert linked["featuredImage"] == 17
    assert linked["seo"]["description"] == copy_deck["meta_description"]
    assert entries[1]["text"] == copy_deck["headline"]
    assert entries[2]["text"] == copy_deck["body"]
    assert entries[3]["href"] == "https://wa.me/15551234567"
    assert entries[3]["key"] == "home.hero.primary-action"

    no_destination = runner._initial_homepage_payload_data(
        _payload_first_request(), SimpleNamespace(copy_deck=copy_deck)
    )
    action = no_destination["sections"][0]["entries"][3]
    assert action["blockType"] == "helloAdaParagraph"
    assert action["text"] == copy_deck["primary_action"]
    assert "href" not in action


def test_payload_first_stage_persists_and_binds_the_exact_default_locale_revision():
    class Payload:
        document = None

        def require_authoring_contract(self):
            return {
                "enabled": {"collections": ["pages"]},
                "locales": ["es-MX", "en"],
                "defaultLocale": "es-MX",
                "schemaIdentity": "schema-identity",
                "authoringContractHash": "authoring-hash",
            }

        def read_media(self, identifier, *, identifier_kind, draft):
            raise AssertionError("there is no selected tenant media asset in this test")

        def create(self, collection, data, *, locale):
            assert collection == "pages" and locale == "es-MX"
            self.document = {"id": 41, "slug": "home", "sourceId": "pages:home", **data,
                             "_helloadaRevision": "sha256:" + "1" * 64}
            return dict(self.document)

        def read(self, collection, *, identifier, identifier_kind, draft, locale):
            assert (collection, identifier, identifier_kind, draft, locale) == ("pages", "41", "id", True, "es-MX")
            return dict(self.document)

    request = _payload_first_request()
    staged = runner._stage_initial_homepage_payload(
        {"payload_gateway": Payload()},
        request,
        SimpleNamespace(
            copy_deck={
                "headline": "A clear promise.",
                "body": "An owner-confirmed service.",
                "primary_action": "Learn more",
            },
            asset_composition_plan=(),
            asset_evidence=(),
        ),
    )

    receipt = staged.content["payload_draft_receipts"][0]
    assert receipt["document_id"] == "41"
    assert receipt["revision"] == "sha256:" + "1" * 64
    assert receipt["locale"] == "es-MX"
    assert receipt["content_keys"] == [
        "home.hero.heading", "home.hero.introduction", "home.hero.primary-action",
    ]
    assert "payload_draft_receipts" not in request.content


def test_payload_first_stage_adopts_existing_home_route_draft_and_binds_run_identity():
    from site_agent.hands.payload_gateway import PayloadGatewayError

    class Payload:
        document = {"id": 41, "slug": "home", "sourceId": "pages:home",
                    "_helloadaRevision": "sha256:" + "1" * 64}
        updated = None
        verified_read = False

        def require_authoring_contract(self):
            return {"enabled": {"collections": ["pages"]}, "locales": ["es-MX"],
                    "defaultLocale": "es-MX", "schemaIdentity": "schema-identity",
                    "authoringContractHash": "authoring-hash"}

        def read_media(self, *_args, **_kwargs):
            raise AssertionError("no media")

        def create(self, *_args, **_kwargs):
            raise PayloadGatewayError(
                "Payload gateway returned 409: a Payload document already uses this route; "
                "read and update that exact draft instead", status_code=409
            )

        def read(self, collection, *, identifier, identifier_kind, draft, locale):
            assert collection == "pages" and draft and locale == "es-MX"
            if identifier_kind == "slug":
                assert identifier == "home"
                return dict(self.document)
            assert (identifier, identifier_kind) == ("41", "id")
            self.verified_read = True
            return dict(self.document)

        def update(self, collection, document_id, data, *, locale, expected_hash, expected_fields):
            assert (collection, document_id, locale) == ("pages", "41", "es-MX")
            assert expected_hash == self.document["_helloadaRevision"]
            self.updated = dict(data)
            self.document = {**self.document, **data, "_helloadaRevision": "sha256:" + "2" * 64}
            return dict(self.document)

    payload = Payload()
    request = _payload_first_request()
    staged = runner._stage_initial_homepage_payload(
        {"payload_gateway": payload}, request,
        SimpleNamespace(copy_deck={"headline": "New heading.", "body": "New body.",
                                   "primary_action": "Learn more"},
                       asset_composition_plan=(), asset_evidence=()),
    )
    receipt = staged.content["payload_draft_receipts"][0]
    assert next(item["text"] for item in payload.updated["sections"][0]["entries"]
                if item["key"] == "home.hero.heading") == "New heading."
    assert set(payload.updated) == {"title", "slug", "sections", "seo"}
    assert payload.verified_read
    assert receipt["document_id"] == "41"
    assert receipt["operation"] == "update"
    assert receipt["run_id"] == request.run_id


@pytest.mark.parametrize("existing, unreadable", [
    ({"id": 42, "slug": "about", "sourceId": "pages:about",
      "_helloadaRevision": "sha256:" + "1" * 64}, False),
    (None, True),
])
def test_payload_first_stage_does_not_adopt_different_or_unreadable_route(existing, unreadable):
    from site_agent.hands.payload_gateway import PayloadGatewayError

    class Payload:
        def require_authoring_contract(self):
            return {"enabled": {"collections": ["pages"]}, "locales": ["es-MX"],
                    "defaultLocale": "es-MX", "schemaIdentity": "schema-identity",
                    "authoringContractHash": "authoring-hash"}
        def read_media(self, *_args, **_kwargs):
            raise AssertionError("no media")
        def create(self, *_args, **_kwargs):
            raise PayloadGatewayError("conflict", status_code=409)
        def read(self, collection, *, identifier, identifier_kind, draft, locale):
            assert identifier_kind == "slug" and identifier == "home"
            if unreadable:
                raise PayloadGatewayError("not found", status_code=404)
            return dict(existing)
        def update(self, *_args, **_kwargs):
            raise AssertionError("must not update an unverified route")

    with pytest.raises(runner.RunnerError, match="the initial Payload homepage draft could not be verified"):
        runner._stage_initial_homepage_payload(
            {"payload_gateway": Payload()}, _payload_first_request(),
            SimpleNamespace(copy_deck={"headline": "Heading.", "body": "Body.",
                                       "primary_action": "Learn more"},
                           asset_composition_plan=(), asset_evidence=()),
        )


def _build_target(value):
    value.setdefault("build_profile", NEXT_REACT_PROFILE.name)
    value["allowed_paths"] = list(NEXT_REACT_PROFILE.writable_patterns)
    return BuildTarget.from_dict(value)


def _write_presentation(root, content):
    path = root / "src" / "components" / "site" / "presentation" / "Home.tsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "export function Home(){return <main dangerouslySetInnerHTML={{__html: "
        + json.dumps(content)
        + "}} />}\n"
    )


@pytest.fixture(autouse=True)
def _isolate_host_toolchain_boundary(monkeypatch):
    """Keep builder lifecycle tests independent of npm registry state."""
    import site_agent.hands.site_build as site_build

    monkeypatch.setattr(site_build, "prepare_site_toolchain", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        site_build,
        "build_site",
        lambda _root, profile, **_kwargs: SiteBuildResult(
            profile=profile.name,
            ok=True,
            output_dir=profile.output_dir,
            commands=({"command": ["test"], "status": "passed"},),
            route_inventory=("index.html",),
        ),
    )


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
    source = clone / "src" / "components" / "site" / "presentation"
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
    target = _build_target({
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
    target = _build_target({
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
        _write_presentation(worktree, "<html><body><h1>Candidate</h1></body></html>")
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
    assert manifest["source_files"] == {"changed": ["src/components/site/presentation/Home.tsx"]}
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
    target = _build_target({
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
        calls.append({"agent_name": kwargs.get("agent_name"), "prompt": prompt, "memory": kwargs.get("memory")})
        if kwargs.get("agent_name") == "native-direction":
            return {
                "session_id": "direction-session",
                "reply": "A quiet editorial threshold opens into a tactile story of the owner’s work.",
                "transcript": '{"type":"text","sessionID":"direction-session"}\n',
            }
        _write_presentation(worktree, "<html><body><h1>Candidate</h1></body></html>")
        return {
            "session_id": "build-session",
            "reply": "implemented",
            "transcript": '{"type":"text","sessionID":"build-session"}\n',
        }

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)

    assert [call["agent_name"] for call in calls] == ["native-direction", "build"]
    assert calls[0]["memory"] is memory
    assert calls[1]["memory"] is memory
    assert "A quiet editorial threshold" in calls[1]["prompt"]
    assert receipt.direction_path == "design-runs/native-direction-build/direction.md"
    assert receipt.direction_transcript_path == "design-runs/native-direction-build/direction-opencode.jsonl"
    direction_file = tmp_path / "data" / receipt.direction_path
    assert direction_file.read_text() == "A quiet editorial threshold opens into a tactile story of the owner’s work.\n"
    assert (tmp_path / "data" / receipt.direction_transcript_path).is_file()
    memory.close()


def test_native_direction_without_memory_preserves_legacy_turn_kwargs(tmp_path, monkeypatch):
    clone, base_sha = _clone(tmp_path)
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "design_engine": {"orchestration": "native"},
        "builder": {"enabled": True},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": "native-direction-no-memory",
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "a" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
    })
    target = _build_target({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/native-direction-no-memory",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
    })
    calls = []

    monkeypatch.setattr(runner, "install_agent_files", lambda *args, **kwargs: None)

    def fake_turn(worktree, _prompt, _config, **kwargs):
        calls.append(dict(kwargs))
        if kwargs.get("agent_name") == "native-direction":
            return {"session_id": "direction-session", "reply": "A quiet editorial threshold.", "transcript": "direction\n"}
        _write_presentation(worktree, "<html><body><h1>Candidate</h1></body></html>")
        return {"session_id": "build-session", "reply": "implemented", "transcript": "build\n"}

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    runner.stage_design_build({"config": config}, request, target)

    assert [call["agent_name"] for call in calls] == ["native-direction", "build"]
    assert all("memory" not in call for call in calls)


@pytest.mark.parametrize("outcome", ["invalid", "provider_error", "corrected_valid", "checkpoint_resume"])
def test_native_direction_repair_is_bounded_and_fenced(tmp_path, monkeypatch, outcome):
    from site_agent.hands.builder import BuilderError, NativeOpenCodeBuilder

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
    run_id = "invalid-creative-direction-memory"
    memory.create_design_run(
        run_id=run_id,
        mode="local_experiment",
        intake_json={"schema_version": 1},
        intake_hash="b" * 64,
        base_sha=base_sha,
        candidate_ref=f"refs/ada-design-lab/{run_id}",
    )
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "design_engine": {"orchestration": "creative", "model": "provider/model"},
        "builder": {"enabled": True},
    }
    request = PageBuildRequest.from_dict({
        "schema_version": 1,
        "run_id": run_id,
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": "index.html",
        "purpose": "Create the homepage.",
        "site_intake_hash": "b" * 64,
        "acceptance_criteria": ["Keep the homepage accessible."],
        "context_snapshot": snapshot.to_dict(),
        "context_snapshot_hash": snapshot.content_hash,
    })
    target = _build_target({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": f"refs/ada-design-lab/{run_id}",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
    })
    calls = []
    prompts = []
    competing_errors = []
    competing_attempts = []

    monkeypatch.setattr(runner, "install_agent_files", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_typed_execution_config", lambda config, request, target: config)
    if outcome in {"corrected_valid", "checkpoint_resume"}:
        from site_agent.application.design_orchestration import SpecialistDesignCoordinator as RealCoordinator

        class FakeCoordinator:
            _normalize_experience_plan_payload = staticmethod(RealCoordinator._normalize_experience_plan_payload)

            def __init__(self, _context):
                pass

            def record_implementation_phase(self, *args, **kwargs):
                return None

            def run_experience_fidelity_phase(self, *args, **kwargs):
                return SimpleNamespace(to_dict=lambda: {})

        monkeypatch.setattr(
            "site_agent.application.design_orchestration.SpecialistDesignCoordinator", FakeCoordinator,
        )
        monkeypatch.setattr(runner, "_run_local_design_self_check", lambda *args, **kwargs: {})
        monkeypatch.setattr(runner, "_provision_referenced_frontend_libraries", lambda *args, **kwargs: ())

    def fake_turn(_worktree, _prompt, _config, **kwargs):
        calls.append(dict(kwargs))
        prompts.append(_prompt)
        if outcome == "checkpoint_resume" and kwargs.get("agent_name") in {"native-direction", "build"}:
            # Re-enter the complete facade through an independent SQLite
            # connection while the winner's durable phase is still running.
            competing_memory = Memory(tmp_path / "data" / "memory.db")
            competing_attempts.append(kwargs["agent_name"])
            try:
                NativeOpenCodeBuilder({"config": config, "memory": competing_memory}).build_design(request, target)
            except BuilderError as exc:
                competing_errors.append(str(exc))
            finally:
                competing_memory.close()
        if kwargs.get("agent_name") == "build":
            _write_presentation(_worktree, "<html><body><h1>Candidate</h1></body></html>")
            return {"session_id": "build-session", "reply": "implemented", "transcript": "build transcript\n"}
        assert kwargs.get("agent_name") == "native-direction"
        if outcome == "provider_error":
            raise runner.RunnerError("provider process failed", result={"transcript": "provider failure\n"})
        from tests.test_design_contracts import _experience_plan

        valid_plan = _experience_plan()
        valid_plan.pop("asset_evidence")
        valid_plan.pop("asset_composition_plan")
        invalid_plan = json.loads(json.dumps(valid_plan))
        invalid_plan["behavior_system"]["utility_behaviors"][0].pop("meaning")
        if outcome == "checkpoint_resume" or (outcome == "corrected_valid" and len(calls) == 2):
            return {
                "session_id": "direction-corrected" if outcome == "corrected_valid" else "direction-valid",
                "structured": {"direction": "A specific measured arrival.", "experience_plan": valid_plan},
                "transcript": "valid structured plan\n",
            }
        return {
            "session_id": "direction-invalid",
            "structured": {"direction": "A considered threshold.", "experience_plan": invalid_plan},
            "transcript": "invalid structured plan\n",
        }

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    if outcome == "checkpoint_resume":
        class SimulatedInterruption(Exception):
            pass

        def interrupt_before_build(message):
            if "starting the integrated Build turn" in message:
                raise SimulatedInterruption()

        with pytest.raises(SimulatedInterruption):
            runner.stage_design_build(
                {"config": config, "memory": memory}, request, target, progress=interrupt_before_build,
            )
        completed = memory.list_design_phase_artifacts(run_id, phase="native_direction")
        assert [item["status"] for item in completed] == ["completed"]
        composition = memory.get_design_run(run_id)["planning_json"]["integrated_composition"]
        assert composition["state"] == "planned"
        persisted_hash = completed[0]["input_hashes"]
        persisted_context_hash = completed[0]["context_snapshot_hash"]
        assert completed[0]["payload"]["direction"] == "A specific measured arrival."
        memory.close()
        reopened = Memory(tmp_path / "data" / "memory.db")
        receipt = NativeOpenCodeBuilder({"config": config, "memory": reopened}).build_design(request, target)
        assert receipt.experience_plan["behavior_system"]["utility_behaviors"][0]["meaning"]
        assert [call["agent_name"] for call in calls] == ["native-direction", "build"]
        assert competing_attempts == ["native-direction", "build"]
        assert len(competing_errors) == 2
        assert competing_errors == [
            "native direction provider call is still running; reconciliation required before replay",
            "Build dispatch was already claimed for this run; safe reconciliation is required before another invocation",
        ]
        assert calls[-1]["memory"] is reopened
        assert "A specific measured arrival." in prompts[-1]
        assert "image_files" not in calls[0] or calls[0]["image_files"] == calls[-1].get("image_files")
        reopened_completed = reopened.list_design_phase_artifacts(run_id, phase="native_direction")
        fence = reopened.list_design_phase_artifacts(run_id, phase="build_dispatch")
        assert reopened_completed[0]["input_hashes"] == persisted_hash
        assert reopened_completed[0]["context_snapshot_hash"] == persisted_context_hash == snapshot.content_hash
        assert fence[0]["input_hashes"] == persisted_hash
        assert reopened.get_design_run(run_id)["planning_json"]["integrated_composition"]["experience_plan_hash"] == composition["experience_plan_hash"]
        # A completed planning checkpoint is reusable once, but the durable
        # Build fence prevents a restart or facade entry from issuing Build again.
        with pytest.raises(BuilderError, match="Build dispatch was already claimed"):
            NativeOpenCodeBuilder({"config": config, "memory": reopened}).build_design(request, target)
        assert [call["agent_name"] for call in calls] == ["native-direction", "build"]

        # The same run cannot reuse its checkpoint when any frozen identity
        # dimension changes. Each failure occurs before another provider turn.
        from site_agent.core.design_contracts import BuildTarget

        facade = NativeOpenCodeBuilder({"config": config, "memory": reopened})
        changed_request_data = request.to_dict()
        changed_request_data["purpose"] = "A materially changed request."
        changed_request = PageBuildRequest.from_dict(changed_request_data)
        changed_snapshot_data = snapshot.to_dict()
        changed_snapshot_data["owner_request"] = "A materially changed context."
        changed_snapshot = DesignContextSnapshot.from_dict(changed_snapshot_data)
        changed_context_data = request.to_dict()
        changed_context_data["context_snapshot"] = changed_snapshot.to_dict()
        changed_context_data["context_snapshot_hash"] = changed_snapshot.content_hash
        changed_context = PageBuildRequest.from_dict(changed_context_data)
        changed_assets_data = request.to_dict()
        changed_assets_data["supplied_media_asset_ids"] = [47]
        changed_assets = PageBuildRequest.from_dict(changed_assets_data)
        monkeypatch.setattr(runner, "_materialize_media", lambda *args, **kwargs: [])
        changed_target_data = target.to_dict()
        changed_target_data["candidate_ref"] = f"refs/ada-design-lab/{run_id}-different"
        changed_target = BuildTarget.from_dict(changed_target_data)
        for drift_request, drift_target in (
            (changed_request, target), (changed_context, target),
            (changed_assets, target), (request, changed_target),
        ):
            with pytest.raises(BuilderError, match="identity mismatch"):
                facade.build_design(drift_request, drift_target)
        assert reopened_completed[0]["input_hashes"] == persisted_hash
        assert [call["agent_name"] for call in calls] == ["native-direction", "build"]
        reopened.close()
        return

    if outcome == "corrected_valid":
        receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)
        assert receipt.experience_plan["behavior_system"]["utility_behaviors"][0]["meaning"]
        assert [call["agent_name"] for call in calls] == ["native-direction", "native-direction", "build"]
        phase = memory.list_design_phase_artifacts(run_id, phase="native_direction")
        fence = memory.list_design_phase_artifacts(run_id, phase="build_dispatch")
        assert [item["status"] for item in phase] == ["failed", "completed"]
        assert [item["status"] for item in fence] == ["running"]
        assert phase[0]["payload"]["response"]["structured"]["experience_plan"]["behavior_system"]["utility_behaviors"][0].get("meaning") is None
        assert "utility_behaviors[0].meaning" in prompts[1]
        # The correction continues the failed session and carries only the
        # diagnostic; replaying the frozen request and the previous answer
        # made a one-field repair as expensive as the original turn.
        assert calls[1]["session_id"] == "direction-invalid"
        assert "A considered threshold." not in prompts[1]
        assert "PAGE BUILD REQUEST" not in prompts[1]
        assert "failed typed validation" in prompts[1]
        assert phase[0]["context_snapshot_hash"] == phase[1]["context_snapshot_hash"] == snapshot.content_hash
        assert phase[0]["input_hashes"] == phase[1]["input_hashes"] == fence[0]["input_hashes"]
        assert memory.get_design_run(run_id)["planning_json"]["integrated_composition"]["state"] == "planned"
        with pytest.raises(runner.RunnerError, match="Build dispatch was already claimed"):
            runner.stage_design_build({"config": config, "memory": memory}, request, target)
        assert [call["agent_name"] for call in calls] == ["native-direction", "native-direction", "build"]
    else:
        with pytest.raises(runner.RunnerError, match=(
            "provider process failed" if outcome == "provider_error" else r"utility_behaviors\[0\].meaning"
        )):
            runner.stage_design_build({"config": config, "memory": memory}, request, target)
        assert len(calls) == (1 if outcome == "provider_error" else 2)
        assert all(call["agent_name"] == "native-direction" for call in calls)
    phases = memory.list_design_phase_artifacts(run_id, phase="native_direction")
    if outcome == "provider_error":
        assert [phase["status"] for phase in phases] == ["failed"]
        assert phases[0]["error_code"] == "provider_or_process_failure"
        memory.close()
        reopened = Memory(tmp_path / "data" / "memory.db")
        with pytest.raises(runner.RunnerError, match="provider/process failure is terminal"):
            runner.stage_design_build({"config": config, "memory": reopened}, request, target)
        assert len(calls) == 1
        reopened.close()
        return
    elif outcome == "invalid":
        assert [phase["status"] for phase in phases] == ["failed", "failed"]
        assert "utility_behaviors[0].meaning" in phases[0]["payload"]["diagnostic"]
        memory.close()
        reopened = Memory(tmp_path / "data" / "memory.db")
        with pytest.raises(ContractError, match="exhausted"):
            runner.stage_design_build({"config": config, "memory": reopened}, request, target)
        assert len(calls) == 2
        reopened.close()
        return
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
    target = _build_target({
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
        _write_presentation(worktree, "<html><body><h1>Candidate</h1></body></html>")
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
    target = _build_target({
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
    # The direction turn must not spend the build's time reading the codebase.
    assert "Do not inspect the repository" in prompt
    assert "configured framework boundary" not in prompt
    assert "Read only the relevant package/config files" not in prompt
    assert "existing source entrypoints" not in prompt


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
    # Direction is a judgement about the subject; sending Ada into the
    # repository cost 19 minutes and produced nothing the Build turn needs.
    assert "Never inspect the repository" in definition


def test_direction_correction_continues_the_session_instead_of_replaying():
    prompt, extra = runner._direction_correction(
        {"session_id": "ses_direction", "reply": "A considered threshold."},
        "asset_composition_plan.asset_id is invalid",
    )

    assert extra == {"session_id": "ses_direction"}
    assert "asset_composition_plan.asset_id is invalid" in prompt
    assert "A considered threshold." not in prompt
    assert "PAGE BUILD REQUEST" not in prompt


def test_direction_correction_without_a_session_still_asks_for_a_fix():
    prompt, extra = runner._direction_correction({}, "copy_deck.body is required")

    assert extra == {}
    assert "copy_deck.body is required" in prompt


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
    target = _build_target({
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
        _write_presentation(worktree, "<html><body><h1>Candidate</h1></body></html>")
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
    target = _build_target({
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
            "memory": kwargs.get("memory"),
        })
        if kwargs.get("agent_name") == "native-direction":
            direction = "A quiet threshold opens into a tactile story of the owner's work."
            text = json.dumps({"direction": direction, "experience_plan": raw_plan})
            return {
                "session_id": "direction-session",
                "reply": text,
                "transcript": json.dumps({"type": "text", "text": text}) + "\n",
            }
        _write_presentation(worktree, "<html><body><h1>Candidate</h1></body></html>")
        return {
            "session_id": "build-session",
            "reply": "implemented",
            "transcript": '{"type":"text","text":"implemented"}\n',
        }

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)

    assert [call["agent_name"] for call in calls] == ["native-direction", "build"]
    assert calls[0]["memory"] is memory
    assert calls[1]["memory"] is memory
    assert calls[0]["image_files"]
    assert calls[0]["image_files"] == calls[1]["image_files"]
    assert "public/images/owner.webp" in calls[0]["image_files"]
    assert "Return exactly one JSON object" in calls[0]["prompt"]
    assert "brand_source_map" in calls[0]["prompt"]
    assert "asset_composition_plan" in calls[0]["prompt"]
    assert "final visitor-facing homepage copy" in calls[0]["prompt"]
    assert "Do not inspect the repository" in calls[0]["prompt"]
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
    css = clone / "src" / "app" / "(frontend)" / "site.css"
    css.parent.mkdir(parents=True)
    css.write_text("body { color: red; }")
    _git(clone, "add", "styles.css", "app.js", "src/app/(frontend)/site.css")
    _git(clone, "commit", "-qm", "homepage entrypoints")
    base_sha = _git(clone, "rev-parse", "HEAD").stdout.strip()
    memory = Memory(tmp_path / "data" / "memory.db")
    config = {
        "data_dir": str(tmp_path / "data"),
        "site": {"clone_path": str(clone)},
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
    target = _build_target({
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
        _write_presentation(worktree, "<html><body><h1>New</h1></body></html>")
        (worktree / "src" / "app" / "(frontend)" / "site.css").write_text("body { color: blue; }")
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
    target = _build_target({
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
        _write_presentation(worktree, "<html><body><h1>New</h1></body></html>")
        return {"session_id": "deleted-session", "reply": "implemented"}

    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)

    receipt = runner.stage_design_build({"config": config, "memory": memory}, request, target)

    manifest = json.loads(_git(clone, "show", f"{receipt.candidate_sha}:design/ada-design-manifest.json").stdout)
    assert manifest["source_files"] == {"changed": ["src/components/site/presentation/Home.tsx"]}
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
    target = _build_target({
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
        _write_presentation(worktree, "<html><body><h1>Candidate</h1></body></html>")
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
    target = _build_target({
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
    target = _build_target({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/partial-design",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["*.html", "design/**"],
    })

    def failed_turn(worktree, prompt, config, **kwargs):
        _write_presentation(worktree, "<html><body><h1>Partial</h1></body></html>")
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
    target = _build_target({
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
        _write_presentation(worktree, "<html><body><h1>Candidate</h1></body></html>")
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
    target = _build_target({
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
        _write_presentation(worktree, "<html><body><h1>Repaired</h1></body></html>")
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
    target = _build_target({
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
        _write_presentation(worktree, "<html><body><h1>Independent</h1></body></html>")
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
    target = _build_target({
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
        _write_presentation(worktree, "<html><body><h1>Refined</h1></body></html>")
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
    target = _build_target({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/design-quality-repair",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": list(NEXT_REACT_PROFILE.writable_patterns),
    })
    turns = []

    def fake_turn(worktree, prompt, config, progress=None, session_id=None, timeout_seconds=None, **kwargs):
        turns.append(prompt)
        _write_presentation(worktree, "<html><body><h1>Candidate</h1></body></html>")
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
    target = _build_target({
        "mode": "local_experiment",
        "base_sha": base_sha,
        "candidate_ref": "refs/ada-design-lab/invalid-manifest",
        "push_mode": "none",
        "publishable": False,
        "clone_path": str(clone),
        "allowed_paths": ["index.html", "design/**"],
    })

    def fake_turn(worktree, prompt, config, **kwargs):
        _write_presentation(worktree, "<html><body><h1>Candidate</h1></body></html>")
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


def test_host_manifest_maps_next_homepage_output_to_tenant_presentation_source(tmp_path):
    worktree = tmp_path / "next"
    (worktree / "src" / "app").mkdir(parents=True)
    (worktree / "src" / "app" / "page.tsx").write_text("export default function Page() { return <main /> }")
    presentation = worktree / "src" / "components" / "site" / "presentation"
    presentation.mkdir(parents=True)
    (presentation / "Home.tsx").write_text("export function Home() { return <main /> }")
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
    target = _build_target({
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
        {"src/app/page.tsx", "src/components/site/presentation/Home.tsx"},
    )

    assert manifest["source_homepage_path"] == "src/components/site/presentation/Home.tsx"


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


def test_composition_entries_follow_the_supplied_assets_not_only_evidence():
    """Owner-selected media is authoritative even before visual evidence exists."""
    from site_agent.hands.opencode_runner import _bind_compositions

    entries = [
        {"schema_version": 1, "asset_id": "41", "asset_sha256": "a" * 64,
         "structural_contribution": ["hero"], "evidence_refs": ["owner:message:10"]},
        {"schema_version": 1, "asset_id": "5", "asset_sha256": "b" * 64,
         "structural_contribution": ["hero"], "evidence_refs": ["owner:message:10"]},
        {"schema_version": 1, "asset_id": "asset-7", "asset_sha256": "c" * 64,
         "structural_contribution": ["hero"], "evidence_refs": ["owner:message:10"]},
    ]
    kept = _bind_compositions(entries, {}, [5, 6, 7])
    # Payload ids are numeric; the typed plan and its evidence both use media-<id>.
    assert [entry["asset_id"] for entry in kept] == ["media-5", "media-7"]
    # Without any supplied media an invented identifier is still refused.
    assert _bind_compositions(entries, {}, []) == []
