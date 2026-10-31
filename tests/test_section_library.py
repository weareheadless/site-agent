"""The section library is shared runtime, and it carries no fixed look."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src" / "site_agent" / "templates" / "next-payload"
SECTIONS = TEMPLATE / "src" / "components" / "site" / "sections"


def test_shared_sections_are_declared_in_the_runtime_overlay():
    """A section that is not in the overlay never reaches a tenant Worker."""
    overlay = json.loads((ROOT / "deploy" / "shared-runtime-overlay.json").read_text())

    for name in ("hero.tsx", "registry.ts"):
        assert (SECTIONS / name).is_file(), f"missing shared section: {name}"
        assert f"src/components/site/sections/{name}" in overlay["copy"]


def test_hero_exposes_direction_instead_of_baking_one_look():
    """Direction is the designer's decision, so the component takes it as data.

    If the component hard-codes an alignment or a treatment, every site
    converges on the library author's taste and Ada's choice is not real.
    """
    source = (SECTIONS / "hero.tsx").read_text()

    for alignment in ("split-left", "split-right", "centred", "overlap", "reversed"):
        assert alignment in source, f"hero cannot express {alignment}"
    assert "'colour' | 'monochrome'" in source
    assert "'editorial' | 'compact'" in source
    assert "signature" in source, "the designer needs a slot for one deliberate gesture"


def test_sections_use_theme_tokens_not_hard_coded_colours():
    """A palette change must be an edit, not a rebuild."""
    source = (SECTIONS / "hero.tsx").read_text()
    css = (TEMPLATE / "src" / "app" / "(frontend)" / "site.css").read_text()

    for colour in ("bg-paper", "text-ink", "text-muted", "text-body", "bg-rule"):
        assert colour in source
    # No literal palette values in the component.
    assert "#" not in source, "hero.tsx contains a hard-coded colour"
    assert "@theme" in css
    assert "--color-paper" in css and "--tenant-paper" in css
