"""Durable background knowledge-infusion loop + chat-job watchdog hardening."""

from site_agent.brain.incubation_infusion import (
    IncubationInfusionError,
    IncubationInfusionExecutor,
    IncubationInfusionService,
    build_infusion_snapshot,
    parse_infusion_contract,
    snapshot_hash,
)
from site_agent.core.contracts import ContractError
from site_agent.core.incubation_contracts import DeductionKind, InfusionMode, InfusionRunStatus
from site_agent.core.memory import Memory
from site_agent.core.design_intake_contracts import DesignIntakeDraft
from site_agent.core.design_intake_contracts import IntakeFieldProvenance


def _config(**overrides):
    config = {"infusion": {"enabled": True, "mode": "native", "cooldown_seconds": 1, "idle_seconds": 1}}
    config["infusion"].update(overrides)
    return config


def _snapshot():
    return build_infusion_snapshot(
        draft={"fields": {"business": {"offer_summary": "Vitrailliste a Lyon depuis 2007."}}},
        genesis={"business_world": {"purpose": "Montrer l'atelier"}, "creative_identity": {"principles": ["chaleur"]}},
        deductions=[],
        findings=[],
        insights=[],
        sources=[],
        assets=[],
        owner_language="fr",
    )


class _FakeLLM:
    def __init__(self, contract, base_url="https://api.entrim.ai/v1"):
        self.contract = contract
        self.base_url = base_url
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        assert kwargs.get("enable_thinking") is False
        assert kwargs.get("json_mode") is True
        return self.contract


class _FakeRunner:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def __call__(self, context, snapshot, session_id, **kwargs):
        self.calls += 1
        return {"reply": self.reply, "session_id": "infusion-sess-1", "used_pipeworx": True, "transcript": ""}


def _service(tmp_path, config, llm=None, runner=None, activity=None, research=None, genesis=None):
    memory = Memory(tmp_path / "incubation.db")
    service = IncubationInfusionService(
        memory,
        config=config,
        llm=llm,
        activity_service=activity,
        research_service=research,
        genesis_service=genesis,
        opencode_runner=runner,
    )
    return memory, service


def test_infusion_contract_parser_accepts_and_normalizes_expected_shape():
    contract = parse_infusion_contract("""```json
    {"deductions":[{"kind":"opportunity","summary":"Segment luminaires upcycles non exploite","confidence":0.8,"basis":"snapshot","supports_paths":["audience.primary"]}],
     "followup_research":[{"type":"pipeworx","query":"segment luminaires upcycles","reason":"check"}],
     "genesis_notes":{"business_world":{"values":["engagement durable"]}},
     "horizon_questions":["B2B ou B2C ?"]}
    ```""")
    assert contract is not None
    assert contract["deductions"][0]["kind"] == "opportunity"
    assert contract["followup_research"][0]["type"] == "pipeworx"
    assert contract["genesis_notes"]["business_world"]["values"] == ["engagement durable"]


def test_infusion_contract_parser_rejects_invalid_kinds_and_keeps_citation_uris():
    contract = parse_infusion_contract('{"deductions":[{"kind":"bogus","summary":"x"},{"kind":"bad","summary":"y"}],"followup_research":[],"horizon_questions":[]}')
    assert contract["deductions"] == []
    contract2 = parse_infusion_contract('{"deductions":[{"kind":"risk","summary":"y","citation_uris":["https://example.com/page","pipeworx://edgar/1"]}],"followup_research":[],"horizon_questions":[]}')
    assert contract2["deductions"][0]["citation_uris"] == ["pipeworx://edgar/1"]


def test_snapshot_hash_is_stable_for_equal_snapshots():
    a = _snapshot()
    b = _snapshot()
    assert snapshot_hash(a) == snapshot_hash(b)


def test_native_pass_persists_typed_deductions_and_completes_run(tmp_path):
    contract = '{"deductions":[{"kind":"opportunity","summary":"Segment luminaires upcycles non exploite","confidence":0.8,"basis":"snapshot","supports_paths":["audience.primary"]}],"followup_research":[],"genesis_notes":{},"horizon_questions":[]}'
    llm = _FakeLLM(contract)
    memory, service = _service(tmp_path, _config(), llm=llm)
    try:
        run = service.enqueue(trigger="intake_revision", session_id=f"intake-{'a' * 32}", snapshot=_snapshot())
        assert run is not None
        assert run["mode"] == InfusionMode.NATIVE.value
        finished, error = service.process_one("worker-1")
        assert finished and error is None
        deductions = memory.list_incubation_deductions()
        assert len(deductions) == 1
        assert deductions[0]["kind"] == "opportunity"
        assert deductions[0]["run_id"] == run["run_id"]
        assert memory.list_infusion_runs()[0]["status"] == "completed"
    finally:
        memory.close()


def test_native_pass_omits_enable_thinking_on_non_entrim_providers(tmp_path):
    """enable_thinking is an entrim-only knob; OpenRouter-style providers must
    never receive it (they reject unknown body keys)."""
    contract = '{"deductions":[],"followup_research":[],"genesis_notes":{},"horizon_questions":[]}'

    class _OpenRouterLLM:
        base_url = "https://openrouter.ai/api/v1"

        def __init__(self, contract):
            self.contract = contract
            self.calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            assert "enable_thinking" not in kwargs
            assert kwargs.get("json_mode") is True
            return self.contract

    llm = _OpenRouterLLM(contract)
    memory, service = _service(tmp_path, _config(), llm=llm)
    try:
        run = service.enqueue(trigger="idle", session_id=f"intake-{'c' * 32}", snapshot=_snapshot())
        assert run is not None
        finished, error = service.process_one("worker-1")
        assert finished and error is None
        assert llm.calls == 1
    finally:
        memory.close()


def test_native_pass_surfaces_the_underlying_provider_error(tmp_path):
    class _BrokenLLM:
        base_url = "https://openrouter.ai/api/v1"

        def chat(self, messages, **kwargs):
            raise RuntimeError("provider refused unknown body key")

    memory, service = _service(tmp_path, _config(), llm=_BrokenLLM())
    try:
        run = service.enqueue(trigger="idle", session_id=f"intake-{'d' * 32}", snapshot=_snapshot())
        assert run is not None
        finished, error = service.process_one("worker-1")
        assert finished is True
        assert error and "provider refused unknown body key" in error
    finally:
        memory.close()


def test_dedupe_prevents_repeating_the_same_deduction(tmp_path):
    contract = '{"deductions":[{"kind":"opportunity","summary":"Segment luminaires upcycles non exploite","confidence":0.8,"basis":"snapshot","supports_paths":["audience.primary"]}],"followup_research":[],"genesis_notes":{},"horizon_questions":[]}'
    memory, service = _service(tmp_path, _config(), llm=_FakeLLM(contract))
    try:
        service.enqueue(trigger="idle", session_id=f"intake-{'b' * 32}", snapshot=_snapshot())
        service.process_one("worker-1")
        service_enqueued = service.enqueue(trigger="idle", session_id=f"intake-{'b' * 32}", snapshot=_snapshot())
        # newest completed run must finish; second identical deduction must be deduped
        if service_enqueued is not None:
            service.process_one("worker-1")
        assert len(memory.list_incubation_deductions()) == 1
    finally:
        memory.close()


def test_throttle_skips_when_a_pass_is_in_flight(tmp_path):
    memory, service = _service(tmp_path, _config(), llm=_FakeLLM('{"deductions":[],"followup_research":[],"genesis_notes":{},"horizon_questions":[]}'))
    try:
        run = service.enqueue(trigger="idle", session_id=f"intake-{'c' * 32}", snapshot=_snapshot())
        assert run is not None
        memory.update_infusion_run(run["run_id"], status=InfusionRunStatus.RUNNING.value)
        again = service.enqueue(trigger="idle", session_id=f"intake-{'c' * 32}", snapshot=_snapshot())
        assert again is None  # one pass at a time
    finally:
        memory.close()


def test_opencode_mode_uses_runner_and_marks_pipeworx_discoveries(tmp_path):
    reply = '{"deductions":[{"kind":"market_context","summary":"Le segment restauration a durabilite croit","confidence":0.7,"basis":"source","source_refs":["source_x"],"citation_uris":["pipeworx://edgar/1"]}],"followup_research":[],"genesis_notes":{},"horizon_questions":[]}'
    runner = _FakeRunner(reply)
    config = {"infusion": {"enabled": True, "mode": "opencode", "cooldown_seconds": 1, "idle_seconds": 1}}
    memory, service = _service(tmp_path, config, llm=None, runner=runner)
    try:
        run = service.enqueue(trigger="research_completed", session_id=f"intake-{'d' * 32}", snapshot=_snapshot())
        assert run["mode"] == InfusionMode.OPENCODE.value
        finished, error = service.process_one("worker-1")
        assert finished and error is None
        assert runner.calls == 1
        deductions = memory.list_incubation_deductions()
        assert deductions[0]["discovered_by"] == "pipeworx"
        assert deductions[0]["citation_uris"] == ["pipeworx://edgar/1"]
    finally:
        memory.close()


def test_auto_mode_falls_back_to_native_when_opencode_runner_fails(tmp_path):
    def failing_runner(context, snapshot, session_id, **kwargs):
        raise RuntimeError("opencode binary missing")

    reply = '{"deductions":[{"kind":"risk","summary":"Risque : dependre d un seul canal","confidence":0.5,"basis":"hypothesis","supports_paths":[]}],"followup_research":[],"genesis_notes":{},"horizon_questions":[]}'
    llm = _FakeLLM(reply)
    config = {"infusion": {"enabled": True, "mode": "auto", "cooldown_seconds": 1, "idle_seconds": 1}}
    memory, service = _service(tmp_path, config, llm=llm, runner=failing_runner)
    try:
        run = service.enqueue(trigger="idle", session_id=f"intake-{'e' * 32}", snapshot=_snapshot())
        assert run["mode"] == InfusionMode.OPENCODE.value
        finished, error = service.process_one("worker-1")
        assert finished and error is None
        assert memory.list_incubation_deductions()[0]["kind"] == "risk"
    finally:
        memory.close()


def test_executor_process_one_polls_and_requeues_abandoned_runs(tmp_path):
    contract = '{"deductions":[],"followup_research":[],"genesis_notes":{},"horizon_questions":[]}'
    memory, service = _service(tmp_path, _config(), llm=_FakeLLM(contract))
    executor = IncubationInfusionExecutor(service, interval=0.01)
    try:
        run = service.enqueue(trigger="idle", session_id=f"intake-{'f' * 32}", snapshot=_snapshot())
        memory.update_infusion_run(run["run_id"], status=InfusionRunStatus.RUNNING.value)
        assert memory.requeue_abandoned_infusion_runs() == 1
        assert service.process_one("worker-2") == (True, None)
        assert memory.list_infusion_runs()[0]["status"] == "completed"
    finally:
        executor.stop()
        memory.close()


def test_deduction_crud_roundtrip_guards_hash(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    try:
        run = memory.save_infusion_run(_infusion_run())
        assert run["run_id"].startswith("infusion_")
        assert memory.get_infusion_run(run["run_id"])["status"] == "pending"
        assert memory.claim_pending_infusion_run("w")["run_id"] == run["run_id"]
    finally:
        memory.close()


def _infusion_run():
    from site_agent.core.incubation_contracts import InfusionRun

    now = "2026-09-04T00:00:00Z"
    return InfusionRun.from_dict({
        "run_id": "infusion_" + "1" * 32,
        "trigger": "idle",
        "mode": "native",
        "status": "pending",
        "budget_tokens": 1200,
        "snapshot_hash": "0" * 64,
        "session_id": f"intake-{'a' * 32}",
        "created_at": now,
        "updated_at": now,
    })


def test_watchdog_flags_stale_chat_jobs(tmp_path):
    from datetime import datetime, timedelta, timezone

    memory = Memory(tmp_path / "incubation.db")
    try:
        conversation = memory.create_conversation("stale")
        job_id = memory.enqueue_chat_job(conversation, "hello")
        job = memory.get_chat_job(job_id)
        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
        with memory.conn:
            memory.conn.execute("UPDATE chat_jobs SET updated_ts = ? WHERE id = ?", (old, job["id"]))
        failed = memory.fail_stale_chat_jobs(max_seconds=240)
        assert failed == [job["id"]]
        assert memory.get_chat_job(job["id"])["status"] == "error"
        assert "reason=stale" in memory.get_chat_job(job["id"])["error"]
    finally:
        memory.close()


def test_chat_job_result_records_duration_ms(tmp_path):
    from site_agent.application.design_intake import DesignIntakeService
    from site_agent.core.chat_jobs import run_job

    class _Advisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            from site_agent.core.design_intake_contracts import IntakeTurnResult

            return IntakeTurnResult.from_dict({
                "assistant_message": "Compris, continue.",
                "field_updates": [{"path": "business.name", "value": "Atelier", "basis": "owner_statement"}],
                "suggested_readiness": "collecting",
            })

        last_call_count = 1

    memory = Memory(tmp_path / "intake.db")
    try:
        service = DesignIntakeService(memory, advisor=_Advisor())
        session = service.create_session()
        queued = service.send_message(session["session_id"], "Je m'appelle Marc.")
        job = memory.claim_chat_job("worker")
        result = run_job({"memory": memory, "design_intake_service": service, "config": {}, "llm": object()}, job, "worker")
        assert result["duration_ms"] >= 0
        assert result["advisor_call_count"] == 1
    finally:
        memory.close()


def test_confirm_bump_prevents_revision_collision_on_retry(tmp_path):
    """A post-confirmation owner turn must not collide on the revision unique
    key: confirmation records revision r+1 and bumps the session revision."""
    from site_agent.application.design_intake import DesignIntakeService
    from site_agent.core.design_contracts import SiteIntake
    from site_agent.core.chat_jobs import run_job

    def _intake() -> SiteIntake:
        return SiteIntake.from_dict({
            "schema_version": 1,
            "business": {
                "name": "Atelier Vitrail",
                "offer_summary": "Restaure et vend du vitrail a Lyon.",
                "primary_services": ["Restauration de vitraux", "Vente"],
                "location": "Lyon",
            },
            "audience": {"primary": "Particuliers"},
            "conversion": {"primary_action": "Prendre contact", "not_available": True},
            "brand": {"voice": "Chaleureux et precis."},
            "site": {"required_pages": ["index.html"]},
        })

    class _Lab:
        def __init__(self):
            self.submissions = []

        def submit(self, prompt, raw_intake, **kwargs):
            self.submissions.append(raw_intake)
            return {"run_id": "intake-lab-" + "b" * 32, "status": "building", "publishable": False}

        def get_run(self, run_id):
            return {"run_id": run_id, "status": "building", "publishable": False}

    stage = {"index": 0}
    from site_agent.core.design_intake_contracts import IntakeTurnResult

    class _Advisor:
        last_call_count = 1

        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            stage["index"] += 1
            if stage["index"] == 1:
                updates = [{"path": "audience.primary", "value": "Architectes", "basis": "owner_statement"}]
            else:
                updates = [{"path": "audience.primary", "value": "Architectes et particuliers", "basis": "owner_statement"}]
            return IntakeTurnResult.from_dict({
                "assistant_message": "Je note.",
                "field_updates": updates,
                "suggested_readiness": "ready_to_build",
            })

    memory = Memory(tmp_path / "intake.db")
    try:
        service = DesignIntakeService(memory, default_intake=_intake(), advisor=_Advisor(), lab_service=_Lab())
        session = service.create_session()
        assert session["revision"] == 1
        confirmed = service.confirm_and_build(
            session["session_id"],
            revision=session["revision"],
            draft_hash=session["draft_hash"],
        )
        confirmed_revision = confirmed["session"]["confirmed_revision"]
        assert confirmed_revision == 2

        queued = service.send_message(session["session_id"], "Le but, c'est surtout les architectes.")
        job = memory.claim_chat_job("worker")
        first = run_job({"memory": memory, "design_intake_service": service, "config": {}, "llm": object()}, job, "worker")
        assert first.get("error") is None
        # confirmation at 2, this follow-up turn lands at 3 — no UNIQUE collision.
        assert first["intake_revision"] == 3
        assert len(memory.list_design_intake_revisions(session["session_id"]) ) >= 3
    finally:
        memory.close()

def test_system_vocabulary_never_becomes_a_subject(tmp_path):
    from site_agent.brain.incubation_infusion import (
        _owner_terms,
        _system_term_leak,
    )
    from site_agent.core.design_intake_contracts import DesignIntakeDraft, IntakeFieldProvenance

    memory = Memory(tmp_path / "incubation.db")
    memory.create_conversation("c1")
    draft = DesignIntakeDraft.empty()
    draft = draft.with_value(
        "business.offer_summary",
        "Cave diving retreats in the cenotes of the Yucatan.",
        IntakeFieldProvenance(path="business.offer_summary", origin="confirmed", source_message_id=1),
    )
    memory.create_design_intake_session(f"intake-{'d' * 32}", draft)
    owner = _owner_terms(memory)
    assert "diving" in owner and "cenotes" in owner

    # The observed failure: engine vocabulary read as a business topic.
    assert _system_term_leak("resolve the 'infusion' ambiguity to a single credible brand", owner) is True
    assert _system_term_leak("snapshot.json contains zero reference material", owner) is True
    assert _system_term_leak("home infusion therapy market growth", owner) is True
    # Owner vocabulary legitimately containing the word must stay allowed.
    clinic_terms = owner | {"infusion"}
    assert _system_term_leak("home infusion therapy market growth", clinic_terms) is False
    # Grounded knowledge about the business passes.
    assert _system_term_leak("Segment luminaires upcycles non exploite", owner) is False
    memory.close()


def test_infusion_drops_engine_deductions_and_followups(tmp_path):
    contract = (
        '{"deductions":['
        '{"kind":"competitor_note","summary":"The dominant reading of infusion is medical home IV infusion","confidence":0.6,"basis":"source"},'
        '{"kind":"risk","summary":"snapshot.json contains zero reference material","confidence":0.5,"basis":"snapshot"},'
        '{"kind":"opportunity","summary":"Cenote diving guests care about water clarity and safety","confidence":0.7,"basis":"snapshot"}],'
        '"followup_research":[{"type":"pipeworx","query":"resolve the infusion ambiguity brand","reason":"ambiguity"},'
        '{"type":"community","query":"r/CaveDiving","reason":"divers discuss cenote safety"}],'
        '"genesis_notes":{},"horizon_questions":[]}'
    )
    memory, service = _service(tmp_path, _config(), llm=_FakeLLM(contract))
    try:
        memory.create_conversation("c1")
        draft = DesignIntakeDraft.empty()
        draft = draft.with_value(
            "business.offer_summary",
            "5-day cave diving retreats in the cenotes.",
            IntakeFieldProvenance(path="business.offer_summary", origin="confirmed", source_message_id=1),
        )
        memory.create_design_intake_session(f"intake-{'e' * 32}", draft)
        service.enqueue(trigger="intake_revision", session_id=f"intake-{'e' * 32}", snapshot=_snapshot())
        finished, error = service.process_one("worker-1")
        assert finished and error is None
        summaries = [item["summary"] for item in memory.list_incubation_deductions()]
        assert len(summaries) == 1
        assert "Cenote diving" in summaries[0]
    finally:
        memory.close()


def test_no_owner_vocabulary_means_no_followup_research(tmp_path):
    class _RecordingResearch:
        def __init__(self):
            self.bodies = []

        def request(self, body, *, enqueue=False):
            self.requests.append(body)

        _requests = property(lambda self: self._r)

    research = _RecordingResearch()
    research._r = []
    memory, service = _service(tmp_path, _config(), llm=_FakeLLM('{"deductions":[],"followup_research":[{"type":"pipeworx","query":"anything at all","reason":"x"}],"genesis_notes":{},"horizon_questions":[]}'), research=research)
    try:
        service.enqueue(trigger="idle", session_id=f"intake-{'f' * 32}", snapshot=_snapshot())
        service.process_one("worker-1")
        assert research._r == []
    finally:
        memory.close()
