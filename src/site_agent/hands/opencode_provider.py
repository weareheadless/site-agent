"""Focused OpenCode specialist execution for the design coordinator.

This module intentionally does not contain design policy or lifecycle
transitions.  It describes the narrow provider boundary: choose a named role,
write its disposable agent definition, execute one bounded turn, and return
the provider result for application-level contract validation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


class SpecialistProviderError(RuntimeError):
    """A specialist invocation could not produce a provider result."""


@dataclass(frozen=True)
class SpecialistRole:
    name: str
    description: str
    mode: str
    write_scope: str
    skill_names: tuple[str, ...] = ()


SPECIALIST_ROLES: dict[str, SpecialistRole] = {
    "copywriter": SpecialistRole(
        "copywriter",
        "Writes a typed copy deck from verified facts and conversion constraints.",
        "subagent",
        "none",
        ("design-core.md",),
    ),
    "concept-designer": SpecialistRole(
        "concept-designer",
        "Develops one subject-specific visual concept from approved evidence.",
        "subagent",
        "none",
        ("design-core.md", "frontend-design.md", "high-end-visual-design.md"),
    ),
    "creative-director": SpecialistRole(
        "creative-director",
        "Selects a concept and reviews its rendered realization against the locked direction.",
        "subagent",
        "none",
        ("design-core.md", "high-end-visual-design.md", "web-design-guidelines.md"),
    ),
    "site-implementer": SpecialistRole(
        "site-implementer",
        "Implements the locked design plan in the isolated source worktree.",
        "primary",
        "implementation",
        ("frontend-design.md", "web-design-guidelines.md"),
    ),
    "motion-designer": SpecialistRole(
        "motion-designer",
        "Adds the locked purposeful motion behavior and reduced-motion implementation.",
        "primary",
        "motion",
        ("gsap-core.md", "gsap-react.md", "gsap-performance.md"),
    ),
    "experience-critic": SpecialistRole(
        "experience-critic",
        "Reviews rendered evidence for comprehension, hierarchy, conversion, and usability.",
        "subagent",
        "none",
        ("web-design-guidelines.md",),
    ),
    "technical-critic": SpecialistRole(
        "technical-critic",
        "Reviews rendered evidence and implementation deviations for technical risk.",
        "subagent",
        "none",
        ("web-design-guidelines.md", "gsap-performance.md"),
    ),
    "repair-implementer": SpecialistRole(
        "repair-implementer",
        "Applies only the frozen repair findings to a child candidate.",
        "primary",
        "repair",
        ("frontend-design.md", "web-design-guidelines.md"),
    ),
}


def get_specialist_role(name: str) -> SpecialistRole:
    key = str(name or "").strip().lower()
    try:
        return SPECIALIST_ROLES[key]
    except KeyError as exc:
        raise SpecialistProviderError(f"unknown specialist role: {key or '<empty>'}") from exc


def _agent_definition(role: SpecialistRole) -> str:
    task_rule = (
        "Never invoke the task tool or delegate to another agent."
        if role.mode == "subagent"
        else "Never invoke the task tool or delegate to another agent; the host controls all workflow transitions."
    )
    write_rule = {
        "none": "Do not edit, write, patch, delete, or install files.",
        "implementation": "You may edit only the host-provided implementation worktree; do not mutate Git state.",
        "motion": "You may edit only the host-provided motion integration scope; do not mutate Git state.",
        "repair": "You may edit only paths named by the host repair brief; do not mutate Git state.",
    }[role.write_scope]
    return (
        "---\n"
        f"description: {role.description}\n"
        f"mode: {role.mode}\n"
        "permission:\n"
        "  task: deny\n"
        + ("  edit: deny\n  write: deny\n  bash: deny\n" if role.write_scope == "none" else "")
        + "---\n\n"
        f"You are the {role.name} specialist in a finite design workflow.\n"
        "The host supplies the phase inputs and validates your structured output.\n"
        f"{write_rule}\n"
        f"{task_rule}\n"
        "Do not approve, publish, contact external services, invent business facts, or change the design direction outside the host contract.\n"
        "Return only the requested structured phase result; do not return a plan for another agent.\n"
    )


def write_specialist_agents(workspace: str | Path, roles: Sequence[str] | None = None) -> tuple[str, ...]:
    """Write role definitions into a disposable OpenCode workspace."""
    root = Path(workspace).expanduser().resolve()
    agent_dir = root / ".opencode" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    selected = tuple(roles or SPECIALIST_ROLES)
    written: list[str] = []
    for name in selected:
        role = get_specialist_role(name)
        path = agent_dir / f"{role.name}.md"
        path.write_text(_agent_definition(role), encoding="utf-8")
        written.append(str(path.relative_to(root)).replace("\\", "/"))
    return tuple(written)


def structured_output_prompt(instruction: str, contract_name: str) -> str:
    """Append a strict output boundary without embedding conversational examples."""
    text = str(instruction or "").strip()
    if not text:
        raise SpecialistProviderError("specialist instruction must not be empty")
    contract = str(contract_name or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,79}", contract):
        raise SpecialistProviderError("specialist contract name is invalid")
    return (
        f"{text}\n\nOUTPUT CONTRACT: {contract}. Return exactly one JSON object with the "
        "contract fields, no Markdown fences, no commentary, and no second attempt."
    )


def decode_structured_output(result: Mapping[str, Any]) -> dict[str, Any]:
    """Decode the one JSON object returned by a specialist."""
    direct = result.get("structured")
    if isinstance(direct, dict):
        return direct
    text = str(result.get("reply") or "").strip()
    if not text:
        raw_tail = result.get("raw_tail") or []
        text = "\n".join(str(item) for item in raw_tail if item).strip()
    if text.startswith("```") and text.endswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SpecialistProviderError("specialist did not return one JSON object") from exc
    if not isinstance(value, dict):
        raise SpecialistProviderError("specialist output must be a JSON object")
    return value


@dataclass(frozen=True)
class SpecialistInvocation:
    role: str
    workspace: Path
    prompt: str
    config: Mapping[str, Any]
    session_id: str | None = None
    timeout_seconds: int | None = None
    api_key: str | None = None
    env: Mapping[str, str] | None = None
    api_key_env: str | None = None
    image_files: tuple[str, ...] = ()
    memory: Any | None = None

    def __post_init__(self) -> None:
        get_specialist_role(self.role)
        if not str(self.prompt).strip():
            raise SpecialistProviderError("specialist prompt must not be empty")
        object.__setattr__(self, "workspace", Path(self.workspace).expanduser().resolve())
        object.__setattr__(self, "role", str(self.role).strip().lower())


@dataclass(frozen=True)
class SpecialistResult:
    role: str
    session_id: str
    reply: str
    raw_tail: tuple[str, ...] = ()
    tool_calls: tuple[dict[str, Any], ...] = ()
    usage: dict[str, int] = field(default_factory=dict)
    cost: float | None = None

    def provider_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "session_id": self.session_id,
            "reply": self.reply,
            "raw_tail": list(self.raw_tail),
            "tool_calls": [dict(item) for item in self.tool_calls],
            "usage": dict(self.usage),
            **({"cost": self.cost} if self.cost is not None else {}),
        }


class OpenCodeSpecialistAdapter:
    """Execute exactly one named specialist turn through the OpenCode CLI."""

    def prepare(self, workspace: str | Path, roles: Sequence[str] | None = None) -> tuple[str, ...]:
        return write_specialist_agents(workspace, roles)

    def invoke(self, request: SpecialistInvocation, progress=None) -> SpecialistResult:
        self.prepare(request.workspace, (request.role,))
        from .opencode_runner import run_opencode_turn

        result = run_opencode_turn(
            request.workspace,
            request.prompt,
            dict(request.config),
            progress=progress,
            session_id=request.session_id,
            timeout_seconds=request.timeout_seconds,
            api_key=request.api_key,
            env=request.env,
            api_key_env=request.api_key_env,
            image_files=request.image_files,
            memory=request.memory,
            agent_name=request.role,
        )
        return SpecialistResult(
            role=request.role,
            session_id=str(result.get("session_id") or ""),
            reply=str(result.get("reply") or ""),
            raw_tail=tuple(str(item) for item in (result.get("raw_tail") or ())),
            tool_calls=tuple(dict(item) for item in (result.get("tool_calls") or ()) if isinstance(item, Mapping)),
            usage=dict(result.get("usage") or {}),
            cost=float(result["cost"]) if result.get("cost") is not None else None,
        )
