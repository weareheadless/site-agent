"""The section library is pinned tenant presentation, not a runtime overlay."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src" / "site_agent" / "templates" / "next-payload"
SECTIONS = TEMPLATE / "src" / "components" / "site" / "sections"


def test_candidate_receives_a_pinned_section_snapshot_without_replacing_presentation(tmp_path):
    from site_agent.hands.opencode_runner import _stage_section_templates, RunnerError
    import pytest

    presentation = tmp_path / "src/components/site/presentation/PagePresentation.tsx"
    presentation.parent.mkdir(parents=True)
    presentation.write_text("owner composition")
    previous = presentation.parent / "section-library-v1/hero.tsx"
    previous.parent.mkdir()
    previous.write_text("previous pinned presentation")
    paths = _stage_section_templates(tmp_path)
    assert presentation.read_text() == "owner composition"
    assert previous.read_text() == "previous pinned presentation"
    assert len(paths) == 5
    assert all("section-library-v3/" in path for path in paths)
    for path in paths:
        assert (tmp_path / path).read_bytes() == (SECTIONS / Path(path).name).read_bytes()
    assert _stage_section_templates(tmp_path) == paths
    (tmp_path / paths[0]).write_text("different pinned version")
    with pytest.raises(RunnerError, match="section template snapshot"):
        _stage_section_templates(tmp_path)


def test_section_toolchain_is_prepared_before_install_without_replacing_tenant_config(tmp_path):
    from site_agent.hands.opencode_runner import _prepare_section_toolchain, RunnerError
    import pytest

    package = tmp_path / "package.json"
    package.write_text(json.dumps({"dependencies": {"next": "16.3.4"}}))
    paths = _prepare_section_toolchain(tmp_path)
    assert set(paths) == {"package.json", "postcss.config.mjs"}
    declared = json.loads(package.read_text())
    approved = json.loads((TEMPLATE / "package.json").read_text())["devDependencies"]
    for name in ("tailwindcss", "@tailwindcss/postcss"):
        assert declared["devDependencies"][name] == approved[name]
    assert declared["dependencies"]["next"] == "16.3.4"
    assert (tmp_path / "postcss.config.mjs").read_bytes() == (TEMPLATE / "postcss.config.mjs").read_bytes()
    assert _prepare_section_toolchain(tmp_path) == ()
    (tmp_path / "postcss.config.mjs").write_text("tenant custom config")
    with pytest.raises(RunnerError, match="PostCSS configuration"):
        _prepare_section_toolchain(tmp_path)
    assert (tmp_path / "postcss.config.mjs").read_text() == "tenant custom config"


def test_composition_plumbing_is_prepared_without_designing_or_losing_existing_presentation(tmp_path):
    from site_agent.hands.opencode_runner import _stage_section_templates, _wire_section_composition, RunnerError
    import pytest

    _stage_section_templates(tmp_path)
    presentation = tmp_path / 'src/components/site/presentation'
    page = presentation / 'PagePresentation.tsx'
    original = 'export default function Page(props) { return <main>{props.document.title}</main> }\n'
    page.write_text(original)
    paths = _wire_section_composition(tmp_path)
    assert len(paths) == 2
    assert (presentation / 'NonComposedPagePresentation.tsx').read_text() == original
    wired = page.read_text()
    assert 'section-library-v3/composition' in wired
    assert 'mediaUrl(value)' in wired
    assert '<ExistingPresentation {...props}' in wired
    assert _wire_section_composition(tmp_path) == ()
    page.write_text('another approved composition')
    with pytest.raises(RunnerError, match='overwrite an existing presentation'):
        _wire_section_composition(tmp_path)
    assert page.read_text() == 'another approved composition'


def test_sections_are_scaffold_not_shared_runtime():
    """Sections are the site's own design, so they ship in the scaffold.

    `src/components/site` is tenant-owned presentation and the runtime overlay
    refuses to replace it. A section library belongs to the scaffold every new
    site is created from, which is also why improving it cannot restyle a live
    site without the owner moving to a new variant.
    """
    overlay = json.loads((ROOT / "deploy" / "shared-runtime-overlay.json").read_text())

    for name in ("hero.tsx", "registry.ts", "adapt.ts", "supporting.tsx"):
        assert (SECTIONS / name).is_file(), f"missing scaffold section: {name}"
        assert f"src/components/site/sections/{name}" not in overlay["copy"]


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


def test_adapter_maps_content_blocks_to_section_props():
    """The adapter is the one place that decides which block becomes what."""
    source = (SECTIONS / "adapt.ts").read_text()

    for block in ("helloAdaHeading", "helloAdaParagraph", "helloAdaLink", "helloAdaImage"):
        assert block in source, f"adapter ignores {block}"
    assert (SECTIONS / "adapt.ts").is_file()



def test_composition_vocabulary_matches_the_renderable_registry():
    """Ada may only name a layout the scaffold can actually render.

    The contract in design_contracts and the registry in the scaffold are two
    halves of one vocabulary; if they drift, Ada composes a page nobody can
    build.
    """
    from site_agent.core.design_contracts import SECTION_LAYOUTS

    import re

    registry = (SECTIONS / "registry.ts").read_text()
    block = registry.split("sectionComponents", 1)[1].split("}", 1)[0]
    registered = set(re.findall(r"^\s{2}([a-z][a-z0-9-]*):", block, re.MULTILINE))
    assert registered, "could not read the section registry"
    assert set(SECTION_LAYOUTS) == registered


def test_adapter_reads_the_eyebrow_before_the_heading_and_keeps_every_paragraph():
    """A composed hero must not swap the eyebrow into the body or drop copy.

    The authoring surface is ordered, so the adapter decides by position: a
    paragraph before the heading is the eyebrow, the first after it is the
    body, and later paragraphs stay visible as supporting copy.
    """
    source = (SECTIONS / "adapt.ts").read_text()

    assert "headingSeen" in source, "adapter cannot tell copy before the heading from copy after it"
    assert "eyebrow" in source
    assert "supporting.push" in source, "further approved paragraphs would be dropped"

    hero = (SECTIONS / "hero.tsx").read_text()
    assert "supporting" in hero, "hero never renders the supporting copy the adapter collects"
