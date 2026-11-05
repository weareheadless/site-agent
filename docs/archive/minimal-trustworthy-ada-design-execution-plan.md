# Minimal, Trustworthy Ada Design Execution

## Purpose

Instructions for the coding AI implementing the next correction.

Ada owns the creative design and its implementation. The owner receives a
functioning, internally reviewed experience—not an animation debugging task.
Trust Ada to make creative and implementation decisions. Keep the host small:
isolation, build, faithful browser access, durable evidence, and approval safety.

This is a focused implementation proposal under `AGENTS.md` and
`brand-composition-and-behavior-system-implementation-plan.md`. Preserve their
integrated realization, experience fidelity, autonomous repair, end-to-end
acceptance, and approval requirements. Do not use older overlapping plans to
add phases. Any change to mandatory responsibilities requires an explicit
authority amendment; do not silently bypass them.

## What failed

Current path:

```text
confirmed intake -> Ada planning -> Ada generation -> build
  -> deterministic validation -> visual/behavioral review -> owner review
```

Recent runs stopped in the added pre-candidate sighted correction loop. A larger
timeout did not make that architecture work. It merely allowed it to fail later.

There is also a concrete observer defect to investigate first:
`_OwnerFrameSurface.screenshot(full_page=True)` expands the iframe to document
height. That changes the candidate viewport, viewport units, and potentially
ScrollTrigger geometry while capturing evidence. Ada reported an inflated
`100svh` hero. The causal connection is plausible, not yet proven for every run.

Do not assume all generated animation is broken until the observer is trustworthy.

## Design rules

1. **One creative owner: Ada.** Do not split composition and animation between
   authors or ask another agent to reinvent the direction.
2. **Observe without changing the page.** Browser evidence must describe the
   actual owner viewport and sandbox, not a resized substitute.
3. **Use existing artifacts.** No new plan schema, condition registry, review
   service, agent committee, or orchestration framework.
4. **Let AI judge intent and appearance.** The host reports browser facts; it
   does not encode taste or translate arbitrary creative prose into a generic
   rules engine.
5. **Fix causes, not scores.** No generated-state claim, source marker, GSAP
   import, or animation count is proof of a delivered experience.
6. **Preserve evidence and output.** Retention is not approval or readiness.
7. **Measure the whole journey.** A 15-minute review loop does not satisfy a
   roughly 20-minute total product promise.

## Implementation order

### 1. Prove and fix the observer first

Primary file: `src/site_agent/hands/playwright_quality.py`.

- Start with a failing browser regression fixture: viewport-height content and
  a simple scroll-linked animation inside the same iframe sandbox.
- Record iframe viewport dimensions and relevant element geometry before and
  after capture. Capture must not change either or trigger a resize.
- Replace iframe-expansion screenshots with ordinary viewport captures.
- To observe the rest of a page, scroll normally and capture a small sequence
  of viewport frames. Do not stitch by changing layout, disable animation, or
  inject styles into the generated site.
- Reuse the existing adapter and screenshot storage. Keep the change local.
- Restore intentional probe scroll/control state before the next independent
  observation. Do not mistake scroll movement for animation.

Exit condition: a real browser test proves that taking screenshots preserves
viewport dimensions and animation geometry. Unit mocks alone are insufficient.

### 2. Diagnose one retained Ada output, unchanged

- Select one recent failed run with retained source/checkpoints and a plan.
- Inspect its actual owner surface with the corrected observer.
- Compare the visible sequence with Ada's existing design plan: beginning,
  defining transition, and completion. Include mobile and reduced motion.
- Report separately: serving/hydration failure, observer failure, missing
  implementation, and creative-quality concern.
- Do not modify the generated source. Do not mark the old run successful from
  this diagnostic inspection or spend another generation turn to avoid diagnosis.

Exit condition: name a reproducible failure and its responsible boundary—or
show that the alleged defect was caused by observation.

### 3. Simplify the existing execution, do not add another pipeline

Keep the intended path understandable:

```text
confirmed intake and assets
  -> Ada designs and implements the complete experience
  -> host builds and retains the result
  -> faithful owner-surface observations
  -> Ada assesses her result against her intent
  -> focused correction only when actual evidence requires it
  -> verify the changed result
  -> owner receives the finished candidate
```

These are responsibilities, not a requirement for a new agent or model call at
each arrow. Reuse existing calls and persisted artifacts. Keep required plan
data intact; do not add another contract to describe the same thing.

- Remove the redundant pre-candidate full-render/correct/full-render mechanism
  only as part of consolidating the existing review/repair responsibility.
  Do not leave both mechanisms active or relocate the same unconditional loop.
- Ada's integrated implementation must own layout, animation, responsive
  behavior, and reduced motion from the beginning.
- Give the existing internal assessment the plan and a compact set of actual
  viewport frames, relevant interaction observations, and console/network errors.
- Ask Ada to assess the intended experience and visual coherence, not merely
  fill in a condition-coverage report. Prompts contain responsibilities and
  evidence, never canned creative examples.
- Use the existing finite autonomous repair mechanism only for concrete defects.
  A correction is not mandatory when the result already works. Preserve any
  required fidelity assessment without forcing an extra writable turn.
- Infrastructure failures belong to the host. Do not ask Ada to compensate for
  broken preview delivery or a measurement-induced layout change.
- Recheck corrected behavior and necessary regressions using the same faithful
  observer. Do not waive hydration, assets, representative viewports, reduced
  motion, or internal visual assessment to save time.
- Retain failed output and diagnostics without making them owner-ready. Never
  require the owner to decide whether Ada implemented her own animation plan.

Before changing orchestration, identify the existing duplicate calls that will
be removed and the existing call that retains each required responsibility.
If this cannot be expressed briefly, stop: the proposal is still too complex.

### 4. One fresh acceptance run

After the observer proof and focused tests, rerun Ada from the confirmed intake
or an explicitly valid persisted boundary. Do not manually repair the candidate.

Verify in the real owner review surface:

- JavaScript hydrates; required modules and assets load without errors.
- The defining journey visibly starts, progresses, and completes.
- Desktop, tablet, mobile, and reduced motion behave intentionally.
- Internal visual assessment evaluates the hydrated sequence and composition.
- The owner first receives a complete candidate, not diagnostic output.
- Production stays unchanged without explicit approval.

Record elapsed generation, build, observation, assessment, correction (if any),
and total time using existing diagnostics. Report measured durations, not budget
settings. If the journey is too slow, identify the costly operation before
changing anything. Do not increase timeouts, lower reasoning, or repeat fresh
runs as a substitute for understanding the bottleneck.

## Scope and verification

Likely files: `hands/playwright_quality.py`, its browser tests, and only the
existing orchestration call sites proven redundant by inspection.

Avoid changing configuration, UI, schemas, and persistence together. Preserve
unrelated uncommitted work. Do not commit generated sites, databases, screenshots,
credentials, or runtime configuration.

Run focused tests first, then:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
```

## Completion report

State what was removed, what was fixed, the exact acceptance run identity, and
what was observed. Answer:

1. Did Ada—not the coding AI—create the candidate from the intake?
2. Did its defining experience visibly work?
3. Was it observed in the actual owner review surface?
4. Did any workaround bypass autonomous generation or validation?
5. Is the result ready for owner feedback within the intended journey?

Missing evidence means incomplete. Passing infrastructure tests alone is not
delivery. The goal is less machinery and a convincing working experience—not
another document-shaped pipeline that claims success.
