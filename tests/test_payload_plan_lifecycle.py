import copy
import json

import pytest

from site_agent.brain.editor import handle_message
from site_agent.core.memory import Memory
from site_agent.hands.base import SiteAdapter


def _contract():
    return {
        "locales": ["en"],
        "defaultLocale": "en",
        "enabled": {"collections": ["posts"], "globals": ["siteSettings"]},
        "authoring": {
            "collections": {
                "posts": [
                    {"name": "slug", "type": "text", "required": True},
                    {"name": "title", "type": "text", "required": True},
                    {"name": "summary", "type": "text"},
                ]
            },
            "globals": {"siteSettings": [{"name": "siteName", "type": "text"}]},
        },
    }


def _plan(slug, fields=("slug", "title"), *, source_brief=""):
    effects = []
    if fields:
        effects.append({
            "kind": "collection",
            "operation": "create",
            "collection": "posts",
            "identifier": slug,
            "identifier_kind": "slug",
            "fields": list(fields),
            "summary": f"Prepare {slug}",
        })
    return {
        "content_effects": effects,
        "source_brief": source_brief,
        "response_only": False,
    }


def _tool(name, **arguments):
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class _LLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.conversations = []

    def chat_tools(self, conversation, _tools, **_kwargs):
        self.conversations.append(copy.deepcopy(conversation))
        if not self.responses:
            raise AssertionError("unexpected extra model turn")
        return self.responses.pop(0)


class _Payload:
    def __init__(self, *, fail_create=False):
        self.fail_create = fail_create
        self.creates = []
        self.writes = []

    def require_authoring_contract(self):
        return _contract()

    def create(self, collection, data, *, locale):
        self.creates.append((collection, dict(data), locale))
        if self.fail_create:
            raise TimeoutError("write outcome is unknown")
        return {
            "id": "post-1",
            "slug": data["slug"],
            "title": data["title"],
            "_status": "draft",
            "_helloadaRevision": "sha256:" + "a" * 64,
        }

    def read(self, collection, **_kwargs):
        return {
            "id": "post-1", "slug": "article", "title": "Old title",
            "_helloadaRevision": "sha256:" + "b" * 64,
        }

    def update(self, collection, document_id, data, *, expected_hash, locale):
        self.writes.append(("update", collection, document_id, data, expected_hash, locale))
        return {
            "id": document_id, "slug": "article", **data,
            "_helloadaRevision": "sha256:" + "c" * 64,
        }

    def read_global(self, _global, **_kwargs):
        return {"siteName": "Old name", "_helloadaRevision": "sha256:" + "b" * 64}

    def update_global(self, global_name, data, *, expected_hash, locale):
        self.writes.append(("update_global", global_name, data, expected_hash, locale))
        return {"id": global_name, **data, "_helloadaRevision": "sha256:" + "c" * 64}


class _Adapter(SiteAdapter):
    name = "test"

    def get_file(self, path, branch=None):
        return None, None

    def commit_file(self, path, data, message, branch=None):
        raise AssertionError("these tests must not mutate a repository")


def _context(tmp_path, llm, payload, *, max_work_steps=8):
    memory = Memory(tmp_path / "memory.db")
    context = {
        "memory": memory,
        "llm": llm,
        "payload_gateway": payload,
        "config": {
            "persona": {"name": "Ada"},
            "llm": {"tool_calling": True, "max_work_steps": max_work_steps},
            "site": {"adapter": "github_static", "repository": "acme/site"},
        },
    }
    return context, memory


def _permit_prompt_contract(monkeypatch):
    from site_agent.hands import repo_changes

    monkeypatch.setattr(repo_changes, "source_authoring_contract", lambda _config: {})


def _final(text="Done."):
    return {"content": text, "tool_calls": None}


def test_handler_accepts_plan_replacement_before_any_dispatch(tmp_path, monkeypatch):
    _permit_prompt_contract(monkeypatch)
    first = _plan("first-article")
    replacement = _plan("second-article")
    llm = _LLM([
        {"content": None, "tool_calls": [_tool("plan_website_change", **first)]},
        {"content": None, "tool_calls": [_tool("plan_website_change", **replacement)]},
        {"content": None, "tool_calls": [_tool(
            "create_payload_draft", collection="posts",
            data={"slug": "second-article", "title": "Second title"},
        )]},
        _final(),
    ])
    payload = _Payload()
    context, memory = _context(tmp_path, llm, payload)
    try:
        handle_message(context, _Adapter(), "Prepare an article")
        assert payload.creates == [(
            "posts", {"slug": "second-article", "title": "Second title"}, "en",
        )]
        assert context["_website_change_plan"]["content_effects"][0]["identifier"] == "second-article"
        assert context["_website_change_plan_dispatched"] is True
    finally:
        memory.close()


def test_handler_rejected_malformed_plan_does_not_freeze_and_can_be_corrected(tmp_path, monkeypatch):
    _permit_prompt_contract(monkeypatch)
    malformed = _plan("article", ("slug",))
    corrected = _plan("article", ("slug", "title"))
    llm = _LLM([
        {"content": None, "tool_calls": [_tool("plan_website_change", **malformed)]},
        {"content": None, "tool_calls": [_tool("plan_website_change", **corrected)]},
        {"content": None, "tool_calls": [_tool(
            "create_payload_draft", collection="posts",
            data={"slug": "article", "title": "A title"},
        )]},
        _final(),
    ])
    payload = _Payload()
    context, memory = _context(tmp_path, llm, payload)
    try:
        handle_message(context, _Adapter(), "Prepare an article")
        assert payload.creates == [(
            "posts", {"slug": "article", "title": "A title"}, "en",
        )]
        assert "website change plan is invalid" in llm.conversations[1][-1]["content"]
        assert context["_website_change_plan"]["content_effects"][0]["fields"] == ["slug", "title"]
    finally:
        memory.close()


def test_handler_rejected_payload_args_do_not_freeze_plan_and_allow_correction(tmp_path, monkeypatch):
    _permit_prompt_contract(monkeypatch)
    original = _plan("article", ("slug", "title"))
    replacement = _plan("article", ("slug", "title", "summary"))
    llm = _LLM([
        {"content": None, "tool_calls": [_tool("plan_website_change", **original)]},
        {"content": None, "tool_calls": [_tool(
            "create_payload_draft", collection="posts", data={"slug": "article"},
        )]},
        {"content": None, "tool_calls": [_tool("plan_website_change", **replacement)]},
        {"content": None, "tool_calls": [_tool(
            "create_payload_draft", collection="posts",
            data={"slug": "article", "title": "A title", "summary": "A summary"},
        )]},
        _final(),
    ])
    payload = _Payload()
    context, memory = _context(tmp_path, llm, payload)
    try:
        handle_message(context, _Adapter(), "Prepare an article")
        assert payload.creates == [(
            "posts", {"slug": "article", "title": "A title", "summary": "A summary"}, "en",
        )]
        assert context["_website_change_plan"]["content_effects"][0]["fields"] == [
            "slug", "summary", "title",
        ]
        assert context["_website_change_plan_dispatched"] is True
    finally:
        memory.close()


def test_handler_freezes_plan_after_successful_payload_write(tmp_path, monkeypatch):
    _permit_prompt_contract(monkeypatch)
    original = _plan("article")
    replacement = _plan("replacement")
    llm = _LLM([
        {"content": None, "tool_calls": [_tool("plan_website_change", **original)]},
        {"content": None, "tool_calls": [_tool(
            "create_payload_draft", collection="posts",
            data={"slug": "article", "title": "A title"},
        )]},
        {"content": None, "tool_calls": [_tool("plan_website_change", **replacement)]},
        _final(),
    ])
    payload = _Payload()
    context, memory = _context(tmp_path, llm, payload)
    try:
        handle_message(context, _Adapter(), "Prepare an article")
        assert context["_website_change_plan"]["content_effects"][0]["identifier"] == "article"
        assert context["_website_change_plan_dispatched"] is True
        assert "plan is frozen" in llm.conversations[3][-1]["content"]
    finally:
        memory.close()


@pytest.mark.parametrize("target_kind", ["collection", "global"])
def test_handler_freezes_plan_after_successful_payload_update(tmp_path, monkeypatch, target_kind):
    _permit_prompt_contract(monkeypatch)
    if target_kind == "collection":
        effect = {
            "kind": "collection", "operation": "update", "collection": "posts",
            "identifier": "post-1", "identifier_kind": "id", "fields": ["title"],
            "summary": "Update the article title",
        }
        mutation_calls = [
            _tool("read_payload_content", collection="posts", identifier="post-1", identifier_kind="id"),
            _tool("update_payload_draft", collection="posts", id="post-1",
                  expected_hash="sha256:" + "b" * 64, data={"title": "New title"}),
        ]
    else:
        effect = {
            "kind": "global", "operation": "update", "global": "siteSettings",
            "identifier": "siteSettings", "identifier_kind": "global", "fields": ["siteName"],
            "summary": "Update the site name",
        }
        mutation_calls = [
            _tool("read_payload_global", **{"global": "siteSettings"}),
            _tool("update_payload_global", **{
                "global": "siteSettings", "expected_hash": "sha256:" + "b" * 64,
                "data": {"siteName": "New name"},
            }),
        ]
    original = {"content_effects": [effect], "source_brief": "", "response_only": False}
    replacement = _plan("replacement")
    llm = _LLM([
        {"content": None, "tool_calls": [_tool("plan_website_change", **original)]},
        {"content": None, "tool_calls": [mutation_calls[0]]},
        {"content": None, "tool_calls": [mutation_calls[1]]},
        {"content": None, "tool_calls": [_tool("plan_website_change", **replacement)]},
        _final(),
    ])
    payload = _Payload()
    context, memory = _context(tmp_path, llm, payload)
    try:
        handle_message(context, _Adapter(), "Update the selected content")
        assert context["_website_change_plan_dispatched"] is True
        assert context["_website_change_plan"]["content_effects"][0]["kind"] == target_kind
        assert "plan is frozen" in llm.conversations[4][-1]["content"]
        assert len(payload.writes) == 1
    finally:
        memory.close()


def test_handler_write_exception_freezes_plan_and_prevents_payload_replay(tmp_path, monkeypatch, caplog):
    _permit_prompt_contract(monkeypatch)
    original = _plan("article")
    replacement = _plan("replacement")
    llm = _LLM([
        {"content": None, "tool_calls": [_tool("plan_website_change", **original)]},
        {"content": None, "tool_calls": [_tool(
            "create_payload_draft", collection="posts",
            data={"slug": "article", "title": "A title"},
        )]},
        {"content": None, "tool_calls": [_tool("plan_website_change", **replacement)]},
        {"content": None, "tool_calls": [_tool(
            "create_payload_draft", collection="posts",
            data={"slug": "article", "title": "A title"},
        )]},
    ])
    payload = _Payload(fail_create=True)
    context, memory = _context(tmp_path, llm, payload, max_work_steps=4)
    try:
        with pytest.raises(RuntimeError, match="configured tool-step limit"):
            handle_message(context, _Adapter(), "Prepare an article")
        assert len(payload.creates) == 1
        assert context["_website_change_plan"]["content_effects"][0]["identifier"] == "article"
        assert context["_website_change_plan_dispatched"] is True
        assert context["_website_change_plan"]["content_effects"][0]["_dispatched"] is True
        assert "already dispatched" in caplog.text
    finally:
        memory.close()


def test_handler_resets_dispatch_evidence_for_a_new_request(tmp_path, monkeypatch):
    _permit_prompt_contract(monkeypatch)
    first_llm = _LLM([
        {"content": None, "tool_calls": [_tool("plan_website_change", **_plan("first"))]},
        {"content": None, "tool_calls": [_tool(
            "create_payload_draft", collection="posts",
            data={"slug": "first", "title": "First title"},
        )]},
        _final(),
    ])
    payload = _Payload()
    context, memory = _context(tmp_path, first_llm, payload)
    try:
        handle_message(context, _Adapter(), "Prepare the first article")
        assert context["_website_change_plan_dispatched"] is True

        second_llm = _LLM([
            {"content": None, "tool_calls": [_tool("plan_website_change", **_plan("second"))]},
            {"content": None, "tool_calls": [_tool(
                "create_payload_draft", collection="posts",
                data={"slug": "second", "title": "Second title"},
            )]},
            _final(),
        ])
        context["llm"] = second_llm
        handle_message(context, _Adapter(), "Prepare the second article")
        assert [call[1]["slug"] for call in payload.creates] == ["first", "second"]
        assert context["_website_change_plan"]["content_effects"][0]["identifier"] == "second"
        assert context["_website_change_plan_dispatched"] is True
    finally:
        memory.close()


def test_handler_marks_source_build_at_dispatch_even_when_it_raises(tmp_path, monkeypatch):
    _permit_prompt_contract(monkeypatch)
    from site_agent.hands import opencode_runner

    monkeypatch.setattr(opencode_runner, "builder_available", lambda _config: True)

    def stage_build(context, _brief, _progress):
        assert context.get("_website_change_plan_dispatched") is True
        assert context.get("_website_change_source_build_dispatched") is True
        raise TimeoutError("build outcome is unknown")

    monkeypatch.setattr(opencode_runner, "stage_build", stage_build)
    plan = _plan(
        "unused", (),
        source_brief="Update the presentation",
    )
    plan["source_paths"] = ["src/page.tsx"]
    plan["acceptance_criteria"] = ["The requested presentation change is visible"]
    llm = _LLM([
        {"content": None, "tool_calls": [_tool("plan_website_change", **plan)]},
        {"content": None, "tool_calls": [_tool("spawn_build", brief="Update the presentation")]},
    ])
    context, memory = _context(tmp_path, llm, _Payload())
    try:
        with pytest.raises(RuntimeError, match="Builder failed: build outcome is unknown"):
            handle_message(context, _Adapter(), "Update the presentation")
        assert context["_website_change_plan_dispatched"] is True
        assert context["_website_change_source_build_dispatched"] is True
        assert "per-request dispatch evidence" in llm.conversations[0][0]["content"]
        assert "outcome is uncertain" in llm.conversations[0][0]["content"]
    finally:
        memory.close()
