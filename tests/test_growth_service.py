import json
from types import SimpleNamespace

from site_agent.application.growth_workflow import run_growth_cycle
from site_agent.core.jobs import register_jobs
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

    def publish(self, *args, **kwargs):
        self.publishes += 1
        raise AssertionError("scheduled work must not publish")


class Ada:
    def chat(self, messages, **kwargs):
        material = json.loads(messages[-1]["content"])
        if material.get("stage") == "prepare":
            return json.dumps({"changes": {"metaDescription": "Local service from Business. Explore the services and contact the team."}})
        return json.dumps({"summary": "The homepage needs a useful search description.", "opportunities": [{"kind": "payload_content", "title": "Make the homepage clearer in search", "why": "The homepage has no description.", "hypothesis": "A clear description explains the service to search visitors.", "collection": "pages", "documentId": "1", "evidence": ["payload:pages:1"], "requiredSources": ["inventory"], "scope": "Improve the homepage meta description without changing its visible design.", "metric": "gsc.clicks"}]})


def test_live_payload_registers_one_growth_service_not_independent_producers(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    scheduler = Scheduler(memory, lock_path=tmp_path / "scheduler.lock", timezone_name="America/Cancun")
    settings = config()
    context = {"config": settings, "memory": memory, "payload_gateway": Payload(), "llm": Ada()}
    register_jobs(scheduler, settings, context)
    names = [name for name, _, _ in scheduler.jobs]
    assert {"growth_initial", "growth_daily", "growth_weekly", "growth_monthly", "growth_pending"} <= set(names)
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
