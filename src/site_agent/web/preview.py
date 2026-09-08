"""Preview rendering primitives shared by the admin review endpoint.

This module deliberately knows nothing about FastAPI, drafts, or sessions. It
turns a staged site's generated output into files the Design iframe can load
and keeps preview URL rewriting independent from the deployment mount point.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..hands.site_build import PELICAN_BASELINE_PROFILE, SiteBuildError, SiteBuildProfile, build_site, get_build_profile


PreviewScope = tuple[str, str | int]


_HTML_URL = re.compile(
    r"(?P<prefix>\b(?:href|src)\s*=\s*)"
    r"(?P<quote>[\"'])(?P<value>[^\"']*)(?P=quote)",
    re.IGNORECASE,
)
_CSS_URL = re.compile(
    r"(?P<prefix>\burl\(\s*)(?P<quote>[\"']?)(?P<value>.*?)(?P=quote)(?P<suffix>\s*\))",
    re.IGNORECASE,
)
_LOCAL_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


class PreviewAccess:
    """Short-lived bearer capabilities limited to one preview scope."""

    def __init__(self, ttl: int = 10 * 60) -> None:
        self.ttl = max(60, ttl)
        self._tokens: dict[str, tuple[PreviewScope, float]] = {}
        self._lock = threading.Lock()

    def issue(self, scope: PreviewScope) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = time.monotonic()
            self._prune_locked(now)
            self._tokens[token] = (scope, now + self.ttl)
        return token

    def valid(self, token: str | None, scope: PreviewScope) -> bool:
        if not token:
            return False
        with self._lock:
            now = time.monotonic()
            self._prune_locked(now)
            grant = self._tokens.get(token)
            return bool(grant and grant[0] == scope and grant[1] > now)

    def _prune_locked(self, now: float) -> None:
        expired = [token for token, (_, expires_at) in self._tokens.items() if expires_at <= now]
        for token in expired:
            del self._tokens[token]


def _relative_review_root(page_path: str) -> str:
    """Return the relative URL from a rendered page to its review root."""
    parent = PurePosixPath(page_path).parent
    depth = len([part for part in parent.parts if part not in ("", ".")])
    return "../" * depth or "./"


def _local_reference(value: str) -> bool:
    return bool(value) and not value.startswith(("#", "//")) and not _LOCAL_SCHEME.match(value)


def _with_preview_token(value: str, access_token: str, preview_variant: str = "") -> str:
    if not value or (not access_token and not preview_variant):
        return value
    parts = urlsplit(value)
    query = parse_qsl(parts.query, keep_blank_values=True)
    keys = {key for key, _ in query}
    if access_token and "preview_token" not in keys:
        query.append(("preview_token", access_token))
    if preview_variant and "variant" not in keys:
        query.append(("variant", preview_variant))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _preview_runtime(access_token: str, preview_variant: str = "", preview_root: str = "") -> str:
    """Give sandboxed site scripts a narrow, token-authenticated fetch path."""
    runtime = r'''<script data-site-agent-preview>
(() => {
  const token = __SITE_AGENT_PREVIEW_TOKEN__;
  const variant = __SITE_AGENT_PREVIEW_VARIANT__;
  const explicitPreviewRoot = __SITE_AGENT_PREVIEW_ROOT__;
  const previewPath = explicitPreviewRoot
    ? new RegExp('^' + explicitPreviewRoot.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    : /\/api\/(?:preview|review|design\/runs\/[^/]+\/review)\//;
  const page = new URL(location.href);
  const rootMatch = page.pathname.match(/^(.*\/api\/(?:preview|review)\/(?:\d+\/)?|.*\/api\/design\/runs\/[^/]+\/review\/)/);
  const previewRoot = explicitPreviewRoot || (rootMatch && rootMatch[1]);
  const addToken = input => {
    const raw = input instanceof Request ? input.url : String(input);
    let url;
    try { url = new URL(raw, location.href); } catch (_) { return raw; }
    const local = url.protocol === page.protocol && url.host === page.host;
    if (!local) return raw;
    if (!previewPath.test(url.pathname) && previewRoot && raw.startsWith('/') && !raw.startsWith('/api/')) {
      const mapped = new URL(previewRoot + url.pathname.replace(/^\/+/, ''), page.href);
      mapped.search = url.search;
      mapped.hash = url.hash;
      url = mapped;
    }
    if (previewPath.test(url.pathname)) {
      url.searchParams.set('preview_token', token);
      if (variant) url.searchParams.set('variant', variant);
    }
    return url.href;
  };
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = addToken(input);
    return input instanceof Request ? nativeFetch(new Request(url, input), init) : nativeFetch(url, init);
  };
  const nativeOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    return nativeOpen.call(this, method, addToken(url), ...rest);
  };
  if (navigator.sendBeacon) {
    const nativeBeacon = navigator.sendBeacon.bind(navigator);
    navigator.sendBeacon = (url, data) => nativeBeacon(addToken(url), data);
  }
  try {
    const clean = new URL(location.href);
    clean.searchParams.delete('preview_token');
    history.replaceState(null, '', clean.pathname + clean.search + clean.hash);
  } catch (_) {}
})();
</script>
'''
    return (
        runtime.replace("__SITE_AGENT_PREVIEW_TOKEN__", json.dumps(access_token))
        .replace("__SITE_AGENT_PREVIEW_VARIANT__", json.dumps(preview_variant))
        .replace("__SITE_AGENT_PREVIEW_ROOT__", json.dumps(preview_root.rstrip("/") + "/" if preview_root else ""))
    )


def _inject_preview_runtime(text: str, access_token: str, preview_variant: str = "", preview_root: str = "") -> str:
    if not access_token:
        return text
    runtime = _preview_runtime(access_token, preview_variant, preview_root)
    head = re.search(r"<head\b[^>]*>", text, re.IGNORECASE)
    if head:
        return text[:head.end()] + runtime + text[head.end():]
    return runtime + text


def rewrite_preview_html(
    data: bytes,
    draft_id: int,
    page_path: str,
    site_url: str = "",
    access_token: str = "",
    preview_variant: str = "",
    preview_root: str = "",
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
        elif _local_reference(value):
            return (
                f"{match.group('prefix')}{match.group('quote')}"
                f"{_with_preview_token(value, access_token, preview_variant)}"
                f"{match.group('quote')}"
            )
        else:
            return match.group(0)

        target = _with_preview_token(target, access_token, preview_variant)
        return (
            f"{match.group('prefix')}{match.group('quote')}"
            f"{relative_root}{target}"
            f"{match.group('quote')}"
        )

    text = _HTML_URL.sub(replace_url, text)
    return _inject_preview_runtime(text, access_token, preview_variant, preview_root).encode("utf-8")


def rewrite_preview_css(data: bytes, page_path: str, access_token: str = "", preview_variant: str = "") -> bytes:
    """Keep CSS asset URLs inside the token-authenticated preview tree."""
    if not access_token:
        return data
    text = data.decode("utf-8", "replace")
    relative_root = _relative_review_root(page_path)

    def replace_url(match: re.Match[str]) -> str:
        value = match.group("value").strip()
        if not _local_reference(value) or value.startswith("var("):
            return match.group(0)
        target = relative_root + value.lstrip("/") if value.startswith("/") else value
        return (
            f"{match.group('prefix')}{match.group('quote')}"
                f"{_with_preview_token(target, access_token, preview_variant)}"
            f"{match.group('quote')}{match.group('suffix')}"
        )

    return _CSS_URL.sub(replace_url, text).encode("utf-8")


class PreviewBuildCache:
    """Build a preview ref once and serve generated output files from it.

    The cache is process-local and keyed by the resolved Git commit. It is not
    product state: a restart simply rebuilds the current preview when needed.
    """

    def __init__(
        self,
        max_entries: int = 3,
        build_env: Mapping[str, str] | None = None,
        temp_root: str | Path | None = None,
    ) -> None:
        self.max_entries = max(1, max_entries)
        self.build_env = dict(build_env) if build_env is not None else None
        raw_temp_root = str(temp_root or "").strip()
        self.temp_root = Path(raw_temp_root).expanduser().resolve() if raw_temp_root else None
        self._entries: OrderedDict[tuple[str, str, str, str], Path] = OrderedDict()
        self._lock = threading.Lock()

    def read_file(
        self,
        clone: Path,
        ref: str,
        name: str,
        overlays: Mapping[str, bytes] | None = None,
        profile: SiteBuildProfile | str | None = None,
    ) -> bytes:
        """Return a generated output file, or ``b""`` when it cannot build."""
        rel = PurePosixPath(name.lstrip("/"))
        if not rel.parts or ".." in rel.parts:
            return b""

        clone_key = str(clone.resolve())
        try:
            build_profile = self._resolve_profile(profile)
        except (SiteBuildError, TypeError, ValueError):
            return b""
        with self._lock:
            revision = self._revision(clone, ref)
            if not revision:
                return b""
            key = (clone_key, revision, self._overlay_hash(overlays), build_profile.name)
            output = self._entries.get(key)
            if output is None or not output.is_dir():
                output = self._build(clone, ref, overlays, build_profile, build_env=self.build_env)
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
    def _overlay_hash(overlays: Mapping[str, bytes] | None) -> str:
        if not overlays:
            return ""
        digest = hashlib.sha256()
        for name in sorted(overlays):
            data = overlays[name]
            if not isinstance(data, bytes):
                raise RuntimeError("preview overlay data must be bytes")
            digest.update(str(name).encode("utf-8"))
            digest.update(b"\0")
            digest.update(data)
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _resolve_profile(profile: SiteBuildProfile | str | None) -> SiteBuildProfile:
        if profile is None or (isinstance(profile, str) and not profile.strip()):
            return PELICAN_BASELINE_PROFILE
        if isinstance(profile, SiteBuildProfile):
            return profile
        return get_build_profile(str(profile))

    @staticmethod
    def _safe_extract(archive: tarfile.TarFile, destination: Path) -> bool:
        root = destination.resolve()
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                return False
        archive.extractall(destination)
        return True

    def _build(
        self,
        clone: Path,
        ref: str,
        overlays: Mapping[str, bytes] | None = None,
        profile: SiteBuildProfile | str | None = None,
        build_env: Mapping[str, str] | None = None,
    ) -> Path | None:
        try:
            build_profile = self._resolve_profile(profile)
        except (SiteBuildError, TypeError, ValueError):
            return None
        if self.temp_root is not None:
            try:
                self.temp_root.mkdir(parents=True, exist_ok=True)
                if not self.temp_root.is_dir():
                    return None
            except OSError:
                return None
        try:
            tmp = Path(tempfile.mkdtemp(
                prefix="site-agent-preview-",
                dir=str(self.temp_root) if self.temp_root is not None else None,
            ))
        except OSError:
            return None
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
                if not self._safe_extract(tar, site):
                    raise RuntimeError("preview archive contains an unsafe path")
            if overlays:
                site_root = site.resolve()
                for raw_name, data in overlays.items():
                    rel = PurePosixPath(str(raw_name))
                    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
                        raise RuntimeError("preview overlay contains an unsafe path")
                    target = (site / rel).resolve()
                    if target == site_root or site_root not in target.parents:
                        raise RuntimeError("preview overlay contains an unsafe path")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
            build_environment = dict(build_env) if build_env is not None else os.environ.copy()
            if build_profile.name == PELICAN_BASELINE_PROFILE.name:
                build = site / "build.sh"
                if not build.is_file():
                    raise RuntimeError("preview has no build.sh")
                python_bin = Path(sys.executable).parent
                build_environment["PATH"] = os.pathsep.join(
                    part for part in (str(python_bin), build_environment.get("PATH", "")) if part
                )
                built = subprocess.run(
                    ["bash", "build.sh"],
                    cwd=site,
                    capture_output=True,
                    timeout=60,
                    env=build_environment,
                )
                output = site / build_profile.output_dir
                if built.returncode != 0 or not output.is_dir():
                    raise RuntimeError("preview build failed")
            else:
                result = build_site(
                    site,
                    build_profile,
                    npm_cache=tmp / "npm-cache",
                    env=build_environment,
                    timeout_seconds=60,
                )
                if not result.ok:
                    raise RuntimeError("preview build failed")
                output = site / build_profile.output_dir
                if not output.is_dir():
                    raise RuntimeError("preview build output is missing")
            archive_path.unlink(missing_ok=True)
            return output
        except (OSError, RuntimeError, subprocess.SubprocessError, tarfile.TarError):
            shutil.rmtree(tmp, ignore_errors=True)
            return None

    def _trim_locked(self) -> None:
        while len(self._entries) > self.max_entries:
            _, output = self._entries.popitem(last=False)
            shutil.rmtree(output.parent.parent, ignore_errors=True)
