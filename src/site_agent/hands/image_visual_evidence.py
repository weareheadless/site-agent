"""Deterministic, provider-neutral visual evidence for approved local images.

This module measures image bytes only.  It never chooses a layout, changes the
source bytes, calls a network service, or invents semantic meaning.  Semantic
enrichment can be layered on later through the versioned evidence contract.
"""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from typing import Any

from PIL import Image, ImageStat, UnidentifiedImageError

from ..core.contracts import ContractError
from ..core.design_contracts import AssetVisualEvidence


class ImageEvidenceError(RuntimeError):
    """The approved bytes could not be decoded into deterministic evidence."""


_ALPHA_THRESHOLD = 8


def _alpha_mask(image: Image.Image) -> Image.Image | None:
    if "A" not in image.getbands() and "transparency" not in image.info:
        return None
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    return alpha.point(lambda value: 255 if value > _ALPHA_THRESHOLD else 0)


def _optical_bounds(mask: Image.Image):
    from ..core.design_contracts import NormalizedRegion

    bounds = mask.getbbox()
    if not bounds:
        return None
    left, top, right, bottom = bounds
    width, height = mask.size
    return NormalizedRegion.from_dict({
        "x": left / width,
        "y": top / height,
        "width": (right - left) / width,
        "height": (bottom - top) / height,
        "confidence": 0.98,
        "label": "visible-content",
    }, "asset_visual_evidence.optical_bounds")


def _optical_center(mask: Image.Image):
    from ..core.design_contracts import NormalizedPoint

    width, height = mask.size
    pixels = mask.load()
    total = 0
    x_total = 0
    y_total = 0
    for y in range(height):
        for x in range(width):
            weight = int(pixels[x, y])
            if weight:
                total += weight
                x_total += x * weight
                y_total += y * weight
    if not total:
        return None
    return NormalizedPoint.from_dict({
        "x": (x_total / total) / max(width - 1, 1),
        "y": (y_total / total) / max(height - 1, 1),
        "confidence": 0.96,
        "label": "visible-content",
    }, "asset_visual_evidence.optical_center")


def _visual_mass(image: Image.Image, mask: Image.Image | None) -> tuple[float, ...]:
    """Return a bounded 3x3 summary without treating it as a design decision."""
    if mask is not None:
        sample = mask.resize((3, 3), Image.Resampling.BOX)
        return tuple(round(float(value) / 255.0, 4) for value in sample.getdata())
    grayscale = image.convert("L").resize((3, 3), Image.Resampling.BOX)
    # Darker pixels carry more visual mass in this conservative summary.  The
    # result is evidence for a specialist, not an instruction to use darkness.
    return tuple(round(1.0 - (float(value) / 255.0), 4) for value in grayscale.getdata())


def _dominant_colors(image: Image.Image) -> tuple[str, ...]:
    sample = image.convert("RGB").copy()
    sample.thumbnail((64, 64), Image.Resampling.BOX)
    colors = sample.getcolors(maxcolors=64 * 64)
    if not colors:
        average = ImageStat.Stat(sample).mean
        return ("#%02x%02x%02x" % tuple(int(max(0, min(255, value))) for value in average[:3]),)
    colors.sort(key=lambda item: item[0], reverse=True)
    result: list[str] = []
    for _, rgb in colors:
        value = "#%02x%02x%02x" % tuple(int(channel) for channel in rgb[:3])
        if value not in result:
            result.append(value)
        if len(result) >= 4:
            break
    return tuple(result)


def extract_image_visual_evidence(
    *,
    asset_id: str,
    asset_sha256: str,
    relative_path: str,
    data: bytes,
    media_role: str = "unknown",
    semantic: dict[str, Any] | None = None,
    evidence_sources: tuple[str, ...] = ("deterministic",),
    analyzer_version: str = "image-visual-evidence-v1",
    provider_id: str = "host",
    model: str = "",
) -> AssetVisualEvidence:
    """Measure one approved image without mutating or persisting its bytes."""
    actual_sha256 = sha256(bytes(data)).hexdigest()
    if str(asset_sha256 or "").lower() != actual_sha256:
        raise ContractError("asset_visual_evidence asset_sha256 does not match supplied bytes")
    try:
        with Image.open(BytesIO(bytes(data))) as opened:
            image = opened.copy()
            image.load()
    except (OSError, SyntaxError, UnidentifiedImageError) as exc:
        raise ImageEvidenceError("approved image could not be decoded") from exc

    if image.width < 1 or image.height < 1:
        raise ImageEvidenceError("approved image has invalid dimensions")
    mask = _alpha_mask(image)
    semantic = semantic if isinstance(semantic, dict) else {}
    evidence = {
        "schema_version": 1,
        "asset_id": asset_id,
        "asset_sha256": actual_sha256,
        "relative_path": relative_path,
        "media_role": media_role,
        "pixel_width": image.width,
        "pixel_height": image.height,
        "aspect_ratio": image.width / image.height,
        "has_alpha": mask is not None,
        "optical_bounds": _optical_bounds(mask).to_dict() if mask is not None and _optical_bounds(mask) else None,
        "optical_center": _optical_center(mask).to_dict() if mask is not None and _optical_center(mask) else None,
        "visual_mass": list(_visual_mass(image, mask)),
        "safe_backgrounds": ["unknown"],
        "minimum_legible_size": None,
        "dominant_colors": list(_dominant_colors(image)),
        "contrast_edges": [],
        "focal_regions": [],
        "negative_space_regions": [],
        "semantic_description": str(semantic.get("description") or "")[:4_000],
        "subjects": list(semantic.get("subjects") or ())[:40],
        "materials_and_textures": list(semantic.get("materials_and_textures") or ())[:40],
        "emotional_tone": str(semantic.get("emotional_tone") or "")[:1_000],
        "brand_signals": list(semantic.get("brand_signals") or ())[:40],
        "quality_constraints": list(semantic.get("quality_constraints") or ())[:40],
        "evidence_sources": list(evidence_sources),
        "confidence": 0.92 if mask is not None else 0.65,
        "analyzer_version": analyzer_version,
        "provider_id": provider_id,
        "model": model,
    }
    return AssetVisualEvidence.from_dict(evidence)


__all__ = ["ImageEvidenceError", "extract_image_visual_evidence"]
