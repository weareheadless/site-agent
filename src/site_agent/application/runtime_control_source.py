"""Exact local Git-object materialization for selected runtime control bytes.

This helper does not select a receipt or establish deployment freshness.
"""
from __future__ import annotations

import contextlib
import io
import re
import subprocess
import tarfile
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
    repo = Path(repository).resolve(strict=True)
    parent = Path(scratch_parent)
    if parent.is_symlink() or not parent.is_dir():
        raise RuntimeControlSourceError("owned scratch parent must be an existing real directory")
    parent = parent.resolve(strict=True)
    try:
        origins = _git(repo, "remote", "get-url", "origin").decode("utf-8").strip().splitlines()
    except UnicodeError as exc:
        raise RuntimeControlSourceError("repository origin is invalid") from exc
    if len(origins) != 1 or not _OFFICIAL.fullmatch(origins[0]):
        raise RuntimeControlSourceError("repository origin is not the official Site-Agent repository")
    sha = binding.control_sha
    if _git(repo, "cat-file", "-t", sha).decode().strip() != "commit":
        raise RuntimeControlSourceError("selected control object is not a commit")
    if _git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}").decode().strip() != sha:
        raise RuntimeControlSourceError("selected control SHA is not an exact commit")
    archive = _git(repo, "archive", "--format=tar", sha)
    with tempfile.TemporaryDirectory(prefix="ui047-control-", dir=parent) as temp:
        root = Path(temp) / "source"
        root.mkdir()
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tf:
                members = tf.getmembers()
                for member in members:
                    p = Path(member.name)
                    if (p.is_absolute() or not p.parts or ".." in p.parts
                            or member.issym() or member.islnk()
                            or not (member.isfile() or member.isdir())):
                        raise RuntimeControlSourceError("Git archive contains an unsafe or unsupported entry")
                for member in members:
                    dest = root.joinpath(*Path(member.name).parts)
                    if member.isdir():
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        stream = tf.extractfile(member)
                        if stream is None:
                            raise RuntimeControlSourceError("Git archive file content is unavailable")
                        dest.write_bytes(stream.read())
            actual = shared_runtime_fingerprint(root)
            if actual != binding.shared_runtime_fingerprint:
                raise RuntimeControlSourceError("selected control fingerprint does not match activation")
            yield RuntimeControlSource(sha, actual, root)
        except RuntimeControlSourceError:
            raise
        except Exception as exc:
            raise RuntimeControlSourceError("selected control snapshot is invalid") from exc
