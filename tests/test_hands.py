import json
import subprocess

import pytest

from site_agent.hands import ADAPTERS, AdapterError, get_adapter
from site_agent.hands import cloudflare_pages, github_static  # noqa: F401
from site_agent.hands import neutral_scaffold  # noqa: F401


def _config(adapter="github_static", **site):
    return {
        "env": {"github_token": "GITHUB_TOKEN", "cloudflare_api_token": "CF_TOKEN"},
        "site": {
            "adapter": adapter,
            "repository": "acme/site",
            "branch": "main",
            "content_path": "content.json",
            **site,
        },
    }


def test_adapters_are_registered():
    assert "github_static" in ADAPTERS
    assert "cloudflare_pages" in ADAPTERS
    assert "neutral_scaffold" in ADAPTERS


def test_unknown_adapter_raises():
    with pytest.raises(AdapterError):
        get_adapter("nope", {})


def test_github_static_validates_repo_and_token():
    adapter = get_adapter("github_static", _config(repository=""))
    with pytest.raises(AdapterError):
        adapter.validate()
    adapter = get_adapter("github_static", _config())
    adapter.root["env"]["github_token"] = ""
    with pytest.raises(AdapterError):
        adapter.validate()


def test_commit_file_puts_b64_content_with_existing_sha(monkeypatch):
    calls = []

    def fake_request(method, url, token=None, payload=None, timeout=30):
        calls.append((method, url, payload))
        if method == "GET":
            return 200, {"sha": "abc123", "content": ""}
        return 200, {"commit": {"sha": "deadbeef"}, "content": {"html_url": "https://x/y"}}

    monkeypatch.setattr(github_static, "_request", fake_request)
    adapter = get_adapter("github_static", _config())
    result = adapter.commit_file("content.json", b'{"a":1}', "Update content")
    method, url, payload = calls[-1]
    assert method == "PUT"
    assert url.endswith("/repos/acme/site/contents/content.json")
    assert payload["sha"] == "abc123"
    assert payload["branch"] == "main"
    assert json.loads(__import__("base64").b64decode(payload["content"])) == {"a": 1}
    assert result["committed"] is True
    assert result["commit_sha"] == "deadbeef"


def test_get_content_parses_json(monkeypatch):
    monkeypatch.setattr(
        github_static,
        "_request",
        lambda *a, **k: (200, {"sha": "s", "content": __import__("base64").b64encode(b'{"hero":"hi"}').decode()}),
    )
    adapter = get_adapter("github_static", _config())
    assert adapter.get_content() == {"hero": "hi"}


def test_cloudflare_pages_inherits_commit_and_reports_unconfigured_status():
    adapter = get_adapter("cloudflare_pages", _config("cloudflare_pages", cloudflare={"account_id": "", "project_name": "", "mode": "git"}))
    assert isinstance(adapter, github_static.GithubStatic)
    assert adapter.status() == {"adapter": "cloudflare_pages", "mode": "git", "deployment": "unconfigured"}


def test_cloudflare_pages_status_reads_latest_deployment(monkeypatch):
    config = _config(
        "cloudflare_pages",
        cloudflare={"account_id": "acc1", "project_name": "ov", "mode": "git"},
    )
    adapter = get_adapter("cloudflare_pages", config)

    def fake_cf(url, token):
        assert "accounts/acc1/pages/projects/ov/deployments" in url
        assert token == "CF_VALUE"
        return {
            "success": True,
            "result": [
                {
                    "id": "dep1",
                    "url": "https://ov.pages.dev",
                    "environment": "production",
                    "modified_on": "2026-08-22T00:00:00Z",
                    "latest_stage": {"name": "deploy", "status": "success"},
                }
            ],
        }

    monkeypatch.setattr(cloudflare_pages, "_cf_request", fake_cf)
    monkeypatch.setattr(cloudflare_pages, "secret", lambda root, name: "CF_VALUE")
    status = adapter.status()
    assert status["deployment"]["status"] == "success"
    assert status["deployment"]["stage"] == "deploy"


def test_cloudflare_direct_mode_rejected_until_phase4():
    adapter = get_adapter(
        "cloudflare_pages",
        _config("cloudflare_pages", cloudflare={"account_id": "a", "project_name": "p", "mode": "direct"}),
    )
    with pytest.raises(AdapterError):
        adapter.validate()


def test_restore_snapshot_creates_one_atomic_commit_from_target_tree(monkeypatch):
    calls = []

    def fake_request(method, url, token=None, payload=None, timeout=30):
        calls.append((method, url, payload))
        if method == "GET" and "/commits/target" in url:
            return 200, {"commit": {"tree": {"sha": "target-tree"}}}
        if method == "GET" and "/git/ref/heads/main" in url:
            return 200, {"object": {"sha": "current-sha"}}
        if method == "GET" and "/commits/current-sha" in url:
            return 200, {"commit": {"tree": {"sha": "current-tree"}}}
        if method == "GET" and "/git/trees/target-tree" in url:
            return 200, {"tree": [
                {"path": "index.html", "mode": "100644", "type": "blob", "sha": "old-index"},
            ]}
        if method == "GET" and "/git/trees/current-tree" in url:
            return 200, {"tree": [
                {"path": "index.html", "mode": "100644", "type": "blob", "sha": "new-index"},
                {"path": "new.css", "mode": "100644", "type": "blob", "sha": "new-css"},
            ]}
        if method == "POST" and "/git/trees" in url:
            return 201, {"sha": "rollback-tree"}
        if method == "POST" and "/git/commits" in url:
            return 201, {"sha": "rollback-commit"}
        if method == "PATCH" and "/git/refs/heads/preview" in url:
            return 200, {"object": {"sha": "rollback-commit"}}
        raise AssertionError((method, url, payload))

    monkeypatch.setattr(github_static, "_request", fake_request)
    adapter = get_adapter("github_static", _config())
    result = adapter.restore_snapshot("target", "preview", "Restore version")

    assert result["committed"] is True
    tree_call = next(call for call in calls if call[0] == "POST" and "/git/trees" in call[1])
    entries = tree_call[2]["tree"]
    assert {entry["path"] for entry in entries} == {"index.html", "new.css"}
    assert next(entry for entry in entries if entry["path"] == "index.html")["sha"] == "old-index"
    assert next(entry for entry in entries if entry["path"] == "new.css")["sha"] is None


def test_merge_design_candidate_refuses_stale_production_head(monkeypatch):
    calls = []

    def fake_request(method, url, token=None, payload=None, timeout=30):
        calls.append((method, url, payload))
        if method == "GET":
            return 200, {"object": {"sha": "current-sha"}}
        raise AssertionError("a stale candidate must not call the merge endpoint")

    monkeypatch.setattr(github_static, "_request", fake_request)
    adapter = get_adapter("github_static", _config())
    result = adapter.merge_design_candidate("unused", "c" * 40, "b" * 40, "Approve design")

    assert result["merged"] is False
    assert result["status"] == 409
    assert result["candidate_sha"] == "c" * 40
    assert len(calls) == 1


def test_merge_design_candidate_uses_reviewed_sha(monkeypatch):
    calls = []

    def fake_request(method, url, token=None, payload=None, timeout=30):
        calls.append((method, url, payload))
        if method == "GET":
            return 200, {"object": {"sha": "b" * 40}}
        return 201, {"sha": "m" * 40, "parents": [{"sha": "b" * 40}], "html_url": "https://x/merge"}

    monkeypatch.setattr(github_static, "_request", fake_request)
    adapter = get_adapter("github_static", _config())
    result = adapter.merge_design_candidate("unused", "c" * 40, "b" * 40, "Approve design")

    assert result == {
        "merged": True,
        "path": f"{'c' * 40}->main",
        "candidate_sha": "c" * 40,
        "commit_sha": "m" * 40,
        "parent_sha": "b" * 40,
        "html_url": "https://x/merge",
    }
    assert calls[-1][2]["head"] == "c" * 40


def test_neutral_scaffold_keeps_candidate_local_until_owner_merge(tmp_path):
    repo = tmp_path / "site"
    repo.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    (repo / "index.html").write_text("baseline")
    (repo / "content.json").write_text('{"title":"baseline"}\n')
    git("add", "-A")
    git("commit", "-qm", "baseline")
    base_sha = git("rev-parse", "HEAD").stdout.strip()
    git("checkout", "-q", "-b", "candidate")
    (repo / "index.html").write_text("candidate")
    git("add", "index.html")
    git("commit", "-qm", "candidate")
    candidate_sha = git("rev-parse", "HEAD").stdout.strip()
    git("checkout", "-q", "main")

    adapter = get_adapter("neutral_scaffold", {
        "site": {
            "adapter": "neutral_scaffold",
            "clone_path": str(repo),
            "branch": "main",
            "content_path": "content.json",
        },
    })
    adapter.validate()
    assert adapter.status()["remote"] is False
    assert git("rev-parse", "main").stdout.strip() == base_sha
    assert adapter.get_file("index.html")[1] == b"baseline"

    merged = adapter.merge_design_candidate({}, candidate_sha, base_sha, "Approve design")

    assert merged["merged"] is True
    assert merged["candidate_sha"] == candidate_sha
    assert merged["parent_sha"] == base_sha
    assert git("rev-parse", "main").stdout.strip() == merged["commit_sha"]
    assert adapter.get_file("index.html")[1] == b"candidate"


from site_agent.hands.opencode_runner import ProseFilter, _looks_like_prose  # noqa: E402


def test_prose_filter_keeps_agent_words():
    f = ProseFilter()
    assert f.feed("I'll wire the ScrollTrigger timeline now") == "I'll wire the ScrollTrigger timeline now"
    assert f.feed("The hero gets a continuous descent as you scroll.").startswith("The hero")
    assert f.feed("- added the depth counter to the hero") == "- added the depth counter to the hero"


def test_looks_like_prose_drops_repo_artifacts():
    assert not _looks_like_prose("-rw-r--r-- 1 ada ada 1234 index.html")
    assert not _looks_like_prose("drwxr-xr-x 2 ada ada 4096 .git")
    assert not _looks_like_prose("total 48")
    assert not _looks_like_prose("diff --git a/index.html b/index.html")
    assert not _looks_like_prose("padding: 40px;")
    assert not _looks_like_prose("color: #fff")
    assert not _looks_like_prose("styles.css")
    assert not _looks_like_prose("→ Read index.html")
    assert not _looks_like_prose("✗ Read styles.css failed")
    assert not _looks_like_prose("")
    assert _looks_like_prose("fetching origin")            # real agent phrase, kept


def test_prose_filter_skips_code_fences_and_listings():
    f = ProseFilter()
    assert f.feed("```css") == ""
    assert f.feed(".hero { padding: 40px; }") == ""          # inside fence
    assert f.feed("```") == ""
    assert f.feed("Now the hero breathes.") == "Now the hero breathes."  # back in prose


def test_prose_filter_keeps_prose_that_mentions_filenames():
    # a natural summary sentence is kept even though it names files
    assert _looks_like_prose("I updated styles.css and app.js")
    assert not _looks_like_prose("styles.css app.js index.html")  # bare listing still dropped
