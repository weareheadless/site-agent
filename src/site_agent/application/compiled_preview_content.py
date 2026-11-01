"""Copy exact canonical public content into the existing isolated Payload preview.

The temporary snapshot is an import input, never a runtime reader or content
fallback. Authentication, owner records and application stores are not copied.
"""
from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

from ..hands.payload_gateway import PayloadMediaService

_WEBSITE_COLLECTIONS = ("pages", "posts", "products", "categories")
_WEBSITE_GLOBALS = ("navigation", "siteSettings")


def canonical_preview_snapshot(gateway: Any, effects: list[dict[str, Any]]) -> dict[str, Any]:
    contract = gateway.require_authoring_contract()
    locales = contract["locales"]
    default_locale = contract["defaultLocale"]
    enabled = (contract.get("enabled") or {}).get("collections") or ()
    documents: dict[tuple[str, str], dict[str, Any]] = {}
    globals_: dict[str, dict[str, Any]] = {}

    def record(collection: str, locale: str, document: Mapping[str, Any]) -> None:
        identifier = str(document.get("id") or "").strip()
        if not identifier:
            raise ValueError("canonical preview document has no stable ID")
        entry = documents.setdefault((collection, identifier), {"collection": collection, "id": identifier,
                                                                "locales": {}})
        entry["locales"][locale] = dict(document)

    for locale in locales:
        for collection in _WEBSITE_COLLECTIONS:
            if collection not in enabled:
                continue
            rows = gateway.list(collection, draft=False, limit=100, locale=locale)
            if len(rows) >= 100:
                raise ValueError("compiled preview requires a complete bounded canonical content snapshot")
            for row in rows:
                record(collection, locale, gateway.read(
                    collection, identifier=str(row.get("id")), identifier_kind="id",
                    draft=False, locale=locale))

    for effect in effects:
        locale = effect["locale"]
        if locale not in locales:
            raise ValueError("candidate content locale is outside the canonical contract")
        if effect["kind"] == "collection":
            collection = effect["target"]
            if collection not in _WEBSITE_COLLECTIONS:
                raise ValueError("compiled preview only imports canonical website content")
            document = gateway.read(collection, identifier=effect["document_id"],
                                    identifier_kind="id", draft=True, locale=locale)
        elif effect["kind"] == "global" and effect["target"] in _WEBSITE_GLOBALS:
            slug = effect["target"]
            document = gateway.read_global(slug, draft=True, locale=locale)
            # Only a candidate-authored global is imported. An untouched global
            # keeps the preview's empty default rather than inventing values the
            # canonical workspace never stored.
            globals_.setdefault(slug, {"slug": slug, "locales": {}})["locales"][locale] = document
        else:
            raise ValueError("compiled preview contains an unsupported canonical content effect")
        if document.get("_helloadaRevision") != effect["revision"]:
            raise ValueError("candidate Payload revision changed before compiled preview")
        if effect["kind"] == "collection":
            record(effect["target"], locale, document)

    media_ids: set[str] = set()

    def referenced_media(value: Any) -> None:
        if isinstance(value, Mapping):
            if value.get("id") and value.get("filename") and value.get("mimeType"):
                media_ids.add(str(value["id"]))
            for child in value.values():
                referenced_media(child)
        elif isinstance(value, list):
            for child in value:
                referenced_media(child)

    referenced_media(list(documents.values()))
    referenced_media(list(globals_.values()))
    service = PayloadMediaService(gateway)
    media = []
    for identifier in sorted(media_ids):
        row = gateway.read_media(identifier, draft=False)
        data, content_type = service.read_preview(int(identifier), thumbnail=False)
        media.append({"document": dict(row), "bytes": base64.b64encode(data).decode("ascii"),
                      "contentType": content_type})
    return {"schema": 1, "defaultLocale": default_locale, "documents": list(documents.values()),
            "globals": list(globals_.values()), "media": media}
