from pathlib import Path


HTML = Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html"


def test_intake_lab_uses_the_owner_workspace_shell_and_viewport_controls():
    html = HTML.read_text()

    assert 'class="workspace"' in html
    assert 'class="ada-rail"' in html
    assert 'id="preview-frame"' in html
    assert 'data-viewport="desktop"' in html
    assert 'data-viewport="ipad"' in html
    assert 'data-viewport="mobile"' in html
    assert "--bg: #f6f8f4" in html
    assert '"Manrope"' in html
    assert '"Cormorant Garamond"' in html
    assert '"DM Mono"' in html


def test_intake_lab_exposes_the_main_thinking_window_and_one_provision_handoff():
    html = HTML.read_text()

    assert 'id="trace-list"' in html
    assert 'id="thinking-window"' in html
    assert 'id="thinking-heading"' in html
    assert 'class="thinking-window"' in html
    assert 'id="stage-eyebrow"' in html
    assert 'id="trace-status"' in html
    assert 'class="trace-section"' not in html
    assert "RESEARCH" in html
    assert "AUDIENCE" in html
    assert "DESIGN" in html
    assert 'aria-live="polite"' in html
    assert 'id="confirm-brief"' in html
    assert '>Provision website<' in html
    assert 'id="provision"' in html
    assert 'id="activate"' not in html
    assert 'Accept candidate' not in html


def test_intake_lab_replaces_the_thinking_window_with_the_staged_preview():
    html = HTML.read_text()

    assert 'const previewPhases = new Set(["building", "ready", "modifying", "provisioning", "managed"])' in html
    assert 'const previewMode = Boolean(workspace.candidate) || previewPhases.has(phase)' in html
    assert 'document.body.dataset.stage = previewMode ? "preview" : "thinking"' in html
    assert '$("#thinking-window").hidden = previewMode' in html
    assert '$("#preview-frame").hidden = !previewMode' in html
    assert '$("#viewport-controls").hidden = !previewMode' in html


def test_intake_lab_can_open_a_persisted_incubation_from_a_shareable_review_url():
    html = HTML.read_text()

    assert 'new URLSearchParams(window.location.search).get("incubation_id")' in html
    assert 'api(`/incubations/${encodeURIComponent(requestedIncubationId)}`)' in html
    assert 'window.history.replaceState(null, "", window.location.pathname)' in html
    assert 'api("/incubations/default")' in html


def test_intake_lab_uses_scoped_live_and_candidate_preview_variants():
    html = HTML.read_text()

    assert "preview-token?variant=${target.variant}" in html
    assert "/preview/${target.variant}/${parts}" in html
    assert "live_build" in html
    assert "live_preview" in html
    assert 'variant: "candidate"' in html
    assert "Stable candidate" in html


def test_intake_lab_can_pin_the_owner_surface_to_the_run_under_validation():
    html = HTML.read_text()

    assert 'state.previewRunId = String(query.get("preview_run_id") || "").trim()' in html
    assert 'state.previewVariant = String(query.get("preview_variant") || "candidate")' in html
    assert 'if (state.previewRunId)' in html
    assert 'runId: state.previewRunId' in html


def test_intake_lab_keeps_validation_pinned_previews_quiescent():
    html = HTML.read_text()

    assert 'if (!state.previewRunId) {' in html
    assert 'state.refreshTimer = window.setInterval(refresh, 1800)' in html
    assert 'state.jobTimer = window.setInterval(pollJob, 900)' in html


def test_intake_lab_explains_the_scroll_journey_and_reduced_motion_state():
    html = HTML.read_text()

    assert 'id="preview-motion-note"' in html
    assert "Scroll inside the preview to follow the light." in html
    assert "Motion is held static by your reduced-motion preference." in html
    assert 'matchMedia("(prefers-reduced-motion: reduce)")' in html


def test_intake_lab_chat_polls_durable_jobs_and_keeps_attachments():
    html = HTML.read_text()

    assert "/chat/jobs/" in html
    assert 'state.job.status' in html
    assert '["done", "error"].includes(state.job.status)' in html
    assert 'id="upload"' in html
    assert 'idPath("/media")' in html
    assert 'attachments: state.attachments.map' in html
    assert 'event.shiftKey' in html


def test_intake_lab_respects_reduced_motion_without_decorative_animation():
    html = HTML.read_text()

    assert "prefers-reduced-motion" in html
    assert "canvas" not in html.lower()
    assert "gsap" not in html.lower()
    assert "@keyframes" not in html
    assert "animation:" not in html


def test_intake_lab_hides_pipeline_vocabulary_from_the_owner_surface():
    html = HTML.read_text().lower()

    assert "ada's mind" not in html
    assert "neural" not in html
    assert "visual review" not in html
    assert "visual refinement" not in html
    assert "small improvements" not in html
    assert "redesign direction" not in html
    assert "provider" not in html
    assert "model" not in html
    assert "quality gate" not in html
