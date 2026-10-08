"""Canonical account-qualified Cloudflare Worker preview origins."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlsplit

from ..credentials import cloudflare_api_token, cloudflare_env_names, credential_environment
from ..hands.cloudflare_resources import CloudflareResourceError, CloudflareResourceProvisioner


class WorkerOriginError(RuntimeError):
    """The registered tenant Worker origin could not be confirmed."""


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def canonical_worker_preview_url(
    config: Mapping[str, object],
    env: Mapping[str, str] | None = None,
) -> str:
    """Resolve the exact account-qualified workers.dev URL from Cloudflare."""
    site = _mapping(config.get("site"))
    deployment = _mapping(site.get("source_deployment"))
    worker = str(deployment.get("worker_name") or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", worker):
        raise WorkerOriginError("The registered Cloudflare Worker identity is invalid.")

    resolved_env = credential_environment(config, env)
    token = cloudflare_api_token(config, resolved_env)
    _token_name, account_name = cloudflare_env_names(config)
    account_id = str(resolved_env.get(account_name) or "").strip()
    if not token or not account_id:
        raise WorkerOriginError("The registered Cloudflare account credentials are unavailable.")

    try:
        resolved = CloudflareResourceProvisioner(account_id, token).workers_dev_url(worker)
    except CloudflareResourceError as exc:
        raise WorkerOriginError("Cloudflare could not confirm the account-qualified Worker origin.") from exc

    parsed = urlsplit(resolved)
    host = str(parsed.hostname or "").lower()
    prefix = f"{worker}."
    account_subdomain = host[len(prefix):-len(".workers.dev")] if host.startswith(prefix) and host.endswith(".workers.dev") else ""
    if (
        parsed.scheme != "https"
        or parsed.port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or not account_subdomain
        or host == f"{worker}.workers.dev"
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", account_subdomain)
    ):
        raise WorkerOriginError("Cloudflare returned an invalid account-qualified Worker origin.")
    return f"https://{host}"


__all__ = ["WorkerOriginError", "canonical_worker_preview_url"]
