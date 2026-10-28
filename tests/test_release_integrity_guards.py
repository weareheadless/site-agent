import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("version_guard", ROOT / "scripts/check_shared_package_version.py")
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)

def fixture(monkeypatch, tmp_path, marker="2.0.0"):
    monkeypatch.setattr(GUARD, "ROOT", tmp_path)
    package = tmp_path / "packages/helloada-payload-admin"
    (package / "src").mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"version": "2.0.0"}))
    (package / "src/version.ts").write_text(f"export const HELLOADA_PAYLOAD_ADMIN_VERSION = '{marker}'")
    monkeypatch.setattr(GUARD.subprocess, "run", lambda *a, **k: type("Result", (), {"stdout": '{"version":"1.0.0"}'})())

def test_source_change_without_version_bump_fails(monkeypatch, tmp_path):
    fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(GUARD.subprocess, "run", lambda *a, **k: type("Result", (), {"stdout": '{"version":"2.0.0"}'})())
    assert GUARD.validate(["packages/helloada-payload-admin/src/index.ts"], "base")

def test_source_change_with_bump_passes(monkeypatch, tmp_path):
    fixture(monkeypatch, tmp_path)
    assert GUARD.validate(["packages/helloada-payload-admin/src/index.ts"], "base") == []

def test_non_source_change_passes():
    assert GUARD.validate(["packages/helloada-payload-admin/README.md"], "HEAD") == []

def test_package_bump_without_matching_marker_fails(monkeypatch, tmp_path):
    fixture(monkeypatch, tmp_path, marker="1.0.0")
    errors = GUARD.validate(["packages/helloada-payload-admin/src/index.ts"], "base")
    assert errors and "payload-admin-v2.0.0" in errors[0]

def test_no_tracked_symlink_resolves_outside_repository():
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout.split(b"\0")
    root = ROOT.resolve()
    escapes = [raw.decode() for raw in tracked if raw and (ROOT / raw.decode()).is_symlink() and not (ROOT / raw.decode()).resolve().is_relative_to(root)]
    assert not escapes, f"Tracked symlinks escape repository root: {escapes}"

def test_unresolvable_base_fails_readably(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_shared_package_version.py", "--base", "definitely-not-a-real-base-ref"])
    assert GUARD.main() == 1
    captured = capsys.readouterr()
    assert "could not be resolved to a commit" in captured.err
    assert "Traceback" not in captured.err
