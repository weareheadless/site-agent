from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

from site_agent.application.crawlseo_migration import (
    _hash, _inventory_fingerprint, apply_resolution, build_resolution_preview,
    resolution_status,
)
from site_agent.core.contracts import ContractError
from site_agent.core.memory import Memory


def _plan(memory: Memory):
    inventory = memory.crawlseo_migration_snapshot()
    plan = {"tenant": "test", "siteId": "site", "inventory": inventory,
            "crawlseo": {"budget": {"policyRevision": 2}, "actions": [], "binding": {"id": "b"}}}
    plan["snapshotHash"] = _hash({"test": "snapshot"})
    return plan


def _route_body(plan, request_id="request-0001"):
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    return {"type": "canonical_routes_verification", "operatorRequestId": request_id,
            "expectedSnapshotHash": plan["snapshotHash"],
            "expectedEvidenceFingerprint": _inventory_fingerprint("canonical_routes_verification", plan),
            "decision": "verified", "evidence": {"robotsTxtHash": "sha256:" + "a" * 64, "sitemapHash": "sha256:" + "b" * 64,
                "canonicalSiteId": "site", "checkedAt": now, "evidenceMode": "operator_attested"}}


def test_resolution_rejects_stale_snapshot(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    plan = _plan(memory)
    body = _route_body(plan)
    body["expectedSnapshotHash"] = "sha256:wrong"
    with pytest.raises(ContractError, match="snapshot hash"):
        build_resolution_preview(plan, body)


def test_receipt_is_idempotent_and_request_id_conflict_rejected(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    plan = _plan(memory)
    body = _route_body(plan)
    preview = build_resolution_preview(plan, body)
    first = apply_resolution(memory, plan, body)
    again = apply_resolution(memory, plan, body)
    assert preview["resolution"]["decision"] == "verified"
    assert first["idempotent"] is False
    assert again["idempotent"] is True
    conflict = {**body, "evidence": {**body["evidence"], "robotsTxtHash": "sha256:" + "d" * 64}}
    # Same request ID cannot be repurposed, even if its proof remains structurally valid.
    with pytest.raises(ContractError, match="conflicting receipt"):
        apply_resolution(memory, plan, conflict)
    assert resolution_status(plan, memory)["gatePassed"] is False


def test_deleted_owner_fact_can_only_be_quarantined_and_deferred(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    plan = _plan(memory)
    fact = {"id": 4, "deleted": True, "updated_ts": "f1"}
    initiative = {"id": 4, "updated_ts": "i1"}
    plan["inventory"]["issue330References"] = {"ownerFactConversation": fact, "initiatives": {"4": initiative}}
    plan["snapshotHash"] = _hash({"ownerFact": "deleted"})
    base = {"type": "owner_fact_disposition", "operatorRequestId": "request-fact-01",
            "expectedSnapshotHash": plan["snapshotHash"],
            "expectedEvidenceFingerprint": _inventory_fingerprint("owner_fact_disposition", plan),
            "decision": "quarantine_defer", "evidence": {"initiativeId": 4, "conversationId": 4,
                "deletedFactRestored": False, "reason": "deleted in source",
                "factRecordHash": _hash(fact), "factRevision": "f1",
                "initiativeRecordHash": _hash(initiative), "initiativeRevision": "i1"}}
    assert build_resolution_preview(plan, base)["valid"]
    forbidden = {**base, "decision": "replacement_reference", "evidence": {**base["evidence"],
        "deletedFactRestored": True, "replacementConversationId": 99}}
    with pytest.raises(ContractError, match="existing exact confirmation"):
        build_resolution_preview(plan, forbidden)


def test_route_evidence_rejects_bad_digest_wrong_site_and_old_time(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    plan = _plan(memory)
    body = _route_body(plan)
    body["evidence"]["robotsTxtHash"] = "sha256:short"
    with pytest.raises(ContractError, match="SHA-256"):
        build_resolution_preview(plan, body)
    body = _route_body(plan)
    body["evidence"]["canonicalSiteId"] = "other"
    with pytest.raises(ContractError, match="canonical site"):
        build_resolution_preview(plan, body)
    body = _route_body(plan)
    body["evidence"]["checkedAt"] = "2020-01-01T00:00:00+00:00"
    with pytest.raises(ContractError, match="recent ISO"):
        build_resolution_preview(plan, body)


def test_receipts_are_sql_immutable(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    plan = _plan(memory)
    apply_resolution(memory, plan, _route_body(plan))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        memory.conn.execute("UPDATE crawlseo_migration_receipts SET receipt_json='{}'")
    memory.conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        memory.conn.execute("DELETE FROM crawlseo_migration_receipts")
    memory.conn.rollback()


def test_action_ledger_requires_complete_matching_current_hashes(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    plan = _plan(memory)
    plan["crawlseo"]["actionSiteIdentityVerified"] = True
    plan["crawlseo"]["bindingSiteIdentityVerified"] = True
    local = {k: plan["inventory"].get(k) for k in ("initiatives", "ownerActions", "executionBindings", "connectorEvents")}
    remote = plan["crawlseo"]["actions"]
    body = {"type": "action_ledger_comparison", "operatorRequestId": "ledger-0001",
            "expectedSnapshotHash": plan["snapshotHash"],
            "expectedEvidenceFingerprint": _inventory_fingerprint("action_ledger_comparison", plan),
            "decision": "compared", "evidence": {"cursorComplete": True, "actionsTruncated": False,
                "available": True, "remoteLedgerHash": _hash(remote), "localLedgerHash": _hash(local),
                "remoteActionDispositions": [], "comparisonHash": _hash({"remote": remote, "local": local, "dispositions": []}), "evidenceMode": "operator_attested"}}
    assert build_resolution_preview(plan, body)["valid"]
    body["evidence"]["cursorComplete"] = False
    with pytest.raises(ContractError, match="complete, untruncated"):
        build_resolution_preview(plan, body)


def test_protected_owner_review_is_not_retirable_by_id_or_state(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    plan = _plan(memory)
    row = {"id": 99, "state": "proposed", "approval_id": 15, "review_package_hash": "sha256:abc", "updated_ts": "v1"}
    plan["inventory"]["initiatives"]["items"] = [row]
    body = {"type": "work_disposition", "operatorRequestId": "work-protect-01",
            "expectedSnapshotHash": plan["snapshotHash"],
            "expectedEvidenceFingerprint": _inventory_fingerprint("work_disposition", plan, [{"kind": "initiative", "id": 99, "revision": "v1", "recordHash": _hash(row)}]),
            "decision": "quarantine", "scope": [{"kind": "initiative", "id": 99, "revision": "v1", "recordHash": _hash(row)}],
            "evidence": {"reason": "operator review"}}
    with pytest.raises(ContractError, match="owner decision"):
        build_resolution_preview(plan, body)


def test_budget_reconciliation_rejects_missing_actual_and_incomplete_scope(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    plan = _plan(memory)
    plan["crawlseo"]["budgetSiteIdentityVerified"] = True
    row = {"reservation_id": "r1", "period": "2026-10", "currency": "USD", "provider_task_id": "task1",
           "updated_ts": "v1", "recorded_actual_cost_micros": None}
    plan["inventory"]["budgetReservations"] = {"items": [row], "total": 1}
    plan["crawlseo"]["budget"] = {"policyRevision": 2, "remainingMicros": 0}
    comparison = {"reservationId": "r1", "recordHash": _hash(row), "revision": "v1",
        "taskId": "task1", "period": "2026-10", "currency": "USD", "receiptId": "provider:1"}
    receipt_payload = {key: comparison.get(key) for key in ("receiptId", "reservationId", "taskId", "period", "currency", "reconciledActualCostMicros")}
    receipt_payload["sourceHash"] = plan["snapshotHash"]
    comparison["receiptHash"] = _hash(receipt_payload)
    evidence = {"evidenceMode": "operator_attested", "reconciliationId": "rec1",
        "sourceHash": plan["snapshotHash"], "remoteBudgetSnapshot": plan["crawlseo"]["budget"],
        "reservationComparisons": [comparison]}
    body = {"type": "budget_reconciliation", "operatorRequestId": "budget-0001",
        "expectedSnapshotHash": plan["snapshotHash"],
        "expectedEvidenceFingerprint": _inventory_fingerprint("budget_reconciliation", plan),
        "decision": "reconciled_evidence", "evidence": evidence}
    with pytest.raises(ContractError, match="actual cost"):
        build_resolution_preview(plan, body)
    comparison["reconciledActualCostMicros"] = "4"
    receipt_payload = {key: comparison.get(key) for key in ("receiptId", "reservationId", "taskId", "period", "currency", "reconciledActualCostMicros")}
    receipt_payload["sourceHash"] = evidence["sourceHash"]
    comparison["receiptHash"] = _hash(receipt_payload)
    assert build_resolution_preview(plan, body)["valid"]
    evidence["reservationComparisons"].clear()
    with pytest.raises(ContractError, match="scope reservations"):
        build_resolution_preview(plan, body)


def test_work_retention_rejects_blocked_and_duplicate_scope(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    plan = _plan(memory)
    row = {"id": 1, "state": "blocked", "approval_id": None, "review_package_hash": None,
           "updated_ts": "v1", "candidateDecisionState": "no_owner_decision"}
    plan["inventory"]["initiatives"]["items"] = [row]
    ref = {"kind": "initiative", "id": 1, "revision": "v1", "recordHash": _hash(row)}
    body = {"type": "work_disposition", "operatorRequestId": "work-terminal-01",
        "expectedSnapshotHash": plan["snapshotHash"],
        "expectedEvidenceFingerprint": _inventory_fingerprint("work_disposition", plan, [ref]),
        "decision": "retain_history", "scope": [ref], "evidence": {"reason": "terminal"}}
    with pytest.raises(ContractError, match="only terminal"):
        build_resolution_preview(plan, body)


def test_work_receipt_fingerprint_is_scoped_and_partial_supersession_keeps_other_scope(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    plan = _plan(memory)
    rows = [
        {"id": 1, "state": "failed", "updated_ts": "v1"},
        {"id": 2, "state": "failed", "updated_ts": "v1"},
    ]
    plan["inventory"]["initiatives"]["items"] = rows
    memory.crawlseo_migration_snapshot = lambda: plan["inventory"]
    a_scope = [{"kind": "initiative", "id": row["id"], "revision": "v1", "recordHash": _hash(row)} for row in rows]
    a = {"type": "work_disposition", "operatorRequestId": "work-scope-a-001",
         "expectedSnapshotHash": plan["snapshotHash"], "expectedEvidenceFingerprint": _inventory_fingerprint("work_disposition", plan, a_scope),
         "decision": "retain_history", "scope": a_scope, "evidence": {"reason": "reviewed"}}
    result_a = apply_resolution(memory, plan, a)
    b_scope = [a_scope[0]]
    b = {**a, "operatorRequestId": "work-scope-b-001", "expectedEvidenceFingerprint": _inventory_fingerprint("work_disposition", plan, b_scope), "scope": b_scope}
    result_b = apply_resolution(memory, plan, b)
    assert memory.crawlseo_migration_current_receipt_ids() == {result_a["receipt"]["receiptId"], result_b["receipt"]["receiptId"]}
    plan["inventory"]["initiatives"]["items"][0] = {**rows[0], "state": "completed", "updated_ts": "v2"}
    status = resolution_status(plan, memory)
    by_id = {row["receipt"]["receiptId"]: row for row in status["items"]}
    assert by_id[result_a["receipt"]["receiptId"]]["current"] is True
    assert by_id[result_a["receipt"]["receiptId"]]["state"] == "valid"
    assert [ref["id"] for ref in by_id[result_a["receipt"]["receiptId"]]["currentScope"]] == [2]
    assert by_id[result_b["receipt"]["receiptId"]]["current"] is True
    assert by_id[result_b["receipt"]["receiptId"]]["state"] == "stale"


def test_apply_rechecks_local_inventory_inside_transaction(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    plan = _plan(memory)
    plan["crawlseo"]["actionSiteIdentityVerified"] = True
    plan["crawlseo"]["bindingSiteIdentityVerified"] = True
    original = memory.persist_crawlseo_migration_receipt

    def race(receipt, *, validate_snapshot=None):
        memory.conn.execute("INSERT INTO crawlseo_event_inbox(event_id,sequence,site_id,action_id,action_revision,event_type,payload_hash,disposition,reason,received_ts) VALUES('race',1,'site',NULL,NULL,'test','h','ignored','','now')")
        memory.conn.commit()
        return original(receipt, validate_snapshot=validate_snapshot)

    monkeypatch.setattr(memory, "persist_crawlseo_migration_receipt", race)
    local = {k: plan["inventory"].get(k) for k in ("initiatives", "ownerActions", "executionBindings", "connectorEvents")}
    remote = plan["crawlseo"]["actions"]
    body = {"type": "action_ledger_comparison", "operatorRequestId": "ledger-race-01",
        "expectedSnapshotHash": plan["snapshotHash"],
        "expectedEvidenceFingerprint": _inventory_fingerprint("action_ledger_comparison", plan),
        "decision": "compared", "evidence": {"cursorComplete": True, "actionsTruncated": False,
            "available": True, "remoteLedgerHash": _hash(remote), "localLedgerHash": _hash(local),
            "remoteActionDispositions": [], "comparisonHash": _hash({"remote": remote, "local": local, "dispositions": []}), "evidenceMode": "operator_attested"}}
    with pytest.raises(ContractError, match="inventory changed"):
        apply_resolution(memory, plan, body)

