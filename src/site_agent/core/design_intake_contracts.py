"""Contracts for Ada's conversational design-intake workflow.

The conversational draft is deliberately different from :class:`SiteIntake`.
It may be partial while Ada and the owner are talking, but every value that
enters it has an explicit provenance record before it can be frozen into a
design run.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .contracts import ContractError
from .design_contracts import SiteIntake, canonical_hash, canonical_json


DESIGN_INTAKE_SCHEMA_VERSION = 1
_MAX_TEXT = 20_000
_MAX_ITEMS = 100
_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


class IntakeOrigin(str, Enum):
    CONFIRMED = "confirmed"
    ADVISED = "advised"
    ASSUMED = "assumed"
    DEFERRED = "deferred"


class IntakeSessionState(str, Enum):
    COLLECTING = "collecting"
    READY_TO_BUILD = "ready_to_build"
    CONFIRMED = "confirmed"


class IntakeAssetUsage(str, Enum):
    WEBSITE = "website"
    INSPIRATION_ONLY = "inspiration_only"
    UNDECIDED = "undecided"


class IntakeUpdateBasis(str, Enum):
    OWNER_STATEMENT = "owner_statement"
    OWNER_CORRECTION = "owner_correction"
    OWNER_ACCEPTANCE = "owner_acceptance"
    RECOMMENDATION = "recommendation"
    DEFERRED = "deferred"


_ALLOWED_FIELD_PATHS = frozenset({
    "business.name",
    "business.offer_summary",
    "business.primary_services",
    "business.location",
    "business.service_area",
    "business.location_not_applicable",
    "business.differentiators",
    "business.verified_trust_evidence",
    "business.values",
    "audience.primary",
    "audience.secondary",
    "audience.motivations",
    "audience.concerns",
    "audience.desired_impression",
    "conversion.primary_action",
    "conversion.secondary_action",
    "conversion.contact_destination",
    "conversion.not_available",
    "conversion.success_outcome",
    "brand.voice",
    "brand.values",
    "brand.vibe",
    "brand.colors",
    "brand.typography",
    "brand.styles_to_avoid",
    "brand.visual_preferences",
    "brand.visual_dislikes",
    "brand.existing_fonts",
    "brand.existing_palette",
    "brand.prohibited_claims",
    "site.required_pages",
    "site.navigation_intent",
    "site.stable_urls",
    "site.language",
    "site.device_priority",
    "constraints.prohibited_claims",
    "constraints.accessibility_needs",
    "constraints.motion_preference",
    "constraints.notes",
    "constraints.safety",
    "constraints.environment",
    "constraints.prohibited_claims",
    "design.assumption_permission",
    "design.content_readiness",
})

_CORE_PATHS = (
    "business.name",
    "business.offer_summary",
    "business.primary_services",
    "business.location",
    "audience.primary",
    "conversion.primary_action",
    "site.required_pages",
    "brand.voice",
    "design.assumption_permission",
)
_OWNER_CONFIRMED_ORIGINS = frozenset({
    IntakeOrigin.CONFIRMED.value,
    IntakeOrigin.ADVISED.value,
})

def allowed_intake_field_paths() -> tuple[str, ...]:
    """Return the stable public field-path allowlist for advisor adapters."""
    return tuple(sorted(_ALLOWED_FIELD_PATHS))


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{path} must be an object")
    try:
        canonical_json(value)
    except ContractError as exc:
        raise ContractError(f"{path} contains unsupported JSON values") from exc
    return copy.deepcopy(dict(value))


def _text(value: Any, path: str, *, required: bool = True, maximum: int = _MAX_TEXT) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ContractError(f"{path} must be text")
    result = value.strip()
    if required and not result:
        raise ContractError(f"{path} must not be empty")
    if len(result) > maximum:
        raise ContractError(f"{path} exceeds {maximum} characters")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in result):
        raise ContractError(f"{path} contains control characters")
    return result


def _list(value: Any, path: str, *, required: bool = False, maximum: int = _MAX_ITEMS) -> list[Any]:
    if value is None and not required:
        return []
    if not isinstance(value, list):
        raise ContractError(f"{path} must be a list")
    if required and not value:
        raise ContractError(f"{path} must not be empty")
    if len(value) > maximum:
        raise ContractError(f"{path} contains too many items")
    return copy.deepcopy(value)


def _path(value: Any, name: str = "path") -> str:
    result = _text(value, name, maximum=120)
    if not _PATH.fullmatch(result) or result not in _ALLOWED_FIELD_PATHS:
        raise ContractError(f"{name} is not an allowed intake field")
    return result


def _optional_positive_id(value: Any, path: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{path} must be a positive integer")
    return value


def _copy_path_set(root: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    current = root
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = copy.deepcopy(value)


def _path_value(root: Mapping[str, Any], dotted: str) -> Any:
    current: Any = root
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _validate_field_tree(value: Mapping[str, Any], prefix: str = "") -> None:
    """Ensure draft fields can only contain declared dotted paths."""
    for raw_key, child in value.items():
        if not isinstance(raw_key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", raw_key):
            raise ContractError("design_intake_draft.fields contains an invalid key")
        path = f"{prefix}.{raw_key}" if prefix else raw_key
        if path in _ALLOWED_FIELD_PATHS:
            continue
        if not isinstance(child, Mapping):
            raise ContractError(f"{path} is not an allowed intake field")
        _validate_field_tree(child, path)


def _allowed_field_subset(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_key, child in value.items():
        if not isinstance(raw_key, str):
            continue
        path = f"{prefix}.{raw_key}" if prefix else raw_key
        if path in _ALLOWED_FIELD_PATHS:
            result[raw_key] = copy.deepcopy(child)
        elif isinstance(child, Mapping):
            nested = _allowed_field_subset(child, path)
            if nested:
                result[raw_key] = nested
    return result


def _field_paths(value: Mapping[str, Any], prefix: str = "") -> tuple[str, ...]:
    paths: list[str] = []
    for raw_key, child in value.items():
        path = f"{prefix}.{raw_key}" if prefix else raw_key
        if path in _ALLOWED_FIELD_PATHS or not isinstance(child, Mapping):
            if path in _ALLOWED_FIELD_PATHS and _value_present(child):
                paths.append(path)
            continue
        paths.extend(_field_paths(child, path))
    return tuple(paths)


def _value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


_STRICT_TEXT_FIELD_PATHS = frozenset({
    "business.name",
    "business.offer_summary",
    "audience.primary",
    "conversion.primary_action",
    "brand.voice",
})
_STRICT_LIST_FIELD_PATHS = frozenset({
    "business.primary_services",
    "site.required_pages",
})
_STRICT_BOOLEAN_FIELD_PATHS = frozenset({
    "business.location_not_applicable",
    "conversion.not_available",
})


def _model_field_value_is_compatible(path: str, value: Any) -> bool:
    """Keep malformed model values out of fields with strict final shapes."""
    if path in _STRICT_TEXT_FIELD_PATHS:
        return isinstance(value, str)
    if path == "conversion.contact_destination":
        return value is None or isinstance(value, str)
    if path in _STRICT_BOOLEAN_FIELD_PATHS:
        return isinstance(value, bool)
    if path in _STRICT_LIST_FIELD_PATHS:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return True


def _drop_incompatible_model_values(fields: dict[str, Any]) -> set[str]:
    invalid_paths: set[str] = set()
    checked_paths = (
        *_STRICT_TEXT_FIELD_PATHS,
        *_STRICT_LIST_FIELD_PATHS,
        "conversion.contact_destination",
        *_STRICT_BOOLEAN_FIELD_PATHS,
    )
    for path in checked_paths:
        value = _path_value(fields, path)
        if value is not None and not _model_field_value_is_compatible(path, value):
            invalid_paths.add(path)
    for path in invalid_paths:
        parts = path.split(".")
        current: Any = fields
        for part in parts[:-1]:
            if not isinstance(current, dict):
                break
            current = current.get(part)
        if isinstance(current, dict):
            current.pop(parts[-1], None)
    return invalid_paths


@dataclass(frozen=True)
class IntakeFieldProvenance:
    path: str
    origin: str
    source_message_id: int | None = None
    note: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IntakeFieldProvenance":
        value = _object(raw, "provenance")
        unknown = set(value) - {"path", "origin", "source_message_id", "note"}
        if unknown:
            raise ContractError("provenance contains unsupported fields")
        path = _path(value.get("path"), "provenance.path")
        origin = _text(value.get("origin"), "provenance.origin", maximum=30).lower()
        if origin not in {item.value for item in IntakeOrigin}:
            raise ContractError("provenance.origin is invalid")
        return cls(
            path=path,
            origin=origin,
            source_message_id=_optional_positive_id(value.get("source_message_id"), "provenance.source_message_id"),
            note=_text(value.get("note"), "provenance.note", required=False, maximum=2_000),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "origin": self.origin,
            "source_message_id": self.source_message_id,
            "note": self.note,
        }


@dataclass(frozen=True)
class IntakeDisposition:
    path: str
    note: str
    value: Any = None
    source_message_id: int | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], name: str = "disposition") -> "IntakeDisposition":
        value = _object(raw, name)
        unknown = set(value) - {"path", "note", "value", "source_message_id"}
        if unknown:
            raise ContractError(f"{name} contains unsupported fields")
        return cls(
            path=_path(value.get("path"), f"{name}.path"),
            note=_text(value.get("note"), f"{name}.note", maximum=2_000),
            value=copy.deepcopy(value.get("value")),
            source_message_id=_optional_positive_id(value.get("source_message_id"), f"{name}.source_message_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "note": self.note,
            "value": copy.deepcopy(self.value),
            "source_message_id": self.source_message_id,
        }


@dataclass(frozen=True)
class IntakeContradiction:
    path: str
    first_value: Any
    second_value: Any
    first_source_message_id: int | None = None
    second_source_message_id: int | None = None
    resolution: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IntakeContradiction":
        value = _object(raw, "contradiction")
        unknown = set(value) - {
            "path", "first_value", "second_value", "first_source_message_id",
            "second_source_message_id", "resolution",
        }
        if unknown:
            raise ContractError("contradiction contains unsupported fields")
        return cls(
            path=_path(value.get("path"), "contradiction.path"),
            first_value=copy.deepcopy(value.get("first_value")),
            second_value=copy.deepcopy(value.get("second_value")),
            first_source_message_id=_optional_positive_id(value.get("first_source_message_id"), "contradiction.first_source_message_id"),
            second_source_message_id=_optional_positive_id(value.get("second_source_message_id"), "contradiction.second_source_message_id"),
            resolution=_text(value.get("resolution"), "contradiction.resolution", required=False, maximum=2_000),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "first_value": copy.deepcopy(self.first_value),
            "second_value": copy.deepcopy(self.second_value),
            "first_source_message_id": self.first_source_message_id,
            "second_source_message_id": self.second_source_message_id,
            "resolution": self.resolution,
        }


@dataclass(frozen=True)
class IntakeAssetBinding:
    asset_id: int
    position: int
    # Uploaded references are available to the initial visual build by default.
    # ``inspiration_only`` remains an explicit opt-out; ``undecided`` is kept as
    # a legacy wire value and is normalized to ``website`` below.
    usage: str = IntakeAssetUsage.WEBSITE.value
    reference_aspects: tuple[str, ...] = ()
    owner_note: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IntakeAssetBinding":
        value = _object(raw, "asset_binding")
        unknown = set(value) - {"asset_id", "position", "usage", "reference_aspects", "owner_note"}
        if unknown:
            raise ContractError("asset_binding contains unsupported fields")
        asset_id = value.get("asset_id")
        if isinstance(asset_id, bool) or not isinstance(asset_id, int) or asset_id < 1:
            raise ContractError("asset_binding.asset_id must be a positive integer")
        position = value.get("position", 0)
        if isinstance(position, bool) or not isinstance(position, int) or position < 0 or position >= _MAX_ITEMS:
            raise ContractError("asset_binding.position is invalid")
        usage = _text(value.get("usage", IntakeAssetUsage.WEBSITE.value), "asset_binding.usage", maximum=30).lower()
        if usage not in {item.value for item in IntakeAssetUsage}:
            raise ContractError("asset_binding.usage is invalid")
        if usage == IntakeAssetUsage.UNDECIDED.value:
            # Older clients persisted an owner-decision state.  The visual
            # builder, not the owner, now chooses which supplied images to use.
            usage = IntakeAssetUsage.WEBSITE.value
        aspects = _list(value.get("reference_aspects"), "asset_binding.reference_aspects", maximum=20)
        normalized_aspects = tuple(_text(item, "asset_binding.reference_aspect", maximum=40).lower() for item in aspects)
        return cls(
            asset_id=asset_id,
            position=position,
            usage=usage,
            reference_aspects=normalized_aspects,
            owner_note=_text(value.get("owner_note"), "asset_binding.owner_note", required=False, maximum=2_000),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "position": self.position,
            "usage": self.usage,
            "reference_aspects": list(self.reference_aspects),
            "owner_note": self.owner_note,
        }


@dataclass(frozen=True)
class DesignIntakeDraft:
    schema_version: int
    fields: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, IntakeFieldProvenance] = field(default_factory=dict)
    assumptions: tuple[IntakeDisposition, ...] = ()
    deferred: tuple[IntakeDisposition, ...] = ()
    contradictions: tuple[IntakeContradiction, ...] = ()
    open_topics: tuple[str, ...] = ()
    assets: tuple[IntakeAssetBinding, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DesignIntakeDraft":
        value = _object(raw, "design_intake_draft")
        version = value.get("schema_version")
        if isinstance(version, bool) or version != DESIGN_INTAKE_SCHEMA_VERSION:
            raise ContractError(f"design_intake_draft.schema_version must be {DESIGN_INTAKE_SCHEMA_VERSION}")
        fields = _object(value.get("fields") or {}, "design_intake_draft.fields")
        _validate_field_tree(fields)
        invalid_field_paths = _drop_incompatible_model_values(fields)
        provenance_raw = value.get("provenance") or {}
        if not isinstance(provenance_raw, Mapping):
            raise ContractError("design_intake_draft.provenance must be an object")
        provenance: dict[str, IntakeFieldProvenance] = {}
        for key, item in provenance_raw.items():
            if not isinstance(key, str) or key not in _ALLOWED_FIELD_PATHS:
                raise ContractError("provenance contains an invalid intake field")
            if key in invalid_field_paths:
                continue
            if not isinstance(item, Mapping):
                raise ContractError("provenance entries must be objects")
            item_data = dict(item)
            supplied_path = item_data.pop("path", key)
            if supplied_path != key:
                raise ContractError("provenance.path does not match its field key")
            provenance_item = IntakeFieldProvenance.from_dict({"path": key, **item_data})
            provenance[provenance_item.path] = provenance_item
        assumptions = tuple(
            item for item in (
                IntakeDisposition.from_dict(item, "assumption")
                for item in _list(value.get("assumptions"), "design_intake_draft.assumptions")
            )
            if item.path not in invalid_field_paths
        )
        deferred = tuple(
            item for item in (
                IntakeDisposition.from_dict(item, "deferred")
                for item in _list(value.get("deferred"), "design_intake_draft.deferred")
            )
            if item.path not in invalid_field_paths
        )
        contradictions = tuple(
            IntakeContradiction.from_dict(item)
            for item in _list(value.get("contradictions"), "design_intake_draft.contradictions")
        )
        open_topics = tuple(
            _text(item, "design_intake_draft.open_topics[]", maximum=300)
            for item in _list(value.get("open_topics"), "design_intake_draft.open_topics", maximum=30)
        )
        assets = tuple(
            IntakeAssetBinding.from_dict(item)
            for item in _list(value.get("assets"), "design_intake_draft.assets", maximum=20)
        )
        known = {
            "schema_version", "fields", "provenance", "assumptions", "deferred",
            "contradictions", "open_topics", "assets", "readiness",
        }
        unknown = sorted(set(value) - known)
        if unknown:
            raise ContractError("design_intake_draft contains unsupported fields: " + ", ".join(unknown[:5]))
        result = cls(
            schema_version=version,
            fields=fields,
            provenance=provenance,
            assumptions=assumptions,
            deferred=deferred,
            contradictions=contradictions,
            open_topics=open_topics,
            assets=tuple(sorted(assets, key=lambda item: (item.position, item.asset_id))),
            extra={},
        )
        supplied_readiness = value.get("readiness")
        if supplied_readiness is not None and supplied_readiness not in {
            item.value for item in IntakeSessionState
        }:
            raise ContractError("design_intake_draft.readiness is invalid")
        result.validate()
        return result

    @classmethod
    def empty(cls) -> "DesignIntakeDraft":
        return cls(schema_version=DESIGN_INTAKE_SCHEMA_VERSION)

    @classmethod
    def from_site_intake(cls, intake: SiteIntake) -> "DesignIntakeDraft":
        if not isinstance(intake, SiteIntake):
            raise ContractError("intake must be a validated SiteIntake")
        fields = {
            "business": _allowed_field_subset(intake.business, "business"),
            "audience": _allowed_field_subset(intake.audience, "audience"),
            "conversion": _allowed_field_subset(intake.conversion, "conversion"),
            "brand": _allowed_field_subset(intake.brand, "brand"),
            "site": _allowed_field_subset(intake.site, "site"),
            "constraints": _allowed_field_subset(intake.constraints, "constraints"),
            "design": {"assumption_permission": "owner-approved"},
        }
        provenance = {
            path: IntakeFieldProvenance(path=path, origin=IntakeOrigin.CONFIRMED.value, note="Imported from a validated intake.")
            for path in _field_paths(fields)
        }
        assets: list[IntakeAssetBinding] = []
        for position, asset in enumerate(intake.assets):
            if isinstance(asset, Mapping) and isinstance(asset.get("id"), str) and str(asset["id"]).isdigit():
                assets.append(IntakeAssetBinding.from_dict({
                    "asset_id": int(asset["id"]),
                    "position": position,
                    "usage": str(asset.get("usage") or IntakeAssetUsage.WEBSITE.value),
                    "reference_aspects": list(asset.get("reference_aspects") or ()),
                    "owner_note": str(asset.get("owner_note") or ""),
                }))
        return cls(schema_version=DESIGN_INTAKE_SCHEMA_VERSION, fields=fields, provenance=provenance, assets=tuple(assets))

    def validate(self) -> None:
        _validate_field_tree(self.fields)
        material_paths = set(_field_paths(self.fields))
        for path in self.provenance:
            _path(path, "provenance.path")
        missing_provenance = sorted(material_paths - set(self.provenance))
        if missing_provenance:
            raise ContractError("missing provenance for " + ", ".join(missing_provenance[:5]))
        seen: set[str] = set()
        for item in (*self.assumptions, *self.deferred):
            if item.path in seen:
                raise ContractError(f"intake disposition is duplicated for {item.path}")
            seen.add(item.path)
        for item in self.assets:
            if item.asset_id < 1:
                raise ContractError("asset binding ID is invalid")
        canonical_hash(self.to_dict())

    def value(self, path: str) -> Any:
        return _path_value(self.fields, _path(path))

    def owner_confirmed_value(self, path: str) -> Any:
        """Return a value the owner stated or explicitly accepted."""
        path = _path(path)
        provenance = self.provenance.get(path)
        if provenance is None or provenance.origin not in _OWNER_CONFIRMED_ORIGINS:
            return None
        return self.value(path)

    @property
    def location_context_resolved(self) -> bool:
        """Require an owner location, service area, or explicit opt-out."""
        for path in ("business.location", "business.service_area"):
            if _value_present(self.owner_confirmed_value(path)):
                return True
        return self.owner_confirmed_value("business.location_not_applicable") is True

    def with_value(self, path: str, value: Any, provenance: IntakeFieldProvenance) -> "DesignIntakeDraft":
        path = _path(path)
        if provenance.path != path:
            raise ContractError("provenance path does not match updated field")
        fields = copy.deepcopy(self.fields)
        _copy_path_set(fields, path, value)
        updated = dict(self.provenance)
        updated[path] = provenance
        assumptions = tuple(item for item in self.assumptions if item.path != path)
        deferred = tuple(item for item in self.deferred if item.path != path)
        contradictions = tuple(item for item in self.contradictions if item.path != path or item.resolution)
        return DesignIntakeDraft(
            schema_version=self.schema_version,
            fields=fields,
            provenance=updated,
            assumptions=assumptions,
            deferred=deferred,
            contradictions=contradictions,
            open_topics=self.open_topics,
            assets=self.assets,
            extra=self.extra,
        )

    @property
    def unresolved_core_paths(self) -> tuple[str, ...]:
        unresolved: list[str] = []
        for path in _CORE_PATHS:
            if path == "business.location":
                if self.location_context_resolved:
                    continue
                unresolved.append(path)
                continue
            value = self.value(path)
            if _model_field_value_is_compatible(path, value) and _value_present(value):
                if path == "business.name" and not self._name_owner_stated():
                    unresolved.append(path)
                continue
            if any(item.path == path for item in (*self.assumptions, *self.deferred)):
                continue
            unresolved.append(path)
        return tuple(unresolved)

    def _name_owner_stated(self) -> bool:
        """A brand name only counts for readiness when the owner stated it.

        A synthesized or model-derived name (recommendation) must never unlock
        the build gate on its own; the advisor has to ask the owner for the real
        name instead. An owner acceptance of a proposed name is treated as a
        genuine owner decision.
        """
        provenance = self.provenance.get("business.name")
        if provenance is None:
            return False
        return provenance.origin in {
            IntakeOrigin.CONFIRMED.value,
            IntakeOrigin.ADVISED.value,
        }

    @property
    def readiness(self) -> str:
        if self.contradictions and not all(item.resolution.strip() for item in self.contradictions):
            return IntakeSessionState.COLLECTING.value
        if self.unresolved_core_paths:
            return IntakeSessionState.COLLECTING.value
        try:
            self.to_site_intake()
        except (ContractError, ValueError):
            return IntakeSessionState.COLLECTING.value
        return IntakeSessionState.READY_TO_BUILD.value

    @property
    def undecided_assets(self) -> tuple[IntakeAssetBinding, ...]:
        return tuple(
            item for item in self.assets
            if item.usage == IntakeAssetUsage.UNDECIDED.value
        )

    def to_site_intake(self) -> SiteIntake:
        """Apply only safe, reversible defaults and validate the final intake."""
        fields = copy.deepcopy(self.fields)
        _drop_incompatible_model_values(fields)
        if not _value_present(_path_value(fields, "business.name")):
            _copy_path_set(fields, "business.name", "Working website")
        offer = _path_value(fields, "business.offer_summary")
        if not _value_present(offer):
            raise ContractError("business.offer_summary is required before building")
        if not _value_present(_path_value(fields, "business.primary_services")):
            _copy_path_set(fields, "business.primary_services", [str(offer).strip()])
        if not _value_present(_path_value(fields, "audience.primary")):
            _copy_path_set(fields, "audience.primary", "People considering this offer")
        if not _value_present(_path_value(fields, "conversion.primary_action")):
            _copy_path_set(fields, "conversion.primary_action", "Learn more and get in touch")
        if not _value_present(_path_value(fields, "brand.voice")):
            _copy_path_set(fields, "brand.voice", "Clear, warm, and specific")
        if not _value_present(_path_value(fields, "site.required_pages")):
            _copy_path_set(fields, "site.required_pages", ["index.html"])
        conversion = fields.setdefault("conversion", {})
        if not isinstance(conversion, dict):
            conversion = {}
            fields["conversion"] = conversion
        if not _value_present(conversion.get("contact_destination")):
            conversion["contact_destination"] = None
            conversion["not_available"] = True
        design = fields.setdefault("design", {})
        if not isinstance(design, dict):
            design = {}
            fields["design"] = design
        design["assumptions"] = [item.to_dict() for item in self.assumptions]
        design["deferred"] = [item.to_dict() for item in self.deferred]
        design["provenance"] = {path: item.to_dict() for path, item in self.provenance.items()}
        assets = []
        for item in self.assets:
            assets.append({
                "id": str(item.asset_id),
                "usage": item.usage,
                "position": item.position,
                "reference_aspects": list(item.reference_aspects),
                "owner_note": item.owner_note,
            })
        if assets:
            fields["assets"] = assets
        fields["provenance"] = {
            **(fields.get("provenance") if isinstance(fields.get("provenance"), Mapping) else {}),
            "intake_draft_hash": self.content_hash,
            "assumptions": [item.to_dict() for item in self.assumptions],
            "deferred": [item.to_dict() for item in self.deferred],
        }
        fields["unknowns"] = [item.note for item in self.deferred]
        fields["schema_version"] = 1
        return SiteIntake.from_dict(fields)

    def to_dict(self) -> dict[str, Any]:
        result = {
            **copy.deepcopy(self.extra),
            "schema_version": self.schema_version,
            "fields": copy.deepcopy(self.fields),
            "provenance": {path: item.to_dict() for path, item in sorted(self.provenance.items())},
            "assumptions": [item.to_dict() for item in self.assumptions],
            "deferred": [item.to_dict() for item in self.deferred],
            "contradictions": [item.to_dict() for item in self.contradictions],
            "open_topics": list(self.open_topics),
            "assets": [item.to_dict() for item in self.assets],
        }
        # Readiness is derived from the draft and must not participate in the
        # hash used while checking whether the draft can become a SiteIntake.
        result["readiness"] = self.readiness
        return result

    @property
    def content_hash(self) -> str:
        return canonical_hash({
            **copy.deepcopy(self.extra),
            "schema_version": self.schema_version,
            "fields": copy.deepcopy(self.fields),
            "provenance": {path: item.to_dict() for path, item in sorted(self.provenance.items())},
            "assumptions": [item.to_dict() for item in self.assumptions],
            "deferred": [item.to_dict() for item in self.deferred],
            "contradictions": [item.to_dict() for item in self.contradictions],
            "open_topics": list(self.open_topics),
            "assets": [item.to_dict() for item in self.assets],
        })

    def summary(self) -> "IntakeSummary":
        return IntakeSummary.from_draft(self)


@dataclass(frozen=True)
class IntakeSummary:
    """Owner-facing, read-only grouping of a draft's decisions."""

    schema_version: int
    readiness: str
    confirmed: dict[str, Any] = field(default_factory=dict)
    advised: dict[str, Any] = field(default_factory=dict)
    assumed: tuple[IntakeDisposition, ...] = ()
    deferred: tuple[IntakeDisposition, ...] = ()
    contradictions: tuple[IntakeContradiction, ...] = ()
    website_assets: tuple[IntakeAssetBinding, ...] = ()
    inspiration_assets: tuple[IntakeAssetBinding, ...] = ()
    undecided_assets: tuple[IntakeAssetBinding, ...] = ()
    open_topics: tuple[str, ...] = ()

    @classmethod
    def from_draft(cls, draft: DesignIntakeDraft) -> "IntakeSummary":
        confirmed: dict[str, Any] = {}
        advised: dict[str, Any] = {}
        assumed_paths = {item.path for item in draft.assumptions}
        deferred_paths = {item.path for item in draft.deferred}
        for path, provenance in draft.provenance.items():
            value = _path_value(draft.fields, path)
            if provenance.origin == IntakeOrigin.CONFIRMED.value:
                confirmed[path] = copy.deepcopy(value)
            elif provenance.origin == IntakeOrigin.ADVISED.value:
                advised[path] = copy.deepcopy(value)
            elif provenance.origin == IntakeOrigin.ASSUMED.value and path not in assumed_paths:
                assumed_paths.add(path)
            elif provenance.origin == IntakeOrigin.DEFERRED.value and path not in deferred_paths:
                deferred_paths.add(path)
        assumptions = list(draft.assumptions)
        deferred = list(draft.deferred)
        for path in sorted(assumed_paths):
            if not any(item.path == path for item in assumptions):
                assumptions.append(IntakeDisposition(path=path, note="Ada selected a reversible default.", value=_path_value(draft.fields, path)))
        for path in sorted(deferred_paths):
            if not any(item.path == path for item in deferred):
                deferred.append(IntakeDisposition(path=path, note="The owner deferred this detail.", value=_path_value(draft.fields, path)))
        assets = {
            IntakeAssetUsage.WEBSITE.value: [],
            IntakeAssetUsage.INSPIRATION_ONLY.value: [],
            IntakeAssetUsage.UNDECIDED.value: [],
        }
        for asset in draft.assets:
            assets.setdefault(asset.usage, []).append(asset)
        return cls(
            schema_version=draft.schema_version,
            readiness=draft.readiness,
            confirmed=confirmed,
            advised=advised,
            assumed=tuple(sorted(assumptions, key=lambda item: item.path)),
            deferred=tuple(sorted(deferred, key=lambda item: item.path)),
            contradictions=draft.contradictions,
            website_assets=tuple(assets[IntakeAssetUsage.WEBSITE.value]),
            inspiration_assets=tuple(assets[IntakeAssetUsage.INSPIRATION_ONLY.value]),
            undecided_assets=tuple(assets[IntakeAssetUsage.UNDECIDED.value]),
            open_topics=draft.open_topics,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "readiness": self.readiness,
            "confirmed": copy.deepcopy(self.confirmed),
            "advised": copy.deepcopy(self.advised),
            "assumed": [item.to_dict() for item in self.assumed],
            "deferred": [item.to_dict() for item in self.deferred],
            "contradictions": [item.to_dict() for item in self.contradictions],
            "assets": {
                "website": [item.to_dict() for item in self.website_assets],
                "inspiration_only": [item.to_dict() for item in self.inspiration_assets],
                "undecided": [item.to_dict() for item in self.undecided_assets],
            },
            "open_topics": list(self.open_topics),
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class IntakeFieldUpdate:
    path: str
    value: Any
    basis: str
    note: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IntakeFieldUpdate":
        value = _object(raw, "field_update")
        unknown = set(value) - {"path", "value", "basis", "note"}
        if unknown:
            raise ContractError("field_update contains unsupported fields")
        path = _path(value.get("path"), "field_update.path")
        basis = _text(value.get("basis", IntakeUpdateBasis.OWNER_STATEMENT.value), "field_update.basis", maximum=40).lower()
        if basis not in {item.value for item in IntakeUpdateBasis}:
            raise ContractError("field_update.basis is invalid")
        return cls(path=path, value=copy.deepcopy(value.get("value")), basis=basis,
                   note=_text(value.get("note"), "field_update.note", required=False, maximum=2_000))

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "value": copy.deepcopy(self.value), "basis": self.basis, "note": self.note}


_CREATIVE_INSIGHT_KINDS = frozenset({
    "audience_language", "audience_concern", "audience_desire", "business_context",
    "content_opportunity", "creative_implication", "contradiction",
})

_LEGACY_INTAKE_TURN_FIELDS = frozenset({"open_questions", "topics_addressed", "next_topics"})


@dataclass(frozen=True)
class CreativeInsight:
    """A bounded design interpretation that is never an owner-confirmed fact."""

    kind: str
    summary: str
    basis: str
    related_intake_paths: tuple[str, ...] = ()
    related_asset_ids: tuple[int, ...] = ()
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CreativeInsight":
        value = _object(raw, "creative_insight")
        unknown = set(value) - {
            "kind", "summary", "basis", "related_intake_paths", "related_asset_ids", "confidence",
        }
        if unknown:
            raise ContractError("creative_insight contains unsupported fields")
        kind = _text(value.get("kind"), "creative_insight.kind", maximum=40).lower()
        if kind not in _CREATIVE_INSIGHT_KINDS:
            raise ContractError("creative_insight.kind is invalid")
        summary = _text(value.get("summary"), "creative_insight.summary", maximum=2_000)
        if re.search(r"https?://|\b[^\s@]+@[^\s@]+\.[^\s@]+\b|(?:^|\s)(?:/|[A-Za-z]:[\\/])", summary, re.IGNORECASE):
            raise ContractError("creative_insight.summary contains prohibited private detail")
        basis = _text(value.get("basis", IntakeUpdateBasis.RECOMMENDATION.value), "creative_insight.basis", maximum=40).lower()
        if basis not in {item.value for item in IntakeUpdateBasis}:
            raise ContractError("creative_insight.basis is invalid")
        paths = tuple(_path(item, f"creative_insight.related_intake_paths[{index}]") for index, item in enumerate(
            _list(value.get("related_intake_paths"), "creative_insight.related_intake_paths", required=False, maximum=12)
        ))
        raw_asset_ids = _list(value.get("related_asset_ids"), "creative_insight.related_asset_ids", required=False, maximum=20)
        asset_ids: list[int] = []
        for index, item in enumerate(raw_asset_ids):
            asset_id = _optional_positive_id(item, f"creative_insight.related_asset_ids[{index}]")
            if asset_id is None:
                raise ContractError("creative_insight.related_asset_ids must contain positive integers")
            asset_ids.append(asset_id)
        confidence = value.get("confidence", 0.0)
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ContractError("creative_insight.confidence must be between 0 and 1")
        return cls(
            kind=kind,
            summary=summary,
            basis=basis,
            related_intake_paths=paths,
            related_asset_ids=tuple(asset_ids),
            confidence=float(confidence),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "basis": self.basis,
            "related_intake_paths": list(self.related_intake_paths),
            "related_asset_ids": list(self.related_asset_ids),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class IntakeTurnResult:
    schema_version: int
    assistant_message: str
    field_updates: tuple[IntakeFieldUpdate, ...] = ()
    assumption_updates: tuple[IntakeDisposition, ...] = ()
    deferred_updates: tuple[IntakeDisposition, ...] = ()
    contradictions: tuple[IntakeContradiction, ...] = ()
    suggested_readiness: str = IntakeSessionState.COLLECTING.value
    creative_insights: tuple[CreativeInsight, ...] = ()
    ui_action: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IntakeTurnResult":
        value = {
            key: item
            for key, item in _object(raw, "intake_turn_result").items()
            if key not in _LEGACY_INTAKE_TURN_FIELDS
        }
        known = {
            "schema_version", "assistant_message", "field_updates", "assumption_updates", "deferred_updates",
            "contradictions", "suggested_readiness", "creative_insights", "ui_action",
        }
        unknown = sorted(set(value) - known)
        if unknown:
            raise ContractError("intake_turn_result contains unsupported fields: " + ", ".join(unknown[:5]))
        version = value.get("schema_version", DESIGN_INTAKE_SCHEMA_VERSION)
        if isinstance(version, bool) or version != DESIGN_INTAKE_SCHEMA_VERSION:
            raise ContractError(f"intake_turn_result.schema_version must be {DESIGN_INTAKE_SCHEMA_VERSION}")
        updates = tuple(
            update for update in (
                IntakeFieldUpdate.from_dict(item)
                for item in _list(value.get("field_updates"), "field_updates")
            )
            if _model_field_value_is_compatible(update.path, update.value)
        )
        assumptions = tuple(IntakeDisposition.from_dict(item, "assumption_update") for item in _list(value.get("assumption_updates"), "assumption_updates"))
        deferred = tuple(IntakeDisposition.from_dict(item, "deferred_update") for item in _list(value.get("deferred_updates"), "deferred_updates"))
        contradictions = tuple(IntakeContradiction.from_dict(item) for item in _list(value.get("contradictions"), "contradictions"))
        suggested = _text(value.get("suggested_readiness", IntakeSessionState.COLLECTING.value), "suggested_readiness", maximum=30).lower()
        if suggested not in {item.value for item in IntakeSessionState if item is not IntakeSessionState.CONFIRMED}:
            raise ContractError("suggested_readiness is invalid")
        result = cls(
            schema_version=version,
            assistant_message=_text(value.get("assistant_message"), "assistant_message", maximum=8_000),
            field_updates=updates,
            assumption_updates=assumptions,
            deferred_updates=deferred,
            contradictions=contradictions,
            suggested_readiness=suggested,
            creative_insights=tuple(
                CreativeInsight.from_dict(item)
                for item in _list(value.get("creative_insights"), "creative_insights", required=False, maximum=8)
            ),
            ui_action=_safe_ui_action(value.get("ui_action")),
            extra={},
        )
        canonical_hash(result.to_dict())
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            **copy.deepcopy(self.extra),
            "schema_version": self.schema_version,
            "assistant_message": self.assistant_message,
            "field_updates": [item.to_dict() for item in self.field_updates],
            "assumption_updates": [item.to_dict() for item in self.assumption_updates],
            "deferred_updates": [item.to_dict() for item in self.deferred_updates],
            "contradictions": [item.to_dict() for item in self.contradictions],
            "suggested_readiness": self.suggested_readiness,
            "creative_insights": [item.to_dict() for item in self.creative_insights],
            "ui_action": dict(self.ui_action),
        }


def _safe_ui_action(value: Any) -> dict[str, Any]:
    """Normalize an optional model-proposed UI action, ignoring malformed values.

    The advisor may propose an action so the owner's intent ("show me the new
    version") becomes a machine-executable step. Any invalid proposal is dropped
    silently so a stray model field can never break a conversation turn.
    """
    if not isinstance(value, dict):
        return {}
    action = str(value.get("action") or "").strip().lower()
    if action not in {"open_preview", "start_build"}:
        return {}
    result: dict[str, Any] = {"action": action}
    run_id = str(value.get("run_id") or "").strip()
    if action == "open_preview":
        if not run_id:
            return {}
        result["run_id"] = run_id
    elif isinstance(value.get("fresh"), bool):
        result["fresh"] = value["fresh"]
    return result


def merge_intake_turn(
    draft: DesignIntakeDraft,
    turn: IntakeTurnResult,
    *,
    source_message_id: int,
) -> DesignIntakeDraft:
    """Apply a validated model turn while assigning provenance in the service."""
    if isinstance(source_message_id, bool) or source_message_id < 1:
        raise ContractError("source_message_id must be positive")
    current = draft
    assumptions = {item.path: item for item in current.assumptions}
    deferred = {item.path: item for item in current.deferred}
    for update in turn.field_updates:
        if not _model_field_value_is_compatible(update.path, update.value):
            continue
        if update.basis in {IntakeUpdateBasis.OWNER_STATEMENT.value, IntakeUpdateBasis.OWNER_CORRECTION.value}:
            origin = IntakeOrigin.CONFIRMED.value
        elif update.basis == IntakeUpdateBasis.OWNER_ACCEPTANCE.value:
            origin = IntakeOrigin.ADVISED.value
        elif update.basis == IntakeUpdateBasis.DEFERRED.value:
            origin = IntakeOrigin.DEFERRED.value
        else:
            origin = IntakeOrigin.ASSUMED.value
        current = current.with_value(
            update.path,
            update.value,
            IntakeFieldProvenance(path=update.path, origin=origin, source_message_id=source_message_id, note=update.note),
        )
        assumptions.pop(update.path, None)
        deferred.pop(update.path, None)
    for item in turn.assumption_updates:
        deferred.pop(item.path, None)
        assumptions[item.path] = IntakeDisposition(
            path=item.path, note=item.note, value=copy.deepcopy(item.value), source_message_id=source_message_id,
        )
        if item.value is not None:
            current = current.with_value(
                item.path,
                item.value,
                IntakeFieldProvenance(
                    path=item.path,
                    origin=IntakeOrigin.ASSUMED.value,
                    source_message_id=source_message_id,
                    note=item.note,
                ),
            )
    for item in turn.deferred_updates:
        assumptions.pop(item.path, None)
        deferred[item.path] = IntakeDisposition(
            path=item.path, note=item.note, value=copy.deepcopy(item.value), source_message_id=source_message_id,
        )
        if item.value is not None:
            current = current.with_value(
                item.path,
                item.value,
                IntakeFieldProvenance(
                    path=item.path,
                    origin=IntakeOrigin.DEFERRED.value,
                    source_message_id=source_message_id,
                    note=item.note,
                ),
            )
    contradictions = list(current.contradictions)
    existing = {(item.path, canonical_json(item.first_value), canonical_json(item.second_value)) for item in contradictions}
    for item in turn.contradictions:
        key = (item.path, canonical_json(item.first_value), canonical_json(item.second_value))
        if key not in existing:
            contradictions.append(IntakeContradiction(
                path=item.path,
                first_value=item.first_value,
                second_value=item.second_value,
                first_source_message_id=source_message_id,
                second_source_message_id=None,
                resolution=item.resolution,
            ))
            existing.add(key)
    return DesignIntakeDraft(
        schema_version=current.schema_version,
        fields=current.fields,
        provenance=current.provenance,
        assumptions=tuple(sorted(assumptions.values(), key=lambda item: item.path)),
        deferred=tuple(sorted(deferred.values(), key=lambda item: item.path)),
        contradictions=tuple(contradictions),
        open_topics=current.open_topics,
        assets=current.assets,
        extra=current.extra,
    )


__all__ = [
    "DESIGN_INTAKE_SCHEMA_VERSION",
    "DesignIntakeDraft",
    "CreativeInsight",
    "IntakeAssetBinding",
    "IntakeAssetUsage",
    "IntakeContradiction",
    "IntakeDisposition",
    "IntakeFieldProvenance",
    "IntakeFieldUpdate",
    "IntakeOrigin",
    "IntakeSessionState",
    "IntakeSummary",
    "IntakeTurnResult",
    "IntakeUpdateBasis",
    "allowed_intake_field_paths",
    "merge_intake_turn",
]
