from pathlib import Path

from PIL import Image

from site_agent.hands.playwright_quality import (
    PlaywrightQualityAdapter,
    _OwnerFrameSurface,
    PlaywrightQualityAdapter,
    _hidden_resting_text,
    _interaction_metrics,
    _keyboard_metrics,
    _mark_observed_journey_transitions,
    _observable_delta,
    _observed_signature_behaviors,
)


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


def test_scroll_probe_observes_a_locked_behavior_whose_fingerprint_changed():
    initial = [{"id": "behavior-dive-lamp", "state": "unobserved", "fingerprint": "resting"}]
    snapshots = [
        {"position": 0, "signature_behaviors": [{"id": "behavior-dive-lamp", "state": "unobserved", "fingerprint": "resting"}]},
        {"position": 400, "signature_behaviors": [{"id": "behavior-dive-lamp", "state": "unobserved", "fingerprint": "moved"}]},
    ]

    observed = _observed_signature_behaviors(initial, snapshots)

    assert observed == [{
        "id": "behavior-dive-lamp",
        "state": "observed",
        "fingerprint": "moved",
        "observed_via": "scroll",
    }]


def test_scroll_probe_leaves_an_unchanged_behavior_unobserved():
    initial = [{"id": "behavior-static", "state": "unobserved", "fingerprint": "same"}]
    snapshots = [
        {"position": 400, "signature_behaviors": [{"id": "behavior-static", "state": "unobserved", "fingerprint": "same"}]},
    ]

    assert _observed_signature_behaviors(initial, snapshots) == []


def test_scroll_probe_does_not_accept_a_candidate_observed_claim():
    snapshots = [
        {"position": 400, "signature_behaviors": [{"id": "behavior-x", "state": "observed", "fingerprint": "same"}]},
    ]

    assert _observed_signature_behaviors([], snapshots) == []


def test_scroll_probe_does_not_accept_an_offscreen_signature_loop():
    initial = [{
        "id": "behavior-dive-lamp",
        "state": "unobserved",
        "trigger": "scroll",
        "visible": False,
        "fingerprint": "resting",
    }]
    snapshots = [{
        "position": 400,
        "signature_behaviors": [{
            "id": "behavior-dive-lamp",
            "state": "rendered",
            "trigger": "scroll",
            "visible": False,
            "fingerprint": "looped-offscreen",
        }],
    }]

    assert _observed_signature_behaviors(initial, snapshots) == []


def test_journey_transition_requires_a_rendered_change_not_a_candidate_claim():
    before = [{
        "condition_id": "scene-arrival",
        "visible": True,
        "state": "rendered",
        "completion": "",
        "rendered_fingerprint": {"text": "Arrival", "opacity": "1"},
    }]
    after = [{
        **before[0],
        "state": "completed",
        "completion": "arrival complete",
    }]

    observed = _mark_observed_journey_transitions(before, after)

    assert observed[0]["observed_transition"] is False


def test_journey_transition_ignores_viewport_relative_scroll_geometry():
    before = [{
        "condition_id": "scene-proof",
        "visible": True,
        "rendered_fingerprint": {
            "box": {"x": 24, "y": 800, "width": 400, "height": 120},
            "transform": "none",
            "opacity": "1",
        },
    }]
    after = [{
        **before[0],
        "rendered_fingerprint": {
            "box": {"x": 24, "y": 120, "width": 400, "height": 120},
            "transform": "none",
            "opacity": "1",
        },
    }]

    assert _mark_observed_journey_transitions(before, after)[0]["observed_transition"] is False


def test_hidden_resting_text_returns_meaningful_invisible_elements():
    class Page:
        def evaluate(self, script):
            assert "effectivelyHidden" in script
            return [{"tag": "h1", "text": "Hidden headline"}]

    assert _hidden_resting_text(Page()) == [{"tag": "h1", "text": "Hidden headline"}]


def test_observable_delta_uses_rendered_geometry_not_animation_engine_state():
    samples = [
        {"nodes": [{"key": "hero", "tag": "h1", "visible": True, "fingerprint": {"box": {"x": 0}}}], "signature_behaviors": []},
        {"nodes": [{"key": "hero", "tag": "h1", "visible": True, "fingerprint": {"box": {"x": 24}}}], "signature_behaviors": []},
    ]

    result = _observable_delta(samples)

    assert result["observed"] is True
    assert result["changed_nodes"][0]["key"] == "hero"


def test_observable_delta_ignores_signature_position_changes_during_scroll():
    samples = [
        {
            "nodes": [],
            "signature_behaviors": [
                {"id": "alignment-rule", "fingerprint": {"box": {"x": 0, "y": 100, "width": 200, "height": 24}, "transform": "none"}}
            ],
        },
        {
            "nodes": [],
            "signature_behaviors": [
                {"id": "alignment-rule", "fingerprint": {"box": {"x": 0, "y": -300, "width": 200, "height": 24}, "transform": "none"}}
            ],
        },
    ]

    assert _observable_delta(samples, ignore_scroll_position=True) == {
        "observed": False,
        "changed_nodes": [],
        "signature_behaviors": [],
        "sample_count": 2,
    }


def test_observable_delta_observes_signature_descendant_render_change():
    samples = [
        {
            "nodes": [],
            "signature_behaviors": [{
                "id": "alignment-rule",
                "fingerprint": {
                    "box": {"x": 0, "y": 100, "width": 200, "height": 24},
                    "transform": "none",
                    "descendants": [{"transform": "matrix(1, 0, 0, 1, -5, -30)", "opacity": "1"}],
                },
            }],
        },
        {
            "nodes": [],
            "signature_behaviors": [{
                "id": "alignment-rule",
                "fingerprint": {
                    "box": {"x": 0, "y": -300, "width": 200, "height": 24},
                    "transform": "none",
                    "descendants": [{"transform": "none", "opacity": "1"}],
                },
            }],
        },
    ]

    result = _observable_delta(samples, ignore_scroll_position=True)

    assert result["observed"] is True
    assert result["signature_behaviors"][0]["id"] == "alignment-rule"


def test_owner_frame_waits_for_preview_navigation_before_returning():
    class Frame:
        def __init__(self):
            self._url_reads = 0

        @property
        def url(self):
            self._url_reads += 1
            return "about:blank" if self._url_reads == 1 else "http://127.0.0.1:4314/api/review/candidate/index.html"

        def wait_for_selector(self, _selector, *, state, timeout):
            assert state == "attached"

        def wait_for_load_state(self, state, *, timeout):
            assert state == "domcontentloaded"

    class Handle:
        def __init__(self, frame):
            self.frame = frame

        def content_frame(self):
            return self.frame

    class Iframe:
        def __init__(self, handle):
            self.handle = handle

        def wait_for(self, *, state, timeout):
            assert state == "visible"

        def element_handle(self):
            return self.handle

    class Page:
        def __init__(self):
            self.frame = Frame()
            self.iframe = Iframe(Handle(self.frame))

        def locator(self, selector):
            assert selector == "#preview-iframe"
            return self.iframe

        @property
        def frames(self):
            return [self.frame]

        def wait_for_timeout(self, _milliseconds):
            return None

    surface = PlaywrightQualityAdapter._owner_frame(Page())

    assert surface._frame.url.endswith("/index.html")


def test_owner_viewport_selects_the_matching_owner_surface_control():
    class Control:
        def __init__(self):
            self.waited = None
            self.clicked = False

        def wait_for(self, *, state, timeout):
            self.waited = (state, timeout)

        def click(self):
            self.clicked = True

    class Page:
        def __init__(self):
            self.control = Control()
            self.selector = None

        def locator(self, selector):
            self.selector = selector
            return self.control

        def wait_for_timeout(self, milliseconds):
            assert milliseconds == 100

    page = Page()

    PlaywrightQualityAdapter._select_owner_viewport(page, "tablet")

    assert page.selector == '#viewport-controls button[data-viewport="ipad"]'
    assert page.control.waited == ("visible", 30_000)
    assert page.control.clicked is True


def test_owner_frame_screenshot_does_not_resize_the_owner_viewport(tmp_path):
    class Frame:
        pass

    class Iframe:
        def __init__(self):
            self.screenshot_path = None

        def screenshot(self, *, path):
            self.screenshot_path = path
            Image.new("RGB", (320, 844), (24, 24, 24)).save(path)

    class Shell:
        def __init__(self):
            self.iframe = Iframe()

        def locator(self, selector):
            assert selector == "#preview-iframe"
            return self.iframe

    frame = Frame()
    shell = Shell()
    output = tmp_path / "owner-viewport.png"

    _OwnerFrameSurface(shell, frame).screenshot(path=output, full_page=True)

    assert Image.open(output).size == (320, 844)
    assert shell.iframe.screenshot_path == str(output)


def test_keyboard_probe_sends_tab_through_the_rendered_document():
    class Focusable:
        def __init__(self):
            self.pressed = []

        def press(self, key):
            self.pressed.append(key)

    class Focusables:
        def __init__(self):
            self.first = Focusable()

        def count(self):
            return 2

    class Page:
        def __init__(self):
            self.focusables = Focusables()

        def locator(self, _selector):
            return self.focusables

        def evaluate(self, _script):
            return {"focusable_count": 2, "focus_visible": True, "active_tag": "a"}

    page = Page()

    assert _keyboard_metrics(page)["focus_visible"] is True
    assert page.focusables.first.pressed == ["Tab"]
