"""Server-only, local registration of a HelloAda website tenant.

Registering a website in HelloAda creates a real site-agent tenant on the local
filesystem: a tenant config, a dedicated memory database, a runtime api token,
and a durable entry in the provisioned-tenant registry.  The tenant is then
built and started through the exact same path used for host-declared tenants, so
a provisioned website behaves identically to a configured one.

This module intentionally stops before provider mutations. The companion
``application.bootstrap`` saga owns the separately retryable GitHub/Cloudflare/
Payload bootstrap after this local identity and token boundary exists.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from ..config import deep_merge
from ..core.memory import SCHEMA_VERSION, Memory
from ..hands.design_experiment import DesignExperimentError, initialize_neutral_repository

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
    try:
        root = provisioned_root(config)
    except TenantRegistrationError:
        return {}, {}
    index_path = root / _TENANTS_FILE
    if not index_path.is_file():
        return {}, {}
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}, {}
    declared: dict[str, Any] = {}
    extra_env: dict[str, str] = {}
    if not isinstance(raw, Mapping):
        return {}, {}
    configured_section = config.get("workspace_api") or {}
    configured_tenants = configured_section.get("tenants") if isinstance(configured_section, Mapping) else {}
    configured_ids = {
        str(value or "").strip().lower()
        for value in (configured_tenants.keys() if isinstance(configured_tenants, Mapping) else ())
    }
    for tenant_id, entry in raw.items():
        tenant_id = str(tenant_id or "").strip().lower()
        if not _SAFE_ID.fullmatch(tenant_id) or not isinstance(entry, Mapping):
            continue
        if tenant_id in configured_ids:
            # A host-declared tenant owns its id; a persisted website must not
            # silently shadow it during a restart.
            continue
        config_path = Path(str(entry.get("config_path") or "")).expanduser().resolve()
        token_env = str(entry.get("api_token_env") or tenant_token_env(tenant_id)).strip()
        tenant_dir = (root / tenant_id).resolve()
        env_path = tenant_dir / "tenant.env"
        if (
            not config_path.is_file()
            or root.resolve() not in config_path.parents
            or config_path.name != "config.yaml"
            or tenant_dir != config_path.parent
            or not _SAFE_ENV.fullmatch(token_env)
        ):
            continue
        token = _read_token_env(env_path, token_env)
        if token:
            extra_env[token_env] = token
        declared[tenant_id] = {"config_path": str(config_path), "api_token_env": token_env}
    return declared, extra_env


class TenantRegistrationService:
    """Provision one tenant workspace directory and register it in the API."""

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
    def _ensure_existing_neutral_scaffold(path: Path) -> bool:
        """Upgrade an older local registration before returning its idempotent receipt."""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise TenantRegistrationError("existing tenant config is unreadable") from exc
        if not isinstance(raw, Mapping):
            raise TenantRegistrationError("existing tenant config must be an object")
        site = raw.get("site") if isinstance(raw.get("site"), Mapping) else {}
        if (
            str(site.get("adapter") or "").strip() != "neutral_scaffold"
            or bool(site.get("website_present"))
            or str(site.get("clone_path") or "").strip()
        ):
            return False

        site_dir = path.parent / "site"
        try:
            initialize_neutral_repository(site_dir)
        except (DesignExperimentError, OSError) as exc:
            raise TenantRegistrationError(
                f"tenant source scaffold could not be created: {str(exc)[:300]}"
            ) from exc

        upgraded = dict(raw)
        upgraded["site"] = {
            **dict(site),
            **_neutral_site_overrides(site_dir),
            "website_present": False,
        }
        upgraded["design_engine"] = deep_merge(
            dict(raw.get("design_engine") or {})
            if isinstance(raw.get("design_engine"), Mapping)
            else {},
            _neutral_design_overrides(),
        )
        upgraded["builder"] = deep_merge(
            dict(raw.get("builder") or {})
            if isinstance(raw.get("builder"), Mapping)
            else {},
            _neutral_builder_overrides(),
        )
        TenantRegistrationService._replace_config(path, upgraded)
        return True

    @staticmethod
    def _record_index(root: Path, tenant_id: str, config_path: Path, token_env: str) -> None:
        index_path = root / _TENANTS_FILE
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
        except (OSError, ValueError, UnicodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        raw[tenant_id] = {"config_path": str(config_path), "api_token_env": token_env}
        temporary = index_path.with_name(f"{index_path.name}.{secrets.token_hex(8)}.tmp")
        temporary.write_text(
            json.dumps(raw, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(index_path)

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

    # -- the provisioning call -------------------------------------------

    def register(
        self,
        tenant_id: str,
        *,
        display_name: str = "",
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            return self._register(tenant_id, display_name=display_name, env=env)

    def _register(
        self,
        tenant_id: str,
        *,
        display_name: str = "",
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        normalized = str(tenant_id or "").strip().lower()
        if not _SAFE_ID.fullmatch(normalized):
            raise TenantRegistrationError("website id must be a lowercase slug")
        existing = self.registry.for_tenant_id(normalized)
        if existing is not None:
            indexed_config_path = self._indexed_config_path(normalized)
            if not indexed_config_path:
                raise TenantRegistrationError("website id is already reserved")
            # Older registrations created only the config/database. Upgrade
            # those local no-site tenants before returning the idempotent
            # receipt; the API process is restarted by the host after a config
            # migration so the new runtime graph is loaded.
            scaffold_upgraded = self._ensure_existing_neutral_scaffold(Path(indexed_config_path))
            # Idempotent: the tenant is already registered in this process.
            receipt = self._receipt(
                normalized,
                str(existing.config.get("data_dir") or ""),
                config_path=indexed_config_path,
                created=False,
            )
            if scaffold_upgraded:
                receipt["scaffold_upgraded"] = True
            return receipt

        tenant_dir = self._tenant_dir(normalized)
        tenant_dir.mkdir(parents=True, exist_ok=True)
        try:
            tenant_dir.chmod(0o700)
        except OSError:
            pass
        config_path = tenant_dir / "config.yaml"
        data_dir = tenant_dir / "data"
        site_dir = tenant_dir / "site"
        data_dir.mkdir(parents=True, exist_ok=True)

        try:
            initialize_neutral_repository(site_dir)
        except (DesignExperimentError, OSError) as exc:
            raise TenantRegistrationError(
                f"tenant source scaffold could not be created: {str(exc)[:300]}"
            ) from exc

        created = self._write_config(
            config_path,
            _new_site_config(normalized, data_dir, display_name, site_dir),
        )
        memory = Memory(data_dir / "memory.db")
        try:
            schema_version = memory.get_schema_version()
        finally:
            memory.close()

        token = secrets.token_urlsafe(32)
        token_env = tenant_token_env(normalized)
        self._write_token_env(tenant_dir, token_env, token)
        self._record_index(self.root, normalized, config_path, token_env)

        tenant_env = dict(self.env)
        if env:
            tenant_env.update(env)
        try:
            self.registry.register_tenant(
                normalized,
                str(config_path),
                api_token=token,
                api_token_env=token_env,
                env=tenant_env,
            )
        except TenantRegistrationError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep provider/config details at this boundary
            raise TenantRegistrationError(
                f"tenant runtime could not be registered: {str(exc)[:300]}"
            ) from exc
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
        except (OSError, ValueError, UnicodeError):
            return ""
        entry = raw.get(tenant_id) if isinstance(raw, Mapping) else None
        if isinstance(entry, Mapping) and str(entry.get("config_path") or "").strip():
            return str(entry["config_path"])
        return ""

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
            "status": "ready",
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
            **_neutral_site_overrides(site_dir),
            "website_present": False,
        },
        "blog": {
            "engine": "payload",
            "journal_enabled": True,
        },
        "design_engine": _neutral_design_overrides(),
        "builder": _neutral_builder_overrides(),
        "publish_mode": "ask_first",
    }


def _neutral_site_overrides(site_dir: Path) -> dict[str, Any]:
    from ..hands.site_build import NEXT_REACT_PROFILE

    return {
        "adapter": "neutral_scaffold",
        "repository": "",
        "clone_path": str(site_dir),
        "branch": "main",
        "preview_branch": "",
        "writable_patterns": list(NEXT_REACT_PROFILE.writable_patterns),
    }


def _neutral_design_overrides() -> dict[str, Any]:
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


def _neutral_builder_overrides() -> dict[str, Any]:
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
