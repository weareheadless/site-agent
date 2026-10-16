"""Durable handoff from an owner's answer to Ada's next Growth assessment."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..core.contracts import utc_now


_USER_REQUEST_MARKER = "\n[User request]\n"


def _user_response(job: Mapping[str, Any]) -> str:
    message = str(job.get("message") or "")
    if _USER_REQUEST_MARKER in message:
        response = message.rsplit(_USER_REQUEST_MARKER, 1)[1].strip()
    elif "[Owner workspace context" in message:
        raise ValueError("the linked owner reply does not contain its user-message boundary")
    else:
        response = message.strip()
    if not response:
        raise ValueError("the linked owner reply is empty")
    if len(response) > 8000:
        raise ValueError("the linked owner reply exceeds the workspace limit")
    return response


def queue_saved_owner_responses(context: Mapping[str, Any]) -> list[str]:
    """Queue any persisted owner answer whose follow-up run was interrupted."""
    memory = context["memory"]
    from .growth_workflow import queue_growth_check

    queued: list[str] = []
    for initiative in memory.list_strategy_initiatives(limit=None):
        validation = initiative.get("validation") if isinstance(initiative.get("validation"), Mapping) else {}
        response = validation.get("ownerResponse")
        if not isinstance(response, Mapping) or not response.get("text") or response.get("consumedByRunId"):
            continue
        updated_response = dict(response)
        run_id = str(updated_response.get("queuedRunId") or "").strip()
        if not run_id:
            run = queue_growth_check(context, trigger="owner_review")
            run_id = str(run["run_id"])
            updated_response["queuedRunId"] = run_id
            validation = {**validation, "ownerResponse": updated_response}
            memory.update_strategy_initiative(int(initiative["id"]), validation=validation)
        if initiative.get("state") == "waiting_for_owner":
            memory.transition_strategy_initiative(
                int(initiative["id"]), "superseded", validation=validation,
                last_error="The owner answered; Ada is reassessing the recommendation with that information.",
            )
        queued.append(run_id)
    return queued


def complete_growth_owner_response(context: Mapping[str, Any], job: Mapping[str, Any]) -> bool:
    """Persist an answer only for the exact owner-information action tied to this job."""
    memory = context["memory"]
    job_id = int(job["id"])
    initiatives = memory.list_strategy_initiatives(limit=None)
    for action in memory.list_owner_actions(limit=None, job_id=job_id):
        requirement = getattr(action.requirement, "value", action.requirement)
        if action.capability_id != "growth.owner_information" or requirement != "owner_information":
            continue
        source_ref = str(action.source_ref or "")
        prefix = "growth-initiative:"
        if not source_ref.startswith(prefix):
            continue
        try:
            initiative_id = int(source_ref[len(prefix):])
        except ValueError:
            continue
        initiative = next((row for row in initiatives if int(row["id"]) == initiative_id), None)
        if initiative is None or initiative.get("state") != "waiting_for_owner":
            return False
        validation = initiative.get("validation") if isinstance(initiative.get("validation"), Mapping) else {}
        previous = validation.get("ownerResponse")
        if isinstance(previous, Mapping) and int(previous.get("jobId") or 0) != job_id:
            return False
        response = {
            "jobId": job_id,
            "messageId": int(job.get("message_id") or 0) or None,
            "conversationId": int(job.get("conversation_id") or 0) or None,
            "text": _user_response(job),
            "receivedAt": utc_now(),
        }
        memory.update_strategy_initiative(
            initiative_id, validation={**validation, "ownerResponse": response}
        )
        queue_saved_owner_responses(context)
        return True
    return False


def owner_response_evidence(memory: Any, run_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bind queued owner answers into the precise assessment that will consume them."""
    responses: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for initiative in memory.list_strategy_initiatives(limit=None):
        validation = initiative.get("validation") if isinstance(initiative.get("validation"), Mapping) else {}
        response = validation.get("ownerResponse")
        if not isinstance(response, Mapping):
            continue
        if str(response.get("queuedRunId") or "") != str(run_id) or response.get("consumedByRunId"):
            continue
        initiative_id = int(initiative["id"])
        source_ref = f"owner-answer:{initiative_id}"
        responses.append({
            "initiativeId": initiative_id,
            "sourceRef": source_ref,
            "title": str(initiative.get("title") or ""),
            "question": str(initiative.get("summary") or ""),
            "answer": str(response.get("text") or ""),
            "answeredAt": response.get("receivedAt"),
        })
        sources.append({
            "id": f"owner_answer_{initiative_id}",
            "state": "ready",
            "sourceRef": source_ref,
            "observedAt": response.get("receivedAt") or utc_now(),
        })
    return responses, sources


def consume_owner_responses(memory: Any, run_id: str, responses: list[Mapping[str, Any]]) -> None:
    """Mark answers consumed only after their full evidence is durably in the run."""
    initiatives = {
        int(row["id"]): row for row in memory.list_strategy_initiatives(limit=None)
    }
    for item in responses:
        try:
            initiative_id = int(item["initiativeId"])
        except (KeyError, TypeError, ValueError):
            continue
        initiative = initiatives.get(initiative_id)
        if initiative is None:
            continue
        validation = initiative.get("validation") if isinstance(initiative.get("validation"), Mapping) else {}
        response = validation.get("ownerResponse")
        if not isinstance(response, Mapping) or str(response.get("queuedRunId") or "") != str(run_id):
            continue
        consumed_by = str(response.get("consumedByRunId") or "")
        if consumed_by and consumed_by != str(run_id):
            continue
        updated = dict(response)
        updated["consumedByRunId"] = str(run_id)
        memory.update_strategy_initiative(
            initiative_id, validation={**validation, "ownerResponse": updated}
        )
