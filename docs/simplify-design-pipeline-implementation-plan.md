# Simplify the Design Pipeline Implementation Plan (Replace First, Then Remove)

**Status:** Authoritative corrective plan for design-pipeline simplification.

**Audience:** A coding AI implementing this plan in this repository.

**Relationship to other documents:**
`docs/brand-composition-and-behavior-system-implementation-plan.md` defines the
*product mission* for creative planning, integrated realization, and experience
fidelity. This document keeps that mission and replaces the *host implementation*
of it. Where the two conflict about **how** planning, orchestration, motion, or
review is implemented, this document is authoritative. The mission-level rules
about owner approval, candidate retention, isolation, preview, and production
safety remain in force from `AGENTS.md` and the OpenCode-first plan.

**Read this whole document before touching code. The cleanup is not optional and
is not "later". Removing the bloat is a required phase with its own acceptance
gate.**

---

## 1. Why this plan exists

The product is a single owner journey:

1. A person confirms an intake.
2. Ada consumes the confirmed intake, its assets, copy, constraints, and
   experience plan.
3. Ada carries the work through the design pipeline herself.
4. The owner receives a candidate in the Design review flow.
5. Production changes only on explicit approval.

The current pipeline can technically produce a candidate, but the owner-visible
result got **worse**, not better: no recognizable adventure path, no meaningful
animation, and the design reads as a generic template. At the same time internal
reports declared browser, motion, journey, and visual gates "passed".

That contradiction is the failure. It was caused by **host over-engineering**:

- The host re-implemented multi-agent orchestration in Python instead of using
  OpenCode's native agents/subagents and `task` tool.
- The host turned creative intent into large, hash-bound JSON schemas and
  validated them as pass/fail, so the model learned to satisfy the schema
  (`data-ada-journey-condition` markers, coverage maps, `local_check_status:
  passed`) instead of making a real experience.
- Every failure added another phase or gate. The design pipeline is now
  **~13,812 lines** of application code plus **~9,299 lines** of tests, and one
  confirmed-intake run makes roughly **11+ separate OpenCode/LLM turns**.

**Bloat is not a cosmetic problem. It is the primary technical cause of the
regression.** Large contradictory prompts, strict schemas layered over creative
work, and many overlapping gates make it impossible for the model to think about
the actual design. The model spends its capacity satisfying the harness. The
codebase must be cleaned for the product to work at all.

---

## 2. The target in one sentence

**Keep the specialist architecture (design direction -> concept -> integrated
build) but implement it simply through OpenCode's native agents and prompts,
and delete the Python orchestration, the strict creative contracts, and the
overlapping gates that replaced it.**

The host keeps only what a model cannot own: durable jobs, exact-SHA isolation,
secret/path checks, the authoritative build, real-browser runtime evidence,
preview, and explicit owner approval.

---

## 3. Non-negotiable invariants

These are never weakened by this plan:

- A site mutation is either an explicit owner action or a pending draft.
- Production changes only through explicit approval.
- Every design run is pinned to an exact base commit SHA.
- Every candidate is an immutable commit/ref; a failed later stage never erases
  a retained candidate.
- Local experiments use `push_mode: none` and `publishable: false`.
- GitHub, Cloudflare, R2, admin, SEO, and publishing credentials never enter the
  design child environment.
- Preview works under the deployment mount point (`/ada/`).
- The candidate is reviewed in the Design tab; a raw preview link never
  substitutes for the review flow.
- Missing evidence is `incomplete`, never `passed`.
- Deterministic checks verify measurable facts; they never claim to measure
  taste or to prove that an experience was felt.
- Prompts carry contracts, typed shapes, and behavioral rules only. Never embed
  worked examples, canned replies, sample questions, or preselected creative
  language.
- The coding agent maintaining this repo may repair generic orchestration,
  contracts, adapters, preview, and validation. It may **not** design, rewrite,
  or polish a run-specific candidate.

---

## 4. Target architecture (the simple specialist path)

```
confirmed intake + approved media + design skills + approved capabilities (GSAP)
  -> exact-SHA disposable worktree
  -> STEP 1: DESIGN DIRECTION  (read-only OpenCode turn)
        Produces one original, human-readable design direction grounded in the
        intake and media: concept, art direction, typography/color intent,
        composition intent, the defining experience/adventure, the signature
        interaction, and the motion intent. Persisted as a durable artifact and
        shown in review.
  -> STEP 2: INTEGRATED BUILD  (one OpenCode primary session, writable)
        Receives the confirmed intake and the design direction losslessly.
        Implements the complete candidate in one pass: composition, copy use,
        responsive behavior, the defining experience, reduced motion, and
        performance. It may use OpenCode's native `task`/subagents freely.
  -> host: allowed-path + secret validation
  -> host: authoritative build from the immutable candidate SHA
  -> immutable candidate ref retained
  -> host: real-browser runtime evidence
        hydration, console errors, failed module/asset requests, representative
        viewports, reduced-motion emulation
  -> Design review in the owner surface
  -> explicit owner approve or decline
  -> optional: one owner/visual-feedback refinement run (a new durable candidate)
```

Notes that make this simple:

- **Orchestration lives in OpenCode, not Python.** The design-direction and
  build sessions may use `task` and native subagents. The host must allow
  `{"task": {"*": "allow"}}` for these agents, not deny it.
- **Two model steps, not eleven.** A third "build" step is provided by the host
  build; planning is one prompt-driven session.
- **The design direction is prompt guidance and durable evidence, not a gate.**
  It is stored as an artifact (for review) and injected into the build prompt.
  It has no strict JSON schema and no host pass/fail contract.
- **No host-authored journey/coverage JSON.** The host never requires the model
  to emit implementation coverage maps, journey condition IDs, or
  `local_check_status`.
- **Objective runtime evidence only.** Browser evidence is diagnostics; it does
  not certify the experience, and the owner's observation is authoritative.

---

## 5. Replace-first execution model

The repository must stay green at every step. Do **not** delete the specialist
code first: that leaves broken imports and hours of red tests, which is itself a
cause of confused, low-quality changes.

Order of operations:

1. Add the new thin `native` path alongside the existing specialist path.
2. Prove the new path end-to-end on the frozen acceptance intake.
3. Switch the lab configuration to the new path.
4. **Remove** the specialist machinery, contracts, config, and tests.
5. Rewrite the authoritative plan documents to match the shipped architecture.

Removal (step 4) is a first-class deliverable, not a follow-up. The task is not
done while the obsolete code still exists.

---

## 6. Phases, with acceptance criteria

### Phase 0 — Freeze the acceptance scenario

- [ ] Retain the original confirmed Claro Oscuro intake, its assets, copy,
      constraints, and the expected owner-visible experience as an immutable
      acceptance fixture.
- [ ] Record the single start operation (confirmed intake -> candidate) and the
      single final observation surface (the Design-tab preview for that exact
      candidate SHA).
- [ ] Record the wall-clock budget (target: about 20 minutes) and per-step
      budgets.
- [ ] Prohibit manual candidate edits and manual specialist dispatch during the
      acceptance run.

Acceptance: one action starts from the confirmed intake; the expected result is
described as observable experience conditions, not expected markup.

### Phase 1 — Add the thin native path

- [ ] Add a new orchestration mode `native` (replacing the role of
      `specialist`). Keep `legacy` readable only if needed for historical runs;
      it must not be reachable for new confirmed-intake runs.
- [ ] Implement the design-direction step as one read-only OpenCode turn that
      writes a human-readable design direction artifact (markdown or plain
      text). It must not mutate the repository.
- [ ] Implement the build step as one writable OpenCode primary session that
      receives the intake and the design direction and implements the candidate.
      It must be allowed to use `task`/subagents.
- [ ] The build step must NOT be required to emit a strict plan, a coverage map,
      journey condition IDs, or a passed local-check JSON.
- [ ] Keep the host build authoritative: the candidate is built by the host from
      the immutable SHA, regardless of any local check the model ran.
- [ ] Persist the design-direction artifact and link it to the run so the owner
      and reviewers can read it.

Acceptance:
- A run in `native` mode performs exactly one design-direction turn and one
  build turn (plus the host build), with no specialist phase artifacts required.
- No Python phase state machine, no `_invoke_phase` hash binding, and no strict
  creative contract is required for a new run to succeed.
- The candidate is retained even if later browser evidence is incomplete.

### Phase 2 — Prove the native path on the frozen intake

- [ ] Run the frozen acceptance intake through the `native` path.
- [ ] Inspect the actual Design-tab preview, after hydration, at desktop,
      tablet, mobile, and reduced motion.
- [ ] Confirm the defining experience is visibly present and works.
- [ ] Treat browser console errors, failed module requests, and failed asset
      requests as failures.
- [ ] Record elapsed time and per-step durations.
- [ ] Confirm no production or remote mutation occurred.

Acceptance: the owner can identify the planned design direction and experience in
the real preview without reading source, manifests, or developer notes. If the
experience is not visible, the correct response is to fix the generic prompt or
tooling at the earliest failing boundary and rerun — never to hand-edit the
candidate and never to add a review layer.

### Phase 3 — Remove the bloat (mandatory)

Only after Phase 2 passes. Delete the following and fix all imports.

**Delete files entirely:**
- `src/site_agent/application/design_orchestration.py` (1,611 lines)
- `src/site_agent/hands/opencode_provider.py` (514 lines)
- `tests/test_design_orchestration.py`
- `tests/test_opencode_provider.py`

**Delete orchestration from `hands/opencode_runner.py`:**
- The specialist plan path: `plan_builder`, `design_plan` plumbing, the
  `site-implementer` / `repair-implementer` / `motion-designer` /
  `experience-fidelity-specialist` agent selection for planning.
- `_journey_source_coverage` and every use of it.
- The `record_implementation_phase`, `run_experience_fidelity_phase`, and
  `record_repair_phase` calls.
- The specialist `_design_prompt` branches that inject `specialist_locked_plan`
  / `specialist_repair_brief` and demand strict JSON.
- Keep: worktree creation, agent/skill installation, `run_opencode_turn`,
  allowed-path/secret validation, host manifest, host build, candidate commit,
  transcript persistence, media/font materialization.

**Delete from `application/designs.py`:**
- `_experience_plan_for_run` and all `experience_plan` plumbing into
  `run_quality_gates`.
- The specialist branches in `execute_build` / `validate_run`.
- Duplicate/overlapping refinement creators: keep exactly one refinement
  operation. Remove `create_sighted_refinement_run` and `create_derived_page_run`
  if they duplicate `create_visual_refinement_run`; otherwise collapse them into
  one method. Preserve the ability to create exactly one durable child candidate
  from a critique.
- Keep: lifecycle transitions, candidate retention, host build invocation,
  quality-report recording, screenshot artifacts, review-draft creation.

**Delete from `application/design_jobs.py`:**
- `_specialist_orchestration_enabled`, `_run_specialist_reviews_if_ready`, and
  the specialist-review call site.
- Keep the durable worker loop, recovery, and `_validate_retained` (but remove
  the early return that bypassed review; with one review path there is nothing
  to bypass).

**Delete from `hands/design_quality.py`:**
- The creative/experience proxy gates: the `experience_journey` block,
  `evaluate_composition_plan` and its `composition` gate, and
  `evaluate_temporal_evidence` / the `temporal` gate, plus the
  `ExperiencePlanBundle` branches in `_run_quality_in_workspace`.
- Keep objective gates: repository path/secret policy, dependency policy,
  native-source sanity where generic, fonts, build, output, content, conversion,
  manifest, and the browser runtime evidence. Keep the browser evidence as
  evidence; do not let it stand in for the owner's observation.

**Delete from `core/design_contracts.py`:**
- Specialist creative contracts: `ExperiencePlanBundle`, `ExperienceJourney`,
  `BrandBehaviorSystem`, `AssetCompositionPlan`, `BrandSourceMap`,
  `LogoCompositionRule`, `AssetVisualEvidence`, `ExperienceFidelityReport`, and
  the phase-envelope classes `CopyDeck`, `CreativeConcept`, `DesignPlanBundle`,
  `ImplementationReport`, `MotionReport`, `CreativeRealizationReview`,
  `CriticReport`, `RepairBrief`, `RepairReport`, `AssetEvidenceReport`,
  `BrandSourceReport`, `TransferReview`, `TemporalReview`.
- Keep: `DesignRunStatus`, `DesignOperationKind`, `DesignPhase`,
  `DesignPhaseStatus`, `SiteIntake`, `PageBuildRequest`, `BuildTarget`,
  `DesignBrief`, `ArtDirection`, `DesignManifest`, `DesignContextSnapshot`,
  `VisualCritiqueReport`, `QualityReport`, `DesignCandidateReceipt`,
  `TemporalExperienceEvidence` only if still used by the simplified browser
  evidence; remove it if not.

**Delete configuration:**
- `design_engine.orchestration: specialist` and `require_experience_plan`.
- `design_engine.specialist_timeout_seconds`.
- The `specialist` branch in `hands/builder.py` (`build_design`).
- Update `config.py` validation accordingly; `orchestration` should accept
  `native` (and, if retained, `legacy`).
- Update `defaults.yaml` and `intake-ada.yaml`.

**Delete tests that only exercised removed machinery:**
- Most of `tests/test_design_composition_quality.py`.
- Specialist assertions in `tests/test_design_quality.py`,
  `tests/test_design_service.py`, `tests/test_design_builder.py`.
- Any test that asserts a candidate passes because journey markers exist in
  source.

Acceptance:
- `rg -n "specialist|SpecialistDesignCoordinator|ExperiencePlanBundle|ExperienceJourney|journey_condition|_invoke_phase|opencode_provider" src tests` returns no runtime references.
- `ruff`/compile and the full test suite are green.
- The design pipeline's application LOC and prompt sizes are measurably smaller
  than the pre-plan baseline. Record the before/after numbers in the commit
  message.

### Phase 4 — Rewrite the durable plan and instructions

- [ ] Rewrite `docs/brand-composition-and-behavior-system-implementation-plan.md`
      so that the specialist architecture is described as **OpenCode-native
      (design direction -> integrated build)** with no host phase machine and no
      strict creative gate. Preserve the mission and invariants.
- [ ] Update `docs/opencode-first-design-pipeline-implementation-plan.md` to
      point at the two-step native path.
- [ ] Update `AGENTS.md` where it describes specialist orchestration or the
      strict experience-plan gate, so it matches the shipped architecture. Keep
      the mission lock, invariants, and the "do not manually polish candidates"
      rule intact.
- [ ] Add a short note that bloat is a defect: new host gates, phases, or
      schemas over creative work are presumptively rejected.

### Phase 5 — Final acceptance

- [ ] Run the frozen intake end-to-end through the simplified path again.
- [ ] Observe the defining experience in the real Design preview at all required
      viewports and reduced motion.
- [ ] Confirm zero console/module/asset failures after hydration.
- [ ] Confirm no production mutation and no manual candidate edits.
- [ ] Confirm the elapsed time is compatible with the product promise.
- [ ] Run the full verification suite (section 9).

---

## 7. What the model must actually receive (prompt/tooling contract)

**Design-direction turn (read-only):** the confirmed intake, approved media
evidence, the owner's creative request, and the design skills. It returns one
original design direction. It must not copy a template.

**Build turn (writable primary session):** the confirmed intake, the design
direction artifact verbatim, approved media/file paths, the design + motion
skills, and the approved capabilities (GSAP when configured). It implements the
whole candidate. It may delegate bounded exploration/validation to native
subagents via `task`, but final edits stay in the primary session.

**Host:** path/secret policy, the authoritative build, capture runtime evidence,
retain the immutable candidate, expose the Design preview, and wait for the
owner.

Do not add: plan JSON gates, coverage maps, journey markers required for a pass,
review panels, transfer critics, or motion/fidelity phases.

---

## 8. Anti-patterns (do not repeat)

- Do not add a new gate, phase, schema, or reviewer to compensate for a weak
  result. Fix the prompt or the tool boundary instead, then rerun.
- Do not treat source markers, a manifest entry, a model claim, or an internal
  gate marked `passed` as proof the experience exists.
- Do not let a static page pass a behavioral gate.
- Do not hand-design, rewrite, or polish a run-specific candidate to make a run
  look successful.
- Do not preserve the specialist Python code "just in case". If it is not in the
  target architecture, remove it.
- Do not expand infrastructure before the simplified intake-to-review journey
  passes.
- Do not describe the mission as complete unless the owner-visible Design surface
  was exercised after hydration.

---

## 9. Verification commands

Run focused tests first, then the full suite and the package smoke test:

```bash
.venv/bin/pytest -q tests/test_design_quality.py tests/test_design_service.py \
  tests/test_design_builder.py tests/test_design_contracts.py
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
```

Static reference check (must return nothing):

```bash
rg -n "SpecialistDesignCoordinator|ExperiencePlanBundle|ExperienceJourney|journey_condition|_invoke_phase|opencode_provider" src tests
```

---

## 10. Definition of done

- [ ] A confirmed intake produces a candidate through the `native` path: one
      design-direction turn, one integrated build turn, host build, browser
      evidence, Design preview.
- [ ] The defining experience/adventure is observable in the real Design-tab
      preview at desktop, tablet, mobile, and reduced motion.
- [ ] Browser console errors, failed module requests, and failed asset requests
      are treated as failures.
- [ ] The specialist Python orchestration, strict creative contracts, config,
      and their tests are deleted.
- [ ] The authoritative plan and `AGENTS.md` describe the simplified
      architecture.
- [ ] Full test suite, compile check, and wheel build pass.
- [ ] No production mutation and no manual candidate editing occurred.
- [ ] Before/after code-size and step-count numbers are recorded.

---

## 11. Progress checklist

- [ ] Phase 0: acceptance fixture frozen
- [ ] Phase 1: `native` path added and green
- [ ] Phase 2: `native` path proven on frozen intake
- [ ] Phase 3: specialist bloat removed and suite green
- [ ] Phase 4: authoritative plan and `AGENTS.md` rewritten
- [ ] Phase 5: final acceptance passed
