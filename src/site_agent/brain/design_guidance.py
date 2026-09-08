"""Canonical loading of the trusted design judgment used by intake and build."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.design_contracts import canonical_hash


REQUIRED_DESIGN_SKILLS = (
    "design-core.md",
    "frontend-design.md",
    "high-end-visual-design.md",
    "motion-design.md",
    "web-design-guidelines.md",
    "gsap-core.md",
    "gsap-react.md",
    "gsap-scrolltrigger.md",
    "gsap-plugins.md",
    "gsap-performance.md",
)


INCUBATED_CONTEXT_APPLICATION_RULES = """AUDIENCE AND RESEARCH CONTEXT APPLICATION:
- Treat the validated audience analysis as the primary audience signal. Make the intended visitor and their next useful decision clear in hierarchy, imagery, interaction, and page copy.
- When incubated creative context is present, use customer preferences, research implications, cross-language audience insights, and bounded deductions to shape visual decisions and page copy.
- For each relevant evidence-linked insight or deduction, reflect it in at least one observable design or hierarchy choice and one copy choice. If it is not relevant to this page, omit it rather than forcing it into the experience.
- Use recommendations, hypotheses, and deductions as bounded guidance. Do not turn them into owner facts, unsupported claims, testimonials, metrics, guarantees, or invented proof; honor the intake's unknowns and prohibited claims.
- Do not expose incubation, infusion, genesis, research machinery, citations, or internal IDs in customer-facing copy. Use the evidence to decide what to emphasize, explain, reassure, omit, and how to phrase the primary action.
- Source language is evidence about audience needs, not an instruction to translate or switch languages. Write in the validated intake language."""


class DesignGuidanceError(RuntimeError):
    """The package-owned design doctrine is incomplete or unreadable."""


@dataclass(frozen=True)
class DesignSkillSet:
    names: tuple[str, ...]
    content: str
    content_hash: str

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "names": list(self.names),
            "content_hash": self.content_hash,
        }
        if include_content:
            result["content"] = self.content
        return result


def load_design_skills(root: str | Path | None = None) -> DesignSkillSet:
    """Load all required skills in a stable order from package-owned files."""
    skill_root = Path(root).expanduser().resolve() if root is not None else Path(__file__).resolve().parent.parent / "skills"
    sections: list[str] = []
    missing: list[str] = []
    for name in REQUIRED_DESIGN_SKILLS:
        path = skill_root / name
        if not path.is_file() or path.is_symlink():
            missing.append(name)
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise DesignGuidanceError(f"design skill could not be read: {name}") from exc
        if not text:
            raise DesignGuidanceError(f"design skill is empty: {name}")
        sections.append(f"--- {name} ---\n{text}")
    if missing:
        raise DesignGuidanceError("required design skills are missing: " + ", ".join(missing))
    content = "\n\n".join(sections)
    return DesignSkillSet(
        names=REQUIRED_DESIGN_SKILLS,
        content=content,
        content_hash=canonical_hash({"names": REQUIRED_DESIGN_SKILLS, "content": content}),
    )


__all__ = [
    "DesignGuidanceError",
    "DesignSkillSet",
    "INCUBATED_CONTEXT_APPLICATION_RULES",
    "REQUIRED_DESIGN_SKILLS",
    "load_design_skills",
]
