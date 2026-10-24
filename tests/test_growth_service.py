import json
import pytest
from types import SimpleNamespace

from site_agent.application.growth_workflow import _persist_evidence_artifact, ensure_default_goal, has_recoverable_growth_replay, has_recoverable_historical_noop, run_growth_cycle, run_pending_growth
from site_agent.application.growth_tasks import growth_tasks
from site_agent.core.jobs import _has_recoverable_article_sync, register_growth_jobs, register_jobs
from site_agent.core.growth_contracts import GrowthPolicy
from site_agent.core.memory import Memory
from site_agent.core.scheduler import Scheduler


@pytest.fixture(autouse=True)
def github_journal_transport(monkeypatch):
    from tests.test_growth_delivery import GitHub
    from site_agent.application import growth_delivery
    github = GitHub()
    monkeypatch.setattr(growth_delivery, "_request", github)
    monkeypatch.setattr(growth_delivery, "github_api_token", lambda *_args: "test-token")
    return github


def config():
    return {
        "instance_name": "test-business",
        "scheduler": {"enabled": True},
        "growth": {"timezone": "America/Cancun", "approval_required": True},
        "site": {"repository": "owner/customer", "website_present": True, "public_url": "https://business.test", "payload": {"enabled": True}},
    }


class Payload:
    def __init__(self):
        self.live = {"id": "1", "sourceId": "page:home", "slug": "home", "title": "Business", "summary": "Local service", "metaDescription": "", "updatedAt": "revision-1"}
        self.draft = dict(self.live)
        self.writes = 0
        self.apply_calls = 0
        self.publishes = 0
        self.growth_contract_checks = 0
        self.contract = SimpleNamespace(collections=("pages",), collection_fields={"pages": frozenset(("title", "summary", "metaDescription"))}, globals=())

    def list(self, collection, *, draft=True, **kwargs):
        return [dict(self.draft if draft else self.live)]

    def require_growth_contract(self):
        self.growth_contract_checks += 1
        return {"version": 1}

    def require_authoring_contract(self):
        return {
            "version": 1,
            "locales": ["en"],
            "defaultLocale": "en",
            "enabled": {"collections": ["pages"], "globals": []},
            "authoring": {
                "collections": {"pages": [{"name": field} for field in self.contract.collection_fields["pages"]]},
                "globals": {},
            },
        }

    def authoring_fields(self, kind, slug, *, authoring_contract=None):
        if kind == "collection" and slug == "pages":
            return tuple(self.contract.collection_fields["pages"])
        raise AssertionError((kind, slug))

    def validate_growth_candidate(self, package, package_hash):
        return {
            "status": "passed", "packageHash": package_hash, "tenant": "test-business",
            "checks": {
                "canonicalSchema": True, "exactDraft": True, "private": True,
                "publicRenderer": True, "approvalBoundary": True,
            },
            "preview": {
                "status": "passed", "route": package.get("route") or "/",
                "kind": "page", "collection": package.get("collection"),
                "documentId": package.get("documentId"),
                "documentHash": "sha256:" + "a" * 64,
                "verifiedAt": "2026-10-23T00:00:00Z", "expiresAt": 1792713600,
            },
        }

    def read(self, collection, *, draft=True, **kwargs):
        return dict(self.draft if draft else self.live)

    def update(self, collection, document_id, data, **kwargs):
        self.writes += 1
        self.draft.update(
            data, updatedAt=f"revision-{self.writes + 1}",
            _helloadaRevision="sha256:" + f"{self.writes:064x}",
        )
        return dict(self.draft)

    def apply_growth_candidate(self, package, package_hash):
        assert package_hash
        self.apply_calls += 1
        if any(self.draft.get(key) != value for key, value in package["after"].items()):
            self.update(package["collection"], package["documentId"], package["changes"])
        return {"ok": True, "candidateHash": package["candidateHash"]}

    def publish_growth_candidate(self, package_hash):
        raise AssertionError("scheduled work must not publish")

    def publish(self, *args, **kwargs):
        self.publishes += 1
        raise AssertionError("scheduled work must not publish")


class Ada:
    def __init__(self):
        self.stages = []

    def chat(self, messages, **kwargs):
        material = json.loads(messages[-1]["content"])
        self.stages.append(material.get("stage"))
        if material.get("stage") == "prepare":
            return json.dumps({"status": "supported", "changes": {"metaDescription": "Local service from Business. Explore the services and contact the team."}})
        return json.dumps({"summary": "The homepage needs a useful search description.", "opportunities": [{"kind": "payload_content", "primaryArea": "search_visibility", "title": "Make the homepage clearer in search", "why": "The homepage has no description.", "hypothesis": "A clear description explains the service to search visitors.", "collection": "pages", "documentId": "1", "evidence": ["inventory", "ga4"], "requiredSources": ["inventory"], "scope": "Improve the homepage meta description without changing its visible design.", "metric": "gsc.clicks"}]})


def test_live_payload_registers_one_growth_service_not_independent_producers(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="America/Cancun")
    settings = config()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": Payload(), "llm": Ada()}
    register_jobs(scheduler, settings, context)
    names = [name for name, _, _ in scheduler.jobs]
    assert {"growth_initial", "growth_daily", "growth_weekly", "growth_monthly", "growth_pending", "growth_article_sync"} <= set(names)
    assert "seo_outcomes" in names
    assert not set(names) & {"article", "seo_insight", "seo_research_cycle", "seo_site_report_cycle", "article_research_cycle", "growth_reconciler"}
    assert all(item["next_run"] is not None for item in scheduler.upcoming())
    memory.close()


def test_payload_revision_write_failure_never_restores_the_held_old_approval():
    from site_agent.application.growth_candidates import restore_growth_source_revision

    class MemoryStub:
        def __init__(self):
            self.initiative = {
                "id": 8, "state": "validating",
                "validation": {"revision": {
                    "candidateType": "payload_content", "writeAttempted": True,
                    "previousDraftId": 63, "previousReviewPackageHash": "old-hash",
                }},
                "draft_id": 63,
            }
            self.draft = {"id": 63, "status": "pending", "meta": {
                "review_package_hash": "old-hash", "growth_revision_pending": True,
            }}

        def list_strategy_initiatives(self, limit=None):
            return [self.initiative]

        def list_drafts(self, limit=500):
            return [self.draft]

        def update_strategy_initiative(self, _id, **kwargs):
            self.initiative.update(kwargs)

    memory = MemoryStub()
    assert restore_growth_source_revision(memory, 8, "Payload write outcome is uncertain")
    assert memory.initiative["state"] == "validating"
    assert memory.initiative["validation"]["revision"]["status"] == "uncertain"
    assert memory.draft["status"] == "pending"
    assert memory.draft["meta"]["growth_revision_pending"] is True


def test_payload_revision_retry_resumes_exact_checkpoint_after_old_approval_closes(tmp_path, monkeypatch):
    from site_agent.application.growth_candidates import content_hash, finalize_payload_growth_revision

    memory = Memory(tmp_path / "payload-revision-retry.db")
    payload = Payload()
    context = {
        "tenant_id": "test-business", "config": config(), "memory": memory,
        "payload_gateway": payload, "llm": Ada(),
    }
    run = run_growth_cycle(context, trigger="weekly")
    assert run["status"] == "complete"
    initiative, = memory.list_strategy_initiatives(limit=None)
    previous_draft = memory.get_draft(int(initiative["draft_id"]))
    previous_package = previous_draft["meta"]["growth_package"]
    previous_hash = previous_draft["meta"]["review_package_hash"]
    previous_approval_id = int(initiative["approval_id"])
    memory.update_draft_meta(previous_draft["id"], {
        **previous_draft["meta"], "growth_revision_pending": True,
        "growth_revision_initiative_id": initiative["id"],
    })
    updated = payload.update("pages", "1", {
        "metaDescription": "A clearer revised description for local service customers.",
    })
    receipt = {
        "kind": "collection", "operation": "update", "target": "pages", "document_id": "1",
        "revision": updated["_helloadaRevision"], "locale": "en", "fields": ["metaDescription"],
    }
    revision_request = {
        "initiativeId": int(initiative["id"]), "chatJobId": 9001,
        "previousDraftId": int(previous_draft["id"]), "previousApprovalId": previous_approval_id,
        "previousReviewPackageHash": previous_hash, "candidateType": "payload_content",
        "collection": "pages", "documentId": "1", "baseHash": previous_package["baseHash"],
        "previousCandidateHash": previous_package["candidateHash"], "fields": list(previous_package["fields"]),
    }
    validation = dict(initiative.get("validation") or {})
    validation.update({"status": "validating", "revision": {
        **revision_request, "writeAttempted": True, "locale": "en",
        "writeTarget": {"collection": "pages", "documentId": "1", "fields": ["metaDescription"]},
    }})
    memory.transition_strategy_initiative(
        int(initiative["id"]), "validating", expected_state="ready_for_review", validation=validation,
    )

    with pytest.raises(ValueError, match="receipt exceeds or differs"):
        finalize_payload_growth_revision(context, revision_request, [{
            **receipt, "fields": ["metaDescription", "title"],
        }])
    assert memory.get_approval_request(previous_approval_id).status.value == "pending"

    update_draft_status = memory.update_draft_status
    failed_once = False

    def interrupt_after_old_decision(draft_id, status):
        nonlocal failed_once
        if int(draft_id) == int(previous_draft["id"]) and status == "superseded" and not failed_once:
            failed_once = True
            raise RuntimeError("injected crash after old approval decision")
        return update_draft_status(draft_id, status)

    monkeypatch.setattr(memory, "update_draft_status", interrupt_after_old_decision)
    with pytest.raises(RuntimeError, match="injected crash"):
        finalize_payload_growth_revision(context, revision_request, [receipt])
    assert memory.get_approval_request(previous_approval_id).status.value == "declined"
    assert payload.writes == 2  # one initial candidate write plus the one revision write
    interrupted = next(
        row for row in memory.list_strategy_initiatives(limit=None)
        if int(row["id"]) == int(initiative["id"])
    )
    checkpoint = interrupted["validation"]["revision"]
    checkpoint_draft = memory.get_draft(int(checkpoint["newDraftId"]))
    assert checkpoint_draft["meta"]["review_package_hash"] == checkpoint["newReviewPackageHash"]
    assert memory.get_approval_request(int(checkpoint["newApprovalId"])).status.value == "pending"
    revised_decision = memory.conn.execute(
        "SELECT 1 FROM strategy_decisions WHERE initiative_id = ? AND decision = 'revised' "
        "AND source_revision = '' AND review_package_hash = ?",
        (int(initiative["id"]), previous_hash),
    ).fetchone()
    assert revised_decision is not None

    monkeypatch.setattr(memory, "update_draft_status", update_draft_status)
    completed = finalize_payload_growth_revision(context, revision_request, [receipt])
    assert completed["idempotent"] is False
    assert payload.writes == 2
    current = next(row for row in memory.list_strategy_initiatives(limit=None) if int(row["id"]) == int(initiative["id"]))
    replacement = memory.get_draft(int(current["draft_id"]))
    assert replacement["status"] == "pending"
    assert replacement["meta"]["review_package_hash"] == current["review_package_hash"]
    assert content_hash(replacement["meta"]["growth_package"]) == current["review_package_hash"]
    assert memory.get_approval_request(int(current["approval_id"])).status.value == "pending"
    assert memory.get_approval_request(previous_approval_id).status.value == "declined"
    payload_candidate_drafts = [row for row in memory.list_drafts(limit=None) if row.get("kind") == "payload_content"]
    assert len(payload_candidate_drafts) == 2
    assert sorted(row["status"] for row in payload_candidate_drafts) == ["pending", "superseded"]
    memory.close()


def test_weekly_service_prepares_real_draft_without_publication_or_duplicate_work(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    context = {"tenant_id": "test-business", "config": config(), "memory": memory, "payload_gateway": payload, "llm": Ada()}
    first = run_growth_cycle(context, trigger="weekly")
    assert first["status"] == "complete"
    assert first["detail"]["candidateIds"]
    candidates = memory.list_strategy_initiatives()
    assert len(candidates) == 1
    assert candidates[0]["state"] == "ready_for_review"
    assert candidates[0]["review_package_hash"]
    assert memory.list_drafts()[0]["kind"] == "payload_content"
    assert payload.draft["metaDescription"]
    assert payload.live["metaDescription"] == ""
    assert payload.publishes == 0
    second = run_growth_cycle(context, trigger="weekly")
    assert second["run_id"] == first["run_id"]
    assert payload.writes == 1
    memory.close()


def test_growth_candidate_gets_one_exact_schema_correction_before_payload_write(tmp_path):
    class CorrectingAda(Ada):
        def chat(self, messages, **kwargs):
            material = json.loads(messages[-1]["content"])
            if material.get("stage") != "prepare":
                return super().chat(messages, **kwargs)
            self.stages.append("prepare")
            if "correction" not in material:
                return json.dumps({"status": "supported", "changes": {"madeUpField": "not allowed"}})
            return json.dumps({"status": "supported", "changes": {"metaDescription": "Local service from Business. Explore the services and contact the team."}})

    memory = Memory(tmp_path / "memory.db")
    payload, planner = Payload(), CorrectingAda()
    run = run_growth_cycle({"tenant_id": "test-business", "config": config(), "memory": memory, "payload_gateway": payload, "llm": planner}, trigger="weekly")

    assert run["status"] == "complete"
    assert len(run["detail"]["candidateIds"]) == 1
    assert planner.stages == ["assess", "prepare", "prepare"]
    assert payload.writes == 1
    assert payload.draft["metaDescription"].startswith("Local service")
    assert memory.list_strategy_initiatives()[0]["state"] == "ready_for_review"
    memory.close()


def test_growth_candidate_stops_after_one_failed_schema_correction(tmp_path):
    class InvalidAda(Ada):
        def chat(self, messages, **kwargs):
            material = json.loads(messages[-1]["content"])
            if material.get("stage") != "prepare":
                return super().chat(messages, **kwargs)
            self.stages.append("prepare")
            return json.dumps({"status": "supported", "changes": {"inventedField": "not allowed"}})

    memory = Memory(tmp_path / "memory.db")
    payload, planner = Payload(), InvalidAda()
    run = run_growth_cycle({"tenant_id": "test-business", "config": config(), "memory": memory, "payload_gateway": payload, "llm": planner}, trigger="weekly")

    assert run["status"] == "blocked"
    assert len(run["detail"]["blocks"]) == 1
    assert "after one correction" in run["detail"]["blocks"][0]["reason"]
    assert "inventedField" in run["detail"]["blocks"][0]["reason"]
    assert planner.stages == ["assess", "prepare", "prepare"]
    assert payload.writes == payload.publishes == 0
    assert memory.list_drafts() == []
    memory.close()


def test_unsupported_new_page_scope_is_deferred_without_creating_a_fake_task(tmp_path):
    class DeferredAda(Ada):
        def chat(self, messages, **kwargs):
            material = json.loads(messages[-1]["content"])
            if material.get("stage") != "prepare":
                return super().chat(messages, **kwargs)
            self.stages.append("prepare")
            return json.dumps({"status": "deferred", "reason": "This recommendation needs a new page and route; the current Growth review can only edit an existing Payload document.", "reassessWhen": "When the shared new-page route becomes available."})

    memory = Memory(tmp_path / "memory.db")
    payload, planner = Payload(), DeferredAda()
    run = run_growth_cycle({"tenant_id": "test-business", "config": config(), "memory": memory, "payload_gateway": payload, "llm": planner}, trigger="weekly")

    initiative = memory.list_strategy_initiatives()[0]
    assert run["status"] == "complete"
    assert run["detail"]["candidateIds"] == []
    assert run["detail"]["blocks"] == []
    assert run["detail"]["assessment"]["unpreparedOpportunities"][0]["errorCode"] == "unsupported_existing_document_route"
    assert initiative["state"] == "deferred"
    assert payload.writes == payload.publishes == 0
    assert memory.list_drafts() == []
    assert growth_tasks(memory, memory.list_strategy_initiatives(limit=None), memory.list_drafts(), [], [], runs=[run]) == []
    memory.close()


def test_payload_assessment_without_an_exact_inventory_target_is_deferred(tmp_path):
    class UnboundTargetAda(Ada):
        def chat(self, messages, **kwargs):
            material = json.loads(messages[-1]["content"])
            if material.get("stage") != "assess":
                return super().chat(messages, **kwargs)
            result = json.loads(super().chat(messages, **kwargs))
            result["opportunities"][0]["documentId"] = "missing-document"
            return json.dumps(result)

    memory = Memory(tmp_path / "memory.db")
    payload, planner = Payload(), UnboundTargetAda()
    run = run_growth_cycle({"tenant_id": "test-business", "config": config(), "memory": memory, "payload_gateway": payload, "llm": planner}, trigger="weekly")

    deferred = run["detail"]["assessment"]["unpreparedOpportunities"][0]
    assert run["status"] == "complete"
    assert deferred["errorCode"] == "target_not_in_canonical_inventory"
    assert deferred["disposition"] == "deferred"
    assert memory.list_strategy_initiatives(limit=None) == []
    assert payload.writes == 0
    assert planner.stages == ["assess"]
    memory.close()


def _failed_saved_assessment(memory, settings, *, error="Ada referenced evidence that is not in this run"):
    goal = ensure_default_goal(memory)
    policy = GrowthPolicy.from_config(settings)
    run = memory.create_growth_run(
        run_id="growth-historical-evidence-binding-failure",
        run_key="growth-historical-evidence-binding-failure-key",
        trigger="owner_review",
        goal_revision=goal["revision"],
        timezone=policy.timezone,
        phase="preparing",
        status="failed",
        policy=policy.to_dict(),
        origin_revision=policy.origin_revision,
        phase_version=2,
    )
    material = {
        "sources": [
            {"id": "inventory", "state": "ready", "sourceRef": "canonical_payload_inventory"},
            {"id": "ga4", "state": "ready", "sourceRef": "metrics_snapshot:1"},
        ],
        "inventory": [{
            "collection": "pages",
            "document": {"id": "1", "sourceId": "page:home", "slug": "home", "title": "Business", "summary": "Local service", "metaDescription": ""},
            "sourceRef": "payload:pages:1",
            "route": "/",
        }],
        "metrics": {},
        "datasets": {},
        "collectionErrors": {},
    }
    artifact_id, evidence_hash, _ = _persist_evidence_artifact(
        memory, run=run, goal=goal, policy=policy, sources=material["sources"], material=material,
    )
    opportunity = {
        "kind": "payload_content",
        "title": "Make the homepage clearer in search",
        "why": "The homepage has no search description.",
        "hypothesis": "A clear description helps search visitors understand the offer.",
        "collection": "pages",
        "documentId": "1",
        "evidence": ["inventory", "ga4"],
        "requiredSources": ["inventory"],
        "scope": "Improve the homepage meta description.",
        "metric": "gsc.clicks",
    }
    detail = {
        "material": material,
        "evidenceArtifactId": artifact_id,
        "evidenceHash": evidence_hash,
        "policy": policy.to_dict(),
        "assessment": {"summary": "The homepage has a clear, evidence-backed improvement.", "opportunities": [opportunity]},
        "error": error,
    }
    memory.update_growth_run(
        run["run_id"], detail=detail, next_due_ts="2099-10-16T04:08:16+00:00",
    )
    return run["run_id"]


def test_activation_resumes_partial_saved_run_after_bounded_owner_summary_failure(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    settings = config()
    run_id = _failed_saved_assessment(memory, settings, error="summary exceeds 500 characters")
    run = memory.get_growth_run(run_id)
    cycle = memory.growth_strategy_cycle(run_id, run["detail"]["evidenceArtifactId"])
    opportunity = run["detail"]["assessment"]["opportunities"][0]
    memory.create_strategy_initiative(
        cycle["id"], kind=opportunity["kind"], title=opportunity["title"], summary=opportunity["scope"],
        expected={"opportunity": opportunity}, state="blocked", growth_run_id=run_id,
        goal_revision=run["goal_revision"], origin_revision=run["origin_revision"],
    )
    assert has_recoverable_growth_replay(memory)

    planner = Ada()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": Payload(), "llm": planner}
    reconciled = []
    monkeypatch.setattr("site_agent.application.growth_workflow._reconcile_article_research", lambda _context: reconciled.append(True))
    run_pending_growth(context)

    resumed = memory.get_growth_run(run_id)
    assert resumed["status"] == "complete"
    assert resumed["detail"]["recoveryEvents"][-1]["code"] == "owner_action_summary_contract_fixed"
    assert "error" not in resumed["detail"]
    assert planner.stages == ["prepare"]
    assert reconciled == []
    memory.close()


def test_saved_initiative_transition_failure_replays_without_reassessing_or_repeating_research(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    settings = config()
    run_id = _failed_saved_assessment(
        memory,
        settings,
        error="invalid strategy initiative transition deferred -> blocked",
    )
    run = memory.get_growth_run(run_id)
    detail = dict(run["detail"])
    payload_opportunity = detail["assessment"]["opportunities"][0]
    owner_opportunity = {
        "kind": "owner_information",
        "title": "Confirm the appointment duration",
        "scope": "Tell Ada how long a standard appointment takes.",
        "why": "The public booking information does not specify appointment duration.",
        "evidence": ["inventory"],
        "requiredSources": [],
    }
    detail["assessment"]["opportunities"].append(owner_opportunity)
    detail["candidateIds"] = []
    cycle = memory.growth_strategy_cycle(run_id, detail["evidenceArtifactId"])
    deferred_id = memory.create_strategy_initiative(
        cycle["id"],
        kind="payload_content",
        title=payload_opportunity["title"],
        summary=payload_opportunity["scope"],
        expected={"opportunity": payload_opportunity},
        state="deferred",
        growth_run_id=run_id,
        goal_revision=run["goal_revision"],
        origin_revision=run["origin_revision"],
        validation={
            "status": "deferred",
            "reason": "No actual page change was needed.",
            "errorCode": "no_actionable_change",
        },
    )
    owner_id = memory.create_strategy_initiative(
        cycle["id"],
        kind="owner_information",
        title=owner_opportunity["title"],
        summary=owner_opportunity["scope"],
        expected={"opportunity": owner_opportunity},
        state="preparing",
        growth_run_id=run_id,
        goal_revision=run["goal_revision"],
        origin_revision=run["origin_revision"],
    )
    detail["blocks"] = [{"initiativeId": deferred_id, "reason": "Ada proposed no actual change"}]
    memory.update_growth_run(run_id, detail=detail)
    assert has_recoverable_growth_replay(memory)

    planner = Ada()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": Payload(), "llm": planner}
    monkeypatch.setattr(
        "site_agent.application.growth_workflow._reconcile_article_research",
        lambda _context: pytest.fail("saved-work replay must not dispatch or poll research"),
    )

    run_pending_growth(context)

    replayed = memory.get_growth_run(run_id)
    initiatives = {row["id"]: row for row in memory.list_strategy_initiatives(limit=None)}
    owner = initiatives[owner_id]
    assert replayed["status"] == "complete"
    assert replayed["detail"]["recoveryEvents"][-1]["code"] == "initiative_state_transition_conflict_replayed"
    assert "error" not in replayed["detail"]
    assert initiatives[deferred_id]["state"] == "deferred"
    assert owner["state"] == "waiting_for_owner"
    assert owner["owner_action_id"] is not None
    assert memory.get_owner_action(owner["owner_action_id"]) is not None
    assert planner.stages == []
    assert context["payload_gateway"].writes == context["payload_gateway"].publishes == 0
    memory.close()


def test_long_owner_question_scope_becomes_bounded_action_summary_without_losing_initiative_detail(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    settings = config()
    run_id = _failed_saved_assessment(memory, settings, error="summary exceeds 500 characters")
    run = memory.get_growth_run(run_id)
    detail = run["detail"]
    opportunity = {
        "kind": "owner_information",
        "title": "Confirm your booking details",
        "why": "The website does not define appointment duration.",
        "hypothesis": "Accurate availability will make the booking experience reliable.",
        "evidence": ["inventory"],
        "requiredSources": ["inventory"],
        "scope": "Confirm the appointment duration, availability, staff capacity, cancellation rules, customer preparation notes, location details, and any service-specific requirements that Ada must include before preparing a booking experience. " + "Owner detail. " * 50,
    }
    detail["assessment"]["opportunities"] = [opportunity]
    memory.update_growth_run(run_id, detail=detail)
    cycle = memory.growth_strategy_cycle(run_id, detail["evidenceArtifactId"])
    initiative_id = memory.create_strategy_initiative(
        cycle["id"], kind=opportunity["kind"], title=opportunity["title"], summary=opportunity["scope"],
        expected={"opportunity": opportunity}, state="preparing", growth_run_id=run_id,
        goal_revision=run["goal_revision"], origin_revision=run["origin_revision"],
    )
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": Payload(), "llm": Ada()}

    run_pending_growth(context)

    initiative = memory.update_strategy_initiative(initiative_id)
    action = memory.get_owner_action(initiative["owner_action_id"])
    assert initiative["summary"] == opportunity["scope"]
    assert initiative["state"] == "waiting_for_owner"
    assert action.summary
    assert len(action.summary) <= 500
    assert action.summary.endswith("…")
    memory.close()


def test_pending_growth_resumes_exact_historical_failure_from_saved_assessment(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    settings = config()
    payload = Payload()
    planner = Ada()
    run_id = _failed_saved_assessment(memory, settings)
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": payload, "llm": planner}
    reconciled = []
    monkeypatch.setattr("site_agent.application.growth_workflow._reconcile_article_research", lambda _context: reconciled.append(True))

    run_pending_growth(context)

    run = memory.get_growth_run(run_id)
    assert run["status"] == "complete"
    assert run["detail"]["recoveryEvents"][-1]["code"] == "evidence_binding_fixed"
    assert "error" not in run["detail"]
    initiatives = memory.list_strategy_initiatives(limit=None)
    assert len(initiatives) == 1
    assert initiatives[0]["state"] == "ready_for_review"
    assert payload.writes == 1
    assert payload.publishes == 0
    assert planner.stages == ["prepare"]
    assert reconciled == []
    memory.close()


def _blocked_payload_contract_run(memory, settings):
    run_id = _failed_saved_assessment(memory, settings)
    run = memory.get_growth_run(run_id)
    cycle = memory.growth_strategy_cycle(run_id, run["detail"]["evidenceArtifactId"])
    opportunity = run["detail"]["assessment"]["opportunities"][0]
    initiative_id = memory.create_strategy_initiative(
        cycle["id"], kind=opportunity["kind"], title=opportunity["title"], summary=opportunity["scope"],
        expected={"opportunity": opportunity}, state="blocked", growth_run_id=run_id,
        goal_revision=run["goal_revision"], origin_revision=run["origin_revision"],
    )
    detail = dict(run["detail"])
    detail.pop("error", None)
    detail["candidateIds"] = []
    detail["blocks"] = [{"initiativeId": initiative_id, "reason": "Payload gateway returned 404: Route not found \"/api/workspace/growth/contract\""}]
    memory.update_growth_run(
        run_id, status="blocked", phase="preparing", detail=detail,
        next_due_ts="2099-10-16T04:08:16+00:00",
    )
    return run_id, initiative_id, cycle["id"]


def _blocked_payload_schema_run(memory, settings):
    from site_agent.application.growth_workflow import _GROWTH_SCHEMA_MISMATCH

    run_id = _failed_saved_assessment(memory, settings)
    run = memory.get_growth_run(run_id)
    cycle = memory.growth_strategy_cycle(run_id, run["detail"]["evidenceArtifactId"])
    opportunity = run["detail"]["assessment"]["opportunities"][0]
    initiative_id = memory.create_strategy_initiative(
        cycle["id"], kind=opportunity["kind"], title=opportunity["title"], summary=opportunity["scope"],
        expected={"opportunity": opportunity}, state="blocked", growth_run_id=run_id,
        goal_revision=run["goal_revision"], origin_revision=run["origin_revision"],
        last_error=_GROWTH_SCHEMA_MISMATCH,
    )
    detail = dict(run["detail"])
    detail.pop("error", None)
    detail["candidateIds"] = []
    detail["blocks"] = [{"initiativeId": initiative_id, "reason": _GROWTH_SCHEMA_MISMATCH}]
    memory.update_growth_run(
        run_id, status="blocked", phase="preparing", detail=detail,
        next_due_ts="2099-10-16T04:08:16+00:00",
    )
    return run_id, initiative_id


def test_pending_growth_resumes_only_the_saved_payload_candidate_after_contract_route_returns(tmp_path, monkeypatch):
    from site_agent.application.actions import OwnerActionService
    from site_agent.core.contracts import ActionPriority, ActionRequirement, OwnerAction

    memory = Memory(tmp_path / "memory.db")
    settings = config()
    run_id, initiative_id, cycle_id = _blocked_payload_contract_run(memory, settings)
    owner_id = memory.create_strategy_initiative(
        cycle_id, kind="owner_information", title="Confirm booking details", summary="Tell Ada the duration.",
        expected={"opportunity": {"kind": "owner_information", "title": "Confirm booking details"}},
        state="waiting_for_owner", growth_run_id=run_id,
        goal_revision=memory.get_growth_run(run_id)["goal_revision"],
        origin_revision=memory.get_growth_run(run_id)["origin_revision"],
    )
    action = OwnerActionService(memory).create(OwnerAction(
        capability_id="growth.owner_information", provider_id="site-agent",
        title="Confirm booking details", summary="Tell Ada the duration.", action_label="Answer Ada",
        priority=ActionPriority.NORMAL, requirement=ActionRequirement.OWNER_INFORMATION,
        source_ref=f"growth-initiative:{owner_id}", dedupe_key=f"growth-initiative:{owner_id}",
    ))
    memory.update_strategy_initiative(owner_id, owner_action_id=action.id)
    assert has_recoverable_growth_replay(memory)

    payload = Payload()
    planner = Ada()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": payload, "llm": planner}
    reconciled = []
    monkeypatch.setattr("site_agent.application.growth_workflow._reconcile_article_research", lambda _context: reconciled.append(True))

    run_pending_growth(context)

    resumed = memory.get_growth_run(run_id)
    initiatives = memory.list_strategy_initiatives(limit=None)
    candidate = next(row for row in initiatives if int(row["id"]) == initiative_id)
    owner_question = next(row for row in initiatives if int(row["id"]) == owner_id)
    assert resumed["status"] == "complete"
    recovery = resumed["detail"]["recoveryEvents"][-1]
    assert recovery["code"] == "payload_growth_contract_route_restored"
    assert recovery["resumedAt"]
    assert recovery["previousError"] == 'Payload gateway returned 404: Route not found "/api/workspace/growth/contract"'
    assert candidate["state"] == "ready_for_review"
    assert candidate["review_package_hash"]
    assert owner_question["state"] == "waiting_for_owner"
    assert owner_question["owner_action_id"] == action.id
    assert memory.get_owner_action(action.id) is not None
    assert payload.growth_contract_checks == 2  # one recovery gate, then canonical candidate preparation
    assert payload.writes == 1
    assert payload.publishes == 0
    assert planner.stages == ["prepare"]
    assert reconciled == []
    memory.close()


def test_pending_growth_leaves_contract_blocked_candidate_untouched_when_route_is_still_unavailable(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    settings = config()
    run_id, initiative_id, _ = _blocked_payload_contract_run(memory, settings)

    class UnavailablePayload(Payload):
        def require_growth_contract(self):
            self.growth_contract_checks += 1
            raise RuntimeError("Payload gateway returned 404: Route not found \"/api/workspace/growth/contract\"")

    payload = UnavailablePayload()
    planner = Ada()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": payload, "llm": planner}
    reconciled = []
    monkeypatch.setattr("site_agent.application.growth_workflow._reconcile_article_research", lambda _context: reconciled.append(True))
    before = memory.get_growth_run(run_id)

    try:
        run_pending_growth(context)
    except RuntimeError as exc:
        assert str(exc) == "Payload gateway returned 404: Route not found \"/api/workspace/growth/contract\""
    else:
        raise AssertionError("a blocked Payload contract route must remain a scheduler-visible failure")

    after = memory.get_growth_run(run_id)
    initiative = next(row for row in memory.list_strategy_initiatives(limit=None) if int(row["id"]) == initiative_id)
    assert after["status"] == "blocked"
    assert after["next_due_ts"] == before["next_due_ts"]
    assert initiative["state"] == "blocked"
    assert payload.growth_contract_checks == 1
    assert payload.writes == 0
    assert payload.publishes == 0
    assert planner.stages == []
    assert reconciled == []
    memory.close()


def test_pending_growth_replays_only_saved_schema_failure_once_and_defers_unsupported_scope(tmp_path, monkeypatch):
    from site_agent.application.growth_workflow import _recoverable_growth_schema_failure

    class DeferredAda(Ada):
        def chat(self, messages, **kwargs):
            material = json.loads(messages[-1]["content"])
            if material.get("stage") != "prepare":
                return super().chat(messages, **kwargs)
            self.stages.append("prepare")
            return json.dumps({"status": "deferred", "reason": "A new page route is outside the existing-document editor.", "reassessWhen": "When the shared new-page route becomes available."})

    memory = Memory(tmp_path / "memory.db")
    settings = config()
    run_id, initiative_id = _blocked_payload_schema_run(memory, settings)
    before = memory.get_growth_run(run_id)
    assert _recoverable_growth_schema_failure(memory, before)
    assert has_recoverable_growth_replay(memory)

    payload, planner = Payload(), DeferredAda()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": payload, "llm": planner}
    reconciled = []
    monkeypatch.setattr("site_agent.application.growth_workflow._reconcile_article_research", lambda _context: reconciled.append(True))
    run_pending_growth(context)

    resumed = memory.get_growth_run(run_id)
    initiative = next(row for row in memory.list_strategy_initiatives(limit=None) if int(row["id"]) == initiative_id)
    assert resumed["status"] == "complete"
    assert resumed["detail"]["recoveryEvents"][-1]["code"] == "growth_schema_candidate_retry"
    assert resumed["detail"]["assessment"]["unpreparedOpportunities"][0]["errorCode"] == "unsupported_existing_document_route"
    assert initiative["state"] == "deferred"
    assert payload.writes == payload.publishes == 0
    assert planner.stages == ["prepare"]
    assert reconciled == []
    assert not _recoverable_growth_schema_failure(memory, resumed)
    memory.close()


def test_payload_contract_recovery_rejects_candidates_with_side_effects(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    run_id, initiative_id, _ = _blocked_payload_contract_run(memory, config())
    detail = memory.get_growth_run(run_id)["detail"]
    detail["candidateIds"] = ["already-created"]
    memory.update_growth_run(run_id, detail=detail)
    assert not has_recoverable_growth_replay(memory)
    memory.close()


def test_activation_wakes_only_exact_recoverable_growth_and_article_jobs(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    settings = config()
    _failed_saved_assessment(memory, settings)
    cycle = memory.create_strategy_cycle("historical-noop", "2026-10", "noop-hash", {})
    memory.create_strategy_initiative(
        cycle["id"], kind="payload_content", title="Unneeded change", summary="Already correct",
        state="blocked", last_error="Ada proposed no actual change",
    )
    source_id_block = "Payload posts contract is missing required fields: sourceId"
    memory.save_draft(
        "Recoverable article",
        "Article body",
        meta={"payload_sync": {"state": "blocked", "validation": {"status": "blocked", "reason": source_id_block}}},
    )
    memory.save_draft(
        "Locale-blocked article",
        "Article body",
        meta={"payload_sync": {"state": "blocked", "locale": "fr", "validation": {"status": "blocked", "reason": "The requested locale 'fr' is not enabled for this website."}}},
    )
    memory.save_draft(
        "Unrelated blocked article",
        "Article body",
        meta={"payload_sync": {"state": "blocked", "validation": {"status": "blocked", "reason": "Payload posts contract is missing required fields: content"}}},
    )
    memory.save_draft(
        "Declined article",
        "Article body",
        meta={"payload_sync": {"state": "blocked", "validation": {"status": "blocked", "reason": source_id_block}}},
    )
    memory.update_draft_status(3, "declined")
    memory.kv_set("next_run:growth_pending", 9999999.0)
    memory.kv_set("next_run:growth_article_sync", 9999999.0)

    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="America/Cancun", clock=lambda: 1234.5)
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": Payload(), "llm": Ada()}
    register_jobs(scheduler, settings, context)

    assert memory.kv_get("next_run:growth_pending") == 1234.5
    assert memory.kv_get("next_run:growth_article_sync") == 1234.5
    assert _has_recoverable_article_sync(memory)
    assert has_recoverable_historical_noop(memory)
    assert scheduler.due("growth_pending")
    assert scheduler.due("growth_article_sync")
    memory.close()


def test_activation_does_not_wake_unrelated_or_completed_growth_work(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    memory.save_draft(
        "Unrelated blocked article",
        "Article body",
        meta={"payload_sync": {"state": "blocked", "validation": {"status": "blocked", "reason": "Payload posts contract is missing required fields: content"}}},
    )
    locale_idea = memory.create_article_idea(
        "provider-locale-failure", "b" * 64,
        {"working_title": "A guide", "candidate_queries": ["guide"], "language": "en", "market": "US"},
    )
    memory.update_article_idea(
        locale_idea["id"], status="failed",
        error="DATAFORSEO_TASK_40501_INVALID_FIELD_LANGUAGE_CODE_",
    )
    memory.kv_set("next_run:growth_pending", 9999999.0)
    memory.kv_set("next_run:growth_article_sync", 9999999.0)

    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="America/Cancun", clock=lambda: 1234.5)
    settings = config()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": Payload(), "llm": Ada()}
    register_jobs(scheduler, settings, context)

    assert memory.kv_get("next_run:growth_pending") == 9999999.0
    assert memory.kv_get("next_run:growth_article_sync") == 9999999.0
    assert not _has_recoverable_article_sync(memory)
    assert not has_recoverable_historical_noop(memory)
    memory.close()


def test_long_payload_evidence_is_projected_only_in_bounded_review_summaries_and_resumes_once(tmp_path, monkeypatch):
    why = "Evidence for this recommendation remains complete. " * 18
    scope = "Detailed change scope remains available to the owner. " * 18

    class LongEvidenceAda(Ada):
        def chat(self, messages, **kwargs):
            material = json.loads(messages[-1]["content"])
            if material.get("stage") == "prepare":
                return super().chat(messages, **kwargs)
            self.stages.append("assess")
            return json.dumps({"summary": "A long-evidence opportunity.", "opportunities": [{
                "kind": "payload_content", "title": "Make the homepage clearer in search",
                "why": why, "hypothesis": "A clear description helps search visitors.", "primaryArea": "search_visibility",
                "collection": "pages", "documentId": "1", "evidence": ["inventory", "ga4"],
                "requiredSources": ["inventory"], "scope": scope, "metric": "gsc.clicks",
            }]})

    memory = Memory(tmp_path / "memory.db")
    payload, planner = Payload(), LongEvidenceAda()
    context = {"tenant_id": "test-business", "config": config(), "memory": memory, "payload_gateway": payload, "llm": planner}
    update_strategy_cycle = memory.update_strategy_cycle
    fail_once = True

    def interrupt_after_candidate(*args, **kwargs):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RuntimeError("simulated interruption after candidate preparation")
        return update_strategy_cycle(*args, **kwargs)

    monkeypatch.setattr(memory, "update_strategy_cycle", interrupt_after_candidate)
    interrupted = run_growth_cycle(context, trigger="weekly")
    assert interrupted["status"] == "failed"
    initiatives = memory.list_strategy_initiatives()
    assert len(initiatives) == 1, interrupted.get("detail", {}).get("error")
    initiative, = initiatives
    assert initiative["state"] == "ready_for_review"
    action, = [a for a in memory.list_owner_actions(limit=None) if a.source_ref == f"growth-initiative:{initiative['id']}"]
    artifact, = [a for a in memory.list_artifacts(limit=500) if a.source_action_id == action.id]
    draft, = [d for d in memory.list_drafts(limit=None) if d["kind"] == "payload_content"]
    package = draft["meta"]["growth_package"]

    assert len(action.summary) <= 500
    assert len(artifact.summary) <= 500
    assert initiative["rationale"] == why
    assert initiative["summary"] == scope
    assert initiative["expected"]["opportunity"]["why"] == why
    assert initiative["expected"]["opportunity"]["scope"] == scope
    assert draft["body"] == scope
    assert package["why"] == why and package["scope"] == scope
    assert artifact.preview_data["why"] == why
    assert payload.draft["metaDescription"]

    memory.update_growth_run(interrupted["run_id"], status="running", next_due_ts=None)
    resumed = run_growth_cycle(context, trigger="weekly", run_id=interrupted["run_id"], resume_interrupted=True)
    assert resumed["status"] == "complete"
    assert resumed["detail"]["recoveryEvents"][-1]["code"] == "growth_worker_restart_recovery"
    assert payload.writes == 1
    assert payload.apply_calls == 1
    assert payload.publishes == 0
    assert len(memory.list_owner_actions(limit=None)) == 1
    assert len([a for a in memory.list_artifacts(limit=500) if a.source_action_id == action.id]) == 1
    assert len([d for d in memory.list_drafts(limit=None) if d["kind"] == "payload_content"]) == 1
    memory.close()


def test_resumed_payload_preparation_reconciles_before_creating_review(tmp_path, monkeypatch):
    from site_agent.application.growth_candidates import content_hash, prepare_payload_candidate
    from site_agent.application import growth_candidates

    memory = Memory(tmp_path / "resumed-payload-preparation.db")
    payload = Payload()
    changes = {"metaDescription": "A clearer description for local service customers."}
    base = {key: payload.live[key] for key in payload.contract.collection_fields["pages"]}
    payload.draft.update(changes)
    cycle = memory.create_strategy_cycle("resume", "2026-10", "resume-hash", {})
    initiative_id = memory.create_strategy_initiative(
        cycle["id"], kind="payload_content", title="Improve search description", summary="Review the description.",
        state="preparing", validation={"preparation": {
            "changes": changes, "baseHash": content_hash(base), "collection": "pages", "documentId": "1",
        }},
    )
    initiative = memory.update_strategy_initiative(initiative_id)
    opportunity = {"collection": "pages", "documentId": "1", "title": "Improve description",
                   "why": "No description exists.", "scope": "Improve the search result."}
    inventory = [{"collection": "pages", "document": {"id": "1"}, "route": "/"}]
    evidence = {"policy": {"policy_version": "1"}, "evidenceHash": "evidence-hash"}
    monkeypatch.setattr(growth_candidates, "journal", lambda _context: SimpleNamespace(issue=lambda _row: None))

    result = prepare_payload_candidate(
        {"tenant_id": "test-business", "config": config(), "memory": memory, "payload_gateway": payload},
        initiative, opportunity, inventory, evidence,
    )
    assert result["state"] == "ready_for_review"
    assert payload.apply_calls == 1
    assert payload.writes == 0
    assert len([row for row in memory.list_drafts(limit=None) if row.get("kind") == "payload_content"]) == 1
    memory.close()

def test_activation_wakes_only_exact_unlinked_payload_draft_reconciliation(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    memory.save_draft(
        "Orphaned article",
        "Article body",
        meta={"payload_sync": {
            "state": "blocked",
            "validation": {
                "status": "blocked",
                "reason": "An existing Payload post is not linked to Ada's exact sync record; it must be reviewed before any update.",
            },
        }},
    )
    memory.save_draft(
        "Payload shell blocked by old sync guard",
        "Article body",
        meta={"payload_sync": {
            "state": "blocked",
            "validation": {
                "status": "blocked",
                "reason": "An existing Payload post is not linked to Ada's exact sync record; its content differs, so it remains blocked for owner review.",
            },
        }},
    )
    memory.kv_set("next_run:growth_article_sync", 9999999.0)

    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="America/Cancun", clock=lambda: 1234.5)
    settings = config()
    register_jobs(scheduler, settings, {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": Payload(), "llm": Ada()})

    assert _has_recoverable_article_sync(memory)
    assert memory.kv_get("next_run:growth_article_sync") == 1234.5
    memory.close()

def test_invalid_opportunity_evidence_does_not_abort_valid_preparation(tmp_path):
    class PartlyInvalidAda(Ada):
        def chat(self, messages, **kwargs):
            material = json.loads(messages[-1]["content"])
            if material.get("stage") != "assess":
                return super().chat(messages, **kwargs)
            good = json.loads(super().chat(messages, **kwargs))["opportunities"][0]
            bad = {**good, "title": "Unbound finding", "evidence": ["outside-this-run"]}
            return json.dumps({"summary": "One finding needs evidence repair; another can proceed.", "opportunities": [bad, good]})

    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    run = run_growth_cycle({"tenant_id": "test-business", "config": config(), "memory": memory, "payload_gateway": payload, "llm": PartlyInvalidAda()}, trigger="weekly")

    assert run["status"] == "complete"
    assert len(run["detail"]["candidateIds"]) == 1
    assert run["detail"]["assessment"]["unpreparedOpportunities"][0]["errorCode"] == "evidence_not_bound_to_run"
    assert len(memory.list_strategy_initiatives(limit=None)) == 1
    assert payload.writes == 1
    assert payload.publishes == 0
    memory.close()


def test_missing_required_evidence_blocks_only_that_candidate_not_fabricated_completion(tmp_path):
    class UnavailableAda(Ada):
        def chat(self, messages, **kwargs):
            response = json.loads(super().chat(messages, **kwargs))
            response["opportunities"][0]["requiredSources"] = ["gsc"]
            return json.dumps(response)

    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    run = run_growth_cycle({"tenant_id": "test-business", "config": config(), "memory": memory, "payload_gateway": payload, "llm": UnavailableAda()}, trigger="weekly")
    assert run["status"] == "blocked"
    assert payload.writes == 0
    assert memory.list_strategy_initiatives()[0]["state"] == "blocked"
    memory.close()


def test_unprotected_gateway_is_rejected_before_any_content_write(tmp_path):
    class UnprotectedPayload(Payload):
        def require_growth_contract(self):
            raise RuntimeError("The managed publication contract is not installed")
    memory = Memory(tmp_path / "memory.db")
    payload = UnprotectedPayload()
    run = run_growth_cycle({"tenant_id": "test-business", "config": config(), "memory": memory, "payload_gateway": payload, "llm": Ada()}, trigger="weekly")
    assert run["status"] == "blocked"
    assert run["next_due_ts"]
    assert payload.writes == payload.publishes == 0
    assert memory.list_drafts() == []
    memory.close()


def test_renderer_failure_is_not_a_validated_candidate_or_owner_decision(tmp_path):
    class BrokenRenderer(Payload):
        def validate_growth_candidate(self, package, package_hash):
            raise RuntimeError("The public renderer could not display the exact candidate")
    memory = Memory(tmp_path / "memory.db")
    payload = BrokenRenderer()
    run = run_growth_cycle({"tenant_id": "test-business", "config": config(), "memory": memory, "payload_gateway": payload, "llm": Ada()}, trigger="weekly")
    assert run["status"] == "blocked"
    assert memory.list_strategy_initiatives()[0]["state"] == "blocked"
    assert not memory.list_owner_actions()
    assert not memory.list_drafts()
    assert payload.publishes == 0
    memory.close()


def test_monthly_growth_run_reuses_one_durable_research_request_and_polls_it(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    settings = config()
    settings["seo"] = {
        "site_url": "https://business.test",
        "research": {
            "enabled": True,
            "timezone": "UTC",
            "languages": [{"code": "en", "markets": ["US"], "primary": True}],
            "existing_locales": ["en"],
            "business_goals": ["relevant visitors"],
            "priority_services": ["local service"],
            "anchor_topics": ["service topic"],
        },
    }
    request = memory.create_seo_research_request(
        "2026-09", "standard-v1", "seo:2026-09:standard-v1", {"focus_market": {"language": "en", "country": "US"}}
    )
    monkeypatch.setattr("site_agent.brain.seo.previous_period", lambda _config: "2026-09")
    monkeypatch.setattr("site_agent.brain.seo.run", lambda _context: None)
    run = run_growth_cycle(
        {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": payload, "crawlseo_service": object()},
        trigger="monthly",
    )
    assert run["status"] == "pending"
    assert run["detail"]["monthlyResearch"]["requestId"] == request["id"]
    assert run["detail"]["monthlyResearch"]["status"] in {"preparing", "pending"}
    assert "not connected" not in str(run["detail"].get("error") or "").lower()
    memory.close()


def test_payload_growth_jobs_default_on_independently_of_legacy_scheduler_flag(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="America/Cancun", clock=lambda: 1234.5)
    settings = config()
    settings["scheduler"]["enabled"] = False
    settings["growth"].pop("enabled", None)
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": Payload(), "llm": Ada()}

    register_jobs(scheduler, settings, context)

    names = {name for name, _, _ in scheduler.jobs}
    assert {"growth_initial", "growth_daily", "growth_weekly", "growth_monthly", "growth_pending", "growth_article_sync"} <= names
    assert "seo_outcomes" in names
    assert memory.kv_get("next_run:growth_pending") == 1234.5
    assert memory.kv_get("next_run:growth_article_sync") == 1234.5
    memory.close()


def test_pending_payload_growth_reconciles_saved_article_drafts(monkeypatch, tmp_path):
    memory = Memory(tmp_path / "memory.db")
    calls = []
    monkeypatch.setattr("site_agent.core.jobs._mirror_article_drafts", lambda context: calls.append(context["tenant_id"]))
    monkeypatch.setattr("site_agent.application.growth_workflow._reconcile_article_research", lambda _context: None)
    context = {"tenant_id": "test-business", "config": config(), "memory": memory, "payload_gateway": object(), "tenant_id": "growth-demo"}

    run_pending_growth(context)
    assert calls == []

    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="America/Cancun", clock=lambda: 1234.5)
    register_jobs(scheduler, config(), context)
    sync = next(operation for name, _spec, operation in scheduler.jobs if name == "growth_article_sync")
    sync()
    assert calls == ["growth-demo"]
    memory.close()


def _growth_json_truncation_run(memory, settings):
    from site_agent.application.growth_workflow import _EMPTY_GROWTH_JSON_COMPLETION

    run_id, initiative_id, _ = _blocked_payload_contract_run(memory, settings)
    run = memory.get_growth_run(run_id)
    detail = dict(run["detail"])
    detail["recoveryEvents"] = [{
        "code": "payload_growth_contract_route_restored",
        "resumedAt": "2026-10-16T04:19:14+00:00",
        "previousError": 'Payload gateway returned 404: Route not found "/api/workspace/growth/contract"',
    }]
    detail["blocks"] = [{"initiativeId": initiative_id, "reason": _EMPTY_GROWTH_JSON_COMPLETION}]
    memory.update_growth_run(
        run_id, status="blocked", phase="preparing", detail=detail,
        next_due_ts="2099-10-16T04:08:16+00:00",
    )
    return run_id, initiative_id


def test_pending_growth_retries_exact_truncated_proposal_once_without_hidden_reasoning(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    settings = config()
    run_id, initiative_id = _growth_json_truncation_run(memory, settings)
    assert has_recoverable_growth_replay(memory)

    payload = Payload()
    planner = Ada()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": payload, "llm": planner}
    monkeypatch.setattr("site_agent.application.growth_workflow._reconcile_article_research", lambda _context: None)

    run_pending_growth(context)

    resumed = memory.get_growth_run(run_id)
    candidate = next(row for row in memory.list_strategy_initiatives(limit=None) if int(row["id"]) == initiative_id)
    assert resumed["status"] == "complete"
    assert resumed["detail"]["recoveryEvents"][-1]["code"] == "growth_json_no_reasoning_retry"
    assert resumed["detail"]["recoveryEvents"][-1]["previousError"].startswith("model returned an empty completion")
    assert candidate["state"] == "ready_for_review"
    assert candidate["review_package_hash"]
    assert payload.writes == 1
    assert payload.publishes == 0
    assert planner.stages == ["prepare"]
    assert not has_recoverable_growth_replay(memory)
    memory.close()


def test_failed_non_reasoning_growth_replay_is_not_repeated(tmp_path, monkeypatch):
    from site_agent.application.growth_workflow import _EMPTY_GROWTH_JSON_COMPLETION

    class TruncatedAda:
        def __init__(self):
            self.calls = 0

        def chat(self, *_args, **_kwargs):
            self.calls += 1
            raise RuntimeError(_EMPTY_GROWTH_JSON_COMPLETION)

    memory = Memory(tmp_path / "memory.db")
    settings = config()
    run_id, _ = _growth_json_truncation_run(memory, settings)
    planner = TruncatedAda()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": Payload(), "llm": planner}
    monkeypatch.setattr("site_agent.application.growth_workflow._reconcile_article_research", lambda _context: None)

    run_pending_growth(context)
    failed = memory.get_growth_run(run_id)
    assert failed["status"] == "blocked"
    assert failed["detail"]["recoveryEvents"][-1]["code"] == "growth_json_no_reasoning_retry"
    assert not has_recoverable_growth_replay(memory)

    run_pending_growth(context)
    assert planner.calls == 1
    memory.close()


def _interrupted_payload_revision(memory, context, payload, *, write_attempted=False, save_receipt=False, persist_job_id=True):
    run = run_growth_cycle(context, trigger="weekly")
    assert run["status"] == "complete"
    initiative, = memory.list_strategy_initiatives(limit=None)
    initiative_id = int(initiative["id"])
    previous_draft = memory.get_draft(int(initiative["draft_id"]))
    previous_package = previous_draft["meta"]["growth_package"]
    previous_hash = previous_draft["meta"]["review_package_hash"]
    previous_approval_id = int(initiative["approval_id"])
    previous_id = int(previous_draft["id"])
    previous_validation = dict(initiative.get("validation") or {})
    memory.update_draft_meta(previous_id, {
        **previous_draft["meta"], "growth_revision_pending": True,
        "growth_revision_initiative_id": initiative_id,
    })
    revision_request = {
        "initiativeId": initiative_id,
        "previousDraftId": previous_id,
        "previousApprovalId": previous_approval_id,
        "previousReviewPackageHash": previous_hash,
        "candidateType": "payload_content",
        "collection": str(previous_package["collection"]),
        "documentId": str(previous_package["documentId"]),
        "baseHash": str(previous_package["baseHash"]),
        "previousCandidateHash": str(previous_package["candidateHash"]),
        "fields": list(previous_package["fields"]),
    }
    conversation_id = memory.create_conversation("Growth revision")
    job_id = memory.enqueue_chat_job(
        conversation_id,
        "Revise this proposal",
        payload={"growth_task_revision": revision_request},
    )
    revision = {**revision_request, "previousValidation": previous_validation}
    if write_attempted:
        revision.update({
            "writeAttempted": True,
            "writeTarget": {
                "collection": revision_request["collection"],
                "documentId": revision_request["documentId"],
                "fields": ["metaDescription"],
            },
            "locale": "en",
        })
    saved_revision = {**revision}
    if persist_job_id:
        saved_revision["chatJobId"] = job_id
    validation = {**previous_validation, "status": "validating", "revision": saved_revision}
    memory.transition_strategy_initiative(
        initiative_id, "validating", expected_state="ready_for_review", validation=validation,
    )
    job = memory.claim_chat_job("revision-worker") if persist_job_id else None
    if persist_job_id:
        assert job and int(job["id"]) == job_id
    writes_before_revision = payload.writes
    if save_receipt:
        assert job is not None
        updated = payload.update(revision_request["collection"], revision_request["documentId"], {
            "metaDescription": "A revised description prepared from the exact owner request.",
        })
        receipt = {
            "kind": "collection", "operation": "update", "target": revision_request["collection"],
            "document_id": revision_request["documentId"], "revision": updated["_helloadaRevision"],
            "locale": "en", "fields": ["metaDescription"],
            "summary": "Updated the reviewed description.",
        }
        assert memory.record_chat_job_effect(job_id, "revision-worker", receipt)
    memory.interrupt_running_chat_jobs()
    return {
        "initiative_id": initiative_id,
        "previous_draft_id": previous_id,
        "previous_hash": previous_hash,
        "previous_package": previous_package,
        "previous_base": dict(previous_package["before"]),
        "previous_approval_id": previous_approval_id,
        "job_id": job_id,
        "writes_before_revision": writes_before_revision,
    }


def _reconcile_interrupted_payload_revision(context, monkeypatch):
    from site_agent.application import growth_delivery

    # The recovery test exercises only the tenant's existing durable Growth
    # reconciliation boundary; no engineering journal transport is needed.
    monkeypatch.setattr(growth_delivery, "reconcile_delivery", lambda _context: None)
    run_pending_growth(context)


def test_normal_growth_reconciliation_restores_interrupted_prewrite_payload_revision(tmp_path, monkeypatch):
    from site_agent.application.growth_candidates import content_hash

    memory = Memory(tmp_path / "interrupted-payload-revision.db")
    settings = config()
    payload = Payload()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": payload, "llm": Ada()}
    try:
        saved = _interrupted_payload_revision(memory, context, payload, write_attempted=False)
        # A missing writeAttempted checkpoint is the exact pre-dispatch case:
        # the target Payload draft still equals the approved candidate.
        assert content_hash({field: payload.live.get(field) for field in sorted(saved["previous_package"]["fields"])}) == saved["previous_package"]["baseHash"]
        assert has_recoverable_growth_replay(memory)
        assert memory.get_chat_job(saved["job_id"])["error"] == "interrupted by server restart; retry this job"
        scheduler = Scheduler(
            memory,
            lock_path=tmp_path / "scheduler.lock",
            clock=lambda: 1_800_000_000,
            timezone_name="America/Cancun",
        )
        memory.kv_set("next_run:growth_pending", scheduler.clock() + 3600)
        register_growth_jobs(scheduler, settings, context)
        assert memory.kv_get("next_run:growth_pending") <= scheduler.clock()

        _reconcile_interrupted_payload_revision(context, monkeypatch)

        initiative = memory.update_strategy_initiative(saved["initiative_id"])
        previous = memory.get_draft(saved["previous_draft_id"])
        assert initiative["state"] == "ready_for_review"
        assert initiative["draft_id"] == saved["previous_draft_id"]
        assert initiative["validation"]["revisionFailure"]
        assert initiative["review_package_hash"] == saved["previous_hash"]
        assert previous["status"] == "pending"
        assert "growth_revision_pending" not in previous["meta"]
        assert previous["meta"]["growth_package"] == saved["previous_package"]
        assert previous["meta"]["review_package_hash"] == saved["previous_hash"]
        assert content_hash({field: payload.live.get(field) for field in sorted(saved["previous_package"]["fields"])}) == saved["previous_package"]["baseHash"]
        assert payload.writes == saved["writes_before_revision"]
        assert memory.get_chat_job(saved["job_id"])["status"] == "error"
        assert not has_recoverable_growth_replay(memory)
    finally:
        memory.close()


def test_normal_growth_reconciliation_skips_revision_during_enqueue_id_checkpoint_window(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "payload-revision-enqueue-window.db")
    settings = config()
    payload = Payload()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": payload, "llm": Ada()}
    try:
        saved = _interrupted_payload_revision(memory, context, payload, persist_job_id=False)
        revision = memory.update_strategy_initiative(saved["initiative_id"])["validation"]["revision"]
        assert "chatJobId" not in revision
        assert memory.get_chat_job(saved["job_id"])["status"] == "queued"
        assert not has_recoverable_growth_replay(memory)
        scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="America/Cancun")
        future = scheduler.clock() + 3600
        memory.kv_set("next_run:growth_pending", future)
        register_growth_jobs(scheduler, settings, context)
        assert memory.kv_get("next_run:growth_pending") == future

        _reconcile_interrupted_payload_revision(context, monkeypatch)

        initiative = memory.update_strategy_initiative(saved["initiative_id"])
        previous = memory.get_draft(saved["previous_draft_id"])
        assert initiative["state"] == "validating"
        assert "revisionFailure" not in initiative["validation"]
        assert previous["status"] == "pending"
        assert previous["meta"]["growth_revision_pending"] is True
        assert memory.get_chat_job(saved["job_id"])["status"] == "queued"
    finally:
        memory.close()


def test_normal_growth_reconciliation_keeps_interrupted_attempt_without_receipt_uncertain(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "interrupted-payload-attempt.db")
    settings = config()
    payload = Payload()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": payload, "llm": Ada()}
    try:
        saved = _interrupted_payload_revision(memory, context, payload, write_attempted=True)
        assert has_recoverable_growth_replay(memory)

        _reconcile_interrupted_payload_revision(context, monkeypatch)

        initiative = memory.update_strategy_initiative(saved["initiative_id"])
        revision = initiative["validation"]["revision"]
        previous = memory.get_draft(saved["previous_draft_id"])
        assert initiative["state"] == "validating"
        assert revision["status"] == "uncertain"
        assert revision["writeAttempted"] is True
        assert previous["status"] == "pending"
        assert previous["meta"]["growth_revision_pending"] is True
        assert payload.writes == saved["writes_before_revision"]
        assert not has_recoverable_growth_replay(memory)
    finally:
        memory.close()


def test_normal_growth_reconciliation_finalizes_exact_saved_payload_receipt_without_replay(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "interrupted-payload-receipt.db")
    settings = config()
    payload = Payload()
    context = {"tenant_id": "test-business", "config": settings, "memory": memory, "payload_gateway": payload, "llm": Ada()}
    try:
        saved = _interrupted_payload_revision(memory, context, payload, write_attempted=True, save_receipt=True)
        writes_after_receipt = payload.writes
        assert has_recoverable_growth_replay(memory)

        _reconcile_interrupted_payload_revision(context, monkeypatch)

        initiative = memory.update_strategy_initiative(saved["initiative_id"])
        previous = memory.get_draft(saved["previous_draft_id"])
        replacement = memory.get_draft(int(initiative["draft_id"]))
        assert initiative["state"] == "ready_for_review"
        assert initiative["validation"]["lastRevision"]["chatJobId"] == saved["job_id"]
        assert replacement["status"] == "pending"
        assert replacement["meta"]["growth_package"]["revisionOf"] == saved["previous_hash"]
        assert previous["status"] == "superseded"
        assert memory.get_approval_request(saved["previous_approval_id"]).status.value == "declined"
        assert memory.get_chat_job(saved["job_id"])["status"] == "error"
        assert payload.writes == writes_after_receipt
        assert not has_recoverable_growth_replay(memory)
    finally:
        memory.close()
