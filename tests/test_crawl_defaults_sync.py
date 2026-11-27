"""The crawl defaults a site should have, and the sites that must keep their own.

A sitemap and a robots file that names it are not design decisions, so no site
should have to invent them. They are also genuinely tenant-owned: Growth may
propose a crawl change that edits exactly those files. The fleet mechanism
therefore seeds a default only where the site has not declared that capability
itself — a default that overwrote an authored file would be a release undoing
the owner's work, which is the defect this test exists to prevent.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _fake_identity(monkeypatch):
    """plan() records the control identity; a test checkout may not be a git repo."""
    import subprocess as _subprocess
    monkeypatch.setattr(
        _subprocess, "check_output",
        lambda *args, **kwargs: "0" * 40 + "\n",
    )


def _module():
    spec = importlib.util.spec_from_file_location(
        "sync_tenant_repository_check", ROOT / "scripts/sync-tenant-repository-check.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_defaults_are_the_template_owned_files():
    sync = _module()
    # The same bytes a new site is born with, so an existing site inherits the
    # default rather than a second copy of it.
    for path, source in sync.DEFAULTS.items():
        assert (ROOT / "src/site_agent/templates/next-payload" / path) == source
        assert source.is_file(), path


def test_every_supported_crawl_shape_counts_as_already_declared():
    sync = _module()
    # A tenant may use the metadata route or a static file; either way the
    # capability exists and the default must not be added beside it.
    assert "src/app/sitemap.ts" in sync.DEFAULT_OCCUPIED["src/app/sitemap.ts"]
    assert "public/sitemap.xml" in sync.DEFAULT_OCCUPIED["src/app/sitemap.ts"]
    assert "src/app/robots.txt/route.ts" in sync.DEFAULT_OCCUPIED["src/app/robots.ts"]
    assert "public/robots.txt" in sync.DEFAULT_OCCUPIED["src/app/robots.ts"]


def test_an_authored_crawl_file_is_never_overwritten(monkeypatch):
    sync = _module()
    existing = {
        "main": {
            "src/app/robots.ts": (b"tenant robots", "sha-robots"),
            "src/app/sitemap.ts": (b"tenant sitemap", "sha-sitemap"),
        },
    }
    written: list[str] = []
    monkeypatch.setattr(sync, "_remote_file",
                        lambda token, repo, branch, path: existing.get(branch, {}).get(path))
    monkeypatch.setattr(sync, "_branches", lambda *args, **kwargs: ["main"])
    monkeypatch.setattr(sync, "_tenant_rows", lambda *args, **kwargs: [{
        "tenant": "owned", "status": "planned", "repository": "weareheadless/owned", "branches": ["main"],
    }])
    monkeypatch.setattr(sync, "github_api_token", lambda *args, **kwargs: "token")
    monkeypatch.setattr(sync, "credential_environment", lambda *args, **kwargs: {})
    _fake_identity(monkeypatch)
    monkeypatch.setattr(sync, "_write",
                        lambda token, repo, branch, path, content, sha, message=None: written.append(path))

    result = sync.plan({"x": 1}, {}, [], apply=True)
    assert result["tenants"][0]["status"] == "applied"
    seeded = [path for path in written if path in {**sync.DEFAULTS, **sync.DEFAULT_SUPPORT}]
    assert seeded == [], seeded


def test_a_site_without_crawl_files_receives_all_of_them(monkeypatch):
    sync = _module()
    written: list[str] = []
    monkeypatch.setattr(sync, "_remote_file", lambda token, repo, branch, path: None)
    monkeypatch.setattr(sync, "_branches", lambda *args, **kwargs: ["main"])
    monkeypatch.setattr(sync, "_tenant_rows", lambda *args, **kwargs: [{
        "tenant": "bare", "status": "planned", "repository": "weareheadless/bare", "branches": ["main"],
    }])
    monkeypatch.setattr(sync, "github_api_token", lambda *args, **kwargs: "token")
    monkeypatch.setattr(sync, "credential_environment", lambda *args, **kwargs: {})
    _fake_identity(monkeypatch)
    monkeypatch.setattr(sync, "_write",
                        lambda token, repo, branch, path, content, sha, message=None: written.append(path))

    sync.plan({"x": 1}, {}, [], apply=True)
    assert sorted(path for path in written
                  if path in {**sync.DEFAULTS, **sync.DEFAULT_SUPPORT}) == sorted(
        {**sync.DEFAULTS, **sync.DEFAULT_SUPPORT})


def test_a_site_with_a_static_sitemap_only_gains_robots(monkeypatch):
    """casamigo's shape: a hand-authored public/sitemap.xml is the sitemap."""
    sync = _module()
    existing = {"main": {"public/sitemap.xml": (b"<urlset/>", "sha")}}
    written: list[str] = []
    monkeypatch.setattr(sync, "_remote_file",
                        lambda token, repo, branch, path: existing.get(branch, {}).get(path))
    monkeypatch.setattr(sync, "_branches", lambda *args, **kwargs: ["main"])
    monkeypatch.setattr(sync, "_tenant_rows", lambda *args, **kwargs: [{
        "tenant": "static", "status": "planned", "repository": "weareheadless/static", "branches": ["main"],
    }])
    monkeypatch.setattr(sync, "github_api_token", lambda *args, **kwargs: "token")
    monkeypatch.setattr(sync, "credential_environment", lambda *args, **kwargs: {})
    _fake_identity(monkeypatch)
    monkeypatch.setattr(sync, "_write",
                        lambda token, repo, branch, path, content, sha, message=None: written.append(path))

    sync.plan({"x": 1}, {}, [], apply=True)
    # The static sitemap is authored, so the metadata sitemap is not added; only
    # robots (which the site lacks) and the helper that serves it. Seeding robots
    # without the helper is a build that imports a module the repo does not have.
    seeded = sorted(path for path in written if path in sync.DEFAULTS)
    assert "src/app/sitemap.ts" not in seeded
    assert "src/app/robots.ts" in seeded
    # robots.ts imports the helper, so the helper must ship with it.
    assert "src/lib/site-origin.ts" in written


def test_a_default_already_committed_still_receives_its_helper(monkeypatch):
    """A branch seeded before the helper existed: the gap is in the helper, not the run."""
    sync = _module()
    robots = (sync.DEFAULTS["src/app/robots.ts"]).read_bytes()
    existing = {
        "main": {
            "public/sitemap.xml": (b"<urlset/>", "sha"),
            "src/app/robots.ts": (robots, "sha-robots"),
        },
    }
    written: list[str] = []
    monkeypatch.setattr(sync, "_remote_file",
                        lambda token, repo, branch, path: existing.get(branch, {}).get(path))
    monkeypatch.setattr(sync, "_branches", lambda *args, **kwargs: ["main"])
    monkeypatch.setattr(sync, "_tenant_rows", lambda *args, **kwargs: [{
        "tenant": "seeded", "status": "planned", "repository": "weareheadless/seeded", "branches": ["main"],
    }])
    monkeypatch.setattr(sync, "github_api_token", lambda *args, **kwargs: "token")
    monkeypatch.setattr(sync, "credential_environment", lambda *args, **kwargs: {})
    _fake_identity(monkeypatch)
    monkeypatch.setattr(sync, "_write",
                        lambda token, repo, branch, path, content, sha, message=None: written.append(path))

    sync.plan({"x": 1}, {}, [], apply=True)
    # Nothing is re-seeded, but the committed robots.ts imports the helper, so
    # the helper is the one thing still missing from that branch.
    crawl = [path for path in written if path in {**sync.DEFAULTS, **sync.DEFAULT_SUPPORT}]
    assert crawl == ["src/lib/site-origin.ts"]


def test_an_authored_crawl_route_without_the_helper_gains_nothing(monkeypatch):
    """A tenant's own crawl route is the tenant's; the default helper is not added to it."""
    sync = _module()
    existing = {
        "main": {
            "public/sitemap.xml": (b"<urlset/>", "sha"),
            "src/app/robots.ts": (b"export default function robots() { return { rules: [] } }\n", "sha"),
        },
    }
    written: list[str] = []
    monkeypatch.setattr(sync, "_remote_file",
                        lambda token, repo, branch, path: existing.get(branch, {}).get(path))
    monkeypatch.setattr(sync, "_branches", lambda *args, **kwargs: ["main"])
    monkeypatch.setattr(sync, "_tenant_rows", lambda *args, **kwargs: [{
        "tenant": "handwritten", "status": "planned", "repository": "weareheadless/handwritten",
        "branches": ["main"],
    }])
    monkeypatch.setattr(sync, "github_api_token", lambda *args, **kwargs: "token")
    monkeypatch.setattr(sync, "credential_environment", lambda *args, **kwargs: {})
    _fake_identity(monkeypatch)
    monkeypatch.setattr(sync, "_write",
                        lambda token, repo, branch, path, content, sha, message=None: written.append(path))

    sync.plan({"x": 1}, {}, [], apply=True)
    crawl = [path for path in written if path in {**sync.DEFAULTS, **sync.DEFAULT_SUPPORT}]
    assert crawl == []
