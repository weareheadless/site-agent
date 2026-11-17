"""Copy exact canonical public content into the existing isolated Payload preview.

The temporary snapshot is an import input, never a runtime reader or content
fallback. Authentication, owner records and application stores are not copied.
"""
from __future__ import annotations

import base64
import urllib.parse
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..hands.payload_gateway import PayloadGatewayError, PayloadMediaService

# Routable collections. Catalog children and taxonomy are reachable only
# through the documents that reference them, so they never carry a public route.
_WEBSITE_COLLECTIONS = ("pages", "posts", "products")
_GLOBAL_METADATA = frozenset({"id", "_status", "updatedAt", "createdAt", "globalType", "_helloadaRevision", "slug"})
# A compiled preview reads one document per locale over the tenant's gateway.
# The bound keeps an accidentally enormous site from spending the whole build
# budget here; it fails loudly instead of importing part of the site.
MAX_PREVIEW_DOCUMENTS = 2_000
# Every media file the site references is copied into the preview, and those
# bytes are held in this process on the way to the build. Casamigo's catalog is
# the largest known site at 148MB; the bound leaves room to grow while keeping
# one preview from consuming the host that serves every tenant.
MAX_PREVIEW_MEDIA_BYTES = 512 * 1024 * 1024
# A compiled preview reads one document per locale over the tenant's gateway,
# and then every media file those documents reference. Each read is now a
# reused connection, and the tenant Worker answers a media file in 200-600ms,
# so throughput scales with concurrency until the host's own limits: measured
# on one tenant, 4 readers fetched 6.8 files/s, 8 fetched 13.3 and 12 fetched
# 18. Twelve is the ceiling that still leaves the API's request threads and a
# build's memory alone.
PREVIEW_READ_CONCURRENCY = 12


def _global_has_saved_content(document: Mapping[str, Any]) -> bool:
    """Whether a public global read carries any value the owner saved.

    A global that was never published answers a public read with its last saved
    value and `_status: draft`, and the live site renders that value: Oceanic's
    navigation has never been published, so production shows its saved items
    while a preview that dropped the global showed no menu at all. A global with
    nothing saved is still skipped, because seeding it would invent an empty row
    the workspace never stored and the canonical schema rejects it. This reads
    only whether a value exists; it never interprets what the value means.
    """
    for key, value in document.items():
        if key in _GLOBAL_METADATA:
            continue
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, (list, dict)) and value:
            return True
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value:
            return True
    return False


def _collect_upload_ids(fields: Any, document: Any, found: set[str]) -> None:
    """Collect every media ID one document references through its schema.

    Upload relations travel as bare IDs, so a document cannot tell a media ID
    from a document ID without the canonical field types. Walking the authored
    schema is what makes a preview copy exactly the files the site renders
    instead of guessing from the newest part of the library.
    """
    if not isinstance(document, Mapping) or not isinstance(fields, Iterable):
        return
    for field in fields:
        if not isinstance(field, Mapping):
            continue
        kind = str(field.get("type") or "")
        if kind == "tabs":
            for tab in field.get("tabs") or ():
                if isinstance(tab, Mapping):
                    _collect_upload_ids(tab.get("fields"), document, found)
            continue
        name = str(field.get("name") or "")
        if not name:
            _collect_upload_ids(field.get("fields"), document, found)
            continue
        if name not in document:
            continue
        value = document[name]
        if kind == "upload":
            for item in value if isinstance(value, list) else [value]:
                identifier = item.get("id") if isinstance(item, Mapping) else item
                if str(identifier or "").strip():
                    found.add(str(identifier))
        elif kind == "group":
            _collect_upload_ids(field.get("fields"), value, found)
        elif kind == "array":
            for item in value if isinstance(value, list) else ():
                _collect_upload_ids(field.get("fields"), item, found)
        elif kind == "blocks":
            blocks = {
                str(block.get("slug") or ""): block
                for block in field.get("blocks") or () if isinstance(block, Mapping)
            }
            for item in value if isinstance(value, list) else ():
                if not isinstance(item, Mapping):
                    continue
                block = blocks.get(str(item.get("blockType") or ""))
                if block is not None:
                    _collect_upload_ids(block.get("fields"), item, found)


def _nested_media_ids(value: Any, found: set[str]) -> None:
    """Collect media documents embedded in a response, whatever the schema."""
    if isinstance(value, Mapping):
        if value.get("id") and value.get("filename") and value.get("mimeType"):
            found.add(str(value["id"]))
        for child in value.values():
            _nested_media_ids(child, found)
    elif isinstance(value, list):
        for child in value:
            _nested_media_ids(child, found)


def _media_size(document: Mapping[str, Any]) -> int:
    """The declared byte size of one media document, or zero when it states none."""
    for key in ("filesize", "size"):
        try:
            return max(0, int(document.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return 0


def _read_together(items: list[str], read: Callable[[str], Any]) -> list[tuple[str, Any]]:
    """Read independent documents through one bounded pool, in input order.

    The snapshot is a list of exact reads, and a catalog of hundreds turns that
    into hundreds of round trips. The pool is bounded and ordered, so the
    resulting snapshot is identical to a sequential read of the same documents
    while a large site still previews in minutes.
    """
    if len(items) < 2:
        return [(item, read(item)) for item in items]
    with ThreadPoolExecutor(max_workers=min(PREVIEW_READ_CONCURRENCY, len(items))) as pool:
        results = list(pool.map(read, items))
    return list(zip(items, results))


def canonical_preview_snapshot(gateway: Any, effects: list[dict[str, Any]]) -> dict[str, Any]:
    contract = gateway.require_authoring_contract()
    locales = contract["locales"]
    default_locale = contract["defaultLocale"]
    enabled = (contract.get("enabled") or {}).get("collections") or ()
    authoring = contract.get("authoring") or {}
    authoring_collections = authoring.get("collections") or {}
    authoring_globals = authoring.get("globals") or {}
    documents: dict[tuple[str, str], dict[str, Any]] = {}
    globals_: dict[str, dict[str, Any]] = {}

    def record(collection: str, locale: str, document: Mapping[str, Any]) -> None:
        identifier = str(document.get("id") or "").strip()
        if not identifier:
            raise ValueError("canonical preview document has no stable ID")
        entry = documents.setdefault((collection, identifier), {"collection": collection, "id": identifier,
                                                                "locales": {}})
        entry["locales"][locale] = dict(document)

    # The preview renders the whole site, not the newest page of it. The
    # workspace index is the only canonical list that names every editable
    # document; reading it here is what keeps a site with more documents than
    # one gateway page from being previewed as a fraction of itself.
    index = gateway.workspace_index()
    indexed = {
        collection: [
            str(item.get("id") or "").strip()
            for item in index["documents"]
            if isinstance(item, Mapping) and item.get("collection") == collection
        ]
        for collection in _WEBSITE_COLLECTIONS if collection in enabled
    }
    total = sum(len(ids) for ids in indexed.values())
    if total > MAX_PREVIEW_DOCUMENTS:
        raise ValueError(
            f"compiled preview requires a complete canonical content snapshot; this website has "
            f"{total} documents and a compiled preview supports at most {MAX_PREVIEW_DOCUMENTS}"
        )

    omitted: dict[tuple[str, str], int] = {}
    for locale in locales:
        for collection, identifiers in indexed.items():
            def read_public(identifier: str, *, locale: str = locale,
                            collection: str = collection) -> dict[str, Any] | None:
                try:
                    return gateway.read(
                        collection, identifier=identifier, identifier_kind="id",
                        draft=False, locale=locale)
                except PayloadGatewayError as exc:
                    # A document with no public route in this locale is not
                    # part of the site in this locale: the live site cannot
                    # link to it either. Casamigo has properties translated
                    # into one market only, and refusing the whole preview over
                    # them would hide a site that renders.
                    if exc.status_code != 409:
                        raise
                    omitted[(collection, locale)] = omitted.get((collection, locale), 0) + 1
                    return None
            for identifier, document in _read_together(identifiers, read_public):
                if not identifier:
                    raise ValueError("the canonical workspace index has a document without an identity")
                if document is None:
                    continue
                # Payload draft=False selects the main row; an intake-only
                # document there can still be unpublished with empty locales.
                # Only exact candidate effects below may introduce its draft.
                if document.get("_status") != "published":
                    continue
                record(collection, locale, document)
        # Every rendered page reads the shared globals, so the preview needs
        # them even when the candidate does not touch them. A candidate draft
        # below replaces the published value for that locale. What the public
        # read returns is what the live site renders, draft status or not; a
        # global with nothing saved is skipped rather than invented.
        for slug in ("navigation", "siteSettings"):
            document = gateway.read_global(slug, draft=False, locale=locale)
            if isinstance(document, Mapping) and _global_has_saved_content(document):
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
        elif effect["kind"] == "global" and effect["target"] in ("navigation", "siteSettings"):
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
    for entry in documents.values():
        collection = entry["collection"]
        for document in entry["locales"].values():
            _collect_upload_ids(authoring_collections.get(collection), document, media_ids)
            _nested_media_ids(document, media_ids)
    for entry in globals_.values():
        for document in entry["locales"].values():
            _collect_upload_ids(authoring_globals.get(entry["slug"]), document, media_ids)
            _nested_media_ids(document, media_ids)
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

    def read_media_document(identifier: str) -> dict[str, Any]:
        return dict(gateway.read_media(identifier, draft=False))

    # Every referenced file is copied, so the library's declared size is known
    # before a byte is downloaded. The snapshot lives in the shared API process:
    # a library past the bound is refused here rather than filling the host's
    # memory and taking every tenant's requests down with it.
    media_documents = dict(_read_together(sorted(media_ids), read_media_document))
    declared = sum(int(_media_size(row)) for row in media_documents.values())
    if declared > MAX_PREVIEW_MEDIA_BYTES:
        raise ValueError(
            f"compiled preview copies every media file the website references; this website "
            f"references {declared / (1024 * 1024):.0f}MB of media and a compiled preview "
            f"supports at most {MAX_PREVIEW_MEDIA_BYTES // (1024 * 1024)}MB"
        )

    def read_media(identifier: str) -> dict[str, Any]:
        row = media_documents[identifier]
        data, content_type = service.read_preview(
            int(identifier), thumbnail=False,
            url=PayloadMediaService.document_url(gateway, row) or None,
        )
        return {"document": row, "bytes": base64.b64encode(data).decode("ascii"),
                "contentType": content_type}

    media = [item for _, item in _read_together(sorted(media_ids), read_media)]
    return {"schema": 1, "defaultLocale": default_locale, "documents": list(documents.values()),
            "globals": list(globals_.values()), "media": media, "routes": routes,
            "omitted": [
                {"collection": collection, "locale": locale, "documents": count}
                for (collection, locale), count in sorted(omitted.items())
            ]}
