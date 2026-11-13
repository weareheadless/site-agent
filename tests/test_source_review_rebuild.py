"""A pending review outlives the base it was prepared from.

Production moves, the candidate's old tree no longer compiles, and retrying the
same revision can never succeed. Rebuilding re-applies the exact reviewed change
onto the current production head, points the review at that commit, and builds
one fresh preview. These tests pin the facts that make that honest: only the
reviewed paths move, the reviewed blobs are the candidate's own, and the review
is refused rather than half-applied when the preview branch carries other work.
"""

from __future__ import annotations

import pytest

from site_agent.application.workspace import BridgeError, ChatService
from site_agent.core.memory import Memory
from site_agent.hands import github_static
from site_agent.hands.base import AdapterError
from site_agent.hands.github_static import GithubStatic

BASE = "1" * 40
CANDIDATE = "2" * 40
CURRENT = "3" * 40
REBUILT = "4" * 40
BASE_TREE = "a" * 40
CANDIDATE_TREE = "b" * 40
CURRENT_TREE = "c" * 40
REBUILT_TREE = "d" * 40

CONFIG = {
    "design_engine": {"build_profile": "next_react"},
    "site": {"repository": "acme/site", "branch": "main"},
}


class FakeGithub:
    """The smallest GitHub the adapter can be honest against."""

    def __init__(self, *, trees, commits, refs, protected_change=False):
        self.trees = {sha: dict(entries) for sha, entries in trees.items()}
        if protected_change:
            self.trees[CANDIDATE_TREE]["payload.config.ts"] = {
                "path": "payload.config.ts", "mode": "100644", "type": "blob", "sha": "cfg",
            }
        self.commits = dict(commits)
        self.refs = dict(refs)
        self.calls: list[tuple[str, str]] = []
        self.created_commits: list[dict] = []

    def __call__(self, method, url, token=None, payload=None, timeout=30):
        del token, timeout
        self.calls.append((method, url))
        path = url.split("/repos/acme/site", 1)[1].split("?", 1)[0]
        if method == "GET" and path.startswith("/git/ref/heads/"):
            branch = path.rsplit("/", 1)[1]
            return 200, {"object": {"sha": self.refs[branch]}}
        if method == "GET" and path.startswith("/commits/"):
            sha = path.rsplit("/", 1)[1]
            return 200, {"commit": {"tree": {"sha": self.commits[sha]}, "message": "reviewed"}}
        if method == "GET" and path.startswith("/git/trees/"):
            tree = path.split("/git/trees/", 1)[1]
            body = {"tree": [dict(value) for value in self.trees[tree].values()]}
            if tree == "truncated":
                body = {"tree": [], "truncated": True}
            return 200, body
        if method == "POST" and path == "/git/trees":
            base = {value["path"]: dict(value) for value in self.trees[payload["base_tree"]].values()}
            for entry in payload["tree"]:
                if entry["sha"] is None:
                    base.pop(entry["path"], None)
                else:
                    base[entry["path"]] = dict(entry)
            self.trees[REBUILT_TREE] = base
            return 201, {"sha": REBUILT_TREE}
        if method == "POST" and path == "/git/commits":
            assert payload["parents"] == [CURRENT]
            self.commits[REBUILT] = payload["tree"]
            self.created_commits.append(payload)
            return 201, {"sha": REBUILT}
        if method == "PATCH" and path.startswith("/git/refs/heads/"):
            branch = path.rsplit("/", 1)[1]
            self.refs[branch] = payload["sha"]
            return 200, {}
        raise AssertionError(f"unexpected github call {method} {url}")


def _review(**overrides):
    trees = {
        BASE_TREE: {
            "src/components/site/presentation/SiteHeader.tsx": {
                "path": "src/components/site/presentation/SiteHeader.tsx",
                "mode": "100644", "type": "blob", "sha": "old-header",
            },
            "src/app/globals.css": {
                "path": "src/app/globals.css", "mode": "100644", "type": "blob", "sha": "css",
            },
        },
        CANDIDATE_TREE: {
            "src/components/site/presentation/SiteHeader.tsx": {
                "path": "src/components/site/presentation/SiteHeader.tsx",
                "mode": "100644", "type": "blob", "sha": "new-header",
            },
            "src/app/globals.css": {
                "path": "src/app/globals.css", "mode": "100644", "type": "blob", "sha": "css",
            },
            "public/favicon.ico": {
                "path": "public/favicon.ico", "mode": "100644", "type": "blob", "sha": "icon",
            },
        },
        CURRENT_TREE: {
            # Production moved: the page and its chrome changed under the review.
            "src/components/site/presentation/SiteHeader.tsx": {
                "path": "src/components/site/presentation/SiteHeader.tsx",
                "mode": "100644", "type": "blob", "sha": "current-header",
            },
            "src/app/globals.css": {
                "path": "src/app/globals.css", "mode": "100644", "type": "blob", "sha": "css",
            },
            "src/app/page.tsx": {
                "path": "src/app/page.tsx", "mode": "100644", "type": "blob", "sha": "page",
            },
        },
    }
    commits = {BASE: BASE_TREE, CANDIDATE: CANDIDATE_TREE, CURRENT: CURRENT_TREE}
    refs = {"main": CURRENT, "preview": CANDIDATE}
    github = FakeGithub(trees=trees, commits=commits, refs=refs, **overrides)
    adapter = GithubStatic(CONFIG, {"GITHUB_TOKEN": "token"})
    return github, github.refs, adapter


def _apply(monkeypatch, github):
    monkeypatch.setattr(github_static, "_request", github)
    return github


def test_reapply_moves_only_the_reviewed_paths_onto_the_current_head(monkeypatch):
    github, refs, adapter = _review()
    _apply(monkeypatch, github)

    result = adapter.reapply_review_candidate(
        candidate_sha=CANDIDATE, base_sha=BASE, branch="preview", message="Re-apply the reviewed change",
    )

    assert result["rebased"] is True
    assert result["commit_sha"] == REBUILT
    assert result["base_sha"] == CURRENT
    assert result["paths"] == [
        "public/favicon.ico", "src/components/site/presentation/SiteHeader.tsx",
    ]
    rebuilt = github.trees[REBUILT_TREE]
    assert rebuilt["public/favicon.ico"]["sha"] == "icon"
    assert rebuilt["src/components/site/presentation/SiteHeader.tsx"]["sha"] == "new-header"
    # Production's own newer state and untouched files stay exactly as they are.
    assert rebuilt["src/app/page.tsx"]["sha"] == "page"
    assert rebuilt["src/app/globals.css"]["sha"] == "css"
    assert refs["preview"] == REBUILT
    assert refs["main"] == CURRENT


def test_reapply_no_ops_when_the_review_already_sits_on_the_current_head(monkeypatch):
    github, refs, adapter = _review()
    refs["main"] = BASE
    _apply(monkeypatch, github)

    result = adapter.reapply_review_candidate(
        candidate_sha=CANDIDATE, base_sha=BASE, branch="preview", message="Re-apply",
    )

    assert result["rebased"] is False
    assert result["commit_sha"] == CANDIDATE
    assert github.created_commits == []
    assert refs["preview"] == CANDIDATE


def test_reapply_refuses_when_the_preview_branch_carries_other_work(monkeypatch):
    github, refs, adapter = _review()
    refs["preview"] = "9" * 40
    _apply(monkeypatch, github)

    with pytest.raises(AdapterError, match="no longer carries this exact review"):
        adapter.reapply_review_candidate(
            candidate_sha=CANDIDATE, base_sha=BASE, branch="preview", message="Re-apply",
        )
    assert github.created_commits == []


def test_reapply_refuses_a_review_that_touches_platform_source(monkeypatch):
    github, refs, adapter = _review(protected_change=True)
    _apply(monkeypatch, github)

    with pytest.raises(AdapterError, match="may not publish"):
        adapter.reapply_review_candidate(
            candidate_sha=CANDIDATE, base_sha=BASE, branch="preview", message="Re-apply",
        )
    assert github.created_commits == []
    assert refs["preview"] == CANDIDATE


class _Deployer:
    def __init__(self, latest=None):
        self.adapter = _Adapter()
        self.latest = latest or {}
        self.started: list[dict] = []

    def latest_preview(self, branch=None):
        return dict(self.latest)

    def start(self, body):
        self.started.append(dict(body))
        return {"id": "job-rebuilt", "status": "running", "commit": body["commit"]}

    def status(self, job_id):
        return {}


class _Adapter:
    def __init__(self):
        self.calls: list[dict] = []

    def reapply_review_candidate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "rebased": True,
            "commit_sha": REBUILT,
            "base_sha": CURRENT,
            "paths": ["public/favicon.ico"],
        }


def _service(tmp_path, *, latest=None):
    memory = Memory(tmp_path / "memory.db")
    draft = memory.save_draft(
        "Use the logo mark as the page icon", "diff", kind="merge",
        meta={
            "head": "preview",
            "base": "main",
            "head_sha": CANDIDATE,
            "base_sha": BASE,
            "summary": "Use the logo mark as the page icon",
            "changed_paths": ["public/favicon.ico"],
            "preview": {
                "mode": "compile", "status": "blocked", "requires_build": True,
                "changed_paths": ["public/favicon.ico"],
                "head_sha": CANDIDATE, "job_id": "failed-job",
            },
        },
    )
    deployer = _Deployer(latest)
    service = ChatService(
        memory, type("LLM", (), {"api_key": "test"})(),
        config=CONFIG, source_deployment=deployer,
    )
    return memory, draft, deployer, service


def test_rebuild_repoints_the_review_and_builds_the_new_commit(tmp_path):
    memory, draft, deployer, service = _service(tmp_path)
    try:
        result = service.source_preview_rebuild({"draft_id": draft})

        assert result["rebased"] is True
        assert result["commit"] == REBUILT
        assert result["previous_commit"] == CANDIDATE
        assert deployer.adapter.calls == [{
            "candidate_sha": CANDIDATE, "base_sha": BASE, "branch": "preview",
            "message": "Re-apply reviewed change on the current website: Use the logo mark as the page icon",
        }]
        assert deployer.started == [{
            "branch": "preview", "commit": REBUILT, "draft_id": draft, "mode": "compiled_preview",
        }]
        meta = memory.get_draft(draft)["meta"]
        assert meta["head_sha"] == REBUILT
        assert meta["base_sha"] == CURRENT
        assert meta["preview"]["head_sha"] == REBUILT
        assert meta["preview"]["job_id"] == "job-rebuilt"
        assert meta["preview"]["status"] == "building"
        assert meta["rebased_from"] == [
            {"candidate_sha": CANDIDATE, "base_sha": BASE, "at": meta["rebased_from"][0]["at"]},
        ]
        assert memory.list_drafts()[0]["status"] == "pending"
    finally:
        memory.close()


def test_rebuild_refuses_while_the_same_review_is_building(tmp_path):
    memory, draft, deployer, service = _service(
        tmp_path, latest={"commit": CANDIDATE, "status": "running", "id": "live"},
    )
    try:
        with pytest.raises(BridgeError, match="already building"):
            service.source_preview_rebuild({"draft_id": draft})
        assert deployer.adapter.calls == []
        assert deployer.started == []
    finally:
        memory.close()


def test_rebuild_refuses_a_review_that_already_has_a_ready_preview(tmp_path):
    memory, draft, deployer, service = _service(
        tmp_path, latest={"commit": CANDIDATE, "status": "ready", "id": "live"},
    )
    try:
        with pytest.raises(BridgeError, match="already has a ready preview"):
            service.source_preview_rebuild({"draft_id": draft})
        assert deployer.started == []
    finally:
        memory.close()


def test_rebuild_only_applies_to_a_pending_source_review(tmp_path):
    memory, draft, deployer, service = _service(tmp_path)
    try:
        memory.update_draft_status(draft, "rejected")
        with pytest.raises(BridgeError, match="pending source review"):
            service.source_preview_rebuild({"draft_id": draft})
        assert deployer.started == []
    finally:
        memory.close()
