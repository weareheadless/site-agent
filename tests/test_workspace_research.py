from site_agent.application.intake_coordinator import IntakeCoordinator
from site_agent.core.design_contracts import SiteIntake
from site_agent.core.design_intake_contracts import DesignIntakeDraft
from site_agent.core.jobs import register_jobs
from site_agent.core.memory import Memory
from site_agent.core.scheduler import Scheduler


class _RecoveryLLM:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return '{"candidate_communities":[{"name":"Scuba","language":"en","rationale":"Specialist context."}],"candidate_feeds":[],"query_terms_by_language":{}}'


class _NoopExecutor:
    def start(self):
        pass


def _ready_draft() -> DesignIntakeDraft:
    return DesignIntakeDraft.from_site_intake(SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "North Star Studio",
            "offer_summary": "Brand strategy for independent businesses.",
            "primary_services": ["Brand strategy"],
            "location": "Marseille",
        },
        "audience": {"primary": "Independent business owners"},
        "conversion": {"primary_action": "Book a consultation", "not_available": True},
        "brand": {"voice": "Clear and warm."},
        "site": {"required_pages": ["index.html"], "language": "fr"},
    }))


def test_research_recovery_retries_latest_ready_revision_once(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    llm = _RecoveryLLM()
    coordinator = IntakeCoordinator(
        memory,
        config={"intake": {"research": {"enabled": True}}},
        llm=llm,
    )
    coordinator.research_executor = _NoopExecutor()
    try:
        session = coordinator.intake_service.create_session(draft=_ready_draft())

        coordinator.recover_research_after_restart()
        first = memory.list_research_requests(limit=10)

        assert len(first) == 1
        assert first[0]["trigger"] == "infusion"
        assert first[0]["status"] == "queued"
        assert llm.calls == 1
        assert memory.kv_get("research_recovery_marker") == f"{session['session_id']}:{session['revision']}"

        coordinator.recover_research_after_restart()

        assert len(memory.list_research_requests(limit=10)) == 1
        assert llm.calls == 1
    finally:
        memory.close()


def test_research_status_keeps_insights_linked_to_public_sources(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    coordinator = IntakeCoordinator(memory, config={}, llm=None)
    coordinator.research_service.projection = lambda: {
        "requests": [{
            "request_id": "research_123",
            "status": "completed",
            "updated_at": "2026-09-17T08:00:00+00:00",
            "finding_ids": ["finding_123"],
            "insight_ids": ["insight_123"],
        }],
        "jobs": [{"job_id": "research_job_123", "request_id": "research_123"}],
        "sources": [{
            "source_id": "src_123",
            "title": "Public design feed",
            "url": "https://example.org/feed.xml",
            "language": "fr",
            "trust_state": "allowed",
        }],
        "findings": [{
            "finding_id": "finding_123",
            "source_id": "src_123",
            "summary": "A bounded public observation.",
            "confidence": 0.6,
        }],
        "insights": [{
            "insight_id": "insight_123",
            "kind": "trend",
            "summary": "A cautious trend signal.",
            "confidence": 0.5,
            "finding_ids": ["finding_123"],
        }],
    }
    try:
        status = coordinator.research_status()

        assert status["status"] == "completed"
        assert status["insights"][0]["kind"] == "trend"
        assert status["insights"][0]["sources"][0]["source_id"] == "src_123"
        assert status["findings"][0]["source"]["url"] == "https://example.org/feed.xml"
    finally:
        memory.close()


def test_scheduler_registers_research_recovery_for_enabled_intake(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    coordinator = IntakeCoordinator(memory, config={}, llm=None)
    scheduler = Scheduler(memory, tmp_path / "scheduler.lock")
    try:
        register_jobs(
            scheduler,
            {
                "scheduler": {"enabled": True},
                "sources": {"rss_feeds": [{"url": "https://example.org/feed.xml"}]},
            },
            {
                "config": {
                    "scheduler": {"enabled": True},
                    "sources": {"rss_feeds": [{"url": "https://example.org/feed.xml"}]},
                },
                "memory": memory,
                "llm": object(),
                "intake_coordinator": coordinator,
            },
        )

        assert "research_recovery" in [name for name, _spec, _fn in scheduler.jobs]
    finally:
        memory.close()


def test_scheduler_registers_article_research_reconciliation(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    scheduler = Scheduler(memory, tmp_path / "scheduler.lock")
    config = {
        "scheduler": {"enabled": True},
        "seo": {"article_research": {"enabled": True}},
    }
    try:
        register_jobs(
            scheduler,
            config,
            {"config": config, "memory": memory, "llm": object(), "crawlseo_service": object()},
        )

        names = [name for name, _spec, _fn in scheduler.jobs]
        # The weekly job selects and requests; the daily job adopts the result.
        assert "article" in names
        assert "article_research_cycle" in names
    finally:
        memory.close()


def test_scheduler_omits_research_cycle_without_provider(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    scheduler = Scheduler(memory, tmp_path / "scheduler.lock")
    config = {
        "scheduler": {"enabled": True},
        "editorial": {"enabled": True},
        "seo": {"article_research": {"enabled": True}},
    }
    try:
        register_jobs(
            scheduler,
            config,
            {"config": config, "memory": memory, "llm": object()},
        )

        names = [name for name, _spec, _fn in scheduler.jobs]
        assert "article" in names
        assert "article_research_cycle" not in names
    finally:
        memory.close()
