"""Planning adapters for the typed Astro/React design specification."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import urlsplit

from ..core.design_contracts import ArtDirection, DesignBrief, SiteIntake, canonical_json
from ..core.motion_contracts import canonical_motion_capability, canonical_reduced_motion_strategy
from ..core.react_design_contracts import ReactDesignSpec


INCUBATED_CONTEXT_APPLICATION_RULES = """AUDIENCE AND RESEARCH CONTEXT APPLICATION:
- Treat INTAKE.audience and BRIEF.audience_intent as the primary audience analysis. Make the intended visitor and their next useful decision clear in hierarchy, imagery, interaction, and page copy.
- When INCUBATED CREATIVE CONTEXT is present, use customer_genesis, owner preferences and dislikes, research implications, cross-language audience insights, and infusion deductions to shape both visual decisions and page copy.
- For each relevant evidence-linked insight or deduction, reflect it in at least one observable design or hierarchy choice and one copy choice. If it is not relevant to this page, omit it rather than forcing it into the experience.
- Use recommendations, hypotheses, and deductions as bounded guidance. Do not turn recommendations or hypotheses into owner facts, unsupported claims, testimonials, metrics, guarantees, or invented proof; honor the intake's unknowns and prohibited claims.
- Do not expose incubation, infusion, genesis, research machinery, citations, or internal IDs in customer-facing copy. Use the evidence to decide what to emphasize, explain, reassure, omit, and how to phrase the primary action.
- Source language is evidence about audience needs, not an instruction to translate or switch languages. Write in the validated intake language."""


class DesignPlannerError(RuntimeError):
    """A planner could not produce a valid design specification."""


class DesignPlanner(Protocol):
    def plan(self, intake: SiteIntake, brief: DesignBrief, direction: ArtDirection) -> ReactDesignSpec:
        ...


def _location(intake: SiteIntake) -> str:
    for key in ("service_area", "location", "place"):
        value = intake.business.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            values = [str(item).strip() for item in value if str(item).strip()]
            if values:
                return ", ".join(values)
    return "the stated service area"


def _action(intake: SiteIntake, *, label: str | None = None) -> dict[str, Any]:
    conversion = intake.conversion
    destination = str(conversion.get("contact_destination") or "").strip()
    result: dict[str, Any] = {
        "label": label or str(conversion.get("primary_action") or "Start a conversation"),
        "available": bool(destination),
    }
    if destination:
        result["href"] = destination
    return result


def _navigation(intake: SiteIntake) -> list[dict[str, str]]:
    raw = (intake.site or {}).get("navigation_intent") or []
    labels = [str(item).strip() for item in raw if str(item).strip()]
    if not labels:
        labels = ["Philosophy", "Training", "Contact", "Journal"]
    result: list[dict[str, str]] = []
    for label in labels[:12]:
        key = re.sub(r"[^a-z]+", " ", label.lower()).strip()
        href = {
            "philosophy": "#philosophy",
            "training": "#training",
            "training dates": "#training",
            "contact": "#contact",
            "journal": "/articles.html",
        }.get(key)
        if href is None:
            continue
        result.append({"label": label, "href": href})
    return result or [
        {"label": "Philosophy", "href": "#philosophy"},
        {"label": "Training", "href": "#training"},
        {"label": "Contact", "href": "#contact"},
        {"label": "Journal", "href": "/articles.html"},
    ]


def deterministic_spec(
    intake: SiteIntake,
    brief: DesignBrief,
    direction: ArtDirection,
    *,
    frontend_libraries: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
) -> ReactDesignSpec:
    """Create a safe local starter design without requiring a model or network."""
    name = str(intake.business.get("name") or "The business").strip()
    offer = str(intake.business.get("offer_summary") or "The stated offer").strip()
    audience = str(intake.audience.get("primary") or "People looking for a considered next step").strip()
    location = _location(intake)
    services = [str(item).strip() for item in (intake.business.get("primary_services") or []) if str(item).strip()]
    assets = [item for item in intake.assets if isinstance(item, Mapping) and item.get("id") and item.get("id") in {asset.get("id") for asset in intake.assets}]
    asset_specs = [
        {
            "id": str(item.get("id")),
            "source": str(item.get("id")),
            "alt": str(item.get("role") or f"{name} visual reference"),
            "role": str(item.get("role") or "site imagery"),
        }
        for item in assets[:12]
    ]
    hero_asset = asset_specs[0]["id"] if asset_specs else None
    split_asset = asset_specs[1]["id"] if len(asset_specs) > 1 else None
    logo_asset = next(
        (
            asset["id"]
            for asset in asset_specs
            if "logo" in f"{asset['id']} {asset.get('role', '')}".lower()
        ),
        "",
    )
    action = _action(intake)
    sections: list[dict[str, Any]] = [
        {
            "kind": "hero",
            "props": {
                "eyebrow": location,
                "title": f"{offer.rstrip('.')}.",
                "body": f"A measured path for {audience.lower()}.",
                "actions": [action],
                **({"image_asset_id": hero_asset} if hero_asset else {}),
            },
        },
        {
            "kind": "editorial",
            "props": {
                "eyebrow": "A clear point of view",
                "title": "Make room for the work that matters.",
                "body": f"{name} brings {offer.lower()} into focus without adding claims the brief cannot support.",
                "items": [
                    {"title": "For the right people", "body": audience},
                    {"title": "In the right place", "body": location},
                ],
            },
        },
        {
            "kind": "features",
            "props": {
                "eyebrow": "The offer, in practice",
                "title": "A progression you can understand.",
                "body": "Start with the part that is useful now. Continue only when the next step is clear.",
                "items": [
                    {"title": service, "body": f"A stated {name} service, presented without unsupported outcomes."}
                    for service in (services or [offer])[:6]
                ],
            },
        },
    ]
    if split_asset:
        sections.append({
            "kind": "split",
            "props": {
                "eyebrow": "Attention to detail",
                "title": "Less noise. Better decisions.",
                "body": "The page makes the essential information legible first, then lets people choose how far to go.",
                "image_asset_id": split_asset,
                "image_side": "right",
            },
        })
    sections.extend([
        {
            "kind": "contact",
            "props": {
                "eyebrow": "The next step",
                "title": "Begin with a useful conversation.",
                "body": str(intake.conversion.get("primary_action") or "Choose the next step").strip() + ".",
                "availability": "A contact destination was not supplied in the brief." if not action["available"] else "The supplied contact destination is ready when you are.",
                "action": action,
            },
        },
    ])
    pages: list[dict[str, Any]] = []
    required_pages = list((intake.site or {}).get("required_pages") or ["index.html", "articles.html"])
    for index, output_path in enumerate(required_pages[:20]):
        output_path = str(output_path)
        if output_path in {"index.html", "index.htm"}:
            pages.append({
                "id": "home",
                "output_path": "index.html",
                "title": f"{name} | {offer}",
                "description": f"{offer} for {audience.lower()} in {location}.",
                "h1": sections[0]["props"]["title"],
                "sections": sections,
                "primary_action": action,
            })
        else:
            pages.append({
                "id": re.sub(r"[^a-z0-9]+", "-", output_path.lower()).strip("-") or f"page-{index}",
                "output_path": output_path,
                "title": f"Journal | {name}",
                "description": f"Notes and useful context from {name}.",
                "h1": "Notes for the next deep breath.",
                "sections": [{
                    "kind": "journal",
                    "props": {
                        "eyebrow": "The journal",
                        "title": "Notes for the next deep breath.",
                        "body": f"A growing collection of useful detail around {offer.lower()}.",
                    },
                }],
            })
    if not pages:
        pages.append({
            "id": "home",
            "output_path": "index.html",
            "title": name,
            "description": offer,
            "h1": sections[0]["props"]["title"],
            "sections": sections,
            "primary_action": action,
        })
    prohibited = []
    for source in (intake.brand.get("prohibited_claims"), (intake.constraints or {}).get("prohibited_claims")):
        if isinstance(source, (list, tuple)):
            prohibited.extend(str(item).strip() for item in source if str(item).strip())
    available_library_names = {
        str(item.get("name") or "").strip().lower()
        for item in (frontend_libraries or ())
        if isinstance(item, Mapping)
    }
    spec = {
        "schema_version": 1,
        "direction_id": direction.name,
        "site_name": name,
        "language": "en",
        "site_url": str((intake.provenance or {}).get("site_url") or ""),
        "intake_hash": intake.content_hash,
        "navigation": _navigation(intake),
        "tokens": {
            "colors": {"ink": "#062c31", "paper": "#f3efe7", "accent": "#e76f51", "muted": "#607571"},
            "type": {"display": "Cormorant Garamond, Georgia, serif", "body": "Manrope, system-ui, sans-serif", "mono": "ui-monospace, monospace"},
            "spacing": {"unit": 8, "section": 96, "gap": 24},
            "layout": {"max-width": 1180, "gutter": 24},
            "shape": {"radius": 0},
        },
        "routes": pages,
        "assets": asset_specs,
        **({"logo_asset_id": logo_asset} if logo_asset else {}),
        "motion": {
            # Do not emit executable motion intent when the host has not made
            # the approved GSAP runtime available. Configured production
            # builds include GSAP in this catalog and retain the full plan.
            "enabled": "gsap" in available_library_names,
            "libraries": ["gsap"] if "gsap" in available_library_names else [],
            "reduced_motion": "Keep all meaning visible without transforms or transitions.",
        },
        "signature_gesture": direction.signature_gesture,
        "component_inventory": ["SiteHeader", "Hero", "EditorialSection", "FeatureGrid", "ContactSection", "SiteFooter"],
        "omissions": list(brief.unresolved_unknowns),
        "unknowns": list(brief.unresolved_unknowns),
        "prohibited_claims": list(dict.fromkeys(prohibited)),
    }
    return ReactDesignSpec.from_dict(spec)


class DeterministicDesignPlanner:
    def __init__(
        self,
        frontend_libraries: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
    ) -> None:
        self.frontend_libraries = tuple(frontend_libraries or ())

    def plan(self, intake: SiteIntake, brief: DesignBrief, direction: ArtDirection) -> ReactDesignSpec:
        return deterministic_spec(intake, brief, direction, frontend_libraries=self.frontend_libraries)


def _json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines and lines[-1].strip().startswith("```") else lines[1:]).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise DesignPlannerError("model did not return a JSON design specification")
        try:
            value = json.loads(raw[start:end + 1])
        except json.JSONDecodeError as exc:
            raise DesignPlannerError("model returned invalid design JSON") from exc
    if not isinstance(value, dict):
        raise DesignPlannerError("model design output must be an object")
    return value


_MODEL_SECTION_FIELDS = {
    "hero": {"eyebrow", "title", "body", "actions", "image_asset_id"},
    "editorial": {"eyebrow", "title", "body", "items"},
    "split": {"eyebrow", "title", "body", "image_asset_id", "image_side", "items"},
    "features": {"eyebrow", "title", "body", "items"},
    "facts": {"eyebrow", "title", "body", "items"},
    "cta": {"eyebrow", "title", "body", "action"},
    "contact": {"eyebrow", "title", "body", "availability", "action"},
    "journal": {"eyebrow", "title", "body", "action"},
}
_MODEL_KIND_ALIASES = {
    "text": "editorial",
    "text_image": "split",
    "image_text": "split",
    "feature_grid": "features",
    "feature-grid": "features",
    "call_to_action": "cta",
    "call-to-action": "cta",
    "form": "contact",
}
_MODEL_CSS_SCALAR = re.compile(r"^[A-Za-z0-9 .,'()/_%+#-]+$")


def _model_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _model_scalar(value: Any, preferred: tuple[str, ...] = ()) -> Any:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return value.strip() if isinstance(value, str) else value
    if isinstance(value, Mapping):
        for key in (*preferred, "value", "css", "text"):
            if key in value:
                result = _model_scalar(value[key], preferred)
                if result not in (None, ""):
                    return result
    return None


def _model_css_scalar(value: Any) -> Any:
    """Keep only values the compiler can safely emit as a CSS declaration."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    result = str(value).strip()
    if not result or len(result) > 160 or not _MODEL_CSS_SCALAR.fullmatch(result):
        return None
    return result if isinstance(value, str) else value


def _model_absolute_url(value: Any) -> str:
    candidate = _model_text(value)
    parsed = urlsplit(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate
    return ""


def _normalize_model_tokens(raw: Any, intake: SiteIntake | None = None) -> dict[str, Any]:
    source = raw.get("tokens") if isinstance(raw, Mapping) and isinstance(raw.get("tokens"), Mapping) else raw
    if not isinstance(source, Mapping):
        source = {}
    if not source.get("tokens") and isinstance(source.get("theme"), Mapping):
        source = source["theme"]
    result: dict[str, Any] = {}
    aliases = {"type": ("type", "typography"), "spacing": ("spacing",), "layout": ("layout",), "shape": ("shape",), "colors": ("colors", "palette")}
    for group, candidates in aliases.items():
        values: dict[str, Any] = {}
        group_source = next((source.get(name) for name in candidates if isinstance(source.get(name), Mapping)), {})
        for key, value in group_source.items():
            scalar = _model_scalar(value, ("family", "font_family", "hex", "color", "size", "padding", "max_width"))
            scalar = _model_css_scalar(scalar)
            if scalar is not None:
                token_key = re.sub(r"[^A-Za-z0-9]+", "_", str(key)).strip("_").lower()
                if token_key:
                    values[token_key] = scalar
        result[group] = values
    color_aliases = {
        "paper": ("paper", "surface_primary", "primary_surface", "surface", "background", "deep", "field"),
        "ink": ("ink_primary", "primary_ink", "ink", "foreground", "foam"),
        "accent": ("accent", "accent_primary", "primary_accent", "sea", "highlight"),
        "muted": ("text_muted", "secondary_ink", "ink_secondary", "muted", "secondary", "dim"),
    }
    preferred_color_aliases = {
        "paper": ("surface_primary", "primary_surface"),
        "ink": ("ink_primary", "primary_ink"),
        "accent": ("accent_primary", "primary_accent"),
        "muted": ("text_muted", "secondary_ink", "ink_secondary"),
    }
    for target, candidates in color_aliases.items():
        preferred = preferred_color_aliases[target]
        candidate = next((name for name in preferred if name in result["colors"]), None)
        if candidate is None and target not in result["colors"]:
            candidate = next((name for name in candidates if name in result["colors"]), None)
        if candidate is not None:
            result["colors"][target] = result["colors"][candidate]
    for target, candidates in {
        "display": ("heading", "serif"),
        "body": ("text", "sans"),
        "mono": ("code",),
    }.items():
        if target not in result["type"]:
            for candidate in candidates:
                if candidate in result["type"]:
                    result["type"][target] = result["type"][candidate]
                    break
    spacing = result["spacing"]
    if "section" not in spacing and "section_padding" in spacing:
        spacing["section"] = spacing["section_padding"]
    if "section" not in spacing and "section_gap" in spacing:
        spacing["section"] = spacing["section_gap"]
    layout = result["layout"]
    if "container" not in layout and "content_max" in layout:
        layout["container"] = layout["content_max"]
    if "container" not in layout:
        for candidate in ("container_width", "container_max_width", "max_width"):
            if candidate in layout:
                layout["container"] = layout[candidate]
    if "gutter" not in layout:
        for candidate in ("container_padding", "page_padding"):
            if candidate in layout:
                layout["gutter"] = layout[candidate]
                break
    shape = result["shape"]
    if "radius" not in shape:
        for candidate in ("corner_radius", "border_radius", "radius_md"):
            if candidate in shape:
                shape["radius"] = shape[candidate]
                break
    brand = intake.brand if intake is not None and isinstance(intake.brand, Mapping) else {}
    color_source = brand.get("existing_palette") or brand.get("existing_colors") or brand.get("colors")
    if isinstance(color_source, Mapping):
        for key, value in color_source.items():
            if key not in result["colors"]:
                scalar = _model_scalar(value, ("hex", "color", "value"))
                scalar = _model_css_scalar(scalar)
                token_key = re.sub(r"[^A-Za-z0-9]+", "_", str(key)).strip("_").lower()
                if scalar is not None and token_key:
                    result["colors"][token_key] = scalar
    font_source = brand.get("existing_fonts") or brand.get("fonts")
    if isinstance(font_source, Mapping):
        for key in ("body", "display", "mono"):
            if key not in result["type"]:
                value = _model_scalar(font_source.get(key), ("family", "font_family"))
                value = _model_css_scalar(value)
                if value is not None:
                    result["type"][key] = value
    for key, fallback in (
        ("body", brand.get("font_body")),
        ("display", brand.get("font_display")),
        ("mono", brand.get("font_mono")),
    ):
        if key not in result["type"]:
            value = _model_scalar(fallback, ("family", "font_family"))
            value = _model_css_scalar(value)
            if value is not None:
                result["type"][key] = value
    return result


def _model_text_tree(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join([*(str(key) for key in value), *(_model_text_tree(item) for item in value.values())])
    if isinstance(value, list):
        return " ".join(_model_text_tree(item) for item in value)
    return _model_text(value)


def _normalize_model_library_requests(motion: dict[str, Any]) -> None:
    request_key = next(
        (key for key in ("libraries", "frontend_libraries", "library_requests") if key in motion),
        None,
    )
    if request_key is None:
        return
    raw = motion[request_key]
    if not isinstance(raw, list):
        return
    names: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            item = item.get("name") or item.get("id") or item.get("library")
        if isinstance(item, str) and item.strip():
            name = item.strip().lower()
            if name not in names:
                names.append(name)
    motion["libraries"] = names


def _normalize_model_motion(
    value: Any,
    intake: SiteIntake | None = None,
    signature_gesture: str = "",
    *,
    allow_subject_default: bool = True,
) -> dict[str, Any]:
    motion = dict(value) if isinstance(value, Mapping) else {}
    _normalize_model_library_requests(motion)
    primitives = motion.get("primitives") if isinstance(motion.get("primitives"), list) else []
    raw_primitives = [*primitives]
    if motion.get("primitive") is not None:
        raw_primitives.append(motion["primitive"])
    primitive_names = set()
    for item in raw_primitives:
        if isinstance(item, Mapping):
            item = item.get("name") or item.get("id") or item.get("type")
        name = _model_text(item).lower().replace("_", "-").replace(" ", "-")
        if name:
            primitive_names.add(name)
    motion_context = f"{_model_text_tree(motion)} {signature_gesture}".lower()
    business_context = ""
    if intake is not None:
        business_context = _model_text_tree(intake.business).lower()
        business_context += " " + _model_text_tree(intake.brand).lower()
    depth_subject = any(term in f"{business_context} {signature_gesture.lower()}" for term in ("depth", "freediv", "cenote", "breath-hold"))
    signature_intent = "signature" in motion_context or "tide-line" in motion_context or "tideline" in motion_context
    if "enabled" not in motion and (raw_primitives or signature_intent):
        motion["enabled"] = True
    if allow_subject_default and motion.get("enabled") is not False and not _model_text(motion.get("signature")):
        if "depth-descent" in primitive_names or (depth_subject and signature_intent):
            motion["signature"] = "depth-descent"
    if "reduced_motion" not in motion:
        reduced_motion = _model_text(motion.get("reduced_motion_behavior"))
        if reduced_motion:
            motion["reduced_motion"] = reduced_motion
    return motion


def _normalize_model_motion_plan(value: Any) -> Any:
    """Canonicalize provider wording while failing closed for unknown strategies."""
    if not isinstance(value, Mapping):
        return value
    plan = dict(value)
    raw_capabilities = plan.get("capabilities")
    if isinstance(raw_capabilities, list):
        capabilities: list[str] = []
        for item in raw_capabilities:
            capability = canonical_motion_capability(item) or "core"
            if capability not in capabilities:
                capabilities.append(capability)
        plan["capabilities"] = capabilities or ["core"]
    reduced = plan.get("reduced_motion")
    if not isinstance(reduced, Mapping):
        return plan
    reduced_plan = dict(reduced)
    strategy = canonical_reduced_motion_strategy(reduced_plan.get("strategy"))
    if strategy is None:
        details = _model_text(reduced_plan.get("details")).lower()
        fade_only = "fade" in details or "opacity" in details
        transform_terms = ("transform", "translate", "scale", "move", "position", "parallax")
        strategy = "fade-only" if fade_only and not any(term in details for term in transform_terms) else "static"
    reduced_plan["strategy"] = strategy
    plan["reduced_motion"] = reduced_plan
    return plan


def _approved_asset_id(value: Any, approved: Mapping[str, Mapping[str, Any]]) -> str:
    candidate = _model_text(value)
    if candidate in approved:
        return candidate
    basename = candidate.rsplit("/", 1)[-1]
    for asset_id in approved:
        if asset_id.rsplit("/", 1)[-1] == basename:
            return asset_id
    return ""


def _normalize_model_action(value: Any, fallback: Mapping[str, Any]) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        label = _model_text(value.get("label") or value.get("text") or value.get("name"))
        href = _model_text(value.get("href") or value.get("url") or value.get("link"))
        available = value.get("available") if isinstance(value.get("available"), bool) else bool(href)
        if available and not href:
            available = False
        if label:
            result: dict[str, Any] = {"label": label, "available": available}
            if href:
                result["href"] = href
            return result
    elif isinstance(value, str) and value.strip():
        return {"label": value.strip(), "available": False}
    if fallback:
        return dict(fallback)
    return None


def _normalize_model_item(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str) and value.strip():
        return {"title": value.strip()}
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    aliases = {
        "title": ("title", "heading", "name"),
        "body": ("body", "description", "text", "lede"),
        "label": ("label",),
        "value": ("value",),
        "href": ("href", "url", "link"),
    }
    for key, names in aliases.items():
        text = next((_model_text(value.get(name)) for name in names if _model_text(value.get(name))), "")
        if text:
            result[key] = text
    return result if any(key in result for key in ("title", "label", "value")) else None


def _normalize_model_section(value: Any, approved: Mapping[str, Mapping[str, Any]], fallback_action: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    source = dict(value)
    props = dict(source.get("props")) if isinstance(source.get("props"), Mapping) else {}
    for key in ("eyebrow", "title", "body", "actions", "action", "items", "image_asset_id", "image_side", "availability"):
        if key not in props and key in source:
            props[key] = source[key]
    aliases = {"eyebrow": ("kicker", "label"), "title": ("heading",), "body": ("lede", "description", "text")}
    for key, names in aliases.items():
        if key not in props:
            props[key] = next((source[name] for name in names if source.get(name) is not None), None)
    if "image_asset_id" not in props and source.get("image") is not None:
        image = source["image"]
        props["image_asset_id"] = image.get("id") or image.get("asset_id") or image.get("source") if isinstance(image, Mapping) else image
    if "items" not in props:
        for key in ("cards", "features", "points"):
            if isinstance(source.get(key), list):
                props["items"] = source[key]
                break

    raw_kind = _model_text(source.get("kind") or source.get("type")).lower().replace(" ", "_")
    kind = _MODEL_KIND_ALIASES.get(raw_kind, raw_kind)
    if kind not in _MODEL_SECTION_FIELDS:
        kind = "split" if props.get("image_asset_id") else "features" if isinstance(props.get("items"), list) else "cta" if props.get("action") else "editorial"
    normalized: dict[str, Any] = {}
    for key in _MODEL_SECTION_FIELDS[kind]:
        if key not in props:
            continue
        item = props[key]
        if key in {"eyebrow", "title", "body", "availability", "image_side"}:
            text = _model_text(item)
            if text:
                normalized[key] = text
        elif key == "image_asset_id":
            asset_id = _approved_asset_id(item, approved)
            if asset_id:
                normalized[key] = asset_id
        elif key == "items":
            values = item if isinstance(item, list) else []
            entries = [entry for raw_item in values if (entry := _normalize_model_item(raw_item)) is not None]
            if entries:
                normalized[key] = entries
        elif key == "actions":
            values = item if isinstance(item, list) else [item]
            entries = [entry for raw_action in values if (entry := _normalize_model_action(raw_action, fallback_action)) is not None]
            if entries:
                normalized[key] = entries
        elif key == "action":
            action = _normalize_model_action(item, fallback_action)
            if action is not None:
                normalized[key] = action
    if not normalized:
        return None
    return {"kind": kind, "props": normalized}


def _normalize_model_route(
    value: Any,
    index: int,
    required_pages: tuple[str, ...],
    approved: Mapping[str, Mapping[str, Any]],
    fallback_action: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    source = dict(value)
    meta = source.get("meta") if isinstance(source.get("meta"), Mapping) else {}
    route_id = _model_text(source.get("id") or source.get("route_id") or source.get("name") or f"page-{index}")
    output_path = _model_text(source.get("output_path") or source.get("path") or source.get("url"))
    output_path = output_path.lstrip("/")
    if not output_path:
        output_path = required_pages[index] if index < len(required_pages) else "index.html"
    if output_path == "." or output_path.endswith("/"):
        output_path = output_path.rstrip("/") + "/index.html" if output_path not in {"", "."} else "index.html"
    if "." not in output_path.rsplit("/", 1)[-1]:
        output_path += ".html"
    title = _model_text(source.get("title") or meta.get("title") or source.get("name") or route_id)
    description = _model_text(source.get("description") or meta.get("description") or title)
    h1 = _model_text(source.get("h1") or meta.get("h1") or title)
    raw_sections = source.get("sections") or source.get("blocks") or []
    if isinstance(raw_sections, Mapping):
        raw_sections = list(raw_sections.values())
    sections = [
        section
        for raw_section in (raw_sections if isinstance(raw_sections, list) else [])
        if (section := _normalize_model_section(raw_section, approved, fallback_action)) is not None
    ]
    if not sections:
        sections = [{"kind": "editorial", "props": {"title": h1, "body": description}}]
    result: dict[str, Any] = {
        "id": route_id,
        "output_path": output_path,
        "title": title,
        "description": description,
        "h1": h1,
        "sections": sections,
    }
    action = _normalize_model_action(source.get("primary_action") or source.get("action"), fallback_action)
    if action is not None:
        result["primary_action"] = action
    return result


def _normalize_model_texts(value: Any) -> list[str]:
    if isinstance(value, list):
        return [text for item in value if (text := _model_text(item))]
    return []


def _normalize_model_inventory(value: Any) -> list[str]:
    if isinstance(value, list):
        return [text for item in value if (text := _model_text(item))]
    if isinstance(value, Mapping):
        result: list[str] = []
        for item in value.values():
            if isinstance(item, list):
                result.extend(_normalize_model_inventory(item))
            elif (text := _model_text(item)):
                result.append(text)
        return list(dict.fromkeys(result))
    return []


def _normalize_model_spec(
    raw: Mapping[str, Any],
    intake: SiteIntake,
    direction: Any,
    *,
    initial_homepage: bool = False,
    approved_asset_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    allowed_asset_ids = (
        None
        if approved_asset_ids is None
        else {str(item).strip() for item in approved_asset_ids if str(item).strip()}
    )
    approved = {
        _model_text(asset.get("id")): asset
        for asset in intake.assets
        if isinstance(asset, Mapping)
        and _model_text(asset.get("id"))
        and (allowed_asset_ids is None or _model_text(asset.get("id")) in allowed_asset_ids)
    }
    fallback_action = _action(intake)
    raw_assets = raw.get("assets") if isinstance(raw.get("assets"), list) else []
    assets: list[dict[str, str]] = []
    for raw_asset in raw_assets:
        if not isinstance(raw_asset, Mapping):
            continue
        asset_id = _approved_asset_id(raw_asset.get("id") or raw_asset.get("asset_id") or raw_asset.get("source"), approved)
        if not asset_id:
            continue
        source = approved[asset_id]
        assets.append({
            "id": asset_id,
            "source": asset_id,
            "alt": _model_text(raw_asset.get("alt")) or _model_text(source.get("alt")) or _model_text(raw_asset.get("role")) or "Site visual reference",
            "role": _model_text(raw_asset.get("role")) or _model_text(source.get("role")) or "site imagery",
        })
    for asset_id, source in approved.items():
        if asset_id == _approved_asset_id(raw.get("logo_asset_id"), approved) and asset_id not in {item["id"] for item in assets}:
            assets.append({"id": asset_id, "source": asset_id, "alt": _model_text(source.get("role")) or "Brand mark", "role": _model_text(source.get("role")) or "logo"})
    if not assets:
        assets = [
            {"id": asset_id, "source": asset_id, "alt": _model_text(source.get("role")) or "Site visual reference", "role": _model_text(source.get("role")) or "site imagery"}
            for asset_id, source in approved.items()
        ]
    raw_navigation = raw.get("navigation")
    navigation: list[dict[str, str]] = []
    if isinstance(raw_navigation, list):
        defaults = _navigation(intake)
        for index, item in enumerate(raw_navigation):
            if isinstance(item, Mapping):
                label = _model_text(item.get("label") or item.get("name") or item.get("text"))
                href = _model_text(item.get("href") or item.get("url") or item.get("link"))
            else:
                label, href = _model_text(item), ""
            if label and not href and index < len(defaults):
                href = defaults[index]["href"]
            if label and href:
                navigation.append({"label": label, "href": href})
    navigation = navigation or _navigation(intake)
    required_pages = tuple(str(item) for item in ((intake.site or {}).get("required_pages") or ("index.html",)))
    raw_routes = raw.get("routes") if isinstance(raw.get("routes"), list) else raw.get("pages")
    if isinstance(raw_routes, Mapping):
        raw_routes = [dict(item, id=key) if isinstance(item, Mapping) else item for key, item in raw_routes.items()]
    routes = [
        route
        for index, raw_route in enumerate(raw_routes if isinstance(raw_routes, list) else [])
        if (route := _normalize_model_route(raw_route, index, required_pages, approved, fallback_action)) is not None
    ]
    seen_ids: set[str] = set()
    for index, route in enumerate(routes):
        if route["id"] in seen_ids:
            route["id"] = f"{route['id']}-{index}"
        seen_ids.add(route["id"])
    logo_asset_id = _approved_asset_id(raw.get("logo_asset_id"), approved)
    signature_gesture = _model_text(raw.get("signature_gesture")) or (
        "" if initial_homepage else direction.signature_gesture
    )
    site_url = _model_absolute_url(raw.get("site_url") or raw.get("url"))
    if not site_url:
        site_url = _model_absolute_url((intake.provenance or {}).get("site_url"))
    result = {
        "schema_version": 1,
        "direction_id": _model_text(raw.get("direction_id")) or (
            "intake-led" if initial_homepage else direction.name
        ),
        "site_name": _model_text(raw.get("site_name") or raw.get("name")) or str(intake.business.get("name") or "The business"),
        "language": _model_text(raw.get("language")) or "en",
        "site_url": site_url,
        "intake_hash": _model_text(raw.get("intake_hash")) or intake.content_hash,
        "navigation": navigation,
        "tokens": _normalize_model_tokens(raw, intake),
        "routes": routes,
        "assets": assets,
        **({"logo_asset_id": logo_asset_id} if logo_asset_id else {}),
        "motion": _normalize_model_motion(
            raw.get("motion"),
            intake,
            signature_gesture,
            allow_subject_default=not initial_homepage,
        ),
        "signature_gesture": signature_gesture,
        "component_inventory": _normalize_model_inventory(raw.get("component_inventory")),
        "omissions": _normalize_model_texts(raw.get("omissions")),
        "unknowns": _normalize_model_texts(raw.get("unknowns")),
        "prohibited_claims": _normalize_model_texts(raw.get("prohibited_claims")),
    }
    raw_motion_plan = raw.get("motion_plan")
    if isinstance(raw_motion_plan, Mapping):
        result["motion_plan"] = _normalize_model_motion_plan(raw_motion_plan)
    return result


class LLMDesignPlanner:
    def __init__(
        self,
        client: Any,
        *,
        max_repairs: int = 2,
        current_site_evidence: Mapping[str, Any] | None = None,
        media_metadata: Mapping[str, Any] | None = None,
        frontend_libraries: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
        design_guidance: str = "",
        initial_homepage: bool = False,
        owner_design_request: str = "",
        incubated_creative_context: Mapping[str, Any] | None = None,
        approved_asset_ids: tuple[str, ...] | None = None,
    ) -> None:
        self.client = client
        self.max_repairs = max(0, min(int(max_repairs), 2))
        self.current_site_evidence = dict(current_site_evidence or {})
        self.media_metadata = dict(media_metadata or {})
        self.frontend_libraries = [dict(item) for item in (frontend_libraries or ())]
        self.design_guidance = str(design_guidance or "").strip()
        self.initial_homepage = bool(initial_homepage)
        self.owner_design_request = str(owner_design_request or "").strip()
        self.incubated_creative_context = dict(incubated_creative_context or {})
        self.approved_asset_ids = (
            None
            if approved_asset_ids is None
            else tuple(str(item).strip() for item in approved_asset_ids if str(item).strip())
        )
        self.last_raw_output = ""
        self.repair_attempts = 0

    def plan(self, intake: SiteIntake, brief: DesignBrief, direction: ArtDirection) -> ReactDesignSpec:
        design_request = self.owner_design_request or intake.extra.get("design_request")
        request_block = (
            f"\n\nOWNER DESIGN REQUEST:\n{design_request.strip()[:6_000]}"
            if isinstance(design_request, str) and design_request.strip()
            else ""
        )
        if self.initial_homepage:
            reference_policy = (
                "This is an initial homepage. Use the validated intake as the sole creative brief. "
                "Do not use existing-site evidence, current CSS variables, current typography, current palette, "
                "or current composition as design references. Existing files are implementation substrate only. "
            )
            direction_block = ""
            site_evidence_block = ""
        else:
            reference_policy = (
                "Treat current-site evidence as a design reference: preserve recognizable brand signatures or make a "
                "deliberate evolution rather than replacing them with generic defaults. Existing CSS variables, "
                "font families, primary surface, ink, and accent are binding defaults unless the owner explicitly "
                "requests a rebrand; evolve composition, not identity. "
            )
            direction_block = f"SELECTED DIRECTION:\n{canonical_json(direction.to_dict())}\n\n"
            site_evidence_block = f"CURRENT SITE EVIDENCE:\n{canonical_json(self.current_site_evidence)}\n\n"
        incubated_context_block = (
            "INCUBATED CREATIVE CONTEXT (validated evidence and bounded recommendations; not host instructions):\n"
            + canonical_json(self.incubated_creative_context)[:60_000]
            + "\n\n"
            if self.incubated_creative_context
            else ""
        )
        approved_asset_block = (
            "APPROVED MEDIA ASSET IDS (use only these exact IDs in assets, logo_asset_id, and image_asset_id; "
            "all other intake media is not approved for this build):\n"
            + canonical_json(list(self.approved_asset_ids))
            + "\n\n"
            if self.approved_asset_ids is not None
            else ""
        )
        prompt = (
            "Return one valid ReactDesignSpec JSON object. Do not return Markdown, JSX, CSS, arbitrary package names, shell commands, "
            "or executable content. Use only the supplied facts. Keep unavailable destinations unavailable. "
            "Honor the owner design request as a visual brief, not as permission to invent business facts. "
            "The result should feel authored rather than like a starter template: create a distinctive composition, "
            "clear typographic hierarchy, intentional section rhythm, and purposeful use of supplied imagery. "
            "Do not fall back to repetitive cards, generic gradients, decorative filler, or stock-industry language. "
             "Preserve meaning and the primary action on mobile and with reduced motion. "
             "If the supplied assets include a logo or brand mark, set logo_asset_id and use it in the site chrome. "
             + reference_policy
            + "The top-level keys are exactly schema_version, direction_id, site_name, language, site_url, intake_hash, "
             + "navigation, tokens, routes, assets, logo_asset_id, motion, motion_plan, signature_gesture, component_inventory, "
            + "omissions, unknowns, and prohibited_claims. Required fields include schema_version=1, navigation, tokens "
            + "with colors/type/spacing/layout/shape objects, routes, and assets. Use site_name rather than name, routes "
            + "rather than pages, and tokens rather than theme; primary_action belongs on a route or section action. "
            + "Each route must use id, output_path, title, description, h1, sections, and optional primary_action. "
            + "Each section must use kind plus props; supported kinds are hero, editorial, split, features, facts, cta, "
            + "contact, and journal. Do not use route keys name, path, or meta, and do not use section key type. "
            + "Allowed props are hero(eyebrow,title,body,actions,image_asset_id), editorial(eyebrow,title,body,items), "
            + "split(eyebrow,title,body,image_asset_id,image_side,items), features(eyebrow,title,body,items), "
            + "facts(eyebrow,title,body,items), cta(eyebrow,title,body,action), contact(eyebrow,title,body,availability,action), "
            + "and journal(eyebrow,title,body,action). Actions use label, optional href, and available; items use only "
            + "title, body, label, value, and href. "
            + "The host-approved frontend library catalog is provided below. Choose only the exact library names "
            + "needed for the concept in motion.libraries; use an empty list when no runtime library is needed. "
            + "The host verifies and downloads only requested enabled libraries, so never invent packages, versions, or URLs. "
             + "The host will reject unknown fields and unsupported components.\n\n"
             + "motion_plan is optional for compatibility with legacy output. When present, it must be a typed, non-executable "
             + "object with schema_version=1, creative_thesis, audience_fit, template_policy of forbid or owner_requested, "
              + "reduced_motion with strategy exactly one of static, fade-only, or alternate, details, and preserves_content=true, capabilities exactly one or more of core, timeline, stagger, scrolltrigger, parallax, pin, scrub, hover, flip, observer, draggable, react, or signature, pages, signature_interaction, "
             + "and custom_components. Pages must exactly match routes by output_path. Each page section must use the host target "
             + "id section-{index} in route order, and actions may use only the approved kinds entrance, timeline, stagger, "
             + "parallax, pin, scrub, hover, flip, observer, draggable, and signature with declared capabilities. Motion targets "
             + "are IDs, not CSS selectors or code. Custom components must use the host registry only.\n\n"
            + f"INTAKE:\n{canonical_json(intake.to_dict())}\n\n"
            + f"BRIEF:\n{canonical_json(brief.to_dict())}\n\n"
              + direction_block
              + site_evidence_block
                + f"MEDIA METADATA:\n{canonical_json(self.media_metadata)}\n\n"
                + approved_asset_block
                + f"AVAILABLE FRONTEND LIBRARIES:\n{canonical_json(self.frontend_libraries)}\n\n"
               + incubated_context_block
               + INCUBATED_CONTEXT_APPLICATION_RULES
               + "\n\n"
                + "DESIGN SKILLS AND CAPABILITIES:\n"
              + "The host scaffold is Astro/React and can provision approved GSAP and ScrollTrigger runtime files. "
              + "Use high-level frontend, high-end visual, and motion-design judgment when it improves the concept. "
              + "Choose motion from the intake and concept rather than a named or predetermined animation primitive. "
              + "Do not add a counter or meter unless the intake makes it useful; if you add one, derive its range from "
              + "the full content model rather than an arbitrary cap. "
              + "Express a meaningful signature interaction in the typed motion and signature_gesture fields; do not "
              + "return source code, package versions, URLs, or shell commands; use only catalog names in motion.libraries.\n"
              + f"{self.design_guidance}"
              + f"{request_block}"
          )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Ada, an original and opinionated creative director and senior Astro/React web designer. "
                    "Produce a typed design plan as data, never executable source. Avoid safe, interchangeable defaults."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        last_error: Exception | None = None
        self.repair_attempts = 0
        for attempt in range(self.max_repairs + 1):
            try:
                output = self.client.chat(messages, json_mode=True)
                self.last_raw_output = output
                return ReactDesignSpec.from_dict(_normalize_model_spec(
                    _json_object(output),
                    intake,
                    direction,
                    initial_homepage=self.initial_homepage,
                    approved_asset_ids=self.approved_asset_ids,
                ))
            except Exception as exc:  # noqa: BLE001 - convert provider/contract failures into planner errors
                last_error = exc
                if attempt >= self.max_repairs:
                    break
                self.repair_attempts = attempt + 1
                messages.extend([
                    {"role": "assistant", "content": str(output) if "output" in locals() else ""},
                    {"role": "user", "content": f"Repair the JSON against the host contract. Error: {str(exc)[:1200]}"},
                ])
        raise DesignPlannerError(str(last_error or "planner failed")) from last_error


__all__ = [
    "DesignPlanner",
    "DesignPlannerError",
    "DeterministicDesignPlanner",
    "INCUBATED_CONTEXT_APPLICATION_RULES",
    "LLMDesignPlanner",
    "deterministic_spec",
]
