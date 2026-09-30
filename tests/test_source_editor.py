from __future__ import annotations

import hashlib
import json
from subprocess import CompletedProcess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_agent.application.workspace import ChatService, SourceConflict
from site_agent.application.source_editor import SourceConflictError, SourceEditorService
from site_agent.web.workspace import register_workspace_routes


SOURCE = '''const image = "https://old.example/image.jpg";
export function Hero() {
  return <h1>Hello workspace</h1>;
}
'''


class GithubDouble:
    def __init__(self, source: str):
        self.files = {
            "main": {"src/components/Hero.tsx": source.encode()},
            "preview": {"src/components/Hero.tsx": source.encode()},
        }
        self.ensure_calls: list[str] = []
        self.commits: list[dict] = []

    def validate(self):
        return None

    def list_files(self, *, branch):
        return list(self.files[branch])

    def get_file(self, path, *, branch=None):
        return f"blob-{branch}-{path}", self.files[branch][path]

    def ensure_branch(self, branch):
        self.ensure_calls.append(branch)
        if branch not in self.files:
            self.files[branch] = dict(self.files["main"])
        return {"branch": branch, "created": False}

    def commit_file(self, path, data, message, *, branch=None, expected_sha=None):
        self.commits.append({
            "path": path,
            "data": data,
            "message": message,
            "branch": branch,
            "expected_sha": expected_sha,
        })
        self.files[branch][path] = data
        return {"committed": True, "commit_sha": "commit-source-edit", "branch": branch}


def _service(tmp_path, adapter, inventory):
    script = tmp_path / "scripts" / "source-inventory.ts"
    script.parent.mkdir()
    script.write_text("// test inventory entry point\n", encoding="utf-8")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, json.dumps(inventory), "")

    config = {
        "site": {
            "repository": "owner/workspace",
            "branch": "main",
            "preview_branch": "preview",
            "writable_patterns": ["src/components/**"],
            "source_editor": {
                "inventory_script": str(script),
                "node_tool": ["tsx"],
            },
        },
    }
    return SourceEditorService(config, {}, adapter=adapter, runner=runner), calls


def _field(kind="literal", field_type="image", path="src/components/Hero.tsx"):
    if kind == "literal":
        start = SOURCE.index('"https://old.example/image.jpg"')
        end = start + len('"https://old.example/image.jpg"')
        raw = SOURCE[start:end]
        value = "https://old.example/image.jpg"
    else:
        start = SOURCE.index("Hello workspace")
        end = start + len("Hello workspace")
        raw = SOURCE[start:end]
        value = raw
    return {
        "id": "field-source-1",
        "file": path,
        "valueStart": start,
        "valueEnd": end,
        "raw": raw,
        "value": value,
        "type": field_type,
        "status": "editable",
        "editable": True,
        "kind": kind,
    }


def test_inventory_materializes_github_source_and_passes_root_to_tool(tmp_path):
    adapter = GithubDouble(SOURCE)
    inventory = {"version": 1, "fields": [], "filesScanned": 1}
    service, calls = _service(tmp_path, adapter, inventory)

    result = service.inventory({"branch": "main"})

    assert result["branch"] == "main"
    assert result["source"] == "github_materialized"
    assert result["inventory"] == inventory
    command = calls[0][0]
    assert command[:2] == ["tsx", str(tmp_path / "scripts" / "source-inventory.ts")]
    assert command[-2] == "--root"
    assert calls[0][1]["cwd"]
    assert adapter.commits == []


def test_edit_patches_string_literal_and_commits_only_to_preview(tmp_path):
    adapter = GithubDouble(SOURCE)
    field = _field()
    inventory = {"version": 1, "fields": [field], "filesScanned": 1}
    service, _calls = _service(tmp_path, adapter, inventory)
    field["sourceHash"] = hashlib.sha256(SOURCE.encode()).hexdigest()

    result = service.edit({"branch": "main", "field": field, "value": "https://new.example/image.jpg"})

    assert result["branch"] == "preview"
    assert result["commit"]["commit_sha"] == "commit-source-edit"
    assert adapter.ensure_calls == []
    assert len(adapter.commits) == 1
    assert adapter.commits[0]["branch"] == "preview"
    assert b'const image = "https://new.example/image.jpg";' in adapter.commits[0]["data"]


def test_edit_accepts_portable_asset_image_reference(tmp_path):
    adapter = GithubDouble(SOURCE)
    field = _field()
    field["sourceHash"] = hashlib.sha256(SOURCE.encode()).hexdigest()
    service, _calls = _service(tmp_path, adapter, {"version": 1, "fields": [field]})

    service.edit({"field": field, "value": "asset:0123456789abcdef"})

    assert b'const image = "asset:0123456789abcdef";' in adapter.commits[0]["data"]


def test_edit_patches_jsx_text_and_rejects_stale_source(tmp_path):
    adapter = GithubDouble(SOURCE)
    field = _field(kind="jsx-text", field_type="text")
    field["sourceHash"] = hashlib.sha256(SOURCE.encode()).hexdigest()
    inventory = {"version": 1, "fields": [field], "filesScanned": 1}
    service, _calls = _service(tmp_path, adapter, inventory)

    result = service.edit({"field": field, "value": "Bonjour"})
    assert b">Bonjour</h1>" in adapter.commits[0]["data"]
    assert result["value"] == "Bonjour"

    adapter.files["preview"]["src/components/Hero.tsx"] = b"const changed = true;\n"
    with pytest.raises(SourceConflictError, match="source changed"):
        service.edit({"field": field, "value": "Encore"})
    assert len(adapter.commits) == 1


def test_edit_rejects_range_conflict_before_commit(tmp_path):
    adapter = GithubDouble(SOURCE)
    field = _field()
    field["sourceHash"] = hashlib.sha256(SOURCE.encode()).hexdigest()
    inventory = {"version": 1, "fields": [field], "filesScanned": 1}
    service, _calls = _service(tmp_path, adapter, inventory)

    with pytest.raises(SourceConflictError, match="range"):
        service.edit({"field": field, "raw": '"not-the-current-value"', "value": "https://new.example"})
    assert adapter.commits == []


def test_edit_converts_typescript_utf16_ranges_before_patching(tmp_path):
    source = 'const copy = "😀 hello";\n'
    adapter = GithubDouble(source)
    path = "src/components/Emoji.tsx"
    adapter.files["main"] = {path: source.encode()}
    adapter.files["preview"] = {path: source.encode()}
    raw = '"😀 hello"'
    start = len('const copy = '.encode('utf-16-le')) // 2
    end = start + len(raw.encode('utf-16-le')) // 2
    field = {
        "id": "field-emoji",
        "file": path,
        "valueStart": start,
        "valueEnd": end,
        "raw": raw,
        "value": "😀 hello",
        "type": "text",
        "status": "editable",
        "editable": True,
        "kind": "literal",
        "sourceHash": hashlib.sha256(source.encode()).hexdigest(),
    }
    service, _calls = _service(tmp_path, adapter, {"version": 1, "fields": [field]})

    service.edit({"field": field, "value": "Bonjour"})

    assert b'const copy = "Bonjour";' in adapter.commits[0]["data"]


def test_batch_patches_image_and_jsx_text_with_one_commit_for_the_file(tmp_path):
    adapter = GithubDouble(SOURCE)
    image = _field()
    heading = _field(kind="jsx-text", field_type="text")
    source_hash = hashlib.sha256(SOURCE.encode()).hexdigest()
    image["sourceHash"] = source_hash
    heading["sourceHash"] = source_hash
    service, _calls = _service(tmp_path, adapter, {"version": 1, "fields": [image, heading]})

    result = service.edit({
        "edits": [
            {"field": image, "value": "/media/new-lamp.jpg"},
            {"field": heading, "value": "Bonjour workspace"},
        ],
    })

    assert result["batch"] is True
    assert len(result["files"]) == 1
    assert len(result["commits"]) == 1
    assert len(adapter.commits) == 1
    committed = adapter.commits[0]["data"]
    assert b'const image = "/media/new-lamp.jpg";' in committed
    assert b">Bonjour workspace</h1>" in committed


def test_batch_commits_once_per_file_and_validates_all_before_writing(tmp_path):
    adapter = GithubDouble(SOURCE)
    other_path = "src/components/Other.tsx"
    adapter.files["main"][other_path] = SOURCE.encode()
    adapter.files["preview"][other_path] = SOURCE.encode()
    first = _field(path="src/components/Hero.tsx")
    second = _field(kind="jsx-text", field_type="text", path=other_path)
    source_hash = hashlib.sha256(SOURCE.encode()).hexdigest()
    first["sourceHash"] = source_hash
    second["sourceHash"] = source_hash
    service, _calls = _service(tmp_path, adapter, {"version": 1, "fields": [first, second]})

    result = service.edit({
        "edits": [
            {"field": first, "value": "https://new.example/lamp.jpg"},
            {"field": second, "value": "Other heading"},
        ],
    })

    assert len(result["files"]) == 2
    assert len(result["commits"]) == 2
    assert len(adapter.commits) == 2
    assert {item["path"] for item in adapter.commits} == {"src/components/Hero.tsx", other_path}

    adapter.commits.clear()
    adapter.files["preview"]["src/components/Hero.tsx"] = SOURCE.encode()
    adapter.files["preview"][other_path] = SOURCE.encode()
    second["sourceHash"] = "stale-source-hash"
    with pytest.raises(SourceConflictError, match="source changed"):
        service.edit({
            "edits": [
                {"field": first, "value": "https://new.example/again.jpg"},
                {"field": second, "value": "Rejected heading"},
            ],
        })
    assert adapter.commits == []


def test_preview_styles_reads_the_preview_branch_without_running_a_build(tmp_path):
    adapter = GithubDouble(SOURCE)
    path = "src/app/(frontend)/styles.css"
    adapter.files["preview"][path] = b".nav-dropdown { display: flex; align-items: stretch; }\n"
    service, calls = _service(tmp_path, adapter, {"version": 1, "fields": []})

    result = service.preview_styles()

    assert result["path"] == path
    assert result["branch"] == "preview"
    assert result["content"].startswith(".nav-dropdown")
    assert calls == []


class BridgeSourceEditor:
    def inventory(self, body):
        return {"branch": body.get("branch", "main"), "inventory": {"fields": []}}

    def edit(self, body):
        if "edits" in body:
            assert isinstance(body["edits"], list)
            return {"ok": True, "batch": True, "files": []}
        raise SourceConflictError("source changed since inventory")

    def preview_styles(self):
        return {
            "path": "src/app/(frontend)/styles.css",
            "branch": "preview",
            "sha": "blob-preview-styles",
            "source_hash": "hash-preview-styles",
            "content": ".nav-dropdown { display: flex; }",
        }


class BridgeSourceDeployment:
    def start(self, body):
        return {"id": "source-job-1", "status": "queued", "branch": body.get("branch", "preview")}

    def status(self, job_id):
        return {"id": job_id, "status": "ready", "preview_url": "https://draft.example"}

    def latest(self, branch=None):
        return {"id": "source-job-1", "status": "ready", "branch": branch or "preview"}

    def promote(self, job_id):
        return {"id": job_id, "status": "deployed", "deployed_version_id": "version-1"}


def test_source_routes_require_auth_and_validate_edit_requests():
    app = FastAPI()
    service = ChatService(source_editor=BridgeSourceEditor())
    register_workspace_routes(
        app,
        config={},
        env={"WORKSPACE_SITE_AGENT_TOKEN": "workspace-secret"},
        service=service,
    )

    with TestClient(app) as client:
        assert client.post("/api/workspace/source/inventory", json={}).status_code == 401
        assert client.post(
            "/api/workspace/source/inventory",
            headers={"Authorization": "Bearer workspace-secret"},
            json=[],
        ).status_code == 400
        inventory = client.post(
            "/api/workspace/source/inventory",
            headers={"Authorization": "Bearer workspace-secret"},
            json={"branch": "main"},
        )
        batch = client.post(
            "/api/workspace/source/edit",
            headers={"Authorization": "Bearer workspace-secret"},
            json={"edits": [{"value": "new"}]},
        )
        conflict = client.post(
            "/api/workspace/source/edit",
            headers={"Authorization": "Bearer workspace-secret"},
            json={"field": {}, "value": "new"},
        )
        styles = client.get(
            "/api/workspace/source/preview/styles",
            headers={"Authorization": "Bearer workspace-secret"},
        )

    assert inventory.status_code == 200
    assert inventory.json()["branch"] == "main"
    assert batch.status_code == 200
    assert batch.json()["batch"] is True
    assert conflict.status_code == 409
    assert styles.status_code == 200
    assert styles.json()["branch"] == "preview"
    assert "display: flex" in styles.json()["content"]


def test_source_preview_routes_require_auth_and_return_job_status():
    app = FastAPI()
    service = ChatService(source_deployment=BridgeSourceDeployment())
    register_workspace_routes(
        app,
        config={},
        env={"WORKSPACE_SITE_AGENT_TOKEN": "workspace-secret"},
        service=service,
    )

    with TestClient(app) as client:
        assert client.post("/api/workspace/source/preview", json={}).status_code == 401
        started = client.post(
            "/api/workspace/source/preview",
            headers={"Authorization": "Bearer workspace-secret"},
            json={"branch": "preview", "commit": "abc"},
        )
        status = client.get(
            "/api/workspace/source/preview/source-job-1",
            headers={"Authorization": "Bearer workspace-secret"},
        )
        latest = client.get(
            "/api/workspace/source/preview?branch=preview",
            headers={"Authorization": "Bearer workspace-secret"},
        )
        deployed = client.post(
            "/api/workspace/source/preview/source-job-1/deploy",
            headers={"Authorization": "Bearer workspace-secret"},
        )

    assert started.status_code == 200
    assert started.json()["id"] == "source-job-1"
    assert status.status_code == 200
    assert status.json()["preview_url"] == "https://draft.example"
    assert latest.status_code == 200
    assert latest.json()["branch"] == "preview"
    assert deployed.status_code == 200
    assert deployed.json()["status"] == "deployed"
