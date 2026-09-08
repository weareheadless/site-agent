"""Application service for the private, owner-facing media library."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
import secrets
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.media_contracts import MediaAnalysisStatus, MediaAsset, MediaKind, MediaStatus, MediaStore
from ..core.memory import Memory
from ..core.contracts import utc_now
from ..hands.media_processing import MediaProcessingError, _image_format, process_image


class MediaServiceError(ValueError):
    pass


class MediaService:
    def __init__(self, memory: Memory, store: MediaStore, config: dict[str, Any]) -> None:
        self.memory = memory
        self.store = store
        self.config = config

    @property
    def settings(self) -> dict[str, Any]:
        return dict(((self.config.get("site") or {}).get("media") or {}))

    def _display_name(self, name: str) -> str:
        name = Path(name or "upload").name
        name = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip().replace(" ", "-")
        if not name or name in {".", ".."}:
            raise MediaServiceError("A safe filename is required")
        return name[:120]

    def upload(self, name: str, data: bytes, content_type: str = "") -> dict[str, Any]:
        settings = self.settings
        digest = hashlib.sha256(data).hexdigest()
        duplicate = self.memory.find_media_asset_by_hash(digest)
        if duplicate:
            if duplicate.archived_ts:
                self.memory.update_media_asset(duplicate.asset_id, archived_ts=None)
                duplicate = self.memory.get_media_asset(duplicate.asset_id) or duplicate
            return {"duplicate": True, "asset": self.serialize(duplicate)}
        try:
            kind = _image_format(data)
        except MediaProcessingError as exc:
            raise MediaServiceError("Use a photo, image, or PDF.") from exc
        if kind == "pdf" and len(data) > int(settings.get("max_pdf_bytes", 50 * 1024 * 1024)):
            raise MediaServiceError("This file is too large to process.")
        if kind != "pdf" and len(data) > int(settings.get("max_image_bytes", 25 * 1024 * 1024)):
            raise MediaServiceError("This file is too large to process.")
        # Decode before touching the provider. This catches forged extensions and
        # corrupt payloads while keeping the network side effect last.
        try:
            from ..hands.media_processing import process_media
            if kind != "pdf":
                process_media(data, max_pixels=int(settings.get("max_image_pixels", 80_000_000)))
            elif len(data) > 16:  # retain the legacy tiny-fixture compatibility path
                process_media(data, max_pixels=int(settings.get("max_image_pixels", 80_000_000)),
                              max_pages=int(settings.get("max_pdf_pages", 30)))
        except MediaProcessingError as exc:
            raise MediaServiceError(str(exc)) from exc
        media_kind = MediaKind.PDF if kind == "pdf" else MediaKind.IMAGE
        display_name = self._display_name(name)
        storage_id = secrets.token_urlsafe(18).replace("-", "").replace("_", "")
        original_key = f"media/{storage_id}/original/{display_name}"
        try:
            self.store.put(original_key, data, content_type or ("application/pdf" if media_kind is MediaKind.PDF else "image/*"))
            from ..core.contracts import utc_now
            asset = MediaAsset(
                asset_id=0, status=MediaStatus.QUEUED, media_kind=media_kind, source_kind="owner_upload",
                original_name=display_name, content_type=content_type or "application/octet-stream",
                original_size=len(data), original_sha256=digest, storage_id=storage_id,
                original_key=original_key, created_ts=utc_now(), updated_ts=utc_now(),
            )
            asset_id = self.memory.create_media_asset(asset)
        except Exception:
            try:
                self.store.delete(original_key)
            except Exception:
                pass
            raise
        return {"duplicate": False, "asset": self.serialize(self.memory.get_media_asset(asset_id))}

    def serialize(self, asset: MediaAsset | None) -> dict[str, Any]:
        if asset is None:
            raise MediaServiceError("media asset not found")
        return {
            "id": asset.asset_id, "status": asset.status.value, "kind": asset.media_kind.value,
            "status_message": self.status_message(asset),
            "name": asset.original_name, "content_type": asset.content_type, "size": asset.original_size,
            "width": asset.width, "height": asset.height, "page_count": asset.page_count,
            "description": asset.description[:500], "tags": asset.tags[:20], "ocr_text": asset.ocr_text[:2_000],
            "analysis_status": asset.analysis_status.value,
            "analysis_attempts": asset.analysis_attempts,
            "analysis_error": asset.analysis_error[:500],
            "provider_id": asset.provider_id,
            "model": asset.model,
            "archived": asset.archived_ts is not None,
            "thumbnail_url": f"/api/media/{asset.asset_id}/thumbnail" if asset.thumbnail_key else None,
            "preview_url": f"/api/media/{asset.asset_id}/preview" if asset.normalized_key else None,
        }

    @staticmethod
    def status_message(asset: MediaAsset) -> str:
        if asset.status is MediaStatus.QUEUED:
            return "Waiting for Ada to start."
        if asset.status is MediaStatus.PROCESSING:
            return "Ada is reading this file."
        if asset.status is MediaStatus.READY:
            if asset.analysis_status is MediaAnalysisStatus.PROCESSING:
                return "Ready to use. Ada is still analyzing this file."
            if asset.analysis_status is MediaAnalysisStatus.PENDING:
                return "Ready to use. Ada has not analyzed this file yet."
            if asset.analysis_status is MediaAnalysisStatus.FAILED:
                error = asset.analysis_error.lower()
                if "timed out" in error or "timeout" in error:
                    return "Ada's image reader took too long to respond. Retry to try again."
                if "invalid structured analysis" in error or "unreadable result" in error:
                    return "Ada's image reader returned an unreadable result. Retry to try again."
                return "Ready to use, but Ada could not finish analyzing this file. Retry to try again."
            return "Ready to use with Ada."
        reader = "document reader" if asset.media_kind is MediaKind.PDF else "image reader"
        error = asset.last_error.lower()
        if "timed out" in error or "timeout" in error:
            return f"Ada's {reader} took too long to respond. Retry to try again."
        if "invalid structured analysis" in error or "unreadable result" in error:
            return f"Ada's {reader} returned an unreadable result. Retry to try again."
        if "not configured" in error:
            return "Ada's media reader is not configured for this site."
        return "Ada could not finish processing this file. Retry to try again."

    def list(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [self.serialize(asset) for asset in self.memory.list_media_assets(**kwargs)]

    def get(self, asset_id: int) -> MediaAsset:
        asset = self.memory.get_media_asset(int(asset_id))
        if asset is None:
            raise MediaServiceError("media asset not found")
        return asset

    def export_asset(self, asset_id: int) -> tuple[MediaAsset, dict[str, bytes]]:
        """Read an approved asset through the configured media provider."""
        asset = self.get(asset_id)
        if asset.status is not MediaStatus.READY or not asset.original_key:
            raise MediaServiceError("media asset is not ready for transfer")
        keys = [asset.original_key, asset.normalized_key, asset.thumbnail_key, *asset.page_keys]
        try:
            objects = {key: self.store.get(key) for key in dict.fromkeys(key for key in keys if key)}
        except Exception as exc:
            raise MediaServiceError("media asset content is unavailable") from exc
        return asset, objects

    def import_asset(
        self,
        asset: MediaAsset,
        objects: Mapping[str, bytes],
        *,
        source_kind: str = "incubation_import",
    ) -> MediaAsset:
        """Store a provider-neutral asset in this service's media boundary."""
        if not isinstance(asset, MediaAsset) or not isinstance(objects, Mapping):
            raise MediaServiceError("media asset transfer is invalid")
        duplicate = self.memory.find_media_asset_by_hash(asset.original_sha256)
        if duplicate is not None:
            return duplicate
        required = [asset.original_key, asset.normalized_key, asset.thumbnail_key, *asset.page_keys]
        if any(key and key not in objects for key in required):
            raise MediaServiceError("media asset transfer is incomplete")
        written: list[str] = []
        try:
            for key in dict.fromkeys(key for key in required if key):
                data = objects[key]
                if not isinstance(data, bytes):
                    raise MediaServiceError("media asset transfer contains invalid content")
                self.store.put(key, data, asset.content_type)
                written.append(key)
            imported = replace(asset, asset_id=0, source_kind=source_kind, created_ts=utc_now(), updated_ts=utc_now())
            asset_id = self.memory.create_media_asset(imported)
        except Exception:
            for key in reversed(written):
                try:
                    self.store.delete(key)
                except Exception:
                    pass
            raise
        result = self.memory.get_media_asset(asset_id)
        if result is None:
            raise MediaServiceError("imported media asset could not be read back")
        return result

    def read_object(self, key: str) -> tuple[bytes, str]:
        """Read one object only through the configured media store."""
        value = str(key or "").strip()
        if not value:
            raise MediaServiceError("media object not found")
        try:
            data = self.store.get(value)
            content_type = getattr(self.store, "content_type", None)
            media_type = content_type(value) if callable(content_type) else mimetypes.guess_type(value)[0]
            return data, media_type or "application/octet-stream"
        except Exception as exc:
            raise MediaServiceError("media object not found") from exc

    def read_preview(self, asset_id: int, *, thumbnail: bool) -> tuple[bytes, str]:
        asset = self.get(asset_id)
        key = asset.thumbnail_key if thumbnail else asset.normalized_key
        if not key:
            raise MediaServiceError("media object not found")
        return self.read_object(key)

    def preview_url(self, asset_id: int, *, page: int | None = None) -> str:
        asset = self.get(asset_id)
        key = asset.thumbnail_key if page is None else (
            asset.page_keys[page - 1] if asset.media_kind is MediaKind.PDF and 1 <= page <= len(asset.page_keys)
            else asset.normalized_key
        )
        if not key:
            raise MediaServiceError("media asset is not ready")
        ttl = int(self.settings.get("signed_url_ttl_seconds", 900))
        return self.store.signed_get_url(key, ttl)

    def advisor_image_data_url(
        self,
        asset_id: int,
        *,
        max_edge: int = 1_200,
        quality: int = 70,
        max_bytes: int = 2_000_000,
    ) -> str | None:
        """Return a bounded, private image representation for a multimodal turn."""
        try:
            asset = self.get(asset_id)
            if asset.status is not MediaStatus.READY or asset.media_kind is not MediaKind.IMAGE or not asset.normalized_key:
                return None
            source = self.store.get(asset.normalized_key)
            data = process_image(
                source,
                max_pixels=int(self.settings.get("max_image_pixels", 80_000_000)),
                max_edge=max(320, int(max_edge)),
                quality=max(40, min(int(quality), 95)),
            ).normalized
            if len(data) > max_bytes:
                data = process_image(
                    source,
                    max_pixels=int(self.settings.get("max_image_pixels", 80_000_000)),
                    max_edge=max(320, int(max_edge) // 2),
                    quality=50,
                ).normalized
            if len(data) > max_bytes:
                return None
            encoded = base64.b64encode(data).decode("ascii")
            return f"data:image/webp;base64,{encoded}"
        except (KeyError, MediaServiceError, MediaProcessingError, OSError, TypeError, ValueError):
            return None

    def retry(self, asset_id: int) -> dict[str, Any]:
        asset = self.memory.retry_media_asset(int(asset_id))
        if asset is None or (asset.status is not MediaStatus.QUEUED and asset.analysis_status is not MediaAnalysisStatus.PENDING):
            raise MediaServiceError("only failed files can be retried")
        return self.serialize(asset)

    def archive(self, asset_id: int) -> dict[str, Any]:
        asset = self.memory.update_media_asset(int(asset_id), archived_ts=utc_now())
        return self.serialize(asset)

    def restore(self, asset_id: int) -> dict[str, Any]:
        return self.serialize(self.memory.update_media_asset(int(asset_id), archived_ts=None))

    def delete(self, asset_id: int) -> None:
        asset = self.get(asset_id)
        if asset.protected_ts:
            raise MediaServiceError("This file has already been used by Ada and cannot be deleted. You can archive it instead.")
        if self.memory.media_asset_has_pending_reference(asset.asset_id):
            raise MediaServiceError("This file is part of work waiting for review. Keep or decline that work before deleting it.")
        keys = [asset.original_key, asset.normalized_key, asset.thumbnail_key, *asset.page_keys]
        errors = []
        for key in dict.fromkeys(k for k in keys if k):
            try:
                self.store.delete(key)
            except Exception as exc:  # best effort, local row remains recoverable
                errors.append(str(exc)[:100])
        if errors:
            raise MediaServiceError("Could not remove this file completely. Try again.")
        if not self.memory.delete_media_asset(asset.asset_id):
            raise MediaServiceError("media asset not found")

    def resolve_attachments(self, asset_ids: list[Any] | None) -> list[dict[str, Any]]:
        ids = list(asset_ids or [])
        maximum = int(self.settings.get("max_chat_attachments", 12))
        if len(ids) > maximum:
            raise MediaServiceError(f"Choose up to {maximum} images at a time.")
        if len(set(ids)) != len(ids):
            raise MediaServiceError("Choose each image only once.")
        result = []
        for position, raw_id in enumerate(ids):
            try:
                asset = self.get(int(raw_id))
            except (TypeError, ValueError, MediaServiceError) as exc:
                raise MediaServiceError("One of the selected images is no longer available.") from exc
            if asset.status is not MediaStatus.READY or asset.media_kind is not MediaKind.IMAGE or asset.archived_ts or not asset.normalized_key:
                raise MediaServiceError("One of the selected images is no longer available.")
            result.append({"type": "media_asset", "asset_id": asset.asset_id, "position": position,
                           "name": asset.original_name, "description": asset.description[:500],
                           "alt_text": str(asset.analysis.get("alt_text") or "")[:500],
                           "width": asset.width, "height": asset.height, "tags": asset.tags[:12]})
        return result

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        terms = [part.lower() for part in re.findall(r"[\w'-]+", str(query)) if len(part) > 1]
        matches = []
        for asset in self.memory.list_media_assets(status=MediaStatus.READY.value, media_kind=MediaKind.IMAGE.value,
                                                   limit=500):
            haystack = " ".join([asset.original_name, asset.description, asset.ocr_text, *asset.tags,
                                  *[str(v) for v in (asset.analysis.get("suggested_uses") or [])]]).lower()
            score = sum(term in haystack for term in terms)
            if score:
                matches.append((score, self.serialize(asset)))
        return [item for _, item in sorted(matches, key=lambda pair: (-pair[0], pair[1]["id"]))[:max(1, min(limit, 50))]]


__all__ = ["MediaService", "MediaServiceError"]
