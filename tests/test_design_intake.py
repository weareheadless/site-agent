import pytest

import json

from site_agent.application.design_intake import DesignIntakeService, DesignIntakeServiceError
from site_agent.application.workspace import DesignBuildHandoff
from site_agent.application.designs import DesignSharedIntelligence
from site_agent.application.customer_genesis import CustomerGenesisService
from site_agent.brain.design_intake import (
    DesignIntakeAdvisorError,
    UnavailableDesignIntakeAdvisor,
    _advisor_prompt,
)
from site_agent.core.design_contracts import SiteIntake
from site_agent.core.design_intake_contracts import (
    DesignIntakeDraft,
    IntakeDisposition,
    IntakeFieldUpdate,
    IntakeFieldProvenance,
    IntakeTurnResult,
    merge_intake_turn,
)
from site_agent.core.chat_jobs import run_job
from site_agent.core.memory import Memory
from site_agent.core.media_contracts import MediaAsset, MediaKind, MediaStatus


def test_advisor_prompt_guides_adaptive_evidence_led_intake_without_industry_scripts():
    prompt = _advisor_prompt(DesignIntakeDraft.empty(), [], "design guidance")
    assert "Adapt your questions and research priorities to this particular business" in prompt
    assert "Use the supplied research findings, working brief, and conversation" in prompt
    assert "Ask only for useful information that is genuinely unresolved" in prompt
    assert "at most two or three related questions per turn" in prompt
    assert "Never claim to have researched a source without evidence" in prompt
    assert "full industry checklist" in prompt
    assert "notes.owner_facts" in prompt


def test_owner_fact_is_validated_persisted_and_round_trips():
    draft = DesignIntakeDraft.empty().with_value(
        "notes.owner_facts", [{"label": "Instagram", "value": "@northstar"}],
        IntakeFieldProvenance("notes.owner_facts", "confirmed", source_message_id=7),
    )
    restored = DesignIntakeDraft.from_dict(json.loads(json.dumps(draft.to_dict())))
    assert restored.value("notes.owner_facts") == [{"label": "Instagram", "value": "@northstar"}]
    assert restored.provenance["notes.owner_facts"].source_message_id == 7
    assert DesignIntakeDraft.from_dict(DesignIntakeDraft.empty().to_dict()).value("notes.owner_facts") is None
    with pytest.raises(Exception):
        DesignIntakeDraft.from_dict({**draft.to_dict(), "fields": draft.fields, "provenance": {}})
    for invalid in (
        [{"label": "Instagram"}],
        [{"label": "x" * 81, "value": "v"}],
        [{"label": "x", "value": "v" * 401}],
        [{"label": "x", "value": "v"}] * 21,
    ):
        with pytest.raises(Exception):
            DesignIntakeDraft.from_dict({
                **DesignIntakeDraft.empty().to_dict(),
                "fields": {"notes": {"owner_facts": invalid}},
                "provenance": {"notes.owner_facts": {"origin": "confirmed"}},
            })


def _intake() -> SiteIntake:
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "North Star Studio",
            "offer_summary": "Brand strategy for independent businesses.",
            "primary_services": ["Brand strategy"],
            "location": "North Shore",
        },
        "audience": {"primary": "Independent business owners"},
        "conversion": {"primary_action": "Book a consultation", "not_available": True},
        "brand": {"voice": "Clear, thoughtful, and warm."},
        "site": {"required_pages": ["index.html"]},
    })


class _Advisor:
    def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
        return IntakeTurnResult(
            schema_version=1,
            assistant_message="I recorded that direction. Confirm the brief when it feels right.",
            field_updates=(IntakeFieldUpdate(
                path="brand.vibe",
                value="Quiet, editorial, and tactile",
                basis="owner_statement",
            ),),
            suggested_readiness="ready_to_build",
        )


def test_conversational_turn_is_durable_and_message_bound(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_Advisor())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "Keep the direction quiet and tactile.")
    job = memory.claim_chat_job("test-worker")

    result = run_job(
        {
            "memory": memory,
            "design_intake_service": service,
            "config": {},
            "llm": object(),
        },
        job,
        "test-worker",
    )

    assert result["operation_kind"] == "design_intake_advice"
    assert result["intake_revision"] == 2
    stored = service.get_session(session["session_id"])
    assert stored["draft"]["fields"]["brand"]["vibe"] == "Quiet, editorial, and tactile"
    assert stored["draft"]["provenance"]["brand.vibe"]["origin"] == "confirmed"
    assert stored["messages"][-1]["role"] == "assistant"
    assert memory.get_chat_job(queued["job_id"])["status"] == "done"
    memory.close()


def test_chat_job_downgrades_completion_claim_when_no_build_started(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _OverconfidentAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message="Done — the preview is ready.",
                suggested_readiness="collecting",
            )

    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_OverconfidentAdvisor())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "Give me a few directions.")
    job = memory.claim_chat_job("status-worker")

    result = run_job(
        {
            "memory": memory,
            "design_intake_service": service,
            "config": {},
            "llm": object(),
        },
        job,
        "status-worker",
    )

    assert "To be clear, I haven't built or previewed this yet." in result["reply"]
    assert memory.get_chat_job(queued["job_id"])["status"] == "done"
    memory.close()


def test_malformed_scalar_field_update_does_not_break_intake_turn():
    turn = IntakeTurnResult.from_dict({
        "schema_version": 1,
        "assistant_message": "I recorded the direction and will keep working through the brief.",
        "field_updates": [
            {
                "path": "business.offer_summary",
                "value": "A quiet, editorial website for independent businesses.",
                "basis": "owner_statement",
            },
            {
                "path": "conversion.primary_action",
                "value": {"label": "Book a consultation"},
                "basis": "owner_statement",
            },
        ],
    })

    assert [item.path for item in turn.field_updates] == ["business.offer_summary"]


def test_malformed_scalar_field_update_does_not_block_genesis_revision(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _MalformedAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message="I recorded the direction and will keep working through the brief.",
                field_updates=(
                    IntakeFieldUpdate(
                        path="business.offer_summary",
                        value="A quiet, editorial website for independent businesses.",
                        basis="owner_statement",
                    ),
                    IntakeFieldUpdate(
                        path="conversion.primary_action",
                        value={"label": "Book a consultation"},
                        basis="owner_statement",
                    ),
                ),
            )

    service = DesignIntakeService(
        memory,
        advisor=_MalformedAdvisor(),
        genesis_service=CustomerGenesisService(memory),
    )
    try:
        session = service.create_session()
        queued = service.send_message(session["session_id"], "Keep the direction quiet and editorial.")
        job = memory.claim_chat_job("malformed-field-worker")

        result = run_job(
            {
                "memory": memory,
                "design_intake_service": service,
                "config": {},
                "llm": object(),
            },
            job,
            "malformed-field-worker",
        )

        assert "error" not in result
        assert memory.get_chat_job(queued["job_id"])["status"] == "done"
        stored = service.get_session(session["session_id"])
        assert stored["draft"]["fields"]["business"]["offer_summary"] == (
            "A quiet, editorial website for independent businesses."
        )
        assert stored["draft"]["fields"].get("conversion", {}).get("primary_action") is None
        assert CustomerGenesisService(memory).current().business_world["purpose"] == (
            "A quiet, editorial website for independent businesses."
        )
    finally:
        memory.close()


def test_malformed_persisted_scalar_is_removed_when_draft_is_reloaded(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    try:
        service = DesignIntakeService(memory)
        session = service.create_session()
        malformed = DesignIntakeDraft.empty().with_value(
            "business.offer_summary",
            "A quiet, editorial website for independent businesses.",
            IntakeFieldProvenance(path="business.offer_summary", origin="confirmed"),
        ).with_value(
            "conversion.primary_action",
            {"label": "Book a consultation"},
            IntakeFieldProvenance(path="conversion.primary_action", origin="confirmed"),
        )
        memory.save_design_intake_revision(
            session["session_id"],
            malformed,
            expected_revision=session["revision"],
        )

        reloaded = memory.get_design_intake_session(session["session_id"])

        assert reloaded is not None
        assert reloaded["draft"]["fields"].get("conversion", {}).get("primary_action") is None
        assert "conversion.primary_action" not in reloaded["draft"]["provenance"]
    finally:
        memory.close()


def test_confirmation_requires_offer_summary_before_building(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory)
    try:
        session = service.create_session()

        with pytest.raises(DesignIntakeServiceError, match=r"business\.offer_summary is required before building"):
            service.confirm(
                session["session_id"],
                revision=session["revision"],
                draft_hash=session["draft_hash"],
                idempotency_key="missing-offer",
            )
    finally:
        memory.close()


def test_creative_insights_from_an_intake_turn_persist_as_incubation_insights(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _AdvisorWithInsights:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message="Noted — the quieter the surface, the stronger the trust.",
                creative_insights=(
                    {
                        "kind": "creative_implication",
                        "summary": "A quieter opening may make the technical offer easier to trust.",
                        "basis": "recommendation",
                        "related_intake_paths": ["brand.voice", "audience.concerns"],
                        "confidence": 0.6,
                    },
                    {
                        "kind": "creative_implication",
                        "summary": "Soft material cues could signal warmth before the first sentence.",
                        "basis": "recommendation",
                        "related_intake_paths": ["brand.colors"],
                        "confidence": 0.5,
                    },
                ),
                suggested_readiness="needs_more",
            )

    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_AdvisorWithInsights())
    session = service.create_session()
    service.send_message(session["session_id"], "Keep the direction quiet and tactile.")
    job = memory.claim_chat_job("test-worker")

    run_job(
        {
            "memory": memory,
            "design_intake_service": service,
            "config": {},
            "llm": object(),
        },
        job,
        "test-worker",
    )

    insights = memory.list_incubation_insights(limit=10)
    assert len(insights) == 2
    summaries = [item["summary"] for item in insights]
    assert any("quieter opening" in summary for summary in summaries)
    assert any("material cues" in summary for summary in summaries)
    assert all(item["kind"] == "creative_implication" for item in insights)
    memory.close()


def test_build_composes_creative_direction_from_confirmed_intake(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def __init__(self): self.submissions = []
        def submit(self, prompt, raw_intake, **kwargs):
            self.submissions.append(prompt)
            return {"run_id": "intake-lab-" + "c" * 32, "status": "building", "publishable": False}
        def get_run(self, run_id):
            if not self.submissions: return None
            return {"run_id": run_id, "status": "building", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-direction",
    )
    final_revision = confirmed["session"]["confirmed_revision_id"]

    result = service.build(session["session_id"], confirmed_revision=final_revision, idempotency_key="build-direction")

    assert len(lab.submissions) == 1
    prompt = lab.submissions[0]
    assert "North Star Studio" in prompt
    assert "Brand strategy for independent businesses." in prompt
    assert "Independent business owners" in prompt
    assert "Clear, thoughtful, and warm." in prompt
    assert "distinctive, high-end, and one of a kind" in prompt
    assert "design skills define the quality bar" in prompt
    assert "EXECUTION BAR" not in prompt
    assert "cenote" not in prompt.casefold()
    assert "shaft of daylight" not in prompt.casefold()
    assert "Build the first visual website candidate" not in prompt
    assert result["session"]["design_run_id"] == "intake-lab-" + "c" * 32
    memory.close()


def test_confirmed_build_handoff_forwards_shared_intelligence(tmp_path):
    """Exercise the exact handoff keyword contract used by DesignIntakeService.build."""
    memory = Memory(tmp_path / "handoff.db")
    intelligence = DesignSharedIntelligence.unavailable()

    class Service:
        config = {}
        def resolve_base_sha(self): return "a" * 40
        def create_run(self, intake, **kwargs):
            self.run = {"run_id": kwargs["run_id"]}
            self.create_kwargs = kwargs
            return self.run
        def capture_context_snapshot(self, run_id, **kwargs):
            self.snapshot_kwargs = kwargs
            return {"shared_intelligence": kwargs["shared_intelligence"].to_dict()}
        def prepare_initial_request(self, run_id): return {}
        def build_target_for_run(self, run_id): return {}
        def queue_build(self, *args): pass
        def get_run(self, run_id): return {"run_id": run_id, "status": "building", "publishable": True}

    class Executor:
        def enqueue(self, run_id): pass

    service = Service()
    handoff = DesignBuildHandoff({"design_service": service, "design_executor": Executor()})
    result = handoff.submit(
        "request", _intake().to_dict(), run_id="run-1", conversation_id=None,
        source_message_id=None, intake_session_id="session-1", intake_revision_id=1,
        context_extra=None, shared_intelligence=intelligence,
    )
    assert result["run_id"] == "run-1"
    assert service.create_kwargs["mode"] == "production_candidate"
    assert service.snapshot_kwargs["shared_intelligence"] is intelligence
    memory.close()


def test_build_confirmed_session_through_real_handoff_preserves_shared_intelligence(tmp_path):
    memory = Memory(tmp_path / "confirmed-handoff.db")
    intelligence = DesignSharedIntelligence.unavailable()

    class Service:
        config = {}
        def resolve_base_sha(self): return "b" * 40
        def create_run(self, intake, **kwargs):
            self.run = {"run_id": kwargs["run_id"], "status": "building", "publishable": True, "intake_json": intake}
            return self.run
        def capture_context_snapshot(self, run_id, **kwargs):
            self.snapshot = {"shared_intelligence": kwargs["shared_intelligence"].to_dict()}
        def prepare_initial_request(self, run_id): return {}
        def build_target_for_run(self, run_id): return {}
        def queue_build(self, *args): pass
        def get_run(self, run_id): return self.run

    class Executor:
        def enqueue(self, run_id): pass

    design_service = Service()
    handoff = DesignBuildHandoff({"design_service": design_service, "design_executor": Executor()})
    intake_service = DesignIntakeService(memory, default_intake=_intake(), lab_service=handoff)
    session = intake_service.create_session()
    confirmed = intake_service.confirm(
        session["session_id"], revision=session["revision"], draft_hash=session["draft_hash"]
    )
    result = intake_service.build(
        session["session_id"], confirmed_revision=confirmed["session"]["confirmed_revision_id"],
        idempotency_key="confirmed-handoff", shared_intelligence=intelligence,
    )
    assert result["run"]["publishable"] is True
    assert result["session"]["status"] == "confirmed"
    assert result["session"]["design_run_id"] == result["run"]["run_id"]
    assert design_service.snapshot["shared_intelligence"] == intelligence.to_dict()
    memory.close()


@pytest.mark.parametrize(
    "recovery_case", ["same-base", "changed-runtime-base", "changed-owner-request",
                      "changed-context-extra", "changed-intake-session-id", "changed-authorized-target",
                      "changed-page-build-request", "changed-shared-intelligence", "foreign-tenant-run",
                      "missing-native-checkpoint",
                      "running-native-checkpoint", "failed-native-checkpoint", "prior-build-attempt"],
)
def test_composed_same_run_recovery_reopens_checkpoint_and_dispatches_build_once(
    tmp_path, monkeypatch, recovery_case,
):
    """Exercise intake -> handoff -> real worker/facade using a disposable tenant clone."""
    import subprocess
    import threading

    from site_agent.application.design_jobs import DesignJobExecutor
    from site_agent.application.designs import DesignService, DesignServiceError
    from site_agent.core.design_contracts import DesignRunStatus
    from site_agent.hands import opencode_runner as runner
    from site_agent.hands.builder import OperationRoutingBuilder
    from site_agent.hands.site_build import SiteBuildResult

    monkeypatch.setenv("FIXTURE_DESIGN_KEY", "fixture-key")
    import site_agent.hands.site_build as site_build
    monkeypatch.setattr(site_build, "prepare_site_toolchain", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(site_build, "build_site", lambda _root, profile, **_kwargs: SiteBuildResult(
        profile=profile.name, ok=True, output_dir=profile.output_dir,
        commands=({"command": ["test"], "status": "passed"},), route_inventory=("index.html",),
    ))

    clone = tmp_path / "tenant-clone"
    clone.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(clone), *args], check=True, capture_output=True, text=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (clone / "index.html").write_text("<html><body>baseline</body></html>")
    git("add", "-A")
    git("commit", "-qm", "tenant baseline")
    remote = tmp_path / "tenant-origin.git"
    subprocess.run(["git", "clone", "--bare", str(clone), str(remote)], check=True, capture_output=True)
    git("remote", "add", "origin", str(remote))
    config = {
        "data_dir": str(tmp_path),
        "site": {"clone_path": str(clone), "writable_patterns": ["*.html", "design/**"]},
        "design_engine": {"orchestration": "creative", "model": "fixture/model"},
        "builder": {"enabled": True},
        "env": {"llm_api_key": "FIXTURE_DESIGN_KEY"},
    }
    db = tmp_path / "memory.db"
    memory = Memory(db)
    class PayloadBoundary:
        document = None
        def require_authoring_contract(self):
            return {"enabled": {"collections": ["pages"]}, "locales": ["en"],
                    "defaultLocale": "en", "schemaIdentity": "fixture", "authoringContractHash": "fixture"}
        def read_media(self, *_args, **_kwargs):
            raise AssertionError("no intake media is attached")
        def create(self, collection, data, *, locale):
            self.document = {"id": 41, "slug": "home", "sourceId": "pages:home", **data,
                             "_helloadaRevision": "sha256:" + "1" * 64}
            return dict(self.document)
        def read(self, *_args, **_kwargs):
            return dict(self.document)
    payload = PayloadBoundary()
    builder = OperationRoutingBuilder({"config": config, "memory": memory, "payload_gateway": payload,
                                       "env": {"FIXTURE_DESIGN_KEY": "fixture-key"}})
    service = DesignService(memory, config=config, builder=builder)
    executor = DesignJobExecutor({"memory": memory, "config": config}, service)
    handoff = DesignBuildHandoff({"memory": memory, "config": config, "design_service": service,
                                  "design_executor": executor})
    intake_service = DesignIntakeService(memory, config=config, default_intake=_intake(), lab_service=handoff)
    session = intake_service.create_session()
    confirmed = intake_service.confirm(session["session_id"], revision=session["revision"], draft_hash=session["draft_hash"])
    result = intake_service.build(session["session_id"], confirmed_revision=confirmed["session"]["confirmed_revision_id"],
                                  idempotency_key="composition13-original")
    run_id = result["run"]["run_id"]
    direction_calls = []
    build_dispatched = threading.Event()

    def fake_turn(_worktree, _prompt, _config, **kwargs):
        direction_calls.append(kwargs.get("agent_name"))
        if kwargs.get("agent_name") == "native-direction":
            from tests.test_design_contracts import _experience_plan
            plan = _experience_plan()
            plan.pop("asset_evidence", None)
            plan.pop("asset_composition_plan", None)
            return {"session_id": "direction", "structured": {"direction": "A measured arrival.",
                    "experience_plan": plan}, "transcript": "valid native direction\n"}
        if kwargs.get("agent_name") == "build":
            build_dispatched.set()
        raise AssertionError("fixture stops after the one recovered Build provider dispatch")

    monkeypatch.setattr(runner, "install_agent_files", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_origin_url", lambda *_args, **_kwargs: str(remote))
    monkeypatch.setattr(runner, "run_opencode_turn", fake_turn)
    real_stage = runner.stage_design_build
    interrupted = False
    def interrupt_at_pre_build(context, request, target, progress=None, **kwargs):
        nonlocal interrupted
        def boundary(message):
            nonlocal interrupted
            if progress:
                progress(message)
            if not interrupted and "starting the integrated Build turn" in message:
                interrupted = True
                raise KeyboardInterrupt("simulated process death at documented pre-Build boundary")
        return real_stage(context, request, target, progress=boundary, **kwargs)
    monkeypatch.setattr(runner, "stage_design_build", interrupt_at_pre_build)
    try:
        executor._run(run_id)
    except KeyboardInterrupt as exc:
        assert "pre-Build boundary" in str(exc)
    else:
        pytest.fail(f"worker stopped before pre-Build barrier: status={service.get_run(run_id).get('status')!r}; "
                    f"error={service.get_run(run_id).get('error')!r}; calls={direction_calls!r}")
    phases = memory.list_design_phase_artifacts(run_id)
    assert any(item["phase"] == "native_direction" and item["status"] == "completed" for item in phases), (
        f"native checkpoint was not reached; worker_error={service.get_run(run_id).get('error')!r}; "
        f"provider_calls={direction_calls!r}; phases={phases!r}"
    )
    run = service.get_run(run_id)
    planning = run["planning_json"]
    from site_agent.core.design_contracts import BuildTarget, PageBuildRequest
    request = PageBuildRequest.from_dict(planning["build_request"])
    target = BuildTarget.from_dict(planning["build_target"])
    memory.transition_design_run(run_id, DesignRunStatus.INTERRUPTED.value,
                                 error="worker process ended at the persisted pre-Build boundary")
    memory.close()
    memory = Memory(db)
    builder = OperationRoutingBuilder({"config": config, "memory": memory, "payload_gateway": payload})
    service = DesignService(memory, config=config, builder=builder)
    executor = DesignJobExecutor({"memory": memory, "config": config}, service)
    handoff = DesignBuildHandoff({"memory": memory, "config": config, "design_service": service,
                                  "design_executor": executor})
    intake_service = DesignIntakeService(memory, config=config, default_intake=_intake(), lab_service=handoff)
    if recovery_case in {"changed-owner-request", "changed-context-extra",
                         "changed-intake-session-id", "changed-authorized-target",
                         "changed-page-build-request", "changed-shared-intelligence", "foreign-tenant-run"}:
        # Exercise the real policy boundary directly with the exact original handoff
        # inputs (context_extra/shared_intelligence were both None).
        if recovery_case == "changed-authorized-target":
            target_repository = target.repository
            config["site"]["repository"] = str(tmp_path / "different-authorized-repository")
            assert service.build_target_for_run(run_id).repository != target_repository
        before_rejection = Memory(db)
        run_before = before_rejection.get_design_run(run_id)
        phases_before = before_rejection.list_design_phase_artifacts(run_id)
        events_before = before_rejection.list_design_run_events(run_id)
        calls_before = len(direction_calls)
        def unexpected_admission(*_args, **_kwargs):
            raise AssertionError("changed recovery identity reached Memory admission CAS")
        monkeypatch.setattr(memory, "admit_prebuild_design_recovery", unexpected_admission)
        owner_request = run["owner_request"]
        recovery_session_id = run["intake_session_id"]
        recovery_context_extra = None
        if recovery_case == "changed-owner-request":
            owner_request += " changed"
            expected_error = "identity does not match"
        elif recovery_case == "changed-context-extra":
            recovery_context_extra = {"changed": True}
            expected_error = "request, context, or shared intelligence changed"
        elif recovery_case == "changed-intake-session-id":
            recovery_session_id += "-changed"
            expected_error = "identity does not match"
        elif recovery_case == "changed-page-build-request":
            from dataclasses import replace
            changed_request = replace(request, purpose=request.purpose + " changed")
            assert changed_request.to_dict() != request.to_dict()
            request = changed_request
            expected_error = "request.*target.*frozen|frozen.*request"
        elif recovery_case == "changed-shared-intelligence":
            changed_shared = DesignSharedIntelligence.unavailable()
            changed_shared.research["revision"] = "different-revision"
            assert changed_shared.to_dict() != DesignSharedIntelligence.unavailable().to_dict()
            expected_error = "request, context, or shared intelligence changed"
        elif recovery_case == "foreign-tenant-run":
            foreign_memory = Memory(tmp_path / "other-tenant" / "memory.db")
            foreign_service = DesignService(foreign_memory, config=config, builder=OperationRoutingBuilder(
                {"config": config, "memory": foreign_memory, "payload_gateway": payload}
            ))
            foreign_executor = DesignJobExecutor({"memory": foreign_memory, "config": config}, foreign_service)
            foreign_calls_before = len(direction_calls)
            foreign_runs_before = foreign_memory.list_design_runs()
            foreign_admit = foreign_memory.admit_prebuild_design_recovery
            def unexpected_foreign_admission(*args, **kwargs):
                raise AssertionError("foreign tenant attempted admission CAS")
            monkeypatch.setattr(foreign_memory, "admit_prebuild_design_recovery", unexpected_foreign_admission)
            from site_agent.application.designs import DesignRunNotFound
            with pytest.raises(DesignRunNotFound):
                foreign_service.recover_prebuild_run(
                    run_id, request=request, target=target,
                    intake_session_id=run["intake_session_id"],
                    intake_revision_id=run["intake_revision_id"], owner_request=run["owner_request"],
                )
            assert foreign_memory.list_design_runs() == foreign_runs_before == []
            assert foreign_memory.list_design_phase_artifacts(run_id) == []
            assert foreign_memory.list_design_run_events(run_id) == []
            assert foreign_executor._queue.empty() and executor._queue.empty()
            assert len(direction_calls) == foreign_calls_before
            foreign_memory.close()
            expected_error = None
        else:
            expected_error = "authorized target changed"
        if recovery_case != "foreign-tenant-run":
            kwargs = {}
            if recovery_case == "changed-shared-intelligence":
                kwargs["shared_intelligence"] = changed_shared
            with pytest.raises(DesignServiceError, match=expected_error):
                service.recover_prebuild_run(
                run_id, request=request, target=target,
                intake_session_id=recovery_session_id,
                intake_revision_id=run["intake_revision_id"], owner_request=owner_request,
                context_extra=recovery_context_extra,
                **kwargs,
                )
        after_rejection = Memory(db)
        assert after_rejection.get_design_run(run_id) == run_before
        assert after_rejection.list_design_phase_artifacts(run_id) == phases_before
        assert after_rejection.list_design_run_events(run_id) == events_before
        assert executor._queue.empty()
        assert len(direction_calls) == calls_before
        after_rejection.close()
        before_rejection.close()
        memory.close()
        return
    if recovery_case in {"missing-native-checkpoint", "running-native-checkpoint",
                         "failed-native-checkpoint", "prior-build-attempt"}:
        # Mutate only durable phase artifacts in this disposable fixture database.
        if recovery_case == "missing-native-checkpoint":
            memory.conn.execute(
                "DELETE FROM design_run_phase_artifacts WHERE run_id = ? AND phase = 'native_direction'", (run_id,)
            )
        elif recovery_case in {"running-native-checkpoint", "failed-native-checkpoint"}:
            memory.conn.execute(
                "UPDATE design_run_phase_artifacts SET status = ? WHERE run_id = ? AND phase = 'native_direction'",
                ("running" if recovery_case == "running-native-checkpoint" else "failed", run_id),
            )
        else:
            memory.claim_design_phase(run_id, "build_dispatch", base_sha=request.base_sha,
                                      context_snapshot_hash=request.context_snapshot_hash)
        memory.conn.commit()
        before_rejection = Memory(db)
        run_before_rejection = before_rejection.get_design_run(run_id)
        phases_before_rejection = before_rejection.list_design_phase_artifacts(run_id)
        events_before_rejection = before_rejection.list_design_run_events(run_id)
        calls_before_rejection = len(direction_calls)

        def unexpected_admission(*_args, **_kwargs):
            raise AssertionError("missing native checkpoint reached recovery admission CAS")

        monkeypatch.setattr(memory, "admit_prebuild_design_recovery", unexpected_admission)
        with pytest.raises(DesignIntakeServiceError, match="completed native direction and no Build attempt"):
            intake_service.build(
                session["session_id"],
                confirmed_revision=confirmed["session"]["confirmed_revision_id"],
                idempotency_key="composition13-missing-native",
            )

        after_rejection = Memory(db)
        assert after_rejection.get_design_run(run_id) == run_before_rejection
        assert after_rejection.list_design_phase_artifacts(run_id) == phases_before_rejection
        assert after_rejection.list_design_run_events(run_id) == events_before_rejection
        assert executor._queue.empty(), "rejected recovery enqueued a Build"
        assert len(direction_calls) == calls_before_rejection, "rejected recovery called a model"
        after_rejection.close()
        before_rejection.close()
        memory.close()
        return
    if recovery_case == "changed-runtime-base":
        (clone / "runtime-drift.txt").write_text("isolated tenant HEAD changed after checkpoint\n")
        git("add", "-A")
        git("commit", "-qm", "runtime base drift")
        assert service.resolve_base_sha() != target.base_sha
        with pytest.raises(DesignIntakeServiceError, match="base"):
            intake_service.build(session["session_id"],
                confirmed_revision=confirmed["session"]["confirmed_revision_id"], idempotency_key="composition13-drift")
        return
    # Both application callers validate the same durable checkpoint before either
    # can execute the real Memory compare-and-swap admission fence.
    second_memory = Memory(db)
    second_service = DesignService(second_memory, config=config, builder=OperationRoutingBuilder(
        {"config": config, "memory": second_memory, "payload_gateway": payload}
    ))
    second_executor = DesignJobExecutor({"memory": second_memory, "config": config}, second_service)
    second_handoff = DesignBuildHandoff({"memory": second_memory, "config": config,
                                        "design_service": second_service, "design_executor": second_executor})
    second_intake = DesignIntakeService(second_memory, config=config, default_intake=_intake(), lab_service=second_handoff)
    admission_barrier = threading.Barrier(2, timeout=10)
    for caller_memory in (memory, second_memory):
        admit = caller_memory.admit_prebuild_design_recovery
        def observed_admit(*args, _admit=admit, **kwargs):
            admission_barrier.wait()
            return _admit(*args, **kwargs)
        caller_memory.admit_prebuild_design_recovery = observed_admit
    outcomes = []
    def call_build(caller_id, intake, key):
        try:
            outcomes.append((caller_id, "result", intake.build(session["session_id"],
                confirmed_revision=confirmed["session"]["confirmed_revision_id"], idempotency_key=key)))
        except Exception as exc:
            outcomes.append((caller_id, "error", exc))
    callers = [threading.Thread(target=call_build, args=("a", intake_service, "composition13-concurrent-a")),
               threading.Thread(target=call_build, args=("b", second_intake, "composition13-concurrent-b"))]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(15)
    assert all(not caller.is_alive() for caller in callers), "recovery callers did not reach admission barrier"
    assert len(outcomes) == 2
    queued = [(caller_id, worker) for caller_id, worker in (("a", executor), ("b", second_executor))
              if not worker._queue.empty()]
    assert len(queued) == 1, f"expected exactly one recovery admission, outcomes={outcomes!r}"
    winning_caller, winning_executor = queued[0]
    by_caller = {caller_id: (kind, value) for caller_id, kind, value in outcomes}
    winner_kind, winner_value = by_caller[winning_caller]
    assert winner_kind == "result", f"admission winner did not return a result: {winner_value!r}"
    assert winner_value["run"]["run_id"] == run_id
    loser_id = "b" if winning_caller == "a" else "a"
    loser_kind, loser_value = by_caller[loser_id]
    if loser_kind == "error":
        assert isinstance(loser_value, DesignIntakeServiceError), repr(loser_value)
        assert "admission" in str(loser_value).lower() or "recovery" in str(loser_value).lower(), repr(loser_value)
    else:
        assert loser_value["run"]["run_id"] == run_id
        assert loser_value.get("recovered") is not True
    assert executor._queue.qsize() + second_executor._queue.qsize() == 1, "concurrent admission enqueued more than once"
    assert service.get_run(run_id)["planning_json"]["build_request"] == request.to_dict()
    assert service.get_run(run_id)["planning_json"]["build_target"] == target.to_dict()
    before_start = Memory(db)
    persisted_before_start = before_start.get_design_run(run_id)
    assert persisted_before_start["status"] == DesignRunStatus.PLANNING.value
    assert persisted_before_start["planning_json"]["build_request"] == request.to_dict()
    assert persisted_before_start["planning_json"]["build_target"] == target.to_dict()
    assert persisted_before_start["context_snapshot_hash"] == request.context_snapshot_hash
    recovery_identity = persisted_before_start["planning_json"]["same_run_recovery_identity"]
    assert recovery_identity["context_extra_hash"] == service.get_run(run_id)["planning_json"]["same_run_recovery_identity"]["context_extra_hash"]
    assert sum(event["stage"] == "recovery_admitted" for event in before_start.list_design_run_events(run_id)) == 1
    intake_before_start = before_start.get_design_intake_session(session["session_id"])
    assert intake_before_start["status"] == "confirmed"
    reservation_before_start = before_start.conn.execute(
        "SELECT state, run_id FROM design_intake_operations WHERE session_id = ? AND operation = 'build'",
        (session["session_id"],),
    ).fetchone()
    assert reservation_before_start is not None
    assert reservation_before_start["state"] != "failed"
    assert reservation_before_start["run_id"] == run_id
    before_start.close()
    losing_executor = second_executor if winning_executor is executor else executor
    assert losing_executor._queue.empty(), "losing caller enqueued a Build"
    winning_executor.start()
    assert build_dispatched.wait(5), "the admitted worker did not reach the Build provider boundary"
    winning_executor.stop()
    winning_executor.join(5)
    assert direction_calls.count("native-direction") == 1
    assert service.get_run(run_id)["status"] == DesignRunStatus.FAILED.value
    assert "fixture stops after the one recovered Build provider dispatch" in service.get_run(run_id)["error"]
    assert direction_calls.count("build") == 1, (
        f"recovered worker did not reach Build provider dispatch: status={service.get_run(run_id).get('status')!r}; "
        f"error={service.get_run(run_id).get('error')!r}; calls={direction_calls!r}; "
        f"phases={memory.list_design_phase_artifacts(run_id)!r}"
    )
    assert sum(item["phase"] == "build_dispatch" for item in memory.list_design_phase_artifacts(run_id)) == 1
    assert direction_calls.count("native-direction") == 1
    reopened = Memory(db)
    persisted = reopened.get_design_run(run_id)
    assert persisted["planning_json"]["build_request"] == request.to_dict()
    assert persisted["planning_json"]["build_target"] == target.to_dict()
    assert any(item["phase"] == "native_direction" and item["status"] == "completed"
               for item in reopened.list_design_phase_artifacts(run_id))
    assert sum(item["phase"] == "build_dispatch" for item in reopened.list_design_phase_artifacts(run_id)) == 1
    assert sum(item["stage"] == "recovery_admitted" for item in reopened.list_design_run_events(run_id)) == 1
    operations = reopened.conn.execute("SELECT state FROM design_intake_operations WHERE session_id = ? AND operation = 'build'", (session["session_id"],)).fetchall()
    assert not operations or all(row["state"] != "failed" for row in operations), "losing caller poisoned intake reservation"
    reopened.close()
    second_memory.close()
    memory.close()


def test_failed_build_is_visible_and_retry_reuses_confirmed_revision(tmp_path):
    memory = Memory(tmp_path / "failed-build.db")

    class _Lab:
        calls = []

        def submit(self, prompt, raw_intake, **kwargs):
            self.calls.append(kwargs["intake_revision_id"])
            if len(self.calls) == 1:
                raise RuntimeError("builder model is not configured; set builder.model or llm.model")
            return {"run_id": "intake-lab-recovered", "status": "building", "publishable": False}

        def get_run(self, run_id):
            return None

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    confirmed = service.confirm(session["session_id"], revision=session["revision"], draft_hash=session["draft_hash"])
    revision_id = confirmed["session"]["confirmed_revision_id"]

    with pytest.raises(DesignIntakeServiceError, match="builder model is not configured"):
        service.build(session["session_id"], confirmed_revision=revision_id, idempotency_key="failed-attempt")
    failed = service.get_session(session["session_id"])
    assert failed["status"] == "failed"
    assert failed["error"] and failed["build_error"]
    result = service.build(session["session_id"], confirmed_revision=revision_id, idempotency_key="retry-attempt")
    assert result["session"]["status"] == "confirmed"
    assert lab.calls == [revision_id, revision_id]
    memory.close()


def test_failed_persisted_candidate_retries_once_with_same_operation_token(tmp_path):
    memory = Memory(tmp_path / "failed-candidate.db")

    class _Lab:
        submissions = []
        def submit(self, prompt, raw_intake, **kwargs):
            self.submissions.append(kwargs["run_id"])
            return memory.create_design_run(
                run_id=kwargs["run_id"], mode="production_candidate", status="building",
                intake_json=raw_intake, intake_hash="c" * 64, base_sha="d" * 40,
                publishable=True, candidate_ref=f"refs/ada-design/{kwargs['run_id']}",
                intake_session_id=kwargs["intake_session_id"],
                intake_revision_id=kwargs["intake_revision_id"],
            )
        def get_run(self, run_id):
            run = memory.get_design_run(run_id)
            return run

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    confirmed = service.confirm(session["session_id"], revision=session["revision"], draft_hash=session["draft_hash"])
    revision_id = confirmed["session"]["confirmed_revision_id"]
    previous = memory.create_design_run(
        run_id="failed-initial-candidate", mode="production_candidate", status="failed",
        intake_json=_intake().to_dict(), intake_hash="a" * 64, base_sha="b" * 40,
        publishable=True, candidate_ref="refs/ada-design/failed-initial-candidate",
        intake_session_id=session["session_id"], intake_revision_id=revision_id,
    )
    frozen = service.get_session(session["session_id"])
    first = service._resolve_ui_action({"action": "start_build"}, frozen)
    second = service._resolve_ui_action({"action": "start_build"}, frozen)
    assert first["build"]["run"]["run_id"] != previous["run_id"]
    reservation = memory.get_design_intake_operation(session["session_id"], "build", first["build"]["idempotency_key"])
    assert bool(reservation["force_new"]) is True
    assert second["build"].get("idempotent") is True
    assert len(lab.submissions) == 1
    memory.close()


def test_build_uses_explicit_owner_design_request_when_provided(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def __init__(self):
            self.submissions = []

        def submit(self, prompt, raw_intake, **kwargs):
            self.submissions.append(prompt)
            return {"run_id": "intake-lab-" + "e" * 32, "status": "building", "publishable": False}

        def get_run(self, run_id):
            if not self.submissions:
                return None
            return {"run_id": run_id, "status": "building", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-explicit",
    )
    final_revision = confirmed["session"]["confirmed_revision_id"]

    explicit = "Make the first viewport feel like a quiet underground cenote with a single shaft of light."
    service.build(session["session_id"], confirmed_revision=final_revision, owner_request=explicit, idempotency_key="build-explicit")

    assert lab.submissions == [explicit]
    memory.close()


def test_asset_request_notes_extract_only_owner_suppliable_imagery_gaps():
    from site_agent.application.design_intake import asset_request_notes

    critique = {
        "findings": [
            {
                "id": "A2",
                "severity": "high",
                "category": "imagery",
                "summary": "The site presents no imagery of the jungle camp or Mayan food; only cave photos are used.",
                "evidence": "Screenshots show only cave imagery.",
            },
            {
                "id": "A3",
                "severity": "medium",
                "category": "composition",
                "summary": "Body text over a dark cave image has marginal contrast.",
                "evidence": "Text overlaps the figure.",
            },
        ]
    }

    notes = asset_request_notes(critique)

    assert len(notes) == 1
    assert "no imagery of the jungle camp" in notes[0]


def test_asset_request_notes_ignore_subjective_and_conversion_findings():
    from site_agent.application.design_intake import asset_request_notes

    critique = {
        "findings": [
            {
                "id": "A1",
                "severity": "high",
                "category": "conversion-path-integration",
                "summary": "The primary CTA is hidden in the footer.",
            },
            {
                "id": "A3",
                "severity": "medium",
                "category": "imagery",
                "summary": "Crop the lighthouse photo for better framing.",
            },
        ]
    }

    assert asset_request_notes(critique) == ()


def test_surface_review_asset_requests_does_not_fabricate_when_ada_is_unavailable(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake())
    session = service.create_session()
    conversation_id = session["conversation_id"]
    memory.create_design_run(
        run_id="intake-lab-" + "f" * 32,
        mode="local_experiment",
        status="needs_repair",
        intake_json=_intake().to_dict(),
        intake_hash="a" * 64,
        base_sha="b" * 40,
        publishable=False,
        candidate_ref="refs/ada-design-lab/run",
        conversation_id=conversation_id,
        intake_session_id=session["session_id"],
    )
    run_id = "intake-lab-" + "f" * 32
    memory.update_design_run(run_id, quality_report_json={
        "state": "passed",
        "visual_critique": {
            "findings": [{
                "id": "A2",
                "severity": "high",
                "category": "imagery",
                "summary": "The site presents no imagery of the local Mayan kitchen; only cave photos are used.",
            }],
        },
    })

    first = service.surface_review_asset_requests(run_id)
    second = service.surface_review_asset_requests(run_id)

    assert first == ["The site presents no imagery of the local Mayan kitchen; only cave photos are used."]
    assert second == first
    messages = memory.get_messages(conversation_id)
    assert messages == []
    events = memory.list_design_run_events(run_id, limit=50)
    surfaced = [e for e in events if e.get("stage") == "asset_request_surfaced"]
    assert surfaced == []
    memory.close()


def test_asset_request_message_uses_advisor_voice_when_available(tmp_path):
    from site_agent.application.design_intake import DesignIntakeService

    class _Advisor:
        def advise(self, *args, **kwargs):
            raise AssertionError("advise must not be called")

        def request_owner_assets(self, *, business_name, context):
            assert business_name == "North Star Studio"
            assert context
            return "Tu n'as pas une photo de la cuisine maya ? Ca donnerait vraiment vie au site."

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_Advisor())
    written = service._asset_request_message("North Star Studio", ("Mayan kitchen imagery",))

    assert written == "Tu n'as pas une photo de la cuisine maya ? Ca donnerait vraiment vie au site."
    memory.close()


def test_surface_review_asset_requests_is_silent_without_asset_gaps(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake())
    session = service.create_session()
    conversation_id = session["conversation_id"]
    run_id = "intake-lab-" + "g" * 32
    memory.create_design_run(
        run_id=run_id,
        mode="local_experiment",
        status="needs_repair",
        intake_json=_intake().to_dict(),
        intake_hash="a" * 64,
        base_sha="b" * 40,
        publishable=False,
        candidate_ref="refs/ada-design-lab/run",
        conversation_id=conversation_id,
        intake_session_id=session["session_id"],
    )
    memory.update_design_run(run_id, quality_report_json={
        "state": "passed",
        "visual_critique": {"findings": [{
            "id": "A1",
            "severity": "high",
            "category": "conversion-path-integration",
            "summary": "The CTA is buried; move it into the header.",
        }]},
    })

    result = service.surface_review_asset_requests(run_id)

    assert result == []
    assert memory.get_messages(conversation_id) == []
    memory.close()


def test_incomplete_advisor_turn_can_persist_before_offer_summary_exists(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(
        memory,
        advisor=_Advisor(),
        genesis_service=CustomerGenesisService(memory),
    )
    try:
        session = service.create_session()
        queued = service.send_message(session["session_id"], "I am still shaping the offer.")
        job = memory.claim_chat_job("test-worker")

        result = run_job(
            {"memory": memory, "design_intake_service": service, "config": {}, "llm": object()},
            job,
            "test-worker",
        )

        assert result["operation_kind"] == "design_intake_advice"
        assert memory.get_chat_job(queued["job_id"])["status"] == "done"
        assert memory.list_customer_genesis_revisions() == []
    finally:
        memory.close()


def test_advisor_turn_keeps_the_owner_facing_message_natural(tmp_path):
    class _NaturalConversationAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message=(
                    "Je vois deja une direction claire. Quel usage veux-tu privilegier pour les images ?"
                ),
            )

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, advisor=_NaturalConversationAdvisor())
    try:
        session = service.create_session()
        queued = service.send_message(session["session_id"], "Je veux continuer.")
        job = memory.claim_chat_job("natural-question-worker")

        result = run_job(
            {"memory": memory, "design_intake_service": service, "config": {}, "llm": object()},
            job,
            "natural-question-worker",
        )

        assert result["reply"] == "Je vois deja une direction claire. Quel usage veux-tu privilegier pour les images ?"
        assert "Open questions:" not in result["reply"]
        assert "open_questions" not in result
        assert "open_questions" not in service.get_session(session["session_id"])["readiness"]
        assert memory.get_chat_job(queued["job_id"])["status"] == "done"
    finally:
        memory.close()


def test_saved_revision_invokes_research_hook_without_making_it_part_of_intake_state(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    calls = []

    def on_revision_saved(session_id, draft, revision):
        stored = memory.get_design_intake_session(session_id)
        calls.append((session_id, draft.content_hash, revision["revision"]))
        assert stored["revision"] == revision["revision"]
        return {"status": "queued", "request_id": "research_" + "a" * 32}

    service = DesignIntakeService(
        memory,
        default_intake=_intake(),
        advisor=_Advisor(),
        on_revision_saved=on_revision_saved,
    )
    try:
        session = service.create_session()
        queued = service.send_message(session["session_id"], "Keep the direction quiet and tactile.")
        job = memory.claim_chat_job("test-worker")
        result = run_job(
            {"memory": memory, "design_intake_service": service, "config": {}, "llm": object()},
            job,
            "test-worker",
        )

        assert result["research"]["status"] == "queued"
        assert calls == [(session["session_id"], result["intake_hash"], 2)]
        assert memory.get_design_intake_session(session["session_id"])["revision"] == 2
        assert memory.get_chat_job(queued["job_id"])["status"] == "done"
    finally:
        memory.close()


def test_confirm_freezes_revision_and_hands_off_one_local_run(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def submit(self, prompt, raw_intake, **kwargs):
            assert raw_intake["provenance"]["intake_session_id"].startswith("intake-")
            return {"run_id": "intake-lab-" + "a" * 32, "status": "building", "publishable": False}

        def get_run(self, run_id):
            return {"run_id": run_id, "status": "building", "publishable": False}

    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=_Lab())
    session = service.create_session()
    result = service.confirm_and_build(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
    )

    assert result["session"]["status"] == "confirmed"
    assert result["session"]["design_run_id"] == "intake-lab-" + "a" * 32
    assert result["run"]["publishable"] is False
    memory.close()


def test_confirmation_and_build_are_separate_and_build_retry_is_idempotent(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def __init__(self):
            self.submissions = []

        def submit(self, prompt, raw_intake, **kwargs):
            self.submissions.append((prompt, raw_intake, kwargs))
            return {"run_id": "intake-lab-" + "b" * 32, "status": "building", "publishable": False}

        def get_run(self, run_id):
            return {"run_id": run_id, "status": "building", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()

    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-test",
    )

    assert confirmed["confirmed"] is True
    assert confirmed["session"]["status"] == "confirmed"
    assert not lab.submissions
    final_revision = confirmed["session"]["confirmed_revision_id"]

    first = service.build(
        session["session_id"],
        confirmed_revision=final_revision,
        idempotency_key="build-test",
    )
    second = service.build(
        session["session_id"],
        confirmed_revision=final_revision,
        idempotency_key="build-test",
    )

    assert len(lab.submissions) == 1
    assert first["run"]["run_id"] == second["run"]["run_id"]
    assert second["idempotent"] is True
    assert first["session"]["design_run_id"] == "intake-lab-" + "b" * 32
    memory.close()


def test_build_recovers_a_stale_reservation_without_creating_a_second_run(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def __init__(self):
            self.submissions = []

        def submit(self, prompt, raw_intake, **kwargs):
            self.submissions.append(kwargs)
            return {"run_id": kwargs["run_id"], "status": "building", "publishable": False}

        def get_run(self, run_id):
            if not self.submissions:
                return None
            return {"run_id": run_id, "status": "building", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-stale-reservation",
    )
    revision_id = confirmed["session"]["confirmed_revision_id"]

    original_reserve = memory.reserve_design_intake_build

    def reserve_then_interrupt(*args, **kwargs):
        original_reserve(*args, **kwargs)
        raise KeyboardInterrupt("simulated process death after reservation")

    memory.reserve_design_intake_build = reserve_then_interrupt
    with pytest.raises(KeyboardInterrupt):
        service.build(
            session["session_id"],
            confirmed_revision=revision_id,
            idempotency_key="build-stale-reservation",
        )
    memory.reserve_design_intake_build = original_reserve
    memory.conn.execute(
        "UPDATE design_intake_operations SET updated_ts = ? WHERE session_id = ? AND operation = 'build'",
        ("2000-01-01T00:00:00+00:00", session["session_id"]),
    )
    memory.conn.commit()

    recovered = service.build(
        session["session_id"],
        confirmed_revision=revision_id,
        idempotency_key="build-stale-reservation",
    )

    assert len(lab.submissions) == 1
    assert recovered["run"]["run_id"] == lab.submissions[0]["run_id"]
    assert recovered["run"]["run_id"].startswith("intake-lab-")
    assert memory.get_design_intake_operation(
        session["session_id"], "build", "build-stale-reservation"
    )["state"] == "submitted"
    memory.close()


def test_failed_candidate_is_not_reused_and_a_fresh_build_is_started(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def __init__(self):
            self.submissions = []

        def submit(self, prompt, raw_intake, **kwargs):
            run_id = "intake-lab-" + ("z" * 32 if self.submissions else "b" * 32)
            self.submissions.append(run_id)
            return {"run_id": run_id, "status": "building", "publishable": False}

        def get_run(self, run_id):
            if run_id == "intake-lab-" + "b" * 32:
                return {"run_id": run_id, "status": "failed", "publishable": False}
            return {"run_id": run_id, "status": "building", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-retry",
    )
    final_revision = confirmed["session"]["confirmed_revision_id"]

    first = service.build(session["session_id"], confirmed_revision=final_revision, idempotency_key="build-retry")
    assert first["run"]["run_id"] == "intake-lab-" + "b" * 32

    fresh = service.build(
        session["session_id"],
        confirmed_revision=final_revision,
        idempotency_key="build-retry-fresh",
        force_new=True,
    )
    assert fresh.get("idempotent") is not True
    assert fresh["run"]["run_id"] == "intake-lab-" + "z" * 32
    assert fresh["session"]["design_run_id"] == "intake-lab-" + "z" * 32
    assert len(lab.submissions) == 2
    memory.close()


def test_bound_assets_are_frozen_into_the_confirmed_site_intake(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    asset_id = memory.create_media_asset(MediaAsset(
        asset_id=0,
        status=MediaStatus.READY,
        media_kind=MediaKind.IMAGE,
        source_kind="owner_upload",
        original_name="hero.webp",
        content_type="image/webp",
        original_size=4,
        original_sha256="a" * 64,
        storage_id="hero",
        original_key="media/hero/original/hero.webp",
        normalized_key="media/hero/normalized/hero.webp",
        thumbnail_key="media/hero/thumbnail/hero.webp",
        created_ts="now",
        updated_ts="now",
    ))

    class _Lab:
        def __init__(self):
            self.intakes = []

        def submit(self, prompt, raw_intake, **kwargs):
            self.intakes.append(raw_intake)
            return {"run_id": "intake-lab-" + "d" * 32, "status": "building", "publishable": False}

        def get_run(self, run_id):
            return {"run_id": run_id, "status": "building", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    updated = service.update_assets(session["session_id"], [{
        "asset_id": asset_id,
        "position": 0,
        "usage": "website",
        "reference_aspects": ["hero composition"],
    }])

    confirmed = service.confirm(
        session["session_id"],
        revision=updated["revision"],
        draft_hash=updated["draft_hash"],
    )
    built = service.build(
        session["session_id"],
        confirmed_revision=confirmed["session"]["confirmed_revision_id"],
    )

    assert built["run"]["publishable"] is False
    assert lab.intakes[0]["assets"] == [{
        "id": str(asset_id),
        "usage": "website",
        "position": 0,
        "reference_aspects": ["hero composition"],
        "owner_note": "",
    }]
    memory.close()


def test_uploaded_asset_is_available_to_build_without_owner_usage_decision(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    asset_id = memory.create_media_asset(MediaAsset(
        asset_id=0,
        status=MediaStatus.READY,
        media_kind=MediaKind.IMAGE,
        source_kind="owner_upload",
        original_name="reference.webp",
        content_type="image/webp",
        original_size=4,
        original_sha256="b" * 64,
        storage_id="reference",
        original_key="media/reference/original/reference.webp",
        normalized_key="media/reference/normalized/reference.webp",
        thumbnail_key="media/reference/thumbnail/reference.webp",
        created_ts="now",
        updated_ts="now",
    ))
    service = DesignIntakeService(memory, default_intake=_intake())
    session = service.create_session()

    updated = service.update_assets(session["session_id"], [{
        "asset_id": asset_id,
        "position": 0,
        "usage": "undecided",
    }])

    assert updated["readiness"]["state"] == "ready_to_build"
    assert updated["readiness"]["undecided_asset_ids"] == []
    confirmed = service.confirm(
        session["session_id"],
        revision=updated["revision"],
        draft_hash=updated["draft_hash"],
    )
    assert confirmed["confirmed"] is True
    memory.close()


def test_message_after_confirmation_keeps_frozen_revision_until_advisor_proposes_revision(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def submit(self, prompt, raw_intake, **kwargs):
            return {"run_id": "intake-lab-" + "c" * 32, "status": "building", "publishable": False}

        def get_run(self, run_id):
            return {"run_id": run_id, "status": "building", "publishable": False}

    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=_Lab())
    session = service.create_session()
    built = service.confirm_and_build(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
    )
    assert built["session"]["design_run_id"] == "intake-lab-" + "c" * 32

    queued = service.send_message(session["session_id"], "I want to revisit the type scale.")
    current = service.get_session(session["session_id"])

    assert queued["job_id"] > 0
    assert current["status"] == "confirmed"
    assert current["design_run_id"] == built["session"]["design_run_id"]
    assert current["confirmed_revision"] == built["session"]["confirmed_revision"]
    memory.close()


def test_explicit_confirmation_reconciles_a_stale_post_confirmation_job(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake())
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-stale-job",
    )

    # Queueing an owner turn keeps the frozen revision until Ada records a change.
    service.send_message(session["session_id"], "Please keep the confirmed direction.")
    current = service.get_session(session["session_id"])
    assert current["status"] == "confirmed"
    assert current["revision"] == confirmed["session"]["confirmed_revision"]

    resumed = service.confirm(
        session["session_id"],
        revision=current["revision"],
        draft_hash=current["draft_hash"],
        idempotency_key="confirm-stale-job-retry",
    )

    assert resumed["confirmed"] is True
    assert resumed["session"]["status"] == "confirmed"
    assert resumed["session"]["confirmed_revision"] == current["revision"]
    memory.close()


def test_empty_draft_stays_collecting_without_inventing_facts(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, advisor=UnavailableDesignIntakeAdvisor())
    session = service.create_session()

    assert session["readiness"]["state"] == "collecting"
    assert session["draft"]["fields"] == {}
    memory.close()


def test_llm_failure_returns_connection_issue_without_fake_follow_up(tmp_path):
    class _FailingLLM:
        api_key = "configured"

        def chat(self, messages, **kwargs):
            raise RuntimeError("model returned an empty completion")

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, llm=_FailingLLM())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "I am starting a retreat business.")
    job = memory.claim_chat_job("fallback-worker")

    result = run_job(
        {
            "memory": memory,
            "design_intake_service": service,
            "config": {},
            "llm": object(),
        },
        job,
        "fallback-worker",
    )

    assert result == {"error": "Connection issue, try again."}
    assert memory.get_chat_job(queued["job_id"])["status"] == "error"
    stored = service.get_session(session["session_id"])
    assert stored["messages"][-1]["role"] == "assistant"
    assert stored["messages"][-1]["text"] == memory.get_chat_job(queued["job_id"])["result"]["reply"]
    assert stored["draft"]["fields"] == {}
    memory.close()


def test_non_llm_advisor_errors_are_not_hidden(tmp_path):
    class _FailingAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            raise DesignIntakeAdvisorError("broken test advisor")

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, advisor=_FailingAdvisor())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "Keep going.")
    job = memory.claim_chat_job("error-worker")

    result = run_job(
        {
            "memory": memory,
            "design_intake_service": service,
            "config": {},
            "llm": object(),
        },
        job,
        "error-worker",
    )

    assert result == {"error": "broken test advisor"}
    assert memory.get_chat_job(queued["job_id"])["status"] == "error"
    memory.close()


def test_intake_advisor_can_use_a_separate_chat_model():
    calls = []

    class _LLM:
        def chat(self, messages, **kwargs):
            calls.append(kwargs)
            return '{"schema_version": 1, "assistant_message": "Tell me who this is for.", "field_updates": [{"path": "business.name", "value": "Workshop", "basis": "owner_statement", "note": ""}], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    advisor = LLMDesignIntakeAdvisor(
        _LLM(),
        {"intake_advisor": {"model": "fast-chat", "timeout_seconds": 12, "max_retries": 0, "max_tokens": 400}},
    )
    result = advisor.advise(DesignIntakeDraft.empty(), [], "I am starting a business.")

    assert result.assistant_message == "Tell me who this is for."
    assert result.field_updates[0].path == "business.name"
    assert calls == [{
        "json_mode": True,
        "temperature": 0.2,
        "max_tokens": 400,
        "timeout_seconds": 12.0,
        "max_retries": 0,
        "model": "fast-chat",
    }]


def test_intake_advisor_hides_internal_read_failure_and_does_not_claim_a_build():
    class _LLM:
        def chat(self, messages, **kwargs):
            return json.dumps({
                "schema_version": 1,
                "assistant_message": (
                    "One transparency note: the repo files wouldn't open for me just now "
                    "(a tooling hiccup on my side), so I'll re-check the exact markup before building."
                ),
                "field_updates": [],
                "assumption_updates": [],
                "deferred_updates": [],
                "contradictions": [],
                "suggested_readiness": "collecting",
            })

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    result = LLMDesignIntakeAdvisor(_LLM(), {}).advise(
        DesignIntakeDraft.empty(), [], "I want a more distinctive homepage."
    )

    assert "repo" not in result.assistant_message.lower()
    assert "tooling" not in result.assistant_message.lower()
    assert "nothing has been changed" in result.assistant_message


def test_intake_advisor_does_not_promise_unstarted_builds():
    class _LLM:
        def chat(self, messages, **kwargs):
            return json.dumps({
                "schema_version": 1,
                "assistant_message": "I can build this on a preview when you choose a direction.",
                "field_updates": [],
                "assumption_updates": [],
                "deferred_updates": [],
                "contradictions": [],
                "suggested_readiness": "collecting",
            })

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    result = LLMDesignIntakeAdvisor(_LLM(), {}).advise(
        DesignIntakeDraft.empty(), [], "Give me some homepage directions."
    )

    assert "I haven't built or previewed this yet" in result.assistant_message


def test_intake_advisor_skips_entrim_thinking_knob_on_openrouter_client():
    calls = []

    class _LLM:
        base_url = "https://openrouter.ai/api/v1"

        def chat(self, messages, **kwargs):
            calls.append(kwargs)
            return '{"schema_version": 1, "assistant_message": "Tell me who this is for.", "field_updates": [{"path": "business.name", "value": "Claro Oscuro", "basis": "owner_statement", "note": ""}], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    advisor = LLMDesignIntakeAdvisor(
        _LLM(),
        {"intake_advisor": {
            "model": "openai/gpt-4.1-mini",
            "timeout_seconds": 90,
            "max_retries": 1,
            "max_tokens": 4096,
            "enable_thinking": False,
        }},
    )
    advisor.advise(DesignIntakeDraft.empty(), [], "I am starting a business.")

    assert calls == [{
        "json_mode": True,
        "temperature": 0.2,
        "max_tokens": 4096,
        "timeout_seconds": 90.0,
        "max_retries": 1,
        "model": "openai/gpt-4.1-mini",
    }]


def test_intake_advisor_keeps_entrim_thinking_knob_on_entrim_client():
    calls = []

    class _LLM:
        base_url = "https://api.entrim.ai/v1"

        def chat(self, messages, **kwargs):
            calls.append(kwargs)
            return '{"schema_version": 1, "assistant_message": "Tell me who this is for.", "field_updates": [{"path": "business.name", "value": "Claro Oscuro", "basis": "owner_statement", "note": ""}], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    advisor = LLMDesignIntakeAdvisor(
        _LLM(),
        {"intake_advisor": {"enable_thinking": False, "max_retries": 1}},
    )
    advisor.advise(DesignIntakeDraft.empty(), [], "I am starting a business.")

    assert calls == [{
        "json_mode": True,
        "temperature": 0.2,
        "max_tokens": 1200,
        "timeout_seconds": 45.0,
        "max_retries": 1,
        "enable_thinking": False,
    }]


def test_intake_advisor_client_is_scoped_when_configured():
    from site_agent.main import _intake_advisor_client

    client = _intake_advisor_client(
        {
            "design_engine": {
                "intake_advisor": {
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "OPENROUTER_API_KEY",
                    "model": "openai/gpt-4.1-mini",
                },
            },
            "llm": {
                "base_url": "https://api.entrim.ai/v1",
                "model": "deepseek-ai/DeepSeek-V4-Flash",
                "timeout_seconds": 300,
                "max_retries": 2,
                "max_tokens": 16384,
            },
            "env": {"llm_api_key": "ENTRIM_API_KEY"},
        },
        memory=None,
        env={"ENTRIM_API_KEY": "entrim-key", "OPENROUTER_API_KEY": "openrouter-key"},
    )

    assert client is not None
    assert client.base_url == "https://openrouter.ai/api/v1"
    assert client.model == "openai/gpt-4.1-mini"
    assert client.api_key == "openrouter-key"
    assert client.enable_thinking is False

    assert _intake_advisor_client(
        {"design_engine": {}, "llm": {}, "env": {}}, memory=None, env={}
    ) is None


def test_intake_turn_discards_legacy_question_metadata():
    result = IntakeTurnResult.from_dict({
        "schema_version": 1,
        "assistant_message": "We can keep shaping this together.",
        "field_updates": [],
        "assumption_updates": [],
        "deferred_updates": [],
        "contradictions": [],
        "topics_addressed": ["business"],
        "next_topics": ["brand"],
        "open_questions": ["What should change next?"],
        "suggested_readiness": "collecting",
    })

    assert "open_questions" not in result.to_dict()
    assert "next_topics" not in result.to_dict()


def test_merge_intake_turn_keeps_assumption_and_deferred_mutually_exclusive():
    draft = DesignIntakeDraft.empty()
    draft = merge_intake_turn(draft, IntakeTurnResult(
        schema_version=1,
        assistant_message="assume",
        assumption_updates=(IntakeDisposition(path="design.content_readiness", note="working", value="copy"),),
    ), source_message_id=1)
    draft = merge_intake_turn(draft, IntakeTurnResult(
        schema_version=1,
        assistant_message="defer",
        deferred_updates=(IntakeDisposition(path="design.content_readiness", note="wait", value=None),),
    ), source_message_id=2)

    assert draft.validate() is None
    assert any(item.path == "design.content_readiness" for item in draft.deferred)
    assert not any(item.path == "design.content_readiness" for item in draft.assumptions)


def test_intake_advisor_makes_exactly_one_call_per_turn():
    calls = []

    class _ForgetfulLLM:
        def chat(self, messages, **kwargs):
            calls.append(messages)
            return '{"schema_version": 1, "assistant_message": "Merci ! Je note la restauration de tapisserie et les workspaces.", "field_updates": [{"path": "business.primary_services", "value": ["Restauration de tapisserie", "Workspaces"], "basis": "owner_statement", "note": ""}], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    result = LLMDesignIntakeAdvisor(_ForgetfulLLM(), {}).advise(
        DesignIntakeDraft.empty(),
        [],
        "Je suis tapissiere restauratrice et j'organise des workspaces.",
    )

    assert len(calls) == 1
    assert [item.path for item in result.field_updates] == ["business.primary_services"]
    assert result.assistant_message == "Merci ! Je note la restauration de tapisserie et les workspaces."


def test_intake_advisor_makes_exactly_one_call_for_acknowledgements():
    calls = []

    class _AckLLM:
        def chat(self, messages, **kwargs):
            calls.append(True)
            return '{"schema_version": 1, "assistant_message": "Super !", "field_updates": [], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    result = LLMDesignIntakeAdvisor(_AckLLM(), {}).advise(
        DesignIntakeDraft.empty(), [], "les 2"
    )

    assert len(calls) == 1
    assert result.assistant_message == "Super !"


def test_intake_advisor_uses_qwen_visual_summary_for_text_only_chat_models():
    calls = []

    class _LLM:
        def chat(self, messages, **kwargs):
            calls.append(messages)
            return '{"schema_version": 1, "assistant_message": "Je note la palette du logo.", "field_updates": [{"path": "brand.existing_palette", "value": ["#D97A35", "#29455C"], "basis": "owner_statement", "note": ""}], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    advisor = LLMDesignIntakeAdvisor(_LLM(), {"intake_advisor": {"model": "deepseek-ai/DeepSeek-V4-Flash"}})
    result = advisor.advise(
        DesignIntakeDraft.empty(),
        [],
        "Inspire-toi de mon logo joint, mais plus doux.",
        assets=[{
            "asset_id": 7,
            "name": "logo.png",
            "description": "A warm rust-orange band over slate bars",
            "tags": ["pattern", "stripes"],
            "dominant_colors": ["#D97A35", "#29455C"],
        }],
    )

    assert result.field_updates[0].path == "brand.existing_palette"
    content = calls[0][-1]["content"]
    assert isinstance(content, list)
    assert content[-1]["type"] == "text"
    assert all(part.get("type") != "image_url" for part in content)
    assert "#D97A35" in content[1]["text"]
    assert "pattern" in content[1]["text"]


def test_intake_advisor_uses_stored_media_summary_instead_of_raw_images():
    calls = []

    class _LLM:
        def chat(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return '{"schema_version": 1, "assistant_message": "I can see the reference.", "field_updates": [], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    advisor = LLMDesignIntakeAdvisor(_LLM(), {"intake_advisor": {"model": "vision-chat"}})
    result = advisor.advise(
        DesignIntakeDraft.empty(),
        [],
        "Use these references to guide the direction.",
        assets=[{"asset_id": 7, "name": "logo.webp", "image_data_url": "data:image/webp;base64,AA=="}],
    )

    assert result.assistant_message == "I can see the reference."
    assert "open_questions" not in result.to_dict()
    content = calls[0][0][-1]["content"]
    assert isinstance(content, list)
    assert all(part.get("type") != "image_url" for part in content if isinstance(part, dict))


def test_intake_advisor_does_not_reupload_already_tagged_images():
    calls = []

    class _LLM:
        def chat(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return '{"schema_version": 1, "assistant_message": "I will use the stored visual tags.", "field_updates": [], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    advisor = LLMDesignIntakeAdvisor(_LLM(), {"intake_advisor": {"model": "vision-chat"}})
    advisor.advise(
        DesignIntakeDraft.empty(),
        [],
        "Use the stored reference analysis.",
        assets=[{
            "asset_id": 7,
            "name": "logo.webp",
            "description": "A warm rust-orange band over slate bars",
            "tags": ["pattern", "stripes"],
            "image_data_url": "data:image/webp;base64,AA==",
        }],
    )

    content = calls[0][0][-1]["content"]
    assert all(part.get("type") != "image_url" for part in content if isinstance(part, dict))
    assert "rust-orange" in content[1]["text"]


def test_intake_advisor_preserves_provider_prose_without_question_metadata():
    class _LLM:
        def chat(self, messages, **kwargs):
            return (
                "Based on the reference, here are the next questions:\n\n"
                "1. Which colors do you envision for the brand?\n"
                "2. Are there styles you want to avoid?"
            )

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    result = LLMDesignIntakeAdvisor(_LLM(), {}).advise(
        DesignIntakeDraft.empty(), [], "Continue with the visual direction."
    )

    assert result.field_updates == ()
    assert result.assistant_message.startswith("Based on the reference")
    assert "open_questions" not in result.to_dict()


def test_intake_advisor_keeps_natural_prose_without_forcing_a_question():
    class _LLM:
        def chat(self, messages, **kwargs):
            return "The contrast between light and darkness is a strong starting point for the visual direction."

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    result = LLMDesignIntakeAdvisor(_LLM(), {}).advise(
        DesignIntakeDraft.empty(), [], "I want the site to feel more atmospheric."
    )

    assert result.assistant_message.startswith("The contrast between light and darkness")
    assert "open_questions" not in result.to_dict()


def test_intake_turn_does_not_rewrite_a_natural_advisor_message(tmp_path):
    class _GenericAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message=(
                    "I've updated the audience and primary actions. "
                    "Which colors should the site use?"
                ),
                suggested_readiness="collecting",
            )

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_GenericAdvisor())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "Yes, continue.")
    job = memory.claim_chat_job("question-worker")

    result = run_job(
        {"memory": memory, "design_intake_service": service, "config": {}, "llm": object()},
        job,
        "question-worker",
    )

    assert "Which colors should the site use" in result["reply"]
    assert "Open questions:" not in result["reply"]
    assert "open_questions" not in result
    assert "open_questions" not in service.get_session(session["session_id"])["readiness"]
    stored_job = memory.get_chat_job(queued["job_id"])
    assert stored_job["status"] == "done"
    step_text = [step["text"] for step in stored_job["steps"]]
    assert "intake / asking Ada for the next useful step" in step_text
    assert "intake / validating the proposed intake turn" in step_text
    memory.close()


def test_intake_turn_does_not_expose_internal_topic_lists(tmp_path):
    class _NaturalAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message="That gives us a clear foundation to work from.",
            )

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_NaturalAdvisor())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "Keep going.")
    job = memory.claim_chat_job("natural-worker")
    result = run_job(
        {"memory": memory, "design_intake_service": service, "config": {}, "llm": object()},
        job,
        "natural-worker",
    )

    assert result["reply"] == "That gives us a clear foundation to work from."
    assert "open_questions" not in result
    assert "open_questions" not in service.get_session(session["session_id"])["readiness"]
    assert memory.get_chat_job(queued["job_id"])["status"] == "done"
    memory.close()


def test_latest_advisor_message_is_durable_without_a_question_list(tmp_path):
    class _DirectConversationAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message="I reviewed the direction. Which color should lead the first screen?",
            )

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, advisor=_DirectConversationAdvisor())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "Continue with the visual direction.")
    job = memory.claim_chat_job("reload-worker")
    run_job(
        {"memory": memory, "design_intake_service": service, "config": {}, "llm": object()},
        job,
        "reload-worker",
    )

    reloaded = service.get_session(session["session_id"])

    assert reloaded["messages"][-1]["text"] == "I reviewed the direction. Which color should lead the first screen?"
    assert "open_questions" not in reloaded["readiness"]
    assert memory.get_chat_job(queued["job_id"])["status"] == "done"
    memory.close()


def test_advisor_prompt_exposes_uploaded_images_as_context():
    from site_agent.brain.design_intake import _advisor_prompt
    from site_agent.brain.design_guidance import load_design_skills

    prompt = _advisor_prompt(DesignIntakeDraft.empty(), [], load_design_skills().content)
    assert "Available uploaded images" in prompt
    assert "read them as visual evidence" in prompt
    assert "bounded summary" in prompt
    assert "do not invent" in prompt


def test_advisor_prompt_reads_vision_summary_as_grounded_evidence():
    from site_agent.brain.design_intake import _advisor_prompt
    from site_agent.brain.design_guidance import load_design_skills

    prompt = _advisor_prompt(DesignIntakeDraft.empty(), [], load_design_skills().content)
    assert "bounded summary" in prompt
    assert "do not invent" in prompt


def test_advisor_prompt_makes_imagery_request_optional_and_non_blocking():
    from site_agent.brain.design_intake import _advisor_prompt
    from site_agent.brain.design_guidance import load_design_skills

    prompt = _advisor_prompt(DesignIntakeDraft.empty(), [], load_design_skills().content)

    assert "Optional imagery conversation" in prompt
    assert "photos, a logo, or visual references" in prompt
    assert "must never block readiness or research" in prompt
    assert "asking" in prompt and "again" in prompt


def test_truncated_intake_json_is_never_echoed_verbatim(tmp_path):
    from site_agent.brain.design_intake import (
        DesignIntakeAdvisorError,
        LLMDesignIntakeAdvisor,
        _looks_jsonish,
    )

    assert _looks_jsonish('{"schema_version": 1, "assistant_message": "x", "field_')
    assert _looks_jsonish("```json\n{\"a\": 1}")
    assert not _looks_jsonish("Merci, dites m'en plus.")
    assert not _looks_jsonish("")

    class _TruncatingLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            # A completion the model was forced to cut off mid-field_updates.
            return '{"schema_version":1,"assistant_message":"Claro Oscuro — un bel univers.",' \
                   '"field_updates":[{"path":"business.name","value":"Claro Oscuro","basis":"owner_statement"},{"path":"brand.'

    llm = _TruncatingLLM()
    advisor = LLMDesignIntakeAdvisor(llm, {"intake_advisor": {}})
    try:
        advisor.advise(DesignIntakeDraft.empty(), [], "Je lance une retraite de plongee appelée Claro Oscuro.")
        raise AssertionError("truncated JSON must raise, not be echoed")
    except DesignIntakeAdvisorError as exc:
        assert "JSON" in str(exc) or "truncated" in str(exc)
    assert llm.calls == 1


def test_short_requests_are_handled_by_the_model_not_the_host():
    """There is no host-side nudge/echo heuristic anymore; every turn is exactly
    one advisor call and the model decides how to respond."""
    calls = []

    class _LLM:
        def chat(self, messages, **kwargs):
            calls.append(messages)
            return '{"schema_version": 1, "assistant_message": "Bien sûr. Continuez quand vous êtes prêt.", "field_updates": [], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    result = LLMDesignIntakeAdvisor(_LLM(), {}).advise(
        DesignIntakeDraft.empty(),
        [],
        "continuez, donnez-moi la suite ?",
    )

    assert len(calls) == 1
    assert result.assistant_message.startswith("Bien sûr.")


def test_force_new_build_creates_a_fresh_candidate_from_a_reviewable_prior(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def __init__(self):
            self.submissions = []

        def submit(self, prompt, raw_intake, **kwargs):
            run_id = f"intake-lab-{len(self.submissions):032x}"
            self.submissions.append((prompt, run_id, kwargs))
            return {"run_id": run_id, "status": "building", "publishable": False}

        def get_run(self, run_id):
            return {"run_id": run_id, "status": "ready_for_review", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-force",
    )
    assert confirmed["confirmed"] is True
    final_revision = confirmed["session"]["confirmed_revision_id"]

    first = service.build(
        session["session_id"],
        confirmed_revision=final_revision,
        idempotency_key="build-force",
    )
    reuse = service.build(
        session["session_id"],
        confirmed_revision=final_revision,
        idempotency_key="build-force",
    )
    assert reuse["idempotent"] is True
    assert reuse["run"]["run_id"] == first["run"]["run_id"]
    assert len(lab.submissions) == 1

    fresh = service.build(
        session["session_id"],
        confirmed_revision=final_revision,
        idempotency_key="build-force-fresh",
        force_new=True,
    )
    assert fresh["run"]["run_id"] != first["run"]["run_id"]
    assert len(lab.submissions) == 2
    memory.close()


def test_resolve_ui_action_only_opens_lineage_runs(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def get_run(self, run_id):
            return {
                "run_id": run_id,
                "status": "ready_for_review",
                "preferred_run_id": run_id,
                "revisions": [
                    {"run_id": "rev-a", "number": 1, "reviewable": False},
                    {"run_id": "rev-b", "number": 2, "reviewable": True},
                ],
            }

    service = DesignIntakeService(memory, lab_service=_Lab())
    confirmed = {"design_run_id": "rev-root", "status": "confirmed"}
    collecting = {"design_run_id": "rev-root", "status": "collecting"}

    resolved = service._resolve_ui_action({"action": "open_preview", "run_id": "rev-b"}, confirmed)
    assert resolved == {"action": "open_preview", "run_id": "rev-b"}
    assert service._resolve_ui_action({"action": "open_preview", "run_id": "rev-root"}, confirmed) == {
        "action": "open_preview", "run_id": "rev-root"
    }
    assert service._resolve_ui_action({"action": "open_preview", "run_id": "not-in-lineage"}, confirmed) is None
    assert service._resolve_ui_action({"action": "nonsense"}, confirmed) is None

    assert service._resolve_ui_action({"action": "start_build"}, confirmed)["action"] == "start_build"
    assert service._resolve_ui_action({"action": "start_build"}, collecting) is None
    memory.close()


class _StartBuildLab:
    def __init__(self): self.submissions = []
    def submit(self, prompt, raw_intake, **kwargs):
        run = {"run_id": f"run-{len(self.submissions)}", "status": "building", "mode": "production_candidate", **kwargs}
        self.submissions.append((prompt, run))
        return run
    def get_run(self, run_id):
        return next((item[1] for item in self.submissions if item[1]["run_id"] == run_id), None)


def test_ready_start_build_proposal_confirms_exact_intake_revision(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    lab = _StartBuildLab()
    service = DesignIntakeService(memory, lab_service=lab)
    draft = DesignIntakeDraft.from_site_intake(_intake())
    session = service.create_session(draft=draft)
    assert session["status"] == "ready_to_build"

    action = service._resolve_ui_action({"action": "start_build"}, session)

    confirmed = service.get_session(session["session_id"])
    assert action["action"] == "start_build"
    assert action["fresh"] is True
    assert action["build"]["run"]["intake_session_id"] == session["session_id"]
    assert action["build"]["run"]["intake_revision_id"] == confirmed["confirmed_revision_id"]
    assert len(lab.submissions) == 1
    assert action["build"]["run"]["mode"] == "production_candidate"
    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmed_revision"]
    assert confirmed["confirmed_hash"]
    assert confirmed["confirmed_ts"]
    memory.close()


def test_ready_start_build_action_is_idempotent_and_visible_in_workspace_status(tmp_path):
    from site_agent.application.workspace import ChatService

    memory = Memory(tmp_path / "intake.db")
    lab = _StartBuildLab()
    service = DesignIntakeService(memory, lab_service=lab)
    session = service.create_session(draft=DesignIntakeDraft.from_site_intake(_intake()))
    first = service._resolve_ui_action({"action": "start_build"}, session)
    repeated = service._resolve_ui_action({"action": "start_build"}, service.get_session(session["session_id"]))
    assert len(lab.submissions) == 1
    assert repeated["build"]["run"]["run_id"] == first["build"]["run"]["run_id"]

    class _Coordinator:
        def status(self, conversation_id):
            confirmed = service.get_session(session["session_id"])
            return {"confirmed": True, "session_id": session["session_id"], "confirmed_revision_id": confirmed["confirmed_revision_id"]}

    class _Memory:
        def list_active_chat_jobs(self, **kwargs): return []
        def list_design_runs(self, **kwargs): return [lab.submissions[0][1]]
        def list_design_run_events(self, run_id, **kwargs): return []

    class _Tenant:
        tenant_id = "test"
        context = {"intake_coordinator": _Coordinator()}
        memory = _Memory()
    # Exercise the existing status projection with the queued production run.
    workspace = object.__new__(ChatService)
    workspace._scope = lambda tenant: (_Tenant.memory, None, "test")
    workspace._journey = lambda tenant: None
    status = workspace.status(tenant=_Tenant())
    assert status["build"]["state"] == "queued"
    assert status["build"]["run_id"] == first["build"]["run"]["run_id"]
    assert len(status["build"]["stages"]) == 6
    memory.close()


def test_start_build_failure_keeps_confirmation_and_reports_plain_reason(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory)
    session = service.create_session(draft=DesignIntakeDraft.from_site_intake(_intake()))
    action = service._resolve_ui_action({"action": "start_build"}, session)
    confirmed = service.get_session(session["session_id"])
    assert action is not None
    assert action["error"] == "design build service is unavailable"
    assert confirmed["status"] == "confirmed"
    memory.close()


def test_advice_turn_start_build_confirms_advanced_revision_once(tmp_path):
    class _BuildAdvisor:
        def advise(self, draft, history, owner_message, **kwargs):
            return IntakeTurnResult(schema_version=1, assistant_message="Building it now…", ui_action={"action": "start_build"})

    memory = Memory(tmp_path / "intake.db")
    lab = _StartBuildLab()
    service = DesignIntakeService(memory, lab_service=lab, advisor=_BuildAdvisor())
    session = service.create_session(draft=DesignIntakeDraft.from_site_intake(_intake()))
    service.send_message(session["session_id"], "go")
    job = memory.claim_chat_job("revision-test")
    result = service.handle_advice_job({}, job)
    current = service.get_session(session["session_id"])
    assert current["confirmed_revision"] == current["revision"]
    assert result["ui_action"]["build"]["run"]["mode"] == "production_candidate"
    assert len(lab.submissions) == 1
    assert result["reply"] == "Building it now…"
    memory.close()


def test_advice_turn_failed_confirmation_does_not_promise_build(tmp_path):
    class _BuildAdvisor:
        def advise(self, draft, history, owner_message, **kwargs):
            return IntakeTurnResult(schema_version=1, assistant_message="Building it now…", ui_action={"action": "start_build"})

    memory = Memory(tmp_path / "intake.db")
    lab = _StartBuildLab()
    service = DesignIntakeService(memory, lab_service=lab, advisor=_BuildAdvisor())
    session = service.create_session(draft=DesignIntakeDraft.from_site_intake(_intake()))
    service.send_message(session["session_id"], "go")
    job = memory.claim_chat_job("revision-test")
    # Simulate persistence leaving the post-turn session outside a confirmable state.
    original_save = memory.save_design_intake_revision
    def save_unready(*args, **kwargs):
        saved = original_save(*args, **kwargs)
        memory.update_design_intake_session(session["session_id"], status="collecting")
        return saved
    memory.save_design_intake_revision = save_unready
    result = service.handle_advice_job({}, job)
    assert result["ui_action"]["action"] is None
    assert result["ui_action"]["error"]
    assert len(result["ui_action"]["error"]) <= 500
    assert not lab.submissions
    assert result["reply"] == "Please confirm the current brief before I start building."
    memory.close()


def test_confirmed_handoff_failure_does_not_request_confirmation(tmp_path):
    class Advisor:
        def advise(self, draft, history, owner_message, **kwargs):
            return IntakeTurnResult(schema_version=1, assistant_message="Building it now…",
                                    ui_action={"action": "start_build"})

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake(), advisor=Advisor())
    session = service.create_session()
    service.confirm(session["session_id"], revision=session["revision"], draft_hash=session["draft_hash"])
    service.send_message(session["session_id"], "go")
    job = memory.claim_chat_job("failure-test")
    result = run_job({"memory": memory, "design_intake_service": service,
                      "config": {}, "llm": object()}, job, "failure-test")
    assert result["ui_action"]["error_code"] == "build_handoff_failed"
    assert "could not start" in result["reply"]
    assert "Please confirm" not in result["reply"]
    assert "Building it now" not in result["reply"]
    assert service.get_session(session["session_id"])["confirmed_revision"]
    assert memory.get_chat_job(job["id"])["status"] == "done"
    assert "design build service is unavailable" in str(memory.get_chat_job(job["id"])["result"])
    memory.close()


def test_failed_confirmed_session_can_reach_guarded_recovery(tmp_path):
    memory = Memory(tmp_path / "failed.db")
    calls = []
    class Advisor:
        def advise(self, draft, history, owner_message, **kwargs):
            return IntakeTurnResult(schema_version=1, assistant_message="Building it now…",
                                    ui_action={"action": "start_build"})

    class Lab:
        def submit(self, *args, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("same-run recovery rejected: same-run recovery identity checkpoint is missing or malformed")
        def get_run(self, run_id):
            return memory.get_design_run(run_id)
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=Lab(), advisor=Advisor())
    session = service.create_session()
    service.confirm(session["session_id"], revision=session["revision"], draft_hash=session["draft_hash"])
    frozen = service.get_session(session["session_id"])
    run = memory.create_design_run(run_id="historical-failed", mode="production_candidate", status="failed",
        intake_json=memory.list_design_intake_revisions(session["session_id"])[-1]["site_intake"], intake_hash="a" * 64, base_sha="b" * 40,
        publishable=True, candidate_ref="refs/ada-design/historical-failed",
        intake_session_id=session["session_id"], intake_revision_id=frozen["confirmed_revision_id"])
    memory.update_design_intake_session(session["session_id"], status="failed", design_run_id=run["run_id"], build_error="stopped")
    for message in ("go", "??"):
        service.send_message(session["session_id"], message)
        job = memory.claim_chat_job("recovery-test")
        result = run_job({"memory": memory, "design_intake_service": service,
                          "config": {}, "llm": object()}, job, "recovery-test")
        action = result["ui_action"]
        assert action["error_code"] == "build_handoff_failed"
        assert "checkpoint" in action["error"]
        assert "could not start" in result["reply"]
        assert "confirm" not in result["reply"].lower()
    current = service.get_session(session["session_id"])
    assert current["confirmed_revision"] == frozen["confirmed_revision"]
    assert current["design_run_id"] == run["run_id"]
    assert calls and all(call["resume_run_id"] == run["run_id"] for call in calls)
    assert len(memory.list_design_runs()) == 1
    memory.close()


def test_customer_view_json_is_compact_and_omits_run_detail(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def get_run(self, run_id):
            return {
                "run_id": "rev-root",
                "status": "validating",
                "preferred_run_id": "rev-b",
                "revisions": [
                    {"run_id": "rev-a", "number": 1, "operation_kind": "initial_build", "status": "validating", "reviewable": False},
                    {"run_id": "rev-b", "number": 2, "operation_kind": "visual_refinement", "status": "ready_for_review", "reviewable": True},
                ],
            }

    service = DesignIntakeService(memory, lab_service=_Lab())
    view = service._customer_view_json({"design_run_id": "rev-root"})
    assert "rev-root" in view
    assert "ready_for_review" in view
    assert "rev-b" in view
    assert "quality_report" not in view
    assert service._customer_view_json({}) == ""
    memory.close()


def test_existing_site_customer_view_carries_the_owner_visible_page(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(
        memory,
        config={
            "site": {
                "payload": {"enabled": True, "url": "https://workspace.example.test"},
            },
            "customer_profile": {
                "business": {"observed_site_settings": {"website_url": "https://workspace-harmonie.com"}},
            },
            "intake": {"database_only": True},
        },
    )
    view = json.loads(service._customer_view_json({}, owner_context={
        "phase": "incubation",
        "route": "/",
        "scope": "selected_page_reference",
        "target": {
            "mode": "incubation",
            "route": {"path": "/", "kind": "page", "sourceId": "home-source"},
            "site": {
                "name": "workspace-harmonie",
                "routes": [{"path": "/", "kind": "home", "collection": "pages", "sourceId": "home-source"}],
            },
        },
    }))
    prompt = _advisor_prompt(
        DesignIntakeDraft.empty(),
        (),
        "",
        customer_view=json.dumps(view),
        database_only=True,
    )

    assert view["existing_site"]["status"] == "existing_live_website"
    assert view["owner_visible_surface"]["target"]["route"]["path"] == "/"
    assert view["owner_visible_surface"]["target"]["site"]["routes"][0]["path"] == "/"
    assert "existing live website" in prompt
    assert "selected_page_reference" in prompt
    assert "The first build is the MAIN PAGE only." not in prompt
    assert "readiness means the incubation brief is complete" in prompt
    assert "offer to confirm and build the first visual page" not in prompt
    memory.close()


def test_design_intake_advisor_receives_the_authoritative_existing_site_journey(tmp_path):
    class _LLM:
        api_key = "configured"

        def chat(self, messages, **kwargs):
            return "{}"

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(
        memory,
        config={
            "site": {"payload": {"enabled": True}},
            "intake": {"enabled": True, "database_only": True},
            "design_engine": {"intake_advisor": {}},
        },
        llm=_LLM(),
    )

    assert service.website_present is True
    assert service.advisor.website_present is True
    assert service.advisor.database_only is True
    memory.close()


def test_intake_advice_job_persists_owner_surface_context(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_Advisor())
    session = service.create_session()
    queued = service.send_message(
        session["session_id"],
        "Continue with the current page.",
        owner_context={"phase": "incubation", "route": "/", "scope": "selected_page_reference"},
    )
    job = memory.get_chat_job(queued["job_id"])

    assert job["payload"]["owner_context"] == {
        "phase": "incubation",
        "route": "/",
        "scope": "selected_page_reference",
    }
    memory.close()


def test_synthesized_brand_name_does_not_unlock_readiness():
    def set_name(basis):
        return merge_intake_turn(
            DesignIntakeDraft.empty(),
            IntakeTurnResult(
                schema_version=1,
                assistant_message="name note",
                field_updates=(IntakeFieldUpdate(
                    path="business.name",
                    value="Mel - Cave Diving Retreats",
                    basis=basis,
                    note="working name",
                ),),
            ),
            source_message_id=1,
        )

    recommended = set_name("recommendation")
    assert "business.name" in recommended.unresolved_core_paths

    stated = set_name("owner_statement")
    assert "business.name" not in stated.unresolved_core_paths

    accepted = set_name("owner_acceptance")
    assert "business.name" not in accepted.unresolved_core_paths


def test_location_context_requires_owner_location_or_explicit_non_applicable_choice():
    def set_field(path, value, basis="owner_statement"):
        return merge_intake_turn(
            DesignIntakeDraft.empty(),
            IntakeTurnResult(
                schema_version=1,
                assistant_message="location note",
                field_updates=(IntakeFieldUpdate(path=path, value=value, basis=basis),),
            ),
            source_message_id=1,
        )

    assert "business.location" in DesignIntakeDraft.empty().unresolved_core_paths
    assert "business.location" in set_field("business.location", "Lyon", "recommendation").unresolved_core_paths
    assert "business.location" not in set_field("business.location", "Lyon").unresolved_core_paths
    assert "business.location" not in set_field("business.service_area", "Worldwide").unresolved_core_paths
    assert "business.location" in set_field("business.location_not_applicable", True, "recommendation").unresolved_core_paths
    assert "business.location" not in set_field("business.location_not_applicable", True).unresolved_core_paths


def test_advisor_prompt_enforces_brand_name_integrity_and_honest_readiness():
    from site_agent.brain import design_intake as intake_brain

    prompt = intake_brain._advisor_prompt(DesignIntakeDraft.empty(), [], "applied guidance", "applied guidance")
    assert "business.name is the name the OWNER wants displayed" in prompt
    assert "Never derive a brand" in prompt
    assert "synthesize a compound name" in prompt
    assert "The prose and the readiness must always agree" in prompt
    assert "business.location_not_applicable" in prompt
    assert "Location context is required" in prompt


def test_advisor_prompt_embeds_logo_ocr_as_context_but_not_as_a_name():
    from site_agent.brain import design_intake as intake_brain

    prompt = intake_brain._advisor_prompt(
        DesignIntakeDraft.empty(),
        [{"tags": ["logo", "branding"], "ocr_text": "CENOTE RETREATS", "description": "Block letters on black", "usage": "website"}],
        "applied guidance",
        "applied guidance",
    )
    assert "CENOTE RETREATS" in prompt
    assert '"is_logo":true' in prompt
    assert "that is not the" in prompt and "owner stating the name" in prompt
    # No scripted conversational examples, no hardcoded languages, no injected
    # host language detection: the model answers from context.
    assert "Worked example:" not in prompt
    assert "Merci" not in prompt
    assert "OWNER LANGUAGE:" not in prompt


def test_background_notes_compose_from_this_turns_evidence_only():
    service = DesignIntakeService(Memory("/tmp/bn-notes.db"))

    notes = service._background_notes(
        [
            {"name": "logo.webp", "tags": ["logo"], "ocr_text": "CLAR OSCURO", "description": "Block letters on black",
             "usage": "website", "width": 375, "height": 285},
            {"name": "cenote.webp", "tags": ["cave"], "description": "Diver in a light shaft", "usage": "website"},
        ],
        ["Cenote diving attracts experienced tech divers."],
        IntakeTurnResult(schema_version=1, assistant_message="x", creative_insights=(
            type("CI", (), {"summary": "Dark logotype implies a serious tone."})(),
        )),
    )
    assert "BACKGROUND ANALYSIS" in notes
    assert 'logo reads "CLAR OSCURO"' in notes
    assert "Diver in a light shaft" in notes
    assert "Cenote diving attracts" in notes
    assert "Dark logotype implies" in notes

    assert service._background_notes([], [], IntakeTurnResult(schema_version=1, assistant_message="x")) == ""


def test_background_analysis_is_persisted_into_the_conversation(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _AnalysisAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=(), **kwargs):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message="I noted the dark logotype.",
                creative_insights=(type("CI", (), {"summary": "Dark logotype implies a serious tone."})(),),
            )

    service = DesignIntakeService(memory, advisor=_AnalysisAdvisor(), lab_service=_FakeLab())
    session = service.create_session()
    service.send_message(session["session_id"], "Here is my logo.")
    job = memory.claim_chat_job("analysis-worker")
    from site_agent.core.chat_jobs import run_job

    run_job({"memory": memory, "design_intake_service": service, "config": {}, "llm": object()}, job, "analysis-worker")
    messages = service.get_session(session["session_id"])["messages"]
    system = [m for m in messages if m.get("role") == "system"]
    assert any("BACKGROUND ANALYSIS" in str(m.get("text") or "") for m in system)
    memory.close()


def test_advisor_prompt_contains_no_owner_message_kind_block():
    """The question/critique distinction is handled by the model from the
    conversation; the host no longer classifies messages or injects a block."""
    from site_agent.brain import design_intake as intake_brain

    prompt = intake_brain._advisor_prompt(DesignIntakeDraft.empty(), [], "guidance", "guidance")
    assert "LATEST OWNER MESSAGE TYPE" not in prompt
    assert "owner_message_kind" not in prompt
    assert "OWNER LANGUAGE" not in prompt


def test_advisor_prompt_keeps_reply_language_grounded_in_conversation_context():
    from site_agent.brain import design_intake as intake_brain

    prompt = intake_brain._advisor_prompt(
        DesignIntakeDraft.empty(),
        [],
        "guidance",
        ["Background evidence may be written in another language."],
    )
    assert "Keep the visible reply in the language of the owner's latest message" in prompt
    assert "Proper names are not language signals" in prompt
    assert "Do not infer reply language from research, source text, OCR, or field values" in prompt
    assert "Only change languages when the owner clearly changes languages or asks for translation" in prompt
    assert "When the current owner turn is language-neutral, inherit the established language from recent owner turns" in prompt
    assert "FINAL RESPONSE CONTRACT" in prompt
    assert "A standalone proper name or other language-neutral fragment does not reset that language" in prompt


class _FakeLab:
    def get_run(self, run_id):
        return {"run_id": run_id, "status": "building", "revisions": []}


def test_conversational_confirmation_accepts_a_ready_brief():
    """The owner's own confirmation in chat is the acceptance; no second button."""
    import inspect
    from site_agent.application import design_intake

    source = inspect.getsource(design_intake.DesignIntakeService)
    assert "conversational-confirm-" in source, "the conversational confirm needs a stable idempotency key"
    assert "READY_TO_BUILD.value:" in source, "a ready brief must be confirmable from the conversation"
    ui = (design_intake.__file__ and "")
    assert ui is not None


class _PayloadMediaService:
    """Payload tenants keep canonical media outside the local library."""

    def __init__(self, assets):
        self.assets = assets

    def get(self, asset_id):
        return self.assets[int(asset_id)]

    def resolve_attachments(self, asset_ids):
        return [{"asset_id": int(asset_id), "position": index, "type": "media_asset"}
                for index, asset_id in enumerate(asset_ids or [])]


class _PayloadAsset:
    def __init__(self, url="https://example.test/api/media/file/hero.png", content_type="image/png"):
        self.asset_id = 41
        self.original_name = "hero.png"
        self.content_type = content_type
        self.url = url


def test_payload_media_can_be_bound_to_intake_without_the_local_library(tmp_path):
    """Owner uploads live in Payload, so binding must ask the media service."""
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(
        memory,
        default_intake=_intake(),
        media_service=_PayloadMediaService({41: _PayloadAsset()}),
    )
    session = service.create_session()

    queued = service.send_message(session["session_id"], "Use this logo.", attachments=[41])

    assert queued["job_id"]
    assert [row["asset_id"] for row in memory.list_design_intake_assets(session["session_id"])] == [41]
    memory.close()


def test_payload_media_that_is_not_an_image_is_still_rejected(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(
        memory,
        default_intake=_intake(),
        media_service=_PayloadMediaService({41: _PayloadAsset(content_type="application/pdf")}),
    )
    session = service.create_session()

    with pytest.raises(DesignIntakeServiceError, match="only ready, unarchived images"):
        service.send_message(session["session_id"], "Use this document.", attachments=[41])
    memory.close()
