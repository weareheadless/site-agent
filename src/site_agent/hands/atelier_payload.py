"""Small server-to-server client for Atelier's draft content gateway.

The site-agent keeps the token and talks to Payload through the narrow gateway
exposed by the Atelier Worker.  It intentionally has no generic HTTP or schema
mutation surface: only the collections and operations used by the workspace
are reachable from Ada's editor tools.
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
from .base import AdapterError, SiteAdapter


class AtelierPayloadError(RuntimeError):
    """The Atelier gateway rejected or could not complete a request."""


COLLECTIONS = ("pages", "products", "posts")
GLOBALS = ("navigation", "siteSettings")
MEDIA_EDITABLE_FIELDS = {
    "alt", "description", "tags", "analysisStatus", "analysisProvider", "analysisModel",
    "analysisVersion", "analysisError", "analysisUpdatedAt", "dominantColors", "suggestedUses",
    "qualityNotes", "ocrText", "proposedKnowledge", "sourceKind", "analysis",
}
EDITABLE_FIELDS = {
    "pages": {
        "sourceId", "slug", "title", "sourceUrl", "pageKind", "metaDescription",
        "canonicalUrl", "content", "sections", "openGraph", "seo", "gallery",
    },
    "products": {
        "sourceId", "slug", "title", "sourceUrl", "description", "content",
        "sections", "price", "currency", "availability", "gallery", "category",
    },
    "posts": {
        "sourceId", "slug", "title", "sourceUrl", "excerpt", "content", "sections",
        "publishedAt", "modifiedAt", "author", "featuredImage", "gallery",
    },
}
GLOBAL_EDITABLE_FIELDS = {
    "navigation": {"items", "groups", "footer", "footerGroups"},
    "siteSettings": {
        "siteName", "businessName", "description", "websiteUrl", "tagline", "contactLabel", "telephone", "email",
        "facebookUrl", "instagramUrl", "promoText", "promoHref", "promoCta", "footerKicker", "footerTitle",
        "footerNote", "logo", "address",
    },
}


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
class AtelierPayloadClient:
    base_url: str
    token: str
    timeout_seconds: float = 30.0

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        env: Mapping[str, str] | None = None,
    ) -> "AtelierPayloadClient | None":
        env = os.environ if env is None else env
        site = config.get("site") or {}
        settings = site.get("payload") or {}
        if not isinstance(settings, Mapping) or not bool(settings.get("enabled", False)):
            return None

        url = _valid_url(str(settings.get("url") or "").strip())
        token_env = str(settings.get("token_env") or "ATELIER_SITE_AGENT_TOKEN").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env):
            raise ConfigError("site.payload.token_env must be a valid environment variable name")
        mapped_env = str((config.get("env") or {}).get("atelier_site_agent_token") or "").strip()
        if mapped_env and token_env == "ATELIER_SITE_AGENT_TOKEN":
            token_env = mapped_env
        token = str(env.get(token_env) or "")
        if not token:
            raise ConfigError(f"Atelier Payload gateway is enabled but {token_env} is not set")
        try:
            timeout = float(settings.get("timeout_seconds", 30.0))
        except (TypeError, ValueError) as exc:
            raise ConfigError("site.payload.timeout_seconds must be a positive number") from exc
        if not 0 < timeout <= 120:
            raise ConfigError("site.payload.timeout_seconds must be between 0 and 120")
        return cls(url, token, timeout)

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
            "User-Agent": "site-agent/atelier-payload",
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
            raise AtelierPayloadError(f"Atelier Payload gateway returned {exc.code}: {message[:300]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AtelierPayloadError("Atelier Payload gateway is unreachable") from exc

    @staticmethod
    def _collection(collection: str) -> str:
        collection = str(collection or "").strip().lower()
        if collection not in COLLECTIONS:
            raise AtelierPayloadError(f"unsupported Atelier collection: {collection or '(empty)'}")
        return collection

    @staticmethod
    def _data(collection: str, data: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise AtelierPayloadError("data must be an object")
        allowed = EDITABLE_FIELDS[collection]
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise AtelierPayloadError(
                f"refusing fields outside the {collection} draft contract: {', '.join(unknown[:8])}"
            )
        if not data:
            raise AtelierPayloadError("at least one editable field is required")
        return dict(data)

    @staticmethod
    def _global(slug: str) -> str:
        slug = str(slug or "").strip()
        if slug not in GLOBALS:
            raise AtelierPayloadError(f"unsupported Atelier global: {slug or '(empty)'}")
        return slug

    @staticmethod
    def _global_data(slug: str, data: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise AtelierPayloadError("data must be an object")
        allowed = GLOBAL_EDITABLE_FIELDS[slug]
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise AtelierPayloadError(
                f"refusing fields outside the {slug} global contract: {', '.join(unknown[:8])}"
            )
        if not data:
            raise AtelierPayloadError("at least one editable global field is required")
        return dict(data)

    def read(
        self,
        collection: str,
        *,
        identifier: str,
        identifier_kind: str = "sourceId",
        draft: bool = True,
    ) -> dict[str, Any]:
        collection = self._collection(collection)
        identifier = str(identifier or "").strip()
        if not identifier:
            raise AtelierPayloadError("a document identifier is required")
        if identifier_kind not in {"id", "sourceId", "slug"}:
            raise AtelierPayloadError("identifier_kind must be id, sourceId, or slug")
        response = self._request(
            "GET",
            "/api/atelier/content",
            query={"collection": collection, identifier_kind: identifier, "draft": str(bool(draft)).lower()},
        )
        document = response.get("document")
        if not isinstance(document, dict):
            raise AtelierPayloadError("gateway returned no document")
        return document

    def list(
        self,
        collection: str,
        *,
        draft: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        collection = self._collection(collection)
        bounded_limit = max(1, min(int(limit), 100))
        response = self._request(
            "GET",
            "/api/atelier/content",
            query={
                "collection": collection,
                "draft": str(bool(draft)).lower(),
                "limit": str(bounded_limit),
            },
        )
        documents = response.get("documents")
        if not isinstance(documents, list):
            raise AtelierPayloadError("gateway returned no document list")
        return [item for item in documents if isinstance(item, dict)]

    def create(self, collection: str, data: Mapping[str, Any]) -> dict[str, Any]:
        collection = self._collection(collection)
        return self._request(
            "POST",
            "/api/atelier/content",
            payload={"operation": "create", "collection": collection, "data": self._data(collection, data)},
        ).get("document") or {}

    def update(self, collection: str, document_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
        collection = self._collection(collection)
        document_id = str(document_id or "").strip()
        if not document_id:
            raise AtelierPayloadError("document id is required")
        return self._request(
            "POST",
            "/api/atelier/content",
            payload={
                "operation": "update",
                "collection": collection,
                "id": document_id,
                "data": self._data(collection, data),
            },
        ).get("document") or {}

    def publish(self, collection: str, document_id: str) -> dict[str, Any]:
        collection = self._collection(collection)
        document_id = str(document_id or "").strip()
        if not document_id:
            raise AtelierPayloadError("document id is required")
        return self._request(
            "POST",
            "/api/atelier/content",
            payload={"operation": "publish", "collection": collection, "id": document_id},
        ).get("document") or {}

    def read_global(self, slug: str, *, draft: bool = True) -> dict[str, Any]:
        slug = self._global(slug)
        response = self._request(
            "GET",
            "/api/atelier/global",
            query={"global": slug, "draft": str(bool(draft)).lower()},
        )
        document = response.get("global")
        if not isinstance(document, dict):
            raise AtelierPayloadError("gateway returned no global")
        return document

    def update_global(self, slug: str, data: Mapping[str, Any]) -> dict[str, Any]:
        slug = self._global(slug)
        return self._request(
            "POST",
            "/api/atelier/global",
            payload={"operation": "update", "global": slug, "data": self._global_data(slug, data)},
        ).get("global") or {}

    def publish_global(self, slug: str) -> dict[str, Any]:
        slug = self._global(slug)
        return self._request(
            "POST",
            "/api/atelier/global",
            payload={"operation": "publish", "global": slug},
        ).get("global") or {}

    @staticmethod
    def _media_data(data: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise AtelierPayloadError("media data must be an object")
        unknown = sorted(set(data) - MEDIA_EDITABLE_FIELDS)
        if unknown:
            raise AtelierPayloadError(f"refusing media fields outside the analysis contract: {', '.join(unknown[:8])}")
        if not data:
            raise AtelierPayloadError("at least one media field is required")
        return dict(data)

    def list_media(self, *, draft: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        response = self._request(
            "GET",
            "/api/atelier/media",
            query={"draft": str(bool(draft)).lower(), "limit": str(bounded_limit)},
        )
        media = response.get("media")
        if not isinstance(media, list):
            raise AtelierPayloadError("gateway returned no media list")
        return [item for item in media if isinstance(item, dict)]

    def read_media(self, identifier: str, *, identifier_kind: str = "id", draft: bool = True) -> dict[str, Any]:
        value = str(identifier or "").strip()
        if not value or identifier_kind not in {"id", "sourceId"}:
            raise AtelierPayloadError("a media id or sourceId is required")
        response = self._request(
            "GET",
            "/api/atelier/media",
            query={identifier_kind: value, "draft": str(bool(draft)).lower()},
        )
        media = response.get("media")
        if not isinstance(media, dict):
            raise AtelierPayloadError("gateway returned no media document")
        return media

    def update_media(self, document_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
        document_id = str(document_id or "").strip()
        if not document_id:
            raise AtelierPayloadError("media id is required")
        return self._request(
            "POST",
            "/api/atelier/media",
            payload={"operation": "update", "id": document_id, "data": self._media_data(data)},
        ).get("media") or {}


class AtelierPayloadSiteAdapter(SiteAdapter):
    """No-file adapter used by the shared API's chat worker.

    Ada's Atelier content tools use ``AtelierPayloadClient`` directly.  The
    editor still expects a ``SiteAdapter`` for its common read context, so this
    deliberately empty adapter prevents accidental GitHub/file mutations.
    """

    name = "atelier_payload"

    def __init__(self, config: dict[str, Any] | None = None, *, payload_client: AtelierPayloadClient | None = None):
        super().__init__(config)
        self.payload_client = payload_client

    def get_content(self) -> dict[str, Any]:
        if self.payload_client is None:
            return {}
        collections: dict[str, list[dict[str, Any]]] = {}
        for collection in COLLECTIONS:
            try:
                rows = self.payload_client.list(collection, draft=True, limit=100)
            except AtelierPayloadError:
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
        for slug in GLOBALS:
            try:
                row = self.payload_client.read_global(slug, draft=True) if self.payload_client else {}
            except AtelierPayloadError:
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

    def get_file(self, path: str, branch: str | None = None) -> tuple[None, None]:
        return None, None

    def commit_file(self, path: str, data: bytes, message: str, branch: str | None = None) -> dict[str, Any]:
        raise AdapterError("Atelier content is Payload-backed; file commits are disabled")

    def validate(self) -> None:
        if not self.site.get("payload", {}).get("enabled", False):
            raise AdapterError("Atelier Payload gateway is not enabled")
