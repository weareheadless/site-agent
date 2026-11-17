import json
import subprocess
import sys
from pathlib import Path

from site_agent.application import source_inventory

ROOT = Path(__file__).resolve().parents[1]


def test_violations_are_returned_as_a_report_and_a_failed_exit(tmp_path, monkeypatch):
    report = {"fields": [], "violations": [
        {"path": "src/hero.tsx", "line": 76, "reason": "editable_field_needs_a_shared_binding"},
    ]}
    analyzer = tmp_path / "source_inventory_ast.mjs"
    analyzer.write_text("// fixture", encoding="utf-8")
    monkeypatch.setattr(source_inventory, "__file__", str(tmp_path / "source_inventory.py"))
    monkeypatch.setattr(source_inventory.shutil, "which", lambda name: sys.executable)
    monkeypatch.setattr(source_inventory.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args, 1, stdout=json.dumps(report), stderr=""))
    assert source_inventory.inventory(tmp_path)["violations"] == report["violations"]


def test_a_broken_inventory_is_still_a_tooling_error(tmp_path, monkeypatch):
    monkeypatch.setattr(source_inventory.shutil, "which", lambda name: sys.executable)
    monkeypatch.setattr(source_inventory.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args, 1, stdout="", stderr="Cannot find module 'typescript'"))
    try:
        source_inventory.inventory(tmp_path)
    except ValueError as exc:
        assert "typescript" in str(exc)
    else:  # pragma: no cover - a silent empty report would hide a real failure
        raise AssertionError("a failed inventory must not return a clean report")


def test_main_exits_non_zero_when_the_report_has_violations(tmp_path, monkeypatch):
    report = {"fields": [], "violations": [{"path": "a.tsx", "line": 1, "reason": "x"}]}
    monkeypatch.setattr(source_inventory, "inventory", lambda root, **kwargs: report)
    monkeypatch.setattr(sys, "argv", ["source_inventory.py", "--root", str(tmp_path)])
    assert source_inventory.main() == 1
    monkeypatch.setattr(source_inventory, "inventory", lambda root, **kwargs: {"fields": [], "violations": []})
    assert source_inventory.main() == 0


def test_the_inventory_carries_the_declared_presentation_profile(tmp_path, monkeypatch):
    """Where a site's copy lives is a property of the site, not of the run."""
    analyzer = tmp_path / "source_inventory_ast.mjs"
    analyzer.write_text("// fixture", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(source_inventory, "__file__", str(tmp_path / "source_inventory.py"))
    monkeypatch.setattr(source_inventory.shutil, "which", lambda name: sys.executable)

    def run(command, *args, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"fields": [], "violations": []}), stderr="")

    monkeypatch.setattr(source_inventory.subprocess, "run", run)
    source_inventory.inventory(tmp_path, presentation_profile="static")
    assert seen["command"][-2:] == ["--presentation-profile", "static"]


def test_an_unknown_presentation_profile_is_a_tooling_error(tmp_path):
    try:
        source_inventory.inventory(tmp_path, presentation_profile="marketing")
    except ValueError as exc:
        assert "presentation profile" in str(exc)
    else:  # pragma: no cover - a guessed profile would silently drop the gate
        raise AssertionError("an unknown presentation profile must fail closed")
