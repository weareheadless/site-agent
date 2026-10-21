"""Business-level read projection; existing Growth records remain authoritative."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
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


def service_model(
    *, tasks: Sequence[Mapping[str, Any]], initiatives: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]], sources: Sequence[Mapping[str, Any]],
    activities: Sequence[Mapping[str, Any]], website_present: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Never collect evidence, start jobs, infer approval, or manufacture coverage."""
    now = now or datetime.now(timezone.utc)
    by_id = {f"initiative:{row['id']}": row for row in initiatives}
    work = []
    for task in tasks:
        if task.get("kind") in {"schedule", "measurement"}:
            continue
        initiative = by_id.get(str(task.get("id")), {})
        expected = initiative.get("expected") or {}
        opportunity = expected.get("opportunity") or {}
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
        })
    unique = {str(row["id"]): row for row in work}
    work = list(unique.values())
    decision_ids = [row["id"] for row in work if row["state"] == "awaiting_owner"]
    assessments = sorted(
        (row for row in runs if isinstance((row.get("detail") or {}).get("assessment"), Mapping)),
        key=lambda row: str(row.get("updated_ts") or ""), reverse=True,
    )
    latest = assessments[0] if assessments else None
    assessment = (latest.get("detail") or {}).get("assessment") if latest else {}
    coverage = {row["area"]: row for row in assessment.get("coverage", []) if isinstance(row, Mapping) and row.get("area") in AREAS}
    schedules = [row for row in activities if row.get("enabled") and row.get("id") in {"growth_initial", "growth_weekly"} and _date(row.get("nextRun"))]
    schedules.sort(key=lambda row: _date(row["nextRun"]))
    upcoming = next((row for row in schedules if _date(row["nextRun"]) > now), None)
    overdue = [row["id"] for row in schedules if _date(row["nextRun"]) <= now]
    areas = []
    for area in AREAS:
        items = [row for row in work if row["primaryArea"] == area or area in row["secondaryAreas"]]
        recorded = coverage.get(area)
        decisions = [row["id"] for row in items if row["state"] == "awaiting_owner"]
        blocked = [row["id"] for row in items if row["executionIssue"]]
        active = [row["id"] for row in items if row["state"] == "preparing"]
        state = "awaiting_activation" if not website_present else "needs_decision" if decisions else "blocked" if blocked else "preparing" if active else "assessed" if recorded else "not_assessed"
        areas.append({
            "id": area, "state": state, "workIds": [row["id"] for row in items],
            "decisionIds": decisions, "blockedWorkIds": blocked, "activeWorkIds": active,
            "summary": recorded.get("summary") if recorded else None,
            "evidenceRefs": recorded.get("evidence") if recorded else [],
            "limitations": recorded.get("limitations") if recorded else ["No explicit area assessment has been recorded."],
            "lastAssessedAt": (latest.get("detail") or {}).get("assessmentCompletedAt") if recorded else None,
            "nextAssessment": {"activityId": upcoming["id"], "at": upcoming["nextRun"], "scope": "shared_growth_review"} if upcoming and website_present else None,
        })
    return {
        "contractVersion": SERVICE_MODEL_VERSION, "websitePresent": website_present,
        "areas": areas, "work": work, "decisionIds": decision_ids,
        "unassignedWorkIds": [row["id"] for row in work if row["primaryArea"] is None],
        "overdueActivityIds": overdue if website_present else [],
        "sources": [{key: row.get(key) for key in ("id", "state", "reason", "observedAt", "sourceRef", "freshnessHours")} for row in sources],
    }
