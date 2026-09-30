"""Durable contracts for owner-gated design operations.

The operation record is deliberately smaller than a design run.  A run keeps
the provider/build detail; an operation records the owner-visible invocation,
its origin, the state it was based on, and the bounded outcome.  This is the
shared seam used by HelloAda and the full website workspace.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from .contracts import ContractError, safe_payload, utc_now


class OperationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperationOrigin(str, Enum):
    OWNER_MESSAGE = "owner_message"
    RECOMMENDATION = "recommendation"


_OPERATION_TRANSITIONS: dict[OperationStatus, frozenset[OperationStatus]] = {
    OperationStatus.QUEUED: frozenset({OperationStatus.RUNNING, OperationStatus.CANCELLED}),
    OperationStatus.RUNNING: frozenset({OperationStatus.DONE, OperationStatus.FAILED, OperationStatus.CANCELLED}),
    OperationStatus.FAILED: frozenset({OperationStatus.QUEUED, OperationStatus.CANCELLED}),
    OperationStatus.DONE: frozenset(),
    OperationStatus.CANCELLED: frozenset(),
}


def validate_operation_transition(
    current: OperationStatus | str,
    target: OperationStatus | str,
) -> None:
    try:
        current_value = OperationStatus(current)
        target_value = OperationStatus(target)
    except (TypeError, ValueError) as exc:
        raise ContractError("operation status is invalid") from exc
    if current_value == target_value:
        return
    if target_value not in _OPERATION_TRANSITIONS[current_value]:
        raise ContractError(
            f"operation cannot transition from {current_value.value} to {target_value.value}"
        )


def _text(value: Any, field_name: str, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field_name} must be non-empty text")
    result = value.strip()
    if len(result) > maximum:
        raise ContractError(f"{field_name} exceeds {maximum} characters")
    return result


def _optional_id(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{field_name} must be a positive integer")
    return value


@dataclass(frozen=True)
class DesignOperation:
    """One durable, owner-visible invocation of a website tool."""

    website_id: str
    tool: str
    origin: OperationOrigin
    input_hash: str
    idempotency_key: str
    status: OperationStatus = OperationStatus.QUEUED
    source_action_id: int | None = None
    conversation_id: int | None = None
    revision_id: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    outcome: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    operation_id: int | None = None
    created_ts: str = field(default_factory=utc_now)
    updated_ts: str = field(default_factory=utc_now)

    @property
    def id(self) -> int | None:
        """Compatibility with the other persisted owner-facing records."""
        return self.operation_id

    def __post_init__(self) -> None:
        object.__setattr__(self, "website_id", _text(self.website_id, "website_id", 180))
        object.__setattr__(self, "tool", _text(self.tool, "tool", 120))
        object.__setattr__(self, "origin", OperationOrigin(self.origin))
        object.__setattr__(self, "status", OperationStatus(self.status))
        object.__setattr__(self, "input_hash", _text(self.input_hash, "input_hash", 128))
        object.__setattr__(self, "idempotency_key", _text(self.idempotency_key, "idempotency_key", 300))
        object.__setattr__(self, "operation_id", _optional_id(self.operation_id, "operation_id"))
        object.__setattr__(self, "source_action_id", _optional_id(self.source_action_id, "source_action_id"))
        object.__setattr__(self, "conversation_id", _optional_id(self.conversation_id, "conversation_id"))
        if self.revision_id is not None:
            object.__setattr__(self, "revision_id", _text(self.revision_id, "revision_id", 180))
        if self.reason is not None:
            object.__setattr__(self, "reason", _text(self.reason, "reason", 500))
        if self.error_code is not None:
            object.__setattr__(self, "error_code", _text(self.error_code, "error_code", 120))
        object.__setattr__(self, "payload", safe_payload(self.payload, max_bytes=100_000))
        object.__setattr__(self, "outcome", safe_payload(self.outcome, max_bytes=100_000))

    def with_transition(self, status: OperationStatus | str, **changes: Any) -> "DesignOperation":
        target = OperationStatus(status)
        validate_operation_transition(self.status, target)
        changes.setdefault("status", target)
        changes.setdefault("updated_ts", utc_now())
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.operation_id,
            "website_id": self.website_id,
            "tool": self.tool,
            "origin": self.origin.value,
            "status": self.status.value,
            "input_hash": self.input_hash,
            "idempotency_key": self.idempotency_key,
            "source_action_id": self.source_action_id,
            "conversation_id": self.conversation_id,
            "revision_id": self.revision_id,
            "reason": self.reason,
            "payload": safe_payload(self.payload),
            "outcome": safe_payload(self.outcome),
            "error_code": self.error_code,
            "created_ts": self.created_ts,
            "updated_ts": self.updated_ts,
        }

    def to_record(self) -> dict[str, Any]:
        record = self.to_dict()
        record["payload"] = json.dumps(record["payload"], ensure_ascii=False, separators=(",", ":"))
        record["outcome"] = json.dumps(record["outcome"], ensure_ascii=False, separators=(",", ":"))
        return record

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "DesignOperation":
        def decode(value: Any, field_name: str) -> dict[str, Any]:
            if value is None or value == "":
                return {}
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ContractError(f"operation {field_name} is not valid JSON") from exc
            if not isinstance(value, Mapping):
                raise ContractError(f"operation {field_name} must be an object")
            return dict(value)

        return cls(
            operation_id=record.get("id"),
            website_id=record["website_id"],
            tool=record["tool"],
            origin=record["origin"],
            status=record["status"],
            input_hash=record["input_hash"],
            idempotency_key=record["idempotency_key"],
            source_action_id=record.get("source_action_id"),
            conversation_id=record.get("conversation_id"),
            revision_id=record.get("revision_id"),
            reason=record.get("reason"),
            payload=decode(record.get("payload"), "payload"),
            outcome=decode(record.get("outcome"), "outcome"),
            error_code=record.get("error_code"),
            created_ts=record["created_ts"],
            updated_ts=record["updated_ts"],
        )


__all__ = [
    "DesignOperation",
    "OperationOrigin",
    "OperationStatus",
    "validate_operation_transition",
]
