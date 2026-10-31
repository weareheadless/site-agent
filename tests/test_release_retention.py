"""Bounded retention for release artifacts and abandoned builder worktrees."""
import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load_script("deploy-payload-customer")
api_deploy = load_script("deploy-site-agent-api")

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def slot(releases: Path, name: str, source_sha: str, mtime: float) -> Path:
    path = releases / name
    path.mkdir()
    (path / "source-sha").write_text(source_sha + "\n")
    path.touch()
    import os
    os.utime(path, (mtime, mtime))
    return path


def source(sources: Path, sha: str, mtime: float) -> Path:
    path = sources / sha
    path.mkdir()
    import os
    os.utime(path, (mtime, mtime))
    return path


def test_prune_release_store_keeps_current_previous_and_recent(tmp_path):
    releases = tmp_path / "api" / "releases"
    sources = tmp_path / "api-sources"
    releases.mkdir(parents=True)
    sources.mkdir()
    slot(releases, "release-old", SHA_A, 1000)
    slot(releases, "release-prev", SHA_B, 2000)
    slot(releases, "release-keep", SHA_C, 3000)
    slot(releases, "release-new", SHA_A, 4000)
    current = tmp_path / "api" / "current"
    current.symlink_to(releases / "release-new")
    for sha, mtime in ((SHA_A, 1000), (SHA_B, 2000), (SHA_C, 3000)):
        source(sources, sha, mtime)

    summary = api_deploy._prune_release_store(
        releases, current, sources, keep=2, previous=releases / "release-prev")

    remaining = {path.name for path in releases.iterdir()}
    assert "release-new" in remaining  # the live slot
    assert "release-keep" in remaining  # newest two
    assert "release-prev" in remaining  # explicit rollback target
    assert "release-old" not in remaining
    assert summary["removedReleases"] == ["release-old"]
    assert summary["errors"] == []
    assert summary["removedSources"] == []


def test_prune_release_store_keeps_sources_referenced_by_kept_slots(tmp_path):
    releases = tmp_path / "api" / "releases"
    sources = tmp_path / "api-sources"
    releases.mkdir(parents=True)
    sources.mkdir()
    slot(releases, "release-live", SHA_A, 1000)
    current = tmp_path / "api" / "current"
    current.symlink_to(releases / "release-live")
    source(sources, SHA_A, 1000)
    source(sources, SHA_B, 2000)
    source(sources, SHA_C, 3000)

    api_deploy._prune_release_store(releases, current, sources, keep=1)

    assert (sources / SHA_A).is_dir(), "a live release keeps its source snapshot"
    assert not (sources / SHA_B).exists()
    assert (sources / SHA_C).is_dir(), "the newest source stays as a small cache"


def test_prune_release_store_ignores_symlinks_and_survives_errors(tmp_path, monkeypatch):
    releases = tmp_path / "api" / "releases"
    sources = tmp_path / "api-sources"
    releases.mkdir(parents=True)
    sources.mkdir()
    slot(releases, "release-live", SHA_A, 3000)
    slot(releases, "release-old", SHA_B, 1000)
    outside = tmp_path / "outside"
    outside.mkdir()
    (releases / "release-link").symlink_to(outside)
    current = tmp_path / "api" / "current"
    current.symlink_to(releases / "release-live")

    def failing_rmtree(path, *args, **kwargs):
        raise OSError("busy")

    monkeypatch.setattr(api_deploy.shutil, "rmtree", failing_rmtree)
    summary = api_deploy._prune_release_store(releases, current, sources, keep=1)

    assert summary["removedReleases"] == []
    assert any("release-old" in error for error in summary["errors"])
    assert outside.is_dir(), "never delete through a symlink"


def test_require_free_space_fails_closed_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(api_deploy.shutil, "disk_usage",
                        lambda _: shutil._ntuple_diskusage(10**9, 10**9, 10**9))
    with pytest.raises(RuntimeError, match="GiB free"):
        api_deploy._require_free_space(tmp_path, minimum_gib=15)

    monkeypatch.setattr(api_deploy.shutil, "disk_usage",
                        lambda _: shutil._ntuple_diskusage(10**12, 10**9, 10**12 - 10**9))
    api_deploy._require_free_space(tmp_path, minimum_gib=15)


def test_discard_artifact_bundle_removes_only_that_directory(tmp_path):
    bundle = tmp_path / "custom-worker-dry-run"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "assets" / "worker.js").write_text("x")
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}")

    assert release.discard_artifact_bundle(bundle) == "complete"
    assert not bundle.exists()
    assert receipt.is_file(), "the receipt must survive bundle cleanup"


def test_discard_artifact_bundle_reports_failure_without_raising(tmp_path, monkeypatch):
    bundle = tmp_path / "custom-worker-dry-run"
    bundle.mkdir()

    def failing_rmtree(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(release.shutil, "rmtree", failing_rmtree)
    assert release.discard_artifact_bundle(bundle) == "failed: OSError"


def test_sweep_builder_worktrees_removes_only_abandoned_ones(tmp_path, monkeypatch):
    import site_agent.hands.opencode_runner as runner
    import os
    import time

    data = tmp_path / "data"
    root = data / "builder-worktrees"
    stale = root / "build-1"
    fresh = root / "build-2"
    for path in (stale, fresh):
        (path / "node_modules").mkdir(parents=True)
    now = time.time()
    os.utime(stale, (now - 48 * 3600, now - 48 * 3600))
    os.utime(fresh, (now - 60, now - 60))
    (root / "not-a-build").mkdir()
    calls = []
    monkeypatch.setattr(runner, "_git", lambda *args, **kwargs: calls.append(args) or "")

    runner._sweep_builder_worktrees(tmp_path, {"data_dir": str(data)})

    assert not stale.exists()
    assert fresh.exists()
    assert (root / "not-a-build").exists()
    assert calls and calls[0][1:3] == ("worktree", "prune")


def test_sweep_builder_worktrees_never_raises_when_git_is_unavailable(tmp_path, monkeypatch):
    import site_agent.hands.opencode_runner as runner
    import os
    import time

    data = tmp_path / "data"
    root = data / "builder-worktrees"
    stale = root / "build-1"
    stale.mkdir(parents=True)
    os.utime(stale, (time.time() - 48 * 3600,) * 2)

    def failing_git(*args, **kwargs):
        raise runner.RunnerError("git unavailable")

    monkeypatch.setattr(runner, "_git", failing_git)
    runner._sweep_builder_worktrees(tmp_path, {"data_dir": str(data)})
    assert not stale.exists()


def test_release_keeps_the_dry_run_bundle_until_the_upload_is_verified():
    """The upload stage re-hashes the dry-run bundle it just uploaded.

    Discarding the bundle straight after hashing it made every release fail at
    upload with "Wrangler dry-run produced no compiled custom Worker", even
    though the bundle had just been built successfully.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "deploy-payload-customer.py").read_text()

    hashed = source.index('receipt["artifactHashes"] = inspect_artifact(')
    upload = source.index('stage("upload")')
    between = source[hashed:upload]

    assert "discard_artifact_bundle(custom_worker_bundle)" not in between
    # The cleanup still happens, at the end of the run.
    assert source.count("discard_artifact_bundle(") == 2  # definition + deferred call
