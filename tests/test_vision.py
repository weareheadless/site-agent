import pytest

from site_agent.core import vision
from site_agent.core.llm import LLMError
from site_agent.core.media_worker import MediaWorker
from site_agent.core.memory import Memory


def test_vision_client_uses_openai_compatible_multimodal_payload(monkeypatch):
    calls = []

    def fake_post(url, headers, payload, timeout):
        calls.append((url, headers, payload, timeout))
        return {"model": "Qwen/Qwen3.8-27B", "choices": [
            {"message": {"content": "focal point: right side"}}
        ]}

    monkeypatch.setattr(vision, "_http_post", fake_post)
    client = vision.VisionClient({
        "vision": {
            "base_url": "https://api.entrim.ai/v1",
            "model": "Qwen/Qwen3.8-27B",
        },
        "env": {"vision_api_key": "ENTRIM_API_KEY"},
    }, env={"ENTRIM_API_KEY": "secret"})

    result = client.analyze("https://example.com/hero.jpg", "Describe this image")

    assert result == "focal point: right side"
    url, headers, payload, timeout = calls[0]
    assert url == "https://api.entrim.ai/v1/chat/completions"
    assert headers["Authorization"] == "Bearer secret"
    assert payload["model"] == "Qwen/Qwen3.8-27B"
    assert payload["messages"][0]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "https://example.com/hero.jpg"},
    }
    assert timeout == 90.0


def test_structured_qwen_aliases_business_information_fields(monkeypatch):
    calls = []
    def fake_post(*args):
        calls.append(args[2])
        return {
        "choices": [{"message": {"content": '{"schema_version":1,"description":"menu","business_information":"No","markdown":""}'}}]
        }
    monkeypatch.setattr(vision, "_http_post", fake_post)
    client = vision.VisionClient({
        "vision": {"base_url": "https://example.test/v1", "model": "qwen"},
        "env": {"vision_api_key": "KEY"},
    }, env={"KEY": "secret"})
    instruction = MediaWorker._instruction()
    result = client.analyze_images(["https://example.test/image.webp"], instruction)
    assert result.knowledge_relevant is False
    assert result.description == "menu"
    assert calls[0]["max_tokens"] == 4096
    assert calls[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert '"knowledge_relevant":false' in instruction
    assert "literal JSON boolean true or false" in instruction
    assert calls[0]["messages"][0]["content"][1]["image_url"]["detail"] == "low"


def test_vision_client_logs_provider_cost_and_requests_usage_receipt(monkeypatch, tmp_path):
    memory = Memory(tmp_path / "memory.db")
    calls = []

    def fake_post(*args):
        calls.append(args[2])
        return {
            "model": "qwen-vision",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.0042},
            "choices": [{"message": {"content": '{"schema_version":1,"description":"hero","tags":[],"alt_text":"hero","orientation":"landscape","dominant_colors":[],"suggested_uses":["hero"],"quality_notes":[],"ocr_text":"","knowledge_relevant":false,"proposed_knowledge_markdown":""}'}}],
        }

    monkeypatch.setattr(vision, "_http_post", fake_post)
    client = vision.VisionClient({
        "vision": {
            "base_url": "https://openrouter.ai/api/v1",
            "model": "qwen-vision",
        },
        "env": {"vision_api_key": "KEY"},
    }, env={"KEY": "secret"}, memory=memory)

    result = client.analyze_images(["https://example.test/image.webp"], MediaWorker._instruction())

    assert result.description == "hero"
    assert calls[0]["usage"] == {"include": True}
    assert memory.llm_spend()["cost_usd"] == 0.0042
    memory.close()


def test_structured_analysis_schema_failures_are_not_retryable(monkeypatch):
    def fake_post(*args):
        return {"choices": [{"message": {"content": '{"knowledge_relevant":"maybe"}'}}]}

    monkeypatch.setattr(vision, "_http_post", fake_post)
    client = vision.VisionClient({
        "vision": {"base_url": "https://example.test/v1", "model": "qwen"},
        "env": {"vision_api_key": "KEY"},
    }, env={"KEY": "secret"})

    with pytest.raises(LLMError) as caught:
        client.analyze_images(["https://example.test/image.webp"], "return JSON")
    assert caught.value.code == "invalid_structured_analysis"
    assert caught.value.retryable is False


def test_site_image_context_analyzes_public_img_sources(monkeypatch, tmp_path):
    clone = tmp_path / "site"
    clone.mkdir()
    (clone / "index.html").write_text(
        '<img src="images/hero.jpg"><img src="data:image/png;base64,skip">'
    )
    (clone / "styles.css").write_text(
        ".hero{background-image:url('images/course.webp')} .noise{background:url(data:image/png;base64,skip)}"
    )
    calls = []

    class FakeVision:
        def __init__(self, config):
            pass

        def analyze(self, url, instruction):
            calls.append((url, instruction))
            return "subject: diver; text-safe space: left"

    monkeypatch.setattr(vision, "VisionClient", FakeVision)
    result = vision.site_image_context({
        "vision": {"enabled": True, "max_images": 6},
        "site": {"preview_url": "https://oceanicvibes.com/"},
    }, clone)

    assert "Image art direction" in result
    assert "https://oceanicvibes.com/images/hero.jpg" in result
    assert len(calls) == 2
    assert {call[0] for call in calls} == {
        "https://oceanicvibes.com/images/hero.jpg",
        "https://oceanicvibes.com/images/course.webp",
    }


def test_site_image_context_is_disabled_without_public_preview_url(tmp_path):
    clone = tmp_path / "site"
    clone.mkdir()
    (clone / "index.html").write_text('<img src="images/hero.jpg">')
    assert vision.site_image_context({"vision": {"enabled": True}}, clone) == ""
