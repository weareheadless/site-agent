from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import FastAPI

from site_agent.application.crawlseo_accounting import (
    AccountingVerificationError,
    current_import_receipt,
    terminal_import_execution_resolved,
    verify_import_receipt,
)


def _plan_and_receipt(*, task_status="FAILED", actual_cost=None):
    created = "2026-10-01T06:00:00+00:00"
    updated = "2026-10-02T06:00:00+00:00"
    settled = updated if actual_cost is not None else None
    status = "settled" if actual_cost is not None else "uncertain"
    reservation = {
        "reservation_id": "legacy-reservation-1", "period": "2026-10", "amount_micros": "12000",
        "currency": "USD", "operation": "dataforseo:article_keyword_overview", "status": status,
        "provider_task_id": "source-run-1", "created_ts": created, "updated_ts": updated,
        "settled_ts": settled, "recorded_actual_cost_micros": str(actual_cost) if actual_cost is not None else None,
    }
    idea = {"id": 9, "research_run_id": "source-run-1", "serp_run_id": None,
        "keyword_budget_reservation_id": reservation["reservation_id"], "serp_budget_reservation_id": None,
        "provider_task_id": "external-provider-1"}
    plan = {
        "siteId": "target-site", "projectId": "target-project", "snapshotHash": "sha256:" + "a" * 64,
        "crawlseo": {"projectId": "target-project", "binding": {"siteId": "target-site", "projectId": "target-project",
            "status": "active", "executor": "helloada", "generation": 7}},
        "legacyPolicy": {"monthlyResearchCapMicros": "500000", "effectiveMonthlyAllowanceMicros": "500000",
            "timezone": "America/Cancun", "researchAuthority": "crawlseo"},
        "inventory": {"budgetReservations": {"total": 1, "truncated": False, "items": [reservation]},
            "articleIdeas": {"total": 1, "truncated": False, "items": [idea]}},
    }
    effective_status = "SETTLED" if actual_cost is not None else "UNCERTAIN"
    source_task = {"id": "source-run-1", "siteId": "source-site", "projectId": "source-project",
        "kind": "KEYWORD_OVERVIEW", "status": task_status, "providerTaskId": "external-provider-1",
        "costMicros": actual_cost, "requestedAt": created, "attemptedAt": created,
        "completedAt": updated, "updatedAt": updated}
    input_row = {"localReservationId": reservation["reservation_id"], "taskId": "source-run-1",
        "operation": reservation["operation"], "legacyStatus": status, "period": "2026-10",
        "timeZone": "America/Cancun", "currency": "USD", "amountMicros": "12000",
        "createdAt": created, "updatedAt": updated, "settledAt": settled}
    effective = {"amountMicros": "12000", "actualCostMicros": str(actual_cost) if actual_cost is not None else None,
        "status": effective_status, "createdAt": created, "updatedAt": updated, "settledAt": settled}
    receipt = {"id": "import_receipt_1", "sourceProjectId": "source-project", "sourceSiteId": "source-site",
        "targetProjectId": "target-project", "targetSiteId": "target-site", "sourceEvidenceHash": "b" * 64,
        "snapshot": {"source": {"projectId": "source-project", "siteId": "source-site", "currency": "USD"},
            "target": {"projectId": "target-project", "siteId": "target-site", "currency": "USD",
                "bindingExecutor": "helloada", "bindingStatus": "active", "bindingGeneration": 7},
            "rows": [{"input": input_row, "sourceTask": source_task, "effective": effective}]}}
    return plan, receipt


def test_authoritative_failed_import_keeps_full_unknown_quote_held_without_zero_actual():
    plan, receipt = _plan_and_receipt()
    verified = verify_import_receipt(receipt, plan, "verify-import-0001")
    assert verified["knownSpendMicros"] == "0"
    assert verified["heldUnknownMicros"] == "12000"
    assert verified["rows"][0]["actualCostMicros"] is None
    assert verified["rows"][0]["effectiveStatus"] == "UNCERTAIN"
    assert terminal_import_execution_resolved(verified["rows"][0], plan["inventory"]["budgetReservations"]["items"][0])


def test_authoritative_known_cost_is_counted_as_spend_and_terminal():
    plan, receipt = _plan_and_receipt(task_status="COMPLETED", actual_cost=475)
    verified = verify_import_receipt(receipt, plan, "verify-import-0002")
    assert verified["knownSpendMicros"] == "475"
    assert verified["heldUnknownMicros"] == "0"
    assert verified["rows"][0]["actualCostMicros"] == "475"


def test_import_verification_requires_exact_target_and_complete_local_coverage():
    plan, receipt = _plan_and_receipt()
    wrong_target = deepcopy(receipt)
    wrong_target["targetSiteId"] = "other-site"
    with pytest.raises(AccountingVerificationError, match="identities"):
        verify_import_receipt(wrong_target, plan, "verify-import-0003")
    partial = deepcopy(receipt)
    partial["snapshot"]["rows"] = []
    with pytest.raises(AccountingVerificationError, match="cover"):
        verify_import_receipt(partial, plan, "verify-import-0004")


def test_nonterminal_provider_task_does_not_resolve_execution_drain():
    plan, receipt = _plan_and_receipt(task_status="ATTEMPTING")
    with pytest.raises(AccountingVerificationError, match="nonterminal"):
        verify_import_receipt(receipt, plan, "verify-import-0005")
    item = {"sourceTaskStatus": "ATTEMPTING", "effectiveStatus": "UNCERTAIN",
        "quoteMicros": "12000", "actualCostMicros": None}
    assert not terminal_import_execution_resolved(item, plan["inventory"]["budgetReservations"]["items"][0])


def test_committed_sanitized_inventory_matches_authoritative_import_receipt_shape():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "crawlseo_legacy_budget_import_sanitized.json")
        .read_text(encoding="utf-8"))
    plan, receipt = fixture["plan"], fixture["receipt"]
    verified = verify_import_receipt(receipt, plan, "fixture-import-check-0001")
    assert verified["localRowCount"] == 7
    assert verified["heldUnknownMicros"] == "100000"
    assert verified["knownSpendMicros"] == "72720"
    rows = {row["localReservationId"]: row for row in verified["rows"]}
    local_rows = plan["inventory"]["budgetReservations"]["items"]
    assert sum(row["sourceTaskStatus"] == "COMPLETED" for row in verified["rows"]) == 6
    assert sum(row["sourceTaskStatus"] == "FAILED" for row in verified["rows"]) == 1
    held_local = next(row for row in local_rows if row["reservation_id"] == "growth-budget-fixture-07")
    held = rows[held_local["reservation_id"]]
    assert held["effectiveStatus"] == "UNCERTAIN"
    assert held["actualCostMicros"] is None
    assert held["quoteMicros"] == held_local["amount_micros"]
    assert terminal_import_execution_resolved(held, held_local)
    assert all(row["operation"].startswith("dataforseo:") for row in verified["rows"])
    for row in receipt["snapshot"]["rows"]:
        local = next(item for item in local_rows if item["reservation_id"] == row["input"]["localReservationId"])
        idea = next(item for item in plan["inventory"]["articleIdeas"]["items"]
            if item.get("keyword_budget_reservation_id") == local["reservation_id"]
            or item.get("serp_budget_reservation_id") == local["reservation_id"])
        # The local provider_task_id is the CrawlSEO run ID; DataForSEO UUIDs live in the idea/source receipt.
        assert local["provider_task_id"] == row["sourceTask"]["id"]
        if row["sourceTask"]["kind"] == "KEYWORD_OVERVIEW":
            assert idea["provider_task_id"] == row["sourceTask"]["providerTaskId"]
        else:
            assert row["sourceTask"]["providerTaskId"] != local["provider_task_id"]


def test_verify_budget_import_route_fetches_authoritative_receipt_and_invalidates_on_local_drift(tmp_path, monkeypatch):
    from site_agent.application.workspace import BridgeError
    from site_agent.hands.crawlseo_migration_control import CrawlSEOMigrationControlClient
    from site_agent.web.workspace import register_workspace_routes
    from tests.test_workspace_web import _payload_growth_review_fixture

    memory, _payload, _hash, _draft_id, _initiative_id, _approval, tenant, service, _task = (
        _payload_growth_review_fixture(tmp_path)
    )
    plan, remote_receipt = _plan_and_receipt()
    plan["inventory"] = deepcopy(plan["inventory"])
    monkeypatch.setattr(service, "crawlseo_migration_plan", lambda *, tenant: plan)
    monkeypatch.setattr(memory, "crawlseo_migration_snapshot", lambda: deepcopy(plan["inventory"]))
    class ControlClient:
        calls = []
        receipt = deepcopy(remote_receipt)
        def budget_import_receipt(self, receipt_id):
            self.calls.append(receipt_id)
            return deepcopy(self.receipt)
    control = ControlClient()
    monkeypatch.setattr(CrawlSEOMigrationControlClient, "from_config", lambda *_args: control)

    body = {"mode": "apply", "expectedSnapshotHash": plan["snapshotHash"],
        "operatorRequestId": "verify-import-route-0001", "importReceiptId": remote_receipt["id"]}
    with pytest.raises(BridgeError, match="fields"):
        service.crawlseo_migration_verify_budget_import({**body, "receipt": remote_receipt}, tenant=tenant)
    assert control.calls == []

    app = FastAPI()
    register_workspace_routes(app, config={}, env={}, service=service, registry=service.registry,
        prefix="/workspace", control_prefix="/control", control_token="migration-control-secret")
    async def exercise_route():
        import httpx
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            denied = await client.post(f"/control/{tenant.tenant_id}/growth/migration/verify-budget-import", json=body)
            approved = await client.post(f"/control/{tenant.tenant_id}/growth/migration/verify-budget-import", json=body,
                headers={"Authorization": "Bearer migration-control-secret"})
            return denied, approved
    denied, approved = asyncio.run(exercise_route())
    assert denied.status_code == 401
    assert approved.status_code == 200, approved.text
    assert approved.json()["receipt"]["heldUnknownMicros"] == "12000"
    assert approved.json()["receipt"]["rows"][0]["actualCostMicros"] is None
    assert control.calls == [remote_receipt["id"]]
    persisted_plan = deepcopy(plan)
    assert current_import_receipt(memory, persisted_plan) is not None
    persisted_plan["inventory"]["articleIdeas"]["items"].append({"id": 999, "status": "held",
        "research_run_id": "unrelated-run", "keyword_budget_reservation_id": None,
        "provider_task_id": "unrelated-provider-task"})
    persisted_plan["inventory"]["articleIdeas"]["total"] += 1
    assert current_import_receipt(memory, persisted_plan) is not None
    persisted_plan["inventory"]["budgetReservations"]["items"][0]["amount_micros"] = "12001"
    assert current_import_receipt(memory, persisted_plan) is None

    control.receipt["targetSiteId"] = "wrong-site"
    with pytest.raises(BridgeError, match="identities"):
        service.crawlseo_migration_verify_budget_import({**body,
            "operatorRequestId": "verify-import-route-0002"}, tenant=tenant)
    assert len(memory.crawlseo_migration_receipts()) == 1
    memory.close()
