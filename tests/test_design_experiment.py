import json
import subprocess
from pathlib import Path

import pytest

from site_agent.hands.design_experiment import (
    DesignExperimentError,
    _validate_managed_payload_scaffold,
    initialize_neutral_repository,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_canonical_neutral_scaffold_is_created_and_reused_unchanged(tmp_path):
    root = tmp_path / "scaffold"
    created, first_sha = initialize_neutral_repository(root)
    original = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file() and ".git" not in path.parts}

    reused, second_sha = initialize_neutral_repository(root)

    assert reused == created == root
    assert first_sha == second_sha == _git(root, "rev-parse", "HEAD")
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file() and ".git" not in path.parts} == original
    assert _git(root, "remote") == ""
    assert _git(root, "status", "--porcelain") == ""


@pytest.mark.parametrize("mutation", ["schema", "admin_pin", "core_pin", "dirty", "remote"])
def test_neutral_scaffold_reuse_rejects_unsupported_or_unsafe_scaffolds(tmp_path, mutation):
    root = tmp_path / "scaffold"
    initialize_neutral_repository(root)

    if mutation in {"schema", "admin_pin", "core_pin"}:
        manifest_path = root / "template-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if mutation == "schema":
            manifest["templateSchema"] = 7
        else:
            package_path = root / "package.json"
            package = json.loads(package_path.read_text())
            name = "@weareheadless/helloada-payload-admin" if mutation == "admin_pin" else "@weareheadless/helloada-payload-core"
            package["dependencies"][name] = "file:tampered"
            package_path.write_text(json.dumps(package))
        if mutation == "schema":
            manifest_path.write_text(json.dumps(manifest))
    elif mutation == "dirty":
        (root / "dirty.txt").write_text("dirty")
    else:
        _git(root, "remote", "add", "origin", "https://example.invalid/site.git")

    with pytest.raises(DesignExperimentError):
        initialize_neutral_repository(root)


def test_creation_validates_canonical_template_before_commit(tmp_path):
    root = tmp_path / "scaffold"
    initialize_neutral_repository(root)
    _validate_managed_payload_scaffold(root)
    manifest = json.loads((root / "template-manifest.json").read_text())
    assert manifest["templateSchema"] == json.loads(
        (Path(__file__).parents[1] / "src/site_agent/templates/next-payload/template-manifest.json").read_text()
    )["templateSchema"]
