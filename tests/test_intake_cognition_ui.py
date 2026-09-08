from pathlib import Path

HTML = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()


def test_ada_mind_cognition_panel_and_ticker_exist():
    assert 'id="ada-mind"' in HTML
    assert 'id="ada-mind-toggle"' in HTML
    assert 'id="ada-ticker"' in HTML
    assert 'aria-controls="ada-mind"' in HTML
    assert ".mind-line" in HTML
    assert ".mind-channel-head" in HTML
    assert "#ada-mind-toggle" in HTML


def test_build_launch_morphs_neurons_into_the_review_window():
    assert "playBuildMorph" in HTML
    assert "the neuron field funnels into the review window" in HTML
    assert "#morph { position: fixed; inset: 0; z-index: 59; pointer-events: none; }" in HTML
    assert ".preview[data-ignite]" in HTML
    assert "@keyframes preview-ignite" in HTML
    assert 'setExperienceView("build"); playBuildMorph();' in HTML
    assert "ensurePreviewFill(preview, \"working\")" in HTML
    assert "preview.querySelector(\".preview-fill\")" in HTML
    assert "liveAtoms.slice(0, 120)" in HTML


def test_failed_candidate_can_be_retried_from_the_review_window():
    assert "Retry candidate" in HTML
    assert "confirm.textContent = buildFailed ? \"Retry candidate\"" in HTML
    assert "[\"failed\", \"interrupted\", \"cancelled\", \"incomplete\", \"needs_repair\"].includes(state.run.status)" in HTML
    assert "retry.addEventListener('click', () => confirmBuild())" in HTML
    assert "The last candidate failed. Start a fresh one when ready." in HTML


def test_ui_reconnects_to_an_inflight_build_after_page_load():
    assert "const connectRun" in HTML
    assert "state.session && state.session.design_run_id" in HTML
    assert "setExperienceView(\"build\")" in HTML
    assert "renderRun();" in HTML
    assert "pollRun();" in HTML
    assert 'connectRun();' in HTML
    assert "if (!state.run && state.session && state.session.design_run_id) connectRun();" in HTML
    assert "state.runPoll" in HTML


def test_boot_uses_the_cookie_scoped_incubation_selected_by_the_server():
    assert 'api("/incubations/default")' in HTML
    assert "resolved && resolved.incubation && resolved.incubation.incubation_id" in HTML
    assert "state.incubationId = requested || null;" in HTML
    assert 'defaultUrl.searchParams.set("incubation_id", state.incubationId)' in HTML
    assert "window.history.replaceState({}, \"\", defaultUrl.pathname + defaultUrl.search)" in HTML
    assert 'localStorage.setItem(state.incubationKey, state.incubationId)' in HTML


def test_intake_lab_can_start_a_new_cookie_scoped_conversation_without_purging_the_old_one():
    assert 'id="new-session" class="new-session" type="button"' in HTML
    assert "const startNewConversation = async ()" in HTML
    assert 'api("/incubations", { method: "POST"' in HTML
    assert "The current chat and design will remain saved." in HTML
    assert "const initialIncubationId = new URLSearchParams(window.location.search).get(\"incubation_id\")" in HTML
    assert "cleanUrl.searchParams.delete(\"incubation_id\")" in HTML
    assert "target.searchParams.delete(\"run_id\")" in HTML
    assert '$("#new-session").addEventListener("click", startNewConversation)' in HTML


def test_boot_defaults_to_the_latest_revision_and_offers_run_switching():
    assert 'id="run-switcher"' in HTML
    assert "const revisions = Array.isArray(candidateRun.revisions) ? candidateRun.revisions : []" in HTML
    assert "const readyRevision = revisions.slice().reverse().find((item) => item && item.reviewable && item.run_id);" in HTML
    assert "const selectRun = async (runId)" in HTML
    assert 'pill.setAttribute("aria-current"' in HTML
    assert 'pill.addEventListener("click", () => selectRun(rev.run_id))' in HTML
    assert "switcher.replaceChildren()" in HTML


def test_cognition_feed_is_derived_from_durable_state_not_llm_lines():
    assert "buildFeedItems" in HTML
    assert "renderCognition" in HTML
    assert "const items = []" in HTML or "renderCognition" in HTML
    assert "deduction-" in HTML
    assert "item.analysis" in HTML or "item.description" in HTML
    assert "state.deductions" in HTML
    assert "state.infusionRuns" in HTML


def test_cognition_lines_are_bound_to_synapse_atoms_for_hover():
    assert "line.dataset.atom = item.key" in HTML
    assert "state.synapse.hoverKey = item.key" in HTML
    assert 'line.classList.add("is-active")' in HTML


def test_synapse_field_uses_ledger_atoms_and_shared_reference_edges():
    assert "buildSynapseAtoms" in HTML
    assert "matchSynapseEdges" in HTML
    assert "atomKeyphrases" in HTML
    assert "a.refs.filter((ref) => b.refs.includes(ref))" in HTML
    assert "state.synapse.edges" in HTML
    assert "force-directed" not in HTML or "physicsStep" in HTML


def test_synapse_field_has_physics_impulses_and_calm_idle_decay():
    assert "physicsStep" in HTML
    assert "impulseSynapse" in HTML
    assert "state.synapse.impulses" in HTML
    assert "maybeAttentionWave" in HTML
    assert "edge._formAt != null && now >= edge._formAt && now < edge._formAt + 900" in HTML
    assert "activeImpulse.edge" in HTML
    assert "state.synapse.edges.filter((edge) =>" in HTML
    assert "edge.semantic && a && b" in HTML
    assert "activeImpulse.semantic" in HTML


def test_synapse_field_respects_reduced_motion_and_mobile():
    assert "drawStaticSynapse" in HTML
    assert "prefers-reduced-motion" in HTML
    assert "@media (max-width: 680px)" in HTML
    assert "#ada-mind, #ada-mind-toggle { display: none; }" in HTML
    assert "window.matchMedia(\"(max-width: 680px)\")" in HTML


def test_poll_cadence_was_reduced_for_crisp_heartbeat():
    assert "document.hidden ? 2200 : 600" in HTML


def test_turn_state_heartbeat_badge_exists():
    assert 'id="turn-state"' in HTML
    assert "state.turnStartedAt" in HTML
    assert ".padStart(2, \"0\")" in HTML


def test_send_message_offers_inline_retry_on_enqueue_failure():
    assert 'id="retry-turn"' in HTML
    assert "state.pendingTurn" in HTML
    assert "enqueueTurn" in HTML
    assert "Message queued after retry." in HTML


def test_poll_done_renders_cached_then_retries_refresh():
    assert "for (let attempt = 0; attempt < 3; attempt++)" in HTML
    assert "The turn finished; still syncing the brief" in HTML

def test_neurons_form_a_stable_2d_orbital_instrument():
    # Twelve deterministic slots form two clean rings around Ada's core.
    assert "const orbitalSlotAngles = [0.22, 1.79, 3.36, 4.93, 0.61, 1.39, 2.18, 2.96, 3.75, 4.53, 5.32, 6.10];" in HTML
    assert "const syncOrbitalSlots = (atoms) => {" in HTML
    assert "const inner = atom._orbitSlot < 4;" in HTML
    assert "const orbitTurn = t * Math.PI * 2 / 56;" in HTML
    assert "const drawOrbitalField = (ctx, w, h, t) => {" in HTML
    assert "const drawOrbitalCore = (ctx, frame, t, coreAlpha, coreScale, idle, staticMode = false) => {" in HTML
    assert "const coreR = (idle ? 34 + 5 * beat : 32 + 4 * beat) * coreScale;" in HTML
    assert 'ctx.textAlign = "center";' in HTML
    assert 'ctx.textBaseline = "middle";' in HTML
    assert 'ctx.fillText("ADA", frame.cx, frame.cy);' in HTML
    # Full text is reserved for a maximum of three stable perimeter callouts.
    assert "const orbitalCalloutSlots = (frame, w) => {" in HTML
    assert "const drawOrbitalCallouts = (ctx, atoms, w, h, now, staticMode = false) => {" in HTML
    assert ".slice(0, slots.length);" in HTML
    assert "wrapCompleteLines(ctx, atom.label, slot.w - 16)" in HTML
    assert "sphereTurn" not in HTML


def test_uploads_show_progress_and_thumbnail_chips_auto_attach():
    assert 'id="upload-progress"' in HTML
    assert "class=\"upload-progress-track\"" in HTML
    assert 'id="upload-progress-fill"' in HTML
    assert "xhr.upload.onprogress" in HTML
    assert "uploadFileXHR" in HTML
    assert "chip.dataset.assetId = String(item.id);" in HTML
    assert '"reading…"' in HTML
    # No more opt-in checkboxes: every ready image attaches automatically.
    assert "data-asset-pick" not in HTML
    assert "Selected images join this message" not in HTML
    assert ".filter((item) => item.status === \"ready\" && !item.archived).map((item) => Number(item.id))" in HTML
