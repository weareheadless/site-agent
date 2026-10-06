"""Canonical receipts for Payload revisions consumed by a source candidate.

These receipts bind a content effect to the exact destination, locale and
saved revision. They are coordination metadata, not a second content store.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


_REVISION = re.compile(r"^sha256:[0-9a-f]{64}$")


def payload_revision_manifest(raw: Sequence[Any]) -> tuple[list[dict[str, Any]], str]:
    """Validate, normalize and hash the exact Payload revision dependency set."""
    if not raw:
        return [], ""
    if len(raw) > 100 or any(not isinstance(item, Mapping) for item in raw):
        raise ValueError("the exact Payload effect set is invalid or exceeds the review limit")

    manifest: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in raw:
        kind = str(item.get("kind") or "").strip()
        target = str(item.get("target") or "").strip()
        document_id = str(item.get("document_id") or "").strip()
        revision = str(item.get("revision") or "").strip()
        locale = str(item.get("locale") or "").strip()
        if kind not in {"collection", "global"} or not target or not document_id or not _REVISION.fullmatch(revision) or not locale:
            raise ValueError("a required Payload effect has no exact destination, locale, or saved revision")
        identity = (kind, target, document_id, locale)
        if identity in seen:
            raise ValueError("the Payload effect set contains a duplicate destination revision")
        seen.add(identity)
        fields = item.get("fields") if isinstance(item.get("fields"), list) else []
        manifest.append({
            "kind": kind,
            "operation": str(item.get("operation") or "update"),
            "target": target,
            "document_id": document_id,
            "revision": revision,
            "locale": locale,
            "fields": sorted({str(field) for field in fields if str(field).strip()}),
            "summary": str(item.get("summary") or "")[:500],
        })
    manifest.sort(key=lambda item: (item["kind"], item["target"], item["document_id"], item["locale"]))
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return manifest, hashlib.sha256(encoded.encode("utf-8")).hexdigest()
