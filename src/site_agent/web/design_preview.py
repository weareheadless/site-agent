"""Portable design-candidate preview helpers.

The tenant API and the password-authenticated admin server both need to serve
the exact retained candidate output.  Keep the immutable-SHA and artifact
rules here so neither surface invents a second build or preview identity.
"""

from __future__ import annotations

import mimetypes
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..core.design_contracts import DesignRunStatus
from .preview import PreviewBuildCache, rewrite_preview_css, rewrite_preview_html, rewrite_preview_js


DESIGN_PREVIEW_REFS = {"original": "base_sha", "deepseek": "candidate_sha"}
DESIGN_PREVIEW_STATUSES = frozenset({
    DesignRunStatus.CANDIDATE_READY.value,
    DesignRunStatus.VALIDATING.value,
    DesignRunStatus.READY_FOR_REVIEW.value,
    DesignRunStatus.NEEDS_REPAIR.value,
    DesignRunStatus.INCOMPLETE.value,
    DesignRunStatus.INTERRUPTED.value,
    DesignRunStatus.FAILED.value,
    DesignRunStatus.CANCELLED.value,
})


def candidate_is_previewable(run: Mapping[str, Any]) -> bool:
    return bool(run.get("candidate_sha")) and str(run.get("status") or "") in DESIGN_PREVIEW_STATUSES


def preview_ref(run: Mapping[str, Any], variant: str = "deepseek") -> tuple[str, str]:
    normalized = str(variant or "deepseek").strip().lower()
    if normalized not in DESIGN_PREVIEW_REFS:
        raise ValueError("variant must be original or deepseek")
    field = DESIGN_PREVIEW_REFS[normalized]
    ref = str(run.get(field) or "").strip().lower()
    if not ref:
        raise ValueError(f"design run has no {normalized} preview revision")
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise ValueError(f"design run {field} is invalid")
    return normalized, ref


def build_profile(design_service: Any, run: Mapping[str, Any], variant: str) -> str:
    if variant == "original" and str(run.get("operation_kind") or "initial_build") == "initial_build":
        return ""
    resolver = getattr(design_service, "build_profile_for_run", None)
    if not callable(resolver):
        return ""
    try:
        return str(resolver(str(run.get("run_id") or "")) or "").strip()
    except Exception:  # noqa: BLE001 - historical rows may have no profile
        return ""


def output_artifact_root(design_service: Any, run: Mapping[str, Any]) -> Path | None:
    """Resolve a retained output artifact without rebuilding a current candidate."""
    if not bool(run.get("artifact_required")):
        return None
    artifact_id = str(run.get("output_artifact_id") or "").strip()
    tree_hash = str(run.get("output_tree_hash") or "").strip().lower()
    if not artifact_id or not tree_hash:
        raise ValueError("design output artifact is not retained")
    store = getattr(design_service, "output_artifact_store", None)
    resolver = getattr(store, "resolve", None)
    if not callable(resolver):
        raise ValueError("design output artifact store is unavailable")
    try:
        artifact = resolver(artifact_id)
    except Exception as exc:  # noqa: BLE001 - fail closed on artifact lookup
        raise ValueError("design output artifact is unavailable") from exc
    if str(getattr(artifact, "tree_hash", "") or "").strip().lower() != tree_hash:
        raise ValueError("design output artifact identity does not match the run")
    path = Path(getattr(artifact, "path", "")).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("design output artifact is unavailable")
    return path


def safe_preview_path(value: str) -> str:
    name = str(value or "").lstrip("/") or "index.html"
    path = PurePosixPath(name)
    if not path.parts or ".." in path.parts or name.startswith((".git/", ".opencode/")):
        raise ValueError("invalid design preview path")
    return str(path)


def list_html_at(clone: Path, ref: str) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(clone), "ls-tree", "-r", "--name-only", ref],
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return []
    paths = [
        line.strip()
        for line in proc.stdout.decode("utf-8", "replace").splitlines()
        if line.strip().lower().endswith((".html", ".htm"))
    ]
    paths.sort(key=lambda item: (item != "index.html", item))
    return paths


def render_candidate_file(
    design_service: Any,
    run: Mapping[str, Any],
    name: str,
    *,
    variant: str,
    access_token: str,
    preview_root: str,
    site_url: str = "",
    preview_cache: PreviewBuildCache,
) -> tuple[bytes, str]:
    """Read one candidate file from the retained artifact or exact SHA."""
    import subprocess as _subprocess

    name = safe_preview_path(name)
    selected_variant, selected_sha = preview_ref(run, variant)
    build_profile_name = build_profile(design_service, run, selected_variant)
    artifact_root = output_artifact_root(design_service, run) if selected_variant == "deepseek" else None
    clone = Path(design_service.clone_path_for_run(str(run.get("run_id") or ""))).expanduser().resolve()
    if artifact_root is None and (not clone.exists() or not (clone / ".git").exists()):
        raise FileNotFoundError("design candidate clone is unavailable")

    content = (
        preview_cache.read_artifact(artifact_root, name)
        if artifact_root is not None
        else preview_cache.read_file(
            clone,
            selected_sha,
            name,
            profile=build_profile_name,
        )
    )
    if not content and artifact_root is None:
        proc = _subprocess.run(
            ["git", "-C", str(clone), "show", f"{selected_sha}:{name}"],
            capture_output=True,
            timeout=30,
        )
        content = proc.stdout if proc.returncode == 0 else b""
    if not content:
        raise FileNotFoundError(f"{name} not in design candidate")

    if name.lower().endswith((".html", ".htm")):
        content = rewrite_preview_html(
            content,
            str(run.get("run_id") or ""),
            name,
            site_url,
            access_token,
            selected_variant,
            preview_root,
        )
    elif name.lower().endswith(".css"):
        content = rewrite_preview_css(content, name, access_token, selected_variant)
    elif name.lower().endswith((".js", ".mjs")):
        content = rewrite_preview_js(content, access_token, selected_variant)
    return content, mimetypes.guess_type(name)[0] or "application/octet-stream"
