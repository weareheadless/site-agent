"""Provider-neutral contracts for owner-facing work.

These contracts are deliberately independent of FastAPI and concrete providers.
They are the boundary shared by application services, scheduled brain policy,
and future MCP adapters.
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar


class ContractError(ValueError):
    """Raised when a contract cannot be safely constructed or transitioned."""


class ActionPriority(str, Enum):
    URGENT = "urgent"
    NORMAL = "normal"
    OPTIONAL = "optional"


class ActionRequirement(str, Enum):
    OWNER_DECISION = "owner_decision"
    OWNER_INFORMATION = "owner_information"
    SUGGESTION = "suggestion"


class ActionState(str, Enum):
    OPEN = "open"
    STARTED = "started"
    WAITING = "waiting"
    COMPLETED = "completed"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"
    STALE = "stale"


class ArtifactKind(str, Enum):
    SITE_CHANGE = "site_change"
    ARTICLE = "article"
    BUSINESS_INFORMATION = "business_information"
    SOCIAL_POST = "social_post"


class EffectClass(str, Enum):
    READ = "read"
    PROPOSAL = "proposal"
    SITE_MUTATION = "site_mutation"
    EXTERNAL_MUTATION = "external_mutation"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    EXPIRED = "expired"
    FAILED = "failed"


class CapabilityAvailability(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ReceiptStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNCERTAIN = "uncertain"


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_key",
    "access_token",
    "authorization",
    "credential",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
)


def _sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _safe_value(value: Any, key: str = "") -> Any:
    if _sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(child_key): _safe_value(child_value, str(child_key)) for child_key, child_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    return str(value)


def safe_payload(payload: Mapping[str, Any] | None, *, max_bytes: int = 100_000) -> dict[str, Any]:
    """Return JSON-safe payload data with credential-shaped values removed."""
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise ContractError("payload must be a JSON object")
    cleaned = _safe_value(payload)
    encoded = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ContractError(f"payload exceeds {max_bytes} bytes")
    return cleaned


def safe_provider_message(message: str | None, *, max_chars: int = 500) -> str:
    """Keep provider failures useful without persisting common secret formats."""
    text = str(message or "")
    text = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret|credential|private[_-]?key)\b\s*[:=]\s*(['\"]?)[^\s,'\"}]+",
        r"\1=[REDACTED]",
        text,
    )
    return text[:max_chars]


_EnumType = TypeVar("_EnumType", bound=Enum)


def _enum_value(enum_type: type[_EnumType], value: _EnumType | str, field_name: str) -> _EnumType:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(str(item.value) for item in enum_type)
        raise ContractError(f"{field_name} must be one of: {allowed}") from exc


def _text(value: str, field_name: str, max_chars: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field_name} must be non-empty text")
    result = value.strip()
    if max_chars is not None and len(result) > max_chars:
        raise ContractError(f"{field_name} exceeds {max_chars} characters")
    return result


def _optional_id(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0:
        raise ContractError(f"{field_name} must be a positive integer")
    return value


def _required_id(value: int, field_name: str) -> int:
    result = _optional_id(value, field_name)
    if result is None:
        raise ContractError(f"{field_name} is required")
    return result


@dataclass(frozen=True)
class OwnerAction:
    capability_id: str
    provider_id: str
    title: str
    summary: str
    action_label: str
    priority: ActionPriority
    requirement: ActionRequirement
    source_ref: str
    dedupe_key: str
    state: ActionState = ActionState.OPEN
    id: int | None = None
    created_ts: str = field(default_factory=utc_now)
    updated_ts: str = field(default_factory=utc_now)
    snoozed_until: str | None = None
    conversation_id: int | None = None
    artifact_id: int | None = None
    approval_id: int | None = None
    draft_id: int | None = None
    payload_version: int = 1
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("capability_id", "provider_id", "source_ref", "dedupe_key"):
            object.__setattr__(self, name, _text(getattr(self, name), name, 180))
        for name in ("title", "summary", "action_label"):
            object.__setattr__(self, name, _text(getattr(self, name), name, 500))
        object.__setattr__(self, "priority", _enum_value(ActionPriority, self.priority, "priority"))
        object.__setattr__(self, "requirement", _enum_value(ActionRequirement, self.requirement, "requirement"))
        object.__setattr__(self, "state", _enum_value(ActionState, self.state, "state"))
        object.__setattr__(self, "id", _optional_id(self.id, "id"))
        for name in ("conversation_id", "artifact_id", "approval_id", "draft_id"):
            object.__setattr__(self, name, _optional_id(getattr(self, name), name))
        if not isinstance(self.payload_version, int) or self.payload_version < 1:
            raise ContractError("payload_version must be a positive integer")
        object.__setattr__(self, "payload", safe_payload(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "title": self.title,
            "summary": self.summary,
            "action_label": self.action_label,
            "priority": self.priority.value,
            "requirement": self.requirement.value,
            "state": self.state.value,
            "source_ref": self.source_ref,
            "dedupe_key": self.dedupe_key,
            "created_ts": self.created_ts,
            "updated_ts": self.updated_ts,
            "snoozed_until": self.snoozed_until,
            "conversation_id": self.conversation_id,
            "artifact_id": self.artifact_id,
            "approval_id": self.approval_id,
            "draft_id": self.draft_id,
            "payload_version": self.payload_version,
            "payload": safe_payload(self.payload),
        }

    def to_owner_dict(self) -> dict[str, Any]:
        """Serialize the small default view; diagnostics stay behind details."""
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "action_label": self.action_label,
            "priority": self.priority.value,
            "state": self.state.value,
            "conversation_id": self.conversation_id,
            "artifact_id": self.artifact_id,
            "approval_id": self.approval_id,
            "draft_id": self.draft_id,
            "details": {
                "capability_id": self.capability_id,
                "provider_id": self.provider_id,
                "requirement": self.requirement.value,
                "source_ref": self.source_ref,
                "dedupe_key": self.dedupe_key,
                "payload_version": self.payload_version,
                "payload": safe_payload(self.payload),
            },
        }

    def to_record(self) -> dict[str, Any]:
        record = self.to_dict()
        record["payload"] = json.dumps(record["payload"], ensure_ascii=False, separators=(",", ":"))
        return record

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "OwnerAction":
        payload = record.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ContractError("owner action payload is not valid JSON") from exc
        return cls(
            id=record.get("id"),
            capability_id=record["capability_id"],
            provider_id=record["provider_id"],
            title=record["title"],
            summary=record["summary"],
            action_label=record["action_label"],
            priority=record["priority"],
            requirement=record["requirement"],
            state=record["state"],
            source_ref=record["source_ref"],
            dedupe_key=record["dedupe_key"],
            created_ts=record["created_ts"],
            updated_ts=record["updated_ts"],
            snoozed_until=record.get("snoozed_until"),
            conversation_id=record.get("conversation_id"),
            artifact_id=record.get("artifact_id"),
            approval_id=record.get("approval_id"),
            draft_id=record.get("draft_id"),
            payload_version=record.get("payload_version", 1),
            payload=payload,
        )


@dataclass(frozen=True)
class Artifact:
    kind: ArtifactKind
    title: str
    summary: str
    renderer: str
    capability_id: str
    provider_id: str
    content_hash: str
    preview_data: dict[str, Any] = field(default_factory=dict)
    source_action_id: int | None = None
    artifact_id: int | None = None
    revision: int = 1
    created_ts: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum_value(ArtifactKind, self.kind, "kind"))
        for name in ("title", "summary", "renderer", "capability_id", "provider_id", "content_hash"):
            object.__setattr__(self, name, _text(getattr(self, name), name, 500))
        object.__setattr__(self, "source_action_id", _optional_id(self.source_action_id, "source_action_id"))
        object.__setattr__(self, "artifact_id", _optional_id(self.artifact_id, "artifact_id"))
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ContractError("revision must be a positive integer")
        object.__setattr__(self, "preview_data", safe_payload(self.preview_data))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.artifact_id,
            "revision": self.revision,
            "kind": self.kind.value,
            "title": self.title,
            "summary": self.summary,
            "renderer": self.renderer,
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "source_action_id": self.source_action_id,
            "content_hash": self.content_hash,
            "preview_data": safe_payload(self.preview_data),
            "created_ts": self.created_ts,
        }

    def to_preview_dict(self) -> dict[str, Any]:
        """Serialize only what an owner-facing renderer needs by default."""
        return {
            "id": self.artifact_id,
            "revision": self.revision,
            "kind": self.kind.value,
            "title": self.title,
            "summary": self.summary,
            "renderer": self.renderer,
            "content_hash": self.content_hash,
            "preview_data": safe_payload(self.preview_data),
            "created_ts": self.created_ts,
            "details": {
                "capability_id": self.capability_id,
                "provider_id": self.provider_id,
                "source_action_id": self.source_action_id,
            },
        }

    def to_record(self) -> dict[str, Any]:
        record = self.to_dict()
        record["preview_data"] = json.dumps(record["preview_data"], ensure_ascii=False, separators=(",", ":"))
        return record

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "Artifact":
        preview_data = record.get("preview_data") or {}
        if isinstance(preview_data, str):
            try:
                preview_data = json.loads(preview_data)
            except json.JSONDecodeError as exc:
                raise ContractError("artifact preview_data is not valid JSON") from exc
        return cls(
            artifact_id=record.get("id"),
            revision=record.get("revision", 1),
            kind=record["kind"],
            title=record["title"],
            summary=record["summary"],
            renderer=record["renderer"],
            capability_id=record["capability_id"],
            provider_id=record["provider_id"],
            source_action_id=record.get("source_action_id"),
            content_hash=record["content_hash"],
            preview_data=preview_data,
            created_ts=record["created_ts"],
        )


@dataclass(frozen=True)
class ApprovalRequest:
    artifact_id: int
    artifact_hash: str
    effect_class: EffectClass
    owner_action_label: str
    provider_id: str
    action_id: int | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    approval_id: int | None = None
    created_ts: str = field(default_factory=utc_now)
    updated_ts: str = field(default_factory=utc_now)
    decided_ts: str | None = None
    owner_feedback: str | None = None
    execution_job_id: int | None = None
    provider_receipt_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _required_id(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "action_id", _optional_id(self.action_id, "action_id"))
        object.__setattr__(self, "approval_id", _optional_id(self.approval_id, "approval_id"))
        object.__setattr__(self, "execution_job_id", _optional_id(self.execution_job_id, "execution_job_id"))
        object.__setattr__(self, "provider_receipt_id", _optional_id(self.provider_receipt_id, "provider_receipt_id"))
        object.__setattr__(self, "artifact_hash", _text(self.artifact_hash, "artifact_hash", 200))
        object.__setattr__(self, "owner_action_label", _text(self.owner_action_label, "owner_action_label", 200))
        object.__setattr__(self, "provider_id", _text(self.provider_id, "provider_id", 180))
        object.__setattr__(self, "effect_class", _enum_value(EffectClass, self.effect_class, "effect_class"))
        object.__setattr__(self, "status", _enum_value(ApprovalStatus, self.status, "status"))
        if self.owner_feedback is not None:
            object.__setattr__(self, "owner_feedback", self.owner_feedback.strip()[:1000])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.approval_id,
            "artifact_id": self.artifact_id,
            "artifact_hash": self.artifact_hash,
            "effect_class": self.effect_class.value,
            "owner_action_label": self.owner_action_label,
            "provider_id": self.provider_id,
            "action_id": self.action_id,
            "status": self.status.value,
            "created_ts": self.created_ts,
            "updated_ts": self.updated_ts,
            "decided_ts": self.decided_ts,
            "owner_feedback": self.owner_feedback,
            "execution_job_id": self.execution_job_id,
            "provider_receipt_id": self.provider_receipt_id,
        }

    def to_owner_dict(self) -> dict[str, Any]:
        return {
            "id": self.approval_id,
            "action_label": self.owner_action_label,
            "status": self.status.value,
            "created_ts": self.created_ts,
            "updated_ts": self.updated_ts,
            "artifact_id": self.artifact_id,
            "details": {
                "effect_class": self.effect_class.value,
                "provider_id": self.provider_id,
                "action_id": self.action_id,
            },
        }

    def to_record(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "ApprovalRequest":
        return cls(
            approval_id=record.get("id"),
            artifact_id=record["artifact_id"],
            artifact_hash=record["artifact_hash"],
            effect_class=record["effect_class"],
            owner_action_label=record["owner_action_label"],
            provider_id=record["provider_id"],
            action_id=record.get("action_id"),
            status=record["status"],
            created_ts=record["created_ts"],
            updated_ts=record["updated_ts"],
            decided_ts=record.get("decided_ts"),
            owner_feedback=record.get("owner_feedback"),
            execution_job_id=record.get("execution_job_id"),
            provider_receipt_id=record.get("provider_receipt_id"),
        )


@dataclass(frozen=True)
class Capability:
    capability_id: str
    provider_id: str
    effect_class: EffectClass
    availability: CapabilityAvailability
    input_contract: dict[str, Any] = field(default_factory=dict)
    result_contract: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 30
    max_result_bytes: int = 1_000_000
    approval_required: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability_id", _text(self.capability_id, "capability_id", 180))
        object.__setattr__(self, "provider_id", _text(self.provider_id, "provider_id", 180))
        object.__setattr__(self, "effect_class", _enum_value(EffectClass, self.effect_class, "effect_class"))
        object.__setattr__(self, "availability", _enum_value(CapabilityAvailability, self.availability, "availability"))
        object.__setattr__(self, "input_contract", safe_payload(self.input_contract))
        object.__setattr__(self, "result_contract", safe_payload(self.result_contract))
        if not isinstance(self.timeout_seconds, int) or self.timeout_seconds <= 0:
            raise ContractError("timeout_seconds must be positive")
        if not isinstance(self.max_result_bytes, int) or self.max_result_bytes <= 0:
            raise ContractError("max_result_bytes must be positive")
        if self.effect_class in {EffectClass.SITE_MUTATION, EffectClass.EXTERNAL_MUTATION} and not self.approval_required:
            raise ContractError("mutating capabilities require explicit approval")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "effect_class": self.effect_class.value,
            "availability": self.availability.value,
            "input_contract": safe_payload(self.input_contract),
            "result_contract": safe_payload(self.result_contract),
            "timeout_seconds": self.timeout_seconds,
            "max_result_bytes": self.max_result_bytes,
            "approval_required": self.approval_required,
        }


@dataclass(frozen=True)
class ProviderReceipt:
    provider_id: str
    capability_id: str
    idempotency_key: str
    status: ReceiptStatus
    action_id: int | None = None
    approval_id: int | None = None
    external_object_id: str | None = None
    external_url: str | None = None
    safe_message: str = ""
    receipt_id: int | None = None
    created_ts: str = field(default_factory=utc_now)
    updated_ts: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("provider_id", "capability_id", "idempotency_key"):
            object.__setattr__(self, name, _text(getattr(self, name), name, 240))
        object.__setattr__(self, "status", _enum_value(ReceiptStatus, self.status, "status"))
        object.__setattr__(self, "action_id", _optional_id(self.action_id, "action_id"))
        object.__setattr__(self, "approval_id", _optional_id(self.approval_id, "approval_id"))
        object.__setattr__(self, "receipt_id", _optional_id(self.receipt_id, "receipt_id"))
        if self.external_object_id is not None:
            object.__setattr__(self, "external_object_id", self.external_object_id[:300])
        if self.external_url is not None:
            object.__setattr__(self, "external_url", safe_provider_message(self.external_url, max_chars=1000))
        object.__setattr__(self, "safe_message", safe_provider_message(self.safe_message))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.receipt_id,
            "provider_id": self.provider_id,
            "capability_id": self.capability_id,
            "action_id": self.action_id,
            "approval_id": self.approval_id,
            "idempotency_key": self.idempotency_key,
            "external_object_id": self.external_object_id,
            "external_url": self.external_url,
            "status": self.status.value,
            "safe_message": self.safe_message,
            "created_ts": self.created_ts,
            "updated_ts": self.updated_ts,
        }

    def to_record(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "ProviderReceipt":
        return cls(
            receipt_id=record.get("id"),
            provider_id=record["provider_id"],
            capability_id=record["capability_id"],
            action_id=record.get("action_id"),
            approval_id=record.get("approval_id"),
            idempotency_key=record["idempotency_key"],
            external_object_id=record.get("external_object_id"),
            external_url=record.get("external_url"),
            status=record["status"],
            safe_message=record.get("safe_message") or "",
            created_ts=record["created_ts"],
            updated_ts=record["updated_ts"],
        )


_ACTION_TRANSITIONS: dict[ActionState, frozenset[ActionState]] = {
    ActionState.OPEN: frozenset({ActionState.STARTED, ActionState.WAITING, ActionState.COMPLETED, ActionState.SNOOZED, ActionState.DISMISSED, ActionState.STALE}),
    ActionState.STARTED: frozenset({ActionState.WAITING, ActionState.COMPLETED, ActionState.STALE}),
    ActionState.WAITING: frozenset({ActionState.STARTED, ActionState.COMPLETED, ActionState.STALE}),
    ActionState.SNOOZED: frozenset({ActionState.OPEN, ActionState.COMPLETED, ActionState.DISMISSED, ActionState.STALE}),
    ActionState.COMPLETED: frozenset(),
    ActionState.DISMISSED: frozenset(),
    ActionState.STALE: frozenset(),
}

_APPROVAL_TRANSITIONS: dict[ApprovalStatus, frozenset[ApprovalStatus]] = {
    ApprovalStatus.PENDING: frozenset({ApprovalStatus.APPROVED, ApprovalStatus.DECLINED, ApprovalStatus.EXPIRED, ApprovalStatus.FAILED}),
    ApprovalStatus.APPROVED: frozenset({ApprovalStatus.FAILED}),
    ApprovalStatus.DECLINED: frozenset(),
    ApprovalStatus.EXPIRED: frozenset(),
    ApprovalStatus.FAILED: frozenset(),
}


def validate_action_transition(current: ActionState | str, target: ActionState | str) -> None:
    current_value = _enum_value(ActionState, current, "current state")
    target_value = _enum_value(ActionState, target, "target state")
    if current_value == target_value:
        return
    if target_value not in _ACTION_TRANSITIONS[current_value]:
        raise ContractError(f"owner action cannot transition from {current_value.value} to {target_value.value}")


def validate_approval_transition(current: ApprovalStatus | str, target: ApprovalStatus | str) -> None:
    current_value = _enum_value(ApprovalStatus, current, "current status")
    target_value = _enum_value(ApprovalStatus, target, "target status")
    if current_value == target_value:
        return
    if target_value not in _APPROVAL_TRANSITIONS[current_value]:
        raise ContractError(f"approval cannot transition from {current_value.value} to {target_value.value}")


__all__ = [
    "ActionPriority",
    "ActionRequirement",
    "ActionState",
    "ApprovalRequest",
    "ApprovalStatus",
    "Artifact",
    "ArtifactKind",
    "Capability",
    "CapabilityAvailability",
    "ContractError",
    "EffectClass",
    "OwnerAction",
    "ProviderReceipt",
    "ReceiptStatus",
    "safe_payload",
    "safe_provider_message",
    "utc_now",
    "validate_action_transition",
    "validate_approval_transition",
]
