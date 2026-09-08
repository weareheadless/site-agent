"""Read-only remote setup for local design experiments.

This module only clones public source and reads remote refs. Candidate work is
handled by the typed design builder, whose local target cannot push.
"""

from __future__ import annotations

import re
import os
import subprocess
from pathlib import Path


class DesignExperimentError(RuntimeError):
    pass


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_BLOCKED_ENV = {
    "GITHUB_TOKEN", "GH_TOKEN", "GH_ENTERPRISE_TOKEN", "GITLAB_TOKEN",
    "CLOUDFLARE_API_TOKEN", "CRAWLSEO_SERVICE_TOKEN", "CICERO_API_KEY",
    "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "SITE_AGENT_ADMIN_PASSWORD",
}


def _public_git_env() -> dict[str, str]:
    allowed = {
        "PATH", "USER", "HOME", "LANG", "LC_ALL", "SHELL", "TMPDIR",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    }
    return {
        key: value for key, value in os.environ.items()
        if key in allowed
        and key not in _BLOCKED_ENV
    } | {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ASKPASS": os.devnull,
    }


def _run(root: Path, *args: str, timeout: int = 120) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_public_git_env(),
    )
    if proc.returncode:
        raise DesignExperimentError(proc.stderr.strip()[:500] or "git command failed")
    return proc.stdout


def _remote_url(repository: str) -> str:
    value = str(repository or "").strip().strip("/")
    if not _REPOSITORY.fullmatch(value):
        raise DesignExperimentError("site.repository must be an owner/repository name")
    return f"https://github.com/{value}.git"


def clone_public_repository(
    repository: str,
    root: str | Path,
    *,
    branch: str = "main",
    progress=None,
) -> Path:
    """Clone or reuse a dedicated experiment clone without authentication."""
    destination = Path(root).expanduser().resolve()
    remote = _remote_url(repository)
    branch = str(branch or "main").strip()
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or ".." in Path(branch).parts:
        raise DesignExperimentError("experiment branch is invalid")
    if destination.exists():
        if not destination.is_dir():
            raise DesignExperimentError("experiment clone path is not a directory")
        if (destination / ".git").exists():
            current = _run(destination, "remote", "get-url", "origin").strip().rstrip("/")
            if current != remote.rstrip("/"):
                raise DesignExperimentError("existing experiment clone points at a different repository")
            if _run(destination, "status", "--porcelain").strip():
                raise DesignExperimentError("existing experiment clone is dirty")
            _run(destination, "fetch", "--no-tags", "origin", f"refs/heads/{branch}:refs/remotes/origin/{branch}", timeout=300)
        elif any(destination.iterdir()):
            raise DesignExperimentError("experiment clone path must be empty or an existing matching clone")
        else:
            destination.rmdir()
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        if progress:
            progress("cloning the public repository into the experiment directory")
        proc = subprocess.run(
            ["git", "clone", "--no-tags", "--single-branch", "--branch", branch, remote, str(destination)],
            capture_output=True,
            text=True,
            timeout=300,
            env=_public_git_env(),
        )
        if proc.returncode:
            raise DesignExperimentError(proc.stderr.strip()[:500] or "public repository clone failed")
    return destination


def clone_local_repository(
    source: str | Path,
    root: str | Path,
    base_sha: str,
    *,
    progress=None,
) -> Path:
    """Copy a local site clone into an isolated, exact-baseline experiment.

    This intentionally never contacts the source remote. The resulting clone
    has no ``origin`` remote, so a local chat experiment cannot fetch, push, or
    accidentally mutate the persistent site clone.
    """
    source_path = Path(source).expanduser().resolve()
    destination = Path(root).expanduser().resolve()
    sha = str(base_sha or "").strip().lower()
    if not _SHA.fullmatch(sha):
        raise DesignExperimentError("local experiment baseline must be a full commit SHA")
    if not (source_path / ".git").exists():
        raise DesignExperimentError(f"source site clone is missing at {source_path}")
    if source_path == destination or source_path in destination.parents or destination in source_path.parents:
        raise DesignExperimentError("local experiment clone overlaps the source site clone")
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise DesignExperimentError("local experiment clone path must be empty or absent")
        destination.rmdir()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("copying the persistent site clone into an isolated experiment directory")
    proc = subprocess.run(
        [
            "git", "clone", "--no-local", "--no-hardlinks", "--no-checkout",
            str(source_path), str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        env=_public_git_env(),
    )
    if proc.returncode:
        raise DesignExperimentError(proc.stderr.strip()[:500] or "local experiment clone failed")
    try:
        _run(destination, "cat-file", "-e", f"{sha}^{{commit}}")
        _run(destination, "checkout", "--detach", sha, timeout=180)
        _run(destination, "remote", "remove", "origin")
        resolved = _run(destination, "rev-parse", "HEAD").strip().lower()
    except DesignExperimentError:
        raise
    if resolved != sha:
        raise DesignExperimentError("local experiment clone did not reach the requested baseline SHA")
    return destination


def initialize_neutral_repository(root: str | Path) -> tuple[Path, str]:
    """Create a host-owned, remote-free scaffold with an immutable baseline."""
    destination = Path(root).expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        if not (destination / ".git").is_dir():
            raise DesignExperimentError("neutral scaffold path must be empty or an existing Git scaffold")
        if _run(destination, "remote").strip():
            raise DesignExperimentError("neutral scaffold must not have a remote")
        if _run(destination, "status", "--porcelain").strip():
            raise DesignExperimentError("neutral scaffold must be clean before use")
        return destination, resolve_commit_sha(destination, "HEAD")

    from ..site_scaffold import initialize_toolchain_workspace

    initialize_toolchain_workspace(destination, "New website")
    _run(destination, "init", "-q", "-b", "main")
    _run(destination, "config", "user.email", "intake-ada@localhost")
    _run(destination, "config", "user.name", "Intake Ada")
    _run(destination, "add", "-A")
    _run(destination, "commit", "-qm", "neutral scaffold baseline")
    return destination, resolve_commit_sha(destination, "HEAD")


def detach_remote(root: str | Path, remote: str = "origin") -> None:
    """Remove a clone remote after an exact baseline has been resolved."""
    destination = Path(root).expanduser().resolve()
    names = _run(destination, "remote").splitlines()
    if remote in {item.strip() for item in names}:
        _run(destination, "remote", "remove", remote)


def resolve_commit_sha(root: str | Path, ref: str) -> str:
    """Resolve a local commit using the credential-free Git environment."""
    value = str(ref or "").strip()
    if not value:
        raise DesignExperimentError("experiment baseline ref is required")
    resolved = _run(Path(root).expanduser().resolve(), "rev-parse", "--verify", f"{value}^{{commit}}").strip().lower()
    if not _SHA.fullmatch(resolved):
        raise DesignExperimentError(f"git did not return a full baseline SHA for {value}")
    return resolved


def head_sha(root: str | Path, branch: str = "main") -> str:
    value = _run(Path(root).expanduser().resolve(), "rev-parse", "--verify", f"refs/remotes/origin/{branch}^{{commit}}").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise DesignExperimentError("experiment baseline did not resolve to a full commit SHA")
    return value


def remote_heads(root: str | Path) -> dict[str, str]:
    output = _run(Path(root).expanduser().resolve(), "ls-remote", "--heads", "origin", timeout=120)
    result: dict[str, str] = {}
    for line in output.splitlines():
        sha, _, ref = line.partition("\t")
        if re.fullmatch(r"[0-9a-f]{40}", sha) and ref.startswith("refs/heads/"):
            result[ref] = sha
    return result


__all__ = [
    "DesignExperimentError",
    "clone_local_repository",
    "clone_public_repository",
    "detach_remote",
    "head_sha",
    "initialize_neutral_repository",
    "remote_heads",
    "resolve_commit_sha",
]
