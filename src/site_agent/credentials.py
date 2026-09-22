"""Host-owned credential profiles shared by site tenants.

The site agent must be able to reuse the host's GitHub and Cloudflare
connections without copying secrets into every website configuration or
exposing them to an authoring model.  This module resolves only the execution
environment; callers decide which subprocess is allowed to receive it.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any
from collections.abc import Mapping

import yaml

from .config import load_env_file


_DEFAULT_GITHUB_KEYS = (
    Path("/home/admin/.ssh/github_weareheadless_ed25519"),
    Path("/ATELIER/atelier-github_ed25519"),
)
_SAFE_ENV_NAME = "^[A-Za-z_][A-Za-z0-9_]*$"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def credential_profile_file(config: Mapping[str, Any] | None) -> Path | None:
    """Return the configured non-secret host profile path, if any."""
    credentials = _mapping((config or {}).get("credentials"))
    raw_path = str(credentials.get("profile_file") or "").strip()
    if not raw_path:
        return None
    return Path(raw_path).expanduser().resolve()


def _merge_profiles(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    result = {str(key): value for key, value in base.items()}
    for key, value in override.items():
        name = str(key)
        if isinstance(value, Mapping) and isinstance(result.get(name), Mapping):
            result[name] = {**dict(result[name]), **dict(value)}
        else:
            result[name] = value
    return result


def _profiles(config: Mapping[str, Any] | None) -> Mapping[str, Any]:
    declared = _mapping((config or {}).get("credentials"))
    profile_path = credential_profile_file(config)
    file_profiles: Mapping[str, Any] = {}
    if profile_path is not None:
        try:
            document = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            document = {}
        if isinstance(document, Mapping):
            file_profiles = _mapping(document.get("credentials") or document)
    inline = {
        key: value
        for key, value in declared.items()
        if key != "profile_file"
    }
    return _merge_profiles(file_profiles, inline)


def credential_profile(config: Mapping[str, Any] | None, name: str) -> Mapping[str, Any]:
    """Return one non-secret host credential profile."""
    return _mapping(_profiles(config).get(name))


def _valid_env_name(value: Any, fallback: str) -> str:
    candidate = str(value or fallback).strip()
    import re

    return candidate if re.fullmatch(_SAFE_ENV_NAME, candidate) else fallback


def credential_environment(
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve host credential files with process environment precedence.

    Values already present in ``env`` win over files.  The returned mapping is
    intended for trusted adapters and deployment subprocesses, never for the
    model prompt or an untrusted site workspace.
    """
    values = dict(os.environ if env is None else env)
    profiles = _profiles(config)
    paths: list[str] = []

    root_file = str(profiles.get("env_file") or "").strip()
    if root_file:
        paths.append(root_file)
    for name in ("github", "cloudflare"):
        path = str(credential_profile(config, name).get("env_file") or "").strip()
        if path:
            paths.append(path)

    # Preserve the existing tenant setting while deployments migrate to the
    # shared profile.  A shared profile path wins when both are configured.
    legacy_file = str(_mapping((config or {}).get("source_deployment")).get("cloudflare_env_file") or "").strip()
    if legacy_file:
        paths.append(legacy_file)

    seen: set[str] = set()
    for raw_path in paths:
        path = str(Path(raw_path).expanduser().resolve())
        if path in seen:
            continue
        seen.add(path)
        values = load_env_file(path, values)
    return values


def github_ssh_key_path(
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    """Find the host-owned GitHub deploy key without reading its contents."""
    source = os.environ if env is None else env
    profile = credential_profile(config, "github")
    candidates: list[Path] = []
    for raw in (
        profile.get("ssh_key_path"),
        profile.get("key_path"),
        source.get("SITE_AGENT_GITHUB_SSH_KEY"),
        *_DEFAULT_GITHUB_KEYS,
    ):
        if raw:
            candidates.append(Path(str(raw)).expanduser())
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


def github_ssh_command(
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Return the Git transport command for the shared GitHub identity."""
    source = os.environ if env is None else env
    profile = credential_profile(config, "github")
    configured = str(profile.get("ssh_command") or source.get("GIT_SSH_COMMAND") or "").strip()
    if configured:
        if any(char in configured for char in "\r\n") or len(configured) > 500:
            return ""
        return configured
    key = github_ssh_key_path(config, source)
    return f"ssh -i {shlex.quote(str(key))} -o IdentitiesOnly=yes" if key else ""


def github_remote(value: str, config: Mapping[str, Any] | None, env: Mapping[str, str] | None = None) -> str:
    """Upgrade a GitHub HTTPS remote to SSH when the host key is available."""
    remote = str(value or "").strip()
    if not github_ssh_command(config, env):
        return remote
    if remote.startswith("https://github.com/"):
        return "git@github.com:" + remote.removeprefix("https://github.com/")
    if remote.startswith("http://github.com/"):
        return "git@github.com:" + remote.removeprefix("http://github.com/")
    return remote


def cloudflare_env_names(config: Mapping[str, Any] | None) -> tuple[str, str]:
    profile = credential_profile(config, "cloudflare")
    mapped = _mapping((config or {}).get("env"))
    return (
        _valid_env_name(profile.get("api_token_env") or mapped.get("cloudflare_api_token"), "CLOUDFLARE_API_TOKEN"),
        _valid_env_name(profile.get("account_id_env") or mapped.get("cloudflare_account_id"), "CLOUDFLARE_ACCOUNT_ID"),
    )


def github_api_token_env(config: Mapping[str, Any] | None) -> str:
    """Return the environment variable name for the shared GitHub API token."""
    profile = credential_profile(config, "github")
    mapped = _mapping((config or {}).get("env"))
    return _valid_env_name(profile.get("api_token_env") or mapped.get("github_token"), "GITHUB_TOKEN")


def cloudflare_api_token(config: Mapping[str, Any] | None, env: Mapping[str, str] | None = None) -> str:
    """Resolve the trusted Cloudflare API token from the shared profile."""
    token_name, _ = cloudflare_env_names(config)
    return credential_environment(config, env).get(token_name, "")


def github_api_token(config: Mapping[str, Any] | None, env: Mapping[str, str] | None = None) -> str:
    """Resolve the trusted GitHub API token from the shared profile."""
    return credential_environment(config, env).get(github_api_token_env(config), "")


def credential_status(
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return non-secret readiness information for admin diagnostics."""
    resolved = credential_environment(config, env)
    key = github_ssh_key_path(config, resolved)
    github_token_name = github_api_token_env(config)
    token_name, account_name = cloudflare_env_names(config)
    cloudflare_file = str(credential_profile(config, "cloudflare").get("env_file") or "").strip()
    file_path = Path(cloudflare_file).expanduser() if cloudflare_file else None
    profile_path = credential_profile_file(config)
    return {
        "profile_file": str(profile_path) if profile_path else "",
        "profile_file_available": bool(profile_path and profile_path.is_file()),
        "github": {
            "api_token_env": github_token_name,
            "api_token_configured": bool(resolved.get(github_token_name)),
            "ssh_key_available": key is not None,
            "ssh_key_path": str(key) if key else "",
            "ssh_key_permissions_secure": bool(key and (key.stat().st_mode & 0o077) == 0),
            "transport_configured": bool(github_ssh_command(config, resolved)),
        },
        "cloudflare": {
            "env_file_configured": bool(cloudflare_file),
            "env_file_available": bool(file_path and file_path.is_file()),
            "api_token_env": token_name,
            "api_token_configured": bool(resolved.get(token_name)),
            "account_id_env": account_name,
            "account_id_configured": bool(resolved.get(account_name)),
        },
    }


__all__ = [
    "cloudflare_env_names",
    "cloudflare_api_token",
    "credential_environment",
    "credential_profile_file",
    "credential_profile",
    "credential_status",
    "github_remote",
    "github_api_token",
    "github_api_token_env",
    "github_ssh_command",
    "github_ssh_key_path",
]
