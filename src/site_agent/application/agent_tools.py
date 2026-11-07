"""Workspace tools for the owner-chat agent.

Ada's chat runs in opencode, which reads the repository natively. What it
cannot do is read or change the site's canonical content, traffic evidence or
Growth backlog, or start a build. Those are this module: the same tool
definitions and the same validators the legacy chat loop used, exposed over
MCP instead of being driven by a host-side loop.

Nothing here re-implements a tool. `_tools_spec` publishes the contract and
`_execute_tool` enforces it, so the plan freeze, the Payload receipt checks and
the source ownership rules keep exactly one owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..brain.turn_state import TurnState

# opencode reads and searches the checkout itself; exposing these would only
# give it a second, weaker path to the same files.
NATIVE_TOOLS = frozenset({"read_file", "list_files"})

# The legacy design handoff needs the in-process design service and a host-side
# follow-up after the turn; the Next build path supersedes it for these sites.
# `spawn_build` starts a second agent in this short-lived child process; the
# owner turn already owns the worktree and changes it directly, so the tool is
# only kept for the legacy in-process engine, which runs inside the API.
UNAVAILABLE_TOOLS = frozenset({"design_request", "spawn_build"})


class AgentToolError(ValueError):
    """A tool call that cannot be served for this workspace or job."""


def _editor():
    from ..brain import editor

    return editor


def _authoring_contract(context: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = context.get("payload_gateway")
    require = getattr(payload, "require_authoring_contract", None)
    if not callable(require):
        return None
    try:
        contract = require()
    except Exception:  # noqa: BLE001 — a missing contract hides content tools, not chat
        return None
    return contract if isinstance(contract, dict) else None


def _prepared_context(memory: Any, context: Mapping[str, Any], job_id: int | None) -> TurnState:
    # A document read and the write that depends on it are separate MCP tool
    # calls. TurnState copies the base mapping shallowly, so one shared dict lets
    # the exact read survive to the next call in the same turn.
    if isinstance(context, dict):
        context.setdefault("_payload_read_documents", {})
    state = TurnState(memory, job_id, context)
    contract = _authoring_contract(state)
    if contract is not None:
        state["_authoring_contract"] = contract
    return state


def tool_catalog(memory: Any, context: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The MCP tool list for this workspace, in its own contract."""
    state = _prepared_context(memory, context, None)
    specs = _editor()._tools_spec(
        state, design_intent=False, authoring_contract=state.get("_authoring_contract"),
    )
    tools: list[dict[str, Any]] = []
    for spec in specs:
        function = spec.get("function") if isinstance(spec, Mapping) else None
        if not isinstance(function, Mapping):
            continue
        name = str(function.get("name") or "")
        if not name or name in NATIVE_TOOLS or name in UNAVAILABLE_TOOLS:
            continue
        tools.append({
            "name": name,
            "description": str(function.get("description") or ""),
            "inputSchema": function.get("parameters") or {"type": "object", "properties": {}},
        })
    return tools


def _require_job(memory: Any, job_id: Any) -> int:
    if not isinstance(job_id, int) or job_id <= 0:
        raise AgentToolError("a chat job id is required for workspace tools")
    if memory.get_chat_job(job_id) is None:
        raise AgentToolError("the chat job is not known to this workspace")
    return job_id


def call_tool(
    memory: Any,
    context: Mapping[str, Any],
    job_id: Any,
    name: str,
    arguments: Mapping[str, Any] | None,
) -> str:
    """Run one workspace tool for this workspace and chat job."""
    job = _require_job(memory, job_id)
    available = {tool["name"] for tool in tool_catalog(memory, context)}
    if name not in available:
        raise AgentToolError(f"unknown workspace tool: {name}")
    state = _prepared_context(memory, context, job)
    result = _editor()._execute_tool(state, None, name, dict(arguments or {}), lambda _: None)
    return result if isinstance(result, str) else str(result)


def turn_summary(memory: Any, context: Mapping[str, Any], job_id: Any) -> dict[str, Any]:
    """What the finished turn produced, for the job record."""
    state = _prepared_context(memory, context, job_id)
    return {
        "completed_payload_effects": state.get("_completed_payload_effects") or [],
        "source_build_completed": bool(state.get("_source_build_completed")),
        "merge_draft_id": state.get("_last_merge_draft_id"),
        "preview": state.get("_last_preview"),
        "change": state.get("_last_change"),
        "changed": state.get("_last_changed"),
        "plan": state.get("_website_change_plan") or None,
    }
