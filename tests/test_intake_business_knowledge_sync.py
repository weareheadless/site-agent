from site_agent.application.intake_coordinator import IntakeCoordinator
from site_agent.core.design_intake_contracts import DesignIntakeDraft
from site_agent.core.memory import Memory


class _KnowledgeClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.writes = []
        self.keys = set()

    def business_knowledge_document(self, **_identity):
        return {"revision": 0}

    def write_business_knowledge_document(self, body):
        self.writes.append(body)
        key = body["idempotencyKey"]
        if self.fail:
            raise RuntimeError("temporary outage")
        if key in self.keys:
            return {"revision": 1}
        self.keys.add(key)
        return {"revision": 1}


def _draft():
    return DesignIntakeDraft.from_dict({
        "schema_version": 1,
        "fields": {"business": {"name": "Studio North", "primary_services": ["Design"]}},
        "provenance": {
            "business.name": {"origin": "confirmed", "source_message_id": 41, "note": "owner said"},
            "business.primary_services": {"origin": "advised", "source_message_id": 42, "note": "accepted suggestion"},
        },
        "assumptions": [{"path": "business.location", "note": "working assumption", "value": "Lyon", "source_message_id": 43}],
        "deferred": [], "contradictions": [], "open_topics": [], "assets": [],
    })


def test_partial_intake_maps_full_provenance_and_is_idempotent(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "intake.db")
    client = _KnowledgeClient()
    monkeypatch.setattr("site_agent.hands.crawlseo.CrawlSEOClient.from_config", lambda _config: client)
    coordinator = IntakeCoordinator(memory, config={
        "seo_provisioning_state": {"crawlseo": {"workspace_id": "workspace-1", "project_id": "project-1"}},
    }, llm=None)
    try:
        revision = {"revision": 2, "created_ts": "2026-10-26T10:00:00+00:00"}
        first = coordinator._sync_business_knowledge("session-1", _draft(), revision)
        replay = coordinator._sync_business_knowledge("session-1", _draft(), revision)
        assert first["status"] == replay["status"] == "synced"
        assert len(client.writes) == 2
        body = client.writes[0]
        assert body["documentId"] == "business-profile"
        assert body["idempotencyKey"] == client.writes[1]["idempotencyKey"]
        assert body["changes"]["businessName"]["provenance"] == {
            "kind": "intake", "sourceId": "session-1:41", "originSystem": "site-agent",
            "originRecordId": "session-1:2", "originRevision": 2,
            "actor": {"type": "owner", "id": "intake"}, "status": "owner_confirmed",
            "recordedAt": "2026-10-26T10:00:00+00:00", "observedAt": "2026-10-26T10:00:00+00:00",
            "evidenceUri": "site-agent://intake/session-1/revision/2/field/business.name", "quote": "owner said",
        }
        assert body["changes"]["services"]["publicationUse"] == "internal_only"
        assert body["changes"]["services"]["provenance"]["status"] == "advised"
        assert body["changes"]["location"]["publicationUse"] == "internal_only"
        assert body["changes"]["location"]["provenance"]["status"] == "assumed"
        assert body["changes"]["businessName"]["publicationUse"] == "approved"
        assert memory.kv_get("business_knowledge_sync:" + __import__("hashlib").sha256(body["idempotencyKey"].encode()).hexdigest())["status"] == "synced"
    finally:
        memory.close()


def test_failed_remote_write_remains_pending_and_can_retry(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "intake.db")
    client = _KnowledgeClient(fail=True)
    monkeypatch.setattr("site_agent.hands.crawlseo.CrawlSEOClient.from_config", lambda _config: client)
    coordinator = IntakeCoordinator(memory, config={
        "seo_provisioning_state": {"crawlseo": {"workspace_id": "workspace-1", "project_id": "project-1"}},
    }, llm=None)
    try:
        revision = {"revision": 1, "created_ts": "2026-10-26T10:00:00+00:00"}
        result = coordinator._sync_business_knowledge("session-2", _draft(), revision)
        assert result["status"] == "pending"
        key_hash = __import__("hashlib").sha256(client.writes[0]["idempotencyKey"].encode()).hexdigest()
        assert memory.kv_get("business_knowledge_sync:" + key_hash) is None
        client.fail = False
        assert coordinator._sync_business_knowledge("session-2", _draft(), revision)["status"] == "synced"
    finally:
        memory.close()


def test_missing_project_is_pending_without_fabricating_identity(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    coordinator = IntakeCoordinator(memory, config={}, llm=None)
    try:
        assert coordinator._sync_business_knowledge("session-3", _draft(), {"revision": 1}) == {
            "status": "pending", "reason": "crawlseo_project_unavailable",
        }
    finally:
        memory.close()
