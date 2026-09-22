"""Portable server-to-server client for a Payload-backed draft gateway.

The site-agent keeps the token and talks to Payload through a narrow gateway
exposed by the configured site.  The collection/global contract is supplied by
instance configuration; this module contains no customer names or field IDs.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from ..config import ConfigError
from .base import AdapterError, SiteAdapter, register
from .payload_fields import EditableFieldGatewayMixin


class PayloadGatewayError(RuntimeError):
    """The Payload gateway rejected or could not complete a request."""


@dataclass(frozen=True)
class PayloadContract:
    """Configured document/global fields exposed by one Payload instance."""

    collection_fields: Mapping[str, frozenset[str]]
    global_fields: Mapping[str, frozenset[str]]
    media_fields: frozenset[str]

    @property
    def collections(self) -> tuple[str, ...]:
        return tuple(self.collection_fields)

    @property
    def globals(self) -> tuple[str, ...]:
        return tuple(self.global_fields)

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "PayloadContract":
        raw = settings.get("contract")
        if not isinstance(raw, Mapping):
            raise ConfigError("site.payload.contract must be configured for a Payload gateway")

        def field_map(value: Any, label: str, *, required: bool) -> dict[str, frozenset[str]]:
            if value is None and not required:
                return {}
            if not isinstance(value, Mapping):
                raise ConfigError(f"site.payload.contract.{label} must be an object")
            result: dict[str, frozenset[str]] = {}
            for raw_name, raw_fields in value.items():
                name = str(raw_name or "").strip()
                if not name:
                    raise ConfigError(f"site.payload.contract.{label} contains an empty name")
                if not isinstance(raw_fields, (list, tuple)):
                    raise ConfigError(f"site.payload.contract.{label}.{name} must be a list")
                fields = frozenset(str(item or "").strip() for item in raw_fields if str(item or "").strip())
                if not fields:
                    raise ConfigError(f"site.payload.contract.{label}.{name} must contain fields")
                result[name] = fields
            if required and not result:
                raise ConfigError(f"site.payload.contract.{label} must contain at least one entry")
            return result

        collection_fields = field_map(raw.get("collections"), "collections", required=True)
        global_fields = field_map(raw.get("globals"), "globals", required=False)
        raw_media = raw.get("media_fields", [])
        if not isinstance(raw_media, (list, tuple)):
            raise ConfigError("site.payload.contract.media_fields must be a list")
        media_fields = frozenset(str(item or "").strip() for item in raw_media if str(item or "").strip())
        return cls(collection_fields, global_fields, media_fields)


def _valid_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.rstrip("/"))
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError("site.payload.url must be an HTTP(S) URL without credentials or query data")
    return value.rstrip("/")


def _safe_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode(errors="replace")) if raw else {}
    except json.JSONDecodeError:
        return {"message": raw.decode(errors="replace")[:300]}


@dataclass(frozen=True)
class PayloadGatewayClient(EditableFieldGatewayMixin):
    base_url: str
    token: str
    contract: PayloadContract
    timeout_seconds: float = 30.0
    gateway_prefix: str = "/api"

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        env: Mapping[str, str] | None = None,
    ) -> "PayloadGatewayClient | None":
        env = os.environ if env is None else env
        site = config.get("site") or {}
        settings = site.get("payload") or {}
        if not isinstance(settings, Mapping) or not bool(settings.get("enabled", False)):
            return None

        url = _valid_url(str(settings.get("url") or "").strip())
        token_env = str(settings.get("token_env") or "PAYLOAD_GATEWAY_TOKEN").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env):
            raise ConfigError("site.payload.token_env must be a valid environment variable name")
        mapped_env = str((config.get("env") or {}).get("payload_gateway_token") or "").strip()
        if mapped_env and token_env == "PAYLOAD_GATEWAY_TOKEN":
            token_env = mapped_env
        token = str(env.get(token_env) or "")
        if not token:
            raise ConfigError(f"Payload gateway is enabled but {token_env} is not set")
        try:
            timeout = float(settings.get("timeout_seconds", 30.0))
        except (TypeError, ValueError) as exc:
            raise ConfigError("site.payload.timeout_seconds must be a positive number") from exc
        if not 0 < timeout <= 120:
            raise ConfigError("site.payload.timeout_seconds must be between 0 and 120")
        gateway_prefix = str(settings.get("api_prefix") or "/api").strip().rstrip("/")
        if not gateway_prefix.startswith("/") or "?" in gateway_prefix or "#" in gateway_prefix:
            raise ConfigError("site.payload.api_prefix must be an absolute path without query data")
        contract = PayloadContract.from_settings(settings)
        return cls(url, token, contract, timeout, gateway_prefix)

    def _gateway_path(self, resource: str) -> str:
        resource = str(resource or "").strip().strip("/")
        if not resource:
            raise PayloadGatewayError("Payload gateway resource is required")
        return f"{self.gateway_prefix}/{resource}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "site-agent/payload-gateway",
        }
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = _safe_json(response.read(2 * 1024 * 1024))
                return body if isinstance(body, dict) else {"document": body}
        except urllib.error.HTTPError as exc:
            detail = _safe_json(exc.read(32 * 1024))
            if isinstance(detail, dict):
                message = str(detail.get("message") or detail.get("error") or "gateway request failed")
            else:
                message = "gateway request failed"
            raise PayloadGatewayError(f"Payload gateway returned {exc.code}: {message[:300]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise PayloadGatewayError("Payload gateway is unreachable") from exc

    def _collection(self, collection: str) -> str:
        collection = str(collection or "").strip().lower()
        if collection not in self.contract.collections:
            raise PayloadGatewayError(f"unsupported Payload collection: {collection or '(empty)'}")
        return collection

    def _data(self, collection: str, data: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise PayloadGatewayError("data must be an object")
        allowed = self.contract.collection_fields[collection]
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise PayloadGatewayError(
                f"refusing fields outside the {collection} draft contract: {', '.join(unknown[:8])}"
            )
        if not data:
            raise PayloadGatewayError("at least one editable field is required")
        return dict(data)

    def _global(self, slug: str) -> str:
        slug = str(slug or "").strip()
        if slug not in self.contract.globals:
            raise PayloadGatewayError(f"unsupported Payload global: {slug or '(empty)'}")
        return slug

    def _global_data(self, slug: str, data: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise PayloadGatewayError("data must be an object")
        allowed = self.contract.global_fields[slug]
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise PayloadGatewayError(
                f"refusing fields outside the {slug} global contract: {', '.join(unknown[:8])}"
            )
        if not data:
            raise PayloadGatewayError("at least one editable global field is required")
        return dict(data)

    def read(
        self,
        collection: str,
        *,
        identifier: str,
        identifier_kind: str = "sourceId",
        draft: bool = True,
        locale: str | None = None,
    ) -> dict[str, Any]:
        collection = self._collection(collection)
        identifier = str(identifier or "").strip()
        if not identifier:
            raise PayloadGatewayError("a document identifier is required")
        if identifier_kind not in {"id", "sourceId", "slug"}:
            raise PayloadGatewayError("identifier_kind must be id, sourceId, or slug")
        response = self._request(
            "GET",
            self._gateway_path("content"),
            query={
                "collection": collection,
                identifier_kind: identifier,
                "draft": str(bool(draft)).lower(),
                **({"locale": str(locale).strip()} if str(locale or "").strip() else {}),
            },
        )
        document = response.get("document")
        if not isinstance(document, dict):
            raise PayloadGatewayError("gateway returned no document")
        return document

    def list(
        self,
        collection: str,
        *,
        draft: bool = True,
        limit: int = 100,
        locale: str | None = None,
    ) -> list[dict[str, Any]]:
        collection = self._collection(collection)
        bounded_limit = max(1, min(int(limit), 100))
        response = self._request(
            "GET",
            self._gateway_path("content"),
            query={
                "collection": collection,
                "draft": str(bool(draft)).lower(),
                "limit": str(bounded_limit),
                **({"locale": str(locale).strip()} if str(locale or "").strip() else {}),
            },
        )
        documents = response.get("documents")
        if not isinstance(documents, list):
            raise PayloadGatewayError("gateway returned no document list")
        return [item for item in documents if isinstance(item, dict)]

    def create(self, collection: str, data: Mapping[str, Any], *, locale: str | None = None) -> dict[str, Any]:
        collection = self._collection(collection)
        return self._request(
            "POST",
            self._gateway_path("content"),
            payload={
                "operation": "create",
                "collection": collection,
                "data": self._data(collection, data),
                **({"locale": str(locale).strip()} if str(locale or "").strip() else {}),
            },
        ).get("document") or {}

    def update(self, collection: str, document_id: str, data: Mapping[str, Any], *, locale: str | None = None) -> dict[str, Any]:
        collection = self._collection(collection)
        document_id = str(document_id or "").strip()
        if not document_id:
            raise PayloadGatewayError("document id is required")
        return self._request(
            "POST",
            self._gateway_path("content"),
            payload={
                "operation": "update",
                "collection": collection,
                "id": document_id,
                "data": self._data(collection, data),
                **({"locale": str(locale).strip()} if str(locale or "").strip() else {}),
            },
        ).get("document") or {}

    def publish(self, collection: str, document_id: str) -> dict[str, Any]:
        collection = self._collection(collection)
        document_id = str(document_id or "").strip()
        if not document_id:
            raise PayloadGatewayError("document id is required")
        return self._request(
            "POST",
            self._gateway_path("content"),
            payload={"operation": "publish", "collection": collection, "id": document_id},
        ).get("document") or {}

    def read_global(self, slug: str, *, draft: bool = True, locale: str | None = None) -> dict[str, Any]:
        slug = self._global(slug)
        response = self._request(
            "GET",
            self._gateway_path("global"),
            query={
                "global": slug,
                "draft": str(bool(draft)).lower(),
                **({"locale": str(locale).strip()} if str(locale or "").strip() else {}),
            },
        )
        document = response.get("global")
        if not isinstance(document, dict):
            raise PayloadGatewayError("gateway returned no global")
        return document

    def update_global(self, slug: str, data: Mapping[str, Any], *, locale: str | None = None) -> dict[str, Any]:
        slug = self._global(slug)
        return self._request(
            "POST",
            self._gateway_path("global"),
            payload={
                "operation": "update",
                "global": slug,
                "data": self._global_data(slug, data),
                **({"locale": str(locale).strip()} if str(locale or "").strip() else {}),
            },
        ).get("global") or {}

    def publish_global(self, slug: str) -> dict[str, Any]:
        slug = self._global(slug)
        return self._request(
            "POST",
            self._gateway_path("global"),
            payload={"operation": "publish", "global": slug},
        ).get("global") or {}

    @staticmethod
    def _media_data(data: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise PayloadGatewayError("media data must be an object")
        unknown = sorted(set(data) - self.contract.media_fields)
        if unknown:
            raise PayloadGatewayError(f"refusing media fields outside the analysis contract: {', '.join(unknown[:8])}")
        if not data:
            raise PayloadGatewayError("at least one media field is required")
        return dict(data)

    def list_media(self, *, draft: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        response = self._request(
            "GET",
            self._gateway_path("media"),
            query={"draft": str(bool(draft)).lower(), "limit": str(bounded_limit)},
        )
        media = response.get("media")
        if not isinstance(media, list):
            raise PayloadGatewayError("gateway returned no media list")
        return [item for item in media if isinstance(item, dict)]

    def read_media(self, identifier: str, *, identifier_kind: str = "id", draft: bool = True) -> dict[str, Any]:
        value = str(identifier or "").strip()
        if not value or identifier_kind not in {"id", "sourceId"}:
            raise PayloadGatewayError("a media id or sourceId is required")
        response = self._request(
            "GET",
            self._gateway_path("media"),
            query={identifier_kind: value, "draft": str(bool(draft)).lower()},
        )
        media = response.get("media")
        if not isinstance(media, dict):
            raise PayloadGatewayError("gateway returned no media document")
        return media

    def update_media(self, document_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
        document_id = str(document_id or "").strip()
        if not document_id:
            raise PayloadGatewayError("media id is required")
        return self._request(
            "POST",
            self._gateway_path("media"),
            payload={"operation": "update", "id": document_id, "data": self._media_data(data)},
        ).get("media") or {}


@dataclass(frozen=True)
class PayloadMediaAsset:
    """Provider-neutral media shape used by the shared conversation services."""

    asset_id: int
    original_name: str
    content_type: str
    original_size: int
    width: int | None
    height: int | None
    description: str
    tags: tuple[str, ...]
    ocr_text: str
    analysis: dict[str, Any]
    url: str
    alt_text: str
    analysis_status: str
    analysis_error: str = ""
    status: str = "ready"
    media_kind: str = "image"
    archived_ts: None = None
    normalized_key: str = "payload"
    thumbnail_key: str = "payload"


def _media_array_values(value: Any, *, limit: int = 20) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value[:limit]:
        raw = item.get("value") if isinstance(item, Mapping) else item
        text = str(raw or "").strip()
        if text:
            result.append(text[:500])
    return tuple(result)


class PayloadMediaService:
    """Adapt Payload's media collection to the conversation media contract.

    The site owns the binary and metadata record in Payload. The shared site
    agent still needs the same small interface as the local media service so
    intake and chat jobs can validate and describe attached images without
    copying them into a second R2/library implementation.
    """

    def __init__(self, payload: PayloadGatewayClient, *, max_attachments: int = 12) -> None:
        self.payload = payload
        self.max_attachments = max(1, min(int(max_attachments), 20))

    @staticmethod
    def _url(payload: PayloadGatewayClient, document: Mapping[str, Any]) -> str:
        sizes = document.get("sizes") if isinstance(document.get("sizes"), Mapping) else {}
        large = sizes.get("large") if isinstance(sizes, Mapping) else {}
        candidate = str(
            document.get("url")
            or (large.get("url") if isinstance(large, Mapping) else "")
            or document.get("originalUrl")
            or ""
        ).strip()
        if candidate.startswith("/"):
            return f"{payload.base_url}{candidate}"
        return candidate

    def _asset(self, document: Mapping[str, Any]) -> PayloadMediaAsset:
        try:
            asset_id = int(document.get("id"))
        except (TypeError, ValueError) as exc:
            raise PayloadGatewayError("Payload media id must be numeric for chat attachments") from exc
        analysis = document.get("analysis") if isinstance(document.get("analysis"), Mapping) else {}
        alt_text = str(analysis.get("alt_text") or document.get("alt") or document.get("filename") or "Site image").strip()
        return PayloadMediaAsset(
            asset_id=asset_id,
            original_name=str(document.get("filename") or "image").strip()[:120],
            content_type=str(document.get("mimeType") or document.get("mime_type") or "image/*"),
            original_size=int(document.get("filesize") or document.get("size") or 0),
            width=int(document.get("width")) if document.get("width") is not None else None,
            height=int(document.get("height")) if document.get("height") is not None else None,
            description=str(document.get("description") or analysis.get("description") or "").strip()[:500],
            tags=_media_array_values(document.get("tags") or analysis.get("tags")),
            ocr_text=str(document.get("ocrText") or analysis.get("ocr_text") or "").strip()[:2_000],
            analysis=dict(analysis),
            url=self._url(self.payload, document),
            alt_text=alt_text[:500],
            analysis_status=str(document.get("analysisStatus") or "pending").strip().lower(),
            analysis_error=str(document.get("analysisError") or "").strip()[:500],
        )

    def get(self, asset_id: int) -> PayloadMediaAsset:
        document = self.payload.read_media(str(asset_id), identifier_kind="id", draft=True)
        return self._asset(document)

    def serialize(self, asset: PayloadMediaAsset | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(asset, Mapping):
            asset = self._asset(asset)
        return {
            "id": asset.asset_id,
            "asset_id": asset.asset_id,
            "type": "media_asset",
            "status": asset.status,
            "kind": asset.media_kind,
            "status_message": "Available in Payload; Ada analyzes uploaded images automatically.",
            "name": asset.original_name,
            "filename": asset.original_name,
            "content_type": asset.content_type,
            "size": asset.original_size,
            "width": asset.width,
            "height": asset.height,
            "description": asset.description,
            "tags": list(asset.tags),
            "ocr_text": asset.ocr_text,
            "analysis_status": asset.analysis_status,
            "analysis_error": asset.analysis_error or None,
            "analysis": asset.analysis,
            "alt_text": asset.alt_text,
            "thumbnail_url": asset.url or None,
            "preview_url": asset.url or None,
            "url": asset.url or None,
        }

    def preview_url(self, asset_id: int, *, page: int | None = None) -> str:
        del page
        asset = self.get(asset_id)
        if not asset.url:
            raise PayloadGatewayError("Payload media does not expose a readable image URL")
        return asset.url

    def read_preview(self, asset_id: int, *, thumbnail: bool = False) -> tuple[bytes, str]:
        del thumbnail
        url = self.preview_url(asset_id)
        request = urllib.request.Request(url, headers={"Accept": "image/*", "User-Agent": "site-agent/payload-media"})
        try:
            with urllib.request.urlopen(request, timeout=self.payload.timeout_seconds) as response:
                return response.read(25 * 1024 * 1024 + 1), response.headers.get_content_type() or "image/*"
        except (urllib.error.URLError, TimeoutError) as exc:
            raise PayloadGatewayError("Payload media preview is unreachable") from exc

    def resolve_attachments(self, asset_ids: list[Any] | None) -> list[dict[str, Any]]:
        ids = list(asset_ids or [])
        if len(ids) > self.max_attachments:
            raise PayloadGatewayError(f"Choose up to {self.max_attachments} images at a time.")
        result: list[dict[str, Any]] = []
        seen: set[int] = set()
        for position, raw_id in enumerate(ids):
            try:
                asset_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise PayloadGatewayError("One of the attached images is invalid.") from exc
            if asset_id in seen:
                raise PayloadGatewayError("Choose each image only once.")
            seen.add(asset_id)
            asset = self.get(asset_id)
            if not asset.url or not asset.content_type.lower().startswith("image/"):
                raise PayloadGatewayError("One of the attached files is not an image.")
            result.append({
                "type": "media_asset",
                "asset_id": asset.asset_id,
                "position": position,
                "name": asset.original_name,
                "description": asset.description,
                "alt_text": asset.alt_text,
                "width": asset.width,
                "height": asset.height,
                "tags": list(asset.tags),
                "analysis_status": asset.analysis_status,
                "analysis_error": asset.analysis_error or None,
                "thumbnail_url": asset.url,
                "preview_url": asset.url,
                "url": asset.url,
            })
        return result


@register
class PayloadGatewaySiteAdapter(SiteAdapter):
    """Payload-backed adapter used by the shared API's chat worker.

    Ada's Payload content tools use ``PayloadGatewayClient`` directly. The
    editor still expects a ``SiteAdapter`` for its common read context. When a
    source adapter is supplied, repository reads are allowed through that
    adapter while file writes remain disabled here; Payload mutations must use
    the narrow gateway tools instead.
    """

    name = "payload_gateway"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        payload_client: PayloadGatewayClient | None = None,
        read_adapter: Any | None = None,
    ):
        super().__init__(config)
        self.read_adapter = read_adapter
        if payload_client is not None:
            self.payload_client = payload_client
            return
        try:
            self.payload_client = PayloadGatewayClient.from_config(self.root)
        except ConfigError as exc:
            raise AdapterError(str(exc)) from exc

    def get_content(self) -> dict[str, Any]:
        if self.payload_client is None:
            return {}
        collections: dict[str, list[dict[str, Any]]] = {}
        for collection in self.payload_client.contract.collections if self.payload_client else ():
            try:
                rows = self.payload_client.list(collection, draft=True, limit=100)
            except PayloadGatewayError:
                rows = []
            collections[collection] = [
                {
                    key: row.get(key)
                    for key in ("id", "sourceId", "slug", "title", "_status", "updatedAt")
                    if row.get(key) is not None
                }
                for row in rows
            ]
        globals: dict[str, dict[str, Any]] = {}
        for slug in self.payload_client.contract.globals if self.payload_client else ():
            try:
                row = self.payload_client.read_global(slug, draft=True) if self.payload_client else {}
            except PayloadGatewayError:
                row = {}
            globals[slug] = {
                key: row.get(key)
                for key in (
                    "siteName", "businessName", "tagline", "items", "groups", "footer", "footerGroups", "telephone", "email",
                    "facebookUrl", "instagramUrl", "footerKicker", "footerTitle", "footerNote", "address",
                )
                if row.get(key) is not None
            }
        return {"payload_documents": collections, "payload_globals": globals}

    def get_file(self, path: str, branch: str | None = None) -> tuple[str | None, bytes | None]:
        requested = str(path or "").lstrip("/")
        payload_content_path = str(self.site.get("content_path") or "content.json").lstrip("/")
        if requested == payload_content_path:
            # This document belongs to Payload, not the source repository.
            # Let get_content() use the gateway contract instead of asking Git
            # for a path that is expected not to exist on either branch.
            return None, None
        if self.read_adapter is None:
            return None, None
        try:
            return self.read_adapter.get_file(requested, branch=branch)
        except TypeError:
            return self.read_adapter.get_file(requested)

    def list_files(self, branch: str | None = None) -> list[str]:
        if self.read_adapter is None:
            raise AttributeError("repository listing is unavailable")
        try:
            return list(self.read_adapter.list_files(branch=branch))
        except TypeError:
            return list(self.read_adapter.list_files())

    def commit_file(self, path: str, data: bytes, message: str, branch: str | None = None) -> dict[str, Any]:
        raise AdapterError("Payload content is gateway-backed; file commits are disabled")

    def validate(self) -> None:
        if not self.site.get("payload", {}).get("enabled", False) or self.payload_client is None:
            raise AdapterError("Payload gateway is not enabled")
