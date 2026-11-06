"""Run one owner-chat turn through opencode.

Ada's chat is an opencode agent with the repository checked out and the
workspace tools available over MCP. The host prepares the checkout, writes the
agent contract, runs the turn, and stores the message opencode produced. It
does not assemble, filter or rewrite that message.

The session id is kept per conversation so a follow-up ("state that again")
continues the same agent turn history instead of starting from nothing.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

CHAT_AGENT = "chat"
INSTRUCTIONS = """# Ada — owner chat

You are Ada, the owner's agent for this website. The owner is a non-technical business owner. You are talking to them in their workspace.

You have this site's repository checked out here, and workspace tools for its content, traffic evidence and Growth backlog. Read the real files before you describe the site; do not describe a website from memory.

## What you can do

You can read anything in the repository, read the site's content, metrics and backlog, prepare content drafts and start a website build when the owner asks for one.

## How to answer

Answer the question that was asked. Be concrete: name the page, the file, the section, the trade-off. If you looked at something, say what you found.

Write in the owner's language and at their level of technical detail. No repository jargon, no infrastructure narration, no tooling commentary.

Your final message is the whole answer. The owner sees only that message, so it must stand alone: if you wrote analysis earlier in this turn, the final message carries it. Never end with a note that refers to text you did not include.
"""


def _chat_home(config: Mapping[str, Any]) -> Path:
    data_dir = Path(str(config.get("data_dir") or "")).expanduser()
    if not str(data_dir) or not data_dir.parent.is_dir():
        raise RuntimeError("the workspace data directory is unavailable for the chat agent")
    home = data_dir / "opencode-chat"
    home.mkdir(parents=True, exist_ok=True)
    for sub in ("config", "data", "cache", "tmp"):
        (home / sub).mkdir(exist_ok=True)
    return home


def _chat_worktree(config: Mapping[str, Any], base_ref: str) -> Path:
    clone = Path(str((config.get("site") or {}).get("clone_path") or "")).expanduser().resolve()
    if not str(clone) or not clone.is_dir():
        raise RuntimeError("the site checkout is unavailable for the chat agent")
    worktree = clone.parent / f"{clone.name}-chat"
    if worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)
    subprocess_run = __import__("subprocess").run
    subprocess_run(["git", "worktree", "prune"], cwd=clone, capture_output=True, text=True, timeout=120)
    result = subprocess_run(
        ["git", "worktree", "add", "--detach", str(worktree), base_ref],
        cwd=clone, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError("the chat checkout could not be prepared: " + (result.stderr or "").strip()[:300])
    return worktree


def _write_agent_files(
    worktree: Path,
    *,
    config: Mapping[str, Any],
    tenant_config_path: str,
    tenant_env_path: str,
    job_id: int,
    model: str,
    key_env: str,
) -> None:
    oc = worktree / ".opencode"
    oc.mkdir(parents=True, exist_ok=True)
    (oc / "ada-instructions.md").write_text(INSTRUCTIONS, encoding="utf-8")
    deny = {"edit": "deny", "bash": "deny", "task": "deny", "external_directory": "deny",
            "webfetch": "deny", "websearch": "deny"}
    allow = {"read": "allow", "glob": "allow", "grep": "allow", "list": "allow"}
    provider, _, bare = model.partition("/")
    base_url = str((config.get("llm") or {}).get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")
    opencode_config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "model": model,
        "instructions": [".opencode/ada-instructions.md"],
        "permission": {**deny, **allow},
        "agent": {CHAT_AGENT: {"description": "Owner conversation for this site",
                               "mode": "primary", "permission": {**deny, **allow}}},
        "provider": {
            provider: {
                "npm": "@ai-sdk/openai-compatible",
                "name": provider,
                "options": {
                    "baseURL": base_url,
                    "apiKey": "{env:" + key_env + "}",
                    "timeout": 600000,
                    "chunkTimeout": 180000,
                },
                "models": {
                    bare: {
                        "name": "Ada's working model",
                        "limit": {"context": 1_048_576, "output": 8192},
                        "options": {"max_tokens": 8192, "reasoning_effort": "low"},
                    }
                },
            }
        },
        "mcp": {
            "workspace": {
                "type": "local",
                "command": [
                    str(Path(__import__("sys").executable)),
                    "-m", "site_agent", "mcp", "workspace",
                    "--config", tenant_config_path,
                    "--env", tenant_env_path,
                    "--job", str(job_id),
                ],
                # Pin the tool process to the exact code this API is running,
                # not to whatever a checkout or a .pth file resolves to.
                "environment": {"PYTHONPATH": str(_package_root())},
                "enabled": True,
                "timeout": {"startup": 120000, "execution": 1800000},
            }
        },
    }
    (worktree / "opencode.json").write_text(json.dumps(opencode_config, indent=2) + "\n", encoding="utf-8")


def _package_root() -> Path:
    import site_agent

    return Path(site_agent.__file__).resolve().parent.parent


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
    """Run one chat turn and return opencode's message unchanged."""
    from . import opencode_runner

    config = dict(context.get("config") or {})
    builder = config.get("builder") or {}
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

    model = str(builder.get("model") or (config.get("llm") or {}).get("model") or "").strip()
    if not model:
        raise RuntimeError("no model is configured for the chat agent")
    key_env = str((config.get("llm") or {}).get("api_key_env") or "OPENROUTER_API_KEY").strip()
    api_key = str((context.get("env") or {}).get("SITE_AGENT_LLM_API_KEY") or "").strip()

    base_ref = opencode_runner._build_base_ref(context.get("memory"), config)
    if progress:
        progress("preparing the site checkout")
    worktree = _chat_worktree(config, base_ref)
    _write_agent_files(
        worktree,
        config=config,
        tenant_config_path=tenant_config_path,
        tenant_env_path=tenant_env_path,
        job_id=job_id,
        model=model,
        key_env=key_env,
    )

    memory = context.get("memory")
    conversation_id = context.get("_delegated_conversation_id")
    session_key = f"chat_session:{conversation_id}" if conversation_id else ""
    session_id = str(memory.kv_get(session_key, "")) if (memory is not None and session_key) else ""
    brief = message if session_id else _history_brief(message, history)
    home = _chat_home(config)

    result = opencode_runner.run_opencode_turn(
        worktree,
        brief,
        config,
        progress=progress,
        session_id=session_id or None,
        agent_name=CHAT_AGENT,
        timeout_seconds=int(builder.get("timeout_seconds", 1800)),
        api_key=api_key,
        env=dict(context.get("env") or {}),
        memory=memory,
        home=home,
        reply_mode="final_message",
    )
    reply = str(result.get("reply") or "").strip()
    if not reply:
        raise RuntimeError("the chat agent returned no message")
    new_session = str(result.get("session_id") or "").strip()
    if memory is not None and session_key and new_session:
        memory.kv_set(session_key, new_session)
    return {"reply": reply, "session_id": new_session, "worktree": str(worktree)}
