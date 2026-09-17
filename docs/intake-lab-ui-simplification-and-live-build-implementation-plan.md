# Intake Lab UI Simplification and Live Build Implementation Plan

**Status:** Proposed implementation contract

**Date:** 2026-09-10

**Scope:** Intake Lab owner experience, Ada's strategy trace, staged live
preview, and the Intake Lab to provisioned-site transition.

**Authority:** This document is authoritative for the owner-facing Intake Lab
UI and its preview behavior. It does not replace the design-pipeline safety
rules in `AGENTS.md`, the native design-pipeline architecture in
`docs/simplify-design-pipeline-implementation-plan.md`, or the production
approval rules in `docs/owner-experience-implementation-plan.md`.

The owner-facing neural-network/cognition UI described in
`docs/intake-ada-cognition-dashboard-implementation-plan.md` is superseded by
this plan. Its durable research, deduction, and knowledge-storage work may be
reused; its canvas, neural animation, mind toggle, and decorative animation are
not part of the target experience.

---

## 1. Product decision

Intake Lab is the **unprovisioned state of the Admin experience**, not a
separate design-management application.

The owner should experience one continuous Ada workspace:

```text
conversation with Ada
  -> Ada researches and understands the business
  -> Ada builds a staged website
  -> owner sees the candidate
  -> owner asks Ada for changes when needed
  -> owner explicitly provisions the website
  -> the same workspace becomes website management
```

The UI must not expose the implementation vocabulary used to operate this
flow. In particular, the owner should not need to understand runs, revisions,
visual reviews, repair children, quality gates, provider names, or internal
pipeline stages.

The product has two owner-facing phases:

1. **Intake / BUILD** — Ada owns the work from the conversation through the
   staged candidate.
2. **Website ready / PROVISION** — the candidate is visible, the owner owns
   the decision, and `Provision website` is the explicit handoff.

`BUILD` is an Ada workflow action, not a second review dashboard. `PROVISION`
is the only primary business action exposed to the owner after a candidate is
ready.

---

## 2. Current problem

The current Intake Lab combines several incompatible experiences:

- a coral/white experimental shell that differs from the OceanicVibes Admin UI;
- a left-side chat column and a neural/canvas background;
- animated entrance, morph, orbital, and ambient effects;
- an `Ada's mind` toggle and cognition panel;
- visible review/refinement and feedback actions;
- visible run switching and version-oriented controls;
- operational build details mixed with owner-facing content;
- a candidate preview that becomes useful only after the build has completed.

The result asks the owner to operate the design pipeline instead of simply
talking with Ada and deciding whether to provision the resulting website.

---

## 3. Target owner experience

### 3.1 Shared OceanicVibes shell

Intake Lab and the provisioned Admin experience must use one visual system and
one spatial model:

- bright, minimal background;
- sea-green panels and borders;
- coral brand accent;
- Manrope for body/UI text;
- Cormorant Garamond for brand/display moments;
- DM Mono for compact trace labels and metadata;
- Ada's conversation rail on the **right** on desktop;
- preview canvas on the **left** and allowed to use the remaining viewport;
- the same header, spacing rhythm, border treatment, focus treatment, and
  responsive collapse in both phases.

The current Admin tokens are the starting source of truth:

```text
--bg:     #f6f8f4
--card:   #fffefa
--panel:  #eaf3f0
--line:   #c8d8d2
--text:   #132a28
--dim:    #607571
--accent: #0b6968
--brand:  #e75c48
--ok:     #16745e
--warn:   #99631d
--bad:    #b63f4b
```

The target desktop composition is:

```text
┌─────────────────────────────────────────────────────────────┐
│ Ada / site identity                         phase + status  │
├───────────────────────────────────────────────┬─────────────┤
│                                               │             │
│                                               │             │
│             full candidate preview           │  Ada chat   │
│             and live build surface            │  right rail │
│                                               │             │
│                                               │  strategy   │
│                                               │  trace      │
│                                               │             │
│                                               │  composer   │
│                                               │             │
│                                               │ Provision   │
│                                               │ website     │
└───────────────────────────────────────────────┴─────────────┘
```

The preview and Ada rail should be full-height rather than constrained inside
a decorative card. The viewport control belongs in the preview toolbar:

```text
Desktop   iPad   Mobile
```

These are presentation controls, not product-decision actions.

### 3.2 Remove from the owner-facing surface

Remove the following markup, behavior, and terminology from the normal Intake
Lab experience:

- neural-network canvas and synapse field;
- `Ada's mind` button and mind panel;
- entrance, morph, orbital, particle, glow, pulse, and ambient animations;
- `Initial review` and `Visual refinement` actions;
- `This fits`;
- `Small improvements`;
- `Redesign direction`;
- visible revision/run switchers;
- `New version`;
- visible quality-gate, visual-review, and repair statuses;
- visible provider/model identifiers;
- owner-facing developer drawers and raw activity controls;
- separate `Accept candidate` and `Activate customer Ada` actions in Intake Lab.

The send-message and attachment controls remain as conversation mechanics. The
only primary business CTA in the ready state is `Provision website`.

The removed concepts may remain available through internal diagnostics and
durable APIs. Removing them from the owner surface does not mean deleting the
durability, audit, or recovery boundary.

### 3.3 Responsive layout

- Desktop: preview main area plus right Ada rail.
- iPad: preview remains primary; Ada rail narrows without hiding the
  conversation or trace.
- Mobile: preview and Ada conversation stack into full-width regions; the
  composer remains reachable without requiring a decorative overlay.
- No horizontal overflow at 1440, 1024/768, or 390px representative widths.
- No animation is required to communicate a state transition.
- `prefers-reduced-motion` remains respected even though decorative motion is
  removed.

---

## 4. Two-phase state model

The UI needs a small public projection over the existing durable internal run
state. Internal statuses remain detailed; the owner-facing projection stays
simple.

### Phase 1 — Intake / BUILD

Ada owns the workflow:

1. Converse with the owner.
2. Extract and confirm the business, audience, offer, constraints, assets, and
   unknowns.
3. Research only where useful and permitted.
4. Record evidence-backed determinations and design implications.
5. Start `BUILD` once the confirmed intake is ready.
6. Update the staged preview at safe checkpoints.
7. Run objective host/browser validation before presenting the candidate.

The owner sees Ada's conversation, strategy trace, and the evolving staged
preview. The owner does not see review/refinement controls or technical run
states.

The public phase projection may be:

```text
intake        Ada is understanding the brief
building      Ada is building the website
ready         Candidate ready for you
blocked       Ada needs to resolve a technical problem
```

`blocked` is reserved for objective failures that make the candidate unsafe or
unusable, not for a subjective visual preference.

### Phase 2 — Website ready / PROVISION

Once the candidate is displayed:

- the displayed candidate is an immutable snapshot;
- Ada does not silently modify it;
- the owner owns the decision;
- the owner asks Ada for any desired changes through chat;
- an explicit change request starts another staged `BUILD` cycle;
- the prior displayed snapshot remains recoverable internally;
- `Provision website` provisions the candidate currently displayed.

The public projection may be:

```text
ready        Candidate ready for you
modifying    Ada is applying your requested changes
ready        Updated candidate ready
provisioning Provisioning your website
managed      Website ready to manage
```

Internal visual critiques may inform Ada's next response, but a subjective
`repair` result must not prevent the owner from seeing a technically valid
candidate or deciding that it is good enough. Objective build, asset, browser,
and runtime failures remain hard gates.

### 4.1 Explicit handoff contract

`Provision website` is the explicit owner approval boundary. The service must:

- verify that a candidate exists and has not been superseded;
- bind the operation to the exact displayed candidate SHA/content hash;
- record the owner approval and provisioning request durably;
- provision only through the existing application service boundary;
- never publish or mutate production implicitly;
- return a clear progress state that the same workspace can render.

The backend may retain separate accept, provision, and activation sub-states for
recovery. Intake Lab should present one owner action and one continuous
conversation, not those implementation steps.

---

## 5. Ada strategy trace

### 5.1 Purpose

Replace the neural background and generic work log with a quiet,
terminal-style **strategy trace**. It should show what Ada has learned and
concluded, not that a worker is copying files or entering pipeline stages.

The trace is an owner-facing explanation layer. It is not a raw provider
transcript and must not expose private chain-of-thought, hidden prompts,
secrets, token streams, or speculative ungrounded assertions.

### 5.2 Trace categories

The trace should support typed entries such as:

| Category | Purpose |
|---|---|
| `INTAKE` | Owner-provided facts and confirmed constraints. |
| `BUSINESS` | Ada's concise interpretation of the business and offer. |
| `AUDIENCE` | Audience facts, needs, and clearly labelled hypotheses. |
| `RESEARCH` | Research findings with source references and trust state. |
| `COMPETITION` | Sourced competitive observations; no invented market claims. |
| `DETERMINATION` | A conclusion Ada is using, with its basis and confidence. |
| `DECISION` | A design/content/positioning decision and its implication. |
| `QUESTION` | An unresolved point Ada needs the owner to answer. |
| `BUILD` | A concise user-relevant checkpoint such as preview availability. |
| `PREVIEW` | A new stable staged preview snapshot is available. |

Each visible entry should carry, where applicable:

- stable entry ID;
- category;
- concise summary;
- basis (`owner`, `research`, `inference`, or `system`);
- source IDs or citation URIs;
- confidence or trust state;
- related intake paths or design implications;
- creation time.

### 5.3 Data and contract rules

- Prefer existing durable records: intake facts, research sources/findings,
  deductions, genesis/creative insights, and design-run events.
- Add a normalized trace-entry contract only where existing records cannot carry
  the required category/source/confidence fields; do not create a second copy of
  every research record.
- Require Ada to emit concise structured rationale summaries when the advisor
  makes a material determination. The host must not manufacture thoughts from
  arbitrary strings or apply conversation heuristics to infer them.
- Research entries must link to the actual source record. A competitive claim
  without supporting evidence must be labelled as a hypothesis or omitted.
- Keep raw model transcripts and technical worker output in internal artifacts;
  they are not the trace data source.
- The same trace must be available to Ada's next turn so the owner can challenge
  a determination through conversation.

### 5.4 Rendering rules

- Terminal typography using the shared DM Mono face.
- Stable, readable rows with timestamp/category/source metadata.
- Append new entries without a typing animation, blinking cursor, glow, or
  auto-moving canvas.
- Keep the latest relevant entries visible while retaining scrollback.
- Do not auto-scroll if the owner has intentionally scrolled upward.
- Use `aria-live="polite"` for new trace summaries without announcing every
  low-level event.
- On mobile, keep the trace below the conversation or as a full-width section;
  do not replace it with a second hidden toggle.

---

## 6. Live staged preview

The visual simplification is only successful if Ada can update the website
continuously while she works. The current candidate-only preview contract is
not sufficient for that behavior.

### 6.1 Preview lifecycle

```text
confirmed intake
  -> isolated staging worktree
  -> Ada changes files
  -> safe checkpoint
  -> host creates a stable live-preview snapshot
  -> trace records PREVIEW
  -> iframe reloads the newest snapshot
  -> final candidate is retained and frozen
```

Live preview means **checkpoint-level live updates**, not serving a partially
written worktree or exposing every keystroke. A checkpoint is created only when
the workspace can be safely rendered.

### 6.2 Snapshot safety

- Never serve the mutable worktree directly.
- Create each live snapshot atomically in the isolated Intake Lab workspace.
- Give every snapshot a content hash and creation event.
- Keep the last known-good snapshot if the newest checkpoint fails to build.
- Do not replace a stable displayed candidate with a broken partial render.
- Keep preview tokens scoped to the incubation, run, and live/candidate variant.
- Preserve the sandboxed iframe and same-prefix asset/CSS rewriting rules.
- Keep production, GitHub, Cloudflare, R2, and customer credentials outside the
  live-preview process.

### 6.3 Event delivery

Reuse the durable activity/run-event projection and current bounded polling
before introducing a new streaming transport. The UI should refresh quickly
enough to feel live while remaining recoverable after reloads or worker restarts.

Add explicit event kinds for:

- strategy trace entry persisted;
- build checkpoint started/completed;
- live-preview snapshot available;
- live-preview build failed while retaining the previous snapshot;
- candidate frozen;
- owner-requested modification started/completed;
- provisioning started/completed/failed.

If polling cannot meet the observed latency target, add SSE as a narrow event
stream over the same durable cursor contract. Do not introduce a WebSocket or a
second ephemeral source of truth merely for animation.

### 6.4 Candidate handoff

When BUILD completes:

- stop mutating the displayed candidate;
- retain the exact candidate SHA and preview identity;
- switch the public state to `ready`;
- leave the trace available for the owner to review;
- enable `Provision website` only when objective gates pass.

An owner-requested change creates a new staged build identity. The UI may show
the new live preview when available, but the backend retains the previous
candidate for recovery without exposing a version browser.

---

## 7. Provisioned continuity

Intake Lab and the provisioned Admin experience should share a shell rather
than navigate between visibly unrelated applications.

### Before provisioning

- Main canvas: staged live website preview.
- Right rail: Ada conversation plus strategy trace.
- Toolbar: Desktop / iPad / Mobile.
- Primary action: `Provision website` when eligible.

### After provisioning

- Main canvas: managed website or managed website preview.
- Right rail: same Ada conversation and trace history.
- Existing chat context remains attached to the site.
- Site-management options appear progressively in the same shell.
- Technical settings and detailed lifecycle history remain progressive
  disclosure, not default Intake Lab content.

The transition should preserve the selected viewport, conversation context, and
visual language. It may update the route and data context, but it must not feel
like a handoff to a different product.

---

## 8. Implementation phases

### Phase 0 — Freeze the product contract

- [ ] Record the two public phases: Intake/BUILD and Website ready/PROVISION.
- [ ] Define the owner projection separately from internal design-run statuses.
- [ ] Define the exact displayed candidate identity used by provisioning.
- [ ] Decide which existing durable research/deduction records feed the trace.
- [ ] Keep the confirmed-intake and production-approval invariants unchanged.

Acceptance: a product decision can be described without mentioning review,
refinement, revision, or provider terminology.

### Phase 1 — Establish the shared OceanicVibes shell

- [ ] Extract shared OceanicVibes tokens and shell rules from
      `src/site_agent/web/static/admin.html`.
- [ ] Make `intake_lab.html` use the same tokens, fonts, right-side Ada rail,
      borders, focus states, and responsive layout.
- [ ] Prefer one reusable static stylesheet/asset route over copying divergent
      token blocks into both HTML files.
- [ ] Make the preview and Ada rail fill the available viewport.
- [ ] Add Desktop / iPad / Mobile controls to the preview toolbar.

Acceptance: Intake and Admin share the same visual shell at desktop, iPad, and
mobile widths, with the Ada rail on the right at desktop widths.

### Phase 2 — Remove the neural and review UI

- [ ] Remove the canvas, synapse/orbital renderer, `Ada's mind` control, and
      all associated animation/morph code.
- [ ] Remove review/refinement/feedback/version controls from the owner surface.
- [ ] Remove visible technical status vocabulary and provider metadata.
- [ ] Keep only conversation mechanics and the eventual `Provision website`
      action.
- [ ] Preserve internal APIs and durable records needed for diagnostics,
      recovery, and the post-provision lifecycle.

Acceptance: the normal owner surface contains no neural canvas, mind button,
review/refinement button, run switcher, or visible version browser.

### Phase 3 — Implement the strategy trace

- [ ] Define the typed trace-entry contract and source/confidence rules.
- [ ] Project existing research, deductions, intake, and determination data into
      the trace without duplicating source records.
- [ ] Extend Ada's advisor/build boundary to persist concise rationale summaries
      as typed records.
- [ ] Render the trace in a static terminal-style panel with scrollback and
      accessible live updates.
- [ ] Keep raw transcripts and technical worker events internal.

Acceptance: a real intake displays evidence-backed business, audience,
research, competition, determination, and design-decision entries without
exposing private chain-of-thought or unsupported claims.

### Phase 4 — Add checkpointed live preview

- [ ] Define live-preview snapshot identity and retention rules.
- [ ] Add a safe snapshot builder that never serves the mutable worktree.
- [ ] Extend the local preview route/contract with a scoped live variant, or an
      equivalent exact-hash snapshot mechanism.
- [ ] Emit durable checkpoint and preview events from the design worker.
- [ ] Refresh the iframe when a new stable snapshot is available.
- [ ] Retain the last known-good preview after a failed checkpoint.
- [ ] Freeze the candidate when BUILD completes.

Acceptance: during a real build, the owner sees multiple meaningful preview
updates and corresponding trace entries, with no broken partial page, leaked
credential, production mutation, console error, or failed asset request.

### Phase 5 — Implement the provision handoff

- [ ] Remove separate owner-facing accept/activate controls from Intake Lab.
- [ ] Make `Provision website` the single explicit owner handoff.
- [ ] Bind provisioning to the exact candidate displayed when the action is
      submitted.
- [ ] Preserve backend sub-states for recovery without exposing them as UI
      phases.
- [ ] Reuse the same shell after provisioning and progressively reveal managed
      website options.

Acceptance: provisioning cannot occur without an explicit owner action, and the
provisioned workspace preserves the Ada conversation and visual context.

### Phase 6 — Modification loop

- [ ] Route requests such as visual, copy, audience, or strategy changes through
      Ada chat rather than special-purpose buttons.
- [ ] Have Ada create a new staged BUILD identity for an explicit request.
- [ ] Keep the currently displayed candidate stable until the new one is ready.
- [ ] Return to `Website ready` after the updated candidate is displayed.
- [ ] Keep prior snapshots internal for recovery without showing version history.

Acceptance: an owner can request a small improvement entirely through chat,
observe the staged update, and decide whether to provision it.

### Phase 7 — Verification and cleanup

- [ ] Rewrite `tests/test_intake_cognition_ui.py` to assert the absence of the
      neural/mind UI and the presence of the strategy trace.
- [ ] Rewrite `tests/test_intake_lab_preview_ui.py` for the shared shell,
      viewport controls, two-phase projection, and live preview behavior.
- [ ] Update `tests/test_intake_lab_web.py` for live-preview authorization,
      phase projection, and the single provisioning handoff.
- [ ] Add contract tests for typed trace entries, source linkage, confidence,
      and unsupported-claim handling.
- [ ] Add live-build tests for atomic snapshot replacement and last-known-good
      fallback.
- [ ] Add browser checks at 1440px desktop, 768px iPad, and 390px mobile.
- [ ] Verify no decorative animations, canvas loops, console errors, failed
      module/asset requests, horizontal overflow, or inaccessible trace updates.
- [ ] Run focused tests, the full test suite, `compileall`, wheel build, and
      `git diff --check`.
- [ ] Live-verify the complete path from confirmed intake through BUILD,
      displayed candidate, chat-requested modification, and explicit PROVISION.

---

## 9. Relevant implementation surfaces

### UI

- `src/site_agent/web/static/intake_lab.html`
  - replace the current neural/experimental layout;
  - render the shared shell, right Ada rail, strategy trace, preview toolbar,
    and two-phase public state.
- `src/site_agent/web/static/admin.html`
  - source and destination for the shared OceanicVibes shell patterns;
  - keep management options appearing after provisioning.
- `src/site_agent/web/server.py`
  - serve any shared static shell asset without changing public admin paths.
- `src/site_agent/web/intake_lab.py`
  - serve the same shell assets, phase projection, live-preview route, and
    scoped preview authorization.

### Ada, trace, and persistence

- `src/site_agent/brain/design_intake.py`
  - typed strategy/rationale output rules and owner conversation context.
- `src/site_agent/application/intake_lab.py`
  - public phase projection, activity/trace projection, and live preview state.
- `src/site_agent/application/incubations.py`
  - durable incubation/provisioning boundary and owner-requested updates.
- `src/site_agent/core/memory.py`
  - reuse existing durable records; add a migration only if the trace contract
    cannot be represented without one.
- `src/site_agent/core/design_contracts.py`
  - typed trace, snapshot, and public phase contracts where appropriate.

### Build and preview

- `src/site_agent/application/design_jobs.py`
  - checkpoint events, worker recovery, and candidate freeze boundary.
- `src/site_agent/application/designs.py`
  - retained candidate identity, objective validation, and preview snapshots.
- `src/site_agent/hands/opencode_runner.py`
  - meaningful Ada/build progress callbacks and safe staging checkpoints.
- `src/site_agent/web/preview.py`
  - exact-hash live/candidate snapshot serving and nested asset rewriting.

---

## 10. Non-goals

- Do not expose raw private chain-of-thought or provider transcripts.
- Do not manually edit or polish a run-specific candidate in application code.
- Do not make the owner operate review/refinement/version controls.
- Do not serve mutable worktrees directly to the browser.
- Do not add a frontend framework or a separate real-time infrastructure stack
  before the durable polling/checkpoint path is measured.
- Do not change production or provision a customer site without the explicit
  `Provision website` action.
- Do not delete internal run history, candidate refs, research evidence, or
  recovery artifacts merely because they are hidden from Intake Lab.

---

## 11. Final acceptance checklist

- [ ] The owner sees one OceanicVibes workspace from Intake through management.
- [ ] Ada's rail is on the right on desktop and remains usable on mobile.
- [ ] The preview occupies the main canvas and supports Desktop / iPad / Mobile.
- [ ] The neural network, mind button, decorative animations, review buttons,
      feedback buttons, and visible version history are gone.
- [ ] The terminal trace shows real, source-linked business, audience, research,
      competition, determination, and design-decision summaries.
- [ ] No raw private chain-of-thought, secrets, or unsupported claims are shown.
- [ ] Ada updates the staged preview at safe build checkpoints.
- [ ] A failed live checkpoint keeps the last known-good preview visible.
- [ ] A displayed candidate remains stable until the owner explicitly requests a
      change through chat.
- [ ] `Provision website` is the only primary business action.
- [ ] Provisioning is bound to the exact displayed candidate and remains
      approval-gated.
- [ ] After provisioning, management options appear in the same shell without a
      jarring product switch.
- [ ] Focused tests, full tests, compile, wheel build, browser checks, reduced
      motion checks, and production-safety checks pass.
