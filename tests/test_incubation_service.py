from types import SimpleNamespace

from site_agent.application.incubations import IncubationApplicationService, IncubationRuntime
from site_agent.application.incubations import IncubationServiceError
from site_agent.config import load_intake_config
from site_agent.core.design_contracts import DesignRunStatus, SiteIntake
from site_agent.core.design_intake_contracts import DesignIntakeDraft
from site_agent.core.incubation_contracts import CustomerAdaGenesis, IncubationDeduction, IncubationInsight, NoveltyContext
from site_agent.core.intake_ada_store import IntakeAdaStore

import pytest


def _service(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    config["incubation"]["scaffold"] = str(tmp_path / "scaffold")
    store = IntakeAdaStore(tmp_path / "intake-data" / "intake-ada.db")
    return IncubationApplicationService(store, root=tmp_path / "incubations", config=config), store


def _lifecycle_graph(service):
    record = service.create_incubation()
    scoped = service.open_store(record.incubation_id)
    conversation_id = scoped.memory.create_conversation("intake")
    session_id = "intake-" + "d" * 32
    intake = SiteIntake.from_dict({
        "schema_version": 1,
        "business": {"name": "Graph Studio", "offer_summary": "A clear service", "primary_services": ["Service"]},
        "audience": {"primary": "People evaluating the service"},
        "conversion": {"primary_action": "Get in touch", "not_available": True},
        "brand": {"voice": "Clear and warm"},
        "site": {"required_pages": ["index.html"]},
    })
    scoped.memory.create_design_intake_session(
        session_id,
        DesignIntakeDraft.from_site_intake(intake),
        conversation_id=conversation_id,
    )
    service.intake_service = lambda _incubation_id: SimpleNamespace(
        get_session=lambda _session_id: {"confirmed_revision_id": 7},
    )
    return record, scoped.memory, session_id, intake


def _graph_run(memory, intake, session_id, run_id, *, status, revision_id=7, parent_run_id=None):
    parent = memory.get_design_run(parent_run_id) if parent_run_id else None
    run = memory.create_design_run(
        run_id=run_id,
        mode="local_experiment",
        status=status,
        intake_json=intake.to_dict(),
        base_sha="a" * 40,
        candidate_ref=f"refs/ada-design-lab/{run_id}",
        parent_run_id=parent_run_id,
        source_candidate_sha=(parent or {}).get("candidate_sha", "") if parent_run_id else "",
        intake_session_id=session_id,
        intake_revision_id=revision_id,
    )
    if status in {DesignRunStatus.READY_FOR_REVIEW.value, DesignRunStatus.NEEDS_REPAIR.value}:
        run = memory.update_design_run(
            run_id,
            candidate_sha=("b" if not parent_run_id else "c") * 40,
            quality_report_json={"state": "passed", "checks": []},
        )
    return run


def test_each_incubation_has_a_distinct_durable_database(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        first = service.create_incubation()
        second = service.create_incubation()

        first_store = service.open_store(first.incubation_id)
        second_store = service.open_store(second.incubation_id)
        assert first_store.path != second_store.path
        assert first_store.path.name == "incubation.db"
        assert first_store.memory.create_conversation("first")
        assert second_store.memory.list_design_intake_sessions() == []

        assert service.get_or_create_default().incubation_id in {first.incubation_id, second.incubation_id}
    finally:
        service.close()
        intake_store.close()


def test_incubation_lifecycle_is_recorded_in_intake_registry(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        record = service.create_incubation()
        changed = service.transition(record.incubation_id, "researching", event="research_started")
        assert changed.status == "researching"
        assert [item["event"] for item in intake_store.list_events(record.incubation_id)] == ["created", "research_started"]
        assert service.summary(record.incubation_id)["genesis"]["revision"] == 1
    finally:
        service.close()
        intake_store.close()


def test_lifecycle_graph_keeps_building_for_an_active_child(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        record, memory, session_id, intake = _lifecycle_graph(service)
        root_id = "intake-lab-" + "a" * 32
        child_id = "design-" + "b" * 32
        _graph_run(memory, intake, session_id, root_id, status=DesignRunStatus.READY_FOR_REVIEW.value)
        _graph_run(
            memory,
            intake,
            session_id,
            child_id,
            status=DesignRunStatus.BUILDING.value,
            parent_run_id=root_id,
        )
        memory.update_design_intake_session(session_id, design_run_id=root_id)
        service.transition(record.incubation_id, "ready_to_build", event="intake_confirmed")
        service.transition(record.incubation_id, "building", event="build_started")

        refreshed = service._refresh_lifecycle(record.incubation_id)

        assert refreshed.status == "building"
    finally:
        service.close()
        intake_store.close()


def test_lifecycle_graph_advances_collecting_incubation_before_active_build(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        record, memory, session_id, intake = _lifecycle_graph(service)
        root_id = "intake-lab-" + "g" * 32
        _graph_run(memory, intake, session_id, root_id, status=DesignRunStatus.BUILDING.value)
        memory.update_design_intake_session(session_id, design_run_id=root_id)

        refreshed = service._refresh_lifecycle(record.incubation_id)

        assert refreshed.status == "building"
        assert [item["event"] for item in intake_store.list_events(record.incubation_id)][-2:] == [
            "descendant_ready_to_build",
            "descendant_active",
        ]
    finally:
        service.close()
        intake_store.close()


def test_lifecycle_graph_promotes_ready_parent_when_child_failed(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        record, memory, session_id, intake = _lifecycle_graph(service)
        root_id = "intake-lab-" + "c" * 32
        child_id = "design-" + "e" * 32
        _graph_run(memory, intake, session_id, root_id, status=DesignRunStatus.READY_FOR_REVIEW.value)
        _graph_run(
            memory,
            intake,
            session_id,
            child_id,
            status=DesignRunStatus.FAILED.value,
            parent_run_id=root_id,
        )
        memory.update_design_intake_session(session_id, design_run_id=root_id)
        service.transition(record.incubation_id, "ready_to_build", event="intake_confirmed")
        service.transition(record.incubation_id, "building", event="build_started")

        refreshed = service._refresh_lifecycle(record.incubation_id)

        assert refreshed.status == "ready_for_feedback"
        assert service.get_record(record.incubation_id).status == "ready_for_feedback"
    finally:
        service.close()
        intake_store.close()


def test_lifecycle_graph_ignores_an_older_confirmed_revision(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        record, memory, session_id, intake = _lifecycle_graph(service)
        old_root_id = "intake-lab-" + "f" * 32
        _graph_run(
            memory,
            intake,
            session_id,
            old_root_id,
            status=DesignRunStatus.BUILDING.value,
            revision_id=6,
        )
        memory.update_design_intake_session(session_id, design_run_id=old_root_id)
        service.transition(record.incubation_id, "ready_to_build", event="intake_confirmed")
        service.transition(record.incubation_id, "building", event="build_started")

        refreshed = service._refresh_lifecycle(record.incubation_id)

        assert refreshed.status == "building"
        assert intake_store.list_events(record.incubation_id)[-1]["event"] == "build_started"
    finally:
        service.close()
        intake_store.close()


class _Worker:
    def __init__(self):
        self.starts = 0
        self.stops = 0
        self.joins = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1

    def join(self, timeout=None):
        self.joins += 1


def test_workers_start_for_runtimes_created_after_service_start(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    config["incubation"]["scaffold"] = str(tmp_path / "scaffold")
    store = IntakeAdaStore(tmp_path / "intake-data" / "intake-ada.db")
    workers = []

    def runtime_factory(_scoped):
        worker = _Worker()
        workers.append(worker)
        return IncubationRuntime(chat_executor=worker)

    service = IncubationApplicationService(
        store,
        root=config["incubation"]["root"],
        config=config,
        runtime_factory=runtime_factory,
    )
    try:
        first = service.create_incubation()
        service.runtime(first.incubation_id)
        service.start()
        second = service.create_incubation()
        service.runtime(second.incubation_id)

        assert [worker.starts for worker in workers] == [1, 1]
        service.stop()
        assert [worker.stops for worker in workers] == [1, 1]
        assert [worker.joins for worker in workers] == [1, 1]
    finally:
        service.close()
        store.close()


def test_start_recovers_queued_research_worker_after_service_restart(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    config["incubation"]["scaffold"] = str(tmp_path / "scaffold")
    store = IntakeAdaStore(tmp_path / "intake-data" / "intake-ada.db")
    workers = []

    def runtime_factory(_scoped):
        worker = _Worker()
        workers.append(worker)
        return IncubationRuntime(research_executor=worker)

    first = IncubationApplicationService(
        store,
        root=config["incubation"]["root"],
        config=config,
        runtime_factory=runtime_factory,
    )
    record = first.create_incubation()
    try:
        source = first.research_service(record.incubation_id).discover(["https://example.com/feed.xml"])
        source_id = source["source_ids"][0]
        first.update_research_source(record.incubation_id, source_id, {"trust_state": "allowed"})
        queued = first.request_research(record.incubation_id, {
            "source_ids": [source_id],
            "fetch": True,
            "query": "audience market",
        })
        assert queued["status"] == "queued"
    finally:
        first.close()

    second = IncubationApplicationService(
        store,
        root=config["incubation"]["root"],
        config=config,
        runtime_factory=runtime_factory,
    )
    try:
        second.start()
        assert workers[-1].starts == 1
    finally:
        second.close()
        store.close()


def test_research_waiting_for_source_approval_is_recorded_as_blocked(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        record = service.create_incubation()
        result = service.request_research(record.incubation_id, {
            "fetch": True,
            "query": "audience context",
        })

        assert result["status"] == "awaiting_source_approval"
        assert service.get_record(record.incubation_id).status == "collecting"
        assert intake_store.list_events(record.incubation_id)[-1]["event"] == "research_blocked"
    finally:
        service.close()
        intake_store.close()


def test_incubated_creative_context_freezes_owner_research_novelty_and_skills(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        record = service.create_incubation()
        scoped = service.open_store(record.incubation_id)
        finding_id = "finding_" + "a" * 32
        scoped.memory.save_incubation_insight(IncubationInsight.from_dict({
            "insight_id": "insight_" + "b" * 32,
            "kind": "audience_language",
            "summary": "French-speaking visitors look for concise technical reassurance.",
            "owner_language": "en",
            "source_languages": ["fr"],
            "finding_ids": [finding_id],
            "supports_paths": ["audience.primary"],
            "contradicts_paths": [],
            "confidence": 0.7,
            "status": "inferred",
            "created_at": "2026-09-03T12:00:00+00:00",
        }))
        intake = SiteIntake.from_dict({
            "schema_version": 1,
            "business": {"name": "Cedar Studio", "offer_summary": "A technical service.", "primary_services": ["Consulting"]},
            "audience": {"primary": "Technical buyers"},
            "conversion": {"primary_action": "Contact us", "not_available": True},
            "brand": {"voice": "Calm and direct"},
            "site": {"required_pages": ["index.html"], "language": "en"},
        })
        novelty = NoveltyContext.from_dict({
            "query_hash": "c" * 64,
            "constraints": ["avoid repetitive cards"],
            "matches": [],
        })

        context = service._incubated_creative_context(
            record.incubation_id,
            session={
                "session_id": "session_context",
                "summary": {
                    "confirmed": {
                        "brand.visual_preferences": ["quiet editorial pacing"],
                        "brand.visual_dislikes": ["generic gradients"],
                    },
                    # Owner-facing direction often arrives as advised (Ada
                    # proposed it, owner accepted) or as a reversible assumed
                    # default. Both are the business's own voice and must reach
                    # the builder — MergePreferencePaths covers any subject.
                    "advised": {"brand.vibe": "warm workshop light"},
                    "assumed": {"brand.colors": "ink blue and oak"},
                },
            },
            intake=intake,
            novelty=novelty,
        )

        assert context.genesis_revision == 1
        assert context.owner_confirmed_visual_preferences == ("quiet editorial pacing", "warm workshop light", "ink blue and oak")
        assert context.owner_confirmed_visual_dislikes == ("generic gradients",)
        assert context.cross_language_audience_insights[0]["source_languages"] == ["fr"]
        assert context.design_skill_set is not None
        assert context.design_skill_set.content_hash
        assert any(item["kind"] == "creative_context_frozen" for item in service.activity_projection(record.incubation_id)["activities"])
    finally:
        service.close()
        intake_store.close()


def test_incubated_creative_context_carries_genesis_and_infusion_deductions(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        record = service.create_incubation()
        scoped = service.open_store(record.incubation_id)
        current = service.genesis_service(record.incubation_id).current()
        genesis = CustomerAdaGenesis.from_dict({
            **current.to_dict(),
            "revision": current.revision + 1,
            "business_world": {
                **current.business_world,
                "values": ["careful workmanship"],
            },
            "creative_identity": {
                **current.creative_identity,
                "principles": ["make the useful detail visible"],
            },
            "research_identity": {
                **current.research_identity,
                "subjects": ["technical buyers"],
            },
        })
        service.genesis_service(record.incubation_id).save(genesis, source_kind="test")
        scoped.memory.save_incubation_deduction(IncubationDeduction.from_dict({
            "schema_version": 1,
            "deduction_id": "deduction_" + "d" * 32,
            "kind": "audience_hypothesis",
            "summary": "Technical buyers need proof before the first conversation.",
            "confidence": 0.8,
            "basis": "source",
            "source_refs": ["source_public"],
            "supports_paths": ["audience.primary"],
            "horizon_questions": [],
            "discovered_by": "opencode",
            "citation_uris": ["pipeworx://source/public"],
            "run_id": "infusion_" + "e" * 32,
            "created_at": "2026-09-03T12:00:00+00:00",
        }))
        intake = SiteIntake.from_dict({
            "schema_version": 1,
            "business": {"name": "Cedar Studio", "offer_summary": "A technical service.", "primary_services": ["Consulting"]},
            "audience": {"primary": "Technical buyers"},
            "conversion": {"primary_action": "Contact us", "not_available": True},
            "brand": {"voice": "Calm and direct"},
            "site": {"required_pages": ["index.html"], "language": "en"},
        })
        novelty = NoveltyContext.from_dict({
            "query_hash": "c" * 64,
            "constraints": [],
            "matches": [],
        })

        context = service._incubated_creative_context(
            record.incubation_id,
            session={"session_id": "session_genesis", "summary": {}},
            intake=intake,
            novelty=novelty,
        )

        assert context.customer_genesis["business_world"]["values"] == ["careful workmanship"]
        assert context.customer_genesis["creative_identity"]["principles"] == ["make the useful detail visible"]
        assert context.customer_genesis["research_identity"]["subjects"] == ["technical buyers"]
        assert context.infusion_deductions[0]["summary"].startswith("Technical buyers need proof")
        assert context.infusion_deductions[0]["citation_uris"] == ["pipeworx://source/public"]
    finally:
        service.close()
        intake_store.close()


def test_incubated_creative_context_is_subject_neutral_across_businesses(tmp_path):
    # The same neutral machinery must enrich a cave-diving site and a
    # sanitary-ware site equally: only the evidence differs, never the code path.
    service, intake_store = _service(tmp_path)
    try:
        def build_context(name, prefs, insights):
            record = service.create_incubation()
            scoped = service.open_store(record.incubation_id)
            for index, text in enumerate(insights):
                scoped.memory.save_incubation_insight(IncubationInsight.from_dict({
                    "insight_id": f"insight_{'a' * 31}{index}",
                    "kind": "creative_implication",
                    "summary": text,
                    "owner_language": "en",
                    "source_languages": [],
                    "finding_ids": [],
                    "supports_paths": ["site.required_pages"],
                    "contradicts_paths": [],
                    "confidence": 0.6,
                    "status": "inferred",
                    "created_at": "2026-09-03T12:00:00+00:00",
                }))
            intake = SiteIntake.from_dict({
                "schema_version": 1,
                "business": {"name": name, "offer_summary": "A service.", "primary_services": ["Service"]},
                "audience": {"primary": "Customers"},
                "conversion": {"primary_action": "Book", "not_available": True},
                "brand": {"voice": "Calm"},
                "site": {"required_pages": ["index.html"], "language": "en"},
            })
            novelty = NoveltyContext.from_dict({"query_hash": "c" * 64, "constraints": [], "matches": []})
            context = service._incubated_creative_context(
                record.incubation_id,
                session={"session_id": "intake-" + "d" * 32, "summary": {"advised": {"brand.visual_preferences": [prefs]}}},
                intake=intake,
                novelty=novelty,
            )
            return {
                "prefs": " ".join(context.owner_confirmed_visual_preferences),
                "insights": " ".join(item["summary"] for item in context.research_backed_creative_implications),
            }

        cave = build_context("Cave Diving Co", "shafts of daylight", ["The cenote walls reward slow reveals."])
        toilet = build_context("Lumen Sanitaryware", "porcelain matte finish", ["Clean lines reduce perceived service risk."])

        # Identical code path produced different, subject-correct evidence.
        assert "shafts of daylight" in cave["prefs"]
        assert "porcelain matte finish" in toilet["prefs"]
        assert "cenote walls" in cave["insights"]
        assert "sanitary" not in cave["insights"]
        assert "cenote" not in toilet["insights"].lower()
    finally:
        service.close()
        intake_store.close()


def test_blocked_candidate_can_be_rebuilt(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        inc = service.create_incubation()
        service.transition(inc.incubation_id, "ready_to_build", event="intake_confirmed")
        service.transition(inc.incubation_id, "building", event="build_started")
        service.transition(inc.incubation_id, "blocked", event="candidate_failed", detail={"run_id": "run-1", "status": "failed"})
        with pytest.raises(IncubationServiceError, match="design build service is unavailable"):
            service.build(inc.incubation_id, {})
    finally:
        service.close()
        intake_store.close()


def test_collecting_incubation_is_not_buildable(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        inc = service.create_incubation()
        with pytest.raises(IncubationServiceError, match="incubation is not ready to build"):
            service.build(inc.incubation_id, {})
    finally:
        service.close()
        intake_store.close()


def test_build_while_building_reconnects_instead_of_rejecting(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        inc = service.create_incubation()
        service.transition(inc.incubation_id, "ready_to_build", event="intake_confirmed")
        service.transition(inc.incubation_id, "building", event="build_started")
        with pytest.raises(IncubationServiceError, match="design build service is unavailable"):
            service.build(inc.incubation_id, {})
    finally:
        service.close()
        intake_store.close()


def test_explicit_force_new_rebuilds_ready_candidate_from_confirmed_intake(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        record, memory, session_id, intake = _lifecycle_graph(service)
        service.transition(record.incubation_id, "ready_to_build", event="intake_confirmed")
        service.transition(record.incubation_id, "building", event="build_started")
        service.transition(record.incubation_id, "ready_for_feedback", event="candidate_ready")

        draft = DesignIntakeDraft.from_site_intake(intake).to_dict()
        calls = []

        class _Intake:
            def get_session(self, requested_session_id):
                return {
                    "session_id": requested_session_id,
                    "status": "confirmed",
                    "revision": 7,
                    "confirmed_revision": 7,
                    "confirmed_revision_id": 7,
                    "draft": draft,
                }

            def build(self, requested_session_id, **kwargs):
                calls.append((requested_session_id, kwargs))
                return {
                    "session": self.get_session(requested_session_id),
                    "run": {"run_id": "fresh-run", "status": "building"},
                }

        runtime = IncubationRuntime(lab_service=object(), intake_service=_Intake())
        service._runtimes[record.incubation_id] = runtime
        service.intake_service = lambda _incubation_id: runtime.intake_service
        service.novelty_service = lambda _incubation_id: SimpleNamespace(
            context_for=lambda _intake: NoveltyContext.from_dict({
                "query_hash": "c" * 64,
                "constraints": [],
                "matches": [],
            })
        )
        service._incubated_creative_context = lambda *args, **kwargs: SimpleNamespace(
            genesis_revision=7,
            research_backed_creative_implications=(),
            to_dict=lambda: {},
        )
        service.activity_service = lambda _incubation_id: SimpleNamespace(record=lambda **kwargs: None)

        with pytest.raises(IncubationServiceError, match="incubation is not ready to build"):
            service.build(record.incubation_id, {"confirmed_revision": 7})

        result = service.build(record.incubation_id, {
            "confirmed_revision": 7,
            "force_new": True,
            "idempotency_key": "explicit-rerun",
        })

        assert result["run"]["run_id"] == "fresh-run"
        assert calls[0][1]["force_new"] is True
        assert service.get_record(record.incubation_id).status == "building"
        assert runtime.intake_service.get_session(session_id)["confirmed_revision"] == 7
    finally:
        service.close()
        intake_store.close()


def test_default_prefers_incumbent_conversation_over_a_newer_shell(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        incumbent = service.create_incubation()
        shell = service.create_incubation()
        scoped = service.open_store(incumbent.incubation_id)
        conversation_id = scoped.memory.create_conversation("Website design intake")
        scoped.memory.create_design_intake_session("intake-" + "a" * 32, conversation_id=conversation_id)

        default = service.get_or_create_default()
        assert default.incubation_id == incumbent.incubation_id
    finally:
        service.close()
        intake_store.close()


def test_asset_visual_notes_exclude_inspiration_only_and_sanitize():
    from site_agent.application.incubations import _asset_visual_reference_notes

    assets = [
        {"id": 1, "name": "logo.webp", "usage": "website",
         "description": "Un logo ocre et la signature de l'atelier", "tags": ["logo", "ocre"],
         "dominant_colors": ["#D97A35"], "suggested_uses": ["header"]},
        {"id": 2, "name": "mood.webp", "usage": "undecided",
         "description": "Contactez nous@exemple.fr sur http://atelier.test", "dominant_colors": []},
        {"id": 3, "name": "secret.webp", "usage": "inspiration_only",
         "description": "Ne pas intégrer", "dominant_colors": []},
    ]
    notes = _asset_visual_reference_notes(assets)
    assert len(notes) == 2
    assert "Inspiration Only" not in notes[0] and "logo.webp" in notes[0]
    assert "palette: #D97A35" in notes[0]
    assert "us@exemple" not in notes[1] and "[contact]" in notes[1]
    assert "http://atelier.test" not in notes[1]


def test_purge_evicts_cached_runtime_and_keeps_only_a_tombstone(tmp_path):
    service, intake_store = _service(tmp_path)
    try:
        record = service.create_incubation()
        incubation_id = record.incubation_id
        store = service.open_store(incubation_id)
        conversation_id = store.memory.create_conversation("first")
        store.memory.add_message(conversation_id, "user", "hello there")
        assert service.runtime(incubation_id) is not None

        assert service.purge(incubation_id) is True
        assert not (tmp_path / "incubations" / incubation_id).exists()
        assert incubation_id not in service._runtimes
        assert incubation_id not in service._stores

        with pytest.raises(IncubationServiceError, match="not found"):
            service.get_record(incubation_id)
        with pytest.raises(IncubationServiceError, match="not found"):
            service.open_store(incubation_id)
        assert intake_store.get_incubation(incubation_id) is None
        tombstone = intake_store.get_incubation(incubation_id, include_purged=True)
        assert tombstone is not None
        assert tombstone.status == "purged"
        assert tombstone.workspace_path == ""
        assert intake_store.list_events(incubation_id) == []
        assert intake_store.list_events(incubation_id, include_purged=True)[0]["detail"]["outcome"] == "removed"
        with pytest.raises(IncubationServiceError, match="identity was purged"):
            service.create_incubation(incubation_id=incubation_id)
        assert service.purge(incubation_id) is True
    finally:
        service.close()
        intake_store.close()


def test_failed_purge_is_non_reopenable_and_retryable(tmp_path, monkeypatch):
    service, intake_store = _service(tmp_path)
    incubation_id = None
    try:
        record = service.create_incubation()
        incubation_id = record.incubation_id

        def fail_remove(_path):
            raise OSError("simulated removal failure")

        monkeypatch.setattr("site_agent.application.incubations.shutil.rmtree", fail_remove)
        with pytest.raises(IncubationServiceError, match="workspace removal"):
            service.purge(incubation_id)

        assert intake_store.get_incubation(incubation_id) is None
        tombstone = intake_store.get_incubation(incubation_id, include_purged=True)
        assert tombstone is not None
        assert tombstone.status == "purged"
        assert intake_store.list_events(incubation_id, include_purged=True)[0]["detail"]["outcome"] == "failed"
    finally:
        monkeypatch.undo()
        if incubation_id is not None:
            assert service.purge(incubation_id) is True
        service.close()
        intake_store.close()
