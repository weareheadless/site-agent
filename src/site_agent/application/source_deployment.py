"""Build private previews and request production through the canonical VPS queue.

The service has no production Cloudflare deployment capability. Owner approval
commits the exact customer SHA to site-agent's central GitOps queue; the VPS
release service builds, promotes and records the only production artifact.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..credentials import credential_environment, cloudflare_env_names, github_ssh_command
from ..hands.github_static import GithubStatic
from .release_queue import ReleaseQueueError, release_root, request_release


class SourceDeploymentError(RuntimeError):
    """A source revision could not be validated or deployed."""


_BRANCH = re.compile(r"^[A-Za-z0-9._/-]+$")
_COMPILED_PREVIEW = "compiled_preview"
_PRODUCTION = "production"


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
        saved = memory.kv_get("source_preview_jobs", {}) if memory is not None else {}
        self._jobs = dict(saved) if isinstance(saved, Mapping) else {}
        recover: list[tuple[str, str, str, str]] = []
        recovered_keys: set[tuple[str, str]] = set()
        for job in sorted(
            (
                value for value in self._jobs.values()
                if isinstance(value, dict)
                and value.get("mode") != _PRODUCTION
                and value.get("status") in {"queued", "running", "ready"}
            ),
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        ):
            if isinstance(job, dict) and job.get("status") in {"queued", "running", "ready"}:
                job_id = str(job.get("id") or "")
                branch = str(job.get("branch") or self.site.get("preview_branch") or "preview")
                mode = str(job.get("mode") or _COMPILED_PREVIEW)
                commit = str(job.get("commit") or "").strip().lower()
                key = (branch, mode)
                if (
                    mode == _COMPILED_PREVIEW
                    and job_id
                    and re.fullmatch(r"[0-9a-f]{40}", commit)
                    and key not in recovered_keys
                ):
                    job.update({
                        "status": "queued",
                        "ok": True,
                        "error": "source deployment process restarted; rebuilding the exact preview commit",
                        "updated_at": _now(),
                    })
                    for stale_key in ("runtime_path", "preview_url", "runtime_port"):
                        job.pop(stale_key, None)
                    recovered_keys.add(key)
                    recover.append((job_id, branch, commit, mode))
                else:
                    job.update({
                        "status": "failed",
                        "ok": False,
                        "error": "source deployment process restarted",
                        "updated_at": _now(),
                    })
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="site-agent-source-build")
        self._runtimes: dict[str, tuple[subprocess.Popen[str], Path]] = {}
        with self._lock:
            self._recover_production_jobs()
            self._persist()
        for job_id, branch, commit, mode in recover:
            self._executor.submit(self._run_job, job_id, branch, commit, mode)

    def _persist(self) -> None:
        if self.memory is None:
            return
        # Jobs remain inspectable by ID, including approvals older than the
        # most recent twenty previews. Never evict active or terminal receipts.
        rows = sorted(
            (dict(value) for value in self._jobs.values() if isinstance(value, Mapping)),
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )
        self.memory.kv_set("source_preview_jobs", {str(row.get("id")): row for row in rows if row.get("id")})

    def _recover_production_jobs(self) -> None:
        """Reconcile approvals only from the central VPS release receipt."""
        seen: set[Any] = set()
        drafts = {row["id"]: row for row in self.memory.list_drafts(limit=100_000)} if self.memory else {}
        for job in sorted(self._jobs.values(), key=lambda j: str(j.get("created_at") or ""), reverse=True):
            if job.get("mode") != _PRODUCTION:
                continue
            draft_id = job.get("draft_id")
            if draft_id in seen:
                continue
            seen.add(draft_id)
            draft = drafts.get(draft_id)
            if draft and draft.get("status") not in {"pending", "approved", "publishing", "publish_failed"}:
                continue
            if not str(job.get("release_id") or "").strip() or not str(job.get("tenant_id") or "").strip():
                job.update(
                    status="failed",
                    ok=False,
                    error="approved change has no durable central release identity",
                    updated_at=_now(),
                )
                if draft and draft.get("status") == "publishing":
                    self.memory.update_draft_status(int(draft_id), "publish_failed")
                continue
            self._refresh_release_job(job)
        for draft_id, draft in drafts.items():
            if draft.get("status") == "publishing" and draft_id not in seen:
                self.memory.update_draft_status(draft_id, "publish_failed")
                self.memory.record_action("publish_failed", f"#{draft_id}: process restarted before deployment was durably queued")

    def _refresh_release_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Project a VPS receipt; this service never builds or deploys production."""
        release_id = str(job.get("release_id") or "")
        tenant = str(job.get("tenant_id") or "")
        if not release_id or not tenant:
            return job
        try:
            path = release_root(self.config) / "runs" / tenant / release_id / "receipt.json"
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return job
        except (OSError, UnicodeError, ValueError, ReleaseQueueError) as exc:
            job.update(status="failed", ok=False, error=f"central release receipt is invalid: {type(exc).__name__}", updated_at=_now())
            self._sync_publish_failure(job)
            self._persist()
            return job
        if (
            receipt.get("tenant") != tenant
            or receipt.get("releaseId") != release_id
            or receipt.get("sourceSha") != job.get("commit")
            or receipt.get("approvalId") != job.get("draft_id")
        ):
            job.update(status="failed", ok=False, error="central release receipt identity does not match this approval", updated_at=_now())
            self._sync_publish_failure(job)
        elif receipt.get("status") in {"deployed", "verified"}:
            should_record = not bool(job.get("release_receipt_processed"))
            job.update(
                status="deployed",
                phase="verified_by_vps",
                ok=True,
                live=True,
                verified_commit=job.get("commit"),
                release_receipt_processed=True,
                release_receipt={
                    key: receipt.get(key)
                    for key in ("pipelineSha", "uploadedVersion", "connectionVerifiedAt", "finishedAt")
                    if receipt.get(key) is not None
                },
                updated_at=_now(),
            )
            job.pop("error", None)
            if should_record:
                self._record_production_publish(job, job)
        elif receipt.get("status") in {"failed", "interrupted"}:
            job.update(
                status="failed",
                phase=str(receipt.get("stage") or "failed"),
                ok=False,
                error=str(receipt.get("error") or "central VPS release failed")[:1_000],
                updated_at=_now(),
            )
            self._sync_publish_failure(job)
        else:
            job.update(
                status="running",
                phase=str(receipt.get("stage") or "queued_on_vps"),
                pipeline_sha=str(receipt.get("pipelineSha") or ""),
                updated_at=_now(),
            )
        self._jobs[str(job.get("id") or "")] = job
        self._persist()
        return job

    def _sync_publish_failure(self, job: Mapping[str, Any]) -> None:
        if self.memory is not None and job.get("mode") == _PRODUCTION and job.get("draft_id") is not None:
            self.memory.update_draft_status(int(job["draft_id"]), "publish_failed")

    def _fail_job(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(status="failed", ok=False, error=error[:1_000], updated_at=_now())
            self._persist()
        self._sync_publish_failure(job)

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
        return credential_environment(self.config, self.env)

    def _child_env(self, *, production: bool = False) -> dict[str, str]:
        child = self._resolved_env()
        # Tenant workers intentionally run with a development NODE_ENV for
        # their interactive loop. Only production framework commands should
        # override it: applying production mode to `npm ci` would omit the
        # dev tools needed by the validation checks (for example, ESLint).
        if production:
            child["NODE_ENV"] = "production"
        node_path = str(self.settings.get("node_path") or "").strip()
        npm_command = str(self.settings.get("npm_command") or "").strip()
        tool_paths = [str(Path(npm_command).expanduser().parent)] if npm_command else []
        if node_path:
            tool_paths.append(node_path)
        if tool_paths:
            inherited_path = child.get("PATH") or os.environ.get("PATH", "")
            child["PATH"] = os.pathsep.join([*tool_paths, inherited_path])
        ssh_command = str(self.settings.get("git_ssh_command") or "").strip()
        if ssh_command:
            child["GIT_SSH_COMMAND"] = ssh_command
        else:
            ssh_command = github_ssh_command(self.config, child)
        if ssh_command:
            child["GIT_SSH_COMMAND"] = ssh_command
        profile_token_name, profile_account_name = cloudflare_env_names(self.config)
        token_name = self._env_name("cloudflare_api_token_env", profile_token_name)
        account_name = self._env_name("cloudflare_account_id_env", profile_account_name)
        token = child.get(token_name, "")
        account = child.get(account_name, "")
        if token:
            child["CLOUDFLARE_API_TOKEN"] = token
        if account:
            child["CLOUDFLARE_ACCOUNT_ID"] = account
        payload = _mapping(self.site.get("payload"))
        secret_file = str(
            self.settings.get("payload_secret_file")
            or payload.get("secret_file")
            or ""
        ).strip()
        if secret_file and not child.get("PAYLOAD_SECRET"):
            try:
                secret = Path(secret_file).expanduser().read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                secret = ""
            if secret:
                child["PAYLOAD_SECRET"] = secret
        return child

    def _verify_toolchain(self, cwd: Path) -> str:
        node_path = str(self.settings.get("node_path") or "").strip()
        npm_command = str(self.settings.get("npm_command") or "").strip()
        node_version = str(self.settings.get("node_version") or "").strip()
        npm_version = str(self.settings.get("npm_version") or "").strip()
        if not node_path or not npm_command or not node_version or not npm_version:
            raise SourceDeploymentError(
                "source builds require the shared node_path, node_version, npm_command and npm_version contract"
            )
        node_bin = Path(node_path).expanduser()
        npm = Path(npm_command).expanduser()
        if not node_bin.is_absolute() or not npm.is_absolute():
            raise SourceDeploymentError("shared source-build toolchain paths must be absolute")
        for name, version in (("Node", node_version), ("npm", npm_version)):
            if not re.fullmatch(r"\d+\.\d+\.\d+", version):
                raise SourceDeploymentError(f"shared source-build toolchain requires an exact {name} version")
        node = node_bin / "node"
        if not node.is_file() or not node.stat().st_mode & 0o111:
            raise SourceDeploymentError("configured Node executable is missing or not executable")
        if not npm.is_file() or not npm.stat().st_mode & 0o111:
            raise SourceDeploymentError("configured npm executable is missing or not executable")
        actual_node = self._run([str(node), "--version"], cwd, timeout=30).stdout.strip().removeprefix("v")
        if actual_node != node_version:
            raise SourceDeploymentError(f"source builds require Node {node_version}; found {actual_node or 'no version'}")
        actual_npm = self._run([str(npm), "--version"], cwd, timeout=30).stdout.strip()
        if actual_npm != npm_version:
            raise SourceDeploymentError(f"source builds require npm {npm_version}; found {actual_npm or 'no version'}")
        return str(npm)

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

    @staticmethod
    def _revision_marker_path(worktree: Path) -> Path:
        """Return the ephemeral public marker used to verify an exact build."""
        return worktree / "public" / "site-agent-revision.txt"

    def _write_revision_marker(self, worktree: Path, commit: str) -> Path:
        """Write a deployment-only marker into the detached build worktree.

        This file is never committed to the customer's repository.  It is
        included in the built artifact so a successful deployment can be
        distinguished from an older runtime that merely returns HTTP 200.
        """
        marker = self._revision_marker_path(worktree)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{commit.strip().lower()}\n", encoding="utf-8")
        return marker

    def _verify_public_revision(self, base_url: str, expected_commit: str, *, label: str) -> dict[str, Any]:
        """Confirm that a runtime serves the exact built revision."""
        expected = str(expected_commit or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", expected):
            raise SourceDeploymentError("deployment revision verification needs a full commit SHA")
        base = str(base_url or "").strip().rstrip("/")
        if not base:
            raise SourceDeploymentError(f"{label} URL is not configured for verification")
        timeout = max(30, int(self.settings.get("verification_timeout_seconds") or 180))
        request_timeout = max(3, min(15, int(self.settings.get("verification_request_timeout_seconds") or 10)))
        marker_url = f"{base}/site-agent-revision.txt?revision_check={expected}"
        deadline = time.monotonic() + timeout
        last_reason = "no response"
        while time.monotonic() < deadline:
            request = urllib.request.Request(
                marker_url,
                headers={
                    "User-Agent": "site-agent/1.0",
                    "Cache-Control": "no-cache",
                    "X-Site-Agent-Revision-Check": expected,
                },
                method="GET",
            )
            try:
                with urllib.request.urlopen(request, timeout=request_timeout) as response:
                    body = response.read().decode("utf-8", errors="replace").strip().lower()
                    status = int(response.status)
                    if status == 200 and body == expected:
                        return {
                            "name": f"{label.lower().replace(' ', '_')}_revision",
                            "ok": True,
                            "status": status,
                            "url": marker_url.split("?", 1)[0],
                            "commit": expected,
                        }
                    last_reason = f"HTTP {status} served revision {body[:80] or '(empty)'}"
            except urllib.error.HTTPError as exc:
                last_reason = f"HTTP {exc.code}"
            except (OSError, urllib.error.URLError) as exc:
                last_reason = str(exc)[:200]
            time.sleep(1)
        raise SourceDeploymentError(
            f"{label} verification did not confirm commit {expected[:12]}: {last_reason}"
        )

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
        directory = Path(tempfile.mkdtemp(prefix="site-agent-source-preview-", dir=str(worktree_root)))
        try:
            self._run(["git", "worktree", "add", "--detach", str(directory), commit], checkout, timeout=120)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return directory, local_head

    def _check(
        self,
        command: list[str],
        cwd: Path,
        name: str,
        timeout: int,
        *,
        parse_json: bool = False,
        production: bool = False,
    ) -> dict[str, Any]:
        try:
            result = subprocess.run(
                command,
                cwd=str(cwd),
                env=self._child_env(production=production),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SourceDeploymentError(f"command failed: {' '.join(command[:4])}: {str(exc)[:300]}") from exc
        if result.returncode:
            output = (result.stderr or result.stdout or "command failed").strip()
            raise SourceDeploymentError(f"{' '.join(command[:4])}: {output[-1_500:]}")
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

    def _inventory_command(self, checkout: Path, worktree: Path) -> list[str]:
        """Run the single host-owned inventory over the immutable preview tree."""
        del checkout
        inventory = Path(__file__).with_name("source_inventory.py").resolve()
        if not inventory.is_file():
            raise SourceDeploymentError("host source inventory is not installed")
        return [sys.executable, str(inventory), "--root", str(worktree)]

    def _preview_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    def _stop_runtime(self, job_id: str) -> None:
        runtime = self._runtimes.pop(str(job_id), None)
        if runtime is None:
            return
        process, worktree = runtime
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    process.terminate()
                except OSError:
                    pass
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    try:
                        process.kill()
                    except OSError:
                        pass
        shutil.rmtree(worktree, ignore_errors=True)

    def _start_runtime(self, job: dict[str, Any], worktree: Path, expected_commit: str | None = None) -> dict[str, Any]:
        """Start the exact OpenNext build behind the tenant-scoped API proxy.

        The browser never receives the loopback address.  Keeping the process on
        the site-agent host gives the owner a stable preview URL without creating
        a second Worker, database, or public Cloudflare deployment.
        """
        for other_id in list(self._runtimes):
            if other_id != str(job["id"]):
                self._stop_runtime(other_id)

        port = self._preview_port()
        command = [
            "npx",
            "--no-install",
            "opennextjs-cloudflare",
            "preview",
            "--config",
            "wrangler.jsonc",
            "--port",
            str(port),
        ]
        # The sole preview invocation uses the exact locally locked executable;
        # missing dependencies are a failed build, never a registry download.
        try:
            process = subprocess.Popen(
                command,
                cwd=str(worktree),
                env=self._child_env(production=True),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                text=True,
            )
        except (OSError, ValueError) as exc:
            raise SourceDeploymentError(f"compiled preview could not start: {str(exc)[:300]}") from exc

        self._runtimes[str(job["id"])] = (process, worktree)
        timeout = max(30, int(self.settings.get("preview_start_timeout_seconds") or 180))
        deadline = time.monotonic() + timeout
        ready = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._stop_runtime(str(job["id"]))
                raise SourceDeploymentError("compiled preview process exited before it was ready")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
                    if int(response.status) < 500:
                        ready = True
                        break
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    ready = True
                    break
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(1)
        if not ready:
            self._stop_runtime(str(job["id"]))
            raise SourceDeploymentError("compiled preview did not become ready in time")
        revision = self._verify_public_revision(
            f"http://127.0.0.1:{port}",
            str(expected_commit or job.get("commit") or ""),
            label="compiled preview",
        )
        return {
            "status": "ready",
            "mode": _COMPILED_PREVIEW,
            "runtime_path": f"/api/workspace/source/preview/{job['id']}/runtime",
            "preview_url": f"/api/workspace/source/preview/{job['id']}/runtime/",
            "deployment_mode": "isolated_host_runtime",
            "runtime_port": port,
            "revision_verification": revision,
        }

    def _build(self, job: dict[str, Any], branch: str, commit: str, mode: str) -> dict[str, Any]:
        if mode != _COMPILED_PREVIEW:
            raise SourceDeploymentError("production builds and uploads are owned by the central VPS release pipeline")
        checkout = self._local_checkout()
        worktree, local_head = self._worktree(checkout, branch, commit)
        timeout = int(self.settings.get("build_timeout_seconds") or 1_800)
        checks: list[dict[str, Any]] = []
        keep_worktree = False
        try:
            self._write_revision_marker(worktree, local_head)
            npm = self._verify_toolchain(worktree)
            checks.append(self._check([npm, "ci", "--no-audit", "--no-fund"], worktree, "dependencies", timeout))
            checks.append(self._check([npm, "run", "typecheck"], worktree, "typecheck", timeout))
            checks.append(self._check([npm, "run", "lint"], worktree, "lint", timeout))
            checks.append(self._check(self._inventory_command(checkout, worktree), worktree, "source_inventory", timeout, parse_json=True))
            checks.append(self._check([npm, "run", "build"], worktree, "next_build", timeout, production=True))
            checks.append(self._check(["npx", "--no-install", "opennextjs-cloudflare", "build"], worktree, "open_next_build", timeout, production=True))

            runtime = self._start_runtime(job, worktree, local_head)
            keep_worktree = True
            result = {
                "ok": True,
                "branch": branch,
                "commit": local_head,
                "checks": checks,
                **runtime,
            }
            job.update(result)
            return result
        finally:
            if not keep_worktree:
                try:
                    self._run(["git", "worktree", "remove", "--force", str(worktree)], checkout, timeout=120)
                except SourceDeploymentError:
                    shutil.rmtree(worktree, ignore_errors=True)

    def _record_production_publish(self, job: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        if self.memory is None:
            return
        raw_draft_id = job.get("draft_id")
        try:
            draft_id = int(raw_draft_id)
        except (TypeError, ValueError):
            return
        self.memory.log_publish(
            summary=str(job.get("publish_summary") or f"Published draft #{draft_id}"),
            path=str(job.get("publish_path") or "site"),
            commit_sha=str(result.get("commit") or ""),
            draft_id=draft_id,
            parent_sha=str(job.get("publish_parent_sha") or ""),
            actor="owner",
            version_type=str(job.get("publish_version_type") or "merge"),
            commit_message=str(job.get("publish_commit_message") or ""),
            idempotent=True,
        )
        self.memory.update_draft_status(draft_id, "live")
        self.memory.record_action("publish_live", f"#{draft_id} live at {str(result.get('commit') or '')[:8]}")

    def _sync_compiled_preview_draft(
        self,
        job: Mapping[str, Any],
        result: Mapping[str, Any] | None = None,
        *,
        error: str = "",
    ) -> None:
        """Publish asynchronous preview readiness back to its review draft.

        ``stage_build`` creates the draft before the compiled preview finishes.
        Without this reconciliation the owner-facing draft can remain marked
        ``building`` forever even though the exact runtime is ready (or can
        look reviewable after a failed build).  The deployment job remains the
        source of truth for the full check receipt; the draft stores the small
        status/candidate reference the workspace needs.
        """
        if self.memory is None or job.get("mode") != _COMPILED_PREVIEW:
            return
        try:
            draft_id = int(job.get("draft_id"))
        except (TypeError, ValueError):
            return
        draft = next(
            (
                item for item in self.memory.list_drafts(limit=200)
                if int(item.get("id") or 0) == draft_id
            ),
            None,
        )
        if not draft or draft.get("status") not in {"pending", "publishing", "publish_failed"}:
            return

        current_meta = dict(draft.get("meta") or {})
        preview = dict(current_meta.get("preview") or {})
        result = result or {}
        status = str(result.get("status") or "").strip().lower()
        preview.update({
            "job_id": str(job.get("id") or ""),
            "head_sha": str(result.get("commit") or job.get("commit") or preview.get("head_sha") or ""),
            "requires_build": status != "ready",
        })
        if status == "ready":
            preview.update({
                "status": "ready",
                "runtime_path": result.get("runtime_path"),
                "preview_url": result.get("preview_url"),
                "deployment_mode": result.get("deployment_mode"),
            })
            preview.pop("error", None)
            title = str(draft.get("title") or "")
            for prefix in ("Preview preparing:", "Preview blocked:"):
                if title.startswith(prefix):
                    title = "Preview ready:" + title[len(prefix):]
                    break
        else:
            preview.update({
                "status": "blocked",
                "error": str(error or result.get("error") or "compiled preview failed")[:1_000],
            })
            title = str(draft.get("title") or "")
            if title.startswith("Preview preparing:"):
                title = "Preview blocked:" + title[len("Preview preparing:"):]

        current_meta["preview"] = preview
        current_meta["head_sha"] = preview.get("head_sha") or current_meta.get("head_sha") or ""
        self.memory.save_draft(
            title=title,
            body=str(draft.get("body") or ""),
            kind=str(draft.get("kind") or "merge"),
            meta=current_meta,
            draft_id=draft_id,
        )

    def _run_job(self, job_id: str, branch: str, requested_commit: str | None, mode: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update({"status": "running", "phase": "building", "updated_at": _now()})
            self._persist()
        try:
            commit = requested_commit or self._head(branch)
            if requested_commit and not re.fullmatch(r"[0-9a-f]{40}", requested_commit):
                raise SourceDeploymentError("requested source commit is invalid")
            current_head = self._head(branch)
            if current_head != commit:
                raise SourceDeploymentError("deployment branch advanced before its build started; rescan and retry")
            result = self._build(job, branch, commit, mode)
            with self._lock:
                self._jobs[job_id] = {**self._jobs[job_id], **result, "updated_at": _now()}
                self._jobs[job_id].pop("error", None)
                self._persist()
            self._sync_compiled_preview_draft(self._jobs[job_id], result)
            if mode == _PRODUCTION:
                self._record_production_publish(self._jobs[job_id], result)
        except Exception as exc:  # noqa: BLE001 - persist a safe job failure
            self._fail_job(job_id, str(exc))
            self._sync_compiled_preview_draft(self._jobs[job_id], error=str(exc))

    def start(
        self,
        request: Mapping[str, Any] | None = None,
        *,
        allow_production: bool = False,
    ) -> dict[str, Any]:
        # Reservation, persistence and dispatch form one single-instance claim.
        with self._lock:
            return self._start_locked(request, allow_production=allow_production)

    def _start_locked(
        self,
        request: Mapping[str, Any] | None = None,
        *,
        allow_production: bool = False,
    ) -> dict[str, Any]:
        """Queue one exact revision.

        Production deployment is an application-level approval operation, not
        a mode a browser or route caller may request.  The workspace approval
        service is the only caller that passes ``allow_production=True``.
        """
        body = _mapping(request)
        branch = self._branch(body.get("branch"))
        requested_commit = str(body.get("commit") or body.get("sha") or "").strip().lower() or None
        mode = str(body.get("mode") or _COMPILED_PREVIEW).strip().lower()
        if mode not in {_COMPILED_PREVIEW, _PRODUCTION}:
            raise SourceDeploymentError("source deployment mode is invalid")
        if mode == _PRODUCTION and not allow_production:
            raise SourceDeploymentError("production deployment requires explicit owner approval")
        if mode == _PRODUCTION and not re.fullmatch(r"[0-9a-f]{40}", requested_commit or ""):
            raise SourceDeploymentError("production deployment requires an exact commit")
        if mode == _PRODUCTION and branch != "main":
            raise SourceDeploymentError("production release must reference the official main branch")
        draft_id = body.get("draft_id")
        publish = _mapping(body.get("publish"))
        with self._lock:
            for existing in self._jobs.values():
                if not isinstance(existing, Mapping):
                    continue
                if (
                    existing.get("branch") == branch
                    and existing.get("commit") == (requested_commit or existing.get("commit"))
                    and existing.get("mode") == mode
                    and existing.get("draft_id") == draft_id
                    and existing.get("status") in {"queued", "running", "verifying", "ready", "deployed"}
                ):
                    return dict(existing)
        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "ok": True,
            "status": "queued",
            "branch": branch,
            "commit": requested_commit or "",
            "mode": mode,
            "created_at": _now(),
            "updated_at": _now(),
        }
        if draft_id is not None:
            job["draft_id"] = draft_id
        for source_key, job_key in (
            ("summary", "publish_summary"),
            ("path", "publish_path"),
            ("parent_sha", "publish_parent_sha"),
            ("version_type", "publish_version_type"),
            ("commit_message", "publish_commit_message"),
        ):
            if publish.get(source_key) is not None:
                job[job_key] = str(publish.get(source_key) or "")[:8_000]
        if mode == _PRODUCTION:
            if draft_id is None:
                raise SourceDeploymentError("production release requires the exact approved decision identity")
            try:
                approval_id = int(draft_id)
            except (TypeError, ValueError) as exc:
                raise SourceDeploymentError("production release approval identity is invalid") from exc
            if approval_id < 1:
                raise SourceDeploymentError("production release approval identity is invalid")
            if self._head(branch) != requested_commit:
                raise SourceDeploymentError("approved source revision is no longer the exact main revision")
            try:
                receipt = request_release(self.config, self.env, requested_commit, approval_id=approval_id)
                root = release_root(self.config)
            except ReleaseQueueError as exc:
                raise SourceDeploymentError(str(exc)) from exc
            job.update({
                "tenant_id": str(self.config.get("instance_name") or ""),
                "release_id": receipt["release_id"],
                "control_sha": receipt["control_sha"],
                "release_root": str(root),
                "status": "queued",
                "phase": "queued_on_vps",
            })
            self._jobs[job_id] = job
            self._persist()
            if self.memory is not None:
                self.memory.update_draft_status(approval_id, "publishing")
            return dict(job)
        with self._lock:
            self._jobs[job_id] = job
            self._persist()
        try:
            self._executor.submit(self._run_job, job_id, branch, requested_commit, mode)
        except Exception as exc:
            self._fail_job(job_id, str(exc))
            raise SourceDeploymentError("source deployment could not be dispatched") from exc
        return self.status(job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if job is None:
                raise SourceDeploymentError("source deployment job not found")
            if job.get("mode") == _PRODUCTION:
                self._refresh_release_job(job)
            return dict(job)

    def latest_preview(self, branch: str | None = None) -> dict[str, Any]:
        return self.latest(branch, mode=_COMPILED_PREVIEW)

    def for_draft(self, draft_id: int) -> dict[str, Any]:
        """The latest production receipt, independently of the review preview."""
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.get("mode") == _PRODUCTION and j.get("draft_id") == draft_id]
            return dict(max(jobs, key=lambda j: str(j.get("created_at") or ""))) if jobs else {}

    def latest(self, branch: str | None = None, *, mode: str | None = None) -> dict[str, Any]:
        with self._lock:
            candidates = [
                value for value in self._jobs.values()
                if isinstance(value, Mapping) and (not branch or str(value.get("branch") or "") == branch)
                and (mode is None or value.get("mode") == mode)
            ]
            if not candidates:
                return {}
            return dict(max(candidates, key=lambda item: str(item.get("updated_at") or item.get("created_at") or "")))

    def runtime(self, job_id: str, path: str, query: str = "", headers: Mapping[str, str] | None = None) -> dict[str, Any]:
        """Proxy one authenticated browser request to an isolated preview."""
        with self._lock:
            job = self._jobs.get(str(job_id))
            runtime = self._runtimes.get(str(job_id))
            if not isinstance(job, Mapping) or job.get("status") != "ready" or runtime is None:
                raise SourceDeploymentError("compiled preview is not ready")
            process, _worktree = runtime
            if process.poll() is not None:
                raise SourceDeploymentError("compiled preview process is no longer running")
            port = int(job.get("runtime_port") or 0)
        clean_path = str(path or "").lstrip("/")
        if ".." in Path(clean_path).parts:
            raise SourceDeploymentError("compiled preview path is invalid")
        target = f"http://127.0.0.1:{port}/{clean_path}"
        if query:
            target = f"{target}?{query}"
        request_headers = {
            key: value
            for key, value in (headers or {}).items()
            if key.lower() in {"accept", "cookie", "user-agent"} and value
        }
        request = urllib.request.Request(target, headers=request_headers, method="GET")
        try:
            response = urllib.request.urlopen(request, timeout=60)
            with response:
                return {
                    "status": int(response.status),
                    "body": response.read(),
                    "content_type": response.headers.get("Content-Type", "application/octet-stream"),
                    "commit": str(job.get("commit") or ""),
                }
        except urllib.error.HTTPError as exc:
            return {
                "status": int(exc.code),
                "body": exc.read(),
                "content_type": exc.headers.get("Content-Type", "text/plain; charset=utf-8"),
                "commit": str(job.get("commit") or ""),
            }
        except (OSError, urllib.error.URLError) as exc:
            raise SourceDeploymentError(f"compiled preview request failed: {str(exc)[:300]}") from exc

    def close(self) -> None:
        """Stop queued preview work during tenant shutdown."""
        for job_id in list(self._runtimes):
            self._stop_runtime(job_id)
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["SourceDeploymentError", "SourceDeploymentService"]
