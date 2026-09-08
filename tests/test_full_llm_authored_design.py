import json
from types import SimpleNamespace

from site_agent.hands.builder import OperationRoutingBuilder
from site_agent.site_scaffold import initialize_toolchain_workspace


def test_all_design_operations_use_native_source_authoring():
    calls = []

    class Native:
        def available(self):
            return True

        def build_design(self, request, target, progress=None):
            calls.append((target.operation_kind, target.mode))
            return "native"

    router = OperationRoutingBuilder({}, native=Native())

    for operation_kind in ("initial_build", "visual_refinement", "technical_repair", "derived_page"):
        assert router.build_design(
            SimpleNamespace(),
            SimpleNamespace(operation_kind=operation_kind, mode="local_experiment"),
        ) == "native"

    assert calls == [
        ("initial_build", "local_experiment"),
        ("visual_refinement", "local_experiment"),
        ("technical_repair", "local_experiment"),
        ("derived_page", "local_experiment"),
    ]


def test_new_site_workspace_contains_toolchain_only(tmp_path):
    root = initialize_toolchain_workspace(tmp_path / "site", "North Star Studio")

    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["astro"]
    assert package["dependencies"]["react"]
    assert package["dependencies"]["gsap"]
    assert package["dependencies"]["@gsap/react"]
    assert (root / "astro.config.mjs").is_file()
    assert (root / "tsconfig.json").is_file()

    # A new build must begin without a page, layout, stylesheet, copy, image,
    # section vocabulary, or other visual decision supplied by the host.
    assert not (root / "index.html").exists()
    assert not (root / "src/pages/index.astro").exists()
    assert not (root / "styles.css").exists()
    assert not (root / "content").exists()
    assert not (root / "themes").exists()
    assert not list(root.rglob("*.css"))
    assert not list(root.rglob("*.astro"))
