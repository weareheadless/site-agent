import json
import io

from site_agent.hands import design_visual_review


def test_visual_review_batches_route_evidence_to_avoid_six_image_timeout(monkeypatch):
    calls = []

    def fake_image_data(path):
        return "data:image/jpeg;base64,AA==", str(path)

    def fake_post(url, headers, payload, timeout):
        image_count = sum(
            1 for item in payload["messages"][1]["content"] if item.get("type") == "image_url"
        )
        calls.append({"url": url, "payload": payload, "timeout": timeout})
        assert image_count <= 3
        assert payload["reasoning"] == {"enabled": False}
        return {
            "choices": [{"message": {"content": json.dumps({
                "state": "passed",
                "findings": [],
                "strengths": [f"batch-{image_count}"],
                "generic_template_signals": [],
                "repair_plan": [],
            })}}]
        }

    monkeypatch.setattr(design_visual_review, "_image_data", fake_image_data)
    monkeypatch.setattr(design_visual_review, "_http_post", fake_post)
    screenshots = [
        {
            "route": route,
            "viewport": {"name": viewport, "width": 390, "height": 844},
            "screenshot_path": f"{route}-{viewport}.png",
            "screenshot_hash": f"{route}-{viewport}",
        }
        for route in ("index.html", "articles.html")
        for viewport in ("desktop", "tablet", "mobile")
    ]

    result = design_visual_review.review_design_screenshots(
        {
            "env": {"vision_api_key": "VISION_KEY"},
            "design_engine": {
                "visual_review": {
                    "base_url": "https://api.example.test/v1",
                    "model": "Qwen/Qwen3.8-27B",
                    "api_key_env": "VISION_KEY",
                    "timeout_seconds": 120,
                    "max_tokens": 1024,
                }
            },
        },
        run_id="visual-batch",
        candidate_sha="a" * 40,
        brief={"purpose": "Review the candidate."},
        screenshots=screenshots,
        env={"VISION_KEY": "secret"},
    )

    assert result.state == "passed"
    assert len(calls) == 2
    assert sorted(
        sum(1 for item in call["payload"]["messages"][1]["content"] if item.get("type") == "image_url")
        for call in calls
    ) == [3, 3]
    assert all(call["payload"]["max_tokens"] == 1024 for call in calls)
    assert len(result.screenshot_evidence) == 6
    assert len(result.extra["review_batches"]) == 2


def test_visual_review_compresses_a_large_valid_screenshot_before_size_guard():
    from PIL import Image

    source = io.BytesIO()
    Image.new("RGB", (2_500, 2_500), (24, 48, 40)).save(source, format="BMP")
    raw = source.getvalue()

    assert len(raw) > 4_000_000
    data_url, label = design_visual_review._encoded_image_data(
        raw,
        content_type="image/bmp",
        label="large-owner-preview.bmp",
    )

    assert label == "large-owner-preview.bmp"
    assert data_url.startswith("data:image/jpeg;base64,")


def test_visual_review_receives_grounding_and_approved_source_images(monkeypatch):
    calls = []

    def fake_image_data(path):
        return "data:image/jpeg;base64,AA==", str(path)

    def fake_post(url, headers, payload, timeout):
        calls.append(payload)
        content = payload["messages"][1]["content"]
        assert any(
            item.get("type") == "text" and "GROUNDED SOURCE AND RUNTIME EVIDENCE" in item.get("text", "")
            for item in content
        )
        assert sum(1 for item in content if item.get("type") == "image_url") == 3
        assert all(
            item["image_url"]["detail"] == "high"
            for item in content
            if item.get("type") == "image_url"
        )
        assert any(
            item.get("type") == "text" and "APPROVED OWNER SOURCE IMAGE" in item.get("text", "")
            for item in content
        )
        return {
            "choices": [{"message": {"content": json.dumps({
                "state": "passed",
                "findings": [],
                "strengths": ["grounded"],
                "generic_template_signals": [],
                "repair_plan": [],
            })}}]
        }

    monkeypatch.setattr(design_visual_review, "_image_data", fake_image_data)
    monkeypatch.setattr(design_visual_review, "_http_post", fake_post)
    result = design_visual_review.review_design_screenshots(
        {
            "env": {"vision_api_key": "VISION_KEY"},
            "design_engine": {
                "visual_review": {
                    "base_url": "https://api.example.test/v1",
                    "model": "Qwen/Qwen3.8-27B",
                    "api_key_env": "VISION_KEY",
                }
            },
        },
        run_id="visual-grounding",
        candidate_sha="a" * 40,
        brief={"purpose": "Review the candidate."},
        screenshots=[{
            "route": "index.html",
            "viewport": {"name": "desktop", "width": 1440, "height": 1000},
            "screenshot_path": "candidate.png",
            "screenshot_hash": "candidate",
        }],
        review_evidence={
            "source_inventory": {"changed_source_files": ["src/app/page.tsx"]},
            "runtime": {"motion": {"status": "passed"}},
        },
        source_images=[
            {"path": "logo.webp", "relative_path": "public/images/logo.webp", "sha256": "b" * 64, "kind": "owner_media"},
            {"path": "hero.webp", "relative_path": "public/images/hero.webp", "sha256": "c" * 64, "kind": "owner_media"},
        ],
        env={"VISION_KEY": "secret"},
    )

    assert result.state == "passed"
    assert result.extra["grounding"]["source_image_count"] == 2
    assert result.extra["grounding"]["review_evidence_hash"]
    assert result.extra["review_batches"][0]["source_image_count"] == 2
    assert len(calls) == 1


def test_visual_review_does_not_pass_with_missing_declared_source_media(monkeypatch):
    def fake_image_data(path):
        return "data:image/jpeg;base64,AA==", str(path)

    def fake_post(url, headers, payload, timeout):
        return {
            "choices": [{"message": {"content": json.dumps({
                "state": "passed",
                "findings": [],
                "strengths": [],
                "generic_template_signals": [],
                "repair_plan": [],
            })}}]
        }

    monkeypatch.setattr(design_visual_review, "_image_data", fake_image_data)
    monkeypatch.setattr(design_visual_review, "_http_post", fake_post)
    result = design_visual_review.review_design_screenshots(
        {
            "env": {"vision_api_key": "VISION_KEY"},
            "design_engine": {
                "visual_review": {
                    "base_url": "https://api.example.test/v1",
                    "model": "Qwen/Qwen3.8-27B",
                    "api_key_env": "VISION_KEY",
                }
            },
        },
        run_id="visual-missing-source",
        candidate_sha="a" * 40,
        brief={"purpose": "Review the candidate."},
        screenshots=[{
            "route": "index.html",
            "viewport": {"name": "desktop", "width": 1440, "height": 1000},
            "screenshot_path": "candidate.png",
            "screenshot_hash": "candidate",
        }],
        review_evidence={
            "source_media": {
                "missing_files": [{
                    "relative_path": "public/images/owner.webp",
                    "error": "source media unavailable",
                }]
            }
        },
        env={"VISION_KEY": "secret"},
    )

    assert result.state == "inconclusive"
    assert result.extra["grounding"]["source_image_errors"] == [{
        "path": "public/images/owner.webp",
        "error": "source media unavailable",
    }]


def test_visual_review_retries_a_flaky_batch_once_before_inconclusive(monkeypatch):
    calls = []

    def fake_image_data(path):
        return "data:image/jpeg;base64,AA==", str(path)

    def fake_post(url, headers, payload, timeout):
        calls.append({"url": url})
        if len(calls) == 1:
            raise RuntimeError("visual review did not return a JSON object")
        return {
            "choices": [{"message": {"content": json.dumps({
                "state": "passed",
                "findings": [],
                "strengths": ["retried"],
                "generic_template_signals": [],
                "repair_plan": [],
            })}}]
        }

    monkeypatch.setattr(design_visual_review, "_image_data", fake_image_data)
    monkeypatch.setattr(design_visual_review, "_http_post", fake_post)
    screenshots = [
        {
            "route": "index.html",
            "viewport": {"name": viewport, "width": 390, "height": 844},
            "screenshot_path": f"index-{viewport}.png",
            "screenshot_hash": f"index-{viewport}",
        }
        for viewport in ("desktop", "tablet", "mobile")
    ]

    result = design_visual_review.review_design_screenshots(
        {
            "env": {"vision_api_key": "VISION_KEY"},
            "design_engine": {
                "visual_review": {
                    "base_url": "https://api.example.test/v1",
                    "model": "Qwen/Qwen3.8-27B",
                    "api_key_env": "VISION_KEY",
                    "timeout_seconds": 120,
                    "max_tokens": 1024,
                }
            },
        },
        run_id="visual-retry",
        candidate_sha="a" * 40,
        brief={"purpose": "Review the candidate."},
        screenshots=screenshots,
        env={"VISION_KEY": "secret"},
    )

    assert result.state == "passed"
    assert len(calls) == 2


def test_visual_review_accepts_json_returned_in_provider_reasoning(monkeypatch):
    def fake_image_data(path):
        return "data:image/jpeg;base64,AA==", str(path)

    def fake_post(url, headers, payload, timeout):
        return {
            "choices": [{"message": {
                "content": None,
                "reasoning": json.dumps({
                    "state": "passed",
                    "findings": [],
                    "strengths": ["reasoning fallback"],
                    "generic_template_signals": [],
                    "repair_plan": [],
                }),
            }}]
        }

    monkeypatch.setattr(design_visual_review, "_image_data", fake_image_data)
    monkeypatch.setattr(design_visual_review, "_http_post", fake_post)
    result = design_visual_review.review_design_screenshots(
        {
            "env": {"vision_api_key": "VISION_KEY"},
            "design_engine": {
                "visual_review": {
                    "base_url": "https://api.example.test/v1",
                    "model": "Qwen/Qwen3.8-27B",
                    "api_key_env": "VISION_KEY",
                    "timeout_seconds": 120,
                    "max_tokens": 1024,
                }
            },
        },
        run_id="visual-reasoning-fallback",
        candidate_sha="a" * 40,
        brief={"purpose": "Review the candidate."},
        screenshots=[{
            "route": "index.html",
            "viewport": {"name": "desktop", "width": 1440, "height": 1000},
            "screenshot_path": "index-desktop.png",
            "screenshot_hash": "index-desktop",
        }],
        env={"VISION_KEY": "secret"},
    )

    assert result.state == "passed"
    assert list(result.strengths) == ["reasoning fallback"]


def test_visual_review_reprompts_when_provider_omits_required_state(monkeypatch):
    calls = []

    def fake_image_data(path):
        return "data:image/jpeg;base64,AA==", str(path)

    def fake_post(url, headers, payload, timeout):
        calls.append(payload)
        if len(calls) == 1:
            return {
                "choices": [{"message": {"content": json.dumps({
                    "review": "A prose-only review without the contract state.",
                    "findings": [],
                    "repair_plan": [],
                })}}]
            }
        prompt = payload["messages"][1]["content"][0]["text"]
        assert "STRUCTURED OUTPUT RETRY" in prompt
        assert "Emit state even when the arrays are empty" in prompt
        return {
            "choices": [{"message": {"content": json.dumps({
                "state": "passed",
                "findings": [],
                "strengths": ["The contract was followed on retry."],
                "generic_template_signals": [],
                "repair_plan": [],
            })}}]
        }

    monkeypatch.setattr(design_visual_review, "_image_data", fake_image_data)
    monkeypatch.setattr(design_visual_review, "_http_post", fake_post)
    result = design_visual_review.review_design_screenshots(
        {
            "env": {"vision_api_key": "VISION_KEY"},
            "design_engine": {
                "visual_review": {
                    "base_url": "https://api.example.test/v1",
                    "model": "Qwen/Qwen3.8-27B",
                    "api_key_env": "VISION_KEY",
                    "timeout_seconds": 120,
                    "max_tokens": 1024,
                }
            },
        },
        run_id="visual-missing-state",
        candidate_sha="a" * 40,
        brief={"purpose": "Review the candidate."},
        screenshots=[{
            "route": "index.html",
            "viewport": {"name": "desktop", "width": 1440, "height": 1000},
            "screenshot_path": "index-desktop.png",
            "screenshot_hash": "index-desktop",
        }],
        env={"VISION_KEY": "secret"},
    )

    assert result.state == "passed"
    assert len(calls) == 2


def test_visual_review_bounds_oversized_provider_findings(monkeypatch):
    def fake_image_data(path):
        return "data:image/jpeg;base64,AA==", str(path)

    def fake_post(url, headers, payload, timeout):
        return {
            "choices": [{"message": {"content": json.dumps({
                "state": "passed",
                "findings": [{"message": "x" * 500_000}],
                "strengths": ["grounded"],
                "generic_template_signals": [],
                "repair_plan": [],
            })}}]
        }

    monkeypatch.setattr(design_visual_review, "_image_data", fake_image_data)
    monkeypatch.setattr(design_visual_review, "_http_post", fake_post)
    result = design_visual_review.review_design_screenshots(
        {
            "env": {"vision_api_key": "VISION_KEY"},
            "design_engine": {
                "visual_review": {
                    "base_url": "https://api.example.test/v1",
                    "model": "Qwen/Qwen3.8-27B",
                    "api_key_env": "VISION_KEY",
                }
            },
        },
        run_id="visual-bounded",
        candidate_sha="a" * 40,
        brief={"purpose": "Review the candidate."},
        screenshots=[{
            "route": "index.html",
            "viewport": {"name": "desktop", "width": 1440, "height": 1000},
            "screenshot_path": "candidate.png",
            "screenshot_hash": "candidate",
        }],
        review_evidence={"runtime": {"scroll_states": ["x" * 500_000]}},
        env={"VISION_KEY": "secret"},
    )

    assert result.state == "passed"
    assert len(result.findings[0]["message"]) == 600


def test_visual_review_is_inconclusive_after_finite_retries(monkeypatch):
    calls = []

    def fake_image_data(path):
        return "data:image/jpeg;base64,AA==", str(path)

    def fake_post(url, headers, payload, timeout):
        calls.append({"url": url})
        raise RuntimeError("visual review did not return a JSON object")

    monkeypatch.setattr(design_visual_review, "_image_data", fake_image_data)
    monkeypatch.setattr(design_visual_review, "_http_post", fake_post)
    screenshots = [
        {
            "route": "index.html",
            "viewport": {"name": "desktop", "width": 390, "height": 844},
            "screenshot_path": "index-desktop.png",
            "screenshot_hash": "index-desktop",
        }
    ]

    result = design_visual_review.review_design_screenshots(
        {
            "env": {"vision_api_key": "VISION_KEY"},
            "design_engine": {
                "visual_review": {
                    "base_url": "https://api.example.test/v1",
                    "model": "Qwen/Qwen3.8-27B",
                    "api_key_env": "VISION_KEY",
                    "timeout_seconds": 120,
                    "max_tokens": 1024,
                }
            },
        },
        run_id="visual-retry-fail",
        candidate_sha="a" * 40,
        brief={"purpose": "Review the candidate."},
        screenshots=screenshots,
        env={"VISION_KEY": "secret"},
    )

    assert result.state == "inconclusive"
    assert len(calls) == 2
    assert result.findings[0]["severity"] == "incomplete"
