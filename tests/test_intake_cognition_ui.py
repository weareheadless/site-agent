from pathlib import Path


HTML = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()


def test_owner_workspace_has_phase_preview_trace_and_decision_surfaces():
    assert 'id="phase-pill"' in HTML
    assert 'id="preview-frame"' in HTML
    assert 'id="trace-list"' in HTML
    assert 'id="confirm-brief"' in HTML
    assert 'id="provision"' in HTML
    assert 'aria-live="polite"' in HTML


def test_boot_uses_the_default_incubation_and_durable_workspace_projection():
    assert 'api("/incubations/default")' in HTML
    assert 'api(idPath("/workspace"))' in HTML
    assert 'localStorage.setItem("ada_incubation_id", state.incubationId)' in HTML
    assert "state.workspace = await api" in HTML
    assert "renderPhase();" in HTML
    assert "await loadPreview();" in HTML


def test_new_conversation_is_explicit_and_does_not_clear_the_server_record():
    assert 'id="new-chat" class="new-chat" type="button"' in HTML
    assert "async function newConversation()" in HTML
    assert 'api("/incubations", { method: "POST"' in HTML
    assert 'localStorage.setItem("ada_incubation_id", state.incubationId)' in HTML


def test_chat_uses_durable_jobs_and_refreshes_after_completion():
    assert "async function pollJob()" in HTML
    assert "idPath(`/chat/jobs/${encodeURIComponent(state.jobId)}`)" in HTML
    assert '["done", "error"].includes(state.job.status)' in HTML
    assert "state.jobId = null" in HTML
    assert "await refresh();" in HTML
    assert "const result = await api(idPath(\"/messages\")" in HTML


def test_preview_prefers_the_validated_candidate_over_a_live_checkpoint():
    assert 'if (workspace.candidate)' in HTML
    assert "if (workspace.live_build && workspace.live_build.snapshot)" in HTML
    assert HTML.index('if (workspace.candidate)') < HTML.index('if (workspace.live_build && workspace.live_build.snapshot)')
    assert 'variant: "live"' in HTML
    assert 'variant: "candidate"' in HTML
    assert "preview-token?variant=${target.variant}" in HTML
    assert "/preview/${target.variant}/${parts}" in HTML


def test_confirmation_and_provisioning_are_separate_owner_actions():
    assert 'api(idPath("/confirm-intake")' in HTML
    assert 'api(idPath("/builds")' in HTML
    assert 'api(idPath("/provision")' in HTML
    assert "Provision this exact website candidate?" in HTML
    assert "candidate.run_id" in HTML
    assert "candidate.candidate_sha" in HTML


def test_reduced_motion_is_supported_without_a_neural_or_cognition_layer():
    assert "prefers-reduced-motion" in HTML
    assert "ada-mind" not in HTML
    assert "neural" not in HTML.lower()
    assert "gsap" not in HTML.lower()
    assert "canvas" not in HTML.lower()
