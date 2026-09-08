"""Compatibility facade for the native OpenCode Build runner.

The authoritative implementation lives in :mod:`opencode_runner`, which owns
the isolated preview worktree, Ada's project instructions, validation, and the
approval-gated preview flow.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, TypedDict

from ..core.design_contracts import BuildTarget, DesignCandidateReceipt, PageBuildRequest


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


class DesignBuilder(Protocol):
    """Typed builder capability for immutable design candidates."""

    def build_design(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        progress: Callable[[str], None] | None = None,
    ) -> DesignCandidateReceipt:
        ...


class BuilderError(RuntimeError):
    def __init__(self, message: str, *, result: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.result = result or {}


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
            raise BuilderError(str(exc), result=getattr(exc, "result", None)) from exc

    def build_design(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        progress: Callable[[str], None] | None = None,
    ) -> DesignCandidateReceipt:
        try:
            from .opencode_runner import stage_design_build

            engine = self.context.get("config", {}).get("design_engine") or {}
            if str(engine.get("orchestration") or "legacy").strip().lower() == "specialist":
                from ..application.design_orchestration import SpecialistDesignCoordinator

                operation_kind = str(getattr(target, "operation_kind", "initial_build") or "initial_build")
                request_content = getattr(request, "content", {}) or {}
                repair_brief = (
                    request_content.get("specialist_repair_brief")
                    if isinstance(request_content, dict)
                    else None
                )
                locked_plan = (
                    request_content.get("specialist_locked_plan")
                    if isinstance(request_content, dict)
                    else None
                )
                if operation_kind == "visual_refinement" and isinstance(repair_brief, dict):
                    return stage_design_build(
                        self.context,
                        request,
                        target,
                        progress,
                        design_plan=locked_plan,
                        repair_brief=repair_brief,
                    )
                if operation_kind != "initial_build":
                    return stage_design_build(self.context, request, target, progress)

                def plan_builder(image_files):
                    return SpecialistDesignCoordinator(self.context).create_plan(
                        request,
                        target,
                        progress,
                        image_files=image_files,
                    ).plan

                return stage_design_build(
                    self.context,
                    request,
                    target,
                    progress,
                    plan_builder=plan_builder,
                )
            return stage_design_build(self.context, request, target, progress)
        except Exception as exc:  # noqa: BLE001 - preserve the facade's error type
            raise BuilderError(str(exc), result=getattr(exc, "result", None)) from exc


class OperationRoutingBuilder:
    """Dispatch every supported design operation to native source authoring."""

    def __init__(
        self,
        context: dict[str, Any],
        *,
        native: NativeOpenCodeBuilder | None = None,
    ) -> None:
        self.context = context
        self.native = native or NativeOpenCodeBuilder(context)

    def available(self) -> bool:
        return self.native.available()

    def build_design(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        progress: Callable[[str], None] | None = None,
    ) -> DesignCandidateReceipt:
        operation_kind = str(target.operation_kind or "").strip()
        if operation_kind in {"initial_build", "visual_refinement", "technical_repair", "derived_page"}:
            return self.native.build_design(request, target, progress)
        raise BuilderError(f"unsupported design operation kind: {operation_kind}")


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
