"""Server-side GitHub repository creation for HelloAda bootstrap.

This is deliberately separate from :mod:`github_static`: that adapter edits an
already connected repository, while bootstrap needs an idempotent repository
creation boundary before the first customer runtime exists.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


GITHUB_API = "https://api.github.com"
_REPOSITORY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class GitHubProvisioningError(RuntimeError):
    """A repository could not be created or read safely."""


@dataclass(frozen=True)
class GitHubRepositoryReceipt:
    owner: str
    name: str
    full_name: str
    clone_url: str
    ssh_url: str
    html_url: str
    created: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "name": self.name,
            "full_name": self.full_name,
            "clone_url": self.clone_url,
            "ssh_url": self.ssh_url,
            "html_url": self.html_url,
            "created": self.created,
        }


def _repository_name(value: str) -> str:
    name = str(value or "").strip()
    if not _REPOSITORY_NAME.fullmatch(name) or name.endswith("."):
        raise GitHubProvisioningError("GitHub repository name is invalid")
    return name


class GitHubRepositoryProvisioner:
    """Minimal GitHub API client for one owner-scoped repository."""

    def __init__(self, token: str, *, timeout_seconds: float = 30.0) -> None:
        self.token = str(token or "").strip()
        if not self.token:
            raise GitHubProvisioningError("GitHub API token is missing")
        self.timeout_seconds = float(timeout_seconds)

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        data = json.dumps(dict(payload)).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{GITHUB_API}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "helloada-bootstrap",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(2 * 1024 * 1024)
                body = json.loads(raw.decode("utf-8") or "{}")
                return int(response.status), body if isinstance(body, dict) else {}
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read(32 * 1024)
                body = json.loads(raw.decode("utf-8") or "{}")
            except (OSError, UnicodeError, ValueError):
                body = {}
            return int(exc.code), body if isinstance(body, dict) else {}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GitHubProvisioningError(
                f"GitHub API request failed: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _receipt(owner: str, body: Mapping[str, Any], *, created: bool) -> GitHubRepositoryReceipt:
        full_name = str(body.get("full_name") or f"{owner}/{body.get('name') or ''}").strip()
        name = str(body.get("name") or full_name.rsplit("/", 1)[-1]).strip()
        clone_url = str(body.get("clone_url") or f"https://github.com/{full_name}.git").strip()
        ssh_url = str(body.get("ssh_url") or f"git@github.com:{full_name}.git").strip()
        html_url = str(body.get("html_url") or f"https://github.com/{full_name}").strip()
        if not full_name or "/" not in full_name or not clone_url or not ssh_url:
            raise GitHubProvisioningError("GitHub returned an incomplete repository receipt")
        return GitHubRepositoryReceipt(
            owner=owner,
            name=name,
            full_name=full_name,
            clone_url=clone_url,
            ssh_url=ssh_url,
            html_url=html_url,
            created=created,
        )

    def ensure_repository(
        self,
        owner: str,
        name: str,
        *,
        description: str = "",
        private: bool = False,
    ) -> GitHubRepositoryReceipt:
        owner = str(owner or "").strip()
        if not owner or "/" in owner or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner):
            raise GitHubProvisioningError("GitHub repository owner is invalid")
        name = _repository_name(name)
        status, existing = self._request(
            "GET",
            f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}",
        )
        if status == 200:
            return self._receipt(owner, existing, created=False)
        if status != 404:
            message = str(existing.get("message") or "repository lookup failed")[:300]
            raise GitHubProvisioningError(f"GitHub repository lookup failed: {message}")

        user_status, user = self._request("GET", "/user")
        login = str(user.get("login") or "").strip().lower() if user_status == 200 else ""
        endpoint = "/user/repos" if login == owner.lower() else f"/orgs/{urllib.parse.quote(owner)}/repos"
        status, created = self._request(
            "POST",
            endpoint,
            payload={
                "name": name,
                "description": str(description or "")[:350],
                "private": bool(private),
                "has_issues": True,
                "has_projects": False,
                "has_wiki": False,
                "auto_init": False,
            },
        )
        if status in {200, 201}:
            return self._receipt(owner, created, created=True)
        # A concurrent bootstrap may have created it between GET and POST.
        if status == 422:
            status, existing = self._request(
                "GET",
                f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}",
            )
            if status == 200:
                return self._receipt(owner, existing, created=False)
        message = str(created.get("message") or "repository creation failed")[:300]
        raise GitHubProvisioningError(f"GitHub repository creation failed: {message}")


__all__ = [
    "GitHubProvisioningError",
    "GitHubRepositoryProvisioner",
    "GitHubRepositoryReceipt",
]
