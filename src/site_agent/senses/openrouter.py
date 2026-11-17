"""OpenRouter management calls used only by tenant assistant-key provisioning.

The visitor assistant's key is spend-limited on the provider, so the ceiling is
enforced by OpenRouter rather than by our own metering. This module is the only
place that creates or reads those keys, and it never logs a key value.
"""
from __future__ import annotations

import json
from typing import Any, Callable
from urllib import error, request

MANAGEMENT_URL = "https://openrouter.ai/api/v1"
DEFAULT_RESET = "monthly"

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


class OpenRouterError(RuntimeError):
    """The provider refused or could not answer a management call."""


def _urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
    call = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(call, timeout=30) as response:  # noqa: S310 - fixed provider host
            return int(response.status), response.read()
    except error.HTTPError as exc:
        return int(exc.code), exc.read()
    except error.URLError as exc:
        raise OpenRouterError(f"provider management call failed: {exc.reason}") from exc


def _call(
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    transport: Transport | None = None,
) -> dict[str, Any]:
    key = str(token or "").strip()
    if not key:
        raise OpenRouterError("the OpenRouter management credential is not configured")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"authorization": f"Bearer {key}", "accept": "application/json"}
    if body is not None:
        headers["content-type"] = "application/json"
    status, raw = (transport or _urllib_transport)(method, f"{MANAGEMENT_URL}{path}", headers, body)
    if status < 200 or status >= 300:
        detail = raw.decode("utf-8", "replace")[:300]
        raise OpenRouterError(f"provider management call refused ({status}): {detail}")
    try:
        value = json.loads(raw.decode("utf-8") or "{}")
    except ValueError as exc:
        raise OpenRouterError("provider management call returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise OpenRouterError("provider management call returned an unexpected shape")
    return value


def list_keys(token: str, *, transport: Transport | None = None) -> list[dict[str, Any]]:
    """Every provider key visible to the management credential."""
    value = _call(token, "GET", "/keys", transport=transport)
    data = value.get("data")
    if not isinstance(data, list):
        raise OpenRouterError("provider returned no key inventory")
    return [entry for entry in data if isinstance(entry, dict)]


def create_key(
    token: str,
    *,
    name: str,
    limit_usd: float,
    reset: str = DEFAULT_RESET,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """Create one spend-limited key and return the provider's answer verbatim."""
    limit = float(limit_usd)
    if limit <= 0:
        raise ValueError("assistant key limit must be positive")
    value = _call(
        token,
        "POST",
        "/keys",
        {"name": name, "limit": limit, "limit_reset": reset},
        transport=transport,
    )
    created = value.get("key")
    if not isinstance(created, str) or not created.strip():
        raise OpenRouterError("provider did not return the created key")
    return value
