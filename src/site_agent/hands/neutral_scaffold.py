"""Local Git adapter for provisioned, remote-free customer sites.

Provisioning hands the customer runtime an exact accepted commit and removes
its remote. This adapter keeps ordinary owner-approved edits and immutable
design merges on that local repository without inventing a network publisher.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .base import AdapterError, SiteAdapter, register


_SHA = re.compile(r"^[0-9a-f]{40}$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


@register
class NeutralScaffold(SiteAdapter):
    """Serve and mutate the local customer clone only after owner approval."""

    name = "neutral_scaffold"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.clone_path = str(self.site.get("clone_path") or "").strip()
        self.branch = str(self.site.get("branch") or "main").strip()
        self.content_path = str(self.site.get("content_path") or "content.json").strip()

    def _root(self) -> Path:
        if not self.clone_path:
            raise AdapterError(f"{self.name}: site.clone_path is not configured")
        root = Path(self.clone_path).expanduser().resolve()
        if not root.is_dir() or not (root / ".git").exists():
            raise AdapterError(f"{self.name}: local Git clone is missing at {root}")
        return root

    @staticmethod
    def _branch_name(value: str) -> str:
        branch = str(value or "").strip()
        if (
            not branch
            or not _BRANCH.fullmatch(branch)
            or branch.startswith("/")
            or branch.endswith("/")
            or ".." in branch
            or "//" in branch
            or "@{" in branch
        ):
            raise AdapterError("local Git branch is invalid")
        return branch

    def _ref(self, branch: str | None = None) -> str:
        return self._branch_name(branch or self.branch)

    def _path(self, value: str) -> tuple[Path, str]:
        relative = str(value or "").strip().replace("\\", "/").lstrip("/")
        path = Path(relative)
        if not relative or path.is_absolute() or ".." in path.parts:
            raise AdapterError(f"{self.name}: unsafe site path")
        root = self._root()
        target = (root / path).resolve(strict=False)
        if target != root and root not in target.parents:
            raise AdapterError(f"{self.name}: site path escapes the clone")
        return target, relative

    def _run(self, *args: str, timeout: int = 120, check: bool = True) -> str:
        root = self._root()
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AdapterError(f"{self.name}: git command failed: {str(exc)[:300]}") from exc
        if check and result.returncode:
            detail = (result.stderr or result.stdout or "git command failed").strip()
            raise AdapterError(f"{self.name}: git {' '.join(args[:2])} failed: {detail[:500]}")
        return result.stdout

    def _succeeds(self, *args: str, timeout: int = 30) -> bool:
        root = self._root()
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AdapterError(f"{self.name}: git command failed: {str(exc)[:300]}") from exc
        return result.returncode == 0

    def _raw(self, *args: str, timeout: int = 30) -> bytes:
        root = self._root()
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                check=False,
                capture_output=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AdapterError(f"{self.name}: git command failed: {str(exc)[:300]}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or b"git command failed").decode(errors="replace").strip()
            raise AdapterError(f"{self.name}: git {' '.join(args[:2])} failed: {detail[:500]}")
        return bytes(result.stdout)

    def _clean(self) -> None:
        if self._run("status", "--porcelain", "--untracked-files=all").strip():
            raise AdapterError(f"{self.name}: local clone has uncommitted changes")

    def _checkout(self, branch: str) -> None:
        branch = self._branch_name(branch)
        self._clean()
        current = self._run("branch", "--show-current").strip()
        if current != branch:
            self._run("checkout", "--quiet", branch)

    def _commit(self, message: str) -> tuple[str, str]:
        self._run(
            "-c", "user.name=Ada (site-agent)",
            "-c", "user.email=ada@site-agent.local",
            "commit", "--no-gpg-sign", "-m", str(message or "site-agent change")[:200],
        )
        commit_sha = self._run("rev-parse", "HEAD").strip().lower()
        parents = self._run("rev-list", "--parents", "-n", "1", "HEAD").strip().split()
        return commit_sha, parents[1] if len(parents) > 1 else ""

    def validate(self) -> None:
        self._root()
        self._run("rev-parse", "--verify", f"{self._ref()}^{{commit}}")

    def status(self) -> dict[str, Any]:
        try:
            root = self._root()
            current = self._run("branch", "--show-current").strip()
            head = self._run("rev-parse", "--short", "HEAD").strip()
            dirty = bool(self._run("status", "--porcelain", "--untracked-files=all").strip())
            return {
                "adapter": self.name,
                "path": str(root),
                "branch": current or "(detached)",
                "head": head,
                "dirty": dirty,
                "remote": bool(self._run("remote").strip()),
            }
        except AdapterError as exc:
            return {"adapter": self.name, "available": False, "error": str(exc)}

    def get_file(self, path: str, branch: str | None = None) -> tuple[str | None, bytes | None]:
        _, relative = self._path(path)
        ref = self._ref(branch)
        self._run("rev-parse", "--verify", f"{ref}^{{commit}}")
        if not self._succeeds("cat-file", "-e", f"{ref}:{relative}"):
            return None, None
        raw = self._raw("show", f"{ref}:{relative}", timeout=30)
        blob_sha = self._run("rev-parse", f"{ref}:{relative}", timeout=30).strip()
        return blob_sha, raw

    def get_content(self, branch: str | None = None) -> dict[str, Any]:
        _, raw = self.get_file(self.content_path, branch=branch)
        if raw is None:
            raise AdapterError(f"{self.name}: {self.content_path} not found")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdapterError(f"{self.name}: {self.content_path} is not valid JSON") from exc
        if not isinstance(value, dict):
            raise AdapterError(f"{self.name}: {self.content_path} must contain an object")
        return value

    def ensure_branch(self, name: str) -> dict[str, Any]:
        branch = self._branch_name(name)
        if self._succeeds("show-ref", "--verify", f"refs/heads/{branch}"):
            return {"created": False, "branch": branch}
        self._run("branch", branch, self._ref())
        return {"created": True, "branch": branch, "sha": self._run("rev-parse", branch).strip()}

    def commit_file(
        self,
        path: str,
        data: bytes,
        message: str,
        branch: str | None = None,
    ) -> dict[str, Any]:
        target, relative = self._path(path)
        target_branch = self._ref(branch)
        self._checkout(target_branch)
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise AdapterError(f"{self.name}: target is not a regular file: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes(data))
        self._run("add", "--", relative)
        if not self._run("diff", "--cached", "--name-only", "--", relative).strip():
            return {"adapter": self.name, "committed": False, "path": relative, "branch": target_branch}
        commit_sha, parent_sha = self._commit(message)
        return {
            "adapter": self.name,
            "committed": True,
            "path": relative,
            "branch": target_branch,
            "commit_sha": commit_sha,
            "parent_sha": parent_sha,
        }

    def delete_file(self, path: str, message: str, branch: str | None = None) -> dict[str, Any]:
        target, relative = self._path(path)
        target_branch = self._ref(branch)
        self._checkout(target_branch)
        if not target.exists():
            return {"adapter": self.name, "deleted": False, "path": relative, "branch": target_branch, "reason": "not found"}
        if target.is_symlink() or not target.is_file():
            raise AdapterError(f"{self.name}: target is not a regular file: {relative}")
        target.unlink()
        self._run("add", "-u", "--", relative)
        commit_sha, parent_sha = self._commit(message)
        return {
            "adapter": self.name,
            "deleted": True,
            "path": relative,
            "branch": target_branch,
            "commit_sha": commit_sha,
            "parent_sha": parent_sha,
        }

    def list_files(self, branch: str | None = None) -> list[str]:
        ref = self._ref(branch)
        self._run("rev-parse", "--verify", f"{ref}^{{commit}}")
        return [item for item in self._run("ls-tree", "-r", "--name-only", ref).splitlines() if item]

    def merge_design_candidate(
        self,
        config: dict[str, Any],
        candidate_sha: str,
        base_sha: str,
        message: str,
    ) -> dict[str, Any]:
        del config
        candidate_sha = str(candidate_sha or "").strip().lower()
        base_sha = str(base_sha or "").strip().lower()
        if not _SHA.fullmatch(candidate_sha) or not _SHA.fullmatch(base_sha):
            raise AdapterError("design candidate and base must be full commit SHAs")
        branch = self._ref()
        current_sha = self._run("rev-parse", f"{branch}^{{commit}}").strip().lower()
        if current_sha != base_sha:
            return {
                "merged": False,
                "status": 409,
                "reason": "production branch advanced since this candidate was built",
                "candidate_sha": candidate_sha,
                "current_sha": current_sha,
            }
        self._run("rev-parse", "--verify", f"{candidate_sha}^{{commit}}")
        if not self._succeeds("merge-base", "--is-ancestor", base_sha, candidate_sha):
            raise AdapterError("design candidate is not based on the current production commit")
        self._checkout(branch)
        try:
            self._run(
                "-c", "user.name=Ada (site-agent)",
                "-c", "user.email=ada@site-agent.local",
                "merge", "--no-ff", "--no-edit", "-m", str(message or "Approve design candidate")[:200], candidate_sha,
                timeout=180,
            )
        except AdapterError:
            self._run("merge", "--abort", check=False)
            raise
        commit_sha, parent_sha = self._commit_identity()
        return {
            "merged": True,
            "path": f"{candidate_sha}->{branch}",
            "candidate_sha": candidate_sha,
            "commit_sha": commit_sha,
            "parent_sha": parent_sha,
        }

    def _commit_identity(self) -> tuple[str, str]:
        commit_sha = self._run("rev-parse", "HEAD").strip().lower()
        parents = self._run("rev-list", "--parents", "-n", "1", "HEAD").strip().split()
        return commit_sha, parents[1] if len(parents) > 1 else ""

    def merge_preview(self, config: dict[str, Any], message: str) -> dict[str, Any]:
        del config
        preview = str(self.site.get("preview_branch") or "preview").strip()
        preview = self._branch_name(preview)
        preview_sha = self._run("rev-parse", f"{preview}^{{commit}}").strip().lower()
        base_sha = self._run("rev-parse", f"{self._ref()}^{{commit}}").strip().lower()
        return self.merge_design_candidate({}, preview_sha, base_sha, message)


__all__ = ["NeutralScaffold"]
