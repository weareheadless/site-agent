"""Stdio MCP server exposing this workspace's tools to the owner-chat agent.

opencode starts this process for one chat turn and passes the chat job in the
environment. Every tool call is served by `application.agent_tools`, which
reuses the canonical contract and validators; this module is only transport.

The process is tenant-scoped: it resolves exactly one registered workspace from
its configuration file and refuses anything else.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-11-05"


def _env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


class WorkspaceServer:
    def __init__(self, config_path: Path, env_path: Path, job_id: int) -> None:
        import yaml

        from ..core.memory import Memory
        from ..hands.payload_gateway import PayloadGatewayClient, PayloadMediaService

        self.job_id = job_id
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("workspace configuration is not an object")
        env = _env_file(env_path)
        data_dir = Path(str(config.get("data_dir") or "")).expanduser()
        if not str(data_dir) or not data_dir.is_dir():
            raise ValueError("workspace data directory is unavailable")
        self.memory = Memory(data_dir / "memory.db")
        payload = PayloadGatewayClient.from_config(config, env)
        context: dict[str, Any] = {
            "config": config,
            "memory": self.memory,
            "env": env,
            "payload_gateway": payload,
            "tenant_id": str(config.get("instance_name") or ""),
        }
        if payload is not None:
            context["media_service"] = PayloadMediaService(payload)
        self.context = context

    def tools(self) -> list[dict[str, Any]]:
        from ..application.agent_tools import tool_catalog

        return tool_catalog(self.memory, self.context)

    def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        from ..application.agent_tools import AgentToolError, call_tool

        try:
            return call_tool(self.memory, self.context, self.job_id, name, arguments), False
        except AgentToolError as exc:
            return f"REFUSED: {exc}", True
        except Exception as exc:  # noqa: BLE001 — a tool failure is reported, not fatal
            return f"{type(exc).__name__}: {str(exc)[:400]}", True


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve(server: WorkspaceServer) -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        method = message.get("method")
        message_id = message.get("id")
        if method == "initialize":
            params = message.get("params") or {}
            _write({"jsonrpc": "2.0", "id": message_id, "result": {
                "protocolVersion": str(params.get("protocolVersion") or PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "site-agent-workspace", "version": "1.0.0"},
            }})
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif method == "tools/list":
            _write({"jsonrpc": "2.0", "id": message_id, "result": {"tools": server.tools()}})
        elif method == "tools/call":
            params = message.get("params") or {}
            text, failed = server.call(str(params.get("name") or ""), dict(params.get("arguments") or {}))
            _write({"jsonrpc": "2.0", "id": message_id, "result": {
                "content": [{"type": "text", "text": text}], "isError": failed,
            }})
        elif message_id is not None:
            _write({"jsonrpc": "2.0", "id": message_id,
                    "error": {"code": -32601, "message": f"unknown method {method}"}})
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="site-agent mcp workspace")
    parser.add_argument("--config", required=True, help="registered tenant configuration")
    parser.add_argument("--env", required=True, help="registered tenant environment file")
    parser.add_argument("--job", required=True, type=int, help="the chat job this turn belongs to")
    args = parser.parse_args(argv)
    server = WorkspaceServer(Path(args.config), Path(args.env), args.job)
    return serve(server)
