# Simple Owner-Surface GSAP Pipeline Implementation Plan

## Status and authority

**Status:** Proposed focused execution addendum.

**Purpose:** Simplify the confirmed-intake-to-owner-review path and make
generated GSAP behavior reliable, observable, and fast enough for the product's
approximately 20-minute promise.

This document implements the mission and acceptance requirements in
`docs/brand-composition-and-behavior-system-implementation-plan.md`. That
document and `AGENTS.md` remain authoritative. If this plan appears to weaken
integrated realization, observable experience fidelity, candidate isolation,
owner review, or production approval safety, stop and follow the authoritative
document.

This plan consolidates the useful simplification work described in
`docs/design-pipeline-simplification-implementation-plan.md` and
`docs/simplify-design-pipeline-implementation-plan.md`. Those documents are
historical inputs, not additional phase lists to execute in parallel.

## 1. Problem statement

The recurring failure is not that Ada cannot write GSAP. Ada has repeatedly
generated GSAP and ScrollTrigger source that builds. The failure is that the
host cannot reliably answer the only product-relevant question:

> Did the exact candidate shown to the owner visibly perform its defining
> behavior after hydration?

The current path answers several weaker questions instead:

- Does source contain a GSAP-shaped call?
- Is a package approved?
- Does `window.gsap` exist?
- Was an animation active at one sampled instant?
- Did candidate-authored metadata say a behavior was observed?
- Did a static visual reviewer receive a field saying motion passed?

None proves owner-visible motion. This allows contradictory outcomes: static or
broken behavior can pass an internal motion gate, while valid module-scoped GSAP
can be reported absent.

The first broken boundary is:

```text
confirmed intake -> Ada direction -> Ada integrated generation -> build
  -> deterministic validation -X-> visual/behavioral review -> owner review
```

There is also an artifact-identity risk. Candidate authoring, validation,
preview rebuilding, live checkpoints, and owner display can operate on different
directories or commits. A successful test of one tree is not evidence for the
tree in the Design iframe.

## 2. Product outcome

One confirmed intake should produce this path:

```text
confirmed intake + approved media
  -> exact-SHA disposable worktree
  -> Ada design direction (read-only, concise)
  -> Ada integrated build (writable; layout + content + GSAP + reduced motion)
  -> host build once
  -> immutable output artifact bound to candidate SHA
  -> host opens the real owner review surface
  -> host observes hydration + visible behavior + reduced motion
  -> optional one Ada repair using those observations
  -> host repeats the same build and observation
  -> owner Design review
  -> explicit owner approval or decline
```

Target model turns:

| Stage | Normal path | Repair path |
|---|---:|---:|
| Ada direction | 1 | 1 |
| Ada integrated build | 1 | 1 |
| Ada objective repair | 0 | at most 1 |
| Automated visual review | at most 1 | at most 1 after repair |
| **Total authoring/review turns** | **2-3** | **3-4** |

Target elapsed time:

| Stage | Budget |
|---|---:|
| Direction | <= 2 minutes |
| Integrated build | <= 10 minutes |
| Host build and owner-surface probe | <= 3 minutes |
| Optional repair | <= 4 minutes |
| Final verification and review preparation | <= 2 minutes |
| **Total** | **about 20 minutes** |

## 3. Non-negotiable invariants

- Ada, not the coding agent, creates and repairs run-specific candidates.
- The integrated build owns composition, responsive behavior, motion, and
  reduced motion together. Motion is not decoration added after design.
- Critical content is visible in HTML/CSS before JavaScript runs.
- Production never changes without explicit owner approval.
- Every run is pinned to an exact base SHA and every candidate is retained as an
  immutable commit/ref.
- Validation and owner review consume the same immutable output artifact.
- The browser probe uses the actual Design/Intake Lab owner route, mount point,
  token rewriting, headers, and iframe sandbox.
- Console errors and failed module, font, image, or asset requests are failures.
- Missing browser evidence is `incomplete`, never `passed`.
- Source, a manifest, a model reply, a marker, or an internal status cannot prove
  animation.
- Reduced motion preserves content and meaning without nonessential spatial or
  continuous motion.
- Autonomous repair is bounded to one child. It never recursively spawns repair
  children.
- Static visual review evaluates static visual quality. It does not certify
  temporal behavior from a still image.

## 4. Simplicity rules

Reject any implementation that adds another creative phase, reviewer, plan
schema, coverage map, or candidate-authored pass signal.

The host keeps only responsibilities a model cannot safely own:

1. durable jobs and state;
2. exact-SHA worktree isolation;
3. permissions, secrets, and changed-path policy;
4. authoritative build;
5. immutable artifact identity;
6. real-browser observation;
7. preview delivery;
8. owner approval and production mutation.

Ada owns:

1. design direction;
2. integrated source implementation;
3. GSAP behavior and cleanup;
4. responsive translation;
5. reduced-motion translation;
6. one focused repair when host evidence proves an objective defect.

## 5. Target contracts

Keep contracts small and factual.

### 5.1 Direction artifact

Persist one human-readable Markdown artifact produced by the read-only direction
turn. It should contain the concept, composition intent, defining visitor
experience, signature behavior, and reduced-motion intent. It is guidance and
audit evidence, not a strict JSON gate.

### 5.2 Candidate receipt

Keep the existing immutable candidate identity and add only the output identity
needed to prove artifact equivalence:

- candidate SHA;
- build profile;
- immutable output artifact ID;
- output tree hash;
- author transcript ID;
- optional repair transcript ID.

### 5.3 Browser behavior evidence

Use one compact host-owned record per route and viewport:

- candidate SHA and output artifact ID;
- exact owner review URL identity;
- viewport and reduced-motion preference;
- hydration/module request results;
- console and failed-request results;
- before/intermediate/after frame hashes;
- sampled element/pixel deltas;
- completion-state visibility;
- elapsed probe time.

Do not add journey IDs, coverage maps, candidate-authored completion states, or
model-authored `passed` fields.

An optional `data-ada-motion-target` attribute may help the host locate the main
behavior. It is a locator only. It cannot assert that behavior occurred. The host
must still measure a visible change. The probe must also detect motion without
this optional locator so creative source is not forced into a schema.

## 6. GSAP authoring standard

The integrated Ada build prompt receives the installed GSAP, GSAP React,
ScrollTrigger, and performance skills. Keep the host prompt short; do not copy
the skills into a second host-authored animation specification.

### 6.1 Visible by default

Generated source must follow progressive enhancement:

- Public text, navigation, controls, and conversion content are visible in the
  server-rendered HTML/CSS state.
- Do not use `.js [data-*] { opacity: 0 }`, `visibility: hidden`, or equivalent
  author CSS to pre-hide critical content.
- After client hydration, GSAP may establish an initial state with `gsap.set()`
  and immediately play toward the visible state.
- If initialization fails, the page remains usable and readable.
- If an intro is interrupted or killed, cleanup restores the complete visible
  state.

This eliminates the recurring failure where a `from()`/`fromTo()` tween and
pre-hidden CSS combine into a hidden-to-hidden animation.

### 6.2 Astro and React hydration

- Any React component that owns GSAP must be mounted with an appropriate Astro
  client directive, normally `client:load` for first-viewport behavior.
- Use `useGSAP()` from `@gsap/react` with a scoped ref.
- Register `useGSAP` and `ScrollTrigger` before use.
- Keep selectors scoped to the component/root.
- Cleanup must revert the GSAP context and remove custom listeners.
- Refresh ScrollTrigger after fonts and relevant images finish loading.
- No animation code runs during server-side rendering.

A runtime-ready signal may be used only as a wait hint for the host. It is not
acceptance evidence.

### 6.3 Timeline correctness

- Use timelines for coordinated sequences rather than delay chains.
- Prefer explicit `fromTo()` states when the natural end state is ambiguous.
- Do not stack multiple immediate-render `from()`/`fromTo()` tweens on the same
  target/property. Use `immediateRender: false` where appropriate.
- End states for critical content must be explicit: readable opacity,
  visibility, and transform.
- Prefer transforms and opacity over layout properties.
- Store timeline/tween references when playback control is required.

### 6.4 ScrollTrigger correctness

- Put ScrollTrigger on the top-level tween or timeline, not nested child tweens.
- Use progressive scroll behavior that can be exercised with normal wheel/touch
  input; do not depend on a single exact pixel threshold.
- Use `ease: "none"` for scrubbed progress and container animations.
- Create triggers in page order and refresh after layout-affecting assets load.
- Pin a stable wrapper and animate a child rather than animating the pinned
  element itself.
- Kill/revert all triggers on teardown.

### 6.5 Reduced motion

- Use `gsap.matchMedia()` or equivalent client media-query handling.
- The reduced branch establishes the completed visible state immediately.
- No nonessential spatial, pinned, scrubbed, looping, or continuous animation
  remains under `prefers-reduced-motion: reduce`.
- Conceptual hierarchy may be preserved through static contrast, composition,
  color, or instantaneous state changes.

## 7. Host observation: test behavior, not GSAP internals

Delete acceptance dependence on `window.gsap`, `window.ScrollTrigger`, active
tween counts, source regexes, or `Element.getAnimations()`. Bundled ESM GSAP is
normally module-scoped, and completed animations correctly report no active
tweens.

### 7.1 Exact observation surface

Playwright must open the owner-facing Design/Intake Lab page and inspect its
preview iframe. It must not substitute a temporary static server.

The tested surface includes:

- deployment mount point (`/ada/` where configured);
- preview token lifecycle and propagation;
- HTML, CSS, and JavaScript rewriting;
- iframe `sandbox` attributes;
- response CSP/CORS headers;
- the exact immutable output artifact selected by the UI.

### 7.2 Readiness

Before motion sampling, wait for bounded, observable readiness:

1. document load;
2. required stylesheets;
3. font readiness;
4. critical image decode;
5. Astro islands no longer waiting for hydration;
6. one animation frame after readiness.

Record every requested module and its response. A timeout, failed island, or
missing bundle is `incomplete`.

### 7.3 Page-load motion probe

For first-viewport motion:

1. begin frame/style sampling before hydration completes;
2. sample at several bounded intervals, for example every animation frame with
   retained checkpoints near 0, 100, 250, 500, 900, and 1500 ms;
3. record viewport screenshots or focused crops at before, intermediate, and
   settled states;
4. measure changes in bounding rectangle, transform matrix, opacity, clip path,
   filter, relevant SVG attributes, and pixel regions;
5. verify the settled state leaves critical content visible.

Do not fail merely because the animation has completed by 1800 ms.

### 7.4 Scroll and interaction probe

- Scroll progressively through the page in small requestAnimationFrame-driven
  increments rather than jumping only to top, middle, and bottom.
- Sample during motion and after scrub catch-up.
- Exercise the real primary control and any explicit signature control, not the
  first six generic buttons.
- Cover pointer, keyboard, and touch only when the actual behavior uses them.
- Restore state between probes.
- Capture before/intermediate/after evidence for the specific trigger.

### 7.5 Objective pass conditions

When the confirmed direction requires motion, browser behavior passes only when:

- the candidate's JavaScript and hydration modules load successfully;
- the host observes a meaningful visible delta during the declared load,
  scroll, or interaction window;
- the behavior reaches a stable completion/resting state;
- critical content remains readable after completion;
- the same behavior is exercised at desktop, tablet, and mobile with an
  appropriate responsive translation;
- a fresh reduced-motion context presents the complete visible state without
  prohibited motion;
- no console, module, asset, or network failure occurs.

Pixel change alone is not sufficient when caused by a cursor, caret, clock,
video, or unrelated ambient loop. Combine frame difference with DOM/SVG style or
geometry trajectories and retain the evidence for diagnosis.

The host may objectively say `motion_observed: true|false`. It must not claim
that the motion is tasteful, original, or emotionally effective. That remains a
visual/owner judgment.

## 8. Build and preview identity

### 8.1 Build once

After Ada's source turn:

1. retain the candidate commit/ref;
2. check out the exact candidate SHA;
3. run the authoritative host build once using the approved shared cache and
   timeout;
4. copy the generated output to a content-addressed immutable artifact store;
5. hash the complete output tree;
6. bind artifact ID and tree hash to the run.

Validation and preview read this artifact. They do not independently rebuild the
candidate under different caches or timeouts.

### 8.2 Candidate is the review source

- A completed candidate always uses the immutable candidate artifact.
- The UI must not prefer a separately copied `live` checkpoint over a completed
  candidate.
- Remove post-validation live checkpoints from the acceptance path.
- If in-progress previews remain, label them clearly as non-reviewable and bind
  them to an explicit source worktree/ref. They disappear when a candidate is
  retained.
- A snapshot's run ID alone is insufficient. Any retained preview identity must
  include the candidate SHA or source worktree identity it represents.

### 8.3 Preview delivery

- Rewrite every generated module/asset reference needed by the supported Astro
  output, including absolute imports, `srcset`, workers, and `new URL(...,
  import.meta.url)` where applicable.
- Token expiry must not break an already-open owner review during the intended
  review window.
- Preview build/delivery errors retain structured diagnostics instead of
  becoming undifferentiated 404 responses.
- Add an end-to-end fixture proving a hydrated Astro island and local GSAP chunk
  load inside the real sandbox.

## 9. One repair operation

Collapse `technical_repair`, autonomous host-evidence repair, and visual
refinement plumbing into one durable child operation, tentatively named
`revision`. Preserve historical operation kinds for reading old records only.

The new operation has factual provenance:

- `source = owner_feedback | objective_validation`;
- parent run ID and candidate SHA;
- concise owner feedback or host observations;
- before/intermediate/after evidence references;
- attempt number.

Rules:

- Objective validation may create at most one automatic revision.
- Owner feedback may create a later revision only through an explicit owner
  action.
- The revision prompt always describes a focused edit of the retained parent.
  It never receives from-scratch homepage instructions.
- The same integrated Ada build agent owns motion repairs. Do not route a GSAP
  defect through a generic technical path that skips motion skills.
- The revised candidate repeats build-once and exact-owner-surface validation.
- A failed revision stops as `needs_repair` or `incomplete`; it never nests
  another automatic revision.

## 10. Static visual review

Keep one sighted review after objective owner-surface behavior passes, or make it
advisory if product policy permits. Remove duplicate review implementations.

- Send viewport-sized high-detail captures or legible crops, not only tall
  low-detail full-page thumbnails.
- Include labeled before/intermediate/after frames for context, but do not ask a
  still-image reviewer to certify timing or hydration.
- Do not tell the reviewer that motion passed. Provide measurements as data.
- Review composition, hierarchy, typography, image treatment, responsive
  translation, readability, and conversion integration.
- A visual reviewer cannot override a failed browser observation.
- Owner judgment remains authoritative for taste and creative preference.

## 11. Code removal and consolidation

Deletion is required, not optional cleanup.

### Remove from acceptance logic

- GSAP source regexes as proof of behavior;
- `window.gsap`/`window.ScrollTrigger` as required runtime evidence;
- active-animation counts as motion success;
- candidate-authored `data-ada-behavior-observed` and journey completion claims;
- static transforms as proof that a transition occurred;
- generic first-six-controls interaction probing;
- strict experience/journey coverage JSON in creative-mode acceptance;
- separate post-hoc motion and fidelity phase machines;
- duplicate visual critique helpers;
- automatic sighted-self-review variants that overlap the single review path;
- completed-candidate `live` checkpoint preference;
- separate preview rebuilds of already-built immutable artifacts;
- duplicate repair creators and operation-specific prompt branches.

### Keep

- durable run/job records;
- exact-SHA worktrees;
- candidate commit/ref retention;
- media and font materialization;
- changed-path, secret, dependency, and production-safety checks;
- authoritative host build;
- owner-surface Playwright adapter;
- immutable screenshots and behavior evidence;
- one revision creator;
- explicit owner approval service.

### Desired end state

New confirmed-intake runs use one orchestration path, one build implementation,
one browser adapter, one static visual reviewer, and one revision operation.
Legacy data remains readable but cannot select obsolete behavior for new runs.

## 12. Implementation phases

### Phase 0 — Freeze the acceptance fixture and baseline

- [ ] Retain the confirmed Claro Oscuro intake, approved assets, and original
      candidate identities as immutable evidence.
- [ ] Record current model-turn count, wall time, Python pipeline LOC, prompt
      sizes, and owner-visible failure.
- [ ] State observable acceptance in owner terms: the light/dark cave experience
      visibly responds during load/scroll and remains meaningful under reduced
      motion.
- [ ] Prohibit manual candidate edits during all acceptance runs.

Acceptance: one operation starts from the confirmed intake, and one final owner
surface is identified before implementation begins.

### Phase 1 — Unify output and preview identity

- [ ] Add immutable built-output storage keyed by candidate SHA, profile, and
      output tree hash.
- [ ] Make deterministic validation consume that artifact.
- [ ] Make candidate preview consume that same artifact.
- [ ] Stop completed candidates from preferring `live` snapshots.
- [ ] Preserve structured preview delivery errors.
- [ ] Add an identity test from candidate SHA through iframe bytes.

Acceptance: hash the JavaScript bundle served to Playwright and to the owner
iframe; the bytes and artifact ID match.

### Phase 2 — Validate the real owner surface

- [ ] Replace `_ArtifactServer` acceptance with navigation through the real
      Design/Intake Lab route and iframe sandbox.
- [ ] Record module, font, image, and stylesheet requests.
- [ ] Wait for bounded hydration readiness.
- [ ] Implement page-load and progressive-scroll frame/style sampling.
- [ ] Implement reduced-motion in a fresh context.
- [ ] Make absent required motion, hidden completion content, hydration failure,
      or failed assets blocking/incomplete outcomes.

Acceptance: a fixture with valid GSAP visibly passes; a fixture with GSAP source
but an unhydrated Astro island fails; a hidden-to-hidden tween fails.

### Phase 3 — Ship the integrated Ada authoring path

- [ ] Use one concise read-only direction turn.
- [ ] Use one writable integrated build turn with design and motion skills.
- [ ] Remove the automatic post-hoc motion specialist from new runs.
- [ ] Enforce the visible-by-default and reduced-motion authoring rules in the
      prompt without prescribing a visual recipe.
- [ ] Persist authoring transcripts and final candidate identity.
- [ ] Treat no repository delta, missing hydration, or required behavior absence
      as failure/incomplete.

Acceptance: the confirmed intake reaches a retained integrated candidate in two
Ada turns before host review.

### Phase 4 — Collapse repair and review

- [ ] Implement one `revision` service path and migrate all new repair/refinement
      triggers to it.
- [ ] Route objective failures with exact evidence to one bounded Ada repair.
- [ ] Ensure repair prompts always preserve and inspect the retained parent.
- [ ] Keep one static visual review implementation and remove motion verdicts
      from it.
- [ ] Remove old operation-kind routing for new runs while retaining historical
      read compatibility.

Acceptance: one objective failure creates one revision; a failed revision cannot
create another automatic revision.

### Phase 5 — Delete obsolete machinery

- [ ] Remove strict creative/journey contracts no longer consumed by the new
      path.
- [ ] Remove specialist Python phase orchestration and related configuration.
- [ ] Remove proxy motion gates and candidate-authored observed-state logic.
- [ ] Remove completed-run live checkpoint plumbing.
- [ ] Remove duplicate tests that validate deleted schemas rather than behavior.
- [ ] Record before/after LOC, prompt size, turn count, and elapsed time.

Acceptance: no new run can enter an obsolete orchestration or repair path, the
full suite is green, and pipeline code/prompt size is materially smaller.

### Phase 6 — End-to-end acceptance

- [ ] Rerun Ada from the confirmed Claro Oscuro intake.
- [ ] Confirm the candidate was authored autonomously.
- [ ] Confirm the defining cave/light/dark behavior is visibly present.
- [ ] Observe it through the actual owner Design surface at desktop, tablet, and
      mobile.
- [ ] Observe the meaning-preserving reduced-motion state.
- [ ] Confirm zero console/module/font/image/asset failures.
- [ ] Confirm the validated and displayed artifact identities match.
- [ ] Confirm elapsed time is compatible with approximately 20 minutes.
- [ ] Confirm production remained unchanged.

Acceptance: the owner can see and exercise the behavior without reading source,
internal metadata, or developer notes.

## 13. Concrete change map

| Concern | Primary locations |
|---|---|
| Thin direction + integrated build | `hands/opencode_runner.py`, `hands/builder.py` |
| Remove Python specialist orchestration | `application/design_orchestration.py`, `hands/opencode_provider.py` |
| One revision lifecycle | `application/designs.py`, `application/design_jobs.py`, `application/incubations.py`, `application/intake_lab.py` |
| Immutable output artifact | `hands/site_build.py`, `web/preview.py`, `core/design_contracts.py`, `core/memory.py` |
| Exact owner-surface browser probe | `hands/playwright_quality.py`, `web/intake_lab.py`, `web/server.py` |
| Objective gate aggregation | `hands/design_quality.py` |
| Static visual review only | `hands/design_visual_review.py` |
| Candidate-first Design UI | `web/static/intake_lab.html`, `web/static/admin.html` |
| Runtime configuration | `config.py`, `defaults.yaml`, `intake-ada.yaml` |
| End-to-end fixtures | `tests/test_preview.py`, `tests/test_playwright_quality.py`, `tests/test_design_quality.py`, `tests/test_design_jobs.py` |

## 14. Required tests

### Unit and contract tests

- output artifact identity rejects a candidate/artifact mismatch;
- reduced-motion context starts with critical content visible;
- hidden resting text is blocking after bounded hydration/settle;
- candidate-authored observed flags cannot produce a pass;
- module-scoped GSAP does not require `window.gsap`;
- one revision cannot spawn a second automatic revision;
- technical/visual/motion requests use the same revision prompt contract;
- historical operation kinds remain readable but cannot be created by new APIs.

### Browser fixtures

Create small real Astro/React fixtures using pinned local dependencies:

1. hydrated `useGSAP()` page-load timeline that passes;
2. same source without `client:load` that fails hydration/motion;
3. CSS-pre-hidden + broken tween that fails resting visibility;
4. ScrollTrigger scrub behavior that passes progressive scrolling;
5. reduced-motion branch that is visible and stationary;
6. reduced-motion branch that incorrectly animates and fails;
7. broken nested chunk or asset URL that fails through preview rewriting;
8. candidate artifact and stale live snapshot where the UI must select the
   candidate.

Each fixture must run through the real review endpoint and iframe sandbox, not a
test-only static server.

### End-to-end acceptance test

The test starts with a confirmed intake and waits for a reviewable candidate. It
asserts:

- Ada model provenance exists for direction and implementation;
- no manual mutation occurred;
- candidate and output artifact identities are bound;
- the owner iframe loads the same artifact;
- no console/module/asset failures occur;
- normal-motion frames contain a host-observed visible delta;
- completion content is visible;
- reduced-motion frames are complete and stationary;
- no production mutation occurred.

## 15. Verification commands

Run focused tests after each phase, then:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
```

Also record for the real acceptance run:

- run ID and candidate SHA;
- output artifact ID/hash;
- direction/build/repair model and transcript IDs;
- model-turn count;
- per-stage and total elapsed time;
- exact owner review route;
- requested JavaScript module list and failures;
- before/intermediate/after evidence at every required viewport;
- reduced-motion evidence;
- production mutation count, expected to be zero.

## 16. Rollout and rollback

Use replace-first migration:

1. implement immutable artifact delivery and owner-surface probing behind the
   current lab configuration;
2. prove the probe with real fixtures;
3. add the thin integrated authoring path;
4. run the frozen acceptance intake;
5. switch new runs to the thin path;
6. delete obsolete paths in the same implementation effort;
7. retain only historical record readers.

Rollback switches new runs back before removing old code only if the new path
cannot retain immutable candidates safely. Do not roll back merely because a
candidate fails creative acceptance; fix the earliest generic pipeline boundary
and rerun Ada.

## 17. Definition of done

- [ ] Ada produces a candidate from confirmed intake through one direction turn
      and one integrated build turn.
- [ ] GSAP behavior is part of integrated realization, not a post-hoc decoration
      pass.
- [ ] Critical content is visible without JavaScript and after every animation.
- [ ] Validation and owner review use the same immutable output bytes.
- [ ] The browser exercises the actual owner iframe after hydration.
- [ ] Required motion is accepted only from host-observed visible deltas.
- [ ] Desktop, tablet, mobile, and reduced-motion behavior are exercised.
- [ ] Console/module/asset failures prevent review readiness.
- [ ] At most one autonomous Ada revision is possible.
- [ ] Static visual review no longer pretends to certify motion.
- [ ] Specialist phase machinery, proxy motion gates, duplicate repair paths,
      and completed-run live checkpoint preference are removed.
- [ ] The new path meets the approximately 20-minute target.
- [ ] The complete candidate is available in the Design review flow.
- [ ] Production remains unchanged until explicit owner approval.

## 18. End-of-task mission questions

Answer after every implementation phase and every acceptance run:

1. Did Ada—not the coding agent—create the candidate from the confirmed intake?
2. Did the candidate visibly follow the defining experience/adventure path?
3. Was that behavior observed in the real owner review surface after hydration?
4. Did any workaround bypass the autonomous pipeline?
5. Is the result honestly ready for owner feedback within the intended journey?

Any `no` means the product mission is incomplete.
