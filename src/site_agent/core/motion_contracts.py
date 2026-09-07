"""Typed, non-executable motion plans for design candidates.

The model may describe choreography, but the plan is never evaluated as code.
The site implementation remains ordinary candidate source and is checked by the
host.  Keeping the plan separate gives review, reduced-motion checks, and
provisioning a stable record of what was intended without granting the model a
new execution channel.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .contracts import ContractError
from .design_contracts import canonical_hash, safe_relative_path


MOTION_PLAN_SCHEMA_VERSION = 1
MOTION_CAPABILITIES = frozenset({
    "core",
    "timeline",
    "stagger",
    "scrolltrigger",
    "parallax",
    "pin",
    "scrub",
    "hover",
    "flip",
    "observer",
    "draggable",
    "react",
    "signature",
})
MOTION_KINDS = frozenset({
    "entrance",
    "timeline",
    "stagger",
    "parallax",
    "pin",
    "scrub",
    "hover",
    "flip",
    "observer",
    "draggable",
    "signature",
})
_MOTION_CAPABILITY_ALIASES = {
    "base": "core",
    "animation": "core",
    "animation-core": "core",
    "gsap": "core",
    "gsap-core": "core",
    "timeline-animation": "timeline",
    "staggered": "stagger",
    "scroll-trigger": "scrolltrigger",
    "scrolltrigger-plugin": "scrolltrigger",
    "parallax-scroll": "parallax",
    "drag": "draggable",
    "signature-interaction": "signature",
    "react-component": "react",
    "react-island": "react",
}
REDUCED_MOTION_STRATEGIES = frozenset({"static", "fade-only", "alternate"})
_REDUCED_MOTION_STRATEGY_ALIASES = {
    "static": "static",
    "none": "static",
    "no-animation": "static",
    "no-animations": "static",
    "no-motion": "static",
    "no-transforms": "static",
    "transform-free": "static",
    "disabled": "static",
    "disabled-motion": "static",
    "disable": "static",
    "reduced-motion": "static",
    "preserve-content": "static",
    "preserve-content-only": "static",
    "content-preserving": "static",
    "fade": "fade-only",
    "fade-only": "fade-only",
    "fade-only-motion": "fade-only",
    "opacity": "fade-only",
    "opacity-only": "fade-only",
    "opacity-only-motion": "fade-only",
    "alternate": "alternate",
    "alternative": "alternate",
    "alternative-motion": "alternate",
    "content-alternative": "alternate",
    "non-motion-alternative": "alternate",
}
_REQUIRED_CAPABILITIES = {
    "timeline": frozenset({"timeline", "core"}),
    "stagger": frozenset({"stagger", "core"}),
    "parallax": frozenset({"parallax", "scrolltrigger", "core"}),
    "pin": frozenset({"pin", "scrolltrigger", "core"}),
    "scrub": frozenset({"scrub", "scrolltrigger", "core"}),
    "hover": frozenset({"hover", "core"}),
    "flip": frozenset({"flip", "core"}),
    "observer": frozenset({"observer", "core"}),
    "draggable": frozenset({"draggable", "core"}),
    "signature": frozenset({"signature", "core"}),
}
_TARGET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,119}$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,119}$")
_POSITION_RE = re.compile(r"^[A-Za-z0-9_<>+=.:%\- ]{1,120}$")
_SAFE_TEXT_RE = re.compile(r"^[A-Za-z0-9 .,'()/_%+#=<>:+\-\[\]]+$")
_MOTION_VALUE_FIELDS = frozenset({
    "x", "y", "z", "xPercent", "yPercent", "scale", "scaleX", "scaleY",
    "rotation", "rotationX", "rotationY", "skewX", "skewY", "opacity",
    "autoAlpha", "transformOrigin", "backgroundColor", "color", "filter",
    "clipPath", "cssVariable",
})
_ACTION_FIELDS = frozenset({
    "kind", "capability", "target", "trigger", "at", "duration", "ease",
    "from", "to", "stagger", "start", "end", "scrub", "pin", "pin_spacing",
    "events", "axis", "bounds", "state", "custom_component_id", "repeat",
    "yoyo",
})
_OBSERVER_EVENTS = frozenset({"onUp", "onDown", "onLeft", "onRight", "onPress", "onRelease"})
_HOST_MOTION_TARGETS = frozenset({"body", "main-content", "page-shell", "signature-rays", "depth-value", "viewport"})
MOTION_COMPONENT_REGISTRY = {
    "motion-interaction": {
        "path": "src/components/interactive/MotionInteraction.tsx",
        "export": "default",
        "capabilities": frozenset({"react"}),
    },
}


def _object(value: Any, path: str, *, known: set[str] | frozenset[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{path} must be an object")
    result = copy.deepcopy(dict(value))
    if known is not None:
        unknown = sorted(set(result) - set(known))
        if unknown:
            raise ContractError(f"{path} contains unsupported fields: {', '.join(unknown[:5])}")
    return result


def _text(value: Any, path: str, *, maximum: int = 4_000, required: bool = True) -> str:
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
    if re.search(r"(?:javascript\s*:|<\s*/?\s*script\b|\bon\w+\s*=|\b(?:eval|Function)\s*\()", result, re.I):
        raise ContractError(f"{path} contains executable content")
    return result


def canonical_reduced_motion_strategy(value: Any) -> str | None:
    """Return the bounded reduced-motion strategy for model/provider wording."""
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return _REDUCED_MOTION_STRATEGY_ALIASES.get(normalized)


def canonical_motion_capability(value: Any) -> str | None:
    """Return the bounded motion capability for model/provider wording."""
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if normalized in MOTION_CAPABILITIES:
        return normalized
    return _MOTION_CAPABILITY_ALIASES.get(normalized)


def _name(value: Any, path: str) -> str:
    result = _text(value, path, maximum=120).lower()
    if not _NAME_RE.fullmatch(result):
        raise ContractError(f"{path} is not a safe identifier")
    return result


def _target(value: Any, path: str, *, required: bool = True) -> str:
    result = _text(value, path, maximum=120, required=required)
    if result and not _TARGET_RE.fullmatch(result):
        raise ContractError(f"{path} must be a motion target id, not executable selector text")
    return result


def _position(value: Any, path: str, *, required: bool = False) -> str | float:
    if isinstance(value, bool):
        raise ContractError(f"{path} must be a timeline position")
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or value < 0 or value > 600:
            raise ContractError(f"{path} must be between 0 and 600 seconds")
        return float(value)
    result = _text(value, path, maximum=120, required=required)
    if result and not _POSITION_RE.fullmatch(result):
        raise ContractError(f"{path} contains an unsafe timeline position")
    return result


def _bounded_tree(value: Any, path: str, *, depth: int = 0) -> Any:
    if depth > 5:
        raise ContractError(f"{path} is too deeply nested")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractError(f"{path} contains an invalid number")
        return value
    if isinstance(value, str):
        return _text(value, path, maximum=2_000)
    if isinstance(value, list):
        if len(value) > 40:
            raise ContractError(f"{path} contains too many items")
        return [_bounded_tree(item, f"{path}[{index}]", depth=depth + 1) for index, item in enumerate(value)]
    if isinstance(value, Mapping):
        if len(value) > 40:
            raise ContractError(f"{path} contains too many fields")
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", key):
                raise ContractError(f"{path} contains an invalid field name")
            result[key] = _bounded_tree(item, f"{path}.{key}", depth=depth + 1)
        return result
    raise ContractError(f"{path} contains an unsupported value")


def _motion_values(value: Any, path: str) -> dict[str, Any]:
    raw = _object(value, path)
    unknown = sorted(set(raw) - _MOTION_VALUE_FIELDS)
    if unknown:
        raise ContractError(f"{path} contains unsupported animation fields: {', '.join(unknown[:5])}")
    result: dict[str, Any] = {}
    for key, item in raw.items():
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise ContractError(f"{path}.{key} must be a scalar animation value")
        if isinstance(item, float) and not math.isfinite(item):
            raise ContractError(f"{path}.{key} contains an invalid number")
        if isinstance(item, str):
            item = _text(item, f"{path}.{key}", maximum=160)
            if not _SAFE_TEXT_RE.fullmatch(item):
                raise ContractError(f"{path}.{key} contains an unsafe animation value")
        result[key] = item
    return result


def _stagger(value: Any, path: str) -> float | dict[str, Any]:
    if isinstance(value, bool):
        raise ContractError(f"{path} must be a stagger amount or object")
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or value < 0 or value > 60:
            raise ContractError(f"{path} must be between 0 and 60 seconds")
        return float(value)
    raw = _object(value, path, known={"amount", "each", "from"})
    result: dict[str, Any] = {}
    for key in ("amount", "each"):
        if key in raw:
            result[key] = _stagger(raw[key], f"{path}.{key}") if isinstance(raw[key], Mapping) else _stagger(raw[key], f"{path}.{key}")
            if isinstance(result[key], dict):
                raise ContractError(f"{path}.{key} must be numeric")
    if "from" in raw:
        origin = raw["from"]
        if isinstance(origin, bool) or not isinstance(origin, (str, int)):
            raise ContractError(f"{path}.from must be a stagger origin")
        if isinstance(origin, str) and origin not in {"start", "center", "end", "edges", "random"}:
            raise ContractError(f"{path}.from is unsupported")
        result["from"] = origin
    if not result:
        raise ContractError(f"{path} must contain amount, each, or from")
    return result


def _events(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{path} must be a non-empty list")
    result: list[str] = []
    for index, item in enumerate(value):
        event = _text(item, f"{path}[{index}]", maximum=30)
        if event not in _OBSERVER_EVENTS:
            raise ContractError(f"{path}[{index}] is unsupported")
        if event not in result:
            result.append(event)
    return tuple(result)


@dataclass(frozen=True)
class MotionAction:
    kind: str
    capability: str
    target: str
    trigger: str = ""
    at: str | float = ""
    duration: float | None = None
    ease: str = ""
    from_values: dict[str, Any] = field(default_factory=dict)
    to_values: dict[str, Any] = field(default_factory=dict)
    stagger: float | dict[str, Any] | None = None
    start: str = ""
    end: str = ""
    scrub: bool | float | None = None
    pin: bool = False
    pin_spacing: bool | str = True
    events: tuple[str, ...] = ()
    axis: str = ""
    bounds: str = ""
    state: str = ""
    custom_component_id: str = ""
    repeat: int | None = None
    yoyo: bool = False

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], path: str) -> "MotionAction":
        value = _object(raw, path, known=_ACTION_FIELDS)
        kind = _text(value.get("kind"), f"{path}.kind", maximum=30).lower()
        if kind not in MOTION_KINDS:
            raise ContractError(f"{path}.kind is unsupported")
        raw_capability = _text(value.get("capability"), f"{path}.capability", maximum=120)
        capability = canonical_motion_capability(raw_capability)
        if capability is None:
            capability = _name(raw_capability, f"{path}.capability")
        if capability not in MOTION_CAPABILITIES:
            raise ContractError(f"{path}.capability is unsupported")
        required = _REQUIRED_CAPABILITIES.get(kind)
        if required and capability not in required:
            allowed = ", ".join(sorted(required))
            raise ContractError(f"{path}.capability must be one of {allowed} for {kind}")
        target = _target(value.get("target"), f"{path}.target")
        trigger = _target(value.get("trigger"), f"{path}.trigger", required=False)
        at = _position(value.get("at"), f"{path}.at") if "at" in value else ""

        duration = value.get("duration")
        if duration is not None:
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(float(duration)) or not 0 <= duration <= 60:
                raise ContractError(f"{path}.duration must be between 0 and 60 seconds")
            duration = float(duration)
        ease = _text(value.get("ease"), f"{path}.ease", maximum=120, required=False)
        if ease and not _SAFE_TEXT_RE.fullmatch(ease):
            raise ContractError(f"{path}.ease contains unsafe text")
        from_values = _motion_values(value["from"], f"{path}.from") if "from" in value else {}
        to_values = _motion_values(value["to"], f"{path}.to") if "to" in value else {}
        stagger = _stagger(value["stagger"], f"{path}.stagger") if "stagger" in value else None
        start = _text(value.get("start"), f"{path}.start", maximum=120, required=False)
        end = _text(value.get("end"), f"{path}.end", maximum=120, required=False)
        if start and not _POSITION_RE.fullmatch(start):
            raise ContractError(f"{path}.start contains an unsafe ScrollTrigger position")
        if end and not _POSITION_RE.fullmatch(end):
            raise ContractError(f"{path}.end contains an unsafe ScrollTrigger position")
        scrub = value.get("scrub")
        if scrub is not None:
            if isinstance(scrub, bool):
                pass
            elif isinstance(scrub, (int, float)) and math.isfinite(float(scrub)) and 0 < scrub <= 60:
                scrub = float(scrub)
            else:
                raise ContractError(f"{path}.scrub must be boolean or between 0 and 60 seconds")
        pin = value.get("pin", False)
        if not isinstance(pin, bool):
            raise ContractError(f"{path}.pin must be boolean")
        pin_spacing = value.get("pin_spacing", True)
        if not isinstance(pin_spacing, (bool, str)) or (isinstance(pin_spacing, str) and pin_spacing != "margin"):
            raise ContractError(f"{path}.pin_spacing must be boolean or margin")
        observer_events = _events(value["events"], f"{path}.events") if "events" in value else ()
        axis = _text(value.get("axis"), f"{path}.axis", maximum=20, required=False)
        if axis and axis not in {"x", "y", "x,y", "rotation"}:
            raise ContractError(f"{path}.axis is unsupported")
        bounds = _target(value.get("bounds"), f"{path}.bounds", required=False)
        state = _text(value.get("state"), f"{path}.state", maximum=120, required=False)
        component_id = _name(value.get("custom_component_id"), f"{path}.custom_component_id") if value.get("custom_component_id") else ""
        repeat = value.get("repeat")
        if repeat is not None:
            if isinstance(repeat, bool) or not isinstance(repeat, int) or not -1 <= repeat <= 20:
                raise ContractError(f"{path}.repeat must be between -1 and 20")
        yoyo = value.get("yoyo", False)
        if not isinstance(yoyo, bool):
            raise ContractError(f"{path}.yoyo must be boolean")
        return cls(
            kind=kind,
            capability=capability,
            target=target,
            trigger=trigger,
            at=at,
            duration=duration,
            ease=ease,
            from_values=from_values,
            to_values=to_values,
            stagger=stagger,
            start=start,
            end=end,
            scrub=scrub,
            pin=pin,
            pin_spacing=pin_spacing,
            events=observer_events,
            axis=axis,
            bounds=bounds,
            state=state,
            custom_component_id=component_id,
            repeat=repeat,
            yoyo=yoyo,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind,
            "capability": self.capability,
            "target": self.target,
        }
        for key, value in (
            ("trigger", self.trigger),
            ("at", self.at),
            ("duration", self.duration),
            ("ease", self.ease),
            ("start", self.start),
            ("end", self.end),
            ("scrub", self.scrub),
            ("axis", self.axis),
            ("bounds", self.bounds),
            ("state", self.state),
            ("custom_component_id", self.custom_component_id),
            ("repeat", self.repeat),
        ):
            if value not in ("", None):
                result[key] = value
        if self.from_values:
            result["from"] = copy.deepcopy(self.from_values)
        if self.to_values:
            result["to"] = copy.deepcopy(self.to_values)
        if self.stagger is not None:
            result["stagger"] = copy.deepcopy(self.stagger)
        if self.pin is not False:
            result["pin"] = self.pin
        if self.pin_spacing is not True:
            result["pin_spacing"] = self.pin_spacing
        if self.events:
            result["events"] = list(self.events)
        if self.yoyo:
            result["yoyo"] = True
        return result


@dataclass(frozen=True)
class MotionSectionPlan:
    section_id: str
    purpose: str
    actions: tuple[MotionAction, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], path: str) -> "MotionSectionPlan":
        value = _object(raw, path, known={"id", "purpose", "actions"})
        actions_raw = value.get("actions") or []
        if not isinstance(actions_raw, list) or len(actions_raw) > 100:
            raise ContractError(f"{path}.actions must be a list of at most 100 items")
        return cls(
            section_id=_name(value.get("id"), f"{path}.id"),
            purpose=_text(value.get("purpose"), f"{path}.purpose", maximum=2_000),
            actions=tuple(
                MotionAction.from_dict(item, f"{path}.actions[{index}]")
                for index, item in enumerate(actions_raw)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.section_id, "purpose": self.purpose, "actions": [item.to_dict() for item in self.actions]}


@dataclass(frozen=True)
class MotionPagePlan:
    path: str
    sections: tuple[MotionSectionPlan, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], path: str) -> "MotionPagePlan":
        value = _object(raw, path, known={"path", "sections"})
        page_path = safe_relative_path(value.get("path"), f"{path}.path")
        if not page_path.endswith((".html", ".htm")):
            raise ContractError(f"{path}.path must be a public HTML path")
        raw_sections = value.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise ContractError(f"{path}.sections must be a non-empty list")
        if len(raw_sections) > 100:
            raise ContractError(f"{path}.sections must contain at most 100 items")
        sections = tuple(
            MotionSectionPlan.from_dict(item, f"{path}.sections[{index}]")
            for index, item in enumerate(raw_sections)
        )
        ids = [item.section_id for item in sections]
        if len(ids) != len(set(ids)):
            raise ContractError(f"{path}.sections must have unique ids")
        return cls(path=page_path, sections=sections)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sections": [item.to_dict() for item in self.sections]}


@dataclass(frozen=True)
class MotionCustomComponent:
    component_id: str
    path: str
    export_name: str
    purpose: str
    capabilities: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], path: str) -> "MotionCustomComponent":
        value = _object(raw, path, known={"id", "path", "export", "purpose", "capabilities"})
        component_id = _name(value.get("id"), f"{path}.id")
        registry_entry = MOTION_COMPONENT_REGISTRY.get(component_id)
        if registry_entry is None:
            raise ContractError(f"{path}.id is not a host-registered React component")
        component_path = safe_relative_path(value.get("path"), f"{path}.path")
        if component_path != registry_entry["path"]:
            raise ContractError(f"{path}.path does not match the host component registry")
        export_name = _text(value.get("export"), f"{path}.export", maximum=120)
        if export_name != registry_entry["export"]:
            raise ContractError(f"{path}.export does not match the host component registry")
        raw_capabilities = value.get("capabilities") or []
        if not isinstance(raw_capabilities, list) or len(raw_capabilities) > 12:
            raise ContractError(f"{path}.capabilities must be a list")
        capabilities: list[str] = []
        for index, item in enumerate(raw_capabilities):
            raw_capability = _text(item, f"{path}.capabilities[{index}]", maximum=120)
            capability = canonical_motion_capability(raw_capability)
            if capability is None:
                capability = _name(raw_capability, f"{path}.capabilities[{index}]")
            if capability not in MOTION_CAPABILITIES:
                raise ContractError(f"{path}.capabilities[{index}] is unsupported")
            if capability not in registry_entry["capabilities"]:
                raise ContractError(f"{path}.capabilities[{index}] is not supported by the host component")
            if capability not in capabilities:
                capabilities.append(capability)
        if "react" not in capabilities:
            raise ContractError(f"{path}.capabilities must include react")
        return cls(
            component_id=component_id,
            path=component_path,
            export_name=export_name,
            purpose=_text(value.get("purpose"), f"{path}.purpose", maximum=2_000),
            capabilities=tuple(capabilities),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.component_id,
            "path": self.path,
            "export": self.export_name,
            "purpose": self.purpose,
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class MotionPlan:
    schema_version: int
    creative_thesis: str
    audience_fit: str
    template_policy: str
    reduced_motion: dict[str, Any]
    capabilities: tuple[str, ...]
    pages: tuple[MotionPagePlan, ...]
    signature_interaction: str = ""
    custom_components: tuple[MotionCustomComponent, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "MotionPlan":
        value = _object(raw, "motion_plan", known={
            "schema_version", "creative_thesis", "audience_fit", "template_policy", "reduced_motion",
            "capabilities", "pages", "signature_interaction", "custom_components",
        })
        version = value.get("schema_version")
        if isinstance(version, bool) or version != MOTION_PLAN_SCHEMA_VERSION:
            raise ContractError(f"motion_plan.schema_version must be {MOTION_PLAN_SCHEMA_VERSION}")
        policy = _text(value.get("template_policy"), "motion_plan.template_policy", maximum=30).lower()
        if policy not in {"forbid", "owner_requested"}:
            raise ContractError("motion_plan.template_policy must be forbid or owner_requested")
        raw_capabilities = value.get("capabilities")
        if not isinstance(raw_capabilities, list) or not raw_capabilities:
            raise ContractError("motion_plan.capabilities must be a non-empty list")
        capabilities: list[str] = []
        for index, item in enumerate(raw_capabilities):
            raw_capability = _text(item, f"motion_plan.capabilities[{index}]", maximum=120)
            capability = canonical_motion_capability(raw_capability)
            if capability is None:
                capability = _name(raw_capability, f"motion_plan.capabilities[{index}]")
            if capability not in MOTION_CAPABILITIES:
                raise ContractError(f"motion_plan.capabilities[{index}] is unsupported")
            if capability not in capabilities:
                capabilities.append(capability)
        reduced = _object(value.get("reduced_motion"), "motion_plan.reduced_motion", known={"strategy", "details", "preserves_content"})
        raw_strategy = _text(reduced.get("strategy"), "motion_plan.reduced_motion.strategy", maximum=60)
        strategy = canonical_reduced_motion_strategy(raw_strategy)
        if strategy not in REDUCED_MOTION_STRATEGIES:
            allowed = ", ".join(sorted(REDUCED_MOTION_STRATEGIES))
            raise ContractError(f"motion_plan.reduced_motion.strategy is unsupported; use {allowed}")
        preserves = reduced.get("preserves_content", True)
        if preserves is not True:
            raise ContractError("motion_plan.reduced_motion.preserves_content must be true")
        reduced_normalized = {
            "strategy": strategy,
            "details": _text(reduced.get("details"), "motion_plan.reduced_motion.details", maximum=2_000),
            "preserves_content": True,
        }
        raw_pages = value.get("pages")
        if not isinstance(raw_pages, list) or not raw_pages:
            raise ContractError("motion_plan.pages must be a non-empty list")
        if len(raw_pages) > 50:
            raise ContractError("motion_plan.pages must contain at most 50 items")
        pages = tuple(MotionPagePlan.from_dict(item, f"motion_plan.pages[{index}]") for index, item in enumerate(raw_pages))
        page_paths = [item.path for item in pages]
        if len(page_paths) != len(set(page_paths)):
            raise ContractError("motion_plan.pages must have unique paths")
        raw_components = value.get("custom_components") or []
        if not isinstance(raw_components, list) or len(raw_components) > 24:
            raise ContractError("motion_plan.custom_components must be a list")
        components = tuple(
            MotionCustomComponent.from_dict(item, f"motion_plan.custom_components[{index}]")
            for index, item in enumerate(raw_components)
        )
        component_ids = [item.component_id for item in components]
        if len(component_ids) != len(set(component_ids)):
            raise ContractError("motion_plan.custom_components must have unique ids")
        component_id_set = set(component_ids)
        for page in pages:
            for section in page.sections:
                for action in section.actions:
                    if action.capability not in capabilities:
                        raise ContractError(
                            f"motion_plan action capability is not declared: {action.capability}"
                        )
                    if action.custom_component_id and action.custom_component_id not in component_id_set:
                        raise ContractError(
                            f"motion_plan action references an unknown custom component: {action.custom_component_id}"
                        )
        signature = _text(value.get("signature_interaction"), "motion_plan.signature_interaction", maximum=2_000, required=False)
        if "signature" in capabilities and not signature:
            raise ContractError("motion_plan.signature_interaction is required when signature is declared")
        return cls(
            schema_version=version,
            creative_thesis=_text(value.get("creative_thesis"), "motion_plan.creative_thesis", maximum=2_000),
            audience_fit=_text(value.get("audience_fit"), "motion_plan.audience_fit", maximum=2_000),
            template_policy=policy,
            reduced_motion=reduced_normalized,
            capabilities=tuple(capabilities),
            pages=pages,
            signature_interaction=signature,
            custom_components=components,
        )

    @classmethod
    def from_routes(
        cls,
        routes: Iterable[Mapping[str, Any]],
        *,
        motion: Mapping[str, Any] | None = None,
        signature_interaction: str = "",
    ) -> "MotionPlan":
        """Create a safe typed plan for legacy specs that have no motion plan."""
        route_rows = [copy.deepcopy(dict(route)) for route in routes]
        legacy_motion = dict(motion or {})
        enabled = legacy_motion.get("enabled") is not False
        raw_reduced = legacy_motion.get("reduced_motion") or legacy_motion.get("reduced_motion_behavior")
        if isinstance(raw_reduced, Mapping):
            raw_reduced = raw_reduced.get("details") or raw_reduced.get("strategy")
        reduced_details = str(raw_reduced or "Keep all content visible without transforms or transitions.").strip()
        strategy = "fade-only" if "fade" in reduced_details.lower() and "transform" not in reduced_details.lower() else "static"
        signature = signature_interaction.strip() if isinstance(signature_interaction, str) else ""
        if not signature:
            legacy_signature = legacy_motion.get("signature_interaction") or legacy_motion.get("signature")
            signature = str(legacy_signature).strip() if isinstance(legacy_signature, str) else ""

        capabilities = ["core"]
        if signature and enabled:
            capabilities.append("signature")
        if enabled and legacy_motion.get("signature") == "depth-descent":
            capabilities.extend(("scrolltrigger", "scrub"))
        pages: list[dict[str, Any]] = []
        for route in route_rows:
            raw_sections = route.get("sections")
            if not isinstance(raw_sections, list) or not raw_sections:
                raise ContractError("legacy route sections must be a non-empty list")
            sections: list[dict[str, Any]] = []
            for index, raw_section in enumerate(raw_sections):
                kind = str(raw_section.get("kind") or "section") if isinstance(raw_section, Mapping) else "section"
                actions: list[dict[str, Any]] = []
                if enabled:
                    actions.append({
                        "kind": "entrance",
                        "capability": "core",
                        "target": f"section-{index}",
                        "from": {"opacity": 0, "y": 24},
                        "to": {"opacity": 1, "y": 0},
                        "duration": 0.8,
                        "ease": "power2.out",
                    })
                sections.append({
                    "id": f"section-{index}",
                    "purpose": f"Preserve the hierarchy of the {kind} section.",
                    "actions": actions,
                })
            pages.append({
                "path": route.get("output_path"),
                "sections": sections,
            })

        plan_value = {
            "schema_version": MOTION_PLAN_SCHEMA_VERSION,
            "creative_thesis": "Reveal each section in a measured sequence without obscuring its meaning.",
            "audience_fit": "Visitors can scan the offer and choose the next useful step.",
            "template_policy": "forbid",
            "reduced_motion": {
                "strategy": strategy,
                "details": reduced_details,
                "preserves_content": True,
            },
            "capabilities": capabilities,
            "pages": pages,
            "signature_interaction": signature,
            "custom_components": [],
        }
        plan = cls.from_dict(plan_value)
        plan.validate_against_routes(route_rows)
        return plan

    def validate_against_routes(self, routes: Iterable[Mapping[str, Any]]) -> None:
        """Require plan pages, sections, and targets to match host-rendered markup."""
        route_rows = [dict(route) for route in routes]
        expected_paths = [safe_relative_path(route.get("output_path"), f"routes[{index}].output_path") for index, route in enumerate(route_rows)]
        if [page.path for page in self.pages] != expected_paths:
            raise ContractError("motion_plan pages must match design routes")
        component_ids = {component.component_id for component in self.custom_components}
        for route_index, (route, page) in enumerate(zip(route_rows, self.pages, strict=True)):
            raw_sections = route.get("sections")
            if not isinstance(raw_sections, list) or len(raw_sections) != len(page.sections):
                raise ContractError(f"motion_plan page {page.path} sections do not match design route")
            expected_ids = [f"section-{index}" for index in range(len(raw_sections))]
            actual_ids = [section.section_id for section in page.sections]
            if actual_ids != expected_ids:
                raise ContractError(f"motion_plan page {page.path} section ids do not match host targets")
            known_targets = set(_HOST_MOTION_TARGETS) | set(expected_ids) | component_ids
            for section in page.sections:
                for action in section.actions:
                    for name, target in (("target", action.target), ("trigger", action.trigger), ("bounds", action.bounds)):
                        if target and target not in known_targets:
                            raise ContractError(
                                f"motion_plan.pages[{route_index}].{section.section_id}.{name} references an unknown host target"
                            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "creative_thesis": self.creative_thesis,
            "audience_fit": self.audience_fit,
            "template_policy": self.template_policy,
            "reduced_motion": copy.deepcopy(self.reduced_motion),
            "capabilities": list(self.capabilities),
            "pages": [item.to_dict() for item in self.pages],
            "signature_interaction": self.signature_interaction,
            "custom_components": [item.to_dict() for item in self.custom_components],
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


__all__ = [
    "MOTION_CAPABILITIES",
    "MOTION_COMPONENT_REGISTRY",
    "MOTION_KINDS",
    "MOTION_PLAN_SCHEMA_VERSION",
    "MotionAction",
    "MotionCustomComponent",
    "MotionPagePlan",
    "MotionPlan",
    "MotionSectionPlan",
]
