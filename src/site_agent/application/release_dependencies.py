"""Verify private GitHub releases and seed npm's cache with exact locked bytes."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any

ASSET = re.compile(
    r"^https://github\.com/weareheadless/site-agent/releases/download/([^/]+)/([^/]+\.tgz)$"
)
# Every platform package is published as an immutable release of this one
# repository, so the release URL is the contract. This used to be a hardcoded
# catalogue of package names, which drifted from what tenants actually pinned:
# a tenant that still declared a package the platform had shipped failed its
# preview build as "undeclared", while the release pipeline deployed the same
# repository. Each declared package is verified below; nothing is ignored.
RELEASE_PACKAGE_PREFIX = "@weareheadless/"
RELEASE_ASSET_API = "/repos/weareheadless/site-agent/releases"

class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "api.github.com",
            "release-assets.githubusercontent.com",
        }:
            raise RuntimeError("Unexpected GitHub release redirect host")
        redirected = super().redirect_request(request, fp, code, message, headers, url)
        if parsed.hostname != "api.github.com":
            redirected.remove_header("Authorization")
        return redirected

def github_fetch(path: str, token: str, *, binary: bool = False) -> Any:
    request = urllib.request.Request(
        "https://api.github.com" + path,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.build_opener(ReleaseRedirect()).open(request, timeout=60) as response:
        data = response.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024:
        raise RuntimeError("Release asset exceeds maximum size")
    return data if binary else json.loads(data)

def verify_integrity(data: bytes, integrity: str, package_name: str) -> None:
    actual = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
    if integrity != actual:
        raise RuntimeError(
            f"{package_name}: published artifact SHA-512 does not match package-lock.json "
            f"(expected {integrity}, received {actual})"
        )

def _declared_packages(package: dict[str, Any]) -> tuple[str, ...]:
    """Select the platform release packages a checkout actually depends on.

    The checkout is the contract: any package published as an immutable release
    of this repository is verified, and each one must carry the exact release
    URL and locked integrity. A dependency that is not such a package fails in
    ``_verified_release_dependencies`` instead of being silently skipped.
    """
    declared = sorted(
        name for name in (package.get("dependencies") or {})
        if name.startswith(RELEASE_PACKAGE_PREFIX)
    )
    return tuple(declared)


def _verified_release_dependencies(
    checkout: Path,
    token: str,
    package_names: tuple[str, ...] | None = None,
) -> Iterator[dict[str, Any]]:
    if not token:
        raise RuntimeError("Central GitHub release credential is required")
    package = json.loads((checkout / "package.json").read_text(encoding="utf-8"))
    if package_names is None:
        package_names = _declared_packages(package)
    if any(not name.startswith(RELEASE_PACKAGE_PREFIX) for name in package_names):
        raise ValueError("Only platform release packages can be verified")
    lock = json.loads((checkout / "package-lock.json").read_text(encoding="utf-8"))
    for name in package_names:
        url = package.get("dependencies", {}).get(name)
        match = ASSET.fullmatch(str(url or ""))
        entry = lock.get("packages", {}).get("node_modules/" + name)
        if not match or not isinstance(entry, dict) or entry.get("resolved") != url or not entry.get("integrity"):
            raise RuntimeError(f"{name}: requires an exact GitHub release URL and locked integrity")
        tag, filename = match.groups()
        release = github_fetch(
            f"{RELEASE_ASSET_API}/tags/{urllib.parse.quote(tag, safe='')}",
            token,
        )
        if release.get("tag_name") != tag or release.get("draft"):
            raise RuntimeError(f"{name}: expected published immutable GitHub release {tag}")
        assets = [asset for asset in release.get("assets", []) if asset.get("name") == filename]
        if len(assets) != 1:
            raise RuntimeError(f"{name}: expected exactly one GitHub release asset {filename}")
        asset = assets[0]
        data = github_fetch(
            f"{RELEASE_ASSET_API}/assets/{asset['id']}",
            token,
            binary=True,
        )
        verify_integrity(data, str(entry["integrity"]), name)
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        if asset.get("digest") != digest:
            raise RuntimeError(f"{name}: GitHub asset digest does not match downloaded bytes")
        yield {
            "package": name,
            "release": tag,
            "filename": filename,
            "assetId": asset["id"],
            "url": url,
            "integrity": entry["integrity"],
            "digest": digest,
            "data": data,
        }

def verify_release_dependencies(
    checkout: Path,
    token: str,
    package_names: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Verify canonical lockfile entries against exact published GitHub bytes."""
    keys = ("package", "release", "assetId", "integrity", "digest")
    return [
        {key: artifact[key] for key in keys}
        for artifact in _verified_release_dependencies(checkout, token, package_names)
    ]

def prepare_release_dependencies(
    checkout: Path,
    token: str,
    npm: str,
    temporary_root: Path,
    run: Callable[[list[str], Path], None],
    package_names: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Verify exact private packages and seed npm's cache without changing the lockfile."""
    checkout = checkout.resolve()
    temporary_root = temporary_root.resolve()
    temporary_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    evidence: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix="helloada-verified-release-assets-",
        dir=temporary_root,
    ) as temporary:
        asset_root = Path(temporary)
        for artifact in _verified_release_dependencies(checkout, token, package_names):
            target = asset_root / artifact["filename"]
            target.write_bytes(artifact["data"])
            target.chmod(0o600)
            run([npm, "cache", "add", str(target), "--ignore-scripts"], checkout)
            evidence.append({
                key: artifact[key]
                for key in ("package", "release", "assetId", "integrity", "digest")
            })
    return evidence


def main() -> int:
    import argparse
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", action="append")
    args = parser.parse_args()
    checkout = Path.cwd() / "src/site_agent/templates/next-payload"
    package_names = tuple(args.package) if args.package else None
    for item in verify_release_dependencies(checkout, os.environ.get("GITHUB_TOKEN", ""), package_names):
        print(f"Verified {item['package']} {item['release']} ({item['digest']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
