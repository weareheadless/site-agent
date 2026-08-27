"""Owner-facing renderers for prepared artifacts.

Renderers turn provider payloads into short, typed preview sections. They do
not execute work and intentionally omit operations, file paths, and provider
diagnostics from the default owner view.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, Protocol

from ..core.contracts import Artifact


@dataclass(frozen=True)
class PreviewSection:
    label: str
    body: str

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "body": self.body}


@dataclass(frozen=True)
class ArtifactPreview:
    title: str
    summary: str
    renderer: str
    sections: tuple[PreviewSection, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "renderer": self.renderer,
            "sections": [section.to_dict() for section in self.sections],
        }


class ArtifactRenderer(Protocol):
    def __call__(self, artifact: Artifact) -> ArtifactPreview:
        ...


def _text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ""


def _site_change(artifact: Artifact) -> ArtifactPreview:
    data = artifact.preview_data
    body = _text(data, "body") or _text(data, "description") or artifact.summary
    sections = [PreviewSection("What changes", body)]
    areas = data.get("areas")
    if isinstance(areas, list):
        labels = [item.strip() for item in areas if isinstance(item, str) and item.strip()]
        if labels:
            sections.append(PreviewSection("Areas involved", ", ".join(labels[:8])))
    return ArtifactPreview(artifact.title, artifact.summary, "site_change", tuple(sections))


def _article(artifact: Artifact) -> ArtifactPreview:
    data = artifact.preview_data
    body = _text(data, "body") or _text(data, "text") or artifact.summary
    sections = [PreviewSection("Article", body)]
    why = _text(data, "why")
    if why:
        sections.append(PreviewSection("Why it matters", why))
    return ArtifactPreview(artifact.title, artifact.summary, "article", tuple(sections))


def _field_lines(data: Mapping[str, Any]) -> list[str]:
    hidden = {
        "build_log",
        "capability_id",
        "command",
        "commands",
        "files",
        "logs",
        "operations",
        "ops",
        "paths",
        "provider_id",
    }
    lines = []
    for key, value in data.items():
        if str(key).lower() in hidden:
            continue
        if isinstance(value, (str, int, float, bool)) and str(value).strip():
            label = str(key).replace("_", " ").strip().capitalize()
            lines.append(f"{label}: {value}")
    return lines


def _business_information(artifact: Artifact) -> ArtifactPreview:
    before = artifact.preview_data.get("before")
    after = artifact.preview_data.get("after")
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        sections = []
        before_lines = _field_lines(before)
        after_lines = _field_lines(after)
        if before_lines:
            sections.append(PreviewSection("Before", "\n".join(before_lines[:20])))
        if after_lines:
            sections.append(PreviewSection("After", "\n".join(after_lines[:20])))
        if sections:
            return ArtifactPreview(
                artifact.title,
                artifact.summary,
                "business_information",
                tuple(sections),
            )
    body = "\n".join(_field_lines(artifact.preview_data)[:20]) or artifact.summary
    return ArtifactPreview(
        artifact.title,
        artifact.summary,
        "business_information",
        (PreviewSection("Information", body),),
    )


def _social_post(artifact: Artifact) -> ArtifactPreview:
    data = artifact.preview_data
    body = _text(data, "text") or _text(data, "body") or artifact.summary
    return ArtifactPreview(artifact.title, artifact.summary, "social_post", (PreviewSection("Post", body),))


def _generic(artifact: Artifact) -> ArtifactPreview:
    body = _text(artifact.preview_data, "body") or _text(artifact.preview_data, "text") or artifact.summary
    return ArtifactPreview(artifact.title, artifact.summary, artifact.renderer, (PreviewSection("Preview", body),))


_RENDERERS: dict[str, ArtifactRenderer] = {
    "site_change": _site_change,
    "site-change": _site_change,
    "article": _article,
    "business_information": _business_information,
    "business-information": _business_information,
    "social_post": _social_post,
    "social-post": _social_post,
}


def render_artifact(artifact: Artifact) -> ArtifactPreview:
    renderer = _RENDERERS.get(artifact.renderer.lower(), _generic)
    return renderer(artifact)


__all__ = ["ArtifactPreview", "ArtifactRenderer", "PreviewSection", "render_artifact"]
