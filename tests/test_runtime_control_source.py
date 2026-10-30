from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from site_agent.application.runtime_activation import RuntimeActivation
from site_agent.application.runtime_control_source import (
    RuntimeControlSourceError, materialize_runtime_control,
)
from site_agent.application.shared_runtime import shared_runtime_fingerprint


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    git("remote", "add", "origin", "https://github.com/weareheadless/site-agent.git")
    checkout = Path(__file__).resolve().parents[1]
    for path in ("deploy/shared-runtime-overlay.json", "src/site_agent/application/shared_runtime.py", "scripts/generate-payload-contract.mjs", "src/site_agent/templates/next-payload", "packages/helloada-mailflare", "packages/helloada-payload-core/src"):
        source = checkout / path
        target = repo / path
        if source.is_dir():
            import shutil
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    (repo / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')
    git("add", ".")
    git("commit", "-qm", "first")
    first = git("rev-parse", "HEAD")
    (repo / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')
    git("add", ".")
    git("commit", "-qm", "second")
    second = git("rev-parse", "HEAD")
    return repo, first, second


def binding(repo, sha):
    return RuntimeActivation(1, "test-site", "release-1", "a" * 40, sha,
                             shared_runtime_fingerprint(repo), "version")


def test_materializes_only_selected_commit_and_cleans_context(repository, tmp_path):
    repo, first, second = repository
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    sibling = scratch / "unrelated"
    sibling.write_text("keep")
    bind = binding(repo, first)
    with materialize_runtime_control(bind, repo, scratch) as proof:
        assert proof.control_sha == first
        assert proof.source_root.joinpath("pyproject.toml").read_text().find("1.2.3") >= 0
        assert proof.source_root != repo
        assert (repo / "pyproject.toml").read_text().find("9.9.9") >= 0
        assert proof.shared_runtime_fingerprint == bind.shared_runtime_fingerprint
        assert proof.source_root.exists()
    assert not proof.source_root.exists()
    assert sibling.read_text() == "keep"
    assert second != first


@pytest.mark.parametrize("origin", ["https://evil.example/weareheadless/site-agent", "https://github.com/other/site-agent", "https://user:token@github.com/weareheadless/site-agent"])
def test_rejects_nonofficial_origin(repository, tmp_path, origin):
    repo, first, _ = repository
    subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", origin], check=True)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(RuntimeControlSourceError, match="origin"):
        with materialize_runtime_control(binding(repo, first), repo, scratch):
            pytest.fail("must not yield")


def test_rejects_missing_commit_and_fingerprint_mismatch(repository, tmp_path):
    repo, first, _ = repository
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for bind in (binding(repo, "f" * 40), RuntimeActivation(1, "test-site", "release-1", "a" * 40, first, "0" * 64, "version")):
        with pytest.raises(RuntimeControlSourceError):
            with materialize_runtime_control(bind, repo, scratch):
                pytest.fail("must not yield")
        assert list(scratch.iterdir()) == []


def test_concurrent_invocations_have_independent_snapshots(repository, tmp_path):
    repo, first, _ = repository
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with materialize_runtime_control(binding(repo, first), repo, scratch) as a:
        with materialize_runtime_control(binding(repo, first), repo, scratch) as b:
            assert a.source_root != b.source_root
            assert a.source_root.exists() and b.source_root.exists()
