"""Disposable, local-only orchestration for Next/React/Payload design experiments."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import copy
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..brain.design_guidance import DesignSkillSet, load_design_skills
from ..application.designs import DesignService
from ..core.contracts import ContractError, safe_provider_message
from ..core.design_contracts import (
    DesignRunStatus,
    SiteIntake,
    canonical_hash,
    canonical_json,
)
from ..core.memory import Memory
from ..credentials import github_ssh_command
from ..hands.design_lab_git import (
    add_worktree,
    baseline_sha,
    clone_source,
    design_lab_environment,
    remove_worktree,
    remote_refs,
)
from ..hands.builder import NativeOpenCodeBuilder
from ..hands.design_quality import QualityPolicy, run_quality_gates
from ..hands.site_build import (
    NEXT_REACT_PROFILE,
    PELICAN_BASELINE_PROFILE,
    SiteBuildResult,
    SiteOutputArtifactStore,
    build_site,
    copy_build_output,
    get_build_profile,
)


class DesignLabError(RuntimeError):
    """The design-lab request cannot be started safely."""


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _resolve_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    return Path(text).expanduser().resolve(strict=False) if text else None


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def path_sentinel(path: str | Path) -> dict[str, Any]:
    """Hash a live path without retaining its contents."""
    root = Path(path).expanduser().resolve(strict=False)
    if not root.exists() and not root.is_symlink():
        return {"path": str(root), "exists": False, "digest": "", "files": 0, "bytes": 0}
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0

    def add(label: str, value: str) -> None:
        digest.update(label.encode("utf-8", "replace"))
        digest.update(b"\0")
        digest.update(value.encode("utf-8", "replace"))
        digest.update(b"\0")

    if root.is_symlink():
        add("symlink", os.readlink(root))
        return {"path": str(root), "exists": True, "kind": "symlink", "digest": digest.hexdigest(), "files": 0, "bytes": 0}
    if root.is_file():
        file_digest, size = _file_digest(root)
        add("file", f"{root.name}:{size}:{file_digest}")
        return {"path": str(root), "exists": True, "kind": "file", "digest": digest.hexdigest(), "files": 1, "bytes": size}
    for child in sorted(root.rglob("*"), key=lambda item: str(item.relative_to(root))):
        relative = str(child.relative_to(root)).replace("\\", "/")
        if child.is_symlink():
            add("symlink", f"{relative}:{os.readlink(child)}")
            continue
        if not child.is_file():
            continue
        file_digest, size = _file_digest(child)
        add("file", f"{relative}:{size}:{file_digest}")
        file_count += 1
        total_bytes += size
    return {"path": str(root), "exists": True, "kind": "directory", "digest": digest.hexdigest(), "files": file_count, "bytes": total_bytes}


def _config_live_paths(config: Mapping[str, Any]) -> tuple[Path, ...]:
    site = config.get("site") or {}
    values = [
        site.get("clone_path"),
        site.get("data_dir"),
        site.get("repository_path"),
        config.get("data_dir"),
        config.get("repository_path"),
    ]
    repository = str(site.get("repository") or "").strip()
    if repository and "/" not in repository and Path(repository).expanduser().exists():
        values.append(repository)
    result: list[Path] = []
    for value in values:
        resolved = _resolve_path(value)
        if resolved is not None and resolved not in result:
            result.append(resolved)
    return tuple(result)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _safe_run_id(value: str | None = None) -> str:
    run_id = str(value or f"design-lab-{uuid.uuid4().hex}").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", run_id):
        raise DesignLabError("run id is invalid")
    return run_id


def _advance(memory: Memory, run_id: str, status: DesignRunStatus, message: str) -> None:
    current = memory.get_design_run(run_id)
    if current is None:
        raise DesignLabError(f"design-lab run disappeared: {run_id}")
    if current["status"] == status.value:
        return
    try:
        memory.transition_design_run(run_id, status.value)
    except ContractError as exc:
        raise DesignLabError(str(exc)) from exc
    memory.add_design_run_event(run_id, status.value, message)


def _site_digest(root: Path) -> dict[str, Any]:
    ignored = {".git", "output", "out", ".next", ".open-next", "dist", "node_modules"}
    digest = hashlib.sha256()
    files = 0
    for path in sorted(root.rglob("*"), key=lambda item: str(item.relative_to(root))):
        if not path.is_file() or any(part in ignored for part in path.relative_to(root).parts):
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        try:
            file_hash, size = _file_digest(path)
        except OSError:
            continue
        digest.update(f"{relative}:{size}:{file_hash}\0".encode())
        files += 1
    return {"files": files, "sha256": digest.hexdigest()}


def _site_design_reference(root: Path) -> str:
    """Return a compact structural/style summary of the immutable baseline."""
    try:
        from ..hands.site_digest import build

        return build(root, ref="HEAD")
    except Exception:  # noqa: BLE001 - reference evidence must never block planning
        return ""


def _artifact_routes(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(path.relative_to(root)).replace("\\", "/")
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".html", ".htm"}
        )
    )


def _quality_policy(
    *,
    output_dir: str,
    required_pages: tuple[str, ...],
    allowed_patterns: tuple[str, ...],
    required_content: tuple[str, ...] = (),
    browser_required: bool,
    expected_intake_hash: str = "",
    manifest_path: str = "",
    allow_toolchain: tuple[str, ...] = (),
    ignored_pages: tuple[str, ...] = (),
    approved_capabilities: tuple[dict[str, Any], ...] = (),
) -> QualityPolicy:
    return QualityPolicy(
        output_dir=output_dir,
        required_pages=required_pages,
        required_content=required_content,
        allowed_patterns=allowed_patterns,
        prohibited_paths=(".env", ".github", "node_modules", "dist"),
        build_command=None,
        browser_required=browser_required,
        manifest_path=manifest_path,
        expected_intake_hash=expected_intake_hash,
        allowed_hard_denied_paths=allow_toolchain,
        ignored_pages=ignored_pages,
        approved_capabilities=approved_capabilities,
    )


class DesignComparisonService:
    """Compare retained public artifacts without choosing a winner."""

    def compare(
        self,
        workspace: str | Path,
        run_id: str,
        *,
        baseline_routes: tuple[str, ...],
        candidate_routes: tuple[str, ...],
        quality: Mapping[str, Any],
    ) -> dict[str, Any]:
        root = Path(workspace).expanduser().resolve()
        baseline = set(baseline_routes)
        candidate = set(candidate_routes)
        paths = sorted(baseline | candidate, key=lambda item: (item not in {"index.html", "index.htm"}, item))
        pairs = [
            {
                "path": path,
                "baseline": f"/artifacts/{run_id}/baseline/{path}" if path in baseline else None,
                "candidate": f"/artifacts/{run_id}/candidate/{path}" if path in candidate else None,
            }
            for path in paths
        ]
        return {
            "schema_version": 1,
            "run_id": run_id,
            "pages": pairs,
            "baseline_only": sorted(baseline - candidate),
            "candidate_only": sorted(candidate - baseline),
            "quality": dict(quality),
            "artifact_root": str(root / "artifacts" / run_id),
        }


class DesignLabService:
    """Run a complete design experiment in a workspace isolated from the site."""

    def __init__(
        self,
        config: Mapping[str, Any],
        workspace: str | Path,
        *,
        env: Mapping[str, str] | None = None,
        builder: Any | None = None,
        browser_factory: Callable[..., Any] | None = None,
        timeout_seconds: int = 900,
        skill_set: DesignSkillSet | None = None,
    ) -> None:
        self.config = dict(config)
        self.workspace = Path(workspace).expanduser().resolve()
        self.env = dict(env or os.environ)
        self.builder = builder
        self.browser_factory = browser_factory
        self.timeout_seconds = max(1, min(int(timeout_seconds), 1800))
        self.skill_set = skill_set

    def _validate_workspace(self) -> None:
        if self.workspace == Path(self.workspace.anchor):
            raise DesignLabError("design-lab workspace is too broad")
        for live in _config_live_paths(self.config):
            if _overlaps(self.workspace, live):
                raise DesignLabError(f"design-lab workspace overlaps a live path: {live}")
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _browser(self, screenshot_root: Path, variant: str, enabled: bool, routes: tuple[str, ...] = ()) -> Any | None:
        if not enabled:
            return None
        if self.browser_factory is not None:
            return self.browser_factory(screenshot_root, variant=variant, routes=routes)
        from ..hands.playwright_quality import PlaywrightQualityAdapter

        return PlaywrightQualityAdapter(screenshot_root, variant=variant, routes=routes)

    def generate(
        self,
        intake: SiteIntake,
        *,
        browser: bool = True,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Run one local experiment through the native source-authoring path.

        The design lab is intentionally a thin retained-artifact wrapper around
        :class:`DesignService`.  It may build the existing source for a
        comparison view, but it never plans a visual spec or emits a host-owned
        page.  The candidate is authored by OpenCode in an isolated worktree
        and is retained only in the lab's local Git ref.
        """
        if not isinstance(intake, SiteIntake):
            raise DesignLabError("design-lab requires a validated SiteIntake")
        self._validate_workspace()
        run_id = _safe_run_id(run_id)
        source_root = self.workspace / "source.git-or-clone"
        worktrees = self.workspace / "worktrees"
        reports = self.workspace / "reports" / run_id
        artifacts = self.workspace / "artifacts" / run_id
        screenshots = self.workspace / "screenshots" / run_id
        npm_cache = self.workspace / "npm-cache"
        reports.mkdir(parents=True, exist_ok=True)
        artifacts.mkdir(parents=True, exist_ok=True)
        lab_env = design_lab_environment(
            self.env,
            model_env_name=str((self.config.get("env") or {}).get("llm_api_key") or ""),
            git_ssh_command=github_ssh_command(self.config, self.env),
        )
        live_paths = _config_live_paths(self.config)
        live_before = {str(path): path_sentinel(path) for path in live_paths}
        source: Path | None = None
        remote_before: dict[str, str] = {}
        remote_after: dict[str, str] = {}
        memory: Memory | None = None
        design_service: DesignService | None = None
        baseline_tree: Path | None = None
        candidate_tree: Path | None = None
        run_created = False
        base_sha = ""
        candidate_sha = ""
        candidate_ref = f"refs/ada-design-lab/{run_id}"
        error = ""
        baseline_build: SiteBuildResult | None = None
        candidate_build: SiteBuildResult | None = None
        baseline_quality: dict[str, Any] | None = None
        candidate_quality: dict[str, Any] | None = None
        quality: dict[str, Any] = {}
        comparison: dict[str, Any] = {}
        try:
            site = self.config.get("site") or {}
            repository = str(site.get("repository") or "").strip()
            local_source = _resolve_path(site.get("clone_path"))
            if local_source is not None and (local_source / ".git").exists():
                # A configured checkout is the authoritative local source for
                # the lab. Do not turn a private repository into an anonymous
                # HTTPS fetch merely because a public repository slug is also
                # present in the tenant config.
                repository = str(local_source)
            branch = str(site.get("branch") or "main").strip()
            if not repository:
                raise DesignLabError("site.repository is required for design-lab")
            source = clone_source(repository, source_root, branch=branch, env=lab_env)
            remote_before = remote_refs(source, env=lab_env)
            base_sha = baseline_sha(source, branch, env=lab_env)
            memory = Memory(self.workspace / "data" / "design-lab.db")
            local_config = copy.deepcopy(self.config)
            local_config["data_dir"] = str(self.workspace / "data")
            local_engine = dict(local_config.get("design_engine") or {})
            local_engine["enabled"] = True
            quality_config = dict(local_engine.get("quality") or {})
            quality_config.setdefault("browser", browser)
            quality_config.setdefault("manifest_path", "design/ada-design-manifest.json")
            quality_config.setdefault("native_source_required", True)
            quality_config.setdefault("originality_required", True)
            local_engine["build_profile"] = str(local_engine.get("build_profile") or NEXT_REACT_PROFILE.name).strip()
            if local_engine["build_profile"] != NEXT_REACT_PROFILE.name:
                raise DesignLabError("design_engine.build_profile must be next_react")
            quality_config["allowed_patterns"] = list(NEXT_REACT_PROFILE.writable_patterns)
            quality_config.setdefault("required_pages", list(intake.site.get("required_pages") or ("index.html",)))
            local_engine["quality"] = quality_config
            local_config["design_engine"] = local_engine
            local_config["builder"] = {
                **dict(local_config.get("builder") or {}),
                "enabled": True,
                "timeout_seconds": self.timeout_seconds,
            }
            # Do not add the lab clone to site.clone_path.  DesignService uses
            # the persisted experiment event to resolve it, while treating the
            # configured customer paths as live paths for overlap protection.
            design_service = DesignService(
                memory,
                config=local_config,
                skill_set=self.skill_set,
                output_artifact_store=SiteOutputArtifactStore(self.workspace / "output-artifacts"),
            )
            run = design_service.create_experiment(
                intake,
                experiment_root=source,
                base_sha=base_sha,
                run_id=run_id,
            )
            run_created = True
            skill_set = self.skill_set or load_design_skills()
            memory.add_design_run_event(run_id, "lab", "Native OpenCode design-lab run reserved.", {
                "workspace": str(self.workspace),
                "base_sha": base_sha,
                "builder": "native_opencode",
            })
            request = design_service.prepare_initial_request(run_id)
            target = design_service.build_target_for_run(run_id)
            if self.builder is None:
                builder_context = {
                    "config": local_config,
                    "memory": memory,
                    "env": lab_env,
                    "build_env": lab_env,
                    "design_skill_set": skill_set,
                }
                design_service.builder = NativeOpenCodeBuilder(builder_context)
            else:
                design_service.builder = self.builder

            # Keep the old comparison surface, but make its baseline profile
            # follow the source's actual toolchain.  Legacy Pelican repositories
            # still compare with Pelican; canonical design candidates use Next.
            worktrees.mkdir(parents=True, exist_ok=True)
            baseline_tree = add_worktree(source, worktrees / "baseline", base_sha, env=lab_env)
            baseline_profile_name = str(quality_config.get("baseline_profile") or "").strip()
            if not baseline_profile_name:
                baseline_profile_name = (
                    NEXT_REACT_PROFILE.name
                    if (baseline_tree / "package.json").is_file()
                    else PELICAN_BASELINE_PROFILE.name
                )
            baseline_profile = get_build_profile(baseline_profile_name)
            baseline_build = build_site(
                baseline_tree,
                baseline_profile,
                npm_cache=npm_cache,
                env=lab_env,
                timeout_seconds=self.timeout_seconds,
            )
            _write_json(reports / "baseline-build.json", baseline_build.to_dict())
            baseline_routes: tuple[str, ...] = ()
            if baseline_build.ok:
                copy_build_output(baseline_tree, baseline_profile, artifacts / "baseline")
                baseline_routes = _artifact_routes(artifacts / "baseline")

            memory.add_design_run_event(run_id, "building", "OpenCode is authoring the complete candidate source.")
            design_service.execute_build(
                run_id,
                request,
                target,
                progress=lambda message: None,
            )
            persisted = design_service.get_run(run_id)
            candidate_sha = str(persisted.get("candidate_sha") or "")
            candidate_ref = str(persisted.get("candidate_ref") or candidate_ref)
            if not candidate_sha:
                raise DesignLabError("native OpenCode build did not retain a candidate SHA")

            candidate_tree = add_worktree(source, worktrees / "candidate", candidate_sha, env=lab_env)
            candidate_build = build_site(
                candidate_tree,
                NEXT_REACT_PROFILE,
                npm_cache=npm_cache,
                env=lab_env,
                timeout_seconds=self.timeout_seconds,
            )
            _write_json(reports / "candidate-build.json", candidate_build.to_dict())
            if candidate_build.ok:
                copy_build_output(candidate_tree, NEXT_REACT_PROFILE, artifacts / "candidate")
                for relative in ("design/ada-design-manifest.json", "design/ada-route-manifest.json"):
                    source_file = candidate_tree / relative
                    target_file = artifacts / "candidate" / relative
                    if source_file.is_file() and not source_file.is_symlink():
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        target_file.write_bytes(source_file.read_bytes())

            required_pages = tuple(str(item) for item in (intake.site.get("required_pages") or ("index.html",)))
            baseline_ignored_pages = tuple(str(item) for item in (quality_config.get("baseline_ignored_pages") or ()))
            baseline_policy = _quality_policy(
                output_dir=baseline_profile.output_dir,
                required_pages=required_pages,
                allowed_patterns=(f"{baseline_profile.output_dir}/**",),
                browser_required=browser,
                ignored_pages=baseline_ignored_pages,
            )
            baseline_browser = self._browser(screenshots, "baseline", browser, required_pages)
            baseline_report = (
                run_quality_gates(
                    baseline_tree,
                    base_sha=base_sha,
                    candidate_sha=base_sha,
                    run_id=run_id,
                    policy=baseline_policy,
                    browser=baseline_browser,
                    build_evidence=baseline_build.to_dict(),
                )
                if baseline_build.ok
                else None
            )
            baseline_quality = (
                baseline_report.to_dict()
                if baseline_report is not None
                else {"state": "incomplete", "reason": "baseline_build_failed"}
            )

            candidate_routes = _artifact_routes(artifacts / "candidate")
            candidate_browser = self._browser(screenshots, "candidate", browser, required_pages)
            candidate_report = design_service.validate_run(
                run_id,
                source,
                browser=candidate_browser,
                build_env=lab_env,
            )
            candidate_quality = candidate_report.to_dict()
            candidate_state = str(candidate_quality.get("state") or "failed")
            baseline_state = str((baseline_quality or {}).get("state") or "failed")
            # Existing-site defects are retained as evidence, but must not make
            # a clean, immutable candidate ineligible for owner review.
            quality_state = candidate_state
            quality = {
                "state": quality_state,
                "baseline_state": baseline_state,
                "baseline_findings_non_blocking": baseline_state != "passed",
                "baseline": baseline_quality,
                "candidate": candidate_quality,
            }
            _write_json(reports / "quality.json", {"schema_version": 1, "run_id": run_id, "state": quality_state, **quality})
            comparison = DesignComparisonService().compare(
                self.workspace,
                run_id,
                baseline_routes=baseline_routes,
                candidate_routes=candidate_routes,
                quality=quality,
            )
            _write_json(reports / "comparison.json", comparison)
            memory.update_design_run(
                run_id,
                quality_report_json={"state": quality_state, **quality},
                quality_report_hash=canonical_hash({"state": quality_state, **quality}),
            )
            if candidate_state != "passed":
                raise DesignLabError(f"quality gates are {quality_state}")
            if memory.get_design_run(run_id)["status"] == DesignRunStatus.VALIDATING.value:
                _advance(memory, run_id, DesignRunStatus.READY_FOR_REVIEW, "Local candidate passed all configured quality gates; no approval action exists in design-lab mode.")
        except Exception as exc:  # noqa: BLE001 - retain every failed run as inspectable evidence
            error = safe_provider_message(str(exc), max_chars=800)
            if memory is not None and run_created:
                try:
                    current = memory.get_design_run(run_id)
                    if current and current["status"] not in {DesignRunStatus.FAILED.value, DesignRunStatus.CANCELLED.value}:
                        memory.transition_design_run(run_id, DesignRunStatus.FAILED.value, error=error)
                        memory.add_design_run_event(run_id, "failed", "Design-lab run failed without production mutation.", {"error": error})
                except Exception:
                    pass
        finally:
            if source is not None:
                if baseline_tree is not None:
                    remove_worktree(source, baseline_tree, env=lab_env)
                if candidate_tree is not None:
                    remove_worktree(source, candidate_tree, env=lab_env)
                try:
                    remote_after = remote_refs(source, env=lab_env)
                except Exception:
                    remote_after = {}
            live_after = {str(path): path_sentinel(path) for path in live_paths}
            remote_unchanged = bool(source is not None and remote_before == remote_after)
            live_unchanged = live_before == live_after
            if not remote_unchanged or not live_unchanged:
                safety_error = "design-lab immutability sentinel failed"
                error = f"{error}; {safety_error}" if error else safety_error
                if memory is not None and run_created:
                    try:
                        current = memory.get_design_run(run_id)
                        if current and current["status"] not in {DesignRunStatus.FAILED.value, DesignRunStatus.CANCELLED.value}:
                            memory.transition_design_run(run_id, DesignRunStatus.FAILED.value, error=safety_error)
                            memory.add_design_run_event(run_id, "failed", safety_error)
                    except Exception:
                        pass
            result = {
                "schema_version": 1,
                "ok": not bool(error) and bool(candidate_sha) and bool(candidate_quality and candidate_quality.get("state") == "passed"),
                "run_id": run_id,
                "workspace": str(self.workspace),
                "baseline_sha": base_sha,
                "candidate_sha": candidate_sha,
                "candidate_ref": candidate_ref,
                "quality": quality,
                "remote_refs_unchanged": remote_unchanged,
                "live_paths_unchanged": live_unchanged,
                "live_path_sentinels": {"before": live_before, "after": live_after},
                "remote_refs": {"before": remote_before, "after": remote_after},
                "artifacts": {
                    "baseline": str(artifacts / "baseline"),
                    "candidate": str(artifacts / "candidate"),
                    "reports": str(reports),
                    "screenshots": str(screenshots),
                },
                "comparison": comparison,
                "source_authoring": {
                    "builder": "native_opencode",
                    "session_id": str((memory.get_design_run(run_id) if memory is not None and run_created else {}).get("opencode_session_id") or ""),
                },
                "error": error,
            }
            _write_json(reports / "run.json", result)
            if memory is not None:
                memory.close()
        return result

    @staticmethod
    def load_retained(workspace: str | Path, run_id: str) -> dict[str, Any]:
        root = Path(workspace).expanduser().resolve()
        run_id = _safe_run_id(run_id)
        path = root / "reports" / run_id / "run.json"
        if not path.is_file() or path.is_symlink():
            raise DesignLabError(f"retained design-lab run does not exist: {run_id}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DesignLabError(f"retained design-lab run is unreadable: {run_id}") from exc
        if not isinstance(value, dict) or value.get("run_id") != run_id:
            raise DesignLabError("retained design-lab run identity is invalid")
        return value


__all__ = ["DesignComparisonService", "DesignLabError", "DesignLabService", "path_sentinel"]
