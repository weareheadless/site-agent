"""Build private previews and request production through the canonical VPS queue.

The service has no production Cloudflare deployment capability. Owner approval
commits the exact customer SHA to site-agent's central GitOps queue; the VPS
release service builds, promotes and records the only production artifact.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..credentials import credential_environment, cloudflare_env_names, github_api_token, github_ssh_command
from . import preview_host
from ..hands.github_static import GithubStatic
from .release_queue import ReleaseQueueError, release_root, request_release


class SourceDeploymentError(RuntimeError):
    """A source revision could not be validated or deployed."""


_BRANCH = re.compile(r"^[A-Za-z0-9._/-]+$")
_PREVIEW_PLATFORM_PATHS = ("/api", "/admin", "/mail", "/_next", "/favicon", "/robots.txt", "/sitemap.xml")
# Files the candidate itself serves from its Payload API rather than from
# `public/`. In production they answer at the site root; inside the preview they
# must answer through the preview mount like the rest of the candidate.
_PREVIEW_CANDIDATE_ASSET_ROOTS = ("/api/media/",)
_COMPILED_PREVIEW = "compiled_preview"
_PRODUCTION = "production"
_PREVIEW_PATH_PREFIX = preview_host.PREVIEW_PREFIX
# A compiled candidate is a complete application, so it is served from its own
# origin at a signed path (application/preview_host.py) instead of a route
# inside the workspace app. The build's Next basePath is that exact path, and
# one service owns both the path and the runtime behind it.
_PREVIEW_FLIGHT_REQUEST_HEADERS = (
    "rsc",
    "next-router-state-tree",
    "next-router-prefetch",
    "next-router-segment-prefetch",
    "next-url",
    "purpose",
    "x-nextjs-data",
)
_PREVIEW_ENV_ALLOWLIST = frozenset({
    "PATH", "LANG", "LC_ALL", "CI", "TZ",
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "NPM_CONFIG_CACHE",
    "NEXT_TELEMETRY_DISABLED",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


class _DocumentAssets(HTMLParser):
    """Collect the files a rendered document makes the browser request.

    A page that returns 200 can still be broken: a `<link rel="icon">` pointed
    at a name the build never emitted 404s in the tab even though the document
    rendered. The gate requests exactly what the markup names, so an asset the
    owner would see fail cannot pass as a ready preview.
    """

    _ELEMENTS: tuple[tuple[str, str], ...] = (
        ("link", "href"),
        ("script", "src"),
        ("img", "src"),
        ("img", "srcset"),
        ("source", "src"),
        ("source", "srcset"),
        ("video", "src"),
        ("video", "poster"),
        ("audio", "src"),
        ("track", "src"),
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        for element, attribute in self._ELEMENTS:
            if tag != element:
                continue
            value = attributes.get(attribute, "").strip()
            if not value:
                continue
            # srcset is a comma-separated candidate list; only the URL matters.
            candidates = [value] if attribute != "srcset" else [
                part.strip().split(" ")[0] for part in value.split(",")
            ]
            self.urls.extend(url for url in candidates if url)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


class SourceDeploymentService:
    """Run source validation and deploy one exact GitHub revision."""

    def __init__(
        self,
        config: Mapping[str, Any],
        env: Mapping[str, str] | None = None,
        *,
        memory: Any | None = None,
        payload_gateway: Any | None = None,
        design_service: Any | None = None,
    ) -> None:
        self.config = dict(config)
        self.env = dict(os.environ if env is None else env)
        self.memory = memory
        self.payload_gateway = payload_gateway
        self.design_service = design_service
        self._preview_home = Path(tempfile.mkdtemp(prefix="site-agent-preview-home-"))
        self._preview_home.chmod(0o700)
        for directory in (self._preview_home / "tmp", self._preview_home / ".npm"):
            directory.mkdir(mode=0o700)
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
                        "error": "source deployment process restarted; restarting the exact compiled preview",
                        "resume": bool(job.get("worktree_path")),
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
        self._futures: dict[str, Any] = {}
        self._runtimes: dict[str, tuple[subprocess.Popen[str], Path]] = {}
        self._runtime_logs: dict[str, tuple[Any, Path]] = {}
        with self._lock:
            self._recover_production_jobs()
            self._sweep_stale_worktrees()
            self._persist()
        for job_id, branch, commit, mode in recover:
            self._futures[job_id] = self._executor.submit(self._run_job, job_id, branch, commit, mode)

    def _sweep_stale_worktrees(self) -> None:
        """Remove this tenant's preview worktrees that no retained job owns.

        A killed build or a process restart leaves a full checkout (and its
        node_modules) behind. Only worktrees registered against this tenant's
        own checkout are considered, and one that a resumable job still points
        at is kept.
        """
        try:
            checkout = self._local_checkout()
        except SourceDeploymentError:
            return
        try:
            listing = self._run(["git", "worktree", "list", "--porcelain"], checkout, timeout=60).stdout
        except SourceDeploymentError:
            return
        referenced = {
            str(Path(str(job.get("worktree_path"))).expanduser().resolve())
            for job in self._jobs.values()
            if isinstance(job, Mapping) and job.get("worktree_path")
        }
        for block in listing.split("\n\n"):
            path = next((line[len("worktree "):] for line in block.splitlines() if line.startswith("worktree ")), "")
            if not path:
                continue
            resolved = Path(path).expanduser().resolve()
            if resolved == checkout or not resolved.name.startswith("site-agent-source-preview-"):
                continue
            if str(resolved) in referenced:
                continue
            try:
                self._run(["git", "worktree", "remove", "--force", str(resolved)], checkout, timeout=120)
            except SourceDeploymentError:
                pass
            shutil.rmtree(resolved, ignore_errors=True)
        try:
            self._run(["git", "worktree", "prune"], checkout, timeout=60)
        except SourceDeploymentError:
            pass
        # A worktree removed without its Git registration leaves a partial
        # directory behind. A real preview worktree always carries both a Git
        # pointer and the Worker configuration, so an unreferenced directory
        # with neither is garbage from an interrupted build.
        root = checkout.parent
        if not root.is_dir():
            return
        for entry in root.glob("site-agent-source-preview-*"):
            if not entry.is_dir() or str(entry.resolve()) in referenced:
                continue
            if (entry / ".git").exists() or (entry / "wrangler.jsonc").exists():
                continue
            shutil.rmtree(entry, ignore_errors=True)

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
            draft = next((row for row in self.memory.list_drafts(limit=500)
                if int(row.get("id") or 0) == int(job.get("draft_id") or 0)), None) if self.memory is not None else None
            if isinstance(((draft or {}).get("meta") or {}).get("growth_package"), Mapping):
                # Receipt refresh is also called by GET. It may project a pending
                # checkpoint, but it must never perform GitHub writes here.
                job.setdefault("growth_journal", {"status": "recording_pending"})
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
        job["release_started_at"] = str(receipt.get("startedAt") or "") or job.get("release_started_at")
        job["release_finished_at"] = str(receipt.get("finishedAt") or "") or job.get("release_finished_at")
        self._jobs[str(job.get("id") or "")] = job
        self._persist()
        return job

    def _sync_publish_failure(self, job: Mapping[str, Any]) -> None:
        if self.memory is not None and job.get("mode") == _PRODUCTION and job.get("draft_id") is not None:
            draft_id = int(job["draft_id"])
            self.memory.update_draft_status(draft_id, "publish_failed")
            draft = next((row for row in self.memory.list_drafts(limit=500) if int(row.get("id") or 0) == draft_id), None)
            package = (draft.get("meta") or {}).get("growth_package") if draft else None
            if isinstance(package, Mapping) and package.get("candidateType") == "source_code":
                reason = str(job.get("error") or "The approved website release failed its production checks")[:700]
                for initiative in self.memory.list_strategy_initiatives(limit=500):
                    if int(initiative.get("draft_id") or 0) != draft_id or initiative.get("state") not in {"publishing", "verifying_live"}:
                        continue
                    validation = dict(initiative.get("validation") or {})
                    validation.update({"status": "blocked", "error": reason})
                    self.memory.transition_strategy_initiative(
                        int(initiative["id"]), "blocked", last_error=reason, validation=validation,
                    )
                from .growth_candidates import wake_growth_pending

                wake_growth_pending(self.memory)

    def _fail_job(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(status="failed", ok=False, error=error[:1_000], updated_at=_now())
            self._persist()
        self._sync_publish_failure(job)

    def _reviewed_payload_effects(self, draft_id: Any, request: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
        try:
            numeric_id = int(draft_id)
        except (TypeError, ValueError):
            if request.get("payload_effects") or request.get("payload_revision_set_hash"):
                raise SourceDeploymentError("the exact Payload dependency set requires an owner review draft identity")
            return [], ""
        draft = self.memory.get_draft(numeric_id) if self.memory is not None and callable(getattr(self.memory, "get_draft", None)) else None
        if not isinstance(draft, Mapping):
            if request.get("payload_effects") or request.get("payload_revision_set_hash"):
                raise SourceDeploymentError("the exact Payload dependency set has no persisted owner review draft")
            return [], ""
        meta = draft.get("meta") if isinstance(draft.get("meta"), Mapping) else {}
        effects = meta.get("payload_effects") if isinstance(meta.get("payload_effects"), list) else []
        if not effects:
            if request.get("payload_effects") or request.get("payload_revision_set_hash"):
                raise SourceDeploymentError("the review draft does not contain the requested exact Payload dependency set")
            return [], ""
        from ..core.payload_receipts import payload_revision_manifest

        try:
            normalized, digest = payload_revision_manifest(effects)
        except ValueError as exc:
            raise SourceDeploymentError(f"the review draft's Payload dependency set is invalid: {exc}") from exc
        if normalized != effects:
            raise SourceDeploymentError("the review draft's Payload dependency set is not in canonical form")
        recorded = str(meta.get("payload_revision_set_hash") or "")
        if recorded != digest:
            raise SourceDeploymentError("the review draft's Payload dependency hash does not match its receipts")
        supplied = str(request.get("payload_revision_set_hash") or "")
        if supplied and supplied != digest:
            raise SourceDeploymentError("the requested preview does not match the reviewed Payload revisions")
        for effect in normalized:
            if (
                effect.get("kind") not in {"collection", "global"}
                or not str(effect.get("target") or "").strip()
                or not str(effect.get("document_id") or "").strip()
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(effect.get("revision") or ""))
                or not str(effect.get("locale") or "").strip()
            ):
                raise SourceDeploymentError("the review draft contains an incomplete Payload revision receipt")
        if request.get("payload_effects") and request.get("payload_effects") != normalized:
            raise SourceDeploymentError("the requested preview's Payload receipts differ from the owner review")
        return normalized, digest

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

    def _preview_env(self, *, production: bool = False, payload_secret: str | None = None) -> dict[str, str]:
        """Give untrusted candidate code only an isolated local-preview environment."""
        preview = {
            name: str(self.env[name])
            for name in _PREVIEW_ENV_ALLOWLIST
            if str(self.env.get(name) or "")
        }
        node_path = str(self.settings.get("node_path") or "").strip()
        npm_command = str(self.settings.get("npm_command") or "").strip()
        tool_paths = [str(Path(npm_command).expanduser().parent)] if npm_command else []
        if node_path:
            tool_paths.append(node_path)
        if tool_paths:
            preview["PATH"] = os.pathsep.join([*tool_paths, preview.get("PATH", "")])
        preview["HOME"] = str(self._preview_home)
        preview["TMPDIR"] = str(self._preview_home / "tmp")
        preview["TMP"] = preview["TMPDIR"]
        preview["TEMP"] = preview["TMPDIR"]
        preview["NPM_CONFIG_CACHE"] = str(self._preview_home / ".npm")
        preview["NPM_CONFIG_INCLUDE"] = "dev"
        if production:
            preview["NODE_ENV"] = "production"
        elif self.env.get("NODE_ENV"):
            preview["NODE_ENV"] = str(self.env["NODE_ENV"])
        preview["NEXT_TELEMETRY_DISABLED"] = "1"
        # Payload needs a secret to initialize in the local Worker. Never pass
        # the tenant's signing key into a candidate build or preview process.
        preview["PAYLOAD_SECRET"] = payload_secret or secrets.token_urlsafe(48)
        preview["HELLOADA_PREVIEW_MODE"] = "1"
        return preview

    def _verify_toolchain(self, cwd: Path) -> str:
        from ..hands.site_build import configured_build_environment, SiteBuildError

        try:
            configured_build_environment(self.settings, cwd, self._preview_env(production=True), run=self._run)
        except SiteBuildError as exc:
            raise SourceDeploymentError(str(exc)) from exc
        return str(self.settings["npm_command"])

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
            from ..hands.opencode_runner import summarize_build_failure
            output = summarize_build_failure((result.stdout or "") + "\n" + (result.stderr or ""))
            raise SourceDeploymentError(f"{' '.join(command[:4])}: {output or 'command failed'}")
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

    def _worktree(self, checkout: Path, branch: str, commit: str, *, retained: bool = False) -> tuple[Path, str]:
        fetch_timeout = int(self.settings.get("fetch_timeout_seconds") or 120)
        if retained:
            local_head = self._run(["git", "rev-parse", "--verify", f"{commit}^{{commit}}"], checkout, timeout=30).stdout.strip().lower()
        else:
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

    def _mark_step(self, job: Mapping[str, Any], step: str) -> None:
        """Publish the current build step so the owner sees movement, not a spinner."""
        with self._lock:
            current = self._jobs.get(str(job.get("id") or ""))
            if current is None:
                return
            current["build_step"] = step
            current["updated_at"] = _now()
            self._persist()

    def ensure_dependencies(self, worktree: Path, *, timeout: int,
                            preview_secret: str = "", npm: str | None = None,
                            ) -> list[dict[str, Any]]:
        """Install one worktree's exact locked dependencies through the cache.

        The compiled preview and the owner turn both run tenant code in an
        isolated worktree, and both need the tenant's real toolchain. They share
        one cache keyed by the lockfile, so whichever runs second hard-links an
        already-installed tree instead of installing a second copy.
        """
        checks: list[dict[str, Any]] = []
        npm = npm or self._verify_toolchain(worktree)
        from .release_dependencies import prepare_release_dependencies

        def seed_private_package(command: list[str], directory: Path) -> None:
            checks.append(self._check(
                command, directory, "private_package_cache", timeout,
                preview_secret=preview_secret,
            ))

        assets = prepare_release_dependencies(
            worktree,
            github_api_token(self.config, self._resolved_env()),
            npm,
            self._preview_home / "tmp",
            seed_private_package,
        )
        dependency_key = self._node_modules_key(worktree)
        if self._link_cached_node_modules(worktree, dependency_key):
            checks.append({"name": "dependencies", "ok": True, "cached": True})
        else:
            checks.append(self._check(
                [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefer-offline"],
                worktree, "dependencies", timeout, preview_secret=preview_secret,
            ))
            self._store_node_modules(worktree, dependency_key)
        if not assets:
            raise SourceDeploymentError("candidate source did not resolve the locked shared package")
        return checks

    def _node_modules_root(self) -> Path | None:
        configured = str(self.settings.get("worktree_root") or "").strip()
        root = Path(configured).expanduser().resolve() if configured else self._local_checkout().parent
        if not root.is_dir():
            return None
        tenant = re.sub(r"[^a-z0-9-]+", "-", str(self.config.get("instance_name") or "tenant").lower()).strip("-")
        if not tenant:
            return None
        return root / ".site-agent-node-modules" / tenant

    @staticmethod
    def _node_modules_key(worktree: Path) -> str:
        digest = hashlib.sha256()
        for name in ("package.json", "package-lock.json"):
            digest.update(name.encode("utf-8"))
            path = worktree / name
            digest.update(path.read_bytes() if path.is_file() else b"")
        return digest.hexdigest()[:24]

    def _link_cached_node_modules(self, worktree: Path, key: str) -> bool:
        """Hard-link an exact, already-installed dependency tree into a new worktree.

        A preview starts from a fresh Git worktree, so a cold ``npm ci`` of the
        same lockfile ran on every build. The tree is identical for an identical
        lockfile, and hard links cost only directory metadata.
        """
        root = self._node_modules_root()
        if root is None:
            return False
        cache = root / key
        if not (cache / ".site-agent-cache-key").is_file():
            return False
        target = worktree / "node_modules"
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        try:
            result = subprocess.run(
                ["cp", "-a", "-l", str(cache), str(target)],
                capture_output=True, text=True, timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0:
            shutil.rmtree(target, ignore_errors=True)
            return False
        (target / ".site-agent-cache-key").write_text(key, encoding="utf-8")
        return True

    def _store_node_modules(self, worktree: Path, key: str) -> None:
        root = self._node_modules_root()
        if root is None:
            return
        cache = root / key
        if cache.exists():
            return
        source = worktree / "node_modules"
        if not source.is_dir():
            return
        try:
            root.mkdir(parents=True, exist_ok=True)
            staging = root / f".{key}.{os.getpid()}"
            shutil.rmtree(staging, ignore_errors=True)
            result = subprocess.run(
                ["cp", "-a", "-l", str(source), str(staging)],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0:
                shutil.rmtree(staging, ignore_errors=True)
                return
            (staging / ".site-agent-cache-key").write_text(key, encoding="utf-8")
            os.rename(staging, cache)
        except (OSError, subprocess.TimeoutExpired):
            return
        # One lockfile identity per tenant is normal; keep one previous build in
        # case the owner reverts a dependency change.
        entries = sorted(
            (item for item in root.iterdir() if item.is_dir() and not item.name.startswith(".")),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for stale in entries[2:]:
            shutil.rmtree(stale, ignore_errors=True)

    def _check(
        self,
        command: list[str],
        cwd: Path,
        name: str,
        timeout: int,
        *,
        parse_json: bool = False,
        production: bool = False,
        preview_secret: str | None = None,
        local_payload: bool = False,
        env_extra: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            child_env = self._preview_env(production=production, payload_secret=preview_secret)
            if env_extra:
                child_env.update({key: str(value) for key, value in env_extra.items()})
            if local_payload:
                child_env.update({"NODE_ENV": "development", "PAYLOAD_CLI": "1"})
            result = subprocess.run(
                command,
                cwd=str(cwd),
                env=child_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SourceDeploymentError(f"command failed: {' '.join(command[:4])}: {str(exc)[:300]}") from exc
        if result.returncode:
            output = (result.stderr or result.stdout or "command failed").strip()
            raise SourceDeploymentError(f"{' '.join(command[:4])}: {output[-1_500:]}")
        item: dict[str, Any] = {"name": name, "ok": True, "seconds": round(time.monotonic() - started, 1)}
        output = (result.stdout or result.stderr or "").strip()
        if parse_json:
            try:
                inventory = json.loads(output)
            except json.JSONDecodeError as exc:
                raise SourceDeploymentError(f"{name} did not return JSON") from exc
            if isinstance(inventory, Mapping):
                item["inventory"] = {
                    key: inventory.get(key)
                    for key in ("root", "filesScanned", "editableCount", "dynamicCount", "bindingCount", "editableImages", "imageElements", "violations")
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

    def _retained_design_run(self, run_id: str, commit: str) -> Mapping[str, Any]:
        """Resolve the immutable candidate before its owner decision exists.

        Browser validation must precede that decision. This is the same compiled
        preview job, not an approval or a separate candidate store.
        """
        run = self.memory.get_design_run(str(run_id)) if self.memory is not None else None
        if (not isinstance(run, Mapping) or run.get("mode") != "production_candidate"
                or not run.get("publishable")
                or run.get("status") not in {"validating", "needs_repair", "incomplete", "ready_for_review"}):
            raise SourceDeploymentError("compiled preview requires a retained managed candidate")
        if run.get("candidate_sha") != commit or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise SourceDeploymentError("compiled preview requires the retained run's exact candidate")
        return run

    def _verify_candidate_source_boundary(self, worktree: Path, commit: str, draft_id: Any,
                                          *, design_run_id: str = "") -> dict[str, Any]:
        """Reject source outside the tenant presentation allowlist before any candidate code runs."""
        if design_run_id:
            from dataclasses import replace
            from ..core.design_contracts import DesignContextSnapshot
            from ..hands.design_quality import _repository_findings

            run = self._retained_design_run(design_run_id, commit)
            if self.design_service is None:
                raise SourceDeploymentError("retained candidate validation service is unavailable")
            policy = self.design_service.quality_policy_for_run(design_run_id)
            snapshot = run.get("context_snapshot")
            if snapshot and policy.approved_media_files:
                policy = replace(policy, approved_media_files=self.design_service._quality_media_files(
                    DesignContextSnapshot.from_dict(snapshot)))
            findings = _repository_findings(worktree, str(run["base_sha"]), commit, policy)
            if findings:
                raise SourceDeploymentError("candidate source boundary failed: " + str(findings[0]["message"]))
            return {"name": "presentation_source_boundary", "ok": True, "run_id": design_run_id}
        try:
            numeric_id = int(draft_id)
        except (TypeError, ValueError) as exc:
            raise SourceDeploymentError("compiled source preview requires its exact owner review draft") from exc
        draft = self.memory.get_draft(numeric_id) if self.memory is not None else None
        if not isinstance(draft, Mapping):
            raise SourceDeploymentError("compiled source preview has no persisted owner review draft")
        if draft.get("kind") not in {"merge", "rollback", "design"} or draft.get("status") != "pending":
            raise SourceDeploymentError("compiled source preview requires a pending source review decision")
        meta = draft.get("meta") if isinstance(draft.get("meta"), Mapping) else {}
        base_sha = str(meta.get("base_sha") or "").strip().lower()
        candidate_sha = str(meta.get("candidate_sha") or meta.get("head_sha") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
            raise SourceDeploymentError("owner review draft has no immutable source base SHA")
        if candidate_sha != commit:
            raise SourceDeploymentError("owner review draft does not identify the exact compiled source commit")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise SourceDeploymentError("compiled source boundary requires a full candidate SHA")

        try:
            from ..hands.repo_changes import source_path_allowed

            output = self._run(
                ["git", "diff", "--name-only", "-z", f"{base_sha}...{commit}"],
                worktree,
                timeout=60,
            ).stdout
        except SourceDeploymentError as exc:
            raise SourceDeploymentError(f"candidate source boundary could not be verified: {exc}") from exc
        paths = [path for path in output.split("\0") if path]
        if not paths:
            raise SourceDeploymentError("candidate has no presentation source changes relative to its reviewed base")
        # The preview boundary accepts exactly what the authoring gate accepted:
        # one ownership decision, so a reviewed change can never be refused here
        # after the agent already made it.
        prohibited = [path for path in paths if not source_path_allowed(self.config, path)]
        if prohibited:
            names = ", ".join(prohibited[:8])
            suffix = f" and {len(prohibited) - 8} more" if len(prohibited) > 8 else ""
            raise SourceDeploymentError(
                "candidate changed platform-owned or non-presentation files before build: " + names + suffix
            )
        return {"name": "presentation_source_boundary", "ok": True, "changed_files": len(paths)}

    def _preview_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    def _prepare_preview_runtime(self, worktree: Path, job: dict[str, Any]) -> None:
        """Point the disposable build at the signed path its runtime is served from."""
        original = worktree / "next.config.mjs"
        retained = worktree / ".helloada-source-preview.next.mjs"
        if original.is_symlink() or not original.is_file() or retained.exists():
            raise SourceDeploymentError("compiled preview needs the exact managed Next config")
        worker_path = worktree / "wrangler.jsonc"
        worker = json.loads(worker_path.read_text(encoding="utf-8"))
        databases = [item for item in worker.get("d1_databases") or [] if item.get("binding") == "D1"]
        buckets = [item for item in worker.get("r2_buckets") or [] if item.get("binding") == "R2"]
        if len(databases) != 1 or len(buckets) != 1:
            raise SourceDeploymentError("compiled website preview requires the canonical D1 and R2 bindings")
        # This is the existing website-only OpenNext preview, not a second
        # deployment of Messages/AI/email. Never initialize remote side-effect
        # bindings while importing public content or rendering the candidate.
        local_worker = {key: worker[key] for key in ("name", "compatibility_date", "compatibility_flags") if key in worker}
        public_vars = {"HELLOADA_TENANT_ID", "HELLOADA_SITE_NAME", "HELLOADA_TEMPLATE_SCHEMA",
                       "HELLOADA_SHARED_RUNTIME_FINGERPRINT", "HELLOADA_PAYLOAD_CORE_VERSION",
                       "HELLOADA_PAYLOAD_SCHEMA_REVISION", "HELLOADA_CONTENT_CONTRACT_VERSION",
                       "HELLOADA_SCHEMA_IDENTITY", "HELLOADA_PAYLOAD_MIGRATION_HEAD", "HELLOADA_SITE_AGENT_VERSION"}
        local_worker.update({"main": ".open-next/worker.js", "assets": {"directory": ".open-next/assets", "binding": "ASSETS"},
                             "d1_databases": [{key: value for key, value in item.items() if key != "remote"} for item in databases],
                             "r2_buckets": [{key: value for key, value in item.items() if key != "remote"} for item in buckets],
                             "vars": {key: value for key, value in (worker.get("vars") or {}).items()
                                      if key in public_vars or key.startswith("NEXT_PUBLIC_")}})
        worker_path.write_text(json.dumps(local_worker, indent=2) + "\n", encoding="utf-8")
        base_path = str(job.get("runtime_base_path") or "")
        if not base_path.startswith(_PREVIEW_PATH_PREFIX) or ".." in base_path.split("/"):
            raise SourceDeploymentError("compiled preview has no signed runtime path")
        original.rename(retained)
        original.write_text(
            "import original from './.helloada-source-preview.next.mjs'\n"
            "export default async (phase, context) => {\n"
            " const config = typeof original === 'function' ? await original(phase, context) : original\n"
            f" return {{ ...config, basePath: {json.dumps(base_path)}, assetPrefix: {json.dumps(base_path)} }}\n"
            "}\n", encoding="utf-8",
        )
        public = worktree / "public"
        job["public_asset_roots"] = [f"/{item.name}" + ("/" if item.is_dir() else "")
                                    for item in sorted(public.iterdir()) if not item.is_symlink()] if public.is_dir() else []

    @staticmethod
    def _rewrite_runtime_assets(body: bytes, content_type: str, job: Mapping[str, Any]) -> bytes:
        """Mount root-relative public asset URLs. Navigation belongs to Next.

        The preview build sets Next's ``basePath`` to this mount, so the client
        router and every ``next/link`` already resolve site routes inside the
        preview. Rewriting those hrefs as well made the router add the mount a
        second time: an in-preview click landed on a doubled URL, the page went
        blank and the prefetch answered 401. Next does not mount plain
        root-relative asset URLs (``<img src="/photos/x.webp">``,
        ``url(/fonts/x.woff2)``) in SSR HTML, its RSC payload or its bundles, so
        those are the only thing this transport rewrites.
        """
        base = str(job.get("runtime_base_path") or "")
        roots = list(job.get("public_asset_roots") or []) + list(_PREVIEW_CANDIDATE_ASSET_ROOTS)
        if not base or not roots or not any(
            kind in content_type for kind in ("text/html", "text/css", "javascript", "text/x-component")
        ):
            return body
        pattern = re.compile(r'''(?P<prefix>\\?["']|url\(\s*["']?)(?P<asset>''' + "|".join(re.escape(root) for root in roots) + ")")
        return pattern.sub(lambda match: match["prefix"] + base + match["asset"], body.decode("utf-8")).encode("utf-8")

    @staticmethod
    def _preview_root_is_ready(status: int) -> bool:
        if int(status) == 404:
            raise SourceDeploymentError(
                "compiled preview homepage returned HTTP 404; refusing to mark an unrendered site ready"
            )
        return int(status) == 200

    def _runtime_log_tail(self, job_id: str, limit: int = 1_500) -> str:
        entry = self._runtime_logs.get(str(job_id))
        if entry is None:
            return ""
        _stream, path = entry
        try:
            return path.read_text(errors="replace")[-limit:].strip()
        except OSError:
            return ""

    def _stop_runtime(self, job_id: str) -> None:
        log_entry = self._runtime_logs.pop(str(job_id), None)
        if log_entry is not None:
            try:
                log_entry[0].close()
            except OSError:
                pass
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

    def _start_runtime(
        self,
        job: dict[str, Any],
        worktree: Path,
        expected_commit: str | None = None,
        *,
        preview_secret: str,
    ) -> dict[str, Any]:
        """Start the exact OpenNext build behind the tenant-scoped API proxy.

        The browser never receives the loopback address.  Keeping the process on
        the site-agent host gives the owner a stable preview URL without creating
        a second Worker, database, or public Cloudflare deployment.
        """
        for other_id in list(self._runtimes):
            if other_id != str(job["id"]):
                self._stop_runtime(other_id)

        port = self._preview_port()
        base_path = str(job.get("runtime_base_path") or "")
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
        # Keep the runtime's own output: a Worker that never binds its port is
        # invisible otherwise, and the boot error is the only useful evidence.
        log_path = self._preview_home / "tmp" / f"runtime-{job['id']}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_stream = log_path.open("wb")
        try:
            process = subprocess.Popen(
                command,
                cwd=str(worktree),
                env=self._preview_env(production=True, payload_secret=preview_secret),
                stdin=subprocess.DEVNULL,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
        except (OSError, ValueError) as exc:
            log_stream.close()
            raise SourceDeploymentError(f"compiled preview could not start: {str(exc)[:300]}") from exc
        self._runtime_logs[str(job["id"])] = (log_stream, log_path)

        self._runtimes[str(job["id"])] = (process, worktree)
        timeout = max(30, int(self.settings.get("preview_start_timeout_seconds") or 180))
        deadline = time.monotonic() + timeout
        ready = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._stop_runtime(str(job["id"]))
                raise SourceDeploymentError("compiled preview process exited before it was ready")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{base_path}/", timeout=3) as response:
                    if self._preview_root_is_ready(int(response.status)):
                        ready = True
                        break
            except urllib.error.HTTPError as exc:
                try:
                    self._preview_root_is_ready(exc.code)
                except SourceDeploymentError:
                    self._stop_runtime(str(job["id"]))
                    raise SourceDeploymentError(str(exc)) from exc
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(1)
        if not ready:
            tail = self._runtime_log_tail(str(job["id"]))
            self._stop_runtime(str(job["id"]))
            raise SourceDeploymentError(
                "compiled preview did not become ready in time" + (f"\n{tail}" if tail else "")
            )
        revision = self._verify_public_revision(
            f"http://127.0.0.1:{port}{base_path}",
            str(expected_commit or job.get("commit") or ""),
            label="compiled preview",
        )
        try:
            # The home page is the site: a candidate that changes shared chrome
            # or a layout can break it while every authored route still renders,
            # so it is always part of the render gate even when the change
            # touched no Payload document on it.
            required_routes = self._required_preview_routes(job.get("preview_routes") or [])
            rendered = self._verify_preview_routes(
                f"http://127.0.0.1:{port}{base_path}",
                required_routes,
                job,
            )
        except SourceDeploymentError:
            self._stop_runtime(str(job["id"]))
            raise
        return {
            "status": "ready",
            "mode": _COMPILED_PREVIEW,
            "runtime_base_path": str(job.get("runtime_base_path") or ""),
            "deployment_mode": "isolated_host_runtime",
            "runtime_port": port,
            "revision_verification": revision,
            "rendered_routes": rendered,
        }

    def _required_preview_routes(self, routes: Sequence[str]) -> list[str]:
        """Every authored route, plus the home page.

        The home page is the site. A candidate that changes shared chrome, a
        layout or a stylesheet can break it while every route it authored still
        renders, and the owner lands on it first.
        """
        required = list(routes)
        if "/" not in required:
            required.insert(0, "/")
        return required

    def _verify_preview_routes(
        self, base: str, routes: Sequence[str], job: Mapping[str, Any] | None = None,
    ) -> list[str]:
        """Every page this candidate authored must render in its own preview.

        A build that compiles is not a page. A component can throw while
        rendering, and without this the owner is handed a "ready" draft whose
        page is a 500. The route list comes from the exact Payload documents
        this candidate saved, so it checks what the owner asked for rather than
        every route on the site.

        A page that returns 200 is still not evidence that its files exist: the
        markup names icons, images, stylesheets and chunks, and any of those can
        404 while the document renders. Each rendered page's same-origin asset
        references are requested too, so a link to a file the build never
        emitted fails here instead of in the owner's browser tab.
        """
        if not base.endswith("/"):
            base += "/"
        verified: list[str] = []
        assets: dict[str, str] = {}
        for route in routes:
            url = urllib.parse.urljoin(base, route.lstrip("/") if route != "/" else ".")
            try:
                with urllib.request.urlopen(url, timeout=20) as response:
                    status = int(response.status)
                    content_type = str(response.headers.get("Content-Type") or "")
                    body = response.read() if "html" in content_type else b""
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                content_type = ""
                body = b""
            except (OSError, urllib.error.URLError) as exc:
                raise SourceDeploymentError(
                    f"compiled preview route {route} could not be requested: {str(exc)[:200]}"
                ) from exc
            if not 200 <= status < 300:
                raise SourceDeploymentError(
                    f"compiled preview route {route} returned {status}; the candidate does not render"
                )
            verified.append(route)
            if body and job is not None:
                # Check the document the browser will actually receive: the
                # preview mounts the candidate's own asset URLs, and a reference
                # that only resolves unmounted is not what the owner sees.
                body = self._rewrite_runtime_assets(body, content_type, job)
            for reference in self._document_asset_references(body, url):
                assets.setdefault(reference, route)
        for reference, route in assets.items():
            try:
                with urllib.request.urlopen(reference, timeout=20) as response:
                    asset_status = int(response.status)
            except urllib.error.HTTPError as exc:
                asset_status = int(exc.code)
            except (OSError, urllib.error.URLError) as exc:
                raise SourceDeploymentError(
                    f"compiled preview page {route} references {reference}, which could not be "
                    f"requested: {str(exc)[:200]}"
                ) from exc
            if not 200 <= asset_status < 300:
                raise SourceDeploymentError(
                    f"compiled preview page {route} references {reference}, which returned "
                    f"{asset_status}; the candidate names a file it cannot serve"
                )
        return verified

    def _document_asset_references(self, body: bytes, page_url: str) -> list[str]:
        """Same-origin files this document names, deduplicated and bounded."""
        if not body:
            return []
        parser = _DocumentAssets()
        try:
            parser.feed(body.decode("utf-8", "replace"))
        except Exception:  # A malformed document still returns 200 above.
            return []
        page = urllib.parse.urlsplit(page_url)
        found: list[str] = []
        for raw in parser.urls:
            if raw.startswith(("data:", "mailto:", "tel:", "javascript:", "#")):
                continue
            absolute = urllib.parse.urljoin(page_url, raw)
            parts = urllib.parse.urlsplit(absolute)
            if parts.scheme not in ("http", "https"):
                continue
            if (parts.scheme, parts.netloc) != (page.scheme, page.netloc):
                continue  # Third-party fonts and scripts are not this preview's to serve.
            if absolute == page_url or absolute in found:
                continue
            found.append(absolute)
            if len(found) >= 80:
                break
        return found

    def _content_inventory(self, checkout: Path, worktree: Path, timeout: int,
                           preview_secret: str) -> dict[str, Any]:
        """Record the shared content-authority inventory without hiding evidence.

        The design quality gates turn these violations into Ada's repair brief;
        the preview still renders so browser behavior can be observed.
        """
        try:
            result = subprocess.run(
                self._inventory_command(checkout, worktree), cwd=str(worktree),
                env=self._preview_env(payload_secret=preview_secret),
                capture_output=True, text=True, timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "incomplete", "error": str(exc)[:400]}
        try:
            report = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            report = None
        if not isinstance(report, Mapping):
            return {"status": "incomplete", "error": (result.stderr or "")[-600:],
                    "returncode": result.returncode}
        if result.returncode and not report.get("violations"):
            # A non-zero exit without violations is a tooling failure, never a
            # clean candidate. Keep the reason so the gate fails closed.
            return {"status": "incomplete", "returncode": result.returncode,
                    "error": (result.stderr or "")[-600:]}
        report = dict(report)
        report.setdefault("status", "failed" if report.get("violations") else "passed")
        return report

    def _seed_canonical_preview(self, worktree: Path, job: dict[str, Any], npm: str,
                                timeout: int, preview_secret: str) -> list[dict[str, Any]]:
        from .compiled_preview_content import canonical_preview_snapshot

        snapshot = canonical_preview_snapshot(self.payload_gateway, list(job.get("payload_effects") or []))
        job["preview_content_hash"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        fd, name = tempfile.mkstemp(prefix="canonical-content-", suffix=".json", dir=self._preview_home / "tmp")
        path = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(snapshot, stream)
            job["preview_routes"] = list(snapshot.get("routes") or [])
            checks = [self._check([npm, "run", "payload", "--", "migrate"], worktree,
                       "preview_schema", timeout, preview_secret=preview_secret, local_payload=True)]
            script = Path(__file__).with_name("seed_compiled_preview.mjs")
            # The seed initializes OpenNext's local dev context, which leaves a
            # Miniflare child running. Capture its output in a file instead of a
            # pipe so the step returns when the seed process exits rather than
            # waiting for that child to close an inherited descriptor.
            checks.append(self._check_to_file(
                [str(Path(str(self.settings["node_path"])) / "node"), "--import", "tsx",
                 str(script), str(worktree), str(path)], worktree, "preview_content", timeout,
                preview_secret=preview_secret, local_payload=True))
            return checks
        finally:
            path.unlink(missing_ok=True)

    def _check_to_file(
        self,
        command: list[str],
        cwd: Path,
        name: str,
        timeout: int,
        *,
        preview_secret: str | None = None,
        local_payload: bool = False,
    ) -> dict[str, Any]:
        """Run one preview step with file-backed output so a lingering child cannot block it."""
        log_path = self._preview_home / "tmp" / f"{name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        child_env = self._preview_env(payload_secret=preview_secret)
        if local_payload:
            child_env.update({"NODE_ENV": "development", "PAYLOAD_CLI": "1"})
        try:
            with log_path.open("wb") as stream:
                result = subprocess.run(
                    command, cwd=str(cwd), env=child_env,
                    stdout=stream, stderr=subprocess.STDOUT, timeout=timeout,
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            tail = log_path.read_text(errors="replace")[-1_500:] if log_path.is_file() else ""
            raise SourceDeploymentError(
                f"command failed: {' '.join(command[:4])}: {str(exc)[:300]}" + (f"\n{tail}" if tail else "")
            ) from exc
        if result.returncode:
            tail = log_path.read_text(errors="replace")[-1_500:] if log_path.is_file() else ""
            raise SourceDeploymentError(f"{' '.join(command[:4])}: {tail}")
        return {"name": name, "ok": True}

    @staticmethod
    def _preview_secret_from(worktree: Path) -> str:
        try:
            for line in (worktree / ".dev.vars").read_text(encoding="utf-8").splitlines():
                name, _, value = line.partition("=")
                if name.strip() == "PAYLOAD_SECRET":
                    return str(json.loads(value.strip()))
        except (OSError, UnicodeError, ValueError):
            return ""
        return ""

    def _resume_build(
        self, job: dict[str, Any], branch: str, commit: str, mode: str,
    ) -> dict[str, Any] | None:
        """Restart an already-compiled preview instead of rebuilding it.

        A process restart used to discard the compiled output and pay the whole
        build again before the owner could look at their own candidate. The
        worktree and its OpenNext output survive on disk; only the runtime has
        to start.
        """
        if mode != _COMPILED_PREVIEW or not job.get("resume"):
            return None
        # A resumed worktree keeps the basePath it was compiled with, and that
        # basePath carries this job's signature. A changed signing key or a
        # rebuilt identity means the compiled output no longer matches the
        # address it would be served at.
        # Only a build compiled for the signed path its own origin serves can be
        # resumed; an older job carries a mount this service no longer serves.
        if not str(job.get("runtime_base_path") or "").startswith(_PREVIEW_PATH_PREFIX):
            return None
        raw = str(job.get("worktree_path") or "").strip()
        if not raw:
            return None
        worktree = Path(raw).expanduser().resolve()
        if not worktree.is_dir() or not (worktree / ".open-next").is_dir():
            return None
        try:
            head = self._run(["git", "rev-parse", "HEAD"], worktree, timeout=30).stdout.strip().lower()
        except SourceDeploymentError:
            return None
        if head != commit:
            return None
        preview_secret = self._preview_secret_from(worktree)
        if not preview_secret:
            return None
        self._mark_step(job, "runtime")
        runtime = self._start_runtime(job, worktree, head, preview_secret=preview_secret)
        return {
            "ok": True,
            "branch": branch,
            "commit": head,
            "checks": list(job.get("checks") or []),
            "worktree_path": str(worktree),
            "resumed": True,
            **runtime,
        }

    def _build(self, job: dict[str, Any], branch: str, commit: str, mode: str) -> dict[str, Any]:
        if mode != _COMPILED_PREVIEW:
            raise SourceDeploymentError("production builds and uploads are owned by the central VPS release pipeline")
        checkout = self._local_checkout()
        run_id = str(job.get("design_run_id") or "")
        self._mark_step(job, "worktree")
        worktree, local_head = (self._worktree(checkout, branch, commit, retained=True)
                               if run_id else self._worktree(checkout, branch, commit))
        timeout = int(self.settings.get("build_timeout_seconds") or 1_800)
        checks: list[dict[str, Any]] = []
        keep_worktree = False
        preview_secret = secrets.token_urlsafe(48)
        try:
            checks.append(self._verify_candidate_source_boundary(worktree, local_head, job.get("draft_id"),
                          **({"design_run_id": run_id} if run_id else {})))
            # Compile exactly what the release will build: the shared runtime
            # copies replace tenant copies and the retired files are removed
            # before any typecheck, lint or Next build runs.
            self._mark_step(job, "overlay")
            from .shared_runtime import apply_preview_runtime_overlay

            payload_config = (self.config.get("site") or {}).get("payload") or {}
            activation = payload_config.get("runtime_activation") or {}
            runtime_fingerprint = str(activation.get("shared_runtime_fingerprint") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", runtime_fingerprint):
                raise SourceDeploymentError(
                    "the tenant has no activated shared runtime; release the site before previewing"
                )
            runtime_overlay = apply_preview_runtime_overlay(
                worktree,
                package_root=Path(__file__).resolve().parents[1],
                runtime_fingerprint=runtime_fingerprint,
            )
            checks.append({
                "name": "shared_runtime_overlay",
                "ok": True,
                "copied": len(runtime_overlay["copied"]),
                "removed": len(runtime_overlay["removed"]),
            })
            self._write_revision_marker(worktree, local_head)
            npm = self._verify_toolchain(worktree)
            self._mark_step(job, "dependencies")
            checks.extend(self.ensure_dependencies(
                worktree, timeout=timeout, preview_secret=preview_secret, npm=npm,
            ))
            # The candidate compiles the same generated contract the release
            # ships: schema identity, Wrangler pins and the committed-route
            # inventory. This runs before the preview rewrites Wrangler for its
            # isolated local bindings.
            self._mark_step(job, "generate-payload-contract")
            contract_generator = (Path(__file__).resolve().parents[1]
                                  / "templates/next-payload/scripts/generate-payload-contract.mjs")
            checks.append(self._check(
                ["node", "--import", "tsx", str(contract_generator), f"--site-root={worktree}"],
                worktree, "generate_payload_contract", timeout, preview_secret=preview_secret,
                env_extra={"HELLOADA_SHARED_RUNTIME_FINGERPRINT": runtime_fingerprint},
            ))
            self._prepare_preview_runtime(worktree, job)
            local_secrets = worktree / ".dev.vars"
            fd = os.open(local_secrets, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("PAYLOAD_SECRET=" + json.dumps(preview_secret) + "\n")
            if self.payload_gateway is not None:
                self._mark_step(job, "content")
                checks.extend(self._seed_canonical_preview(worktree, job, npm, timeout, preview_secret))
            if not run_id:
                # Design candidates are checked by the design quality gates,
                # which reuse this same inventory and keep browser evidence for
                # Ada's bounded repair. Source-review previews keep the hard
                # pre-build gate.
                checks.append(self._check(self._inventory_command(checkout, worktree), worktree, "source_inventory", timeout, parse_json=True, preview_secret=preview_secret))
            else:
                job["content_authority"] = self._content_inventory(checkout, worktree, timeout, preview_secret)
            self._mark_step(job, "typecheck")
            checks.append(self._check([npm, "run", "typecheck"], worktree, "typecheck", timeout, preview_secret=preview_secret))
            # The release gate is typecheck plus the OpenNext build; it never
            # runs lint. Linting here would fail a preview on canonical runtime
            # files that ship unchanged, so keep the gates identical.
            # OpenNext invokes the managed Next build itself. A separate build
            # here compiles the same candidate twice before the owner sees it.
            self._mark_step(job, "build")
            checks.append(self._check(["npx", "--no-install", "opennextjs-cloudflare", "build"], worktree, "open_next_build", timeout, production=True, preview_secret=preview_secret))

            if run_id:
                store = getattr(self.design_service, "output_artifact_store", None)
                if store is None:
                    raise SourceDeploymentError("compiled candidate requires its existing immutable output store")
                artifact = dict(store.publish(worktree / ".open-next", profile="next_react", candidate_sha=local_head))
                artifact.pop("path", None)
                job["output_artifact"] = {"status": "passed", "mode": "compiled_runtime", **artifact}

            self._mark_step(job, "runtime")
            runtime = self._start_runtime(job, worktree, local_head, preview_secret=preview_secret)
            keep_worktree = True
            result = {
                "ok": True,
                "branch": branch,
                "commit": local_head,
                "worktree_path": str(worktree),
                "checks": checks,
                **({"content_authority": job["content_authority"]} if job.get("content_authority") else {}),
                **({"output_artifact": job["output_artifact"]} if job.get("output_artifact") else {}),
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
        draft = next((row for row in self.memory.list_drafts(limit=500) if int(row.get("id") or 0) == draft_id), None)
        package = (draft.get("meta") or {}).get("growth_package") if draft else None
        if isinstance(package, Mapping) and package.get("candidateType") == "source_code":
            source = package.get("source") if isinstance(package.get("source"), Mapping) else {}
            self.memory.record_strategy_publication_for_draft(
                draft_id,
                baseline={
                    "metric": str(package.get("metric") or "gsc.clicks"),
                    "scope": {"kind": "website_source", "paths": list(source.get("changedPaths") or [])},
                    "gsc": self.memory.latest_snapshot("gsc") or {},
                    "ga4": self.memory.latest_snapshot("ga4") or {},
                },
                published_revision=f"git:{str(result.get('verified_commit') or result.get('commit') or '')}",
                validation={
                    "status": "passed",
                    "liveVerification": {
                        "verified": True,
                        "commit": str(result.get("verified_commit") or result.get("commit") or ""),
                        "releaseId": str(result.get("release_id") or ""),
                    },
                },
            )
        from .growth_candidates import wake_growth_pending

        wake_growth_pending(self.memory)

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
                "preview_url": self._with_preview_url(job).get("preview_url"),
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
        if current_meta.get("growth_initiative_id"):
            from .growth_candidates import wake_growth_pending

            wake_growth_pending(self.memory)

    def _run_job(self, job_id: str, branch: str, requested_commit: str | None, mode: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update({"status": "running", "phase": "building", "updated_at": _now()})
            self._persist()
        try:
            run_id = str(job.get("design_run_id") or "")
            commit = requested_commit or self._head(branch)
            if requested_commit and not re.fullmatch(r"[0-9a-f]{40}", requested_commit):
                raise SourceDeploymentError("requested source commit is invalid")
            current_head = (str(self._retained_design_run(run_id, commit)["candidate_sha"])
                            if run_id else self._head(branch))
            if current_head != commit:
                raise SourceDeploymentError("deployment branch advanced before its build started; rescan and retry")
            result = self._resume_build(job, branch, commit, mode) or self._build(job, branch, commit, mode)
            with self._lock:
                # The address is part of the finished job, not something a
                # reader re-derives: the draft sync, the status endpoint and the
                # workspace all hand out this one value.
                self._jobs[job_id] = self._with_preview_url({
                    **self._jobs[job_id], **result, "updated_at": _now(),
                })
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
        design_run_id = str(body.get("design_run_id") or "")
        if design_run_id:
            if mode != _COMPILED_PREVIEW or draft_id is not None:
                raise SourceDeploymentError("retained design validation is a private preview, not an owner approval")
            run = self._retained_design_run(design_run_id, requested_commit or "")
            planning = _mapping(run.get("planning_json"))
            from ..core.payload_receipts import payload_revision_manifest
            payload_effects, payload_revision_set_hash = payload_revision_manifest(planning.get("payload_effects") or [])
            if not payload_effects or payload_revision_set_hash != planning.get("payload_revision_set_hash"):
                raise SourceDeploymentError("retained design has no exact canonical Payload revision receipts")
        else:
            payload_effects, payload_revision_set_hash = self._reviewed_payload_effects(draft_id, body)
        job_id = str(uuid.uuid4())
        runtime_base_path = ""
        if mode == _COMPILED_PREVIEW:
            # The address names this tenant and this job and is signed over
            # both, so the service that answers it can resolve the request from
            # the URL alone. It is minted once here; every reader is handed the
            # same value.
            try:
                runtime_base_path = preview_host.path_for(
                    preview_host.signing_key(self.env),
                    self.config.get("instance_name"),
                    job_id,
                    preview_host.expiry_for(_now()),
                )
            except preview_host.PreviewHostError as exc:
                raise SourceDeploymentError(f"compiled preview is not configured: {exc}") from exc
        with self._lock:
            for existing in self._jobs.values():
                if not isinstance(existing, Mapping):
                    continue
                if (
                    existing.get("branch") == branch
                    and existing.get("commit") == (requested_commit or existing.get("commit"))
                    and existing.get("mode") == mode
                    and existing.get("draft_id") == draft_id
                    and existing.get("design_run_id", "") == design_run_id
                    # The same source commit against different Payload revisions
                    # is a different preview: it renders different content.
                    and existing.get("payload_revision_set_hash", "") == payload_revision_set_hash
                    and existing.get("status") in {"queued", "running", "verifying", "ready", "deployed"}
                ):
                    return dict(existing)
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
        if runtime_base_path:
            job["runtime_base_path"] = runtime_base_path
        if draft_id is not None:
            job["draft_id"] = draft_id
        if design_run_id:
            job["design_run_id"] = design_run_id
        if payload_effects:
            job["payload_effects"] = payload_effects
            job["payload_revision_set_hash"] = payload_revision_set_hash
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
            self._futures[job_id] = self._executor.submit(self._run_job, job_id, branch, requested_commit, mode)
        except Exception as exc:
            self._fail_job(job_id, str(exc))
            raise SourceDeploymentError("source deployment could not be dispatched") from exc
        return self.status(job_id)

    def ensure_design_preview(self, run: Mapping[str, Any]) -> dict[str, Any]:
        """Build once in the existing source-preview lane before browser gates."""
        job = self.start({"design_run_id": run["run_id"], "commit": run["candidate_sha"],
                          "branch": self.site.get("preview_branch") or "preview", "mode": _COMPILED_PREVIEW})
        future = self._futures.get(str(job["id"]))
        if future is not None:
            future.result(timeout=int(self.settings.get("build_timeout_seconds") or 1800) + 300)
        result = self.status(str(job["id"]))
        if result.get("status") != "ready" or result.get("commit") != run["candidate_sha"]:
            raise SourceDeploymentError(str(result.get("error") or "exact candidate preview did not become ready"))
        return result

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if job is None:
                raise SourceDeploymentError("source deployment job not found")
            if job.get("mode") == _PRODUCTION:
                self._refresh_release_job(job)
            return self._with_preview_url(job)

    def _with_preview_url(self, job: Mapping[str, Any]) -> dict[str, Any]:
        """Attach the address the workspace frames for this exact build.

        The path is signed when the job is created, so every reader — status,
        latest, the build result — hands out the same URL and no caller has to
        compose one from parts.
        """
        result = dict(job)
        base = str(result.get("runtime_base_path") or "")
        if not base:
            return result
        try:
            result["preview_url"] = preview_host.origin(self.env) + base
        except preview_host.PreviewHostError:
            # Configuration is checked when a preview starts. An old job without
            # an address must not take the whole status response down.
            result.pop("preview_url", None)
        return result

    def latest_preview(self, branch: str | None = None) -> dict[str, Any]:
        return self.latest(branch, mode=_COMPILED_PREVIEW)

    def preview_for_candidate(self, design_run_id: str, candidate_sha: str) -> dict[str, Any]:
        """Return an existing compiled-preview job for one exact candidate.

        Read-only: it never starts a build and never accepts a different commit.
        A retained candidate is viewable while its own validation is still
        running, so the owner is not asked to wait for a finished review before
        seeing what Ada produced.
        Prefer an available preview over a later unsuccessful compile of the
        same identity; otherwise report the latest compile's progress/failure.
        """
        run_id = str(design_run_id or "").strip()
        commit = str(candidate_sha or "").strip().lower()
        if not run_id or not re.fullmatch(r"[0-9a-f]{40}", commit):
            return {}
        with self._lock:
            matches = [
                dict(job) for job in self._jobs.values()
                if isinstance(job, Mapping)
                and job.get("mode") == _COMPILED_PREVIEW
                and str(job.get("design_run_id") or "") == run_id
                and str(job.get("commit") or "").lower() == commit
            ]
        if not matches:
            return {}
        return max(matches, key=lambda job: (job.get("status") == "ready", str(job.get("created_at") or "")))

    def for_draft(self, draft_id: int) -> dict[str, Any]:
        """The latest production receipt, independently of the review preview.

        This is the projection the workspace reads, so it must reflect the
        central VPS receipt: otherwise a successfully deployed approval keeps
        looking queued to the owner.
        """
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.get("mode") == _PRODUCTION and j.get("draft_id") == draft_id]
            if not jobs:
                return {}
            job = max(jobs, key=lambda j: str(j.get("created_at") or ""))
            self._refresh_release_job(job)
            return dict(job)

    def reconcile_growth_delivery(self) -> list[dict[str, Any]]:
        """Explicit durable Growth-job hook; resume journal, never a release.

        Status/GET/receipt refresh do not call this method. A successful release
        remains deployed if journal recording fails, with a separate diagnostic.
        """
        if self.memory is None:
            raise SourceDeploymentError("Growth journal reconciliation requires tenant memory")
        from .growth_delivery import release_checkpoint

        context = {"memory": self.memory, "config": self.config, "env": self.env,
            "tenant_id": str(self.config.get("instance_name") or "")}
        drafts = {int(row["id"]): row for row in self.memory.list_drafts(limit=500)}
        with self._lock:
            jobs = [dict(row) for row in self._jobs.values() if row.get("mode") == _PRODUCTION]
        results = []
        for saved_job in jobs:
            draft = drafts.get(int(saved_job.get("draft_id") or 0))
            meta = (draft or {}).get("meta") or {}
            package = meta.get("growth_package") or {}
            if package.get("candidateType") != "source_code":
                continue
            initiative = next((row for row in self.memory.list_strategy_initiatives(limit=None)
                if int(row.get("draft_id") or 0) == int(draft["id"])), None)
            try:
                if initiative is None:
                    raise SourceDeploymentError("The released Growth initiative is missing")
                if package.get("tenant") != context["tenant_id"] or int(package.get("initiativeId") or 0) != int(initiative["id"]):
                    raise SourceDeploymentError("The released Growth scope does not match this tenant/work")
                receipt = self.status(str(saved_job["id"]))
                release_checkpoint(context, initiative, str(meta.get("review_package_hash") or ""), receipt)
                checkpoint = {"status": "recorded", "releaseId": receipt.get("release_id"),
                    "sourceSha": receipt.get("commit"), "executionStatus": receipt.get("status")}
                if receipt.get("status") == "deployed":
                    proof_path = release_root(self.config) / "runs" / context["tenant_id"] / str(receipt["release_id"]) / "browser-verification.json"
                    try:
                        proof = json.loads(proof_path.read_text(encoding="utf-8"))
                    except FileNotFoundError:
                        proof = None
                    if proof is None:
                        checkpoint["status"] = "acceptance_pending"
                    else:
                        checks = proof.get("technicalChecks") or []
                        if (proof.get("tenant") != context["tenant_id"] or proof.get("releaseId") != receipt["release_id"]
                            or proof.get("sourceSha") != receipt["commit"] or proof.get("packageHash") != meta.get("review_package_hash")
                            or proof.get("status") != "passed" or not proof.get("verifiedAt") or not checks
                            or any(not isinstance(check, Mapping) or check.get("status") != "passed" or not check.get("criterion") or not check.get("evidence") for check in checks)):
                            raise SourceDeploymentError("Source technical browser acceptance does not match the exact approved release")
                        self.memory.update_strategy_initiative(int(initiative["id"]), validation={
                            **(initiative.get("validation") or {}), "sourceTechnicalAcceptance": proof,
                        })
            except Exception as exc:
                checkpoint = {"status": "recording_pending", "error": type(exc).__name__,
                    "releaseId": saved_job.get("release_id"), "sourceSha": saved_job.get("commit")}
            with self._lock:
                self._jobs[str(saved_job["id"])]["growth_journal"] = checkpoint
                self._persist()
            results.append({"draftId": int(draft["id"]), **checkpoint})
        return results

    def latest_release(self) -> dict[str, Any]:
        """The most recently queued production release, by creation time.

        ``latest`` orders by last update, which can surface an older terminal
        release that happened to be refreshed later. The owner is asking about
        the newest release they approved, so order by when it was queued.
        """
        with self._lock:
            jobs = [dict(value) for value in self._jobs.values() if isinstance(value, Mapping) and value.get("mode") == _PRODUCTION]
            if not jobs:
                return {}
            job = max(jobs, key=lambda item: (str(item.get("created_at") or ""), str(item.get("id") or "")))
        self._refresh_release_job(job)
        return dict(job)

    def latest(self, branch: str | None = None, *, mode: str | None = None) -> dict[str, Any]:
        with self._lock:
            candidates = [
                value for value in self._jobs.values()
                if isinstance(value, Mapping) and (not branch or str(value.get("branch") or "") == branch)
                and (mode is None or value.get("mode") == mode)
            ]
            if not candidates:
                return {}
            return self._with_preview_url(max(candidates, key=lambda item: str(item.get("updated_at") or item.get("created_at") or "")))

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
        target = f"http://127.0.0.1:{port}{job.get('runtime_base_path') or ''}/{clean_path}"
        if query:
            target = f"{target}?{query}"
        allowed = {"accept", "cookie", "user-agent", *_PREVIEW_FLIGHT_REQUEST_HEADERS}
        request_headers = {
            key: value
            for key, value in (headers or {}).items()
            if key.lower() in allowed and value
        }
        request = urllib.request.Request(target, headers=request_headers, method="GET")
        try:
            response = urllib.request.urlopen(request, timeout=60)
            with response:
                return {
                    "status": int(response.status),
                    "body": self._rewrite_runtime_assets(response.read(), response.headers.get("Content-Type", ""), job),
                    "content_type": response.headers.get("Content-Type", "application/octet-stream"),
                    "location": self._rewrite_runtime_location(response.headers.get("Location", ""), job),
                    "commit": str(job.get("commit") or ""),
                }
        except urllib.error.HTTPError as exc:
            return {
                "status": int(exc.code),
                "body": exc.read(),
                "content_type": exc.headers.get("Content-Type", "text/plain; charset=utf-8"),
                "location": self._rewrite_runtime_location(exc.headers.get("Location", ""), job) if exc.headers else "",
                "commit": str(job.get("commit") or ""),
            }
        except (OSError, urllib.error.URLError) as exc:
            raise SourceDeploymentError(f"compiled preview request failed: {str(exc)[:300]}") from exc

    @staticmethod
    def _rewrite_runtime_location(location: str, job: Mapping[str, Any]) -> str:
        """Keep a candidate redirect inside the mount that rendered it.

        `/courses/training` permanently redirects to `/depth`. The browser must
        follow that on the owner surface, not on the preview host or the live
        site, so a root-relative destination takes the build's exact basePath.
        """
        raw = str(location or "").strip()
        base = str(job.get("runtime_base_path") or "")
        if not raw or not base:
            return ""
        parts = urllib.parse.urlsplit(raw)
        if parts.scheme or parts.netloc or not parts.path.startswith("/"):
            return raw
        if parts.path == base or parts.path.startswith(base + "/"):
            return raw
        return base + parts.path + (f"?{parts.query}" if parts.query else "")

    def close(self) -> None:
        """Stop queued preview work during tenant shutdown."""
        for job_id in list(self._runtimes):
            self._stop_runtime(job_id)
        self._executor.shutdown(wait=False, cancel_futures=True)
        shutil.rmtree(self._preview_home, ignore_errors=True)


__all__ = ["SourceDeploymentError", "SourceDeploymentService"]
