from pathlib import Path

from site_agent.hands.playwright_quality import _interaction_metrics


class _Control:
    def __init__(self, page):
        self.page = page

    def click(self, timeout=None):
        self.page.clicked = True


class _Controls:
    def __init__(self, page):
        self.page = page

    def count(self):
        return 1

    def nth(self, _index):
        return _Control(self.page)


class _Page:
    def __init__(self):
        self.clicked = False
        self.screenshots = []

    def locator(self, _selector):
        return _Controls(self)

    def evaluate(self, script):
        if "expanded" in script:
            return {
                "expanded": ["true" if self.clicked else "false"],
                "dialogs": 1 if self.clicked else 0,
                "details": [],
                "active": "button" if self.clicked else "body",
            }
        if "signature_behaviors" in script:
            return {"signature_behaviors": []}
        raise AssertionError("unexpected evaluation")

    def wait_for_timeout(self, _milliseconds):
        return None

    def screenshot(self, *, path, full_page):
        assert full_page is True
        Path(path).write_bytes(b"after" if self.clicked else b"before")
        self.screenshots.append(path)


def test_interaction_probe_compares_visual_state_before_and_after(tmp_path):
    page = _Page()

    result = _interaction_metrics(
        page,
        before_screenshot=tmp_path / "before.png",
        after_screenshot=tmp_path / "after.png",
    )

    assert result["attempted"] == 1
    assert result["state_changed"] is True
    assert result["visual"]["changed"] is True
    assert result["visual"]["before_screenshot_hash"] != result["visual"]["after_screenshot_hash"]
