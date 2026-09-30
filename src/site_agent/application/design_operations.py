"""Owner-gated website operation service.

This is the first shared control-plane seam for HelloAda and the full website
workspace. Recommendations are existing ``OwnerAction`` records with a typed
payload; operations are the durable invocation records that preserve where a
request came from and which website state it was based on.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from ..core.contracts import (
    ActionPriority,
    ActionRequirement,
    ActionState,
    ArtifactKind,
    ContractError,
    OwnerAction,
    safe_payload,
)
from ..core.design_contracts import canonical_hash
from ..core.design_operation_contracts import (
    DesignOperation,
    OperationOrigin,
    OperationStatus,
)
from .actions import OwnerActionService


class DesignOperationError(ValueError):
    """A recommendation or operation cannot be accepted safely."""


RECOMMENDATION_SCHEMA_VERSION = 1
RECOMMENDATION_KIND = "design_recommendation"
DESIGN_TOOLS = frozenset({
    "design.direction",
    "design.build",
    "design.change",
    "design.page",
    "design.deploy",
    "version.restore",
    "launch.integrate",
})


def _website_id(value: Any) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 180:
        raise DesignOperationError("website_id is invalid")
    return result


def _tool(value: Any) -> str:
    result = str(value or "").strip().lower()
    if result not in DESIGN_TOOLS:
        raise DesignOperationError(f"unsupported design tool: {result or '(empty)'}")
    return result


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DesignOperationError(f"{name} must be an object")
    try:
        return safe_payload(dict(value))
    except ContractError as exc:
        raise DesignOperationError(str(exc)) from exc


class DesignOperationService:
    """Create recommendations and durable operation records for one website."""

    def __init__(self, memory, actions: OwnerActionService | None = None, *, website_id: str) -> None:
        self.memory = memory
        self.actions = actions or OwnerActionService(memory)
        self.website_id = _website_id(website_id)

    def recommend(
        self,
        *,
        tool: str,
        title: str,
        reason: str,
        scope: Mapping[str, Any],
        bound_state: Mapping[str, Any],
        source_ref: str,
        priority: ActionPriority | str = ActionPriority.NORMAL,
        action_label: str = "Approve this step",
        conversation_id: int | None = None,
        draft_id: int | None = None,
    ) -> OwnerAction:
        """Create or reuse an owner recommendation for a bounded tool call."""
        normalized_tool = _tool(tool)
        proposed_scope = _object(scope, "proposed_scope")
        bound = _object(bound_state, "bound_state")
        try:
            bound_state_hash = canonical_hash(bound)
            scope_hash = canonical_hash(proposed_scope)
        except ContractError as exc:
            raise DesignOperationError(str(exc)) from exc

        payload = {
            "schema_version": RECOMMENDATION_SCHEMA_VERSION,
            "kind": RECOMMENDATION_KIND,
            "website_id": self.website_id,
            "proposed_tool": normalized_tool,
            "proposed_scope": proposed_scope,
            "bound_state": bound,
            "bound_state_hash": bound_state_hash,
        }
        action = OwnerAction(
            capability_id=f"website.{normalized_tool}",
            provider_id="site-agent",
            title=title,
            summary=reason,
            action_label=action_label,
            priority=priority,
            requirement=ActionRequirement.SUGGESTION,
            source_ref=source_ref,
            dedupe_key=(
                f"recommendation:{self.website_id}:{normalized_tool}:"
                f"{bound_state_hash}:{scope_hash}"
            ),
            conversation_id=conversation_id,
            draft_id=draft_id,
            payload=payload,
        )
        try:
            return self.actions.create(action, reuse_terminal=True)
        except (ContractError, sqlite3.IntegrityError) as exc:
            raise DesignOperationError(str(exc)) from exc

    def recommendation(self, action_id: int) -> OwnerAction:
        action = self.actions.get(action_id)
        if action is None:
            raise DesignOperationError(f"no such recommendation: {action_id}")
        payload = action.payload
        if payload.get("kind") != RECOMMENDATION_KIND:
            raise DesignOperationError(f"owner action {action_id} is not a design recommendation")
        if payload.get("website_id") != self.website_id:
            raise DesignOperationError("recommendation belongs to another website")
        return action

    def recommendation_view(self, action: OwnerAction) -> dict[str, Any]:
        """Return the inline owner view without exposing provider internals."""
        action = self.recommendation(action.id or 0)
        payload = action.payload
        return {
            **action.to_owner_dict(),
            "recommendation": {
                "website_id": self.website_id,
                "proposed_tool": payload.get("proposed_tool"),
                "proposed_scope": _object(payload.get("proposed_scope"), "proposed_scope"),
                "bound_state": _object(payload.get("bound_state"), "bound_state"),
                "bound_state_hash": payload.get("bound_state_hash"),
            },
        }

    def list_recommendations(self, *, limit: int = 50) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for action in self.memory.list_owner_actions(limit=max(1, min(int(limit), 100))):
            if action.payload.get("kind") != RECOMMENDATION_KIND:
                continue
            if action.payload.get("website_id") != self.website_id:
                continue
            result.append(self.recommendation_view(action))
        return result

    def accept(
        self,
        action_id: int,
        *,
        current_state: Mapping[str, Any] | None = None,
        conversation_id: int | None = None,
    ) -> DesignOperation:
        """Accept a recommendation exactly once and create its operation."""
        action = self.recommendation(action_id)
        existing = self.memory.find_operation_by_source_action(self.website_id, action_id)
        if existing is not None:
            if existing.status is OperationStatus.FAILED:
                # A failed operation is still the same owner-approved,
                # immutable request. Re-approving it retries the durable
                # invocation instead of creating a duplicate operation. This
                # matters when provisioning/configuration was repaired after
                # the first attempt.
                try:
                    retry_count = int(existing.payload.get("retry_count") or 0) + 1
                except (AttributeError, TypeError, ValueError):
                    retry_count = 1
                try:
                    retried = self.memory.transition_operation(
                        existing.id or 0,
                        OperationStatus.QUEUED,
                        expected_status=OperationStatus.FAILED,
                        reason="Retrying the previously failed owner-approved operation.",
                        payload={**existing.payload, "retry_count": retry_count},
                        outcome={},
                        error_code=None,
                    )
                except (ContractError, ValueError) as exc:
                    raise DesignOperationError(str(exc)) from exc
                if retried is None:
                    raise DesignOperationError("operation could not be retried")
                return retried
            return existing
        if action.state in {ActionState.DISMISSED, ActionState.STALE}:
            raise DesignOperationError(f"recommendation is {action.state.value}")
        if action.state is ActionState.COMPLETED:
            raise DesignOperationError("recommendation is completed without an operation")
        bound = _object(action.payload.get("bound_state"), "bound_state")
        if current_state is not None and not self._matches_bound_state(bound, current_state):
            if action.state in {ActionState.OPEN, ActionState.WAITING, ActionState.SNOOZED}:
                self.actions.mark_stale(action_id)
            raise DesignOperationError("recommendation is stale: bound website state changed")

        proposed_tool = _tool(action.payload.get("proposed_tool"))
        proposed_scope = _object(action.payload.get("proposed_scope"), "proposed_scope")
        self._validate_tool_gate(proposed_tool, proposed_scope, bound)

        if action.state is ActionState.SNOOZED:
            self.actions.transition(action_id, ActionState.OPEN)
        if action.state in {ActionState.OPEN, ActionState.WAITING, ActionState.SNOOZED}:
            action = self.actions.start(action_id, conversation_id=conversation_id)
        elif action.state is not ActionState.STARTED:
            raise DesignOperationError(f"recommendation cannot be accepted from {action.state.value}")

        input_hash = canonical_hash({
            "website_id": self.website_id,
            "tool": proposed_tool,
            "scope": proposed_scope,
            "bound_state": bound,
        })
        idempotency_key = f"recommendation:{self.website_id}:{action_id}:{input_hash}"
        operation = DesignOperation(
            website_id=self.website_id,
            tool=proposed_tool,
            origin=OperationOrigin.RECOMMENDATION,
            input_hash=input_hash,
            idempotency_key=idempotency_key,
            source_action_id=action_id,
            conversation_id=conversation_id or action.conversation_id,
            reason=action.summary,
            payload={
                "scope": proposed_scope,
                "bound_state": bound,
                "bound_state_hash": action.payload.get("bound_state_hash"),
            },
        )
        try:
            return self.memory.create_operation(operation)
        except sqlite3.IntegrityError:
            existing = self.memory.find_operation_by_source_action(self.website_id, action_id)
            if existing is not None:
                return existing
            existing = self.memory.find_operation_by_idempotency(self.website_id, idempotency_key)
            if existing is not None:
                return existing
            raise

    def queue_owner_request(
        self,
        *,
        tool: str,
        scope: Mapping[str, Any],
        bound_state: Mapping[str, Any],
        source_ref: str,
        conversation_id: int | None = None,
        reason: str | None = None,
    ) -> DesignOperation:
        """Queue an explicitly bounded owner request without a recommendation."""
        normalized_tool = _tool(tool)
        proposed_scope = _object(scope, "scope")
        bound = _object(bound_state, "bound_state")
        input_hash = canonical_hash({
            "website_id": self.website_id,
            "tool": normalized_tool,
            "scope": proposed_scope,
            "bound_state": bound,
            "source_ref": str(source_ref).strip(),
        })
        idempotency_key = f"owner:{self.website_id}:{input_hash}"
        operation = DesignOperation(
            website_id=self.website_id,
            tool=normalized_tool,
            origin=OperationOrigin.OWNER_MESSAGE,
            input_hash=input_hash,
            idempotency_key=idempotency_key,
            conversation_id=conversation_id,
            reason=reason or str(source_ref).strip(),
            payload={"scope": proposed_scope, "bound_state": bound, "source_ref": source_ref},
        )
        try:
            return self.memory.create_operation(operation)
        except sqlite3.IntegrityError:
            existing = self.memory.find_operation_by_idempotency(self.website_id, idempotency_key)
            if existing is not None:
                return existing
            raise

    def get(self, operation_id: int) -> DesignOperation:
        operation = self.memory.get_operation(operation_id)
        if operation is None or operation.website_id != self.website_id:
            raise DesignOperationError(f"no such operation: {operation_id}")
        return operation

    def list(self, *, status: OperationStatus | str | None = None, limit: int = 100) -> list[DesignOperation]:
        return self.memory.list_operations(website_id=self.website_id, status=status, limit=limit)

    def start(self, operation_id: int) -> DesignOperation:
        operation = self.get(operation_id)
        if operation.status is OperationStatus.RUNNING:
            return operation
        if operation.status is not OperationStatus.QUEUED:
            raise DesignOperationError(
                f"operation cannot transition from {operation.status.value} to running"
            )
        try:
            next_operation = self.memory.transition_operation(
                operation_id,
                OperationStatus.RUNNING,
                expected_status=OperationStatus.QUEUED,
            )
        except ContractError as exc:
            raise DesignOperationError(str(exc)) from exc
        if next_operation is None:
            raise DesignOperationError(f"no such operation: {operation_id}")
        return next_operation

    def complete(
        self,
        operation_id: int,
        *,
        outcome: Mapping[str, Any] | None = None,
        revision_id: str | None = None,
    ) -> DesignOperation:
        operation = self.get(operation_id)
        if operation.status is OperationStatus.DONE:
            return operation
        try:
            next_operation = self.memory.transition_operation(
                operation_id,
                OperationStatus.DONE,
                expected_status=OperationStatus.RUNNING,
                outcome=dict(outcome or {}),
                revision_id=revision_id,
            )
        except (ContractError, ValueError) as exc:
            raise DesignOperationError(str(exc)) from exc
        if next_operation is None:
            raise DesignOperationError(f"no such operation: {operation_id}")
        if next_operation.source_action_id is not None:
            action = self.actions.get(next_operation.source_action_id)
            if action is not None and action.state in {ActionState.STARTED, ActionState.WAITING}:
                self.actions.complete(action.id)  # type: ignore[arg-type]
        return next_operation

    def fail(self, operation_id: int, *, error_code: str, reason: str) -> DesignOperation:
        operation = self.get(operation_id)
        if operation.status is OperationStatus.FAILED:
            return operation
        try:
            next_operation = self.memory.transition_operation(
                operation_id,
                OperationStatus.FAILED,
                expected_status=OperationStatus.RUNNING,
                error_code=error_code,
                reason=reason,
            )
        except (ContractError, ValueError) as exc:
            raise DesignOperationError(str(exc)) from exc
        if next_operation is None:
            raise DesignOperationError(f"no such operation: {operation_id}")
        if next_operation.source_action_id is not None:
            action = self.actions.get(next_operation.source_action_id)
            if action is not None and action.state is ActionState.STARTED:
                self.actions.wait(action.id)  # type: ignore[arg-type]
        return next_operation

    def dismiss(self, action_id: int) -> OwnerAction:
        self.recommendation(action_id)
        return self.actions.dismiss(action_id)

    def _validate_tool_gate(
        self,
        tool: str,
        scope: Mapping[str, Any],
        bound: Mapping[str, Any],
    ) -> None:
        """Enforce the first deterministic tool gates before owner state changes."""
        if tool == "design.build":
            direction_hash = str(scope.get("direction_hash") or "").strip()
            raw_artifact_id = scope.get("direction_artifact_id")
            try:
                artifact_id = int(raw_artifact_id)
            except (TypeError, ValueError) as exc:
                raise DesignOperationError(
                    "direction_not_approved: an approved design direction is required"
                ) from exc
            if artifact_id < 1 or not direction_hash:
                raise DesignOperationError(
                    "direction_not_approved: an approved design direction is required"
                )

            artifact = self.memory.get_artifact(artifact_id)
            if (
                artifact is None
                or artifact.kind is not ArtifactKind.DESIGN_DIRECTION
                or artifact.content_hash != direction_hash
            ):
                raise DesignOperationError(
                    "direction_not_approved: the approved direction artifact is missing"
                )

            try:
                confirmed_revision = int(scope.get("confirmed_revision"))
                artifact_revision = int(artifact.preview_data.get("confirmed_revision"))
            except (TypeError, ValueError) as exc:
                raise DesignOperationError(
                    "direction_not_approved: the direction is not bound to an intake revision"
                ) from exc
            if (
                confirmed_revision < 1
                or artifact_revision != confirmed_revision
                or bound.get("intake_revision") != confirmed_revision
                or bound.get("direction_hash") != direction_hash
            ):
                raise DesignOperationError(
                    "direction_outdated: the direction does not match the confirmed intake revision"
                )

        if tool in {"design.change", "design.page", "design.deploy"}:
            revision_id = bound.get("revision_id")
            if revision_id in (None, "", 0) or not str(revision_id).strip():
                raise DesignOperationError(
                    "no_current_revision: this operation requires a current revision"
                )

    @staticmethod
    def _matches_bound_state(bound: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
        try:
            actual = safe_payload(dict(current))
        except ContractError as exc:
            raise DesignOperationError(str(exc)) from exc
        return all(actual.get(key) == value for key, value in bound.items())


__all__ = [
    "DESIGN_TOOLS",
    "DesignOperationError",
    "DesignOperationService",
]
