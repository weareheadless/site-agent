"""Copy exact canonical public content into the existing isolated Payload preview.

The temporary snapshot is an import input, never a runtime reader or content
fallback. Authentication, owner records and application stores are not copied.
"""
from __future__ import annotations

import base64
import urllib.parse
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
                document = gateway.read(
                    collection, identifier=str(row.get("id")), identifier_kind="id",
                    draft=False, locale=locale)
                # Payload draft=False selects the main row; an intake-only
                # document there can still be unpublished with empty locales.
                # Only exact candidate effects below may introduce its draft.
                if collection in {"pages", "posts", "products"} and document.get("_status") != "published":
                    continue
                record(collection, locale, document)
        # Every rendered page reads the shared globals, so the preview needs
        # them even when the candidate does not touch them. A candidate draft
        # below replaces the published value for that locale.
        for slug in _WEBSITE_GLOBALS:
            document = gateway.read_global(slug, draft=False, locale=locale)
            if isinstance(document, Mapping) and document:
                globals_.setdefault(slug, {"slug": slug, "locales": {}})["locales"][locale] = dict(document)

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
    # Relations are returned as ids, so a document alone cannot tell which ids
    # are media. Copy the bounded library so every media relation resolves
    # inside the preview instead of pointing at a production row.
    try:
        for row in gateway.list_media(limit=100, draft=False):
            identifier = str(row.get("id") or "").strip()
            if identifier:
                media_ids.add(identifier)
    except Exception:  # noqa: BLE001 - referenced media still copies if listing is unavailable
        pass
    # The public route of every page this candidate saved. The preview runtime
    # must render each of them before the draft is called ready; a page that
    # compiles but throws while rendering is not a preview.
    routes: list[str] = []
    for effect in effects:
        if effect.get("kind") != "collection" or effect.get("target") != "pages":
            continue
        entry = documents.get(("pages", str(effect.get("document_id") or "")))
        if not entry:
            continue
        document = entry["locales"].get(default_locale) or next(iter(entry["locales"].values()), {})
        slug = str(document.get("slug") or "").strip().strip("/")
        if not slug:
            continue
        path = "/" if slug in {"home", "index"} else "/" + "/".join(
            urllib.parse.quote(segment) for segment in slug.split("/")
        )
        if path not in routes:
            routes.append(path)

    service = PayloadMediaService(gateway)
    media = []
    for identifier in sorted(media_ids):
        row = gateway.read_media(identifier, draft=False)
        data, content_type = service.read_preview(int(identifier), thumbnail=False)
        media.append({"document": dict(row), "bytes": base64.b64encode(data).decode("ascii"),
                      "contentType": content_type})
    return {"schema": 1, "defaultLocale": default_locale, "documents": list(documents.values()),
            "globals": list(globals_.values()), "media": media, "routes": routes}
