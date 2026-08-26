"""github_static — static site served from a GitHub repo branch.

Publishing = committing files through the GitHub Contents API. Modeled on the
OceanicVibes admin server approach: token held server-side, every change is a
reviewable commit.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..config import resolve_secret
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

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.token = secret(config, "github_token")
        self.repo = str(self.site.get("repository", "")).strip().strip("/")
        self.branch = str(self.site.get("branch", "main"))
        self.content_path = str(self.site.get("content_path", "content.json"))

    def _url(self, path: str) -> str:
        encoded = "/".join(part for part in path.split("/") if part)
        return f"{API}/repos/{self.repo}/contents/{encoded}"

    def validate(self) -> None:
        if not self.repo or "/" not in self.repo:
            raise AdapterError(f"{self.name}: site.repository must be 'owner/repo'")
        if not self.token:
            raise AdapterError(f"{self.name}: github_token not configured")

    def get_file(self, path: str, branch: str | None = None) -> tuple[str | None, bytes | None]:
        ref = urllib.parse.quote(branch or self.branch)
        try:
            status, body = _request("GET", f"{self._url(path)}?ref={ref}", token=self.token)
        except AdapterError as exc:
            if " 404" in str(exc):
                return None, None
            raise
        if status != 200:
            return None, None
        content = base64.b64decode(body.get("content") or "")
        return body.get("sha"), content

    def ensure_branch(self, name: str) -> dict[str, Any]:
        """Create a branch pointing at the current head of the working branch."""
        _, head = _request(
            "GET",
            f"{API}/repos/{self.repo}/git/ref/heads/{urllib.parse.quote(self.branch)}",
            token=self.token,
        )
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
            if "422" in str(exc):  # already exists — fine for a preview branch
                return {"created": False, "branch": name}
            raise

    def get_content(self, branch: str | None = None) -> dict[str, Any]:
        _, data = self.get_file(self.content_path, branch=branch)
        if data is None:
            raise AdapterError(f"{self.name}: {self.content_path} not found on branch '{branch or self.branch}'")
        return json.loads(data)

    def commit_file(self, path: str, data: bytes, message: str, branch: str | None = None) -> dict[str, Any]:
        target_branch = branch or self.branch
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
            payload["sha"] = sha
            last_status, body = _request("PUT", self._url(path), token=self.token, payload=payload)
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

    def merge_preview(self, config: dict[str, Any], message: str) -> dict[str, Any]:
        """Owner approved: merge the preview branch into the production branch."""
        status, body = _request(
            "POST",
            f"{API}/repos/{self.repo}/merges",
            token=self.token,
            payload={"base": self.branch, "head": "preview", "commit_message": message[:200]},
        )
        if status not in (200, 201):
            return {"merged": False, "status": status}
        parents = body.get("parents") or []
        return {"merged": True, "path": "preview->" + self.branch,
                "commit_sha": body.get("sha"),
                "parent_sha": (parents[0] or {}).get("sha") if parents else "",
                "html_url": body.get("html_url")}

    def list_files(self, branch: str | None = None) -> list[str]:
        ref = branch or self.branch
        _, tree = _request(
            "GET",
            f"{API}/repos/{self.repo}/git/trees/{urllib.parse.quote(ref)}?recursive=1",
            token=self.token,
        )
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

    def restore_snapshot(self, target_sha: str, branch: str, message: str) -> dict[str, Any]:
        """Create one preview commit that restores the complete target tree.

        This never changes production. The preview branch is based on the
        current production head, then its tree is made identical to the target
        commit. A single commit keeps rollback atomic and history intact.
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
        tree = [
            {"path": path, "mode": entry["mode"], "type": entry["type"], "sha": entry["sha"]}
            for path, entry in target_entries.items()
        ]
        for path in sorted(set(current_entries) - set(target_entries)):
            tree.append({"path": path, "mode": current_entries[path]["mode"], "type": "blob", "sha": None})

        _, created_tree = _request(
            "POST",
            f"{API}/repos/{self.repo}/git/trees",
            token=self.token,
            payload={"base_tree": current_tree, "tree": tree},
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
            "path": "site",
        }

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
