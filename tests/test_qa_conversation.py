import json

import pytest

from site_agent.qa.conversation import OwnerAgent, chat_completion, opencode_completion


def test_the_owner_is_told_who_they_are_and_how_to_answer():
    seen = {}

    def complete(messages):
        seen["messages"] = messages
        return "Atelier Sete, and we have been here six years."

    owner = OwnerAgent("You are Mariana, who runs a ceramics studio.", complete)
    owner.reply("What is the studio called?")
    system = seen["messages"][0]["content"]
    assert seen["messages"][0]["role"] == "system"
    assert "Mariana" in system
    assert "three sentences" in system
    assert "Never invent a fact" in system


def test_the_transcript_is_threaded_so_the_owner_stays_coherent():
    calls = []

    def complete(messages):
        calls.append(messages)
        return f"answer {len(calls)}"

    owner = OwnerAgent("You are Mariana.", complete)
    owner.reply("What is the studio called?")
    owner.reply("How much are the classes?")

    second = calls[1]
    assert [message["role"] for message in second] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert second[1]["content"] == "What is the studio called?"
    assert second[2]["content"] == "answer 1"
    assert second[3]["content"] == "How much are the classes?"


def test_the_owner_never_sends_an_empty_turn():
    with pytest.raises(RuntimeError, match="empty reply"):
        OwnerAgent("You are Mariana.", lambda messages: "   ").reply("Hello?")


def test_an_owner_without_a_brief_is_rejected():
    with pytest.raises(ValueError, match="needs a brief"):
        OwnerAgent("   ", lambda messages: "x")


def test_owner_turns_are_recorded_for_the_evidence():
    owner = OwnerAgent("You are Mariana.", lambda messages: "Two of us run it.")
    owner.reply("Who runs the studio?")
    assert owner.transcript == [{"ada": "Who runs the studio?", "owner": "Two of us run it."}]


def test_chat_completion_reads_an_openai_compatible_response(monkeypatch):
    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": " 240 euros. "}}]}
            ).encode()

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        captured["auth"] = request.headers.get("Authorization")
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    complete = chat_completion(
        model="openai/gpt-6-luna",
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
    )
    assert complete([{"role": "user", "content": "hi"}]) == " 240 euros. "
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["body"]["model"] == "openai/gpt-6-luna"
    assert captured["auth"] == "Bearer test-key"


def test_chat_completion_surfaces_a_provider_error(monkeypatch):
    import urllib.error

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 402, "Payment Required", {}, None
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    complete = chat_completion(model="m", api_key="k")
    with pytest.raises(RuntimeError, match="402"):
        complete([{"role": "user", "content": "hi"}])


def test_opencode_reuses_auth_and_denies_tools(monkeypatch):
    from types import SimpleNamespace

    def run(argv, **kwargs):
        assert "--standalone" not in argv
        assert "env" not in kwargs, "do not replace the runner's auth/config environment"
        if argv[:3] == ["opencode", "api", "post"]:
            session = json.loads(argv[-1])
            assert session["permissions"] == [{"action": "*", "resource": "*", "effect": "deny"}]
            assert session["model"] == {"providerID": "openai", "id": "gpt-6-luna"}
            return SimpleNamespace(returncode=0, stdout='{"data":{"id":"ses_test"}}')
        assert argv[:6] == ["opencode", "run", "--session", "ses_test", "--model", "openai/gpt-6-luna"]
        assert "Mariana" in argv[-1]
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "type": "text", "part": {"text": "The studio is called Atelier Sete."}
        }))

    monkeypatch.setattr("site_agent.qa.conversation.subprocess.run", run)
    complete = opencode_completion()
    assert complete([{"role": "system", "content": "You are Mariana."}]) == (
        "The studio is called Atelier Sete."
    )


@pytest.mark.parametrize("returncode,output", [
    (1, "private credential diagnostic"),
    (0, '{"type":"error","error":"quota"}'),
    (0, '{"type":"step_finish"}'),
])
def test_opencode_failures_do_not_fallback_or_leak_diagnostics(monkeypatch, returncode, output):
    from types import SimpleNamespace
    calls = []

    def run(*args, **kwargs):
        if args[0][:3] == ["opencode", "api", "post"]:
            return SimpleNamespace(returncode=0, stdout='{"data":{"id":"ses_test"}}')
        calls.append(args)
        return SimpleNamespace(returncode=returncode, stdout=output)

    monkeypatch.setattr("site_agent.qa.conversation.subprocess.run", run)
    with pytest.raises(RuntimeError) as exc:
        opencode_completion()([{"role": "user", "content": "Hello"}])
    assert "private credential" not in str(exc.value)
    assert len(calls) == 1


def test_cli_defaults_to_openai_luna_without_an_openrouter_key(monkeypatch):
    from site_agent.qa.cli import _parser, _owner_completer
    monkeypatch.delenv("SITE_AGENT_QA_OWNER_MODEL", raising=False)
    monkeypatch.delenv("SITE_AGENT_QA_OWNER_BACKEND", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    seen = {}

    def factory(**kwargs):
        seen.update(kwargs)
        return lambda messages: "Hello"

    monkeypatch.setattr("site_agent.qa.cli.opencode_completion", factory)
    args = _parser().parse_args(["run", "flows/intake-to-preview.flow.yaml", "--base-url", "http://localhost"])
    assert args.owner_backend == "opencode"
    assert args.owner_model == "openai/gpt-6-luna"
    _owner_completer(args)
    assert seen == {"model": "openai/gpt-6-luna"}


def test_opencode_timeout_interrupts_its_own_session(monkeypatch):
    import subprocess
    from types import SimpleNamespace
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[:4] == ["opencode", "api", "post", "/api/session"]:
            return SimpleNamespace(returncode=0, stdout='{"data":{"id":"ses_owner_timeout"}}')
        if argv[1] == "run":
            raise subprocess.TimeoutExpired(argv, 1)
        return SimpleNamespace(returncode=0, stdout='{}')

    monkeypatch.setattr("site_agent.qa.conversation.subprocess.run", run)
    with pytest.raises(RuntimeError, match="timed out"):
        opencode_completion(timeout=1)([{"role": "user", "content": "Hello"}])
    assert calls[-1][3] == '/api/session/ses_owner_timeout/interrupt'
