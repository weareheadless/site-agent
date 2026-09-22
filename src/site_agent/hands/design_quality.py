"""Host-owned deterministic checks for reviewable design candidates."""

from __future__ import annotations

import html
import hashlib
import ipaddress
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
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

from ..core.contracts import safe_provider_message
from ..core.design_contracts import DesignManifest, QualityReport, TemporalExperienceEvidence, canonical_hash, safe_relative_path
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


def _is_local_preview_source(value: str) -> bool:
    """Treat the ephemeral local preview origin as part of the candidate.

    Browser inspection resolves a relative asset path against the preview
    server, so a local ``/images/...`` becomes an absolute loopback URL in
    composition evidence. That URL is not an external asset substitution.
    Remote origins and explicit ``external_url`` evidence remain blocked.
    """
    parsed = urlsplit(value if not value.startswith("//") else f"http:{value}")
    if parsed.scheme not in {"http", "https"}:
        return False
    host = str(parsed.hostname or "").strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


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
    react_source_required: bool = False
    gsap_required: bool = False
    originality_required: bool = False
    internal_scaffold_fingerprints: tuple[str, ...] = ()
    required_font_families: tuple[str, ...] = ()
    approved_font_files: tuple[dict[str, Any], ...] = ()
    max_rendered_asset_height_viewport_ratio: float = 2.0
    max_empty_scroll_viewport_ratio: float = 2.0
    immersive_asset_ids: tuple[str, ...] = ()
    operation_kind: str = "initial_build"

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
        build_profile = str(engine.get("build_profile") or "").strip().lower()
        if build_profile == "next_react":
            from .site_build import NEXT_REACT_PROFILE

            default_output_dir = NEXT_REACT_PROFILE.output_dir
            default_allowed_patterns = NEXT_REACT_PROFILE.writable_patterns
            default_build_command = None
        else:
            default_output_dir = "output"
            default_allowed_patterns = site.get("writable_patterns") or ()
            default_build_command = blog.get("build_command", cls.build_command)
        command = quality.get("build_command", default_build_command)
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
        libraries = engine.get("libraries") or {}
        gsap_library = libraries.get("gsap") if isinstance(libraries, Mapping) else {}
        try:
            max_rendered_asset_height_viewport_ratio = float(
                quality.get("max_rendered_asset_height_viewport_ratio", cls.max_rendered_asset_height_viewport_ratio)
            )
            max_empty_scroll_viewport_ratio = float(
                quality.get("max_empty_scroll_viewport_ratio", cls.max_empty_scroll_viewport_ratio)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("design_engine.quality geometry ratios must be numbers") from exc
        if max_rendered_asset_height_viewport_ratio <= 0 or max_empty_scroll_viewport_ratio <= 0:
            raise ValueError("design_engine.quality geometry ratios must be positive")
        return cls(
            output_dir=str(quality.get("output_dir") or default_output_dir),
            required_pages=tuple(str(item) for item in pages if str(item).strip()),
            required_content=tuple(str(item) for item in content if str(item).strip()),
            allowed_patterns=tuple(str(item) for item in (quality.get("allowed_patterns") or default_allowed_patterns or ())),
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
            react_source_required=bool(quality.get("react_source_required", engine.get("react_source_required", False))),
            gsap_required=bool(
                quality.get(
                    "gsap_required",
                    gsap_library.get("required", False) if isinstance(gsap_library, Mapping) else False,
                )
            ),
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
            max_rendered_asset_height_viewport_ratio=max_rendered_asset_height_viewport_ratio,
            max_empty_scroll_viewport_ratio=max_empty_scroll_viewport_ratio,
            immersive_asset_ids=tuple(
                str(item).strip()
                for item in (quality.get("immersive_asset_ids") or ())
                if str(item).strip()
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


def _browser_box(value: Any, path: str) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        number = float(item)
        if key in {"width", "height"} and number <= 0:
            return None
        result[key] = number
    return result


def _boxes_intersect(first: Mapping[str, float], second: Mapping[str, float], padding: float = 0) -> bool:
    return not (
        first["x"] + first["width"] + padding <= second["x"]
        or second["x"] + second["width"] + padding <= first["x"]
        or first["y"] + first["height"] + padding <= second["y"]
        or second["y"] + second["height"] + padding <= first["y"]
    )


def evaluate_composition_plan(
    composition_plan: Sequence[Any],
    rendered_evidence: Sequence[Mapping[str, Any]],
    *,
    max_rendered_asset_height_viewport_ratio: float = 2.0,
    max_empty_scroll_viewport_ratio: float = 2.0,
    immersive_asset_ids: Sequence[str] = (),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Check only objective relationships declared by the frozen composition plan.

    The browser adapter supplies role-based boxes and asset identities.  This
    helper deliberately does not inspect CSS class names or infer whether a
    visual choice is attractive.
    """
    from ..core.design_contracts import AssetCompositionPlan

    plans = tuple(
        item if isinstance(item, AssetCompositionPlan) else AssetCompositionPlan.from_dict(item)
        for item in composition_plan
    )
    findings: list[dict[str, Any]] = []
    route_reports: list[dict[str, Any]] = []
    assigned: dict[str, int] = {item.asset_id: 0 for item in plans}
    immersive_ids = {str(item).strip() for item in immersive_asset_ids if str(item).strip()}

    def treatment_is_immersive(plan: Any) -> bool:
        if plan.asset_id in immersive_ids:
            return True
        for treatment in (plan.desktop_treatment, plan.tablet_treatment, plan.mobile_treatment):
            if not isinstance(treatment, Mapping):
                continue
            if any(
                treatment.get(key) is True
                for key in ("immersive", "allow_oversized_rendered_media", "allow_oversized_media")
            ):
                return True
        return False

    for raw_route in rendered_evidence:
        route = dict(raw_route) if isinstance(raw_route, Mapping) else {}
        route_name = str(route.get("route") or "")
        viewport = dict(route.get("viewport") or {}) if isinstance(route.get("viewport"), Mapping) else {}
        raw_elements = route.get("elements") if isinstance(route.get("elements"), list) else []
        elements = [dict(item) for item in raw_elements if isinstance(item, Mapping)]
        route_report = {"route": route_name, "viewport": viewport, "asset_assignments": []}
        viewport_height = viewport.get("height")
        if isinstance(viewport_height, bool) or not isinstance(viewport_height, (int, float)) or viewport_height <= 0:
            viewport_height = None
        document_height = route.get("document_height")
        meaningful_bottom = route.get("meaningful_content_bottom")
        if (
            viewport_height is not None
            and isinstance(document_height, (int, float))
            and not isinstance(document_height, bool)
            and isinstance(meaningful_bottom, (int, float))
            and not isinstance(meaningful_bottom, bool)
            and document_height > meaningful_bottom + viewport_height * max_empty_scroll_viewport_ratio
        ):
            findings.append(_finding(
                "composition", "blocker", "excessive_empty_scroll",
                "Rendered document height leaves excessive empty scroll after meaningful content.",
                route=route_name,
                viewport=viewport,
                document_height=document_height,
                meaningful_content_bottom=meaningful_bottom,
                maximum_empty_scroll=viewport_height * max_empty_scroll_viewport_ratio,
            ))
        for plan in plans:
            matches = [item for item in elements if str(item.get("asset_id") or "") == plan.asset_id]
            if not matches:
                continue
            assigned[plan.asset_id] += len(matches)
            for element in matches:
                assignment = {"asset_id": plan.asset_id, "route": route_name, "status": "passed"}
                element_box = _browser_box(element.get("box"), f"{plan.asset_id}.box")
                assignment["geometry"] = {
                    "box": dict(element_box) if element_box is not None else None,
                    "intrinsic_width": element.get("intrinsic_width"),
                    "intrinsic_height": element.get("intrinsic_height"),
                    "object_fit": str(element.get("object_fit") or ""),
                    "object_position": str(element.get("object_position") or ""),
                    "container_box": element.get("container_box"),
                }
                if element_box is None:
                    assignment["status"] = "failed"
                    findings.append(_finding(
                        "composition", "blocker", "rendered_geometry_missing",
                        "Rendered composition asset is missing a measurable browser box.",
                        asset_id=plan.asset_id, route=route_name,
                    ))
                tag = str(element.get("tag") or "").strip().lower()
                intrinsic_media = any(
                    isinstance(element.get(key), (int, float)) and not isinstance(element.get(key), bool)
                    and float(element.get(key)) > 0
                    for key in ("intrinsic_width", "intrinsic_height")
                )
                if (
                    element_box is not None
                    and viewport_height is not None
                    and (tag in {"img", "picture", "video", "canvas", "svg"} or intrinsic_media)
                    and element_box["height"] > viewport_height * max_rendered_asset_height_viewport_ratio
                    and not treatment_is_immersive(plan)
                ):
                    assignment["status"] = "failed"
                    findings.append(_finding(
                        "composition", "blocker", "rendered_media_geometry",
                        "Rendered media exceeds the configured viewport-relative height budget.",
                        asset_id=plan.asset_id,
                        route=route_name,
                        viewport=viewport,
                        rendered_height=element_box["height"],
                        viewport_height=viewport_height,
                        maximum_height=viewport_height * max_rendered_asset_height_viewport_ratio,
                    ))
                rendered_hash = str(element.get("asset_sha256") or "").lower()
                if rendered_hash != plan.asset_sha256:
                    assignment["status"] = "failed"
                    findings.append(_finding(
                        "composition", "blocker", "asset_hash_mismatch",
                        "Rendered asset does not match the frozen composition asset hash.",
                        asset_id=plan.asset_id, route=route_name, expected=plan.asset_sha256, actual=rendered_hash,
                    ))
                source = str(element.get("src") or element.get("href") or element.get("external_url") or "")
                is_absolute_http = source.startswith(("http://", "https://", "//"))
                if element.get("external_url") or (is_absolute_http and not _is_local_preview_source(source)):
                    assignment["status"] = "failed"
                    findings.append(_finding(
                        "composition", "blocker", "external_asset_substitution",
                        "Rendered composition asset uses an external source.", asset_id=plan.asset_id, route=route_name,
                    ))
                if plan.focal_region_to_preserve is not None:
                    coverage = element.get("focal_coverage")
                    if isinstance(coverage, bool) or not isinstance(coverage, (int, float)) or float(coverage) < 0.8:
                        assignment["status"] = "failed"
                        findings.append(_finding(
                            "composition", "blocker", "focal_region_not_preserved",
                            "Rendered asset evidence does not preserve the planned focal region.",
                            asset_id=plan.asset_id, route=route_name, coverage=coverage,
                        ))
                route_report["asset_assignments"].append(assignment)

            if plan.logo_rule is not None:
                logo_elements = [item for item in matches if str(item.get("role") or "") == "logo"] or matches
                for logo in logo_elements:
                    logo_box = _browser_box(logo.get("box"), f"{plan.asset_id}.box")
                    if logo_box is None:
                        findings.append(_finding(
                            "composition", "blocker", "logo_geometry_missing",
                            "Logo composition evidence is missing a measurable browser box.",
                            asset_id=plan.asset_id, route=route_name,
                        ))
                        continue
                    clear_padding = plan.logo_rule.clear_space * max(logo_box["width"], logo_box["height"])
                    excluded_roles = set(plan.logo_rule.collision_exclusions)
                    for other in elements:
                        if other is logo or str(other.get("role") or "") not in excluded_roles:
                            continue
                        other_box = _browser_box(other.get("box"), "composition element box")
                        if other_box is not None and _boxes_intersect(logo_box, other_box, clear_padding):
                            findings.append(_finding(
                                "composition", "blocker", "logo_collision",
                                "Logo optical clear space intersects a declared excluded role.",
                                asset_id=plan.asset_id, route=route_name,
                                excluded_role=str(other.get("role") or ""),
                                viewport=viewport,
                            ))
        route_reports.append(route_report)

    for plan in plans:
        if assigned[plan.asset_id] == 0:
            findings.append(_finding(
                "composition", "blocker", "planned_asset_missing",
                "A frozen composition asset was not observed in rendered evidence.", asset_id=plan.asset_id,
            ))
    report = {
        "status": "failed" if findings else "passed",
        "routes": route_reports,
        "planned_assets": sorted(assigned),
        "assigned_assets": {key: value for key, value in sorted(assigned.items())},
    }
    return report, findings


def evaluate_temporal_evidence(
    evidence: Any,
    *,
    signature_behavior_id: str = "",
    max_layout_shift: float = 0.1,
    candidate_sha: str = "",
    experience_plan_hash: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Evaluate measurable temporal evidence without judging taste or style."""
    from ..core.design_contracts import TemporalExperienceEvidence

    if not isinstance(evidence, TemporalExperienceEvidence):
        evidence = TemporalExperienceEvidence.from_dict(evidence)
    findings: list[dict[str, Any]] = []
    if candidate_sha and evidence.candidate_sha != candidate_sha:
        findings.append(_finding(
            "temporal", "blocker", "candidate_identity_mismatch",
            "Temporal evidence belongs to a different candidate than the quality run.",
            expected=candidate_sha, actual=evidence.candidate_sha,
        ))
    if experience_plan_hash and evidence.experience_plan_hash != experience_plan_hash:
        findings.append(_finding(
            "temporal", "blocker", "experience_plan_identity_mismatch",
            "Temporal evidence belongs to a different locked experience plan.",
            expected=experience_plan_hash, actual=evidence.experience_plan_hash,
        ))
    if evidence.console_errors:
        findings.append(_finding("temporal", "blocker", "console_errors", "Temporal evidence contains browser console errors.", count=len(evidence.console_errors)))
    if evidence.network_errors:
        findings.append(_finding("temporal", "blocker", "network_errors", "Temporal evidence contains browser network errors.", count=len(evidence.network_errors)))
    if evidence.resting_state_observations.get("critical_content_visible") is not True:
        findings.append(_finding("temporal", "blocker", "resting_state_incomplete", "Critical content is not complete in the observed resting state."))
    if signature_behavior_id:
        observed = any(
            str(item.get("id") or "") == signature_behavior_id
            and str(item.get("state") or "").lower() in {"observed", "passed", "complete"}
            for item in evidence.animation_observations
        )
        if not observed:
            findings.append(_finding(
                "temporal", "blocker", "signature_behavior_unobserved",
                "The locked signature behavior was not observed in host-owned temporal evidence.",
                signature_behavior_id=signature_behavior_id,
            ))
    layout_shift = 0.0
    for item in evidence.layout_shifts:
        value = item.get("value", item.get("cumulative_layout_shift", 0))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            layout_shift += max(0.0, float(value))
    if layout_shift > max_layout_shift:
        findings.append(_finding(
            "temporal", "blocker", "layout_shift_budget",
            "Temporal evidence exceeds the locked layout-shift budget.",
            value=layout_shift, maximum=max_layout_shift,
        ))
    report = {
        "status": "failed" if findings else "passed",
        "route": evidence.route,
        "viewport": dict(evidence.viewport),
        "reduced_motion": evidence.reduced_motion,
        "frame_phases": [str(item.get("phase") or "") for item in evidence.frames],
        "layout_shift": layout_shift,
        "signature_behavior_id": signature_behavior_id,
    }
    return report, findings


def _bind_temporal_evidence(
    raw: Any,
    *,
    candidate_sha: str,
    experience_plan_hash: str,
) -> TemporalExperienceEvidence:
    """Bind browser-produced temporal observations to the immutable run identity."""
    if isinstance(raw, TemporalExperienceEvidence):
        return raw
    value = dict(raw) if isinstance(raw, Mapping) else {}
    identity_bound = False
    if not value.get("candidate_sha"):
        value["candidate_sha"] = candidate_sha
        identity_bound = True
    if not value.get("experience_plan_hash"):
        value["experience_plan_hash"] = experience_plan_hash
        identity_bound = True
    if identity_bound or not value.get("evidence_hash"):
        value.pop("evidence_hash", None)
        value["evidence_hash"] = canonical_hash(value)
    return TemporalExperienceEvidence.from_dict(value)


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
    ".css", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".html", ".htm",
})
_IMPORT_RE = re.compile(
    r"(?:\bimport\s+(?:[^;\n]+?\s+from\s+)?|\bimport\s*\(|\brequire\s*\()\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_EXTERNAL_RESOURCE_RE = re.compile(
    r"<(script|link|img|source|video|audio)\b[^>]*(?:src|href)\s*=\s*[\"']((?:https?:)?//[^\"']+)",
    re.IGNORECASE | re.DOTALL,
)
_EXTERNAL_CSS_RE = re.compile(
    r"(?:@import\s+(?:url\s*\(\s*)?|url\s*\(\s*)[\"']?(?:https?:)?//",
    re.IGNORECASE,
)
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
# internal scaffold, not generic Next/React conventions.  They are only used
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
        and not any(
            part in {".git", ".opencode", "node_modules", ".next", ".open-next", "out", "dist", "output"}
            for part in Path(path).parts
        )
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
    paths_to_scan = changed
    if policy.operation_kind in {"visual_refinement", "technical_repair"}:
        # A bounded repair may intentionally leave the already-valid native
        # implementation untouched while changing only composition or copy.
        # Validate the complete retained candidate tree for repair operations;
        # changed-file-only scanning would falsely report missing React/GSAP.
        try:
            paths_to_scan = set(
                path for path in _git(repo, "ls-tree", "-r", "--name-only", candidate_sha).splitlines()
                if path
            ) | changed
            if policy.allowed_patterns:
                paths_to_scan = {
                    path for path in paths_to_scan
                    if writable(
                        normalize_path(path),
                        policy.allowed_patterns,
                        allowed_hard_denied_paths=policy.allowed_hard_denied_paths,
                    )
                }
        except RuntimeError:
            paths_to_scan = changed
    host_provisioned_paths = _host_provisioned_paths(repo, policy)
    source_paths = [
        path for path in _native_source_files(repo, paths_to_scan)
        if path not in host_provisioned_paths
    ]
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
    react_source_files: list[str] = []
    gsap_usage_files: list[str] = []
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
        if path.suffix.lower() in {".jsx", ".tsx"} or any(
            package in {"react", "react-dom", "@gsap/react"} for package in imports
        ):
            react_source_files.append(relative)
        for specifier in imports:
            if specifier.startswith((".", "/", "#", "~", "@/", "node:")):
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
            gsap_usage_files.append(relative)
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
    if policy.react_source_required and not react_source_files:
        findings.append(_finding(
            "native_source", "blocker", "react_source_missing",
            "The candidate must include a React implementation source file or React integration.",
        ))
    if policy.gsap_required and not gsap_usage_files:
        findings.append(_finding(
            "native_source", "blocker", "gsap_implementation_missing",
            "The candidate must implement the defining behavior with the approved GSAP runtime.",
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
        "host_provisioned_files": sorted(host_provisioned_paths),
        "imports": imported,
        "external_resources": external_resources,
        "animation_files": sorted(set(animation_files)),
        "react_source_files": sorted(set(react_source_files)),
        "gsap_usage_files": sorted(set(gsap_usage_files)),
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
        and not any(
            part in {".git", ".opencode", "node_modules", ".next", ".open-next", "out", "dist", "output"}
            for part in Path(path).parts
        )
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
        # Font provisions are copied into Next's public boundary. Accept the
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
    blocking = {"blocker", "critical", "serious"}
    return {
        "status": "failed" if any(item.get("severity") in blocking for item in findings) else "passed",
        "files": len(files),
        "output_dir": policy.output_dir,
    }, findings


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


def _bounded_browser_text(value: Any, *, maximum: int = 600) -> Any:
    """Keep browser style fingerprints useful without persisting asset data."""
    if not isinstance(value, str) or len(value) <= maximum:
        return value
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"<omitted sha256={digest} chars={len(value)}>"


def _compact_rendered_fingerprint(value: Any) -> Any:
    """Bound descendant fingerprints produced by the browser probes.

    A CSS ``background-image`` can contain a complete data URL, and the same
    signature fingerprint is repeated in every animation sample and scroll
    state.  The host has already compared these values before persistence, so
    retaining the full descendant tree would add diagnostic bulk without
    adding evidence. Preserve the measured top-level style and a count/hash
    for omitted descendants instead.
    """
    if not isinstance(value, Mapping):
        return _bounded_browser_text(value)
    compact: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"descendants", "nodes"} and isinstance(item, (list, tuple)):
            encoded = json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
            compact[f"{key}_count"] = len(item)
            compact[f"{key}_hash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
            continue
        if key in {"backgroundImage", "background_image", "fingerprint"}:
            compact[str(key)] = _bounded_browser_text(item)
            continue
        compact[str(key)] = _compact_rendered_fingerprint(item) if isinstance(item, Mapping) else _bounded_browser_text(item)
    return compact


def _compact_observable_snapshot(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    compact = dict(value)
    nodes = compact.get("nodes")
    if isinstance(nodes, (list, tuple)):
        compact["nodes"] = [
            {
                "key": str(node.get("key") or ""),
                "tag": str(node.get("tag") or ""),
                "visible": node.get("visible") is True,
            }
            for node in nodes[:12]
            if isinstance(node, Mapping)
        ]
    signatures = compact.get("signature_behaviors")
    if isinstance(signatures, (list, tuple)):
        compact["signature_behaviors"] = [
            {
                "id": str(item.get("id") or ""),
                "state": str(item.get("state") or ""),
                "visible": item.get("visible") is True,
            }
            for item in signatures[:12]
            if isinstance(item, Mapping)
        ]
    return compact


def _observable_summary(value: Any) -> dict[str, Any]:
    """Retain the scroll probe's aggregate facts, not repeated DOM snapshots."""
    if not isinstance(value, Mapping):
        return {}
    nodes = value.get("nodes") if isinstance(value.get("nodes"), (list, tuple)) else ()
    signatures = value.get("signature_behaviors") if isinstance(value.get("signature_behaviors"), (list, tuple)) else ()
    return {
        "node_count": len(nodes),
        "visible_node_count": sum(1 for item in nodes if isinstance(item, Mapping) and item.get("visible") is True),
        "signature_behavior_ids": [
            str(item.get("id") or "")
            for item in signatures
            if isinstance(item, Mapping) and str(item.get("id") or "")
        ][:20],
        "critical_content_visible": value.get("critical_content_visible") is True,
    }


def _compact_journey_conditions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    compacted: list[dict[str, Any]] = []
    for item in value[:100]:
        if not isinstance(item, Mapping):
            continue
        compacted.append({
            key: item[key]
            for key in (
                "condition_id",
                "scene_id",
                "trigger",
                "state",
                "completion",
                "visible",
                "interactive",
                "observed_transition",
            )
            if key in item
        })
    return compacted


def _compact_observable_delta(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    compact = dict(value)
    changed_nodes = compact.get("changed_nodes")
    compact["changed_node_count"] = len(changed_nodes) if isinstance(changed_nodes, (list, tuple)) else 0
    compact["changed_node_keys"] = [
        str(item.get("key") or "")
        for item in (changed_nodes or ())
        if isinstance(item, Mapping) and str(item.get("key") or "")
    ][:20]
    compact.pop("changed_nodes", None)
    signatures = compact.get("signature_behaviors")
    if isinstance(signatures, (list, tuple)):
        compact["signature_behaviors"] = [
            {
                "id": str(item.get("id") or ""),
                "state": str(item.get("state") or ""),
                "observed_via": str(item.get("observed_via") or ""),
            }
            for item in signatures[:20]
            if isinstance(item, Mapping)
        ]
    return compact


def _compact_interaction_state(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    compact = dict(value)
    for key in ("before", "after"):
        if isinstance(compact.get(key), Mapping):
            compact[key] = _compact_observable_snapshot(compact[key])
    observations = compact.get("animation_observations")
    if isinstance(observations, (list, tuple)):
        compact["animation_observations"] = [
            {
                **dict(item),
                "fingerprint": _bounded_browser_text(item.get("fingerprint")),
            }
            for item in observations[:20]
            if isinstance(item, Mapping)
        ]
    return compact


def _compact_motion_snapshot(value: Any) -> Any:
    """Keep rendered motion deltas while bounding browser diagnostics.

    Playwright records a node snapshot at every scroll position for every route
    and viewport. Those snapshots are useful while debugging locally, but
    retaining every node in the durable quality report duplicates tens of
    thousands of characters. Keep the bounded samples and aggregate delta.
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
    samples = compact.get("observable_samples")
    if isinstance(samples, list):
        compact["observable_samples"] = [
            {
                "scroll_y": sample.get("scroll_y"),
                "scroll_height": sample.get("scroll_height"),
                "node_count": len(sample.get("nodes") or ()) if isinstance(sample, Mapping) else 0,
                "signature_behavior_count": len(sample.get("signature_behaviors") or ()) if isinstance(sample, Mapping) else 0,
            }
            for sample in (samples[0:1] + samples[-1:] if len(samples) > 2 else samples)
            if isinstance(sample, Mapping)
        ]
    if isinstance(compact.get("observable"), Mapping):
        compact["observable_summary"] = _observable_summary(compact.pop("observable"))
    if isinstance(compact.get("journey_conditions"), (list, tuple)):
        compact["journey_conditions"] = _compact_journey_conditions(compact["journey_conditions"])
    if isinstance(compact.get("scroll_states"), (list, tuple)):
        compact["scroll_states"] = [
            _compact_scroll_state(state)
            for state in compact["scroll_states"][:12]
            if isinstance(state, Mapping)
        ]
    for key in ("observable_delta", "scroll_observable_delta"):
        if isinstance(compact.get(key), Mapping):
            compact[key] = _compact_observable_delta(compact[key])
    if isinstance(compact.get("signature_behaviors"), (list, tuple)):
        compact["signature_behaviors"] = [
            {
                **dict(item),
                "fingerprint": _bounded_browser_text(item.get("fingerprint")),
            }
            for item in compact["signature_behaviors"][:20]
            if isinstance(item, Mapping)
        ]
    return compact


def _compact_scroll_state(value: Any) -> dict[str, Any]:
    state = _compact_motion_snapshot(value)
    if not isinstance(state, Mapping):
        return {}
    return {
        key: state[key]
        for key in (
            "position",
            "scroll_y",
            "scroll_height",
            "motion_node_count",
            "signature_behaviors",
            "journey_conditions",
            "observable_summary",
        )
        if key in state
    }


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
            route["scroll_states"] = [_compact_scroll_state(state) for state in states]
        if isinstance(route.get("interaction_state"), Mapping):
            route["interaction_state"] = _compact_interaction_state(route["interaction_state"])
        for key in ("journey_conditions", "journey_conditions_before", "journey_conditions_after"):
            if isinstance(route.get(key), (list, tuple)):
                route[key] = _compact_journey_conditions(route[key])
        routes.append(route)
    result["routes"] = routes
    states = result.get("scroll_states")
    if isinstance(states, list):
        result["scroll_states"] = [
            {
                **dict(item),
                "states": [
                    _compact_scroll_state(state)
                    for state in (item.get("states") or ())
                ],
            }
            for item in states
            if isinstance(item, Mapping)
        ]
    if isinstance(result.get("journey_conditions"), (list, tuple)):
        result["journey_conditions"] = _compact_journey_conditions(result["journey_conditions"])
    return result


def _temporal_contract_item(value: Mapping[str, Any]) -> dict[str, Any]:
    """Separate route-level journey snapshots from strict temporal evidence."""
    item = dict(value)
    item.pop("journey_conditions_before", None)
    item.pop("journey_conditions_after", None)
    return item


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
    journey_evidence: list[dict[str, Any]] = []
    temporal_evidence: list[dict[str, Any]] = []
    external_request_evidence: list[dict[str, Any]] = []
    for viewport in policy.viewports:
        try:
            result = _compact_browser_result(dict(browser.inspect(output, viewport)))
        except Exception as exc:  # noqa: BLE001
            return {"status": "unavailable"}, [_finding("browser", "incomplete", "browser_unavailable", safe_provider_message(str(exc)))], True
        evidence["viewports"].append({"viewport": dict(viewport), "result": result})
        temporal_evidence.extend(
            _temporal_contract_item(item)
            for item in (result.get("temporal_evidence") or ())
            if isinstance(item, Mapping)
        )
        temporal_evidence.extend(
            _temporal_contract_item(item)
            for route_item in (result.get("routes") or ())
            if isinstance(route_item, Mapping)
            for item in (route_item.get("temporal_evidence") or ())
            if isinstance(item, Mapping)
        )
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
            if route.get("journey_conditions_before") or route.get("journey_conditions_after"):
                journey_evidence.append({
                    "viewport": dict(viewport),
                    "route": route_name,
                    "before": list(route.get("journey_conditions_before") or ()),
                    "after": list(route.get("journey_conditions_after") or ()),
                })
        for route_name, motion_preferences in motion_records:
            motion_evidence.append({
                "viewport": dict(viewport),
                **({"route": route_name} if route_name else {}),
                "preferences": dict(motion_preferences),
            })
            normal_motion = motion_preferences.get("no-preference") or {}
            reduced_motion = motion_preferences.get("reduce") or {}
            reduced_delta = reduced_motion.get("observable_delta") or {}
            if reduced_motion.get("motion_observed") is True or reduced_delta.get("observed") is True:
                findings.append(_finding(
                    "browser", "blocker", "reduced_motion_unsettled",
                    "Reduced-motion emulation still changed rendered geometry or style after readiness.",
                    viewport=dict(viewport),
                    **({"route": route_name} if route_name else {}),
                    details={"no_preference": normal_motion.get("observable_delta") or {}, "reduce": reduced_delta},
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
        hidden_resting_text = result.get("hidden_resting_text")
        if hidden_resting_text:
            findings.append(_finding(
                "browser", "blocker", "resting_text_hidden",
                "Page text is invisible at rest (display none, visibility hidden, or opacity zero).",
                viewport=dict(viewport), details=hidden_resting_text,
            ))
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
    evidence["journey_conditions"] = journey_evidence
    evidence["temporal_evidence"] = temporal_evidence
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
    output_artifact_publisher=None,
    build_env: Mapping[str, str] | None = None,
    experience_plan: Any | None = None,
    temporal_evidence: Sequence[Any] = (),
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
    output_artifact_evidence: dict[str, Any] = {"status": "skipped", "reason": "artifact_store_not_configured"}
    output_blockers = {
        "blocker",
        "critical",
        "serious",
    }
    if callable(output_artifact_publisher) and not any(
        item.get("severity") in output_blockers for item in output_findings
    ):
        try:
            output_artifact_evidence = {
                "status": "passed",
                **dict(output_artifact_publisher(workspace / policy.output_dir)),
            }
        except Exception as exc:  # noqa: BLE001 - retain a durable build-boundary failure
            output_artifact_evidence = {"status": "failed", "error": safe_provider_message(str(exc))}
            findings.append(_finding(
                "build", "blocker", "output_artifact_failed",
                "The authoritative build output could not be retained as an immutable preview artifact.",
                evidence=output_artifact_evidence,
            ))
    content_evidence, content_findings = _content_findings(workspace / policy.output_dir, policy)
    findings.extend(content_findings)
    conversion_evidence, conversion_findings = _conversion_findings(workspace / policy.output_dir, policy)
    findings.extend(conversion_findings)
    manifest_evidence, manifest_findings = _manifest_findings(workspace, policy)
    findings.extend(manifest_findings)
    browser_evidence, browser_findings, browser_incomplete = _browser_findings(workspace / policy.output_dir, policy, browser)
    findings.extend(browser_findings)
    composition_evidence: dict[str, Any] = {"status": "skipped", "reason": "experience_plan_not_supplied"}
    journey_evidence_report: dict[str, Any] = {"status": "skipped", "reason": "experience_plan_not_supplied"}
    temporal_evidence_report: dict[str, Any] = {"status": "skipped", "reason": "experience_plan_not_supplied"}
    experience_plan_hash = ""
    if experience_plan is not None:
        from ..core.design_contracts import ExperiencePlanBundle

        try:
            plan = experience_plan if isinstance(experience_plan, ExperiencePlanBundle) else ExperiencePlanBundle.from_dict(experience_plan)
            experience_plan_hash = plan.content_hash
        except Exception as exc:  # noqa: BLE001 - report malformed creative input as an incomplete gate
            composition_evidence = {"status": "incomplete", "reason": "experience_plan_invalid"}
            temporal_evidence_report = {"status": "incomplete", "reason": "experience_plan_invalid"}
            findings.append(_finding(
                "experience_plan", "incomplete", "experience_plan_invalid",
                "The locked experience plan could not be validated before deterministic review.",
                error=str(exc)[:300],
            ))
        else:
            journey = plan.experience_journey
            expected_condition_ids = set(journey.must_pass_condition_ids)
            condition_records: list[dict[str, Any]] = []
            reduced_condition_records: list[dict[str, Any]] = []
            for viewport_item in browser_evidence.get("viewports") or ():
                if not isinstance(viewport_item, Mapping):
                    continue
                viewport = viewport_item.get("viewport") if isinstance(viewport_item.get("viewport"), Mapping) else {}
                result = viewport_item.get("result") if isinstance(viewport_item.get("result"), Mapping) else {}
                top_level_preferences = result.get("motion_preferences")
                if isinstance(top_level_preferences, Mapping):
                    reduced = top_level_preferences.get("reduce")
                    if isinstance(reduced, Mapping):
                        for item in reduced.get("journey_conditions") or ():
                            if isinstance(item, Mapping):
                                reduced_condition_records.append({
                                    "viewport": dict(viewport),
                                    "route": "",
                                    **dict(item),
                                })
                for route_item in result.get("routes") or ():
                    if not isinstance(route_item, Mapping):
                        continue
                    route_name = str(route_item.get("route") or "")
                    for item in list(route_item.get("journey_conditions_before") or ()) + list(route_item.get("journey_conditions_after") or ()):
                        if isinstance(item, Mapping):
                                condition_records.append({
                                    "viewport": dict(viewport),
                                    "route": route_name,
                                    **dict(item),
                                })
                    preferences = route_item.get("motion_preferences")
                    if isinstance(preferences, Mapping):
                        reduced = preferences.get("reduce")
                        if isinstance(reduced, Mapping):
                            for item in reduced.get("journey_conditions") or ():
                                if isinstance(item, Mapping):
                                    reduced_condition_records.append({
                                        "viewport": dict(viewport),
                                        "route": route_name,
                                        **dict(item),
                                    })
                        for preference_name, destination in (
                            ("no-preference", condition_records),
                            ("reduce", reduced_condition_records),
                        ):
                            preference = preferences.get(preference_name)
                            if not isinstance(preference, Mapping):
                                continue
                            for scroll_state in preference.get("scroll_states") or ():
                                if not isinstance(scroll_state, Mapping):
                                    continue
                                for item in scroll_state.get("journey_conditions") or ():
                                    if not isinstance(item, Mapping):
                                        continue
                                    destination.append({
                                        "viewport": dict(viewport),
                                        "route": route_name,
                                        "observed_via": "progressive_scroll",
                                        "scroll_position": scroll_state.get("position"),
                                        **dict(item),
                                    })
            observed_condition_ids = {
                str(item.get("condition_id") or "").strip()
                for item in condition_records
                if item.get("visible") is True and str(item.get("condition_id") or "").strip()
            }
            observed_reduced_ids = {
                str(item.get("condition_id") or "").strip()
                for item in reduced_condition_records
                if item.get("visible") is True and str(item.get("condition_id") or "").strip()
            }
            missing_condition_ids = sorted(expected_condition_ids - observed_condition_ids)
            missing_reduced_ids = sorted(expected_condition_ids - observed_reduced_ids)
            transitioned_ids = sorted({
                str(item.get("condition_id") or "").strip()
                for item in condition_records
                if str(item.get("condition_id") or "").strip()
                and item.get("observed_transition") is True
            })
            scene_order = {
                str(scene.get("id") or ""): int(scene.get("order") or 0)
                for scene in journey.scenes
                if isinstance(scene, Mapping) and str(scene.get("id") or "").strip()
            }
            scene_by_condition = {
                str(condition_id): str(scene.get("id") or "")
                for scene in journey.scenes
                if isinstance(scene, Mapping)
                for condition_id in (scene.get("acceptance_condition_ids") or ())
            }
            expected_scene_ids = [scene_id for scene_id, _ in sorted(scene_order.items(), key=lambda item: item[1])]
            def canonical_scene_id(item: Mapping[str, Any]) -> str:
                condition_id = str(item.get("condition_id") or "").strip()
                mapped = scene_by_condition.get(condition_id, "")
                if mapped:
                    return mapped
                scene_id = str(item.get("scene_id") or "").strip()
                return scene_id if scene_id in scene_order else ""

            def ordered_marker_scene_id(item: Mapping[str, Any]) -> str:
                """Return only an explicit rendered scene marker.

                Acceptance conditions may be scene-owned in the locked plan
                while remaining page-level in the rendered evidence. Mapping
                those condition IDs back to scenes is useful for coverage and
                transition accounting, but it would manufacture an ordering
                event when such a condition appears before the scene marker.
                The ordered-path proof must therefore use the marker's own
                scene ID and ignore unscoped conditions.
                """
                scene_id = str(item.get("scene_id") or "").strip()
                return scene_id if scene_id in scene_order else ""

            visible_scene_ids = {
                canonical_scene_id(item)
                for item in condition_records
                if item.get("visible") is True and canonical_scene_id(item)
            }
            transitioned_scene_ids = {
                canonical_scene_id(item)
                for item in condition_records
                if item.get("observed_transition") is True
            }
            transitioned_scene_ids.discard("")
            missing_transition_scene_ids = sorted(
                (set(expected_scene_ids) - transitioned_scene_ids),
                key=lambda scene_id: scene_order.get(scene_id, 0),
            )
            ordered_scene_paths: list[dict[str, Any]] = []
            grouped_records: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
            for item in condition_records:
                if item.get("visible") is not True:
                    continue
                key = (
                    str(item.get("route") or ""),
                    str((item.get("viewport") or {}).get("name") or ""),
                )
                grouped_records.setdefault(key, []).append(item)
            for (route_name, viewport_name), records in grouped_records.items():
                scene_ids: list[str] = []
                for item in records:
                    scene_id = ordered_marker_scene_id(item)
                    if scene_id in scene_order and scene_id not in scene_ids:
                        scene_ids.append(scene_id)
                if scene_ids == expected_scene_ids:
                    ordered_scene_paths.append({
                        "route": route_name,
                        "viewport": viewport_name,
                        "scene_ids": scene_ids,
                    })
            trigger_mismatches: list[dict[str, Any]] = []
            seen_trigger_mismatches: set[tuple[str, str, str]] = set()

            def trigger_family(value: Any) -> str:
                # Scene prose is intentionally human-readable (for example,
                # "the light node reaches the exit marker").  Substring
                # matching that prose against candidate condition triggers
                # turns legitimate condition-level interactions into false
                # mismatches. Only compare when the plan uses the explicit
                # machine-readable trigger prefixes accepted by the browser
                # evidence contract.
                text = str(value or "").strip().casefold()
                prefix = re.match(r"^(scroll|viewport|progress|focus|keyboard|pointer|hover|enter|click|tap|interaction|load)(?::|\s|$)", text)
                if not prefix:
                    return ""
                token = prefix.group(1)
                if token in {"scroll", "viewport", "progress"}:
                    return "scroll"
                if token in {"focus", "keyboard"}:
                    return "focus"
                if token in {"pointer", "hover", "enter"}:
                    return "pointer"
                if token in {"click", "tap", "interaction"}:
                    return "interaction"
                return "load"

            for item in condition_records:
                scene_id = canonical_scene_id(item)
                actual_trigger = str(item.get("trigger") or "").strip()
                if not scene_id or not actual_trigger or scene_id not in scene_order:
                    continue
                expected_scene = next(
                    (scene for scene in journey.scenes if str(scene.get("id") or "") == scene_id),
                    None,
                )
                expected_trigger = str((expected_scene or {}).get("trigger") or "").strip()
                expected_family = trigger_family(expected_trigger)
                actual_family = trigger_family(actual_trigger)
                key = (scene_id, expected_family, actual_family)
                if expected_family and actual_family and expected_family != actual_family and key not in seen_trigger_mismatches:
                    seen_trigger_mismatches.add(key)
                    trigger_mismatches.append({
                        "scene_id": scene_id,
                        "expected": expected_trigger,
                        "actual": actual_trigger,
                    })
            journey_evidence_report = {
                "status": "passed",
                "experience_plan_hash": experience_plan_hash,
                "expected_condition_ids": sorted(expected_condition_ids),
                "observed_condition_ids": sorted(observed_condition_ids),
                "reduced_motion_condition_ids": sorted(observed_reduced_ids),
                "transitioned_condition_ids": transitioned_ids,
                "expected_scene_ids": expected_scene_ids,
                "observed_scene_ids": sorted(visible_scene_ids, key=lambda scene_id: scene_order.get(scene_id, 0)),
                "transitioned_scene_ids": sorted(transitioned_scene_ids, key=lambda scene_id: scene_order.get(scene_id, 0)),
                "ordered_scene_paths": ordered_scene_paths,
                "trigger_mismatches": trigger_mismatches,
                "records": condition_records[:120],
            }
            if missing_condition_ids:
                journey_evidence_report["status"] = "incomplete"
                findings.append(_finding(
                    "experience_journey", "incomplete", "journey_condition_missing",
                    "The rendered candidate did not expose every locked journey condition as visible browser evidence.",
                    experience_plan_hash=experience_plan_hash,
                    missing_condition_ids=missing_condition_ids,
                ))
            if missing_reduced_ids:
                journey_evidence_report["status"] = "incomplete"
                findings.append(_finding(
                    "experience_journey", "incomplete", "journey_reduced_motion_missing",
                    "The rendered candidate did not expose every locked journey condition under reduced-motion emulation.",
                    experience_plan_hash=experience_plan_hash,
                    missing_condition_ids=missing_reduced_ids,
                ))
            if not transitioned_ids:
                journey_evidence_report["status"] = "failed"
                findings.append(_finding(
                    "experience_journey", "blocker", "journey_transition_unobserved",
                    "The browser review observed journey markers but no host-measured rendered transition.",
                    experience_plan_hash=experience_plan_hash,
                ))
            if missing_transition_scene_ids:
                journey_evidence_report["status"] = "failed"
                findings.append(_finding(
                    "experience_journey", "blocker", "journey_scene_transition_missing",
                    "The browser review did not observe a rendered transition for every ordered journey scene.",
                    experience_plan_hash=experience_plan_hash,
                    missing_scene_ids=missing_transition_scene_ids,
                ))
            if not ordered_scene_paths:
                journey_evidence_report["status"] = "failed"
                findings.append(_finding(
                    "experience_journey", "blocker", "journey_scene_order_unobserved",
                    "The browser review did not observe the locked scenes in their declared order on one complete path.",
                    experience_plan_hash=experience_plan_hash,
                    expected_scene_ids=expected_scene_ids,
                ))
            if trigger_mismatches:
                journey_evidence_report["status"] = "failed"
                findings.append(_finding(
                    "experience_journey", "blocker", "journey_trigger_mismatch",
                    "Rendered journey markers report a trigger family different from the locked scene contract.",
                    experience_plan_hash=experience_plan_hash,
                    mismatches=trigger_mismatches,
                ))
            rendered_composition: list[dict[str, Any]] = []
            for viewport_item in browser_evidence.get("viewports") or ():
                if not isinstance(viewport_item, Mapping):
                    continue
                viewport = viewport_item.get("viewport") if isinstance(viewport_item.get("viewport"), Mapping) else {}
                result = viewport_item.get("result") if isinstance(viewport_item.get("result"), Mapping) else {}
                for route_item in result.get("routes") or ():
                    if not isinstance(route_item, Mapping):
                        continue
                    elements = route_item.get("composition_elements") or route_item.get("elements")
                    rendered_composition.append({
                        "route": route_item.get("route"),
                        "viewport": dict(viewport),
                        "elements": list(elements) if isinstance(elements, list) else [],
                        "document_height": route_item.get("document_height"),
                        "meaningful_content_bottom": route_item.get("meaningful_content_bottom"),
                    })
            if not plan.asset_composition_plan:
                # An asset-free intake has no frozen role assignment to prove.
                # Do not turn the absence of supplied media into an artificial
                # owner blocker or require the candidate to invent composition
                # markers for assets that do not exist.
                composition_evidence = {
                    "status": "passed",
                    "reason": "no_locked_asset_composition",
                    "routes": rendered_composition,
                }
            elif not rendered_composition or not any(item.get("elements") for item in rendered_composition):
                composition_evidence = {"status": "incomplete", "reason": "browser_composition_roles_missing"}
                findings.append(_finding(
                    "composition", "incomplete", "composition_evidence_missing",
                    "The locked composition has no role-based browser evidence for its asset assignments.",
                    experience_plan_hash=experience_plan_hash,
                ))
            else:
                composition_evidence, composition_findings = evaluate_composition_plan(
                    plan.asset_composition_plan,
                    rendered_composition,
                    max_rendered_asset_height_viewport_ratio=policy.max_rendered_asset_height_viewport_ratio,
                    max_empty_scroll_viewport_ratio=policy.max_empty_scroll_viewport_ratio,
                    immersive_asset_ids=policy.immersive_asset_ids,
                )
                findings.extend(composition_findings)
            signature = plan.behavior_system.signature_behavior
            signature_id = str(signature.get("id") or "") if isinstance(signature, Mapping) else ""
            rendered_motion_observed = False
            signature_motion_observed = False
            for viewport_item in browser_evidence.get("viewports") or ():
                if not isinstance(viewport_item, Mapping):
                    continue
                result = viewport_item.get("result") if isinstance(viewport_item.get("result"), Mapping) else {}
                preferences = result.get("motion_preferences")
                if isinstance(preferences, Mapping):
                    normal = preferences.get("no-preference") if isinstance(preferences.get("no-preference"), Mapping) else {}
                    delta = normal.get("observable_delta") if isinstance(normal.get("observable_delta"), Mapping) else {}
                    rendered_motion_observed = rendered_motion_observed or bool(
                        normal.get("motion_observed") is True or delta.get("observed") is True
                    )
                    signature_motion_observed = signature_motion_observed or any(
                        isinstance(item, Mapping)
                        and str(item.get("id") or "") == signature_id
                        and str(item.get("state") or "").lower() in {"observed", "complete", "passed"}
                        for item in delta.get("signature_behaviors") or ()
                    )
                for route_item in result.get("routes") or ():
                    if not isinstance(route_item, Mapping):
                        continue
                    route_preferences = route_item.get("motion_preferences")
                    if isinstance(route_preferences, Mapping):
                        normal = route_preferences.get("no-preference") if isinstance(route_preferences.get("no-preference"), Mapping) else {}
                        delta = normal.get("observable_delta") if isinstance(normal.get("observable_delta"), Mapping) else {}
                        rendered_motion_observed = rendered_motion_observed or bool(
                            normal.get("motion_observed") is True or delta.get("observed") is True
                        )
                        signature_motion_observed = signature_motion_observed or any(
                            isinstance(item, Mapping)
                            and str(item.get("id") or "") == signature_id
                            and str(item.get("state") or "").lower() in {"observed", "complete", "passed"}
                            for item in delta.get("signature_behaviors") or ()
                        )
                temporal_candidates = list(result.get("temporal_evidence") or ())
                temporal_candidates.extend(
                    item
                    for route_item in result.get("routes") or ()
                    if isinstance(route_item, Mapping)
                    for item in (route_item.get("temporal_evidence") or ())
                )
                for temporal_item in temporal_candidates:
                    if not isinstance(temporal_item, Mapping):
                        continue
                    signature_motion_observed = signature_motion_observed or any(
                        isinstance(item, Mapping)
                        and str(item.get("id") or "") == signature_id
                        and str(item.get("state") or "").lower() in {"observed", "complete", "passed"}
                        for item in temporal_item.get("animation_observations") or ()
                    )
            if signature_id and not signature_motion_observed:
                findings.append(_finding(
                    "motion", "blocker", "motion_behavior_unobserved",
                    "The locked signature behavior did not produce a measurable rendered change in the owner surface.",
                    experience_plan_hash=experience_plan_hash,
                    signature_behavior_id=signature_id,
                ))
            elif not signature_id and not rendered_motion_observed:
                findings.append(_finding(
                    "motion", "blocker", "motion_unobserved",
                    "The owner surface did not produce a measurable rendered motion delta after hydration.",
                    experience_plan_hash=experience_plan_hash,
                ))
            budget = plan.behavior_system.performance_budget
            raw_budget = budget.get("max_layout_shift", budget.get("max_cumulative_layout_shift", 0.1)) if isinstance(budget, Mapping) else 0.1
            try:
                max_layout_shift = max(0.0, float(raw_budget))
            except (TypeError, ValueError):
                max_layout_shift = 0.1
            temporal_items = list(temporal_evidence or browser_evidence.get("temporal_evidence") or ())
            if not temporal_items:
                temporal_evidence_report = {"status": "incomplete", "reason": "temporal_evidence_missing", "experience_plan_hash": experience_plan_hash}
                findings.append(_finding(
                    "temporal", "incomplete", "temporal_evidence_missing",
                    "Static browser screenshots cannot pass the locked signature-behavior gate without temporal evidence.",
                    experience_plan_hash=experience_plan_hash,
                ))
            else:
                temporal_reports: list[dict[str, Any]] = []
                temporal_findings: list[dict[str, Any]] = []
                for item in temporal_items:
                    try:
                        bound = _bind_temporal_evidence(
                            item,
                            candidate_sha=candidate_sha,
                            experience_plan_hash=experience_plan_hash,
                        )
                        report, item_findings = evaluate_temporal_evidence(
                            bound,
                            signature_behavior_id=signature_id,
                            max_layout_shift=max_layout_shift,
                            candidate_sha=candidate_sha,
                            experience_plan_hash=experience_plan_hash,
                        )
                        temporal_reports.append(report)
                        temporal_findings.extend(item_findings)
                    except Exception as exc:  # noqa: BLE001 - malformed evidence is an incomplete gate
                        temporal_findings.append(_finding(
                            "temporal", "incomplete", "temporal_evidence_invalid",
                            "Temporal browser evidence could not be validated against the locked plan.",
                            error=str(exc)[:300],
                        ))
                findings.extend(temporal_findings)
                temporal_evidence_report = {
                    "status": "failed" if any(item.get("severity") in {"blocker", "critical", "serious"} for item in temporal_findings) else "incomplete" if temporal_findings else "passed",
                    "experience_plan_hash": experience_plan_hash,
                    "reports": temporal_reports,
                }
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
            # The detailed, host-owned records remain under evidence.browser.
            # Do not duplicate every motion sample here: a long page can
            # produce thousands of repeated scroll fingerprints and push the
            # persisted quality contract over its diagnostic bound.
            "source": "evidence.browser",
            "viewport_count": len(browser_evidence.get("viewports") or ()),
            "motion_preference_count": len(browser_evidence.get("motion_preferences") or ()),
            "scroll_state_count": sum(
                len(item.get("states") or ())
                for item in (browser_evidence.get("scroll_states") or ())
                if isinstance(item, Mapping)
            ),
            "interaction_state_count": len(browser_evidence.get("interaction_states") or ()),
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
        "output_artifact": output_artifact_evidence,
            "content": content_evidence,
            "conversion": conversion_evidence,
            "manifest": manifest_evidence,
            "motion": motion_evidence,
            "browser": browser_evidence,
            "composition": composition_evidence,
            "experience_journey": journey_evidence_report,
            "temporal": temporal_evidence_report,
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
            "composition": composition_evidence.get("status"),
            "experience_journey": journey_evidence_report.get("status"),
            "temporal": temporal_evidence_report.get("status"),
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
    output_artifact_publisher=None,
    build_env: Mapping[str, str] | None = None,
    experience_plan: Any | None = None,
    temporal_evidence: Sequence[Any] = (),
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
            # Next's npm bin shims are executable files, so checking a
            # committed candidate out under /tmp makes `npm run check` fail
            # with a misleading "next: Permission denied". Keep the
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
            output_artifact_publisher=output_artifact_publisher,
            build_env=build_env,
            experience_plan=experience_plan,
            temporal_evidence=temporal_evidence,
        )
    finally:
        if temporary_workspace is not None:
            try:
                _git(root, "worktree", "remove", "--force", str(temporary_workspace))
            except RuntimeError:
                pass
            shutil.rmtree(temporary_workspace, ignore_errors=True)


__all__ = ["BrowserQualityAdapter", "QualityPolicy", "run_quality_gates"]
