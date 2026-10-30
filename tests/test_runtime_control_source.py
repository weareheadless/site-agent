from __future__ import annotations

import subprocess
import threading
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
    (repo / ".gitattributes").write_text("pyproject.toml export-ignore\nsubst.txt export-subst\n")
    (repo / "subst.txt").write_text("$Format:%H$\n")
    (repo / "executable").write_text("#!/bin/sh\nexit 0\n")
    (repo / "executable").chmod(0o755)
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
    before = subprocess.run(["git", "-C", str(repo), "status", "--porcelain=v2", "--branch"], check=True, capture_output=True).stdout
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True).stdout
    index = subprocess.run(["git", "-C", str(repo), "write-tree"], check=True, capture_output=True).stdout
    (repo / ".git" / "info" / "attributes").write_text("pyproject.toml export-ignore\nsubst.txt export-subst\n")
    with materialize_runtime_control(bind, repo, scratch) as proof:
        assert proof.control_sha == first
        assert proof.source_root.joinpath("pyproject.toml").read_text().find("1.2.3") >= 0
        assert proof.source_root != repo
        assert (repo / "pyproject.toml").read_text().find("9.9.9") >= 0
        assert proof.shared_runtime_fingerprint == bind.shared_runtime_fingerprint
        assert proof.source_root.exists()
        assert proof.source_root.joinpath("pyproject.toml").read_text() == '[project]\nversion = "1.2.3"\n'
        assert proof.source_root.joinpath("subst.txt").read_text() == "$Format:%H$\n"
        assert proof.source_root.joinpath("executable").stat().st_mode & 0o111
    assert not proof.source_root.exists()
    assert sibling.read_text() == "keep"
    assert subprocess.run(["git", "-C", str(repo), "status", "--porcelain=v2", "--branch"], check=True, capture_output=True).stdout == before
    assert subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True).stdout == head
    assert subprocess.run(["git", "-C", str(repo), "write-tree"], check=True, capture_output=True).stdout == index
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
    barrier = threading.Barrier(2)
    roots = []
    errors = []
    def invoke():
        try:
            with materialize_runtime_control(binding(repo, first), repo, scratch) as proof:
                roots.append(proof.source_root)
                barrier.wait(timeout=10)
                assert proof.source_root.exists()
        except BaseException as exc:
            errors.append(exc)
    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert len(set(roots)) == 2
    assert all(not root.exists() for root in roots)


def test_caller_exception_identity_and_cleanup(repository, tmp_path):
    repo, first, _ = repository
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    sentinel = RuntimeError("caller failure")
    with pytest.raises(RuntimeError) as caught:
        with materialize_runtime_control(binding(repo, first), repo, scratch) as proof:
            assert proof.source_root.exists()
            raise sentinel
    assert caught.value is sentinel
    assert list(scratch.iterdir()) == []


def test_rejects_committed_symlink_and_gitlink(repository, tmp_path):
    repo, first, _ = repository
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (repo / "bad-link").symlink_to("pyproject.toml")
    subprocess.run(["git", "-C", str(repo), "add", "bad-link"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "symlink"], check=True)
    symlink_commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    for sha in (symlink_commit,):
        with pytest.raises(RuntimeControlSourceError, match="unsupported"):
            with materialize_runtime_control(binding(repo, sha), repo, scratch):
                pytest.fail("must not yield")
    subprocess.run(["git", "-C", str(repo), "update-index", "--add", "--cacheinfo", f"160000,{first},submodule"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "gitlink"], check=True)
    gitlink_commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    with pytest.raises(RuntimeControlSourceError, match="unsupported"):
        with materialize_runtime_control(binding(repo, gitlink_commit), repo, scratch):
            pytest.fail("must not yield")
    assert list(scratch.iterdir()) == []


def test_injected_unsafe_tree_path_rejected(repository, tmp_path, monkeypatch):
    repo, first, _ = repository
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    import site_agent.application.runtime_control_source as module
    original = module._git
    def injected(path, *args):
        if args[:1] == ("ls-tree",):
            blob = original(path, "rev-parse", f"{first}:pyproject.toml").strip()
            return b"100644 blob " + blob + b"\t../escape\0"
        return original(path, *args)
    monkeypatch.setattr(module, "_git", injected)
    with pytest.raises(RuntimeControlSourceError, match="unsafe"):
        with materialize_runtime_control(binding(repo, first), repo, scratch):
            pytest.fail("must not yield")
    assert not (tmp_path / "escape").exists()
    assert list(scratch.iterdir()) == []


def test_rejects_tree_object_and_malformed_binding(repository, tmp_path):
    repo, first, _ = repository
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    tree = subprocess.run(["git", "-C", str(repo), "rev-parse", f"{first}^{{tree}}"], check=True, capture_output=True, text=True).stdout.strip()
    with pytest.raises(RuntimeControlSourceError):
        with materialize_runtime_control(binding(repo, tree), repo, scratch):
            pytest.fail("must not yield")
    malformed = RuntimeActivation(1, "test-site", "release-1", "a" * 40, first, "z" * 64, "version")
    with pytest.raises(RuntimeControlSourceError, match="malformed"):
        with materialize_runtime_control(malformed, repo, scratch):
            pytest.fail("must not yield")
    assert list(scratch.iterdir()) == []
