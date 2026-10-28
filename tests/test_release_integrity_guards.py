import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import pytest

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

def assert_no_tracked_symlink_escape(repository: Path):
    metadata = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repository, capture_output=True, text=True)
    if metadata.returncode and "not a git repository" in metadata.stderr.lower():
        pytest.skip("Cannot inspect tracked symlinks: git metadata is missing (not a git repository).")
    assert metadata.returncode == 0, f"Could not inspect repository git metadata: {metadata.stderr.strip()}"
    tracked_result = subprocess.run(["git", "ls-files", "-z"], cwd=repository, capture_output=True)
    assert tracked_result.returncode == 0, f"git ls-files failed: {tracked_result.stderr.decode(errors='replace').strip()}"
    tracked = tracked_result.stdout.split(b"\0")
    root = repository.resolve()
    escapes = [raw.decode() for raw in tracked if raw and (repository / raw.decode()).is_symlink() and not (repository / raw.decode()).resolve().is_relative_to(root)]
    assert not escapes, f"Tracked symlinks escape repository root: {escapes}"

def test_no_tracked_symlink_resolves_outside_repository():
    assert_no_tracked_symlink_escape(ROOT)

def test_non_repository_skips_only_for_missing_git_metadata(tmp_path):
    with pytest.raises(pytest.skip.Exception, match=r"git metadata is missing \(not a git repository\)"):
        assert_no_tracked_symlink_escape(tmp_path)

def test_tracked_symlink_to_root_is_rejected(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "escape").symlink_to("/")
    subprocess.run(["git", "add", "escape"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "track external symlink"], cwd=tmp_path, check=True)
    with pytest.raises(AssertionError, match=r"Tracked symlinks escape repository root: \['escape'\]"):
        assert_no_tracked_symlink_escape(tmp_path)

def test_unresolvable_base_fails_readably(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_shared_package_version.py", "--base", "definitely-not-a-real-base-ref"])
    assert GUARD.main() == 1
    captured = capsys.readouterr()
    assert "could not be resolved to a commit" in captured.err
    assert "Traceback" not in captured.err
