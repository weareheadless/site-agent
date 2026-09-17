import json

import pytest

from site_agent.brain.editor import _max_work_steps, handle_message
from site_agent.core.memory import Memory


class FakeToolsLLM:
    """Scripted chat_tools responses; records prompts."""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = []

    def chat_tools(self, messages, tools, temperature=None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        r = self.rounds.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def chat(self, *a, **k):  # pragma: no cover — must not be used in tools mode
        raise AssertionError("JSON fallback used while tool_calling enabled")


def test_max_work_steps_has_safe_default_and_cap():
    assert _max_work_steps({}) == 8
    assert _max_work_steps({"config": {"llm": {"max_work_steps": 16}}}) == 16
    assert _max_work_steps({"config": {"llm": {"max_work_steps": 999}}}) == 24
    assert _max_work_steps({"config": {"llm": {"max_work_steps": "bad"}}}) == 8


def _tc(name, **args):
    return [{"id": "call_1", "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}}]


@pytest.fixture
def env(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    config = {
        "env": {},
        "persona": {"name": "Ada"},
        "llm": {"base_url": "https://api.test/v1", "model": "m", "tool_calling": True},
        "site": {
            "adapter": "github_static",
            "repository": "acme/site",
            "content_path": "content.json",
            "writable_patterns": ["*.html", "*.css", "*.md", "articles/*"],
        },
    }
    context = {"config": config, "memory": memory}
    yield memory, config, context
    memory.close()


def test_tool_loop_reads_then_proposes(env):
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        def __init__(self):
            self.site = {"content_path": "content.json"}
            self.files = {"styles.css": ".footer { padding: 4px; }"}
            self.commits = []
        def get_content(self): return {}
        def get_file(self, path, branch=None):
            raw = self.files.get(path)
            return ("sha", raw.encode()) if raw is not None else (None, None)
        def commit_file(self, path, data, message, branch=None):
            self.commits.append(path)
            return {"committed": True, "path": path}

    adapter = Adapter()
    llm = FakeToolsLLM([
        {"content": "Checking the footer styles.", "tool_calls": _tc("read_file", path="styles.css")},
        {"content": None, "tool_calls": _tc(
            "propose_changes", summary="footer spacing",
            ops=[{"op": "edit", "path": "styles.css",
                  "find": ".footer { padding: 4px; }", "replace": ".footer { padding: 28px 0; }"}])},
    ])
    steps = []
    r = handle_message({"config": env[1], "memory": env[0], "llm": llm}, adapter,
                       "add space under the Oceanic Vibes logo in the footer",
                       progress=steps.append)

    assert r["reply"].startswith("Proposal #")
    assert r["proposal_id"] > 0
    drafts = env[0].list_drafts()
    assert drafts[0]["meta"]["ops"][0]["replace"].startswith(".footer { padding: 28px")
    assert any("reading styles.css" in s for s in steps)
    # A successful mutation is terminal; there is no post-side-effect model
    # round that can repeat it or turn a completed job into an error.
    assert len(llm.calls) == 2


def test_tool_loop_reports_refusals_to_model(env):
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def get_content(self): return {}
        def get_file(self, path, branch=None): return (None, None)
        def commit_file(self, path, data, message, branch=None): return {}

    adapter = Adapter()
    llm = FakeToolsLLM([
        {"content": None, "tool_calls": _tc(
            "propose_changes", summary="hack",
            ops=[{"op": "write", "path": ".github/evil.yml", "content": "x"}])},
        {"content": "Understood — that file is off-limits. Nothing staged.", "tool_calls": None},
    ])
    r = handle_message({"config": env[1], "memory": env[0], "llm": llm}, adapter, "do it")
    assert r["proposal_id"] is None
    assert "off-limits" in r["reply"]
    sent_back = llm.calls[1]["messages"][-1]
    assert sent_back["role"] == "tool" and sent_back["content"].startswith("REFUSED")


def test_tools_spec_respects_writable_patterns(env):
    from site_agent.brain.editor import _tools_spec
    spec = json.dumps(_tools_spec(env[1]))
    assert "propose_changes" in spec


def test_atelier_payload_tools_read_then_update_draft(env):
    from site_agent.brain.editor import _tools_spec
    from site_agent.hands.base import SiteAdapter

    class Payload:
        def __init__(self):
            self.updates = []

        def read(self, collection, **kwargs):
            assert collection == "pages"
            assert kwargs["identifier"] == "home"
            return {"id": "7", "sourceId": "home", "title": "Old heading", "content": {"heading": "Old heading"}}

        def update(self, collection, document_id, data):
            self.updates.append((collection, document_id, data))
            return {"id": document_id, "sourceId": "home", "title": data["title"], "_status": "draft"}

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}

        def get_content(self):
            return {}

        def get_file(self, path, branch=None):
            return (None, None)

        def commit_file(self, path, data, message, branch=None):
            return {}

    payload = Payload()
    context = {**env[2], "llm": FakeToolsLLM([
        {"content": None, "tool_calls": _tc(
            "read_payload_content", collection="pages", identifier="home", identifier_kind="sourceId")},
        {"content": None, "tool_calls": _tc(
            "update_payload_draft", collection="pages", id="7", data={"title": "New heading"})},
    ]), "atelier_payload": payload}
    result = handle_message(context, Adapter(), "Change the heading on the homepage")

    assert result["reply"].startswith("Payload draft updated:")
    assert payload.updates == [("pages", "7", {"title": "New heading"})]
    assert "read_payload_content" in json.dumps(_tools_spec(context))


def test_reads_pending_build_from_preview_branch(env):
    from site_agent.brain.editor import _cached_file
    from site_agent.hands import file_cache

    class BranchAdapter:
        def get_file(self, path, branch=None):
            text = "preview" if branch == "preview" else "main"
            return "sha", text.encode()

    adapter = BranchAdapter()
    context = env[2]
    assert _cached_file(context, adapter, "styles.css") == b"main"

    env[0].save_draft("Preview build", "", "merge", meta={"head": "preview"})
    file_cache.clear()
    assert _cached_file(context, adapter, "styles.css") == b"preview"


def test_spawn_build_tool_runs_staged_builder_and_surfaces_draft(env, monkeypatch):
    from site_agent.hands import opencode_runner as runner

    monkeypatch.setattr(runner, "builder_available", lambda cfg: True)
    monkeypatch.setattr(
        runner, "stage_build",
        lambda ctx, brief, progress=None: {
            "reply": "Built it. Review draft #7.",
            "merge_draft_id": 7, "changed": True,
        },
    )
    memory, config, context = env
    config["site"]["clone_path"] = "/tmp/x"
    config["builder"] = {"enabled": True}

    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def get_content(self): return {}
        def get_file(self, path, branch=None): return (None, None)
        def commit_file(self, path, data, message, branch=None): return {}

    llm = FakeToolsLLM([
        {"content": None, "tool_calls": _tc("spawn_build", brief="coaching page")},
    ])
    r = handle_message({"config": config, "memory": memory, "llm": llm},
                       Adapter(), "build a coaching page")
    assert r["merge_draft_id"] == 7
    assert r["proposal_id"] is None
    assert len(llm.calls) == 1


def test_builder_route_sends_creative_request_directly_to_builder(env, monkeypatch):
    from site_agent.hands import opencode_runner as runner
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def get_content(self): return {}
        def get_file(self, path, branch=None): return (None, None)
        def commit_file(self, path, data, message, branch=None): return {}

    class RoutedLLM:
        def __init__(self):
            self.calls = []
            self.last_resp = None
        def chat_tools(self, messages, tools, **kwargs):
            self.calls.append(messages)
            self.last_resp = {"content": None, "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "spawn_build",
                              "arguments": json.dumps({"brief": "make the homepage feel alive with a restrained GSAP descent"})}}
            ]}
            return self.last_resp

    memory, config, context = env
    config["builder"] = {"enabled": True}
    config["site"]["clone_path"] = "/tmp/site-clone"
    llm = RoutedLLM()
    context["llm"] = llm
    monkeypatch.setattr(runner, "stage_build", lambda ctx, brief, progress=None: {
        "reply": f"staged: {brief}", "merge_draft_id": 99, "changed": True,
    })

    result = handle_message(context, Adapter(), "make the homepage feel alive and show what the new motion tools can do")
    assert result["merge_draft_id"] == 99
    assert result["reply"].startswith("staged:")
    assert len(llm.calls) == 1
    assert "spawn_build" == llm.last_resp["tool_calls"][0]["function"]["name"]


def test_spawn_build_absent_when_builder_disabled(env):
    from site_agent.brain.editor import _tools_spec
    spec = json.dumps(_tools_spec(env[1]))
    assert "spawn_build" not in spec


def test_canonical_design_intent_uses_typed_handoff_instead_of_legacy_builder(env):
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}

        def get_content(self):
            return {}

        def get_file(self, path, branch=None):
            return (None, None)

        def commit_file(self, path, data, message, branch=None):
            return {}

    memory, config, context = env
    config["builder"] = {"enabled": True}
    config["site"]["clone_path"] = "/tmp/design-clone"
    context["design_service"] = object()
    intake = {
        "schema_version": 1,
        "business": {
            "name": "OceanicVibes",
            "offer_summary": "Freediving instruction.",
            "primary_services": ["Training"],
        },
        "audience": {"primary": "Freedivers"},
        "conversion": {"primary_action": "Start a conversation", "not_available": True},
        "brand": {"voice": "Calm and precise."},
        "site": {"required_pages": ["index.html"]},
    }
    llm = FakeToolsLLM([{
        "content": None,
        "tool_calls": _tc(
            "design_request",
            intent="redesign",
            intake=intake,
            owner_summary="I will prepare one reviewable redesign.",
        ),
    }])

    result = handle_message(
        {**context, "llm": llm},
        Adapter(),
        "redesign the homepage around depth",
        source_message_id=17,
    )

    assert result["design_request"]["intent"] == "redesign"
    assert result["design_request"]["source_message_id"] == 17
    assert "spawn_build" not in json.dumps(llm.calls[0]["tools"])


def test_store_proposal_allows_owner_to_reconsider_declined_work(env):
    from site_agent.brain.editor import store_proposal

    memory, config, context = env
    ops = [{"op": "edit", "path": "index.html",
            "find": "<div class=\"hero-image image-frame\"></div>",
            "replace": "<div class=\"breath-ring\" aria-hidden=\"true\"></div>"}]
    pid = store_proposal(memory, {"ops": ops}, "add breath-ring div")
    memory.update_draft_status(pid, "declined")

    second = store_proposal(memory, {"ops": ops}, "owner explicitly asks to retry")
    assert second != pid


def test_decision_ledger_block_lists_declined_and_approved(env):
    from site_agent.brain.editor import _decision_ledger_block, store_proposal

    memory, config, context = env
    good = store_proposal(memory, {"ops": [{"op": "edit", "path": "a.html",
                                             "find": "x", "replace": "y"}]}, "good change")
    bad = store_proposal(memory, {"ops": [{"op": "edit", "path": "b.html",
                                            "find": "p", "replace": "q"}]}, "bad change")
    memory.update_draft_status(good, "approved")
    memory.update_draft_status(bad, "declined")
    memory.add_draft_feedback(bad, "looks amateurish")
    block = _decision_ledger_block(context)
    assert f"#{bad} DECLINED" in block
    assert "looks amateurish" in block  # rejection reason is structured context
    assert f"#{good} APPROVED" in block


def test_ledger_in_system_prompt_per_hop(env):
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def get_content(self): return {}
        def get_file(self, path, branch=None): return (None, None)
        def commit_file(self, path, data, message, branch=None): return {}

    memory, config, context = env
    bad = memory.save_draft("bad", "", "edit", meta={"ops": [{"op": "edit", "path": "x.html", "find": "a", "replace": "b"}]})
    memory.update_draft_status(bad, "declined")

    llm = FakeToolsLLM([
        {"content": None, "tool_calls": _tc("read_file", path="x.html")},
        {"content": None, "tool_calls": _tc(
            "propose_changes", summary="tweak", ops=[{"op": "edit", "path": "x.html", "find": "a", "replace": "c"}])},
        {"content": "done", "tool_calls": None},
    ])
    handle_message({"config": config, "memory": memory, "llm": llm}, Adapter(), "tweak the page")
    assert "Owner decision ledger" in llm.calls[0]["messages"][0]["content"]
    assert f"#{bad} DECLINED" in llm.calls[0]["messages"][0]["content"]


def test_tool_loop_reuses_cached_read_without_behavioral_nudge(env):
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def __init__(self):
            self.files = {"styles.css": ".footer { padding: 4px; }"}
            self.reads = 0
        def get_content(self): return {}
        def get_file(self, path, branch=None):
            self.reads += 1
            raw = self.files.get(path)
            return ("sha", raw.encode()) if raw is not None else (None, None)
        def commit_file(self, path, data, message, branch=None): return {}

    memory, config, context = env
    adapter = Adapter()
    llm = FakeToolsLLM([
        {"content": None, "tool_calls": _tc("read_file", path="styles.css")},
        {"content": None, "tool_calls": _tc("read_file", path="styles.css")},
        {"content": None, "tool_calls": _tc(
            "propose_changes", summary="tweak",
            ops=[{"op": "edit", "path": "styles.css", "find": ".footer { padding: 4px; }",
                  "replace": ".footer { padding: 28px; }"}])},
    ])
    result = handle_message({"config": config, "memory": memory, "llm": llm}, adapter, "add footer padding")
    first_tool = llm.calls[1]["messages"][-1]
    second_tool = llm.calls[2]["messages"][-1]
    assert ".footer { padding: 4px; }" in first_tool["content"]
    assert second_tool["content"] == first_tool["content"]
    assert adapter.reads == 3  # content summary + one file read + live validation
    assert result["proposal_id"] is not None


def test_system_prompt_describes_capabilities_without_forced_routing(env):
    llm = FakeToolsLLM([
        {"content": "I need one detail before changing it.", "tool_calls": None},
    ])
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def get_content(self): return {}
        def get_file(self, path, branch=None): return (None, None)
        def commit_file(self, path, data, message, branch=None): return {}

    handle_message({"config": env[1], "memory": env[0], "llm": llm}, Adapter(), "make it more alive")
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "creative lead" in prompt
    assert "spawn_build" in prompt
    assert "Stop reading files" not in prompt
    assert "call spawn_build immediately" not in prompt


def test_read_file_truncates_with_marker_and_guards_repeat_reads(env):
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def __init__(self):
            self.reads = 0
        def get_content(self): return {}
        def get_file(self, path, branch=None):
            self.reads += 1
            return ("sha", (b"/* head */\n" + b".x{}\n" * 2000).decode().encode())
        def commit_file(self, path, data, message, branch=None): return {}

    memory, config, context = env
    adapter = Adapter()
    llm = FakeToolsLLM([
        {"content": None, "tool_calls": _tc("read_file", path="styles.css")},
        {"content": None, "tool_calls": _tc("read_file", path="styles.css")},
        {"content": "I have what I need.", "tool_calls": None},
    ])
    result = handle_message({"config": config, "memory": memory, "llm": llm}, adapter, "tweak styles")
    first = llm.calls[1]["messages"][-1]["content"]
    second = llm.calls[2]["messages"][-1]["content"]
    assert len(first) <= 4000
    assert "file continues" in first
    assert "already read styles.css" in second
    assert adapter.reads <= 2  # the repeated read never re-fetches the blob
    assert result["reply"] == "I have what I need."


def test_tool_loop_rejects_mixed_mutation_batch(env):
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def get_content(self): return {}
        def get_file(self, path, branch=None): return (None, None)
        def commit_file(self, path, data, message, branch=None): return {}

    mixed = [
        {"id": "read", "type": "function",
         "function": {"name": "read_file", "arguments": json.dumps({"path": "styles.css"})}},
        {"id": "write", "type": "function",
         "function": {"name": "propose_changes", "arguments": json.dumps({
             "summary": "unsafe batch", "ops": [{"op": "write", "path": "x.html", "content": "x"}]
         })}},
    ]
    llm = FakeToolsLLM([
        {"content": None, "tool_calls": mixed},
        {"content": "I did not stage an ambiguous batch.", "tool_calls": None},
    ])
    result = handle_message({"config": env[1], "memory": env[0], "llm": llm}, Adapter(), "change it")
    assert result["proposal_id"] is None
    assert env[0].list_drafts(status="pending") == []
    assert all(m["content"].startswith("REFUSED") for m in llm.calls[1]["messages"][-2:])


def test_validate_ops_preserves_write_content_and_restricts_set_field(env):
    from site_agent.brain.editor import EditError, validate_ops
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def get_content(self): return {"hero": "old"}
        def get_file(self, path, branch=None):
            files = {"content.json": b'{"hero":"old"}', "other.json": b'{"hero":"old"}'}
            return ("sha", files[path]) if path in files else (None, None)
        def commit_file(self, path, data, message, branch=None): return {}

    adapter = Adapter()
    content = "<!doctype html><title>New</title>"
    clean = validate_ops(env[2], [{"op": "write", "path": "new.html", "content": content}], adapter)
    assert clean == [{"op": "write", "path": "new.html", "content": content}]
    with pytest.raises(EditError, match="can only change content.json"):
        validate_ops(env[2], [{"op": "set_field", "path": "other.json",
                               "field": "hero", "value": "new"}], adapter)


def test_apply_ops_writes_content_and_deletes_on_requested_branch():
    from site_agent.brain.editor import _apply_ops
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def __init__(self): self.calls = []
        def get_content(self, branch=None): return {}
        def get_file(self, path, branch=None): return (None, None)
        def commit_file(self, path, data, message, branch=None):
            self.calls.append(("write", path, data, branch))
            return {"committed": True}
        def delete_file(self, path, message, branch=None):
            self.calls.append(("delete", path, None, branch))
            return {"deleted": True}

    adapter = Adapter()
    _apply_ops(adapter, [
        {"op": "write", "path": "new.html", "content": "<p>new</p>"},
        {"op": "delete", "path": "old.html"},
    ], branch="preview")
    assert adapter.calls == [
        ("write", "new.html", b"<p>new</p>", "preview"),
        ("delete", "old.html", None, "preview"),
    ]


def test_tool_calling_required_no_json_fallback(env):
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def get_content(self): return {}
        def get_file(self, path, branch=None): return (None, None)
        def commit_file(self, path, data, message, branch=None): return {}

    class NoToolsLLM:
        def chat(self, messages, **kwargs):
            return json.dumps({"reply": "hi", "action": None})

    config = env[1]
    with pytest.raises(RuntimeError, match="Native tool calling is required"):
        handle_message({"config": config, "memory": env[0], "llm": NoToolsLLM()},
                       Adapter(), "build a page")
