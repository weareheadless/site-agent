"""Home read model for the owner-facing action inbox."""

from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass
from typing import Any

from ..core.contracts import (
    ActionPriority,
    ActionRequirement,
    ActionState,
    ApprovalStatus,
    OwnerAction,
)


@dataclass(frozen=True)
class HandlingSummary:
    active_count: int
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active_count > 0,
            "active_count": self.active_count,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class HomeResult:
    needs_you: tuple[OwnerAction, ...]
    suggestions: tuple[OwnerAction, ...]
    handling: HandlingSummary
    generated_ts: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "needs_you": [action.to_owner_dict() for action in self.needs_you],
            "ada_suggests": [action.to_owner_dict() for action in self.suggestions],
            "ada_is_handling": self.handling.to_dict(),
            "everything_is_handled": not self.needs_you,
            "generated_ts": self.generated_ts,
        }


class HomeService:
    """Compose persisted actions with compatibility views of current records."""

    _priority_order = {
        ActionPriority.URGENT: 0,
        ActionPriority.NORMAL: 1,
        ActionPriority.OPTIONAL: 2,
    }

    def __init__(self, memory):
        self.memory = memory

    def snapshot(self, needs_limit: int = 4, suggestion_limit: int = 3) -> HomeResult:
        needs_limit = max(0, min(int(needs_limit), 20))
        suggestion_limit = max(0, min(int(suggestion_limit), 20))
        now = datetime.datetime.now(datetime.timezone.utc)
        persisted = self.memory.list_owner_actions(limit=200)
        visible = [action for action in persisted if self._visible(action, now)]
        known_refs = {action.source_ref for action in persisted}
        visible.extend(self._pending_approval_actions(known_refs))
        visible.extend(self._pending_draft_actions(known_refs))
        visible.extend(self._legacy_suggestion_actions(known_refs))

        needs = [
            action for action in visible
            if action.requirement != ActionRequirement.SUGGESTION
            and action.state != ActionState.STARTED
        ]
        suggestions = [
            action for action in visible
            if action.requirement == ActionRequirement.SUGGESTION
            and action.state != ActionState.STARTED
        ]
        needs = self._sort(needs)[:needs_limit]
        suggestions = self._sort(suggestions)[:suggestion_limit]

        active_jobs = self.memory.list_active_chat_jobs(limit=20)
        active_actions = sum(action.state == ActionState.STARTED for action in persisted)
        active_count = len(active_jobs) + active_actions
        if active_count:
            summary = f"Ada is working on {active_count} thing{'s' if active_count != 1 else ''} in the background."
        else:
            summary = "Ada is keeping an eye on your website."
        return HomeResult(
            needs_you=tuple(needs),
            suggestions=tuple(suggestions),
            handling=HandlingSummary(active_count=active_count, summary=summary),
            generated_ts=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        )

    @classmethod
    def _visible(cls, action: OwnerAction, now: datetime.datetime) -> bool:
        if action.state in {ActionState.COMPLETED, ActionState.DISMISSED, ActionState.STALE, ActionState.STARTED}:
            return False
        if action.state != ActionState.SNOOZED:
            return True
        if not action.snoozed_until:
            return False
        try:
            deadline = datetime.datetime.fromisoformat(action.snoozed_until.replace("Z", "+00:00"))
        except ValueError:
            return False
        return deadline <= now

    @classmethod
    def _sort(cls, actions: list[OwnerAction]) -> list[OwnerAction]:
        return sorted(
            actions,
            key=lambda action: (cls._priority_order[action.priority], action.updated_ts),
        )

    def _pending_approval_actions(self, known_refs: set[str]) -> list[OwnerAction]:
        result: list[OwnerAction] = []
        for approval in self.memory.list_approval_requests(status=ApprovalStatus.PENDING, limit=100):
            source_ref = f"approval:{approval.approval_id}"
            if source_ref in known_refs:
                continue
            artifact = self.memory.get_artifact(approval.artifact_id)
            title = f"Review {artifact.title}" if artifact else "Review a prepared change"
            result.append(
                OwnerAction(
                    capability_id="review.approval",
                    provider_id=approval.provider_id,
                    title=title,
                    summary="Nothing changes until you decide what to do.",
                    action_label=approval.owner_action_label,
                    priority=ActionPriority.NORMAL,
                    requirement=ActionRequirement.OWNER_DECISION,
                    source_ref=source_ref,
                    dedupe_key=source_ref,
                    approval_id=approval.approval_id,
                    artifact_id=approval.artifact_id,
                    payload={"approval_id": approval.approval_id, "artifact_id": approval.artifact_id},
                )
            )
        return result

    def _pending_draft_actions(self, known_refs: set[str]) -> list[OwnerAction]:
        result: list[OwnerAction] = []
        for draft in self.memory.list_drafts(status="pending", limit=100):
            if draft["kind"] == "report":
                continue
            source_ref = f"draft:{draft['id']}"
            if source_ref in known_refs:
                continue
            result.append(
                OwnerAction(
                    capability_id="review.site_change",
                    provider_id="site-agent",
                    title=f"Review {draft['title'] or 'the prepared website change'}",
                    summary="Ada prepared this change. Nothing is published until you decide.",
                    action_label="Review change",
                    priority=ActionPriority.NORMAL,
                    requirement=ActionRequirement.OWNER_DECISION,
                    source_ref=source_ref,
                    dedupe_key=source_ref,
                    draft_id=draft["id"],
                    payload={"draft_id": draft["id"], "kind": draft["kind"]},
                    created_ts=draft["created_ts"],
                    updated_ts=draft["updated_ts"],
                )
            )
        return result

    def _legacy_suggestion_actions(self, known_refs: set[str]) -> list[OwnerAction]:
        stored = self.memory.kv_get("strategist_cards") or {}
        cards = stored.get("cards") if isinstance(stored, dict) else []
        result: list[OwnerAction] = []
        for card in cards or []:
            if not isinstance(card, dict):
                continue
            title = str(card.get("title") or "A possible next step").strip()
            action = str(card.get("action") or "Talk with Ada about this").strip()
            why = str(card.get("why") or "").strip()
            digest = hashlib.sha256(f"{title}\0{action}".encode()).hexdigest()[:16]
            source_ref = f"strategist:{digest}"
            if source_ref in known_refs:
                continue
            result.append(
                OwnerAction(
                    capability_id="content.suggestion",
                    provider_id="site-agent",
                    title=title,
                    summary=action,
                    action_label="Ask Ada to help",
                    priority=ActionPriority.OPTIONAL,
                    requirement=ActionRequirement.SUGGESTION,
                    source_ref=source_ref,
                    dedupe_key=source_ref,
                    payload={"why": why, "source": "strategist_cards"},
                )
            )
        return result
