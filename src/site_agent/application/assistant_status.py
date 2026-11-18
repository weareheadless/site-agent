"""Read the visitor-assistant state of one tenant for the owner's agent.

Nothing here provisions, releases or spends. It answers what the owner actually
asks: is there an assistant, what is it told to do, is it reachable on the live
site, and what is its provider ceiling and usage. The reachability probe uses an
empty request on purpose: the route validates the declaration, the key and the
rate limiter before it parses the body, so a 400 proves the whole path is
configured without calling the model.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping
from urllib import error, request

from ..senses import openrouter

DECLARATION_PATH = "src/site/assistant.json"
ASSISTANT_ROUTE = "/api/assistant"
PROBE_TIMEOUT_SECONDS = 8.0
# Cloudflare refuses a default library user agent with 403 on this path, which
# would read as "not configured" for a site that is configured.
PROBE_USER_AGENT = "helloada-site-agent/1.0 (+https://helloada.app)"


class AssistantStatusError(RuntimeError):
    """The assistant state could not be read without guessing."""


def parse_declaration(text: str | None) -> dict[str, Any]:
    """Validate one tenant declaration exactly as the release generator does."""
    if text is None:
        return {"declared": False}
    try:
        value = json.loads(text)
    except ValueError as exc:
        return {"declared": False, "invalid": f"not valid JSON: {exc}"}
    if not isinstance(value, dict):
        return {"declared": False, "invalid": "the declaration is not an object"}
    purpose = str(value.get("purpose") or "").strip()
    model = str(value.get("model") or "").strip()
    sources = value.get("sources")
    if not purpose:
        return {"declared": False, "invalid": "no purpose"}
    if not model:
        return {"declared": False, "invalid": "no model"}
    if sources not in ("site", "none"):
        return {"declared": False, "invalid": 'sources must be "site" or "none"'}
    return {
        "declared": True,
        "purpose": purpose,
        "sources": sources,
        "model": model,
        "groundedInSiteContent": sources == "site",
    }


def read_declaration(clone_path: str | Path | None) -> str | None:
    """The tenant's declaration as the checkout holds it, or None when absent.

    The workspace MCP process has no repository adapter, so this reads the
    persistent checkout directly instead of pretending a missing reader means a
    missing declaration.
    """
    raw = str(clone_path or "").strip()
    if not raw:
        raise AssistantStatusError("this tenant has no checkout to read the declaration from")
    root = Path(raw).expanduser().resolve()
    if not (root / "src").is_dir():
        raise AssistantStatusError("the tenant checkout is not available to this process")
    path = (root / DECLARATION_PATH).resolve()
    if root not in path.parents:
        raise AssistantStatusError("the declaration path escapes the tenant checkout")
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def worker_url(config: Mapping[str, Any]) -> str:
    site = config.get("site") if isinstance(config.get("site"), Mapping) else {}
    payload = site.get("payload") if isinstance(site.get("payload"), Mapping) else {}
    for candidate in (payload.get("url"), site.get("url"), config.get("public_url")):
        value = str(candidate or "").strip().rstrip("/")
        if value.startswith("http://") or value.startswith("https://"):
            return value
    raise AssistantStatusError("this tenant has no registered public URL to probe")


def probe(origin: str, transport: Any = None) -> dict[str, Any]:
    """Ask the live site whether the assistant path is configured, without spending."""
    body = json.dumps({"messages": []}).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "accept": "application/json",
        "user-agent": PROBE_USER_AGENT,
    }
    url = f"{origin}{ASSISTANT_ROUTE}"
    send = transport or _urllib_post
    try:
        status, _payload = send(url, headers, body)
    except Exception as exc:  # noqa: BLE001 - reported, never treated as healthy
        return {"reachable": False, "detail": f"the site did not answer: {type(exc).__name__}"}
    if status == 400:
        return {"reachable": True, "configured": True, "detail": "declaration, key and limiter are in place"}
    if status == 404:
        return {"reachable": True, "configured": False, "detail": "this build has no assistant declaration"}
    if status == 503:
        return {"reachable": True, "configured": False, "detail": "the assistant is not fully configured on the live site"}
    if status == 429:
        return {"reachable": True, "configured": True, "detail": "configured, and currently rate limiting this address"}
    return {"reachable": True, "configured": None, "detail": f"the site answered {status}"}


def _urllib_post(url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
    call = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(call, timeout=PROBE_TIMEOUT_SECONDS) as response:  # noqa: S310 - registered tenant URL
            return int(response.status), response.read()
    except error.HTTPError as exc:
        return int(exc.code), exc.read()


def key_state(config: Mapping[str, Any], env: Mapping[str, str], *, transport: Any = None) -> dict[str, Any]:
    """The provider key's own ceiling and usage, or why it cannot be read."""
    from ..credentials import credential_environment, openrouter_api_token

    tenant_id = str(config.get("instance_name") or "").strip().lower()
    if not tenant_id:
        return {"available": False, "detail": "this workspace has no tenant identity"}
    token = openrouter_api_token(config, credential_environment(config, env))
    if not token:
        return {"available": False, "detail": "the host has no provider management credential"}
    name = f"site-agent:{tenant_id}"
    try:
        keys = openrouter.list_keys(token, transport=transport)
    except openrouter.OpenRouterError as exc:
        return {"available": False, "detail": str(exc)[:200]}
    matches = [entry for entry in keys if str(entry.get("name") or "") == name]
    if not matches:
        return {"available": True, "present": False, "name": name,
                "detail": "no spend-limited key exists for this tenant yet"}
    if len(matches) > 1:
        return {"available": True, "present": True, "name": name, "ambiguous": len(matches),
                "detail": f"{len(matches)} provider keys share this tenant's name; reconcile them"}
    entry = matches[0]
    return {
        "available": True,
        "present": True,
        "name": name,
        "limitUsd": entry.get("limit"),
        "limitReset": entry.get("limit_reset"),
        "usageUsd": entry.get("usage"),
        "disabled": bool(entry.get("disabled")),
    }


def read_assistant_state(
    config: Mapping[str, Any],
    env: Mapping[str, str],
    declaration_text: str | None,
    *,
    provider_transport: Any = None,
    probe_transport: Any = None,
) -> dict[str, Any]:
    """Everything an owner question about the assistant needs, in one answer."""
    state: dict[str, Any] = {
        "declaration": parse_declaration(declaration_text),
        "declarationPath": DECLARATION_PATH,
        "key": key_state(config, env, transport=provider_transport),
        # The route is served by the built site, not by the repository checkout:
        # the shared runtime is overlaid at release and preview build time. State
        # the contract in full so a widget can be written without the file.
        "route": {
            "method": "POST",
            "path": ASSISTANT_ROUTE,
            "body": {"messages": [{"role": "user", "content": "..."}]},
            "response": "text/event-stream of OpenRouter chat completion chunks",
            "headers": {
                "x-assistant-mode": "bit (the site's persona answered) or hold (the fixed danger line answered)",
                "x-assistant-fixed": "danger, on a hold turn only",
            },
            "inRepository": False,
            "clientModule": "src/lib/assistant-client.ts",
            "clientUsage": "import { streamAssistant } from '@/lib/assistant-client'",
            "note": ("present in a built preview and in production; absent from the tenant checkout. "
                     "The client module arrives with the same overlay, so a widget imports it rather "
                     "than re-implementing the stream."),
        },
    }
    try:
        state["live"] = probe(worker_url(config), transport=probe_transport)
    except AssistantStatusError as exc:
        state["live"] = {"reachable": False, "detail": str(exc)}
    return state


def plan_key_change(config: Mapping[str, Any], env: Mapping[str, str], *, transport: Any = None) -> dict[str, Any]:
    """What provisioning would do for this tenant. Read-only by construction."""
    from ..credentials import credential_environment, openrouter_api_token

    from . import assistant_key

    tenant_id = str(config.get("instance_name") or "").strip().lower()
    if not tenant_id:
        return {"action": "unavailable", "detail": "this workspace has no tenant identity"}
    data_dir = Path(str(config.get("data_dir") or "")).expanduser()
    env_path = data_dir.parent / "tenant.env" if str(data_dir) else Path("")
    if not env_path.is_file():
        return {
            "action": "unavailable",
            "detail": "the registered tenant environment is not readable from this workspace",
        }
    token = openrouter_api_token(config, credential_environment(config, env))
    if not token:
        return {"action": "unavailable", "detail": "the host has no provider management credential"}
    try:
        return assistant_key.plan(
            tenant_id,
            env_path,
            limit_usd=assistant_key.DEFAULT_LIMIT_USD,
            token=token,
            token_env=_token_env(env_path),
            transport=transport,
        )
    except assistant_key.AssistantKeyError as exc:
        return {"action": "unavailable", "detail": str(exc)[:200]}
    except openrouter.OpenRouterError as exc:
        return {"action": "unavailable", "detail": str(exc)[:200]}


def _token_env(env_path: Path) -> str:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        name = line.split("=", 1)[0].strip()
        if name.startswith("PROVISIONED_") and name.endswith("_TOKEN"):
            return name
    return ""
