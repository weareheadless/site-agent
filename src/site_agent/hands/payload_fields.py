"""Portable declarative-field operations for Payload-backed sites.

This module contains no site, customer, route, or field-ID knowledge.  A
Payload adapter supplies the HTTP request method and collection contract; the
field operations only speak the stable field gateway protocol.
"""

from __future__ import annotations

from typing import Any, Mapping


EDITABLE_TYPES = ("text", "richText", "image", "link")


class EditableFieldError(RuntimeError):
    """A declarative field request was invalid before it reached Payload."""


class EditableFieldGatewayMixin:
    """Add the portable field gateway contract to any Payload HTTP client.

    The host client must provide ``_collection`` and ``_request``.  Keeping the
    mixin independent from a particular tenant lets other Payload adapters use
    the same Ada tools without importing a customer-specific module.
    """

    def _editable_fields_path(self) -> str:
        path_builder = getattr(self, "_gateway_path", None)
        if callable(path_builder):
            return path_builder("editable-fields")
        return "/api/editable-fields"

    @staticmethod
    def _editable_identifier(identifier: str, identifier_kind: str) -> dict[str, str]:
        identifier = str(identifier or "").strip()
        if not identifier:
            raise EditableFieldError("a document identifier is required")
        if identifier_kind not in {"id", "sourceId", "slug"}:
            raise EditableFieldError("identifier_kind must be id, sourceId, or slug")
        return {identifier_kind: identifier}

    @staticmethod
    def _editable_type(field_type: str | None) -> str | None:
        value = str(field_type or "").strip()
        if value and value not in EDITABLE_TYPES:
            raise EditableFieldError(
                f"editable field type must be one of: {', '.join(EDITABLE_TYPES)}"
            )
        return value or None

    def inspect_editable_fields(
        self,
        collection: str,
        *,
        identifier: str,
        identifier_kind: str = "sourceId",
        draft: bool = True,
        locale: str | None = None,
    ) -> dict[str, Any]:
        """Read only the explicit field registry for one Payload document."""
        collection = self._collection(collection)
        query = {
            "collection": collection,
            **self._editable_identifier(identifier, identifier_kind),
            "draft": str(bool(draft)).lower(),
        }
        if str(locale or "").strip():
            query["locale"] = str(locale).strip()
        response = self._request("GET", self._editable_fields_path(), query=query)
        fields = response.get("fields")
        if not isinstance(fields, list):
            raise EditableFieldError("gateway returned no editable field list")
        return response

    def define_editable_field(
        self,
        collection: str,
        *,
        identifier: str,
        key: str,
        field_type: str,
        label: str,
        section: str | None = None,
        value: Any = None,
        image: Any = None,
        rich_text: Any = None,
        identifier_kind: str = "sourceId",
        locale: str | None = None,
    ) -> dict[str, Any]:
        """Create one stable field binding, or complete its definition."""
        collection = self._collection(collection)
        normalized_type = self._editable_type(field_type)
        if normalized_type is None:
            raise EditableFieldError("editable field type is required")
        if not str(key or "").strip():
            raise EditableFieldError("editable field key is required")
        if not str(label or "").strip():
            raise EditableFieldError("editable field label is required")
        payload: dict[str, Any] = {
            "operation": "define",
            "collection": collection,
            **self._editable_identifier(identifier, identifier_kind),
            "key": str(key).strip(),
            "type": normalized_type,
            "label": str(label).strip(),
        }
        if section is not None:
            payload["section"] = str(section).strip()
        if value is not None:
            payload["value"] = value
        if image is not None:
            payload["image"] = image
        if rich_text is not None:
            payload["richText"] = rich_text
        if str(locale or "").strip():
            payload["locale"] = str(locale).strip()
        return self._request("POST", self._editable_fields_path(), payload=payload)

    def set_editable_field(
        self,
        collection: str,
        *,
        identifier: str,
        key: str,
        value: Any = None,
        image: Any = None,
        expected_value: str | None = None,
        identifier_kind: str = "sourceId",
        locale: str | None = None,
    ) -> dict[str, Any]:
        """Update a registered field without creating a binding accidentally."""
        collection = self._collection(collection)
        if not str(key or "").strip():
            raise EditableFieldError("editable field key is required")
        if value is None and image is None:
            raise EditableFieldError("editable field value or image is required")
        payload: dict[str, Any] = {
            "operation": "set_value",
            "collection": collection,
            **self._editable_identifier(identifier, identifier_kind),
            "key": str(key).strip(),
        }
        if value is not None:
            payload["value"] = value
        if image is not None:
            payload["image"] = image
        if expected_value is not None:
            payload["expected_value"] = expected_value
        if str(locale or "").strip():
            payload["locale"] = str(locale).strip()
        return self._request("POST", self._editable_fields_path(), payload=payload)

    def validate_editable_fields(
        self,
        collection: str,
        *,
        identifier: str,
        identifier_kind: str = "sourceId",
        locale: str | None = None,
    ) -> dict[str, Any]:
        """Check stable IDs, duplicate bindings, labels, and types without writing."""
        collection = self._collection(collection)
        payload: dict[str, Any] = {
            "operation": "validate",
            "collection": collection,
            **self._editable_identifier(identifier, identifier_kind),
        }
        if str(locale or "").strip():
            payload["locale"] = str(locale).strip()
        return self._request("POST", self._editable_fields_path(), payload=payload)

    def migrate_editable_fields(
        self,
        collection: str,
        *,
        identifier: str,
        fields: list[Mapping[str, Any]],
        identifier_kind: str = "sourceId",
        locale: str | None = None,
    ) -> dict[str, Any]:
        """Apply an explicit, reviewable batch of declarations atomically."""
        collection = self._collection(collection)
        if not fields:
            raise EditableFieldError("at least one editable field definition is required")
        if len(fields) > 100:
            raise EditableFieldError("at most 100 editable field definitions may be migrated at once")
        payload: dict[str, Any] = {
            "operation": "migrate",
            "collection": collection,
            **self._editable_identifier(identifier, identifier_kind),
            "fields": [dict(field) for field in fields],
        }
        if str(locale or "").strip():
            payload["locale"] = str(locale).strip()
        return self._request("POST", self._editable_fields_path(), payload=payload)
