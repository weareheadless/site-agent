from __future__ import annotations

import copy
import os
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

_SECRET_MARKERS = ("key", "token", "password", "secret")


class ConfigError(ValueError):
    """A configuration file or value cannot be used safely."""


def _defaults_path() -> Path:
    return Path(files("site_agent").joinpath("defaults.yaml"))


def instance_path(env: dict[str, str] | None = None) -> Path | None:
    env = os.environ if env is None else env
    raw = env.get("SITE_AGENT_CONFIG", "")
    if raw:
        return Path(raw)
    local = Path.cwd() / "config.yaml"
    return local if local.exists() else None


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load(config_path: str | Path | None = None, env: dict[str, str] | None = None):
    env = os.environ if env is None else env
    defaults = yaml.safe_load(_defaults_path().read_text()) or {}
    if config_path is not None:
        path = Path(config_path)
        if not path.is_file():
            raise ConfigError(f"configuration file not found: {path}")
    else:
        path = instance_path(env)
        if env.get("SITE_AGENT_CONFIG") and (path is None or not path.is_file()):
            raise ConfigError(f"configuration file not found: {path}")
    sources = [Path("<package>/defaults.yaml"), path] if path else [Path("<package>/defaults.yaml")]
    override = (yaml.safe_load(path.read_text()) or {}) if path else {}
    if not isinstance(override, dict):
        raise ConfigError(f"configuration root must be a mapping: {path}")
    return deep_merge(defaults, override), sources


def resolve_secret(
    config: dict[str, Any],
    name: str,
    env: dict[str, str] | None = None,
) -> str:
    """Resolve an instance secret without coupling core code to an adapter."""
    env = os.environ if env is None else env
    var = str((config.get("env") or {}).get(name, ""))
    return env.get(var, "") if var else ""


def resolve_env(config: dict[str, Any], env: dict[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if env is None else env
    mapping = config.get("env") or {}
    resolved = {}
    for name, var in mapping.items():
        value = env.get(str(var), "")
        resolved[name] = {"var": str(var), "set": bool(value)}
    return resolved


def data_dir(config: dict[str, Any], env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    raw = env.get("SITE_AGENT_DATA", "")
    if raw:
        return Path(raw)
    return Path(str(config.get("data_dir", "data")))


def mask_secrets(config: dict[str, Any]) -> dict[str, Any]:
    masked = copy.deepcopy(config)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and any(m in key.lower() for m in _SECRET_MARKERS) and value:
                    node[key] = "***"
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(masked)
    masked.pop("env", None)
    return masked
