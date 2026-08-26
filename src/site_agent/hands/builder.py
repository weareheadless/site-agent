"""Compatibility facade for the native OpenCode Build runner.

The authoritative implementation lives in :mod:`opencode_runner`, which owns
the isolated preview worktree, Ada's project instructions, validation, and the
approval-gated preview flow.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict


class BuildOutcome(TypedDict, total=False):
    """Stable fields returned by a builder after preview staging."""

    ok: bool
    changed: bool
    reply: str
    output: str
    merge_draft_id: int
    diff_stat: str
    branch: str


class Builder(Protocol):
    """Narrow port for a preview builder implementation."""

    def available(self) -> bool:
        ...

    def build(self, brief: str, progress=None) -> BuildOutcome:
        ...


class BuilderError(RuntimeError):
    pass


class NativeOpenCodeBuilder:
    """Compatibility adapter around the current native OpenCode workflow."""

    def __init__(self, context: dict[str, Any]):
        self.context = context

    def available(self) -> bool:
        return available(self.context.get("config") or {})

    def build(self, brief: str, progress=None) -> BuildOutcome:
        try:
            from .opencode_runner import stage_build

            return stage_build(self.context, brief, progress)  # type: ignore[return-value]
        except Exception as exc:  # noqa: BLE001 - preserve the facade's error type
            raise BuilderError(str(exc)) from exc


def available(config: dict[str, Any]) -> bool:
    from .opencode_runner import builder_available

    return builder_available(config)


def build(context: dict[str, Any], brief: str) -> dict[str, Any]:
    outcome = NativeOpenCodeBuilder(context).build(brief)
    return {
        "ok": True,
        "output_tail": str(outcome.get("reply") or ""),
        "cwd": str((context.get("config", {}).get("site") or {}).get("clone_path", "")),
        "merge_draft_id": outcome.get("merge_draft_id"),
    }
