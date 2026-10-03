"""github_static — static site served from a GitHub repo branch.

Publishing = committing files through the GitHub Contents API. Modeled on the
OceanicVibes admin server approach: token held server-side, every change is a
reviewable commit.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..config import resolve_secret
from ..credentials import credential_environment, github_api_token, github_remote, github_ssh_command
from ..frontend_ownership import is_frontend_owned_path
from .base import AdapterError, SiteAdapter, register

API = "https://api.github.com"


def _request(method: str, url: str, token: str | None = None, payload: Any = None, timeout: int = 30) -> tuple[int, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "site-agent",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise AdapterError(f"github {method} {url} -> {exc.code}: {detail}") from exc


def secret(config: dict[str, Any], name: str, env: dict[str, str] | None = None) -> str:
    """Compatibility wrapper; new code should import config.resolve_secret."""
    return resolve_secret(config, name, env)


@register
class GithubStatic(SiteAdapter):
    name = "github_static"

    def __init__(self, config: dict[str, Any], env: dict[str, str] | None = None):
        super().__init__(config)
        self.env = credential_environment(config, env)
        self.token = github_api_token(config, self.env) or secret(config, "github_token", self.env)
        self.repo = str(self.site.get("repository", "")).strip().strip("/")
        self.branch = str(self.site.get("branch", "main"))
        self.content_path = str(self.site.get("content_path", "content.json"))
        self._api_unavailable = False

    def _local_checkout(self) -> Path | None:
        raw = str(self.site.get("clone_path") or "").strip()
        if not raw:
            return None
        path = Path(raw).expanduser().resolve()
        return path if (path / ".git").exists() else None

    def _git_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self.env)
        command = str(self.site.get("git_ssh_command") or "").strip()
        if not command:
            command = github_ssh_command(self.root, self.env)
        if command:
            env["GIT_SSH_COMMAND"] = command
        return env

    @staticmethod
    def _branch_ref(branch: str) -> str:
        value = str(branch or "").strip()
        if not value or not re.fullmatch(r"[A-Za-z0-9._/-]+", value) or value.startswith("/") or value.endswith("/") or ".." in Path(value).parts:
            raise AdapterError("github: invalid branch")
        return f"refs/remotes/origin/{value}"

    @staticmethod
    def _source_path(path: str) -> str:
        value = str(path or "").replace("\\", "/").strip("/")
        if not value or value == ".git" or value.startswith(".git/") or ".." in Path(value).parts:
            raise AdapterError("github: invalid source path")
        return value

    def _git(self, args: list[str], cwd: Path, *, timeout: int = 120) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                env=self._git_env(),
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdapterError(f"github git transport failed: {str(exc)[:300]}") from exc
        if result.returncode:
            output = (result.stderr or result.stdout or b"git command failed").decode(errors="replace").strip()
            raise AdapterError(f"github git transport: {output[-500:]}")
        return result

    def _local_remote_ref(self, branch: str) -> str:
        checkout = self._local_checkout()
        if checkout is None:
            raise AdapterError("github: local source checkout is not configured")
        current = self._git(["remote", "get-url", "origin"], checkout).stdout.decode().strip()
        transport = github_remote(current, self.root, self.env)
        if transport and transport != current:
            self._git(["remote", "set-url", "origin", transport], checkout)
        ref = self._branch_ref(branch)
        self._git(["fetch", "--no-tags", "origin", f"+{branch}:{ref}"], checkout)
        return ref

    def _local_branch_head(self, branch: str) -> str | None:
        checkout = self._local_checkout()
        if checkout is None:
            return None
        try:
            ref = self._local_remote_ref(branch)
            return self._git(["rev-parse", ref], checkout).stdout.decode().strip() or None
        except AdapterError:
            try:
                return self._git(["rev-parse", f"refs/heads/{branch}"], checkout).stdout.decode().strip() or None
            except AdapterError:
                return None

    def _local_get_file(self, path: str, branch: str) -> tuple[str | None, bytes | None]:
        checkout = self._local_checkout()
        if checkout is None:
            raise AdapterError("github: local source checkout is not configured")
        source_path = self._source_path(path)
        ref = self._local_remote_ref(branch)
        spec = f"{ref}:{source_path}"
        try:
            sha = self._git(["rev-parse", spec], checkout).stdout.decode().strip() or None
            data = self._git(["show", spec], checkout).stdout
            return sha, data
        except AdapterError as exc:
            # A Payload-backed site legitimately has no content.json in the
            # source repository; content is served by the gateway instead.
            # Missing source paths must therefore behave like the API's 404
            # result rather than aborting the entire owner-chat job.
            detail = str(exc).lower()
            if (
                "needed a single revision" in detail
                or "exists on disk" in detail
                or "does not exist in" in detail
            ):
                return None, None
            raise

    def _local_list_files(self, branch: str) -> list[str]:
        checkout = self._local_checkout()
        if checkout is None:
            raise AdapterError("github: local source checkout is not configured")
        ref = self._local_remote_ref(branch)
        output = self._git(["ls-tree", "-r", "--name-only", ref], checkout).stdout.decode()
        return [line.strip() for line in output.splitlines() if line.strip()]

    def _local_ensure_branch(self, name: str) -> dict[str, Any]:
        checkout = self._local_checkout()
        if checkout is None:
            raise AdapterError("github: local source checkout is not configured")
        target = str(name or "").strip()
        try:
            result = self._git(["ls-remote", "--exit-code", "--heads", "origin", f"refs/heads/{target}"], checkout)
            sha = result.stdout.decode().split()[0] if result.stdout.decode().split() else ""
            return {"created": False, "branch": target, "sha": sha}
        except AdapterError:
            base_sha = self._local_branch_head(self.branch)
            if not base_sha:
                raise AdapterError("github: production branch has no head")
            self._git(["push", "origin", f"{base_sha}:refs/heads/{target}"], checkout)
            return {"created": True, "branch": target, "sha": base_sha}

    def _local_commit_file(
        self,
        path: str,
        data: bytes,
        message: str,
        branch: str,
        expected_sha: str | None = None,
    ) -> dict[str, Any]:
        checkout = self._local_checkout()
        if checkout is None:
            raise AdapterError("github: local source checkout is not configured")
        current_sha, _current_data = self._local_get_file(path, branch)
        if expected_sha is not None and current_sha != expected_sha:
            return {
                "adapter": self.name,
                "committed": False,
                "status": 409,
                "path": path,
                "branch": branch,
                "reason": "file changed since the source edit was read",
            }

        worktree_root = Path(tempfile.mkdtemp(prefix="site-agent-github-edit-"))
        worktree = worktree_root / "repo"
        try:
            ref = self._branch_ref(branch)
            self._git(["worktree", "add", "--detach", str(worktree), ref], checkout)
            target = worktree / self._source_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            self._git(["add", "--", self._source_path(path)], worktree)
            self._git(
                [
                    "-c", "user.name=site-agent source editor",
                    "-c", "user.email=site-agent-source@localhost",
                    "commit", "-m", message[:200],
                ],
                worktree,
            )
            commit_sha = self._git(["rev-parse", "HEAD"], worktree).stdout.decode().strip()
            try:
                self._git(["push", "origin", f"HEAD:refs/heads/{branch}"], worktree)
            except AdapterError as exc:
                if "non-fast-forward" in str(exc) or "fetch first" in str(exc):
                    return {
                        "adapter": self.name,
                        "committed": False,
                        "status": 409,
                        "path": path,
                        "branch": branch,
                        "reason": "preview branch changed during the source commit",
                    }
                raise
            return {
                "adapter": self.name,
                "committed": True,
                "branch": branch,
                "path": path,
                "commit_sha": commit_sha,
            }
        finally:
            if worktree.exists():
                try:
                    self._git(["worktree", "remove", "--force", str(worktree)], checkout)
                except AdapterError:
                    pass
            shutil.rmtree(worktree_root, ignore_errors=True)

    def _url(self, path: str) -> str:
        encoded = "/".join(part for part in path.split("/") if part)
        return f"{API}/repos/{self.repo}/contents/{encoded}"

    def validate(self) -> None:
        if not self.repo or "/" not in self.repo:
            raise AdapterError(f"{self.name}: site.repository must be 'owner/repo'")
        if not self.token and self._local_checkout() is None:
            raise AdapterError(f"{self.name}: github_token not configured")

    def get_file(self, path: str, branch: str | None = None) -> tuple[str | None, bytes | None]:
        target_branch = branch or self.branch
        if self._local_checkout() is not None:
            return self._local_get_file(path, target_branch)
        if self._api_unavailable:
            return self._local_get_file(path, target_branch)
        ref = urllib.parse.quote(target_branch)
        try:
            status, body = _request("GET", f"{self._url(path)}?ref={ref}", token=self.token)
        except AdapterError as exc:
            if " 404" in str(exc):
                self._api_unavailable = True
                return self._local_get_file(path, target_branch)
            raise
        if status != 200:
            return None, None
        self._api_unavailable = False
        content = base64.b64decode(body.get("content") or "")
        return body.get("sha"), content

    def ensure_branch(self, name: str) -> dict[str, Any]:
        """Create a branch pointing at the current head of the working branch."""
        if self._local_checkout() is not None:
            return self._local_ensure_branch(name)
        if self._api_unavailable:
            return self._local_ensure_branch(name)
        try:
            _, head = _request(
                "GET",
                f"{API}/repos/{self.repo}/git/ref/heads/{urllib.parse.quote(self.branch)}",
                token=self.token,
            )
        except AdapterError as exc:
            if " 404" in str(exc):
                self._api_unavailable = True
                return self._local_ensure_branch(name)
            raise
        head_sha = head["object"]["sha"]
        try:
            _, created = _request(
                "POST",
                f"{API}/repos/{self.repo}/git/refs",
                token=self.token,
                payload={"ref": f"refs/heads/{name}", "sha": head_sha},
            )
            return {"created": True, "branch": name, "sha": created.get("object", {}).get("sha")}
        except AdapterError as exc:
            if " 404" in str(exc):
                self._api_unavailable = True
                return self._local_ensure_branch(name)
            if "422" in str(exc):  # already exists — fine for a preview branch
                return {"created": False, "branch": name}
            raise

    def get_branch_head(self, name: str | None = None) -> str | None:
        """Return the immutable commit currently pointed at by a branch."""
        branch = name or self.branch
        # A configured checkout is the connected GitHub source of truth for
        # the deployment path. Prefer its SSH-backed remote over the Contents
        # API so a PAT is not required merely to read a branch head.
        if self._local_checkout() is not None:
            return self._local_branch_head(branch)
        if self._api_unavailable:
            return self._local_branch_head(branch)
        try:
            status, body = _request(
                "GET",
                f"{API}/repos/{self.repo}/git/ref/heads/{urllib.parse.quote(branch)}",
                token=self.token,
            )
        except AdapterError as exc:
            if " 404" in str(exc):
                self._api_unavailable = True
                return self._local_branch_head(branch)
            raise
        if status != 200:
            return None
        self._api_unavailable = False
        value = body.get("object", {}).get("sha") if isinstance(body, dict) else None
        return str(value or "").strip() or None

    def get_content(self, branch: str | None = None) -> dict[str, Any]:
        _, data = self.get_file(self.content_path, branch=branch)
        if data is None:
            raise AdapterError(f"{self.name}: {self.content_path} not found on branch '{branch or self.branch}'")
        return json.loads(data)

    def commit_file(
        self,
        path: str,
        data: bytes,
        message: str,
        branch: str | None = None,
        expected_sha: str | None = None,
    ) -> dict[str, Any]:
        target_branch = branch or self.branch
        if self._local_checkout() is not None:
            return self._local_commit_file(path, data, message, target_branch, expected_sha)
        if self._api_unavailable:
            return self._local_commit_file(path, data, message, target_branch, expected_sha)
        payload: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(data).decode(),
            "branch": target_branch,
        }
        # GitHub's contents API rejects a PUT whose `sha` went stale between the
        # GET and the PUT (common when one draft writes the same file twice, or
        # when a second approve lands mid-flight). Refetch and retry a few times.
        last_status = 0
        body: Any = {}
        for _ in range(3):
            sha, _ = self.get_file(path, branch=target_branch)
            if self._api_unavailable:
                return self._local_commit_file(path, data, message, target_branch, expected_sha)
            if expected_sha is not None and sha != expected_sha:
                return {
                    "adapter": self.name,
                    "committed": False,
                    "status": 409,
                    "path": path,
                    "branch": target_branch,
                    "reason": "file changed since the source edit was read",
                }
            payload["sha"] = sha
            try:
                last_status, body = _request("PUT", self._url(path), token=self.token, payload=payload)
            except AdapterError as exc:
                if " 404" in str(exc):
                    self._api_unavailable = True
                    return self._local_commit_file(path, data, message, target_branch, expected_sha)
                if " 409" not in str(exc):
                    raise
                # The contents API does not return a status tuple for HTTP
                # errors. Re-read before retrying so a concurrent edit cannot
                # be silently overwritten by the retry.
                if expected_sha is not None:
                    current_sha, _ = self.get_file(path, branch=target_branch)
                    if current_sha != expected_sha:
                        return {
                            "adapter": self.name,
                            "committed": False,
                            "status": 409,
                            "path": path,
                            "branch": target_branch,
                            "reason": "file changed during the source commit",
                        }
                last_status = 409
                body = {}
            if last_status in (200, 201):
                break
            if last_status != 409:
                break
        result = {"adapter": self.name, "committed": last_status in (200, 201), "path": path, "branch": target_branch}
        if isinstance(body, dict) and body.get("commit"):
            result["commit_sha"] = body["commit"].get("sha")
            result["html_url"] = body.get("content", {}).get("html_url")
        return result

    def delete_file(self, path: str, message: str, branch: str | None = None) -> dict[str, Any]:
        target_branch = branch or self.branch
        file_sha, _ = self.get_file(path, branch=target_branch)
        if not file_sha:
            return {"adapter": self.name, "deleted": False, "path": path,
                    "branch": target_branch, "reason": "not found"}
        status, _ = _request(
            "DELETE",
            f"{self._url(path)}?ref={urllib.parse.quote(target_branch)}",
            token=self.token,
            payload={"message": message, "sha": file_sha, "branch": target_branch},
        )
        return {"adapter": self.name, "deleted": status in (200, 204),
                "path": path, "branch": target_branch}

    def get_commit(self, sha: str) -> dict[str, Any]:
        _, body = _request("GET", f"{API}/repos/{self.repo}/commits/{sha}", token=self.token)
        return body

    def reset_preview_branch(self, name: str | None = None) -> dict[str, Any]:
        """Force the preview branch back to the production branch head, discarding
        any rejected/stale staged work so the next build starts from main again."""
        target = name or "preview"
        _, head = _request(
            "GET",
            f"{API}/repos/{self.repo}/git/ref/heads/{urllib.parse.quote(self.branch)}",
            token=self.token,
        )
        head_sha = head["object"]["sha"]
        try:
            status, body = _request(
                "PATCH",
                f"{API}/repos/{self.repo}/git/refs/heads/{urllib.parse.quote(target)}",
                token=self.token,
                payload={"sha": head_sha, "force": True},
            )
            return {"reset": True, "branch": target, "sha": body.get("object", {}).get("sha")}
        except AdapterError as exc:
            if " 404" in str(exc):  # preview branch doesn't exist yet — nothing to reset
                return {"reset": False, "branch": target, "reason": "missing"}
            raise

    def _merge_preview_via_git(self, message: str) -> dict[str, Any]:
        """Merge and push through the configured SSH transport when the API token
        cannot access the private repository.

        The host already has an owner-scoped deploy key for GitHub. Keeping this
        fallback here preserves the explicit approval boundary without requiring
        a second credential or silently mutating the checked-out worktree.
        """
        checkout = self._local_checkout()
        if checkout is None:
            raise AdapterError("github: local source checkout is not configured")

        worktree = Path(tempfile.mkdtemp(prefix="site-agent-merge-"))
        added = False
        try:
            self._git(
                [
                    "fetch",
                    "--no-tags",
                    "origin",
                    f"+{self.branch}:refs/remotes/origin/{self.branch}",
                    "+preview:refs/remotes/origin/preview",
                ],
                checkout,
            )
            base_ref = self._branch_ref(self.branch)
            preview_ref = self._branch_ref("preview")
            base_sha = self._git(["rev-parse", base_ref], checkout).stdout.decode().strip()
            preview_sha = self._git(["rev-parse", preview_ref], checkout).stdout.decode().strip()
            self._git(["worktree", "add", "--detach", str(worktree), base_sha], checkout)
            added = True
            self._git(["config", "user.name", "site-agent"], worktree)
            self._git(["config", "user.email", "site-agent@local"], worktree)
            self._git(["merge", "--no-ff", "--no-edit", preview_sha, "-m", message[:200]], worktree)
            commit_sha = self._git(["rev-parse", "HEAD"], worktree).stdout.decode().strip()
            parents = self._git(["show", "-s", "--format=%P", "HEAD"], worktree).stdout.decode().split()
            self._git(["push", "origin", f"{commit_sha}:refs/heads/{self.branch}"], worktree)
            return {
                "merged": True,
                "path": "preview->" + self.branch,
                "commit_sha": commit_sha,
                "parent_sha": parents[0] if parents else base_sha,
                "candidate_sha": preview_sha,
                "transport": "ssh_git",
            }
        except AdapterError:
            if added:
                try:
                    self._git(["merge", "--abort"], worktree)
                except AdapterError:
                    pass
            raise
        finally:
            if added:
                try:
                    self._git(["worktree", "remove", "--force", str(worktree)], checkout)
                except AdapterError:
                    shutil.rmtree(worktree, ignore_errors=True)
            else:
                shutil.rmtree(worktree, ignore_errors=True)

    def merge_preview(self, config: dict[str, Any], message: str) -> dict[str, Any]:
        """Owner approved: merge the preview branch into the production branch."""
        try:
            status, body = _request(
                "POST",
                f"{API}/repos/{self.repo}/merges",
                token=self.token,
                payload={"base": self.branch, "head": "preview", "commit_message": message[:200]},
            )
        except AdapterError as exc:
            if " 404" not in str(exc):
                raise
            return self._merge_preview_via_git(message)
        if status not in (200, 201):
            return {"merged": False, "status": status}
        parents = body.get("parents") or []
        return {"merged": True, "path": "preview->" + self.branch,
                "commit_sha": body.get("sha"),
                "parent_sha": (parents[0] or {}).get("sha") if parents else "",
                "html_url": body.get("html_url")}

    def merge_design_candidate(
        self,
        config: dict[str, Any],
        candidate_sha: str,
        base_sha: str,
        message: str,
    ) -> dict[str, Any]:
        """Merge the exact reviewed candidate, refusing an advanced production head."""
        candidate_sha = str(candidate_sha or "").strip().lower()
        base_sha = str(base_sha or "").strip().lower()
        if len(candidate_sha) != 40 or len(base_sha) != 40:
            raise AdapterError("design candidate and base must be full commit SHAs")
        _, head = _request(
            "GET",
            f"{API}/repos/{self.repo}/git/ref/heads/{urllib.parse.quote(self.branch)}",
            token=self.token,
        )
        current_sha = str((head.get("object") or {}).get("sha") or "").lower()
        if current_sha != base_sha:
            return {
                "merged": False,
                "status": 409,
                "reason": "production branch advanced since this candidate was built",
                "candidate_sha": candidate_sha,
                "current_sha": current_sha,
            }
        status, body = _request(
            "POST",
            f"{API}/repos/{self.repo}/merges",
            token=self.token,
            payload={"base": self.branch, "head": candidate_sha, "commit_message": message[:200]},
        )
        if status not in (200, 201):
            return {"merged": False, "status": status, "candidate_sha": candidate_sha}
        parents = body.get("parents") or []
        return {
            "merged": True,
            "path": f"{candidate_sha}->{self.branch}",
            "candidate_sha": candidate_sha,
            "commit_sha": body.get("sha"),
            "parent_sha": (parents[0] or {}).get("sha") if parents else "",
            "html_url": body.get("html_url"),
        }

    def list_files(self, branch: str | None = None) -> list[str]:
        ref = branch or self.branch
        if self._local_checkout() is not None:
            return self._local_list_files(ref)
        if self._api_unavailable:
            return self._local_list_files(ref)
        try:
            _, tree = _request(
                "GET",
                f"{API}/repos/{self.repo}/git/trees/{urllib.parse.quote(ref)}?recursive=1",
                token=self.token,
            )
        except AdapterError as exc:
            if " 404" not in str(exc):
                raise
            self._api_unavailable = True
            return self._local_list_files(ref)
        return [item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"]

    def revert_commit(self, sha: str) -> dict[str, Any]:
        """Undo one commit by restoring every touched file to its parent state."""
        commit = self.get_commit(sha)
        parent = (commit.get("parents") or [{}])[0].get("sha")
        if not parent:
            raise AdapterError(f"cannot revert {sha}: no parent commit")
        results = []
        for f in commit.get("files", []):
            path = f["filename"]
            try:
                status, body = _request("GET", f"{self._url(path)}?ref={parent}", token=self.token)
            except AdapterError:
                status, body = 404, {}
            if status == 200:
                data = base64.b64decode(body.get("content") or "")
                results.append(self.commit_file(path, data, f"Revert {sha[:7]}: restore {path}"))
            else:
                results.append(self.delete_file(path, f"Revert {sha[:7]}: remove {path}"))
        return {"adapter": self.name, "reverted": sha, "files": results}

    def restore_frontend_paths(self, target_sha: str, branch: str, message: str) -> dict[str, Any]:
        """Prepare a frontend-only restoration on the preview branch.

        The commit is based on the current production head and overlays only
        tenant-owned presentation paths. Schema, admin, settings and current
        Payload data remain at the current baseline. Pre-contract commits are
        intentionally not eligible for owner rollback.
        """
        _, target = _request("GET", f"{API}/repos/{self.repo}/commits/{urllib.parse.quote(target_sha)}", token=self.token)
        target_tree = (target.get("commit") or {}).get("tree", {}).get("sha")
        if not target_tree:
            raise AdapterError(f"github: target version {target_sha[:12]} has no tree")

        _, current_ref = _request(
            "GET",
            f"{API}/repos/{self.repo}/git/ref/heads/{urllib.parse.quote(self.branch)}",
            token=self.token,
        )
        current_sha = current_ref.get("object", {}).get("sha")
        if not current_sha:
            raise AdapterError("github: production branch has no head")
        _, current = _request("GET", f"{API}/repos/{self.repo}/commits/{current_sha}", token=self.token)
        current_tree = (current.get("commit") or {}).get("tree", {}).get("sha")
        if not current_tree:
            raise AdapterError("github: production head has no tree")

        target_entries = self._tree_files(target_tree)
        current_entries = self._tree_files(current_tree)
        marker_path = "helloada-content-contract.json"
        marker = target_entries.get(marker_path)
        if not marker:
            raise AdapterError("github: this version predates the supported shared-content rollback baseline")
        _, marker_body = _request(
            "GET", f"{self._url(marker_path)}?ref={urllib.parse.quote(target_sha)}", token=self.token,
        )
        try:
            marker_data = base64.b64decode(marker_body.get("content") or "", validate=False)
            contract = json.loads(marker_data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdapterError("github: selected version has an invalid content-contract marker") from exc
        if contract.get("contract") != "helloada-content-v1":
            raise AdapterError("github: selected version does not use the supported shared-content contract")

        frontend_paths = {
            path for path in set(target_entries) | set(current_entries)
            if is_frontend_owned_path(path)
        }
        if not frontend_paths:
            raise AdapterError("github: selected version has no restorable frontend-owned files")
        changes = []
        for path in sorted(frontend_paths):
            target_entry = target_entries.get(path)
            current_entry = current_entries.get(path)
            if target_entry and current_entry and target_entry.get("sha") == current_entry.get("sha"):
                continue
            if target_entry:
                changes.append({"path": path, "mode": target_entry["mode"], "type": "blob", "sha": target_entry["sha"]})
            elif current_entry:
                changes.append({"path": path, "mode": current_entry["mode"], "type": "blob", "sha": None})
        if not changes:
            raise AdapterError("github: selected version has no frontend differences from the current website")

        _, created_tree = _request(
            "POST",
            f"{API}/repos/{self.repo}/git/trees",
            token=self.token,
            payload={"base_tree": current_tree, "tree": changes},
        )
        tree_sha = created_tree.get("sha")
        if not tree_sha:
            raise AdapterError("github: failed to create rollback tree")
        _, created_commit = _request(
            "POST",
            f"{API}/repos/{self.repo}/git/commits",
            token=self.token,
            payload={"message": message[:200], "tree": tree_sha, "parents": [current_sha]},
        )
        commit_sha = created_commit.get("sha")
        if not commit_sha:
            raise AdapterError("github: failed to create rollback commit")
        _, latest_ref = _request(
            "GET", f"{API}/repos/{self.repo}/git/ref/heads/{urllib.parse.quote(self.branch)}", token=self.token,
        )
        if (latest_ref.get("object") or {}).get("sha") != current_sha:
            raise AdapterError("github: production changed while preparing the frontend restoration; prepare it again")
        _request(
            "PATCH",
            f"{API}/repos/{self.repo}/git/refs/heads/{urllib.parse.quote(branch)}",
            token=self.token,
            payload={"sha": commit_sha, "force": True},
        )
        return {
            "adapter": self.name,
            "committed": True,
            "branch": branch,
            "commit_sha": commit_sha,
            "parent_sha": current_sha,
            "target_sha": target_sha,
            "paths": [item["path"] for item in changes],
            "scope": "frontend_only",
        }

    def restore_snapshot(self, target_sha: str, branch: str, message: str) -> dict[str, Any]:
        """Compatibility name; restoration is deliberately frontend-only."""
        return self.restore_frontend_paths(target_sha, branch, message)

    def _tree_files(self, tree_sha: str) -> dict[str, dict[str, str]]:
        _, body = _request(
            "GET",
            f"{API}/repos/{self.repo}/git/trees/{urllib.parse.quote(tree_sha)}?recursive=1",
            token=self.token,
        )
        return {
            item["path"]: item
            for item in body.get("tree", [])
            if item.get("type") == "blob" and item.get("sha")
        }
