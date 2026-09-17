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
from threading import Lock
from typing import Any, Mapping, Sequence


class SpecialistProviderError(RuntimeError):
    """A specialist invocation could not produce a provider result."""


_SPECIALIST_RUN_LOCK = Lock()


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
        "primary",
        "none",
        ("design-core.md",),
    ),
    "brand-source-analyst": SpecialistRole(
        "brand-source-analyst",
        "Extracts evidence-backed visual grammar from the frozen owner context and supplied media.",
        "primary",
        "none",
        ("design-core.md", "frontend-design.md", "high-end-visual-design.md"),
    ),
    "concept-designer": SpecialistRole(
        "concept-designer",
        "Develops one subject-specific visual concept from approved evidence.",
        "primary",
        "none",
        ("design-core.md", "frontend-design.md", "high-end-visual-design.md"),
    ),
    "creative-director": SpecialistRole(
        "creative-director",
        "Selects a concept and reviews its rendered realization against the locked direction.",
        "primary",
        "none",
        ("design-core.md", "high-end-visual-design.md", "web-design-guidelines.md"),
    ),
    "site-implementer": SpecialistRole(
        "site-implementer",
        "Implements the locked design plan, ordered visitor journey, responsive behavior, and reduced-motion behavior in the isolated source worktree.",
        "primary",
        "implementation",
        (
            "frontend-design.md", "web-design-guidelines.md", "motion-design.md",
            "gsap-core.md", "gsap-react.md", "gsap-scrolltrigger.md", "gsap-performance.md",
        ),
    ),
    "motion-designer": SpecialistRole(
        "motion-designer",
        "Adds the locked purposeful motion behavior and reduced-motion implementation.",
        "primary",
        "motion",
        ("gsap-core.md", "gsap-react.md", "gsap-performance.md"),
    ),
    "experience-fidelity-specialist": SpecialistRole(
        "experience-fidelity-specialist",
        "Closes every missing locked journey condition in the existing realization without introducing a second concept.",
        "primary",
        "fidelity",
        (
            "frontend-design.md", "web-design-guidelines.md", "motion-design.md",
            "gsap-core.md", "gsap-react.md", "gsap-scrolltrigger.md", "gsap-performance.md",
        ),
    ),
    "experience-critic": SpecialistRole(
        "experience-critic",
        "Reviews rendered evidence for comprehension, hierarchy, conversion, and usability.",
        "primary",
        "none",
        ("web-design-guidelines.md",),
    ),
    "technical-critic": SpecialistRole(
        "technical-critic",
        "Reviews rendered evidence and implementation deviations for technical risk.",
        "primary",
        "none",
        ("web-design-guidelines.md", "gsap-performance.md"),
    ),
    "transfer-critic": SpecialistRole(
        "transfer-critic",
        "Tests whether the locked experience plan remains specific to the supplied business and evidence.",
        "primary",
        "none",
        ("design-core.md", "web-design-guidelines.md"),
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


# Authoring phases may run the project's own build/check scripts, but the host
# owns every browser, screenshot, interaction, and visual-validation step. This
# allowlist is deliberate: arbitrary processes (browsers, HTTP servers, custom
# CDP harnesses, package installers) are denied so an authoring turn cannot
# begin an unbounded self-review loop. Rules are last-match-wins, so the
# catch-all deny must come first.
_AUTHORING_BASH_ALLOWLIST: tuple[str, ...] = (
    "cd *",
    "ls *",
    "cat *",
    "head *",
    "tail *",
    "grep *",
    "rg *",
    "wc *",
    "sort *",
    "uniq *",
    "npm *",
    "pnpm *",
    "yarn *",
    "bun *",
    "git status *",
    "git diff *",
    "git log *",
)


def _permission_block(role: SpecialistRole) -> str:
    """Host-controlled capabilities for one specialist phase.

    Read-only phases cannot touch files, run processes, fetch the network, or
    repeat an identical tool call. Authoring phases may edit source and run the
    project's own build/check scripts, but cannot launch a browser, HTTP server,
    or any other self-review process.
    """
    lines = [
        "permission:",
        "  task: deny",
        "  webfetch: deny",
        "  websearch: deny",
        "  doom_loop: deny",
    ]
    if role.write_scope == "none":
        lines += ["  edit: deny", "  bash: deny"]
    else:
        lines += ["  edit: allow", "  bash:", '    "*": deny']
        for pattern in _AUTHORING_BASH_ALLOWLIST:
            lines.append(f'    "{pattern}": allow')
    return "\n".join(lines) + "\n"


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
        "fidelity": "You may edit only the host-provided implementation worktree to close locked journey conditions; do not mutate Git state or introduce a new concept.",
        "repair": "You may edit only paths named by the host repair brief; do not mutate Git state.",
    }[role.write_scope]
    return (
        "---\n"
        f"description: {role.description}\n"
        f"mode: {role.mode}\n"
        + _permission_block(role)
        + "---\n\n"
        f"You are the {role.name} specialist in a finite design workflow.\n"
        "The host supplies the phase inputs and validates your structured output.\n"
        f"{write_rule}\n"
        f"{task_rule}\n"
        + (
            ""
            if role.write_scope == "none"
            else "You may run the project's own build/check scripts to catch mistakes, but the host owns all "
            "rendering, browser, screenshot, interaction, motion, and reduced-motion validation. Do not launch a "
            "browser, HTTP server, or custom rendering/self-review process, and do not delegate.\n"
        )
        + "Do not approve, publish, contact external services, invent business facts, or change the design direction outside the host contract.\n"
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


def _write_specialist_runtime_config(
    workspace: str | Path,
    config: Mapping[str, Any],
    *,
    api_key_env: str | None = None,
    reasoning_effort: str | None = None,
) -> tuple[Path, bytes | None]:
    """Install the configured model limits for one disposable specialist turn.

    Specialist workspaces previously only received the named agent definition.
    That left OpenCode to use its global model configuration, whose 32k output
    limit could end a valid large design artifact with ``step-finish: length``
    before the JSON envelope was complete.  Preserve any existing project
    configuration and restore it after the turn so implementation worktrees do
    not acquire a provider-specific runtime file.
    """
    from .opencode_runner import _qualified_model

    root = Path(workspace).expanduser().resolve()
    config_path = root / "opencode.json"
    previous = config_path.read_bytes() if config_path.exists() else None
    try:
        existing = json.loads(previous.decode("utf-8")) if previous else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}

    builder = config.get("builder") or {}
    llm = config.get("llm") or {}
    design_engine = config.get("design_engine") or {}
    model = str(builder.get("model") or llm.get("model") or "").strip()
    model_id = _qualified_model(model)
    if not model_id or "/" not in model_id:
        return config_path, previous

    provider, bare = model_id.split("/", 1)
    provider_details = {
        "openrouter": {
            "name": "OpenRouter",
            "key_env": "OPENROUTER_API_KEY",
            "base_url": "https://openrouter.ai/api/v1",
            "npm": "@ai-sdk/openai-compatible",
        },
        "entrim": {
            "name": "Entrim",
            "key_env": "ENTRIM_API_KEY",
            "base_url": "https://api.entrim.ai/v1",
            "npm": "@ai-sdk/openai-compatible",
        },
        "openai": {
            "name": "Openai",
            "key_env": "OPENAI_API_KEY",
            "base_url": "",
            "npm": None,
        },
        "anthropic": {
            "name": "Anthropic",
            "key_env": "ANTHROPIC_API_KEY",
            "base_url": "",
            "npm": None,
        },
    }.get(provider)
    if provider_details is None:
        return config_path, previous

    key_env = str(
        api_key_env
        or design_engine.get("api_key_env")
        or llm.get("api_key_env")
        or provider_details["key_env"]
    ).strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env):
        raise SpecialistProviderError("specialist provider credential name is invalid")

    output_tokens = max(1024, int(builder.get("output_tokens", 8192)))
    timeout_ms = max(300, int(builder.get("provider_timeout_seconds", 2100))) * 1000
    chunk_timeout_ms = max(30, int(builder.get("provider_chunk_timeout_seconds", 180))) * 1000
    provider_options: dict[str, Any] = {
        "apiKey": "{env:" + key_env + "}",
        "timeout": timeout_ms,
        "chunkTimeout": chunk_timeout_ms,
    }
    base_url = str(llm.get("base_url") or "").strip() or str(provider_details["base_url"])
    if base_url:
        provider_options["baseURL"] = base_url.rstrip("/")
    provider_entry: dict[str, Any] = {
        "name": provider_details["name"],
        "options": provider_options,
        "models": {
            bare: {
                "name": "Ada's working model",
                "limit": {"context": 1_048_576, "output": output_tokens},
                "options": {
                    "max_tokens": output_tokens,
                    "reasoning_effort": str(
                        reasoning_effort or builder.get("reasoning_effort", "low")
                    ).strip() or "low",
                },
            }
        },
    }
    if provider_details["npm"]:
        provider_entry["npm"] = provider_details["npm"]

    runtime = dict(existing)
    runtime.setdefault("$schema", "https://opencode.ai/config.json")
    runtime.setdefault("permission", {"task": {"*": "deny"}})
    runtime["model"] = model_id
    runtime["small_model"] = model_id
    providers = dict(runtime.get("provider") or {})
    providers[provider] = provider_entry
    runtime["provider"] = providers
    config_path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
    return config_path, previous


def _restore_specialist_runtime_config(path: Path, previous: bytes | None) -> None:
    if previous is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.write_bytes(previous)


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
        "complete DesignPhaseArtifact envelope, no Markdown fences, no commentary, and no second attempt. "
        "The envelope top-level fields are exactly schema_version, run_id, phase, variant_key, attempt, status, "
        "base_sha, context_snapshot_hash, input_hashes, producer, and payload. schema_version must be 1; put all "
        "role-specific contract data under payload rather than at the envelope top level."
    )


def decode_structured_output(result: Mapping[str, Any]) -> dict[str, Any]:
    """Decode the one JSON object returned by a specialist."""
    direct = result.get("structured")
    if isinstance(direct, dict):
        return direct
    text = str(result.get("reply") or "").strip()
    raw_output = str(result.get("raw_output") or "").strip()
    raw_tail = result.get("raw_tail") or []
    raw_text = "\n".join(str(item) for item in raw_tail if item).strip()
    transcript = str(result.get("transcript") or "").strip()

    def transcript_text(value: str) -> str:
        fragments: list[str] = []
        for line in value.splitlines():
            try:
                event = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(event, Mapping):
                continue
            part = event.get("part")
            if not isinstance(part, Mapping):
                part = {}
            seen_items: set[str] = set()
            for item in (event.get("text"), part.get("text")):
                if isinstance(item, str) and item:
                    # OpenCode versions may mirror the same text in both the
                    # event and its part.  Appending both copies turns one
                    # valid JSON response into two adjacent objects, causing
                    # the outer response to be mistaken for a nested object.
                    if item in seen_items:
                        continue
                    seen_items.add(item)
                    fragments.append(item)
        return "\n".join(fragments).strip()

    transcript_output = transcript_text(transcript)

    def exact_json(value: str) -> dict[str, Any] | None:
        candidate = value.strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            candidate = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.I | re.S
            ).strip()
        try:
            decoded = json.loads(candidate)
        except (TypeError, json.JSONDecodeError):
            # A provider can terminate immediately after the final nested
            # value and omit only the closing delimiter for the outer object.
            # Recover that transport truncation only when the remainder is
            # structurally unambiguous: no open string, no mismatched closer,
            # and only trailing containers need closing.  Do not repair
            # missing commas, partial strings, or arbitrary prose.
            stack: list[str] = []
            repaired_chars: list[str] = []
            mismatched_closers = 0
            in_string = False
            escaped = False
            for char in candidate:
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    repaired_chars.append(char)
                    continue
                if char == '"':
                    in_string = True
                elif char in "{[":
                    stack.append(char)
                elif char in "}]":
                    expected = "{" if char == "}" else "["
                    if not stack:
                        return None
                    if stack[-1] != expected:
                        # A provider occasionally emits one object-closing
                        # bracket as an array-closing bracket (or the reverse)
                        # in a large nested JSON response.  When the only
                        # disagreement is the container type, the repair is
                        # structurally unambiguous; do not repair missing
                        # commas, strings, or arbitrary prose.
                        alternate = "}" if char == "]" and stack[-1] == "{" else (
                            "]" if char == "}" and stack[-1] == "[" else None
                        )
                        if alternate is None or mismatched_closers >= 4:
                            return None
                        char = alternate
                        mismatched_closers += 1
                    stack.pop()
                repaired_chars.append(char)
            if in_string or escaped or len(stack) > 8:
                return None
            repaired = "".join(repaired_chars) + "".join(
                "}" if opener == "{" else "]" for opener in reversed(stack)
            )
            try:
                decoded = json.loads(repaired)
            except (TypeError, json.JSONDecodeError):
                return None
        return decoded if isinstance(decoded, dict) else None

    # The runner keeps owner-facing prose separate from the raw event tail. A
    # JSON line is intentionally filtered out of prose, so a specialist's
    # otherwise-valid multi-line object can arrive as a partial ``reply`` while
    # the complete object is still present in ``raw_tail``.
    for candidate in (text, raw_output, raw_text, transcript_output):
        decoded = exact_json(candidate)
        if decoded is not None:
            return decoded

    # Recover one object from terminal/event lines without accepting arbitrary
    # prose. This still requires a complete JSON object and the application
    # contract validation below remains authoritative.
    for source in (raw_output, raw_text, transcript_output):
        objects: list[tuple[int, int, dict[str, Any]]] = []
        for start, char in enumerate(source):
            if char != "{":
                continue
            depth = 0
            in_string = False
            escaped = False
            for index in range(start, len(source)):
                current = source[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif current == "\\":
                        escaped = True
                    elif current == '"':
                        in_string = False
                    continue
                if current == '"':
                    in_string = True
                elif current == "{":
                    depth += 1
                elif current == "}":
                    depth -= 1
                    if depth == 0:
                        decoded = exact_json(source[start : index + 1])
                        if decoded is not None:
                            objects.append((start, index, decoded))
                        break
        envelopes = [
            decoded for _, _, decoded in objects
            if {"phase", "payload"}.issubset(decoded) and decoded.get("schema_version") == 1
        ]
        if envelopes:
            return envelopes[0]
        top_level = [
            decoded for start, end, decoded in objects
            if not any(
                other_start < start and other_end >= end
                for other_start, other_end, _ in objects
            )
        ]
        if len(top_level) == 1:
            return top_level[0]
    if text or raw_text:
        raise SpecialistProviderError("specialist did not return one JSON object")
    raise SpecialistProviderError("specialist did not return one JSON object")


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
    reasoning_effort: str = ""

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
    raw_output: str = ""
    transcript: str = ""
    tool_calls: tuple[dict[str, Any], ...] = ()
    usage: dict[str, int] = field(default_factory=dict)
    cost: float | None = None

    def provider_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "session_id": self.session_id,
            "reply": self.reply,
            "raw_tail": list(self.raw_tail),
            "raw_output": self.raw_output,
            "transcript": self.transcript,
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
        runtime_config, previous_config = _write_specialist_runtime_config(
            request.workspace,
            request.config,
            api_key_env=request.api_key_env,
            reasoning_effort=request.reasoning_effort or None,
        )
        from .opencode_runner import run_opencode_turn

        # OpenCode's local session database is shared by concurrent CLI turns.
        # The coordinator may submit independent phases in parallel, but the
        # provider boundary must serialize those process launches or the second
        # turn can fail before it emits a response with ``database is locked``.
        try:
            with _SPECIALIST_RUN_LOCK:
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
        finally:
            _restore_specialist_runtime_config(runtime_config, previous_config)
        return SpecialistResult(
            role=request.role,
            session_id=str(result.get("session_id") or ""),
            reply=str(result.get("reply") or ""),
            raw_tail=tuple(str(item) for item in (result.get("raw_tail") or ())),
            raw_output=str(result.get("raw_output") or ""),
            transcript=str(result.get("transcript") or ""),
            tool_calls=tuple(dict(item) for item in (result.get("tool_calls") or ()) if isinstance(item, Mapping)),
            usage=dict(result.get("usage") or {}),
            cost=float(result["cost"]) if result.get("cost") is not None else None,
        )
