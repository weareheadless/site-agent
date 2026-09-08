import base64
import json
from unittest import mock

import pytest

from site_agent.core.llm import Client, LLMError, _http_post, estimate_usage_cost
from site_agent.core.memory import Memory


def _config(base_url="https://api.test/v1"):
    return {
        "env": {"llm_api_key": "TEST_KEY"},
        "llm": {
            "base_url": base_url,
            "model": "test-model",
            "timeout_seconds": 5,
            "max_retries": 2,
            "price_per_mtok": {"input": 1.0, "output": 2.0},
        },
    }


_FAKE_ENV = {"TEST_KEY": "sk-live-key"}


def test_estimate_usage_cost_does_not_turn_a_missing_receipt_into_zero():
    assert estimate_usage_cost({}, {"input": 0.15, "output": 0.60}) is None


def _response(content="ok", prompt=100, completion=50):
    return {
        "model": "test-model",
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


def test_http_post_sends_auth_and_payload():
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode()

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return FakeResp()

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        out = _http_post("https://api.test/v1/x", {"Authorization": "Bearer k"}, {"a": 1}, 5)

    assert out == {"ok": True}
    assert captured["url"] == "https://api.test/v1/x"
    assert captured["body"] == {"a": 1}


def test_http_post_wraps_http_error():
    import urllib.error

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, mock.MagicMock())

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        with pytest.raises(LLMError, match="http 401"):
            _http_post("https://api.test/v1/x", {}, {}, 5)


def test_http_post_classifies_provider_error_payload_as_retryable():
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({
                "error": {"code": 503, "message": "model is at capacity"},
            }).encode()

    with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
        with pytest.raises(LLMError, match="model is at capacity") as caught:
            _http_post("https://api.test/v1/x", {}, {}, 5)

    assert caught.value.code == "provider_error"
    assert caught.value.status == 503
    assert caught.value.retryable is True


def test_http_post_retries_invalid_json_response():
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"not json"

    with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
        with pytest.raises(LLMError, match="invalid JSON") as caught:
            _http_post("https://api.test/v1/x", {}, {}, 5)

    assert caught.value.code == "invalid_response"
    assert caught.value.retryable is True


def test_chat_success_logs_cost(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    with mock.patch("site_agent.core.llm._http_post", return_value=_response()):
        client = Client(_config(), mem, _FAKE_ENV)
        text = client.chat([{"role": "user", "content": "hi"}])
    assert text == "ok"
    spend = mem.llm_spend()
    assert spend["prompt_tokens"] == 100
    expected = round(100 * 1.0 / 1e6 + 50 * 2.0 / 1e6, 6)
    assert abs(spend["cost_usd"] - expected) < 1e-9
    mem.close()


def test_chat_prefers_provider_reported_cost(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    response = _response()
    response["usage"]["cost"] = "0.1234567"
    with mock.patch("site_agent.core.llm._http_post", return_value=response):
        client = Client(_config(), mem, _FAKE_ENV)
        assert client.chat([{"role": "user", "content": "hi"}]) == "ok"
    assert mem.llm_spend()["cost_usd"] == 0.123457
    mem.close()


def test_openrouter_requests_authoritative_usage_receipt(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    response = _response()
    response["usage"]["cost"] = 0.000321
    captured = {}

    def fake_post(url, headers, payload, timeout):
        captured["payload"] = payload
        return response

    with mock.patch("site_agent.core.llm._http_post", fake_post):
        client = Client(_config("https://openrouter.ai/api/v1"), mem, _FAKE_ENV)
        assert client.chat([{"role": "user", "content": "hi"}]) == "ok"

    assert captured["payload"]["usage"] == {"include": True}
    assert mem.llm_spend()["cost_usd"] == 0.000321
    mem.close()


def test_client_can_disable_provider_thinking_for_structured_output(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    config = _config("https://openrouter.ai/api/v1")
    config["llm"]["enable_thinking"] = False
    captured = {}

    def fake_post(url, headers, payload, timeout):
        captured["payload"] = payload
        return _response()

    with mock.patch("site_agent.core.llm._http_post", fake_post):
        Client(config, mem, _FAKE_ENV).chat([{"role": "user", "content": "hi"}], json_mode=True)

    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["payload"]["reasoning"] == {"enabled": False}
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    mem.close()


def test_empty_completion_still_logs_provider_usage(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    response = _response(content="")
    response["usage"]["cost"] = 0.000321
    with mock.patch("site_agent.core.llm._http_post", return_value=response):
        with pytest.raises(LLMError, match="empty completion"):
            Client(_config(), mem, _FAKE_ENV).chat([{"role": "user", "content": "hi"}])

    spend = mem.llm_spend()
    assert spend["prompt_tokens"] == 100
    assert spend["completion_tokens"] == 50
    assert spend["cost_usd"] == 0.000321
    mem.close()


def test_budget_guard_uses_configured_prices_for_tokenized_unpriced_calls(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    config = _config()
    config["llm"]["daily_budget_usd"] = 0.00003
    mem.log_llm_cost("test-model", prompt_tokens=10, completion_tokens=5, cost_usd=None)
    client = Client(config, mem, _FAKE_ENV)
    client._check_budget()
    mem.close()


def test_budget_guard_blocks_unmeasurable_unpriced_calls(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    config = _config()
    config["llm"]["daily_budget_usd"] = 1.0
    mem.log_llm_cost("test-model", prompt_tokens=0, completion_tokens=0, cost_usd=None)
    client = Client(config, mem, _FAKE_ENV)
    with mock.patch("site_agent.core.llm._http_post") as never:
        with pytest.raises(LLMError, match="budget cannot be enforced"):
            client.chat([{"role": "user", "content": "hi"}])
    assert never.call_count == 0
    mem.close()


def test_chat_rejects_empty_completion(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    with mock.patch("site_agent.core.llm._http_post", return_value=_response(content="")):
        client = Client(_config(), mem, _FAKE_ENV)
        with pytest.raises(LLMError, match="empty completion"):
            client.chat([{"role": "user", "content": "hi"}])
    mem.close()


def test_chat_retries_on_server_error_then_succeeds(tmp_path):
    responses = [LLMError("llm http 503: busy"), _response(content="recovered")]
    calls = []

    def fake_post(url, headers, payload, timeout):
        result = responses[len(calls)]
        calls.append(1)
        if isinstance(result, Exception):
            raise result
        return result

    with mock.patch("site_agent.core.llm._http_post", fake_post), mock.patch("time.sleep"):
        client = Client(_config(), env=_FAKE_ENV)
        assert client.chat([{"role": "user", "content": "hi"}]) == "recovered"
    assert len(calls) == 2


def test_chat_allows_per_call_timeout_and_retry_overrides():
    calls = []

    def fake_post(url, headers, payload, timeout):
        calls.append((payload, timeout))
        raise LLMError("llm http 503: busy")

    with mock.patch("site_agent.core.llm._http_post", fake_post), mock.patch("time.sleep"):
        client = Client(_config(), env=_FAKE_ENV)
        with pytest.raises(LLMError, match="503"):
            client.chat(
                [{"role": "user", "content": "hi"}],
                max_tokens=700,
                timeout_seconds=3,
                max_retries=0,
            )

    assert calls == [
        ({"model": "test-model", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 700}, 3.0)
    ]


def test_chat_does_not_retry_auth_errors():
    calls = []

    def fake_post(url, headers, payload, timeout):
        calls.append(1)
        raise LLMError("llm http 401: bad key")

    with mock.patch("site_agent.core.llm._http_post", fake_post):
        client = Client(_config(), env=_FAKE_ENV)
        with pytest.raises(LLMError, match="401"):
            client.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1


def test_chat_without_api_key_raises():
    config = _config()
    config["env"]["llm_api_key"] = ""
    client = Client(config)
    with pytest.raises(LLMError, match="not configured"):
        client.chat([{"role": "user", "content": "hi"}])


def test_extract_json_strict():
    from site_agent.core.llm import extract_json
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('   [1, 2]  ') == [1, 2]


def test_extract_json_handles_fenced_and_prose_wrapped():
    from site_agent.core.llm import extract_json
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go:\n{"reply": "ok", "action": {"type": "list_files"}}') == {
        "reply": "ok", "action": {"type": "list_files"}}


def test_extract_json_ignores_objects_in_prose():
    from site_agent.core.llm import extract_json
    # a tiny {a:1}-shaped fragment in prose must not win over the real answer
    assert extract_json('Use the pair {3} and then {"reply": "yes"}') == {"reply": "yes"}


def test_extract_json_repairs_comments_and_trailing_commas():
    from site_agent.core.llm import extract_json
    raw = '{\n  // the answer\n  "a": 1, /* note */\n  "b": [1, 2,],\n}'
    assert extract_json(raw) == {"a": 1, "b": [1, 2]}


def test_extract_json_nested_and_strings_with_braces():
    from site_agent.core.llm import extract_json
    raw = 'pre {"inner": "not real"} {"a": {"b": "}"}, "s": "a}string{ here"} tail'
    assert extract_json(raw) == {"a": {"b": "}"}, "s": "a}string{ here"}


def test_extract_json_returns_none_for_garbage():
    from site_agent.core.llm import extract_json
    assert extract_json("") is None
    assert extract_json("  ") is None
    assert extract_json(123) is None
    assert extract_json("just prose, no json here") is None
    assert extract_json('{"a": trunc') is None


def test_chat_body_includes_enable_thinking_when_requested():
    import site_agent.core.llm as llm_module
    from site_agent.core.llm import Client

    captured_request = {}

    def fake_post(url, headers, payload, timeout):
        captured_request["payload"] = payload
        return {
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    original = llm_module._http_post
    llm_module._http_post = fake_post
    try:
        client = Client({"llm": {"base_url": "https://fake", "model": "m"}}, memory=None)
        client.api_key = "sk-test"
        out = client.chat([{"role": "user", "content": "hi"}], enable_thinking=False, json_mode=False)
        assert out == '{"ok": true}'
        assert captured_request["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
        client.chat([{"role": "user", "content": "hi"}])
        assert "chat_template_kwargs" not in captured_request["payload"]
    finally:
        llm_module._http_post = original
