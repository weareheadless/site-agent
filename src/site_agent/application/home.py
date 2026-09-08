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
from ..brain.self_model import current_self


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
class InnerLifeEntry:
    source: str
    text: str
    ts: str
    mood: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "text": self.text,
            "ts": self.ts,
            "mood": self.mood,
        }


@dataclass(frozen=True)
class InnerSelfSummary:
    description: str
    tendencies: tuple[str, ...]
    open_questions: tuple[str, ...]
    updated_ts: str
    last_shift: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "tendencies": list(self.tendencies),
            "open_questions": list(self.open_questions),
            "updated_ts": self.updated_ts,
            "last_shift": self.last_shift,
        }


@dataclass(frozen=True)
class InnerLifeSummary:
    mood: str
    themes: tuple[str, ...]
    thought: InnerLifeEntry | None
    dream: InnerLifeEntry | None
    awakening: InnerLifeEntry | None
    activity: InnerLifeEntry | None
    self_understanding: InnerSelfSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "mood": self.mood,
            "themes": list(self.themes),
            "thought": self.thought.to_dict() if self.thought else None,
            "dream": self.dream.to_dict() if self.dream else None,
            "awakening": self.awakening.to_dict() if self.awakening else None,
            "activity": self.activity.to_dict() if self.activity else None,
            "self_understanding": self.self_understanding.to_dict(),
        }


@dataclass(frozen=True)
class HomeResult:
    needs_you: tuple[OwnerAction, ...]
    suggestions: tuple[OwnerAction, ...]
    handling: HandlingSummary
    inner_life: InnerLifeSummary
    generated_ts: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "needs_you": [action.to_owner_dict() for action in self.needs_you],
            "ada_suggests": [action.to_owner_dict() for action in self.suggestions],
            "ada_is_handling": self.handling.to_dict(),
            "inner_life": self.inner_life.to_dict(),
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
        generated_ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        return HomeResult(
            needs_you=tuple(needs),
            suggestions=tuple(suggestions),
            handling=HandlingSummary(active_count=active_count, summary=summary),
            inner_life=self._inner_life(),
            generated_ts=generated_ts,
        )

    def _inner_life(self) -> InnerLifeSummary:
        """Return the owner-requested inner-life view without private notes."""
        inner_rows = self.memory.recent_observations(source="inner_voice", limit=50)
        scheduled_rows = [row for row in inner_rows if not (row.get("meta") or {}).get("role")]
        latest_scheduled = scheduled_rows[0] if scheduled_rows else None
        thought_row = next(
            (
                row
                for row in scheduled_rows
                if not (row.get("meta") or {}).get("private")
            ),
            None,
        )
        thought = self._inner_life_entry(thought_row, "inner_voice")

        saved_mood = self.memory.kv_get("mood")
        mood = str(saved_mood.get("current") or "").strip() if isinstance(saved_mood, dict) else ""
        # A private scheduled thought can update the shared mood KV; do not let
        # that state leak when the private thought is the latest one.
        if latest_scheduled and (latest_scheduled.get("meta") or {}).get("private"):
            mood = ""

        saved_themes = self.memory.kv_get("themes", [])
        themes = tuple(
            str(theme).strip()[:48]
            for theme in saved_themes[:6]
            if str(theme).strip()
        ) if isinstance(saved_themes, list) else ()

        dream_rows = self.memory.recent_observations(source="dream", limit=1)
        awakening_rows = self.memory.recent_observations(source="awaken", limit=1)
        dream = self._inner_life_entry(dream_rows[0] if dream_rows else None, "dream")
        awakening = self._inner_life_entry(awakening_rows[0] if awakening_rows else None, "awaken")
        if awakening is None:
            meaning = self.memory.kv_get("last_dream_meaning")
            if isinstance(meaning, str) and meaning.strip():
                awakening = InnerLifeEntry(source="memory", text=meaning.strip(), ts="")

        state = current_self(self.memory)
        shifts = self.memory.recent_observations(source="identity_shift", limit=1)
        last_shift = str(shifts[0].get("text") or "").strip() if shifts else ""
        self_understanding = InnerSelfSummary(
            description=state["self_description"],
            tendencies=tuple(state["persistent_tendencies"]),
            open_questions=tuple(state["open_questions"]),
            updated_ts=state["updated_ts"],
            last_shift=last_shift,
        )

        activity = None
        for row in self.memory.recent_actions(limit=30):
            if row.get("kind") in {"job", "job_error", "health", "inner_voice", "dream", "awaken"}:
                continue
            detail = str(row.get("detail") or "").strip()
            if detail:
                kind = str(row.get("kind") or "activity").strip()
                activity = InnerLifeEntry(
                    source="action",
                    text=f"{kind} - {detail}",
                    ts=str(row.get("ts") or ""),
                )
                break

        return InnerLifeSummary(
            mood=mood,
            themes=themes,
            thought=thought,
            dream=dream,
            awakening=awakening,
            activity=activity,
            self_understanding=self_understanding,
        )

    @staticmethod
    def _inner_life_entry(row: dict[str, Any] | None, source: str) -> InnerLifeEntry | None:
        if not isinstance(row, dict):
            return None
        text = str(row.get("text") or "").strip()
        if not text:
            return None
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        return InnerLifeEntry(
            source=source,
            text=text,
            ts=str(row.get("ts") or ""),
            mood=str(meta.get("mood") or "").strip(),
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
            if draft["kind"] in {"report", "seo_report"}:
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
