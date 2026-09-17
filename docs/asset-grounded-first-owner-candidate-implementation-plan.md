# Asset-Grounded First Owner Candidate Implementation Plan

## Status and authority

**Status:** Proposed focused execution addendum.

**Audience:** The coding AI implementing the design-pipeline correction.

This plan addresses one observed creative regression in the simplified Ada
pipeline. It implements, and does not replace, the requirements in:

- `AGENTS.md`;
- `docs/brand-composition-and-behavior-system-implementation-plan.md`;
- `docs/simple-owner-surface-gsap-pipeline-implementation-plan.md`.

The brand-composition plan remains authoritative for asset-grounded composition,
an executable experience journey, integrated realization, bounded autonomous
repair, and end-to-end owner-surface acceptance. The simple-owner-surface plan
remains the preferred code shape: one concise Ada direction turn, one integrated
Ada build turn, one host browser adapter, one sighted visual review, and at most
one automatic Ada-authored revision.

Do not execute an older plan's phase list in parallel. Do not delete an existing
experience-plan capability merely because the current simplified path has
stopped supplying it. Reconnect the smallest existing contracts needed to make
Ada's direction executable. If a simplification would weaken an authoritative
outcome, stop rather than weakening the outcome.

## 1. Mission and current status

Required product journey:

```text
confirmed intake
  -> visually grounded Ada planning
  -> Ada integrated generation
  -> authoritative build
  -> deterministic owner-surface validation
  -> sighted visual/behavioral review
  -> optional one Ada revision
  -> owner Design review
  -> explicit owner decision
```

Start-of-task mission answers for the current evidence run:

1. Did Ada—not the coding agent—create the candidate from the intake? **Yes.**
2. Did the candidate visibly follow the defining experience/adventure path?
   **No, not strongly enough to satisfy the reviewed direction.**
3. Was that behavior observed in the real owner review surface? **No.**
4. Did any workaround bypass the autonomous pipeline? **No.**
5. Is the result honestly ready for owner feedback within the intended journey?
   **No.**

Therefore the product mission is incomplete. This implementation task may fix
generic pipeline code and rerun Ada; it may not manually improve the retained
candidate.

## 2. First broken boundary

```text
confirmed intake -> Ada planning -X-> Ada generation -> build
  -> deterministic validation -> visual/behavioral review -> owner review
```

The first broken boundary is **Ada planning -> Ada generation**.

The current direction/build path did not carry an executable experience plan
into generation. Consequently, composition, experience-journey, and temporal
validation were recorded as skipped with
`experience_plan_not_supplied`. The current generation transcript also shows
that Ada listed and measured the available images but did not receive or inspect
their visual content before making structural composition decisions.

The resulting candidate demonstrates the failure mode:

- supplied wide images were stacked as ordinary sections instead of used as
  structural compositional evidence;
- a distinctive negative-space/light-shaft affordance in the media was missed;
- copy repeated intake language rather than developing a persuasive sequence;
- purposeful animations were present, but no plan-bound signature experience
  organized the composition;
- Ada had no owner-surface render evidence before candidate retention;
- the sighted review found weak first-viewport composition, a delayed mobile
  action, oversized tablet spacing, dark image treatment, and behavior that was
  not composition-defining.

Do not fix those run-specific symptoms in application code. Fix the missing
evidence and plan handoff, then rerun Ada from the confirmed intake.

## 3. Product outcome

The first candidate shown to the owner should be Ada's first **review-ready**
candidate, not necessarily Ada's first source mutation. Before owner exposure,
the autonomous job may perform one bounded internal revision based on the same
host evidence the owner surface produces.

The target path is:

```text
confirmed intake + approved assets + durable owner taste evidence
  -> host materializes factual asset evidence and sighted media attachments
  -> Ada direction turn inspects that evidence and commits to one coherent idea
  -> host persists and validates the existing experience-plan representation
  -> Ada build turn receives the complete direction, plan, and media evidence
  -> Ada implements composition, copy, responsive behavior, and motion together
  -> host builds one immutable output artifact
  -> host probes the exact owner review surface at required viewports
  -> one sighted reviewer reports visual/editorial problems without prescribing
     a replacement design
  -> if needed, one Ada revision receives the combined factual evidence
  -> host rebuilds and repeats the exact same acceptance path
  -> only then can the final immutable candidate enter owner Design review
```

Normal target: two Ada authoring turns plus one sighted review. Repair target:
one additional Ada turn. Total elapsed time must remain compatible with about
20 minutes.

## 4. Simplicity rules

The implementation must remain small enough to trace from the run service to a
persisted candidate state.

1. Use one Ada identity and one coherent direction. Do not restore a creative
   committee or add another specialist graph.
2. Reuse `ExperiencePlanBundle`, `ExperienceJourney`, asset evidence, existing
   direction artifacts, browser evidence, visual review, and candidate identity.
   Do not introduce a parallel planning schema, coverage map, reviewer, or pass
   signal.
3. The direction turn is read-only. The integrated build and optional revision
   are the only Ada turns with candidate write access.
4. The host owns durable state, immutable identity, builds, browser observation,
   preview delivery, secrets, permissions, and approval. It does not choose a
   visual recipe or rewrite copy.
5. Ada owns the creative thesis, asset relationships, copy strategy, layout,
   responsive translation, signature behavior, motion, and creative repair.
6. One automatic revision budget is shared by deterministic, behavioral,
   visual, and editorial findings. Do not create nested or category-specific
   repair children.
7. Infrastructure retries do not consume the creative revision budget when the
   candidate bytes have not changed. They may only rerun a failed host operation
   against the same immutable identity.
8. Never make a phrase counter, source marker, model claim, static transform, or
   manifest entry evidence of creative or behavioral success.

## 5. Required contracts and evidence flow

### 5.1 Frozen creative input

Before the direction turn, create one hash-bound input manifest from existing
records. It must include:

- confirmed intake revision and hash;
- approved customer-context/genesis revision and hash;
- selected asset IDs, paths, media roles, and content hashes;
- deterministic `AssetVisualEvidence` where available;
- owner-provided references and explicit constraints;
- sanitized owner design-feedback episodes relevant to the incubation;
- source and candidate identities needed for provenance.

This is a projection over existing persisted data, not a new source of truth.
Do not infer business facts or creative motifs in host code.

### 5.2 Sighted asset delivery

Every selected compositional image and logo must be available to the direction
turn as actual image input, not only as filename, dimensions, palette, OCR, or a
text summary.

- Materialize bounded, orientation-correct previews or contact sheets under the
  run evidence directory.
- Preserve stable asset ID and SHA association in labels/metadata.
- Pass those files through the existing OpenCode `image_files` mechanism.
- Keep original files immutable; previews are evidence only.
- Record the evidence file hashes and the direction transcript ID.
- Fail planning as `incomplete` if required visual evidence cannot be delivered.
  Do not silently continue with path-only evidence.

The host proves that images were attached and hash-bound. It does not attempt to
prove what Ada perceived by parsing conversational prose or requiring a
particular tool call.

### 5.3 One Ada-authored direction and executable plan

The read-only direction turn must produce the existing human-readable direction
artifact and populate the existing experience-plan representation. Keep the
artifact bounded and useful to the implementation model. It must commit to:

- one creative thesis grounded in the intake and selected evidence;
- first-viewport hierarchy and conversion intent;
- an asset composition role for each selected major asset, including geometry,
  meaning, relationship to copy, crop/negative-space intent, and desktop/tablet/
  mobile treatment;
- one editorial sequence in which each major region has a distinct communication
  job;
- one defining visitor experience and signature behavior grounded in the
  business, audience, copy, or media;
- observable journey states/triggers/outcomes and meaningful responsive,
  keyboard/touch, no-JavaScript, and reduced-motion translations;
- resting-state completeness and performance constraints.

Use the current strict `ExperiencePlanBundle` and `ExperienceJourney` parser and
hash semantics where they are already implemented. If the concise Markdown
direction remains the provider-facing artifact, deterministically persist the
validated structured projection beside it; do not create a second competing
direction. Both representations must share one plan hash/provenance record.

Planning is incomplete when the plan is absent, invalid, detached from selected
asset hashes, generic enough to transfer unchanged to an unrelated business, or
missing observable responsive/reduced-motion meaning. Source mutation must not
start in that state.

### 5.4 Lossless generation handoff

The integrated build turn must receive:

- the confirmed frozen input manifest;
- the complete Ada-authored direction and validated experience plan;
- selected media paths and the same sighted media evidence;
- relevant owner-feedback/taste constraints;
- approved design, accessibility, GSAP, performance, and reduced-motion skills;
- repository capabilities and mutation boundaries.

Do not summarize away asset relationships, copy intent, journey conditions, or
responsive/reduced-motion requirements. If provider limits prevent a lossless
handoff, provide immutable local artifacts with verified hashes or stop as
`incomplete` before mutation.

The build prompt should require an integrated implementation and local build
self-check, but it must not prescribe a layout, named effect, animation recipe,
industry motif, or canned copy. No worked prompt examples are permitted.

### 5.5 Host-owned render evidence

After Ada's build, retain the candidate and produce one immutable output artifact
bound to candidate SHA and output tree hash. Then use the actual Design/Intake
Lab review route and iframe sandbox to collect:

- high-detail viewport captures at desktop, tablet, and mobile;
- normal-motion before/intermediate/after observations;
- a fresh reduced-motion context;
- hydration/module status and console errors;
- failed image, font, stylesheet, module, and network requests;
- visible resting/completion content;
- observable response to the planned trigger where applicable;
- artifact, candidate, plan, route, viewport, and evidence hashes.

The owner preview and validation must consume the same immutable output bytes.
Missing browser evidence is `incomplete`. Failed runtime or asset delivery is a
failure. Candidate-authored markers may locate a behavior but cannot prove it.

### 5.6 One sighted review

Run one read-only sighted review after objective owner-surface evidence is
available. Give the reviewer legible viewport captures, temporal frame sequences,
the direction, and factual browser observations.

The reviewer evaluates:

- composition and first-viewport hierarchy;
- whether media is structurally integrated rather than merely placed;
- typography, contrast, image treatment, and spacing;
- distinct editorial progression, clarity, and conversion integration;
- responsive translation;
- whether the observed states visibly express the defining experience.

The reviewer reports evidence-bound problems and their severity. It must not
claim hydration/timing success from stills, invent a replacement concept, or
prescribe implementation recipes. Ada decides how to solve valid critique.

### 5.7 One combined pre-owner revision

Aggregate all candidate-caused blocking findings from deterministic validation,
behavior observation, and sighted review into one concise revision brief. Keep
infrastructure failures separate.

The revision must:

- be a child of the retained parent candidate;
- preserve the locked creative thesis while allowing structural changes needed
  to realize it;
- receive the parent source, complete plan, sighted media, viewport captures,
  temporal evidence, and exact factual findings;
- be authored by the same integrated Ada capability with the same design/motion
  skills;
- consume the run's only automatic creative revision attempt;
- repeat build, immutable output creation, owner-surface probing, and sighted
  review;
- stop as `needs_repair` or `incomplete` if it still fails.

Do not force smallest-change preservation when the parent never realized the
locked composition or experience. Do not permit a second automatic child.

## 6. Copy quality without host-written copy

The current phrase-presence checks encouraged literal repetition. Replace their
role in creative acceptance; do not replace them with a host copywriter.

- Preserve exact owner language only where the intake marks wording as required,
  legal, factual, or a named identity.
- Have Ada's direction assign a distinct communicative purpose and evidence basis
  to each major region.
- Require the integrated build to develop the narrative from confirmed facts and
  the owner's language, without inventing claims.
- Treat exact phrase presence as factual coverage evidence only, never as a
  quality score.
- Let the sighted reviewer identify repetition, weak hierarchy, disconnected
  calls to action, or copy that does not advance the planned sequence.
- Do not add canned phrasings, sample headlines, language classifiers, tone
  templates, or industry-specific copy rules to prompts or validators.

## 7. Durable owner taste and anti-regression memory

The system should remember evaluations, not copy previous implementations.

Persist explicit owner feedback as a sanitized creative episode linked to the
incubation, run, candidate SHA, affected quality dimensions, and provenance.
Relevant future direction turns may receive compact owner-derived constraints
such as preferred compositional qualities or rejected tendencies.

Rules:

- owner feedback is authoritative for taste but not permission to publish;
- only explicit feedback is durable preference evidence;
- comparisons may use retained screenshots/artifact identities from the same
  incubation, never copy source or treat a prior layout as a template;
- a prior candidate described by the owner as stronger may be supplied as a
  visual reference with the owner's stated reasons;
- references constrain evaluation, not the creative answer;
- never encode this incident's image feature, business vocabulary, layout, or
  preferred animation in generic host code.

## 8. State and failure semantics

- `planning`: sighted evidence and direction/plan are being produced.
- `incomplete`: required evidence, plan, provider output, build identity, or
  browser observation is absent or invalid.
- `validating`: exact immutable owner-surface evidence is being collected.
- `needs_repair`: candidate-caused blocking findings remain and no automatic
  revision is available or the revision failed.
- `ready_for_review`: objective evidence passes, sighted review has no blocking
  finding, candidate/output identities match, and the final owner preview exists.
- `approved`/production mutation: only through the existing explicit owner
  approval operation.

Candidate retention records Ada's output; it does not imply readiness. A host
provider timeout, browser transport error, or visual-review provider error may be
retried against the unchanged candidate under the existing bounded host policy.
It must not create a creative child or be reported as a creative failure.

## 9. Implementation sequence

Start each phase with a failing focused test or reproducible API request. Keep
exactly one new-run orchestration path; historical records may remain readable.

### Phase 0 — Freeze regression evidence

- [ ] Retain the confirmed intake, asset IDs/hashes, current run IDs, candidate
      SHAs, output artifact identity, direction/build transcripts, browser
      evidence, and sighted-review findings as immutable acceptance evidence.
- [ ] Record current turn count, stage durations, and total wall time.
- [ ] Record the owner feedback about copy, stacked images, missed structural
      use of media, stronger precedent, and improved animation as feedback—not as
      implementation instructions.
- [ ] Prohibit manual candidate changes in all acceptance runs.

Acceptance: one reproducible operation starts from the confirmed intake, and no
expected markup or developer-authored design is part of the fixture.

### Phase 1 — Deliver sighted asset evidence to direction

Primary locations:

- `hands/opencode_runner.py`
- `hands/image_visual_evidence.py`
- `hands/builder.py`
- `application/designs.py`
- `core/design_contracts.py`

Tasks:

- [ ] Reuse current media materialization and bounded evidence generation.
- [ ] Attach all selected major images/logos to the direction turn through
      `image_files` with stable ID/SHA provenance.
- [ ] Persist evidence receipt and transcript identity.
- [ ] Fail closed when required visual inputs are unavailable.

Acceptance: a focused test proves the direction request contains hash-matched
image attachments, while a path/dimensions-only request cannot begin generation.

### Phase 2 — Reconnect direction to the experience plan

Primary locations:

- `application/design_orchestration.py`
- `core/design_contracts.py`
- `application/designs.py`
- `hands/opencode_runner.py`

Tasks:

- [ ] Make the one concise direction turn yield a strict, persisted
      `ExperiencePlanBundle`/`ExperienceJourney` using existing contracts.
- [ ] Require evidence-bound asset composition, editorial progression, signature
      behavior, and responsive/reduced-motion meanings before mutation.
- [ ] Bind the plan to the direction artifact, frozen intake, and asset hashes.
- [ ] Remove the new-run condition that permits required plan-based gates to be
      skipped as `experience_plan_not_supplied`.
- [ ] Preserve historical run readability without allowing legacy fallback for
      new confirmed-intake builds.

Acceptance: a new run cannot call the integrated builder without a valid plan,
and the plan hash remains unchanged through generation and validation.

### Phase 3 — Make integrated generation consume the complete direction

Primary locations:

- `hands/opencode_runner.py`
- `hands/builder.py`
- `hands/opencode_provider.py`
- `application/design_orchestration.py`

Tasks:

- [ ] Supply the complete plan, direction, media evidence, owner constraints, and
      relevant skills to one writable build turn.
- [ ] Keep layout, copy, media treatment, GSAP behavior, responsive behavior,
      reduced motion, and resting state in the same implementation ownership.
- [ ] Reject truncation or mismatched plan hashes before invocation.
- [ ] Keep browser/network capability with the host, not the authoring turn.
- [ ] Remove or disable any active post-hoc motion path for new runs without
      removing historical-read compatibility.

Acceptance: the build receipt proves one integrated Ada turn consumed the exact
plan and selected-media hashes and produced a retained candidate.

### Phase 4 — Complete pre-owner evidence and one revision

Primary locations:

- `hands/playwright_quality.py`
- `hands/design_quality.py`
- `hands/design_visual_review.py`
- `application/designs.py`
- `application/design_jobs.py`
- `application/incubations.py`
- `application/intake_lab.py`

Tasks:

- [ ] Run deterministic and temporal gates with the supplied plan; required gates
      may not be skipped.
- [ ] Keep the exact owner iframe, immutable output artifact, progressive-scroll,
      responsive, interaction, and reduced-motion evidence path.
- [ ] Make visual-review findings evidence-bound and solution-neutral.
- [ ] Combine candidate-caused objective and visual/editorial findings into one
      automatic Ada revision operation.
- [ ] Distinguish host-only retries from the one creative revision budget.
- [ ] Re-run the full evidence sequence for the child and expose only the final
      passing candidate as ready for owner review.

Acceptance: one blocking sighted-review finding can create exactly one Ada child;
an infrastructure retry creates none; a failed child cannot create another.

### Phase 5 — Persist evaluative memory

Primary locations:

- `core/incubation_contracts.py`
- `core/intake_ada_store.py`
- `application/incubations.py`
- existing owner-feedback application services

Tasks:

- [ ] Record explicit design feedback as a sanitized, source-linked creative
      episode.
- [ ] Retrieve only incubation-relevant owner taste evidence for direction.
- [ ] Allow owner-designated stronger candidates to contribute screenshots and
      evaluative reasons, not source templates.
- [ ] Keep approval state and production mutation separate from preference
      memory.

Acceptance: a future direction receives the relevant explicit preference with
run/SHA provenance, while unrelated incubations and unexpressed assumptions do
not leak into it.

### Phase 6 — Remove only superseded new-run branches

- [ ] Ensure all new confirmed-intake builds use one direction, one integrated
      build, one browser adapter, one visual reviewer, and one revision creator.
- [ ] Retain historical deserialization for old operation kinds and artifacts.
- [ ] Delete duplicate active paths only after focused tests prove they are no
      longer selected.
- [ ] Do not delete strict journey/asset contracts that provide authoritative
      experience fidelity.
- [ ] Record model-turn count, prompt size, pipeline LOC, and elapsed-time change.

Acceptance: no new run can silently enter a planless, legacy, post-hoc motion,
duplicate-review, or category-specific repair path.

### Phase 7 — Autonomous end-to-end proof

- [ ] Rerun from the confirmed intake or earliest valid persisted boundary, not
      from a manually improved candidate.
- [ ] Confirm Ada produced all source changes.
- [ ] Confirm every selected major asset has a visibly intentional role.
- [ ] Confirm the editorial sequence does not merely repeat intake phrases.
- [ ] Exercise the defining experience in the real owner review surface on
      desktop, tablet, mobile, keyboard/touch where applicable, and reduced
      motion.
- [ ] Confirm hydration and zero console/module/font/image/asset failures.
- [ ] Confirm validation and owner review use the same candidate and output
      bytes.
- [ ] Record model turns and total elapsed time.
- [ ] Confirm production mutation count is zero.

Acceptance: the final review-ready candidate is Ada's autonomous output, visibly
uses the intake and media as a coherent composition and experience, survives the
real owner surface, and reaches review in approximately 20 minutes.

## 10. Required focused tests

Add focused tests before implementation for these behaviors:

1. A confirmed-intake direction request receives every selected major image as a
   hash-matched attachment.
2. Missing required image evidence stops before source mutation.
3. A new creative run cannot generate with no `ExperiencePlanBundle`.
4. Asset composition entries refer only to frozen selected asset IDs/hashes.
5. The direction and build receipts carry the same plan hash.
6. Validation receives the plan and cannot mark composition, journey, or temporal
   gates skipped because it was not supplied.
7. Provider-context truncation or artifact-hash mismatch stops before build.
8. Static phrase presence cannot independently promote a run to passed.
9. The visual reviewer receives legible viewport/temporal evidence and does not
   receive a host assertion that motion passed.
10. A candidate-caused visual blocker creates one automatic Ada revision.
11. A browser/provider infrastructure retry against unchanged bytes creates no
    revision and consumes no creative attempt.
12. A failed automatic revision cannot spawn another automatic revision.
13. The child repeats immutable artifact creation and exact owner-iframe checks.
14. Explicit owner design feedback persists with incubation/run/SHA provenance
    and cannot approve or publish a candidate.
15. New runs cannot select legacy planless, post-hoc motion, or duplicate repair
    branches; historical records remain readable.

Retain the existing browser fixtures that prove hydration, hidden-to-hidden
failure, progressive scroll, reduced motion, failed nested assets, and immutable
preview identity. Run all fixtures through the real review endpoint and iframe
sandbox, not a test-only static server.

## 11. Verification protocol

For every phase:

1. Run the new focused failing test.
2. Implement only the earliest broken boundary.
3. Run related focused tests.
4. Run the full suite and package checks:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
```

5. Run `git diff --check` and inspect the intended diff without resetting
   unrelated working-tree changes.

For the final real run, record:

- incubation, job, run, parent/child, provider, model, session, and transcript
  IDs;
- confirmed intake, genesis/context, direction, plan, and asset hashes;
- candidate SHA, immutable output artifact ID, and output tree hash;
- exact owner review route under the supported mount point;
- browser request failures and console errors;
- desktop/tablet/mobile and reduced-motion evidence IDs/hashes;
- planned and observed defining behavior;
- visual-review outcome and any single revision provenance;
- per-stage and total elapsed time;
- production mutation count, expected to be zero.

## 12. Non-goals and prohibited fixes

- Do not manually redesign, rewrite, brighten, crop, animate, or polish the
  current candidate.
- Do not encode the current business, image feature, visual solution, or owner
  wording in generic Python, configuration, prompts, or tests.
- Do not add industry-to-layout, asset-to-layout, or industry-to-animation lookup
  tables.
- Do not add a banned-pattern list or a deterministic originality score.
- Do not restore a multi-agent creative committee or a post-hoc motion phase.
- Do not add another plan schema, visual reviewer, quality service, repair type,
  or candidate-authored pass signal.
- Do not let a visual reviewer prescribe a replacement design or certify runtime
  behavior from stills.
- Do not let the authoring agent drive an unbounded browser loop.
- Do not use phrase counts as evidence of good copy.
- Do not copy a prior candidate's source as an anti-regression mechanism.
- Do not expose a raw preview URL as a substitute for the Design review flow.
- Do not mutate production without explicit owner approval.

## 13. Definition of done

- [ ] One concise, sighted Ada direction turn produces a persisted, executable,
      hash-bound experience plan from the confirmed intake and approved media.
- [ ] One integrated Ada build turn owns composition, copy, assets, responsive
      behavior, GSAP/interaction, resting state, and reduced motion together.
- [ ] Every selected major asset has a visible evidence-grounded relationship to
      the composition rather than mere placement.
- [ ] Required composition, journey, and temporal gates are supplied with the
      plan and cannot be silently skipped.
- [ ] The immutable artifact validated by the host is byte-identical to the one
      shown in the owner iframe.
- [ ] Hydration, behavior, assets, responsive layouts, and reduced motion are
      exercised in the real owner review surface.
- [ ] One sighted review evaluates static composition and editorial quality
      without pretending to prove runtime facts.
- [ ] At most one automatic Ada-authored revision can address combined
      candidate-caused findings.
- [ ] Infrastructure retries do not consume creative revision budget.
- [ ] Explicit owner taste feedback is durable and source-linked without becoming
      a template or publishing permission.
- [ ] The complete autonomous path is compatible with the approximately
      20-minute promise.
- [ ] Production remains unchanged until explicit owner approval.

## 14. End-of-task mission questions

Answer after each implementation phase and every acceptance run:

1. Did Ada—not the coding agent—create the candidate from the intake?
2. Did the candidate visibly follow the defining experience/adventure path?
3. Was that behavior observed in the real owner review surface after hydration?
4. Did any workaround bypass the autonomous pipeline?
5. Is the result honestly ready for owner feedback within the intended journey?

Any `no` means the mission is not complete.
