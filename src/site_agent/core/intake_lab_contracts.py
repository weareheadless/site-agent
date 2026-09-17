"""Owner-facing contracts for the Intake Lab workspace.

The design engine keeps a much richer internal lifecycle.  These small
contracts are the deliberately boring boundary presented to the owner: a
public phase, an evidence-backed trace row, and an immutable live preview
identity.  None of them contain provider, worker, filesystem, or transcript
details.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .contracts import ContractError
from .design_contracts import canonical_hash, canonical_json


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{2,159}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")


class OwnerPhase(str, Enum):
    INTAKE = "intake"
    BUILDING = "building"
    READY = "ready"
    MODIFYING = "modifying"
    PROVISIONING = "provisioning"
    MANAGED = "managed"
    BLOCKED = "blocked"


class TraceCategory(str, Enum):
    INTAKE = "INTAKE"
    BUSINESS = "BUSINESS"
    AUDIENCE = "AUDIENCE"
    RESEARCH = "RESEARCH"
    COMPETITION = "COMPETITION"
    DETERMINATION = "DETERMINATION"
    DECISION = "DECISION"
    QUESTION = "QUESTION"
    BUILD = "BUILD"
    PREVIEW = "PREVIEW"


class TraceBasis(str, Enum):
    OWNER = "owner"
    RESEARCH = "research"
    INFERENCE = "inference"
    SYSTEM = "system"


@dataclass(frozen=True)
class OwnerTraceEntry:
    """One concise, source-linked row safe to show in the owner trace."""

    entry_id: str
    category: str
    summary: str
    basis: str
    created_at: str
    source_ids: tuple[str, ...] = ()
    confidence: float | None = None
    implications: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "OwnerTraceEntry":
        if not isinstance(raw, Mapping):
            raise ContractError("owner trace entry must be an object")
        entry_id = str(raw.get("entry_id") or "").strip()
        if not _ID.fullmatch(entry_id):
            raise ContractError("owner trace entry_id is invalid")
        category = str(raw.get("category") or "").strip().upper()
        if category not in {item.value for item in TraceCategory}:
            raise ContractError("owner trace category is invalid")
        summary = str(raw.get("summary") or "").strip()
        if not summary or len(summary) > 500:
            raise ContractError("owner trace summary is invalid")
        basis = str(raw.get("basis") or "").strip().lower()
        if basis not in {item.value for item in TraceBasis}:
            raise ContractError("owner trace basis is invalid")
        created_at = str(raw.get("created_at") or "").strip()
        if not created_at or len(created_at) > 100:
            raise ContractError("owner trace created_at is invalid")
        source_ids = raw.get("source_ids") or []
        if not isinstance(source_ids, (list, tuple)) or len(source_ids) > 20:
            raise ContractError("owner trace source_ids is invalid")
        normalized_sources = tuple(str(item).strip()[:160] for item in source_ids if str(item).strip())
        implications = raw.get("implications") or []
        if not isinstance(implications, (list, tuple)) or len(implications) > 12:
            raise ContractError("owner trace implications is invalid")
        normalized_implications = tuple(str(item).strip()[:240] for item in implications if str(item).strip())
        confidence = raw.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
                raise ContractError("owner trace confidence is invalid")
            confidence = float(confidence)
        return cls(
            entry_id=entry_id,
            category=category,
            summary=summary,
            basis=basis,
            created_at=created_at,
            source_ids=normalized_sources,
            confidence=confidence,
            implications=normalized_implications,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "entry_id": self.entry_id,
            "category": self.category,
            "summary": self.summary,
            "basis": self.basis,
            "created_at": self.created_at,
            "source_ids": list(self.source_ids),
            "confidence": self.confidence,
            "implications": list(self.implications),
        }


@dataclass(frozen=True)
class LivePreviewSnapshot:
    """An immutable, locally staged preview checkpoint."""

    snapshot_id: str
    run_id: str
    commit_sha: str
    created_at: str
    label: str
    variant: str = "live"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "LivePreviewSnapshot":
        if not isinstance(raw, Mapping):
            raise ContractError("live preview snapshot must be an object")
        snapshot_id = str(raw.get("snapshot_id") or "").strip()
        run_id = str(raw.get("run_id") or "").strip()
        commit_sha = str(raw.get("commit_sha") or "").strip().lower()
        if not _ID.fullmatch(snapshot_id) or not _ID.fullmatch(run_id):
            raise ContractError("live preview snapshot identity is invalid")
        if not _SHA1.fullmatch(commit_sha):
            raise ContractError("live preview snapshot commit_sha is invalid")
        created_at = str(raw.get("created_at") or "").strip()
        label = str(raw.get("label") or "").strip()
        if not created_at or len(created_at) > 100 or not label or len(label) > 240:
            raise ContractError("live preview snapshot metadata is invalid")
        if str(raw.get("variant") or "live") != "live":
            raise ContractError("live preview snapshot variant is invalid")
        return cls(snapshot_id, run_id, commit_sha, created_at, label)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id,
            "commit_sha": self.commit_sha,
            "created_at": self.created_at,
            "label": self.label,
            "variant": self.variant,
        }


def trace_entry_id(prefix: str, value: Any) -> str:
    """Create a stable opaque ID for a projected source record."""
    digest = canonical_hash({"prefix": str(prefix), "value": value})[:32]
    return f"trace_{digest}"


__all__ = [
    "LivePreviewSnapshot",
    "OwnerPhase",
    "OwnerTraceEntry",
    "TraceBasis",
    "TraceCategory",
    "trace_entry_id",
]
