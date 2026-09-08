"""Explicit local build profiles for baseline and Astro/React sites."""

from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


class SiteBuildError(RuntimeError):
    """A configured site build could not complete."""


@dataclass(frozen=True)
class SiteBuildProfile:
    name: str
    source_kind: str
    install_command: tuple[str, ...]
    check_command: tuple[str, ...]
    build_command: tuple[str, ...]
    output_dir: str
    route_manifest: str = ""
    writable_patterns: tuple[str, ...] = ()
    prohibited_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class SiteBuildResult:
    profile: str
    ok: bool
    output_dir: str
    commands: tuple[dict[str, Any], ...]
    route_inventory: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "ok": self.ok,
            "output_dir": self.output_dir,
            "commands": [dict(item) for item in self.commands],
            "route_inventory": list(self.route_inventory),
        }


PELICAN_BASELINE_PROFILE = SiteBuildProfile(
    name="pelican_baseline",
    source_kind="pelican",
    install_command=(),
    check_command=(),
    build_command=("bash", "build.sh"),
    output_dir="output",
    writable_patterns=("content/**", "themes/**", "pelicanconf.py", "build.sh"),
    prohibited_paths=(".env", ".github", "output"),
)

ASTRO_REACT_PROFILE = SiteBuildProfile(
    name="astro_react",
    source_kind="astro_react",
    # New source-authored workspaces intentionally start without a lockfile.
    # Direct dependencies are exact in the host-owned toolchain baseline and
    # npm is run without scripts/networked application code. Existing
    # repositories with a lockfile still receive npm's normal reproducible
    # install behavior.
    install_command=("npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"),
    check_command=("npm", "run", "check"),
    build_command=("npm", "run", "build"),
    output_dir="dist",
    route_manifest="design/ada-route-manifest.json",
    writable_patterns=(".gitignore", "package.json", "package-lock.json", "astro.config.mjs", "tsconfig.json", "src/**", "public/**", "design/**", "test/**"),
    prohibited_paths=(".env", ".github", "node_modules", "dist"),
)

# The scaffold owns these build-time dependencies; generated design content does
# not. Keep the catalog exact so the dependency gate can verify the copied manifest.
ASTRO_REACT_TOOLCHAIN_DEPENDENCIES: tuple[dict[str, str], ...] = (
    {"package": "@astrojs/check", "version": "0.9.10"},
    {"package": "@astrojs/react", "version": "4.4.2"},
    {"package": "@gsap/react", "version": "2.1.2"},
    {"package": "@types/node", "version": "22.20.1"},
    {"package": "@types/react", "version": "19.2.18"},
    {"package": "@types/react-dom", "version": "19.2.5"},
    {"package": "gsap", "version": "3.12.5"},
    {"package": "astro", "version": "5.18.2"},
    {"package": "react", "version": "19.2.8"},
    {"package": "react-dom", "version": "19.2.8"},
    {"package": "typescript", "version": "5.9.3"},
)


def prepare_native_workspace(root: str | Path, profile: SiteBuildProfile) -> tuple[str, ...]:
    """Create only the host-owned technical baseline for a native workspace.

    Intake Lab can start from the legacy neutral scaffold, which intentionally
    has no framework source.  Native Astro authoring still needs an exact
    manifest and framework entrypoint before the model can inspect or run the
    approved toolchain.  These files contain no visual scaffold; the model owns
    every page, component, style, and interaction written afterward.
    """
    workspace = Path(root).expanduser().resolve()
    if profile.name != ASTRO_REACT_PROFILE.name:
        return ()
    created: list[str] = []

    manifest_path = workspace / "package.json"
    if not manifest_path.exists():
        runtime = {
            item["package"]: item["version"]
            for item in ASTRO_REACT_TOOLCHAIN_DEPENDENCIES
            if item["package"] in {"@astrojs/react", "@gsap/react", "astro", "gsap", "react", "react-dom"}
        }
        development = {
            item["package"]: item["version"]
            for item in ASTRO_REACT_TOOLCHAIN_DEPENDENCIES
            if item["package"] not in runtime
        }
        manifest_path.write_text(
            json.dumps({
                "name": "ada-native-design",
                "private": True,
                "type": "module",
                "scripts": {
                    "check": "astro check",
                    "build": "astro build",
                    "dev": "astro dev",
                    "preview": "astro preview",
                },
                "dependencies": runtime,
                "devDependencies": development,
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        created.append("package.json")

    config_path = workspace / "astro.config.mjs"
    if not config_path.exists():
        config_path.write_text(
            "import { defineConfig } from 'astro/config';\n"
            "import react from '@astrojs/react';\n\n"
            "export default defineConfig({ integrations: [react()] });\n",
            encoding="utf-8",
        )
        created.append("astro.config.mjs")

    tsconfig_path = workspace / "tsconfig.json"
    if not tsconfig_path.exists():
        tsconfig_path.write_text(
            json.dumps({
                "extends": "astro/tsconfigs/strict",
                "compilerOptions": {
                    "allowJs": True,
                    "checkJs": True,
                    "jsx": "react-jsx",
                    "jsxImportSource": "react",
                },
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        created.append("tsconfig.json")

    gitignore_path = workspace / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text("node_modules/\ndist/\n.astro/\n.opencode/tweak-map.json\n", encoding="utf-8")
        created.append(".gitignore")
    return tuple(created)

_EXACT_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

PROFILES = {profile.name: profile for profile in (PELICAN_BASELINE_PROFILE, ASTRO_REACT_PROFILE)}


def get_build_profile(name: str) -> SiteBuildProfile:
    key = str(name or "").strip().lower()
    try:
        return PROFILES[key]
    except KeyError as exc:
        raise SiteBuildError(f"unknown site build profile: {name}") from exc


def _safe_output(root: Path, output_dir: str) -> Path:
    relative = PurePosixPath(str(output_dir).replace("\\", "/"))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise SiteBuildError("build output directory is unsafe")
    output = (root / relative).resolve()
    if output != root.resolve() and root.resolve() not in output.parents:
        raise SiteBuildError("build output directory escapes workspace")
    return output


def route_inventory(root: str | Path, output_dir: str) -> tuple[str, ...]:
    workspace = Path(root).expanduser().resolve()
    output = _safe_output(workspace, output_dir)
    if not output.is_dir():
        return ()
    routes = [
        str(path.relative_to(output)).replace("\\", "/")
        for path in output.rglob("*")
        if path.is_file() and path.suffix.lower() in {".html", ".htm"}
    ]
    return tuple(sorted(routes, key=lambda item: (item not in {"index.html", "index.htm"}, item)))


def _command_env(npm_cache: Path | None, env: Mapping[str, str] | None) -> dict[str, str]:
    result = {str(key): str(value) for key, value in (env.items() if env is not None else os.environ.items())}
    # The build profile is local-only and must not inherit npm's user-global
    # configuration or scripts from an unrelated customer environment.
    result["CI"] = "1"
    result["NPM_CONFIG_UPDATE_NOTIFIER"] = "false"
    result["NPM_CONFIG_FUND"] = "false"
    if npm_cache is not None:
        cache = Path(npm_cache).expanduser().resolve()
        cache.mkdir(parents=True, exist_ok=True)
        result["npm_config_cache"] = str(cache)
    return result


def _validate_astro_manifest(root: Path, *, require_lockfile: bool = False) -> tuple[str, ...]:
    """Validate the native workspace's direct dependencies before npm runs."""
    manifest_path = root / "package.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise SiteBuildError("Astro/React workspace is missing a regular package.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SiteBuildError(f"Astro/React package.json is invalid: {exc}") from exc
    if not isinstance(manifest, Mapping):
        raise SiteBuildError("Astro/React package.json must be an object")
    approved = {str(item["package"]): str(item["version"]) for item in ASTRO_REACT_TOOLCHAIN_DEPENDENCIES}
    declared: dict[str, str] = {}
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        values = manifest.get(section) or {}
        if not isinstance(values, Mapping):
            raise SiteBuildError(f"Astro/React package.json {section} must be an object")
        for name, version in values.items():
            name = str(name).strip()
            version = str(version).strip()
            expected = approved.get(name)
            if expected is None:
                raise SiteBuildError(f"native dependency is not host-approved: {name}")
            if version != expected or not _EXACT_VERSION_RE.fullmatch(version):
                raise SiteBuildError(f"native dependency must use the approved exact version: {name}@{expected}")
            declared[name] = version
    if require_lockfile:
        lockfile = root / "package-lock.json"
        if not lockfile.is_file() or lockfile.is_symlink():
            raise SiteBuildError("Astro/React workspace is missing a regular package-lock.json")
        try:
            lock = json.loads(lockfile.read_text(encoding="utf-8"))
            packages = lock.get("packages") if isinstance(lock, Mapping) else None
        except (OSError, json.JSONDecodeError) as exc:
            raise SiteBuildError(f"Astro/React package-lock.json is invalid: {exc}") from exc
        if not isinstance(packages, Mapping):
            raise SiteBuildError("Astro/React package-lock.json has no packages map")
        for name, expected in declared.items():
            entry = packages.get(f"node_modules/{name}")
            locked = entry.get("version") if isinstance(entry, Mapping) else None
            if locked != expected:
                raise SiteBuildError(f"Astro/React lockfile does not pin {name}@{expected}")
    return tuple(sorted(declared))


def build_site(
    root: str | Path,
    profile: SiteBuildProfile,
    *,
    npm_cache: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int = 900,
) -> SiteBuildResult:
    """Run one explicit profile without invoking a shell command from config."""
    workspace = Path(root).expanduser().resolve()
    if not workspace.is_dir():
        raise SiteBuildError(f"build workspace does not exist: {workspace}")
    output = _safe_output(workspace, profile.output_dir)
    if profile.name == ASTRO_REACT_PROFILE.name:
        _validate_astro_manifest(workspace, require_lockfile=True)
    evidence: list[dict[str, Any]] = []
    commands = tuple(command for command in (profile.install_command, profile.check_command, profile.build_command) if command)
    command_env = _command_env(Path(npm_cache) if npm_cache is not None else None, env)
    for command in commands:
        try:
            result = subprocess.run(
                list(command),
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=max(1, min(int(timeout_seconds), 1800)),
                env=command_env,
            )
        except subprocess.TimeoutExpired as exc:
            evidence.append({"command": list(command), "status": "timeout", "stdout": str(exc.stdout or "")[-10_000:], "stderr": str(exc.stderr or "")[-10_000:]})
            return SiteBuildResult(profile.name, False, profile.output_dir, tuple(evidence), route_inventory(workspace, profile.output_dir))
        except OSError as exc:
            evidence.append({"command": list(command), "status": "error", "error": str(exc)[:500]})
            return SiteBuildResult(profile.name, False, profile.output_dir, tuple(evidence), route_inventory(workspace, profile.output_dir))
        item = {
            "command": list(command),
            "status": "passed" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "stdout": result.stdout[-10_000:],
            "stderr": result.stderr[-10_000:],
        }
        evidence.append(item)
        if result.returncode != 0:
            return SiteBuildResult(profile.name, False, profile.output_dir, tuple(evidence), route_inventory(workspace, profile.output_dir))
    if not output.is_dir():
        evidence.append({"command": [], "status": "failed", "error": f"missing build output: {profile.output_dir}"})
        return SiteBuildResult(profile.name, False, profile.output_dir, tuple(evidence), ())
    return SiteBuildResult(profile.name, True, profile.output_dir, tuple(evidence), route_inventory(workspace, profile.output_dir))


def prepare_site_toolchain(
    root: str | Path,
    profile: SiteBuildProfile,
    *,
    npm_cache: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int = 900,
) -> tuple[str, ...]:
    """Install the host-approved toolchain before the coding model runs.

    This is deliberately separate from ``build_site``: a source-authoring
    model needs Astro, React, and GSAP available while it implements and
    renders the site, but installation must remain a host operation. The
    package manifest is the only input; no shell command is read from it.
    """
    workspace = Path(root).expanduser().resolve()
    if profile.name != ASTRO_REACT_PROFILE.name or not (workspace / "package.json").is_file():
        return ()
    if (workspace / "package.json").is_symlink():
        raise SiteBuildError("package.json must be a regular file")
    _validate_astro_manifest(workspace)
    command_env = _command_env(Path(npm_cache) if npm_cache is not None else None, env)
    command = list(profile.install_command)
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=max(1, min(int(timeout_seconds), 1800)),
            env=command_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SiteBuildError(f"frontend toolchain preparation failed: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "toolchain installation failed").strip()
        raise SiteBuildError(detail[:1_000])
    _validate_astro_manifest(workspace, require_lockfile=True)
    provisioned = []
    lockfile = workspace / "package-lock.json"
    if lockfile.is_file() and not lockfile.is_symlink():
        provisioned.append("package-lock.json")
    return tuple(provisioned)


def copy_build_output(root: str | Path, profile: SiteBuildProfile, destination: str | Path) -> Path:
    """Copy an already-built public directory into the retained lab artifacts."""
    workspace = Path(root).expanduser().resolve()
    source = _safe_output(workspace, profile.output_dir)
    if not source.is_dir():
        raise SiteBuildError(f"missing build output: {profile.output_dir}")
    target = Path(destination).expanduser().resolve()
    if target == workspace or workspace in target.parents:
        raise SiteBuildError("retained artifact directory must not be inside the build workspace")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


__all__ = [
    "ASTRO_REACT_PROFILE",
    "PELICAN_BASELINE_PROFILE",
    "PROFILES",
    "SiteBuildError",
    "SiteBuildProfile",
    "SiteBuildResult",
    "build_site",
    "copy_build_output",
    "get_build_profile",
    "prepare_native_workspace",
    "prepare_site_toolchain",
    "route_inventory",
]
