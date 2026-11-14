from __future__ import annotations

from site_agent.core.memory import Memory


def _context(tmp_path):
    clone_path = tmp_path / "site"
    clone_path.mkdir(parents=True, exist_ok=True)
    tenant_config = tmp_path / "config.yaml"
    tenant_config.write_text("instance_name: demo\n", encoding="utf-8")
    tenant_env = tmp_path / "tenant.env"
    tenant_env.write_text("PROVISIONED_DEMO_TOKEN=fixture\n", encoding="utf-8")
    memory = Memory(tmp_path / "memory.db")
    return {
        "memory": memory,
        "config": {
            "builder": {"enabled": True},
            "site": {"clone_path": str(clone_path)},
        },
        "env": {},
        "tenant_config_path": str(tenant_config),
        "tenant_env_path": str(tenant_env),
    }


def _captured_turn(monkeypatch, context, history):
    from site_agent.hands import chat_agent, opencode_runner

    captured: dict = {}

    def fake_run_owner_turn(ctx, job_id, brief, **kwargs):
        captured["brief"] = brief
        captured["kwargs"] = kwargs
        return {"reply": "Ada's answer.", "changed": False}

    monkeypatch.setattr(opencode_runner, "run_owner_turn", fake_run_owner_turn)
    chat_agent.run_turn(context, 7, "essaie a nouveau", history, progress=None)
    return captured


def test_a_turn_carries_the_owners_earlier_request_and_the_failed_attempt(tmp_path, monkeypatch):
    """A retry must know what it is retrying.

    The conversation is durable in the tenant's message store. The OpenCode
    session that used to carry it belonged to the disposable builder
    worktree, so it never survived a turn: the retry only saw "try again".
    """
    context = _context(tmp_path)
    history = [
        {"role": "user", "content": "peux tu creer une version francaise du site"},
        {"role": "assistant", "content": "I couldn't complete this task, so there isn't a finished result to review."},
    ]

    captured = _captured_turn(monkeypatch, context, history)

    brief = captured["brief"]
    assert "peux tu creer une version francaise du site" in brief
    assert "I couldn't complete this task" in brief
    assert brief.rstrip().endswith("Owner: essaie a nouveau")


def test_a_turn_never_resumes_a_session_from_an_earlier_turn(tmp_path, monkeypatch):
    """The session store dies with the worktree, so no turn may resume one."""
    context = _context(tmp_path)
    memory = context["memory"]
    # What an earlier turn used to leave behind.
    memory.kv_set("chat_session:owner-turn:1", "ses_e26170d7affe4Ulu2ghOPf8arC")

    captured = _captured_turn(monkeypatch, context, [{"role": "user", "content": "essaie a nouveau"}])

    assert "session_id" not in captured["kwargs"]
    assert "ses_e26170d7affe4Ulu2ghOPf8arC" not in captured["brief"]


def test_a_turn_stores_no_session_for_the_next_turn(tmp_path, monkeypatch):
    """Nothing writes a session id that the next turn could never resolve."""
    context = _context(tmp_path)
    memory = context["memory"]

    _captured_turn(monkeypatch, context, [{"role": "user", "content": "essaie a nouveau"}])

    assert memory.kv_get("chat_session:owner-turn:1") is None


def test_the_first_turn_of_a_conversation_carries_only_its_own_request(tmp_path, monkeypatch):
    context = _context(tmp_path)

    captured = _captured_turn(monkeypatch, context, [])

    assert captured["brief"] == "essaie a nouveau"
