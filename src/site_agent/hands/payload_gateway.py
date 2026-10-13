"""Portable server-to-server client for a Payload-backed draft gateway.

The site-agent keeps the token and talks to Payload through a narrow gateway
exposed by the configured site.  The collection/global contract is supplied by
instance configuration; this module contains no customer names or field IDs.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from ..config import ConfigError
from .base import AdapterError, SiteAdapter, register


_WEBSITE_COLLECTIONS = frozenset({"pages", "posts", "products"})
_WEBSITE_GLOBALS = frozenset({"siteSettings", "navigation"})


class PayloadGatewayError(RuntimeError):
    """The Payload gateway rejected or could not complete a request."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class PayloadContract:
    """Expected identity for the remotely enforced shared authoring schema."""

    media_fields: frozenset[str]
    contract_version: str
    core_version: str
    schema_revision: int
    schema_identity: str

    @property
    def collections(self) -> tuple[str, ...]:
        return tuple(sorted(_WEBSITE_COLLECTIONS))

    @property
    def globals(self) -> tuple[str, ...]:
        return tuple(sorted(_WEBSITE_GLOBALS))

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "PayloadContract":
        raw = settings.get("contract")
        if not isinstance(raw, Mapping):
            raise ConfigError("site.payload.contract must be configured for a Payload gateway")

        raw_media = raw.get("media_fields", [])
        if not isinstance(raw_media, (list, tuple)):
            raise ConfigError("site.payload.contract.media_fields must be a list")
        media_fields = frozenset(str(item or "").strip() for item in raw_media if str(item or "").strip())
        try:
            schema_revision = int(raw.get("schemaRevision") or 0)
        except (TypeError, ValueError) as exc:
            raise ConfigError("site.payload.contract.schemaRevision must be an integer") from exc
        contract_version = str(raw.get("contract") or "").strip()
        core_version = str(raw.get("coreVersion") or "").strip()
        schema_identity = str(raw.get("schemaIdentity") or "").strip()
        if (
            not re.fullmatch(r"helloada-content-v[1-9][0-9]*", contract_version)
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", core_version)
            or schema_revision < 1
            or not re.fullmatch(r"[0-9a-f]{64}", schema_identity)
        ):
            raise ConfigError("site.payload.contract must pin contract, coreVersion, schemaRevision, and schemaIdentity")
        return cls(
            media_fields,
            contract_version,
            core_version,
            schema_revision,
            schema_identity,
        )


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


def _revision(document: Any, response: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise PayloadGatewayError(f"gateway returned no {label}")
    digest = str(response.get("documentHash") or response.get("globalHash") or "").strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise PayloadGatewayError(f"gateway returned no exact {label} revision")
    return {**document, "_helloadaRevision": digest}


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value[:10])
        if "T" in value:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _validate_authoring_link(value: str, path: str) -> None:
    destination = value.strip()
    if (
        "\\" in destination
        or destination.startswith("//")
        or any(ord(char) < 32 for char in destination)
    ):
        raise PayloadGatewayError(f"{path} is not a safe link")
    if destination.startswith(("/", "#", "mailto:", "tel:")):
        return
    try:
        parsed = urllib.parse.urlsplit(destination)
    except ValueError as exc:
        raise PayloadGatewayError(f"{path} is not a safe link") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise PayloadGatewayError(f"{path} is not a safe link")


def _validate_json_value(value: Any, path: str, depth: int = 0) -> None:
    if depth > 40:
        raise PayloadGatewayError(f"{path} exceeds the supported JSON depth")
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise PayloadGatewayError(f"{path} contains a non-finite JSON number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]", depth + 1)
        return
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        for key, item in value.items():
            _validate_json_value(item, f"{path}.{key}", depth + 1)
        return
    raise PayloadGatewayError(f"{path} must contain JSON-compatible data")


def _validate_lexical(value: Any, path: str) -> None:
    if not isinstance(value, Mapping) or set(value) - {"root", "version"}:
        raise PayloadGatewayError(f"{path} is not a supported Payload Lexical document")
    if "version" in value and not isinstance(value["version"], str):
        raise PayloadGatewayError(f"{path}.version must be text")
    root = value.get("root")
    if not isinstance(root, Mapping) or root.get("type") != "root" or not isinstance(root.get("children"), list):
        raise PayloadGatewayError(f"{path} must contain a Payload Lexical root")
    common = {"type", "version", "format", "indent", "direction", "textFormat", "textStyle", "children"}
    fields_by_type = {
        "root": set(), "paragraph": set(), "heading": {"tag"}, "quote": set(),
        "list": {"listType", "start", "tag"}, "listitem": {"value", "checked"},
        "text": {"text", "mode", "detail", "style"}, "linebreak": set(),
        "link": {"fields", "url", "newTab", "linkType", "doc"},
        "autolink": {"fields", "url", "newTab", "linkType", "doc"},
        "upload": {"value", "relationTo"}, "horizontalrule": set(), "tab": set(),
    }

    def walk(node: Any, node_path: str, depth: int) -> None:
        if depth > 40 or not isinstance(node, Mapping) or not isinstance(node.get("type"), str):
            raise PayloadGatewayError(f"{node_path} has an invalid or excessively deep Lexical node")
        node_type = node["type"]
        allowed_type_fields = fields_by_type.get(node_type)
        if allowed_type_fields is None:
            raise PayloadGatewayError(f"{node_path} uses an unsupported Lexical node")
        if set(node) - common - allowed_type_fields:
            raise PayloadGatewayError(f"{node_path} contains unsupported Lexical properties")
        if node_type == "text" and not isinstance(node.get("text"), str):
            raise PayloadGatewayError(f"{node_path}.text must be text")
        if node_type == "heading" and node.get("tag") not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            raise PayloadGatewayError(f"{node_path}.tag is unsupported")
        if node_type == "list" and node.get("listType") not in {"bullet", "number", "check"}:
            raise PayloadGatewayError(f"{node_path}.listType is unsupported")
        if "fields" in node:
            link_fields = node["fields"]
            if not isinstance(link_fields, Mapping) or set(link_fields) - {"url", "newTab", "linkType", "doc"}:
                raise PayloadGatewayError(f"{node_path}.fields contains unsupported link properties")
        children = node.get("children")
        if children is not None:
            if not isinstance(children, list):
                raise PayloadGatewayError(f"{node_path}.children must be a list")
            for index, child in enumerate(children):
                walk(child, f"{node_path}.children[{index}]", depth + 1)

    walk(root, f"{path}.root", 0)


@dataclass(frozen=True)
class PayloadGatewayClient:
    base_url: str
    token: str
    contract: PayloadContract
    timeout_seconds: float = 30.0
    gateway_prefix: str = "/api/workspace"

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
        gateway_prefix = str(settings.get("api_prefix") or "").strip()
        if gateway_prefix != "/api/workspace":
            raise ConfigError("site.payload.api_prefix must be exactly /api/workspace")
        contract = PayloadContract.from_settings(settings)
        return cls(url, token, contract, timeout, gateway_prefix)

    def _gateway_path(self, resource: str) -> str:
        resource = str(resource or "").strip().strip("/")
        if not resource:
            raise PayloadGatewayError("Payload gateway resource is required")
        return f"{self.gateway_prefix}/{resource}"

    def require_authoring_contract(self) -> dict[str, Any]:
        """Read and verify the destination's schema-derived Ada write contract."""
        response = self._request("GET", self._gateway_path("authoring-contract"))
        authoring = response.get("authoring")
        if (
            response.get("version") != 1
            or not isinstance(authoring, Mapping)
            or response.get("contract") != self.contract.contract_version
            or response.get("coreVersion") != self.contract.core_version
            or response.get("schemaRevision") != self.contract.schema_revision
            or not re.fullmatch(r"[0-9a-f]{64}", self.contract.schema_identity)
            or response.get("schemaIdentity") != self.contract.schema_identity
        ):
            raise PayloadGatewayError("The destination's canonical Payload authoring contract is missing or incompatible")
        try:
            serialized = json.dumps(authoring, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            authoring_hash = "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        except (TypeError, ValueError) as exc:
            raise PayloadGatewayError("The destination returned an invalid Payload authoring contract") from exc
        if response.get("authoringContractHash") != authoring_hash:
            raise PayloadGatewayError("The destination's Payload authoring contract hash is invalid")
        enabled = response.get("enabled")
        locales = response.get("locales")
        default_locale = response.get("defaultLocale")
        if not isinstance(enabled, Mapping):
            raise PayloadGatewayError("The destination did not declare enabled Payload website capabilities")
        if (
            not isinstance(locales, list)
            or not locales
            or any(not isinstance(locale, str) or not re.fullmatch(r"[A-Za-z0-9-]{2,20}", locale) for locale in locales)
            or len(set(locales)) != len(locales)
            or default_locale not in locales
        ):
            raise PayloadGatewayError("The destination returned an invalid Payload locale contract")
        enabled_collections = enabled.get("collections")
        enabled_globals = enabled.get("globals")
        if (
            not isinstance(enabled_collections, list)
            or not isinstance(enabled_globals, list)
            or "pages" not in enabled_collections
            or not set(enabled_collections).issubset(_WEBSITE_COLLECTIONS)
            or not set(enabled_globals).issubset(_WEBSITE_GLOBALS)
            or not _WEBSITE_GLOBALS.issubset(set(enabled_globals))
        ):
            raise PayloadGatewayError("The destination advertised an unsupported or incomplete website authoring capability")
        authoring_collections = authoring.get("collections")
        authoring_globals = authoring.get("globals")
        if not isinstance(authoring_collections, Mapping) or not isinstance(authoring_globals, Mapping):
            raise PayloadGatewayError("The destination's Payload authoring schema is incomplete")
        if not set(enabled_collections).issubset(authoring_collections) or not set(enabled_globals).issubset(authoring_globals):
            raise PayloadGatewayError("The destination's enabled authoring capabilities have no schema fields")
        return dict(response)

    @staticmethod
    def _authoring_locale(contract: Mapping[str, Any], locale: str | None) -> str:
        locales = contract.get("locales")
        default_locale = contract.get("defaultLocale")
        if not isinstance(locales, list) or not locales or default_locale not in locales:
            raise PayloadGatewayError("The destination's Payload locale contract is invalid")
        requested = str(locale or default_locale).strip()
        match = next(
            (item for item in locales if isinstance(item, str) and item.casefold() == requested.casefold()),
            None,
        )
        if match is None:
            raise PayloadGatewayError(f"the requested locale '{requested}' is not enabled for this website")
        return match

    def authoring_fields(
        self,
        kind: str,
        slug: str,
        *,
        authoring_contract: Mapping[str, Any] | None = None,
    ) -> tuple[str, ...]:
        contract = authoring_contract or self.require_authoring_contract()
        if kind not in {"collection", "global"}:
            raise PayloadGatewayError("authoring fields require a collection or global")
        authoring = contract.get("authoring")
        section = authoring.get(f"{kind}s") if isinstance(authoring, Mapping) else None
        fields = section.get(slug) if isinstance(section, Mapping) else None
        if not isinstance(fields, list):
            raise PayloadGatewayError(f"the destination does not expose authoring fields for {slug}")
        names = tuple(
            str(field.get("name") or "")
            for field in fields
            if isinstance(field, Mapping) and str(field.get("name") or "").strip()
        )
        if not names:
            raise PayloadGatewayError(f"the destination returned an empty authoring field set for {slug}")
        return names

    @staticmethod
    def _validate_authoring_shape(
        data: Mapping[str, Any],
        fields: Any,
        label: str,
        *,
        block_type: str = "",
        allow_row_id: bool = False,
        require_required: bool = False,
    ) -> None:
        if not isinstance(data, Mapping) or not isinstance(fields, list):
            raise PayloadGatewayError(f"{label} does not match the canonical Payload authoring contract")
        allowed = {
            str(field.get("name")): field
            for field in fields
            if isinstance(field, Mapping) and str(field.get("name") or "").strip()
        }
        unknown = sorted(
            str(key) for key in data
            if str(key) not in allowed
            and not (allow_row_id and str(key) == "id")
            and not (block_type and str(key) == "blockType")
        )
        if unknown:
            raise PayloadGatewayError(f"{label} contains unsupported nested fields: {', '.join(unknown[:8])}")
        if block_type and data.get("blockType") != block_type:
            raise PayloadGatewayError(f"{label}.blockType does not match its declared Payload block")
        if allow_row_id and "id" in data:
            row_id = data.get("id")
            if not ((isinstance(row_id, str) and row_id.strip()) or (isinstance(row_id, int) and not isinstance(row_id, bool) and row_id > 0)):
                raise PayloadGatewayError(f"{label}.id must be a Payload row ID")
        if require_required:
            missing = sorted(
                name for name, field in allowed.items()
                if field.get("required") is True and name not in data
            )
            if missing:
                raise PayloadGatewayError(f"{label} is missing required fields: {', '.join(missing)}")
        for name, value in data.items():
            field = allowed.get(str(name))
            if field is None:
                continue
            kind = str(field.get("type") or "")
            path = f"{label}.{name}"
            supported = {
                "array", "blocks", "checkbox", "date", "email", "group", "json", "number",
                "relationship", "richText", "select", "text", "textarea", "upload",
            }
            if kind not in supported:
                raise PayloadGatewayError(f"{path} uses unsupported Payload authoring type {kind or '(empty)'}")
            if value is None and field.get("required") is not True:
                continue
            if kind in {"group", "array", "blocks"}:
                if kind == "group":
                    PayloadGatewayClient._validate_authoring_shape(
                        value,
                        field.get("fields"),
                        path,
                        require_required=True,
                    )
                    continue
                if not isinstance(value, list):
                    raise PayloadGatewayError(f"{path} must be a list")
                if isinstance(field.get("minRows"), int) and len(value) < field["minRows"]:
                    raise PayloadGatewayError(f"{path} has fewer than its minimum row count")
                if isinstance(field.get("maxRows"), int) and len(value) > field["maxRows"]:
                    raise PayloadGatewayError(f"{path} exceeds its maximum row count")
                blocks = field.get("blocks") if isinstance(field.get("blocks"), list) else []
                for index, item in enumerate(value):
                    if not isinstance(item, Mapping):
                        raise PayloadGatewayError(f"{path}[{index}] must be an object")
                    if kind == "blocks":
                        block = next((candidate for candidate in blocks if isinstance(candidate, Mapping) and candidate.get("slug") == item.get("blockType")), None)
                        if block is None:
                            raise PayloadGatewayError(f"{path}[{index}] uses an unsupported Payload block")
                        nested_fields = block.get("fields")
                        nested_block_type = str(block.get("slug") or "")
                    else:
                        nested_fields = field.get("fields")
                        nested_block_type = ""
                    PayloadGatewayClient._validate_authoring_shape(
                        item,
                        nested_fields,
                        f"{path}[{index}]",
                        block_type=nested_block_type,
                        allow_row_id=True,
                        require_required=True,
                    )
                continue
            if kind in {"text", "textarea", "email", "date"}:
                if not isinstance(value, str):
                    raise PayloadGatewayError(f"{path} must be text")
                if field.get("required") is True and not value.strip():
                    raise PayloadGatewayError(f"{path} must be non-empty text")
                if isinstance(field.get("minLength"), int) and len(value) < field["minLength"]:
                    raise PayloadGatewayError(f"{path} is shorter than its minimum length")
                if isinstance(field.get("maxLength"), int) and len(value) > field["maxLength"]:
                    raise PayloadGatewayError(f"{path} exceeds its maximum length")
                if kind == "date" and not _valid_date(value):
                    raise PayloadGatewayError(f"{path} must be a valid date")
                if kind == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                    raise PayloadGatewayError(f"{path} must be a valid email address")
                if str(field.get("name") or "") in {"href", "promoHref", "canonicalUrl"} and value.strip():
                    _validate_authoring_link(value, path)
                continue
            if kind == "number":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise PayloadGatewayError(f"{path} must be a finite number")
                if not math.isfinite(value):
                    raise PayloadGatewayError(f"{path} must be a finite number")
                if isinstance(field.get("min"), (int, float)) and value < field["min"]:
                    raise PayloadGatewayError(f"{path} is below its minimum")
                if isinstance(field.get("max"), (int, float)) and value > field["max"]:
                    raise PayloadGatewayError(f"{path} exceeds its maximum")
                continue
            if kind == "checkbox":
                if not isinstance(value, bool):
                    raise PayloadGatewayError(f"{path} must be true or false")
                continue
            if kind == "select":
                options = field.get("options")
                values = [item.get("value") if isinstance(item, Mapping) else item for item in options] if isinstance(options, list) else []
                if not values or value not in values:
                    raise PayloadGatewayError(f"{path} is not a supported option")
                continue
            if kind in {"upload", "relationship"}:
                valid_id = lambda item: (isinstance(item, str) and bool(item.strip())) or (isinstance(item, int) and not isinstance(item, bool) and item > 0)
                if field.get("hasMany") is True:
                    if not isinstance(value, list) or not all(valid_id(item) for item in value):
                        raise PayloadGatewayError(f"{path} must be a list of Payload relationship IDs")
                elif not valid_id(value):
                    raise PayloadGatewayError(f"{path} must be a Payload relationship ID")
                continue
            if kind == "richText":
                _validate_lexical(value, path)
                continue
            if kind == "json":
                _validate_json_value(value, path)

    def require_growth_contract(self) -> dict[str, Any]:
        """Managed writes require a destination-enforced contract, not a flag.

        A gateway that only publishes the latest document by ID is not a Growth
        provider. Reject before any draft write when its contract is absent.
        """
        contract = self._request("GET", self._gateway_path("growth/contract"))
        required = {"conditionalDraft", "immutablePreview", "exactApproval", "allPublisherGuard", "effectReceipts"}
        if contract.get("version") != 1 or not required.issubset(set(contract.get("capabilities") or [])):
            raise PayloadGatewayError("The managed Growth publication contract is not installed on this website")
        return contract

    def validate_growth_candidate(self, package: Mapping[str, Any], package_hash: str) -> dict[str, Any]:
        result = self._request("POST", self._gateway_path("growth/validate"), payload={"package": dict(package), "packageHash": package_hash})
        proof = result.get("validation")
        if not isinstance(proof, dict) or proof.get("status") != "passed" or proof.get("packageHash") != package_hash:
            raise PayloadGatewayError("The exact Growth candidate did not pass destination validation")
        required = {"canonicalSchema", "exactDraft", "private", "publicRenderer", "approvalBoundary"}
        checks = proof.get("checks")
        if not isinstance(checks, Mapping) or not all(checks.get(key) is True for key in required):
            raise PayloadGatewayError("The Growth validation proof is incomplete")
        return proof

    def apply_growth_candidate(self, package: Mapping[str, Any], package_hash: str) -> dict[str, Any]:
        result = self._request("POST", self._gateway_path("growth/apply"), payload={"package": dict(package), "packageHash": package_hash})
        if result.get("ok") is not True or result.get("candidateHash") != package.get("candidateHash"):
            raise PayloadGatewayError("The destination did not save the exact Growth candidate")
        return result

    def publish_growth_candidate(self, package_hash: str) -> dict[str, Any]:
        result = self._request("POST", self._gateway_path("growth/publish"), payload={"packageHash": package_hash})
        if result.get("ok") is not True or result.get("status") != "published":
            raise PayloadGatewayError("The destination did not verify publication of the approved Growth candidate")
        return result

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
            raise PayloadGatewayError(f"Payload gateway returned {exc.code}: {message[:300]}", status_code=exc.code) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise PayloadGatewayError("Payload gateway is unreachable") from exc

    def _collection(self, collection: str) -> str:
        collection = str(collection or "").strip().lower()
        if collection not in self.contract.collections or collection not in _WEBSITE_COLLECTIONS:
            raise PayloadGatewayError(f"unsupported Payload collection: {collection or '(empty)'}")
        return collection

    def _data(self, collection: str, data: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise PayloadGatewayError("data must be an object")
        if not data:
            raise PayloadGatewayError("at least one Payload field is required")
        return dict(data)

    def _global(self, slug: str) -> str:
        slug = str(slug or "").strip()
        if slug not in self.contract.globals or slug not in _WEBSITE_GLOBALS:
            raise PayloadGatewayError(f"unsupported Payload global: {slug or '(empty)'}")
        return slug

    def _global_data(self, slug: str, data: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise PayloadGatewayError("data must be an object")
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
        authoring = self.require_authoring_contract()
        locale = self._authoring_locale(authoring, locale)
        if collection not in (authoring.get("enabled") or {}).get("collections", []):
            raise PayloadGatewayError(f"the {collection} module is not enabled for this website")
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
                "locale": locale,
            },
        )
        document = response.get("document")
        return _revision(document, response, "document")

    def list(
        self,
        collection: str,
        *,
        draft: bool = True,
        limit: int = 100,
        locale: str | None = None,
    ) -> list[dict[str, Any]]:
        collection = self._collection(collection)
        authoring = self.require_authoring_contract()
        locale = self._authoring_locale(authoring, locale)
        if collection not in (authoring.get("enabled") or {}).get("collections", []):
            raise PayloadGatewayError(f"the {collection} module is not enabled for this website")
        bounded_limit = max(1, min(int(limit), 100))
        response = self._request(
            "GET",
            self._gateway_path("content"),
            query={
                "collection": collection,
                "draft": str(bool(draft)).lower(),
                "limit": str(bounded_limit),
                "locale": locale,
            },
        )
        documents = response.get("documents")
        if not isinstance(documents, list):
            raise PayloadGatewayError("gateway returned no document list")
        return [item for item in documents if isinstance(item, dict)]

    def create(self, collection: str, data: Mapping[str, Any], *, locale: str | None = None) -> dict[str, Any]:
        collection = self._collection(collection)
        capabilities = self.require_authoring_contract()
        locale = self._authoring_locale(capabilities, locale)
        enabled = (capabilities.get("enabled") or {}).get("collections") or []
        if collection not in enabled:
            raise PayloadGatewayError(f"the {collection} module is not enabled for this website")
        self._validate_authoring_shape(
            self._data(collection, data),
            capabilities["authoring"]["collections"][collection],
            collection,
            require_required=True,
        )
        response = self._request(
            "POST",
            self._gateway_path("content"),
            payload={
                "operation": "create",
                "collection": collection,
                "data": self._data(collection, data),
                "locale": locale,
            },
        )
        return _revision(response.get("document"), response, "created document")

    def update(self, collection: str, document_id: str, data: Mapping[str, Any], *, locale: str | None = None, expected_hash: str | None = None, expected_fields: list[str] | None = None) -> dict[str, Any]:
        collection = self._collection(collection)
        document_id = str(document_id or "").strip()
        if not document_id:
            raise PayloadGatewayError("document id is required")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(expected_hash or "")):
            raise PayloadGatewayError("an exact expected draft revision is required before updating")
        capabilities = self.require_authoring_contract()
        locale = self._authoring_locale(capabilities, locale)
        if collection not in ((capabilities.get("enabled") or {}).get("collections") or []):
            raise PayloadGatewayError(f"the {collection} module is not enabled for this website")
        self._validate_authoring_shape(self._data(collection, data), (capabilities["authoring"]["collections"])[collection], collection)
        response = self._request(
            "POST",
            self._gateway_path("content"),
            payload={
                "operation": "update",
                "collection": collection,
                "id": document_id,
                "data": self._data(collection, data),
                **({"expectedHash": expected_hash, "expectedFields": expected_fields} if expected_hash else {}),
                "locale": locale,
            },
        )
        return _revision(response.get("document"), response, "updated document")

    def publish(self, collection: str, document_id: str, *, locale: str | None = None, expected_hash: str | None = None, expected_fields: list[str] | None = None) -> dict[str, Any]:
        collection = self._collection(collection)
        capabilities = self.require_authoring_contract()
        locale = self._authoring_locale(capabilities, locale)
        if collection not in ((capabilities.get("enabled") or {}).get("collections") or []):
            raise PayloadGatewayError(f"the {collection} module is not enabled for this website")
        document_id = str(document_id or "").strip()
        if not document_id:
            raise PayloadGatewayError("document id is required")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(expected_hash or "")):
            raise PayloadGatewayError("publication requires the exact owner-reviewed draft revision")
        response = self._request(
            "POST",
            self._gateway_path("content"),
            payload={"operation": "publish", "collection": collection, "id": document_id,
                "expectedHash": expected_hash, "locale": locale},
        )
        return _revision(response.get("document"), response, "published document")

    def read_global(self, slug: str, *, draft: bool = True, locale: str | None = None) -> dict[str, Any]:
        slug = self._global(slug)
        capabilities = self.require_authoring_contract()
        locale = self._authoring_locale(capabilities, locale)
        if slug not in ((capabilities.get("enabled") or {}).get("globals") or []):
            raise PayloadGatewayError(f"the {slug} global is not enabled for this website")
        response = self._request(
            "GET",
            self._gateway_path("global"),
            query={
                "global": slug,
                "draft": str(bool(draft)).lower(),
                "locale": locale,
            },
        )
        document = response.get("global")
        return _revision(document, response, "global")

    def update_global(self, slug: str, data: Mapping[str, Any], *, locale: str | None = None, expected_hash: str | None = None) -> dict[str, Any]:
        slug = self._global(slug)
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(expected_hash or "")):
            raise PayloadGatewayError("an exact expected global revision is required before updating")
        capabilities = self.require_authoring_contract()
        locale = self._authoring_locale(capabilities, locale)
        if slug not in ((capabilities.get("enabled") or {}).get("globals") or []):
            raise PayloadGatewayError(f"the {slug} global is not enabled for this website")
        self._validate_authoring_shape(self._global_data(slug, data), (capabilities["authoring"]["globals"])[slug], slug)
        response = self._request(
            "POST",
            self._gateway_path("global"),
            payload={
                "operation": "update",
                "global": slug,
                "data": self._global_data(slug, data),
                "expectedHash": expected_hash,
                "locale": locale,
            },
        )
        return _revision(response.get("global"), response, "updated global")

    def read_booking_configuration(self) -> dict[str, Any]:
        response = self._request("GET", self._gateway_path("booking"))
        settings, types = response.get("settings"), response.get("types")
        if not isinstance(settings, dict) or not isinstance(types, list):
            raise PayloadGatewayError("booking gateway returned an incomplete configuration")
        for item in types:
            if not isinstance(item, dict) or not re.fullmatch(r"ha_booking_[a-f0-9]{32}", str(item.get("id") or "")):
                raise PayloadGatewayError("booking gateway returned an invalid booking type identity")
        return {"settings": settings, "types": types}

    def read_booking_availability(self, type_id: str, local_date: str) -> dict[str, Any]:
        if not re.fullmatch(r"ha_booking_[a-f0-9]{32}", str(type_id or "")) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(local_date or "")):
            raise PayloadGatewayError("a stable booking type ID and local date are required")
        response = self._request("POST", self._gateway_path("booking"), payload={
            "operation": "read_availability", "bookingTypeId": type_id, "date": local_date,
        })
        availability = response.get("availability")
        if not isinstance(availability, dict) or not isinstance(availability.get("slots"), list):
            raise PayloadGatewayError("booking gateway returned invalid availability")
        return availability

    def create_booking_type(self, *, name: str, duration_minutes: int, description: str = "") -> dict[str, Any]:
        name, description = str(name or "").strip(), str(description or "").strip()
        if not name or len(name) > 120 or len(description) > 2000 or not 10 <= int(duration_minutes) <= 480 or int(duration_minutes) % 5:
            raise PayloadGatewayError("booking type name, description, or duration is invalid")
        import unicodedata
        slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()).strip("-")[:80]
        if not slug:
            raise PayloadGatewayError("booking type name must produce a stable reference")
        response = self._request("POST", self._gateway_path("booking"), payload={
            "operation": "create_type",
            "type": {"name": name, "slug": slug, "description": description, "durationMinutes": int(duration_minutes)},
        })
        item = response.get("type")
        if not isinstance(item, dict) or not re.fullmatch(r"ha_booking_[a-f0-9]{32}", str(item.get("id") or "")):
            raise PayloadGatewayError("booking gateway did not return the created type identity")
        return item

    def update_booking_type(self, *, type_id: str, expected_revision: int, name: str, duration_minutes: int, description: str = "") -> dict[str, Any]:
        if not re.fullmatch(r"ha_booking_[a-f0-9]{32}", str(type_id or "")) or int(expected_revision) < 1:
            raise PayloadGatewayError("booking type identity and expected revision are required")
        response = self._request("POST", self._gateway_path("booking"), payload={
            "operation": "update_type", "id": type_id, "expectedRevision": int(expected_revision),
            "type": {"name": str(name or "").strip(), "description": str(description or "").strip(), "durationMinutes": int(duration_minutes)},
        })
        item = response.get("type")
        if not isinstance(item, dict) or item.get("id") != type_id:
            raise PayloadGatewayError("booking gateway did not confirm the updated type")
        return item

    def deactivate_booking_type(self, *, type_id: str, expected_revision: int) -> dict[str, Any]:
        if not re.fullmatch(r"ha_booking_[a-f0-9]{32}", str(type_id or "")) or int(expected_revision) < 1:
            raise PayloadGatewayError("booking type identity and expected revision are required")
        response = self._request("POST", self._gateway_path("booking"), payload={
            "operation": "deactivate_type", "id": type_id, "expectedRevision": int(expected_revision),
        })
        item = response.get("type")
        if not isinstance(item, dict) or item.get("id") != type_id or item.get("enabled") is not False:
            raise PayloadGatewayError("booking gateway did not confirm deactivation")
        return item

    def update_booking_settings(self, settings: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(settings, Mapping):
            raise PayloadGatewayError("booking settings must be an object")
        response = self._request("POST", self._gateway_path("booking"), payload={
            "operation": "update_settings", "settings": dict(settings),
        })
        updated = response.get("settings")
        if not isinstance(updated, dict) or not isinstance(updated.get("revision"), int):
            raise PayloadGatewayError("booking gateway did not return the updated settings revision")
        return updated

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
        return _revision(media, response, "media document")

    def update_media(self, document_id: str, data: Mapping[str, Any], *, expected_hash: str) -> dict[str, Any]:
        document_id = str(document_id or "").strip()
        if not document_id:
            raise PayloadGatewayError("media id is required")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(expected_hash or "")):
            raise PayloadGatewayError("an exact expected media revision is required before updating")
        response = self._request(
            "POST",
            self._gateway_path("media"),
            payload={"operation": "update", "id": document_id, "expectedHash": expected_hash, "data": self._media_data(data)},
        )
        return _revision(response.get("media"), response, "updated media document")


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
    """Read-only source adapter for Payload-backed chat/build workers."""

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

    def get_file(self, path: str, branch: str | None = None) -> tuple[str | None, bytes | None]:
        requested = str(path or "").lstrip("/")
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
