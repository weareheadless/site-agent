from site_agent.core import vision


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
