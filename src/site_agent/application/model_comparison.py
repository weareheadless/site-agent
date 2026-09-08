"""Validation and read models for retained multi-model design-lab runs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ModelComparisonError(RuntimeError):
    """A model comparison manifest or retained artifact is invalid."""


_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_VARIANTS = {"baseline", "candidate"}


def _safe_model_id(value: str) -> str:
    result = str(value or "").strip()
    if not _MODEL_ID.fullmatch(result):
        raise ModelComparisonError("invalid model comparison id")
    return result


def _safe_run_id(value: str) -> str:
    result = str(value or "").strip()
    if not _RUN_ID.fullmatch(result):
        raise ModelComparisonError("invalid retained design-lab run id")
    return result


def _safe_relative_path(value: str) -> str:
    result = str(value or "").replace("\\", "/").lstrip("/")
    if not result or any(part in {"", ".", ".."} for part in result.split("/")):
        raise ModelComparisonError("invalid model comparison artifact path")
    return result


def _read_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ModelComparisonError(f"retained comparison file does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelComparisonError(f"retained comparison file is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ModelComparisonError(f"retained comparison file is not an object: {path}")
    return value


def _workspace(root: Path, value: Any) -> Path:
    raw = Path(str(value or "")).expanduser()
    candidate = (raw if raw.is_absolute() else root / raw).resolve(strict=False)
    if candidate == root or root not in candidate.parents:
        raise ModelComparisonError("model comparison workspace must stay under the manifest directory")
    return candidate


def _comparison_pages(workspace: Path, run_id: str, run: dict[str, Any]) -> tuple[str, ...]:
    comparison = run.get("comparison")
    if not isinstance(comparison, dict):
        comparison_path = workspace / "reports" / run_id / "comparison.json"
        if not comparison_path.is_file() or comparison_path.is_symlink():
            return ()
        comparison = _read_object(comparison_path)
    raw_pages = comparison.get("pages") or []
    if not isinstance(raw_pages, list):
        raise ModelComparisonError(f"retained model comparison pages are invalid: {run_id}")
    pages: list[str] = []
    for raw_page in raw_pages:
        if not isinstance(raw_page, dict):
            raise ModelComparisonError(f"retained model comparison page is invalid: {run_id}")
        page = _safe_relative_path(raw_page.get("path", ""))
        if page not in pages:
            pages.append(page)
    return tuple(pages)


@dataclass(frozen=True)
class ModelComparisonEntry:
    id: str
    label: str
    model: str
    workspace: Path
    run_id: str
    run: dict[str, Any]
    status: str
    error: str
    pages: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        candidates = {
            page: f"/model-artifacts/{self.id}/{self.run_id}/candidate/{page}"
            for page in self.pages
            if self.run_id
        }
        quality = self.run.get("quality")
        return {
            "id": self.id,
            "label": self.label,
            "model": self.model,
            "run_id": self.run_id,
            "status": self.status,
            "ok": bool(self.run.get("ok")),
            "error": self.error,
            "candidate_sha": str(self.run.get("candidate_sha") or ""),
            "baseline_sha": str(self.run.get("baseline_sha") or ""),
            "quality": quality if isinstance(quality, dict) else {},
            "candidates": candidates,
        }


@dataclass(frozen=True)
class ModelComparison:
    manifest_path: Path
    comparison_id: str
    subject: str
    models: tuple[ModelComparisonEntry, ...]
    pages: tuple[str, ...]

    def _entry(self, model_id: str) -> ModelComparisonEntry:
        model_id = _safe_model_id(model_id)
        for entry in self.models:
            if entry.id == model_id:
                return entry
        raise ModelComparisonError("model comparison entry was not found")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "comparison_id": self.comparison_id,
            "subject": self.subject,
            "models": [entry.to_dict() for entry in self.models],
            "pages": list(self.pages),
        }

    def artifact_path(self, model_id: str, run_id: str, variant: str, relative: str) -> Path:
        entry = self._entry(model_id)
        if variant not in _VARIANTS:
            raise ModelComparisonError("unknown model comparison artifact variant")
        if not entry.run_id or _safe_run_id(run_id) != entry.run_id:
            raise ModelComparisonError("retained run does not belong to model comparison entry")
        relative = _safe_relative_path(relative)
        base = (entry.workspace / "artifacts" / entry.run_id / variant).resolve(strict=False)
        target = (base / relative).resolve(strict=False)
        if base == target or base not in target.parents or target.is_symlink() or not target.is_file():
            raise ModelComparisonError("model comparison artifact was not found")
        return target


def load_model_comparison(manifest_path: str | Path) -> ModelComparison:
    """Load a manifest and only expose workspaces beneath its own directory."""
    path = Path(manifest_path).expanduser().resolve(strict=False)
    raw = _read_object(path)
    if raw.get("schema_version") != 1:
        raise ModelComparisonError("unsupported model comparison schema version")
    raw_models = raw.get("models")
    if not isinstance(raw_models, list) or not 1 <= len(raw_models) <= 8:
        raise ModelComparisonError("model comparison must contain between one and eight models")

    root = path.parent
    entries: list[ModelComparisonEntry] = []
    seen: set[str] = set()
    all_pages: list[str] = []
    for raw_model in raw_models:
        if not isinstance(raw_model, dict):
            raise ModelComparisonError("model comparison model entries must be objects")
        model_id = _safe_model_id(raw_model.get("id", ""))
        if model_id in seen:
            raise ModelComparisonError("model comparison model ids must be unique")
        seen.add(model_id)
        workspace = _workspace(root, raw_model.get("workspace"))
        run_id = str(raw_model.get("run_id") or "").strip()
        if run_id:
            run_id = _safe_run_id(run_id)
        run: dict[str, Any] = {}
        error = str(raw_model.get("error") or "")
        if run_id:
            run_path = workspace / "reports" / run_id / "run.json"
            if run_path.is_file() and not run_path.is_symlink():
                run = _read_object(run_path)
                if run.get("run_id") != run_id:
                    raise ModelComparisonError(f"retained run identity is invalid: {run_id}")
            elif not error:
                error = f"retained run does not exist: {run_id}"
        pages = _comparison_pages(workspace, run_id, run) if run_id and run else ()
        for page in pages:
            if page not in all_pages:
                all_pages.append(page)
        status = str(raw_model.get("status") or "").strip()
        if not status:
            status = "passed" if run.get("ok") else ("failed" if run else "not_started")
        entries.append(ModelComparisonEntry(
            id=model_id,
            label=str(raw_model.get("label") or model_id),
            model=str(raw_model.get("model") or ""),
            workspace=workspace,
            run_id=run_id,
            run=run,
            status=status,
            error=error,
            pages=pages,
        ))

    return ModelComparison(
        manifest_path=path,
        comparison_id=str(raw.get("comparison_id") or path.stem),
        subject=str(raw.get("subject") or "Design comparison"),
        models=tuple(entries),
        pages=tuple(all_pages),
    )


__all__ = ["ModelComparison", "ModelComparisonEntry", "ModelComparisonError", "load_model_comparison"]
