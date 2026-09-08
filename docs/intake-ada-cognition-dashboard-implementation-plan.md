# Intake Lab — Conversation Reliability, Speed, and an Ada Cognition Background

Status: implemented + live-verified (2026-09-04). Owner: build agent. Goal: make the Intake Lab (1) never silently
stall a turn, (2) answer noticeably faster, and (3) show Ada's actual cognition
— thoughts, deductions, research, incubation — in a background that is discrete
yet perfectly readable.

Implementation notes (verified live):
- A: `pollJob` renders on done before refreshing, retries `refreshSession` 3×,
  re-schedules, and shows a `TURN COMPLETE` heartbeat; `sendMessage` keeps the
  message and offers inline Retry (`#retry-turn`); `fail_stale_chat_jobs`
  watchdog marks stale jobs `reason=stale`; diagnostic list at
  `GET /api/incubations/{id}/chat/jobs`.
- B: probe showed entrim accepts `chat_template_kwargs.enable_thinking` but
  does not honor it (reasoning tokens still burn). `max_tokens` 4000→2000 cut
  a measured turn ~7.1s→~4.7s; advisor is single-shot + one nudge (never two
  blind retries); poll cadence 600 ms.
- C/C5: `#ada-mind` panel + `#ada-ticker` render a real deterministic feed
  (facts, deductions, findings, genesis, media, runs); `#incubation-canvas`
  is now the synapse field — ledger atoms, shared-reference edges, rAF
  force-directed layout, impulses + attention wave, calm idle decay,
  reduced-motion static snapshot, ≤680px ticker only.
- D: durable `incubation_deductions` + `infusion_runs`; `IncubationInfusionService`
  (enqueue/throttle/budget/dedupe) + `IncubationInfusionExecutor`; native
  DeepSeek fallback with one retry; `stage_infusion` in `hands/opencode_runner.py`
  spawns an isolated opencode session with the `researcher` subagent + pipeworx
  remote MCP, parses the JSON contract from the raw tail, persists 5 typed,
  source-linked deductions (live run produced real cité/BOAMP/École-de-Lyon
  market research), and feeds the advisor's knowledge briefing. The opencode
  session id is retained for diagnostics and never forwarded back to `--session`.
  Note: a fresh opencode session per pass; the intake `session_id` is run
  metadata only.
- Known residual: DeepSeek V4 Flash intermittently emits an empty completion
  (provider flake); the advisor falls back to an honest follow-up and infusion
  retries once — conversation never strands.

---

## 1. Context (what exists today)

The intake path is otherwise healthy: the advisor extracts facts reliably, asks
one focused question per turn, reaches `ready_to_build`, and the build pipeline
produces reviewable candidates. The remaining complaints are four:

1. A turn appeared to stall — "Ada never answered, never moved past this message."
2. The background is illegible.
3. The background shows operational noise (`saved intake / revision N`,
   `direction updated`) instead of Ada's thoughts / research / incubation.
4. Turns are slow (9–38 s, one outlier; DeepSeek V4 Flash reasons before every
   answer and provider flakes cost a retry + nudge, i.e. multiple sequential calls).

Diagnostic result (2026-09-04): the workspace DB shows every turn complete
(4 jobs done, 4 assistant replies persisted). The visible "stall" is therefore
not a lost job — it is a **presentation/recovery gap**:

- `pollJob()` marks the terminal branch `if (job.status === "done") { await
  refreshSession(); ... }` with **no fallback** and no re-render if the refresh
  throws, and it does **not** re-schedule polling on that branch. One transient
  refresh error strands the UI on the last "WORKING" frame forever.
- A single turn can take minutes when the reasoning model emites an empty
  completion: retry (2×) + nudge = up to 3 sequential provider calls, each with
  a 90 s timeout. To the user this is indistinguishable from "stuck".
- `sendMessage` enqueue errors are only shown as a composer note after the fact;
  a failed enqueue leaves no job and no message, so the conversation appears to
  "freeze at" the last message.

---

## 2. Workstream A — the conversation must never appear stuck

### A1. UI recovery (primary fix)
- `pollJob()`: on `done`, always render immediately from cached `state.job` +
  `state.session`, then attempt `refreshSession()` in a `try`; on failure keep the
  cached render, show a soft "still syncing" note, and **re-schedule a couple of
  retries** instead of stopping.
- `sendMessage`: on enqueue error, ask "Retry" inline (preserve the message and
  selected assets) instead of silently dropping the turn. Guard double-clicks
  (disable until response) — already present, keep it.
- Add a composable "turn state" badge: `queued → thinking → answering →
  complete` with the elapsed seconds, so long reasoning is visibly a heartbeat,
  not a freeze.
- `visibilitychange` already re-polls; extend to re-poll whenever a non-terminal
  job exists for slightly longer (keep `document.hidden ? 5000 : 700`).

### A2. Server liveness + observability
- Add a **job watchdog sweep** (in the scheduler or a cheap middleware check):
  any chat job `queued`/`running` older than N minutes (default 4) is marked
  `failed` with `reason=stale` and the session is reconciled. Survives a worker
  restart and surfaces in the UI as a clear error with an "ask again" path.
- `run_job` already records `chat_worker_error` on unexpected failures; also log
  `advisor_call_count` and `duration_ms` per turn into the job result so latency
  spikes are visible in the developer drawer.
- New diagnostic endpoint: `GET /api/incubations/{id}/chat/jobs` (list, statuses,
  ages) so a "stuck" report is resolvable in seconds without opening the DB.

### A3. Interface hardening (cheap)
- Cap the advisor at **one provider call per turn by default + one corrective
  nudge only**, never two full retries of the same prompt before the nudge voice
  changes. Rationale: a flaky empty completion is usually cured by the nudge; the
  second blind retry only doubles latency.

---

## 3. Workstream B — faster answers

Measured baseline (entrim, `deepseek-ai/DeepSeek-V4-Flash`): 9–38 s/turn; the
cost is provider latency + hidden reasoning + occasional empty→retry→nudge.

- **Probe `chat_template_kwargs: { enable_thinking: false }`** against entrim for
  the deepseek intake advisor (same knob already used for Qwen vision). Accept as
  `llm.chat(..., enable_thinking=...)` so it is one config flag per consumer. If
  entrim honors it, per-turn latency should collapse to a few seconds.
  Fallback if unsupported: keep reasoning but reduce `max_tokens` so the model
  cannot over-think (see below).
- **Token budget without over-thinking:** intake advisor `max_tokens` 4000 →
  ~1600 when thinking is off (output fits easily); keep 90 s timeout.
- **Poll cadence:** reduce job poll to ~600 ms while a turn is in flight so the
  heartbeat UI is crisp.
- **Nudge policy:** only nudge when the parsed turn has zero field updates AND
  the owner message contains facts (≥3 tokens) — i.e. do not nudge acknowledges;
  already true, keep and test.
- **Async warm-up:** on page load and after each turn, do not leave the first
  provider call cold — acceptable to skip; do not add speculative LLM calls.
- Target: steady-state 3–8 s/turn, worst case under ~25 s including one nudge.

---

## 4. Workstream C — a readable cognition background

Replace the current decorative/mono-log ambient with an "Ada's mind" surface:
discrete, translucent, readable, and filled with cognitions rather than
operational receipts.

### C1. Readability rules (the "minimal base" requirement)
- Panel sits on the minimal white page with a translucent scrim:
  `background: rgba(255,255,255,.72)` + `backdrop-filter: blur(10px)` +
  `mix-blend-mode: normal`, so text is ≥ 4.5:1 against the canvas.
- Font: the existing mono is fine but bump to 11–12 px, `letter-spacing: .01em`,
  `opacity: 1` for the active line and `.55` for history (never glow-only).
- Keep it out of the way: pinned edges, `max-width` per column, auto-collapse to
  a single-line ticker after 8 s idle, and a dedicated "open Ada's mind" toggle
  in the corner. Full panel hidden on ≤680 px (mobile shows the ticker only).
- Canvas constellation stays as-is but reduces toward the edges (already radial);
  raise its `mix-blend-mode: soft-light` and cut node labels except the active
  one, so it reads as atmosphere, not noise.

### C2. What "thoughts" actually are (all from durable data — no invented text)
Build a **narrative feed** rendered from real state, one sentence per event,
grouped into the existing constellation channels:

| Channel | Sources (already persisted) | Rendered cognition examples |
|---|---|---|
| OBSERVING | qwen asset analysis, latest owner message | "Ada observe le logo : ocres, quiétude artisanale. palette #D97A35" |
| REASONING | intake job `steps`, `creative_insights`, field provenance notes | "Un doute : le site visera-t-il surtout les particuliers ?", "Elle déduit de la réponse que la galerie aura le rôle principal" |
| RESEARCHING | research requests/jobs/sources/findings | "Elle écoute r/Tapisserie — 3 sujets à explorer", "Source maison-tapissier.com/feed candidate, en attente de confiance" |
| INCUBATING | genesis creative_identity / business_world, novel insights | "Elle retient : chaleur, fait-main, 'l'atelier comme un lieu'", "Tension notée : étendre B2B sans perdre les particuliers" |
| DESIGNING | run pipeline labels + phases, build steps | "Elle dessine la page d'accueil : hero chêne, rubrique métier, CTA unique" |

Renderer: a deterministic, rule-based sentence builder (no LLM per line) mapping
structured records → short French/English sentences, keyed by `activity_id` /
`job_id` / `finding_id` to avoid duplicates. Store nothing new: derive on render
from `activity.activities`, `research.*`, `genesis.current`, `intake.messages`,
`creative_insights`, and asset analyses already in the summary payload.

### C3. "Why this is cool" framing
- Add a faint trailing thread per channel (matching the constellation spokes)
  and a one-line "lead thought" that tracks the newest high-signal event (new
  finding, genesis change, phase transition) — this is the "birth of Ada"
  narrative made literal.
- Keep a click-to-expand per line → developer drawer detail (existing
  `activity-detail`).

### C4. Delivered in `web/static/intake_lab.html` only
- No build step. GSAP already vendored. New markup: `#ada-mind` panel +
  `#ada-ticker` + a channel registry identical to the canvas `incChannels`.
- Existing tests must keep passing (they assert on current ids/strings); add new
  assertions for `#ada-mind`, `.cognition`, `data-channel` re-use, reducer
  guards.

### C5. The synapse field — neurons forming as knowledge forms
The constellation canvas becomes a renderer for the same knowledge ledger the
feed reads: a growing graph where **edges are relationships in the data**, so
"thoughts connecting" is real, not decorative.

- **Node = a knowledge atom.** Draft facts, creative insights, research
  findings, qwen asset analyses, genesis principles, and deductions (Workstream
  D). Fields: `type`, `label`, `channel`, `confidence`, `refs
  (supports_paths / source_refs / finding_ids / related_asset_ids)`,
  `keyphrases`, `created_ts`. Color = channel; size = confidence / how often it
  is referenced (integration).
- **Edge = a shared reference.** Two atoms synapse if they intersect on any
  `supports_paths` token, source/`finding_id`, asset id, or genesis↔draft path.
  Cap out-edges per node (~6) to stay legible. Every new deduction auto-lights
  synapses to its evidence + the paths it supports. `edge.created_ts` drives
  impulse effects and idle decay.
- **Layout = the incubation arc (physics, rAF).** Force-directed, core pinned
  ("ADA"). New atoms spawn at the periphery with a random velocity and are
  pulled toward the core as they get integrated; nodes sharing paths attract
  each other, so clusters visibly form and merge over time. This is the
  "inception/birth" moment made literal. Target < 300 nodes; 2D canvas with a
  small dirty-set (only changed atoms tick each frame); WebGL point/line pass
  is a later upgrade if counts grow.
- **Signaling.** Newly-formed edges carry travelling impulse dots (parametric
  bezier). An attention wave periodically radiates from the newest
  high-confidence node and briefly re-ignites its neighbors, then decays.
- **Calm by default.** Idle edges fade over a TTL; glow only on active paths;
  most nodes stay faint dots. Everything sits behind the translucent scrim with
  the text feed readable on top.
- **Two views, one ledger.** Hovering a cognition line highlights its node + its
  synapses; clicking a line opens the detail drawer. No synthetic connections —
  a line exists iff the ledger says the atoms relate.
- **Fallbacks.** `prefers-reduced-motion`: static faint snapshot (no impulses,
  no physics). Mobile (≤680 px): graph hidden, ticker only.

---

## 7. Workstream D — the background "infusion" loop (what actually feeds everything)

Goal: a durable background process that continuously turns new information into
knowledge, and knowledge into more research — the true fuel for the cognition
background and for Ada's persona. Each pass *reads* the current knowledge base,
*adds* deductions + new research, and *persists* everything so the next pass and
the conversation start from more.

### D1. Principles
- Every new piece of information (intake fact, image analysis, research finding,
  deduction, genesis change) enters one **immutable infusion ledger** and is
  convertible into a cognition sentence — nothing is "just a log".
- Passes are durable (survive restart), throttled, and budget-capped — never a
  blocking chat dependency.
- Output is structured and typed; source-linked; never presented as owner facts.
- All data stays bounded and private (no key leakage; citation URIs kept).

### D2. Durable state (Memory migrations)
- `incubation_deductions(deduction_id, kind, summary, confidence, basis,
  source_refs[], supports_paths[], horizon_question[], created_ts)`.
  Kinds: `market_context`, `audience_fact`, `audience_hypothesis`,
  `creative_leaning`, `competitor_note`, `positioning_note`, `risk`,
  `opportunity`.
- `infusion_runs(run_id, trigger, budget_tokens, status, sources_seen,
  deductions_added, created_ts, finished_ts)` for liveness + dedupe.
- Existing `research_requests/findings/insights`, `genesis_revisions`,
  `creative_insights`, asset analyses remain the other inputs.

### D3. When a pass fires (signals + throttle)
- Triggers (any): intake revision saved; research pass completed; genesis
  changed; new image analysis; and an **idle timer** (no trigger for N min but
  knowledge changed) so the panel stays alive.
- Cooldown: ≥1 pass per 60–90 s idle; cap by `daily_budget_usd` and a
  `max_tokens_per_pass` config; one pass at most while a previous is `running`.
- Enqueue via the existing durable job pattern (claim/run/fail) so a crash
  doesn't lose or double-run.

### D4. Pass execution — opencode is the engine, native LLM is the fallback
The executor runs passes in **opencode-first** mode: the same headless
`opencode run` mechanism the repo already uses for design builds, retargeted to
return knowledge instead of a worktree diff.

Input (both modes): a bounded **state snapshot** JSON (canonical): core draft
fields, genesis sections, latest findings/insights (capped), asset-analysis
summaries, existing deductions (dedupe), owner language.

Output contract (strict JSON):
```
{"deductions":[{"kind":..,"summary":"..","confidence":0..1,"basis":"snapshot|sourceX|hypothesis","supports_paths":[..]}],
 "followup_research":[{"type":"feed|community|pipeworx","query|url":"..","reason":".."}],
 "genesis_notes":{"business_world":{},"creative_identity":{}},
 "horizon_questions":[".."]}
```

- **Mode B — opencode engine (primary).** New runner operation
  `stage_infusion` (sibling of `stage_design_build` in
  `hands/opencode_runner.py`):
  1. stage the snapshot into a disposable worktree,
  2. `install_agent_files(..., include_pipeworx=True)` — write `mcp.pipeworx`
     (same server + auth as the operator host) and a `researcher` subagent whose
     system prompt is the current AGENTS-style incubation policy ("use pipeworx
     tools: ask_pipeworx / discover_tools; deepen the single hardest open
     question; cite `pipeworx://` URIs"),
  3. `run_opencode(...)` with a brief that says "study the snapshot, use your
     tools and subagents, then reply with exactly the JSON contract above",
  4. parse the final assistant block from the session transcript (`opencode.jsonl`),
  5. persist deductions + follow-up research + genesis notes, tag sources
     `discovered_by: pipeworx`, keep `pipeworx://` citation URIs; the opencode
     session id is retained for diagnostics.
  Subagents may fan out in parallel over pipeworx queries (market, audience,
  sustainability, competition) and converge in the main session. No file edits
  are required of the agent.
- **Mode A — native fallback (cheap).** One in-process DeepSeek call against the
  same snapshot + contract, used when opencode is unavailable (binary missing,
  session failed) or for a small "quick deduce" pass while no big pass is
  running. Output converges to the same persistence path.

### D4a. Executor & policy (both modes)
- `IncubationInfusionExecutor` (sibling of `IncubationResearchExecutor`):
  claim/run/fail durable jobs, throttle, budget.
- Budget: `max_tokens_per_pass`, `max_passes_per_day`, `daily_budget_usd`;
  one pass at a time. opencode passes are gated (~1 per 30 min / per major state
  change) because each spawns a session with potential subagent fan-out.
- Signals and dedupe: as D3; snapshot hash dedupes identical-context reruns.

### D5. Pipeworx access (now through the same runner the agent uses)
- Pipeworx (lemmy MCP) is available to **opencode**, not in-process Python.
  `stage_infusion` therefore carries the operator host's pipeworx MCP config
  (server + auth) into the per-clone opencode session by extending
  `install_agent_files`, mirroring how the provider config is already written.
- The spawned `researcher` subagent gains `task` access so it can fan out over
  `ask_pipeworx` / `discover_tools` queries in parallel and converge.
- Results are cached as normal `research_sources/findings` tagged
  `discovered_by: pipeworx` with `pipeworx://` citation URIs; `trust_state`
  stays `candidate` until owner approval — same policy as today.
- RSS/reddit research keeps working through the existing network reader; a
  native DeepSeek "quick deduce" pass (Mode A) is the cheap fallback when
  opencode is unavailable.

### D5a. What a pass looks like in the cognition feed (C2)
"Ada relit la commande et ses sources, déduit — potentiel B2B décorateurs/hôtels
non exploité" (OBSERVING/REASONING) → "Ada consulte Pipeworx : segment luminaires
upcyclés, 3 sources retenues" (RESEARCHING, with `pipeworx://` citation) →
"Ada incube : l'atelier comme lieu + engagement durable = axe de positionnement"
(INCUBATING). Each line is a persisted, typed deduction, not a log.

### D6. Feeding back into the conversation and design
- Each pass appends a **knowledge briefing** into `_advisor_prompt`
  (`brain/design_intake.py`) — or the top 3–6 newest deductions + findings — so
  Ada's next question is informed by research ("…d'après ce que je lis sur le
  segment luminaires upcyclés, toi tu fais la différence sur…").
- Deductions feed `_incubated_creative_context` at build time (market/audience/
  positioning context the designer can use), alongside existing preferences,
  research insights, and novelty constraints.
- All deductions/sources/insights are pick-up-able by the cognition feed (C2)
  and by the constellation's RESEARCHING / INCUBATING channels.

### D7. Config (intake-ada.yaml)
```
infusion:
  enabled: true
  mode: opencode            # opencode | native | auto (opencode → fallback to native)
  idle_seconds: 90
  cooldown_seconds: 60
  max_tokens_per_pass: 1200
  max_passes_per_day: 120
  opencode_pass_interval_seconds: 1800   # ≥1 opencode session per 30 min
  include_pipeworx: true
```

---

## 5. Implementation steps (updated)

1. **A2** `core/chat_jobs.py` — watchdog flags stale jobs; log `duration_ms`.
2. **A1** `web/static/intake_lab.html` — resilient `pollJob` + retry-on-refresh,
   turn-state heartbeat, `sendMessage` retry affordance.
3. **A3** `brain/design_intake.py` — single-shot first call + nudge; cap retries.
4. **B** probe `enable_thinking:false` in `core/llm.py` + `intake-ada.yaml`
   (`intake_advisor.max_tokens`, `timeout_seconds`), poll 600 ms.
5. **C** `web/static/intake_lab.html` — cognition feed builder + `#ada-mind`
   panel styling + readability pass + mobile ticker; **C5 synapse field**:
   atom registry from the ledger, edge matcher (shared refs), force-directed
   rAF physics with pinned core, impulse/attention-wave signaling, idle decay,
   feed↔graph hover detail, reduced-motion + mobile fallbacks.
6. **D** (new) — Memory migrations (`incubation_deductions`, `infusion_runs`);
   `IncubationInfusionExecutor` (durable job, throttle, budget) + signal hooks
   after intake revision / research completion / genesis / media analysis +
   idle timer; snapshot builder; contract parser for the transcript reply;
   **runner operation `stage_infusion`** in `hands/opencode_runner.py`
   (snapshot → `run_opencode` with pipeworx MCP + `researcher` subagent via
   `install_agent_files(include_pipeworx=True)` → parse JSON from transcript);
   native DeepSeek `quick_deduce` fallback path; deduction persistence (+
   activity ledger, `pipeworx://` citation URIs, `discovered_by: pipeworx`);
   follow-up research enqueue; genesis_notes application; advisor knowledge
   briefing; build-context surface.
7. Tests: `tests/test_design_intake.py` (nudge only once; heartbeat labels),
   `tests/test_intake_lab_preview_ui.py` (new ids/channels), watchdog unit test,
   infusion executor tests (Mode A with fake LLM; Mode B runner stub returning
   contract JSON; dedupe; throttle; budget cap), latency smoke in live.
8. Full suite + compile + wheel; restart the lab; live-verify: a real
   conversation with research + genesis + at least one infusion pass lights the
   cognition feed with real sentences, no console errors, mobile clean.

## 6. Verification checklist (updated)
- [ ] A turn that previously "hung" now always reaches a terminal visible state
      (answer or clear error + retry) < 5 s after the provider returns.
- [ ] Steady-state turn latency 3–8 s on the deployed model.
- [ ] Background: discrete scrim, text readable (contrast + not glowing),
      collapsible, reduced-motion safe, mobile ticker.
- [ ] Background shows ≥ 3 distinct cognition sentences per channel derived from
      real data (not "saved revision N").
- [ ] C5 synapse field: nodes = ledger atoms, edges only where refs intersect;
      clusters form/merge as new atoms integrate; impulses + attention wave on
      new edges; calm idle decay; hover links feed↔graph; reduced-motion +
      mobile fallbacks work; ≤300 nodes stays smooth.
- [ ] Infusion: a background pass runs after knowledge changes, persists typed
      deductions + activity, enqueues follow-up research, updates the advisor
      briefing and the build context, respects throttle and budget. The
      opencode engine pass (stubbed in tests: runner stub returning contract
      JSON; contract parser unit-tested against a recorded transcript) produces
      deductions with `pipeworx://` citation URIs via the `researcher`
      subagent + pipeworx MCP; native fallback covers opencode-unavailable.
      Cognition feed narrates a full opencode pass end-to-end in the live lab.
- [ ] Zero new page errors; focused + full suite green; wheel rebuilt.