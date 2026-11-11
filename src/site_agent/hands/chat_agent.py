"""Run one owner-chat turn through opencode.

Ada's chat is one opencode session per conversation. It reads the repository,
changes it when the owner asks for a change, uses the workspace tools for the
site's Payload content, and answers in its own words. The host prepares the
worktree, installs the same instructions and skills a build uses, and stages
the review draft after the turn. It never assembles, filters or rewrites the
message opencode produced.

The session id is kept per conversation so a follow-up ("state that again")
continues the same agent turn history instead of starting from nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..brain.design_contract import with_design_contract

# Appended to the installed agent instructions. The build instructions already
# carry the repository, design and source-ownership contracts; these are the
# rules that only apply when the turn is a conversation with the owner.
OWNER_TURN_RULES = with_design_contract("""# Owner turn

You are talking to the owner in their workspace, and this same turn owns the repository. When the owner asks for a change, make it here: read the real files, edit them, and leave the work uncommitted. The host validates, commits and prepares the preview after the turn. Never publish, approve, merge or push.

Answer in the owner's language and at their level. Your final message is the whole answer: what you changed, what you checked, and where the preview appears. You cannot open the owner's signed-in preview yourself, so never tell them it needs their session: they are already in it. An unpublished page has no public address yet; its 404 is expected, not a defect. If something failed, say what failed instead of presenting saved content as finished.

The site's editable content lives in Payload where the site reads it from Payload: change that through the workspace tools. Pages, sections, styles and any content the site keeps in its own source are repository files, and you change those here.
""")


def _workspace_tool_config(
    config: Mapping[str, Any],
    *,
    tenant_config_path: str,
    tenant_env_path: str,
    job_id: int,
) -> dict[str, Any]:
    """The tool server the owner turn runs beside its repository access."""
    return {
        "workspace": {
            "type": "local",
            "command": [
                str(Path(__import__("sys").executable)),
                "-m", "site_agent", "mcp", "workspace",
                "--config", tenant_config_path,
                "--env", tenant_env_path,
                "--job", str(job_id),
            ],
            # Pin the tool process to the exact code this API is running, not
            # to whatever a checkout or a .pth file resolves to.
            "environment": {
                "PYTHONPATH": str(_package_root()),
                "SITE_AGENT_MCP_LOG": str(Path(str(config.get("data_dir") or ".")) / "logs" / "chat-tools.log"),
                # The tool process runs with the agent's isolated HOME, so it
                # cannot find the CLI through `~/.opencode/bin` or $PATH. The
                # API resolved it; pass that exact binary down.
                "SITE_AGENT_OPENCODE_BIN": _opencode_bin(config),
            },
            "enabled": True,
            # A build runs inside this turn; the turn must not be cut short.
            "timeout": 2_700_000,
        }
    }


def _package_root() -> Path:
    import site_agent

    return Path(site_agent.__file__).resolve().parent.parent


def _opencode_bin(config: Mapping[str, Any]) -> str:
    """Resolve the CLI in this process, where HOME and PATH are the host's."""
    from . import opencode_runner

    return opencode_runner.opencode_bin(dict(config))


def _history_brief(message: str, history: list[Mapping[str, Any]] | None) -> str:
    if not history:
        return message
    lines = []
    for item in history[-8:]:
        role = "Owner" if str(item.get("role")) == "user" else "Ada"
        lines.append(f"{role}: {str(item.get('content') or '').strip()}")
    return "\n\n".join(lines + [f"Owner: {message}"])


def run_turn(
    context: dict[str, Any],
    job_id: int,
    message: str,
    history: list[Mapping[str, Any]] | None = None,
    progress=None,
) -> dict[str, Any]:
    """Run one owner turn and return opencode's message unchanged."""
    from . import opencode_runner

    config = dict(context.get("config") or {})
    if not opencode_runner.builder_available(config):
        raise RuntimeError("the chat agent is not enabled on this instance")
    tenant_config_path = str(context.get("tenant_config_path") or "").strip()
    if not tenant_config_path:
        raise RuntimeError("the registered tenant configuration path is unavailable")
    tenant_env_path = str(context.get("tenant_env_path") or "").strip()
    if not tenant_env_path:
        candidate = Path(tenant_config_path).with_name("tenant.env")
        if not candidate.is_file():
            raise RuntimeError("the registered tenant environment file is unavailable")
        tenant_env_path = str(candidate)

    memory = context.get("memory")
    conversation_id = context.get("_delegated_conversation_id")
    # The session belongs to the agent home of the turn that created it. A
    # different home cannot resolve an older id, so the key names the design.
    session_key = f"chat_session:owner-turn:{conversation_id}" if conversation_id else ""
    session_id = str(memory.kv_get(session_key, "")) if (memory is not None and session_key) else ""
    brief = message if session_id else _history_brief(message, history)

    result = opencode_runner.run_owner_turn(
        context,
        job_id,
        brief,
        session_id=session_id or None,
        message=message,
        extra_config={"mcp": _workspace_tool_config(
            config,
            tenant_config_path=tenant_config_path,
            tenant_env_path=tenant_env_path,
            job_id=job_id,
        )},
        instructions_suffix=OWNER_TURN_RULES,
        progress=progress,
    )
    reply = str(result.get("reply") or "").strip()
    if not reply:
        raise RuntimeError("the chat agent returned no message")
    new_session = str(result.get("session_id") or "").strip()
    if memory is not None and session_key and new_session:
        memory.kv_set(session_key, new_session)
    return {
        "reply": reply,
        "session_id": new_session,
        "changed": bool(result.get("changed")),
        "merge_draft_id": result.get("merge_draft_id"),
        "preview": result.get("preview"),
    }
