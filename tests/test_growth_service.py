import json
from types import SimpleNamespace

from site_agent.application.growth_workflow import _persist_evidence_artifact, ensure_default_goal, run_growth_cycle, run_pending_growth
from site_agent.core.jobs import register_jobs
from site_agent.core.growth_contracts import GrowthPolicy
from site_agent.core.memory import Memory
from site_agent.core.scheduler import Scheduler


def config():
    return {
        "instance_name": "test-business",
        "scheduler": {"enabled": True},
        "growth": {"timezone": "America/Cancun", "approval_required": True},
        "site": {"website_present": True, "public_url": "https://business.test", "payload": {"enabled": True}},
    }


class Payload:
    def __init__(self):
        self.live = {"id": "1", "sourceId": "page:home", "slug": "home", "title": "Business", "summary": "Local service", "metaDescription": "", "updatedAt": "revision-1"}
        self.draft = dict(self.live)
        self.writes = 0
        self.publishes = 0
        self.contract = SimpleNamespace(collections=("pages",), collection_fields={"pages": frozenset(("title", "summary", "metaDescription"))}, globals=())

    def list(self, collection, *, draft=True, **kwargs):
        return [dict(self.draft if draft else self.live)]

    def require_growth_contract(self):
        return {"version": 1}

    def require_authoring_contract(self):
        return {
            "version": 1,
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
        return {"status": "passed", "packageHash": package_hash, "checks": {
            "canonicalSchema": True, "exactDraft": True, "private": True,
            "publicRenderer": True, "approvalBoundary": True}}

    def read(self, collection, *, draft=True, **kwargs):
        return dict(self.draft if draft else self.live)

    def update(self, collection, document_id, data, **kwargs):
        self.writes += 1
        self.draft.update(data, updatedAt=f"revision-{self.writes + 1}")
        return dict(self.draft)

    def apply_growth_candidate(self, package, package_hash):
        assert package_hash
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
            return json.dumps({"changes": {"metaDescription": "Local service from Business. Explore the services and contact the team."}})
        return json.dumps({"summary": "The homepage needs a useful search description.", "opportunities": [{"kind": "payload_content", "title": "Make the homepage clearer in search", "why": "The homepage has no description.", "hypothesis": "A clear description explains the service to search visitors.", "collection": "pages", "documentId": "1", "evidence": ["inventory", "ga4"], "requiredSources": ["inventory"], "scope": "Improve the homepage meta description without changing its visible design.", "metric": "gsc.clicks"}]})


def test_live_payload_registers_one_growth_service_not_independent_producers(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="America/Cancun")
    settings = config()
    context = {"config": settings, "memory": memory, "payload_gateway": Payload(), "llm": Ada()}
    register_jobs(scheduler, settings, context)
    names = [name for name, _, _ in scheduler.jobs]
    assert {"growth_initial", "growth_daily", "growth_weekly", "growth_monthly", "growth_pending", "growth_article_sync"} <= set(names)
    assert "seo_outcomes" in names
    assert not set(names) & {"article", "seo_insight", "seo_research_cycle", "seo_site_report_cycle", "article_research_cycle", "growth_reconciler"}
    assert all(item["next_run"] is not None for item in scheduler.upcoming())
    memory.close()


def test_weekly_service_prepares_real_draft_without_publication_or_duplicate_work(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    payload = Payload()
    context = {"config": config(), "memory": memory, "payload_gateway": payload, "llm": Ada()}
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


def _failed_saved_assessment(memory, settings):
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
        "error": "Ada referenced evidence that is not in this run",
    }
    memory.update_growth_run(
        run["run_id"], detail=detail, next_due_ts="2099-10-16T04:08:16+00:00",
    )
    return run["run_id"]


def test_pending_growth_resumes_exact_historical_failure_from_saved_assessment(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    settings = config()
    payload = Payload()
    planner = Ada()
    run_id = _failed_saved_assessment(memory, settings)
    context = {"config": settings, "memory": memory, "payload_gateway": payload, "llm": planner}
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


def test_activation_wakes_only_exact_recoverable_growth_and_article_jobs(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    settings = config()
    _failed_saved_assessment(memory, settings)
    source_id_block = "Payload posts contract is missing required fields: sourceId"
    memory.save_draft(
        "Recoverable article",
        "Article body",
        meta={"payload_sync": {"state": "blocked", "validation": {"status": "blocked", "reason": source_id_block}}},
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
    context = {"config": settings, "memory": memory, "payload_gateway": Payload(), "llm": Ada()}
    register_jobs(scheduler, settings, context)

    assert memory.kv_get("next_run:growth_pending") == 1234.5
    assert memory.kv_get("next_run:growth_article_sync") == 1234.5
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
    memory.kv_set("next_run:growth_pending", 9999999.0)
    memory.kv_set("next_run:growth_article_sync", 9999999.0)

    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="America/Cancun", clock=lambda: 1234.5)
    settings = config()
    context = {"config": settings, "memory": memory, "payload_gateway": Payload(), "llm": Ada()}
    register_jobs(scheduler, settings, context)

    assert memory.kv_get("next_run:growth_pending") == 9999999.0
    assert memory.kv_get("next_run:growth_article_sync") == 9999999.0
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
    run = run_growth_cycle({"config": config(), "memory": memory, "payload_gateway": payload, "llm": PartlyInvalidAda()}, trigger="weekly")

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
    run = run_growth_cycle({"config": config(), "memory": memory, "payload_gateway": payload, "llm": UnavailableAda()}, trigger="weekly")
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
    run = run_growth_cycle({"config": config(), "memory": memory, "payload_gateway": payload, "llm": Ada()}, trigger="weekly")
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
    run = run_growth_cycle({"config": config(), "memory": memory, "payload_gateway": payload, "llm": Ada()}, trigger="weekly")
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
        {"config": settings, "memory": memory, "payload_gateway": payload, "crawlseo_service": object()},
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
    context = {"config": settings, "memory": memory, "payload_gateway": Payload(), "llm": Ada()}

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
    context = {"config": config(), "memory": memory, "payload_gateway": object(), "tenant_id": "growth-demo"}

    run_pending_growth(context)
    assert calls == []

    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="America/Cancun", clock=lambda: 1234.5)
    register_jobs(scheduler, config(), context)
    sync = next(operation for name, _spec, operation in scheduler.jobs if name == "growth_article_sync")
    sync()
    assert calls == ["growth-demo"]
    memory.close()
