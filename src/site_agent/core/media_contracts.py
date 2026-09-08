"""Provider-neutral contracts for the private media library."""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from .contracts import ContractError


class MediaStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class MediaAnalysisStatus(str, Enum):
    """Optional semantic analysis lifecycle, independent of file derivatives."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"


class MediaKind(str, Enum):
    IMAGE = "image"
    PDF = "pdf"


class KnowledgeStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"


def _text(value: Any, name: str, *, empty: bool = False, limit: int = 20_000) -> str:
    if value is None and empty:
        return ""
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ContractError(f"{name} must be non-empty text")
    if len(value) > limit:
        raise ContractError(f"{name} exceeds {limit} characters")
    return value


def _list(value: Any, name: str, *, limit: int = 100) -> list[str]:
    if value is None:
        value = []
    if isinstance(value, str):
        value = [value] if value.strip() else []
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(item, str) for item in value):
        raise ContractError(f"{name} must be a list of at most {limit} strings")
    return [item[:500] for item in value]


@dataclass(frozen=True)
class MediaAnalysis:
    schema_version: int
    description: str
    tags: list[str]
    alt_text: str
    orientation: str
    dominant_colors: list[str]
    suggested_uses: list[str]
    quality_notes: list[str]
    ocr_text: str
    knowledge_relevant: bool
    proposed_knowledge_markdown: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "MediaAnalysis":
        if not isinstance(value, dict):
            raise ContractError("media analysis must be an object")
        version = value.get("schema_version", 1)
        if isinstance(version, bool) or not isinstance(version, int) or version != 1:
            raise ContractError("media analysis schema_version must be 1")
        relevant = value.get("knowledge_relevant")
        if isinstance(relevant, str):
            normalized = re.sub(r"[^a-z0-9]+", " ", relevant.strip().lower()).strip()
            if normalized in {"true", "yes", "y", "1"}:
                relevant = True
            elif normalized in {"false", "no", "n", "0"}:
                relevant = False
            elif normalized.startswith(("true ", "yes ", "relevant ", "business information ")):
                relevant = True
            elif normalized.startswith(("false ", "no ", "not relevant", "irrelevant ", "no business information")):
                relevant = False
        elif isinstance(relevant, (int, float)) and not isinstance(relevant, bool) and relevant in {0, 1}:
            relevant = bool(relevant)
        if not isinstance(relevant, bool):
            raise ContractError("media analysis knowledge_relevant must be boolean")
        proposed = _text(value.get("proposed_knowledge_markdown", ""), "proposed_knowledge_markdown", empty=True)
        if relevant and not proposed.strip():
            raise ContractError("relevant media analysis needs proposed knowledge")
        return cls(
            schema_version=1,
            description=_text(value.get("description", ""), "description", empty=True),
            tags=_list(value.get("tags", []), "tags"),
            alt_text=_text(value.get("alt_text", ""), "alt_text", empty=True, limit=2_000),
            orientation=_text(value.get("orientation", "unknown"), "orientation", empty=True, limit=32),
            dominant_colors=_list(value.get("dominant_colors", []), "dominant_colors", limit=20),
            suggested_uses=_list(value.get("suggested_uses", []), "suggested_uses", limit=20),
            quality_notes=_list(value.get("quality_notes", []), "quality_notes", limit=20),
            ocr_text=_text(value.get("ocr_text", ""), "ocr_text", empty=True, limit=50_000),
            knowledge_relevant=relevant,
            proposed_knowledge_markdown=proposed,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, **{k: v for k, v in self.__dict__.items() if k != "schema_version"}}


@dataclass(frozen=True)
class MediaAsset:
    asset_id: int
    status: MediaStatus
    media_kind: MediaKind
    source_kind: str
    original_name: str
    content_type: str
    original_size: int
    original_sha256: str
    storage_id: str
    original_key: str
    normalized_key: str = ""
    thumbnail_key: str = ""
    page_keys: list[str] = field(default_factory=list)
    width: int | None = None
    height: int | None = None
    page_count: int = 0
    description: str = ""
    tags: list[str] = field(default_factory=list)
    ocr_text: str = ""
    proposed_knowledge: str = ""
    analysis: dict[str, Any] = field(default_factory=dict)
    provider_id: str = ""
    model: str = ""
    analysis_version: int = 1
    analysis_status: MediaAnalysisStatus = MediaAnalysisStatus.PENDING
    analysis_attempts: int = 0
    analysis_error: str = ""
    analysis_updated_ts: str = ""
    attempts: int = 0
    last_error: str = ""
    created_ts: str = ""
    updated_ts: str = ""
    archived_ts: str | None = None
    protected_ts: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "MediaAsset":
        try:
            status = MediaStatus(row["status"])
            kind = MediaKind(row["media_kind"])
            analysis_status = MediaAnalysisStatus(row.get("analysis_status") or MediaAnalysisStatus.PENDING.value)
        except (KeyError, ValueError) as exc:
            raise ContractError("stored media asset has an invalid status or kind") from exc
        return cls(
            asset_id=int(row["id"]), status=status, media_kind=kind,
            source_kind=str(row.get("source_kind") or "owner_upload"),
            original_name=str(row["original_name"]), content_type=str(row["content_type"]),
            original_size=int(row["original_size"]), original_sha256=str(row["original_sha256"]),
            storage_id=str(row["storage_id"]), original_key=str(row["original_key"]),
            normalized_key=str(row.get("normalized_key") or ""), thumbnail_key=str(row.get("thumbnail_key") or ""),
            page_keys=_json_list(row.get("page_keys_json")), width=row.get("width"), height=row.get("height"),
            page_count=int(row.get("page_count") or 0), description=str(row.get("description") or ""),
            tags=_json_list(row.get("tags_json")), ocr_text=str(row.get("ocr_text") or ""),
            proposed_knowledge=str(row.get("proposed_knowledge") or ""), analysis=_json_object(row.get("analysis_json")),
            provider_id=str(row.get("provider_id") or ""), model=str(row.get("model") or ""),
            analysis_version=int(row.get("analysis_version") or 1), analysis_status=analysis_status,
            analysis_attempts=int(row.get("analysis_attempts") or 0),
            analysis_error=str(row.get("analysis_error") or ""),
            analysis_updated_ts=str(row.get("analysis_updated_ts") or ""),
            attempts=int(row.get("attempts") or 0),
            last_error=str(row.get("last_error") or ""), created_ts=str(row.get("created_ts") or ""),
            updated_ts=str(row.get("updated_ts") or ""), archived_ts=row.get("archived_ts"), protected_ts=row.get("protected_ts"),
        )


def _json_list(value: Any) -> list[str]:
    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) and all(isinstance(item, str) for item in result) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _json_object(value: Any) -> dict[str, Any]:
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


class MediaStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def signed_get_url(self, key: str, ttl_seconds: int) -> str: ...


class MediaAnalyzer(Protocol):
    def analyze_images(self, image_urls: list[str], instruction: str) -> MediaAnalysis: ...


__all__ = ["KnowledgeStatus", "MediaAnalysis", "MediaAnalysisStatus", "MediaAsset", "MediaAnalyzer", "MediaKind", "MediaStatus", "MediaStore"]
