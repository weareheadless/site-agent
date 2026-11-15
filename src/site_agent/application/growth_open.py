"""One-click Growth entry: accepted CrawlSEO findings become Ada conversations.

The owner clicks one finding (or selects several technical findings) and the
connector work item becomes a brief in Ada's workspace. The local ledger here is
only a binding between that conversation, the drafts it produced and the
CrawlSEO task(s); CrawlSEO remains the owner-visible task status and the judge of
whether the published change worked.

Rules enforced here, never in the browser:

* only CrawlSEO technical findings may be grouped (O7, O8, O12);
* grouping is 2-10 findings from the same connector site;
* one conversation and one release per click, with idempotent status reports
  fanned out to every member task;
* publication is the delivery evidence: the approving owner is the confirmer,
  and a later recrawl records the outcome.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

LEDGER_KEY = "crawlseo_growth_open"
CONVERSATION_KEY = "crawlseo_growth_conversation"

# Opportunity types whose fix is a technical change. Content, links and research
# must never be multi-selected: one brief would blur separate decisions.
TECHNICAL_TYPES = ("O7", "O8", "O12")
GROUP_MIN = 2
GROUP_MAX = 10

OPEN = "open"
WORKING = "working"
PUBLISHING = "publishing"
LIVE = "live"
RESOLVED = "resolved"
CANCELLED = "cancelled"


class GrowthOpenError(RuntimeError):
    """A safe, owner-readable refusal from the one-click Growth boundary."""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _ledger(memory: Any) -> dict[str, Any]:
    value = memory.kv_get(LEDGER_KEY, {})
    if not isinstance(value, Mapping):
        return {"version": 1, "bindings": {}, "groups": {}}
    return {
        "version": 1,
        "bindings": dict(value.get("bindings") or {}),
        "groups": dict(value.get("groups") or {}),
    }


def _save(memory: Any, ledger: Mapping[str, Any]) -> None:
    memory.kv_set(LEDGER_KEY, dict(ledger))


def binding_for_task(memory: Any, task_id: str) -> dict[str, Any] | None:
    row = _ledger(memory)["bindings"].get(str(task_id))
    return dict(row) if isinstance(row, Mapping) else None


def binding_for_opportunity(memory: Any, opportunity_id: str) -> dict[str, Any] | None:
    for row in _ledger(memory)["bindings"].values():
        if isinstance(row, Mapping) and str(row.get("opportunityId")) == str(opportunity_id):
            return dict(row)
    return None


def remember_conversation(memory: Any, conversation_id: int, binding: Mapping[str, Any]) -> None:
    tasks = [dict(item) for item in binding.get("tasks") or [] if isinstance(item, Mapping)]
    memory.kv_set(f"{CONVERSATION_KEY}:{int(conversation_id)}", {
        "conversationId": int(conversation_id),
        "groupId": binding.get("groupId"),
        "tasks": tasks,
        "updatedAt": _now(),
    })


def conversation_binding(memory: Any, conversation_id: Any) -> dict[str, Any] | None:
    try:
        key = int(conversation_id)
    except (TypeError, ValueError):
        return None
    value = memory.kv_get(f"{CONVERSATION_KEY}:{key}", None)
    if not isinstance(value, Mapping):
        return None
    tasks = [dict(item) for item in value.get("tasks") or [] if isinstance(item, Mapping)]
    return {"conversationId": key, "groupId": value.get("groupId"), "tasks": tasks} if tasks else None


def bind_draft(memory: Any, draft_id: Any, job_id: Any) -> None:
    """Attach the conversation's CrawlSEO tasks to a draft it produced.

    Called at draft creation. The binding lives on the draft metadata, so the
    approval path can report delivery without reconstructing the chat history.
    """
    if not job_id or not draft_id:
        return
    job = memory.get_chat_job(int(job_id))
    if not isinstance(job, Mapping):
        return
    binding = conversation_binding(memory, job.get("conversation_id"))
    if binding is None:
        return
    draft = memory.get_draft(int(draft_id))
    if not draft:
        return
    meta = dict(draft.get("meta") or {})
    if meta.get("crawlseo_tasks") == binding["tasks"]:
        return
    meta["crawlseo_tasks"] = binding["tasks"]
    if binding.get("groupId"):
        meta["crawlseo_group_id"] = str(binding["groupId"])
    memory.update_draft_meta(int(draft_id), meta)
    ledger = _ledger(memory)
    changed = False
    for item in binding["tasks"]:
        task_id = str(item.get("taskId") or "")
        row = ledger["bindings"].get(task_id)
        if row is None or row.get("draftId") == int(draft_id):
            continue
        row = dict(row)
        row.update({"draftId": int(draft_id), "updatedAt": _now()})
        if row.get("state") in {OPEN, WORKING}:
            row["state"] = WORKING
        ledger["bindings"][task_id] = row
        changed = True
    if binding.get("groupId"):
        group = ledger["groups"].get(str(binding["groupId"]))
        if isinstance(group, Mapping) and group.get("draftId") != int(draft_id):
            group = dict(group)
            group.update({"draftId": int(draft_id), "updatedAt": _now()})
            ledger["groups"][str(binding["groupId"])] = group
            changed = True
    if changed:
        _save(memory, ledger)


def _technical_type(row: Mapping[str, Any]) -> bool:
    return str(row.get("type") or "")[:2] in TECHNICAL_TYPES


def _page(row: Mapping[str, Any]) -> str:
    page = str(row.get("pageUrl") or "").strip()
    if page:
        return page
    inputs = row.get("scoreInputs") if isinstance(row.get("scoreInputs"), Mapping) else {}
    anchor = inputs.get("anchor") if isinstance(inputs.get("anchor"), Mapping) else {}
    return str(anchor.get("url") or "")


def _recommendation(row: Mapping[str, Any]) -> str:
    decision = row.get("recommendationDecision") if isinstance(row.get("recommendationDecision"), Mapping) else {}
    for key in ("recommendation", "action", "summary", "nextStep"):
        value = decision.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:1200]
    return str(row.get("summary") or "").strip()[:1200]


def _brief(rows: Sequence[Mapping[str, Any]], *, group: bool) -> str:
    first = rows[0]
    if group:
        lines = [
            "Ada, fix these CrawlSEO findings together as one technical change.",
            "",
            f"{len(rows)} technical findings share one delivery:",
        ]
        for row in rows:
            page = _page(row)
            lines.append(f"- {str(row.get('title') or '').strip()}{f' — {page}' if page else ''}")
        lines.extend([
            "",
            "Why they belong together: they are technical defects on the same site, and one "
            "release closes all of them. Do not touch content, articles, keywords or links.",
            "",
            "Prepare the exact change, then show me the review here in chat and ask me to "
            "validate it. Do not publish before I approve it in this conversation.",
        ])
        return "\n".join(lines)[:8000]
    page = _page(first)
    recommendation = _recommendation(first)
    lines = [
        f"Ada, fix this CrawlSEO finding: {str(first.get('title') or '').strip()}",
        "",
        f"Why it matters: {str(first.get('summary') or '').strip()[:1200]}",
    ]
    if page:
        lines.append(f"Page: {page}")
    if recommendation:
        lines.append(f"Suggested fix: {recommendation}")
    lines.extend([
        "",
        "Prepare the exact change, then show me the review here in chat and ask me to "
        "validate it. Do not publish before I approve it in this conversation.",
    ])
    return "\n".join(lines)[:8000]


def _find_opportunity(opportunities: Mapping[str, Any], opportunity_id: str) -> Mapping[str, Any] | None:
    for row in opportunities.get("opportunities") or []:
        if isinstance(row, Mapping) and str(row.get("id")) == str(opportunity_id):
            return row
    return None


def _fetch_opportunities(service: Any, site_id: str) -> Mapping[str, Any]:
    collected: list[Mapping[str, Any]] = []
    cursor: str | None = None
    counts: Mapping[str, Any] | None = None
    for _ in range(6):
        page = service.connector_opportunities(site_id, limit=100, cursor=cursor)
        if not isinstance(page, Mapping):
            raise GrowthOpenError("CrawlSEO returned an invalid opportunity list")
        if counts is None and isinstance(page.get("counts"), Mapping):
            counts = page["counts"]
        collected.extend(row for row in page.get("opportunities") or [] if isinstance(row, Mapping))
        cursor = page.get("nextCursor") if isinstance(page.get("nextCursor"), str) else None
        if not cursor:
            break
    return {"opportunities": collected, "counts": counts}


def _accept(service: Any, site_id: str, row: Mapping[str, Any], actor: str, key: str,
            generation: int) -> str:
    task = next((item for item in row.get("tasks") or [] if isinstance(item, Mapping)), None)
    if isinstance(task, Mapping) and task.get("id"):
        return str(task["id"])
    if str(row.get("status")) not in {"detected", "parked"}:
        raise GrowthOpenError("this finding already has work in flight")
    decision = row.get("recommendationDecision") if isinstance(row.get("recommendationDecision"), Mapping) else {}
    operation: dict[str, Any] = {
        "siteId": site_id,
        "generation": generation,
        "idempotencyKey": key,
        "confirmedBy": actor,
        "confirmationRef": f"growth:open:{row.get('id')}:{key}",
        "operation": "accept",
        "expectedUpdatedAt": row.get("updatedAt"),
    }
    if isinstance(decision.get("decisionId"), str):
        operation["expectedDecisionId"] = decision["decisionId"]
    result = service.connector_opportunity_operation(str(row.get("id")), operation)
    task_id = str((result or {}).get("taskId") or "")
    if not task_id:
        raise GrowthOpenError("CrawlSEO accepted the finding without a task identity")
    return task_id


def _start_task(service: Any, site_id: str, task_id: str, opportunity_id: str, actor: str,
                key: str, generation: int) -> None:
    current = service.connector_task(site_id, task_id)
    task = current.get("task") if isinstance(current, Mapping) else None
    if not isinstance(task, Mapping):
        raise GrowthOpenError("CrawlSEO returned an invalid task")
    status = str(task.get("status") or "")
    if status != "todo":
        return
    service.connector_confirm_task(task_id, {
        "siteId": site_id,
        "generation": generation,
        "idempotencyKey": key,
        "confirmedBy": actor,
        "confirmationRef": f"growth:start:{task_id}:{key}",
        "opportunityId": opportunity_id,
        "expectedStatus": "todo",
        "status": "in_progress",
    })


def open_opportunity(
    service: Any,
    memory: Any,
    tenant: Any,
    *,
    opportunity_id: str,
    site_id: str,
    generation: int,
    actor: str,
    enqueue: Any,
) -> dict[str, Any]:
    existing = binding_for_opportunity(memory, opportunity_id)
    if existing is not None:
        return {
            "ok": True,
            "idempotent": True,
            "opportunityId": opportunity_id,
            "taskId": existing.get("taskId"),
            "conversationId": existing.get("conversationId"),
            "jobId": existing.get("jobId"),
            "groupId": existing.get("groupId"),
        }
    rows = _fetch_opportunities(service, site_id)
    row = _find_opportunity(rows, opportunity_id)
    if row is None:
        raise GrowthOpenError("this finding is no longer on the CrawlSEO board")
    if str(row.get("status")) in {"rejected", "closed"}:
        raise GrowthOpenError("this finding was already rejected or closed")
    key = f"growth-open:{opportunity_id}:{uuid.uuid4().hex}"
    task_id = _accept(service, site_id, row, actor, key, generation)
    _start_task(service, site_id, task_id, opportunity_id, actor, key, generation)
    result = enqueue({"message": _brief([row], group=False), "context": {"growth_open": opportunity_id}})
    conversation_id = int(result["conversation_id"])
    job_id = int(result["job_id"])
    binding = {
        "taskId": task_id,
        "opportunityId": opportunity_id,
        "title": str(row.get("title") or ""),
        "pageUrl": _page(row) or None,
        "groupId": None,
        "conversationId": conversation_id,
        "jobId": job_id,
        "draftId": None,
        "state": WORKING,
        "links": {},
        "createdAt": _now(),
        "updatedAt": _now(),
        "tasks": [{"siteId": site_id, "taskId": task_id, "opportunityId": opportunity_id, "groupId": None}],
    }
    ledger = _ledger(memory)
    ledger["bindings"][task_id] = binding
    _save(memory, ledger)
    remember_conversation(memory, conversation_id, binding)
    return {"ok": True, "opportunityId": opportunity_id, "taskId": task_id,
            "conversationId": conversation_id, "jobId": job_id}


def open_group(
    service: Any,
    memory: Any,
    tenant: Any,
    *,
    opportunity_ids: Sequence[str],
    site_id: str,
    generation: int,
    actor: str,
    enqueue: Any,
) -> dict[str, Any]:
    ids = []
    for value in opportunity_ids:
        value = str(value or "").strip()
        if value and value not in ids:
            ids.append(value)
    if not GROUP_MIN <= len(ids) <= GROUP_MAX:
        raise GrowthOpenError(f"select between {GROUP_MIN} and {GROUP_MAX} findings")
    rows_by_id = _fetch_opportunities(service, site_id)
    selected = []
    for opportunity_id in ids:
        row = _find_opportunity(rows_by_id, opportunity_id)
        if row is None:
            raise GrowthOpenError("a selected finding is no longer on the CrawlSEO board")
        if str(row.get("status")) in {"rejected", "closed"}:
            raise GrowthOpenError("a selected finding was already rejected or closed")
        if not _technical_type(row):
            raise GrowthOpenError("only technical findings can be fixed together; content and research stay separate")
        selected.append(row)
    # Idempotent grouping: the same exact member set reopens its conversation.
    signature = ",".join(sorted(ids))
    ledger = _ledger(memory)
    for group in ledger["groups"].values():
        if isinstance(group, Mapping) and group.get("signature") == signature:
            return {
                "ok": True,
                "idempotent": True,
                "groupId": group.get("id"),
                "conversationId": group.get("conversationId"),
                "jobId": group.get("jobId"),
                "taskIds": list(group.get("taskIds") or []),
            }
    group_id = f"g{uuid.uuid4().hex[:12]}"
    key = f"growth-group:{group_id}"
    tasks = []
    for row in selected:
        own_key = f"{key}:{row.get('id')}"
        task_id = _accept(service, site_id, row, actor, own_key, generation)
        _start_task(service, site_id, task_id, str(row.get("id")), actor, own_key, generation)
        tasks.append({"siteId": site_id, "taskId": task_id, "opportunityId": str(row.get("id")), "groupId": group_id})
    result = enqueue({"message": _brief(selected, group=True), "context": {"growth_open": group_id}})
    conversation_id = int(result["conversation_id"])
    job_id = int(result["job_id"])
    title = f"{len(tasks)} technical findings"
    group = {
        "id": group_id,
        "signature": signature,
        "title": title,
        "taskIds": [item["taskId"] for item in tasks],
        "opportunityIds": [item["opportunityId"] for item in tasks],
        "conversationId": conversation_id,
        "jobId": job_id,
        "draftId": None,
        "state": WORKING,
        "links": {},
        "createdAt": _now(),
        "updatedAt": _now(),
        "tasks": tasks,
    }
    ledger["groups"][group_id] = group
    for item in tasks:
        ledger["bindings"][item["taskId"]] = {
            "taskId": item["taskId"],
            "opportunityId": item["opportunityId"],
            "title": next((str(row.get("title") or "") for row in selected
                           if str(row.get("id")) == item["opportunityId"]), ""),
            "pageUrl": next((_page(row) for row in selected
                             if str(row.get("id")) == item["opportunityId"]), None),
            "groupId": group_id,
            "conversationId": conversation_id,
            "jobId": job_id,
            "draftId": None,
            "state": WORKING,
            "links": {},
            "createdAt": _now(),
            "updatedAt": _now(),
            "tasks": tasks,
        }
    _save(memory, ledger)
    remember_conversation(memory, conversation_id, group)
    return {"ok": True, "groupId": group_id, "conversationId": conversation_id,
            "jobId": job_id, "taskIds": [item["taskId"] for item in tasks]}


def _five_state(task_status: str, binding_state: str, draft_status: str | None) -> str:
    if task_status == "verified_outcome":
        return RESOLVED
    if binding_state == LIVE or task_status == "delivered":
        return LIVE
    if task_status == "awaiting_human" or draft_status == "pending":
        return "awaiting"
    if binding_state == CANCELLED:
        return OPEN
    return WORKING


def _draft_status(memory: Any, draft_id: Any) -> tuple[str | None, dict[str, Any] | None]:
    try:
        draft = memory.get_draft(int(draft_id)) if draft_id else None
    except (TypeError, ValueError):
        draft = None
    return (str(draft.get("status")) if draft else None), draft


def _live_link(draft: Mapping[str, Any] | None, config: Mapping[str, Any]) -> str | None:
    site = (config.get("site") or {}) if isinstance(config, Mapping) else {}
    for candidate in (site.get("url"), site.get("public_url")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().rstrip("/") + "/"
    return None


def task_ids_for(memory: Any) -> list[str]:
    return [str(key) for key in _ledger(memory)["bindings"].keys()]


def pending_releases(memory: Any) -> list[dict[str, Any]]:
    ledger = _ledger(memory)
    return [dict(row) for row in ledger["bindings"].values()
            if isinstance(row, Mapping) and row.get("state") == PUBLISHING and row.get("draftId")]


def read_bindings(memory: Any, config: Mapping[str, Any], *,
                  task_statuses: Mapping[str, str] | None = None,
                  reconcile: Any = None) -> dict[str, Any]:
    """Owner-visible five-state projection over the local ledger.

    A release queued by approval is reconciled read-only: the deployment receipt
    is the evidence, never a reason to publish again. Reconciling here means the
    ordinary Growth read settles a finished release without a second button.
    """
    if callable(reconcile):
        try:
            reconcile()
        except Exception:
            # A failed reconciliation must not hide the rest of the board; the
            # next read retries the same read-only check.
            pass
    ledger = _ledger(memory)
    bindings = []
    for task_id, row in ledger["bindings"].items():
        if not isinstance(row, Mapping):
            continue
        item = dict(row)
        draft_status, draft = _draft_status(memory, item.get("draftId"))
        task_status = str((task_statuses or {}).get(task_id) or item.get("taskStatus") or "")
        state = _five_state(task_status, str(item.get("state") or WORKING), draft_status)
        if state == "awaiting":
            state = WORKING if draft_status != "pending" else "awaiting"
        links = dict(item.get("links") or {})
        if draft_status == "pending" and item.get("draftId"):
            links["draft"] = f"draft:{item['draftId']}"
        page = str(item.get("pageUrl") or "").strip()
        if page and (state in {LIVE, RESOLVED}):
            links.setdefault("live", page)
        else:
            live = _live_link(draft, config)
            if live and (state in {LIVE, RESOLVED}):
                links.setdefault("live", live)
        bindings.append({
            "taskId": task_id,
            "opportunityId": item.get("opportunityId"),
            "title": item.get("title"),
            "pageUrl": item.get("pageUrl"),
            "groupId": item.get("groupId"),
            "conversationId": item.get("conversationId"),
            "jobId": item.get("jobId"),
            "draftId": item.get("draftId"),
            "draftStatus": draft_status,
            "state": state,
            "links": links,
        })
    groups = []
    for group_id, row in ledger["groups"].items():
        if not isinstance(row, Mapping):
            continue
        item = dict(row)
        draft_status, _draft = _draft_status(memory, item.get("draftId"))
        member_states = [entry["state"] for entry in bindings if entry.get("groupId") == group_id]
        state = WORKING
        if member_states and all(value == RESOLVED for value in member_states):
            state = RESOLVED
        elif member_states and all(value in {LIVE, RESOLVED} for value in member_states):
            state = LIVE
        elif "awaiting" in member_states or draft_status == "pending":
            state = "awaiting"
        groups.append({
            "id": group_id,
            "title": item.get("title"),
            "taskIds": list(item.get("taskIds") or []),
            "opportunityIds": list(item.get("opportunityIds") or []),
            "conversationId": item.get("conversationId"),
            "jobId": item.get("jobId"),
            "draftId": item.get("draftId"),
            "state": state,
            "links": dict(item.get("links") or {}),
        })
    return {"bindings": bindings, "groups": groups}


def deliver_tasks(
    service: Any,
    memory: Any,
    *,
    site_id: str,
    generation: int,
    tasks: Sequence[Mapping[str, Any]],
    actor: str,
    reference: str,
    links: Mapping[str, Any] | None = None,
) -> int:
    """Report publication to every member task, idempotently and per member."""
    delivered = 0
    ledger = _ledger(memory)
    for item in tasks:
        task_id = str(item.get("taskId") or "")
        opportunity_id = str(item.get("opportunityId") or "")
        site = str(item.get("siteId") or site_id)
        if not task_id or not opportunity_id:
            continue
        row = ledger["bindings"].get(task_id)
        if isinstance(row, Mapping) and row.get("state") in {LIVE, RESOLVED}:
            continue
        try:
            current = service.connector_task(site, task_id)
            task = current.get("task") if isinstance(current, Mapping) else None
            status = str((task or {}).get("status") or "")
            if status in {"delivered", "verified_outcome"}:
                delivered += 1
            else:
                service.connector_confirm_task(task_id, {
                    "siteId": site,
                    "generation": generation,
                    "idempotencyKey": f"growth-deliver:{task_id}:{reference}",
                    "confirmedBy": actor,
                    "confirmationRef": reference,
                    "opportunityId": opportunity_id,
                    "expectedStatus": status,
                    "status": "delivered",
                })
                delivered += 1
        except Exception:
            # Publication is already proven by the release receipt. A connector
            # write that fails now stays retryable; it must not fail approval.
            if isinstance(row, Mapping):
                row = dict(row)
                row.update({"state": PUBLISHING, "updatedAt": _now()})
                ledger["bindings"][task_id] = row
            continue
        if isinstance(row, Mapping):
            row = dict(row)
            row.update({"state": LIVE, "confirmedBy": actor, "updatedAt": _now(),
                        "links": {**dict(row.get("links") or {}), **dict(links or {})}})
            ledger["bindings"][task_id] = row
        group_id = row.get("groupId") if isinstance(row, Mapping) else None
        for group_id_value, group in list(ledger["groups"].items()):
            if isinstance(group, Mapping) and group_id and group_id_value == group_id:
                group = dict(group)
                group.update({"state": LIVE, "updatedAt": _now()})
                ledger["groups"][group_id_value] = group
                break
    _save(memory, ledger)
    return delivered


def publication_hook(context: Mapping[str, Any] | None, draft: Mapping[str, Any],
                     result: Mapping[str, Any], *, actor: str | None) -> None:
    """Confirm bound CrawlSEO tasks once publication is proven.

    Called from draft approval. A queued source release is recorded as
    publishing and settled by the next read; an immediate Payload publication is
    live now. Nothing here asks the owner for a second confirmation.
    """
    if context is None:
        return
    memory = context.get("memory")
    meta = draft.get("meta") if isinstance(draft.get("meta"), Mapping) else {}
    tasks = meta.get("crawlseo_tasks") if isinstance(meta.get("crawlseo_tasks"), list) else []
    if not memory or not tasks:
        return
    service = context.get("crawlseo_service")
    if service is None:
        return
    status = str(result.get("status") or "")
    site_id = str((context.get("seo_provisioning_state") or {}).get("crawlseo", {}).get("site_id")
                  or context.get("connector_site_id") or context.get("site_id") or "")
    if not site_id:
        site_id = str((tasks[0] or {}).get("siteId") or "") if tasks and isinstance(tasks[0], Mapping) else ""
    if not site_id:
        return
    try:
        capabilities = service.connector_capabilities(site_id)
        binding = capabilities.get("binding") if isinstance(capabilities, Mapping) else {}
        generation = binding.get("generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            return
    except Exception:
        return
    draft_id = draft.get("id")
    reference = f"growth:draft:{draft_id}"
    if status in {"published", "live", "applied"}:
        delivered = dict(result.get("deployment") or {}) if isinstance(result.get("deployment"), Mapping) else {}
        links = {key: str(delivered.get(key) or "") for key in ("commit", "commit_sha", "url", "live_url")
                 if isinstance(delivered.get(key), str) and delivered.get(key)}
        deliver_tasks(service, memory, site_id=site_id, generation=generation,
                      tasks=[dict(item) for item in tasks if isinstance(item, Mapping)],
                      actor=actor or "owner", reference=reference, links=links)
        return
    if status == "publishing":
        ledger = _ledger(memory)
        for item in tasks:
            if not isinstance(item, Mapping):
                continue
            task_id = str(item.get("taskId") or "")
            row = ledger["bindings"].get(task_id)
            if isinstance(row, Mapping):
                row = dict(row)
                row.update({"state": PUBLISHING, "draftId": draft_id, "updatedAt": _now()})
                ledger["bindings"][task_id] = row
        _save(memory, ledger)


def cancel_binding_for_draft(memory: Any, draft_id: Any) -> None:
    """A discarded review returns its findings to Ada's queue, not to delivery."""
    if not draft_id:
        return
    ledger = _ledger(memory)
    changed = False
    for task_id, row in ledger["bindings"].items():
        if not isinstance(row, Mapping) or int(row.get("draftId") or 0) != int(draft_id):
            continue
        if row.get("state") in {LIVE, RESOLVED}:
            continue
        row = dict(row)
        row.update({"draftId": None, "state": WORKING, "updatedAt": _now()})
        ledger["bindings"][task_id] = row
        changed = True
    for group_id, group in ledger["groups"].items():
        if not isinstance(group, Mapping) or int(group.get("draftId") or 0) != int(draft_id):
            continue
        group = dict(group)
        group.update({"draftId": None, "state": WORKING, "updatedAt": _now()})
        ledger["groups"][group_id] = group
        changed = True
    if changed:
        _save(memory, ledger)
