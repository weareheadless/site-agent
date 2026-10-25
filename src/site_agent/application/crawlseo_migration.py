"""Guarded, durable operator evidence for CrawlSEO migration review.

Receipts document scoped decisions. They never set migration gates to passed.
"""
from __future__ import annotations

import hashlib
import json
import re
import datetime as dt
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping
from typing import Any

from ..core.contracts import ContractError

SUPPORTED_TYPES = {
    "work_disposition", "budget_reconciliation", "canonical_routes_verification",
    "action_ledger_comparison", "owner_fact_disposition",
}
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_WORK_CATEGORIES = {"initiative": "initiatives", "articleIdea": "articleIdeas", "seoResearchRequest": "seoResearchRequests", "seoSiteReport": "seoSiteReports", "ownerAction": "ownerActions", "activeJob": "activeJobs", "draft": "drafts", "growthRun": "growthRuns", "executionBinding": "executionBindings"}


def _scope_row(inv: Mapping[str, Any], ref: Mapping[str, Any]) -> Mapping[str, Any] | None:
    category = _WORK_CATEGORIES.get(str(ref.get("kind")))
    rows = (inv.get(category) or {}).get("items", []) if category else []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if ref.get("kind") == "executionBinding":
            identity = f"{row.get('site_id')}:{row.get('action_id')}:{row.get('action_revision')}"
        else:
            identity = str(row.get("id", row.get("run_id", row.get("action_id"))))
        if identity == str(ref.get("id")):
            return row
    return None


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def evidence_hash(value: Any) -> str:
    """Public canonical digest used for hash-bound operator evidence."""
    return _hash(value)


def _inventory_fingerprint(kind: str, plan: Mapping[str, Any], scope: Any = None) -> str:
    inv = plan.get("inventory") if isinstance(plan.get("inventory"), Mapping) else {}
    if kind == "work_disposition":
        value = []
        for ref in scope if isinstance(scope, list) else []:
            row = _scope_row(inv, ref) if isinstance(ref, Mapping) else None
            value.append({"ref": dict(ref), "record": row})
    elif kind == "budget_reconciliation":
        value = {"budgetReservations": inv.get("budgetReservations"), "providerReceipts": inv.get("providerReceipts"), "remoteBudget": (plan.get("crawlseo") or {}).get("budget")}
    elif kind == "canonical_routes_verification":
        value = {"siteId": plan.get("siteId"), "tenant": plan.get("tenant"), "crawlseoBinding": (plan.get("crawlseo") or {}).get("binding")}
    elif kind == "action_ledger_comparison":
        value = {"siteId": plan.get("siteId"), "local": {k: inv.get(k) for k in ("initiatives", "ownerActions", "executionBindings", "connectorEvents")}, "actions": (plan.get("crawlseo") or {}).get("actions"), "budget": (plan.get("crawlseo") or {}).get("budget")}
    else:
        value = (inv.get("issue330References") or {}).get("ownerFactConversation")
        initiatives = (inv.get("issue330References") or {}).get("initiatives")
        value = {"ownerFactConversation": value, "initiative4": (initiatives or {}).get("4")}
    return _hash(value)


def _validate(body: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    kind = body.get("type")
    request_id = body.get("operatorRequestId")
    if kind not in SUPPORTED_TYPES:
        raise ContractError("unsupported migration resolution type")
    if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
        raise ContractError("operatorRequestId must be a stable 8-128 character identifier")
    if (body.get("expectedSnapshotHash") != plan.get("snapshotHash")
            or not isinstance(plan.get("snapshotHash"), str) or not _SHA256.fullmatch(plan["snapshotHash"])):
        raise ContractError("expected snapshot hash does not match the supplied migration plan")
    evidence = body.get("evidence")
    if not isinstance(evidence, Mapping) or not evidence:
        raise ContractError("typed proof evidence is required")
    fingerprint = _inventory_fingerprint(kind, plan, body.get("scope"))
    if body.get("expectedEvidenceFingerprint") != fingerprint:
        raise ContractError("resolution evidence fingerprint is stale")
    # Decisions are constrained to the narrow operations whose semantics are safe.
    decision = body.get("decision")
    allowed = {
        "work_disposition": {"retain_history", "quarantine", "preserve_execution", "defer"},
        "budget_reconciliation": {"reconciled_evidence"},
        "canonical_routes_verification": {"verified"},
        "action_ledger_comparison": {"compared"},
        "owner_fact_disposition": {"quarantine_defer", "replacement_reference"},
    }[kind]
    if decision not in allowed:
        raise ContractError("unsupported decision for migration resolution type")
    if kind == "work_disposition":
        scope = body.get("scope")
        if not isinstance(scope, list) or not scope:
            raise ContractError("work disposition requires explicit record scope")
        for ref in scope:
            if not isinstance(ref, Mapping) or ref.get("kind") not in _WORK_CATEGORIES:
                raise ContractError("work scope contains an unsupported record")
            row = _scope_row(plan.get("inventory") or {}, ref)
            revision = row.get("updated_ts") if row else None
            if ref["kind"] == "executionBinding" and row:
                revision = f"{row.get('generation')}:{row.get('state')}:{row.get('updated_ts')}"
            if row is None or ref.get("recordHash") != _hash(row) or ref.get("revision") != revision:
                raise ContractError("work disposition record scope or revision is stale")
            has_owner_decision = bool(row.get("approval_id") or row.get("review_package_hash") or row.get("candidateDecisionState") == "exact")
            if has_owner_decision and decision != "preserve_execution":
                raise ContractError("work with an owner decision or exact review must preserve its approval")
            state = row.get("status", row.get("state", ""))
            if decision == "retain_history" and state not in {"completed", "partial", "failed", "drafted", "held", "rejected", "superseded", "archived", "cancelled"}:
                raise ContractError("only terminal work can be retained as history")
            if decision in {"defer", "quarantine"} and state not in {"preparing", "selected", "queued", "pending", "blocked", "failed", "held"}:
                raise ContractError("defer or quarantine is limited to nonexecuting preparation work")
            if decision == "preserve_execution" and not has_owner_decision:
                raise ContractError("preserve_execution requires an existing owner decision or exact review")
    if kind == "budget_reconciliation":
        if (not all(k in evidence for k in ("reconciliationId", "reservationComparisons", "sourceHash", "remoteBudgetSnapshot"))
                or evidence.get("evidenceMode") != "operator_attested"):
            raise ContractError("budget reconciliation must be explicitly operator-attested and bind source and current remote budget")
        if evidence.get("sourceHash") not in {body.get("expectedSnapshotHash"), body.get("expectedEvidenceFingerprint")}:
            raise ContractError("budget reconciliation source hash does not bind the current snapshot")
        budget = (plan.get("crawlseo") or {}).get("budget")
        if (plan.get("crawlseo") or {}).get("budgetSiteIdentityVerified") is not True:
            raise ContractError("budget evidence must be bound to the authorized site identity")
        if evidence.get("remoteBudgetSnapshot") != budget:
            raise ContractError("remote budget evidence conflicts with the current CrawlSEO budget snapshot")
        comparisons = evidence.get("reservationComparisons", [])
        if not isinstance(comparisons, list) or not comparisons:
            raise ContractError("budget reconciliation must scope reservations")
        known = {str(r.get("reservation_id")): r for r in ((plan.get("inventory") or {}).get("budgetReservations") or {}).get("items", [])}
        if len(comparisons) != len(known) or {str(x.get("reservationId")) for x in comparisons if isinstance(x, Mapping)} != set(known):
            raise ContractError("budget reconciliation must compare every local reservation exactly once")
        for item in comparisons:
            row = known.get(str(item.get("reservationId"))) if isinstance(item, Mapping) else None
            if row is None or item.get("recordHash") != _hash(row) or item.get("revision") != row.get("updated_ts"):
                raise ContractError("budget comparison record scope or revision is stale")
            actual = item.get("reconciledActualCostMicros")
            if item.get("taskId") != row.get("provider_task_id") or item.get("period") != row.get("period") or item.get("currency") != row.get("currency"):
                raise ContractError("budget comparison task, period or currency does not match the reservation")
            if not isinstance(item.get("receiptId"), str) or not item["receiptId"] or not isinstance(item.get("receiptHash"), str) or not _SHA256.fullmatch(item["receiptHash"]):
                raise ContractError("each budget reconciliation requires a hash-bound provider receipt reference")
            try:
                amount = Decimal(str(actual))
            except (InvalidOperation, TypeError):
                amount = Decimal("-1")
            if not amount.is_finite() or amount < 0 or not re.fullmatch(r"(?:0|[1-9][0-9]*)", str(actual)):
                raise ContractError("reconciled actual cost must be a nonnegative integer decimal")
            receipt_payload = {key: item.get(key) for key in ("receiptId", "reservationId", "taskId", "period", "currency", "reconciledActualCostMicros")}
            receipt_payload["sourceHash"] = evidence.get("sourceHash")
            if item.get("receiptHash") != _hash(receipt_payload):
                raise ContractError("provider receipt hash does not match its scoped reconciliation evidence")
            stored_actual = row.get("recorded_actual_cost_micros")
            if stored_actual is not None and str(actual) != str(stored_actual):
                raise ContractError("reconciled actual cost conflicts with the stored receipt")
    if kind == "canonical_routes_verification":
        if not all(k in evidence for k in ("robotsTxtHash", "sitemapHash", "canonicalSiteId", "checkedAt")):
            raise ContractError("route verification requires exact robots, sitemap and canonical-site evidence")
        if not _SHA256.fullmatch(str(evidence.get("robotsTxtHash"))) or not _SHA256.fullmatch(str(evidence.get("sitemapHash"))):
            raise ContractError("robots and sitemap evidence must use SHA-256 digests")
        if evidence.get("canonicalSiteId") != plan.get("siteId"):
            raise ContractError("canonical site id does not match the bound tenant")
        try:
            checked = dt.datetime.fromisoformat(str(evidence.get("checkedAt")).replace("Z", "+00:00"))
            now = dt.datetime.now(dt.timezone.utc)
            if checked.tzinfo is None or checked > now + dt.timedelta(minutes=5) or now - checked > dt.timedelta(hours=1):
                raise ValueError
        except ValueError as exc:
            raise ContractError("route evidence checkedAt must be recent ISO time and not in the future") from exc
        if evidence.get("evidenceMode") != "operator_attested":
            raise ContractError("route evidence must be labelled operator_attested; route origin verification belongs to the caller")
    if kind == "action_ledger_comparison":
        if evidence.get("cursorComplete") is not True or evidence.get("actionsTruncated") is not False or evidence.get("available") is not True:
            raise ContractError("Action ledger comparison requires an available, complete, untruncated inventory")
        crawlseo = plan.get("crawlseo") or {}
        if not (crawlseo.get("actionSiteIdentityVerified") is True and crawlseo.get("bindingSiteIdentityVerified") is True):
            raise ContractError("Action and binding evidence must be bound to the authorized site identity")
        remote = crawlseo.get("actions", [])
        if any(not isinstance(row, Mapping) or row.get("evidenceComplete") is not True
                or row.get("invalidEvidenceReferenceCount") != 0 or row.get("unavailableEvidenceSourceCount") != 0
                or not _SHA256.fullmatch(str(row.get("envelopeHash", ""))) for row in remote):
            raise ContractError("each remote Action requires a complete hash-bound evidence envelope")
        local = {k: (plan.get("inventory") or {}).get(k) for k in ("initiatives", "ownerActions", "executionBindings", "connectorEvents")}
        action_dispositions = evidence.get("remoteActionDispositions")
        if not isinstance(action_dispositions, list) or len(action_dispositions) != len(remote):
            raise ContractError("every remote Action must receive one exact review disposition")
        by_id = {str(row.get("id")): row for row in remote if isinstance(row, Mapping)}
        seen: set[str] = set()
        for item in action_dispositions:
            if not isinstance(item, Mapping):
                raise ContractError("remote Action disposition is invalid")
            action_id = str(item.get("actionId"))
            row = by_id.get(action_id)
            if (row is None or action_id in seen or item.get("revision") != row.get("revision")
                    or item.get("envelopeHash") != row.get("envelopeHash")
                    or item.get("decision") not in {"accept_pending_projection", "retain_remote_history", "covered_by_local_mapping"}):
                raise ContractError("remote Action disposition does not bind one exact Action revision and envelope")
            if item.get("decision") == "accept_pending_projection" and row.get("executionStatus") != "not_started":
                raise ContractError("only a not-started Action may be accepted as a pending projection")
            seen.add(action_id)
        if seen != set(by_id):
            raise ContractError("remote Action disposition ledger is incomplete")
        if evidence.get("remoteLedgerHash") != _hash(remote) or evidence.get("localLedgerHash") != _hash(local):
            raise ContractError("Action ledger hashes do not match the current plan arrays")
        if evidence.get("comparisonHash") != _hash({"remote": remote, "local": local, "dispositions": action_dispositions}):
            raise ContractError("Action ledger comparison hash is invalid")
        if evidence.get("evidenceMode") != "operator_attested":
            raise ContractError("ledger comparison must be labelled operator_attested")
    if kind == "owner_fact_disposition":
        refs = (plan.get("inventory") or {}).get("issue330References") or {}
        fact = refs.get("ownerFactConversation")
        initiative4 = (refs.get("initiatives") or {}).get("4")
        if not isinstance(fact, Mapping) or not isinstance(initiative4, Mapping):
            raise ContractError("owner fact disposition requires the current fact and initiative snapshot")
        if (evidence.get("factRecordHash") != _hash(fact)
                or evidence.get("factRevision") != fact.get("updated_ts")
                or evidence.get("initiativeRecordHash") != _hash(initiative4)
                or evidence.get("initiativeRevision") != initiative4.get("updated_ts")):
            raise ContractError("owner fact or initiative scope/revision is stale")
        if decision == "quarantine_defer":
            if (not fact.get("deleted") or evidence.get("initiativeId") != 4
                    or evidence.get("conversationId") != 4 or evidence.get("deletedFactRestored") is not False):
                raise ContractError("deleted owner fact may only be quarantined and deferred without restoration")
        else:
            confirmation = fact.get("confirmation")
            if (fact.get("deleted") or fact.get("relationshipState") != "confirmed"
                    or not isinstance(confirmation, Mapping)
                    or evidence.get("replacementConversationId") != fact.get("id")
                    or evidence.get("replacementCreatedAt") != fact.get("created_ts")
                    or evidence.get("replacementMessageHash") != confirmation.get("conversationMessageHash")
                    or evidence.get("confirmationEvidence") != confirmation):
                raise ContractError("replacement owner fact must reference the existing exact confirmation evidence")
    current_keys = ([f"{kind}:{ref.get('kind')}:{ref.get('id')}" for ref in body.get("scope", [])]
                    if kind == "work_disposition" else [kind])
    return {"type": kind, "operatorRequestId": request_id, "expectedSnapshotHash": plan["snapshotHash"],
            "evidenceFingerprint": fingerprint, "decision": decision, "scope": body.get("scope", []),
            "evidence": dict(evidence), "evidenceState": "operator_attested", "currentKeys": current_keys}


def build_resolution_preview(plan: Mapping[str, Any], body: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate(body, plan)
    return {"valid": True, "wouldAppend": True, "resolution": normalized,
            "notice": "This receipt records scoped operator evidence; it does not mark any migration gate passed."}


def resolution_requirements(plan: Mapping[str, Any], resolution_type: str, scope: Any = None) -> dict[str, Any]:
    """Return the exact plan binding an operator must echo in a resolution request."""
    if resolution_type not in SUPPORTED_TYPES:
        raise ContractError("unsupported migration resolution type")
    return {"expectedSnapshotHash": plan.get("snapshotHash"),
            "expectedEvidenceFingerprint": _inventory_fingerprint(resolution_type, plan, scope),
            "requiredEvidenceType": resolution_type}


def apply_resolution(memory: Any, plan: Mapping[str, Any], body: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate(body, plan)
    live = memory.crawlseo_migration_snapshot()
    live_plan = dict(plan, inventory=live)
    if _inventory_fingerprint(normalized["type"], live_plan, normalized.get("scope")) != normalized["evidenceFingerprint"]:
        raise ContractError("migration inventory changed after preview; resolution is stale")
    normalized["receiptId"] = "sha256:" + hashlib.sha256((normalized["operatorRequestId"] + _hash(normalized)).encode()).hexdigest()
    def still_current(live_inventory: Mapping[str, Any]) -> bool:
        return _inventory_fingerprint(normalized["type"], dict(plan, inventory=live_inventory), normalized.get("scope")) == normalized["evidenceFingerprint"]

    stored, idempotent = memory.persist_crawlseo_migration_receipt(normalized, validate_snapshot=still_current)
    return {"receipt": stored, "idempotent": idempotent, "gatePassed": False}


def resolution_status(plan: Mapping[str, Any], memory: Any) -> dict[str, Any]:
    current = memory.crawlseo_migration_snapshot()
    result = []
    current_receipts = memory.crawlseo_migration_current_receipts()
    for receipt in memory.crawlseo_migration_receipts():
        p = dict(plan, inventory=current)
        current_scope = None
        if receipt.get("type") == "work_disposition":
            active_keys = [f"work_disposition:{ref.get('kind')}:{ref.get('id')}" for ref in receipt.get("scope", [])
                if isinstance(ref, Mapping) and current_receipts.get(f"work_disposition:{ref.get('kind')}:{ref.get('id')}") == receipt.get("receiptId")]
            active_refs = [ref for ref in receipt.get("scope", []) if isinstance(ref, Mapping)
                and f"work_disposition:{ref.get('kind')}:{ref.get('id')}" in active_keys]
            current_scope = active_refs
            # Each ref carries its immutable record hash; a superseded ref is excluded
            # from validation so it cannot stale the still-current remainder.
            valid = bool(active_refs) and all(_scope_row(current, ref) is not None
                and _hash(_scope_row(current, ref)) == ref.get("recordHash") for ref in active_refs)
        else:
            current_fp = _inventory_fingerprint(receipt.get("type", ""), p) if receipt.get("type") in SUPPORTED_TYPES else None
            valid = current_fp == receipt.get("evidenceFingerprint")
        result.append({"receipt": receipt, "state": "valid" if valid else "stale",
                       "currentScope": current_scope if current_scope is not None else receipt.get("scope", [])})
    for item in result:
        item["current"] = item["receipt"].get("receiptId") in set(current_receipts.values())
    return {"items": result, "gatePassed": False, "evidenceState": "operator_attested"}
