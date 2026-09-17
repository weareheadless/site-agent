# Autonomous Creative Site Pipeline Consolidation Plan

## Status

**Active corrective implementation plan.**

**Implementation status:** the Phase 1 artifact boundary is implemented: new
host-composed runs persist an immutable output identity before browser
inspection, owner preview reads that artifact, and artifact-required previews
fail closed instead of rebuilding from source. The remaining orchestration and
contract deletion phases are not implemented yet.

This plan replaces accumulated design-pipeline mechanics with one small path. It
is not another architecture to run beside the existing ones.

Until its end-to-end acceptance gate passes, `AGENTS.md` and
`docs/brand-composition-and-behavior-system-implementation-plan.md` remain
authoritative for product outcomes: Ada creates the candidate, the defining
journey is visible, the real owner surface is tested, repairs remain Ada-authored,
and production changes only after explicit approval.

After acceptance, the documentation cleanup in Phase 6 leaves one authoritative
design document and deletes the superseded plans. The 20-minute target is recorded
but is not a blocker for this correction; quality and consistency come first.

## Goal

Consistently turn a confirmed, incubated intake into an original, asset-grounded,
factually correct website whose responsive GSAP experience works in the exact
surface the owner reviews.

```text
confirmed intake + approved assets
  -> one sighted Ada direction session
  -> one integrated Ada implementation session
  -> immutable candidate SHA
  -> one authoritative build artifact
  -> real owner-review iframe
  -> objective browser evidence + sighted review
  -> optional one evidence-driven Ada repair
  -> same validation path
  -> owner review
  -> explicit approval or decline
```

OpenCode may use its native skills and subagents inside Ada's sessions. Python
must not implement a second creative-agent framework around it.

## Current diagnosis

Required chain:

```text
confirmed intake -> Ada planning -> Ada generation -> build
  -> deterministic validation -> visual/behavioral review -> owner review
```

Ada created candidate `66764579556be94af5b41742dc7736b65fabe7d5`; its bounded
repair created `c647cf75c60fbd708a071fa252ab517ff33d74da`. The repair reduced
three deterministic blockers to one:

```text
owner preview iframe did not hydrate
```

The immediate broken boundary is therefore:

```text
authoritative build output -X-> hydrated owner-review iframe
```

The codebase also has structural causes that will keep producing inconsistent
results unless removed:

1. `legacy`, `native`, `specialist`, and `creative` orchestration coexist.
2. The direction turn must serialize a very large `ExperiencePlanBundle` before
   Ada can write the site.
3. The same creative fields are repeated across contracts, prompts, allowlists,
   normalizers, persistence, and tests.
4. Host normalizers now invent or rewrite creative metadata instead of only
   binding IDs and hashes.
5. Candidate-authored `data-ada-*` completion claims are treated as behavioral
   evidence.
6. Intake preview, Admin review, direct run review, and Playwright acceptance use
   different serving paths.
7. The output artifact is published before browser validation but persisted only
   afterward. The owner route can therefore start a second cold Astro build while
   Playwright waits for the iframe, causing the current timeout.
8. Multiple active-looking plans and implementation-coupled tests preserve
   incompatible architectures.

## Non-negotiable design rules

1. One runtime path creates all new candidates.
2. Ada owns direction, composition, copy realization, and behavior.
3. The host owns persistence, isolation, builds, objective evidence, and approval.
4. Composition and GSAP are implemented together by one primary Ada session.
5. IDs, SHAs, hashes, timestamps, and provider metadata are host-derived.
6. Validation and owner review serve the same immutable bytes.
7. Browser-observed effects count; candidate or model claims do not.
8. Runtime defects repair the retained candidate; they do not restart design.
9. Every replacement phase deletes the superseded code and tests immediately.
10. The completed change must reduce design-pipeline code and test volume.

## Minimal retained data

### Host run record

Keep durable run/parent IDs, intake revision/hash, base/candidate SHA, approved
asset hashes, provider/session/transcript data, output artifact identity, quality
state, and owner decision. Ada does not output these fields.

### Ada creative brief

Replace the overlapping brand, behavior, journey, composition, and rubric
contracts with one concise Ada-authored artifact containing:

- creative thesis and audience effect;
- factual copy and unresolved facts;
- asset roles, focal constraints, treatments, and responsive use;
- ordered visitor scenes;
- defining behavior with observable initial, intermediate, and final states;
- desktop, tablet, mobile, keyboard/touch, reduced-motion, and no-JavaScript
  translations;
- accessibility, performance, risks, and prohibited generic treatments.

There is one scene sequence, not duplicate journey and behavior graphs. Mechanical
decoding may normalize explicitly allowed scalar forms; it may not invent IDs,
evidence, transitions, conditions, or creative completion. One concise correction
turn is allowed for invalid output, after which the run fails explicitly.

### Host evidence

Record artifact identity, iframe/hydration stages, console and network failures,
loaded modules/assets, actions performed, before/intermediate/after rendered
states, viewport/motion mode, final resting state, and sighted findings. Keep this
vocabulary domain-neutral.

## Target module ownership

- `application/design_intake.py`: confirmed revision/hash and build reservation.
- `application/design_jobs.py`: durable execution and one optional repair child.
- `application/designs.py`: run lifecycle, candidate identity, validation, and
  approval boundary.
- `hands/opencode_runner.py`: isolated worktree, direction, implementation, repair.
- `hands/site_build.py`: authoritative build and content-addressed artifact.
- `web/preview.py`: the single artifact reader and mount-safe rewriting.
- `hands/playwright_quality.py`: real owner-surface browser observation.
- `hands/design_visual_review.py`: sighted review of the observed artifact.
- HTTP modules: request/session translation only.

No Python module owns a creative specialist state machine.

## Implementation phases

Every phase follows **replace, prove, delete**. Do not continue while both old and
new implementations remain active.

### Phase 0 — Preserve the regression

- Retain current run IDs, candidate SHAs, reports, and transcripts.
- Reproduce the hydration failure through the owner surface.
- Record production identity and prove it remains unchanged.
- Do not manually edit generated candidate source.
- Freeze new modes, schemas, repair types, preview routes, and plan documents.

**Done when:** the failure is reproducible and production is unchanged.

### Phase 1 — One build artifact and one preview service

- Persist candidate SHA, artifact ID, and tree hash immediately after artifact
  publication and before browser validation.
- Keep quality verdict separate: failed candidates may retain artifacts without
  becoming reviewable.
- Route Intake Lab, Admin Design review, direct run review, and Playwright through
  one artifact-serving function.
- Keep public URLs stable but remove their independent build/read logic.
- Remove source-rebuild fallback for new candidates; missing artifacts fail.
- Derive the preview root from the mounted request path, including `/ada/`.
- Support Astro HTML, CSS, module/dynamic imports, workers, preload URLs,
  `import.meta.url`, responsive images, and local runtime assets.
- Standardize the owner iframe contract and selector.

**Proof:** a real Astro/React fixture builds once, nested modules load under
`/ada/`, validation serves the persisted tree, and corruption fails closed.

**Delete:** duplicate preview builds and validation-only acceptance serving for
new design candidates.

### Phase 2 — Observe real hydration and behavior

- Report separate stages for owner shell, iframe navigation, HTML, document,
  Astro/React hydration, and interaction readiness.
- Capture all console, page, response, module, asset, font, and stylesheet errors.
- Measure before/intermediate/after states during progressive and reverse scroll
  and the defining interaction.
- Exercise desktop, tablet, mobile, resize, interruption, rapid input,
  keyboard/touch where relevant, reduced motion, and no-JavaScript.
- Require a stable, complete, readable final state.
- Remove instance-specific CSS variables from generic validation.

GSAP presence, source regexes, active tween counts, `Element.getAnimations()`,
and candidate-authored completion attributes are not evidence.

**Delete:** proxy gates and tests accepting candidate/model pass claims.

### Phase 3 — One Ada-native orchestration path

- Remove orchestration selection for new runs. Historical values remain readable
  but cannot dispatch old workflows.
- Keep one sighted read-only direction session.
- Allow that OpenCode session to use approved read-only subagents when useful.
- Keep one writable implementation session receiving the confirmed intake,
  approved assets, creative brief, capabilities, framework, and GSAP skills.
- Keep one optional repair child from concrete host and sighted evidence.
- Ensure initial and repaired candidates receive identical validation and review.

**Delete:** Python-scheduled copywriter, analyst, concept committee, director,
transfer, motion, fidelity, critic, and signoff dispatch; inactive mode branches;
unused config; tests preserving only that committee.

### Phase 4 — Replace the oversized creative protocol

- Define the concise creative brief once and derive its prompt contract from that
  definition.
- Bind all run/artifact identity in host code after decoding.
- Pass the brief losslessly to implementation.
- Remove duplicate scene graphs, transfer self-verdicts, confidence maps,
  repeated responsive fields, and model-authored hashes.
- Remove semantic normalization and accumulated aliases.
- Derive the owner summary from the brief rather than requesting duplicate prose.

**Delete:** superseded creative classes in `core/design_contracts.py`, the
overlapping normalizer in `application/design_orchestration.py`, the native copy
in `hands/opencode_runner.py`, and their implementation-coupled tests.

### Phase 5 — One repair lifecycle

- Collapse technical repair, visual refinement, sighted refinement, fidelity
  repair, review retry, and revalidation into one revision lifecycle.
- Bind every repair to an immutable source candidate SHA and original brief.
- Give Ada concrete browser/sighted findings and the retained source.
- Rebuild and review the repair through the same owner-surface path.
- Permit at most one automatic repair; further changes require owner action.
- Never regenerate direction because preview infrastructure failed.

**Delete:** duplicate repair constructors, service methods, route business logic,
UI controls, and refinement-specific review bypasses.

### Phase 6 — Acceptance, documentation, and dead-code removal

Create one real owner-surface acceptance runner. Its first fixture is the
confirmed Claro Oscuro intake and approved assets. It must prove:

1. the public application boundary starts the run;
2. Ada creates direction and source;
3. copy is factual and unknowns remain unresolved;
4. one immutable artifact is used by validation and preview;
5. the sandboxed `/ada/` iframe hydrates without failed requests or console errors;
6. the light/descent journey is visibly meaningful, not a generic reveal;
7. the interaction has measured initial, intermediate, and completed states;
8. desktop, tablet, mobile, reduced motion, and no-JavaScript remain complete;
9. any repair is Ada-authored from the retained candidate;
10. production remains unchanged and the result waits for owner review.

Add negative fixtures for an unhydrated island, missing nested module, static or
hidden-to-hidden motion, false completion marker, incomplete reduced motion, and
artifact mismatch. Then run the same outcome contract over a small unrelated
intake corpus. Consistency means common quality and runtime outcomes, not similar
designs.

After acceptance:

- rewrite `docs/architecture.md` around the shipped path;
- create concise `docs/autonomous-design-pipeline.md` as the sole active design
  architecture and acceptance document;
- update `AGENTS.md` to reference it;
- delete superseded plans after preserving their valid requirements in the new
  document; Git history is the archive;
- remove dead modules, contracts, enums, config, migrations not required to read
  historical records, UI controls, and obsolete tests;
- run an unused-reference audit;
- require a net reduction in application and test code.

At minimum, merge and delete these overlapping plans:

- `brand-composition-and-behavior-system-implementation-plan.md`
- `simple-owner-surface-gsap-pipeline-implementation-plan.md`
- `simplify-design-pipeline-implementation-plan.md`
- `design-pipeline-simplification-implementation-plan.md`
- `asset-grounded-first-owner-candidate-implementation-plan.md`
- `specialist-opencode-design-orchestration-implementation-plan.md`
- `design-engine-pipeline-implementation-plan.md`
- `react-design-creation-system-implementation-plan.md`
- `full-llm-authored-design-implementation-plan.md`
- `canonical-opencode-design-test-implementation-plan.md`
- design-specific material in `opencode-first-design-pipeline-implementation-plan.md`

**Documentation gate:** a new coding agent understands the whole path from
`AGENTS.md`, `docs/architecture.md`, and `docs/autonomous-design-pipeline.md`
without reconciling historical alternatives.

## Tests retained

Keep focused tests for intake identity, durable jobs, restart recovery, exact-SHA
worktrees, path/secret safety, dependency and asset integrity, immutable
candidates, artifact integrity, mount-safe authorization, factual copy, objective
browser evidence, responsive/reduced-motion states, and explicit approval.

Remove tests whose main purpose is exact prompt prose, private normalizers,
specialist call counts, mode branching, internal agent names, candidate-authored
pass markers, source regexes as visual proof, raw UI source strings, or historical
phases no longer created.

## Migration rules

- Keep public API paths stable by routing them to the single service.
- Keep historical candidates, transcripts, artifacts, and decisions inspectable.
- Do not convert historical creative payloads by inventing new fields.
- New runs use only the replacement path; no dual-write or shadow committee.
- Add no universal workflow, plugin, event, or compatibility abstraction.
- A symbol retained only because an obsolete test references it is dead code.
- If implementation adds more orchestration code than it deletes, stop.

## Completion gate

This plan is complete only when there is one orchestration path, one concise
creative artifact, one Build owner, one artifact-serving path, one browser
adapter, one sighted review, and one optional repair; Claro Oscuro passes in the
real owner surface without manual candidate edits; an unrelated intake corpus
passes the same outcome contract; production approval remains explicit; and the
superseded code, tests, config, UI, and documentation are deleted.

Valid JSON, generated GSAP, a successful Astro build, internal marker coverage,
or an attractive static screenshot is not completion.

## Implementation discipline

For every phase:

1. State the first broken boundary.
2. Start with a failing focused test or owner-surface request.
3. Change only the responsible layer.
4. Never manually repair generated candidate source.
5. Rerun from the earliest valid persisted boundary.
6. Delete the superseded implementation in the same phase.
7. Run focused tests, full pytest, compileall, wheel build, and `git diff --check`.
8. Inspect the real hydrated owner surface.
9. Report blocked results honestly.

Do not answer another failure by adding a parallel service, mode, contract, gate,
repair type, preview route, or implementation plan.

## Current mission status

1. Ada created the current candidate: **yes**.
2. The defining experience is visibly proven: **no**.
3. It was observed in the real owner surface: **no; hydration failed**.
4. A workaround bypassed the pipeline: **no**.
5. It is ready for owner feedback: **no**.

This plan is not evidence of product completion.
