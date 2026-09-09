"""Typed contracts for Ada's design-engine pipeline.

The design engine deliberately keeps customer facts, design decisions, build
targets, and validation evidence separate.  LLM output enters through the
``from_dict`` constructors below and is rejected before it can reach a builder.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlsplit
from typing import Any, ClassVar

from .contracts import ContractError


DESIGN_SCHEMA_VERSION = 1
MAX_CONTRACT_BYTES = 400_000
MAX_TEXT_LENGTH = 20_000
MAX_LIST_ITEMS = 200
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.md$")
_CONTEXT_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z]{2,4})?$")
_CONTEXT_INSIGHT_ID_RE = re.compile(r"^insight_[A-Za-z0-9._:-]{2,159}$")
_CONTEXT_FINDING_ID_RE = re.compile(r"^finding_[A-Za-z0-9._:-]{2,159}$")
_CONTEXT_DEDUCTION_ID_RE = re.compile(r"^deduction_[A-Za-z0-9._:-]{2,159}$")


class DesignRunStatus(str, Enum):
    CREATED = "created"
    ASSESSING_INTAKE = "assessing_intake"
    PLANNING = "planning"
    BUILDING = "building"
    CANDIDATE_READY = "candidate_ready"
    VALIDATING = "validating"
    READY_FOR_REVIEW = "ready_for_review"
    NEEDS_REPAIR = "needs_repair"
    INCOMPLETE = "incomplete"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DesignOperationKind(str, Enum):
    INITIAL_BUILD = "initial_build"
    TECHNICAL_REPAIR = "technical_repair"
    VISUAL_REFINEMENT = "visual_refinement"
    DERIVED_PAGE = "derived_page"


class DesignPhase(str, Enum):
    """Durable specialist phases owned by the design coordinator."""

    COPY = "copy"
    CONCEPT = "concept"
    CREATIVE_SELECTION = "creative_selection"
    IMPLEMENTATION = "implementation"
    MOTION = "motion"
    CREATIVE_REALIZATION_REVIEW = "creative_realization_review"
    EXPERIENCE_REVIEW = "experience_review"
    TECHNICAL_REVIEW = "technical_review"
    REPAIR_BRIEF = "repair_brief"
    REPAIR = "repair"
    CREATIVE_FINAL_SIGNOFF = "creative_final_signoff"
    ASSET_EVIDENCE = "asset_evidence"
    BRAND_SOURCE = "brand_source"
    TRANSFER_REVIEW = "transfer_review"
    TEMPORAL_REVIEW = "temporal_review"


class DesignPhaseStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def validate_design_phase(value: str | DesignPhase) -> str:
    try:
        return DesignPhase(value).value
    except (TypeError, ValueError) as exc:
        raise ContractError("phase is invalid") from exc


def validate_design_phase_status(value: str | DesignPhaseStatus) -> str:
    try:
        return DesignPhaseStatus(value).value
    except (TypeError, ValueError) as exc:
        raise ContractError("phase status is invalid") from exc


_DESIGN_RUN_TRANSITIONS: dict[DesignRunStatus, frozenset[DesignRunStatus]] = {
    DesignRunStatus.CREATED: frozenset({DesignRunStatus.ASSESSING_INTAKE, DesignRunStatus.FAILED, DesignRunStatus.CANCELLED}),
    DesignRunStatus.ASSESSING_INTAKE: frozenset({DesignRunStatus.PLANNING, DesignRunStatus.FAILED, DesignRunStatus.CANCELLED}),
    DesignRunStatus.PLANNING: frozenset({DesignRunStatus.BUILDING, DesignRunStatus.INTERRUPTED, DesignRunStatus.FAILED, DesignRunStatus.CANCELLED}),
    DesignRunStatus.BUILDING: frozenset({DesignRunStatus.CANDIDATE_READY, DesignRunStatus.INCOMPLETE, DesignRunStatus.INTERRUPTED, DesignRunStatus.FAILED, DesignRunStatus.CANCELLED}),
    DesignRunStatus.CANDIDATE_READY: frozenset({DesignRunStatus.VALIDATING, DesignRunStatus.CANCELLED, DesignRunStatus.FAILED}),
    DesignRunStatus.VALIDATING: frozenset({DesignRunStatus.NEEDS_REPAIR, DesignRunStatus.INCOMPLETE, DesignRunStatus.READY_FOR_REVIEW, DesignRunStatus.INTERRUPTED, DesignRunStatus.FAILED, DesignRunStatus.CANCELLED}),
    # Deterministic validation may complete before the explicit read-only
    # visual gate is requested. That gate can reopen validation without
    # making any production mutation.
    DesignRunStatus.READY_FOR_REVIEW: frozenset({DesignRunStatus.VALIDATING, DesignRunStatus.NEEDS_REPAIR}),
    DesignRunStatus.NEEDS_REPAIR: frozenset({DesignRunStatus.CANCELLED}),
    DesignRunStatus.INCOMPLETE: frozenset({DesignRunStatus.VALIDATING, DesignRunStatus.CANCELLED}),
    DesignRunStatus.INTERRUPTED: frozenset(),
    DesignRunStatus.FAILED: frozenset(),
    DesignRunStatus.CANCELLED: frozenset(),
}


def validate_design_run_transition(current: str | DesignRunStatus, target: str | DesignRunStatus) -> None:
    """Reject lifecycle jumps that could make incomplete work reviewable."""
    try:
        current_status = DesignRunStatus(current)
        target_status = DesignRunStatus(target)
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid design run status") from exc
    if target_status not in _DESIGN_RUN_TRANSITIONS[current_status]:
        raise ContractError(f"design run cannot transition from {current_status.value} to {target_status.value}")


def validate_design_operation_kind(value: str | DesignOperationKind) -> str:
    try:
        return DesignOperationKind(value).value
    except (TypeError, ValueError) as exc:
        raise ContractError("operation_kind is invalid") from exc


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically and reject non-JSON numeric values."""
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ContractError("value is not safely JSON serializable") from exc


def canonical_hash(value: Any) -> str:
    """Return the SHA-256 of a canonical JSON value."""
    encoded = canonical_json(value).encode("utf-8")
    if len(encoded) > MAX_CONTRACT_BYTES:
        raise ContractError(f"contract exceeds {MAX_CONTRACT_BYTES} bytes")
    return hashlib.sha256(encoded).hexdigest()


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{path} must be an object")
    try:
        canonical_json(value)
    except ContractError as exc:
        raise ContractError(f"{path} contains unsupported JSON values") from exc
    return copy.deepcopy(dict(value))


def _schema(value: Mapping[str, Any], path: str = "schema_version") -> int:
    version = value.get(path)
    if isinstance(version, bool) or not isinstance(version, int) or version != DESIGN_SCHEMA_VERSION:
        raise ContractError(f"{path} must be {DESIGN_SCHEMA_VERSION}")
    return version


def _text(value: Any, path: str, *, required: bool = True, maximum: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str):
        if not required and value is None:
            return ""
        raise ContractError(f"{path} must be text")
    result = value.strip()
    if required and not result:
        raise ContractError(f"{path} must not be empty")
    if len(result) > maximum:
        raise ContractError(f"{path} exceeds {maximum} characters")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in result):
        raise ContractError(f"{path} contains control characters")
    return result


def _list(value: Any, path: str, *, item_type: type = str, required: bool = True, maximum: int = MAX_LIST_ITEMS) -> list[Any]:
    if value is None and not required:
        return []
    if not isinstance(value, list):
        raise ContractError(f"{path} must be a list")
    if required and not value:
        raise ContractError(f"{path} must not be empty")
    if len(value) > maximum:
        raise ContractError(f"{path} contains too many items")
    if item_type is not object and any(not isinstance(item, item_type) for item in value):
        raise ContractError(f"{path} contains an invalid item")
    return copy.deepcopy(value)


def safe_relative_path(value: Any, path: str = "path") -> str:
    """Normalize a repository/public path without permitting traversal."""
    result = _text(value, path, maximum=512).replace("\\", "/").lstrip("/")
    parts = result.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ContractError(f"{path} must be a safe relative path")
    return "/".join(parts)


def _page_path(value: Any, path: str) -> str:
    result = safe_relative_path(value, path)
    if result.startswith((".git/", ".opencode/")):
        raise ContractError(f"{path} is not a customer page path")
    return result


def _contact(value: Any, path: str) -> str:
    result = _text(value, path, maximum=2_000)
    parsed = urlsplit(result)
    if parsed.scheme and parsed.scheme not in {"http", "https", "mailto", "tel"}:
        raise ContractError(f"{path} has an unsupported URL scheme")
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        raise ContractError(f"{path} must contain a valid host")
    if parsed.scheme in {"mailto", "tel"} and not parsed.path:
        raise ContractError(f"{path} must contain a destination")
    return result


def _hash(value: Any, path: str, pattern: re.Pattern[str]) -> str:
    result = _text(value, path, maximum=128).lower()
    if not pattern.fullmatch(result):
        raise ContractError(f"{path} is not a valid content hash")
    return result


def _optional_object(value: Any, path: str) -> dict[str, Any]:
    if value is None:
        return {}
    return _object(value, path)


def _extra(value: Mapping[str, Any], known: set[str]) -> dict[str, Any]:
    return {key: copy.deepcopy(item) for key, item in value.items() if key not in known}


def _bounded_number(
    value: Any,
    path: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    required: bool = True,
) -> float | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{path} must be a number")
    result = float(value)
    if minimum is not None and result < minimum:
        raise ContractError(f"{path} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ContractError(f"{path} must be at most {maximum}")
    return result


def _positive_integer(value: Any, path: str, *, required: bool = True) -> int | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{path} must be a positive integer")
    return value


def _normalized_id(value: Any, path: str, *, maximum: int = 160) -> str:
    result = _text(value, path, maximum=maximum)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._:-]{0,159}", result):
        raise ContractError(f"{path} is invalid")
    return result


def _text_tuple(value: Any, path: str, *, maximum: int = MAX_LIST_ITEMS, item_maximum: int = 1_000) -> tuple[str, ...]:
    values = _list(value, path, required=False, maximum=maximum)
    return tuple(_text(item, f"{path}[{index}]", maximum=item_maximum) for index, item in enumerate(values))


def _strict_object(value: Any, path: str, known: set[str]) -> dict[str, Any]:
    result = _object(value, path)
    unknown = set(result) - known
    if unknown:
        raise ContractError(f"{path} contains unknown fields: {', '.join(sorted(unknown))}")
    return result


def _named_records(
    value: Any,
    path: str,
    *,
    required_fields: tuple[str, ...] = ("id", "meaning"),
    maximum: int = 40,
) -> tuple[dict[str, Any], ...]:
    items = _list(value, path, item_type=object, required=False, maximum=maximum)
    result: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, raw in enumerate(items):
        item = _object(raw, f"{path}[{index}]")
        for field_name in required_fields:
            if field_name not in item:
                raise ContractError(f"{path}[{index}].{field_name} is required")
        identifier = _normalized_id(item.get("id"), f"{path}[{index}].id")
        if identifier in identifiers:
            raise ContractError(f"{path} contains duplicate id: {identifier}")
        identifiers.add(identifier)
        normalized = copy.deepcopy(item)
        normalized["id"] = identifier
        for field_name in required_fields:
            if field_name != "id":
                _text(normalized.get(field_name), f"{path}[{index}].{field_name}", maximum=4_000)
        result.append(normalized)
    return tuple(result)


@dataclass(frozen=True)
class NormalizedPoint:
    """A bounded point in an asset's normalized coordinate space."""

    x: float
    y: float
    confidence: float = 1.0
    label: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], path: str = "point") -> "NormalizedPoint":
        value = _strict_object(raw, path, {"x", "y", "confidence", "label"})
        return cls(
            x=float(_bounded_number(value.get("x"), f"{path}.x", minimum=0, maximum=1)),
            y=float(_bounded_number(value.get("y"), f"{path}.y", minimum=0, maximum=1)),
            confidence=float(_bounded_number(value.get("confidence", 1), f"{path}.confidence", minimum=0, maximum=1)),
            label=_text(value.get("label"), f"{path}.label", required=False, maximum=160),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {"x": self.x, "y": self.y, "confidence": self.confidence}
        if self.label:
            result["label"] = self.label
        return result


@dataclass(frozen=True)
class NormalizedRegion:
    """A bounded rectangular region in an asset's normalized coordinate space."""

    x: float
    y: float
    width: float
    height: float
    confidence: float = 1.0
    label: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], path: str = "region") -> "NormalizedRegion":
        value = _strict_object(raw, path, {"x", "y", "width", "height", "confidence", "label"})
        x = float(_bounded_number(value.get("x"), f"{path}.x", minimum=0, maximum=1))
        y = float(_bounded_number(value.get("y"), f"{path}.y", minimum=0, maximum=1))
        width = float(_bounded_number(value.get("width"), f"{path}.width", minimum=0, maximum=1))
        height = float(_bounded_number(value.get("height"), f"{path}.height", minimum=0, maximum=1))
        if width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            raise ContractError(f"{path} must be a normalized rectangle within 0..1")
        return cls(
            x=x,
            y=y,
            width=width,
            height=height,
            confidence=float(_bounded_number(value.get("confidence", 1), f"{path}.confidence", minimum=0, maximum=1)),
            label=_text(value.get("label"), f"{path}.label", required=False, maximum=160),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "confidence": self.confidence,
        }
        if self.label:
            result["label"] = self.label
        return result


def _region_list(value: Any, path: str, *, maximum: int = 40) -> tuple[NormalizedRegion, ...]:
    items = _list(value, path, item_type=object, required=False, maximum=maximum)
    return tuple(NormalizedRegion.from_dict(item, f"{path}[{index}]") for index, item in enumerate(items))


def _point_or_none(value: Any, path: str) -> NormalizedPoint | None:
    if value is None:
        return None
    return NormalizedPoint.from_dict(value, path)


def _region_or_none(value: Any, path: str) -> NormalizedRegion | None:
    if value is None:
        return None
    return NormalizedRegion.from_dict(value, path)


@dataclass(frozen=True)
class AssetVisualEvidence:
    """Hash-bound deterministic and semantic evidence for one approved asset."""

    schema_version: int
    asset_id: str
    asset_sha256: str
    relative_path: str
    media_role: str
    pixel_width: int | None
    pixel_height: int | None
    aspect_ratio: float | None
    has_alpha: bool
    optical_bounds: NormalizedRegion | None = None
    optical_center: NormalizedPoint | None = None
    visual_mass: tuple[float, ...] = ()
    safe_backgrounds: tuple[str, ...] = ()
    minimum_legible_size: float | None = None
    dominant_colors: tuple[str, ...] = ()
    contrast_edges: tuple[dict[str, Any], ...] = ()
    focal_regions: tuple[NormalizedRegion, ...] = ()
    negative_space_regions: tuple[NormalizedRegion, ...] = ()
    semantic_description: str = ""
    subjects: tuple[str, ...] = ()
    materials_and_textures: tuple[str, ...] = ()
    emotional_tone: str = ""
    brand_signals: tuple[str, ...] = ()
    quality_constraints: tuple[str, ...] = ()
    evidence_sources: tuple[str, ...] = ()
    confidence: float = 0.0
    analyzer_version: str = ""
    provider_id: str = ""
    model: str = ""

    _ROLES: ClassVar[frozenset[str]] = frozenset({
        "logo", "identity_mark", "photograph", "illustration", "texture", "document", "unknown",
    })
    _BACKGROUND_TYPES: ClassVar[frozenset[str]] = frozenset({"light", "dark", "mixed", "unknown"})
    _EVIDENCE_SOURCES: ClassVar[frozenset[str]] = frozenset({"deterministic", "vision", "owner_note", "approved_knowledge"})

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AssetVisualEvidence":
        value = _strict_object(raw, "asset_visual_evidence", {
            "schema_version", "asset_id", "asset_sha256", "relative_path", "media_role", "pixel_width",
            "pixel_height", "aspect_ratio", "has_alpha", "optical_bounds", "optical_center", "visual_mass",
            "safe_backgrounds", "minimum_legible_size", "dominant_colors", "contrast_edges", "focal_regions",
            "negative_space_regions", "semantic_description", "subjects", "materials_and_textures",
            "emotional_tone", "brand_signals", "quality_constraints", "evidence_sources", "confidence",
            "analyzer_version", "provider_id", "model",
        })
        version = _schema(value)
        role = _text(value.get("media_role"), "asset_visual_evidence.media_role", maximum=40).lower()
        if role not in cls._ROLES:
            raise ContractError("asset_visual_evidence.media_role is invalid")
        width = _positive_integer(value.get("pixel_width"), "asset_visual_evidence.pixel_width", required=False)
        height = _positive_integer(value.get("pixel_height"), "asset_visual_evidence.pixel_height", required=False)
        if (width is None) != (height is None):
            raise ContractError("asset_visual_evidence pixel dimensions must be provided together")
        ratio = _bounded_number(value.get("aspect_ratio"), "asset_visual_evidence.aspect_ratio", minimum=0, required=False)
        if width is not None and ratio is None:
            ratio = width / height  # type: ignore[operator]
        if ratio is not None and ratio <= 0:
            raise ContractError("asset_visual_evidence.aspect_ratio must be positive")
        has_alpha = value.get("has_alpha")
        if not isinstance(has_alpha, bool):
            raise ContractError("asset_visual_evidence.has_alpha must be boolean")
        mass = _list(value.get("visual_mass"), "asset_visual_evidence.visual_mass", required=False, maximum=64, item_type=object)
        visual_mass = tuple(float(_bounded_number(item, f"asset_visual_evidence.visual_mass[{index}]", minimum=0, maximum=1)) for index, item in enumerate(mass))
        backgrounds = _text_tuple(value.get("safe_backgrounds"), "asset_visual_evidence.safe_backgrounds", maximum=8, item_maximum=40)
        if any(item.lower() not in cls._BACKGROUND_TYPES for item in backgrounds):
            raise ContractError("asset_visual_evidence.safe_backgrounds contains an invalid value")
        sources = tuple(
            re.sub(r"[\s-]+", "_", item.lower())
            for item in _text_tuple(value.get("evidence_sources"), "asset_visual_evidence.evidence_sources", maximum=8, item_maximum=40)
        )
        if any(item not in cls._EVIDENCE_SOURCES for item in sources):
            raise ContractError("asset_visual_evidence.evidence_sources contains an invalid value")
        colors = _text_tuple(value.get("dominant_colors"), "asset_visual_evidence.dominant_colors", maximum=24, item_maximum=80)
        contrast = _list(value.get("contrast_edges"), "asset_visual_evidence.contrast_edges", item_type=object, required=False, maximum=24)
        normalized_contrast = tuple(_object(item, f"asset_visual_evidence.contrast_edges[{index}]") for index, item in enumerate(contrast))
        return cls(
            schema_version=version,
            asset_id=_normalized_id(value.get("asset_id"), "asset_visual_evidence.asset_id"),
            asset_sha256=_hash(value.get("asset_sha256"), "asset_visual_evidence.asset_sha256", _SHA256_RE),
            relative_path=safe_relative_path(value.get("relative_path"), "asset_visual_evidence.relative_path"),
            media_role=role,
            pixel_width=width,
            pixel_height=height,
            aspect_ratio=ratio,
            has_alpha=has_alpha,
            optical_bounds=_region_or_none(value.get("optical_bounds"), "asset_visual_evidence.optical_bounds"),
            optical_center=_point_or_none(value.get("optical_center"), "asset_visual_evidence.optical_center"),
            visual_mass=visual_mass,
            safe_backgrounds=backgrounds,
            minimum_legible_size=_bounded_number(value.get("minimum_legible_size"), "asset_visual_evidence.minimum_legible_size", minimum=0, maximum=1, required=False),
            dominant_colors=colors,
            contrast_edges=normalized_contrast,
            focal_regions=_region_list(value.get("focal_regions"), "asset_visual_evidence.focal_regions"),
            negative_space_regions=_region_list(value.get("negative_space_regions"), "asset_visual_evidence.negative_space_regions"),
            semantic_description=_text(value.get("semantic_description"), "asset_visual_evidence.semantic_description", required=False, maximum=4_000),
            subjects=_text_tuple(value.get("subjects"), "asset_visual_evidence.subjects", maximum=40),
            materials_and_textures=_text_tuple(value.get("materials_and_textures"), "asset_visual_evidence.materials_and_textures", maximum=40),
            emotional_tone=_text(value.get("emotional_tone"), "asset_visual_evidence.emotional_tone", required=False, maximum=1_000),
            brand_signals=_text_tuple(value.get("brand_signals"), "asset_visual_evidence.brand_signals", maximum=40),
            quality_constraints=_text_tuple(value.get("quality_constraints"), "asset_visual_evidence.quality_constraints", maximum=40),
            evidence_sources=sources,
            confidence=float(_bounded_number(value.get("confidence", 0), "asset_visual_evidence.confidence", minimum=0, maximum=1)),
            analyzer_version=_text(value.get("analyzer_version"), "asset_visual_evidence.analyzer_version", required=False, maximum=120),
            provider_id=_text(value.get("provider_id"), "asset_visual_evidence.provider_id", required=False, maximum=120),
            model=_text(value.get("model"), "asset_visual_evidence.model", required=False, maximum=240),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "asset_sha256": self.asset_sha256,
            "relative_path": self.relative_path,
            "media_role": self.media_role,
            "pixel_width": self.pixel_width,
            "pixel_height": self.pixel_height,
            "aspect_ratio": self.aspect_ratio,
            "has_alpha": self.has_alpha,
            "optical_bounds": self.optical_bounds.to_dict() if self.optical_bounds else None,
            "optical_center": self.optical_center.to_dict() if self.optical_center else None,
            "visual_mass": list(self.visual_mass),
            "safe_backgrounds": list(self.safe_backgrounds),
            "minimum_legible_size": self.minimum_legible_size,
            "dominant_colors": list(self.dominant_colors),
            "contrast_edges": copy.deepcopy(list(self.contrast_edges)),
            "focal_regions": [item.to_dict() for item in self.focal_regions],
            "negative_space_regions": [item.to_dict() for item in self.negative_space_regions],
            "semantic_description": self.semantic_description,
            "subjects": list(self.subjects),
            "materials_and_textures": list(self.materials_and_textures),
            "emotional_tone": self.emotional_tone,
            "brand_signals": list(self.brand_signals),
            "quality_constraints": list(self.quality_constraints),
            "evidence_sources": list(self.evidence_sources),
            "confidence": self.confidence,
            "analyzer_version": self.analyzer_version,
            "provider_id": self.provider_id,
            "model": self.model,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class BrandSourceMap:
    """Evidence-backed visual grammar; a hypothesis, never a replacement for owner facts."""

    schema_version: int
    identity_assets: tuple[str, ...]
    primary_brand_signals: tuple[str, ...]
    geometry_vocabulary: tuple[str, ...]
    spacing_rhythm: tuple[str, ...]
    line_and_edge_language: tuple[str, ...]
    color_relationships: tuple[str, ...]
    type_relationship_hypotheses: tuple[str, ...]
    material_relationships: tuple[str, ...]
    image_treatment_hypotheses: tuple[str, ...]
    signals_to_preserve: tuple[str, ...]
    signals_not_safe_to_infer: tuple[str, ...]
    owner_evidence_refs: tuple[str, ...]
    asset_evidence_refs: tuple[str, ...]
    confidence_by_signal: dict[str, float]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "BrandSourceMap":
        value = _strict_object(raw, "brand_source_map", {
            "schema_version", "identity_assets", "primary_brand_signals", "geometry_vocabulary", "spacing_rhythm",
            "line_and_edge_language", "color_relationships", "type_relationship_hypotheses", "material_relationships",
            "image_treatment_hypotheses", "signals_to_preserve", "signals_not_safe_to_infer", "owner_evidence_refs",
            "asset_evidence_refs", "confidence_by_signal",
        })
        version = _schema(value)
        owner_refs = _text_tuple(value.get("owner_evidence_refs"), "brand_source_map.owner_evidence_refs", maximum=40, item_maximum=300)
        asset_refs = _text_tuple(value.get("asset_evidence_refs"), "brand_source_map.asset_evidence_refs", maximum=40, item_maximum=300)
        if not owner_refs and not asset_refs:
            raise ContractError("brand_source_map requires owner or asset evidence references")
        raw_confidence = _optional_object(value.get("confidence_by_signal"), "brand_source_map.confidence_by_signal")
        confidence: dict[str, float] = {}
        for key, item in raw_confidence.items():
            normalized_key = _normalized_id(key, "brand_source_map.confidence_by_signal key", maximum=120)
            confidence[normalized_key] = float(_bounded_number(item, f"brand_source_map.confidence_by_signal.{normalized_key}", minimum=0, maximum=1))
        fields = (
            "identity_assets", "primary_brand_signals", "geometry_vocabulary", "spacing_rhythm",
            "line_and_edge_language", "color_relationships", "type_relationship_hypotheses", "material_relationships",
            "image_treatment_hypotheses", "signals_to_preserve", "signals_not_safe_to_infer",
        )
        return cls(
            schema_version=version,
            **{name: _text_tuple(value.get(name), f"brand_source_map.{name}", maximum=60, item_maximum=2_000) for name in fields},
            owner_evidence_refs=owner_refs,
            asset_evidence_refs=asset_refs,
            confidence_by_signal=confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity_assets": list(self.identity_assets),
            "primary_brand_signals": list(self.primary_brand_signals),
            "geometry_vocabulary": list(self.geometry_vocabulary),
            "spacing_rhythm": list(self.spacing_rhythm),
            "line_and_edge_language": list(self.line_and_edge_language),
            "color_relationships": list(self.color_relationships),
            "type_relationship_hypotheses": list(self.type_relationship_hypotheses),
            "material_relationships": list(self.material_relationships),
            "image_treatment_hypotheses": list(self.image_treatment_hypotheses),
            "signals_to_preserve": list(self.signals_to_preserve),
            "signals_not_safe_to_infer": list(self.signals_not_safe_to_infer),
            "owner_evidence_refs": list(self.owner_evidence_refs),
            "asset_evidence_refs": list(self.asset_evidence_refs),
            "confidence_by_signal": copy.deepcopy(self.confidence_by_signal),
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class LogoCompositionRule:
    """Optical logo rules kept separate from the general asset assignment."""

    schema_version: int
    asset_id: str
    optical_sizing: str
    clear_space: float
    allowed_backgrounds: tuple[str, ...]
    navigation_relationship: str
    breakpoint_treatments: dict[str, str]
    minimum_optical_size: float
    maximum_optical_size: float
    collision_exclusions: tuple[str, ...]
    role: str
    evidence_refs: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "LogoCompositionRule":
        value = _strict_object(raw, "logo_composition_rule", {
            "schema_version", "asset_id", "optical_sizing", "clear_space", "allowed_backgrounds",
            "navigation_relationship", "breakpoint_treatments", "minimum_optical_size", "maximum_optical_size",
            "collision_exclusions", "role", "evidence_refs",
        })
        version = _schema(value)
        minimum = float(_bounded_number(value.get("minimum_optical_size"), "logo_composition_rule.minimum_optical_size", minimum=0, maximum=1))
        maximum = float(_bounded_number(value.get("maximum_optical_size"), "logo_composition_rule.maximum_optical_size", minimum=0, maximum=1))
        if minimum > maximum:
            raise ContractError("logo_composition_rule minimum optical size exceeds maximum")
        backgrounds = _text_tuple(value.get("allowed_backgrounds"), "logo_composition_rule.allowed_backgrounds", maximum=8, item_maximum=40)
        treatments = _optional_object(value.get("breakpoint_treatments"), "logo_composition_rule.breakpoint_treatments")
        if not {"desktop", "tablet", "mobile"}.issubset(treatments):
            raise ContractError("logo_composition_rule.breakpoint_treatments requires desktop, tablet, and mobile")
        return cls(
            schema_version=version,
            asset_id=_normalized_id(value.get("asset_id"), "logo_composition_rule.asset_id"),
            optical_sizing=_text(value.get("optical_sizing"), "logo_composition_rule.optical_sizing", maximum=2_000),
            clear_space=float(_bounded_number(value.get("clear_space"), "logo_composition_rule.clear_space", minimum=0, maximum=1)),
            allowed_backgrounds=backgrounds,
            navigation_relationship=_text(value.get("navigation_relationship"), "logo_composition_rule.navigation_relationship", maximum=2_000),
            breakpoint_treatments={key: _text(item, f"logo_composition_rule.breakpoint_treatments.{key}", maximum=500) for key, item in treatments.items()},
            minimum_optical_size=minimum,
            maximum_optical_size=maximum,
            collision_exclusions=_text_tuple(value.get("collision_exclusions"), "logo_composition_rule.collision_exclusions", maximum=20, item_maximum=160),
            role=_text(value.get("role"), "logo_composition_rule.role", maximum=40),
            evidence_refs=_text_tuple(value.get("evidence_refs"), "logo_composition_rule.evidence_refs", maximum=40, item_maximum=300),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "optical_sizing": self.optical_sizing,
            "clear_space": self.clear_space,
            "allowed_backgrounds": list(self.allowed_backgrounds),
            "navigation_relationship": self.navigation_relationship,
            "breakpoint_treatments": copy.deepcopy(self.breakpoint_treatments),
            "minimum_optical_size": self.minimum_optical_size,
            "maximum_optical_size": self.maximum_optical_size,
            "collision_exclusions": list(self.collision_exclusions),
            "role": self.role,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class AssetCompositionPlan:
    """A frozen, responsive assignment of one approved asset to the page."""

    schema_version: int
    asset_id: str
    asset_sha256: str
    narrative_role: str
    page_regions: tuple[str, ...]
    relationship_to_copy: str
    relationship_to_other_assets: str
    structural_contribution: tuple[str, ...]
    crop_policy: str
    focal_region_to_preserve: NormalizedRegion | None
    negative_space_usage: str
    layering_and_overlap_policy: str
    background_and_contrast_policy: str
    desktop_treatment: dict[str, Any]
    tablet_treatment: dict[str, Any]
    mobile_treatment: dict[str, Any]
    loading_priority: str
    accessibility_intent: str
    prohibited_uses: tuple[str, ...]
    acceptance_conditions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    logo_rule: LogoCompositionRule | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AssetCompositionPlan":
        value = _strict_object(raw, "asset_composition_plan", {
            "schema_version", "asset_id", "asset_sha256", "narrative_role", "page_regions", "relationship_to_copy",
            "relationship_to_other_assets", "structural_contribution", "crop_policy", "focal_region_to_preserve",
            "negative_space_usage", "layering_and_overlap_policy", "background_and_contrast_policy",
            "desktop_treatment", "tablet_treatment", "mobile_treatment", "loading_priority", "accessibility_intent",
            "prohibited_uses", "acceptance_conditions", "evidence_refs", "logo_rule",
        })
        version = _schema(value)
        asset_id = _normalized_id(value.get("asset_id"), "asset_composition_plan.asset_id")
        logo_rule = None if value.get("logo_rule") is None else LogoCompositionRule.from_dict(value["logo_rule"])
        if logo_rule is not None and logo_rule.asset_id != asset_id:
            raise ContractError("asset_composition_plan.logo_rule asset_id does not match")
        contribution = _text_tuple(value.get("structural_contribution"), "asset_composition_plan.structural_contribution", maximum=8, item_maximum=80)
        if not contribution:
            raise ContractError("asset_composition_plan.structural_contribution must not be empty")
        evidence_refs = _text_tuple(value.get("evidence_refs"), "asset_composition_plan.evidence_refs", maximum=40, item_maximum=300)
        if not evidence_refs:
            raise ContractError("asset_composition_plan.evidence_refs must not be empty")
        return cls(
            schema_version=version,
            asset_id=asset_id,
            asset_sha256=_hash(value.get("asset_sha256"), "asset_composition_plan.asset_sha256", _SHA256_RE),
            narrative_role=_text(value.get("narrative_role"), "asset_composition_plan.narrative_role", maximum=1_000),
            page_regions=_text_tuple(value.get("page_regions"), "asset_composition_plan.page_regions", maximum=20, item_maximum=160),
            relationship_to_copy=_text(value.get("relationship_to_copy"), "asset_composition_plan.relationship_to_copy", maximum=2_000),
            relationship_to_other_assets=_text(value.get("relationship_to_other_assets"), "asset_composition_plan.relationship_to_other_assets", maximum=2_000),
            structural_contribution=contribution,
            crop_policy=_text(value.get("crop_policy"), "asset_composition_plan.crop_policy", maximum=2_000),
            focal_region_to_preserve=_region_or_none(value.get("focal_region_to_preserve"), "asset_composition_plan.focal_region_to_preserve"),
            negative_space_usage=_text(value.get("negative_space_usage"), "asset_composition_plan.negative_space_usage", maximum=2_000),
            layering_and_overlap_policy=_text(value.get("layering_and_overlap_policy"), "asset_composition_plan.layering_and_overlap_policy", maximum=2_000),
            background_and_contrast_policy=_text(value.get("background_and_contrast_policy"), "asset_composition_plan.background_and_contrast_policy", maximum=2_000),
            desktop_treatment=_object(value.get("desktop_treatment"), "asset_composition_plan.desktop_treatment"),
            tablet_treatment=_object(value.get("tablet_treatment"), "asset_composition_plan.tablet_treatment"),
            mobile_treatment=_object(value.get("mobile_treatment"), "asset_composition_plan.mobile_treatment"),
            loading_priority=_text(value.get("loading_priority"), "asset_composition_plan.loading_priority", maximum=40),
            accessibility_intent=_text(value.get("accessibility_intent"), "asset_composition_plan.accessibility_intent", maximum=2_000),
            prohibited_uses=_text_tuple(value.get("prohibited_uses"), "asset_composition_plan.prohibited_uses", maximum=30, item_maximum=500),
            acceptance_conditions=_text_tuple(value.get("acceptance_conditions"), "asset_composition_plan.acceptance_conditions", maximum=30, item_maximum=1_000),
            evidence_refs=evidence_refs,
            logo_rule=logo_rule,
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "asset_sha256": self.asset_sha256,
            "narrative_role": self.narrative_role,
            "page_regions": list(self.page_regions),
            "relationship_to_copy": self.relationship_to_copy,
            "relationship_to_other_assets": self.relationship_to_other_assets,
            "structural_contribution": list(self.structural_contribution),
            "crop_policy": self.crop_policy,
            "focal_region_to_preserve": self.focal_region_to_preserve.to_dict() if self.focal_region_to_preserve else None,
            "negative_space_usage": self.negative_space_usage,
            "layering_and_overlap_policy": self.layering_and_overlap_policy,
            "background_and_contrast_policy": self.background_and_contrast_policy,
            "desktop_treatment": copy.deepcopy(self.desktop_treatment),
            "tablet_treatment": copy.deepcopy(self.tablet_treatment),
            "mobile_treatment": copy.deepcopy(self.mobile_treatment),
            "loading_priority": self.loading_priority,
            "accessibility_intent": self.accessibility_intent,
            "prohibited_uses": list(self.prohibited_uses),
            "acceptance_conditions": list(self.acceptance_conditions),
            "evidence_refs": list(self.evidence_refs),
            "logo_rule": self.logo_rule.to_dict() if self.logo_rule else None,
        }
        return result


@dataclass(frozen=True)
class BrandBehaviorSystem:
    """Domain-neutral physical-law contract consumed by one implementation run."""

    schema_version: int
    thesis: str
    business_relevance: str
    audience_effect: str
    evidence_refs: tuple[str, ...]
    conceptual_entities: tuple[dict[str, Any], ...]
    state_variables: tuple[dict[str, Any], ...]
    input_signals: tuple[dict[str, Any], ...]
    forces_and_relationships: tuple[dict[str, Any], ...]
    output_channels: tuple[dict[str, Any], ...]
    scene_graph: tuple[dict[str, Any], ...]
    signature_behavior: dict[str, Any]
    utility_behaviors: tuple[dict[str, Any], ...]
    narrative_behaviors: tuple[dict[str, Any], ...]
    resting_state: dict[str, Any]
    no_javascript_translation: str
    reduced_motion_translation: str
    mobile_translation: str
    keyboard_and_focus_behavior: str
    performance_budget: dict[str, Any]
    interruption_and_resize_behavior: str
    allowed_implementation_capabilities: tuple[str, ...]
    prohibited_generic_effects: tuple[str, ...]
    observable_acceptance_conditions: tuple[str, ...]
    transfer_test: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "BrandBehaviorSystem":
        known = {
            "schema_version", "thesis", "business_relevance", "audience_effect", "evidence_refs", "conceptual_entities",
            "state_variables", "input_signals", "forces_and_relationships", "output_channels", "scene_graph",
            "signature_behavior", "utility_behaviors", "narrative_behaviors", "resting_state", "no_javascript_translation",
            "reduced_motion_translation", "mobile_translation", "keyboard_and_focus_behavior", "performance_budget",
            "interruption_and_resize_behavior", "allowed_implementation_capabilities", "prohibited_generic_effects",
            "observable_acceptance_conditions", "transfer_test",
        }
        value = _strict_object(raw, "brand_behavior_system", known)
        version = _schema(value)
        evidence_refs = _text_tuple(value.get("evidence_refs"), "brand_behavior_system.evidence_refs", maximum=40, item_maximum=300)
        if not evidence_refs:
            raise ContractError("brand_behavior_system.evidence_refs must not be empty")
        signature = _object(value.get("signature_behavior"), "brand_behavior_system.signature_behavior")
        if not signature.get("id") or not signature.get("meaning"):
            raise ContractError("brand_behavior_system.signature_behavior requires id and meaning")
        _normalized_id(signature.get("id"), "brand_behavior_system.signature_behavior.id")
        acceptance = _text_tuple(signature.get("acceptance_conditions"), "brand_behavior_system.signature_behavior.acceptance_conditions", maximum=20, item_maximum=1_000)
        if not acceptance:
            raise ContractError("brand_behavior_system.signature_behavior.acceptance_conditions must not be empty")
        signature["id"] = _normalized_id(signature["id"], "brand_behavior_system.signature_behavior.id")
        signature["meaning"] = _text(signature["meaning"], "brand_behavior_system.signature_behavior.meaning", maximum=2_000)
        signature["acceptance_conditions"] = list(acceptance)
        transfer_test = _object(value.get("transfer_test"), "brand_behavior_system.transfer_test")
        transfer_state = _text(transfer_test.get("state"), "brand_behavior_system.transfer_test.state", maximum=20).lower()
        if transfer_state not in {"pending", "passed", "rejected"}:
            raise ContractError("brand_behavior_system.transfer_test.state is invalid")
        fields = (
            "thesis", "business_relevance", "audience_effect", "no_javascript_translation", "reduced_motion_translation",
            "mobile_translation", "keyboard_and_focus_behavior", "interruption_and_resize_behavior",
        )
        texts = {name: _text(value.get(name), f"brand_behavior_system.{name}", maximum=4_000) for name in fields}
        return cls(
            schema_version=version,
            **texts,
            evidence_refs=evidence_refs,
            conceptual_entities=_named_records(value.get("conceptual_entities"), "brand_behavior_system.conceptual_entities"),
            state_variables=_named_records(value.get("state_variables"), "brand_behavior_system.state_variables"),
            input_signals=_named_records(value.get("input_signals"), "brand_behavior_system.input_signals"),
            forces_and_relationships=_named_records(value.get("forces_and_relationships"), "brand_behavior_system.forces_and_relationships"),
            output_channels=_named_records(value.get("output_channels"), "brand_behavior_system.output_channels", required_fields=("id", "property")),
            scene_graph=_named_records(value.get("scene_graph"), "brand_behavior_system.scene_graph", required_fields=("id", "exit_condition")),
            signature_behavior=signature,
            utility_behaviors=_named_records(value.get("utility_behaviors"), "brand_behavior_system.utility_behaviors"),
            narrative_behaviors=_named_records(value.get("narrative_behaviors"), "brand_behavior_system.narrative_behaviors"),
            resting_state=_object(value.get("resting_state"), "brand_behavior_system.resting_state"),
            performance_budget=_object(value.get("performance_budget"), "brand_behavior_system.performance_budget"),
            allowed_implementation_capabilities=_text_tuple(value.get("allowed_implementation_capabilities"), "brand_behavior_system.allowed_implementation_capabilities", maximum=30, item_maximum=120),
            prohibited_generic_effects=_text_tuple(value.get("prohibited_generic_effects"), "brand_behavior_system.prohibited_generic_effects", maximum=30, item_maximum=500),
            observable_acceptance_conditions=_text_tuple(value.get("observable_acceptance_conditions"), "brand_behavior_system.observable_acceptance_conditions", maximum=40, item_maximum=1_000),
            transfer_test=transfer_test,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "thesis": self.thesis,
            "business_relevance": self.business_relevance,
            "audience_effect": self.audience_effect,
            "evidence_refs": list(self.evidence_refs),
            "conceptual_entities": copy.deepcopy(list(self.conceptual_entities)),
            "state_variables": copy.deepcopy(list(self.state_variables)),
            "input_signals": copy.deepcopy(list(self.input_signals)),
            "forces_and_relationships": copy.deepcopy(list(self.forces_and_relationships)),
            "output_channels": copy.deepcopy(list(self.output_channels)),
            "scene_graph": copy.deepcopy(list(self.scene_graph)),
            "signature_behavior": copy.deepcopy(self.signature_behavior),
            "utility_behaviors": copy.deepcopy(list(self.utility_behaviors)),
            "narrative_behaviors": copy.deepcopy(list(self.narrative_behaviors)),
            "resting_state": copy.deepcopy(self.resting_state),
            "no_javascript_translation": self.no_javascript_translation,
            "reduced_motion_translation": self.reduced_motion_translation,
            "mobile_translation": self.mobile_translation,
            "keyboard_and_focus_behavior": self.keyboard_and_focus_behavior,
            "performance_budget": copy.deepcopy(self.performance_budget),
            "interruption_and_resize_behavior": self.interruption_and_resize_behavior,
            "allowed_implementation_capabilities": list(self.allowed_implementation_capabilities),
            "prohibited_generic_effects": list(self.prohibited_generic_effects),
            "observable_acceptance_conditions": list(self.observable_acceptance_conditions),
            "transfer_test": copy.deepcopy(self.transfer_test),
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class ExperiencePlanBundle:
    """Immutable creative source of truth passed to the realization agent."""

    schema_version: int
    run_id: str
    base_sha: str
    context_snapshot_hash: str
    selected_concept_id: str
    copy_deck_hash: str
    asset_evidence: tuple[AssetVisualEvidence, ...]
    brand_source_map: BrandSourceMap
    brand_source_map_hash: str
    asset_composition_plan: tuple[AssetCompositionPlan, ...]
    behavior_system: BrandBehaviorSystem
    layout_and_typography_plan: dict[str, Any]
    responsive_composition_plan: dict[str, Any]
    protected_strengths: tuple[str, ...]
    variation_points: tuple[str, ...]
    implementation_risks: tuple[str, ...]
    transfer_test: dict[str, Any]
    review_rubric: tuple[dict[str, Any], ...]
    input_artifact_hashes: tuple[str, ...]
    copy_deck: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ExperiencePlanBundle":
        known = {
            "schema_version", "run_id", "base_sha", "context_snapshot_hash", "selected_concept_id", "copy_deck_hash",
            "asset_evidence", "brand_source_map", "brand_source_map_hash", "asset_composition_plan", "behavior_system",
            "layout_and_typography_plan", "responsive_composition_plan", "protected_strengths", "variation_points",
            "implementation_risks", "transfer_test", "review_rubric", "input_artifact_hashes",
            "copy_deck",
        }
        value = _strict_object(raw, "experience_plan_bundle", known)
        version = _schema(value)
        source_map = BrandSourceMap.from_dict(value.get("brand_source_map"))
        source_map_hash = _hash(value.get("brand_source_map_hash"), "experience_plan_bundle.brand_source_map_hash", _SHA256_RE)
        if source_map_hash != source_map.content_hash:
            raise ContractError("experience_plan_bundle.brand_source_map_hash does not match brand_source_map")
        evidence_raw = _list(value.get("asset_evidence"), "experience_plan_bundle.asset_evidence", item_type=object, required=False, maximum=80)
        evidence = tuple(AssetVisualEvidence.from_dict(item) for item in evidence_raw)
        evidence_by_id = {item.asset_id: item for item in evidence}
        composition_raw = _list(value.get("asset_composition_plan"), "experience_plan_bundle.asset_composition_plan", item_type=object, required=False, maximum=80)
        composition = tuple(AssetCompositionPlan.from_dict(item) for item in composition_raw)
        seen_assets: set[str] = set()
        for item in composition:
            if item.asset_id in seen_assets:
                raise ContractError("experience_plan_bundle contains duplicate asset composition assignments")
            seen_assets.add(item.asset_id)
            evidence_item = evidence_by_id.get(item.asset_id)
            if evidence_item is None:
                raise ContractError(f"experience_plan_bundle composition references missing asset evidence: {item.asset_id}")
            if evidence_item.asset_sha256 != item.asset_sha256:
                raise ContractError(f"experience_plan_bundle asset hash mismatch for {item.asset_id}")
        transfer_test = _object(value.get("transfer_test"), "experience_plan_bundle.transfer_test")
        if _text(transfer_test.get("state"), "experience_plan_bundle.transfer_test.state", maximum=20).lower() != "passed":
            raise ContractError("experience_plan_bundle.transfer_test must pass before realization")
        rubric_raw = _list(value.get("review_rubric"), "experience_plan_bundle.review_rubric", item_type=object, required=True, maximum=40)
        rubric = tuple(_named_records(rubric_raw, "experience_plan_bundle.review_rubric", required_fields=("id", "condition"), maximum=40))
        input_hashes = _text_tuple(value.get("input_artifact_hashes"), "experience_plan_bundle.input_artifact_hashes", maximum=64, item_maximum=128)
        for index, item in enumerate(input_hashes):
            if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", item.lower()):
                raise ContractError(f"experience_plan_bundle.input_artifact_hashes[{index}] is not a content hash")
        return cls(
            schema_version=version,
            run_id=_text(value.get("run_id"), "experience_plan_bundle.run_id", maximum=120),
            base_sha=_hash(value.get("base_sha"), "experience_plan_bundle.base_sha", _SHA1_RE),
            context_snapshot_hash=_hash(value.get("context_snapshot_hash"), "experience_plan_bundle.context_snapshot_hash", _SHA256_RE),
            selected_concept_id=_normalized_id(value.get("selected_concept_id"), "experience_plan_bundle.selected_concept_id"),
            copy_deck_hash=_hash(value.get("copy_deck_hash"), "experience_plan_bundle.copy_deck_hash", _SHA256_RE),
            asset_evidence=evidence,
            brand_source_map=source_map,
            brand_source_map_hash=source_map_hash,
            asset_composition_plan=composition,
            behavior_system=BrandBehaviorSystem.from_dict(value.get("behavior_system")),
            layout_and_typography_plan=_object(value.get("layout_and_typography_plan"), "experience_plan_bundle.layout_and_typography_plan"),
            responsive_composition_plan=_object(value.get("responsive_composition_plan"), "experience_plan_bundle.responsive_composition_plan"),
            protected_strengths=_text_tuple(value.get("protected_strengths"), "experience_plan_bundle.protected_strengths", maximum=40, item_maximum=1_000),
            variation_points=_text_tuple(value.get("variation_points"), "experience_plan_bundle.variation_points", maximum=40, item_maximum=1_000),
            implementation_risks=_text_tuple(value.get("implementation_risks"), "experience_plan_bundle.implementation_risks", maximum=40, item_maximum=1_000),
            transfer_test=transfer_test,
            review_rubric=rubric,
            input_artifact_hashes=tuple(item.lower() for item in input_hashes),
            copy_deck=_optional_object(value.get("copy_deck"), "experience_plan_bundle.copy_deck"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "base_sha": self.base_sha,
            "context_snapshot_hash": self.context_snapshot_hash,
            "selected_concept_id": self.selected_concept_id,
            "copy_deck_hash": self.copy_deck_hash,
            "asset_evidence": [item.to_dict() for item in self.asset_evidence],
            "brand_source_map": self.brand_source_map.to_dict(),
            "brand_source_map_hash": self.brand_source_map_hash,
            "asset_composition_plan": [item.to_dict() for item in self.asset_composition_plan],
            "behavior_system": self.behavior_system.to_dict(),
            "layout_and_typography_plan": copy.deepcopy(self.layout_and_typography_plan),
            "responsive_composition_plan": copy.deepcopy(self.responsive_composition_plan),
            "protected_strengths": list(self.protected_strengths),
            "variation_points": list(self.variation_points),
            "implementation_risks": list(self.implementation_risks),
            "transfer_test": copy.deepcopy(self.transfer_test),
            "review_rubric": copy.deepcopy(list(self.review_rubric)),
            "input_artifact_hashes": list(self.input_artifact_hashes),
            "copy_deck": copy.deepcopy(self.copy_deck),
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class TemporalExperienceEvidence:
    """Hash-bound local browser evidence for the locked behavior system."""

    schema_version: int
    candidate_sha: str
    experience_plan_hash: str
    route: str
    viewport: dict[str, Any]
    reduced_motion: bool
    interaction_script_id: str
    frames: tuple[dict[str, Any], ...]
    layout_shifts: tuple[dict[str, Any], ...]
    console_errors: tuple[dict[str, Any], ...]
    network_errors: tuple[dict[str, Any], ...]
    animation_observations: tuple[dict[str, Any], ...]
    keyboard_path_observations: tuple[str, ...]
    resting_state_observations: dict[str, Any]
    evidence_hash: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TemporalExperienceEvidence":
        known = {
            "schema_version", "candidate_sha", "experience_plan_hash", "route", "viewport", "reduced_motion",
            "interaction_script_id", "frames", "layout_shifts", "console_errors", "network_errors",
            "animation_observations", "keyboard_path_observations", "resting_state_observations", "evidence_hash",
        }
        value = _strict_object(raw, "temporal_experience_evidence", known)
        version = _schema(value)
        viewport = _strict_object(value.get("viewport"), "temporal_experience_evidence.viewport", {"name", "width", "height"})
        width = _positive_integer(viewport.get("width"), "temporal_experience_evidence.viewport.width")
        height = _positive_integer(viewport.get("height"), "temporal_experience_evidence.viewport.height")
        viewport = {"name": _text(viewport.get("name"), "temporal_experience_evidence.viewport.name", maximum=80), "width": width, "height": height}
        reduced_motion = value.get("reduced_motion")
        if not isinstance(reduced_motion, bool):
            raise ContractError("temporal_experience_evidence.reduced_motion must be boolean")
        raw_frames = _list(value.get("frames"), "temporal_experience_evidence.frames", item_type=object, required=True, maximum=30)
        frames: list[dict[str, Any]] = []
        phases: set[str] = set()
        for index, raw_frame in enumerate(raw_frames):
            frame = _strict_object(raw_frame, f"temporal_experience_evidence.frames[{index}]", {"phase", "path", "timestamp_ms", "label"})
            phase = _text(frame.get("phase"), f"temporal_experience_evidence.frames[{index}].phase", maximum=30).lower()
            if phase not in {"before", "intermediate", "after"}:
                raise ContractError("temporal_experience_evidence frame phase is invalid")
            phases.add(phase)
            normalized = {
                "phase": phase,
                "path": safe_relative_path(frame.get("path"), f"temporal_experience_evidence.frames[{index}].path"),
            }
            if frame.get("timestamp_ms") is not None:
                normalized["timestamp_ms"] = _bounded_number(frame.get("timestamp_ms"), f"temporal_experience_evidence.frames[{index}].timestamp_ms", minimum=0)
            if frame.get("label") is not None:
                normalized["label"] = _text(frame.get("label"), f"temporal_experience_evidence.frames[{index}].label", required=False, maximum=200)
            frames.append(normalized)
        if not {"before", "intermediate", "after"}.issubset(phases):
            raise ContractError("temporal_experience_evidence requires before, intermediate, and after frames")

        def objects(name: str) -> tuple[dict[str, Any], ...]:
            items = _list(value.get(name), f"temporal_experience_evidence.{name}", item_type=object, required=False, maximum=60)
            return tuple(_object(item, f"temporal_experience_evidence.{name}[{index}]") for index, item in enumerate(items))

        identity_without_hash = dict(value)
        identity_without_hash.pop("evidence_hash", None)
        evidence_hash = _hash(value.get("evidence_hash"), "temporal_experience_evidence.evidence_hash", _SHA256_RE)
        if evidence_hash != canonical_hash(identity_without_hash):
            raise ContractError("temporal_experience_evidence.evidence_hash does not match evidence")
        return cls(
            schema_version=version,
            candidate_sha=_hash(value.get("candidate_sha"), "temporal_experience_evidence.candidate_sha", _SHA1_RE),
            experience_plan_hash=_hash(value.get("experience_plan_hash"), "temporal_experience_evidence.experience_plan_hash", _SHA256_RE),
            route=_page_path(value.get("route"), "temporal_experience_evidence.route"),
            viewport=viewport,
            reduced_motion=reduced_motion,
            interaction_script_id=_normalized_id(value.get("interaction_script_id"), "temporal_experience_evidence.interaction_script_id"),
            frames=tuple(frames),
            layout_shifts=objects("layout_shifts"),
            console_errors=objects("console_errors"),
            network_errors=objects("network_errors"),
            animation_observations=objects("animation_observations"),
            keyboard_path_observations=_text_tuple(value.get("keyboard_path_observations"), "temporal_experience_evidence.keyboard_path_observations", maximum=60, item_maximum=240),
            resting_state_observations=_object(value.get("resting_state_observations"), "temporal_experience_evidence.resting_state_observations"),
            evidence_hash=evidence_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_sha": self.candidate_sha,
            "experience_plan_hash": self.experience_plan_hash,
            "route": self.route,
            "viewport": copy.deepcopy(self.viewport),
            "reduced_motion": self.reduced_motion,
            "interaction_script_id": self.interaction_script_id,
            "frames": copy.deepcopy(list(self.frames)),
            "layout_shifts": copy.deepcopy(list(self.layout_shifts)),
            "console_errors": copy.deepcopy(list(self.console_errors)),
            "network_errors": copy.deepcopy(list(self.network_errors)),
            "animation_observations": copy.deepcopy(list(self.animation_observations)),
            "keyboard_path_observations": list(self.keyboard_path_observations),
            "resting_state_observations": copy.deepcopy(self.resting_state_observations),
            "evidence_hash": self.evidence_hash,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class SiteIntake:
    schema_version: int
    business: dict[str, Any]
    audience: dict[str, Any]
    conversion: dict[str, Any]
    brand: dict[str, Any]
    site: dict[str, Any]
    constraints: dict[str, Any] = field(default_factory=dict)
    assets: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    unknowns: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SiteIntake":
        value = _object(raw, "intake")
        version = _schema(value)
        business = _object(value.get("business"), "business")
        _text(business.get("name"), "business.name", maximum=300)
        _text(business.get("offer_summary"), "business.offer_summary")
        services = _list(business.get("primary_services"), "business.primary_services")
        for index, service in enumerate(services):
            _text(service, f"business.primary_services[{index}]", maximum=500)

        audience = _object(value.get("audience"), "audience")
        _text(audience.get("primary"), "audience.primary", maximum=1_000)
        conversion = _object(value.get("conversion"), "conversion")
        _text(conversion.get("primary_action"), "conversion.primary_action", maximum=500)
        destination = conversion.get("contact_destination")
        if destination is None:
            if conversion.get("not_available") is not True:
                raise ContractError(
                    "conversion.contact_destination is required or conversion.not_available must be true"
                )
        else:
            _contact(destination, "conversion.contact_destination")

        brand = _object(value.get("brand"), "brand")
        _text(brand.get("voice"), "brand.voice", maximum=2_000)
        site = _object(value.get("site"), "site")
        pages = _list(site.get("required_pages"), "site.required_pages")
        normalized_pages = []
        for index, page in enumerate(pages):
            normalized_pages.append(_page_path(page, f"site.required_pages[{index}]"))
        site["required_pages"] = normalized_pages

        raw_assets = _list(value.get("assets"), "assets", item_type=object, required=False)
        assets: list[dict[str, Any]] = []
        for index, asset in enumerate(raw_assets):
            asset_object = _object(asset, f"assets[{index}]")
            if "id" in asset_object:
                asset_object["id"] = _text(asset_object["id"], f"assets[{index}].id", maximum=200)
            assets.append(asset_object)

        unknowns = _list(value.get("unknowns"), "unknowns", required=False)
        for index, item in enumerate(unknowns):
            _text(item, f"unknowns[{index}]", maximum=1_000)

        result = cls(
            schema_version=version,
            business=business,
            audience=audience,
            conversion=conversion,
            brand=brand,
            site=site,
            constraints=_optional_object(value.get("constraints"), "constraints"),
            assets=tuple(assets),
            provenance=_optional_object(value.get("provenance"), "provenance"),
            unknowns=tuple(unknowns),
            extra=_extra(value, {
                "schema_version", "business", "audience", "conversion", "brand", "site",
                "constraints", "assets", "provenance", "unknowns",
            }),
        )
        canonical_hash(result.to_dict())
        return result

    def to_dict(self) -> dict[str, Any]:
        result = {
            **copy.deepcopy(self.extra),
            "schema_version": self.schema_version,
            "business": copy.deepcopy(self.business),
            "audience": copy.deepcopy(self.audience),
            "conversion": copy.deepcopy(self.conversion),
            "brand": copy.deepcopy(self.brand),
            "site": copy.deepcopy(self.site),
        }
        if self.constraints:
            result["constraints"] = copy.deepcopy(self.constraints)
        if self.assets:
            result["assets"] = copy.deepcopy(list(self.assets))
        if self.provenance:
            result["provenance"] = copy.deepcopy(self.provenance)
        if self.unknowns:
            result["unknowns"] = list(self.unknowns)
        return result

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class DesignRequest:
    """Validated owner intent handed from chat to the design service."""

    intent: str
    intake: SiteIntake
    owner_summary: str
    source_message_id: int | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DesignRequest":
        value = _object(raw, "design_request")
        intent = _text(value.get("intent"), "design_request.intent", maximum=40).lower()
        if intent not in {"initial_site", "redesign", "derived_page"}:
            raise ContractError("design_request.intent is invalid")
        intake_value = value.get("intake")
        if not isinstance(intake_value, Mapping):
            raise ContractError("design_request.intake must be an object")
        source_message_id = value.get("source_message_id")
        if source_message_id is not None and (
            isinstance(source_message_id, bool) or not isinstance(source_message_id, int) or source_message_id < 1
        ):
            raise ContractError("design_request.source_message_id is invalid")
        result = cls(
            intent=intent,
            intake=SiteIntake.from_dict(intake_value),
            owner_summary=_text(value.get("owner_summary"), "design_request.owner_summary", maximum=2_000),
            source_message_id=source_message_id,
        )
        canonical_hash(result.to_dict())
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "intake": self.intake.to_dict(),
            "owner_summary": self.owner_summary,
            "source_message_id": self.source_message_id,
        }


@dataclass(frozen=True)
class DesignSkillReceipt:
    """Immutable identity of the trusted design guidance used by a run."""

    names: tuple[str, ...]
    content_hash: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DesignSkillReceipt":
        value = _object(raw, "design_skill_set")
        names = _list(value.get("names"), "design_skill_set.names")
        if not names or len(names) > 20:
            raise ContractError("design_skill_set.names must be a bounded non-empty list")
        normalized = tuple(_text(item, f"design_skill_set.names[{index}]", maximum=120) for index, item in enumerate(names))
        if len(set(normalized)) != len(normalized) or any(not _SKILL_NAME_RE.fullmatch(item) for item in normalized):
            raise ContractError("design_skill_set.names contains an invalid skill name")
        return cls(
            names=normalized,
            content_hash=_hash(value.get("content_hash"), "design_skill_set.content_hash", _SHA256_RE),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"names": list(self.names), "content_hash": self.content_hash}


def _context_insights(value: Any, name: str) -> tuple[dict[str, Any], ...]:
    items = _list(value, name, item_type=object, required=False, maximum=50)
    result: list[dict[str, Any]] = []
    allowed = {
        "insight_id", "kind", "summary", "confidence", "status", "owner_language",
        "source_languages", "finding_ids", "supports_paths",
    }
    for index, raw in enumerate(items):
        item = _object(raw, f"{name}[{index}]")
        if set(item) - allowed:
            raise ContractError(f"{name}[{index}] contains unsupported fields")
        summary = _text(item.get("summary"), f"{name}[{index}].summary", maximum=2_000)
        if re.search(r"https?://|\b[^\s@]+@[^\s@]+\.[^\s@]+\b|(?:^|\s)(?:/|[A-Za-z]:[\\/])", summary, re.IGNORECASE):
            raise ContractError(f"{name}[{index}].summary contains prohibited private detail")
        normalized: dict[str, Any] = {"summary": summary}
        if "insight_id" in item:
            insight_id = _text(item.get("insight_id"), f"{name}[{index}].insight_id", maximum=160)
            if not _CONTEXT_INSIGHT_ID_RE.fullmatch(insight_id):
                raise ContractError(f"{name}[{index}].insight_id is invalid")
            normalized["insight_id"] = insight_id
        for key in ("kind", "status"):
            if key in item:
                text = _text(item.get(key), f"{name}[{index}].{key}", maximum=40).lower()
                if not re.fullmatch(r"[a-z][a-z0-9_-]*", text):
                    raise ContractError(f"{name}[{index}].{key} is invalid")
                normalized[key] = text
        if "owner_language" in item:
            language = _text(item.get("owner_language"), f"{name}[{index}].owner_language", maximum=24).lower().replace("_", "-")
            if not _CONTEXT_LANGUAGE_RE.fullmatch(language):
                raise ContractError(f"{name}[{index}].owner_language is invalid")
            normalized["owner_language"] = language
        if "confidence" in item:
            confidence = item.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
                raise ContractError(f"{name}[{index}].confidence must be between 0 and 1")
            normalized["confidence"] = float(confidence)
        languages = _list(item.get("source_languages"), f"{name}[{index}].source_languages", required=False, maximum=20)
        normalized_languages: list[str] = []
        for language in languages:
            normalized_language = _text(language, f"{name}[{index}].source_languages[]", maximum=24).lower().replace("_", "-")
            if not _CONTEXT_LANGUAGE_RE.fullmatch(normalized_language):
                raise ContractError(f"{name}[{index}].source_languages contains an invalid language")
            normalized_languages.append(normalized_language)
        if languages:
            normalized["source_languages"] = normalized_languages
        finding_ids = _list(item.get("finding_ids"), f"{name}[{index}].finding_ids", required=False, maximum=50)
        normalized_finding_ids: list[str] = []
        for finding_id in finding_ids:
            normalized_id = _text(finding_id, f"{name}[{index}].finding_ids[]", maximum=160)
            if not _CONTEXT_FINDING_ID_RE.fullmatch(normalized_id):
                raise ContractError(f"{name}[{index}].finding_ids contains an invalid identifier")
            normalized_finding_ids.append(normalized_id)
        if finding_ids:
            normalized["finding_ids"] = normalized_finding_ids
        supports_paths = _list(item.get("supports_paths"), f"{name}[{index}].supports_paths", required=False, maximum=20)
        normalized_paths: list[str] = []
        for path in supports_paths:
            normalized_path = _text(path, f"{name}[{index}].supports_paths[]", maximum=160)
            if not re.fullmatch(r"[a-z][a-z0-9_.-]*", normalized_path):
                raise ContractError(f"{name}[{index}].supports_paths contains an invalid path")
            normalized_paths.append(normalized_path)
        if supports_paths:
            normalized["supports_paths"] = normalized_paths
        result.append(normalized)
    return tuple(result)


def _context_deductions(value: Any, name: str) -> tuple[dict[str, Any], ...]:
    items = _list(value, name, item_type=object, required=False, maximum=50)
    result: list[dict[str, Any]] = []
    allowed = {
        "deduction_id", "kind", "summary", "confidence", "basis", "source_refs",
        "supports_paths", "citation_uris",
    }
    for index, raw in enumerate(items):
        item = _object(raw, f"{name}[{index}]")
        if set(item) - allowed:
            raise ContractError(f"{name}[{index}] contains unsupported fields")
        deduction_id = _text(item.get("deduction_id"), f"{name}[{index}].deduction_id", maximum=160)
        if not _CONTEXT_DEDUCTION_ID_RE.fullmatch(deduction_id):
            raise ContractError(f"{name}[{index}].deduction_id is invalid")
        summary = _text(item.get("summary"), f"{name}[{index}].summary", maximum=2_000)
        if re.search(r"https?://|\b[^\s@]+@[^\s@]+\.[^\s@]+\b|(?:^|\s)(?:/|[A-Za-z]:[\\/])", summary, re.IGNORECASE):
            raise ContractError(f"{name}[{index}].summary contains prohibited private detail")
        confidence = item.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ContractError(f"{name}[{index}].confidence must be between 0 and 1")
        basis = _text(item.get("basis"), f"{name}[{index}].basis", maximum=120)
        if not re.fullmatch(r"[a-z][a-z0-9:_-]{0,119}", basis):
            raise ContractError(f"{name}[{index}].basis is invalid")
        kind = _text(item.get("kind"), f"{name}[{index}].kind", maximum=40).lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", kind):
            raise ContractError(f"{name}[{index}].kind is invalid")
        normalized: dict[str, Any] = {
            "deduction_id": deduction_id,
            "kind": kind,
            "summary": summary,
            "confidence": float(confidence),
            "basis": basis,
        }
        source_refs = _list(item.get("source_refs"), f"{name}[{index}].source_refs", required=False, maximum=20)
        normalized["source_refs"] = [
            _text(source, f"{name}[{index}].source_refs[]", maximum=240)
            for source in source_refs
        ]
        supports_paths = _list(item.get("supports_paths"), f"{name}[{index}].supports_paths", required=False, maximum=20)
        normalized_paths: list[str] = []
        for path in supports_paths:
            normalized_path = _text(path, f"{name}[{index}].supports_paths[]", maximum=160)
            if not re.fullmatch(r"[a-z][a-z0-9_.-]*", normalized_path):
                raise ContractError(f"{name}[{index}].supports_paths contains an invalid path")
            normalized_paths.append(normalized_path)
        normalized["supports_paths"] = normalized_paths
        citation_uris = _list(item.get("citation_uris"), f"{name}[{index}].citation_uris", required=False, maximum=20)
        normalized_uris: list[str] = []
        for uri in citation_uris:
            normalized_uri = _text(uri, f"{name}[{index}].citation_uris[]", maximum=240)
            if not normalized_uri.startswith("pipeworx://"):
                raise ContractError(f"{name}[{index}].citation_uris contains an unsupported URI")
            normalized_uris.append(normalized_uri)
        normalized["citation_uris"] = normalized_uris
        result.append(normalized)
    return tuple(result)


def _context_genesis(value: Any, name: str) -> dict[str, Any]:
    raw = _optional_object(value, name)
    section_fields = {
        "business_world": {"purpose", "values", "customer_promises", "tensions", "language"},
        "relationship": {"owner_preferences", "decision_style", "communication_preferences", "boundaries"},
        "creative_identity": {"principles", "developing_tastes", "patterns_to_avoid", "open_questions"},
        "research_identity": {"subjects", "communities"},
    }
    scalar_fields = {"purpose", "decision_style"}
    result: dict[str, Any] = {}
    for section_name, allowed in section_fields.items():
        if section_name not in raw:
            continue
        section = _object(raw.get(section_name), f"{name}.{section_name}")
        if set(section) - allowed:
            raise ContractError(f"{name}.{section_name} contains unsupported fields")
        normalized: dict[str, Any] = {}
        for field_name, field_value in section.items():
            path = f"{name}.{section_name}.{field_name}"
            if field_name in scalar_fields:
                normalized[field_name] = _text(field_value, path, required=False, maximum=2_000)
                continue
            values = _list(field_value, path, required=False, maximum=50)
            normalized[field_name] = [
                _text(item, f"{path}[{index}]", maximum=500)
                for index, item in enumerate(values)
            ]
        if normalized:
            result[section_name] = normalized
    return result


@dataclass(frozen=True)
class IncubatedCreativeContext:
    """Validated customer-specific context allowed into an isolated design request."""

    genesis_revision: int
    genesis_hash: str
    owner_confirmed_visual_preferences: tuple[str, ...] = ()
    owner_confirmed_visual_dislikes: tuple[str, ...] = ()
    research_backed_creative_implications: tuple[dict[str, Any], ...] = ()
    cross_language_audience_insights: tuple[dict[str, Any], ...] = ()
    customer_genesis: dict[str, Any] = field(default_factory=dict)
    infusion_deductions: tuple[dict[str, Any], ...] = ()
    novelty_constraints: dict[str, Any] = field(default_factory=dict)
    patterns_to_avoid: tuple[str, ...] = ()
    design_skill_set: DesignSkillReceipt | None = None
    visual_reference_notes: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IncubatedCreativeContext":
        value = _object(raw, "incubated_creative_context")

        def texts(name: str, maximum: int = 20) -> tuple[str, ...]:
            return tuple(_text(item, f"incubated_creative_context.{name}[{index}]") for index, item in enumerate(
                _list(value.get(name), f"incubated_creative_context.{name}", required=False, maximum=maximum)
            ))

        revision = value.get("genesis_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ContractError("incubated_creative_context.genesis_revision is invalid")
        skill_data = value.get("design_skill_set")
        if not isinstance(skill_data, Mapping):
            raise ContractError("incubated_creative_context.design_skill_set is required")
        return cls(
            genesis_revision=revision,
            genesis_hash=_hash(value.get("genesis_hash"), "incubated_creative_context.genesis_hash", _SHA256_RE),
            owner_confirmed_visual_preferences=texts("owner_confirmed_visual_preferences"),
            owner_confirmed_visual_dislikes=texts("owner_confirmed_visual_dislikes"),
            research_backed_creative_implications=_context_insights(
                value.get("research_backed_creative_implications"),
                "incubated_creative_context.research_backed_creative_implications",
            ),
            cross_language_audience_insights=_context_insights(
                value.get("cross_language_audience_insights"),
                "incubated_creative_context.cross_language_audience_insights",
            ),
            customer_genesis=_context_genesis(
                value.get("customer_genesis"),
                "incubated_creative_context.customer_genesis",
            ),
            infusion_deductions=_context_deductions(
                value.get("infusion_deductions"),
                "incubated_creative_context.infusion_deductions",
            ),
            novelty_constraints=_optional_object(value.get("novelty_constraints"), "incubated_creative_context.novelty_constraints"),
            patterns_to_avoid=texts("patterns_to_avoid"),
            design_skill_set=DesignSkillReceipt.from_dict(skill_data),
            visual_reference_notes=texts("visual_reference_notes", maximum=24),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "genesis_revision": self.genesis_revision,
            "genesis_hash": self.genesis_hash,
            "owner_confirmed_visual_preferences": list(self.owner_confirmed_visual_preferences),
            "owner_confirmed_visual_dislikes": list(self.owner_confirmed_visual_dislikes),
            "research_backed_creative_implications": copy.deepcopy(list(self.research_backed_creative_implications)),
            "cross_language_audience_insights": copy.deepcopy(list(self.cross_language_audience_insights)),
            "customer_genesis": copy.deepcopy(self.customer_genesis),
            "infusion_deductions": copy.deepcopy(list(self.infusion_deductions)),
            "novelty_constraints": copy.deepcopy(self.novelty_constraints),
            "patterns_to_avoid": list(self.patterns_to_avoid),
            "design_skill_set": self.design_skill_set.to_dict() if self.design_skill_set else None,
            "visual_reference_notes": list(self.visual_reference_notes),
        }


@dataclass(frozen=True)
class DesignContextSnapshot:
    """The exact owner, site, memory, and repository context used by a run.

    A snapshot is deliberately plain JSON so it can be persisted, hashed, and
    handed to an isolated builder without allowing that builder to reread a
    moving conversation or mutable instance state.
    """

    schema_version: int
    captured_at: str
    owner_request: str
    base_sha: str
    conversation_id: int | None = None
    source_message_id: int | None = None
    chat_job_id: int | None = None
    conversation: tuple[dict[str, Any], ...] = ()
    effective_persona: str = ""
    self_model: dict[str, Any] = field(default_factory=dict)
    approved_persona_notes: dict[str, Any] = field(default_factory=dict)
    memories: tuple[dict[str, Any], ...] = ()
    research: tuple[dict[str, Any], ...] = ()
    business_knowledge: tuple[dict[str, Any], ...] = ()
    attachments: tuple[dict[str, Any], ...] = ()
    site_facts: dict[str, Any] = field(default_factory=dict)
    source_repository: str = ""
    site_digest: str = ""
    route_inventory: tuple[str, ...] = ()
    current_content: dict[str, Any] = field(default_factory=dict)
    asset_inventory: tuple[dict[str, Any], ...] = ()
    asset_visual_evidence: tuple[AssetVisualEvidence, ...] = ()
    measured_design: dict[str, Any] = field(default_factory=dict)
    verified_facts: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    prohibited_claims: tuple[str, ...] = ()
    capabilities: tuple[dict[str, Any], ...] = ()
    execution_profile: dict[str, Any] = field(default_factory=dict)
    design_skill_set: DesignSkillReceipt | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DesignContextSnapshot":
        value = _object(raw, "context_snapshot")
        version = _schema(value)

        def optional_id(name: str) -> int | None:
            item = value.get(name)
            if item is None:
                return None
            if isinstance(item, bool) or not isinstance(item, int) or item < 1:
                raise ContractError(f"{name} must be a positive integer")
            return item

        def objects(name: str) -> tuple[dict[str, Any], ...]:
            items = _list(value.get(name), name, item_type=object, required=False)
            return tuple(_object(item, f"{name}[{index}]") for index, item in enumerate(items))

        def texts(name: str, maximum: int = 2_000) -> tuple[str, ...]:
            items = _list(value.get(name), name, required=False)
            return tuple(_text(item, f"{name}[{index}]", maximum=maximum) for index, item in enumerate(items))

        known = {
            "schema_version", "captured_at", "conversation_id", "source_message_id", "chat_job_id",
            "owner_request", "conversation", "effective_persona", "self_model", "approved_persona_notes",
            "memories", "research", "business_knowledge", "attachments", "site_facts", "source_repository",
            "base_sha", "site_digest", "route_inventory", "current_content", "asset_inventory", "measured_design",
            "asset_visual_evidence", "verified_facts", "unknowns", "prohibited_claims", "capabilities", "execution_profile", "design_skill_set",
        }
        result = cls(
            schema_version=version,
            captured_at=_text(value.get("captured_at"), "captured_at", maximum=100),
            conversation_id=optional_id("conversation_id"),
            source_message_id=optional_id("source_message_id"),
            chat_job_id=optional_id("chat_job_id"),
            owner_request=_text(value.get("owner_request"), "owner_request"),
            conversation=objects("conversation"),
            effective_persona=_text(value.get("effective_persona"), "effective_persona", required=False, maximum=40_000),
            self_model=_optional_object(value.get("self_model"), "self_model"),
            approved_persona_notes=_optional_object(value.get("approved_persona_notes"), "approved_persona_notes"),
            memories=objects("memories"),
            research=objects("research"),
            business_knowledge=objects("business_knowledge"),
            attachments=objects("attachments"),
            site_facts=_optional_object(value.get("site_facts"), "site_facts"),
            source_repository=_text(value.get("source_repository"), "source_repository", required=False, maximum=500),
            base_sha=_hash(value.get("base_sha"), "base_sha", _SHA1_RE),
            site_digest=_text(value.get("site_digest"), "site_digest", required=False, maximum=20_000),
            route_inventory=tuple(safe_relative_path(item, f"route_inventory[{index}]") for index, item in enumerate(
                _list(value.get("route_inventory"), "route_inventory", required=False)
            )),
            current_content=_optional_object(value.get("current_content"), "current_content"),
            asset_inventory=objects("asset_inventory"),
            asset_visual_evidence=tuple(
                AssetVisualEvidence.from_dict(item)
                for item in _list(value.get("asset_visual_evidence"), "asset_visual_evidence", item_type=object, required=False, maximum=80)
            ),
            measured_design=_optional_object(value.get("measured_design"), "measured_design"),
            verified_facts=texts("verified_facts"),
            unknowns=texts("unknowns"),
            prohibited_claims=texts("prohibited_claims"),
            capabilities=objects("capabilities"),
            execution_profile=_optional_object(value.get("execution_profile"), "execution_profile"),
            design_skill_set=(
                None
                if value.get("design_skill_set") is None
                else DesignSkillReceipt.from_dict(value["design_skill_set"])
            ),
            extra=_extra(value, known),
        )
        canonical_hash(result.to_dict())
        return result

    def to_dict(self) -> dict[str, Any]:
        result = {
            **copy.deepcopy(self.extra),
            "schema_version": self.schema_version,
            "captured_at": self.captured_at,
            "conversation_id": self.conversation_id,
            "source_message_id": self.source_message_id,
            "chat_job_id": self.chat_job_id,
            "owner_request": self.owner_request,
            "conversation": copy.deepcopy(list(self.conversation)),
            "effective_persona": self.effective_persona,
            "self_model": copy.deepcopy(self.self_model),
            "approved_persona_notes": copy.deepcopy(self.approved_persona_notes),
            "memories": copy.deepcopy(list(self.memories)),
            "research": copy.deepcopy(list(self.research)),
            "business_knowledge": copy.deepcopy(list(self.business_knowledge)),
            "attachments": copy.deepcopy(list(self.attachments)),
            "site_facts": copy.deepcopy(self.site_facts),
            "source_repository": self.source_repository,
            "base_sha": self.base_sha,
            "site_digest": self.site_digest,
            "route_inventory": list(self.route_inventory),
            "current_content": copy.deepcopy(self.current_content),
            "asset_inventory": copy.deepcopy(list(self.asset_inventory)),
            "measured_design": copy.deepcopy(self.measured_design),
            "verified_facts": list(self.verified_facts),
            "unknowns": list(self.unknowns),
            "prohibited_claims": list(self.prohibited_claims),
            "capabilities": copy.deepcopy(list(self.capabilities)),
            "execution_profile": copy.deepcopy(self.execution_profile),
        }
        if self.design_skill_set is not None:
            result["design_skill_set"] = self.design_skill_set.to_dict()
        if self.asset_visual_evidence:
            result["asset_visual_evidence"] = [item.to_dict() for item in self.asset_visual_evidence]
        return result

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class IntakeAssessment:
    complete_enough: bool
    blocking_questions: tuple[str, ...] = ()
    non_blocking_unknowns: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    safe_defaults_applied: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IntakeAssessment":
        value = _object(raw, "assessment")
        if not isinstance(value.get("complete_enough"), bool):
            raise ContractError("complete_enough must be boolean")

        def texts(name: str) -> tuple[str, ...]:
            items = _list(value.get(name), name, required=False)
            return tuple(_text(item, f"{name}[{index}]", maximum=2_000) for index, item in enumerate(items))

        return cls(
            complete_enough=value["complete_enough"],
            blocking_questions=texts("blocking_questions"),
            non_blocking_unknowns=texts("non_blocking_unknowns"),
            contradictions=texts("contradictions"),
            safe_defaults_applied=texts("safe_defaults_applied"),
            warnings=texts("warnings"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete_enough": self.complete_enough,
            "blocking_questions": list(self.blocking_questions),
            "non_blocking_unknowns": list(self.non_blocking_unknowns),
            "contradictions": list(self.contradictions),
            "safe_defaults_applied": list(self.safe_defaults_applied),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class DesignBrief:
    schema_version: int
    intake_hash: str
    business_objective: str
    audience_intent: str
    primary_conversion: str
    information_hierarchy: tuple[str, ...]
    trust_strategy: str
    content_requirements: tuple[str, ...]
    visual_objectives: tuple[str, ...]
    constraints: tuple[str, ...] = ()
    required_pages: tuple[str, ...] = ()
    supplied_assets: tuple[str, ...] = ()
    success_hypotheses: tuple[str, ...] = ()
    unresolved_unknowns: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DesignBrief":
        value = _object(raw, "design_brief")
        version = _schema(value)
        intake_hash = _hash(value.get("intake_hash"), "intake_hash", _SHA256_RE)

        def text(name: str, maximum: int = MAX_TEXT_LENGTH) -> str:
            return _text(value.get(name), name, maximum=maximum)

        def texts(name: str, required: bool = True) -> tuple[str, ...]:
            values = _list(value.get(name), name, required=required)
            return tuple(_text(item, f"{name}[{index}]") for index, item in enumerate(values))

        pages = tuple(_page_path(item, f"required_pages[{index}]") for index, item in enumerate(
            _list(value.get("required_pages"), "required_pages", required=False)
        ))
        assets = tuple(_text(item, f"supplied_assets[{index}]", maximum=300) for index, item in enumerate(
            _list(value.get("supplied_assets"), "supplied_assets", required=False)
        ))
        known = {
            "schema_version", "intake_hash", "business_objective", "audience_intent",
            "primary_conversion", "information_hierarchy", "trust_strategy",
            "content_requirements", "visual_objectives", "constraints", "required_pages",
            "supplied_assets", "success_hypotheses", "unresolved_unknowns",
        }
        result = cls(
            schema_version=version,
            intake_hash=intake_hash,
            business_objective=text("business_objective"),
            audience_intent=text("audience_intent"),
            primary_conversion=text("primary_conversion"),
            information_hierarchy=texts("information_hierarchy"),
            trust_strategy=text("trust_strategy"),
            content_requirements=texts("content_requirements"),
            visual_objectives=texts("visual_objectives"),
            constraints=texts("constraints", required=False),
            required_pages=pages,
            supplied_assets=assets,
            success_hypotheses=texts("success_hypotheses", required=False),
            unresolved_unknowns=texts("unresolved_unknowns", required=False),
            extra=_extra(value, known),
        )
        canonical_hash(result.to_dict())
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            **copy.deepcopy(self.extra),
            "schema_version": self.schema_version,
            "intake_hash": self.intake_hash,
            "business_objective": self.business_objective,
            "audience_intent": self.audience_intent,
            "primary_conversion": self.primary_conversion,
            "information_hierarchy": list(self.information_hierarchy),
            "trust_strategy": self.trust_strategy,
            "content_requirements": list(self.content_requirements),
            "visual_objectives": list(self.visual_objectives),
            "constraints": list(self.constraints),
            "required_pages": list(self.required_pages),
            "supplied_assets": list(self.supplied_assets),
            "success_hypotheses": list(self.success_hypotheses),
            "unresolved_unknowns": list(self.unresolved_unknowns),
        }


@dataclass(frozen=True)
class ArtDirection:
    schema_version: int
    name: str
    thesis: str
    business_relevance: str
    composition_strategy: str
    typography_strategy: str
    color_and_material_strategy: str
    image_strategy: str
    motion_strategy: str
    signature_gesture: str
    mobile_translation: str
    reduced_motion_translation: str
    conversion_strategy: str
    template_risk: str
    implementation_risks: tuple[str, ...] = ()
    selected: bool = False
    rejection_reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ArtDirection":
        value = _object(raw, "art_direction")
        version = _schema(value)
        raw_name = value.get("name", value.get("direction_id"))
        name = _text(raw_name, "name", maximum=120).lower().replace(" ", "-")
        names = (
            "thesis", "business_relevance", "composition_strategy", "typography_strategy",
            "color_and_material_strategy", "image_strategy", "motion_strategy", "signature_gesture",
            "mobile_translation", "reduced_motion_translation", "conversion_strategy", "template_risk",
        )
        values = {name: _text(value.get(name), name, maximum=4_000) for name in names}
        risks = _list(value.get("implementation_risks"), "implementation_risks", required=False)
        implementation_risks = tuple(_text(item, f"implementation_risks[{index}]", maximum=1_000)
                                     for index, item in enumerate(risks))
        selected = value.get("selected", False)
        if not isinstance(selected, bool):
            raise ContractError("selected must be boolean")
        rejection_reason = _text(value.get("rejection_reason"), "rejection_reason", required=False, maximum=2_000)
        known = set(names) | {
            "schema_version", "name", "direction_id", "implementation_risks", "selected", "rejection_reason",
        }
        return cls(
            schema_version=version,
            name=name,
            **values,
            implementation_risks=implementation_risks,
            selected=selected,
            rejection_reason=rejection_reason,
            extra=_extra(value, known),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **copy.deepcopy(self.extra),
            "schema_version": self.schema_version,
            "name": self.name,
            "thesis": self.thesis,
            "business_relevance": self.business_relevance,
            "composition_strategy": self.composition_strategy,
            "typography_strategy": self.typography_strategy,
            "color_and_material_strategy": self.color_and_material_strategy,
            "image_strategy": self.image_strategy,
            "motion_strategy": self.motion_strategy,
            "signature_gesture": self.signature_gesture,
            "mobile_translation": self.mobile_translation,
            "reduced_motion_translation": self.reduced_motion_translation,
            "conversion_strategy": self.conversion_strategy,
            "template_risk": self.template_risk,
            "implementation_risks": list(self.implementation_risks),
            "selected": self.selected,
            "rejection_reason": self.rejection_reason,
        }

    @property
    def direction_id(self) -> str:
        """Compatibility alias for early design-run records."""
        return self.name

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class DesignManifest:
    schema_version: int
    source_homepage_path: str
    design_direction_id: str
    intake_hash: str
    tokens: dict[str, Any]
    shared_regions: tuple[str, ...]
    brand_voice_summary: str = ""
    typography: dict[str, Any] = field(default_factory=dict)
    spacing: dict[str, Any] = field(default_factory=dict)
    breakpoints: dict[str, Any] = field(default_factory=dict)
    surfaces: dict[str, Any] = field(default_factory=dict)
    shell: dict[str, Any] = field(default_factory=dict)
    image_rules: dict[str, Any] = field(default_factory=dict)
    motion: dict[str, Any] = field(default_factory=dict)
    component_inventory: tuple[dict[str, Any], ...] = ()
    page_shell_requirements: tuple[str, ...] = ()
    accessibility_invariants: tuple[str, ...] = ()
    allowed_variation_points: tuple[str, ...] = ()
    prohibited_drift: tuple[str, ...] = ()
    signature_gesture: dict[str, Any] = field(default_factory=dict)
    source_files: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DesignManifest":
        value = _object(raw, "design_manifest")
        version = _schema(value)
        if "candidate_sha" in value or "source_commit_sha" in value:
            raise ContractError("commit identity belongs in DesignSourceBinding, not the manifest")
        source = _page_path(value.get("source_homepage_path") or "index.html", "source_homepage_path")
        # New native manifests do not select a visual direction.  Keep parsing
        # the old field so persisted compiler-era records remain readable.
        direction = _text(value.get("design_direction_id"), "design_direction_id", required=False, maximum=120)
        intake_hash = _hash(value.get("intake_hash"), "intake_hash", _SHA256_RE)

        def objects(name: str) -> dict[str, Any]:
            return _optional_object(value.get(name), name)

        def texts(name: str) -> tuple[str, ...]:
            items = _list(value.get(name), name, required=False)
            return tuple(_text(item, f"{name}[{index}]", maximum=1_000) for index, item in enumerate(items))

        raw_components = _list(value.get("component_inventory"), "component_inventory", item_type=object, required=False)
        components = tuple(_object(item, f"component_inventory[{index}]") for index, item in enumerate(raw_components))
        known = {
            "schema_version", "source_homepage_path", "design_direction_id", "intake_hash", "tokens",
            "shared_regions", "brand_voice_summary", "typography", "spacing", "breakpoints", "surfaces",
            "shell", "image_rules", "motion", "component_inventory", "page_shell_requirements",
            "accessibility_invariants", "allowed_variation_points", "prohibited_drift", "signature_gesture",
            "source_files",
        }
        shared = texts("shared_regions")
        result = cls(
            schema_version=version,
            source_homepage_path=source,
            design_direction_id=direction,
            intake_hash=intake_hash,
            tokens=objects("tokens"),
            shared_regions=shared,
            brand_voice_summary=_text(value.get("brand_voice_summary"), "brand_voice_summary", required=False, maximum=2_000),
            typography=objects("typography"),
            spacing=objects("spacing"),
            breakpoints=objects("breakpoints"),
            surfaces=objects("surfaces"),
            shell=objects("shell"),
            image_rules=objects("image_rules"),
            motion=objects("motion"),
            component_inventory=components,
            page_shell_requirements=texts("page_shell_requirements"),
            accessibility_invariants=texts("accessibility_invariants"),
            allowed_variation_points=texts("allowed_variation_points"),
            prohibited_drift=texts("prohibited_drift"),
            signature_gesture=objects("signature_gesture"),
            source_files=objects("source_files"),
            extra=_extra(value, known),
        )
        canonical_hash(result.to_dict())
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize factual native metadata without inventing visual controls.

        Empty visual fields are omitted from new manifests.  Non-empty legacy
        fields are retained when reading and writing compiler-era records so
        migration and audit tooling can still inspect them.
        """
        result: dict[str, Any] = {
            **copy.deepcopy(self.extra),
            "schema_version": self.schema_version,
            "source_homepage_path": self.source_homepage_path,
            "intake_hash": self.intake_hash,
            "source_files": copy.deepcopy(self.source_files),
        }
        optional = {
            "design_direction_id": self.design_direction_id,
            "tokens": self.tokens,
            "shared_regions": list(self.shared_regions),
            "brand_voice_summary": self.brand_voice_summary,
            "typography": self.typography,
            "spacing": self.spacing,
            "breakpoints": self.breakpoints,
            "surfaces": self.surfaces,
            "shell": self.shell,
            "image_rules": self.image_rules,
            "motion": self.motion,
            "component_inventory": list(self.component_inventory),
            "page_shell_requirements": list(self.page_shell_requirements),
            "accessibility_invariants": list(self.accessibility_invariants),
            "allowed_variation_points": list(self.allowed_variation_points),
            "prohibited_drift": list(self.prohibited_drift),
            "signature_gesture": self.signature_gesture,
        }
        for key, value in optional.items():
            if value:
                result[key] = copy.deepcopy(value)
        return result

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class DesignSourceBinding:
    candidate_sha: str
    manifest_path: str
    manifest_hash: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DesignSourceBinding":
        value = _object(raw, "design_source")
        return cls(
            candidate_sha=_hash(value.get("candidate_sha"), "design_source.candidate_sha", _SHA1_RE),
            manifest_path=safe_relative_path(value.get("manifest_path"), "design_source.manifest_path"),
            manifest_hash=_hash(value.get("manifest_hash"), "design_source.manifest_hash", _SHA256_RE),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "candidate_sha": self.candidate_sha,
            "manifest_path": self.manifest_path,
            "manifest_hash": self.manifest_hash,
        }

    def verify_manifest(self, manifest: DesignManifest) -> None:
        if manifest.content_hash != self.manifest_hash:
            raise ContractError("design manifest hash does not match its source binding")


@dataclass(frozen=True)
class BuildTarget:
    mode: str
    base_sha: str
    candidate_ref: str
    push_mode: str
    publishable: bool
    repository: str = ""
    clone_path: str = ""
    allowed_paths: tuple[str, ...] = ()
    operation_kind: str = DesignOperationKind.INITIAL_BUILD.value

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "BuildTarget":
        value = _object(raw, "build_target")
        mode = _text(value.get("mode"), "mode", maximum=40)
        if mode not in {"production_candidate", "local_experiment"}:
            raise ContractError("mode must be production_candidate or local_experiment")
        push_mode = _text(value.get("push_mode"), "push_mode", maximum=40)
        if push_mode not in {"shared_preview", "isolated_remote_ref", "none"}:
            raise ContractError("push_mode is invalid")
        publishable = value.get("publishable")
        if not isinstance(publishable, bool):
            raise ContractError("publishable must be boolean")
        if mode == "local_experiment" and (push_mode != "none" or publishable):
            raise ContractError("local_experiment must be non-pushable and non-publishable")
        candidate_ref = _text(value.get("candidate_ref"), "candidate_ref", maximum=240)
        if not _SAFE_REF_RE.fullmatch(candidate_ref) or ".." in candidate_ref:
            raise ContractError("candidate_ref is unsafe")
        paths = _list(value.get("allowed_paths"), "allowed_paths", required=False)
        allowed_paths = tuple(safe_relative_path(item, f"allowed_paths[{index}]") for index, item in enumerate(paths))
        repository = _text(value.get("repository"), "repository", required=False, maximum=300)
        clone_path = _text(value.get("clone_path"), "clone_path", required=False, maximum=1_000)
        return cls(
            mode=mode,
            base_sha=_hash(value.get("base_sha"), "base_sha", _SHA1_RE),
            candidate_ref=candidate_ref,
            push_mode=push_mode,
            publishable=publishable,
            repository=repository,
            clone_path=clone_path,
            allowed_paths=allowed_paths,
            operation_kind=validate_design_operation_kind(
                value.get("operation_kind", DesignOperationKind.INITIAL_BUILD.value)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "base_sha": self.base_sha,
            "candidate_ref": self.candidate_ref,
            "push_mode": self.push_mode,
            "publishable": self.publishable,
            "repository": self.repository,
            "clone_path": self.clone_path,
            "allowed_paths": list(self.allowed_paths),
            "operation_kind": self.operation_kind,
        }


@dataclass(frozen=True)
class PageIntake:
    schema_version: int
    page_id: str
    desired_url: str
    purpose: str
    primary_audience_intent: str
    primary_action: str
    required_facts: tuple[str, ...]
    navigation_relationship: str
    secondary_action: str = ""
    supplied_media_ids: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    seo_intent: dict[str, Any] = field(default_factory=dict)
    protected_content: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PageIntake":
        value = _object(raw, "page_intake")
        version = _schema(value)
        page_id = _text(value.get("page_id"), "page_id", maximum=120)
        desired_url = _page_path(value.get("desired_url"), "desired_url")

        def text(name: str, maximum: int = MAX_TEXT_LENGTH, required: bool = True) -> str:
            return _text(value.get(name), name, maximum=maximum, required=required)

        def texts(name: str, required: bool = True) -> tuple[str, ...]:
            items = _list(value.get(name), name, required=required)
            return tuple(_text(item, f"{name}[{index}]", maximum=2_000) for index, item in enumerate(items))

        media = tuple(_text(item, f"supplied_media_ids[{index}]", maximum=200) for index, item in enumerate(
            _list(value.get("supplied_media_ids"), "supplied_media_ids", required=False)
        ))
        return cls(
            schema_version=version,
            page_id=page_id,
            desired_url=desired_url,
            purpose=text("purpose"),
            primary_audience_intent=text("primary_audience_intent"),
            primary_action=text("primary_action", maximum=500),
            required_facts=texts("required_facts"),
            navigation_relationship=text("navigation_relationship", maximum=1_000),
            secondary_action=text("secondary_action", maximum=500, required=False),
            supplied_media_ids=media,
            references=texts("references", required=False),
            constraints=texts("constraints", required=False),
            seo_intent=_optional_object(value.get("seo_intent"), "seo_intent"),
            protected_content=texts("protected_content", required=False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "page_id": self.page_id,
            "desired_url": self.desired_url,
            "purpose": self.purpose,
            "primary_audience_intent": self.primary_audience_intent,
            "primary_action": self.primary_action,
            "required_facts": list(self.required_facts),
            "navigation_relationship": self.navigation_relationship,
            "secondary_action": self.secondary_action,
            "supplied_media_ids": list(self.supplied_media_ids),
            "references": list(self.references),
            "constraints": list(self.constraints),
            "seo_intent": copy.deepcopy(self.seo_intent),
            "protected_content": list(self.protected_content),
        }

@dataclass(frozen=True)
class PageBuildRequest:
    schema_version: int
    run_id: str
    mode: str
    base_sha: str
    page_path: str
    purpose: str
    acceptance_criteria: tuple[str, ...]
    site_intake_hash: str = ""
    design_source: DesignSourceBinding | None = None
    required_shared_regions: tuple[str, ...] = ()
    allowed_variation_points: tuple[str, ...] = ()
    required_files: tuple[str, ...] = ()
    prohibited_files: tuple[str, ...] = ()
    supplied_media_paths: tuple[str, ...] = ()
    supplied_media_asset_ids: tuple[int, ...] = ()
    content: dict[str, Any] = field(default_factory=dict)
    context_snapshot: DesignContextSnapshot | None = None
    context_snapshot_hash: str = ""
    incubated_creative_context: IncubatedCreativeContext | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PageBuildRequest":
        value = _object(raw, "page_build_request")
        version = _schema(value)
        mode = _text(value.get("mode"), "mode", maximum=40)
        if mode not in {"initial_homepage", "visual_refinement", "derived_page"}:
            raise ContractError("mode must be initial_homepage, visual_refinement, or derived_page")
        design_source = None
        if value.get("design_source") is not None:
            design_source = DesignSourceBinding.from_dict(value["design_source"])
        if mode == "derived_page" and design_source is None:
            raise ContractError("derived_page requires design_source")
        context_snapshot = None
        if value.get("context_snapshot") is not None:
            context_snapshot = DesignContextSnapshot.from_dict(value["context_snapshot"])
        context_snapshot_hash = ""
        if value.get("context_snapshot_hash"):
            context_snapshot_hash = _hash(value.get("context_snapshot_hash"), "context_snapshot_hash", _SHA256_RE)
        if context_snapshot is not None and context_snapshot_hash != context_snapshot.content_hash:
            raise ContractError("context_snapshot_hash does not match context_snapshot")
        if context_snapshot is None and context_snapshot_hash:
            raise ContractError("context_snapshot_hash requires context_snapshot")
        incubated_creative_context = (
            None
            if value.get("incubated_creative_context") is None
            else IncubatedCreativeContext.from_dict(value["incubated_creative_context"])
        )
        if (
            incubated_creative_context is not None
            and context_snapshot is not None
            and context_snapshot.design_skill_set is not None
            and incubated_creative_context.design_skill_set is not None
            and context_snapshot.design_skill_set.content_hash != incubated_creative_context.design_skill_set.content_hash
        ):
            raise ContractError("incubated creative context uses a different design skill set")

        def texts(name: str, required: bool = False) -> tuple[str, ...]:
            values = _list(value.get(name), name, required=required)
            return tuple(_text(item, f"{name}[{index}]", maximum=1_000) for index, item in enumerate(values))

        def paths(name: str) -> tuple[str, ...]:
            return tuple(_page_path(item, f"{name}[{index}]") for index, item in enumerate(
                _list(value.get(name), name, required=False)
            ))

        raw_asset_ids = _list(
            value.get("supplied_media_asset_ids"),
            "supplied_media_asset_ids",
            item_type=object,
            required=False,
        )
        media_asset_ids: list[int] = []
        for index, item in enumerate(raw_asset_ids):
            if isinstance(item, bool) or not isinstance(item, int) or item < 1:
                raise ContractError(f"supplied_media_asset_ids[{index}] must be a positive integer")
            if item in media_asset_ids:
                raise ContractError("supplied_media_asset_ids must contain unique IDs")
            media_asset_ids.append(item)

        return cls(
            schema_version=version,
            run_id=_text(value.get("run_id"), "run_id", maximum=120),
            mode=mode,
            base_sha=_hash(value.get("base_sha"), "base_sha", _SHA1_RE),
            page_path=_page_path(value.get("page_path"), "page_path"),
            purpose=_text(value.get("purpose"), "purpose"),
            acceptance_criteria=texts("acceptance_criteria", required=True),
            site_intake_hash=(
                _hash(value.get("site_intake_hash"), "site_intake_hash", _SHA256_RE)
                if value.get("site_intake_hash") else ""
            ),
            design_source=design_source,
            required_shared_regions=texts("required_shared_regions"),
            allowed_variation_points=texts("allowed_variation_points"),
            required_files=paths("required_files"),
            prohibited_files=paths("prohibited_files"),
            supplied_media_paths=paths("supplied_media_paths"),
            supplied_media_asset_ids=tuple(media_asset_ids),
            content=_optional_object(value.get("content"), "content"),
            context_snapshot=context_snapshot,
            context_snapshot_hash=context_snapshot_hash,
            incubated_creative_context=incubated_creative_context,
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "mode": self.mode,
            "base_sha": self.base_sha,
            "page_path": self.page_path,
            "purpose": self.purpose,
            "acceptance_criteria": list(self.acceptance_criteria),
            "site_intake_hash": self.site_intake_hash,
            "design_source": self.design_source.to_dict() if self.design_source else None,
            "required_shared_regions": list(self.required_shared_regions),
            "allowed_variation_points": list(self.allowed_variation_points),
            "required_files": list(self.required_files),
            "prohibited_files": list(self.prohibited_files),
            "supplied_media_paths": list(self.supplied_media_paths),
            "supplied_media_asset_ids": list(self.supplied_media_asset_ids),
            "content": copy.deepcopy(self.content),
            "context_snapshot": self.context_snapshot.to_dict() if self.context_snapshot else None,
            "context_snapshot_hash": self.context_snapshot_hash,
        }
        if self.incubated_creative_context is not None:
            result["incubated_creative_context"] = self.incubated_creative_context.to_dict()
        return result


@dataclass(frozen=True)
class DesignPhaseArtifact:
    """Hash-bound output from one finite specialist phase.

    The payload is deliberately role-specific JSON rather than freeform text.
    Concrete phase classes below bind the artifact to an expected phase while
    retaining one persistence shape for the coordinator and recovery code.
    """

    schema_version: int
    run_id: str
    phase: str
    variant_key: str
    attempt: int
    status: str
    base_sha: str
    context_snapshot_hash: str
    input_hashes: tuple[str, ...]
    producer: str
    payload: dict[str, Any]

    EXPECTED_PHASES: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DesignPhaseArtifact":
        value = _object(raw, "design_phase_artifact")
        version = _schema(value)
        phase = validate_design_phase(value.get("phase"))
        if cls.EXPECTED_PHASES and phase not in cls.EXPECTED_PHASES:
            raise ContractError(f"phase must be one of {', '.join(cls.EXPECTED_PHASES)}")
        status = validate_design_phase_status(value.get("status"))
        attempt = value.get("attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 2:
            raise ContractError("attempt must be between 1 and 2")
        raw_hashes = _list(value.get("input_hashes"), "input_hashes", required=False, maximum=32)
        input_hashes: list[str] = []
        for index, item in enumerate(raw_hashes):
            text = _text(item, f"input_hashes[{index}]", maximum=128).lower()
            if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", text):
                raise ContractError(f"input_hashes[{index}] is not a content hash")
            input_hashes.append(text)
        known = {
            "schema_version", "run_id", "phase", "variant_key", "attempt", "status",
            "base_sha", "context_snapshot_hash", "input_hashes", "producer", "payload",
        }
        unknown = set(value) - known
        if unknown:
            raise ContractError(f"design_phase_artifact contains unknown fields: {', '.join(sorted(unknown))}")
        result = cls(
            schema_version=version,
            run_id=_text(value.get("run_id"), "run_id", maximum=120),
            phase=phase,
            variant_key=_text(value.get("variant_key"), "variant_key", maximum=120),
            attempt=attempt,
            status=status,
            base_sha=_hash(value.get("base_sha"), "base_sha", _SHA1_RE),
            context_snapshot_hash=(
                _hash(value.get("context_snapshot_hash"), "context_snapshot_hash", _SHA256_RE)
                if value.get("context_snapshot_hash") else ""
            ),
            input_hashes=tuple(input_hashes),
            producer=_text(value.get("producer"), "producer", maximum=120),
            payload=_object(value.get("payload"), "payload"),
        )
        canonical_hash(result.to_dict())
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "phase": self.phase,
            "variant_key": self.variant_key,
            "attempt": self.attempt,
            "status": self.status,
            "base_sha": self.base_sha,
            "context_snapshot_hash": self.context_snapshot_hash,
            "input_hashes": list(self.input_hashes),
            "producer": self.producer,
            "payload": copy.deepcopy(self.payload),
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class CopyDeck(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.COPY.value,)


@dataclass(frozen=True)
class CreativeConcept(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.CONCEPT.value,)


@dataclass(frozen=True)
class DesignPlanBundle(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.CREATIVE_SELECTION.value,)


@dataclass(frozen=True)
class ImplementationReport(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.IMPLEMENTATION.value,)


@dataclass(frozen=True)
class MotionReport(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.MOTION.value,)


@dataclass(frozen=True)
class CreativeRealizationReview(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.CREATIVE_REALIZATION_REVIEW.value, DesignPhase.CREATIVE_FINAL_SIGNOFF.value)


@dataclass(frozen=True)
class CriticReport(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.EXPERIENCE_REVIEW.value, DesignPhase.TECHNICAL_REVIEW.value)


@dataclass(frozen=True)
class RepairBrief(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.REPAIR_BRIEF.value,)


@dataclass(frozen=True)
class RepairReport(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.REPAIR.value,)


@dataclass(frozen=True)
class AssetEvidenceReport(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.ASSET_EVIDENCE.value,)


@dataclass(frozen=True)
class BrandSourceReport(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.BRAND_SOURCE.value,)


@dataclass(frozen=True)
class TransferReview(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.TRANSFER_REVIEW.value,)


@dataclass(frozen=True)
class TemporalReview(DesignPhaseArtifact):
    EXPECTED_PHASES = (DesignPhase.TEMPORAL_REVIEW.value,)


@dataclass(frozen=True)
class VisualCritiqueReport:
    """Structured visual review evidence from the configured design model."""

    run_id: str
    candidate_sha: str
    model_id: str
    state: str
    findings: tuple[dict[str, Any], ...] = ()
    strengths: tuple[str, ...] = ()
    generic_template_signals: tuple[str, ...] = ()
    screenshot_evidence: tuple[dict[str, Any], ...] = ()
    repair_plan: tuple[dict[str, Any], ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "VisualCritiqueReport":
        value = _object(raw, "visual_critique_report")
        state = _text(value.get("state"), "state", maximum=30).lower()
        if state not in {"passed", "repair", "failed", "inconclusive"}:
            raise ContractError("visual_critique_report.state is invalid")

        def objects(name: str) -> tuple[dict[str, Any], ...]:
            items = _list(value.get(name), name, item_type=object, required=False)
            return tuple(_object(item, f"{name}[{index}]") for index, item in enumerate(items))

        def texts(name: str) -> tuple[str, ...]:
            items = _list(value.get(name), name, required=False)
            return tuple(_text(item, f"{name}[{index}]", maximum=2_000) for index, item in enumerate(items))

        known = {
            "run_id", "candidate_sha", "model_id", "state", "findings", "strengths",
            "generic_template_signals", "screenshot_evidence", "repair_plan",
        }
        result = cls(
            run_id=_text(value.get("run_id"), "run_id", maximum=120),
            candidate_sha=_hash(value.get("candidate_sha"), "candidate_sha", _SHA1_RE),
            model_id=_text(value.get("model_id"), "model_id", maximum=200),
            state=state,
            findings=objects("findings"),
            strengths=texts("strengths"),
            generic_template_signals=texts("generic_template_signals"),
            screenshot_evidence=objects("screenshot_evidence"),
            repair_plan=objects("repair_plan"),
            extra=_extra(value, known),
        )
        canonical_hash(result.to_dict())
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            **copy.deepcopy(self.extra),
            "run_id": self.run_id,
            "candidate_sha": self.candidate_sha,
            "model_id": self.model_id,
            "state": self.state,
            "findings": copy.deepcopy(list(self.findings)),
            "strengths": list(self.strengths),
            "generic_template_signals": list(self.generic_template_signals),
            "screenshot_evidence": copy.deepcopy(list(self.screenshot_evidence)),
            "repair_plan": copy.deepcopy(list(self.repair_plan)),
        }


@dataclass(frozen=True)
class QualityReport:
    run_id: str
    candidate_sha: str
    state: str
    findings: tuple[dict[str, Any], ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    repair_attempts: int = 0
    gates: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "QualityReport":
        value = _object(raw, "quality_report")
        state = _text(value.get("state"), "state", maximum=30)
        if state not in {"passed", "failed", "incomplete"}:
            raise ContractError("quality_report.state is invalid")
        raw_findings = _list(value.get("findings"), "findings", item_type=object, required=False)
        findings = tuple(_object(item, f"findings[{index}]") for index, item in enumerate(raw_findings))
        attempts = value.get("repair_attempts", 0)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or not 0 <= attempts <= 10:
            raise ContractError("repair_attempts must be between 0 and 10")
        gates = _optional_object(value.get("gates"), "gates")
        known = {"run_id", "candidate_sha", "state", "findings", "evidence", "repair_attempts", "gates"}
        return cls(
            run_id=_text(value.get("run_id"), "run_id", maximum=120),
            candidate_sha=_hash(value.get("candidate_sha"), "candidate_sha", _SHA1_RE),
            state=state,
            findings=findings,
            evidence=_optional_object(value.get("evidence"), "evidence"),
            repair_attempts=attempts,
            gates=gates,
            extra=_extra(value, known),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "candidate_sha": self.candidate_sha,
            "state": self.state,
            "findings": copy.deepcopy(list(self.findings)),
            "evidence": copy.deepcopy(self.evidence),
            "repair_attempts": self.repair_attempts,
            "gates": copy.deepcopy(self.gates),
            **copy.deepcopy(self.extra),
        }


@dataclass(frozen=True)
class DesignCandidateReceipt:
    run_id: str
    operation_kind: str
    base_sha: str
    candidate_sha: str
    candidate_ref: str
    diff_summary: str
    changed_paths: tuple[str, ...]
    manifest_path: str
    manifest_hash: str
    opencode_session_id: str
    provider: str
    model: str
    publishable: bool
    build_profile: str = ""
    transcript_path: str = ""
    transcript_artifact_id: int | None = None
    design_manifest: dict[str, Any] = field(default_factory=dict)
    build_error: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DesignCandidateReceipt":
        value = _object(raw, "candidate_receipt")
        paths = _list(value.get("changed_paths"), "changed_paths")
        publishable = value.get("publishable")
        if not isinstance(publishable, bool):
            raise ContractError("publishable must be boolean")
        design_manifest = _optional_object(value.get("design_manifest"), "design_manifest")
        manifest_hash = _hash(value.get("manifest_hash"), "manifest_hash", _SHA256_RE)
        if design_manifest:
            parsed_manifest = DesignManifest.from_dict(design_manifest)
            if parsed_manifest.content_hash != manifest_hash:
                raise ContractError("manifest_hash does not match design_manifest")
        transcript_path = str(value.get("transcript_path") or value.get("transcript_artifact_path") or "").strip()
        if transcript_path:
            transcript_path = safe_relative_path(transcript_path, "transcript_path")
        transcript_artifact_id = value.get("transcript_artifact_id")
        if transcript_artifact_id is not None and (
            isinstance(transcript_artifact_id, bool)
            or not isinstance(transcript_artifact_id, int)
            or transcript_artifact_id < 1
        ):
            raise ContractError("transcript_artifact_id is invalid")
        if not transcript_path and transcript_artifact_id is None:
            raise ContractError("candidate receipt requires transcript_path or transcript_artifact_id")
        return cls(
            run_id=_text(value.get("run_id"), "run_id", maximum=120),
            operation_kind=validate_design_operation_kind(value.get("operation_kind")),
            base_sha=_hash(value.get("base_sha"), "base_sha", _SHA1_RE),
            candidate_sha=_hash(value.get("candidate_sha"), "candidate_sha", _SHA1_RE),
            candidate_ref=_text(value.get("candidate_ref"), "candidate_ref", maximum=240),
            diff_summary=_text(value.get("diff_summary"), "diff_summary", required=False, maximum=5_000),
            changed_paths=tuple(safe_relative_path(item, f"changed_paths[{index}]") for index, item in enumerate(paths)),
            manifest_path=safe_relative_path(value.get("manifest_path"), "manifest_path"),
            manifest_hash=manifest_hash,
            opencode_session_id=_text(value.get("opencode_session_id"), "opencode_session_id", maximum=240),
            provider=_text(value.get("provider", value.get("provider_id")), "provider", maximum=120),
            model=_text(value.get("model", value.get("model_id")), "model", maximum=240),
            publishable=publishable,
            build_profile=_text(value.get("build_profile"), "build_profile", required=False, maximum=80),
            transcript_path=transcript_path,
            transcript_artifact_id=transcript_artifact_id,
            design_manifest=design_manifest,
            build_error=_text(value.get("build_error"), "build_error", required=False, maximum=2_000),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "operation_kind": self.operation_kind,
            "base_sha": self.base_sha,
            "candidate_sha": self.candidate_sha,
            "candidate_ref": self.candidate_ref,
            "diff_summary": self.diff_summary,
            "changed_paths": list(self.changed_paths),
            "manifest_path": self.manifest_path,
            "manifest_hash": self.manifest_hash,
            "opencode_session_id": self.opencode_session_id,
            "provider": self.provider,
            "model": self.model,
            "publishable": self.publishable,
            "build_profile": self.build_profile,
            "transcript_path": self.transcript_path,
            "transcript_artifact_id": self.transcript_artifact_id,
            "design_manifest": copy.deepcopy(self.design_manifest),
            "build_error": self.build_error,
        }

    @property
    def provider_id(self) -> str:
        return self.provider

    @property
    def model_id(self) -> str:
        return self.model
