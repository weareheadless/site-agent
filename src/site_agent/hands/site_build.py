"""Explicit local build profiles for legacy static and Next/React sites."""

from __future__ import annotations

import os
import json
import hashlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any, Mapping


class SiteBuildError(RuntimeError):
    """A configured site build could not complete."""


@dataclass(frozen=True)
class SiteBuildProfile:
    name: str
    source_kind: str
    install_command: tuple[str, ...]
    check_commands: tuple[tuple[str, ...], ...]
    build_command: tuple[str, ...]
    output_dir: str
    route_manifest: str = ""
    writable_patterns: tuple[str, ...] = ()
    prohibited_paths: tuple[str, ...] = ()

    @property
    def check_command(self) -> tuple[str, ...]:
        """Compatibility view for callers that only support one check."""
        return self.check_commands[0] if self.check_commands else ()


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


@dataclass(frozen=True)
class SiteOutputArtifact:
    """A content-addressed copy of one authoritative site build output."""

    artifact_id: str
    tree_hash: str
    profile: str
    output_dir: str
    path: Path
    route_inventory: tuple[str, ...] = ()

    def to_dict(self, *, include_path: bool = False) -> dict[str, Any]:
        value = {
            "artifact_id": self.artifact_id,
            "tree_hash": self.tree_hash,
            "profile": self.profile,
            "output_dir": self.output_dir,
            "route_inventory": list(self.route_inventory),
        }
        if include_path:
            value["path"] = str(self.path)
        return value


class SiteOutputArtifactStore:
    """Persist immutable, content-addressed output trees for review.

    The store deliberately accepts only an already-built output directory. It
    never runs a site build, so validation and owner preview can share the exact
    bytes produced by the authoritative host build.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    @staticmethod
    def _tree_hash(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            if path.is_symlink():
                raise SiteBuildError("build output contains a symlink")
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _routes(root: Path) -> tuple[str, ...]:
        routes = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".html", ".htm"}
        ]
        return tuple(sorted(routes, key=lambda item: (item not in {"index.html", "index.htm"}, item)))

    def publish(
        self,
        output: str | Path,
        *,
        profile: SiteBuildProfile | str,
        candidate_sha: str = "",
    ) -> dict[str, Any]:
        source = Path(output).expanduser().resolve()
        if not source.is_dir():
            raise SiteBuildError(f"build output does not exist: {source}")
        build_profile = get_build_profile(profile) if isinstance(profile, str) else profile
        tree_hash = self._tree_hash(source)
        artifact_id = f"site-output-{tree_hash}"
        destination = (self.root / tree_hash).resolve()
        if destination == self.root or self.root not in destination.parents:
            raise SiteBuildError("output artifact escaped its store")
        with self._lock:
            if not destination.exists():
                temporary = self.root / f".staging-{tree_hash}-{os.getpid()}"
                shutil.rmtree(temporary, ignore_errors=True)
                try:
                    shutil.copytree(source, temporary)
                    os.replace(temporary, destination)
                except Exception:
                    shutil.rmtree(temporary, ignore_errors=True)
                    raise
        artifact = SiteOutputArtifact(
            artifact_id=artifact_id,
            tree_hash=tree_hash,
            profile=build_profile.name,
            output_dir=build_profile.output_dir,
            path=destination,
            route_inventory=self._routes(destination),
        )
        result = artifact.to_dict()
        if candidate_sha:
            result["candidate_sha"] = str(candidate_sha).strip().lower()
        return result

    def resolve(self, artifact_id: str) -> SiteOutputArtifact:
        value = str(artifact_id or "").strip()
        match = re.fullmatch(r"site-output-([0-9a-f]{64})", value)
        if not match:
            raise SiteBuildError("output artifact identity is invalid")
        tree_hash = match.group(1)
        path = (self.root / tree_hash).resolve()
        if path == self.root or self.root not in path.parents or not path.is_dir():
            raise SiteBuildError("output artifact is unavailable")
        if self._tree_hash(path) != tree_hash:
            raise SiteBuildError("output artifact contents changed")
        return SiteOutputArtifact(
            artifact_id=value,
            tree_hash=tree_hash,
            profile="",
            output_dir=".",
            path=path,
            route_inventory=self._routes(path),
        )


PELICAN_BASELINE_PROFILE = SiteBuildProfile(
    name="pelican_baseline",
    source_kind="pelican",
    install_command=(),
    check_commands=(),
    build_command=("bash", "build.sh"),
    output_dir="output",
    writable_patterns=("content/**", "themes/**", "pelicanconf.py", "build.sh"),
    prohibited_paths=(".env", ".github", "output"),
)

NEXT_REACT_PROFILE = SiteBuildProfile(
    name="next_react",
    source_kind="next_react_payload",
    # New source-authored workspaces intentionally start without a lockfile.
    # Direct dependencies are exact in the host-owned toolchain baseline and
    # npm is run without lifecycle scripts. Existing repositories with a
    # lockfile still receive npm's normal reproducible install behavior.
    install_command=("npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"),
    check_commands=(("npm", "run", "typecheck"), ("npm", "run", "lint")),
    build_command=("npm", "run", "build"),
    output_dir="out",
    route_manifest="design/ada-route-manifest.json",
    writable_patterns=(
        ".gitignore", "package.json", "package-lock.json",
        "next.config.mjs", "next.config.js", "next.config.ts", "next-env.d.ts", "tsconfig.json",
        "eslint.config.mjs",
        "payload.config.ts", "open-next.config.ts", "wrangler.jsonc",
        "src/**", "public/**", "design/**", "scripts/**", "test/**", "tests/**",
    ),
    prohibited_paths=(".env", ".github", "node_modules", ".next", ".open-next", "out"),
)

# The scaffold owns these build-time dependencies; generated design content does
# not. Keep the catalog exact so the dependency gate can verify the copied manifest.
NEXT_REACT_TOOLCHAIN_DEPENDENCIES: tuple[dict[str, str], ...] = (
    {"package": "@eslint/eslintrc", "version": "3.3.1"},
    {"package": "@gsap/react", "version": "2.1.2"},
    {"package": "@opennextjs/cloudflare", "version": "1.20.6"},
    {"package": "@payloadcms/db-d1-sqlite", "version": "3.88.0"},
    {"package": "@payloadcms/next", "version": "3.88.0"},
    {"package": "@payloadcms/richtext-lexical", "version": "3.88.0"},
    {"package": "@payloadcms/storage-r2", "version": "3.88.0"},
    {"package": "@payloadcms/translations", "version": "3.88.0"},
    {"package": "@payloadcms/ui", "version": "3.88.0"},
    {"package": "@types/node", "version": "22.19.9"},
    {"package": "@types/react", "version": "19.2.14"},
    {"package": "@types/react-dom", "version": "19.2.3"},
    {"package": "cross-env", "version": "7.0.3"},
    {"package": "dotenv", "version": "16.6.1"},
    {"package": "eslint", "version": "9.16.0"},
    {"package": "eslint-config-next", "version": "16.3.4"},
    {"package": "graphql", "version": "16.11.0"},
    {"package": "gsap", "version": "3.12.5"},
    {"package": "next", "version": "16.3.4"},
    {"package": "payload", "version": "3.88.0"},
    {"package": "prettier", "version": "3.6.2"},
    {"package": "react", "version": "19.2.6"},
    {"package": "react-dom", "version": "19.2.6"},
    {"package": "tsx", "version": "4.22.4"},
    {"package": "typescript", "version": "5.7.3"},
    {"package": "wrangler", "version": "4.130.0"},
)


_NEXT_RUNTIME_DEPENDENCIES = frozenset({
    "@gsap/react", "@opennextjs/cloudflare", "@payloadcms/db-d1-sqlite", "@payloadcms/next",
    "@payloadcms/richtext-lexical", "@payloadcms/storage-r2", "@payloadcms/translations",
    "@payloadcms/ui", "cross-env", "dotenv", "graphql", "gsap", "next", "payload", "react", "react-dom",
})


def _next_manifest(name: str) -> dict[str, Any]:
    runtime = {
        item["package"]: item["version"]
        for item in NEXT_REACT_TOOLCHAIN_DEPENDENCIES
        if item["package"] in _NEXT_RUNTIME_DEPENDENCIES
    }
    development = {
        item["package"]: item["version"]
        for item in NEXT_REACT_TOOLCHAIN_DEPENDENCIES
        if item["package"] not in runtime
    }
    return {
        "name": f"ada-{name.lower().replace(' ', '-')}-site" if name else "ada-site",
        "private": True,
        "type": "module",
        "scripts": {
            "typecheck": "tsc --noEmit",
            "lint": "eslint .",
            "build": "next build",
            "dev": "next dev",
            "start": "next start",
        },
        "dependencies": runtime,
        "devDependencies": development,
    }


def prepare_native_workspace(root: str | Path, profile: SiteBuildProfile) -> tuple[str, ...]:
    """Create only the host-owned technical baseline for a native workspace.

    Intake Lab can start from the legacy neutral scaffold, which intentionally
    has no framework source. Native Next authoring still needs an exact
    manifest and App Router entrypoint before the model can inspect or run the
    approved toolchain. These files are technical only; Ada owns the page,
    components, copy, imagery, fonts, and motion written afterward.
    """
    workspace = Path(root).expanduser().resolve()
    if profile.name != NEXT_REACT_PROFILE.name:
        return ()
    created: list[str] = []

    manifest_path = workspace / "package.json"
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps(_next_manifest("native-design"), indent=2) + "\n", encoding="utf-8")
        created.append("package.json")

    config_path = workspace / "next.config.mjs"
    if not config_path.exists():
        config_path.write_text(
            "/** @type {import('next').NextConfig} */\n"
            "const nextConfig = { output: 'export' };\n\n"
            "export default nextConfig;\n",
            encoding="utf-8",
        )
        created.append("next.config.mjs")

    tsconfig_path = workspace / "tsconfig.json"
    if not tsconfig_path.exists():
        tsconfig_path.write_text(
            json.dumps({
                "compilerOptions": {
                    "target": "ES2017",
                    "lib": ["dom", "dom.iterable", "esnext"],
                    "skipLibCheck": True,
                    "strict": True,
                    "noEmit": True,
                    "esModuleInterop": True,
                    "module": "esnext",
                    "moduleResolution": "bundler",
                    "resolveJsonModule": True,
                    "isolatedModules": True,
                    "jsx": "preserve",
                    "incremental": True,
                    "plugins": [{"name": "next"}],
                },
                "include": ["next-env.d.ts", ".next/types/**/*.ts", "src/**/*.ts", "src/**/*.tsx"],
                "exclude": ["node_modules"],
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        created.append("tsconfig.json")

    next_env_path = workspace / "next-env.d.ts"
    if not next_env_path.exists():
        next_env_path.write_text(
            "/// <reference types=\"next\" />\n"
            "/// <reference types=\"next/image-types/global\" />\n\n"
            "// NOTE: This file should not be edited\n",
            encoding="utf-8",
        )
        created.append("next-env.d.ts")

    eslint_path = workspace / "eslint.config.mjs"
    if not eslint_path.exists():
        eslint_path.write_text(
            "import { dirname } from 'node:path'\n"
            "import { fileURLToPath } from 'node:url'\n"
            "import { FlatCompat } from '@eslint/eslintrc'\n\n"
            "const __filename = fileURLToPath(import.meta.url)\n"
            "const __dirname = dirname(__filename)\n"
            "const compat = new FlatCompat({ baseDirectory: __dirname })\n\n"
            "export default [...compat.extends('next/core-web-vitals', 'next/typescript')]\n",
            encoding="utf-8",
        )
        created.append("eslint.config.mjs")

    layout_path = workspace / "src" / "app" / "layout.tsx"
    if not layout_path.exists():
        layout_path.parent.mkdir(parents=True, exist_ok=True)
        layout_path.write_text(
            "import type { ReactNode } from 'react'\n\n"
            "export default function RootLayout({ children }: { children: ReactNode }) {\n"
            "  return <html lang=\"en\"><body>{children}</body></html>\n"
            "}\n",
            encoding="utf-8",
        )
        created.append("src/app/layout.tsx")

    page_path = workspace / "src" / "app" / "page.tsx"
    if not page_path.exists():
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text("export default function HomePage() {\n  return null\n}\n", encoding="utf-8")
        created.append("src/app/page.tsx")

    payload_path = workspace / "payload.config.ts"
    if not payload_path.exists():
        payload_path.write_text(
            "import { buildConfig } from 'payload'\n\n"
            "export default buildConfig({\n"
            "  secret: process.env.PAYLOAD_SECRET || 'local-development-secret',\n"
            "  collections: [],\n"
            "})\n",
            encoding="utf-8",
        )
        created.append("payload.config.ts")

    gitignore_path = workspace / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text("node_modules/\n.next/\nout/\n.open-next/\n.opencode/tweak-map.json\n", encoding="utf-8")
        created.append(".gitignore")
    return tuple(created)

_EXACT_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

PROFILES = {profile.name: profile for profile in (PELICAN_BASELINE_PROFILE, NEXT_REACT_PROFILE)}


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


def _validate_next_manifest(root: Path, *, require_lockfile: bool = False) -> tuple[str, ...]:
    """Validate the native workspace's direct dependencies before npm runs."""
    manifest_path = root / "package.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise SiteBuildError("Next/React workspace is missing a regular package.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SiteBuildError(f"Next/React package.json is invalid: {exc}") from exc
    if not isinstance(manifest, Mapping):
        raise SiteBuildError("Next/React package.json must be an object")
    approved = {str(item["package"]): str(item["version"]) for item in NEXT_REACT_TOOLCHAIN_DEPENDENCIES}
    declared: dict[str, str] = {}
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        values = manifest.get(section) or {}
        if not isinstance(values, Mapping):
            raise SiteBuildError(f"Next/React package.json {section} must be an object")
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
            raise SiteBuildError("Next/React workspace is missing a regular package-lock.json")
        try:
            lock = json.loads(lockfile.read_text(encoding="utf-8"))
            packages = lock.get("packages") if isinstance(lock, Mapping) else None
        except (OSError, json.JSONDecodeError) as exc:
            raise SiteBuildError(f"Next/React package-lock.json is invalid: {exc}") from exc
        if not isinstance(packages, Mapping):
            raise SiteBuildError("Next/React package-lock.json has no packages map")
        for name, expected in declared.items():
            entry = packages.get(f"node_modules/{name}")
            locked = entry.get("version") if isinstance(entry, Mapping) else None
            if locked != expected:
                raise SiteBuildError(f"Next/React lockfile does not pin {name}@{expected}")
    return tuple(sorted(declared))


def _mount_options(path: Path) -> tuple[str, ...] | None:
    """Return the effective mount options for a path when Linux exposes them."""
    try:
        target = path.expanduser().resolve()
        best: tuple[str, tuple[str, ...]] | None = None
        for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
            parts = line.split(" ")
            if len(parts) < 4:
                continue
            mount_point = parts[1].replace("\\040", " ").replace("\\011", "\t")
            if str(target) != mount_point and not str(target).startswith(mount_point.rstrip("/") + "/"):
                continue
            options = tuple(item for item in parts[3].split(",") if item)
            if best is None or len(mount_point) > len(best[0]):
                best = (mount_point, options)
        return best[1] if best is not None else None
    except OSError:
        return None


def _is_noexec_mount(path: Path) -> bool:
    options = _mount_options(path)
    return bool(options is not None and "noexec" in options)


def _stage_executable_workspace(source: Path) -> Path:
    """Copy source to a short-lived executable mount for native toolchains.

    Design worktrees may live on a noexec mount.  Running npm there can appear
    to install successfully while omitting optional native packages such as
    Rollup's platform binary; the later build then fails with a misleading
    missing-module error.  The host owns this relocation so generated source
    does not need filesystem-specific launcher files.
    """
    for base_name in ("/var/tmp", "/dev/shm", tempfile.gettempdir()):
        base = Path(base_name)
        if _is_noexec_mount(base):
            continue
        try:
            staged = Path(tempfile.mkdtemp(prefix="site-agent-build-", dir=str(base)))
            shutil.copytree(
                source,
                staged,
                symlinks=True,
                dirs_exist_ok=True,
                ignore=lambda _path, names: {
                    name
                    for name in names
                    if name in {".git", ".opencode", ".agent-home", ".next", ".open-next", "out", "dist", "node_modules"}
                },
            )
            return staged
        except OSError:
            if "staged" in locals():
                shutil.rmtree(staged, ignore_errors=True)
    raise SiteBuildError("no executable staging mount is available for the native site build")


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
    staged_workspace: Path | None = None
    execution_root = workspace
    if _is_noexec_mount(workspace):
        staged_workspace = _stage_executable_workspace(workspace)
        execution_root = staged_workspace
    output = _safe_output(execution_root, profile.output_dir)
    if profile.name == NEXT_REACT_PROFILE.name:
        _validate_next_manifest(execution_root, require_lockfile=True)
    evidence: list[dict[str, Any]] = []
    commands = tuple(
        command
        for command in (profile.install_command, *profile.check_commands, profile.build_command)
        if command
    )
    command_env = _command_env(Path(npm_cache) if npm_cache is not None else None, env)
    try:
        for command in commands:
            try:
                result = subprocess.run(
                    list(command),
                    cwd=execution_root,
                    capture_output=True,
                    text=True,
                    timeout=max(1, min(int(timeout_seconds), 1800)),
                    env=command_env,
                )
            except subprocess.TimeoutExpired as exc:
                evidence.append({"command": list(command), "status": "timeout", "stdout": str(exc.stdout or "")[-10_000:], "stderr": str(exc.stderr or "")[-10_000:]})
                return SiteBuildResult(profile.name, False, profile.output_dir, tuple(evidence), route_inventory(execution_root, profile.output_dir))
            except OSError as exc:
                evidence.append({"command": list(command), "status": "error", "error": str(exc)[:500]})
                return SiteBuildResult(profile.name, False, profile.output_dir, tuple(evidence), route_inventory(execution_root, profile.output_dir))
            item = {
                "command": list(command),
                "status": "passed" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
                "stdout": result.stdout[-10_000:],
                "stderr": result.stderr[-10_000:],
            }
            evidence.append(item)
            if result.returncode != 0:
                return SiteBuildResult(profile.name, False, profile.output_dir, tuple(evidence), route_inventory(execution_root, profile.output_dir))
        if not output.is_dir():
            evidence.append({"command": [], "status": "failed", "error": f"missing build output: {profile.output_dir}"})
            return SiteBuildResult(profile.name, False, profile.output_dir, tuple(evidence), ())
        if staged_workspace is not None:
            retained_output = _safe_output(workspace, profile.output_dir)
            shutil.rmtree(retained_output, ignore_errors=True)
            shutil.copytree(output, retained_output, symlinks=True)
        return SiteBuildResult(profile.name, True, profile.output_dir, tuple(evidence), route_inventory(workspace, profile.output_dir))
    finally:
        if staged_workspace is not None:
            shutil.rmtree(staged_workspace, ignore_errors=True)


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
    model needs Next, React, Payload, and GSAP available while it implements and
    renders the site, but installation must remain a host operation. The
    package manifest is the only input; no shell command is read from it.
    """
    workspace = Path(root).expanduser().resolve()
    if profile.name != NEXT_REACT_PROFILE.name or not (workspace / "package.json").is_file():
        return ()
    if (workspace / "package.json").is_symlink():
        raise SiteBuildError("package.json must be a regular file")
    _validate_next_manifest(workspace)
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
    _validate_next_manifest(workspace, require_lockfile=True)
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
    "NEXT_REACT_PROFILE",
    "NEXT_REACT_TOOLCHAIN_DEPENDENCIES",
    "PELICAN_BASELINE_PROFILE",
    "PROFILES",
    "SiteBuildError",
    "SiteBuildProfile",
    "SiteBuildResult",
    "SiteOutputArtifact",
    "SiteOutputArtifactStore",
    "build_site",
    "copy_build_output",
    "get_build_profile",
    "prepare_native_workspace",
    "prepare_site_toolchain",
    "route_inventory",
]
