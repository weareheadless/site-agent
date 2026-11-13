from types import SimpleNamespace

import pytest

from site_agent.application.workspace import BridgeError, ChatService


class Connector:
    def __init__(self, generation=3):
        self.generation = generation
        self.calls = []

    def connector_capabilities(self, site_id=None):
        self.calls.append(("capabilities", site_id))
        return {"schemaVersion": "1.0", "siteId": site_id, "projectId": "project-1",
                "binding": {"status": "active", "executor": "helloada", "generation": self.generation}}

    def connector_opportunities(self, site_id, limit=50, cursor=None, status=None):
        self.calls.append(("opportunities", site_id, limit, cursor, status))
        return {"schemaVersion": "1.0", "siteId": site_id, "projectId": "project-1",
                "opportunities": [], "counts": {"detected": 1, "total": 1}, "nextCursor": None}

    def connector_opportunity_operation(self, opportunity_id, operation):
        self.calls.append(("decision", opportunity_id, dict(operation)))
        return {"schemaVersion": "1.0", "siteId": operation["siteId"], "projectId": "project-1",
                "opportunityId": opportunity_id, "status": "accepted"}

    def connector_task(self, site_id, task_id):
        self.calls.append(("task", site_id, task_id))
        return {"schemaVersion": "1.0", "siteId": site_id, "projectId": "project-1", "task": {"id": task_id}}

    def connector_confirm_task(self, task_id, confirmation):
        self.calls.append(("confirm", task_id, dict(confirmation)))
        return {"schemaVersion": "1.0", "siteId": confirmation["siteId"], "projectId": "project-1", "taskId": task_id}

    def connector_analytics(self, site_id, start_date=None, end_date=None):
        self.calls.append(("analytics", site_id, start_date, end_date))
        return {"schemaVersion": "1.0", "siteId": site_id, "projectId": "project-1",
                "requestedPeriod": {"startDate": start_date or "2026-11-05", "endDate": end_date or "2026-11-11"}}


def _service(connector=None, site_id="site-1"):
    connector = connector or Connector()
    context = {"crawlseo_service": connector, "seo_provisioning_state": {"crawlseo": {"site_id": site_id}}}
    if site_id:
        context["connector_site_id"] = site_id
    tenant = SimpleNamespace(tenant_id="oceanicvibes", context=context)
    return ChatService(registry=SimpleNamespace(tenants={"oceanicvibes": tenant})), tenant, connector


def test_opportunities_read_the_bound_site_and_forward_filters():
    service, tenant, connector = _service()
    result = service.growth_opportunities(tenant=tenant, status="detected", cursor=None, limit=25)
    assert result["counts"] == {"detected": 1, "total": 1}
    assert connector.calls[-1] == ("opportunities", "site-1", 25, None, "detected")


def test_opportunities_report_an_unavailable_connector_instead_of_an_empty_page():
    service, tenant, _connector = _service(site_id=None)
    with pytest.raises(BridgeError, match="connector is unavailable"):
        service.growth_opportunities(tenant=tenant)


def test_a_decision_uses_the_authenticated_owner_and_never_the_body_claim():
    service, tenant, connector = _service()
    result = service.decide_crawlseo_opportunity(
        "opp-1",
        {
            "operation": "accept",
            "expectedUpdatedAt": "2026-11-12T10:00:00.000Z",
            "expectedDecisionId": "decision-1",
            "idempotencyKey": "ui:decision-1",
            "confirmationRef": "conversation:9/message:4",
            "confirmedBy": "someone-else",
        },
        tenant=tenant,
        owner_actor_id="payload:owner-1",
    )
    assert result["status"] == "accepted"
    payload = connector.calls[-1][2]
    assert payload["confirmedBy"] == "payload:owner-1"
    assert payload["generation"] == 3
    assert payload["siteId"] == "site-1"
    assert payload["operation"] == "accept"
    assert payload["expectedUpdatedAt"] == "2026-11-12T10:00:00.000Z"
    assert payload["expectedDecisionId"] == "decision-1"


def test_a_decision_without_an_authenticated_owner_is_refused_before_any_call():
    service, tenant, connector = _service()
    with pytest.raises(BridgeError, match="authenticated owner"):
        service.decide_crawlseo_opportunity("opp-1", {"operation": "accept", "idempotencyKey": "k",
            "confirmationRef": "ref"}, tenant=tenant, owner_actor_id=None)
    assert connector.calls == [("capabilities", "site-1")] or connector.calls == []


def test_a_decision_needs_an_idempotency_key_and_a_confirmation_reference():
    service, tenant, _connector = _service()
    with pytest.raises(BridgeError, match="idempotency key"):
        service.decide_crawlseo_opportunity("opp-1", {"operation": "park"}, tenant=tenant,
                                            owner_actor_id="payload:owner-1")


def test_task_confirmation_relays_only_the_owner_delivery_step():
    service, tenant, connector = _service()
    service.confirm_crawlseo_task(
        "task-1",
        {"opportunityId": "opp-1", "expectedStatus": "in_progress", "status": "delivered",
         "idempotencyKey": "ui:task-1", "confirmationRef": "conversation:9/message:7"},
        tenant=tenant,
        owner_actor_id="payload:owner-1",
    )
    payload = connector.calls[-1][2]
    assert payload == {
        "siteId": "site-1", "generation": 3, "idempotencyKey": "ui:task-1",
        "confirmedBy": "payload:owner-1", "confirmationRef": "conversation:9/message:7",
        "opportunityId": "opp-1", "expectedStatus": "in_progress", "status": "delivered",
    }


def test_performance_reads_saved_observations_for_the_bound_site():
    service, tenant, connector = _service()
    result = service.crawlseo_performance(tenant=tenant, start_date="2026-11-05", end_date="2026-11-11")
    assert result["requestedPeriod"] == {"startDate": "2026-11-05", "endDate": "2026-11-11"}
    assert connector.calls[-1] == ("analytics", "site-1", "2026-11-05", "2026-11-11")


def test_a_tenant_without_a_connector_binding_is_refused():
    connector = Connector()
    tenant = SimpleNamespace(tenant_id="oceanicvibes", context={"crawlseo_service": connector})
    service = ChatService(registry=SimpleNamespace(tenants={"oceanicvibes": tenant}))
    with pytest.raises(BridgeError, match="connector is unavailable"):
        service.crawlseo_task("task-1", tenant=tenant)
