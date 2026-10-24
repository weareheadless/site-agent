"""Business-level read projection; existing Growth records remain authoritative."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any
from ..core.growth_contracts import GROWTH_AREAS as AREAS

SERVICE_MODEL_VERSION = "growth-service-v1"

# Existing capabilities only. A planner's assessment is not a measurement.
AREA_CAPABILITIES = {
    "content": {"scope": "canonical_content_inventory", "sourceIds": ["inventory"], "automatedMeasurement": "content_inventory"},
    "search_visibility": {"scope": "search_and_keyword_evidence", "sourceIds": ["gsc", "dataforseo"], "automatedMeasurement": "configured_sources"},
    "website_health": {"scope": "available_crawl_evidence", "sourceIds": ["inventory"], "automatedMeasurement": "crawl_when_available"},
    "audience_competitors": {"scope": "traffic_and_available_competitor_evidence", "sourceIds": ["ga4", "dataforseo"], "automatedMeasurement": "configured_sources"},
    "speed_experience": {"scope": "evidence_led_source_investigation", "sourceIds": [], "automatedMeasurement": "not_supported"},
}


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


_ACTIVE_CAPACITY_STATES = {"preparing", "validating", "ready_for_review", "publishing", "verifying_live"}


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _run_source_states(run: Mapping[str, Any], sources: Sequence[Mapping[str, Any]], now: datetime,
                       inventory_freshness_hours: int) -> dict[str, str]:
    detail = run.get("detail") or {}
    material = detail.get("material") or {}
    states: dict[str, str] = {}
    for source in material.get("sources", []):
        observed = _date(source.get("observedAt"))
        state = source.get("state")
        if state == "ready":
            max_age = source.get("freshnessHours", inventory_freshness_hours)
            state = "unavailable" if observed is None or observed > now + timedelta(minutes=5) else "stale" if now - observed > timedelta(hours=max_age) else "ready"
        for ref in (source.get("id"), source.get("sourceRef")):
            if ref:
                states[str(ref)] = state
    for document in material.get("inventory", []):
        if document.get("sourceRef"):
            states[str(document["sourceRef"])] = states.get("inventory", "unavailable")
    # A current provider read can invalidate a saved observation, but a fresh
    # provider status cannot refresh the timestamp of an older run's evidence.
    for source in sources:
        current_state = source.get("state")
        if current_state in {"stale", "unavailable"}:
            for ref in (source.get("id"), source.get("sourceRef")):
                if ref:
                    states[str(ref)] = current_state
            if source.get("id") == "inventory":
                for document in material.get("inventory", []):
                    if isinstance(document, Mapping) and document.get("sourceRef"):
                        states[str(document["sourceRef"])] = current_state
    return states


def _opportunity_findings(runs: Sequence[Mapping[str, Any]], initiatives: Sequence[Mapping[str, Any]],
                          sources: Sequence[Mapping[str, Any]], now: datetime,
                          inventory_freshness_hours: int,
                          max_active_candidates: int,
                          visible_work_ids: set[str],
                          initiative_work_aliases: Mapping[str, str]) -> dict[str, list[dict[str, Any]]]:
    """Project each saved finding with its exact assessment lineage and current evidence/work state."""
    by_area: dict[str, list[dict[str, Any]]] = {area: [] for area in AREAS}
    for run in runs:
        run_id = str(run.get("run_id") or "")
        detail = run.get("detail") or {}
        assessment = detail.get("assessment") or {}
        completed_at = detail.get("assessmentCompletedAt")
        opportunities = assessment.get("opportunities")
        if not run_id or not _date(completed_at) or not isinstance(opportunities, list):
            continue
        waiting = detail.get("waitingForCapacity")
        waiting = waiting if isinstance(waiting, list) and all(isinstance(item, str) for item in waiting) else []
        title_counts: dict[str, int] = {}
        for opportunity in opportunities:
            if isinstance(opportunity, Mapping) and isinstance(opportunity.get("title"), str):
                title_counts[opportunity["title"]] = title_counts.get(opportunity["title"], 0) + 1
        candidate_ids = detail.get("candidateIds")
        candidate_ids = {str(value) for value in candidate_ids} if isinstance(candidate_ids, list) else set()
        queued_ids = detail.get("queuedInitiativeIds")
        queued_ids = {str(value) for value in queued_ids} if isinstance(queued_ids, list) else set()
        source_states = _run_source_states(run, sources, now, inventory_freshness_hours)
        material = detail.get("material") or {}
        unprepared = assessment.get("unpreparedOpportunities")
        unprepared = unprepared if isinstance(unprepared, list) else []
        for index, opportunity in enumerate(opportunities):
            if not isinstance(opportunity, Mapping):
                continue
            primary = opportunity.get("primaryArea")
            if primary not in AREAS:
                continue
            secondary = [area for area in opportunity.get("secondaryAreas", []) if area in AREAS and area != primary]
            expected_hash = _json_hash(opportunity)
            duplicate_opportunity = sum(1 for item in opportunities
                if isinstance(item, Mapping) and _json_hash(item) == expected_hash) > 1
            matches = [row for row in initiatives
                if str(row.get("growth_run_id") or "") == run_id
                and isinstance(row.get("expected"), Mapping)
                and isinstance(row["expected"].get("opportunity"), Mapping)
                and _json_hash(row["expected"]["opportunity"]) == expected_hash]
            initiative = matches[0] if len(matches) == 1 and not duplicate_opportunity else None
            status = "unknown" if len(matches) > 1 or duplicate_opportunity else "assessment_pending"
            status_reason = None
            initiative_id = None
            candidate_id = None
            if initiative is not None:
                initiative_id = initiative.get("id")
                state = str(initiative.get("state") or "unknown")
                status = state
                if str(initiative_id) in candidate_ids:
                    candidate_id = initiative_id
                validation = initiative.get("validation") or {}
                if isinstance(validation, Mapping):
                    status_reason = validation.get("reason") or validation.get("reassessWhen")
            elif opportunity.get("title") in waiting:
                if title_counts.get(opportunity.get("title"), 0) == 1:
                    status = "waiting_for_capacity"
                    status_reason = "Waiting for candidate capacity."
                else:
                    status = "unknown"
                    status_reason = "The saved capacity marker cannot be uniquely linked to this finding."
            else:
                for retained in unprepared:
                    if isinstance(retained, Mapping) and all(retained.get(key) == value for key, value in opportunity.items()):
                        status = str(retained.get("disposition") or "deferred")
                        status_reason = retained.get("preparationNote") or retained.get("reassessWhen")
                        break
            if not status_reason and status == "assessment_pending" and run.get("status") == "pending":
                status_reason = "Assessment preparation has not recorded a candidate state yet."
            evidence_refs = [ref for ref in opportunity.get("evidence", []) if isinstance(ref, str)]
            states = [source_states.get(ref, "unavailable") for ref in evidence_refs]
            evidence_state = "unavailable" if not states or any(state not in {"ready", "stale"} for state in states) else "stale" if "stale" in states else "current"
            finding: dict[str, Any] = {
                "id": f"{run_id}:{index}", "runId": run_id, "opportunityIndex": index,
                "assessedAt": completed_at, "kind": opportunity.get("kind"),
                "title": opportunity.get("title"), "problem": opportunity.get("why"),
                "hypothesis": opportunity.get("hypothesis"), "nextStep": opportunity.get("scope"),
                "primaryArea": primary, "secondaryAreas": list(dict.fromkeys(secondary)),
                "evidenceRefs": evidence_refs, "requiredSources": [ref for ref in opportunity.get("requiredSources", []) if isinstance(ref, str)],
                "evidenceState": evidence_state, "status": status,
                "waitingOnWorkIds": [],
            }
            if status_reason:
                finding["statusReason"] = str(status_reason)[:500]
            if initiative_id is not None:
                finding["initiativeId"] = initiative_id
                if candidate_id is not None:
                    finding["candidateId"] = str(candidate_id)
            if opportunity.get("collection") is not None and opportunity.get("documentId") is not None:
                finding["target"] = {"collection": opportunity["collection"], "documentId": opportunity["documentId"]}
            if status == "waiting_for_capacity":
                active_blockers = [
                    row for row in initiatives
                    if row.get("kind") != "owner_information" and row.get("state") in _ACTIVE_CAPACITY_STATES
                    and str(row.get("growth_run_id") or "") != run_id and row.get("id") is not None
                ]
                same_run_ids = candidate_ids | queued_ids
                active_blockers.extend(row for row in initiatives
                    if row.get("kind") != "owner_information" and row.get("state") in _ACTIVE_CAPACITY_STATES
                    and str(row.get("growth_run_id") or "") == run_id
                    and str(row.get("id")) in same_run_ids and row.get("id") is not None)
                unique_blockers = {str(row["id"]): row for row in active_blockers}
                full = len(unique_blockers) >= max(1, int(max_active_candidates))
                finding["capacityState"] = "full" if full else "available"
                if full:
                    represented_blockers = set()
                    for work_id in sorted(unique_blockers, key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value)):
                        raw_id = f"initiative:{work_id}"
                        canonical_id = raw_id if raw_id in visible_work_ids else initiative_work_aliases.get(str(work_id))
                        if canonical_id in visible_work_ids:
                            represented_blockers.add(canonical_id)
                    finding["waitingOnWorkIds"] = sorted(represented_blockers)
                else:
                    finding["statusReason"] = "The saved wait marker is pending reconciliation; capacity is currently available."
            for area in dict.fromkeys([primary, *secondary]):
                by_area[area].append(finding)
    for findings in by_area.values():
        findings.sort(key=lambda item: (_date(item.get("assessedAt")) or datetime.min.replace(tzinfo=timezone.utc), item["opportunityIndex"]), reverse=True)
    return by_area


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
        source_acceptance = validation.get("sourceTechnicalAcceptance") or {}
        source_checks = source_acceptance.get("technicalChecks") or []
        source_verified = (verification.get("verified") is True and verification.get("releaseId")
            and re.fullmatch(r"[0-9a-f]{40}", str(verification.get("commit") or ""))
            and source_acceptance.get("status") == "passed"
            and source_acceptance.get("sourceSha") == verification.get("commit")
            and source_acceptance.get("releaseId") == verification.get("releaseId")
            and source_acceptance.get("packageHash") == initiative.get("review_package_hash")
            and bool(source_checks) and all(isinstance(check, Mapping) and check.get("status") == "passed"
                and check.get("criterion") and check.get("evidence") for check in source_checks))
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
    reconciliation: Mapping[str, Any] | None = None,
    inventory_freshness_hours: int = 168,
    max_active_candidates: int = 2,
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
    visible_work_ids = {str(row["id"]) for row in work}
    initiative_work_aliases: dict[str, str] = {}
    for task in tasks:
        task_id = str(task.get("id") or "")
        if task_id not in visible_work_ids:
            continue
        history = task.get("history")
        if not isinstance(history, list):
            continue
        for item in history:
            if isinstance(item, Mapping) and item.get("initiativeId") is not None:
                initiative_work_aliases[str(item["initiativeId"])] = task_id
    decision_ids = [row["id"] for row in work if row["state"] == "awaiting_owner"]
    assessments = sorted(
        (row for row in runs if isinstance((row.get("detail") or {}).get("assessment"), Mapping)
         and _date((row.get("detail") or {}).get("assessmentCompletedAt"))),
        key=lambda row: _date(row["detail"]["assessmentCompletedAt"]), reverse=True,
    )
    coverage: dict[str, Mapping[str, Any]] = {}
    coverage_runs: dict[str, Mapping[str, Any]] = {}
    coverage_source_states: dict[str, dict[str, str]] = {}
    for assessed_run in assessments:
        detail = assessed_run.get("detail") or {}
        assessment = detail.get("assessment") or {}
        rows = assessment.get("coverage")
        if not isinstance(rows, list):
            continue
        source_states = _run_source_states(
            assessed_run, sources, now, inventory_freshness_hours,
        )
        for row in rows:
            area_id = row.get("area") if isinstance(row, Mapping) else None
            if area_id not in AREAS or area_id in coverage:
                continue
            coverage[area_id] = row
            coverage_runs[area_id] = assessed_run
            coverage_source_states[area_id] = source_states
    findings_by_area = _opportunity_findings(
        runs, initiatives, sources, now, inventory_freshness_hours, max_active_candidates,
        visible_work_ids, initiative_work_aliases,
    )
    schedules = [row for row in activities if row.get("enabled") and row.get("id") in {"growth_initial", "growth_weekly"} and _date(row.get("nextRun"))]
    schedules.sort(key=lambda row: _date(row["nextRun"]))
    upcoming = next((row for row in schedules if _date(row["nextRun"]) > now), None)
    overdue = [row["id"] for row in schedules if _date(row["nextRun"]) <= now]
    preparation = []
    for run in runs:
        detail = run.get("detail") or {}
        waiting = detail.get("waitingForCapacity")
        if run.get("status") != "pending" or not isinstance(waiting, list) or not waiting:
            continue
        opportunity_areas = list(dict.fromkeys(
            area for opportunity in (detail.get("assessment") or {}).get("opportunities", [])
            if opportunity.get("title") in waiting
            for area in [opportunity.get("primaryArea"), *opportunity.get("secondaryAreas", [])]
            if area in AREAS
        ))
        preparation.append({"runId": run.get("run_id"), "state": "waiting_for_capacity",
            "areaIds": opportunity_areas, "findingCount": len(waiting),
            "eligibleAt": run.get("next_due_ts"),
            "executor": "growth_pending" if reconciliation and reconciliation.get("enabled") else None,
            "nextReconciliationAt": reconciliation.get("nextRun") if reconciliation and reconciliation.get("enabled") else None})
    areas = []
    for area in AREAS:
        items = [row for row in work if row["primaryArea"] == area or area in row["secondaryAreas"]]
        recorded = coverage.get(area)
        coverage_run = coverage_runs.get(area)
        source_states = coverage_source_states.get(area, {})
        decisions = [row["id"] for row in items if row["state"] == "awaiting_owner"]
        blocked = [row["id"] for row in items if row["executionIssue"]]
        active = [row["id"] for row in items if row["state"] == "preparing"]
        deferred = [row["id"] for row in items if row["state"] == "deferred"]
        pending_runs = [row["runId"] for row in preparation if area in row["areaIds"]]
        unresolved = [ref for ref in recorded.get("evidence", []) if ref not in source_states] if recorded else []
        evidence_states = [source_states.get(ref, "unavailable") for ref in recorded.get("evidence", [])] if recorded else []
        evidence_state = (
            "not_assessed" if not recorded
            else "unavailable" if not evidence_states or any(value not in {"ready", "stale"} for value in evidence_states)
            else "stale" if "stale" in evidence_states else "recorded"
        )
        if not website_present:
            state = "awaiting_activation"
        elif decisions:
            state = "needs_decision"
        elif blocked:
            state = "blocked"
        elif active:
            state = "preparing"
        elif pending_runs:
            state = "waiting_for_capacity"
        elif deferred:
            state = "deferred"
        elif evidence_state in {"stale", "unavailable"}:
            state = evidence_state
        else:
            state = "assessed" if recorded else "not_assessed"
        areas.append({
            "id": area, "state": state, "workIds": [row["id"] for row in items],
            "capability": AREA_CAPABILITIES[area],
            "evidenceState": evidence_state,
            "decisionIds": decisions, "blockedWorkIds": blocked, "activeWorkIds": active,
            "deferredWorkIds": deferred,
            "pendingRunIds": pending_runs,
            "summary": recorded.get("summary") if recorded else None,
            **({"ownerSummary": dict(recorded["ownerSummary"])} if recorded and evidence_state == "recorded"
                and isinstance(recorded.get("ownerSummary"), Mapping)
                and set(recorded["ownerSummary"]) == {"headline", "problem", "nextStep"}
                and all(isinstance(recorded["ownerSummary"].get(key), str)
                    and 0 < len(recorded["ownerSummary"][key].strip()) <= limit
                    for key, limit in (("headline", 180), ("problem", 500), ("nextStep", 500))) else {}),
            "findings": findings_by_area[area],
            "evidenceRefs": recorded.get("evidence") if recorded else [],
            "unresolvedEvidenceRefs": unresolved,
            "limitations": ([*recorded.get("limitations", []), *(["Some assessment evidence can no longer be resolved."] if unresolved else [])]
                            if recorded else ["No explicit area assessment has been recorded."]),
            "lastAssessedAt": (coverage_run.get("detail") or {}).get("assessmentCompletedAt") if recorded and coverage_run else None,
            "nextAssessment": {"activityId": upcoming["id"], "at": upcoming["nextRun"], "scope": "shared_growth_review"} if upcoming and website_present else None,
        })
    return {
        "contractVersion": SERVICE_MODEL_VERSION, "websitePresent": website_present,
        "areas": areas, "work": work, "decisionIds": decision_ids,
        "recentResults": _results(tasks, by_id, now),
        "preparation": preparation,
        "unassignedWorkIds": [row["id"] for row in work if row["primaryArea"] is None],
        "overdueActivityIds": overdue if website_present else [],
        "sources": [{key: row.get(key) for key in ("id", "state", "reason", "observedAt", "sourceRef", "freshnessHours")} for row in sources],
    }
