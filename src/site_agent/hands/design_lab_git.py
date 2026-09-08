"""Local-only Git helpers for the disposable design lab.

This adapter deliberately has no push, merge, or publish operation.  It clones
public/local source, creates detached worktrees, and writes only a namespaced
local ref for a retained candidate.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit
from collections.abc import Mapping


class DesignLabGitError(RuntimeError):
    """A local design-lab Git operation failed."""


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]+$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_SAFE_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_ENV_KEYS = {
    "HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "USERPROFILE"
}
_BLOCKED_PREFIXES = ("GITHUB_", "GH_", "CLOUDFLARE_", "R2_", "AWS_", "AZURE_", "GOOGLE_", "CICERO_")
_BLOCKED_EXACT = {
    "GITHUB_TOKEN", "GH_TOKEN", "CLOUDFLARE_API_TOKEN", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
    "SITE_AGENT_ADMIN_PASSWORD", "CRAWLSEO_SERVICE_TOKEN", "SITE_AGENT_VISION_API_KEY",
}


def design_lab_environment(source: Mapping[str, str] | None = None, *, model_env_name: str = "") -> dict[str, str]:
    """Return a minimal child environment with only the selected model secret."""
    source = os.environ if source is None else source
    result = {key: str(source[key]) for key in _SAFE_ENV_KEYS if key in source and str(source[key])}
    model_env_name = str(model_env_name or "").strip()
    if model_env_name and _SAFE_ENV_NAME.fullmatch(model_env_name) and source.get(model_env_name):
        result[model_env_name] = str(source[model_env_name])
    result.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ASKPASS": os.devnull,
    })
    return result


def _run(repo: Path, args: tuple[str, ...], *, env: Mapping[str, str], timeout: int = 300) -> str:
    try:
        process = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=max(1, min(int(timeout), 900)),
            env=dict(env),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DesignLabGitError(f"git {' '.join(args[:2])} failed: {str(exc)[:300]}") from exc
    if process.returncode:
        detail = (process.stderr or process.stdout or "git command failed").strip()
        raise DesignLabGitError(f"git {' '.join(args[:2])} failed: {detail[:500]}")
    return process.stdout


def _remote_for(repository: str) -> tuple[str, Path | None]:
    value = str(repository or "").strip()
    if _REPOSITORY.fullmatch(value):
        return f"https://github.com/{value}.git", None
    if value.startswith("file://"):
        parsed = urlsplit(value)
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise DesignLabGitError("local repository URL must not contain credentials or query data")
        path = Path(unquote(parsed.path)).expanduser().resolve()
    else:
        path = Path(value).expanduser().resolve()
    if not path.exists() or not (path.is_dir() or path.is_file()):
        raise DesignLabGitError("site.repository must be a public owner/repository or an existing local Git repository")
    return str(path), path


def _canonical_remote(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    if raw.startswith("file://"):
        return str(Path(unquote(urlsplit(raw).path)).expanduser().resolve()).rstrip("/")
    if raw.startswith("/"):
        return str(Path(raw).expanduser().resolve()).rstrip("/")
    return raw.removesuffix(".git").lower()


def clone_source(
    repository: str,
    destination: str | Path,
    *,
    branch: str = "main",
    env: Mapping[str, str] | None = None,
) -> Path:
    """Clone public or local source into the lab, reusing only a clean match."""
    remote, _ = _remote_for(repository)
    branch = str(branch or "main").strip()
    if not _BRANCH.fullmatch(branch) or ".." in Path(branch).parts:
        raise DesignLabGitError("design-lab branch is invalid")
    child_env = design_lab_environment(env)
    root = Path(destination).expanduser().resolve()
    if root.exists():
        if (root / ".git").exists():
            current = _run(root, ("remote", "get-url", "origin"), env=child_env).strip()
            if _canonical_remote(current) != _canonical_remote(remote):
                raise DesignLabGitError("existing design-lab clone points at a different repository")
            if _run(root, ("status", "--porcelain"), env=child_env).strip():
                raise DesignLabGitError("existing design-lab clone is dirty")
            _run(root, ("fetch", "--no-tags", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"), env=child_env)
            return root
        if any(root.iterdir()):
            raise DesignLabGitError("design-lab source directory must be empty or an existing matching clone")
        root.rmdir()
    root.parent.mkdir(parents=True, exist_ok=True)
    try:
        process = subprocess.run(
            ["git", "clone", "--no-tags", "--single-branch", "--branch", branch, remote, str(root)],
            capture_output=True,
            text=True,
            timeout=900,
            env=child_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DesignLabGitError(f"git clone failed: {str(exc)[:300]}") from exc
    if process.returncode:
        raise DesignLabGitError(f"git clone failed: {(process.stderr or process.stdout or '')[:500]}")
    return root


def remote_refs(repo: str | Path, *, env: Mapping[str, str] | None = None) -> dict[str, str]:
    output = _run(Path(repo).expanduser().resolve(), ("ls-remote", "--heads", "origin"), env=design_lab_environment(env))
    refs: dict[str, str] = {}
    for line in output.splitlines():
        sha, separator, ref = line.partition("\t")
        if separator and re.fullmatch(r"[0-9a-f]{40}", sha) and ref.startswith("refs/heads/"):
            refs[ref] = sha
    return refs


def baseline_sha(repo: str | Path, branch: str, *, env: Mapping[str, str] | None = None) -> str:
    branch = str(branch or "main").strip()
    if not _BRANCH.fullmatch(branch) or ".." in Path(branch).parts:
        raise DesignLabGitError("design-lab branch is invalid")
    value = _run(
        Path(repo).expanduser().resolve(),
        ("rev-parse", "--verify", f"refs/remotes/origin/{branch}^{{commit}}"),
        env=design_lab_environment(env),
    ).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise DesignLabGitError("design-lab baseline did not resolve to a full commit SHA")
    return value


def add_worktree(repo: str | Path, destination: str | Path, commit_sha: str, *, env: Mapping[str, str] | None = None) -> Path:
    if not re.fullmatch(r"[0-9a-f]{40}", str(commit_sha or "").lower()):
        raise DesignLabGitError("worktree commit must be a full SHA")
    root = Path(destination).expanduser().resolve()
    if root.exists():
        raise DesignLabGitError(f"worktree destination already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    _run(Path(repo).expanduser().resolve(), ("worktree", "add", "--detach", str(root), commit_sha), env=design_lab_environment(env), timeout=300)
    return root


def remove_worktree(repo: str | Path, worktree: str | Path, *, env: Mapping[str, str] | None = None) -> None:
    root = Path(worktree).expanduser().resolve()
    try:
        _run(Path(repo).expanduser().resolve(), ("worktree", "remove", "--force", str(root)), env=design_lab_environment(env), timeout=300)
    except DesignLabGitError:
        shutil.rmtree(root, ignore_errors=True)
        try:
            _run(Path(repo).expanduser().resolve(), ("worktree", "prune"), env=design_lab_environment(env), timeout=120)
        except DesignLabGitError:
            pass


def empty_worktree(worktree: str | Path) -> Path:
    """Remove source files from a fresh worktree while preserving its Git link."""
    root = Path(worktree).expanduser().resolve()
    if not root.is_dir() or not (root / ".git").exists():
        raise DesignLabGitError("candidate worktree is not a Git worktree")
    for child in root.iterdir():
        if child.name == ".git":
            continue
        if child.is_symlink() or child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)
    return root


def commit_candidate(worktree: str | Path, *, message: str, env: Mapping[str, str] | None = None) -> str:
    root = Path(worktree).expanduser().resolve()
    child_env = design_lab_environment(env)
    _run(root, ("add", "--all"), env=child_env, timeout=120)
    staged = _run(root, ("diff", "--cached", "--name-only"), env=child_env).strip()
    if not staged:
        raise DesignLabGitError("native design builder produced no repository changes")
    _run(root, ("-c", "user.name=Ada (design-lab)", "-c", "user.email=ada@site-agent.local", "commit", "--no-gpg-sign", "-m", message), env=child_env, timeout=300)
    value = _run(root, ("rev-parse", "HEAD^{commit}"), env=child_env).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise DesignLabGitError("candidate commit did not resolve to a full SHA")
    return value


def create_local_ref(repo: str | Path, run_id: str, commit_sha: str, *, env: Mapping[str, str] | None = None) -> str:
    run_id = str(run_id or "").strip()
    if not _RUN_ID.fullmatch(run_id) or not re.fullmatch(r"[0-9a-f]{40}", str(commit_sha or "").lower()):
        raise DesignLabGitError("invalid local candidate ref identity")
    ref = f"refs/ada-design-lab/{run_id}"
    _run(Path(repo).expanduser().resolve(), ("update-ref", ref, commit_sha, ""), env=design_lab_environment(env), timeout=120)
    return ref


__all__ = [
    "DesignLabGitError",
    "add_worktree",
    "baseline_sha",
    "clone_source",
    "commit_candidate",
    "create_local_ref",
    "design_lab_environment",
    "empty_worktree",
    "remote_refs",
    "remove_worktree",
]
