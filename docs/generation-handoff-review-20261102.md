# Generation handoff review — November 2, 2026

This is a bounded review of the existing uncommitted generation changes, not
a new architecture or release authorization. The owner-approved requirements
remain in `fast-faithful-design-replacement-architecture.md`.

## Boundary and findings

confirmed intake -> Ada planning -> Ada generation -> build -> deterministic validation -> visual/behavioral review -> owner review

The reviewed boundary is planning -> generation in
`hands/opencode_runner.py:stage_design_build`.

- The prior changes remove mandatory section-library staging and wiring, and
  let Ada author presentation using canonical Payload content. Historical
  section implementations remain available; existing candidates are untouched.
- Supplying `design_plan` already skips native-direction dispatch. When no
  complete plan exists, direction still supplies typed copy and experience
  requirements needed by `_stage_initial_homepage_payload`. Removing that turn
  without the replacement same-session staging/resume contract would drop a
  necessary boundary, not merely simplify it.
- The initial direction call and its one permitted typed correction duplicated
  dispatch, transcript persistence, validation and error handling. The second
  branch also failed to update the creative session identity. Build could
  continue the original invalid session instead of the accepted correction.
- Prompt compaction had removed exact asset and journey observation attribute
  names. Browser evidence consumers still require those selectors; generic
  instructions to mark visible elements were insufficient.

## Changes in this review

Consolidated direction dispatch and correction into one path. The existing
durable phase claim still limits typed correction to one attempt. Provider
failure remains terminal, failed evidence remains persisted, completed planning
is reusable, and the Build-dispatch fence is unchanged. Both immediate and
restarted correction now persist and pass the accepted session ID to Build.
Removed an identical parent-repair digest/token branch. Restored the exact
observation selector contract in compact form without restoring the long prose.

## Verification and limits

- Session-continuity regression failed before the fix and passed afterward.
- Added interruption-before-correction and correction-provider-failure coverage;
  existing tests retain competing-claim, checkpoint reuse and identity-drift checks.
- Observation-selector regression failed before restoring the contract.
- Focused generation/contract tests: 177 passed.
- Full Python suite: 2,313 passed on each of two consecutive runs.
- `compileall`, wheel build and `git diff --check` passed.

No model run, content mutation, approval, release-queue mutation, merge or
deployment was performed. This review does not prove latency improvements or
owner-visible design fidelity. Remaining replacement-architecture work includes
eliminating the separate expansive direction phase through canonical same-session
copy staging and durable resume, not simply deleting its required output.
Any release must still use the reviewed immutable source/package artifacts and
canonical VPS queue, followed by authenticated workspace verification.

Mission audit: Ada authored the retained candidate; defining experience fidelity
and behavior in the actual owner review surface remain unproven; this review
does not bypass the autonomous pipeline; readiness for owner feedback remains
unproven. The overall design mission is incomplete.
