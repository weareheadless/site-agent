"""Builder behaviour: stacked previews, merge-draft staging, site digest."""

import json
import subprocess
import time

import pytest

from site_agent.application.actions import OwnerActionService
from site_agent.core.memory import Memory
from site_agent.core.contracts import ActionPriority, ActionRequirement, OwnerAction
from site_agent.hands import opencode_runner as runner
from site_agent.hands import site_digest


def _git(clone, *args):
    return subprocess.run(
        ["git", "-C", str(clone), *args], capture_output=True, text=True, check=True
    )


def _make_clone(tmp_path, name="siterepo"):
    """A real git repo with main + a preview branch that adds a page, and
    simulated remote-tracking refs so prepare_preview works without network."""
    clone = tmp_path / name
    clone.mkdir()
    _git(clone, "init", "-q", "-b", "main")
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    (clone / "index.html").write_text(
        "<html><head><title>Main</title></head><body><p>live</p></body></html>"
    )
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "main v1")
    main_sha = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    _git(clone, "branch", "preview")
    _git(clone, "checkout", "-q", "preview")
    (clone / "coaching.html").write_text(
        "<html><head><title>Coaching</title></head><body><p>staged page</p></body></html>"
    )
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "preview adds coaching")
    preview_sha = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    _git(clone, "checkout", "-q", "main")
    _git(clone, "update-ref", "refs/remotes/origin/main", main_sha)
    _git(clone, "update-ref", "refs/remotes/origin/preview", preview_sha)
    return clone


def _builder_config(clone):
    return {
        "env": {"github_token": "GITHUB_TOKEN", "llm_api_key": "LLM_KEY"},
        "data_dir": str(clone.parent / "data"),
        "site": {"repository": "acme/site", "clone_path": str(clone),
                 "writable_patterns": ["*.html", "*.css", "*.js", "images/*"]},
         "builder": {"enabled": True, "validation_repair_attempts": 2},
        "llm": {"model": "gpt-4o-mini"},
    }


def test_run_brief_lets_opencode_plan_and_execute_in_one_run(tmp_path, monkeypatch):
    clone = _make_clone(tmp_path)
    config = _builder_config(clone)
    memory = Memory(tmp_path / "data" / "memory.db")
    context = {"config": config, "memory": memory, "llm": object()}
    progress = []

    monkeypatch.setattr(runner, "prepare_preview", lambda *args, **kwargs: clone)
    monkeypatch.setattr(runner, "_site_digest", lambda *args, **kwargs: "site map")
    monkeypatch.setattr(runner, "_vision_context", lambda *args, **kwargs: "")
    monkeypatch.setattr(runner, "install_agent_files", lambda *args, **kwargs: None)
    captured = {}

    def fake_run_opencode(clone, brief, config, progress=None, session_id=None, timeout_seconds=None, **kwargs):
        captured["brief"] = brief
        return {"session_id": "session-1", "reply": "finished"}

    monkeypatch.setattr(runner, "run_opencode_turn", fake_run_opencode)

    outcome = runner.run_brief(context, "animate the homepage", progress.append)

    assert outcome["changed"] is False
    assert "creative lead" in captured["brief"]
    assert "distinctive design" in captured["brief"]
    assert "leave all changes UNCOMMITTED" in captured["brief"]
    assert "mapping the existing site" in progress
    assert "preparing design tools" in progress
    assert not any("implementation plan" in step or "inner voice" in step for step in progress)
    memory.close()


def test_run_brief_agent_files_do_not_count_as_implementation(tmp_path, monkeypatch):
    clone = _make_clone(tmp_path)
    config = _builder_config(clone)
    context = {"config": config, "memory": None, "llm": object()}

    monkeypatch.setattr(runner, "prepare_preview", lambda *args, **kwargs: clone)
    monkeypatch.setattr(runner, "_site_digest", lambda *args, **kwargs: "site map")
    monkeypatch.setattr(runner, "_vision_context", lambda *args, **kwargs: "")

    def fake_install(target, *args, **kwargs):
        (target / ".opencode").mkdir(parents=True)
        (target / ".opencode" / "ada-instructions.md").write_text("profile")
        (target / ".opencode" / "opencode.json").write_text("{}")

    monkeypatch.setattr(runner, "install_agent_files", fake_install)
    monkeypatch.setattr(
        runner, "run_opencode_turn",
        lambda *args, **kwargs: {"session_id": "session-1", "reply": "Finished"},
    )

    outcome = runner.run_brief(context, "animate the homepage")

    assert outcome == {"changed": False, "output": "Finished"}


def test_run_opencode_rejects_a_final_failed_tool_call(tmp_path, monkeypatch):
    class FakeProcess:
        pid = 12345
        returncode = 0
        stdout = iter(["→ Read index.html\n", "✗ Read styles.css failed\n"])

        def wait(self, timeout=None):
            return self.returncode

        def terminate(self):
            self.returncode = -15

    monkeypatch.setattr(runner, "_opencode_bin", lambda config: "opencode")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    with pytest.raises(runner.RunnerError, match="stopped after a failed tool call"):
        runner.run_opencode(tmp_path, "animate the homepage", {"builder": {"timeout_seconds": 3}})


def test_run_opencode_enforces_timeout_while_streaming(tmp_path, monkeypatch):
    class SlowStream:
        def __init__(self, process):
            self.process = process

        def __iter__(self):
            return self

        def __next__(self):
            time.sleep(0.05)
            if self.process.killed:
                raise StopIteration
            return "still working\n"

    class FakeProcess:
        pid = 12345
        returncode = -15

        def __init__(self):
            self.killed = False
            self.stdout = SlowStream(self)

        def wait(self, timeout=None):
            return self.returncode

        def terminate(self):
            self.killed = True

    process = FakeProcess()
    monkeypatch.setattr(runner, "_opencode_bin", lambda config: "opencode")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        runner.os,
        "killpg",
        lambda _pid, _signal: setattr(process, "killed", True),
    )

    with pytest.raises(runner.RunnerError, match="timed out after 1s"):
        runner.run_opencode(
            tmp_path, "animate the homepage", {"builder": {"timeout_seconds": 1}}
        )


def test_run_opencode_leaves_provider_retries_to_opencode(tmp_path, monkeypatch):
    class FakeProcess:
        pid = 12345
        returncode = 0

        def __init__(self):
            self.killed = False
            self.stdout = iter([
                "provider_unavailable: Model is at capacity\n",
                "provider_unavailable: Model is at capacity\n",
                "Recovered and finished the requested work.\n",
            ])

        def wait(self, timeout=None):
            return self.returncode

        def terminate(self):
            self.killed = True

    process = FakeProcess()
    captured = {}
    monkeypatch.setattr(runner, "_opencode_bin", lambda config: "opencode")

    def fake_popen(*args, **kwargs):
        captured["command"] = args[0]
        return process

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        runner.os,
        "killpg",
        lambda _pid, _signal: setattr(process, "killed", True),
    )

    output = runner.run_opencode(
        tmp_path,
        "animate the homepage",
        {"llm": {"model": "deepseek/deepseek-v4-flash-0731"}},
    )

    assert "--print-logs" in captured["command"]
    assert "--auto" in captured["command"]
    assert "--agent" in captured["command"]
    assert "build" in captured["command"]
    assert "qwen" not in captured["command"]
    assert process.killed is False
    assert "Recovered and finished" in output


def test_run_opencode_does_not_treat_silence_as_a_stall(tmp_path, monkeypatch):
    class DelayedStream:
        def __iter__(self):
            time.sleep(1.1)
            yield "Finished after a quiet model turn.\n"

    class FakeProcess:
        pid = 12345
        returncode = 0
        stdout = DelayedStream()

        def wait(self, timeout=None):
            return self.returncode

        def terminate(self):
            raise AssertionError("a healthy quiet process must not be terminated")

    process = FakeProcess()
    monkeypatch.setattr(runner, "_opencode_bin", lambda config: "opencode")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        runner.os,
        "killpg",
        lambda _pid, _signal: (_ for _ in ()).throw(
            AssertionError("a healthy quiet process must not be terminated")
        ),
    )

    output = runner.run_opencode(
        tmp_path,
        "animate the homepage",
        {"builder": {"timeout_seconds": 3, "idle_timeout_seconds": 1}},
    )

    assert "Finished after a quiet model turn" in output


def test_run_opencode_turn_parses_events_and_resumes_session(tmp_path, monkeypatch):
    class FakeProcess:
        pid = 12345
        returncode = 0

        def __init__(self, lines):
            self.stdout = iter(lines)

        def wait(self, timeout=None):
            return self.returncode

    sessions = [
        [
            json.dumps({"type": "step_start", "sessionID": "session-1"}),
            json.dumps({
                "type": "tool_use",
                "sessionID": "session-1",
                "part": {"type": "tool", "tool": "write", "state": {"status": "completed"}},
            }),
            json.dumps({"type": "text", "part": {"text": "Direction ready."}}),
        ],
        [json.dumps({"type": "text", "part": {"text": "Implementation ready."}})],
    ]
    commands = []
    monkeypatch.setattr(runner, "_opencode_bin", lambda config: "opencode")

    def fake_popen(*args, **kwargs):
        commands.append(args[0])
        return FakeProcess(sessions.pop(0))

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    config = {"builder": {"timeout_seconds": 3, "model": "deepseek/model"}}

    first = runner.run_opencode_turn(tmp_path, "direction", config)
    second = runner.run_opencode_turn(
        tmp_path, "implement", config, session_id=first["session_id"]
    )

    assert first["session_id"] == "session-1"
    assert first["native_tool_calls"] == 1
    assert second["session_id"] == "session-1"
    assert "--format" in commands[0] and "json" in commands[0]
    assert commands[1][commands[1].index("--session") + 1] == "session-1"


def test_run_opencode_turn_streams_all_live_steps_but_returns_only_final_segment(tmp_path, monkeypatch):
    class FakeProcess:
        pid = 12345
        returncode = 0

        def __init__(self, lines):
            self.stdout = iter(lines)

        def wait(self, timeout=None):
            return self.returncode

    lines = [json.dumps({"type": "step_start", "sessionID": "session-progress"})]
    lines.extend(
        json.dumps({"type": "text", "part": {"text": f"Inspecting repository area {index}."}})
        for index in range(10)
    )
    lines.append(json.dumps({
        "type": "tool_use",
        "part": {"type": "tool", "tool": "read", "state": {"status": "completed"}},
    }))
    lines.extend([
        json.dumps({"type": "text", "part": {"text": "The mobile preview is ready."}}),
        json.dumps({"type": "text", "part": {"text": "Review the updated draft when ready."}}),
    ])

    monkeypatch.setattr(runner, "_opencode_bin", lambda config: "opencode")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: FakeProcess(lines))
    progress: list[str] = []

    result = runner.run_opencode_turn(
        tmp_path,
        "inspect the mobile preview",
        {"builder": {"timeout_seconds": 3, "model": "deepseek/model"}},
        progress=progress.append,
    )

    assert all(f"Inspecting repository area {index}." in progress for index in range(10))
    assert result["reply"] == "The mobile preview is ready.\nReview the updated draft when ready."


def test_run_opencode_turn_stages_oversized_prompt_outside_argv(tmp_path, monkeypatch):
    class FakeProcess:
        pid = 12345
        returncode = 0
        stdout = iter([
            json.dumps({"type": "step_start", "sessionID": "session-large"}),
            json.dumps({"type": "text", "part": {"text": "finished"}}),
        ])

        def wait(self, timeout=None):
            return self.returncode

    commands = []
    monkeypatch.setattr(runner, "_opencode_bin", lambda config: "opencode")

    def fake_popen(*args, **kwargs):
        commands.append(args[0])
        staged = tmp_path / ".opencode/host-request.md"
        assert staged.read_text(encoding="utf-8") == "direction\n" * 60_000
        return FakeProcess()

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    brief = "direction\n" * 60_000

    result = runner.run_opencode_turn(
        tmp_path,
        brief,
        {"builder": {"timeout_seconds": 3, "model": "deepseek/model"}},
    )

    assert result["session_id"] == "session-large"
    assert commands[0][-1].startswith("Read the complete host request at .opencode/host-request.md")
    assert len(commands[0][-1].encode("utf-8")) < 1_000
    assert not (tmp_path / ".opencode/host-request.md").exists()


def test_run_opencode_turn_records_step_usage_and_provider_cost(tmp_path, monkeypatch):
    class FakeProcess:
        pid = 12345
        returncode = 0
        stdout = iter([
            json.dumps({"type": "step_start", "sessionID": "session-cost"}),
            json.dumps({
                "type": "step_finish",
                "part": {
                    "type": "step-finish",
                    "cost": 0.0123,
                    "tokens": {"input": 100, "output": 40, "reasoning": 10},
                },
            }),
            json.dumps({"type": "text", "part": {"text": "finished"}}),
        ])

        def wait(self, timeout=None):
            return self.returncode

    memory = Memory(tmp_path / "memory.db")
    monkeypatch.setattr(runner, "_opencode_bin", lambda config: "opencode")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    result = runner.run_opencode_turn(
        tmp_path,
        "build",
        {"builder": {"timeout_seconds": 3, "model": "deepseek/model"}},
        memory=memory,
    )

    assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    assert result["cost"] == 0.0123
    assert memory.llm_spend()["cost_usd"] == 0.0123
    memory.close()


def test_run_opencode_turn_attaches_image_files_after_message(tmp_path, monkeypatch):
    class FakeProcess:
        pid = 12345
        returncode = 0
        stdout = iter([json.dumps({"type": "step_start", "sessionID": "session-img"}),
                       json.dumps({"type": "text", "part": {"text": "seen"}})])

        def wait(self, timeout=None):
            return self.returncode

    commands = []
    monkeypatch.setattr(runner, "_opencode_bin", lambda config: "opencode")

    def fake_popen(*args, **kwargs):
        commands.append(args[0])
        return FakeProcess()

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner.os, "killpg", lambda *args: None)
    image = tmp_path / "evidence" / "render-00.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\xff\xd8\xff")

    first = runner.run_opencode_turn(
        tmp_path,
        "refine the render",
        {"builder": {"timeout_seconds": 3}},
        image_files=["evidence/render-00.jpg", str(image)],
    )

    assert first["session_id"] == "session-img"
    cmd = commands[0]
    assert cmd[-5] == "refine the render"
    assert cmd[-4] == "-f"
    assert cmd[-3] == str((tmp_path / "evidence" / "render-00.jpg").resolve())
    assert cmd[-2] == "-f"
    assert cmd[-1] == str(image)
    assert cmd.count("-f") == 2


def test_run_opencode_turn_rejects_plain_dsml(tmp_path, monkeypatch):
    class FakeProcess:
        pid = 12345
        returncode = 0
        stdout = iter([json.dumps({"type": "text", "part": {"text": "<DSML>tool"}})])

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(runner, "_opencode_bin", lambda config: "opencode")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(runner.os, "killpg", lambda *args: None)

    with pytest.raises(runner.RunnerError, match="unsupported DSML/XML"):
        runner.run_opencode_turn(tmp_path, "build", {"builder": {"timeout_seconds": 3}})


def test_initial_build_reports_validation_failure_without_automatic_repair(tmp_path, monkeypatch):
    clone = _make_clone(tmp_path)
    prepared = runner._change_state(clone)
    validation_calls = []
    turn_calls = []

    monkeypatch.setattr(
        runner, "_prepare_builder_context",
        lambda context, progress=None: (clone, clone, "origin/main", prepared),
    )

    def fake_validate(*args, **kwargs):
        validation_calls.append(True)
        raise runner.RunnerError("article output missing")

    monkeypatch.setattr(runner, "_validate_preview", fake_validate)
    monkeypatch.setattr(runner, "_remove_builder_worktree", lambda *args: None)

    def fake_phase(*args, **kwargs):
        turn_calls.append(kwargs.get("session_id"))
        (clone / "index.html").write_text("changed")
        return {"session_id": "session-1", "reply": "implemented"}

    monkeypatch.setattr(runner, "run_opencode_turn", fake_phase)

    with pytest.raises(runner.RunnerError, match="article output missing") as caught:
        runner.run_brief(
            {"config": {"builder": {"validation_repair_attempts": 2}}, "memory": None},
            "build the first homepage",
        )

    assert len(validation_calls) == 1
    assert turn_calls == [None]
    assert caught.value.result["validation_error"] == "article output missing"


def test_chat_job_records_builder_error_as_failed(tmp_path, monkeypatch):
    from site_agent.core.chat_jobs import run_job

    memory = Memory(tmp_path / "memory.db")
    conversation_id = memory.create_conversation("build")
    job_id = memory.enqueue_chat_job(conversation_id, "animate the homepage")
    worker = "worker"
    job = memory.claim_chat_job(worker)
    assert job is not None
    action = memory.create_owner_action(
        OwnerAction(
            capability_id="content.suggestion",
            provider_id="site-agent",
            title="Animate the homepage",
            summary="Ada is preparing the change.",
            action_label="Ask Ada to help",
            priority=ActionPriority.OPTIONAL,
            requirement=ActionRequirement.SUGGESTION,
            source_ref="test:builder-failure",
            dedupe_key="test:builder-failure",
            state="started",
            conversation_id=conversation_id,
        )
    )
    memory.link_owner_action(action.id, job_id=job_id)

    from site_agent.brain import editor

    monkeypatch.setattr(
        editor,
        "handle_message",
        lambda *args, **kwargs: {
            "reply": "Builder failed: opencode timed out",
            "proposal_id": None,
            "error": True,
        },
    )

    result = run_job(
        {"config": {"site": {}}, "memory": memory, "llm": object(), "owner_action_service": OwnerActionService(memory)},
        job,
        worker,
        adapter_factory=lambda: object(),
    )

    stored = memory.get_chat_job(job_id)
    assert stored["status"] == "error"
    assert "Builder failed" in stored["error"]
    assert "Builder failed" in result["error"]
    assert memory.get_owner_action(action.id).state.value == "waiting"
    memory.close()


def test_builder_rejects_changes_outside_writable_sandbox(tmp_path):
    clone = _make_clone(tmp_path)
    config = _builder_config(clone)
    _git(clone, "checkout", "-q", "preview")
    (clone / "package.json").write_text('{"scripts":{"postinstall":"bad"}}')

    with pytest.raises(runner.RunnerError, match="outside the writable sandbox"):
        runner._validate_build_paths(config, clone, "origin/preview")


def test_builder_allows_configured_site_files(tmp_path):
    clone = _make_clone(tmp_path)
    config = _builder_config(clone)
    _git(clone, "checkout", "-q", "preview")
    (clone / "styles.css").write_text("body { color: navy; }")

    runner._validate_build_paths(config, clone, "origin/preview")


def test_journal_scope_allows_only_public_journal_navigation_on_homepage(tmp_path):
    clone = _make_clone(tmp_path)
    original = (clone / "index.html").read_text()
    (clone / "index.html").write_text(
        original.replace("</body>", '<a href="/articles.html">Journal</a></body>')
    )

    runner._validate_journal_scope(clone, "origin/main")


def test_journal_scope_rejects_homepage_design_files(tmp_path):
    clone = _make_clone(tmp_path)
    (clone / "styles.css").write_text("body { color: red; }")

    with pytest.raises(runner.RunnerError, match="outside its isolated scope"):
        runner._validate_journal_scope(clone, "origin/main")


def test_journal_scope_rejects_non_navigation_homepage_markup(tmp_path):
    clone = _make_clone(tmp_path)
    original = (clone / "index.html").read_text()
    (clone / "index.html").write_text(original.replace("<p>live</p>", "<p>rewritten</p>"))

    with pytest.raises(runner.RunnerError, match="outside public journal navigation"):
        runner._validate_journal_scope(clone, "origin/main")


def test_builder_origin_url_never_persists_token():
    url = runner._origin_url("acme/site")
    assert url == "https://github.com/acme/site.git"
    assert "token" not in url


def test_ensure_clone_upgrades_https_origin_before_fetching_with_host_ssh(tmp_path, monkeypatch):
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    key = tmp_path / "github_ed25519"
    key.write_text("private-key-placeholder")
    key.chmod(0o600)
    profile = tmp_path / "host-credentials.yaml"
    profile.write_text(
        "credentials:\n"
        "  github:\n"
        f"    ssh_key_path: {key}\n",
        encoding="utf-8",
    )
    config = {
        "credentials": {"profile_file": str(profile)},
        "site": {
            "repository": "weareheadless/workspace-harmonie-headless",
            "clone_path": str(clone),
        },
    }
    calls = []

    def fake_git(_clone, *args, **kwargs):
        calls.append((args, kwargs))
        if args[:2] == ("remote", "get-url"):
            return "https://github.com/weareheadless/workspace-harmonie-headless.git\n"
        return ""

    monkeypatch.setattr(runner, "_git", fake_git)

    assert runner.ensure_clone(config) == clone
    assert any(
        args[:3] == ("remote", "set-url", "origin")
        and args[3] == "git@github.com:weareheadless/workspace-harmonie-headless.git"
        for args, _ in calls
    )
    fetch = next((item for item in calls if item[0][:2] == ("fetch", "origin")), None)
    assert fetch is not None
    assert str(key) in str(fetch[1]["ssh_command"])


def test_build_base_ref_stacks_on_pending_merge(tmp_path):
    memory = Memory(tmp_path / "m.db")
    assert runner._build_base_ref(memory) == "origin/main"
    memory.save_draft("pending edit", "{}", kind="edit", meta={"ops": []})
    assert runner._build_base_ref(memory) == "origin/main"
    memory.save_draft("unapproved build", "diff", kind="merge",
                      meta={"head": "preview", "base": "main"})
    assert runner._build_base_ref(memory) == "origin/preview"
    memory.close()


def test_prepare_preview_builds_on_top_of_unapproved_work(tmp_path, monkeypatch):
    clone = _make_clone(tmp_path)
    config = _builder_config(clone)
    monkeypatch.setattr(runner, "ensure_clone", lambda cfg, progress=None: clone)

    # follow-up request while a build is unapproved must keep the staged page
    worktree = runner.prepare_preview(config, base_ref="origin/preview")
    try:
        assert "staged page" in (worktree / "coaching.html").read_text()
    finally:
        runner._remove_builder_worktree(clone, worktree)

    # a fresh build (no pending work) starts from main: staged page absent
    worktree = runner.prepare_preview(config, base_ref="origin/main")
    try:
        assert not (worktree / "coaching.html").exists()
    finally:
        runner._remove_builder_worktree(clone, worktree)


def test_prepare_preview_falls_back_when_base_missing(tmp_path, monkeypatch):
    clone = _make_clone(tmp_path)
    config = _builder_config(clone)
    monkeypatch.setattr(runner, "ensure_clone", lambda cfg, progress=None: clone)
    _git(clone, "update-ref", "-d", "refs/remotes/origin/preview")
    # base_ref names a branch that no longer exists -> falls back to main, no crash
    worktree = runner.prepare_preview(config, base_ref="origin/preview")
    try:
        assert (worktree / "index.html").exists()
    finally:
        runner._remove_builder_worktree(clone, worktree)


def test_prepare_preview_always_isolated_and_never_touches_local_work(tmp_path, monkeypatch):
    clone = _make_clone(tmp_path)
    config = _builder_config(clone)
    monkeypatch.setattr(runner, "ensure_clone", lambda cfg, progress=None: clone)
    original = (clone / "index.html").read_text()
    (clone / "index.html").write_text(original.replace("Main", "Local work"))

    worktree = runner.prepare_preview(config, base_ref="origin/main")
    try:
        assert worktree != clone
        assert "Local work" in (clone / "index.html").read_text()
        assert "Main" in (worktree / "index.html").read_text()
    finally:
        runner._remove_builder_worktree(clone, worktree)
    assert "Local work" in (clone / "index.html").read_text()


def test_stage_merge_draft_supersedes_older_pending_merges(tmp_path):
    memory = Memory(tmp_path / "m.db")
    old = memory.save_draft("first build", "diff", kind="merge",
                            meta={"head": "preview", "base": "main"})
    keep = memory.save_draft("pending edit", "{}", kind="edit", meta={"ops": []})
    context = {"config": {}, "memory": memory}
    new = runner.stage_merge_draft(context, "improve the page", {"diff_stat": "coaching.html | 3 ++"})
    statuses = {d["id"]: d["status"] for d in memory.list_drafts(limit=10)}
    assert statuses[old] == "discarded"
    assert statuses[keep] == "pending"          # unrelated edits survive
    assert statuses[new] == "pending"
    draft = [d for d in memory.list_drafts(limit=10) if d["id"] == new][0]
    assert draft["kind"] == "merge"
    assert draft["meta"]["summary"] == "improve the page"
    assert draft["meta"]["preview"]["mode"] == "compile"
    memory.close()


def test_stage_build_returns_owner_ready_css_receipt(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "m.db")
    candidate = "a" * 40
    monkeypatch.setattr(
        runner,
        "run_brief",
        lambda context, message, progress=None: {
            "changed": True,
            "output": "internal builder transcript",
            "diff_stat": "styles.css | 4 +++-",
            "branch": "preview",
            "candidate_sha": candidate,
            "base_sha": "b" * 40,
            "changed_paths": ["src/app/(frontend)/styles.css"],
            "preview": runner.preview_plan_for_paths(["src/app/(frontend)/styles.css"]),
        },
    )

    result = runner.stage_build(
        {"memory": memory, "config": {"site": {"branch": "main", "preview_branch": "preview"}}},
        "give the homepage headings more room",
    )

    assert result["change"]["status"] == "ready_for_review"
    assert result["preview"]["status"] == "ready"
    assert "What changed:" in result["reply"]
    assert "internal builder transcript" not in result["reply"]
    draft = memory.list_drafts(limit=1)[0]
    assert draft["meta"]["head_sha"] == candidate
    assert draft["meta"]["preview"]["status"] == "ready"
    memory.close()


def test_stage_build_queues_compiled_preview_and_does_not_claim_ready(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "m.db")
    candidate = "c" * 40

    class Deployer:
        def start(self, request):
            assert request["mode"] == "compiled_preview"
            assert request["commit"] == candidate
            return {"id": "preview-job-1", "status": "queued"}

    monkeypatch.setattr(
        runner,
        "run_brief",
        lambda context, message, progress=None: {
            "changed": True,
            "output": "internal builder transcript",
            "diff_stat": "Page.tsx | 4 +++-",
            "branch": "preview",
            "candidate_sha": candidate,
            "base_sha": "b" * 40,
            "changed_paths": ["src/components/Page.tsx"],
            "preview": runner.preview_plan_for_paths(["src/components/Page.tsx"]),
        },
    )

    result = runner.stage_build(
        {
            "memory": memory,
            "config": {"site": {"branch": "main", "preview_branch": "preview"}},
            "source_deployment": Deployer(),
        },
        "change the homepage component",
    )

    assert result["change"]["status"] == "preparing_preview"
    assert result["preview"]["status"] == "building"
    assert result["preview"]["job_id"] == "preview-job-1"
    assert "preparing the real website preview" in result["reply"]
    memory.close()


def test_preview_plan_uses_overlay_for_css_and_compile_for_rendered_code():
    css = runner.preview_plan_for_paths(["src/app/(frontend)/styles.css"])
    assert css["mode"] == "overlay"
    assert css["requires_build"] is False

    code = runner.preview_plan_for_paths(["src/components/SiteChrome.tsx"])
    assert code["mode"] == "compile"
    assert code["requires_build"] is True


def test_site_digest_builds_structural_summary(tmp_path):
    clone = tmp_path / "siterepo"
    clone.mkdir()
    _git(clone, "init", "-q", "-b", "main")
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    (clone / "index.html").write_text(
        "<html><head><title>OceanicVibes</title>"
        '<link rel="stylesheet" href="styles.css">'
        "</head><body>"
        '<nav><a href="coaching.html">Coaching</a></nav>'
        '<section id="hero" class="hero"><h1>Breathe deep</h1></section>'
        "</body></html>"
    )
    (clone / "styles.css").write_text(
        ":root { --accent: #7ec8ff; --bg: #0b1017; }\n"
        ".hero { font-family: 'Manrope', sans-serif; }\n"
        ".footer p { color: #333; }\n"
        "@media (max-width: 768px) { .hero { padding: 10px; } }\n"
    )
    (clone / "content.json").write_text('{"heroTitle": "Breathe deep"}')
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "v1")
    _git(clone, "update-ref", "refs/remotes/origin/main",
         subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"],
                        capture_output=True, text=True).stdout.strip())

    digest = site_digest.build(clone, ref="main")
    assert "OceanicVibes" in digest
    assert "Coaching" in digest
    assert "hero" in digest
    assert "--accent" in digest and "#7ec8ff" in digest
    assert "Manrope" in digest
    assert "media queries: 1" in digest
    assert "content.json: yes" in digest


def test_site_digest_cached_until_main_moves(tmp_path, monkeypatch):
    clone = _make_clone(tmp_path)
    memory = Memory(tmp_path / "m.db")
    calls = []
    real_build = site_digest.build

    def counting_build(c, ref="origin/main"):
        calls.append(ref)
        return real_build(c, ref)

    monkeypatch.setattr(site_digest, "build", counting_build)
    first = site_digest.cached(clone, memory)
    assert len(calls) == 1
    assert site_digest.cached(clone, memory) == first     # cached: no rebuild
    assert len(calls) == 1
    memory.close()


def test_tools_spec_gates_spawn_build_on_builder(tmp_path):
    from site_agent.brain.editor import _tools_spec

    no_builder = {"site": {"clone_path": ""}, "builder": {}}
    assert "spawn_build" not in json.dumps(_tools_spec(no_builder))

    with_builder = {"site": {"clone_path": "/tmp/x"}, "builder": {"enabled": True}}
    assert "spawn_build" in json.dumps(_tools_spec(with_builder))

    disabled = {"site": {"clone_path": "/tmp/x"}, "builder": {"enabled": False}}
    assert "spawn_build" not in json.dumps(_tools_spec(disabled))


def _content_clone(tmp_path):
    clone = tmp_path / "maprepo"
    clone.mkdir()
    _git(clone, "init", "-q", "-b", "main")
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    (clone / "index.html").write_text(
        "<html><head><title>OV</title><link rel='stylesheet' href='styles.css'></head>"
        "<body><nav><a href='/coaching'>Coaching</a></nav>"
        '<section class="hero"><h1>Breathe deep</h1><p>Master your depth.</p></section>'
        "<footer><p>$1</p></footer></body></html>"
    )
    (clone / "styles.css").write_text(
        ":root{--ink:#071c22;--sea:#9edbd1}\n"
        ".hero{padding:120px 0;background:#e6f1eb}\n"
        ".footer{margin:0;color:#6a817d}\n"
    )
    (clone / "content.json").write_text(
        '{"heroTitle":"Breathe deep","about":{"lead":"lead text"}}'
    )
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "v1")
    _git(clone, "update-ref", "refs/remotes/origin/main",
         subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"],
                        capture_output=True, text=True).stdout.strip())
    return clone


def test_tweakmap_extracts_css_html_content(tmp_path):
    from site_agent.hands import tweakmap

    clone = _content_clone(tmp_path)
    files = tweakmap.build(clone, ref="main")
    css = {e["label"]: e for e in files["styles.css"]}
    assert css[".hero padding"]["current"] == "120px 0"
    assert css[".hero padding"]["find"] == "padding:120px 0;"
    assert css[".footer margin"]["find"] == "margin:0;"
    # :root vars capped, layout classes ranked first
    assert files["styles.css"][0]["selector"] in (".footer", ".hero")
    text = {e["label"]: e for e in files["index.html"]}
    assert any("Breathe deep" in l for l in text)
    # '$1' placeholder filtered out
    assert not any("$1" in l for l in text)
    fields = {e["field"]: e for e in files["content.json"]}
    assert fields["heroTitle"]["current"] == "Breathe deep"
    assert fields["about.lead"]["current"] == "lead text"


def test_tweakmap_ensure_caches_and_merges_builder_overlay(tmp_path, monkeypatch):
    from site_agent.hands import tweakmap

    clone = _content_clone(tmp_path)
    memory = Memory(tmp_path / "m.db")
    config = {"site": {"clone_path": str(clone)}}

    first = tweakmap.ensure(memory, config)
    assert first and first["styles.css"]

    calls = []
    real_build = tweakmap.build
    monkeypatch.setattr(tweakmap, "build", lambda c, ref="origin/main": calls.append(ref) or real_build(c, ref))
    assert tweakmap.ensure(memory, config) is not None   # cached: no rebuild
    assert calls == []

    # a builder overlay with a semantic label wins over the deterministic knob
    memory.kv_set(tweakmap.BUILDER_KEY, {
        "head": "previewsha",
        "files": {"styles.css": [
            {"kind": "css", "label": "hero.padding", "file": "styles.css",
             "selector": ".hero", "prop": "padding", "current": "120px 0", "find": "padding:120px 0;"}]},
    })
    merged = tweakmap.ensure(memory, config)
    hero = [e for e in merged["styles.css"] if e["label"] == "hero.padding"]
    assert hero and hero[0]["current"] == "120px 0"
    assert len(hero) == 1  # builder entry deduped over deterministic .hero padding

    tweakmap.drop_builder_map(memory)
    assert memory.kv_get(tweakmap.BUILDER_KEY) is None
    memory.close()


def test_store_builder_map_reads_agent_json(tmp_path):
    from site_agent.hands import tweakmap

    clone = _content_clone(tmp_path)
    memory = Memory(tmp_path / "m.db")
    oc = clone / ".opencode"
    oc.mkdir(exist_ok=True)
    (oc / "tweak-map.json").write_text(json.dumps({
        "files": {"styles.css": [
            {"kind": "css", "label": "footer.padding", "file": "styles.css",
             "selector": ".footer", "prop": "padding", "current": "0", "find": "margin:0;"}]},
    }))
    tweakmap.store_builder_map(clone, memory, "abc123")
    stored = memory.kv_get(tweakmap.BUILDER_KEY)
    assert stored["head"] == "abc123"
    assert stored["files"]["styles.css"][0]["label"] == "footer.padding"
    # missing file -> no-op
    (clone / ".opencode" / "tweak-map.json").unlink()
    memory.kv_set(tweakmap.BUILDER_KEY, None)
    tweakmap.store_builder_map(clone, memory, "x")
    assert memory.kv_get(tweakmap.BUILDER_KEY) is None
    memory.close()


def test_tweakmap_injected_into_tool_prompt(tmp_path):
    from site_agent.hands import tweakmap

    class FakeToolsLLM:
        def __init__(self):
            self.calls = []

        def chat_tools(self, messages, tools, temperature=None):
            self.calls.append(messages)
            if len(self.calls) > 1:
                return {"content": "Staged.", "tool_calls": None}
            return {
                "content": "Staged.",
                "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "propose_changes",
                                  "arguments": json.dumps({
                                      "summary": "footer margin",
                                      "ops": [{"op": "edit", "path": "styles.css",
                                               "find": "margin:0;", "replace": "margin:4px;"}]})}}
                ],
            }

    from site_agent.brain.editor import handle_message
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def get_content(self): return {"heroTitle": "Breathe deep"}
        def get_file(self, path, branch=None): return (None, None)
        def commit_file(self, path, data, message, branch=None): return {}

    clone = _content_clone(tmp_path)
    memory = Memory(tmp_path / "m.db")
    config = {
        "site": {"adapter": "github_static", "repository": "acme/site",
                 "content_path": "content.json", "clone_path": str(clone),
                 "writable_patterns": ["*.html", "*.css", "*.md"]},
        "llm": {"tool_calling": True},
        "persona": {"name": "Ada"},
    }
    llm = FakeToolsLLM()
    handle_message({"config": config, "memory": memory, "llm": llm},
                   Adapter(), "add 2px to the footer margin")
    system_prompt = llm.calls[0][0]["content"]
    assert "Editable parameters" in system_prompt
    assert ".hero padding" in system_prompt
    memory.close()


def test_file_cache_serves_repeated_reads_instantly():
    from site_agent.hands import file_cache

    class Adapter:
        def __init__(self):
            self.calls = []

        def get_file(self, path, branch=None):
            self.calls.append(path)
            return ("sha", f"<p>{path}</p>".encode())

    config = {"site": {"repository": "acme/site"}}
    a = Adapter()
    assert file_cache.get(config, a, "styles.css") == b"<p>styles.css</p>"
    assert file_cache.get(config, a, "styles.css") == b"<p>styles.css</p>"
    assert a.calls == ["styles.css"]        # fetched once, second read cached
    file_cache.clear()
    assert file_cache.get(config, a, "styles.css") == b"<p>styles.css</p>"
    assert a.calls == ["styles.css", "styles.css"]  # cleared -> refetch


def _token_clone(tmp_path):
    """A repo whose main page carries a real, measured design contract."""
    clone = tmp_path / "tokrepo"
    clone.mkdir()
    _git(clone, "init", "-q", "-b", "main")
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    (clone / "index.html").write_text(
        "<html><head><title>OV Template</title>"
        '<link rel="stylesheet" href="styles.css">'
        "</head><body><p>main</p></body></html>"
    )
    (clone / "styles.css").write_text(
        ":root{--ink:#071c22;--sea:#9edbd1;--sans:'Manrope',sans-serif}\n"
        "body{margin:0;font-size:15px;line-height:1.6}\n"
        ".site-header{position:fixed;top:22px;padding:13px 18px;z-index:10;"
        "width:min(1240px,calc(100% - 48px));"
        "border:1px solid rgba(226,244,236,.16);border-radius:999px}\n"
        ".hero{padding:180px 0}\n"
        ".closing-copy{padding-top:120px;padding-bottom:120px}\n"
        ".footer{padding:54px 0 76px}\n"
        "@media(max-width:800px){.hero{padding:90px 0}}\n"
    )
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "v1")
    _git(clone, "update-ref", "refs/remotes/origin/main",
         subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"],
                        capture_output=True, text=True).stdout.strip())
    return clone


def test_template_tokens_extracts_main_page_contract(tmp_path):
    from site_agent.hands import template_tokens

    clone = _token_clone(tmp_path)
    out = template_tokens.build(clone, ref="main")
    assert "OV Template" in out
    assert "--sea #9edbd1" in out                  # :root variables
    assert "page margin (body): 0" in out
    assert "min(1240px" in out                     # container width
    assert "section vertical spacing: 180px" in out  # .hero wins over closing
    assert "footer padding: 54px 0 76px" in out
    assert "border radius: 999px" in out
    assert "border style: 1px solid rgba(226,244,236,.16)" in out
    assert "body type: 15px / 1.6" in out
    assert "primary header layout: .site-header position fixed" in out
    assert "fixed-header content safety:" in out
    assert "responsive breakpoints (media queries): 1" in out
    # media-query values must not leak into the base contract
    assert "90px" not in out


def test_template_tokens_ignores_admin_sheets(tmp_path):
    from site_agent.hands import template_tokens

    clone = tmp_path / "adminsite"
    clone.mkdir()
    _git(clone, "init", "-q", "-b", "main")
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    (clone / "index.html").write_text("<html><head><title>X</title></head><body>y</body></html>")
    (clone / "admin.css").write_text("body{margin:99px}")
    (clone / "styles.css").write_text("body{margin:0;font-size:14px;line-height:1.5}")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "v1")
    _git(clone, "update-ref", "refs/remotes/origin/main",
         subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"],
                        capture_output=True, text=True).stdout.strip())
    out = template_tokens.build(clone, ref="main")
    assert "page margin (body): 0" in out       # styles.css, not admin.css
    assert "99px" not in out


def test_template_tokens_cached_until_main_moves(tmp_path, monkeypatch):
    from site_agent.hands import template_tokens

    clone = _token_clone(tmp_path)
    memory = Memory(tmp_path / "m.db")
    calls = []
    real_build = template_tokens.build

    def counting_build(c, ref="origin/main"):
        calls.append(ref)
        return real_build(c, ref)

    monkeypatch.setattr(template_tokens, "build", counting_build)
    first = template_tokens.cached(clone, memory)
    assert len(calls) == 1
    assert template_tokens.cached(clone, memory) == first   # cached: no rebuild
    assert len(calls) == 1
    memory.close()


def test_template_tokens_injected_into_builder_agent_md(tmp_path):
    clone = _token_clone(tmp_path)
    runner.install_agent_files(
        clone, None, "gpt-4o-mini", "k",
        persona="WHO YOU ARE:\ncalm coach.",
        site_digest="pages: 1",
        template_tokens="section vertical spacing: 180px",
    )
    instructions = (clone / ".opencode" / "ada-instructions.md").read_text()
    opencode_config = json.loads((clone / "opencode.json").read_text())
    assert "DESIGN REFERENCE" in instructions
    assert "The design quality core wins" in instructions
    assert "180px" in instructions
    assert "SITE REFERENCE" in instructions
    assert "pages: 1" in instructions
    assert "calm coach" in instructions
    assert "do not create or start GSAP timelines" in instructions
    assert "visible at first paint" in instructions
    assert opencode_config["instructions"] == [".opencode/ada-instructions.md"]
    assert opencode_config["permission"]["task"]["*"] == "allow"


def test_build_brief_carries_role_and_leaves_design_to_ada():
    brief = runner.build_brief("make the homepage feel warmer", {})
    assert "Owner: make the homepage feel warmer" in brief
    assert "creative lead" in brief
    assert "distinctive design" in brief
    assert "design and motion skills define the quality bar" in brief
    assert "not a prescribed direction" not in brief
    assert "UNCOMMITTED" in brief
    assert "DESIGN SCOPE" not in brief


def test_build_brief_journal_has_bounded_layout_contract():
    brief = runner.build_brief(
        "set up the Pelican journal",
        {"blog": {"engine": "pelican"}, "site": {"payload": {"enabled": False}}},
    )
    assert "JOURNAL REQUEST" in brief
    assert "autonomously" in brief
    assert "phased design" not in brief
    assert "fixed-header" in brief


def test_build_brief_payload_journal_uses_native_source_contract():
    brief = runner.build_brief(
        "fix the journal link",
        {"blog": {"engine": "payload"}, "site": {"payload": {"enabled": True}}},
    )
    assert "NATIVE NEXT/PAYLOAD REQUEST" in brief
    assert "JOURNAL REQUEST" not in brief
    assert "Do not execute build.sh" in brief


def test_install_agent_files_does_not_modify_site_files(tmp_path):
    clone = _token_clone(tmp_path)
    gitignore = clone / ".gitignore"
    before = gitignore.read_text() if gitignore.exists() else ""

    runner.install_agent_files(clone, None, "gpt-4o-mini", "k")

    instructions = (clone / ".opencode" / "ada-instructions.md").read_text()
    opencode_config = json.loads((clone / "opencode.json").read_text())
    assert "creative lead" in instructions
    assert "native task tool" in instructions
    assert "Motion library catalog" not in instructions
    assert opencode_config["permission"]["task"]["*"] == "allow"
    assert (gitignore.read_text() if gitignore.exists() else "") == before
    status = _git(clone, "status", "--porcelain").stdout
    assert ".opencode" not in status
    assert ".agent-home" not in status


def test_install_agent_files_configures_slow_streaming_provider(tmp_path):
    clone = _token_clone(tmp_path)
    runner.install_agent_files(
        clone, None, "deepseek/deepseek-v4-flash-0731", "k",
        provider_timeout_seconds=2100,
        provider_chunk_timeout_seconds=180,
        output_tokens=8192,
    )

    config = json.loads((clone / "opencode.json").read_text())
    provider = config["provider"]["openrouter"]
    assert config["model"] == "openrouter/deepseek/deepseek-v4-flash-0731"
    assert provider["options"]["timeout"] == 2_100_000
    assert provider["options"]["chunkTimeout"] == 180_000
    assert provider["models"]["deepseek/deepseek-v4-flash-0731"]["limit"] == {
        "context": 1_048_576,
        "output": 8192,
    }
    assert provider["models"]["deepseek/deepseek-v4-flash-0731"]["options"] == {
        "max_tokens": 8192,
        "reasoning_effort": "low",
    }
    assert provider["options"]["apiKey"] == "{env:OPENROUTER_API_KEY}"
    assert '"apiKey": "k"' not in (clone / "opencode.json").read_text()


def test_install_agent_files_qualifies_openai_model_without_storing_key(tmp_path):
    clone = _token_clone(tmp_path)
    runner.install_agent_files(
        clone, None, "gpt-5.6-luna", "k",
        provider_base_url="https://api.openai.com/v1",
    )

    config = json.loads((clone / "opencode.json").read_text())
    assert config["model"] == "openai/gpt-5.6-luna"
    assert config["provider"]["openai"]["options"]["apiKey"] == "{env:OPENAI_API_KEY}"
    assert config["provider"]["openai"]["options"]["baseURL"] == "https://api.openai.com/v1"
    assert config["provider"]["openai"]["models"]["gpt-5.6-luna"]["name"] == "Ada's working model"
    assert '"apiKey": "k"' not in (clone / "opencode.json").read_text()


def test_install_agent_files_configures_entrim_openai_compatible_provider(tmp_path):
    clone = _token_clone(tmp_path)
    runner.install_agent_files(
        clone, None, "entrim/deepseek-ai/DeepSeek-V4-Flash", "k",
        provider_base_url="https://api.entrim.ai/v1",
    )

    config = json.loads((clone / "opencode.json").read_text())
    provider = config["provider"]["entrim"]
    assert config["model"] == "entrim/deepseek-ai/DeepSeek-V4-Flash"
    assert provider["options"]["apiKey"] == "{env:ENTRIM_API_KEY}"
    assert provider["options"]["baseURL"] == "https://api.entrim.ai/v1"
    assert provider["models"]["deepseek-ai/DeepSeek-V4-Flash"]["limit"]["output"] == 8192
    assert '"apiKey": "k"' not in (clone / "opencode.json").read_text()


def test_install_agent_files_uses_configured_provider_credential_name(tmp_path):
    clone = _token_clone(tmp_path)
    runner.install_agent_files(
        clone, None, "entrim/deepseek-ai/DeepSeek-V4-Flash", "k",
        provider_base_url="https://api.entrim.ai/v1",
        provider_env_name="SITE_AGENT_LLM_API_KEY",
    )

    config = json.loads((clone / "opencode.json").read_text())
    assert config["provider"]["entrim"]["options"]["apiKey"] == "{env:SITE_AGENT_LLM_API_KEY}"


def test_builder_environment_does_not_inherit_operator_secrets(tmp_path, monkeypatch):
    clone = _token_clone(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("SITE_AGENT_ADMIN_PASSWORD", "admin-secret")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = runner._isolated_env(clone, "openrouter-secret")

    assert env["OPENROUTER_API_KEY"] == "openrouter-secret"
    assert "GITHUB_TOKEN" not in env
    assert "OPENAI_API_KEY" not in env
    assert "SITE_AGENT_ADMIN_PASSWORD" not in env
    assert env["HOME"] == str(clone / ".agent-home")


def test_builder_environment_maps_provider_key_without_other_secrets(tmp_path, monkeypatch):
    clone = _token_clone(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = runner._isolated_env(clone, "openai-secret", provider="openai")

    assert env["OPENAI_API_KEY"] == "openai-secret"
    assert "GITHUB_TOKEN" not in env
    assert "OPENROUTER_API_KEY" not in env


def test_builder_environment_maps_entrim_provider_key_without_other_secrets(tmp_path, monkeypatch):
    clone = _token_clone(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = runner._isolated_env(clone, "entrim-secret", provider="entrim")

    assert env["ENTRIM_API_KEY"] == "entrim-secret"
    assert "GITHUB_TOKEN" not in env
    assert "OPENROUTER_API_KEY" not in env


def test_run_opencode_turn_uses_supplied_child_environment(tmp_path, monkeypatch):
    captured = {}

    class FakeProcess:
        pid = 12345
        returncode = 0
        stdout = iter(())

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(runner, "_opencode_bin", lambda config: "opencode")

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    child_home = tmp_path / "process-home"
    runner.run_opencode_turn(
        tmp_path,
        "build",
        {"builder": {"timeout_seconds": 3, "model": "entrim/model"}},
        api_key="selected-secret",
        env={
            "HOME": str(child_home),
            "PATH": "/usr/bin",
            "GITHUB_TOKEN": "operator-secret",
        },
    )

    child_env = captured["env"]
    assert child_env["HOME"] == str(child_home.resolve())
    assert child_env["PATH"] == "/usr/bin"
    assert child_env["ENTRIM_API_KEY"] == "selected-secret"
    assert "GITHUB_TOKEN" not in child_env


def test_template_tokens_describe_shadow_without_prescribing_flatness(tmp_path):
    from site_agent.hands import template_tokens

    clone = _token_clone(tmp_path)
    (clone / "styles.css").write_text(
        ":root{--ink:#071c22}\nbody{margin:0;box-shadow:none}"
    )
    _git(clone, "add", "styles.css")
    _git(clone, "commit", "-qm", "shadow")
    out = template_tokens.build(clone, ref="main")
    assert "shadow: none on sampled rules" in out
    assert "flat surfaces" not in out


def test_template_tokens_injected_into_chat_tools_prompt(tmp_path):
    from site_agent.hands import template_tokens

    class FakeToolsLLM:
        def __init__(self):
            self.calls = []

        def chat_tools(self, messages, tools, temperature=None):
            self.calls.append(messages)
            if len(self.calls) > 1:
                return {"content": "Staged.", "tool_calls": None}
            return {
                "content": "Staged.",
                "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "propose_changes",
                                  "arguments": json.dumps({
                                      "summary": "new page",
                                      "ops": []})}}
                ],
            }

    from site_agent.brain.editor import handle_message
    from site_agent.hands.base import SiteAdapter

    class Adapter(SiteAdapter):
        name = "t"
        site = {"content_path": "content.json"}
        def get_content(self): return {}
        def get_file(self, path, branch=None): return (None, None)
        def commit_file(self, path, data, message, branch=None): return {}

    clone = _token_clone(tmp_path)
    memory = Memory(tmp_path / "m.db")
    config = {
        "site": {"adapter": "github_static", "repository": "acme/site",
                 "content_path": "content.json", "clone_path": str(clone),
                 "writable_patterns": ["*.html", "*.css", "*.md"]},
        "llm": {"tool_calling": True},
        "persona": {"name": "Ada"},
    }
    llm = FakeToolsLLM()
    handle_message({"config": config, "memory": memory, "llm": llm},
                   Adapter(), "build me a coaching page")
    system_prompt = llm.calls[0][0]["content"]
    assert "Design reference" in system_prompt
    assert "section vertical spacing: 180px" in system_prompt
    memory.close()
