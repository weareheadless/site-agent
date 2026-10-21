"""Verified website render inputs. This receipt does not imply preview readiness.

The gateway hashes its exact JSON string; preserving those bytes avoids relying
on JavaScript and Python producing identical number/Unicode serialization.
Media binaries and the built runtime have their own required review receipts.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


class RenderSnapshotError(ValueError):
    """A render input cannot be tied to the expected tenant revision."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RenderSnapshotError("render snapshot contains duplicate JSON keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise RenderSnapshotError(f"non-finite JSON number: {value}")


@dataclass(frozen=True)
class RenderSnapshot:
    json_bytes: bytes
    digest: str

    @classmethod
    def verify(
        cls, envelope: Mapping[str, Any], *, tenant: str, source_sha: str, schema_identity: str,
    ) -> "RenderSnapshot":
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", tenant)
                or not re.fullmatch(r"[0-9a-f]{40}", source_sha)
                or not re.fullmatch(r"[0-9a-f]{64}", schema_identity)):
            raise RenderSnapshotError("expected render identity is incomplete")
        raw = envelope.get("snapshotJson")
        digest = envelope.get("hash")
        if envelope.get("version") != 1 or not isinstance(raw, str) or not isinstance(digest, str):
            raise RenderSnapshotError("render snapshot envelope is invalid")
        encoded = raw.encode("utf-8")
        if digest != "sha256:" + hashlib.sha256(encoded).hexdigest():
            raise RenderSnapshotError("render snapshot digest does not match its bytes")
        try:
            value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        except (ValueError, RecursionError) as exc:
            raise RenderSnapshotError("render snapshot JSON is invalid") from exc
        if not isinstance(value, dict) or set(value) != {
            "schema", "tenant", "sourceSha", "schemaIdentity", "locales", "defaultLocale", "documents", "globals", "media",
        }:
            raise RenderSnapshotError("render snapshot shape is invalid")
        if (value["schema"] != 1 or value["tenant"] != tenant
                or value["sourceSha"] != source_sha or value["schemaIdentity"] != schema_identity):
            raise RenderSnapshotError("render snapshot identity does not match the candidate base")
        locales = value["locales"]
        if (not isinstance(locales, list) or not locales
                or any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9-]{2,20}", item) for item in locales)
                or len(set(locales)) != len(locales) or value["defaultLocale"] not in locales):
            raise RenderSnapshotError("render snapshot locales are invalid")
        for kind in ("documents", "globals"):
            if not isinstance(value[kind], dict) or set(value[kind]) != set(locales):
                raise RenderSnapshotError("render snapshot locale coverage is incomplete")
        collections = {"pages", "posts", "postCategories", "products", "productCategories", "contactForms", "appointmentTypes"}
        for locale in locales:
            documents, globals_ = value["documents"][locale], value["globals"][locale]
            if (not isinstance(documents, dict) or "pages" not in documents or set(documents) - collections
                    or not isinstance(globals_, dict) or set(globals_) != {"navigation", "siteSettings"}
                    or any(not isinstance(row, dict) for row in globals_.values())):
                raise RenderSnapshotError("render snapshot exceeds or omits website scope")
            for rows in documents.values():
                if not isinstance(rows, list) or any(not isinstance(row, dict) or "id" not in row for row in rows):
                    raise RenderSnapshotError("render snapshot documents have invalid identities")
                ids = [str(row["id"]) for row in rows]
                if any(not item or item == "None" for item in ids) or len(set(ids)) != len(ids):
                    raise RenderSnapshotError("render snapshot documents have duplicate identities")
        if not isinstance(value["media"], list) or any(not isinstance(row, dict) for row in value["media"]):
            raise RenderSnapshotError("render snapshot media manifest is invalid")
        media_ids: set[str] = set()
        media_fields = {"id", "sourceId", "filename", "mimeType", "filesize", "width", "height", "url", "thumbnailURL", "focalX", "focalY", "sizes"}
        for row in value["media"]:
            identity = str(row.get("id") or "")
            if (not identity or identity in media_ids or set(row) - media_fields
                    or not isinstance(row.get("filename"), str) or not isinstance(row.get("mimeType"), str)):
                raise RenderSnapshotError("render snapshot media manifest is invalid")
            media_ids.add(identity)
        return cls(encoded, digest)
