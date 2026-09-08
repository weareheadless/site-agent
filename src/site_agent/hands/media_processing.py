"""Safe mechanical normalization for uploaded images and PDFs."""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError


class MediaProcessingError(ValueError):
    pass


@dataclass(frozen=True)
class ProcessedMedia:
    media_kind: str
    content_type: str
    normalized: bytes
    thumbnail: bytes
    pages: tuple[bytes, ...] = ()
    width: int | None = None
    height: int | None = None
    page_count: int = 0


def _register_heif() -> None:
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return
    register_heif_opener()


def _image_format(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis", b"heic", b"heix", b"hevc", b"mif1"}:
        return "avif" if data[8:12] in {b"avif", b"avis"} else "heif"
    raise MediaProcessingError("Use a photo, image, or PDF.")


def _bounded_image(data: bytes, max_pixels: int) -> Image.Image:
    _register_heif()
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            image = Image.open(io.BytesIO(data))
            if image.width * image.height > max_pixels:
                raise MediaProcessingError("This file is too large to process.")
            image.load()
        except Image.DecompressionBombWarning as exc:
            raise MediaProcessingError("This file is too large to process.") from exc
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise MediaProcessingError("Use a photo, image, or PDF.") from exc
    return image


def _rgb(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        return image.convert("RGBA")
    return image.convert("RGB")


def _webp(image: Image.Image, quality: int, *, animation: bool = False) -> bytes:
    output = io.BytesIO()
    save_kwargs: dict[str, Any] = {"format": "WEBP", "quality": quality, "method": 6}
    if animation and getattr(image, "n_frames", 1) > 1:
        frames = []
        durations = []
        for index in range(image.n_frames):
            image.seek(index)
            frames.append(_rgb(image.copy()))
            durations.append(int(image.info.get("duration", 100)))
        frames[0].save(output, save_all=True, append_images=frames[1:], duration=durations, loop=image.info.get("loop", 0), **save_kwargs)
    else:
        _rgb(image).save(output, **save_kwargs)
    return output.getvalue()


def _thumbnail(image: Image.Image, quality: int, edge: int = 480) -> bytes:
    thumb = _rgb(image)
    thumb.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    return _webp(thumb, quality)


def process_image(data: bytes, *, max_pixels: int = 80_000_000, max_edge: int = 3200, quality: int = 84) -> ProcessedMedia:
    kind = _image_format(data)
    if kind == "pdf":
        raise MediaProcessingError("PDFs must be processed with process_pdf")
    image = _bounded_image(data, max_pixels)
    normalized_image = _rgb(image)
    normalized_image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    if kind == "gif" and getattr(image, "n_frames", 1) > 1:
        # Preserve animation while applying orientation, color, and the edge cap.
        frames = []
        for index in range(image.n_frames):
            image.seek(index)
            frame = _rgb(image.copy())
            frame.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            frames.append(frame)
        normalized_image = frames[0]
        output = io.BytesIO()
        durations = []
        for index in range(image.n_frames):
            image.seek(index)
            durations.append(int(image.info.get("duration", 100)))
        frames[0].save(output, format="WEBP", save_all=True, append_images=frames[1:],
                        duration=durations, loop=image.info.get("loop", 0), quality=quality, method=6)
        normalized = output.getvalue()
    else:
        normalized = _webp(normalized_image, quality)
    return ProcessedMedia(
        media_kind="image", content_type="image/webp", normalized=normalized,
        thumbnail=_thumbnail(image, quality), width=normalized_image.width, height=normalized_image.height,
    )


def process_pdf(data: bytes, *, max_bytes: int = 50 * 1024 * 1024, max_pages: int = 30,
                max_pixels: int = 80_000_000, dpi: int = 220, quality: int = 84) -> ProcessedMedia:
    if len(data) > max_bytes or not data.startswith(b"%PDF-"):
        raise MediaProcessingError("Use a photo, image, or PDF.")
    try:
        import fitz
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise MediaProcessingError("Ada could not read this file. You can retry it.") from exc
    try:
        if document.is_encrypted:
            raise MediaProcessingError("This PDF is password-protected. Upload an unlocked copy.")
        if document.page_count < 1 or document.page_count > max_pages:
            raise MediaProcessingError("This PDF has too many pages to process.")
        optimized = io.BytesIO()
        try:
            document.save(optimized, garbage=4, clean=True, deflate=True)
        except RuntimeError:
            optimized = io.BytesIO()
        normalized = optimized.getvalue() if optimized.tell() and len(optimized.getvalue()) < len(data) else data
        pages: list[bytes] = []
        for page_number in range(document.page_count):
            page = document.load_page(page_number)
            rect = page.rect
            scale = dpi / 72
            if rect.width * scale * rect.height * scale > max_pixels:
                raise MediaProcessingError("This PDF page is too large to process.")
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            pages.append(_webp(image, quality))
        first = Image.open(io.BytesIO(pages[0]))
        return ProcessedMedia(
            media_kind="pdf", content_type="application/pdf", normalized=normalized,
            thumbnail=_thumbnail(first, quality), pages=tuple(pages), page_count=len(pages),
        )
    finally:
        document.close()


def process_media(data: bytes, content_type: str = "", **limits: Any) -> ProcessedMedia:
    kind = _image_format(data)
    if kind == "pdf":
        return process_pdf(data, **limits)
    return process_image(data, **limits)


__all__ = ["MediaProcessingError", "ProcessedMedia", "process_image", "process_media", "process_pdf"]
