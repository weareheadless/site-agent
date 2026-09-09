from hashlib import sha256
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from site_agent.core.contracts import ContractError
from site_agent.hands.image_visual_evidence import ImageEvidenceError, extract_image_visual_evidence


def _png(*, alpha: bool) -> bytes:
    image = Image.new("RGBA" if alpha else "RGB", (100, 50), (0, 0, 0, 0) if alpha else (245, 240, 230))
    if alpha:
        ImageDraw.Draw(image).rectangle((20, 10, 79, 39), fill=(20, 30, 40, 255))
    else:
        ImageDraw.Draw(image).rectangle((10, 5, 90, 45), fill=(20, 30, 40))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_transparent_logo_uses_optical_bounds_not_file_bounds():
    data = _png(alpha=True)
    digest = sha256(data).hexdigest()

    evidence = extract_image_visual_evidence(
        asset_id="logo",
        asset_sha256=digest,
        relative_path="public/images/logo.png",
        data=data,
        media_role="logo",
    )

    assert evidence.has_alpha is True
    assert evidence.pixel_width == 100
    assert evidence.pixel_height == 50
    assert evidence.optical_bounds is not None
    assert evidence.optical_bounds.x == pytest.approx(0.2, abs=0.02)
    assert evidence.optical_bounds.width == pytest.approx(0.6, abs=0.02)
    assert evidence.optical_center is not None
    assert evidence.optical_center.x == pytest.approx(0.5, abs=0.02)
    assert evidence.content_hash


def test_opaque_asset_is_conservative_about_optical_bounds_and_does_not_mutate_bytes():
    data = _png(alpha=False)
    before = bytes(data)
    digest = sha256(data).hexdigest()

    evidence = extract_image_visual_evidence(
        asset_id="photo",
        asset_sha256=digest,
        relative_path="public/images/photo.png",
        data=data,
        media_role="photograph",
    )

    assert evidence.optical_bounds is None
    assert evidence.safe_backgrounds == ("unknown",)
    assert data == before


def test_visual_evidence_rejects_unreadable_or_mismatched_assets():
    with pytest.raises(ContractError, match="does not match"):
        extract_image_visual_evidence(
            asset_id="logo",
            asset_sha256="a" * 64,
            relative_path="public/images/logo.png",
            data=b"not-an-image",
            media_role="logo",
        )

    with pytest.raises(ImageEvidenceError, match="could not be decoded"):
        extract_image_visual_evidence(
            asset_id="logo",
            asset_sha256=sha256(b"not-an-image").hexdigest(),
            relative_path="public/images/logo.png",
            data=b"not-an-image",
            media_role="logo",
        )
