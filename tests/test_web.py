import json

import pytest
from fastapi.testclient import TestClient

from site_agent.brain.editor import slugify
from site_agent.core.contracts import (
    ActionPriority,
    ActionRequirement,
    ApprovalRequest,
    Artifact,
    ArtifactKind,
    EffectClass,
    OwnerAction,
)
from site_agent.core.memory import Memory
from site_agent.hands.base import SiteAdapter
from site_agent.web.server import create_app


class FakeAdapter(SiteAdapter):
    name = "fake"

    def __init__(self, files=None):
        self.site = {}
        self.files = files or {}
        self.branch = "main"
        self.commits = []
        self._n = 0

    def validate(self):
        return None

    def get_file(self, path, branch=None):
        raw = self.files.get(path)
        return (None, None) if raw is None else ("sha-" + path, raw.encode())

    def ensure_branch(self, name):
        return {"created": True, "branch": name}

    def list_files(self):
        return sorted(set(self.files) | {"index.html", "styles.css"})

    def commit_file(self, path, data, message, branch=None):
        self._n += 1
        self.commits.append({"path": path, "body": data.decode(), "message": message, "branch": branch or self.branch})
        self.files[path] = data.decode()
        return {"committed": True, "path": path, "commit_sha": "abc123%040d" % self._n, "branch": branch or self.branch}

    def delete_file(self, path, message, branch=None):
        self.files.pop(path, None)
        target_branch = branch or self.branch
        self.commits.append({"path": path, "message": message, "deleted": True, "branch": target_branch})
        return {"deleted": True, "path": path, "branch": target_branch}

    def restore_snapshot(self, target_sha, branch, message):
        self._n += 1
        self.commits.append({"path": "site", "message": message, "branch": branch})
        return {
            "committed": True,
            "branch": branch,
            "commit_sha": "rollback%040d" % self._n,
            "parent_sha": "current123",
            "target_sha": target_sha,
            "path": "site",
        }


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return self.replies.pop(0)

    def chat_tools(self, messages, tools, **kwargs):
        self.calls.append(messages)
        raw = self.replies.pop(0)
        if isinstance(raw, str):
            raw = json.loads(raw)
        reply = raw.get("reply", "")
        action = raw.get("action")
        if not action or not action.get("type"):
            return {"content": reply, "tool_calls": None}
        name = action["type"]
        args = {k: v for k, v in action.items() if k != "type"}
        return {"content": reply, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}}]}


@pytest.fixture
def runtime(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    config = {
        "env": {
            "admin_password": "SITE_AGENT_ADMIN_PASSWORD",
            "github_token": "GITHUB_TOKEN",
        },
        "instance_name": "testsite",
        "site": {"adapter": "github_static", "repository": "acme/site",
                 "preview_branch": "",
                 "writable_patterns": ["src/app/(frontend)/site.css", "src/components/site/presentation/**"]},
        "persona": {"name": "Ada", "voice": "", "audience": "", "taboo": []},
        "admin": {"host": "127.0.0.1", "port": 3011},
    }
    adapter = FakeAdapter()
    env = {"SITE_AGENT_ADMIN_PASSWORD": "sekret"}

    from fastapi.testclient import TestClient as TC  # noqa: F401
    import site_agent.web.server as server_mod

    context = {"config": config, "memory": memory, "llm": None, "scheduler": None}
    app = create_app(context, env=env)
    original_get_adapter = server_mod.get_adapter
    server_mod.get_adapter = lambda name, cfg: adapter

    with TestClient(app, base_url="https://testserver") as client:
        yield memory, config, adapter, context, client
    server_mod.get_adapter = original_get_adapter
    memory.close()


def _login(client, password="sekret"):
    return client.post("/api/login", json={"password": password})


def chat_and_wait(client, message, conversation_id=None):
    body = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    start = client.post("/api/chat", json=body).json()
    import time
    for _ in range(60):
        job = client.get(f"/api/chat/jobs/{start['job_id']}").json()
        if job["status"] == "done":
            result = dict(job["result"])
            result["conversation_id"] = start["conversation_id"]
            return result
        if job["status"] == "error":
            return {"reply": f"⚠ {job['error']}", "error": True,
                    "proposal_id": None, "conversation_id": start["conversation_id"]}
        time.sleep(0.1)
    raise AssertionError("chat job did not finish")


def test_auth_flow(runtime):
    _, _, _, _, client = runtime
    assert client.get("/api/status").status_code == 401
    assert _login(client, "wrong").status_code == 401
    assert _login(client).status_code == 200
    assert client.get("/api/session").json()["authenticated"] is True
    assert client.get("/api/status").status_code == 200


def test_status_shape(runtime):
    memory, config, _, _, client = runtime
    _login(client)
    status = client.get("/api/status").json()
    assert status["instance"] == "testsite"
    assert isinstance(status["upcoming"], list)
    assert "spend_7d" in status
    assert status["inner_self"]["version"] == 1
    assert status["worktree"]["available"] is False


def test_home_endpoint_returns_owner_action_sections(runtime):
    memory, _, _, _, client = runtime
    memory.create_owner_action(
        OwnerAction(
            capability_id="site.change.propose",
            provider_id="site-agent",
            title="Confirm the course dates",
            summary="Ada needs the new dates before updating your website.",
            action_label="Tell Ada the dates",
            priority=ActionPriority.URGENT,
            requirement=ActionRequirement.OWNER_INFORMATION,
            source_ref="test:course-dates",
            dedupe_key="test:course-dates",
        )
    )
    memory.kv_set("strategist_cards", {"cards": [{"title": "Write an article", "action": "Ask Ada to draft it"}]})
    memory.record_observation("inner_voice", "The visible thought belongs in the owner's console.", meta={"mood": "clear"})
    memory.record_observation("inner_voice", "The private thought stays in memory.", meta={"private": True, "mood": "secret"})
    memory.record_observation("dream", "A red buoy moved through the dark water.")
    memory.record_action("digest", "1 new reading note")
    _login(client)
    response = client.get("/api/home")
    assert response.status_code == 200
    payload = response.json()
    assert payload["needs_you"][0]["title"] == "Confirm the course dates"
    assert payload["ada_suggests"][0]["title"] == "Write an article"
    assert payload["ada_is_handling"]["active"] is False
    assert payload["inner_life"]["thought"]["text"] == "The visible thought belongs in the owner's console."
    assert "private thought" not in json.dumps(payload["inner_life"])
    assert payload["inner_life"]["dream"]["text"] == "A red buoy moved through the dark water."
    assert payload["inner_life"]["mood"] == ""
    assert payload["inner_life"]["activity"]["text"] == "digest - 1 new reading note"


def test_conversation_lifecycle_routes_preserve_tombstones(runtime):
    memory, _, _, _, client = runtime
    conversation_id = memory.create_conversation("Owner thread")
    memory.add_message(conversation_id, "user", "private text")
    _login(client)

    response = client.post(f"/api/conversations/{conversation_id}/archive")
    assert response.status_code == 200
    assert conversation_id not in {row["id"] for row in client.get("/api/conversations").json()["conversations"]}
    assert conversation_id in {
        row["id"] for row in client.get("/api/conversations?include_archived=true").json()["conversations"]
    }
    assert client.post(f"/api/conversations/{conversation_id}/restore").status_code == 200
    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 200
    tombstone = client.get(f"/api/conversations/{conversation_id}")
    assert tombstone.status_code == 200
    assert tombstone.json()["deleted"] is True
    assert tombstone.json()["messages"] == []


def test_artifact_approval_routes_use_approval_service(runtime):
    memory, _, _, _, client = runtime
    artifact = memory.create_artifact(
        Artifact(
            kind=ArtifactKind.ARTICLE,
            title="Prepared article",
            summary="Ready for review.",
            renderer="article",
            capability_id="content.article.prepare",
            provider_id="site-agent",
            content_hash="sha256:route",
            preview_data={"body": "hello"},
        )
    )
    approval = memory.create_approval_request(
        ApprovalRequest(
            artifact_id=artifact.artifact_id,
            artifact_hash=artifact.content_hash,
            effect_class=EffectClass.PROPOSAL,
            owner_action_label="Keep this draft",
            provider_id="site-agent",
        )
    )
    _login(client)
    queue = client.get("/api/approvals?status=pending")
    assert queue.status_code == 200
    assert queue.json()["approvals"][0]["artifact"]["title"] == "Prepared article"
    preview = client.get(f"/api/approvals/{approval.approval_id}")
    assert preview.status_code == 200
    assert preview.json()["artifact"]["title"] == "Prepared article"
    decided = client.post(f"/api/approvals/{approval.approval_id}/approve")
    assert decided.status_code == 200
    assert decided.json()["approval"]["status"] == "approved"


def test_seo_report_routes_include_artifact_and_article_research_context(runtime):
    memory, _, _, _, client = runtime
    artifact = memory.create_artifact(
        Artifact(
            kind=ArtifactKind.SEO_REPORT,
            title="Website SEO report 2026-07",
            summary="Monthly website report.",
            renderer="seo_report",
            capability_id="seo.report.read",
            provider_id="site-agent",
            content_hash="sha256:seo-report",
            preview_data={"body": "# Website SEO report: 2026-07\n\nTraffic improved."},
        )
    )
    report = memory.create_seo_site_report("2026-07")
    memory.update_seo_site_report(
        report["id"],
        status="completed",
        summary="Traffic improved.",
        artifact_id=artifact.artifact_id,
        evidence_json={"site": {"gsc": {"status": "ready"}}},
    )
    idea = memory.create_article_idea(
        "article:2026-W30",
        "idea-hash",
        {"working_title": "A useful guide", "audience_need": "Readers need clarity."},
    )
    memory.update_article_idea(idea["id"], status="drafted", draft_id=4)
    _login(client)

    latest = client.get("/api/seo/site-reports/latest")
    assert latest.status_code == 200
    assert latest.json()["report"]["artifact"]["preview_data"]["body"].startswith("# Website SEO")
    assert client.get("/api/seo/site-reports?limit=12").json()["reports"][0]["period"] == "2026-07"
    ideas = client.get("/api/seo/article-research?status=drafted").json()["ideas"]
    assert ideas[0]["idea_json"]["working_title"] == "A useful guide"
    detail = client.get(f"/api/seo/article-research/{idea['id']}")
    assert detail.status_code == 200
    assert detail.json()["idea"]["draft_id"] == 4


def test_article_rejections_endpoint_returns_captured_candidates(runtime):
    memory, _, _, _, client = runtime
    memory.record_rejected_article_idea(
        cycle_key="article:2026-W35",
        raw='{"working_title":"Rejected title"}',
        parsed={"working_title": "Rejected title"},
        reason="time-sensitive article ideas require a source URL",
    )
    _login(client)
    response = client.get("/api/seo/article-rejections")
    assert response.status_code == 200
    rejections = response.json()["rejections"]
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "time-sensitive article ideas require a source URL"
    assert rejections[0]["parsed_json"]["working_title"] == "Rejected title"


def test_action_lifecycle_routes_use_owner_action_service(runtime):
    memory, _, _, _, client = runtime
    from site_agent.core.contracts import ActionPriority, ActionRequirement, OwnerAction

    snoozed = memory.create_owner_action(
        OwnerAction(
            capability_id="content.suggestion",
            provider_id="site-agent",
            title="A future suggestion",
            summary="Not urgent.",
            action_label="Ask Ada to help",
            priority=ActionPriority.OPTIONAL,
            requirement=ActionRequirement.SUGGESTION,
            source_ref="test:snoozed-action",
            dedupe_key="test:snoozed-action",
        )
    )
    started = memory.create_owner_action(
        OwnerAction(
            capability_id="content.suggestion",
            provider_id="site-agent",
            title="A focused suggestion",
            summary="Ada can help.",
            action_label="Ask Ada to help",
            priority=ActionPriority.OPTIONAL,
            requirement=ActionRequirement.SUGGESTION,
            source_ref="test:started-action",
            dedupe_key="test:started-action",
        )
    )
    _login(client)
    response = client.post(f"/api/actions/{snoozed.id}/snooze", json={})
    assert response.status_code == 200
    assert response.json()["action"]["state"] == "snoozed"
    assert snoozed.id not in {action["id"] for action in client.get("/api/home").json()["ada_suggests"]}

    response = client.post(f"/api/actions/{started.id}/start", json={})
    assert response.status_code == 200
    assert response.json()["action"]["conversation_id"] is not None
    assert client.post(f"/api/actions/{started.id}/dismiss").status_code == 409


def test_chat_links_started_owner_action_to_its_job(runtime):
    memory, _, _, context, client = runtime
    action = memory.create_owner_action(
        OwnerAction(
            capability_id="content.suggestion",
            provider_id="site-agent",
            title="Prepare a welcome page",
            summary="Ada can prepare the first draft.",
            action_label="Ask Ada to help",
            priority=ActionPriority.OPTIONAL,
            requirement=ActionRequirement.SUGGESTION,
            source_ref="test:chat-action",
            dedupe_key="test:chat-action",
        )
    )
    conversation_id = memory.create_conversation("Welcome page")
    context["llm"] = FakeLLM([json.dumps({"reply": "Working on it.", "action": None})])
    _login(client)

    response = client.post(
        "/api/chat",
        json={"message": "prepare the welcome page", "conversation_id": conversation_id, "action_id": action.id},
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    linked = memory.get_owner_action(action.id)
    assert linked.job_id == job_id
    assert linked.state.value == "started"

    import time
    for _ in range(60):
        job = memory.get_chat_job(job_id)
        if job["status"] in {"done", "error"}:
            break
        time.sleep(0.1)
    assert memory.get_chat_job(job_id)["status"] == "done"
    assert memory.get_owner_action(action.id).state.value == "completed"


def test_failed_chat_job_moves_linked_owner_action_to_waiting_atomically(runtime):
    memory, _, _, _, _ = runtime
    action = memory.create_owner_action(
        OwnerAction(
            capability_id="content.suggestion",
            provider_id="site-agent",
            title="Prepare a welcome page",
            summary="Ada can prepare the first draft.",
            action_label="Ask Ada to help",
            priority=ActionPriority.OPTIONAL,
            requirement=ActionRequirement.SUGGESTION,
            source_ref="test:failed-chat-action",
            dedupe_key="test:failed-chat-action",
        )
    )
    conversation_id = memory.create_conversation("Welcome page")
    job_id = memory.enqueue_chat_job(conversation_id, "Prepare the welcome page")
    memory.transition_owner_action(action.id, "started")
    memory.link_owner_action(action.id, conversation_id=conversation_id, job_id=job_id)

    job = memory.claim_chat_job("test-worker")
    assert job is not None
    assert job["id"] == job_id
    assert memory.fail_chat_job(job_id, "test-worker", "provider failed")

    assert memory.get_chat_job(job_id)["status"] == "error"
    assert memory.get_owner_action(action.id).state.value == "waiting"


def test_dirty_worktree_is_not_exposed_in_customer_ui(runtime, tmp_path):
    import subprocess

    memory, config, _, _, client = runtime
    clone = tmp_path / "site"
    clone.mkdir()
    subprocess.run(["git", "-C", str(clone), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    (clone / "app.js").write_text("const version = 'published';\n")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "published"], check=True)
    (clone / "app.js").write_text("const version = 'local';\n")
    (clone / "scratch.txt").write_text("untracked local work\n")
    config["site"]["clone_path"] = str(clone)

    _login(client)
    state = client.get("/api/status").json()["worktree"]
    assert state["available"] and state["dirty"]
    assert {f["path"] for f in state["files"]} == {"app.js", "scratch.txt"}
    page = client.get("/").text
    assert "repoNotice" not in page and "/site/worktree/discard" not in page
    assert "designBuildStatus" not in page and "Check again" not in page

    discarded = client.post("/api/site/worktree/discard")
    assert discarded.status_code == 200
    assert (clone / "app.js").read_text() == "const version = 'published';\n"
    assert not (clone / "scratch.txt").exists()
    assert client.get("/api/status").json()["worktree"]["dirty"] is False


def test_dirty_worktree_cannot_be_discarded_during_chat_job(runtime, tmp_path):
    import subprocess

    memory, config, _, _, client = runtime
    clone = tmp_path / "site"
    clone.mkdir()
    subprocess.run(["git", "-C", str(clone), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    (clone / "app.js").write_text("published\n")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "published"], check=True)
    (clone / "app.js").write_text("local\n")
    config["site"]["clone_path"] = str(clone)
    conv = memory.create_conversation("busy")
    job_id = memory.enqueue_chat_job(conv, "work")
    assert memory.claim_chat_job("test-worker")["id"] == job_id
    _login(client)
    response = client.post("/api/site/worktree/discard")
    assert response.status_code == 409
    memory.interrupt_running_chat_jobs()


def test_theme_endpoint_defaults_and_overrides(runtime):
    memory, config, _, _, client = runtime
    _login(client)
    theme = client.get("/api/theme").json()
    assert theme["bg"] == "#f6f8f4"
    assert theme["accent"] == "#0b6968"
    assert "font_body" in theme and "fonts_url" in theme

    config["admin"]["theme"] = {"bg": "#061116", "accent": "#9edbd1"}
    theme2 = client.get("/api/theme").json()
    assert theme2["bg"] == "#061116"
    assert theme2["accent"] == "#9edbd1"
    assert theme2["card"] == "#fffefa"  # untouched fields keep defaults


def test_restore_version_creates_pending_rollback(runtime):
    memory, config, adapter, _, client = runtime
    config["site"]["preview_branch"] = "preview"
    _login(client)
    did = memory.save_draft("Article X", "body", kind="article")
    memory.log_publish("site update: frontend", "frontend", "a" * 40, draft_id=did, version_type="merge")
    versions = client.get("/api/versions")
    assert versions.status_code == 200 and versions.json()["versions"][0]["current"] is True
    version_id = versions.json()["versions"][0]["id"]
    resp = client.post(f"/api/versions/{version_id}/restore")
    assert resp.status_code == 200
    draft = memory.list_drafts(status="pending")[0]
    assert draft["kind"] == "rollback"
    assert resp.json()["draft_id"] == draft["id"]


def test_design_ui_uses_internal_review_state(runtime):
    _, _, _, _, client = runtime
    html = client.get("/").text
    assert "journal_preview_url" not in html
    assert "renderPreviewLink" not in html
    assert "id=\"previewlink\"" not in html
    assert 'id="preview" title="Staged site preview" sandbox="allow-scripts allow-forms"' in html
    assert 'id="designVariantPicker"' in html
    assert 'value="original"' in html
    assert 'value="deepseek"' in html
    assert "function setDesignPreviewVariant(value)" in html
    assert "REQUESTED_DESIGN_RUN_ID" in html
    assert "selectDesignRun(REQUESTED_DESIGN_RUN_ID)" in html
    assert "preview-token" in html
    assert "id=\"designBuildStatus\"" not in html
    assert "loadJournal" not in html
    assert "enableJournal" not in html
    assert "id=\"designNote\"" not in html
    assert "loadBuildStatus" not in html
    assert "function watchBackgroundJob(jobId)" in html
    assert 'data-tab="overview" onclick="switchTab(\'overview\')">Home</button>' in html
    assert 'data-tab="content" onclick="switchTab(\'content\')">Website</button>' in html
    assert 'data-tab="design" onclick="switchTab(\'design\')">Review</button>' in html
    assert 'data-tab="media" onclick="switchTab(\'media\')">Photos</button>' in html
    assert "async function autoReview(request)" in html
    assert "function isVisualDraft(kind)" in html
    assert "kind==='article'" in html
    assert "isVisualDraft(d.kind)?`<button class=\"quiet\" onclick=\"enterReview(${d.id})\">Review</button>`" in html
    assert 'id="draftDetailsDialog"' in html
    assert "showDraftDetails" in html
    assert 'onclick="showDraftDetails(${d.id})"' in html
    assert 'id="btnDetails"' in html
    assert "Show decision record" in html
    assert "View proposal details" in html
    assert "if(request!==designRequest)return;" in html
    assert "setDesignButtons();await reloadPreview();" in html
    assert "Website versions" in html
    assert "Preview this version" in html
    assert "Bring this version back" in html
    assert "Recent work" in html
    assert 'id="homeNeeds"' in html
    assert 'id="homeSuggests"' in html
    assert 'id="homeHandlingSummary"' in html
    assert 'id="homeInnerLife"' in html
    assert 'id="homeThought"' in html
    assert 'id="homeDream"' in html
    assert "renderInnerLife" in html
    assert 'class="inner-life-bar"' in html
    assert 'class="home-section inner-life"' not in html
    assert "inner-life-thought" not in html
    assert "splitInnerLifeText" in html
    assert "-webkit-line-clamp:3" in html
    assert "setInterval(show,6500)" in html
    assert "button.primary{background:var(--brand)" in html
    assert 'summary>More details</summary>' in html
    assert "api('/home')" in html
    assert "function renderHomeError(message)" in html
    assert 'aria-label="Dismiss ${actionTitle}"' in html
    assert "homeSnooze" in html
    assert "approvalQueue" in html
    assert "rendered_preview" in html
    assert "Publish this change" in html
    assert "Keep current" in html
    assert "feedbackDialog" in html
    assert "prompt(" not in html
    assert "chat-titlebar" in html
    assert "New chat" in html
    assert 'data-chat-tab="chat"' in html
    assert 'data-chat-tab="history"' in html
    assert "switchChatTab" in html
    assert "conversationList" in html
    assert "conversationDialog" not in html
    assert "convsel" not in html
    assert "#chat{width:100%;height:390px" in html
    assert "#chat{display:none}" not in html
    assert "focus-visible" in html
    assert "loadConversationHistory" in html
    assert "openConversationFromHistory" in html
    assert "archiveConversation" in html
    assert "removeConversation" in html
    assert "Permanently delete this conversation" not in html
    assert "clearConversations()" not in html
    assert "const isFormData = typeof FormData !== 'undefined' && opts.body instanceof FormData;" in html
    assert "if(isFormData) headers.delete('Content-Type');" in html
    assert "if(path.endsWith('/index.html'))path=path.slice(0,-'/index.html'.length);" in html
    assert "xhr.open('POST',BASE+'/api/media/upload',true);" in html
    assert "xhr.upload.onprogress" in html


def test_media_ui_has_visible_upload_queue_and_previews(runtime):
    _, _, _, _, client = runtime
    html = client.get("/").text
    assert 'id="mediaUploadQueue"' in html
    assert 'id="mediaQueueList"' in html
    assert "XMLHttpRequest" in html
    assert "renderMediaQueue" in html
    assert "thumbnail_url" in html
    assert "Processing" in html


def test_file_backed_content_api_is_retired(runtime):
    _memory, _config, adapter, _, client = runtime
    _login(client)
    assert client.get("/api/content").status_code == 404
    assert client.post("/api/content", json={"content": {"title": "not stored here"}}).status_code == 404
    assert adapter.commits == []


def test_review_endpoint_never_serves_unbuilt_source_files(tmp_path, monkeypatch):
    import subprocess

    clone = tmp_path / "siterepo"
    clone.mkdir()
    subprocess.run(["git", "-C", str(clone), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    (clone / "index.html").write_text("<html>old</html>")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "main v1"], check=True)
    (clone / "index.html").write_text("<html>new staged</html>")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "preview work"], check=True)
    subprocess.run(["git", "-C", str(clone), "branch", "-M", "preview"], check=True)

    from site_agent.core.memory import Memory

    mem = Memory(tmp_path / "memory.db")
    config = {
        "env": {"admin_password": "SITE_AGENT_ADMIN_PASSWORD", "github_token": "GITHUB_TOKEN"},
        "site": {"adapter": "github_static", "repository": "acme/site",
                 "clone_path": str(clone)},
        "admin": {},
    }
    env = {"SITE_AGENT_ADMIN_PASSWORD": "sekret"}
    import site_agent.web.server as server_mod
    monkeypatch.setattr(server_mod.PreviewBuildCache, "read_file", lambda *args, **kwargs: b"")
    from fastapi.testclient import TestClient

    app = server_mod.create_app({"config": config, "memory": mem, "llm": None, "scheduler": None}, env=env)
    client = TestClient(app, base_url="https://testserver")
    _login(client)
    did = mem.save_draft("Staged change", "diff", kind="merge")

    r = client.get(f"/api/review/{did}/index.html")
    assert r.status_code == 404
    assert "canonical preview build" in r.json()["detail"]
    mem.close()


def test_published_preview_never_serves_unbuilt_source_files(tmp_path, monkeypatch):
    import subprocess

    clone = tmp_path / "siterepo"
    clone.mkdir()
    run = lambda *args: subprocess.run(["git", "-C", str(clone), *args], check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (clone / "index.html").write_text("<html>published</html>")
    (clone / "unbuilt-route.html").write_text("<html>stale local page</html>")
    run("add", "-A")
    run("commit", "-qm", "local main")
    run("switch", "-q", "-c", "remote-main")
    (clone / "unbuilt-route.html").unlink()
    run("add", "-A")
    run("commit", "-qm", "published ref")
    published_sha = subprocess.check_output(
        ["git", "-C", str(clone), "rev-parse", "HEAD"], text=True
    ).strip()
    run("switch", "-q", "main")
    run("update-ref", "refs/remotes/origin/main", published_sha)

    mem = Memory(tmp_path / "memory.db")
    config = {
        "env": {"admin_password": "SITE_AGENT_ADMIN_PASSWORD", "github_token": "GITHUB_TOKEN"},
        "site": {
            "adapter": "github_static",
            "repository": "acme/site",
            "clone_path": str(clone),
        },
        "admin": {},
    }
    env = {"SITE_AGENT_ADMIN_PASSWORD": "sekret"}
    import site_agent.web.server as server_mod
    monkeypatch.setattr(server_mod.PreviewBuildCache, "read_file", lambda *args, **kwargs: b"")
    app = create_app({"config": config, "memory": mem, "llm": None, "scheduler": None}, env=env)
    with TestClient(app, base_url="https://testserver") as client:
        _login(client)
        response = client.get("/api/preview/unbuilt-route.html")
        assert response.status_code == 404
        assert "canonical site build" in response.json()["detail"]
    mem.close()


def test_published_preview_serves_only_the_canonical_build_artifact(tmp_path, monkeypatch):
    clone = _git_clone_with_pages(tmp_path, main_pages=["index.html"])
    import site_agent.web.server as server_mod
    monkeypatch.setattr(
        server_mod.PreviewBuildCache,
        "read_file",
        lambda self, _clone, _ref, name, **_kwargs: b"<html>canonical output</html>" if name == "index.html" else b"",
    )
    mem, client = _pages_app(tmp_path, clone)
    response = client.get("/api/preview/index.html")
    assert response.status_code == 200
    assert "canonical output" in response.text
    mem.close()


def test_review_endpoint_rejects_file_only_edit_drafts(tmp_path):
    """A source diff is not reviewable without the canonical built candidate."""
    import subprocess

    clone = tmp_path / "siterepo"
    clone.mkdir()
    subprocess.run(["git", "-C", str(clone), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    (clone / "index.html").write_text('<link rel="stylesheet" href="styles.css"><p>Open water / Line training</p>')
    (clone / "styles.css").write_text("body { color: red; }\n")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "main v1"], check=True)
    subprocess.run(["git", "-C", str(clone), "branch", "-M", "main"], check=True)

    from site_agent.core.memory import Memory

    mem = Memory(tmp_path / "memory.db")
    config = {
        "env": {"admin_password": "SITE_AGENT_ADMIN_PASSWORD", "github_token": "GITHUB_TOKEN"},
        "site": {"adapter": "github_static", "repository": "acme/site",
                 "clone_path": str(clone)},
        "admin": {},
    }
    env = {"SITE_AGENT_ADMIN_PASSWORD": "sekret"}
    import site_agent.web.server as server_mod
    from fastapi.testclient import TestClient

    app = server_mod.create_app({"config": config, "memory": mem, "llm": None, "scheduler": None}, env=env)
    client = TestClient(app, base_url="https://testserver")
    _login(client)
    did = mem.save_draft(
        "Cenote fix", "diff",
        kind="edit",
        meta={"ops": [
            {"op": "edit", "path": "index.html",
             "find": "Open water / Line training", "replace": "Cenotes / Line training"},
        ]},
    )

    response = client.get(f"/api/review/{did}/index.html")
    assert response.status_code == 409
    assert "verified site build" in response.json()["detail"]
    mem.close()


def test_review_endpoint_never_renders_file_only_edit_drafts(tmp_path):
    import subprocess

    clone = tmp_path / "siterepo"
    clone.mkdir()
    subprocess.run(["git", "-C", str(clone), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    (clone / "index.html").write_text("<p>Live version</p>")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "main v1"], check=True)
    subprocess.run(["git", "-C", str(clone), "branch", "-M", "main"], check=True)

    from site_agent.core.memory import Memory

    mem = Memory(tmp_path / "memory.db")
    config = {
        "env": {"admin_password": "SITE_AGENT_ADMIN_PASSWORD", "github_token": "GITHUB_TOKEN"},
        "site": {"adapter": "github_static", "repository": "acme/site",
                 "clone_path": str(clone)},
        "admin": {},
    }
    env = {"SITE_AGENT_ADMIN_PASSWORD": "sekret"}
    import site_agent.web.server as server_mod
    from fastapi.testclient import TestClient

    app = server_mod.create_app({"config": config, "memory": mem, "llm": None, "scheduler": None}, env=env)
    client = TestClient(app, base_url="https://testserver")
    _login(client)
    did = mem.save_draft(
        "Change", "diff",
        kind="edit",
        meta={"ops": [
            {"op": "edit", "path": "index.html",
             "find": "Live version", "replace": "Rejected change"},
        ]},
    )

    response = client.get(f"/api/review/{did}/index.html")
    assert response.status_code == 409
    assert "verified site build" in response.json()["detail"]
    mem.close()


def test_review_endpoint_requires_auth_and_draft(runtime):
    memory, config, _, _, client = runtime
    assert client.get("/api/review/1/index.html").status_code == 401
    _login(client)
    assert client.get("/api/review/999/index.html").status_code == 404


def test_legacy_static_preview_does_not_fall_back_to_raw_origin_files(tmp_path):
    """A managed Next/Payload preview must not serve a raw static clone as success."""
    import subprocess

    clone = tmp_path / "siterepo"
    clone.mkdir()
    subprocess.run(["git", "-C", str(clone), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    (clone / "index.html").write_text("<p>Published state</p>")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "main v1"], check=True)
    subprocess.run(["git", "-C", str(clone), "branch", "-M", "main"], check=True)

    from site_agent.core.memory import Memory

    mem = Memory(tmp_path / "memory.db")
    config = {
        "env": {"admin_password": "SITE_AGENT_ADMIN_PASSWORD", "github_token": "GITHUB_TOKEN"},
        "site": {"adapter": "github_static", "repository": "acme/site",
                 "clone_path": str(clone)},
        "admin": {},
    }
    env = {"SITE_AGENT_ADMIN_PASSWORD": "sekret"}
    import site_agent.web.server as server_mod
    from fastapi.testclient import TestClient

    app = server_mod.create_app({"config": config, "memory": mem, "llm": None, "scheduler": None}, env=env)
    client = TestClient(app, base_url="https://testserver")
    _login(client)

    r = client.get("/api/preview/index.html")
    assert r.status_code == 404
    mem.close()


def test_report_and_draft_lifecycle(runtime):
    memory, _, _, _, client = runtime
    memory.save_draft("Weekly report A", "# This week\n\nAll calm.", kind="report")
    memory.save_draft("Weekly report B — newer", "# This week\n\nWaves.", kind="report")
    _login(client)

    latest = client.get("/api/report/latest").json()["report"]
    assert latest["title"].endswith("B — newer")

    resp = client.post(f"/api/drafts/{latest['id']}/approve")
    assert resp.status_code == 200
    drafts = client.get("/api/drafts").json()["drafts"]
    assert all(d["status"] != "approved" for d in drafts)  # approved excluded from pending list

    other = [d for d in memory.list_drafts(limit=10)][-1]
    client.post(f"/api/drafts/{other['id']}/discard")
    statuses = {d["id"]: d["status"] for d in memory.list_drafts(limit=10)}
    assert statuses[other["id"]] == "discarded"


def test_approve_reflection_merges_persona(runtime):
    memory, _, _, _, client = runtime
    from site_agent.core.reflect import _digest, approved_notes

    proposal = {"voice_notes": ["Be blunter"], "avoid": ["Hype words"]}
    current = approved_notes(memory)
    package = {"kind": "ada_writing_guidance", "before": current, "after": proposal, "existingContentAffected": False}
    meta = {"proposal": proposal, "base_hash": _digest(current), "review_package_hash": _digest(package)}
    did = memory.save_draft("Self-reflection", json.dumps(proposal), kind="reflection", meta=meta)
    _login(client)
    assert client.post(f"/api/drafts/{did}/approve").status_code == 200
    assert memory.kv_get("persona_notes")["voice_notes"] == ["Be blunter"]


def test_incomplete_reflection_is_not_approvable(runtime):
    memory, _, _, _, client = runtime
    from site_agent.core.reflect import approved_notes

    proposal = {"voice_notes": ["Be blunter"], "avoid": []}
    did = memory.save_draft("Incomplete reflection", json.dumps(proposal), kind="reflection", meta=proposal)
    _login(client)
    response = client.post(f"/api/drafts/{did}/approve")
    assert response.status_code == 400
    assert approved_notes(memory)["voice_notes"] == []


def test_file_only_edit_draft_cannot_be_approved(runtime):
    memory, _, adapter, _, client = runtime
    did = memory.save_draft(
        "Legacy source edit", "", kind="edit", meta={"changes": [{"path": "src/app/page.tsx"}]}
    )
    _login(client)
    resp = client.post(f"/api/drafts/{did}/approve")
    assert resp.status_code == 409
    assert "verified site build" in resp.json()["detail"]
    assert adapter.commits == []
    draft = [d for d in memory.list_drafts(limit=10) if d["id"] == did][0]
    assert draft["status"] == "pending"


def test_retired_draft_endpoint_cannot_publish_payload_articles(runtime):
    memory, _, adapter, _, client = runtime
    did = memory.save_draft("Frenzel in four sessions", "# Frenzel\n\nBody.", kind="article")
    _login(client)
    resp = client.post(f"/api/drafts/{did}/approve")
    assert resp.status_code == 409
    assert "Payload" in resp.json()["detail"]
    assert adapter.commits == []
    assert next(item for item in memory.list_drafts(limit=10) if item["id"] == did)["status"] == "pending"


def test_article_details_expose_research_and_publish_trace(runtime):
    memory, config, adapter, _, client = runtime
    did = memory.save_draft(
        "A useful guide",
        "## A useful guide\n\nPublished content.",
        kind="article",
        meta={"angle": "Explain the practical answer.", "why": "Readers need clarity."},
    )
    idea = memory.create_article_idea(
        "article:2026-W30",
        "idea-hash",
        {
            "working_title": "A useful guide",
            "audience_need": "Readers need clarity.",
            "reader_question": "How do I make the right choice?",
            "reader_situation": "The reader is comparing options before contacting the business.",
            "reader_intent": "Choose the right next step.",
            "business_relevance": "The business can clarify the decision.",
            "market_context": "Readers compare alternatives and price before contacting the business.",
            "expert_angle": "Explain which conditions change the recommendation.",
            "expertise_basis": ["Owner-confirmed practice."],
            "technical_watchouts": ["Avoid universal claims."],
            "scope_boundaries": ["Do not diagnose without the relevant facts."],
            "thesis": "Explain the practical answer.",
            "why_now": "A recurring community question",
            "origin": "community_question",
            "candidate_queries": ["reader question basics"],
            "language": "en",
            "market": "US",
            "source_urls": ["https://example.test/question"],
        },
    )
    memory.update_article_idea(
        idea["id"],
        status="drafted",
        research_run_id="run-1",
        serp_run_id="run-serp",
        provider_task_id="task-1",
        research_result_hash="result-hash",
        research_result_json=[{"keyword": "reader question basics", "search_volume": 20, "competition": 0.2}],
        research_note_json={
            "decision": "keep",
            "selected_query": "reader question basics",
            "reasoning": "The audience need is specific.",
            "serp_evidence": {"query": "reader question basics", "checked_at": "2026-08-29 10:00:00 +00:00", "organic": [{"rank": 1, "domain": "school.example", "title": "Guide", "url": "https://school.example"}]},
            "serp_receipt": {"run_id": "run-serp", "provider_task_id": "task-serp", "cost_micros": 2000},
        },
        research_cost_micros=50000,
        draft_id=did,
        researched_ts="2026-07-01T12:00:00+00:00",
    )
    _login(client)

    details = client.get(f"/api/drafts/{did}")
    assert details.status_code == 200
    decision = details.json()["decision_details"]
    assert decision["selection"]["audience_need"] == "Readers need clarity."
    assert decision["selection"]["reader_question"] == "How do I make the right choice?"
    assert decision["selection"]["expert_angle"] == "Explain which conditions change the recommendation."
    assert decision["selection"]["selected_query"] == "reader question basics"
    assert decision["keyword_research"]["status"] == "completed"
    assert decision["keyword_research"]["result_count"] == 1
    assert decision["keyword_research"]["results"][0]["keyword"] == "reader question basics"
    assert decision["serp_research"]["status"] == "completed"
    assert decision["serp_research"]["run_id"] == "run-serp"
    assert decision["serp_research"]["organic_count"] == 1

    rejected = client.post(f"/api/drafts/{did}/approve")
    assert rejected.status_code == 409
    assert adapter.commits == []


def test_chat_rejects_legacy_file_mutation_tool(runtime):
    memory, _, _, context, client = runtime

    context["llm"] = FakeLLM([
        json.dumps({
            "reply": "",
            "action": {"type": "propose_changes", "summary": "legacy attempt",
                       "ops": [{"op": "write", "path": "src/app/page.tsx", "content": "unsafe"}]},
        }),
        json.dumps({
            "reply": "I need to prepare a proper implementation preview before changing the site.",
            "action": None,
        }),
    ])
    _login(client)
    body = chat_and_wait(client, "change the hero title")
    assert "implementation preview" in body["reply"]
    assert memory.list_drafts() == []


def test_chat_with_builder_enabled_routes_source_tweak_to_builder(runtime, monkeypatch):
    """Existing-site source changes use the reviewable builder workflow even
    when the requested visual tweak is small; they must not create a
    proposal-only draft."""
    memory, config, adapter, context, client = runtime
    config["builder"] = {"enabled": True}
    config["site"]["clone_path"] = "/tmp/nonexistent-clone"

    from site_agent.hands import opencode_runner as runner

    monkeypatch.setattr(
        runner,
        "stage_build",
        lambda ctx, brief, progress=None: {
            "reply": "Preview preparation started.",
            "merge_draft_id": 42,
            "changed": True,
            "preview": {"status": "building", "mode": "compiled_preview"},
            "change": {"status": "candidate_created", "draft_id": 42},
        },
    )
    context["llm"] = FakeLLM([
        json.dumps({
            "reply": "",
            "action": {"type": "plan_website_change", "content_effects": [],
                       "source_brief": "Add 2px to the footer margin.", "response_only": False},
        }),
        json.dumps({
            "reply": "Handing this to the implementation builder.",
            "action": {"type": "spawn_build", "brief": "Add 2px to the footer margin."},
        }),
    ])
    context["persona_prompt"] = "You are Ada."
    _login(client)
    adapter.files["styles.css"] = ".footer { padding: 4px; }"
    body = chat_and_wait(client, "add 2px to the footer margin")
    assert body["proposal_id"] is None
    assert body["merge_draft_id"] == 42
    assert body["preview"]["status"] == "building"


def test_chat_spawn_build_runs_staged_builder(runtime, monkeypatch):
    """The native tool plan starts the staged source builder and surfaces its draft."""
    memory, config, adapter, context, client = runtime
    config["builder"] = {"enabled": True}
    config["site"]["clone_path"] = "/tmp/whatever"

    from site_agent.hands import opencode_runner as runner
    monkeypatch.setattr(
        runner, "stage_build",
        lambda ctx, brief, progress=None: {
            "reply": f"Built {brief[:20]}...", "merge_draft_id": 42, "changed": True,
        },
    )
    context["llm"] = FakeLLM([
        json.dumps({
            "reply": "",
            "action": {"type": "plan_website_change", "content_effects": [],
                       "source_brief": "Build a coaching page.", "response_only": False},
        }),
        json.dumps({
            "reply": "Handing this to my builder agent.",
            "action": {"type": "spawn_build", "brief": "build a coaching page"},
        }),
    ])
    context["persona_prompt"] = "You are Ada."
    _login(client)
    body = chat_and_wait(client, "build a coaching page")
    assert body["reply"].lower().startswith("built build a coaching pag")
    assert body["merge_draft_id"] == 42


def test_chat_spawn_build_without_builder_is_graceful(runtime):
    memory, config, adapter, context, client = runtime
    context["llm"] = FakeLLM([
        json.dumps({
            "reply": "",
            "action": {"type": "spawn_build", "brief": "big redesign"},
        }),
        json.dumps({
            "reply": "The builder agent isn't enabled, and this is too broad for a safe direct edit.",
            "action": None,
        }),
    ])
    context["persona_prompt"] = "You are Ada."
    _login(client)
    body = chat_and_wait(client, "redesign everything")
    assert body["proposal_id"] is None
    assert "builder agent isn't enabled" in body["reply"]


def test_slugify():
    assert slugify("Frenzel — in Four Sessions!") == "frenzel-in-four-sessions"


def test_conversations_persist_across_chat(runtime):
    memory, _, _, context, client = runtime

    context["llm"] = FakeLLM([json.dumps({"reply": "answer 1", "action": None}),
                              json.dumps({"reply": "answer 2", "action": None}),
                              json.dumps({"reply": "answer 3", "action": None})])
    _login(client)
    r1 = chat_and_wait(client, "first question")
    r2 = chat_and_wait(client, "follow-up", r1["conversation_id"])
    assert r1["conversation_id"] == r2["conversation_id"]

    convs = memory.list_conversations()
    assert len(convs) == 1 and convs[0]["title"] == "first question"
    msgs = memory.get_messages(r1["conversation_id"])
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[2]["text"] == "follow-up"

    detail = client.get(f"/api/conversations/{r1['conversation_id']}").json()
    assert len(detail["messages"]) == 4

    # a chat without conversation_id starts a NEW conversation
    chat_and_wait(client, "fresh thread")
    assert len(memory.list_conversations()) == 2


def test_clear_conversations_hides_past_but_keeps_jobs(runtime):
    memory, _, _, _, client = runtime
    past = memory.create_conversation("past")
    active = memory.create_conversation("active")
    current = memory.create_conversation("current")
    job_id = memory.enqueue_chat_job(active, "keep this job")
    assert memory.claim_chat_job("test-worker")["id"] == job_id

    _login(client)
    response = client.post(
        "/api/conversations/clear",
        json={"keep_conversation_id": current},
    )
    assert response.status_code == 200
    assert response.json()["archived"] == 1
    assert {c["id"] for c in memory.list_conversations()} == {active, current}

    memory.interrupt_running_chat_jobs()
    response = client.post(
        "/api/conversations/clear",
        json={"keep_conversation_id": current},
    )
    assert response.json()["archived"] == 1
    assert {c["id"] for c in memory.list_conversations()} == {current}
    assert client.get(f"/api/conversations/{active}").status_code == 200
    assert {c["id"] for c in memory.list_conversations(include_archived=True)} == {past, active, current}


def test_chat_job_persisted_and_relistable(runtime):
    """A chat request persists as a DB job so it survives browser close and
    can be re-attached by conversation."""
    memory, _, _, context, client = runtime
    context["llm"] = FakeLLM([json.dumps({"reply": "persisted answer", "action": None})])
    context["persona_prompt"] = "You are Ada."
    _login(client)

    start = client.post("/api/chat", json={"message": "build me a page"}).json()
    job_id = start["job_id"]
    # The job id is an integer row id persisted to the DB, not an ephemeral token.
    assert isinstance(job_id, int)

    # It's queryable and eventually completes.
    import time
    status = None
    for _ in range(60):
        job = client.get(f"/api/chat/jobs/{job_id}").json()
        status = job["status"]
        if status in ("done", "error"):
            break
        time.sleep(0.1)
    assert status == "done"
    assert job["result"]["reply"] == "persisted answer"

    # Completed jobs remain in the conversation record, while the active-job
    # endpoint is intentionally empty after completion.
    conversation = client.get(f"/api/conversations/{start['conversation_id']}").json()
    assert any(j["id"] == job_id for j in conversation["jobs"])
    assert client.get(f"/api/chat/jobs?conversation_id={start['conversation_id']}").json()["jobs"] == []


def test_chat_job_enqueue_persists_message_and_explicit_retry(runtime):
    """A queued request is visible immediately, and interrupted work requires
    an explicit retry rather than being replayed by a worker."""
    memory, _, _, _, _ = runtime
    conv = memory.create_conversation("task")
    job_id = memory.enqueue_chat_job(conv, "big redesign")

    assert memory.get_messages(conv)[0]["text"] == "big redesign"
    claimed = memory.claim_chat_job("worker")
    assert claimed is not None and claimed["id"] == job_id

    assert memory.interrupt_running_chat_jobs() == 1
    interrupted = memory.get_chat_job(job_id)
    assert interrupted["status"] == "error"
    assert "retry" in interrupted["error"]
    assert memory.claim_chat_job("worker") is None

    assert memory.retry_chat_job(job_id)
    re_claimed = memory.claim_chat_job("worker")
    assert re_claimed is not None and re_claimed["id"] == job_id
    assert re_claimed["status"] == "running"


def test_incomplete_done_chat_job_can_be_retried(runtime):
    memory, _, _, _, _ = runtime
    conv = memory.create_conversation("task")
    job_id = memory.enqueue_chat_job(conv, "content build")
    claimed = memory.claim_chat_job("worker")
    assert claimed is not None
    assert memory.complete_chat_job(
        job_id, "worker", {"changed": False, "merge_draft_id": None, "reply": "no changes"}
    )

    assert memory.retry_chat_job(job_id)
    re_claimed = memory.claim_chat_job("worker")
    assert re_claimed is not None and re_claimed["id"] == job_id


def test_chat_job_completion_preserves_every_payload_write_receipt(runtime):
    memory, _, _, _, _ = runtime
    conversation_id = memory.create_conversation("task")
    job_id = memory.enqueue_chat_job(conversation_id, "update content and design")
    assert memory.claim_chat_job("worker") is not None
    first = {"target": "pages", "document_id": "1", "revision": "sha256:" + "a" * 64, "fields": ["sections"]}
    second = {"target": "siteSettings", "document_id": "siteSettings", "revision": "sha256:" + "b" * 64, "fields": ["footerTitle"]}
    assert memory.record_chat_job_effect(job_id, "worker", first)
    assert memory.record_chat_job_effect(job_id, "worker", second)
    assert memory.complete_chat_job(job_id, "worker", {
        "changed": True,
        "reply": "Done",
        "payload_effects": [first],
    })

    result = memory.get_chat_job(job_id)["result"]
    assert result["payload_effects"] == [first, second]


def test_chat_job_claim_is_single_owner(tmp_path):
    """Separate SQLite connections cannot claim the same queued job."""
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "memory.db"
    first = Memory(path)
    second = Memory(path)
    conv = first.create_conversation("task")
    job_id = first.enqueue_chat_job(conv, "one build")
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda args: args[0].claim_chat_job(args[1]),
                               [(first, "first"), (second, "second")]))
    assert sum(claim is not None for claim in claims) == 1
    assert any(claim and claim["id"] == job_id for claim in claims)
    first.close()
    second.close()


def test_chat_job_retry_endpoint_requires_failed_job(runtime):
    memory, _, _, _, client = runtime
    conv = memory.create_conversation("task")
    job_id = memory.enqueue_chat_job(conv, "retry this")
    assert memory.claim_chat_job("worker") is not None
    memory.interrupt_running_chat_jobs()

    _login(client)
    response = client.post(f"/api/chat/jobs/{job_id}/retry")
    assert response.status_code == 200
    assert memory.get_chat_job(job_id)["status"] == "queued"
    assert client.post(f"/api/chat/jobs/{job_id}/retry").status_code == 409


def test_publishes_are_listed_as_versions_and_restorable(runtime):
    memory, config, adapter, _, client = runtime
    did = memory.save_draft("Website update", "", kind="merge", meta={"summary": "Website update"})
    memory.log_publish("Website update", "frontend", "a" * 40, draft_id=did, version_type="merge")
    _login(client)

    pubs = client.get("/api/publishes").json()["publishes"]
    assert len(pubs) == 1
    assert pubs[0]["path"] == "frontend"

    config["site"]["preview_branch"] = "preview"
    restore = client.post(f"/api/versions/{pubs[0]['id']}/restore")
    assert restore.status_code == 200
    assert memory.list_drafts(status="pending")[0]["kind"] == "rollback"


def test_retired_article_file_publisher_fails_closed(runtime):
    memory, _config, adapter, _, client = runtime
    _login(client)

    did = memory.save_draft("My First Article", "# Hi\n\nBody.", kind="article")
    resp = client.post(f"/api/drafts/{did}/approve")
    assert resp.status_code == 409
    assert "Payload" in resp.json()["detail"]
    assert adapter.commits == []


def test_retired_article_file_unpublisher_fails_closed(runtime):
    memory, _config, adapter, _, client = runtime
    _login(client)

    did = memory.save_draft("Unsafe advice", "# Unsafe\n\nExhale underwater.", kind="article")
    resp = client.post(f"/api/drafts/{did}/decline", json={"feedback": "Never advise exhaling underwater; it is dangerous."})
    assert resp.status_code == 409
    assert "Payload" in resp.json()["detail"]
    assert adapter.commits == []


def test_decline_without_feedback_still_records_decision(runtime):
    memory, config, adapter, _, client = runtime
    _login(client)
    did = memory.save_draft("Plain draft", "body", kind="edit")
    resp = client.post(f"/api/drafts/{did}/decline", json={})
    assert resp.status_code == 200
    drafts = {d["id"]: d for d in memory.list_drafts(limit=10)}
    assert drafts[did]["status"] == "declined"
    assert memory.recent_observations(source="feedback") == []


def test_decline_stores_feedback_on_draft(runtime):
    memory, config, adapter, _, client = runtime
    _login(client)
    did = memory.save_draft(
        "Proposed changes: Add a breath ring element",
        json.dumps([{"op": "edit", "path": "index.html", "find": "a", "replace": "b"}]),
        kind="edit",
        meta={"ops": [{"op": "edit", "path": "index.html", "find": "a", "replace": "b"}]},
    )
    resp = client.post(f"/api/drafts/{did}/decline", json={"feedback": "looks amateurish"})
    assert resp.status_code == 200
    draft = memory.list_drafts(limit=10)[0]
    assert draft["status"] == "declined"
    assert draft["meta"].get("feedback") == "looks amateurish"
    # decision ledger renders the reason without any free-text parsing
    from site_agent.brain.editor import _decision_ledger_block
    block = _decision_ledger_block({"config": config, "memory": memory})
    assert "looks amateurish" in block and f"#{did} DECLINED" in block


def test_decline_without_feedback_still_ends_declined(runtime):
    memory, config, adapter, _, client = runtime
    _login(client)
    did = memory.save_draft("Plain draft", "body", kind="edit")
    resp = client.post(f"/api/drafts/{did}/decline", json={})
    assert resp.status_code == 200
    draft = memory.list_drafts(limit=10)[0]
    assert draft["status"] == "declined"
    assert not draft["meta"].get("feedback")


def test_file_only_edit_draft_cannot_be_approved(runtime):
    memory, config, adapter, _, client = runtime
    did = memory.save_draft("Legacy file edit", "", kind="edit",
                            meta={"ops": [{"op": "edit", "path": "styles.css"}]})
    _login(client)
    resp = client.post(f"/api/drafts/{did}/approve")
    assert resp.status_code == 409
    assert "verified site build" in resp.json()["detail"]
    assert adapter.commits == []


def test_file_only_edit_draft_cannot_be_previewed(runtime):
    memory, _config, adapter, _, client = runtime
    did = memory.save_draft("Legacy file edit", "", kind="edit",
                            meta={"ops": [{"op": "edit", "path": "styles.css"}]})
    _login(client)
    resp = client.post(f"/api/drafts/{did}/preview")
    assert resp.status_code == 409
    assert "verified site build" in resp.json()["detail"]
    assert adapter.commits == []


def test_preview_requires_branch_config(runtime):
    _, config, _, _, client = runtime
    config["site"].pop("preview_branch", None)
    memory = runtime[0]
    did = memory.save_draft("e", "{}", kind="edit", meta={"changes": []})
    _login(client)
    resp = client.post(f"/api/drafts/{did}/preview")
    assert resp.status_code == 409 and "verified site build" in resp.json()["detail"]


def test_decline_merge_drops_tweakmap_overlay(runtime):
    """Rejecting a build clears its tweak-map overlay so stale knobs aren't
    offered to the owner."""
    from site_agent.hands import tweakmap

    memory, config, adapter, _, client = runtime
    config["site"]["preview_branch"] = "preview"
    resets = []
    adapter.reset_preview_branch = lambda name: resets.append(name) or {"reset": True, "branch": name}
    memory.kv_set(tweakmap.BUILDER_KEY, {"head": "abc", "files": {"styles.css": []}})
    did = memory.save_draft("Staged redesign", "diff", kind="merge",
                            meta={"head": "preview", "base": "main"})
    _login(client)
    resp = client.post(f"/api/drafts/{did}/decline", json={"feedback": "too much"})
    assert resp.status_code == 200
    assert memory.kv_get(tweakmap.BUILDER_KEY) is None


def test_decline_merge_resets_preview_branch(runtime):
    """Rejecting a merge draft rolls the preview branch back to main."""
    memory, config, adapter, _, client = runtime
    config["site"]["preview_branch"] = "preview"
    resets = []
    adapter.reset_preview_branch = lambda name: resets.append(name) or {"reset": True, "branch": name}
    did = memory.save_draft("Staged redesign", "diff", kind="merge",
                            meta={"head": "preview", "base": "main"})
    _login(client)
    resp = client.post(f"/api/drafts/{did}/decline", json={"feedback": "too much"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reset"] == {"reset": True, "branch": "preview"}
    assert resets == ["preview"]
    assert memory.list_drafts(status="declined")[0]["id"] == did


def test_decline_merge_skips_reset_when_no_branch_config(runtime):
    """No preview_branch configured -> no reset attempted, decline still works."""
    memory, config, adapter, _, client = runtime
    config["site"].pop("preview_branch", None)
    called = []
    adapter.reset_preview_branch = lambda name: called.append(name)
    did = memory.save_draft("Staged redesign", "diff", kind="merge")
    _login(client)
    resp = client.post(f"/api/drafts/{did}/decline", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reset"] is None
    assert called == []
    assert memory.list_drafts(status="declined")[0]["id"] == did


def test_decline_edit_draft_does_not_reset(runtime):
    """Only merge drafts trigger a preview reset on decline."""
    memory, config, adapter, _, client = runtime
    config["site"]["preview_branch"] = "preview"
    called = []
    adapter.reset_preview_branch = lambda name: called.append(name)
    did = memory.save_draft("Proposed edit", "diff", kind="edit",
                            meta={"ops": [{"op": "edit", "path": "index.html", "find": "a", "replace": "b"}]})
    _login(client)
    resp = client.post(f"/api/drafts/{did}/decline", json={})
    assert resp.status_code == 200
    assert called == []
    assert memory.list_drafts(status="declined")[0]["id"] == did


def test_history_endpoint_lists_lifecycle(runtime):
    memory, config, _, _, client = runtime
    _login(client)
    e = memory.save_draft("Proposed edit: hero", "diff", kind="edit")
    m = memory.save_draft("Staged redesign", "diff", kind="merge",
                          meta={"head": "preview", "base": "main"})
    memory.update_draft_status(m, "declined")
    memory.log_publish("edit: hero", "index.html", "deadbeef", draft_id=e)
    memory.update_draft_status(e, "approved")
    memory.mark_publish_reverted(commit_sha="deadbeef")

    resp = client.get("/api/history")
    assert resp.status_code == 200
    by_id = {d["id"]: d for d in resp.json()["history"]}
    assert by_id[m]["status"] == "declined"
    assert by_id[e]["status"] == "approved"
    assert by_id[e]["commit_sha"] == "deadbeef"
    assert by_id[e]["reverted_ts"] is not None
    assert by_id[e]["kind"] == "edit"


def test_approve_rejects_legacy_file_edit_draft(runtime):
    memory, _config, adapter, _, client = runtime
    _login(client)
    old = memory.save_draft("Old source proposal", "diff", kind="edit", meta={"ops": []})
    response = client.post(f"/api/drafts/{old}/approve")
    assert response.status_code == 409
    assert adapter.commits == []
    assert next(row for row in memory.list_drafts() if row["id"] == old)["status"] == "pending"


def test_approve_merge_supersedes_all_pending_edits(runtime):
    """A merge replaces the whole preview branch -> every pending edit is stale."""
    memory, config, adapter, _, client = runtime
    _login(client)
    edit1 = memory.save_draft("edit about", "diff", kind="edit",
                              meta={"ops": [{"op": "edit", "path": "about.html", "find": "a", "replace": "b"}]})
    edit2 = memory.save_draft("edit contact", "diff", kind="edit",
                              meta={"ops": [{"op": "edit", "path": "contact.html", "find": "a", "replace": "b"}]})
    merge = memory.save_draft("Full redesign", "diff", kind="merge",
                              meta={"head": "preview", "base": "main"})
    adapter.merge_preview = lambda cfg, msg: {"merged": True, "commit_sha": "feedbeef", "path": "preview->main"}
    resp = client.post(f"/api/drafts/{merge}/approve")
    assert resp.status_code == 200
    assert set(resp.json()["superseded"]) == {edit1, edit2}
    statuses = {d["id"]: d["status"] for d in memory.list_drafts(limit=10)}
    assert statuses[edit1] == "discarded" and statuses[edit2] == "discarded"


def _git_clone_with_pages(tmp_path, main_pages, preview_pages=None):
    """Build a local git repo with origin/main (and optionally a preview branch)
    containing the given HTML pages, returned with its path."""
    import subprocess

    clone = tmp_path / "pagesrepo"
    clone.mkdir()
    subprocess.run(["git", "-C", str(clone), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    for name in main_pages:
        (clone / name).write_text(f"<html>main {name}</html>")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "main v1"], check=True)
    subprocess.run(["git", "-C", str(clone), "branch", "-M", "main"], check=True)
    subprocess.run(["git", "-C", str(clone), "branch", "preview"], check=True)
    if preview_pages:
        subprocess.run(["git", "-C", str(clone), "checkout", "-q", "preview"], check=True)
        for name in preview_pages:
            (clone / name).write_text(f"<html>preview {name}</html>")
        subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(clone), "commit", "-qm", "preview work"], check=True)
        subprocess.run(["git", "-C", str(clone), "checkout", "-q", "main"], check=True)
    return clone


def _pages_app(tmp_path, clone):
    from site_agent.core.memory import Memory
    from fastapi.testclient import TestClient
    import site_agent.web.server as server_mod

    mem = Memory(tmp_path / "pages.db")
    config = {
        "env": {"admin_password": "SITE_AGENT_ADMIN_PASSWORD", "github_token": "GITHUB_TOKEN"},
        "site": {"adapter": "github_static", "repository": "acme/site",
                 "clone_path": str(clone)},
        "admin": {},
    }
    env = {"SITE_AGENT_ADMIN_PASSWORD": "sekret"}
    app = server_mod.create_app({"config": config, "memory": mem, "llm": None, "scheduler": None}, env=env)
    client = TestClient(app, base_url="https://testserver")
    _login(client)
    return mem, client


def test_pages_endpoint_lists_published_pages(tmp_path):
    clone = _git_clone_with_pages(tmp_path, main_pages=["index.html", "coaching.html"])
    mem, client = _pages_app(tmp_path, clone)
    r = client.get("/api/pages")
    assert r.status_code == 200
    body = r.json()
    assert set(body["pages"]) == {"coaching.html", "index.html"}
    assert body["pages"][0] == "index.html"  # homepage first = default selection
    assert body["new_pages"] == []
    mem.close()


def test_pages_endpoint_merge_draft_shows_preview_pages(tmp_path):
    clone = _git_clone_with_pages(tmp_path, main_pages=["index.html"],
                                  preview_pages=["index.html", "newpage.html"])
    mem, client = _pages_app(tmp_path, clone)
    did = mem.save_draft("Staged redesign", "diff", kind="merge",
                         meta={"head": "preview", "base": "main"})
    r = client.get(f"/api/pages?draft_id={did}")
    assert r.status_code == 200
    body = r.json()
    assert "newpage.html" in body["pages"]
    assert "newpage.html" in body["new_pages"]
    mem.close()


def test_pages_endpoint_rejects_unbuilt_edit_draft(tmp_path):
    clone = _git_clone_with_pages(tmp_path, main_pages=["index.html"])
    mem, client = _pages_app(tmp_path, clone)
    did = mem.save_draft(
        "New coaching page", "diff", kind="edit",
        meta={"ops": [{"op": "write", "path": "coaching.html", "content": "<html>coaching</html>"}]},
    )
    r = client.get(f"/api/pages?draft_id={did}")
    assert r.status_code == 409
    assert "verified site build" in r.json()["detail"]
    mem.close()
