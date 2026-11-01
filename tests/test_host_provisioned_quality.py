import hashlib
import json
import subprocess

from site_agent.hands.design_quality import QualityPolicy, _host_provisioned_paths, _repository_findings


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


def test_repository_policy_accepts_host_compiler_but_keeps_platform_protected(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    (tmp_path / "baseline").write_text("baseline")
    git("add", ".")
    git("commit", "-qm", "baseline")
    base = git("rev-parse", "HEAD")
    paths = {"package.json": "{}", "package-lock.json": "{}", ".env": "PRIVATE=value",
             "payload.config.ts": "protected schema"}
    for name, content in paths.items():
        (tmp_path / name).write_text(content)
    (tmp_path / "manifest.json").write_text(json.dumps({"host_generated": True, "host_metadata": {
        "provisioned_file_hashes": {
            name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in paths
        },
    }}))
    git("add", ".")
    git("commit", "-qm", "candidate")
    policy = QualityPolicy(manifest_path="manifest.json", allowed_patterns=("src/**",),
                           prohibited_paths=tuple(paths))
    findings = _repository_findings(tmp_path, base, "HEAD", policy)
    assert {item["path"] for item in findings if item["code"] == "path_policy"} == {
        ".env", "payload.config.ts",
    }
    (tmp_path / "package.json").write_text("modified compiler")
    findings = _repository_findings(tmp_path, base, "HEAD", policy)
    assert "package.json" in {item["path"] for item in findings if item["code"] == "path_policy"}


def test_frozen_owner_media_evidence_accepts_only_exact_path_and_bytes(tmp_path):
    media = tmp_path / "public/assets/owner.webp"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"owner bytes")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "host_generated": True, "host_metadata": {"owner_media_hashes": {}},
    }))
    policy = QualityPolicy(manifest_path="manifest.json", approved_media_files=({
        "relative_path": "public/assets/owner.webp",
        "asset_sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
    },))
    assert _host_provisioned_paths(tmp_path, policy) == {"public/assets/owner.webp"}
    media.write_bytes(b"modified bytes")
    assert not _host_provisioned_paths(tmp_path, policy)
