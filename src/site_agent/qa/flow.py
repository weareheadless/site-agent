"""Declarative flow definitions.

A flow is data, not code, so that adding coverage is a reviewable diff rather
than a new test framework. Unknown actions and unknown expectations fail at load
time: a typo must never silently produce a flow that asserts nothing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml


class FlowError(ValueError):
    """A flow definition is not executable as written."""


ACTIONS = ("goto", "click", "fill", "press", "wait_for", "assert", "screenshot", "http", "converse")
TIERS = ("deterministic", "live")
OPS = ("eq", "ne", "gt", "gte", "lt", "lte", "contains", "len_eq", "len_gte", "len_lte")
EXPECTATIONS = (
    "visible",
    "hidden",
    "text",
    "text_absent",
    "count",
    "url_contains",
    "status",
    "json",
    "console_clean",
    "network_clean",
    "no_page_errors",
)
# Expectations that read a completed http step instead of the page.
_HTTP_EXPECTATIONS = ("status", "json")


def _identifier(value, where):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,100}', value):
        raise FlowError(f'{where}: id must be a safe lower-case identifier')
    return value


@dataclass(frozen=True)
class Expectation:
    kind: str
    selector: str | None = None
    text: str | None = None
    path: str | None = None
    step: str | None = None
    value: Any = None
    op: str = "eq"
    timeout_ms: int = 15_000
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "selector": self.selector,
            "text": self.text,
            "path": self.path,
            "step": self.step,
            "value": self.value,
            "op": self.op,
            "timeout_ms": self.timeout_ms,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], where: str) -> "Expectation":
        kind = str(raw.get("kind") or raw.get("expect") or "").strip()
        if kind not in EXPECTATIONS:
            raise FlowError(f"{where}: unknown expectation {kind!r}; known: {', '.join(EXPECTATIONS)}")
        op = str(raw.get("op") or "eq")
        if op not in OPS:
            raise FlowError(f"{where}: unknown comparison {op!r}")
        if kind in ("visible", "hidden", "text", "text_absent", "count") and not raw.get("selector"):
            raise FlowError(f"{where}: expectation {kind!r} needs a selector")
        if kind in ('text', 'text_absent', 'url_contains') and not raw.get('text'):
            raise FlowError(f"{where}: expectation {kind!r} needs non-empty text")
        if kind in ('count', 'status') and not isinstance(raw.get('value'), int):
            raise FlowError(f'{where}: {kind} needs an integer value')
        if int(raw.get('timeout_ms') or 15_000) <= 0:
            raise FlowError(f'{where}: timeout must be positive')
        if kind in _HTTP_EXPECTATIONS and not raw.get("step"):
            raise FlowError(f"{where}: expectation {kind!r} needs the id of an http step")
        if kind == "json" and not raw.get("path"):
            raise FlowError(f"{where}: expectation 'json' needs a dotted path")
        return cls(
            kind=kind,
            selector=raw.get("selector"),
            text=raw.get("text"),
            path=raw.get("path"),
            step=raw.get("step"),
            value=raw.get("value"),
            op=op,
            timeout_ms=int(raw.get("timeout_ms") or 15_000),
            description=raw.get("description"),
        )


@dataclass(frozen=True)
class Step:
    id: str
    action: str
    selector: str | None = None
    url: str | None = None
    text: str | None = None
    key: str | None = None
    method: str | None = None
    path: str | None = None
    body: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)
    expect: tuple[Expectation, ...] = ()
    screenshot: bool = True
    note: str | None = None
    mark: str | None = None
    until: tuple[Expectation, ...] = ()
    abort: tuple[Expectation, ...] = ()
    persona: Mapping[str, Any] | None = None
    reply_timeout_ms: int = 240_000
    confirm_dialog: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "selector": self.selector,
            "url": self.url,
            "text": self.text,
            "key": self.key,
            "method": self.method,
            "path": self.path,
            "body": self.body,
            "headers": dict(self.headers),
            "expect": [item.to_dict() for item in self.expect],
            "screenshot": self.screenshot,
            "note": self.note,
            "mark": self.mark,
            "until": [item.to_dict() for item in self.until],
            "abort": [item.to_dict() for item in self.abort],
            "persona": dict(self.persona) if self.persona else None,
            "reply_timeout_ms": self.reply_timeout_ms,
            "confirm_dialog": self.confirm_dialog,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], where: str) -> "Step":
        identifier = str(raw.get("id") or "").strip()
        if not identifier:
            raise FlowError(f"{where}: step needs an id")
        _identifier(identifier, where)
        action = str(raw.get("action") or "").strip()
        if action not in ACTIONS:
            raise FlowError(f"{where}: unknown action {action!r}; known: {', '.join(ACTIONS)}")
        expectations = tuple(
            Expectation.from_dict(item, f"{where}.expect[{index}]")
            for index, item in enumerate(raw.get("expect") or ())
        )
        until = tuple(
            Expectation.from_dict(item, f"{where}.until[{index}]")
            for index, item in enumerate(raw.get("until") or ())
        )
        abort = tuple(
            Expectation.from_dict(item, f"{where}.abort[{index}]")
            for index, item in enumerate(raw.get("abort") or ())
        )
        if any(item.kind not in ('visible', 'hidden', 'text', 'text_absent', 'count') for item in abort):
            raise FlowError(f'{where}: abort needs a page condition')
        _require_action_fields(action, raw, where)
        mark = raw.get("mark")
        if mark is not None and not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", str(mark)):
            raise FlowError(f"{where}: mark {mark!r} must be lower-case letters, digits, - or _")
        return cls(
            id=identifier,
            action=action,
            selector=raw.get("selector"),
            url=raw.get("url"),
            text=raw.get("text"),
            key=raw.get("key"),
            method=(raw.get("method") or "GET").upper(),
            path=raw.get("path"),
            body=raw.get("body"),
            headers=dict(raw.get("headers") or {}),
            expect=expectations,
            screenshot=bool(raw.get("screenshot", True)),
            note=raw.get("note"),
            mark=str(mark) if mark is not None else None,
            until=until,
            abort=abort,
            persona=dict(raw.get("persona") or {}) or None,
            reply_timeout_ms=int(raw.get("reply_timeout_ms") or 240_000),
            confirm_dialog=raw.get('confirm_dialog'),
        )


def _require_action_fields(action: str, raw: Mapping[str, Any], where: str) -> None:
    if action == "goto" and not raw.get("url"):
        raise FlowError(f"{where}: 'goto' needs a url")
    if action in ("click", "fill", "wait_for") and not raw.get("selector"):
        raise FlowError(f"{where}: {action!r} needs a selector")
    if action == "fill" and raw.get("text") is None:
        raise FlowError(f"{where}: 'fill' needs text")
    if action == "press" and not raw.get("key"):
        raise FlowError(f"{where}: 'press' needs a key")
    if action == "assert" and not raw.get("expect"):
        raise FlowError(f"{where}: 'assert' with no expectations asserts nothing")
    if action == "http" and not raw.get("path"):
        raise FlowError(f"{where}: 'http' needs a path")
    if action == "converse":
        if not raw.get("until"):
            raise FlowError(f"{where}: 'converse' needs 'until', or the conversation never ends")
        persona = raw.get("persona")
        if not isinstance(persona, Mapping):
            raise FlowError(f"{where}: 'converse' needs a persona brief describing the owner")
        brief = persona.get("brief")
        if not isinstance(brief, str) or not brief.strip():
            raise FlowError(f"{where}: persona needs a brief: who this owner is and what they know")
        turns = persona.get("max_turns", 12)
        if not isinstance(turns, int) or not 1 <= turns <= 40:
            raise FlowError(f"{where}: persona.max_turns must be an integer between 1 and 40")
    elif raw.get("until"):
        raise FlowError(f"{where}: 'until' only makes sense on a 'converse' step")


@dataclass(frozen=True)
class Flow:
    id: str
    title: str
    tier: str
    description: str = ""
    requires: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    steps: tuple[Step, ...] = ()
    source_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "tier": self.tier,
            "description": self.description,
            "requires": list(self.requires),
            "tags": list(self.tags),
            "steps": [step.to_dict() for step in self.steps],
        }

    @property
    def step_ids(self) -> tuple[str, ...]:
        return tuple(step.id for step in self.steps)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], *, source_path: str | None = None) -> "Flow":
        where = source_path or "flow"
        identifier = str(raw.get("id") or "").strip()
        if not identifier:
            raise FlowError(f"{where}: flow needs an id")
        _identifier(identifier, where)
        tier = str(raw.get("tier") or "deterministic").strip()
        if tier not in TIERS:
            raise FlowError(f"{where}: unknown tier {tier!r}; known: {', '.join(TIERS)}")
        steps = tuple(
            Step.from_dict(item, f"{where}: step[{index}]")
            for index, item in enumerate(raw.get("steps") or ())
        )
        if not steps:
            raise FlowError(f"{where}: flow has no steps")
        seen: set[str] = set()
        for step in steps:
            if step.id in seen:
                raise FlowError(f"{where}: duplicate step id {step.id!r}")
            seen.add(step.id)
        for step in steps:
            for expectation in step.expect:
                if expectation.step and expectation.step not in seen:
                    raise FlowError(
                        f"{where}: step {step.id!r} expects from unknown http step {expectation.step!r}"
                    )
        return cls(
            id=identifier,
            title=str(raw.get("title") or identifier),
            tier=tier,
            description=str(raw.get("description") or ""),
            requires=tuple(str(item) for item in raw.get("requires") or ()),
            tags=tuple(str(item) for item in raw.get("tags") or ()),
            steps=steps,
            source_path=source_path,
        )


def load_flow(path: str | Path) -> Flow:
    """Load one flow from a YAML or JSON file."""

    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise FlowError(f"cannot read flow {target}: {exc}") from exc
    try:
        if target.suffix.lower() == ".json":
            raw = json.loads(text)
        else:
            raw = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise FlowError(f"cannot parse flow {target}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise FlowError(f"flow {target} must be a mapping")
    return Flow.from_dict(raw, source_path=str(target))


def load_flows(root: str | Path) -> tuple[Flow, ...]:
    """Load every flow under a directory, sorted by id."""

    base = Path(root)
    if not base.is_dir():
        return ()
    paths: Sequence[Path] = sorted(
        [*base.glob("*.yaml"), *base.glob("*.yml"), *base.glob("*.json")]
    )
    return tuple(sorted((load_flow(path) for path in paths), key=lambda flow: flow.id))
