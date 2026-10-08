"""Server-only, local registration of a HelloAda website tenant.

Registering a website in HelloAda creates its tenant identity on the local
filesystem: a tenant config, dedicated memory database, runtime API token and
a pending entry in the sole tenant registry. The shared API mounts that tenant
only after bootstrap verifies its canonical Payload Worker.

This module intentionally stops before provider mutations. The companion
``application.bootstrap`` saga owns the separately retryable GitHub/Cloudflare/
Payload bootstrap after this local identity and token boundary exists.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from ..core.memory import SCHEMA_VERSION, Memory

_SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_SAFE_ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# The edge Worker has one stable secret name. The value is still unique per
# tenant because the shared API stores it under tenant_token_env(tenant_id).
# Keeping this boundary explicit prevents a tenant-specific Worker name from
# drifting away from the generated Payload template.
WORKER_SITE_AGENT_TOKEN_ENV = "HELLOADA_SITE_AGENT_TOKEN"

_TENANTS_FILE = "tenants.json"


class TenantRegistrationError(ValueError):
    """A website workspace cannot be provisioned safely."""


def tenant_token_env(tenant_id: str) -> str:
    """Deterministic per-tenant runtime token environment variable name."""
    return "PROVISIONED_" + str(tenant_id or "").replace("-", "_").upper() + "_TOKEN"


def provisioned_root(config: Mapping[str, Any]) -> Path:
    """Root directory for runtime-registered tenant workspaces."""
    section = config.get("workspace_api") or {}
    section = section if isinstance(section, Mapping) else {}
    configured = str(section.get("provisioned_root") or "").strip()
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        data_dir = str(config.get("data_dir") or "data").strip()
        root = Path(data_dir).expanduser().resolve() / "websites"
    if root == Path(root.anchor) or root.parent == root:
        raise TenantRegistrationError("provisioned tenant root is too broad")
    return root


def load_provisioned_tenants(
    config: Mapping[str, Any],
    env: Mapping[str, str] | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return declared tenant specs and token environment reloaded from disk.

    Called at API startup so runtime-registered websites survive a restart.
    Returns (tenant_specs, extra_env) where tenant_specs maps tenant id to
    ``{"config_path": ..., "api_token_env": ...}`` and extra_env carries each
    tenant's api token read from its 0600 env file.
    """
    root = provisioned_root(config)
    index_path = root / _TENANTS_FILE
    if not index_path.is_file():
        return {}, {}
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise TenantRegistrationError("tenant registry is unreadable") from exc
    declared: dict[str, Any] = {}
    extra_env: dict[str, str] = {}
    if not isinstance(raw, Mapping):
        raise TenantRegistrationError("tenant registry must be an object")
    configured_section = config.get("workspace_api") or {}
    configured_tenants = configured_section.get("tenants") if isinstance(configured_section, Mapping) else {}
    configured_ids = {
        str(value or "").strip().lower()
        for value in (configured_tenants.keys() if isinstance(configured_tenants, Mapping) else ())
    }
    for tenant_id, entry in raw.items():
        tenant_id = str(tenant_id or "").strip().lower()
        if not _SAFE_ID.fullmatch(tenant_id) or not isinstance(entry, Mapping):
            raise TenantRegistrationError("tenant registry contains an invalid entry")
        if tenant_id in configured_ids:
            # A host-declared tenant owns its id; a persisted website must not
            # silently shadow it during a restart.
            raise TenantRegistrationError(f"tenant {tenant_id} registration paths are invalid")
        config_path = Path(str(entry.get("config_path") or "")).expanduser().resolve()
        token_env = str(entry.get("api_token_env") or tenant_token_env(tenant_id)).strip()
        bootstrap_state = str(entry.get("bootstrap_state") or "ready").strip()
        tenant_dir = (root / tenant_id).resolve()
        env_path = tenant_dir / "tenant.env"
        if (
            not config_path.is_file()
            or root.resolve() not in config_path.parents
            or config_path.name != "config.yaml"
            or tenant_dir != config_path.parent
            or not _SAFE_ENV.fullmatch(token_env)
        ):
            raise TenantRegistrationError(f"tenant {tenant_id} registration paths are invalid")
        if bootstrap_state not in {"pending", "runtime", "ready"}:
            raise TenantRegistrationError(
                f"tenant {tenant_id} has an unsupported bootstrap state"
            )
        if bootstrap_state == "pending":
            continue
        token = _read_token_env(env_path, token_env)
        if not token:
            raise TenantRegistrationError(f"tenant {tenant_id} runtime token is missing")
        extra_env[token_env] = token
        declared[tenant_id] = {"config_path": str(config_path), "api_token_env": token_env}
    return declared, extra_env


class TenantRegistrationService:
    """Persist a tenant identity before its canonical Payload runtime exists."""

    def __init__(
        self,
        config: Mapping[str, Any],
        env: Mapping[str, str],
        *,
        registry: Any,
    ) -> None:
        self.config = dict(config)
        self.env = dict(env or {})
        self.registry = registry
        self.root = provisioned_root(config)
        self._lock = threading.RLock()

    # -- helpers ----------------------------------------------------------

    def _tenant_dir(self, tenant_id: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        tenant_dir = (self.root / tenant_id).resolve()
        expected_root = self.root.resolve()
        if tenant_dir == expected_root or expected_root not in tenant_dir.parents:
            raise TenantRegistrationError("tenant directory escapes the provisioned root")
        return tenant_dir

    def _registry_lock(self) -> int:
        """Serialize registration and registry changes across API processes."""
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        return os.open(self.root / ".registration.lock", os.O_CREAT | os.O_RDWR, 0o600)

    @staticmethod
    def _write_config(path: Path, config: Mapping[str, Any]) -> bool:
        if path.exists():
            try:
                existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                raise TenantRegistrationError("existing tenant config is unreadable") from exc
            if isinstance(existing, Mapping) and existing.get("instance_name") == config.get("instance_name"):
                return False
            raise TenantRegistrationError("existing tenant config belongs to another tenant")
        TenantRegistrationService._replace_config(path, config)
        return True

    @staticmethod
    def _replace_config(path: Path, config: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            temporary.write_text(yaml.safe_dump(dict(config), sort_keys=False), encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(path)
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise TenantRegistrationError("tenant config could not be created") from exc

    @staticmethod
    def _record_index(
        root: Path,
        tenant_id: str,
        config_path: Path,
        token_env: str,
        *,
        bootstrap_state: str,
    ) -> None:
        index_path = root / _TENANTS_FILE
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
        except (OSError, ValueError, UnicodeError) as exc:
            raise TenantRegistrationError("tenant registry is unreadable") from exc
        if not isinstance(raw, dict):
            raise TenantRegistrationError("tenant registry must be an object")
        raw[tenant_id] = {
            "config_path": str(config_path),
            "api_token_env": token_env,
            "bootstrap_state": bootstrap_state,
        }
        temporary = index_path.with_name(f"{index_path.name}.{secrets.token_hex(8)}.tmp")
        temporary.write_text(
            json.dumps(raw, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(index_path)

    def _validate_index(self) -> None:
        """Fail before creating tenant files when the central index is corrupt."""
        index_path = self.root / _TENANTS_FILE
        if not index_path.is_file():
            return
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise TenantRegistrationError("tenant registry is unreadable") from exc
        if not isinstance(raw, Mapping):
            raise TenantRegistrationError("tenant registry must be an object")
        for tenant_id, entry in raw.items():
            if not _SAFE_ID.fullmatch(str(tenant_id)) or not isinstance(entry, Mapping):
                raise TenantRegistrationError("tenant registry contains an invalid entry")

    @staticmethod
    def _write_token_env(tenant_dir: Path, token_env: str, token: str) -> None:
        path = tenant_dir / "tenant.env"
        body = (
            "# Written by HelloAda website provisioning. Kept server-side only.\n"
            f"{token_env}={token}\n"
        )
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        temporary.write_text(body, encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def mark_runtime_mounted(self, tenant_id: str) -> None:
        """Persist that a health-verified Payload runtime is mounted for its connection gate."""
        self._mark_runtime_state(tenant_id, target="runtime", allowed={"pending", "runtime", "ready"})

    def mark_runtime_configured(self, tenant_id: str) -> None:
        """Mark a mounted Payload tenant owner-ready after the connection gate passes."""
        self._mark_runtime_state(tenant_id, target="ready", allowed={"runtime", "ready"})

    def _mark_runtime_state(self, tenant_id: str, *, target: str, allowed: set[str]) -> None:
        with self._lock:
            descriptor = self._registry_lock()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                normalized = str(tenant_id or "").strip().lower()
                if not _SAFE_ID.fullmatch(normalized):
                    raise TenantRegistrationError("website id must be a lowercase slug")
                config_path = self._tenant_dir(normalized) / "config.yaml"
                token_env = tenant_token_env(normalized)
                if not config_path.is_file() or not _read_token_env(config_path.parent / "tenant.env", token_env):
                    raise TenantRegistrationError("configured tenant identity or token is missing")
                try:
                    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                except (OSError, yaml.YAMLError) as exc:
                    raise TenantRegistrationError("configured tenant config is unreadable") from exc
                if not isinstance(raw, Mapping) or raw.get("instance_name") != normalized:
                    raise TenantRegistrationError("configured tenant identity does not match its registry entry")
                site = raw.get("site") if isinstance(raw, Mapping) and isinstance(raw.get("site"), Mapping) else {}
                payload = site.get("payload") if isinstance(site.get("payload"), Mapping) else {}
                if (
                    site.get("adapter") != "payload_gateway"
                    or payload.get("enabled") is not True
                    or payload.get("token_env") != token_env
                ):
                    raise TenantRegistrationError("tenant Payload runtime is not configured")
                state = self._indexed_bootstrap_state(normalized)
                if state == target or (target == "runtime" and state == "ready"):
                    return
                if state not in allowed:
                    raise TenantRegistrationError("tenant has an unsupported bootstrap state")
                self._record_index(
                    self.root,
                    normalized,
                    config_path,
                    token_env,
                    bootstrap_state=target,
                )
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def sync_payload_runtime(
        self,
        tenant_id: str,
        runtime_identity: Mapping[str, Any],
        *,
        website_present: bool,
    ) -> bool:
        """Pin an already verified Worker contract into this tenant's runtime config."""
        normalized = str(tenant_id or "").strip().lower()
        if not _SAFE_ID.fullmatch(normalized):
            raise TenantRegistrationError("website id must be a lowercase slug")
        if not isinstance(website_present, bool):
            raise TenantRegistrationError("verified websitePresent state must be a boolean")
        expected_keys = {
            "adminVersion", "contract", "coreVersion", "schemaRevision",
            "schemaIdentity", "migrationHead",
        }
        if set(runtime_identity) != expected_keys:
            raise TenantRegistrationError("verified Payload runtime identity is incomplete")
        identity = dict(runtime_identity)
        if (
            not isinstance(identity["adminVersion"], str)
            or not re.fullmatch(r"[0-9]+[.][0-9]+[.][0-9]+", identity["adminVersion"])
            or not isinstance(identity["contract"], str)
            or not re.fullmatch(r"helloada-content-v[1-9][0-9]*", identity["contract"])
            or not isinstance(identity["coreVersion"], str)
            or not re.fullmatch(r"[0-9]+[.][0-9]+[.][0-9]+", identity["coreVersion"])
            or isinstance(identity["schemaRevision"], bool)
            or not isinstance(identity["schemaRevision"], int)
            or identity["schemaRevision"] < 1
            or not isinstance(identity["schemaIdentity"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", identity["schemaIdentity"])
            or not isinstance(identity["migrationHead"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", identity["migrationHead"])
        ):
            raise TenantRegistrationError("verified Payload runtime identity is invalid")

        with self._lock:
            descriptor = self._registry_lock()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                self._validate_index()
                tenant_dir = self._tenant_dir(normalized)
                config_path = tenant_dir / "config.yaml"
                indexed_path = self._indexed_config_path(normalized)
                if (
                    not indexed_path
                    or Path(indexed_path).expanduser().resolve() != config_path.resolve()
                    or config_path.is_symlink()
                    or not config_path.is_file()
                ):
                    raise TenantRegistrationError("tenant config path is not registered canonically")
                if self._indexed_bootstrap_state(normalized) not in {"pending", "runtime", "ready"}:
                    raise TenantRegistrationError("tenant runtime is not registered for activation")
                token_env = tenant_token_env(normalized)
                if not _read_token_env(tenant_dir / "tenant.env", token_env):
                    raise TenantRegistrationError("registered website API token is missing")

                try:
                    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                except (OSError, UnicodeError, yaml.YAMLError) as exc:
                    raise TenantRegistrationError("tenant config is unreadable") from exc
                if not isinstance(raw, dict) or raw.get("instance_name") != normalized:
                    raise TenantRegistrationError("tenant config identity does not match its registry entry")
                site = raw.get("site")
                if not isinstance(site, dict) or site.get("adapter") != "payload_gateway":
                    raise TenantRegistrationError("tenant does not use the canonical Payload gateway")
                payload = site.get("payload")
                if (
                    not isinstance(payload, dict)
                    or payload.get("enabled") is not True
                    or payload.get("token_env") != token_env
                ):
                    raise TenantRegistrationError("tenant Payload runtime is not enabled canonically")
                contract = payload.get("contract")
                if not isinstance(contract, Mapping):
                    raise TenantRegistrationError("tenant Payload contract is missing")
                allowed_keys = expected_keys | {
                    "media_fields", "locales", "defaultLocale", "collections", "globals",
                }
                if set(contract) - allowed_keys:
                    raise TenantRegistrationError("tenant Payload contract has unsupported fields")
                for key in ("collections", "globals"):
                    if key in contract and not isinstance(contract[key], Mapping):
                        raise TenantRegistrationError(f"tenant Payload {key} metadata is invalid")

                media_fields = contract.get("media_fields", [])
                if (
                    not isinstance(media_fields, list)
                    or any(not isinstance(item, str) or not item.strip() for item in media_fields)
                    or len(set(media_fields)) != len(media_fields)
                ):
                    raise TenantRegistrationError("tenant Payload media fields are invalid")
                locales = contract.get("locales")
                default_locale = contract.get("defaultLocale")
                if locales is not None or default_locale is not None:
                    if (
                        not isinstance(locales, list)
                        or not locales
                        or any(not isinstance(locale, str) or not re.fullmatch(r"[A-Za-z0-9-]{2,20}", locale) for locale in locales)
                        or len(set(locales)) != len(locales)
                        or default_locale not in locales
                    ):
                        raise TenantRegistrationError("tenant Payload locale configuration is invalid")

                canonical_contract = dict(identity)
                if media_fields:
                    canonical_contract["media_fields"] = list(media_fields)
                if locales is not None:
                    canonical_contract["locales"] = list(locales)
                    canonical_contract["defaultLocale"] = default_locale
                updated = dict(raw)
                updated_site = dict(site)
                updated_site["website_present"] = website_present
                updated_payload = dict(payload)
                updated_payload["contract"] = canonical_contract
                updated_site["payload"] = updated_payload
                updated["site"] = updated_site
                before = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
                after = yaml.safe_dump(updated, sort_keys=False, allow_unicode=True)
                if before == after:
                    return False
                self._replace_config(config_path, updated)
                return True
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    # -- the provisioning call -------------------------------------------

    def register(
        self,
        tenant_id: str,
        *,
        display_name: str = "",
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            descriptor = self._registry_lock()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                return self._register(tenant_id, display_name=display_name, env=env)
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def _register(
        self,
        tenant_id: str,
        *,
        display_name: str = "",
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        self._validate_index()
        normalized = str(tenant_id or "").strip().lower()
        if not _SAFE_ID.fullmatch(normalized):
            raise TenantRegistrationError("website id must be a lowercase slug")
        existing = self.registry.for_tenant_id(normalized)
        if existing is not None:
            indexed_config_path = self._indexed_config_path(normalized)
            if not indexed_config_path:
                raise TenantRegistrationError("website id is already reserved")
            receipt = self._receipt(
                normalized,
                str(existing.config.get("data_dir") or ""),
                config_path=indexed_config_path,
                created=False,
            )
            return receipt

        tenant_dir = self._tenant_dir(normalized)
        config_path = tenant_dir / "config.yaml"
        if config_path.exists():
            try:
                raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                raise TenantRegistrationError("existing tenant config is unreadable") from exc
            if not isinstance(raw, Mapping) or raw.get("instance_name") != normalized:
                raise TenantRegistrationError("existing tenant config belongs to another tenant")
            data_dir = str(raw.get("data_dir") or "")
            token_env = tenant_token_env(normalized)
            token = _read_token_env(tenant_dir / "tenant.env", token_env)
            if not data_dir or not token:
                raise TenantRegistrationError("existing tenant registration is incomplete")
            state = self._indexed_bootstrap_state(normalized)
            if state in {"runtime", "ready"}:
                raise TenantRegistrationError("configured tenant runtime is missing from the registry")
            if state not in {"", "pending"}:
                raise TenantRegistrationError("existing tenant has an unsupported bootstrap state")
            if not state:
                self._record_index(
                    self.root,
                    normalized,
                    config_path,
                    token_env,
                    bootstrap_state="pending",
                )
            return self._receipt(
                normalized,
                data_dir,
                config_path=config_path,
                created=False,
            )

        tenant_dir.mkdir(parents=True, exist_ok=False)
        try:
            tenant_dir.chmod(0o700)
        except OSError:
            pass
        config_path = tenant_dir / "config.yaml"
        data_dir = tenant_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        created = self._write_config(
            config_path,
            _new_site_config(normalized, data_dir, display_name, tenant_dir / "site"),
        )
        memory = Memory(data_dir / "memory.db")
        try:
            schema_version = memory.get_schema_version()
        finally:
            memory.close()

        token = secrets.token_urlsafe(32)
        token_env = tenant_token_env(normalized)
        self._write_token_env(tenant_dir, token_env, token)
        self._record_index(
            self.root,
            normalized,
            config_path,
            token_env,
            bootstrap_state="pending",
        )
        return self._receipt(
            normalized,
            str(data_dir),
            config_path=str(config_path),
            schema_version=schema_version,
            created=created,
        )

    def _indexed_config_path(self, tenant_id: str) -> str:
        index_path = self.root / _TENANTS_FILE
        if not index_path.is_file():
            return ""
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise TenantRegistrationError("tenant registry is unreadable") from exc
        if not isinstance(raw, Mapping):
            raise TenantRegistrationError("tenant registry must be an object")
        entry = raw.get(tenant_id) if isinstance(raw, Mapping) else None
        if isinstance(entry, Mapping) and str(entry.get("config_path") or "").strip():
            return str(entry["config_path"])
        return ""

    def is_registered(self, tenant_id: str) -> bool:
        """Check the durable tenant index, including tenants still bootstrapping."""
        normalized = str(tenant_id or "").strip().lower()
        if not _SAFE_ID.fullmatch(normalized):
            return False
        with self._lock:
            self._validate_index()
            indexed_path = self._indexed_config_path(normalized)
            if not indexed_path:
                return False
            expected_path = (self.root / normalized / "config.yaml").resolve()
            config_path = Path(indexed_path).expanduser().resolve()
            if config_path != expected_path or not config_path.is_file():
                raise TenantRegistrationError("registered website config path is invalid")
            try:
                config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                raise TenantRegistrationError("registered website config is unreadable") from exc
            if not isinstance(config, Mapping) or config.get("instance_name") != normalized:
                raise TenantRegistrationError("registered website identity is invalid")
            return True

    def _indexed_bootstrap_state(self, tenant_id: str) -> str:
        index_path = self.root / _TENANTS_FILE
        if not index_path.is_file():
            return ""
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise TenantRegistrationError("tenant registry is unreadable") from exc
        entry = raw.get(tenant_id) if isinstance(raw, Mapping) else None
        return str(entry.get("bootstrap_state") or "ready") if isinstance(entry, Mapping) else ""

    def _receipt(
        self,
        tenant_id: str,
        data_dir: str,
        *,
        config_path: str | Path | None = None,
        schema_version: int | None = None,
        created: bool = True,
    ) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "config_path": str(config_path) if config_path else "",
            "data_dir": str(data_dir),
            "api_token_env": tenant_token_env(tenant_id),
            "schema_version": int(schema_version or SCHEMA_VERSION),
            "status": "registered",
            "created": bool(created),
        }


def _new_site_config(
    tenant_id: str,
    data_dir: Path,
    display_name: str,
    site_dir: Path,
) -> dict[str, Any]:
    """Override block for a brand-new website tenant (merged with package defaults)."""
    return {
        "instance_name": str(tenant_id),
        "data_dir": str(data_dir),
        "display_name": str(display_name or tenant_id)[:200],
        "intake": {
            "enabled": True,
            "database_only": False,
            "research": {"enabled": False},
        },
        "site": {
            "adapter": "payload_gateway",
            "repository": "",
            "clone_path": str(site_dir),
            "branch": "main",
            "preview_branch": "",
            "payload": {"enabled": False},
            "website_present": False,
        },
        "editorial": {"enabled": True},
        "design_engine": _new_design_overrides(),
        "builder": _new_builder_overrides(),
        "publish_mode": "ask_first",
    }


def _new_design_overrides() -> dict[str, Any]:
    return {
        "enabled": True,
        "build_profile": "next_react",
        "orchestration": "creative",
        "production_candidate": True,
        "quality": {
            "browser": False,
            "accessibility": True,
            "visual_critic": False,
        },
    }


def _new_builder_overrides() -> dict[str, Any]:
    """Give creative direction enough completion budget for its typed handoff."""
    return {
        "enabled": True,
        "output_tokens": 32768,
    }


def _read_token_env(path: Path, expected_name: str) -> str:
    if not path.is_file():
        return ""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            name, value = line.split("=", 1)
            if name.strip() == expected_name and value.strip():
                return value.strip()
    except (OSError, UnicodeError):
        pass
    return ""


__all__ = [
    "WORKER_SITE_AGENT_TOKEN_ENV",
    "TenantRegistrationError",
    "TenantRegistrationService",
    "load_provisioned_tenants",
    "provisioned_root",
    "tenant_token_env",
]
