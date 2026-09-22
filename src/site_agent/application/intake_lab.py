"""Application service for the standalone, local Intake Lab.

The lab is deliberately a thin adapter around the typed design workflow.  It
owns source isolation and safe projections, while ``DesignService`` owns the
design lifecycle and ``DesignJobExecutor`` owns execution.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..core.contracts import ContractError
from ..core.design_contracts import (
    BuildTarget,
    DesignRunStatus,
    PageBuildRequest,
    SiteIntake,
    canonical_hash,
    canonical_json,
)
from ..hands.design_experiment import (
    clone_local_repository,
    clone_public_repository,
    detach_remote,
    head_sha,
    initialize_neutral_repository,
    resolve_commit_sha,
)


class IntakeLabError(ValueError):
    """The local Intake Lab request cannot be safely completed."""


_SHA = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TERMINAL = {
    DesignRunStatus.READY_FOR_REVIEW.value,
    DesignRunStatus.NEEDS_REPAIR.value,
    DesignRunStatus.INCOMPLETE.value,
    DesignRunStatus.INTERRUPTED.value,
    DesignRunStatus.FAILED.value,
    DesignRunStatus.CANCELLED.value,
}
_PATH_KEYS = {
    "path",
    "source_path",
    "screenshot_path",
    "transcript_path",
    "clone_path",
    "clone_root",
    "worktree",
    "worktree_root",
    "workspace",
    "root",
    "output_dir",
    "artifact_path",
    "repository",
    "repository_path",
    "repository_url",
    "remote",
    "origin",
}
_SENSITIVE_KEY_PARTS = ("token", "secret", "password", "credential", "api_key", "apikey")
_PIPELINE_STAGES = (
    ("intake", "Intake", frozenset({"created", "experiment", "intake_lab", "assessing_intake", "intake_assessment"})),
    ("planning", "Planning", frozenset({"planning", "plan_output", "derived_source", "refinement_planned"})),
    ("building", "Build", frozenset({"building", "queued", "claimed", "progress", "retaining_candidate", "candidate_ready", "candidate_failed"})),
    ("validation", "Deterministic validation", frozenset({"validating", "quality_failed", "quality_error"})),
    ("visual_review", "Visual review", frozenset({"visual_review_pending", "visual_review", "visual_review_error"})),
    ("result", "Result", frozenset({"review", "approved", "declined", "cancelled", "failed", "interrupted", "ready_for_review"})),
)
_STATUS_STAGE = {
    DesignRunStatus.CREATED.value: "intake",
    DesignRunStatus.ASSESSING_INTAKE.value: "intake",
    DesignRunStatus.PLANNING.value: "planning",
    DesignRunStatus.BUILDING.value: "building",
    DesignRunStatus.CANDIDATE_READY.value: "validation",
    DesignRunStatus.VALIDATING.value: "validation",
}
_OPERATION_LABELS = {
    "initial_build": "Initial design",
    "visual_refinement": "Visual refinement",
    "technical_repair": "Technical repair",
    "derived_page": "Derived page",
}
_EVENT_KEYS = {
    "base_sha",
    "candidate_sha",
    "candidate_ref",
    "count",
    "error",
    "finding_count",
    "intake_hash",
    "implementation_model",
    "model_id",
    "mode",
    "operation_kind",
    "parent_run_id",
    "provider_id",
    "push_mode",
    "screenshot_count",
    "source_kind",
    "state",
    "visual_review_model",
    "worker",
    "snapshot_id",
    "commit_sha",
    "label",
}


def _parse_timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _duration_seconds(start: Any, end: Any) -> int | None:
    first = _parse_timestamp(start)
    last = _parse_timestamp(end)
    if first is None or last is None:
        return None
    return max(0, int((last - first).total_seconds()))


def _duration_label(seconds: int | None) -> str:
    if seconds is None:
        return "Timing unavailable"
    if seconds < 60:
        return f"{seconds}s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {remainder}s" if remainder else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def _event_timestamp(event: Mapping[str, Any]) -> str | None:
    value = event.get("created_ts") or event.get("created_at")
    return str(value) if value else None


def _result_projection(
    status: str,
    report: Mapping[str, Any],
    visual: Mapping[str, Any] | None,
    error: str | None,
    operation_kind: str = "initial_build",
) -> dict[str, Any]:
    quality_state = str(report.get("state") or "pending")
    visual_state = str((visual or {}).get("state") or "pending")
    quality_findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    visual_findings = (visual or {}).get("findings") if isinstance((visual or {}).get("findings"), list) else []
    if status == DesignRunStatus.READY_FOR_REVIEW.value:
        result_state = "visually_reviewed" if visual_state == "passed" else "deterministically_valid"
        summary = (
            "Deterministic checks and visual review passed."
            if result_state == "visually_reviewed"
            else "Deterministic checks passed; this candidate is ready for review."
        )
        next_action = "Review the retained candidate before any owner approval."
    elif status == DesignRunStatus.NEEDS_REPAIR.value:
        result_state = "needs_repair"
        if visual_state == "repair":
            count = len(visual_findings)
            summary = f"Deterministic checks passed, but visual review found {count} repair item(s)."
            next_action = (
                "This bounded refinement already consumed the automatic repair; further changes require explicit owner feedback."
                if operation_kind == "visual_refinement"
                else "Review the visual findings and decide whether to start the available refinement."
            )
        else:
            count = len(quality_findings)
            summary = f"Deterministic validation found {count} blocking issue(s)."
            next_action = "Fix the deterministic findings in a new run."
    elif status == DesignRunStatus.INCOMPLETE.value:
        result_state = "inconclusive"
        if visual_state == "inconclusive":
            summary = "Deterministic checks passed, but visual review did not complete."
            next_action = "Retry the visual review before treating this candidate as reviewable."
        elif error:
            summary = f"The validation pipeline is incomplete: {error}"
            next_action = "Inspect the diagnostic and retry the incomplete operation explicitly."
        else:
            summary = "The validation pipeline did not complete, so this candidate is not reviewable."
            next_action = "Inspect the incomplete gate and retry explicitly."
    elif status in {DesignRunStatus.FAILED.value, DesignRunStatus.INTERRUPTED.value, DesignRunStatus.CANCELLED.value}:
        result_state = "failed"
        summary = error or f"The run ended as {status.replace('_', ' ')}."
        next_action = "Start a new run after reviewing the diagnostic."
    elif quality_state == "passed" and visual_state in {"pending", ""} and status == DesignRunStatus.VALIDATING.value:
        result_state = "deterministic_valid"
        summary = "Deterministic checks passed; visual review is still pending."
        next_action = "Wait for or retry the separate visual review operation."
    else:
        result_state = "in_progress"
        summary = f"The run is currently {status.replace('_', ' ')}."
        next_action = "Wait for the next pipeline stage to finish."
    return {
        "state": result_state,
        "label": {
            "visually_reviewed": "Visually reviewed",
            "deterministically_valid": "Deterministically valid",
            "deterministic_valid": "Deterministically valid",
            "needs_repair": "Needs repair",
            "inconclusive": "Inconclusive",
            "failed": "Failed",
            "in_progress": "In progress",
        }[result_state],
        "summary": _bounded_text(summary, maximum=500),
        "next_action": _bounded_text(next_action, maximum=500),
        "deterministic_state": quality_state,
        "visual_state": visual_state,
        "quality_finding_count": len(quality_findings),
        "visual_finding_count": len(visual_findings),
        "error": error,
    }


def _owner_status(status: str, report: Mapping[str, Any], visual: Mapping[str, Any] | None) -> str:
    """Project internal lifecycle states into the small owner decision set."""
    if status == DesignRunStatus.CANCELLED.value:
        return "cancelled"
    if status in {DesignRunStatus.FAILED.value, DesignRunStatus.INTERRUPTED.value}:
        return "blocked"
    quality_state = str(report.get("state") or "pending")
    visual_state = str((visual or {}).get("state") or "pending")
    if quality_state in {"failed", "incomplete"}:
        return "blocked"
    if status == DesignRunStatus.NEEDS_REPAIR.value:
        return "blocked"
    if status == DesignRunStatus.INCOMPLETE.value:
        return "blocked"
    if status == DesignRunStatus.READY_FOR_REVIEW.value:
        if quality_state != "passed" or visual_state in {"repair", "inconclusive", "failed"}:
            return "blocked"
        return "ready_for_feedback"
    return "working"


def _pipeline_projection(
    events: list[Mapping[str, Any]],
    status: str,
    report: Mapping[str, Any],
    visual: Mapping[str, Any] | None,
    created_at: str | None,
    updated_at: str | None,
    error: str | None,
) -> list[dict[str, Any]]:
    starts: dict[str, str] = {}
    for event in events:
        stage = str(event.get("stage") or "")
        for key, _, event_names in _PIPELINE_STAGES:
            if stage in event_names:
                timestamp = _event_timestamp(event)
                if timestamp and key not in starts:
                    starts[key] = timestamp
                break

    terminal = status in _TERMINAL
    result_start = starts.get("result")
    terminal_events = {
        "candidate_failed", "quality_failed", "quality_error", "visual_review", "visual_review_error",
        "ready_for_review", "review", "approved", "declined", "cancelled", "failed", "interrupted",
    }
    for event in events:
        if str(event.get("stage") or "") in terminal_events:
            timestamp = _event_timestamp(event)
            if timestamp:
                if str(event.get("stage") or "") in {"visual_review", "visual_review_error"} and visual:
                    result_start = timestamp
                elif result_start is None:
                    result_start = timestamp
    if terminal:
        starts.setdefault("result", result_start or updated_at or created_at or "")

    current_stage = "result" if terminal else _STATUS_STAGE.get(status)
    if status == DesignRunStatus.VALIDATING.value and any(
        str(event.get("stage") or "") == "visual_review_pending" for event in events
    ):
        current_stage = "visual_review"
    result = _result_projection(status, report, visual, error)
    output: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for index, (key, label, _) in enumerate(_PIPELINE_STAGES):
        started_at = starts.get(key)
        next_started = next(
            (starts.get(next_key) for next_key, _, _ in _PIPELINE_STAGES[index + 1:] if starts.get(next_key)),
            None,
        )
        if not started_at:
            state = "pending"
            completed_at = None
            duration = None
        else:
            completed_at = next_started
            if next_started:
                state = "complete"
            elif terminal:
                state = "complete"
                completed_at = updated_at or started_at
            elif current_stage == key:
                state = "active"
                completed_at = None
            else:
                state = "complete"
                completed_at = updated_at or started_at
            duration = _duration_seconds(started_at, completed_at or (now if state == "active" else started_at))
        if key == "intake":
            summary = "Facts were checked against the typed intake contract." if state != "pending" else "Waiting for the intake to be accepted."
        elif key == "planning":
            summary = "The brief and art direction were selected." if state != "pending" else "Waiting for an accepted intake."
        elif key == "building":
            summary = "An isolated candidate was retained." if state == "complete" else "The isolated candidate is being built."
        elif key == "validation":
            quality_state = str(report.get("state") or "pending")
            summary = {
                "passed": "All deterministic quality gates passed.",
                "failed": "One or more deterministic quality gates failed.",
                "incomplete": "Deterministic validation did not complete.",
            }.get(quality_state, "Deterministic quality validation is pending.")
        elif key == "visual_review":
            visual_state = str((visual or {}).get("state") or "pending")
            summary = {
                "passed": "The visual review passed.",
                "repair": "The visual review found actionable repair items.",
                "inconclusive": "The visual review did not complete conclusively.",
            }.get(visual_state, "The separate visual review is pending.")
        else:
            summary = result["summary"] if state != "pending" else "The final outcome is not available yet."
        output.append({
            "key": key,
            "label": label,
            "state": state,
            "current": current_stage == key,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": duration,
            "duration_label": _duration_label(duration),
            "summary": summary,
        })
    return output


def _resolved(path: str | Path | None) -> Path | None:
    value = str(path or "").strip()
    return Path(value).expanduser().resolve(strict=False) if value else None


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def validate_intake_lab_workspace(
    workspace: str | Path,
    config: Mapping[str, Any],
    *,
    allow_workspace_data_dir: bool = False,
) -> Path:
    """Reject workspace locations that could overlap live application state."""
    root = _resolved(workspace)
    if root is None or root == Path(root.anchor):
        raise IntakeLabError("Intake Lab workspace is too broad")
    home = Path.home().resolve()
    if root == home:
        raise IntakeLabError("Intake Lab workspace cannot be the home directory")

    site = config.get("site") or {}
    live: list[Path] = []
    for key, value in (
        ("data_dir", config.get("data_dir")),
        ("repository_path", config.get("repository_path")),
        ("clone_path", site.get("clone_path")),
        ("site_data_dir", site.get("data_dir")),
        ("site_repository_path", site.get("repository_path")),
    ):
        resolved = _resolved(value)
        if resolved is not None:
            if key == "data_dir" and allow_workspace_data_dir and root in resolved.parents:
                continue
            live.append(resolved)

    cwd = Path.cwd().resolve()
    if (cwd / ".git").exists():
        live.append(cwd)
    package_root = Path(__file__).resolve()
    for parent in package_root.parents:
        if (parent / ".git").exists():
            live.append(parent)
            break

    if any(_overlaps(root, path) for path in live):
        raise IntakeLabError("Intake Lab workspace overlaps the live site or data path")
    return root


def _credential_names(config: Mapping[str, Any]) -> set[str]:
    """Return only environment names consumed by the two model adapters."""
    env_config = config.get("env") or {}
    engine = config.get("design_engine") or {}
    visual = engine.get("visual_review") or {}
    vision = config.get("vision") or {}
    names: set[str] = set()
    for value in (
        env_config.get("llm_api_key"),
        env_config.get("vision_api_key"),
        engine.get("api_key_env"),
        visual.get("api_key_env"),
        vision.get("api_key_env"),
        (engine.get("intake_advisor") or {}).get("api_key_env"),
    ):
        name = str(value or "").strip()
        if _ENV_NAME.fullmatch(name):
            names.add(name)
    return names


def build_intake_lab_environment(
    config: Mapping[str, Any],
    source_env: Mapping[str, str],
    workspace: str | Path,
) -> dict[str, str]:
    """Build a child environment without inheriting owner or integration secrets."""
    root = _resolved(workspace)
    if root is None:
        raise IntakeLabError("Intake Lab workspace is required for process isolation")
    process_home = root / "process-home"
    process_tmp = root / "process-tmp"
    process_home.mkdir(parents=True, exist_ok=True)
    process_tmp.mkdir(parents=True, exist_ok=True)

    result: dict[str, str] = {}
    for key in ("PATH", "USER", "LANG", "LC_ALL", "SHELL"):
        if key in source_env:
            result[key] = str(source_env[key])
    result.setdefault("PATH", os.defpath)
    result.update({
        "HOME": str(process_home),
        "XDG_CONFIG_HOME": str(process_home / ".config"),
        "XDG_CACHE_HOME": str(process_home / ".cache"),
        "XDG_DATA_HOME": str(process_home / ".local" / "share"),
        "TMPDIR": str(process_tmp),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ASKPASS": os.devnull,
    })
    for directory in (
        process_home / ".config",
        process_home / ".cache",
        process_home / ".local" / "share",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    for key in ("SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
        value = str(source_env.get(key, ""))
        if not value:
            continue
        if key in {"HTTP_PROXY", "HTTPS_PROXY"}:
            parsed = urlsplit(value)
            if parsed.username or parsed.password:
                raise IntakeLabError(f"{key} must not contain proxy credentials")
        result[key] = value

    for name in _credential_names(config):
        if name in source_env:
            result[name] = str(source_env[name])
    return result


def build_intake_lab_build_environment(
    config: Mapping[str, Any],
    source_env: Mapping[str, str],
    workspace: str | Path,
) -> dict[str, str]:
    """Build the host-site build environment without model credentials."""
    result = build_intake_lab_environment(config, source_env, workspace)
    for name in _credential_names(config):
        result.pop(name, None)
    # Keep the virtualenv bin directory itself. Resolving the interpreter can
    # collapse a venv symlink to /usr/bin and select an incompatible Node/npm
    # toolchain before the host's configured build tools.
    runtime_bin = Path(sys.executable).expanduser().parent if sys.executable else None
    if runtime_bin is not None:
        user_tool_bin = (Path.home() / ".local" / "bin").resolve()
        tool_paths = [str(runtime_bin)]
        if user_tool_bin.is_dir() and user_tool_bin != runtime_bin.resolve():
            # Intake Lab may be launched by a service with a minimal PATH. Keep
            # the host's user-local Node/npm toolchain available for the
            # approved Next build instead of silently falling back to an older
            # system Node binary.
            tool_paths.append(str(user_tool_bin))
        result["PATH"] = os.pathsep.join(
            part for part in (*tool_paths, result.get("PATH", "")) if part
        )
    return result


def _prompt(value: Any) -> str:
    if not isinstance(value, str):
        raise IntakeLabError("prompt must be text")
    result = value.strip()
    if not result:
        raise IntakeLabError("prompt must not be empty")
    if len(result) > 20_000:
        raise IntakeLabError("prompt exceeds 20000 characters")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in result):
        raise IntakeLabError("prompt contains control characters")
    return result


def _bounded_text(value: Any, *, maximum: int = 500) -> str:
    text = str(value or "")
    return text[:maximum]


def _redact_text(value: Any, workspace: Path) -> str:
    text = _bounded_text(value)
    replacements = {str(workspace): "<lab-workspace>", str(Path.home()): "<home>"}
    for path in (
        Path.cwd().resolve(),
        _resolved((workspace / "runs")) or workspace,
    ):
        replacements[str(path)] = "<local-path>"
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _safe_value(value: Any, workspace: Path, *, depth: int = 0) -> Any:
    if depth > 4:
        return "<truncated>"
    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(item, workspace, depth=depth + 1)
            for key, item in value.items()
            if str(key).lower() not in _PATH_KEYS
            and not any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, workspace, depth=depth + 1) for item in list(value)[:100]]
    if isinstance(value, str):
        return _redact_text(value, workspace)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _redact_text(value, workspace)


def _event_projection(event: Mapping[str, Any], workspace: Path) -> dict[str, Any]:
    detail = event.get("detail") if isinstance(event.get("detail"), Mapping) else {}
    safe_detail = {
        str(key): _safe_value(value, workspace)
        for key, value in detail.items()
        if str(key) in _EVENT_KEYS
    }
    return {
        "id": event.get("id"),
        "stage": _bounded_text(event.get("stage"), maximum=60),
        "message": _redact_text(event.get("message"), workspace),
        "detail": safe_detail,
        "created_at": event.get("created_ts") or event.get("created_at"),
    }


def _quality_projection(report: Mapping[str, Any] | None, workspace: Path) -> dict[str, Any]:
    if not isinstance(report, Mapping) or not report:
        return {"state": "pending", "gates": {}, "findings": [], "evidence": {}}
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    evidence = report.get("evidence") if isinstance(report.get("evidence"), Mapping) else {}
    visual = evidence.get("visual_critique") if isinstance(evidence.get("visual_critique"), Mapping) else report.get("visual_critique")
    projected = {
        "state": _bounded_text(report.get("state") or "pending", maximum=30),
        "gates": _safe_value(report.get("gates") if isinstance(report.get("gates"), Mapping) else {}, workspace),
        "findings": _safe_value(findings, workspace),
        "evidence": _safe_value(evidence, workspace),
        "repair_attempts": report.get("repair_attempts", 0),
    }
    if isinstance(visual, Mapping):
        projected["visual_critique"] = _safe_value(visual, workspace)
    return projected


def _run_root_id(run: Mapping[str, Any], runs_by_id: Mapping[str, Mapping[str, Any]]) -> str:
    current = run
    seen: set[str] = set()
    while True:
        run_id = str(current.get("run_id") or "")
        if not run_id or run_id in seen:
            return run_id
        seen.add(run_id)
        parent_id = str(current.get("parent_run_id") or "").strip()
        parent = runs_by_id.get(parent_id)
        if not parent:
            return run_id
        current = parent


def _run_order(run: Mapping[str, Any]) -> tuple[datetime, int, str]:
    return (
        _parse_timestamp(run.get("created_ts") or run.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        int(run.get("id") or 0),
        str(run.get("run_id") or ""),
    )


def _revision_reason(
    run: Mapping[str, Any],
    number: int,
    runs_by_id: Mapping[str, Mapping[str, Any]],
    workspace: Path,
) -> str:
    operation = str(run.get("operation_kind") or "initial_build")
    if operation == "visual_refinement":
        parent = runs_by_id.get(str(run.get("parent_run_id") or ""))
        parent_number = number - 1
        if parent:
            root_id = _run_root_id(parent, runs_by_id)
            siblings = sorted(
                (item for item in runs_by_id.values() if _run_root_id(item, runs_by_id) == root_id),
                key=_run_order,
            )
            parent_number = next(
                (index for index, item in enumerate(siblings, start=1) if item.get("run_id") == parent.get("run_id")),
                parent_number,
            )
            report = parent.get("quality_report_json") if isinstance(parent.get("quality_report_json"), Mapping) else {}
            critique = report.get("visual_critique") if isinstance(report, Mapping) else {}
            if isinstance(critique, Mapping):
                repair_plan = critique.get("repair_plan") if isinstance(critique.get("repair_plan"), list) else []
                findings = critique.get("findings") if isinstance(critique.get("findings"), list) else []
                source = repair_plan[0] if repair_plan and isinstance(repair_plan[0], Mapping) else (
                    findings[0] if findings and isinstance(findings[0], Mapping) else {}
                )
                why = str(source.get("change") or source.get("message") or source.get("finding") or "").strip()
                if why:
                    return f"Visual refinement of revision {parent_number} to address: {_redact_text(why, workspace)}"
        return f"Visual refinement of revision {parent_number}."
    if operation == "technical_repair":
        return f"Technical repair of revision {max(1, number - 1)}."
    if operation == "derived_page":
        return f"Derived page from revision {max(1, number - 1)}."
    return "Initial design generated from the intake sheet."


_REVIEWABLE_STATUSES = {
    DesignRunStatus.READY_FOR_REVIEW.value,
}


def _revision_summary(
    run: Mapping[str, Any],
    number: int,
    root_id: str,
    runs_by_id: Mapping[str, Mapping[str, Any]],
    workspace: Path,
) -> dict[str, Any]:
    report = run.get("quality_report_json") if isinstance(run.get("quality_report_json"), Mapping) else {}
    visual = report.get("visual_critique") if isinstance(report.get("visual_critique"), Mapping) else None
    status = str(run.get("status") or "failed")
    error = _redact_text(run.get("error"), workspace) if run.get("error") else None
    result = _result_projection(status, report, visual, error)
    created_at = run.get("created_ts") or run.get("created_at")
    updated_at = run.get("updated_ts") or run.get("updated_at")
    duration = _duration_seconds(created_at, updated_at)
    candidate_sha = str(run.get("candidate_sha") or "") or None
    return {
        "run_id": str(run.get("run_id") or ""),
        "number": number,
        "operation_kind": str(run.get("operation_kind") or "initial_build"),
        "label": _OPERATION_LABELS.get(str(run.get("operation_kind") or ""), "Design operation"),
        "root_run_id": root_id,
        "parent_run_id": str(run.get("parent_run_id") or "") or None,
        "source_candidate_sha": str(run.get("source_candidate_sha") or "") or None,
        "candidate_sha": candidate_sha,
        "candidate_available": bool(candidate_sha),
        "reviewable": bool(candidate_sha) and status in _REVIEWABLE_STATUSES,
        "status": status,
        "result_state": result["state"],
        "result_label": result["label"],
        "reason": _revision_reason(run, number, runs_by_id, workspace),
        "created_at": created_at,
        "updated_at": updated_at,
        "duration_seconds": duration,
        "duration_label": _duration_label(duration),
    }


class IntakeLabService:
    """Coordinate one local Intake Lab submission without owning design policy."""

    def __init__(
        self,
        design_service,
        executor,
        *,
        config: Mapping[str, Any],
        workspace: str | Path,
        default_intake: SiteIntake | None,
        default_prompt: str,
        review_environment: Mapping[str, str] | None = None,
        design_intake_service: Any | None = None,
        chat_executor: Any | None = None,
        live_preview_store: Any | None = None,
    ) -> None:
        if default_intake is not None and not isinstance(default_intake, SiteIntake):
            raise IntakeLabError("default_intake must be a validated SiteIntake")
        self.design_service = design_service
        self.executor = executor
        self.config = dict(config)
        self.workspace = validate_intake_lab_workspace(
            workspace,
            self.config,
            allow_workspace_data_dir=True,
        )
        self.default_intake = default_intake
        self.default_prompt = _prompt(default_prompt)
        self.review_environment = dict(review_environment or {})
        self.design_intake_service = design_intake_service
        self.chat_executor = chat_executor
        self.live_preview_store = live_preview_store
        self.workspace.mkdir(parents=True, exist_ok=True)

    def describe(self) -> dict[str, Any]:
        engine = self.config.get("design_engine") or {}
        llm = self.config.get("llm") or {}
        visual = engine.get("visual_review") or {}
        vision = self.config.get("vision") or {}
        implementation_model = str(engine.get("model") or llm.get("model") or "").strip()
        implementation_provider = str(engine.get("provider") or llm.get("provider") or "").strip()
        visual_model = str(visual.get("model") or vision.get("model") or "deepseek/deepseek-v4-flash-vision-exp").strip()
        visual_provider = str(visual.get("provider") or vision.get("provider") or engine.get("provider") or llm.get("provider") or "").strip()
        site_name = "New site"
        if self.default_intake is not None:
            site_name = str(self.default_intake.business.get("name") or site_name).strip() or site_name
        return {
            "site_name": site_name,
            "implementation": {"provider": implementation_provider, "model": implementation_model},
            "visual_review": {"provider": visual_provider, "model": visual_model},
            "default_prompt": self.default_prompt,
            "default_intake": self.default_intake.to_dict() if self.default_intake is not None else {},
            "variants": ["candidate", "live"],
            "viewports": [
                {"name": "desktop", "width": 1440, "height": 1000},
                {"name": "tablet", "width": 768, "height": 1024},
                {"name": "mobile", "width": 390, "height": 844},
            ],
            "publishing_enabled": False,
            "deprecated_routes": ["/api/runs"],
        }

    def _run_root(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(str(run_id or "")):
            raise IntakeLabError("invalid Intake Lab run ID")
        return self.workspace / "runs" / str(run_id) / "repository"

    def _source_clone(self, run_id: str) -> tuple[Path, str, str]:
        if str(self.config.get("role") or "").strip().lower() == "intake":
            incubation = self.config.get("incubation") or {}
            configured_scaffold = str(incubation.get("scaffold") or "").strip()
            scaffold = Path(configured_scaffold).expanduser().resolve() if configured_scaffold else self.workspace / "neutral-scaffold"
            destination = self._run_root(run_id)
            if _overlaps(scaffold, self.workspace / "runs") or _overlaps(scaffold, destination):
                raise IntakeLabError("neutral scaffold overlaps the Intake Lab run workspace")
            try:
                scaffold, base_sha = initialize_neutral_repository(scaffold)
                clone_local_repository(scaffold, destination, base_sha)
            except Exception as exc:  # noqa: BLE001 - normalize scaffold setup errors
                raise IntakeLabError(str(exc)[:500]) from exc
            return destination, base_sha, "neutral"

        site = self.config.get("site") or {}
        destination = self._run_root(run_id)
        local_source = _resolved(site.get("clone_path"))
        if local_source is not None and (local_source / ".git").exists():
            try:
                source_ref = str(site.get("base_sha") or site.get("branch") or "HEAD").strip()
                base_sha = resolve_commit_sha(local_source, source_ref)
            except Exception as exc:  # noqa: BLE001 - normalize source setup errors
                raise IntakeLabError(str(exc)[:500]) from exc
            clone_local_repository(local_source, destination, base_sha)
            return destination, base_sha, "local"

        repository = str(site.get("repository") or "").strip()
        if not repository:
            raise IntakeLabError("site.clone_path or site.repository is required for Intake Lab")
        branch = str(site.get("branch") or "main").strip()
        clone_public_repository(repository, destination, branch=branch)
        try:
            base_sha = head_sha(destination, branch)
            detach_remote(destination)
        except Exception as exc:  # noqa: BLE001 - normalize source setup errors
            raise IntakeLabError(str(exc)[:500]) from exc
        return destination, base_sha, "public"

    def submit(
        self,
        prompt: str,
        raw_intake: Mapping[str, Any],
        *,
        run_id: str | None = None,
        conversation_id: int | None = None,
        source_message_id: int | None = None,
        chat_job_id: int | None = None,
        intake_session_id: str | None = None,
        intake_revision_id: int | None = None,
        context_extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_prompt = _prompt(prompt)
        if not isinstance(raw_intake, Mapping):
            raise IntakeLabError("intake must be an object")
        try:
            encoded = canonical_json(raw_intake)
            if len(encoded.encode("utf-8")) > 400_000:
                raise IntakeLabError("intake exceeds 400000 bytes")
            intake = SiteIntake.from_dict(raw_intake)
        except IntakeLabError:
            raise
        except (ContractError, TypeError, ValueError) as exc:
            raise IntakeLabError(str(exc)[:500]) from exc

        run_id = str(run_id or f"intake-lab-{uuid.uuid4().hex}").strip()
        if not _RUN_ID.fullmatch(run_id):
            raise IntakeLabError("run ID is invalid")
        persisted = False
        try:
            clone, base_sha, source_kind = self._source_clone(run_id)
            self.design_service.create_experiment(
                intake,
                experiment_root=clone,
                base_sha=base_sha,
                run_id=run_id,
                owner_request=request_prompt,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                chat_job_id=chat_job_id,
                intake_session_id=intake_session_id,
                intake_revision_id=intake_revision_id,
            )
            persisted = True
            if context_extra:
                self.design_service.capture_context_snapshot(
                    run_id,
                    owner_request=request_prompt,
                    conversation_id=conversation_id,
                    source_message_id=source_message_id,
                    chat_job_id=chat_job_id,
                    context_extra=context_extra,
                )
            self.design_service.memory.add_design_run_event(
                run_id,
                "intake_lab",
                "Standalone Intake Lab request accepted.",
                {
                    "intake_hash": intake.content_hash,
                    "source_kind": source_kind,
                    "implementation_model": self.describe()["implementation"]["model"],
                    "visual_review_model": self.describe()["visual_review"]["model"],
                    "intake_session_id": str(intake_session_id or ""),
                },
            )
            request = self.design_service.prepare_initial_request(run_id)
            target = self.design_service.build_target_for_run(run_id)
            if not isinstance(request, PageBuildRequest) or not isinstance(target, BuildTarget):
                raise IntakeLabError("design service did not produce typed build state")
            if target.mode != "local_experiment" or target.push_mode != "none" or target.publishable:
                raise IntakeLabError("Intake Lab build target is not local-only")
            self.design_service.queue_build(run_id, request, target)
            self.executor.enqueue(run_id)
            return self._project(self.design_service.get_run(run_id), detail=True)
        except Exception as exc:  # noqa: BLE001 - retain a durable diagnostic when possible
            if persisted:
                try:
                    current = self.design_service.memory.get_design_run(run_id)
                    if current and current["status"] not in _TERMINAL:
                        self.design_service.memory.transition_design_run(run_id, DesignRunStatus.FAILED.value, error=str(exc))
                        self.design_service.memory.add_design_run_event(
                            run_id,
                            "intake_lab_error",
                            "Intake Lab setup failed before the worker was queued.",
                            {"error": str(exc)[:500]},
                        )
                except Exception:
                    pass
            if isinstance(exc, IntakeLabError):
                raise
            raise IntakeLabError(str(exc)[:500]) from exc

    def retry_visual_review(self, run_id: str) -> dict[str, Any]:
        """Retry only the read-only visual gate for a retained local candidate."""
        safe_id = str(run_id or "").strip()
        self._raw_local_run(safe_id)
        reviewer = getattr(self.design_service, "visual_review_run", None)
        if not callable(reviewer):
            raise IntakeLabError("visual review is unavailable")
        try:
            reviewer(
                safe_id,
                env=self.review_environment,
                source_media=getattr(self, "media_service", None),
            )
            finisher = getattr(getattr(self, "executor", None), "finish_validation", None)
            if callable(finisher):
                finisher(safe_id)
            return self.get_run(safe_id)
        except Exception as exc:  # noqa: BLE001 - keep the adapter boundary bounded
            raise IntakeLabError(str(exc)[:500]) from exc

    def revalidate_run(self, run_id: str) -> dict[str, Any]:
        """Re-run host gates against a retained candidate without regenerating it."""
        safe_id = str(run_id or "").strip()
        run = self._raw_local_run(safe_id)
        context = getattr(self.executor, "context", {})
        factory = context.get("browser_quality_factory") if isinstance(context, Mapping) else None
        if not callable(factory):
            raise IntakeLabError("browser quality validation is unavailable")
        try:
            browser = factory(safe_id, run)
            report = self.design_service.revalidate_run(
                safe_id,
                self.design_service.clone_path_for_run(safe_id),
                browser=browser,
                build_env=context.get("build_env") if isinstance(context, Mapping) else None,
            )
            finisher = getattr(self.executor, "finish_validation", None)
            if callable(finisher):
                finisher(safe_id)
            return {"run": self.get_run(safe_id), "quality_report": report.to_dict()}
        except IntakeLabError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the host boundary bounded
            raise IntakeLabError(str(exc)[:500]) from exc

    def create_technical_repair(
        self,
        run_id: str,
        *,
        owner_request: str = "",
    ) -> dict[str, Any]:
        """Queue one explicit owner-directed repair from a retained candidate."""
        safe_id = str(run_id or "").strip()
        self._raw_local_run(safe_id)
        creator = getattr(self.design_service, "create_technical_repair_run", None)
        if not callable(creator):
            raise IntakeLabError("technical repair is unavailable")
        prompt = _prompt(owner_request or "Repair the retained candidate using the owner's explicit feedback.")
        try:
            created = creator(
                safe_id,
                run_id=f"design-{uuid.uuid4().hex}",
                owner_request=prompt,
            )
            if not isinstance(created, Mapping):
                raise IntakeLabError("technical repair did not produce typed build state")
            child = created.get("run")
            if not isinstance(child, Mapping) or not str(child.get("run_id") or "").strip():
                raise IntakeLabError("technical repair did not produce a run")
            request = PageBuildRequest.from_dict(created.get("request") or {})
            target = BuildTarget.from_dict(created.get("target") or {})
            if target.mode != "local_experiment" or target.push_mode != "none" or target.publishable:
                raise IntakeLabError("technical repair target is not local-only")
            child_id = str(child["run_id"])
            self.design_service.queue_build(child_id, request, target)
            self.executor.enqueue(child_id)
            return self.get_run(child_id)
        except IntakeLabError:
            raise
        except Exception as exc:  # noqa: BLE001 - retain a bounded adapter error
            raise IntakeLabError(str(exc)[:500]) from exc

    def create_visual_refinement(self, run_id: str) -> dict[str, Any]:
        """Queue the one typed repair child from the stored visual critique."""
        safe_id = str(run_id or "").strip()
        parent = self._raw_local_run(safe_id)
        report = parent.get("quality_report_json") or {}
        raw_critique = report.get("visual_critique") if isinstance(report, Mapping) else None
        if not isinstance(raw_critique, Mapping):
            raise IntakeLabError("an actionable visual critique is required")
        try:
            from ..core.design_contracts import VisualCritiqueReport

            critique = VisualCritiqueReport.from_dict(raw_critique)
            created = self.design_service.create_visual_refinement_run(
                safe_id,
                critique,
                run_id=f"design-{uuid.uuid4().hex}",
            )
            child = created["run"]
            request = PageBuildRequest.from_dict(created["request"])
            target = BuildTarget.from_dict(created["target"])
            self.design_service.queue_build(child["run_id"], request, target)
            self.executor.enqueue(child["run_id"])
            return self.get_run(child["run_id"])
        except Exception as exc:  # noqa: BLE001 - keep the adapter boundary bounded
            raise IntakeLabError(str(exc)[:500]) from exc

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            bounded = max(1, min(int(limit), 100))
        except (TypeError, ValueError) as exc:
            raise IntakeLabError("limit is invalid") from exc
        runs = self._local_runs()
        return [self._project(run, detail=False, related_runs=runs) for run in runs[:bounded]]

    def get_run(self, run_id: str) -> dict[str, Any]:
        try:
            run = self._raw_local_run(run_id)
        except Exception as exc:  # noqa: BLE001 - prevent cross-service detail leakage
            raise IntakeLabError("Intake Lab run was not found") from exc
        return self._project(run, detail=True, related_runs=self._local_runs())

    def pages(self, run_id: str) -> list[str]:
        run = self._raw_local_run(run_id)
        intake = SiteIntake.from_dict(run.get("intake_json") or {})
        return list(intake.site.get("required_pages") or ())

    def preview_identity(self, run_id: str, variant: str) -> tuple[Path, str]:
        run = self._raw_local_run(run_id)
        variant = str(variant or "").strip().lower()
        if variant != "candidate":
            raise IntakeLabError("preview variant is invalid")
        sha = str(run.get("candidate_sha") or "").strip().lower()
        if not _SHA.fullmatch(sha):
            raise IntakeLabError("preview variant is not available")
        try:
            clone = _resolved(self.design_service.clone_path_for_run(run_id))
        except Exception:
            # A retained child can be visible through the scoped run graph while
            # its direct service lookup is briefly stale. Its experiment event
            # still records the immutable shared clone used for the preview.
            clone = self._experiment_root(run)
            if clone is None:
                raise IntakeLabError("preview clone is unavailable")
        workspace = self.workspace.resolve()
        if (
            clone is None
            or (clone != workspace and workspace not in clone.parents)
            or not (clone / ".git").is_dir()
        ):
            raise IntakeLabError("preview clone is outside the Intake Lab workspace")
        return clone, sha

    def preview_artifact_identity(self, run_id: str, variant: str = "candidate") -> tuple[Path, str] | None:
        """Resolve the immutable output tree retained by host validation.

        ``None`` is reserved for legacy runs that predate output artifacts; new
        candidates must carry both the artifact ID and its tree hash before the
        owner preview can use this path.
        """
        if str(variant or "").strip().lower() != "candidate":
            return None
        run = self._raw_local_run(run_id)
        artifact_required = bool(run.get("artifact_required"))
        artifact_id = str(run.get("output_artifact_id") or "").strip()
        tree_hash = str(run.get("output_tree_hash") or "").strip().lower()
        if not artifact_id or not tree_hash:
            if artifact_required:
                raise IntakeLabError("candidate output artifact is not retained")
            return None
        store = getattr(self.design_service, "output_artifact_store", None)
        resolver = getattr(store, "resolve", None)
        if not callable(resolver):
            if artifact_required:
                raise IntakeLabError("candidate output artifact store is unavailable")
            return None
        try:
            artifact = resolver(artifact_id)
        except Exception as exc:  # noqa: BLE001 - expose a bounded preview failure
            raise IntakeLabError("candidate output artifact is unavailable") from exc
        if str(getattr(artifact, "tree_hash", "") or "").lower() != tree_hash:
            raise IntakeLabError("candidate output artifact identity does not match the retained run")
        return Path(artifact.path).resolve(), artifact_id

    def preview_profile(self, run_id: str) -> str:
        """Return the persisted host-owned profile for an immutable candidate."""
        run = self._raw_local_run(run_id)
        resolver = getattr(self.design_service, "build_profile_for_run", None)
        if not callable(resolver):
            return ""
        try:
            return str(resolver(run_id) or "").strip()
        except Exception:
            parent_id = str(run.get("parent_run_id") or "").strip()
            if parent_id and parent_id != str(run_id):
                return self.preview_profile(parent_id)
            raise IntakeLabError("preview profile is unavailable")

    def live_preview_identity(self, run_id: str) -> tuple[Path, str]:
        """Resolve the latest immutable checkpoint without exposing its path."""
        if self.live_preview_store is None:
            raise IntakeLabError("live preview is not available")
        self._raw_local_run(run_id)
        try:
            latest = self.live_preview_store.latest(str(run_id))
        except Exception as exc:  # noqa: BLE001 - keep the preview boundary bounded
            raise IntakeLabError("live preview is unavailable") from exc
        if not latest:
            raise IntakeLabError("live preview is not available")
        snapshot, clone = latest
        if snapshot.run_id != str(run_id):
            raise IntakeLabError("live preview identity does not match the run")
        return Path(clone).resolve(), str(snapshot.commit_sha).lower()

    def live_preview_snapshot(self, run_id: str) -> dict[str, Any] | None:
        """Return the owner-safe latest checkpoint metadata."""
        if self.live_preview_store is None:
            return None
        try:
            self._raw_local_run(run_id)
            latest = self.live_preview_store.latest(str(run_id))
        except Exception:
            return None
        if not latest:
            return None
        snapshot, _ = latest
        return snapshot.to_dict()

    def _raw_local_run(self, run_id: str) -> dict[str, Any]:
        if not _RUN_ID.fullmatch(str(run_id or "")):
            raise IntakeLabError("Intake Lab run was not found")
        try:
            run = self.design_service.get_run(run_id)
        except Exception as exc:  # noqa: BLE001
            # The list projection is the authoritative scoped graph for a
            # retained child. Prefer an exact match over dropping back to the
            # parent when a direct lookup races a worker/database refresh.
            try:
                run = next(
                    (
                        item for item in self.design_service.list_runs(mode="local_experiment", limit=500)
                        if str(item.get("run_id") or "") == str(run_id)
                    ),
                    None,
                )
            except Exception:
                run = None
            if run is None:
                raise IntakeLabError("Intake Lab run was not found") from exc
        if run.get("mode") != "local_experiment" or run.get("publishable") is not False:
            raise IntakeLabError("Intake Lab run was not found")
        return run

    @staticmethod
    def _experiment_root(run: Mapping[str, Any]) -> Path | None:
        for event in reversed(run.get("events") or ()):
            if not isinstance(event, Mapping) or event.get("stage") != "experiment":
                continue
            detail = event.get("detail")
            if isinstance(detail, Mapping) and detail.get("root"):
                return _resolved(detail["root"])
        return None

    def _local_runs(self) -> list[dict[str, Any]]:
        """Load the bounded local run graph with complete event histories."""
        try:
            listed = self.design_service.list_runs(mode="local_experiment", limit=500)
        except Exception as exc:  # noqa: BLE001 - keep the adapter boundary stable
            raise IntakeLabError("Intake Lab runs are unavailable") from exc
        runs: list[dict[str, Any]] = []
        for listed_run in listed:
            run_id = str(listed_run.get("run_id") or "").strip()
            if not run_id:
                continue
            try:
                run = self.design_service.get_run(run_id)
            except Exception:
                run = listed_run
            if run.get("mode") == "local_experiment" and run.get("publishable") is False:
                runs.append(run)
        return runs

    def _project(
        self,
        run: Mapping[str, Any],
        *,
        detail: bool,
        related_runs: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if run.get("mode") != "local_experiment" or run.get("publishable") is not False:
            raise IntakeLabError("Intake Lab run was not found")
        intake = SiteIntake.from_dict(run.get("intake_json") or {})
        report = run.get("quality_report_json") if isinstance(run.get("quality_report_json"), Mapping) else {}
        visual = report.get("visual_critique") if isinstance(report, Mapping) else None
        visual_settings = self.describe()["visual_review"]
        events = run.get("events") if isinstance(run.get("events"), list) else []
        graph = list(related_runs or ())
        if not any(item.get("run_id") == run.get("run_id") for item in graph):
            graph.append(run)
        runs_by_id = {
            str(item.get("run_id")): item
            for item in graph
            if str(item.get("run_id") or "").strip()
        }
        root_id = _run_root_id(run, runs_by_id)
        revisions = sorted(
            (item for item in runs_by_id.values() if _run_root_id(item, runs_by_id) == root_id),
            key=_run_order,
        )
        revision_numbers = {str(item.get("run_id")): index for index, item in enumerate(revisions, start=1)}
        revision_number = revision_numbers.get(str(run.get("run_id")), 1)
        revision = _revision_summary(run, revision_number, root_id, runs_by_id, self.workspace)
        created_at = run.get("created_ts") or run.get("created_at")
        updated_at = run.get("updated_ts") or run.get("updated_at")
        status = str(run.get("status") or "failed")
        error = _redact_text(run.get("error"), self.workspace) if run.get("error") else None
        result = _result_projection(
            status,
            report,
            visual,
            error,
            operation_kind=str(run.get("operation_kind") or "initial_build"),
        )
        duration_end = updated_at if status in _TERMINAL else datetime.now(timezone.utc).isoformat(timespec="seconds")
        duration = _duration_seconds(created_at, duration_end)
        profile_resolver = getattr(getattr(self, "design_service", None), "build_profile_for_run", None)
        try:
            build_profile = str(profile_resolver(str(run.get("run_id") or "")) or "").strip() if callable(profile_resolver) else ""
        except Exception:
            build_profile = ""
        projected: dict[str, Any] = {
            "run_id": str(run.get("run_id") or ""),
            "mode": "local_experiment",
            "status": status,
            "owner_status": _owner_status(status, report, visual),
            "terminal": status in _TERMINAL,
            "operation_kind": str(run.get("operation_kind") or "initial_build"),
            "build_profile": build_profile or None,
            "business_name": str((intake.business or {}).get("name") or ""),
            "parent_run_id": str(run.get("parent_run_id") or "") or None,
            "source_candidate_sha": str(run.get("source_candidate_sha") or "") or None,
            "revision": revision,
            "revision_count": len(revisions),
            "candidate_available": bool(str(run.get("candidate_sha") or "").strip()),
            "implementation": {
                "provider": str(run.get("provider_id") or self.describe()["implementation"]["provider"]),
                "model": str(run.get("model_id") or self.describe()["implementation"]["model"]),
            },
            "visual_review": {
                "provider": visual_settings["provider"],
                "model": str((visual or {}).get("model_id") or visual_settings["model"]),
                "state": str((visual or {}).get("state") or "pending"),
                "findings": _safe_value((visual or {}).get("findings") or [], self.workspace),
                "strengths": _safe_value((visual or {}).get("strengths") or [], self.workspace),
                "repair_plan": _safe_value((visual or {}).get("repair_plan") or [], self.workspace),
            },
            "base_sha": str(run.get("base_sha") or "") or None,
            "candidate_sha": str(run.get("candidate_sha") or "") or None,
            "output_artifact_id": str(run.get("output_artifact_id") or "") or None,
            "output_tree_hash": str(run.get("output_tree_hash") or "") or None,
            "publishable": False,
            "push_mode": "none",
            "quality": _quality_projection(report, self.workspace),
            "pages": list(intake.site.get("required_pages") or ()),
            "events": [
                _event_projection(event, self.workspace)
                for event in events[-(500 if detail else 20):]
            ],
            "pipeline": _pipeline_projection(events, status, report, visual, created_at, updated_at, error),
            "result": result,
            "duration_seconds": duration,
            "duration_label": _duration_label(duration),
            "error": error,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        if detail:
            projected["owner_request"] = _redact_text(run.get("owner_request"), self.workspace)
            projected["revisions"] = [
                _revision_summary(item, index, root_id, runs_by_id, self.workspace)
                for index, item in enumerate(revisions, start=1)
            ]
            preferred = next(
                (
                    item for item in reversed(projected["revisions"])
                    if item.get("reviewable")
                ),
                None,
            )
            if preferred is None:
                preferred = next(
                    (
                        item for item in reversed(projected["revisions"])
                        if item.get("candidate_available")
                    ),
                    None,
                )
            preview_run = preferred or next(
                (
                    item for item in reversed(projected["revisions"])
                    if item.get("candidate_available")
                ),
                None,
            )
            projected["preferred_run_id"] = (
                str(preferred.get("run_id") or "")
                if preferred is not None else str(run.get("run_id") or "")
            )
            projected["preview_run_id"] = (
                str(preview_run.get("run_id") or "")
                if preview_run is not None else None
            )
        return projected


__all__ = [
    "IntakeLabError",
    "IntakeLabService",
    "build_intake_lab_build_environment",
    "build_intake_lab_environment",
    "validate_intake_lab_workspace",
]
