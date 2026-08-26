"""Preview rendering primitives shared by the admin review endpoint.

This module deliberately knows nothing about FastAPI, drafts, or sessions. It
turns a staged site's generated output into files the Design iframe can load
and keeps preview URL rewriting independent from the deployment mount point.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path, PurePosixPath


_HTML_URL = re.compile(
    r"(?P<prefix>\b(?:href|src)\s*=\s*)"
    r"(?P<quote>[\"'])(?P<value>[^\"']*)(?P=quote)",
    re.IGNORECASE,
)


def _relative_review_root(page_path: str) -> str:
    """Return the relative URL from a rendered page to its review root."""
    parent = PurePosixPath(page_path).parent
    depth = len([part for part in parent.parts if part not in ("", ".")])
    return "../" * depth or "./"


def rewrite_preview_html(
    data: bytes,
    draft_id: int,
    page_path: str,
    site_url: str = "",
) -> bytes:
    """Route site-owned HTML URLs through the current admin mount.

    Relative URLs are intentional: an iframe loaded at ``/ada/api/review``
    stays under ``/ada`` without this module needing deployment-specific
    knowledge. External URLs, fragments, data URLs, and protocol-relative URLs
    are left untouched.
    """
    text = data.decode("utf-8", "replace")
    page_path = page_path.lstrip("/") or "index.html"
    relative_root = _relative_review_root(page_path)
    configured_site_url = site_url.strip().rstrip("/")

    def replace_url(match: re.Match[str]) -> str:
        value = match.group("value")
        target = ""
        if configured_site_url and value.startswith(configured_site_url + "/"):
            target = value[len(configured_site_url) + 1 :]
        elif value == "/":
            target = "index.html"
        elif value.startswith("/") and not value.startswith("//"):
            target = value[1:]
        else:
            return match.group(0)

        return (
            f"{match.group('prefix')}{match.group('quote')}"
            f"{relative_root}{target}"
            f"{match.group('quote')}"
        )

    return _HTML_URL.sub(replace_url, text).encode("utf-8")


class PreviewBuildCache:
    """Build a preview ref once and serve generated output files from it.

    The cache is process-local and keyed by the resolved Git commit. It is not
    product state: a restart simply rebuilds the current preview when needed.
    """

    def __init__(self, max_entries: int = 3) -> None:
        self.max_entries = max(1, max_entries)
        self._entries: OrderedDict[tuple[str, str], Path] = OrderedDict()
        self._lock = threading.Lock()

    def read_file(self, clone: Path, ref: str, name: str) -> bytes:
        """Return a generated output file, or ``b""`` when it cannot build."""
        rel = PurePosixPath(name.lstrip("/"))
        if not rel.parts or ".." in rel.parts:
            return b""

        clone_key = str(clone.resolve())
        with self._lock:
            revision = self._revision(clone, ref)
            if not revision:
                return b""
            key = (clone_key, revision)
            output = self._entries.get(key)
            if output is None or not output.is_dir():
                output = self._build(clone, ref)
                if output is None:
                    return b""
                self._entries[key] = output
                self._entries.move_to_end(key)
                self._trim_locked()
            else:
                self._entries.move_to_end(key)

            target = (output / rel).resolve()
            output_root = output.resolve()
            if output_root != target and output_root not in target.parents:
                return b""
            try:
                return target.read_bytes()
            except OSError:
                return b""

    def clear(self) -> None:
        """Remove cached build directories, primarily for tests and shutdown."""
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for output in entries:
            shutil.rmtree(output.parent.parent, ignore_errors=True)

    @staticmethod
    def _revision(clone: Path, ref: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(clone), "rev-parse", ref],
            capture_output=True,
            timeout=30,
        )
        return proc.stdout.decode().strip() if proc.returncode == 0 else ""

    @staticmethod
    def _safe_extract(archive: tarfile.TarFile, destination: Path) -> bool:
        root = destination.resolve()
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                return False
        archive.extractall(destination)
        return True

    @classmethod
    def _build(cls, clone: Path, ref: str) -> Path | None:
        tmp = Path(tempfile.mkdtemp(prefix="site-agent-preview-"))
        archive_path = tmp / "site.tar"
        site = tmp / "site"
        try:
            archive = subprocess.run(
                ["git", "-C", str(clone), "archive", ref],
                capture_output=True,
                timeout=30,
            )
            if archive.returncode != 0:
                raise RuntimeError("could not archive preview ref")
            archive_path.write_bytes(archive.stdout)
            site.mkdir()
            with tarfile.open(archive_path) as tar:
                if not cls._safe_extract(tar, site):
                    raise RuntimeError("preview archive contains an unsafe path")
            build = site / "build.sh"
            if not build.is_file():
                raise RuntimeError("preview has no build.sh")
            built = subprocess.run(
                ["bash", "build.sh"],
                cwd=site,
                capture_output=True,
                timeout=60,
            )
            output = site / "output"
            if built.returncode != 0 or not output.is_dir():
                raise RuntimeError("preview build failed")
            archive_path.unlink(missing_ok=True)
            return output
        except (OSError, RuntimeError, subprocess.SubprocessError, tarfile.TarError):
            shutil.rmtree(tmp, ignore_errors=True)
            return None

    def _trim_locked(self) -> None:
        while len(self._entries) > self.max_entries:
            _, output = self._entries.popitem(last=False)
            shutil.rmtree(output.parent.parent, ignore_errors=True)
