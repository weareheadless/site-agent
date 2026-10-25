"""Hash-bound verification of immutable CrawlSEO legacy budget imports."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class AccountingVerificationError(ValueError):
    """An authoritative budget receipt does not exactly cover current local evidence."""


_SHA = re.compile(r"^[a-f0-9]{64}$")
_OPERATIONS = {
    "KEYWORD_OVERVIEW": "dataforseo:article_keyword_overview",
    "ORGANIC_SERP": "dataforseo:article_serp_snapshot",
}
_LOCAL_OPERATIONS = {
    "article_keyword_overview": "dataforseo:article_keyword_overview",
    "article_serp_snapshot": "dataforseo:article_serp_snapshot",
    "dataforseo:article_keyword_overview": "dataforseo:article_keyword_overview",
    "dataforseo:article_serp_snapshot": "dataforseo:article_serp_snapshot",
}
_TERMINAL = {"COMPLETED", "FAILED"}


def evidence_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def terminal_import_execution_resolved(imported: Mapping[str, Any] | None, local: Mapping[str, Any]) -> bool:
    """A mapped terminal task is drained; unresolved amounts remain held separately."""
    if not isinstance(imported, Mapping) or imported.get("sourceTaskStatus") not in _TERMINAL:
        return False
    if imported.get("effectiveStatus") not in {"UNCERTAIN", "SETTLED"}:
        return False
    try:
        if int(imported.get("quoteMicros")) != int(local.get("amount_micros")):
            return False
    except (TypeError, ValueError):
        return False
    if imported.get("effectiveStatus") == "UNCERTAIN":
        return imported.get("actualCostMicros") is None
    return imported.get("actualCostMicros") is not None


def local_accounting_fingerprint(plan: Mapping[str, Any]) -> str:
    inventory = plan.get("inventory") if isinstance(plan.get("inventory"), Mapping) else {}
    reservations = inventory.get("budgetReservations") if isinstance(inventory.get("budgetReservations"), Mapping) else {}
    ideas_box = inventory.get("articleIdeas") if isinstance(inventory.get("articleIdeas"), Mapping) else {}
    ideas = ideas_box.get("items") if isinstance(ideas_box.get("items"), list) else []
    linked_ideas = []
    for local in reservations.get("items", []) if isinstance(reservations.get("items"), list) else []:
        if not isinstance(local, Mapping):
            linked_ideas.append({"invalidReservation": True})
            continue
        normalized_operation = _LOCAL_OPERATIONS.get(str(local.get("operation") or ""))
        slot = "research_run_id" if normalized_operation == "dataforseo:article_keyword_overview" else "serp_run_id"
        reservation_key = "keyword_budget_reservation_id" if slot == "research_run_id" else "serp_budget_reservation_id"
        matches = [idea for idea in ideas if isinstance(idea, Mapping)
            and str(idea.get(reservation_key) or "") == str(local.get("reservation_id") or "")]
        linked_ideas.append({"reservationId": local.get("reservation_id"), "operation": normalized_operation,
            "matches": [{key: idea.get(key) for key in (
                "id", "keyword_budget_reservation_id", "research_run_id", "serp_budget_reservation_id", "serp_run_id",
            )} | ({"provider_task_id": idea.get("provider_task_id")} if slot == "research_run_id" else {})
                for idea in matches]})
    return evidence_hash({
        "siteId": plan.get("siteId"),
        "projectId": (plan.get("crawlseo") or {}).get("projectId") if isinstance(plan.get("crawlseo"), Mapping) else None,
        "binding": (plan.get("crawlseo") or {}).get("binding") if isinstance(plan.get("crawlseo"), Mapping) else None,
        "legacyPolicy": plan.get("legacyPolicy"),
        "budgetReservations": reservations,
        "articleIdeasTruncated": ideas_box.get("truncated"),
        "linkedArticleIdeas": linked_ideas,
    })


def _integer(value: Any, label: str, *, nullable: bool = False) -> int | None:
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,39})", str(value)):
        raise AccountingVerificationError(f"authoritative budget receipt has an invalid {label}")
    return int(value)


def _date(value: Any, label: str) -> dt.datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AccountingVerificationError(f"authoritative budget receipt has an invalid {label}")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AccountingVerificationError(f"authoritative budget receipt has an invalid {label}") from exc
    if parsed.tzinfo is None:
        raise AccountingVerificationError(f"authoritative budget receipt {label} lacks a timezone")
    return parsed.astimezone(dt.timezone.utc)


def _same_time(left: Any, right: Any, label: str) -> bool:
    try:
        return _date(left, label) == _date(right, label)
    except AccountingVerificationError:
        return False


def _reservation_task_link(local: Mapping[str, Any], ideas: list[Any]) -> tuple[str, str, Mapping[str, Any]]:
    reservation_id = str(local.get("reservation_id") or "")
    operation = _LOCAL_OPERATIONS.get(str(local.get("operation") or ""))
    if operation is None:
        raise AccountingVerificationError("local reservation operation is outside the legacy import contract")
    slot = "research_run_id" if operation == "dataforseo:article_keyword_overview" else "serp_run_id"
    idea_reservation = "keyword_budget_reservation_id" if slot == "research_run_id" else "serp_budget_reservation_id"
    matches = [idea for idea in ideas if isinstance(idea, Mapping)
        and str(idea.get(idea_reservation) or "") == reservation_id and str(idea.get(slot) or "")]
    if len(matches) != 1:
        raise AccountingVerificationError("local reservation does not map to one exact historical provider run")
    return str(matches[0][slot]), slot, matches[0]


def _check_local_row(row: Mapping[str, Any], local: Mapping[str, Any], plan: Mapping[str, Any], ideas: list[Any]) -> dict[str, Any]:
    source = row.get("sourceTask") if isinstance(row.get("sourceTask"), Mapping) else {}
    legacy = row.get("input") if isinstance(row.get("input"), Mapping) else {}
    effective = row.get("effective") if isinstance(row.get("effective"), Mapping) else {}
    local_id = str(local.get("reservation_id") or "")
    if not (local_id and legacy.get("localReservationId") == local_id):
        raise AccountingVerificationError("import row does not identify the exact local reservation")
    expected_task_id, slot, idea = _reservation_task_link(local, ideas)
    if legacy.get("taskId") != expected_task_id or source.get("id") != expected_task_id:
        raise AccountingVerificationError("import row does not identify the exact local provider run")
    normalized_operation = _LOCAL_OPERATIONS.get(str(local.get("operation") or ""))
    if (_OPERATIONS.get(str(source.get("kind"))) != normalized_operation
            or _LOCAL_OPERATIONS.get(str(legacy.get("operation") or "")) != normalized_operation):
        raise AccountingVerificationError("imported provider operation differs from the local reservation")

    amount = _integer(local.get("amount_micros"), "local quote")
    if (_integer(legacy.get("amountMicros"), "legacy quote") != amount
            or _integer(effective.get("amountMicros"), "effective quote") != amount):
        raise AccountingVerificationError("imported quote differs from the local reservation")
    currency = str(local.get("currency") or "").upper()
    if currency != "USD" or str(legacy.get("currency") or "").upper() != currency:
        raise AccountingVerificationError("imported currency differs from the supported local currency")
    if legacy.get("period") != local.get("period"):
        raise AccountingVerificationError("imported billing period differs from the local reservation")
    policy = plan.get("legacyPolicy") if isinstance(plan.get("legacyPolicy"), Mapping) else {}
    timezone = str(policy.get("timezone") or "")
    if not timezone or legacy.get("timeZone") != timezone:
        raise AccountingVerificationError("imported timezone differs from the current legacy policy")
    try:
        zone = ZoneInfo(timezone)
        created = _date(legacy.get("createdAt"), "legacy creation time")
        assert created is not None
        if created.astimezone(zone).strftime("%Y-%m") != str(local.get("period") or ""):
            raise AccountingVerificationError("local reservation period does not match its timezone")
    except (ZoneInfoNotFoundError, AssertionError) as exc:
        raise AccountingVerificationError("legacy policy timezone or reservation time is invalid") from exc
    for key, local_key in (("createdAt", "created_ts"), ("updatedAt", "updated_ts"), ("settledAt", "settled_ts")):
        if not _same_time(legacy.get(key), local.get(local_key), key):
            raise AccountingVerificationError(f"imported {key} differs from the local reservation")
    local_status = str(local.get("status") or "").lower()
    if legacy.get("legacyStatus") != local_status:
        raise AccountingVerificationError("imported legacy status differs from the local reservation")
    status = str(effective.get("status") or "")
    if status not in {"SETTLED", "UNCERTAIN"}:
        raise AccountingVerificationError("authoritative import row has an unsupported effective status")
    source_status = str(source.get("status") or "").upper()
    if source_status not in _TERMINAL:
        raise AccountingVerificationError("import receipt includes a nonterminal provider task")
    cost = _integer(source.get("costMicros"), "source task cost", nullable=True)
    actual = _integer(effective.get("actualCostMicros"), "effective actual cost", nullable=True)
    local_actual = _integer(local.get("recorded_actual_cost_micros"), "local actual cost", nullable=True)
    if local_actual is not None and local_actual != actual:
        raise AccountingVerificationError("authoritative source cost differs from the local recorded cost")
    if cost is not None and status != "SETTLED":
        raise AccountingVerificationError("source task cost receipt was not imported as settled actual spend")
    if status == "SETTLED":
        if source_status not in _TERMINAL or cost is None or actual != cost:
            raise AccountingVerificationError("settled import is missing its terminal source cost receipt")
    elif actual is not None:
        raise AccountingVerificationError("non-settled import must not claim an actual cost")
    if (not _same_time(effective.get("createdAt"), legacy.get("createdAt"), "effective creation time")
            or not _same_time(effective.get("updatedAt"), legacy.get("updatedAt"), "effective update time")):
        raise AccountingVerificationError("effective ledger timestamps differ from the imported legacy row")
    if status == "SETTLED":
        expected_settled = legacy.get("settledAt") or source.get("completedAt") or legacy.get("createdAt")
        if not _same_time(effective.get("settledAt"), expected_settled, "effective settlement time"):
            raise AccountingVerificationError("effective settlement time differs from its source evidence")
    elif effective.get("settledAt") is not None:
        raise AccountingVerificationError("non-settled import must not claim a settlement time")
    if status == "UNCERTAIN" and _integer(effective.get("amountMicros"), "held quote") != amount:
        raise AccountingVerificationError("uncertain import does not preserve the full local quote")
    source_site = str(plan.get("_receiptSourceSiteId") or "")
    source_project = str(plan.get("_receiptSourceProjectId") or "")
    if not source_site or source.get("siteId") != source_site or source.get("projectId") != source_project:
        raise AccountingVerificationError("source provider task is outside the receipt's exact source binding")
    provider_task_id = source.get("providerTaskId")
    if local.get("provider_task_id") != expected_task_id:
        raise AccountingVerificationError("local reservation does not point at its exact CrawlSEO source run")
    idea_provider_task_id = idea.get("provider_task_id")
    if slot == "research_run_id" and provider_task_id and idea_provider_task_id and provider_task_id != idea_provider_task_id:
        raise AccountingVerificationError("source provider receipt identity differs from the local research record")
    return {
        "localReservationId": local_id,
        "taskId": expected_task_id,
        "runSlot": slot,
        "operation": normalized_operation,
        "quoteMicros": str(amount),
        "currency": currency,
        "period": local.get("period"),
        "timeZone": timezone,
        "localStatus": local_status,
        "effectiveStatus": status,
        "actualCostMicros": str(actual) if actual is not None else None,
        "providerTaskId": provider_task_id,
        "sourceTaskStatus": source_status,
        "sourceTaskAttemptedAt": source.get("attemptedAt"),
        "sourceTaskCompletedAt": source.get("completedAt"),
        "createdAt": legacy.get("createdAt"),
        "updatedAt": legacy.get("updatedAt"),
        "settledAt": effective.get("settledAt"),
    }


def verify_import_receipt(receipt: Mapping[str, Any], plan: Mapping[str, Any], operator_request_id: str) -> dict[str, Any]:
    """Validate the host-fetched immutable receipt against every current local row."""
    receipt_id = str(receipt.get("id") or "")
    snapshot = receipt.get("snapshot") if isinstance(receipt.get("snapshot"), Mapping) else {}
    source = snapshot.get("source") if isinstance(snapshot.get("source"), Mapping) else {}
    target = snapshot.get("target") if isinstance(snapshot.get("target"), Mapping) else {}
    rows = snapshot.get("rows")
    inventory = plan.get("inventory") if isinstance(plan.get("inventory"), Mapping) else {}
    reservations = inventory.get("budgetReservations") if isinstance(inventory.get("budgetReservations"), Mapping) else {}
    ideas_box = inventory.get("articleIdeas") if isinstance(inventory.get("articleIdeas"), Mapping) else {}
    local_rows = reservations.get("items") if isinstance(reservations.get("items"), list) else []
    ideas = ideas_box.get("items") if isinstance(ideas_box.get("items"), list) else []
    crawlseo = plan.get("crawlseo") if isinstance(plan.get("crawlseo"), Mapping) else {}
    binding = crawlseo.get("binding") if isinstance(crawlseo.get("binding"), Mapping) else {}
    binding_generation = binding.get("generation")
    target_site = str(plan.get("siteId") or "")
    target_project = str(crawlseo.get("projectId") or "")
    if (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", receipt_id)
            or receipt.get("targetSiteId") != target_site or receipt.get("targetProjectId") != target_project
            or target.get("siteId") != target_site or target.get("projectId") != target_project
            or str(target.get("bindingExecutor") or "").lower() != "helloada"
            or str(target.get("bindingStatus") or "").upper() != "ACTIVE"
            or isinstance(binding_generation, bool) or not isinstance(binding_generation, int) or binding_generation < 1
            or target.get("bindingGeneration") != binding.get("generation")
            or receipt.get("sourceSiteId") != source.get("siteId")
            or receipt.get("sourceProjectId") != source.get("projectId")
            or receipt.get("sourceSiteId") == target_site or receipt.get("sourceProjectId") == target_project
            or str(source.get("currency") or "").upper() != "USD"
            or str(target.get("currency") or "").upper() != "USD"
            or isinstance(target.get("bindingGeneration"), bool)
            or not isinstance(target.get("bindingGeneration"), int)
            or not isinstance(receipt.get("sourceEvidenceHash"), str)
            or not _SHA.fullmatch(str(receipt.get("sourceEvidenceHash")))):
        raise AccountingVerificationError("authoritative receipt source/target identities do not match the current migration plan")
    if (reservations.get("truncated") is not False or ideas_box.get("truncated") is not False
            or not isinstance(rows, list) or len(rows) != len(local_rows) or len(rows) > 100):
        raise AccountingVerificationError("authoritative receipt does not cover a complete bounded local budget inventory")
    by_id = {str(row.get("reservation_id") or ""): row for row in local_rows if isinstance(row, Mapping)}
    if len(by_id) != len(local_rows) or set(by_id) != {
        str(row.get("input", {}).get("localReservationId") or "")
        for row in rows if isinstance(row, Mapping) and isinstance(row.get("input"), Mapping)
    }:
        raise AccountingVerificationError("authoritative import receipt does not exactly cover local reservations")
    input_rows = [row.get("input") for row in rows if isinstance(row, Mapping) and isinstance(row.get("input"), Mapping)]
    if (len(input_rows) != len(rows)
            or len({str(row.get("localReservationId")) for row in input_rows}) != len(rows)
            or len({str(row.get("taskId")) for row in input_rows}) != len(rows)):
        raise AccountingVerificationError("authoritative import rows reuse a local reservation or source task")

    row_projection = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise AccountingVerificationError("authoritative import receipt contains an invalid row")
        local_id = str((row.get("input") or {}).get("localReservationId") or "")
        row_projection.append(_check_local_row(row, by_id[local_id], plan | {
            "_receiptSourceSiteId": source.get("siteId"),
            "_receiptSourceProjectId": source.get("projectId"),
        }, ideas))
    row_projection.sort(key=lambda row: row["localReservationId"])
    known_spend = sum(int(row["actualCostMicros"]) for row in row_projection if row["effectiveStatus"] == "SETTLED")
    held_unknown = sum(int(row["quoteMicros"]) for row in row_projection
        if row["effectiveStatus"] in {"UNCERTAIN", "RESERVED"})
    receipt_hash = evidence_hash(dict(receipt))
    return {
        "receiptId": "sha256:" + hashlib.sha256((operator_request_id + receipt_id + receipt_hash).encode()).hexdigest(),
        "siteId": target_site,
        "projectId": target_project,
        "remoteReceiptId": receipt_id,
        "operatorRequestId": operator_request_id,
        "state": "verified",
        "decision": "authoritative_budget_import_verified",
        "sourceProjectId": str(source.get("projectId")),
        "sourceSiteId": str(source.get("siteId")),
        "targetProjectId": target_project,
        "targetSiteId": target_site,
        "bindingGeneration": binding.get("generation"),
        "sourceEvidenceHash": receipt.get("sourceEvidenceHash"),
        "remoteReceiptHash": receipt_hash,
        "localAccountingFingerprint": local_accounting_fingerprint(plan),
        "localRowCount": len(row_projection),
        "knownSpendMicros": str(known_spend),
        "heldUnknownMicros": str(held_unknown),
        "rows": row_projection,
    }


def current_import_receipt(memory: Any, plan: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return only the current verified import whose exact local inventory still matches."""
    try:
        pointers = memory.crawlseo_migration_current_receipts()
        receipt_id = pointers.get("crawlseo_legacy_budget_import")
        row = next((item for item in memory.crawlseo_migration_receipts()
            if isinstance(item, Mapping) and item.get("receiptId") == receipt_id
            and item.get("type") == "crawlseo_legacy_budget_import" and item.get("state") == "verified"), None)
        if (row is None or row.get("localAccountingFingerprint") != local_accounting_fingerprint(plan)
                or row.get("siteId") != plan.get("siteId")
                or row.get("projectId") != (plan.get("crawlseo") or {}).get("projectId")
                or row.get("bindingGeneration") != ((plan.get("crawlseo") or {}).get("binding") or {}).get("generation")):
            return None
        return dict(row)
    except Exception:
        return None


def imported_row_for_reservation(memory: Any, plan: Mapping[str, Any], reservation: Mapping[str, Any]) -> dict[str, Any] | None:
    """Current verified import row for a reservation; exposed for activation/freeze gates."""
    current = current_import_receipt(memory, plan)
    if not current:
        return None
    reservation_id = str(reservation.get("reservation_id") or "")
    row = next((item for item in current.get("rows", []) if isinstance(item, Mapping)
        and item.get("localReservationId") == reservation_id), None)
    return dict(row) if row else None
