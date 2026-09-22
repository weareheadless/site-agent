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
import signal
import socket
import subprocess
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
        saved = memory.kv_get("atelier_source_preview_jobs", {}) if memory is not None else {}
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
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="atelier-source-build")
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
        self.memory.kv_set("atelier_source_preview_jobs", {str(row.get("id")): row for row in rows if row.get("id")})

    def _recover_production_jobs(self) -> None:
        """Resume known pre-deploy work; reconcile ambiguous writes by GET only.

        A process may die after Cloudflare accepts a deployment but before its
        receipt is saved. Never replay that mutation automatically. Verification
        either establishes the exact live revision or leaves a terminal failure.
        """
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
            status = job.get("status")
            if status == "deployed":
                self._record_production_publish(job, job)
            elif status in {"queued", "running"} and (status == "queued" or job.get("phase") == "building"):
                if re.fullmatch(r"[0-9a-f]{40}", str(job.get("commit") or "")):
                    self._executor.submit(self._run_job, job["id"], job["branch"], job["commit"], _PRODUCTION)
                else:
                    self._fail_job(job["id"], "interrupted publish has no exact commit")
            elif status in {"running", "verifying"} or (
                status == "failed" and "verification did not confirm commit" in str(job.get("error") or "")
            ):
                job.update(status="verifying", updated_at=_now())
                self._executor.submit(self._reconcile_production, job["id"])
            elif status == "failed":
                self._sync_publish_failure(job)
        for draft_id, draft in drafts.items():
            if draft.get("status") == "publishing" and draft_id not in seen:
                self.memory.update_draft_status(draft_id, "publish_failed")
                self.memory.record_action("publish_failed", f"#{draft_id}: process restarted before deployment was durably queued")

    def _reconcile_production(self, job_id: str) -> None:
        job = self.status(job_id)
        try:
            revision = self._verify_public_revision(self._runtime_url(), job["commit"], label="live site")
            with self._lock:
                job.update(status="deployed", ok=True, live=True, verified_commit=job["commit"],
                           revision_verification=revision, updated_at=_now())
                job.pop("error", None)
                self._jobs[job_id] = job
                self._persist()
            self._record_production_publish(job, job)
        except Exception as exc:  # noqa: BLE001 - recovery must reach a terminal state
            self._fail_job(job_id, str(exc))

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

    def _child_env(self) -> dict[str, str]:
        child = self._resolved_env()
        node_path = str(self.settings.get("node_path") or "").strip()
        if node_path:
            child["PATH"] = f"{node_path}:{child.get('PATH') or os.environ.get('PATH', '')}"
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
        return worktree / "public" / "atelier-revision.txt"

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
        marker_url = f"{base}/atelier-revision.txt?atelier_revision_check={expected}"
        deadline = time.monotonic() + timeout
        last_reason = "no response"
        while time.monotonic() < deadline:
            request = urllib.request.Request(
                marker_url,
                headers={
                    "User-Agent": "Atelier-Site-Agent/1.0",
                    "Cache-Control": "no-cache",
                    "X-Atelier-Revision-Check": expected,
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

    def _inventory_command(self, checkout: Path, worktree: Path) -> list[str]:
        """Resolve host-owned review tooling without requiring it in site source.

        ``scripts/source-inventory.ts`` is an Ada review tool, not a runtime
        asset. Older remote source revisions legitimately do not contain it, so
        the exact site revision must not fail merely because the host tool is
        absent from that revision. The scan root remains the detached revision.
        """
        configured = str(self.settings.get("inventory_script") or "scripts/source-inventory.ts").strip()
        candidates = [Path(configured)] if Path(configured).is_absolute() else [worktree / configured, checkout / configured]
        for candidate in candidates:
            resolved = candidate.expanduser().resolve()
            if resolved.is_file():
                command = ["npx", "--no-install", "tsx", str(resolved)]
                if resolved != worktree and worktree not in resolved.parents:
                    command.extend(["--root", str(worktree)])
                return command
        raise SourceDeploymentError("source inventory tooling is not available on the host")

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
        npm = str(self.settings.get("npm_command") or "npm")
        command = [
            npm,
            "exec",
            "--no",
            "--",
            "opennextjs-cloudflare",
            "preview",
            "--config",
            "wrangler.jsonc",
            "--port",
            str(port),
        ]
        # npm exec is not consistent across the pinned npm versions used by the
        # existing deployment host. Fall back to the already-established npx
        # invocation if it rejects the command before the worker binds. The
        # Wrangler config marks D1 as a remote binding; using local Wrangler
        # with that binding keeps the server-side runtime reachable, whereas
        # OpenNext's global ``--remote`` tunnel rejects this host with 1010.
        if npm == "npm":
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
        try:
            process = subprocess.Popen(
                command,
                cwd=str(worktree),
                env=self._child_env(),
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
            "runtime_path": f"/api/atelier/source/preview/{job['id']}/runtime",
            "preview_url": f"/api/atelier/source/preview/{job['id']}/runtime/",
            "deployment_mode": "isolated_host_runtime",
            "runtime_port": port,
            "revision_verification": revision,
        }

    def _build(self, job: dict[str, Any], branch: str, commit: str, mode: str) -> dict[str, Any]:
        checkout = self._local_checkout()
        worktree, local_head = self._worktree(checkout, branch, commit)
        timeout = int(self.settings.get("build_timeout_seconds") or 1_800)
        checks: list[dict[str, Any]] = []
        keep_worktree = False
        try:
            self._write_revision_marker(worktree, local_head)
            npm = str(self.settings.get("npm_command") or "npm")
            checks.append(self._check([npm, "ci", "--no-audit", "--no-fund"], worktree, "dependencies", timeout))
            checks.append(self._check([npm, "run", "typecheck"], worktree, "typecheck", timeout))
            checks.append(self._check([npm, "run", "lint"], worktree, "lint", timeout))
            checks.append(self._check(self._inventory_command(checkout, worktree), worktree, "source_inventory", timeout, parse_json=True))
            checks.append(self._check([npm, "run", "build"], worktree, "next_build", timeout))
            checks.append(self._check(["npx", "--no-install", "opennextjs-cloudflare", "build"], worktree, "open_next_build", timeout))

            if mode == _COMPILED_PREVIEW:
                runtime = self._start_runtime(job, worktree, local_head)
                keep_worktree = True
                result = {
                    "ok": True,
                    "branch": branch,
                    "commit": local_head,
                    "checks": checks,
                    **runtime,
                }
            else:
                profile_token_name, profile_account_name = cloudflare_env_names(self.config)
                token_name = self._env_name("cloudflare_api_token_env", profile_token_name)
                account_name = self._env_name("cloudflare_account_id_env", profile_account_name)
                resolved_env = self._resolved_env()
                if not resolved_env.get(token_name) or not resolved_env.get(account_name):
                    raise SourceDeploymentError("Cloudflare deployment credentials are not configured")
                with self._lock:
                    job.update(phase="deploying", updated_at=_now())
                    self._persist()
                deploy = self._check(
                    ["npx", "--no-install", "opennextjs-cloudflare", "deploy", "--config", "wrangler.jsonc"],
                    worktree,
                    "cloudflare_worker_deploy",
                    timeout,
                )
                with self._lock:
                    job.update(phase="verifying", deployment_completed=True, checks=checks + [deploy], updated_at=_now())
                    self._persist()
                revision = self._verify_public_revision(self._runtime_url(), local_head, label="live site")
                result = {
                    "ok": True,
                    "status": "deployed",
                    "mode": _PRODUCTION,
                    "branch": branch,
                    "commit": local_head,
                    "preview_url": self._runtime_url(),
                    "deployment_mode": "single_worker",
                    "checks": checks + [deploy],
                    "live": True,
                    "verified_commit": local_head,
                    "revision_verification": revision,
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
            if title.startswith("Preview preparing:"):
                title = "Preview ready:" + title[len("Preview preparing:"):]
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
        with self._lock:
            self._jobs[job_id] = job
            self._persist()
            if mode == _PRODUCTION and self.memory is not None and draft_id is not None:
                self.memory.update_draft_status(int(draft_id), "publishing")
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
                raise SourceDeploymentError("this preview is not a deployed production revision")
            return dict(job)

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
