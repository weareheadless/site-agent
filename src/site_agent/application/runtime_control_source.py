"""Exact local Git-object materialization for selected runtime control bytes.

This helper does not select a receipt or establish deployment freshness.
"""
from __future__ import annotations

import contextlib
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from site_agent.application.runtime_activation import RuntimeActivation
from site_agent.application.shared_runtime import shared_runtime_fingerprint


class RuntimeControlSourceError(RuntimeError):
    """The selected local control object cannot be safely materialized."""


@dataclass(frozen=True, slots=True)
class RuntimeControlSource:
    control_sha: str
    shared_runtime_fingerprint: str
    source_root: Path


_OFFICIAL = re.compile(r"(?:git@github\.com:weareheadless/site-agent|https://github\.com/weareheadless/site-agent)(?:\.git)?\Z")


def _git(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeControlSourceError("local Git object operation failed") from exc


def _materialize_tree(repo: Path, sha: str, root: Path) -> None:
    """Write only regular blobs from the selected commit's tree, byte-for-byte."""
    entries = _git(repo, "ls-tree", "-rz", "--full-tree", sha).split(b"\0")
    seen: set[str] = set()
    for entry in entries:
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b"\t", 1)
            mode, object_type, object_id = metadata.split(b" ")
            path_text = raw_path.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise RuntimeControlSourceError("Git tree contains a malformed or ambiguous entry") from exc
        parts = path_text.split("/")
        if (not path_text or path_text.startswith("/") or "\\" in path_text
                or any(part in {"", ".", ".."} for part in parts)
                or any("\x00" in part for part in parts)):
            raise RuntimeControlSourceError("Git tree contains an unsafe path")
        if mode not in {b"100644", b"100755"} or object_type != b"blob":
            raise RuntimeControlSourceError("Git tree contains an unsupported entry")
        if path_text in seen:
            raise RuntimeControlSourceError("Git tree contains a duplicate path")
        seen.add(path_text)
        destination = root.joinpath(*parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_git(repo, "cat-file", "blob", object_id.decode("ascii")))
        if mode == b"100755":
            destination.chmod(0o755)


@contextlib.contextmanager
def materialize_runtime_control(
    binding: RuntimeActivation, repository: Path, scratch_parent: Path,
) -> Iterator[RuntimeControlSource]:
    """Yield exact, fingerprint-verified control bytes in an owned temp directory."""
    if not isinstance(binding, RuntimeActivation):
        raise RuntimeControlSourceError("runtime activation binding is malformed")
    try:
        RuntimeActivation.from_mapping(binding.to_dict())
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeControlSourceError("runtime activation binding is malformed") from exc
    if (not re.fullmatch(r"[0-9a-f]{40}", binding.control_sha)
            or not re.fullmatch(r"[0-9a-f]{64}", binding.shared_runtime_fingerprint)):
        raise RuntimeControlSourceError("runtime activation binding is malformed")
    try:
        repo = Path(repository).resolve(strict=True)
        parent = Path(scratch_parent)
        if parent.is_symlink() or not parent.is_dir():
            raise RuntimeControlSourceError("owned scratch parent must be an existing real directory")
        parent = parent.resolve(strict=True)
        origins = _git(repo, "remote", "get-url", "origin").decode("utf-8").strip().splitlines()
        sha = binding.control_sha
        if _git(repo, "cat-file", "-t", sha).decode().strip() != "commit":
            raise RuntimeControlSourceError("selected control object is not a commit")
        if _git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}").decode().strip() != sha:
            raise RuntimeControlSourceError("selected control SHA is not an exact commit")
    except UnicodeError as exc:
        raise RuntimeControlSourceError("repository metadata is invalid") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeControlSourceError("repository or scratch path is invalid") from exc
    if len(origins) != 1 or not _OFFICIAL.fullmatch(origins[0]):
        raise RuntimeControlSourceError("repository origin is not the official Site-Agent repository")
    with tempfile.TemporaryDirectory(prefix="ui047-control-", dir=parent) as temp:
        root = Path(temp) / "source"
        root.mkdir()
        try:
            _materialize_tree(repo, sha, root)
            actual = shared_runtime_fingerprint(root)
            if actual != binding.shared_runtime_fingerprint:
                raise RuntimeControlSourceError("selected control fingerprint does not match activation")
        except RuntimeControlSourceError:
            raise
        except Exception as exc:
            raise RuntimeControlSourceError("selected control snapshot is invalid") from exc
        yield RuntimeControlSource(sha, actual, root)
