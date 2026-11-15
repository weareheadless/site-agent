from __future__ import annotations

from types import SimpleNamespace

import pytest

from site_agent.application.growth_open import (
    GrowthOpenError,
    bind_draft,
    deliver_tasks,
    open_group,
    open_opportunity,
    publication_hook,
    read_bindings,
)
from site_agent.core.memory import Memory


def _opportunity(identifier: str, *, kind: str = "O8_structured_data_gap", status: str = "detected",
                 tasks: list[dict] | None = None) -> dict:
    return {
        "id": identifier,
        "type": kind,
        "status": status,
        "title": f"Missing structured data on https://example.test/{identifier}",
        "summary": "No identity schema on this page.",
        "pageUrl": f"https://example.test/{identifier}",
        "updatedAt": "2026-11-15T10:00:00.000Z",
        "recommendationDecision": {"readiness": "actionable", "confidence": "high", "decisionId": "d-1"},
        "scoreInputs": {},
        "queries": [],
        "tasks": tasks or [],
    }


class Connector:
    def __init__(self, opportunities: list[dict] | None = None) -> None:
        self.opportunities = opportunities or []
        self.calls: list[tuple] = []
        self.status = {row["id"]: "todo" for row in self.opportunities}

    def connector_capabilities(self, site_id=None):
        return {"binding": {"generation": 4}}

    def connector_opportunities(self, site_id, limit=50, cursor=None, status=None):
        return {"siteId": site_id, "opportunities": self.opportunities, "counts": {}, "nextCursor": None}

    def connector_opportunity_operation(self, opportunity_id, operation):
        self.calls.append(("accept", opportunity_id, dict(operation)))
        row = next(item for item in self.opportunities if item["id"] == opportunity_id)
        row["status"] = "accepted"
        task = {"id": f"task-{opportunity_id}", "status": "todo"}
        row["tasks"] = [task]
        return {"opportunityId": opportunity_id, "status": "accepted", "taskId": task["id"]}

    def connector_task(self, site_id, task_id):
        return {"task": {"id": task_id, "status": self.status.get(task_id, "todo")}}

    def connector_confirm_task(self, task_id, confirmation):
        self.calls.append(("confirm", task_id, dict(confirmation)))
        self.status[task_id] = confirmation["status"]
        return {"taskId": task_id, "status": confirmation["status"]}


def _enqueue(memory: Memory):
    def enqueue(body):
        conversation = memory.create_conversation(title=body["message"][:60])
        job = memory.enqueue_chat_job(conversation, body["message"], display_message=body["message"])
        return {"conversation_id": conversation, "job_id": job}
    return enqueue


def _tenant(memory: Memory, site_id: str = "site-1"):
    return SimpleNamespace(tenant_id="astrid", memory=memory, config={},
                           context={"crawlseo_service": Connector(), "seo_provisioning_state": {"crawlseo": {"site_id": site_id}}})


def test_open_accepts_the_finding_starts_the_task_and_writes_one_brief(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    connector = Connector([_opportunity("opp-1")])
    tenant = _tenant(memory)
    result = open_opportunity(connector, memory, tenant, opportunity_id="opp-1", site_id="site-1",
                             generation=4, actor="payload:astrid:1", enqueue=_enqueue(memory))
    assert result["taskId"] == "task-opp-1"
    assert result["conversationId"]
    assert connector.status["task-opp-1"] == "in_progress"
    assert [call[0] for call in connector.calls] == ["accept", "confirm"]
    message = memory.conn.execute(
        "SELECT text FROM chat_messages WHERE conversation_id = ? ORDER BY id LIMIT 1",
        (result["conversationId"],),
    ).fetchone()["text"]
    assert "fix this CrawlSEO finding" in message

    # Clicking again opens the same conversation instead of accepting twice.
    again = open_opportunity(connector, memory, tenant, opportunity_id="opp-1", site_id="site-1",
                             generation=4, actor="payload:astrid:1", enqueue=_enqueue(memory))
    assert again["idempotent"] is True
    assert again["conversationId"] == result["conversationId"]
    assert [call[0] for call in connector.calls].count("accept") == 1
    memory.close()


def test_group_refuses_content_and_accepts_only_technical_members(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    connector = Connector([_opportunity("opp-1"), _opportunity("opp-2"), _opportunity("blog", kind="O3_content_gap")])
    tenant = _tenant(memory)

    with pytest.raises(GrowthOpenError, match="only technical"):
        open_group(connector, memory, tenant, opportunity_ids=["opp-1", "blog"], site_id="site-1",
                   generation=4, actor="payload:astrid:1", enqueue=_enqueue(memory))

    result = open_group(connector, memory, tenant, opportunity_ids=["opp-1", "opp-2"], site_id="site-1",
                        generation=4, actor="payload:astrid:1", enqueue=_enqueue(memory))
    assert len(result["taskIds"]) == 2
    message = memory.conn.execute(
        "SELECT text FROM chat_messages WHERE conversation_id = ? ORDER BY id LIMIT 1",
        (result["conversationId"],),
    ).fetchone()["text"]
    assert "2 technical findings share one delivery" in message
    memory.close()


def test_a_draft_from_the_conversation_carries_the_task_binding(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    connector = Connector([_opportunity("opp-1")])
    tenant = _tenant(memory)
    opened = open_opportunity(connector, memory, tenant, opportunity_id="opp-1", site_id="site-1",
                             generation=4, actor="payload:astrid:1", enqueue=_enqueue(memory))
    draft = memory.save_draft(title="Fix schema", body="", kind="merge", meta={})
    bind_draft(memory, draft, opened["jobId"])
    meta = memory.get_draft(draft)["meta"]
    assert meta["crawlseo_tasks"][0]["taskId"] == "task-opp-1"
    board = read_bindings(memory, {}, task_statuses={"task-opp-1": "in_progress"})
    assert board["bindings"][0]["draftId"] == draft
    # A pending draft is the owner's turn, even though Ada owns the work.
    assert board["bindings"][0]["state"] == "awaiting"
    memory.close()


def test_publication_confirms_every_member_once_and_marks_it_live(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    connector = Connector([_opportunity("opp-1"), _opportunity("opp-2")])
    tenant = _tenant(memory)
    opened = open_group(connector, memory, tenant, opportunity_ids=["opp-1", "opp-2"], site_id="site-1",
                        generation=4, actor="payload:astrid:1", enqueue=_enqueue(memory))
    tasks = [{"siteId": "site-1", "taskId": task_id, "opportunityId": opportunity_id}
             for task_id, opportunity_id in zip(opened["taskIds"], ["opp-1", "opp-2"])]

    assert deliver_tasks(connector, memory, site_id="site-1", generation=4, tasks=tasks,
                         actor="payload:astrid:1", reference="growth:draft:9") == 2
    assert {task_id: connector.status[task_id] for task_id in opened["taskIds"]} == {
        task_id: "delivered" for task_id in opened["taskIds"]}
    confirmed = [call for call in connector.calls if call[0] == "confirm"]
    assert len(confirmed) == 4  # two starts + two deliveries

    # A retried approval does not report the same delivery again.
    assert deliver_tasks(connector, memory, site_id="site-1", generation=4, tasks=tasks,
                         actor="payload:astrid:1", reference="growth:draft:9") == 0
    board = read_bindings(memory, {}, task_statuses={task_id: "delivered" for task_id in opened["taskIds"]})
    assert {binding["state"] for binding in board["bindings"]} == {"live"}
    memory.close()


def test_a_queued_release_waits_for_its_own_receipt(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    connector = Connector([_opportunity("opp-1")])
    tenant = _tenant(memory)
    opened = open_opportunity(connector, memory, tenant, opportunity_id="opp-1", site_id="site-1",
                             generation=4, actor="payload:astrid:1", enqueue=_enqueue(memory))
    draft = memory.save_draft(title="Fix schema", body="", kind="merge", meta={})
    bind_draft(memory, draft, opened["jobId"])
    memory.update_draft_status(draft, "publishing")
    stored = memory.get_draft(draft)
    publication_hook(tenant.context, stored, {"status": "publishing"}, actor="payload:astrid:1")
    binding = read_bindings(memory, {})["bindings"][0]
    assert binding["state"] == "working"  # queued, not yet proven live
    assert connector.status["task-opp-1"] == "in_progress"
    memory.close()


def test_read_projects_the_five_owner_states(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    connector = Connector([_opportunity("opp-open"), _opportunity("opp-working"), _opportunity("opp-live"),
                           _opportunity("opp-resolved")])
    tenant = _tenant(memory)
    for identifier in ("opp-working", "opp-live", "opp-resolved"):
        open_opportunity(connector, memory, tenant, opportunity_id=identifier, site_id="site-1",
                         generation=4, actor="payload:astrid:1", enqueue=_enqueue(memory))
    board = read_bindings(memory, {}, task_statuses={
        "task-opp-working": "in_progress", "task-opp-live": "delivered", "task-opp-resolved": "verified_outcome",
    })
    states = {binding["opportunityId"]: binding["state"] for binding in board["bindings"]}
    assert states["opp-working"] == "working"
    assert states["opp-live"] == "live"
    assert states["opp-resolved"] == "resolved"
    memory.close()
