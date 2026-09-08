import io

import pytest
from PIL import Image

from site_agent.hands.media_processing import MediaProcessingError, process_image


def _jpeg(size=(100, 50)):
    output = io.BytesIO()
    Image.new("RGB", size, "red").save(output, format="JPEG")
    return output.getvalue()


def test_image_normalization_resizes_and_creates_thumbnail():
    result = process_image(_jpeg((5000, 1000)), max_edge=3200)
    assert result.media_kind == "image"
    assert result.content_type == "image/webp"
    assert result.width == 3200
    assert result.height == 640
    assert result.normalized.startswith(b"RIFF")
    assert result.thumbnail.startswith(b"RIFF")


def test_unknown_and_pdf_inputs_are_rejected_by_image_processor():
    with pytest.raises(MediaProcessingError, match="Use a photo"):
        process_image(b"not-an-image")
    with pytest.raises(MediaProcessingError, match="PDFs"):
        process_image(b"%PDF-1.7 fake")
