from pathlib import Path


def test_intake_lab_preview_scales_fixed_viewport_inside_embedded_panel():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert ".frame-viewport { width: 100%; overflow: hidden;" in html
    assert ".frame-canvas { transform-origin: top left; }" in html
    assert "const scale = Math.min(1, availableWidth / width);" in html
    assert "viewport.style.height = `${Math.ceil(height * scale)}px`;" in html
    assert "iframe.style.width = `${width}px`;" in html
    assert "new ResizeObserver(fitPreviews)" in html


def test_intake_lab_ui_exposes_revision_pipeline_and_final_result():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert 'id="revision-panel"' in html
    assert 'id="revision-count"' in html
    assert 'id="result-panel"' in html
    assert 'id="result-summary"' in html
    assert 'id="result-next"' in html
    assert 'id="quality-gates"' in html
    assert 'run.pipeline' in html
    assert 'run.revisions' in html
    assert 'run.duration_label' in html
    assert 'step.label || stateLabel(step.key)' in html


def test_intake_lab_preview_waits_for_a_candidate_page_and_retries_without_manual_refresh():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert "const stopPreviewPolling = () =>" in html
    assert "state.previewPending" in html
    assert "find((item) => item && item.candidate && item.path)" in html
    assert "The candidate is retained while its preview is syncing." in html
    assert "schedulePreviewRetry" in html


def test_intake_lab_preserves_an_explicit_run_selection_during_refresh():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert 'const preferToShow = requestedRunId ||' in html


def test_intake_lab_ui_keeps_durable_intake_trace_without_a_question_list():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert "latest_advice_job_id" in html
    assert "chat/jobs/${latestJobId}" in html
    assert "job.status === \"done\"" in html
    assert ".slice(-9)" in html
    assert "readiness.open_questions" not in html
    assert "id=\"open-list\"" not in html
    assert "Open questions:" not in html
    assert "mediaPoll" in html


def test_intake_lab_ui_exposes_three_durable_activity_channels():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert 'id="activity-strip"' in html
    assert 'data-channel="discovering"' in html
    assert 'data-channel="becoming"' in html
    assert 'data-channel="designing"' in html
    assert 'id="activity-load-older"' in html
    assert "after_id=" in html
    assert "activityPoll" in html
    assert "before_id=" in html


def test_intake_lab_starts_as_chat_and_keeps_diagnostics_in_debug_view():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert '<body data-view="intake"' in html
    assert 'body[data-view="intake"] .conversation-intro' in html
    assert 'body[data-view="intake"] .conversation-meta' in html
    assert 'body[data-view="intake"] #activity-strip' in html
    assert 'body[data-view="intake"] .rail' in html
    assert 'opacity: .96' in html
    assert 'id="confirm-panel" class="panel confirm chat-confirm"' in html
    assert 'id="confirm" class="button dark"' in html
    assert '>Confirm and build<' in html


def test_intake_lab_background_is_neuroscience_not_text_logs():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    # The old log columns are gone from the visible layer.
    assert '.ambient-column' not in html
    assert '.ambient-footer' not in html
    assert 'ADA / FIELD NOTES' not in html
    # The brain remains: canvas + cognition feed + a living breathing core.
    assert 'id="incubation-canvas"' in html
    assert 'id="ada-mind"' in html
    assert 'field-reading' not in html
    assert 'renderFieldReading' not in html
    assert 'const idle = visible.length === 0;' in html
    assert 'id="ambient-state"' in html
    # Legacy trace markers stay only as hidden diagnostics, never visible text.
    assert 'id="background-trace" class="trace" hidden' in html


def test_intake_lab_renders_ada_incubation_constellation_and_birth_transition():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert 'id="incubation-canvas"' in html
    assert "incChannels" in html
    assert "gsap.min.js" in html
    assert "playBirth" in html
    assert ".birth-flash" in html
    assert "ensurePreviewFill" in html
    assert "revealPreviewFrame" in html
    assert ".preview-fill" in html


def test_confirm_build_switches_to_the_evolving_build_workspace():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert 'id="build-workspace"' in html
    assert 'id="build-activity"' in html
    assert 'id="build-visual"' in html or 'class="build-visual"' in html
    assert 'const buildPhases = [' in html
    assert 'const validationPhases = [' in html
    assert 'const startBuildMotion = () =>' in html
    assert 'const setExperienceView = (view, { syncHistory = true } = {}) =>' in html
    assert 'setExperienceView("build");' in html
    assert 'document.body.dataset.view !== "intake"' in html


def test_normal_chat_uses_ada_greeting_and_compact_composer_controls():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert "Hi, I'm Ada. What are you working on?" in html
    assert 'placeholder="Message Ada"' in html
    assert 'aria-label="Send message"' in html
    assert '>Send<' in html
    assert 'Talk to Ada' not in html
    assert 'A picture can help' not in html


def test_message_composer_sends_on_enter_and_keeps_shift_enter_for_newlines():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert 'const submitOnEnter = (event) =>' in html
    assert 'event.key !== "Enter"' in html
    assert 'event.shiftKey' in html
    assert 'event.preventDefault();' in html
    assert '$("#composer").requestSubmit();' in html
    assert '$("#message").addEventListener("keydown", submitOnEnter);' in html


def test_offer_summary_is_an_explicit_build_gate():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert "business.offer_summary is required before building" in html
    assert "offerSummary" in html
    assert "canConfirm =" in html


def test_brief_action_is_inline_but_refresh_stays_in_developer_view():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    confirm_start = html.index('<section id="confirm-panel"')
    build_start = html.index('<section id="build-workspace"')
    debug_start = html.index('<aside id="debug-drawer"')
    assert confirm_start < build_start
    assert confirm_start < debug_start
    assert 'id="confirm-panel" class="panel confirm chat-confirm"' in html
    assert 'id="refresh"' in html[debug_start:]
    assert 'id="refresh"' not in html[:debug_start]


def test_design_view_is_represented_in_history_and_restored_from_the_url():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()

    assert 'new URLSearchParams(window.location.search)' in html
    assert 'params.set("view", "design")' in html
    assert 'history.replaceState' in html
    assert 'params.set("run_id", runId)' in html
    assert 'window.addEventListener("popstate"' in html


def test_intake_chat_docks_in_a_left_column_and_lets_the_network_own_the_rest():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()
    assert 'body[data-view="intake"] main { min-height: calc(100dvh - 62px); padding: 26px 28px 40px; grid-template-columns: minmax(360px, 440px) minmax(240px, 1fr);' in html
    assert 'body[data-view="intake"] .conversation { width: 100%; height: min(680px, calc(100dvh - 130px));' in html
    assert '<div class="network-side"' in html
    assert 'Neural field — Ada\'s live thoughts' in html
    assert 'body[data-view="build"] .network-side { display: none; }' in html
    # Medium screens fall back to the centered conversation.
    assert '@media (max-width: 1000px) {' in html
    assert 'body[data-view="intake"] .network-side { display: none; }' in html


def test_intake_neural_network_transmits_and_thinks_out_loud():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()
    # The field is a stable 2D orbital instrument, not a perspective simulation.
    assert "const orbitalFrame = (w, h) => {" in html
    assert "const orbitalSlotAngles = [0.22, 1.79, 3.36, 4.93, 0.61, 1.39, 2.18, 2.96, 3.75, 4.53, 5.32, 6.10];" in html
    assert ".slice(0, 12);" in html
    assert "const orbitTurn = t * Math.PI * 2 / 56;" in html
    assert "const drawOrbitalField = (ctx, w, h, t) => {" in html
    assert "const drawOrbitalSignal = (ctx, edge, progress, color) => {" in html
    assert "const drawOrbitalConnection = (ctx, edge) => {" in html
    assert "const drawOrbitalCore = (ctx, frame, t, coreAlpha, coreScale, idle, staticMode = false) => {" in html
    assert "const coreR = (idle ? 34 + 5 * beat : 32 + 4 * beat) * coreScale;" in html
    assert 'ctx.textAlign = "center";' in html
    assert 'ctx.textBaseline = "middle";' in html
    assert 'ctx.fillText("ADA", frame.cx, frame.cy);' in html
    assert "3.5 * coreScale" not in html
    assert "const orbitalCalloutSlots = (frame, w) => {" in html
    assert "const drawOrbitalCallouts = (ctx, atoms, w, h, now, staticMode = false) => {" in html
    assert "const edgeMeaning = (a, b, sharedRefs) => {" in html
    assert "research meets brief /" in html
    assert "Source —" in html
    assert "drawSynapse" in html
    # Full labels are limited to three stable perimeter callouts.
    assert ".slice(0, slots.length);" in html
    assert "wrapCompleteLines(ctx, atom.label, slot.w - 16)" in html
    assert "const wrapCompleteLines = (ctx, text, maxWidth) => {" in html
    assert "state.synapse.impulses.filter((impulse) => now - impulse.start < 1200)" in html
    assert "sphereTurn" not in html
    assert "const FOV = 820, depth = 340;" not in html
    # Ada's mind log collapses by default.
    assert '<section id="ada-mind" aria-label="Ada\'s current thinking" aria-live="polite" hidden>' in html
    assert 'setMindOpen(false);' in html


def test_intake_chat_is_see_through_to_the_network():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()
    assert "background: rgba(255, 255, 255, .55);" in html
    assert "backdrop-filter: blur(14px) saturate(1.15);" in html
    assert 'body[data-view="intake"] main { min-height: calc(100dvh - 62px); padding: 26px 28px 40px; grid-template-columns: minmax(360px, 440px) minmax(240px, 1fr);' in html


def test_intake_has_a_precision_entrance():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()
    # The page starts from NOTHING: the interface is held out of view on first
    # paint (body.intro-pending) behind a sparse scaffold, then morphs in as
    # Ada's existing core grows from a speck and the window shapes into place.
    assert 'class="intro-pending"' in html or 'class="intro-pending "' in html
    assert "body.intro-pending main," in html
    assert "const startIntroScaffold = () => {" in html
    assert "state.synapse.birthAt = Number.POSITIVE_INFINITY;" in html
    assert "window.setTimeout(playEntrance, 1050);" in html
    assert "const playEntrance = () => {" in html
    assert "document.body.classList.remove(\"intro-pending\");" in html
    assert "document.body.classList.add(\"genesis-active\");" in html
    assert "state.synapse.birthAt = performance.now();" in html
    assert "animation: window-ember 3.4s" in html
    assert "clip-path: inset(0 0 100% 0 round 14px);" in html
    assert 'gsap.fromTo(".ambient-layer", { opacity: 0 }' in html
    assert "playEntrance();" not in html or "window.setTimeout(playEntrance, 1050)" in html
    assert "if (reduceMotion || document.body.dataset.introPlayed) return;" not in html or "document.body.dataset.introPlayed) return;" in html
    # The old 90s burst (colorful particles + stroked rectangle) is gone.
    assert "paletteBang" not in html


def test_intake_big_bang_morphs_into_neurons_and_chat_window():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()
    # Each thought is BORN at the core and flies out on its own beat — the
    # idle field is just Ada's breathing core, no pre-drawn neuron scatter.
    assert "atom._spawnAt" in html
    assert "atom._birthP" in html
    assert "atom._px" in html and "atom._py" in html
    assert "1 - Math.pow(1 - p, 3)" in html
    assert "stable orbital slot" in html
    # The window forges out of the same light via clip-path morph.
    assert "body.genesis-active .chat-window" in html
    assert "@keyframes window-ember" in html
    assert "const orbitalSlotAngles" in html


def test_resting_state_refinements_stay_within_the_palette():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()
    # Persistent transparency: the window is glassy, the field glows through.
    assert "background: rgba(255, 255, 255, .55);" in html
    assert "backdrop-filter: blur(14px) saturate(1.15);" in html
    # Texture and idle life, all in the existing terracotta/warm-white family.
    assert "ambient-grain" in html
    assert "feTurbulence type='fractalNoise'" in html
    assert "ambient-shaft" in html
    assert "@keyframes shaft-breathe" in html
    assert "@keyframes grid-drift" in html
    assert "animation: grid-drift 90s linear infinite;" in html
    assert "ctx.setLineDash([22, 120]);" in html
    assert "maybeIdleFlicker" in html
    assert "state.synapse.lastFlicker" in html
    assert "now - state.synapse.lastWave < 12000" in html


def test_resting_field_stays_alive_and_neurons_are_legible():
    html = (Path(__file__).parents[1] / "src" / "site_agent" / "web" / "static" / "intake_lab.html").read_text()
    # Continuous idle breathing + one slow orbital turn keeps the field alive.
    assert "state.synapse.genesisAt" not in "x" and "t * Math.PI * 2 / 56" in html
    assert "atom._breath = 1 + 0.08 * Math.sin(t * 1.3 + (atom._seed || 0));" in html
    # Nodes remain interactive; the graph itself carries the semantic labels.
    assert "class=\"ambient-legend\"" not in html
    assert "Neuron key" not in html
    assert "pointer-events: auto; cursor: crosshair;" in html
    assert "drawOrbitalCallouts" in html
    assert "hitAtom" in html
    assert 'state.synapse.hoverKey = hitAtom(px, py) || null;' in html
    assert 'el.addEventListener("pointermove", onPointer);' in html
