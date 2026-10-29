import json

import pytest

from site_agent.qa.conversation import OwnerAgent, chat_completion


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
