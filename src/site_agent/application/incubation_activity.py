"""Owner-safe activity projection for one customer incubation."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any, Callable

from ..core.contracts import ContractError, safe_payload, safe_provider_message, utc_now
from ..core.incubation_contracts import IncubationActivity
from ..core.memory import Memory


class IncubationActivityError(ValueError):
    """An activity event could not be safely persisted or projected."""


_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d(). -]{7,}\d)(?!\w)")
_PATH = re.compile(r"(?:^|\s)(?:/|[A-Za-z]:[\\/])[^\s]+")
_DOMAIN = re.compile(r"(?<![@\w])(?:[a-z0-9-]+\.)+(?:com|org|net|io|co|dev|app|test)(?!\w)", re.IGNORECASE)


def _redact_text(value: str) -> str:
    result = safe_provider_message(value, max_chars=2_000)
    result = _URL.sub("[redacted URL]", result)
    result = _EMAIL.sub("[redacted email]", result)
    result = _PHONE.sub("[redacted phone]", result)
    result = _PATH.sub(" [redacted path]", result)
    result = _DOMAIN.sub("[redacted domain]", result)
    return " ".join(result.split())


def _redact_detail(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _redact_detail(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact_detail(child) for child in value]
    if isinstance(value, tuple):
        return [_redact_detail(child) for child in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


class IncubationActivityService:
    """Create and read durable activity without exposing provider payloads."""

    def __init__(self, memory: Memory, *, now: Callable[[], str] = utc_now) -> None:
        self.memory = memory
        self.now = now

    def record(
        self,
        *,
        category: str,
        kind: str,
        state: str,
        summary: str,
        provenance: str,
        confidence: float | None = None,
        detail: Mapping[str, Any] | None = None,
        activity_id: str | None = None,
        occurred_at: str | None = None,
        conversation_id: int | None = None,
        message_id: int | None = None,
        chat_job_id: int | None = None,
        intake_session_id: str | None = None,
        intake_revision: int | None = None,
        research_request_id: str | None = None,
        source_id: str | None = None,
        finding_ids: list[str] | tuple[str, ...] | None = None,
        genesis_revision: int | None = None,
        design_run_id: str | None = None,
        provider_id: str | None = None,
    ) -> dict[str, Any]:
        if detail is not None and not isinstance(detail, Mapping):
            raise IncubationActivityError("activity detail must be an object")
        payload = {
            "activity_id": activity_id or f"activity_{uuid.uuid4().hex}",
            "occurred_at": occurred_at or self.now(),
            "category": category,
            "kind": kind,
            "state": state,
            "summary": _redact_text(str(summary or "")),
            "provenance": provenance,
            "confidence": confidence,
            "detail": _redact_detail(safe_payload(detail or {}, max_bytes=20_000)),
            "conversation_id": conversation_id,
            "message_id": message_id,
            "chat_job_id": chat_job_id,
            "intake_session_id": intake_session_id,
            "intake_revision": intake_revision,
            "research_request_id": research_request_id,
            "source_id": source_id,
            "finding_ids": list(finding_ids or []),
            "genesis_revision": genesis_revision,
            "design_run_id": design_run_id,
            "provider_id": provider_id,
        }
        try:
            activity = IncubationActivity.from_dict(payload)
            return self.memory.append_incubation_activity(activity)
        except (ContractError, TypeError, ValueError) as exc:
            raise IncubationActivityError(str(exc)[:500]) from exc

    @staticmethod
    def _projection(item: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(item)
        # Provider identity and internal conversation plumbing are not useful to
        # an owner and should not become part of the visible activity surface.
        for key in ("provider_id", "conversation_id", "message_id", "chat_job_id", "intake_session_id"):
            result.pop(key, None)
        result["detail"] = _redact_detail(result.get("detail") or {})
        return result

    def list(
        self,
        *,
        after_id: int | str | None = None,
        before_id: int | str | None = None,
        limit: int = 100,
        categories: tuple[str, ...] | list[str] = (),
    ) -> dict[str, Any]:
        try:
            result = self.memory.list_incubation_activity(
                after_id=after_id,
                before_id=before_id,
                limit=limit,
                categories=categories,
            )
        except (ContractError, TypeError, ValueError) as exc:
            raise IncubationActivityError(str(exc)[:500]) from exc
        result["activities"] = [self._projection(item) for item in result.get("activities", [])]
        return result

    def get(self, activity_id: str | int) -> dict[str, Any] | None:
        try:
            item = self.memory.get_incubation_activity(activity_id)
        except (ContractError, TypeError, ValueError) as exc:
            raise IncubationActivityError(str(exc)[:500]) from exc
        return self._projection(item) if item else None


__all__ = ["IncubationActivityError", "IncubationActivityService"]
