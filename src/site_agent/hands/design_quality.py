"""Host-owned deterministic checks for reviewable design candidates."""

from __future__ import annotations

import html
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from fnmatch import fnmatch
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

from ..core.contracts import safe_provider_message
from ..core.design_contracts import DesignManifest, QualityReport, safe_relative_path
from .repo_changes import HARD_DENY, normalize_path, writable


_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:OPENAI|ANTHROPIC|GOOGLE|AWS|GITHUB|CLOUDFLARE)_[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)\s*[:=]", re.I),
    re.compile(r"\b(?:sk|gh[ps]_[A-Za-z0-9_]+)-[A-Za-z0-9_-]{8,}"),
)
_PLACEHOLDER_RE = re.compile(r"\b(?:lorem ipsum|todo|tbd|coming soon|placeholder|your company name)\b", re.I)
_CONTACT_HOSTS = frozenset({
    "acuityscheduling.com",
    "booksy.com",
    "booking.com",
    "calendly.com",
    "facebook.com",
    "instagram.com",
    "linktr.ee",
    "mindbodyonline.com",
    "tiktok.com",
    "twitter.com",
    "wa.me",
    "whatsapp.com",
    "x.com",
    "youtube.com",
})


def _looks_like_source_path(value: str) -> bool:
    """Ignore descriptive manifest metadata when checking declared paths."""
    value = str(value or "").strip().replace("\\", "/")
    if not value or any(character.isspace() for character in value) or ":" in value:
        return False
    name = PurePosixPath(value).name
    return "/" in value or bool(PurePosixPath(name).suffix) or name in {"Dockerfile", "Makefile", "LICENSE", "README"}


@dataclass(frozen=True)
class QualityPolicy:
    output_dir: str = "output"
    required_pages: tuple[str, ...] = ()
    required_content: tuple[str, ...] = ()
    allowed_patterns: tuple[str, ...] = ()
    prohibited_paths: tuple[str, ...] = ()
    build_command: tuple[str, ...] | str | None = ("bash", "build.sh")
    build_timeout_seconds: int = 120
    browser_required: bool = False
    visual_critic: bool = False
    manifest_path: str = ""
    expected_intake_hash: str = ""
    allowed_hard_denied_paths: tuple[str, ...] = ()
    ignored_pages: tuple[str, ...] = ()
    approved_capabilities: tuple[dict[str, Any], ...] = ()
    viewports: tuple[dict[str, int], ...] = (
        {"name": "desktop", "width": 1440, "height": 1000},
        {"name": "tablet", "width": 768, "height": 1024},
        {"name": "mobile", "width": 390, "height": 844},
    )
    contact_destination_unavailable: bool = False
    native_source_required: bool = False
    originality_required: bool = False
    internal_scaffold_fingerprints: tuple[str, ...] = ()
    required_font_families: tuple[str, ...] = ()
    approved_font_files: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any] | None = None,
        *,
        required_pages=(),
        required_content=(),
        expected_intake_hash: str = "",
        approved_capabilities=(),
    ) -> "QualityPolicy":
        """Build host-owned gates from instance configuration, not site assumptions."""
        config = config or {}
        engine = config.get("design_engine") or {}
        quality = engine.get("quality") or {}
        if not isinstance(quality, Mapping):
            raise ValueError("design_engine.quality must be an object")
        site = config.get("site") or {}
        blog = config.get("blog") or {}
        command = quality.get("build_command", blog.get("build_command", cls.build_command))
        if isinstance(command, (list, tuple)):
            command = tuple(str(item) for item in command)
        elif command is not None and not isinstance(command, str):
            raise ValueError("design_engine.quality.build_command must be text, a list, or null")
        raw_viewports = engine.get("required_viewports", quality.get("viewports", cls.viewports))
        viewports: list[dict[str, int]] = []
        for index, viewport in enumerate(raw_viewports or ()):
            if not isinstance(viewport, Mapping):
                raise ValueError(f"design_engine.required_viewports[{index}] must be an object")
            try:
                width = int(viewport["width"])
                height = int(viewport["height"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"design_engine.required_viewports[{index}] must include width and height") from exc
            if width < 1 or height < 1:
                raise ValueError(f"design_engine.required_viewports[{index}] dimensions must be positive")
            viewports.append({"name": str(viewport.get("name") or f"viewport-{index}"), "width": width, "height": height})
        pages = quality.get("required_pages", required_pages)
        if isinstance(pages, str):
            pages = (pages,)
        if not isinstance(pages, (list, tuple)):
            raise ValueError("design_engine.quality.required_pages must be a list")
        content = quality.get("required_content", required_content)
        if isinstance(content, str):
            content = (content,)
        if not isinstance(content, (list, tuple)):
            raise ValueError("design_engine.quality.required_content must be a list")
        capabilities = approved_capabilities or engine.get("capabilities") or ()
        if isinstance(capabilities, Mapping):
            capabilities = [
                {"name": key, **(value if isinstance(value, Mapping) else {"value": value})}
                for key, value in capabilities.items()
            ]
        if not capabilities and engine.get("libraries"):
            try:
                from .frontend_dependencies import available_frontend_libraries

                capabilities = available_frontend_libraries(config)
            except Exception:  # noqa: BLE001 - invalid optional capability data is handled by the gate
                capabilities = ()
        return cls(
            output_dir=str(quality.get("output_dir") or "output"),
            required_pages=tuple(str(item) for item in pages if str(item).strip()),
            required_content=tuple(str(item) for item in content if str(item).strip()),
            allowed_patterns=tuple(str(item) for item in (quality.get("allowed_patterns") or site.get("writable_patterns") or ())),
            prohibited_paths=tuple(str(item) for item in (quality.get("prohibited_paths") or ())),
            build_command=command,
            build_timeout_seconds=int(quality.get("build_timeout_seconds", cls.build_timeout_seconds)),
            browser_required=bool(quality.get("browser", quality.get("browser_required", False))),
            visual_critic=bool(quality.get("visual_critic", False)),
            manifest_path=str(engine.get("manifest_path") or quality.get("manifest_path") or ""),
            allowed_hard_denied_paths=tuple(str(item) for item in (quality.get("allowed_hard_denied_paths") or ())),
            expected_intake_hash=expected_intake_hash,
            ignored_pages=tuple(str(item) for item in (quality.get("ignored_pages") or ())),
            approved_capabilities=tuple(
                dict(item) for item in capabilities if isinstance(item, Mapping)
            ),
            viewports=tuple(viewports),
            contact_destination_unavailable=bool(quality.get("contact_destination_unavailable", False)),
            native_source_required=bool(quality.get("native_source_required", engine.get("native_source_required", False))),
            originality_required=bool(quality.get("originality_required", engine.get("originality_required", False))),
            internal_scaffold_fingerprints=tuple(
                str(item).strip().lower()
                for item in (quality.get("internal_scaffold_fingerprints") or ())
                if str(item).strip()
            ),
            required_font_families=tuple(
                str(item).strip()
                for item in (quality.get("required_font_families") or quality.get("required_fonts") or ())
                if str(item).strip()
            ),
            approved_font_files=tuple(
                dict(item)
                for item in (quality.get("approved_font_files") or quality.get("approved_fonts") or ())
                if isinstance(item, Mapping)
            ),
        )


class BrowserQualityAdapter(Protocol):
    def inspect(self, output_dir: Path, viewport: Mapping[str, int]) -> Mapping[str, Any]:
        ...


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.lang = ""
        self.viewport = ""
        self.h1_count = 0
        self.links: list[str] = []
        self.images: list[dict[str, str]] = []
        self.author_style_count = 0
        self._in_title = False
        self._text: list[str] = []
        self._visible_text: list[str] = []
        self._hidden_elements: list[tuple[str, bool]] = []

    @property
    def _inside_hidden_element(self) -> bool:
        return any(hidden for _, hidden in self._hidden_elements)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        hidden = self._inside_hidden_element or values.get("aria-hidden", "").lower() == "true"
        if name == "html":
            self.lang = values.get("lang", "").strip()
        elif name == "title":
            self._in_title = True
        elif name == "meta":
            meta_name = values.get("name", "").lower()
            if meta_name == "description":
                self.description = values.get("content", "").strip()
            elif meta_name == "viewport":
                self.viewport = values.get("content", "").strip()
        elif name == "h1":
            self.h1_count += 1
        elif name == "a":
            if values.get("href"):
                self.links.append(values["href"])
        elif name == "img":
            self.images.append({
                "src": values.get("src", ""),
                "alt": values.get("alt", ""),
                "has_alt": "true" if "alt" in values else "false",
                "decorative": "true" if hidden or values.get("role", "").lower() in {"presentation", "none"} else "false",
            })
        elif name == "link" and "stylesheet" in values.get("rel", "").lower().split():
            self.author_style_count += 1
        elif name == "style":
            self.author_style_count += 1
        if name not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self._hidden_elements.append((name, values.get("aria-hidden", "").lower() == "true"))

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "title":
            self._in_title = False
        for index in range(len(self._hidden_elements) - 1, -1, -1):
            if self._hidden_elements[index][0] == name:
                del self._hidden_elements[index:]
                break

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        self._text.append(data)
        if not self._inside_hidden_element:
            self._visible_text.append(data)

    @property
    def text(self) -> str:
        return html.unescape(" ".join(self._text))

    @property
    def visible_text(self) -> str:
        return html.unescape(" ".join(self._visible_text))


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300] or "git command failed")
    return proc.stdout


def _changed_paths(repo: Path, base_sha: str, candidate_sha: str) -> set[str]:
    paths: set[str] = set()
    if base_sha != candidate_sha:
        try:
            paths.update(path for path in _git(repo, "diff", "--name-only", "-z", f"{base_sha}...{candidate_sha}").split("\0") if path)
        except RuntimeError:
            pass
    try:
        paths.update(path for path in _git(repo, "diff", "--name-only", "-z", "HEAD").split("\0") if path)
        paths.update(path for path in _git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0") if path)
    except RuntimeError:
        pass
    return paths


def _finding(gate: str, severity: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"gate": gate, "severity": severity, "code": code, "message": message, **extra}


def _host_provisioned_paths(repo: Path, policy: QualityPolicy) -> set[str]:
    """Return regular files the host recorded as provisioned runtime assets.

    The native build deliberately commits host-provisioned runtime files so an
    immutable candidate can be checked from Git.  They are not model-authored
    source, though, and therefore must not be rejected by the source allowlist.
    Read only the host-generated manifest metadata and still require every
    declared path to resolve to a regular file inside the checked worktree.
    """
    if not policy.manifest_path:
        return set()
    try:
        manifest_path = safe_relative_path(policy.manifest_path, "manifest_path")
        raw_manifest = json.loads((repo / manifest_path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - the manifest gate reports malformed metadata
        return set()
    if not isinstance(raw_manifest, Mapping) or raw_manifest.get("host_generated") is not True:
        return set()
    metadata = raw_manifest.get("host_metadata")
    if not isinstance(metadata, Mapping):
        return set()
    raw_paths = metadata.get("provisioned_runtime_paths") or []
    if not isinstance(raw_paths, (list, tuple)):
        return set()
    root = repo.resolve()
    provisioned: set[str] = set()
    for raw_path in raw_paths:
        try:
            relative = safe_relative_path(raw_path, "host_metadata.provisioned_runtime_paths")
        except Exception:
            continue
        target = repo / relative
        try:
            resolved = target.resolve()
        except OSError:
            continue
        if target.is_symlink() or not target.is_file() or (resolved != root and root not in resolved.parents):
            continue
        provisioned.add(normalize_path(relative))
    return {path for path in provisioned if path}


def _repository_findings(repo: Path, base_sha: str, candidate_sha: str, policy: QualityPolicy) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        changed = _changed_paths(repo, base_sha, candidate_sha)
    except Exception as exc:  # noqa: BLE001
        return [_finding("repository", "blocker", "git_error", safe_provider_message(str(exc)))]
    patterns = list(policy.allowed_patterns)
    allowed_hard_denied = set(policy.allowed_hard_denied_paths)
    host_manifest = normalize_path(policy.manifest_path) if policy.manifest_path else ""
    host_provisioned_paths = _host_provisioned_paths(repo, policy)
    for path in sorted(changed):
        clean = normalize_path(path)
        hard_denied = any(denied in clean and clean not in allowed_hard_denied for denied in HARD_DENY)
        host_metadata = bool(host_manifest and clean == host_manifest and not hard_denied)
        allowlisted = (
            host_metadata
            or (clean in host_provisioned_paths and not hard_denied)
            or (writable(clean, patterns, allowed_hard_denied_paths=allowed_hard_denied) if patterns else clean in allowed_hard_denied)
        )
        if not clean or hard_denied or any(
            clean == prohibited or clean.startswith(prohibited.rstrip("/") + "/")
            for prohibited in policy.prohibited_paths
        ) or (patterns and not allowlisted):
            findings.append(_finding("repository", "blocker", "path_policy", f"Changed path is outside the design allowlist: {path}", path=path))
        raw_target = (repo / clean) if clean else repo
        target = raw_target.resolve() if clean else repo.resolve()
        if clean and (target != repo.resolve() and repo.resolve() not in target.parents):
            findings.append(_finding("repository", "blocker", "path_escape", f"Changed path escapes the worktree: {path}", path=path))
        if clean and raw_target.is_symlink():
            findings.append(_finding("repository", "blocker", "path_escape", f"Changed path is a symlink: {path}", path=path))
        if clean and target.is_file() and target.stat().st_size <= 1_000_000:
            try:
                content = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
            if any(pattern.search(content) for pattern in _SECRET_PATTERNS):
                findings.append(_finding("repository", "blocker", "secret", f"Credential-like content was found in {path}.", path=path))
    return findings


def _show_text(repo: Path, ref: str, path: str) -> str:
    if not ref:
        return ""
    try:
        return _git(repo, "show", f"{ref}:{path}")
    except RuntimeError:
        return ""


def _package_dependencies(value: Mapping[str, Any]) -> dict[str, str]:
    dependencies: dict[str, str] = {}
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        raw = value.get(section) or {}
        if not isinstance(raw, Mapping):
            continue
        for name, version in raw.items():
            if isinstance(name, str) and isinstance(version, str):
                dependencies[name.strip()] = version.strip()
    return dependencies


def _approved_capability_map(policy: QualityPolicy) -> dict[str, str]:
    approved: dict[str, str] = {}
    for item in policy.approved_capabilities:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("package") or item.get("name") or "").strip()
        version = str(item.get("version") or "").strip()
        if name and version:
            approved[name] = version
    return approved


def _dependency_findings(repo: Path, base_sha: str, candidate_sha: str, policy: QualityPolicy) -> list[dict[str, Any]]:
    """Reject package additions unless the host has approved and pinned them."""
    changed = _changed_paths(repo, base_sha, candidate_sha)
    manifests = sorted(path for path in changed if Path(path).name == "package.json")
    if not manifests:
        return []
    approved = _approved_capability_map(policy)
    findings: list[dict[str, Any]] = []
    lock_names = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb"}
    changed_locks = {path for path in changed if Path(path).name in lock_names}
    for manifest_path in manifests:
        candidate_path = repo / manifest_path
        try:
            candidate_data = json.loads(candidate_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            findings.append(_finding(
                "dependencies", "blocker", "invalid_package_manifest",
                f"The changed package manifest is invalid: {manifest_path} ({type(exc).__name__}).",
                path=manifest_path,
            ))
            continue
        if not isinstance(candidate_data, Mapping):
            findings.append(_finding(
                "dependencies", "blocker", "invalid_package_manifest",
                f"The changed package manifest is not an object: {manifest_path}.", path=manifest_path,
            ))
            continue
        base_raw = _show_text(repo, base_sha, manifest_path)
        try:
            base_data = json.loads(base_raw) if base_raw else {}
        except json.JSONDecodeError:
            base_data = {}
        base_dependencies = _package_dependencies(base_data) if isinstance(base_data, Mapping) else {}
        candidate_dependencies = _package_dependencies(candidate_data)
        added_or_changed = {
            name: version for name, version in candidate_dependencies.items()
            if base_dependencies.get(name) != version
        }
        if not added_or_changed:
            continue
        if not changed_locks:
            findings.append(_finding(
                "dependencies", "blocker", "lockfile_missing",
                "Dependency changes must include a lockfile change.", path=manifest_path,
            ))
        for name, requested in sorted(added_or_changed.items()):
            expected = approved.get(name)
            if expected is None:
                findings.append(_finding(
                    "dependencies", "blocker", "dependency_not_approved",
                    f"Dependency {name} is not in the host-approved capability catalog.",
                    package=name, requested=requested,
                ))
                continue
            if requested != expected or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", requested):
                findings.append(_finding(
                    "dependencies", "blocker", "dependency_not_pinned",
                    f"Dependency {name} must use the approved exact version {expected}.",
                    package=name, requested=requested, approved=expected,
                ))
                continue
            lock_path = next((path for path in sorted(changed_locks) if Path(path).name == "package-lock.json"), "")
            if lock_path:
                try:
                    lock_data = json.loads((repo / lock_path).read_text(encoding="utf-8"))
                    locked = ((lock_data.get("packages") or {}).get(f"node_modules/{name}") or {}).get("version")
                except (OSError, json.JSONDecodeError, AttributeError):
                    locked = None
                if locked != expected:
                    findings.append(_finding(
                        "dependencies", "blocker", "lockfile_mismatch",
                        f"Lockfile does not pin {name} to the approved version {expected}.",
                        package=name, locked=locked, approved=expected,
                    ))
    return findings


_NATIVE_SOURCE_SUFFIXES = frozenset({
    ".astro", ".css", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".html", ".htm",
})
_IMPORT_RE = re.compile(
    r"(?:\bimport\s+(?:[^;\n]+?\s+from\s+)?|\bimport\s*\(|\brequire\s*\()\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_EXTERNAL_RESOURCE_RE = re.compile(
    r"<(script|link|img|source|video|audio)\b[^>]*(?:src|href)\s*=\s*[\"']((?:https?:)?//[^\"']+)",
    re.IGNORECASE | re.DOTALL,
)
_EXTERNAL_CSS_RE = re.compile(r"(?:@import|url)\s*\([^)]*(?:https?:)?//", re.IGNORECASE)
_EXTERNAL_FETCH_RE = re.compile(r"\b(?:fetch|import)\s*\(\s*[\"']https?://", re.IGNORECASE)
_GSAP_ANIMATION_RE = re.compile(
    r"\b(?:gsap\.(?:to|from|fromTo|timeline|set)|ScrollTrigger\.create|useGSAP)\s*\(",
    re.IGNORECASE,
)
_GSAP_REGISTER_RE = re.compile(r"\b(?:gsap\.)?registerPlugin\s*\(([^)]*)\)", re.IGNORECASE | re.DOTALL)
_GSAP_PLUGIN_IMPORT_RE = re.compile(
    r"\bimport\s*\{([^}]+)\}\s*from\s*[\"']gsap(?:/[^\"']+)?[\"']",
    re.IGNORECASE | re.DOTALL,
)
_REDUCED_MOTION_RE = re.compile(
    r"prefers-reduced-motion|matchMedia\s*\(\s*[\"'][^\"']*reduce|reduced_motion",
    re.IGNORECASE,
)
_CLEANUP_RE = re.compile(
    r"\b(?:useGSAP|gsap\.context|contextSafe|(?:timeline|context|animation|trigger|ctx)\.(?:revert|kill)|ScrollTrigger\.getAll)",
    re.IGNORECASE,
)
_FONT_FACE_RE = re.compile(r"@font-face\s*\{(?P<body>[^}]*)\}", re.IGNORECASE | re.DOTALL)
_FONT_URL_RE = re.compile(r"url\(\s*(['\"]?)(?P<url>[^'\")]+)\1\s*\)", re.IGNORECASE)

# These are deliberately implementation-specific fingerprints of the old
# internal scaffold, not generic Astro/React conventions.  They are only used
# to detect accidental reuse; the gate never suggests a replacement design.
_INTERNAL_SCAFFOLD_MARKERS: tuple[frozenset[str], ...] = (
    frozenset({"siteheader", "responsivemenu", "motioninteraction"}),
    frozenset({"motion_plan", "data-motion-plan", "data-motion-page"}),
)


def _package_root(specifier: str) -> str:
    value = str(specifier or "").strip()
    if value.startswith("@"):
        parts = value.split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else value
    return value.split("/", 1)[0]


def _native_source_files(repo: Path, changed: set[str]) -> list[str]:
    return sorted(
        path for path in changed
        if Path(path).suffix.lower() in _NATIVE_SOURCE_SUFFIXES
        and not any(part in {".git", ".opencode", "node_modules", "dist", "output"} for part in Path(path).parts)
    )


def _native_source_findings(
    repo: Path,
    base_sha: str,
    candidate_sha: str,
    policy: QualityPolicy,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Check native source safety without constraining its visual structure."""
    if not policy.native_source_required:
        return {"status": "skipped", "reason": "native_source_not_required"}, []
    changed = _changed_paths(repo, base_sha, candidate_sha)
    source_paths = _native_source_files(repo, changed)
    findings: list[dict[str, Any]] = []
    if not source_paths:
        return {"status": "failed", "source_files": []}, [_finding(
            "native_source", "blocker", "native_source_missing",
            "A native design candidate must change at least one source file.",
        )]

    package_manifest: Mapping[str, Any] = {}
    package_path = repo / "package.json"
    if package_path.is_file() and not package_path.is_symlink():
        try:
            loaded = json.loads(package_path.read_text(encoding="utf-8"))
            if isinstance(loaded, Mapping):
                package_manifest = loaded
        except (OSError, json.JSONDecodeError):
            package_manifest = {}
    declared = _package_dependencies(package_manifest)
    approved = _approved_capability_map(policy)
    imported: dict[str, list[str]] = {}
    external_resources: list[dict[str, str]] = []
    registered_plugins: list[str] = []
    animation_files: list[str] = []
    cleanup_files: list[str] = []
    reduced_motion_files: list[str] = []

    for relative in source_paths:
        path = repo / relative
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(_finding(
                "native_source", "blocker", "unreadable_source", f"Native source could not be read: {relative}.",
                path=relative, error=str(exc)[:240],
            ))
            continue
        imports = sorted({_package_root(match) for match in _IMPORT_RE.findall(text)})
        imported[relative] = imports
        for specifier in imports:
            if specifier.startswith((".", "/", "#", "~", "@/", "astro:", "node:")):
                continue
            if specifier not in declared:
                findings.append(_finding(
                    "native_source", "blocker", "source_import_not_declared",
                    f"Native source imports a package that is not declared in package.json: {specifier}.",
                    path=relative, package=specifier,
                ))
            elif specifier not in approved:
                findings.append(_finding(
                    "native_source", "blocker", "source_import_not_approved",
                    f"Native source imports a package outside the host-approved capability catalog: {specifier}.",
                    path=relative, package=specifier,
                ))

        for tag, url in _EXTERNAL_RESOURCE_RE.findall(text):
            external_resources.append({"path": relative, "tag": tag.lower(), "url": url[:500]})
        if _EXTERNAL_CSS_RE.search(text) or _EXTERNAL_FETCH_RE.search(text):
            external_resources.append({"path": relative, "tag": "source", "url": "external network reference"})

        if _GSAP_ANIMATION_RE.search(text):
            animation_files.append(relative)
            if _CLEANUP_RE.search(text):
                cleanup_files.append(relative)
            if _REDUCED_MOTION_RE.search(text):
                reduced_motion_files.append(relative)
        if path.suffix.lower() == ".css" and re.search(r"@keyframes|(?:animation|transition)\s*:", text, re.IGNORECASE):
            animation_files.append(relative)
            if _REDUCED_MOTION_RE.search(text):
                reduced_motion_files.append(relative)

        for raw_names in _GSAP_REGISTER_RE.findall(text):
            for name in re.findall(r"\b[A-Za-z_$][\w$]*\b", raw_names):
                if name not in registered_plugins:
                    registered_plugins.append(name)
                plugin_capabilities = {
                    str(capability).casefold().replace("-", "")
                    for item in policy.approved_capabilities
                    if isinstance(item, Mapping)
                    for capability in (item.get("capabilities") or ())
                }
                if name.casefold().replace("-", "") not in plugin_capabilities:
                    findings.append(_finding(
                        "native_source", "blocker", "gsap_plugin_not_approved",
                        f"GSAP plugin is not in the approved capability catalog: {name}.",
                        path=relative, plugin=name,
                    ))
            imported_plugin_text = " ".join(_GSAP_PLUGIN_IMPORT_RE.findall(text))
            for name in re.findall(r"\b[A-Za-z_$][\w$]*\b", raw_names):
                if not re.search(rf"\b{re.escape(name)}\b", imported_plugin_text):
                    findings.append(_finding(
                        "native_source", "blocker", "gsap_plugin_unregistered_import",
                        f"Registered GSAP plugin has no local gsap plugin import: {name}.",
                        path=relative, plugin=name,
                    ))

    for item in external_resources:
        findings.append(_finding(
            "native_source", "blocker", "external_runtime_dependency",
            "Native source references an external runtime, asset, stylesheet, or script; the build must work offline.",
            **item,
        ))
    if animation_files and not cleanup_files:
        findings.append(_finding(
            "native_source", "blocker", "animation_cleanup_missing",
            "Animated native source must include a teardown path for timelines, triggers, or listeners.",
            paths=sorted(set(animation_files)),
        ))
    if animation_files and not reduced_motion_files:
        findings.append(_finding(
            "native_source", "blocker", "reduced_motion_branch_missing",
            "Animated native source must include a reduced-motion branch or media rule.",
            paths=sorted(set(animation_files)),
        ))

    return {
        "status": "failed" if findings else "passed",
        "source_files": source_paths,
        "imports": imported,
        "external_resources": external_resources,
        "animation_files": sorted(set(animation_files)),
        "cleanup_files": sorted(set(cleanup_files)),
        "reduced_motion_files": sorted(set(reduced_motion_files)),
        "registered_plugins": sorted(registered_plugins),
    }, findings


def _font_findings(
    repo: Path,
    base_sha: str,
    candidate_sha: str,
    policy: QualityPolicy,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Verify that authored font faces are local, WOFF2, and host-approved."""
    changed = _changed_paths(repo, base_sha, candidate_sha)
    changed_font_paths = sorted(
        path for path in changed
        if Path(path).suffix.lower() == ".woff2"
        and not any(part in {".git", ".opencode", "node_modules", "dist", "output"} for part in Path(path).parts)
    )
    # A repair is allowed to remove an authored font asset.  Git reports a
    # deleted asset as changed, but it must not be inspected as though the
    # candidate still contained a non-regular file.  Keep the deletion in the
    # evidence while applying the safety checks only to assets present in the
    # immutable candidate tree.
    removed_font_files = sorted(
        relative for relative in changed_font_paths
        if not (repo / relative).exists() and not (repo / relative).is_symlink()
    )
    font_paths = [
        relative for relative in changed_font_paths
        if relative not in removed_font_files
    ]
    approved: dict[str, dict[str, Any]] = {}
    for raw in policy.approved_font_files:
        if not isinstance(raw, Mapping):
            continue
        try:
            relative = safe_relative_path(raw.get("path") or raw.get("destination"), "approved_font_files.path")
        except Exception:
            continue
        # Font provisions are copied into Astro's public boundary. Accept the
        # shorter ``fonts/name.woff2`` spelling in older instance config, but
        # compare it using the committed candidate path.
        if not relative.startswith("public/"):
            relative = "public/" + relative
        approved[relative] = dict(raw)

    findings: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for relative in font_paths:
        path = repo / relative
        if path.is_symlink() or not path.is_file():
            findings.append(_finding(
                "fonts", "blocker", "font_not_regular",
                "A native font asset must be a regular local file.", path=relative,
            ))
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            findings.append(_finding(
                "fonts", "blocker", "font_unreadable",
                "A native font asset could not be read.", path=relative, error=str(exc)[:240],
            ))
            continue
        digest = hashlib.sha256(data).hexdigest()
        hashes[relative] = digest
        if not data.startswith(b"wOF2"):
            findings.append(_finding(
                "fonts", "blocker", "font_not_woff2",
                "Native font assets must be valid WOFF2 files.", path=relative,
            ))
        record = approved.get(relative)
        if record is None:
            findings.append(_finding(
                "fonts", "blocker", "font_not_approved",
                "A changed font asset is not in the host-approved font catalog.", path=relative,
            ))
        else:
            expected = str(record.get("sha256") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected) or expected != digest:
                findings.append(_finding(
                    "fonts", "blocker", "font_hash_mismatch",
                    "A local font does not match its host-approved SHA-256.",
                    path=relative, expected=expected, actual=digest,
                ))

    face_evidence: list[dict[str, Any]] = []
    source_paths = _native_source_files(repo, changed)
    for relative in source_paths:
        path = repo / relative
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for face in _FONT_FACE_RE.finditer(text):
            body = face.group("body")
            family_match = re.search(r"font-family\s*:\s*([^;]+)", body, re.IGNORECASE)
            family = str(family_match.group(1).strip() if family_match else "")
            urls = [str(match.group("url")).strip() for match in _FONT_URL_RE.finditer(body)]
            face_record = {"path": relative, "family": family, "urls": urls}
            face_evidence.append(face_record)
            for raw_url in urls:
                parsed = urlsplit(raw_url)
                if parsed.scheme or parsed.netloc or raw_url.startswith("//"):
                    findings.append(_finding(
                        "fonts", "blocker", "external_font",
                        "Font faces must load from local WOFF2 files, not a network URL.",
                        path=relative, url=raw_url[:500],
                    ))
                    continue
                clean_url = parsed.path.lstrip("/")
                if not clean_url.lower().endswith(".woff2"):
                    findings.append(_finding(
                        "fonts", "blocker", "font_format_not_woff2",
                        "Font faces must reference WOFF2 assets.", path=relative, url=raw_url[:500],
                    ))
                    continue
                candidates = []
                if raw_url.startswith("/"):
                    candidates.append(repo / "public" / clean_url)
                candidates.extend((repo / Path(relative).parent / clean_url, repo / clean_url))
                target = next((candidate.resolve() for candidate in candidates if candidate.is_file() and not candidate.is_symlink()), None)
                if target is None or (target != repo.resolve() and repo.resolve() not in target.parents):
                    findings.append(_finding(
                        "fonts", "blocker", "font_file_missing",
                        "A local @font-face reference does not resolve to a repository WOFF2 file.",
                        path=relative, url=raw_url[:500],
                    ))
                    continue
                resolved_relative = str(target.relative_to(repo.resolve())).replace("\\", "/")
                face_record.setdefault("files", []).append(resolved_relative)
                if approved and resolved_relative not in approved:
                    findings.append(_finding(
                        "fonts", "blocker", "font_not_approved",
                        "A rendered @font-face references a font outside the host-approved font catalog.",
                        path=relative, url=raw_url[:500], resolved_path=resolved_relative,
                    ))

    if policy.required_font_families:
        observed_families = [str(item.get("family") or "") for item in face_evidence]
        for required_family in policy.required_font_families:
            if not any(required_family.casefold() in family.casefold() for family in observed_families):
                findings.append(_finding(
                    "fonts", "blocker", "required_font_face_missing",
                    "A required font family has no local @font-face declaration.",
                    family=required_family,
                ))

    return {
        "status": "failed" if findings else "passed",
        "changed_font_files": changed_font_paths,
        "removed_font_files": removed_font_files,
        "font_hashes": hashes,
        "approved_font_files": sorted(approved),
        "font_faces": face_evidence,
    }, findings


def _normalized_source_signature(text: str) -> str:
    tags = re.findall(r"<\s*/?\s*([a-z][a-z0-9-]*)", text.casefold())
    classes = re.findall(r"class(?:Name)?\s*=\s*[\"'{`]([^\"'}`]+)", text.casefold())
    selectors = re.findall(r"(?:^|})\s*([^@{}][^{}]*)\s*\{", text.casefold())
    structure = {
        "tags": tags[:5_000],
        "classes": sorted(re.findall(r"[a-z][a-z0-9_-]*", " ".join(classes)))[:5_000],
        "selectors": sorted(re.sub(r"\s+", " ", item).strip() for item in selectors)[:5_000],
    }
    return hashlib.sha256(json.dumps(structure, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _originality_findings(
    repo: Path,
    base_sha: str,
    candidate_sha: str,
    policy: QualityPolicy,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Detect reuse of internal scaffold fingerprints without prescribing design."""
    if not policy.originality_required:
        return {"status": "skipped", "reason": "originality_not_required"}, []
    changed = _changed_paths(repo, base_sha, candidate_sha)
    source_paths = _native_source_files(repo, changed)
    source_text = []
    for relative in source_paths:
        path = repo / relative
        try:
            source_text.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    combined = "\n".join(source_text)
    normalized = re.sub(r"\s+", " ", combined.casefold())
    marker_hits = [
        sorted(marker for marker in marker_set if marker in normalized)
        for marker_set in _INTERNAL_SCAFFOLD_MARKERS
    ]
    structure_hash = _normalized_source_signature(combined)
    findings: list[dict[str, Any]] = []
    for marker_set, hits in zip(_INTERNAL_SCAFFOLD_MARKERS, marker_hits):
        if len(hits) == len(marker_set):
            findings.append(_finding(
                "originality", "blocker", "internal_scaffold_reuse",
                "Candidate source matches a protected internal scaffold fingerprint.",
                markers=hits,
            ))
    if structure_hash in set(policy.internal_scaffold_fingerprints):
        findings.append(_finding(
            "originality", "blocker", "internal_structure_reuse",
            "Candidate normalized source structure matches a protected internal scaffold fingerprint.",
            fingerprint=structure_hash,
        ))
    return {
        "status": "failed" if findings else "passed",
        "source_files": source_paths,
        "normalized_structure_sha256": structure_hash,
        "internal_marker_hits": marker_hits,
        "configured_fingerprint_match": structure_hash in set(policy.internal_scaffold_fingerprints),
    }, findings


def _build(
    repo: Path,
    policy: QualityPolicy,
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if policy.build_command is None:
        return {"status": "skipped"}, []
    command = shlex.split(policy.build_command) if isinstance(policy.build_command, str) else list(policy.build_command)
    proc_env = dict(env) if env is not None else dict(os.environ)
    # The venv python is a symlink to the base interpreter; resolve() would
    # point at the system bin and hide the venv's own tooling (e.g. pelican).
    runtime_bin = str(Path(sys.executable).parent)
    proc_env["PATH"] = os.pathsep.join(
        part for part in (runtime_bin, proc_env.get("PATH", os.defpath)) if part
    )
    try:
        result = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=max(1, min(int(policy.build_timeout_seconds), 900)),
            env=proc_env,
        )
    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": "build timed out"}, [_finding("build", "blocker", "build_timeout", "The configured build timed out.")]
    stdout = safe_provider_message(result.stdout, max_chars=10_000)
    stderr = safe_provider_message(result.stderr, max_chars=10_000)
    evidence = {"status": "passed" if result.returncode == 0 else "failed", "command": command,
                "returncode": result.returncode, "stdout": stdout, "stderr": stderr}
    if result.returncode:
        return evidence, [_finding("build", "blocker", "build_failed", "The configured site build failed.", evidence=evidence)]
    return evidence, []


def _output_findings(repo: Path, policy: QualityPolicy) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    output = (repo / policy.output_dir).resolve()
    root = repo.resolve()
    if output != root and root not in output.parents:
        return {"status": "failed"}, [_finding("output", "blocker", "output_escape", "The output directory escapes the worktree.")]
    if not output.is_dir():
        return {"status": "failed", "output_dir": policy.output_dir}, [_finding("output", "blocker", "missing_output", "The build did not produce its output directory.")]
    findings: list[dict[str, Any]] = []
    files = [path for path in output.rglob("*") if path.is_file()]
    for required in policy.required_pages:
        target = (output / PurePosixPath(required)).resolve()
        if target != output and output not in target.parents:
            findings.append(_finding("output", "blocker", "required_page_escape", f"Required page escapes output: {required}", path=required))
        elif not target.is_file():
            findings.append(_finding("output", "blocker", "missing_output", f"Required output page is missing: {required}", path=required))
    for path in files:
        relative = str(path.relative_to(output)).replace("\\", "/")
        if any(fnmatch(relative, pattern) for pattern in policy.ignored_pages):
            continue
        if path.suffix.lower() in {".jinja", ".jinja2", ".j2"} or any(part in {"themes", "content"} for part in path.relative_to(output).parts):
            findings.append(_finding("output", "blocker", "source_leak", f"Source material leaked into public output: {relative}", path=relative))
        if path.suffix.lower() in {".html", ".htm"}:
            findings.extend(_html_findings(
                output,
                path,
                require_styling=policy.browser_required or policy.visual_critic,
            ))
    return {"status": "failed" if findings else "passed", "files": len(files), "output_dir": policy.output_dir}, findings


def _content_key(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE)).strip()


def _content_findings(output: Path, policy: QualityPolicy) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Verify typed brief requirements appear in visible public output."""
    requirements = tuple(dict.fromkeys(_content_key(item) for item in policy.required_content if _content_key(item)))
    if not requirements:
        return {"status": "skipped", "reason": "no_required_content"}, []
    pages: list[str] = []
    visible_text: list[str] = []
    for required in policy.required_pages:
        path = (output / PurePosixPath(required)).resolve()
        if path.is_file() and output.resolve() in path.parents and path.suffix.lower() in {".html", ".htm"}:
            parser = _DocumentParser()
            try:
                parser.feed(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            pages.append(required)
            visible_text.append(parser.visible_text)
    content = _content_key(" ".join(visible_text))
    missing = [requirement for requirement in requirements if requirement not in content]
    findings = [
        _finding(
            "content",
            "blocker",
            "missing_required_content",
            "A required brief item is missing from visible public output.",
            requirement=requirement,
            pages=pages,
        )
        for requirement in missing
    ]
    return {
        "status": "failed" if missing else "passed",
        "pages": pages,
        "required": list(requirements),
        "missing": missing,
    }, findings


def _conversion_findings(output: Path, policy: QualityPolicy) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Reject contact and social destinations when the typed intake has none."""
    if not policy.contact_destination_unavailable:
        return {"status": "skipped", "reason": "contact_destination_available_or_not_configured"}, []
    if not output.is_dir():
        return {"status": "skipped", "reason": "missing_output"}, []

    links: list[dict[str, str]] = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".html", ".htm"}:
            continue
        relative = str(path.relative_to(output)).replace("\\", "/")
        if any(fnmatch(relative, pattern) for pattern in policy.ignored_pages):
            continue
        parser = _DocumentParser()
        try:
            parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for href in parser.links:
            parsed = urlsplit(href)
            scheme = parsed.scheme.lower()
            hostname = (parsed.hostname or "").lower().removeprefix("www.")
            is_contact_host = hostname in _CONTACT_HOSTS or any(
                hostname.endswith("." + suffix) for suffix in _CONTACT_HOSTS
            )
            if scheme in {"mailto", "tel"} or is_contact_host:
                links.append({"path": relative, "scheme": scheme or "https", "href": href[:240]})

    findings = [
        _finding(
            "conversion",
            "blocker",
            "unsupported_contact_destination",
            "The intake does not provide a contact destination, but public output contains a contact link.",
            path=link["path"],
            scheme=link["scheme"],
            href=link["href"],
        )
        for link in links
    ]
    return {"status": "failed" if findings else "passed", "links": links}, findings


def _manifest_findings(repo: Path, policy: QualityPolicy) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not policy.manifest_path:
        return {"status": "skipped"}, []
    try:
        manifest_path = safe_relative_path(policy.manifest_path, "manifest_path")
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed"}, [_finding("manifest", "blocker", "manifest_path", str(exc))]
    path = repo / manifest_path
    if not path.is_file() or path.is_symlink():
        return {"status": "failed", "path": manifest_path}, [_finding(
            "manifest", "blocker", "missing_manifest", f"Design manifest is missing: {manifest_path}", path=manifest_path
        )]
    try:
        manifest = DesignManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "path": manifest_path}, [_finding(
            "manifest", "blocker", "invalid_manifest", f"Design manifest is invalid: {str(exc)[:240]}", path=manifest_path
        )]
    findings: list[dict[str, Any]] = []
    if policy.expected_intake_hash and manifest.intake_hash != policy.expected_intake_hash:
        findings.append(_finding("manifest", "blocker", "manifest_intake_mismatch", "Manifest intake hash does not match the run intake."))
    paths = [manifest.source_homepage_path]

    def collect(value: Any) -> None:
        if isinstance(value, str) and _looks_like_source_path(value):
            paths.append(value.strip())
        elif isinstance(value, Mapping):
            for item in value.values():
                collect(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    collect(manifest.source_files)
    checked: list[str] = []
    for value in paths:
        if value.startswith(("http://", "https://", "mailto:", "tel:")):
            continue
        try:
            relative = safe_relative_path(value, "manifest.source_file")
        except Exception:
            findings.append(_finding("manifest", "blocker", "unsafe_source_path", "Manifest contains an unsafe source path.", path=value[:240]))
            continue
        target = repo / relative
        if target.is_symlink() or not target.is_file():
            findings.append(_finding("manifest", "blocker", "missing_source_file", f"Manifest source file is missing: {relative}", path=relative))
        checked.append(relative)
    return {"status": "failed" if findings else "passed", "path": manifest_path, "source_files_checked": sorted(set(checked))}, findings


def _stage_host_runtime_files(repo: Path, policy: QualityPolicy) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Copy host-provisioned runtime files into build output before browser checks."""
    if not policy.manifest_path:
        return {"status": "skipped", "reason": "manifest_not_configured"}, []
    try:
        manifest_path = safe_relative_path(policy.manifest_path, "manifest_path")
        raw_manifest = json.loads((repo / manifest_path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - the manifest gate reports the primary error
        return {"status": "skipped", "reason": "manifest_unavailable"}, []
    if not isinstance(raw_manifest, Mapping) or raw_manifest.get("host_generated") is not True:
        return {"status": "skipped", "reason": "host_manifest_required"}, []
    metadata = raw_manifest.get("host_metadata")
    if not isinstance(metadata, Mapping):
        return {"status": "skipped", "reason": "runtime_metadata_missing"}, []
    raw_paths = metadata.get("provisioned_runtime_paths") or []
    if not isinstance(raw_paths, list) or not raw_paths:
        return {"status": "skipped", "reason": "no_host_runtime_paths"}, []

    output = (repo / policy.output_dir).resolve()
    root = repo.resolve()
    findings: list[dict[str, Any]] = []
    staged: list[str] = []
    if output != root and root not in output.parents:
        return {"status": "failed"}, [_finding("runtime", "blocker", "output_escape", "The output directory escapes the worktree.")]
    for raw_path in raw_paths:
        try:
            relative = safe_relative_path(raw_path, "host_metadata.provisioned_runtime_paths")
        except Exception as exc:  # noqa: BLE001
            findings.append(_finding("runtime", "blocker", "unsafe_runtime_path", str(exc), path=str(raw_path)[:240]))
            continue
        if relative == policy.output_dir or relative.startswith(policy.output_dir.rstrip("/") + "/"):
            findings.append(_finding("runtime", "blocker", "unsafe_runtime_path", "Host runtime path must be outside the build output.", path=relative))
            continue
        source = (root / relative).resolve()
        if ((source != root and root not in source.parents) or source.is_symlink() or not source.is_file()):
            findings.append(_finding("runtime", "blocker", "missing_runtime_file", f"Host-provisioned runtime file is missing: {relative}", path=relative))
            continue
        target = (output / relative).resolve()
        if target != output and output not in target.parents:
            findings.append(_finding("runtime", "blocker", "runtime_output_escape", f"Host runtime output escapes the build directory: {relative}", path=relative))
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        except OSError as exc:
            findings.append(_finding("runtime", "blocker", "runtime_stage_failed", f"Could not stage host runtime file: {relative} ({exc})", path=relative))
            continue
        staged.append(relative)
    return {"status": "failed" if findings else "passed", "paths": staged}, findings


def _html_findings(output: Path, path: Path, *, require_styling: bool = False) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    parser = _DocumentParser()
    try:
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        return [_finding("document", "blocker", "unreadable_output", f"Could not read {path.name}: {exc}", path=str(path.relative_to(output)))]
    relative = str(path.relative_to(output))
    if require_styling and parser.author_style_count == 0:
        findings.append(_finding(
            "styling",
            "blocker",
            "unstyled_page",
            f"Designed output page has no author stylesheet or inline style: {relative}",
            path=relative,
        ))
    if not parser.title.strip():
        findings.append(_finding("document", "blocker", "missing_title", f"Page has no title: {relative}", path=relative))
    if not parser.description:
        findings.append(_finding("document", "warning", "missing_description", f"Page has no meta description: {relative}", path=relative))
    if not parser.lang:
        findings.append(_finding("document", "blocker", "missing_language", f"Page has no language declaration: {relative}", path=relative))
    if not parser.viewport:
        findings.append(_finding("document", "blocker", "missing_viewport", f"Page has no viewport metadata: {relative}", path=relative))
    if parser.h1_count != 1:
        findings.append(_finding("document", "blocker", "h1_count", f"Page must contain exactly one H1: {relative}", path=relative, count=parser.h1_count))
    for image in parser.images:
        if image.get("has_alt") != "true" and image.get("decorative") != "true":
            findings.append(_finding("accessibility", "blocker", "missing_alt", f"Image has no alt text: {relative}", path=relative, src=image["src"]))
    if _PLACEHOLDER_RE.search(parser.text):
        findings.append(_finding("document", "warning", "placeholder_text", f"Placeholder text detected: {relative}", path=relative))
    for href in parser.links:
        parts = urlsplit(href)
        if href.startswith("javascript:"):
            findings.append(_finding("document", "blocker", "unsafe_link", f"Unsafe JavaScript link: {relative}", path=relative, href=href[:200]))
            continue
        if parts.scheme or href.startswith(("//", "#")):
            continue
        target_name = parts.path.lstrip("/") or "index.html"
        target_root = output if href.startswith("/") and not href.startswith("//") else path.parent
        target = (target_root / target_name).resolve()
        if target.suffix == "":
            candidate = target.with_suffix(".html")
            if candidate.is_file():
                target = candidate
        if target != output.resolve() and output.resolve() not in target.parents:
            findings.append(_finding("document", "blocker", "link_escape", f"Local link escapes output: {href}", path=relative))
        elif not target.is_file():
            findings.append(_finding("document", "warning", "broken_link", f"Local link target is missing: {href}", path=relative))
    return findings


def _compact_motion_snapshot(value: Any) -> Any:
    """Keep motion counters while bounding per-node browser diagnostics.

    Playwright records a node snapshot at every scroll position for every route
    and viewport. Those snapshots are useful while debugging locally, but
    retaining them in the durable quality report duplicates tens of thousands
    of characters and can exceed the persistence payload limit. The gate only
    needs the aggregate counters; retain the node count for traceability.
    """
    if not isinstance(value, Mapping):
        return value
    compact = dict(value)
    runtime = compact.get("runtime")
    if isinstance(runtime, Mapping):
        runtime_compact = dict(runtime)
        nodes = runtime_compact.pop("motion_nodes", None)
        if isinstance(nodes, (list, tuple)):
            runtime_compact["motion_node_count"] = len(nodes)
        compact["runtime"] = runtime_compact
    else:
        nodes = compact.pop("motion_nodes", None)
        if isinstance(nodes, (list, tuple)):
            compact["motion_node_count"] = len(nodes)
    return compact


def _compact_browser_result(value: Mapping[str, Any]) -> dict[str, Any]:
    """Bound repeated motion node data before storing browser evidence."""
    result = dict(value)
    routes: list[dict[str, Any]] = []
    for raw_route in result.get("routes") or ():
        if not isinstance(raw_route, Mapping):
            continue
        route = dict(raw_route)
        preferences = route.get("motion_preferences")
        if isinstance(preferences, Mapping):
            route["motion_preferences"] = {
                str(name): _compact_motion_snapshot(snapshot)
                for name, snapshot in preferences.items()
            }
        states = route.get("scroll_states")
        if isinstance(states, list):
            route["scroll_states"] = [_compact_motion_snapshot(state) for state in states]
        routes.append(route)
    result["routes"] = routes
    states = result.get("scroll_states")
    if isinstance(states, list):
        result["scroll_states"] = [
            {
                **dict(item),
                "states": [
                    _compact_motion_snapshot(state)
                    for state in (item.get("states") or ())
                ],
            }
            for item in states
            if isinstance(item, Mapping)
        ]
    return result


def _browser_findings(output: Path, policy: QualityPolicy, browser: BrowserQualityAdapter | None) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    if not policy.browser_required:
        return {"status": "skipped"}, [], False
    if browser is None:
        return {"status": "unavailable"}, [_finding("browser", "incomplete", "browser_unavailable", "Browser quality evidence is unavailable.")], True
    findings: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {"status": "passed", "viewports": []}
    motion_evidence: list[dict[str, Any]] = []
    contrast_evidence: list[dict[str, Any]] = []
    font_evidence: list[dict[str, Any]] = []
    font_check_evidence: list[dict[str, Any]] = []
    image_evidence: list[dict[str, Any]] = []
    text_wrap_evidence: list[dict[str, Any]] = []
    scroll_evidence: list[dict[str, Any]] = []
    interaction_evidence: list[dict[str, Any]] = []
    external_request_evidence: list[dict[str, Any]] = []
    for viewport in policy.viewports:
        try:
            result = _compact_browser_result(dict(browser.inspect(output, viewport)))
        except Exception as exc:  # noqa: BLE001
            return {"status": "unavailable"}, [_finding("browser", "incomplete", "browser_unavailable", safe_provider_message(str(exc)))], True
        evidence["viewports"].append({"viewport": dict(viewport), "result": result})
        contrast_failures = result.get("contrast_failures") or []
        font_load_failures = result.get("font_load_failures") or []
        font_checks = result.get("font_checks") or []
        low_resolution_images = result.get("low_resolution_images") or []
        text_wrap_failures = result.get("text_wrap_failures") or []
        contrast_evidence.extend({"viewport": dict(viewport), **item} for item in contrast_failures if isinstance(item, Mapping))
        font_evidence.extend({"viewport": dict(viewport), **item} for item in font_load_failures if isinstance(item, Mapping))
        font_check_evidence.extend({"viewport": dict(viewport), **item} for item in font_checks if isinstance(item, Mapping))
        image_evidence.extend({"viewport": dict(viewport), **item} for item in low_resolution_images if isinstance(item, Mapping))
        text_wrap_evidence.extend({"viewport": dict(viewport), **item} for item in text_wrap_failures if isinstance(item, Mapping))
        external_requests = result.get("external_requests") or []
        external_request_evidence.extend(
            {"viewport": dict(viewport), **item}
            for item in external_requests
            if isinstance(item, Mapping)
        )
        if external_requests:
            findings.append(_finding(
                "browser", "blocker", "external_request",
                "Rendered output attempted an external network request; native candidates must run with local assets and runtimes.",
                viewport=dict(viewport), details=external_requests,
            ))
        motion_records: list[tuple[str, Mapping[str, Any]]] = []
        top_level_motion = result.get("motion_preferences")
        if isinstance(top_level_motion, Mapping):
            motion_records.append(("", top_level_motion))
        for route in result.get("routes") or ():
            if not isinstance(route, Mapping):
                continue
            route_motion = route.get("motion_preferences")
            if isinstance(route_motion, Mapping):
                motion_records.append((str(route.get("route") or ""), route_motion))
            route_name = str(route.get("route") or "")
            if route.get("scroll_states"):
                scroll_evidence.append({"viewport": dict(viewport), "route": route_name, "states": route.get("scroll_states")})
            if route.get("interaction_state"):
                interaction_evidence.append({"viewport": dict(viewport), "route": route_name, "state": route.get("interaction_state")})
        for route_name, motion_preferences in motion_records:
            motion_evidence.append({
                "viewport": dict(viewport),
                **({"route": route_name} if route_name else {}),
                "preferences": dict(motion_preferences),
            })
            normal_motion = motion_preferences.get("no-preference") or {}
            reduced_motion = motion_preferences.get("reduce") or {}
            normal_active = int(normal_motion.get("active_animations", 0) or 0)
            reduced_active = int(reduced_motion.get("active_animations", 0) or 0)
            normal_runtime = normal_motion.get("runtime") or {}
            reduced_runtime = reduced_motion.get("runtime") or {}
            normal_gsap_active = int(normal_runtime.get("gsap_active_tweens") or 0)
            reduced_gsap_active = int(reduced_runtime.get("gsap_active_tweens") or 0)
            normal_triggers = int(normal_runtime.get("scroll_trigger_count") or 0)
            reduced_triggers = int(reduced_runtime.get("scroll_trigger_count") or 0)
            if (normal_active and reduced_active >= normal_active) or (
                normal_gsap_active and reduced_gsap_active >= normal_gsap_active
            ) or (normal_triggers and reduced_triggers):
                findings.append(_finding(
                    "browser", "blocker", "reduced_motion_ignored",
                    "Reduced-motion emulation left GSAP, ScrollTrigger, or as many animations active as normal motion.",
                    viewport=dict(viewport),
                    **({"route": route_name} if route_name else {}),
                    details={"no_preference": normal_motion, "reduce": reduced_motion},
                ))
        for key, code, message in (
            ("console_errors", "console_error", "Browser console errors were reported."),
            ("failed_requests", "network_error", "Browser requests failed."),
            ("overflow", "horizontal_overflow", "Horizontal overflow was detected."),
            ("clipping", "element_clipping", "Important content was clipped at the viewport edge."),
            ("fixed_header_overlap", "fixed_header_overlap", "Important content overlaps the fixed header."),
        ):
            value = result.get(key)
            if value:
                findings.append(_finding("browser", "blocker", code, message, viewport=dict(viewport), details=value))
        for item in result.get("accessibility") or ():
            findings.append(_finding("accessibility", "blocker", "accessibility", "Browser accessibility findings were reported.", viewport=dict(viewport), details=item))
        if contrast_failures:
            findings.append(_finding(
                "browser", "blocker", "contrast_failure",
                "Rendered text did not meet the required WCAG contrast ratio.",
                viewport=dict(viewport), details=contrast_failures,
            ))
        if font_load_failures:
            findings.append(_finding(
                "browser", "warning", "font_load_failure",
                "One or more rendered font families were not confirmed as loaded; fallback use is recorded.",
                viewport=dict(viewport), details=font_load_failures,
            ))
        if policy.required_font_families:
            for required_family in policy.required_font_families:
                matches = [
                    item for item in font_checks
                    if isinstance(item, Mapping)
                    and required_family.casefold() in str(item.get("family") or "").casefold()
                ]
                if not matches:
                    findings.append(_finding(
                        "fonts", "blocker", "required_font_missing",
                        "A requested font family was not observed in rendered public text.",
                        family=required_family, viewport=dict(viewport),
                    ))
                elif not any(item.get("loaded") is True for item in matches):
                    findings.append(_finding(
                        "fonts", "blocker", "required_font_not_loaded",
                        "A requested font family was rendered only through an unconfirmed fallback.",
                        family=required_family, viewport=dict(viewport), details=matches,
                    ))
        if low_resolution_images:
            findings.append(_finding(
                "browser", "warning", "low_resolution_image",
                "An image is rendered wider than its available source resolution.",
                viewport=dict(viewport), details=low_resolution_images,
            ))
        if text_wrap_failures:
            findings.append(_finding(
                "browser", "blocker", "text_wrap_failure",
                "Long public copy is rendered with no more than one word per line.",
                viewport=dict(viewport), details=text_wrap_failures,
            ))
        for route in result.get("routes") or ():
            if route.get("error"):
                findings.append(_finding("browser", "blocker", "route_error", "A rendered route could not be inspected.", viewport=dict(viewport), details={"route": route.get("route"), "error": route.get("error")}))
            keyboard = route.get("keyboard") or {}
            if keyboard.get("focusable_count") and not keyboard.get("focus_visible"):
                findings.append(_finding("accessibility", "blocker", "focus_visibility", "Keyboard focus was not visibly indicated.", viewport=dict(viewport), details={"route": route.get("route"), "keyboard": keyboard}))
    if findings:
        evidence["status"] = "failed"
    evidence["motion_preferences"] = motion_evidence
    evidence["contrast_failures"] = contrast_evidence
    evidence["font_load_failures"] = font_evidence
    evidence["font_checks"] = font_check_evidence
    evidence["low_resolution_images"] = image_evidence
    evidence["text_wrap_failures"] = text_wrap_evidence
    evidence["scroll_states"] = scroll_evidence
    evidence["interaction_states"] = interaction_evidence
    evidence["external_requests"] = external_request_evidence
    return evidence, findings, False


def _run_quality_in_workspace(
    workspace: Path,
    *,
    base_sha: str,
    candidate_sha: str,
    run_id: str,
    policy: QualityPolicy,
    browser: BrowserQualityAdapter | None,
    repair_attempts: int,
    build_evidence: Mapping[str, Any] | None = None,
    build_runner=None,
    build_env: Mapping[str, str] | None = None,
) -> QualityReport:
    findings = _repository_findings(workspace, base_sha, candidate_sha, policy)
    findings.extend(_dependency_findings(workspace, base_sha, candidate_sha, policy))
    native_source_evidence, native_source_findings = _native_source_findings(
        workspace, base_sha, candidate_sha, policy
    )
    findings.extend(native_source_findings)
    originality_evidence, originality_findings = _originality_findings(
        workspace, base_sha, candidate_sha, policy
    )
    findings.extend(originality_findings)
    font_evidence, font_findings = _font_findings(
        workspace, base_sha, candidate_sha, policy
    )
    findings.extend(font_findings)
    if build_runner is not None:
        try:
            build_evidence = dict(build_runner(workspace))
        except Exception as exc:  # noqa: BLE001 - convert adapter failures into gate evidence
            build_evidence = {"status": "failed", "error": safe_provider_message(str(exc))}
        build_findings = [] if build_evidence.get("ok", build_evidence.get("status") == "passed") else [
            _finding("build", "blocker", "build_failed", "The configured site build failed.", evidence=build_evidence)
        ]
    elif build_evidence is None:
        build_evidence, build_findings = _build(workspace, policy, env=build_env)
    else:
        build_evidence = dict(build_evidence)
        build_findings = [] if build_evidence.get("ok", build_evidence.get("status") == "passed") else [
            _finding("build", "blocker", "build_failed", "The configured site build failed.", evidence=build_evidence)
        ]
    findings.extend(build_findings)
    runtime_evidence, runtime_findings = _stage_host_runtime_files(workspace, policy)
    findings.extend(runtime_findings)
    output_evidence, output_findings = _output_findings(workspace, policy)
    findings.extend(output_findings)
    content_evidence, content_findings = _content_findings(workspace / policy.output_dir, policy)
    findings.extend(content_findings)
    conversion_evidence, conversion_findings = _conversion_findings(workspace / policy.output_dir, policy)
    findings.extend(conversion_findings)
    manifest_evidence, manifest_findings = _manifest_findings(workspace, policy)
    findings.extend(manifest_findings)
    browser_evidence, browser_findings, browser_incomplete = _browser_findings(workspace / policy.output_dir, policy, browser)
    findings.extend(browser_findings)
    motion_evidence = {
        "status": "passed" if not native_source_evidence.get("animation_files") else (
            "incomplete"
            if browser_incomplete or not policy.browser_required
            else browser_evidence.get("status", "passed")
        ),
        "validation": "native_source_and_browser_behavior",
        "source": {
            "animation_files": native_source_evidence.get("animation_files", []),
            "cleanup_files": native_source_evidence.get("cleanup_files", []),
            "reduced_motion_files": native_source_evidence.get("reduced_motion_files", []),
        },
        "browser": {
            "motion_preferences": browser_evidence.get("motion_preferences", []),
            "scroll_states": browser_evidence.get("scroll_states", []),
            "interaction_states": browser_evidence.get("interaction_states", []),
        },
    }
    if native_source_evidence.get("animation_files") and not policy.browser_required:
        findings.append(_finding(
            "motion", "incomplete", "motion_behavior_unverified",
            "Native motion source exists but browser behavior was not requested, so the candidate cannot be fully verified.",
            paths=native_source_evidence.get("animation_files", []),
        ))
    build_status = build_evidence.get("status")
    if build_status is None and "ok" in build_evidence:
        build_status = "passed" if build_evidence.get("ok") else "failed"
    blockers = {"blocker", "critical", "serious"}
    state = "failed" if any(item["severity"] in blockers for item in findings) else "incomplete" if browser_incomplete or any(item["severity"] == "incomplete" for item in findings) else "passed"
    return QualityReport.from_dict({
        "run_id": run_id,
        "candidate_sha": candidate_sha,
        "state": state,
        "findings": findings,
        "evidence": {
            "build": build_evidence,
            "native_source": native_source_evidence,
            "originality": originality_evidence,
            "fonts": font_evidence,
            "runtime": runtime_evidence,
            "output": output_evidence,
            "content": content_evidence,
            "conversion": conversion_evidence,
            "manifest": manifest_evidence,
            "motion": motion_evidence,
            "browser": browser_evidence,
        },
        "gates": {
            "repository": "failed" if any(item["gate"] == "repository" and item["severity"] in blockers for item in findings) else "passed",
            "build": build_status,
            "native_source": native_source_evidence.get("status"),
            "originality": originality_evidence.get("status"),
            "fonts": font_evidence.get("status"),
            "output": output_evidence.get("status"),
            "content": content_evidence.get("status"),
            "conversion": conversion_evidence.get("status"),
            "manifest": manifest_evidence.get("status"),
            "motion": motion_evidence.get("status"),
            "browser": browser_evidence.get("status"),
        },
        "repair_attempts": repair_attempts,
    })


def run_quality_gates(
    repo: str | Path,
    *,
    base_sha: str,
    candidate_sha: str,
    run_id: str,
    policy: QualityPolicy | None = None,
    browser: BrowserQualityAdapter | None = None,
    repair_attempts: int = 0,
    build_evidence: Mapping[str, Any] | None = None,
    build_runner=None,
    build_env: Mapping[str, str] | None = None,
) -> QualityReport:
    """Run all deterministic checks and return evidence without mutating the repo."""
    policy = policy or QualityPolicy()
    root = Path(repo).expanduser().resolve()
    workspace = root
    temporary_workspace: Path | None = None
    try:
        # A candidate must be checked as committed, immutable content rather
        # than against whatever happens to be in the persistent clone.
        if base_sha != candidate_sha:
            # The container's system temporary directory is mounted noexec.
            # Astro's npm bin shims are executable files, so checking a
            # committed candidate out under /tmp makes `npm run check` fail
            # with a misleading "astro: Permission denied". Keep the
            # immutable quality worktree beside the repository instead; the
            # design-lab workspace is on the executable application volume.
            temporary_workspace = Path(tempfile.mkdtemp(prefix="ada-quality-", dir=str(root.parent)))
            try:
                _git(root, "rev-parse", "--verify", f"{base_sha}^{{commit}}")
                _git(root, "rev-parse", "--verify", f"{candidate_sha}^{{commit}}")
                _git(root, "worktree", "add", "--detach", str(temporary_workspace), candidate_sha)
                workspace = temporary_workspace
            except RuntimeError as exc:
                return QualityReport.from_dict({
                    "run_id": run_id,
                    "candidate_sha": candidate_sha,
                    "state": "failed",
                    "findings": [_finding("repository", "blocker", "candidate_unavailable", safe_provider_message(str(exc)))],
                    "evidence": {},
                    "repair_attempts": repair_attempts,
                })
        return _run_quality_in_workspace(
            workspace,
            base_sha=base_sha,
            candidate_sha=candidate_sha,
            run_id=run_id,
            policy=policy,
            browser=browser,
            repair_attempts=repair_attempts,
            build_evidence=build_evidence,
            build_runner=build_runner,
            build_env=build_env,
        )
    finally:
        if temporary_workspace is not None:
            try:
                _git(root, "worktree", "remove", "--force", str(temporary_workspace))
            except RuntimeError:
                pass
            shutil.rmtree(temporary_workspace, ignore_errors=True)


__all__ = ["BrowserQualityAdapter", "QualityPolicy", "run_quality_gates"]
