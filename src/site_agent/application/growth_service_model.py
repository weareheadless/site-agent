"""Business-level read projection; existing Growth records remain authoritative."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import re
from typing import Any
from ..core.growth_contracts import GROWTH_AREAS as AREAS

SERVICE_MODEL_VERSION = "growth-service-v1"


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _refs(task: Mapping[str, Any]) -> dict[str, Any]:
    return {key: task[key] for key in (
        "id", "draftId", "ownerActionId", "approvalId", "reviewPackageHash", "conversationId",
    ) if task.get(key) is not None}


def _results(tasks, by_id, now):
    """Publication proofs and observations are different facts, not success labels."""
    results = []
    for task in tasks:
        initiative = by_id.get(str(task.get("id")), {})
        validation = initiative.get("validation") or {}
        verification = validation.get("liveVerification") or {}
        checks = verification.get("checks") if isinstance(verification, Mapping) else None
        payload_verified = verification.get("status") == "passed" and isinstance(checks, list) and bool(checks) and all(
            isinstance(check, Mapping) and isinstance(check.get("status"), int) and 200 <= check["status"] < 300
            and check.get("documentId") and check.get("updatedAt") and _date(check.get("verifiedAt")) for check in checks
        )
        source_verified = (verification.get("verified") is True and verification.get("releaseId")
                           and re.fullmatch(r"[0-9a-f]{40}", str(verification.get("commit") or "")))
        if (not initiative.get("published_revision") or validation.get("status") != "passed"
                or not isinstance(verification, Mapping)
                or not (payload_verified or source_verified)):
            continue
        observations = task.get("outcomes") or []
        measured = {row.get("horizon_days") for row in observations}
        due = [(horizon, initiative.get(f"review_{horizon}_ts")) for horizon in (30, 90, 180)
               if horizon not in measured and _date(initiative.get(f"review_{horizon}_ts"))]
        impact = [{
            "id": row.get("id"), "horizonDays": row.get("horizon_days"),
            "measuredAt": row.get("measured_ts"), "assessment": row.get("assessment"),
            "confidence": row.get("confidence"), "metric": (row.get("baseline") or {}).get("metric"),
            "baseline": (row.get("baseline") or {}).get("value"),
            "observed": (row.get("observed") or {}).get("value"),
            "notes": str(row.get("notes") or "")[:500], "causalAttribution": False,
        } for row in observations]
        results.append({
            **_refs(task), "title": task.get("title"), "state": "verified",
            "publishedRevision": initiative["published_revision"],
            "releaseId": verification.get("releaseId"), "sourceSha": verification.get("commit"),
            "implementedAt": (initiative.get("expected") or {}).get("implemented_ts"),
            "impactState": "observed" if impact else "awaiting_data", "impact": impact,
            "nextMeasurement": {"horizonDays": due[0][0], "at": due[0][1],
                "state": "scheduled" if _date(due[0][1]) > now else "overdue"} if due else None,
        })
    return sorted(results, key=lambda row: str(row.get("implementedAt") or ""), reverse=True)[:8]


def service_model(
    *, tasks: Sequence[Mapping[str, Any]], initiatives: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]], sources: Sequence[Mapping[str, Any]],
    activities: Sequence[Mapping[str, Any]], website_present: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Never collect evidence, start jobs, infer approval, or manufacture coverage."""
    now = now or datetime.now(timezone.utc)
    by_id = {f"initiative:{row['id']}": row for row in initiatives}
    # Existing task views intentionally omit internal deferrals. The service
    # view must still explain them without turning them into owner decisions.
    represented = {str(task.get("id")) for task in tasks}
    projected_tasks = [*tasks, *({
        "id": f"initiative:{row['id']}", "title": row.get("title"),
        "kind": row.get("kind"), "focus": "deferred", "state": row["state"],
        "updatedAt": row.get("updated_ts"),
    } for row in initiatives if row.get("state") == "deferred" and f"initiative:{row['id']}" not in represented)]
    work = []
    for task in projected_tasks:
        if task.get("kind") in {"schedule", "measurement"}:
            continue
        initiative = by_id.get(str(task.get("id")), {})
        expected = initiative.get("expected") or {}
        opportunity = expected.get("opportunity") or {}
        validation = initiative.get("validation") or {}
        primary = opportunity.get("primaryArea")
        # Articles have an intrinsic content scope. Unclassified historical work
        # remains explicitly unassigned, never classified by title keywords.
        if primary is None and task.get("kind") == "article":
            primary = "content"
        primary = primary if primary in AREAS else None
        secondary = [area for area in opportunity.get("secondaryAreas", []) if area in AREAS and area != primary]
        state = "awaiting_owner" if task.get("focus") == "needs_you" else str(task.get("focus") or "unresolved")
        if state == "awaiting_owner" and not task.get("canApprove") and not task.get("ownerActionId"):
            state = "unresolved"
        work.append({
            **_refs(task), "primaryArea": primary, "secondaryAreas": list(dict.fromkeys(secondary)),
            "title": task.get("title"), "why": initiative.get("rationale") or opportunity.get("why") or task.get("summary"),
            "scope": task.get("scope"), "state": state, "executionState": task.get("state"),
            "actor": "owner" if state == "awaiting_owner" else "platform" if task.get("executionIssue") else "ada",
            "canApprove": state == "awaiting_owner" and task.get("canApprove") is True,
            "evidenceRefs": initiative.get("evidence") or opportunity.get("evidence") or [],
            "updatedAt": task.get("updatedAt"), "nextRun": task.get("nextRun"),
            "executionIssue": task.get("executionIssue") is True,
            "dispositionReason": validation.get("reason"), "reassessWhen": validation.get("reassessWhen"),
        })
    unique = {str(row["id"]): row for row in work}
    work = list(unique.values())
    decision_ids = [row["id"] for row in work if row["state"] == "awaiting_owner"]
    assessments = sorted(
        (row for row in runs if isinstance((row.get("detail") or {}).get("assessment"), Mapping)
         and _date((row.get("detail") or {}).get("assessmentCompletedAt"))),
        key=lambda row: _date(row["detail"]["assessmentCompletedAt"]), reverse=True,
    )
    latest = assessments[0] if assessments else None
    assessment = (latest.get("detail") or {}).get("assessment") if latest else {}
    coverage = {row["area"]: row for row in assessment.get("coverage", []) if isinstance(row, Mapping) and row.get("area") in AREAS}
    schedules = [row for row in activities if row.get("enabled") and row.get("id") in {"growth_initial", "growth_weekly"} and _date(row.get("nextRun"))]
    schedules.sort(key=lambda row: _date(row["nextRun"]))
    upcoming = next((row for row in schedules if _date(row["nextRun"]) > now), None)
    overdue = [row["id"] for row in schedules if _date(row["nextRun"]) <= now]
    source_states = {
        str(ref): row.get("state")
        for row in sources for ref in (row.get("id"), row.get("sourceRef")) if ref
    }
    areas = []
    for area in AREAS:
        items = [row for row in work if row["primaryArea"] == area or area in row["secondaryAreas"]]
        recorded = coverage.get(area)
        decisions = [row["id"] for row in items if row["state"] == "awaiting_owner"]
        blocked = [row["id"] for row in items if row["executionIssue"]]
        active = [row["id"] for row in items if row["state"] == "preparing"]
        deferred = [row["id"] for row in items if row["state"] == "deferred"]
        evidence_states = [source_states[ref] for ref in recorded.get("evidence", []) if ref in source_states] if recorded else []
        evidence_state = (
            "unavailable" if any(value not in {"ready", "stale"} for value in evidence_states)
            else "stale" if "stale" in evidence_states else "recorded" if recorded else "not_assessed"
        )
        state = "awaiting_activation" if not website_present else "needs_decision" if decisions else "blocked" if blocked else "preparing" if active else "deferred" if deferred else evidence_state if evidence_state in {"stale", "unavailable"} else "assessed" if recorded else "not_assessed"
        areas.append({
            "id": area, "state": state, "workIds": [row["id"] for row in items],
            "evidenceState": evidence_state,
            "decisionIds": decisions, "blockedWorkIds": blocked, "activeWorkIds": active,
            "deferredWorkIds": deferred,
            "summary": recorded.get("summary") if recorded else None,
            "evidenceRefs": recorded.get("evidence") if recorded else [],
            "limitations": recorded.get("limitations") if recorded else ["No explicit area assessment has been recorded."],
            "lastAssessedAt": (latest.get("detail") or {}).get("assessmentCompletedAt") if recorded else None,
            "nextAssessment": {"activityId": upcoming["id"], "at": upcoming["nextRun"], "scope": "shared_growth_review"} if upcoming and website_present else None,
        })
    return {
        "contractVersion": SERVICE_MODEL_VERSION, "websitePresent": website_present,
        "areas": areas, "work": work, "decisionIds": decision_ids,
        "recentResults": _results(tasks, by_id, now),
        "unassignedWorkIds": [row["id"] for row in work if row["primaryArea"] is None],
        "overdueActivityIds": overdue if website_present else [],
        "sources": [{key: row.get(key) for key in ("id", "state", "reason", "observedAt", "sourceRef", "freshnessHours")} for row in sources],
    }
