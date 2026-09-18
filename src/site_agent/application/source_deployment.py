"""Build an exact GitHub source revision and deploy the single Atelier Worker.

GitHub is the version ledger for this proof of concept.  This service validates
the requested commit in an isolated worktree and then deploys that exact
checkout to the one configured Worker URL.  It deliberately does not create
Cloudflare preview aliases or ask the owner to chase a new URL after every
test.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..config import load_env_file
from ..hands.github_static import GithubStatic


class SourceDeploymentError(RuntimeError):
    """A source revision could not be validated or deployed."""


_BRANCH = re.compile(r"^[A-Za-z0-9._/-]+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


class SourceDeploymentService:
    """Run source validation and deploy one exact GitHub revision."""

    def __init__(self, config: Mapping[str, Any], env: Mapping[str, str] | None = None, *, memory: Any | None = None) -> None:
        self.config = dict(config)
        self.env = dict(os.environ if env is None else env)
        self.memory = memory
        self.adapter = GithubStatic(self.config, self.env)
        saved = memory.kv_get("atelier_source_preview_jobs", {}) if memory is not None else {}
        self._jobs = dict(saved) if isinstance(saved, Mapping) else {}
        for job in self._jobs.values():
            if isinstance(job, dict) and job.get("status") in {"queued", "running"}:
                job.update({"status": "failed", "ok": False, "error": "source deployment process restarted", "updated_at": _now()})
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="atelier-source-build")
        self._persist()

    def _persist(self) -> None:
        if self.memory is None:
            return
        # Keep the durable audit trail bounded while retaining recent commit /
        # deployment records for owner review.
        rows = sorted(
            (dict(value) for value in self._jobs.values() if isinstance(value, Mapping)),
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )[:20]
        self.memory.kv_set("atelier_source_preview_jobs", {str(row.get("id")): row for row in rows if row.get("id")})

    @property
    def site(self) -> Mapping[str, Any]:
        return _mapping(self.config.get("site"))

    @property
    def settings(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for candidate in (
            self.site.get("source_deployment"),
            self.config.get("source_deployment"),
        ):
            if isinstance(candidate, Mapping):
                result.update(candidate)
        return result

    def _branch(self, value: Any) -> str:
        branch = str(value or self.site.get("preview_branch") or "preview").strip()
        if not branch or not _BRANCH.fullmatch(branch) or branch.startswith("/") or branch.endswith("/") or ".." in Path(branch).parts:
            raise SourceDeploymentError("source deployment branch is invalid")
        return branch

    def _local_checkout(self) -> Path:
        raw = str(self.settings.get("clone_path") or self.site.get("clone_path") or "").strip()
        if not raw:
            raise SourceDeploymentError("source deployment clone_path is not configured")
        path = Path(raw).expanduser().resolve()
        if not (path / ".git").exists():
            raise SourceDeploymentError("source deployment clone_path is not a Git checkout")
        return path

    def _env_name(self, setting: str, default: str) -> str:
        return str(self.settings.get(setting) or default).strip()

    def _resolved_env(self) -> dict[str, str]:
        env_file = str(self.settings.get("cloudflare_env_file") or "").strip()
        return load_env_file(env_file, self.env) if env_file else dict(self.env)

    def _child_env(self) -> dict[str, str]:
        child = self._resolved_env()
        node_path = str(self.settings.get("node_path") or "").strip()
        if node_path:
            child["PATH"] = f"{node_path}:{child.get('PATH') or os.environ.get('PATH', '')}"
        ssh_command = str(self.settings.get("git_ssh_command") or "").strip()
        if not ssh_command:
            key = Path("/ATELIER/atelier-github_ed25519")
            if key.is_file():
                ssh_command = f"ssh -i {key} -o IdentitiesOnly=yes"
        if ssh_command:
            child["GIT_SSH_COMMAND"] = ssh_command
        token_name = self._env_name("cloudflare_api_token_env", "CLOUDFLARE_API_TOKEN")
        account_name = self._env_name("cloudflare_account_id_env", "CLOUDFLARE_ACCOUNT_ID")
        token = child.get(token_name, "")
        account = child.get(account_name, "")
        if token:
            child["CLOUDFLARE_API_TOKEN"] = token
        if account:
            child["CLOUDFLARE_ACCOUNT_ID"] = account
        return child

    def _run(self, command: list[str], cwd: Path, *, timeout: int) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                command,
                cwd=str(cwd),
                env=self._child_env(),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SourceDeploymentError(f"command failed: {' '.join(command[:4])}: {str(exc)[:300]}") from exc
        if result.returncode:
            output = (result.stderr or result.stdout or "command failed").strip()
            raise SourceDeploymentError(f"{' '.join(command[:4])}: {output[-1_500:]}")
        return result

    def _head(self, branch: str) -> str:
        get_head = getattr(self.adapter, "get_branch_head", None)
        if not callable(get_head):
            raise SourceDeploymentError("GitHub adapter cannot resolve the deployment branch head")
        try:
            head = str(get_head(branch) or "").strip().lower()
        except Exception as exc:  # noqa: BLE001 - normalize adapter details
            raise SourceDeploymentError(str(exc)[:500]) from exc
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            raise SourceDeploymentError("GitHub returned an invalid deployment branch head")
        return head

    def _runtime_url(self) -> str:
        url = str(self.site.get("preview_url") or self.site.get("url") or "").strip().rstrip("/")
        if not url:
            raise SourceDeploymentError("the single Worker URL is not configured")
        return url

    def _worktree(self, checkout: Path, branch: str, commit: str) -> tuple[Path, str]:
        fetch_timeout = int(self.settings.get("fetch_timeout_seconds") or 120)
        self._run(["git", "fetch", "--no-tags", "origin", f"+{branch}:refs/remotes/origin/{branch}"], checkout, timeout=fetch_timeout)
        local_head = self._run(["git", "rev-parse", f"refs/remotes/origin/{branch}"], checkout, timeout=30).stdout.strip().lower()
        if local_head != commit:
            raise SourceDeploymentError("local Git checkout did not fetch the requested GitHub commit")
        configured_root = str(self.settings.get("worktree_root") or "").strip()
        worktree_root = Path(configured_root).expanduser().resolve() if configured_root else checkout.parent
        if not worktree_root.is_dir():
            raise SourceDeploymentError("source deployment worktree_root is not a directory")
        # The host's /tmp is noexec, so npm's native install scripts (notably
        # esbuild) cannot run from a temporary worktree there. Keep the
        # ephemeral checkout beside the configured repository unless a tenant
        # explicitly supplies another executable filesystem.
        directory = Path(tempfile.mkdtemp(prefix="atelier-source-preview-", dir=str(worktree_root)))
        try:
            self._run(["git", "worktree", "add", "--detach", str(directory), commit], checkout, timeout=120)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return directory, local_head

    def _check(self, command: list[str], cwd: Path, name: str, timeout: int, *, parse_json: bool = False) -> dict[str, Any]:
        result = self._run(command, cwd, timeout=timeout)
        item: dict[str, Any] = {"name": name, "ok": True}
        output = (result.stdout or result.stderr or "").strip()
        if parse_json:
            try:
                inventory = json.loads(output)
            except json.JSONDecodeError as exc:
                raise SourceDeploymentError(f"{name} did not return JSON") from exc
            if isinstance(inventory, Mapping):
                item["inventory"] = {
                    key: inventory.get(key)
                    for key in ("root", "filesScanned", "editableCount", "dynamicCount", "warnings")
                    if key in inventory
                }
            else:
                raise SourceDeploymentError(f"{name} returned an invalid inventory")
        if output:
            item["output"] = output[-2_000:]
        return item

    def _build(self, job: dict[str, Any], branch: str, commit: str) -> dict[str, Any]:
        checkout = self._local_checkout()
        worktree, local_head = self._worktree(checkout, branch, commit)
        timeout = int(self.settings.get("build_timeout_seconds") or 1_800)
        checks: list[dict[str, Any]] = []
        try:
            npm = str(self.settings.get("npm_command") or "npm")
            checks.append(self._check([npm, "ci", "--no-audit", "--no-fund"], worktree, "dependencies", timeout))
            checks.append(self._check([npm, "run", "typecheck"], worktree, "typecheck", timeout))
            checks.append(self._check([npm, "run", "lint"], worktree, "lint", timeout))
            checks.append(self._check(["npx", "--no-install", "tsx", "scripts/source-inventory.ts"], worktree, "source_inventory", timeout, parse_json=True))
            checks.append(self._check([npm, "run", "build"], worktree, "next_build", timeout))
            checks.append(self._check(["npx", "--no-install", "opennextjs-cloudflare", "build"], worktree, "open_next_build", timeout))

            token_name = self._env_name("cloudflare_api_token_env", "CLOUDFLARE_API_TOKEN")
            account_name = self._env_name("cloudflare_account_id_env", "CLOUDFLARE_ACCOUNT_ID")
            resolved_env = self._resolved_env()
            if not resolved_env.get(token_name) or not resolved_env.get(account_name):
                raise SourceDeploymentError("Cloudflare deployment credentials are not configured")
            deploy = self._check(
                ["npx", "--no-install", "opennextjs-cloudflare", "deploy", "--config", "wrangler.jsonc"],
                worktree,
                "cloudflare_worker_deploy",
                timeout,
            )
            result = {
                "ok": True,
                "status": "deployed",
                "branch": branch,
                "commit": local_head,
                "preview_url": self._runtime_url(),
                "deployment_mode": "single_worker",
                "checks": checks + [deploy],
            }
            job.update(result)
            return result
        finally:
            try:
                self._run(["git", "worktree", "remove", "--force", str(worktree)], checkout, timeout=120)
            except SourceDeploymentError:
                shutil.rmtree(worktree, ignore_errors=True)

    def _run_job(self, job_id: str, branch: str, requested_commit: str | None) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update({"status": "running", "updated_at": _now()})
            self._persist()
        try:
            commit = requested_commit or self._head(branch)
            if requested_commit and not re.fullmatch(r"[0-9a-f]{40}", requested_commit):
                raise SourceDeploymentError("requested source commit is invalid")
            current_head = self._head(branch)
            if current_head != commit:
                raise SourceDeploymentError("deployment branch advanced before its build started; rescan and retry")
            result = self._build(job, branch, commit)
            with self._lock:
                self._jobs[job_id] = {**self._jobs[job_id], **result, "updated_at": _now()}
                self._persist()
        except Exception as exc:  # noqa: BLE001 - persist a safe job failure
            with self._lock:
                self._jobs[job_id] = {
                    **self._jobs[job_id],
                    "status": "failed",
                    "ok": False,
                    "error": str(exc)[:1_000],
                    "updated_at": _now(),
                }
                self._persist()

    def start(self, request: Mapping[str, Any] | None = None) -> dict[str, Any]:
        body = _mapping(request)
        branch = self._branch(body.get("branch"))
        requested_commit = str(body.get("commit") or body.get("sha") or "").strip().lower() or None
        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "ok": True,
            "status": "queued",
            "branch": branch,
            "commit": requested_commit or "",
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._lock:
            self._jobs[job_id] = job
            self._persist()
        self._executor.submit(self._run_job, job_id, branch, requested_commit)
        return dict(job)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if job is None:
                raise SourceDeploymentError("source deployment job not found")
            return dict(job)

    def latest(self, branch: str | None = None) -> dict[str, Any]:
        with self._lock:
            candidates = [
                value for value in self._jobs.values()
                if isinstance(value, Mapping) and (not branch or str(value.get("branch") or "") == branch)
            ]
            if not candidates:
                return {}
            return dict(max(candidates, key=lambda item: str(item.get("updated_at") or item.get("created_at") or "")))

    def promote(self, job_id: str) -> dict[str, Any]:
        """Return an already deployed job for backwards-compatible callers.

        Direct Worker deployment happens as the final step of ``_build``.  The
        old promote endpoint remains harmless for older clients, but it no
        longer creates or shifts a separate Cloudflare version.
        """
        with self._lock:
            job = self._jobs.get(str(job_id))
            if job is None:
                raise SourceDeploymentError("source deployment job not found")
            if job.get("status") != "deployed":
                raise SourceDeploymentError("this proof-of-concept deploys directly to the configured Worker")
            return dict(job)

    def close(self) -> None:
        """Stop queued preview work during tenant shutdown."""
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["SourceDeploymentError", "SourceDeploymentService"]
