from site_agent.application.incubation_research import IncubationResearchExecutor, IncubationResearchService
from site_agent.core.incubation_contracts import ResearchSource, SourceTrustState, SubscriptionState
from site_agent.core.memory import Memory
from site_agent.hands.feed_discovery import FeedDiscoveryError, ResearchDocument, canonical_public_url


class _FailingReader:
    def read(self, source):
        raise FeedDiscoveryError("feed is unreachable", code="connection_failed")


def test_automatic_pass_falls_back_to_pipeworx_when_no_source_is_readable(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    fallback_calls = []

    def _fallback(request):
        fallback_calls.append(request)
        return [{
            "summary": "Cave-diving exploration weeks are priced premium and booked by certified divers.",
            "title": "Cave diving market note",
            "source": "pipeworx",
            "url": "https://pipeworx.io/research/cave-diving",
            "confidence": 0.7,
        }]

    service = IncubationResearchService(memory, reader=_FailingReader(), fallback_reader=_fallback)
    candidate = ResearchSource.from_dict({
        "source_id": "src_abc123def4567890abc123def4567890",
        "kind": "rss",
        "url": "https://example.com/cave.xml",
        "feed_url": "https://example.com/cave.xml",
        "title": "r/caving",
        "discovered_by": "research_planner",
        "trust_state": SourceTrustState.CANDIDATE.value,
        "ongoing_subscription": SubscriptionState.NOT_APPLICABLE.value,
    })
    memory.save_research_source(candidate)
    try:
        result = service.request({
            "trigger": "intake_threshold",
            "query": "cave diving exploration week",
            "intake_revision": 2,
            "owner_language": "en",
            "source_ids": [candidate.source_id],
            "fetch": True,
        }, enqueue=True)

        assert result["status"] == "queued"
        assert fallback_calls == []

        executor = IncubationResearchExecutor(service, interval=0.01)
        try:
            assert executor.process_one() is True
        finally:
            executor.stop()

        assert len(fallback_calls) == 1
        assert fallback_calls[0]["query"] == "cave diving exploration week"
        projection = service.projection()
        assert projection["jobs"][0]["status"] == "completed"
        assert projection["requests"][0]["status"] == "completed"
        assert projection["findings"], "fallback evidence must be persisted as findings"
        finding = projection["findings"][0]
        assert "Cave-diving exploration weeks" in finding["summary"]
        assert finding["source_id"].startswith("src_fallback_")
        assert projection["insights"], "fallback findings must be synthesized into insights"
    finally:
        memory.close()


class _Reader:
    def __init__(self):
        self.calls = []

    def read(self, source):
        self.calls.append(source.source_id)
        return (
            ResearchDocument(
                source_id=source.source_id,
                url=source.url,
                title="A useful market note",
                summary="A concise observation about the audience.",
                published_at="2026-09-02T00:00:00+00:00",
                content_hash="a" * 64,
            ),
        )


def test_public_feed_research_requires_owner_source_approval(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    reader = _Reader()
    service = IncubationResearchService(memory, reader=reader)
    try:
        discovered = service.request({"feed_urls": ["https://example.com/feed.xml"]})
        assert discovered["status"] == "awaiting_source_approval"
        source_id = discovered["source_ids"][0]
        assert reader.calls == []

        result = service.request({
            "approve_source_ids": [source_id],
            "source_ids": [source_id],
            "run": True,
            "query": "audience market",
        })
        assert result["status"] == "complete"
        assert reader.calls == [source_id]
        assert result["findings"][0]["source_id"] == source_id
        assert "https://" not in result["findings"][0]["summary"]
    finally:
        memory.close()


def test_public_feed_url_policy_rejects_private_targets():
    for value in ("file:///tmp/feed.xml", "http://localhost/feed", "http://127.0.0.1/feed", "https://user:pass@example.com/feed"):
        try:
            canonical_public_url(value)
        except FeedDiscoveryError:
            pass
        else:
            raise AssertionError(f"expected URL policy rejection for {value}")


def test_research_source_disposition_is_persisted_without_direct_sql(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    service = IncubationResearchService(memory, reader=_Reader())
    try:
        source_id = service.discover(["https://example.com/feed.xml"])["source_ids"][0]
        updated = service.update_source(source_id, {"trust_state": "allowed", "ongoing_subscription": "approved"})
        assert updated["trust_state"] == "allowed"
        assert updated["ongoing_subscription"] == "approved"
        assert memory.get_research_source(source_id)["trust_state"] == "allowed"
    finally:
        memory.close()


def test_research_pass_persists_evidence_linked_cross_language_insights(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    service = IncubationResearchService(memory, reader=_Reader())
    try:
        source_id = service.discover(["https://example.com/feed.xml"])["source_ids"][0]
        service.update_source(source_id, {"trust_state": "allowed", "language": "fr"})

        result = service.request({
            "owner_language": "en",
            "query": "audience market",
            "source_ids": [source_id],
            "run": True,
        })

        assert result["insights"]
        insight = result["insights"][0]
        assert insight["source_languages"] == ["fr"]
        assert insight["finding_ids"] == [result["findings"][0]["finding_id"]]
        assert result["request"]["insight_ids"] == [insight["insight_id"]]
        assert "https://" not in insight["summary"]
    finally:
        memory.close()


def test_enqueued_research_is_durable_and_runs_outside_request_path(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    reader = _Reader()
    service = IncubationResearchService(memory, reader=reader)
    executor = IncubationResearchExecutor(service, interval=0.01)
    try:
        source_id = service.discover(["https://example.com/feed.xml"])["source_ids"][0]
        service.update_source(source_id, {"trust_state": "allowed"})

        queued = service.request({
            "owner_language": "en",
            "query": "audience market",
            "source_ids": [source_id],
            "fetch": True,
        }, enqueue=True)

        assert queued["status"] == "queued"
        assert queued["job"]["status"] == "queued"
        assert reader.calls == []

        assert executor.process_one() is True
        projection = service.projection()
        assert projection["jobs"][0]["status"] == "completed"
        assert projection["requests"][0]["status"] == "completed"
        assert reader.calls == [source_id]
    finally:
        executor.stop()
        memory.close()
