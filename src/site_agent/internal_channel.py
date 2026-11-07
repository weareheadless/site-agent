"""Loopback channel from the API to the agent's tool process.

A chat turn runs opencode, which starts the workspace tools as a child MCP
process. That child has no tenant services: no preview builder, no deployment
queue, no scheduler. A tool that owns durable work must run where those
services live, which is the API.

The API mints one token per process, passes it to the tool process with this
channel's address, and accepts the call only from loopback. Nothing here is
reachable through the public ingress, which proxies only ``/v1/``.

This is a deferred structural fix, not the design. The split it bridges — a
read-only chat agent that starts a second agent through a tool call — is the
real fault. One agent owning the worktree, with the turn ending by handing its
commit to the preview, removes this channel.
"""

from __future__ import annotations

import secrets

_TOKEN = secrets.token_urlsafe(32)
_URL = ""


def configure(*, host: str, port: int) -> None:
    """Record the address the API actually listens on for its own children."""
    global _URL
    target = "127.0.0.1" if str(host).strip() in {"", "0.0.0.0", "::", "[::]"} else str(host).strip()
    _URL = f"http://{target}:{int(port)}"


def token() -> str:
    return _TOKEN


def url() -> str:
    return _URL


def environment() -> dict[str, str]:
    """The variables the tool process needs to reach this API."""
    values = {"SITE_AGENT_INTERNAL_TOKEN": _TOKEN}
    if _URL:
        values["SITE_AGENT_INTERNAL_URL"] = _URL
    return values
