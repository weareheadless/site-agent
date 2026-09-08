"""Host-controlled capability provisioning for generated frontend sites.

The host owns the small allowlist, downloads only pinned package archives,
verifies their integrity, and exposes only approved local capability files to
the native source-authoring session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import subprocess
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class FrontendDependencyError(RuntimeError):
    """An approved frontend dependency could not be resolved safely."""


@dataclass(frozen=True)
class ApprovedFrontendLibrary:
    name: str
    package: str
    version: str
    integrity: str
    files: tuple[tuple[str, str], ...]
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class FrontendLibraryResult:
    """The verified runtime files and receipt for one design-lab compile."""

    files: dict[str, bytes]
    libraries: tuple[dict[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "libraries": [dict(item) for item in self.libraries],
            "files": sorted(self.files),
        }


# Keep package selection in host code.  The authoring session never accepts a package
# name, version, URL, or archive path from the model or design request.
APPROVED_FRONTEND_LIBRARIES: dict[str, ApprovedFrontendLibrary] = {
    "gsap": ApprovedFrontendLibrary(
        name="gsap",
        package="gsap",
        version="3.12.5",
        integrity="sha512-srBfnk4n+Oe/ZnMIOXt3gT605BX9x5+rh/prT2F1SsNJsU1XuMiP0E2aptW481OnonOGACZWBqseH5Z7csHxhQ==",
        files=(
            ("dist/gsap.min.js", "public/vendor/gsap/gsap.min.js"),
            ("dist/ScrollTrigger.min.js", "public/vendor/gsap/ScrollTrigger.min.js"),
            ("dist/Flip.min.js", "public/vendor/gsap/Flip.min.js"),
            ("dist/Observer.min.js", "public/vendor/gsap/Observer.min.js"),
            ("dist/Draggable.min.js", "public/vendor/gsap/Draggable.min.js"),
        ),
        capabilities=("timelines", "scroll-linked animation", "ScrollTrigger", "Flip", "Observer", "Draggable"),
    ),
}

_MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
_MAX_RUNTIME_FILE_BYTES = 2 * 1024 * 1024


def _enabled_libraries(config: Mapping[str, object]) -> tuple[ApprovedFrontendLibrary, ...]:
    engine = config.get("design_engine") or {}
    if not isinstance(engine, Mapping):
        raise FrontendDependencyError("design_engine must be an object")
    raw = engine.get("libraries") or {}
    if not isinstance(raw, Mapping):
        raise FrontendDependencyError("design_engine.libraries must be an object")

    enabled: list[ApprovedFrontendLibrary] = []
    for raw_name, setting in raw.items():
        name = str(raw_name).strip().lower()
        library = APPROVED_FRONTEND_LIBRARIES.get(name)
        if library is None:
            raise FrontendDependencyError(f"frontend library is not approved: {name}")
        if isinstance(setting, Mapping):
            flag = setting.get("enabled", True)
        elif isinstance(setting, bool):
            flag = setting
        else:
            raise FrontendDependencyError(f"design_engine.libraries.{name} must be a boolean or object")
        if not isinstance(flag, bool):
            raise FrontendDependencyError(f"design_engine.libraries.{name}.enabled must be boolean")
        if flag:
            enabled.append(library)
    return tuple(sorted(enabled, key=lambda item: item.name))


def available_frontend_libraries(config: Mapping[str, object]) -> list[dict[str, object]]:
    """Describe enabled capabilities without exposing integrity or archive details."""
    return [
        {
            "name": library.name,
            "package": library.package,
            "version": library.version,
            "capabilities": list(library.capabilities),
            "required": any(
                str(name).strip().lower() == library.name
                and isinstance(setting, Mapping)
                and setting.get("required") is True
                for name, setting in ((config.get("design_engine") or {}).get("libraries") or {}).items()
            ),
        }
        for library in _enabled_libraries(config)
    ]


def required_frontend_library_names(config: Mapping[str, object]) -> tuple[str, ...]:
    """Return instance-owned frontend libraries required by a typed baseline."""
    engine = config.get("design_engine") or {}
    raw = (engine.get("libraries") or {}) if isinstance(engine, Mapping) else {}
    if not isinstance(raw, Mapping):
        raise FrontendDependencyError("design_engine.libraries must be an object")
    enabled = {library.name for library in _enabled_libraries(config)}
    return tuple(sorted(
        str(name).strip().lower()
        for name, setting in raw.items()
        if isinstance(setting, Mapping)
        and setting.get("required") is True
        and str(name).strip().lower() in enabled
    ))


def _requested_library_names(motion: Mapping[str, object]) -> tuple[str, ...] | None:
    request_key = next(
        (key for key in ("libraries", "frontend_libraries", "library_requests") if key in motion),
        None,
    )
    if request_key is None:
        return None
    raw = motion[request_key]
    if not isinstance(raw, list):
        raise FrontendDependencyError(f"motion.{request_key} must be a list")
    names: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            item = item.get("name") or item.get("id") or item.get("library")
        if not isinstance(item, str) or not item.strip():
            raise FrontendDependencyError(f"motion.{request_key} entries must name a library")
        name = item.strip().lower()
        if name not in names:
            names.append(name)
    return tuple(names)


def _archive_path(destination: Path, library: ApprovedFrontendLibrary) -> Path:
    name = f"{library.package.replace('/', '-')}-{library.version}.tgz"
    target = (destination / name).resolve()
    if target.parent != destination.resolve():
        raise FrontendDependencyError("frontend dependency archive path escaped its cache")
    return target


def _pack(
    library: ApprovedFrontendLibrary,
    destination: Path,
    *,
    npm_cache: Path | None,
    env: Mapping[str, str] | None,
) -> Path:
    if destination.is_symlink():
        raise FrontendDependencyError("frontend dependency cache cannot be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    expected = _archive_path(destination, library)
    if expected.exists():
        return expected

    command_env = {str(key): str(value) for key, value in (env.items() if env is not None else os.environ.items())}
    command_env.update({
        "CI": "1",
        "NPM_CONFIG_IGNORE_SCRIPTS": "true",
        "NPM_CONFIG_UPDATE_NOTIFIER": "false",
        "NPM_CONFIG_FUND": "false",
        "NPM_CONFIG_USERCONFIG": os.devnull,
    })
    if npm_cache is not None:
        npm_cache = npm_cache.expanduser().resolve()
        npm_cache.mkdir(parents=True, exist_ok=True)
        command_env["npm_config_cache"] = str(npm_cache)

    try:
        process = subprocess.run(
            [
                "npm",
                "pack",
                f"{library.package}@{library.version}",
                "--ignore-scripts",
                "--json",
                "--pack-destination",
                str(destination),
                "--registry",
                "https://registry.npmjs.org",
            ],
            cwd=destination,
            capture_output=True,
            text=True,
            timeout=300,
            env=command_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FrontendDependencyError(f"could not download approved frontend library {library.name}: {exc}") from exc
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "npm pack failed").strip()
        raise FrontendDependencyError(f"could not download approved frontend library {library.name}: {detail[:500]}")
    try:
        payload = json.loads(process.stdout)
        filename = payload[0]["filename"] if isinstance(payload, list) and payload else ""
    except (TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise FrontendDependencyError(f"npm returned invalid metadata for {library.name}") from exc
    actual = (destination / str(filename)).resolve()
    if actual.parent != destination.resolve() or not actual.is_file() or actual.is_symlink():
        raise FrontendDependencyError(f"npm returned an unsafe archive for {library.name}")
    if actual != expected:
        raise FrontendDependencyError(f"npm archive name changed for {library.name}; expected {expected.name}")
    return actual


def _verify_and_extract(archive: Path, library: ApprovedFrontendLibrary) -> dict[str, bytes]:
    if archive.is_symlink() or not archive.is_file():
        raise FrontendDependencyError(f"approved frontend archive is not a regular file: {library.name}")
    if archive.stat().st_size > _MAX_ARCHIVE_BYTES:
        raise FrontendDependencyError(f"approved frontend archive is too large: {library.name}")
    data = archive.read_bytes()
    scheme, separator, expected_digest = library.integrity.partition("-")
    if scheme != "sha512" or not separator or not expected_digest:
        raise FrontendDependencyError(f"invalid integrity policy for {library.name}")
    actual_digest = base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")
    if not hmac.compare_digest(actual_digest, expected_digest):
        raise FrontendDependencyError(f"integrity check failed for frontend library {library.name}")

    extracted: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as package:
            for package_path, output_path in library.files:
                member_name = f"package/{package_path}"
                try:
                    member = package.getmember(member_name)
                except KeyError as exc:
                    raise FrontendDependencyError(f"approved file is missing from {library.name}: {package_path}") from exc
                if not member.isfile() or member.size > _MAX_RUNTIME_FILE_BYTES:
                    raise FrontendDependencyError(f"approved file is not a safe regular file: {package_path}")
                handle = package.extractfile(member)
                if handle is None:
                    raise FrontendDependencyError(f"could not read approved file: {package_path}")
                extracted[output_path] = handle.read()
    except (OSError, tarfile.TarError) as exc:
        raise FrontendDependencyError(f"could not inspect approved frontend library {library.name}") from exc
    return extracted


def materialize_frontend_libraries(
    config: Mapping[str, object],
    motion: Mapping[str, object] | None,
    destination: str | Path,
    *,
    npm_cache: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> FrontendLibraryResult:
    """Resolve configured approved libraries into host-provisioned local bytes.

    Libraries are only materialized for an enabled motion system and an explicit
    model request. The package allowlist and versions remain host-owned; config
    may enable a known library but cannot replace its package, version, integrity,
    or output paths.
    """
    motion = motion or {}
    if motion.get("enabled") is not True:
        return FrontendLibraryResult(files={})
    available = _enabled_libraries(config)
    requested = _requested_library_names(motion)
    required = required_frontend_library_names(config)
    requested = tuple(dict.fromkeys((*tuple(requested or ()), *required)))
    if not requested:
        return FrontendLibraryResult(files={})
    by_name = {library.name: library for library in available}
    unavailable = [name for name in requested if name not in by_name]
    if unavailable:
        raise FrontendDependencyError(
            "requested frontend library is not available: " + ", ".join(unavailable)
        )
    libraries = tuple(by_name[name] for name in requested)
    if not libraries:
        return FrontendLibraryResult(files={})

    raw_cache = Path(destination).expanduser()
    if raw_cache.is_symlink():
        raise FrontendDependencyError("frontend dependency cache cannot be a symlink")
    cache = raw_cache.resolve()
    files: dict[str, bytes] = {}
    receipts: list[dict[str, object]] = []
    for library in libraries:
        archive = _pack(library, cache, npm_cache=Path(npm_cache) if npm_cache is not None else None, env=env)
        runtime_files = _verify_and_extract(archive, library)
        overlap = set(files).intersection(runtime_files)
        if overlap:
            raise FrontendDependencyError(f"frontend library output collision: {sorted(overlap)[0]}")
        files.update(runtime_files)
        receipts.append({
            "name": library.name,
            "package": library.package,
            "version": library.version,
            "integrity": library.integrity,
            "files": sorted(runtime_files),
        })
    return FrontendLibraryResult(files=files, libraries=tuple(receipts))


__all__ = [
    "APPROVED_FRONTEND_LIBRARIES",
    "ApprovedFrontendLibrary",
    "FrontendDependencyError",
    "FrontendLibraryResult",
    "available_frontend_libraries",
    "materialize_frontend_libraries",
    "required_frontend_library_names",
]
