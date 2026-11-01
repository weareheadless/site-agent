import hashlib
import json
import subprocess

from site_agent.hands.design_quality import QualityPolicy, _host_provisioned_paths


def test_quality_accepts_only_exact_host_provisioned_bytes(tmp_path):
    path = tmp_path / "postcss.config.mjs"
    path.write_text("canonical compiler")
    manifest = tmp_path / "design/ada-design-manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"host_generated": True, "host_metadata": {
        "provisioned_file_hashes": {"postcss.config.mjs": hashlib.sha256(path.read_bytes()).hexdigest()},
    }}))
    policy = QualityPolicy(manifest_path="design/ada-design-manifest.json")
    assert "postcss.config.mjs" in _host_provisioned_paths(tmp_path, policy)
    path.write_text("unexpected model edit")
    assert "postcss.config.mjs" not in _host_provisioned_paths(tmp_path, policy)


def test_retained_legacy_candidate_keeps_host_ownership_without_manifest_edits(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()
    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    (tmp_path / "package.json").write_text("baseline")
    git("add", ".")
    git("commit", "-qm", "baseline")
    base = git("rev-parse", "HEAD")
    (tmp_path / "package.json").write_text("host compiler")
    (tmp_path / "page.tsx").write_text("Ada source")
    (tmp_path / "manifest.json").write_text(json.dumps({"host_generated": True, "host_metadata": {
        "base_sha": base, "changed_source_files": ["page.tsx"],
    }}))
    git("add", ".")
    git("commit", "-qm", "candidate")
    policy = QualityPolicy(manifest_path="manifest.json")
    assert _host_provisioned_paths(tmp_path, policy) == {"package.json"}
    (tmp_path / "package.json").write_text("dirty modification")
    assert not _host_provisioned_paths(tmp_path, policy)
