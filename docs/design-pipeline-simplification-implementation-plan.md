# Design Pipeline Simplification & Fidelity Repair Implementation Plan

Status: proposed
Audience: the coding agent implementing this work
Authority: this plan implements the four required outcomes of
`docs/brand-composition-and-behavior-system-implementation-plan.md` (integrated
realization, experience journey, autonomous repair, end-to-end acceptance). It
must not weaken those outcomes. Where this plan reduces roles or gates, it must
still preserve the outcomes; if the reader believes a reduction does, stop and
raise it rather than weakening the outcome.

## 0. Mission (restated, non-negotiable)

The product journey is:

1. A person completes and confirms the intake.
2. Ada consumes the confirmed intake, assets, copy, constraints, and experience
   plan.
3. Ada carries the work through the design pipeline herself.
4. About 20 minutes later the person receives a candidate in the Design review
   flow.
5. Production is unchanged until the person explicitly approves.

Hard invariants:

- The candidate is Ada's output. The coding agent never redesigns, rewrites,
  polishes, or hand-repairs a candidate to make a run look successful.
- Preview URLs work under the deployment mount point `/ada/`.
- A site mutation is an explicit owner action or a pending draft.
- Production changes only on explicit approval.
- Chat/design jobs are durable and inspectable by ID.
- Never describe infrastructure progress, passing unit tests, a manifest entry,
  or an internal gate marked `passed` as completion of the mission.

Success requires: Ada generated the candidate; the defining experience is
observable in the real owner Design preview after hydration; browser console,
module, and asset failures are treated as failures; motion is verified at
representative viewports including reduced motion; the run is roughly 20
minutes; no production mutation without approval.

## 1. Diagnosis

Observed failures in order:

1. The primary implementation turn owned unbounded custom Chromium/CDP visual
   self-review and looped until `opencode timed out after 1800s`. Host quality
   gates never ran.
2. After capability containment, a run reached the host gates and produced a
   thin realization: the host measured `active_animations = 0`, no interactive
   controls, no interaction state change, while the temporal gate still passed
   because a resting `transform !== 'none'` and a micro scroll-fingerprint
   delta counted as "observed".
3. The mandatory handoff in the authoritative plan — *host runtime evidence
   finds a fidelity defect -> Ada experience-fidelity repair agent -> one
   plan-bound repaired child* — is not wired for deterministic fidelity
   defects. A fidelity failure went terminal `needs_repair` with no Ada repair.
4. A required role (`creative_realization_review`) crashed with an OpenCode
   error and, because the run was already terminal, the failure was swallowed
   and the run stayed `ready_for_review`.
5. Repair is configured off: `repair_attempts: 0`,
   `validation_repair_attempts: 0`.
6. The authoring agents work blind: they never receive the host render of what
   they wrote. The host harness produces screenshots and motion/interaction
   traces, but that evidence only reaches the post-hoc visual-review model and
   the gates — not the agents that write and repair behavior.

Root cause: **Ada is not fulfilling the executable experience requirement, and
the pipeline does not enact its own mandated "host evidence -> Ada bounded
repair" handoff.** Gates are the trigger and the acceptance record, not the
cure. Adding more gate logic is a bandaid and is out of scope.

Second-order variables to measure, not assume: implementation model capability
and concept variance. The flash-tier model has produced real scroll
choreography (measured: 2 active animations normally, 0 under reduced motion,
4 interactive controls, running animations 0->24 during scroll) and has also
produced a near-static result. This plan makes the miss visible and repairable;
it cannot substitute for a model capable of the realization.

## 2. Target architecture: one loop, three actors

```
confirmed intake
  -> Ada author (one session: one plan + integrated source implementation)
  -> host render bundle (objective evidence: screenshots, motion, interaction,
       reduced motion, jank under CPU throttling)
  -> Ada repair (one bounded turn, fed the render bundle)
  -> host deterministic acceptance
  -> owner Design review (taste)
```

Four required outcomes preserved:

- Integrated realization: the same Ada turn plans and implements, so no
  concept is lost in a committee handoff.
- Experience journey: the locked plan is a persisted, executable artifact; the
  host measures whether the planned behavior actually changes when exercised.
- Autonomous repair: exactly one bounded Ada repair driven by host evidence.
- End-to-end acceptance: objective deterministic gates plus owner review.

### Loop budget

| Stage | Target |
|---|---|
| plan + implement | <= 12 min |
| host render bundle | <= 2 min |
| Ada repair (one) | <= 5 min |
| deterministic acceptance | <= 2 min |
| **total** | **~20 min** |

## 3. Workstreams

Each workstream is independently testable. Do not start a later phase until the
earlier phase has a green focused test and a real run data point.

### Phase 1 — The loop (highest leverage; do this first)

Goal: Ada builds, the host shows her the render, she repairs once, the host
accepts. Keep the existing planning roles for now.

1. **Host render bundle contract.**
   - Add a typed artifact (dataclass in `core/design_contracts.py`) that carries:
     candidate SHA, experience-plan hash, per-viewport screenshots (path +
     hash), scroll/interaction traces, reduced-motion trace, motion
     measurements, jank measurements, and console/network errors.
   - The bundle is produced by the existing harness in
     `hands/playwright_quality.py` and persisted alongside the run.
   - It is data, not instructions. Treat all of it as untrusted input.

2. **Feed the bundle to Ada's repair turn.**
   - In `hands/opencode_runner.py`, when a fidelity defect is found, invoke the
     experience-fidelity repair role with the bundle's screenshot paths passed
     as `-f` image files (the existing `image_files` mechanism) and the
     measurements included in the prompt as canonical JSON.
   - The repair prompt is a contract: state the defect, the exact failed
     acceptance condition IDs, the measured evidence, and the requirement to
     preserve the locked plan. No worked examples, no canned phrasings.

3. **Wire the mandated handoff for deterministic defects.**
   - In `application/design_jobs.py` and `application/designs.py`, when host
     runtime evidence finds a fidelity defect on an initial build, create
     **one** plan-bound repair child pinned to the retained candidate
     (`create_visual_refinement_run` or an equivalent single repair entry
     point), attach the render bundle, and re-validate the child.
   - Stop after one repair. Never hand-edit. Never create a second repair child.

4. **Enable the bound.**
   - `src/site_agent/intake-ada.yaml`: set `repair_attempts: 1` and
     `validation_repair_attempts: 1`. `config.py` already validates the range.

5. **Required-role failures are incomplete.**
   - If a required role is not invoked, returns the wrong contract, consumes the
     wrong plan hash, crashes, or is bypassed, the run transitions to
     `incomplete` (never `ready_for_review`).
   - Fix the swallow in `application/design_jobs.py` where a terminal run
     absorbs a specialist-review exception. A crashed creative-realization or
     fidelity role must downgrade a run that has not yet been owner-reviewed.

6. **Authoring agents never drive the browser.**
   - Keep the permission containment in `hands/opencode_provider.py`
     (`bash: "*": deny` plus a build/check allowlist; `webfetch/websearch/task/
     doom_loop: deny`). The host owns the browser.
   - The repair turn gets pre-rendered evidence instead of a browser, so Ada is
     not blind.

Focused tests:

- a deterministic fidelity defect creates exactly one repair child and no more;
- the repair child receives the render bundle screenshot paths and measurement
  JSON;
- a crashed required role marks the run `incomplete`;
- `repair_attempts: 1` is accepted by config validation.

### Phase 2 — One author instead of a committee

Goal: preserve integrated realization and the experience journey with one Ada
planning+implementation session. Do not lose the locked plan artifact.

1. Replace the multi-role planning sequence (copywriter, brand-source-analyst,
   3x concept designer, creative director, transfer critic) with one Ada
   planning turn that emits the same persisted `ExperiencePlanBundle`
   (`experience_journey`, `behavior_system`, `asset_composition_plan`,
   acceptance condition IDs).
2. Keep the plan hash-bound and persisted as the implementation contract.
3. Remove the redundant critic panel
   (`creative-director`/`experience-critic`/`technical-critic` review), or
   demote it to non-blocking advisory. Acceptance is the deterministic gate
   plus the owner.
4. Keep exactly one experience-fidelity repair (Phase 1).

If a reduction here is judged to weaken the authoritative plan's required
outcomes, stop and raise it; do not silently weaken.

Focused tests:

- one planning turn yields a contract-valid `ExperiencePlanBundle`;
- a new run never falls back to a legacy plan or a visual-only refinement path;
- the plan hash flows unchanged into implementation and repair.

### Phase 3 — Jank is objective, not a prompt

Goal: turn "smooth" into a measured budget.

1. **CPU-throttled scroll probe.** In `hands/playwright_quality.py`, run the
   scroll/interaction probe a second time under Chromium CDP
   `Emulation.setCPUThrottlingRate` (start at 4x). Record:
   - frame intervals and max frame gap during the scroll sequence,
   - long-task count (`PerformanceObserver` `longtask`),
   - dropped-frame ratio.
2. **Jank budget** in the quality gate: a configurable max frame gap and
   long-task budget. Exceeding it is a fidelity defect that routes to the one
   Ada repair with the measurements. Do not fail on an unthrottled run.
3. **Property audit** from source: flag animations of layout properties
   (`top/left/width/height/margin`), paint-heavy filters, and unhinted
   `will-change` unless the plan justifies them. This extends the existing
   native-source findings; it does not replace measurement.
4. **Reduce-motion is a measured fact, not a claim:** keep asserting that the
   reduced-motion path has zero active animations/tweens/scroll-triggers while
   content stays visible.

Focused tests:

- throttled probe reports jank metrics and a defined budget outcome;
- a deliberately janky fixture exceeds the budget and routes to repair;
- reduced-motion assertions still fail a candidate that animates under reduce.

### Phase 4 — Generic is constrained, taste stays with the owner

Goal: reduce obvious genericity without pretending a gate can judge taste.

1. **Signature tied to subject.** Require the plan's `signature_behavior` to
   cite business/audience/copy/media evidence and to change content state,
   hierarchy, or navigation — not just opacity/position of blocks.
2. **State-change requirement.** Host measurement should show that exercising
   the planned trigger changes something beyond decoration (e.g., an inverted
   plane, a changed readout, a revealed station), not merely a transform.
3. **Skills are guidance only.** Keep `high-end-visual-design.md` and
   `motion-design.md` in the skill set, but never treat them as enforcement.
4. **Owner reference beats automation.** If the owner supplies a moodboard or
   reference site, include it as visual evidence in planning and review. It is
   the strongest anti-generic input available.
5. **Do not add a banned-patterns list.** It moves genericity around and is
   brittle.

## 4. Concrete change map

| Concern | Primary file(s) |
|---|---|
| Authoring turn, design prompt, finalization | `hands/opencode_runner.py` |
| Render bundle production, jank probe, signature observation | `hands/playwright_quality.py` |
| Gate aggregation, temporal/journey evaluation, jank budget | `hands/design_quality.py` |
| Typed contracts (plan, journey, render bundle, reports) | `core/design_contracts.py` |
| Single planning turn, implementation/fidelity/repair phases | `application/design_orchestration.py` |
| Job lifecycle, handoff, crash handling, review linkage | `application/design_jobs.py` |
| Validate/render/visual-review/repair child creation | `application/designs.py` |
| Role capabilities and permissions | `hands/opencode_provider.py` |
| Configuration (`repair_attempts`, `validation_repair_attempts`, jank budget) | `src/site_agent/intake-ada.yaml`, `config.py` |

## 5. Verification

Run for every phase:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
```

Then a real run from the confirmed intake. For the real run, verify in order:

1. `GET /api/chat/jobs/{job_id}` if the run came from chat; otherwise the
   intake-lab run endpoints.
2. The run reaches a terminal state and records whether Ada created the
   candidate.
3. `GET /api/incubations/{id}/runs/{run_id}`: quality gates, visual review, and
   the render bundle are present and consistent.
4. Load the actual owner preview under the Design tab; confirm hydration.
5. Inspect candidate asset/module requests under the same `/ada/` (or lab)
   prefix; any console/module/asset error is a failure.
6. Exercise the planned trigger at desktop, tablet, and mobile, and under
   reduced motion; confirm the behavior changes and reduced motion reduces it.
7. Confirm no production mutation occurred without approval.

## 6. Definition of done

- Ada (one author) generates a candidate from the confirmed intake.
- The candidate hydrates in the real owner Design preview with no console,
  module, or asset errors.
- The planned experience changes observable state when exercised at all
  required viewports, and reduced motion is honored.
- At most one bounded Ada repair occurred, driven by host render evidence.
- A required-role crash or omission yields `incomplete`, never
  `ready_for_review`.
- Jank is measured under CPU throttling and within budget, or reported as a
  defect.
- Total autonomous elapsed time is compatible with the ~20-minute promise.
- No production mutation without explicit owner approval.

## 7. Non-goals / do not do

- Do not add more gates to compensate for a weak realization.
- Do not let the coding agent manually edit, polish, or "finish" a candidate.
- Do not let an authoring agent run its own browser, HTTP server, CDP harness,
  or network fetch.
- Do not enable more than one repair.
- Do not describe a run as complete when a required role was skipped or crashed.
- Do not mark a run reviewable when the defining experience is not observed.

## 8. End-of-task questions (answer honestly every time)

1. Did Ada — not the coding agent — create the candidate from the intake?
2. Did the candidate visibly follow the defining experience/adventure path?
3. Was that behavior observed in the real owner review surface after hydration?
4. Did any workaround bypass the autonomous pipeline?
5. Is the result honestly ready for owner feedback within the intended journey?

Any "no" means the mission is not complete.
