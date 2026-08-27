"""Owner-action application service.

The service owns deduplication and state transitions so HTTP and future MCP
adapters do not need to know how owner actions are stored.
"""

from __future__ import annotations

import sqlite3

from ..core.contracts import (
    ActionState,
    Capability,
    CapabilityAvailability,
    ContractError,
    OwnerAction,
)


class ActionServiceError(RuntimeError):
    pass


class OwnerActionService:
    def __init__(self, memory):
        self.memory = memory

    def create(self, action: OwnerAction, capability: Capability | None = None) -> OwnerAction:
        if capability is not None:
            self.ensure_capability(capability, action)
        existing = self.memory.find_owner_action(action.dedupe_key)
        if existing is not None:
            return existing
        try:
            return self.memory.create_owner_action(action)
        except sqlite3.IntegrityError:
            # Another request may have won the dedupe race.
            existing = self.memory.find_owner_action(action.dedupe_key)
            if existing is not None:
                return existing
            raise

    def get(self, action_id: int) -> OwnerAction | None:
        return self.memory.get_owner_action(action_id)

    def transition(
        self,
        action_id: int,
        state: ActionState | str,
        *,
        snoozed_until: str | None = None,
    ) -> OwnerAction:
        action = self.memory.transition_owner_action(action_id, state, snoozed_until=snoozed_until)
        if action is None:
            raise KeyError(f"no such owner action: {action_id}")
        return action

    def start(self, action_id: int, conversation_id: int | None = None) -> OwnerAction:
        existing = self.get(action_id)
        if existing is None:
            raise KeyError(f"no such owner action: {action_id}")
        if conversation_id is None:
            conversation_id = existing.conversation_id
        if conversation_id is not None and self.memory.get_conversation(conversation_id) is None:
            raise KeyError(f"no such conversation: {conversation_id}")
        action = self.transition(action_id, ActionState.STARTED)
        if conversation_id is None:
            conversation_id = self.memory.create_conversation(action.title)
            self.memory.add_message(
                conversation_id,
                "system",
                f"Context from Ada's suggestion:\n{action.title}\n{action.summary}",
            )
        action = self.memory.link_owner_action(action.id, conversation_id=conversation_id)
        return action

    def snooze(self, action_id: int, until: str) -> OwnerAction:
        return self.transition(action_id, ActionState.SNOOZED, snoozed_until=until)

    def dismiss(self, action_id: int) -> OwnerAction:
        return self.transition(action_id, ActionState.DISMISSED)

    def complete(self, action_id: int) -> OwnerAction:
        return self.transition(action_id, ActionState.COMPLETED)

    def mark_stale(self, action_id: int) -> OwnerAction:
        return self.transition(action_id, ActionState.STALE)

    def reconcile(
        self,
        *,
        draft_id: int | None = None,
        artifact_id: int | None = None,
        approval_id: int | None = None,
    ) -> list[OwnerAction]:
        """Complete active actions whose prepared work has finished."""
        if draft_id is None and artifact_id is None and approval_id is None:
            return []
        matched: list[OwnerAction] = []
        for action in self.memory.list_owner_actions(limit=500):
            if draft_id is not None and action.draft_id != draft_id:
                continue
            if artifact_id is not None and action.artifact_id != artifact_id:
                continue
            if approval_id is not None and action.approval_id != approval_id:
                continue
            if action.state in {ActionState.OPEN, ActionState.STARTED, ActionState.WAITING, ActionState.SNOOZED}:
                matched.append(self.complete(action.id))
        return matched

    @staticmethod
    def ensure_capability(capability: Capability, action: OwnerAction | None = None) -> None:
        if capability.availability == CapabilityAvailability.UNAVAILABLE:
            raise ActionServiceError(f"capability unavailable: {capability.capability_id}")
        if action is not None and action.capability_id != capability.capability_id:
            raise ContractError("owner action and capability identifiers do not match")
