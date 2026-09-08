# Canonical OpenCode Design Test Implementation Plan

> **Superseded on 2026-08-31.** Do not implement further phases from this
> document. The authoritative corrective plan is
> `docs/opencode-first-design-pipeline-implementation-plan.md`. It retains every
> safe candidate before validation, removes hidden same-session repair loops,
> and tests the complete DeepSeek implementation plus Qwen visual-refinement
> workflow.

**Status:** Implementation contract; implementation in progress after owner authorization

**Date:** 2026-08-31

**Model for the first acceptance run:** `deepseek/deepseek-v4-flash-0731`

**Supersedes for design-test execution:**

- `docs/react-design-creation-system-implementation-plan.md`
- the local `ReactDesignSpec -> AstroReactCompiler -> frontend_scaffold` test path
- the current multi-model comparison scripts and comparison UI

The earlier documents remain historical evidence until the cleanup phase in this
plan. They are not implementation authority for the next design test.

## Purpose

Test Ada's real product workflow from one owner design request to one reviewable,
immutable website candidate. The test must use the same application service,
durable job, OpenCode builder, quality, preview, and approval boundaries intended
for production. It may differ from production only in its isolated filesystem,
credential filtering, fixed model, immutable source SHA, and non-publishable
target.

This is not a test of a JSON-to-template compiler. The implementation agent owns
the page composition, markup, styles, motion, responsive behavior, and use of
available frontend capabilities. The host owns facts, safety, immutable identity,
quality evidence, and the ability to publish.

## Product Decision

Use the existing canonical path:

```text
authenticated owner message
  -> durable ChatJob
  -> typed SiteIntake plus frozen Ada context
  -> DesignService
  -> durable DesignRun queued for background execution
  -> DesignJobExecutor
  -> NativeOpenCodeBuilder
  -> stage_design_build()
  -> native OpenCode build session and bounded subagents
  -> implementation in an exact-SHA detached worktree
  -> build, browser capture, deterministic checks, visual critique
  -> same-session repair when findings are actionable
  -> immutable candidate commit and local namespaced ref
  -> post-commit reproduction of every blocking gate
  -> existing Design tab preview and review record
```

Do not add another design application service, another builder protocol, another
frontend compiler, or a second run database. Extend the existing typed contracts
and services where information is missing.

## Meaning Of One Shot

One shot means one owner interaction, not one model call.

- The HTTP request immediately creates a durable chat job and returns its ID.
- The chat job creates and links a design run, then completes with an owner-safe
  acknowledgment and `design_run_id`.
- The design run continues asynchronously after the chat job completes.
- Ada may inspect, delegate, implement, build, capture screenshots, criticize,
  and repair within that one design run.
- Ada asks a follow-up only when `IntakeAssessment` identifies a genuinely
  blocking contradiction or missing destination. A preference that Ada can
  decide safely is not a blocking question.
- The owner is not asked to request a second generation merely because Ada
  skipped internal review.

## Canonical Reuse Map

### Keep as authoritative boundaries

- `application/designs.py`: create, queue, execute, validate, and review design
  runs.
- `application/design_jobs.py`: asynchronous design execution using the run ID
  as the durable handle.
- `core/design_contracts.py`: validated intake, request, target, manifest,
  quality, and receipt contracts.
- `core/memory.py`: design runs, events, chat jobs, conversations, memories, and
  migrations.
- `hands/builder.py`: `DesignBuilder` and `NativeOpenCodeBuilder`.
- `hands/opencode_runner.py`: exact-SHA worktrees, OpenCode sessions, repairs,
  candidate commits, and refs.
- `hands/design_quality.py`: host-owned gate aggregation and fail-closed state.
- `hands/playwright_quality.py`: concrete local browser inspection and external
  screenshots.
- `web/preview.py`: generated-output builds, mount-safe URL rewriting, sandboxing,
  and cache behavior.
- `web/server.py`: authenticated HTTP translation and scoped preview tokens.
- `web/static/admin.html`: the existing Design tab and review controls.
- `runtime.py`: service composition. Do not introduce another global context.

### Keep but correct

- `brain/design_brief.py` remains the deterministic fact and objective
  normalizer.
- `brain/art_direction.py` may provide preliminary hypotheses, but it must not
  predetermine the implemented visual system. OpenCode's creative process owns
  exploration and synthesis.
- `brain/page_strategy.py` remains the typed request compiler, extended with the
  frozen context and execution requirements.
- `brain/editor.py` remains owner-intent translation, but design work must no
  longer return a free-form `spawn_build` brief for the legacy builder path.
- `hands/frontend_dependencies.py` may be reused only as an approved capability
  catalog. It must not select composition, markup, CSS, or a component
  vocabulary.

### Retire from the canonical test

- `application/design_lab.py`
- `application/model_comparison.py`
- `brain/react_design.py`
- `core/react_design_contracts.py`
- `hands/astro_react_compiler.py`
- `frontend_scaffold/`
- `web/design_lab.py`
- scaffold-specific commands, scripts, tests, and generated comparison assets

Do not delete these in an early phase. First make the canonical DeepSeek run
replace their useful behavior, then remove them in one traceable cleanup phase.

## Current Gaps

1. Owner chat can still route broad design work through `spawn_build` and the
   legacy `stage_build()` path instead of creating a typed design run.
2. Design runs persist intake and planning but not a frozen, reproducible Ada
   context snapshot.
3. `install_agent_files()` reads current persona and memory at execution time,
   so a delayed job can see different context from the accepted request.
4. The OpenCode prompt asks for implementation but does not require a recorded
   creative exploration, explicit subagent roles, screenshot review, or a final
   self-critique.
5. The current repair loop handles host validation findings, but visual quality
   is not a real blocking gate.
6. Browser checks detect basic runtime and layout failures but do not calculate
   text contrast, font-load success, first-viewport hierarchy, image crop risk,
   or meaningful reduced-motion behavior comprehensively.
7. The post-commit worker validation cannot repair because the implementation
   worktree has already been removed. All repairable gates must run before the
   commit and then be reproduced after it.
8. The Design tab can preview a candidate, but the test needs a simple
   full-width `Original | DeepSeek` selector rather than a separate comparison
   application or simultaneous columns.
9. A server restart interrupts chat work explicitly but does not apply an
   equally explicit interrupted-state policy to in-progress design runs.

## Non-Negotiable Invariants

- The source starts from the exact configured production commit SHA.
- Test work uses a dedicated clone, database, cache, screenshots directory, and
  artifact directory outside the live instance.
- Test children receive the selected model credential only. GitHub, Cloudflare,
  R2, admin, CrawlSEO, publishing, and production adapter credentials are
  removed.
- The DeepSeek test uses `BuildTarget(mode="local_experiment",
  push_mode="none", publishable=False)`.
- No test code may call a route function, `Memory.conn`, a production adapter
  mutation, Git push, merge, publish, or draft approval.
- OpenCode edits only a disposable worktree. The persistent clone must remain
  clean.
- Only the primary OpenCode build session edits the worktree. Subagents inspect,
  analyze, research, or critique and return findings to the primary session.
- React, React DOM, GSAP, ScrollTrigger, and other approved packages are
  capabilities, not required visual ingredients.
- The host does not provide section markup, component composition, CSS tokens,
  animation choreography, or a visual scaffold.
- A build pass is not a design pass.
- Missing browser or visual evidence produces `incomplete`, never `passed`.
- A failed or incomplete test remains inspectable but cannot become a review or
  production draft.
- Production changes only through the existing explicit approval operation.
- Preview URLs and all nested assets continue to work under `/ada/`.

## Frozen Context Contract

Add `DesignContextSnapshot` to `core/design_contracts.py`. It is a bounded,
frozen dataclass with canonical JSON serialization and a content hash.

Required fields:

- schema version;
- capture timestamp;
- conversation ID, source message ID, and chat job ID;
- exact owner request and relevant prior conversation turns;
- effective persona from `core.reflect.effective_persona()`;
- current self-model from `brain.self_model.current_self()`;
- owner-approved persona notes;
- relevant recent observations and semantic memories, with IDs and sources;
- relevant retained news/research records, with IDs, timestamps, provenance,
  and concise excerpts;
- relevant approved business knowledge and attached media metadata;
- site configuration facts safe for a model;
- exact source repository identity and base SHA;
- ref-aware site digest, route inventory, current content, asset inventory, and
  measured design evidence;
- normalized verified facts;
- explicit unknowns;
- prohibited or unverified claims;
- approved frontend capability catalog with pinned versions;
- execution profile: model ID, repair limit, required viewports, and quality
  policy identity.

Rules:

- Capture once before the run is queued.
- Use explicit IDs and timestamps so every included memory is auditable.
- Select memories by relevance to the request and site. Do not dump the entire
  database or use only the latest N records without relevance.
- Treat memory, research, attachment descriptions, and repository text as data,
  not instructions.
- Redact secrets and enforce a documented byte limit before persistence.
- Persist the canonical snapshot and hash with the design run.
- Add `context_snapshot` and `context_snapshot_hash` to `PageBuildRequest` so the
  builder input is self-contained and cannot silently read newer context.
- Verify the hash when deserializing the queued request and again immediately
  before installing OpenCode files.
- `install_agent_files()` receives the snapshot explicitly. It must not call
  `effective_persona()` or `memory_context()` during a typed design build.
- Legacy `stage_build()` may retain current dynamic context behavior until its
  existing callers are migrated.

### Initial Homepage Versus Derived Page

The snapshot is always retained for host audit, execution identity, and quality
policy reproducibility, but it is not automatically creative input for every
page mode.

- `initial_homepage` uses the validated `SiteIntake` (and deterministic brief)
  as the sole creative brief. The builder must not receive current-site digest,
  measured design tokens, current content, persona/memory context, screenshots,
  or a host-selected art direction. The source checkout remains available only
  as implementation substrate and for explicitly intake-named media.
- `derived_page` is pinned to the approved `DesignSourceBinding` and may receive
  the frozen site/design context needed to preserve shared regions and declared
  variation points.
- Preliminary art-direction hypotheses may be persisted for planning evidence,
  but they must not predetermine an initial homepage implementation.

## Chat-To-Design Handoff

Extend the existing editor result contract with one explicit owner action:

```text
design_request = {
  intent: initial_site | redesign | derived_page,
  intake: validated SiteIntake payload,
  owner_summary: short acknowledgment,
  source_message_id: integer
}
```

The editor must choose `design_request` instead of `spawn_build` when the owner
asks for a new site, substantial redesign, new visual direction, or complete
page creation that belongs to the design engine.

`core/chat_jobs.run_job()` then performs only this handoff:

1. Validate `SiteIntake`.
2. Resolve the exact source SHA without fallback.
3. Capture `DesignContextSnapshot`.
4. Call `DesignService.create_run()` or `create_experiment()`.
5. Call `DesignService.queue_build()` with a host-created `BuildTarget`.
6. Enqueue the run on the existing `DesignJobExecutor`.
7. Complete the chat job with `design_run_id`, current status, and an owner-safe
   acknowledgment.

The chat worker must not call `execute_build()` and must not wait for OpenCode.
The HTTP adapter and editor must not construct Git refs or mutation policy.

Persist links in both directions:

- chat job result includes `design_run_id`;
- design run stores `conversation_id`, `source_message_id`, and `chat_job_id`;
- design events include these IDs in diagnostics;
- conversation reads continue to show the completed chat job even while the
  linked design run is active.

## OpenCode Creative Execution

Keep OpenCode's built-in `build` agent as the primary implementation agent. Add
requirements to the typed design instructions rather than replacing it with a
custom universal agent.

### Required process

1. For an initial homepage, inspect the exact source only for build constraints,
   required output behavior, and explicitly supplied media. For a derived page,
   inspect the approved source, content, assets, routes, and rendered site.
2. Delegate bounded read-only analysis to subagents.
3. Develop multiple textual creative directions tied to the subject, audience,
   offer, and available assets.
4. Challenge generic patterns and choose one direction with a concise rationale.
5. Define content hierarchy, conversion path, typography, composition, image
   treatment, responsive translation, motion purpose, and reduced-motion plan.
6. Implement the chosen direction directly in the worktree; an initial homepage
   must be an intake-led composition rather than a restyle of the source page.
7. Run the site's real build and local checks.
8. Inspect browser screenshots and computed evidence at every required viewport.
   If the implementation runtime cannot inspect pixels, perform one bounded DOM
   and computed-style check and leave pixel review to the host quality gates.
9. Delegate a read-only visual/UX critique after implementation.
10. Repair concrete findings in the same primary session.
11. Rebuild and re-inspect all viewports.
12. Write the design manifest and leave all implementation changes uncommitted
    for host finalization.

### Bounded subagent roles

The primary agent may combine roles when the task is small, but the DeepSeek
acceptance run must exercise these distinct responsibilities:

- site and asset analyst: source architecture, existing routes, content, assets,
  and constraints;
- audience and conversion critic: hierarchy, trust, factual safety, and primary
  action;
- creative-direction challenger: subject specificity and template-risk review;
- post-build visual critic: screenshots, responsive composition, typography,
  imagery, contrast, and motion behavior.

Subagent responses are advisory artifacts. The primary session records the
selected direction, rejected alternatives, and adopted findings in a bounded
execution report. Do not persist private chain-of-thought.

### Capability policy

- Pass a host-verified catalog of approved, pinned libraries in the context.
- Do not require a library merely because it is available.
- Permit package/config changes only when the build target explicitly allows
  those paths and the dependency validator confirms every added package against
  the catalog.
- Remove the blanket typed-build prohibition on `package.json` only behind this
  explicit target policy. Keep it for legacy broad builds.
- Require a lockfile change with any dependency change.
- Disable lifecycle scripts during dependency installation in the test.
- Block arbitrary package names, remote scripts, CDN URLs, and unpinned versions.
- React adoption must preserve static output, current routes, metadata, and the
  configured build contract. This plan does not mandate a production framework
  migration.

## Quality And Repair Architecture

Use two validation passes with the same policy.

### Pre-commit repairable pass

Run inside the active implementation worktree before `finalize_design_target()`:

- changed-path and dependency policy;
- secret and symlink checks;
- real site build;
- generated route and asset inventory;
- document and factual checks;
- concrete Playwright inspection;
- deterministic visual metrics;
- DeepSeek screenshot/UX critique;
- design-manifest conformance.

If blocking findings are repairable, continue the same OpenCode session with
only concrete findings and relevant artifact paths. Re-run every gate after each
repair. Default maximum: two repair turns after the initial implementation.

Stop immediately for path escape, credential exposure, unavailable immutable
base, target-policy breach, or prohibited remote mutation. Stop when a repair
turn produces no material change.

### Post-commit reproduction pass

After the candidate commit and local ref exist, `DesignService.validate_run()`
checks out the exact candidate SHA and reruns every blocking gate. It does not
repair. A mismatch between pre-commit and post-commit results is a blocker and
must retain both reports.

Only the post-commit report can transition a run to `ready_for_review`.

### Deterministic visual evidence

Extend the browser adapter and quality policy to record and gate:

- computed foreground/background contrast for visible text, including text over
  images and pseudo-elements where measurable;
- loaded font families versus fallback fonts;
- text size, line height, measure, and clipping for headings and body copy;
- first-viewport H1, primary action, and important image visibility;
- horizontal overflow and viewport-edge clipping;
- fixed/sticky chrome overlap;
- image intrinsic dimensions, rendered dimensions, aspect ratio, object-fit,
  crop position, and low-resolution upscaling;
- touch target size and spacing;
- visible keyboard focus;
- navigation behavior at desktop and mobile widths;
- runtime errors and failed local requests;
- animation counts and active ScrollTriggers;
- reduced-motion behavior with both `reduce` and `no-preference` contexts;
- screenshot path and SHA for every route and viewport.

Minimum contrast blockers follow WCAG thresholds. Do not average colors across a
section and call that evidence; sample the actual text background or report the
measurement as unavailable.

### Structured visual critique

Add a typed `VisualCritiqueReport` with:

- model ID;
- candidate and screenshot hashes;
- viewport and route references;
- findings with severity, category, evidence reference, and repair suggestion;
- strengths worth preserving;
- generic-template signals;
- subject-specificity assessment;
- final disposition: `pass`, `repair`, or `incomplete`.

The DeepSeek-only test must confirm before generation that the selected model can
consume the screenshot evidence through the configured OpenCode/provider path.
If it cannot, do not substitute another model silently. Mark visual critique
unavailable and the run incomplete until a DeepSeek-compatible evidence path is
implemented.

A numeric aesthetic score alone never passes or fails a run.

## Artifacts And Persistence

Add append-only persistence fields or a run-artifact table after checking the
latest migration number. Do not store large binary screenshots in SQLite.

Persist:

- context snapshot and hash;
- conversation, message, and chat job IDs;
- selected model and provider identifiers;
- OpenCode session ID;
- bounded native tool-call summary and subagent role summary;
- creative execution report;
- pre-commit quality attempts;
- post-commit quality report;
- visual critique report;
- baseline and candidate screenshot manifests;
- candidate receipt and manifest;
- artifact-root-relative paths and SHA-256 hashes.

Store screenshots, logs, and reports under a run-owned directory outside the
customer repository. Every path must resolve below the configured artifact root.
Never commit OpenCode configuration, screenshots, caches, reports, or session
state to the customer repository.

Run events should use owner-safe stage names:

```text
created
context_captured
queued
claimed
analyzing
exploring_direction
implementing
building
inspecting
critiquing
repairing
validating
candidate
ready_for_review | failed | cancelled | interrupted
```

Technical details remain bounded and available under diagnostics.

## Job Lifecycle And Recovery

Keep one `DesignJobExecutor`; do not delegate the job to an OpenChamber session or
another queue.

- Persist a `claimed` event before execution.
- On startup, re-enqueue only runs whose complete typed request and target were
  durably queued but never claimed.
- Mark runs found in `building`, `repairing`, or `validating` after process death
  as `interrupted` or failed-with-retry metadata. Do not replay side effects
  implicitly.
- Add an explicit owner retry operation that creates a new run pinned to the same
  input snapshot and base SHA. Do not mutate a terminal run back to queued.
- Cancellation remains cooperative; check cancellation between OpenCode turns and
  quality stages.
- A completed, failed, cancelled, or interrupted run remains inspectable by ID.

If adding `interrupted`, update the typed transition matrix and persistence tests
before updating worker behavior.

## Review Experience

Reuse the current Design tab, scoped preview tokens, `PreviewBuildCache`, HTML/CSS
rewriting, iframe sandbox, and explicit production approval flow.

For the isolated DeepSeek test:

- show one full-width preview iframe;
- offer `Original` and `DeepSeek` as mutually exclusive selectors;
- keep the page selector and desktop/tablet/mobile controls;
- resolve Original from the exact base SHA and DeepSeek from the exact candidate
  SHA;
- show concise run status and the selected direction;
- show blockers, warnings, repaired findings, and evidence under progressive
  disclosure;
- expose no approve, publish, merge, or promote action for `local_experiment`;
- retain the candidate after the local server stops.

Do not use side-by-side columns, raw preview URLs, or a separate comparison
server as a substitute for Design review.

## Implementation Phases

Implement phases in order. Start each phase with the focused failing tests.

### Phase 0: Baseline And Safety Inventory

Tasks:

- Record current Git status without reverting unrelated work.
- Record current migration count, full test count, package smoke result, and disk
  availability.
- Pin the production source SHA and verify the dedicated experiment paths do not
  overlap live clone/data paths.
- Capture remote refs, persistent clone status, and production database hashes as
  mutation sentinels.
- Identify which current files belong exclusively to the scaffold test before
  later deletion.

Focused tests:

- experiment path overlap fails before clone or model activity;
- environment retains only the selected model credential;
- local target cannot push or become publishable;
- immutable base resolution never falls back to another ref.

Acceptance:

- The test can prove zero live or remote mutation on every exit path.

### Phase 1: Frozen Context And Traceability

Likely files:

- `core/design_contracts.py`
- `core/memory.py`
- `brain/prompts.py`
- `brain/self_model.py`
- `application/designs.py`
- `brain/page_strategy.py`

Tasks:

- Add and validate `DesignContextSnapshot`.
- Add persisted context and source-link fields.
- Implement relevance-bounded snapshot capture using existing memory methods.
- Make the typed request carry and verify the snapshot.
- Make typed OpenCode setup consume only the frozen snapshot.

Focused tests:

- canonical hash is stable across key ordering;
- delayed execution receives the original persona/memory, not later mutations;
- included memories retain source IDs and provenance;
- hostile memory and attachment text remains data, not instructions;
- oversized context fails before queueing;
- secrets are absent from persisted context;
- request/context hash mismatch fails before worktree creation.

Acceptance:

- A run can be reproduced from persisted input without consulting current Ada
  state.

### Phase 2: Durable Chat Handoff

Likely files:

- `brain/editor.py`
- `core/chat_jobs.py`
- `application/designs.py`
- `application/design_jobs.py`
- `web/server.py`
- `web/static/admin.html`

Tasks:

- Add the typed `design_request` editor result.
- Route substantial design intent away from legacy `spawn_build`.
- Create, link, queue, and enqueue one design run from the chat worker.
- Complete chat promptly without waiting for design execution.
- Show the linked design status in the conversation and Design tab.

Focused tests:

- a redesign message creates one chat job and one linked design run;
- chat completion precedes OpenCode execution;
- duplicate worker delivery does not create a second run;
- non-design focused edits retain their existing behavior;
- a blocking intake issue asks one question and queues no build;
- a non-blocking preference is decided by Ada and queues the run;
- route handlers call application services and never the builder directly.

Acceptance:

- One owner message produces a durable asynchronous design run through
  `DesignService`.

### Phase 3: Native OpenCode Creative Loop

Likely files:

- `hands/opencode_runner.py`
- `hands/builder.py`
- `brain/art_direction.py`
- existing OpenCode skill files

Tasks:

- Replace dynamic typed-build context installation with the frozen snapshot.
- Expand `_design_prompt()` with the required creative and review process.
- Preserve OpenCode task permission and primary-session edit ownership.
- Capture session/tool/subagent summaries without private reasoning.
- Add approved dependency capability policy without adding visual scaffolding.
- Make progress stages durable and owner-safe.

Focused tests:

- typed build prompt includes the exact snapshot hash and execution requirements;
- subagent instructions prohibit concurrent worktree edits;
- tool evidence distinguishes primary edits from read-only delegated work;
- package changes outside the approved catalog fail;
- an approved pinned package plus lockfile passes policy;
- the agent is not given fixed section kinds, CSS tokens, or markup;
- candidate still starts from and descends directly from the exact base SHA.

Acceptance:

- The full coding agent, not a host template, determines the implemented design.

### Phase 4: Browser Evidence, Visual Critique, And Repair

Likely files:

- `hands/playwright_quality.py`
- `hands/design_quality.py`
- `hands/opencode_runner.py`
- `core/design_contracts.py`

Tasks:

- Add deterministic visual metrics and both motion preferences.
- Add typed DeepSeek visual critique.
- Run all repairable gates before commit.
- Continue the same OpenCode session for repairs.
- Reproduce all gates against the exact candidate SHA after commit.
- Keep artifacts outside the repository.

Focused tests:

- dark text on a nearly identical dark background is a blocker;
- fallback font use is reported;
- low-resolution image upscaling is reported;
- mobile overflow, clipping, chrome overlap, and missing focus are blockers;
- missing reduced-motion behavior is a blocker when motion exists;
- unavailable screenshot critique yields `incomplete`;
- repair receives concrete findings and retains the same session ID;
- every gate reruns after repair;
- unchanged repair stops the loop;
- pre/post-commit evidence mismatch fails the run;
- screenshots and reports are never committed.

Acceptance:

- The previously unreadable DeepSeek candidate cannot pass.
- Every ready candidate has reproducible desktop, tablet, and mobile evidence.

### Phase 5: Immutable Original/DeepSeek Review

Likely files:

- `web/preview.py`
- `web/server.py`
- `web/static/admin.html`
- `tests/test_preview.py`
- `tests/test_design_web.py`

Tasks:

- Add baseline variant resolution by the run's exact base SHA.
- Reuse one preview cache keyed by run, variant SHA, build config, and overlay.
- Add the one-at-a-time selector to the Design tab.
- Expose quality and critique evidence under details.
- Keep experiments read-only.

Focused tests:

- Original and DeepSeek resolve exact, different SHAs;
- nested CSS, images, fonts, scripts, and fetches remain under `/ada/`;
- preview token scope cannot cross run or variant;
- experiment UI contains no mutation action;
- only one preview iframe is rendered at a time;
- mobile admin layout remains usable;
- expired tokens and path traversal fail closed.

Acceptance:

- The owner can inspect the complete original or candidate at full width within
  the existing Design workflow.

### Phase 6: Canonical DeepSeek Test Command

Likely files:

- `main.py`
- `application/designs.py`
- a minimal script that invokes the public CLI, if shell automation is needed

Tasks:

- Make the existing `design-experiment` command queue and execute the canonical
  service path with the frozen context and concrete browser adapter.
- Remove OceanicVibes path assumptions from generic code; keep them in the
  instance config or fixture.
- Force the first acceptance run to the exact DeepSeek model.
- Print run ID, base SHA, candidate SHA when available, status, artifact root,
  and local Design URL. Do not print a raw candidate preview as the review flow.
- Preserve failed and incomplete runs for diagnosis.

Focused tests:

- the command instantiates `DesignService` and `NativeOpenCodeBuilder`, not
  `LLMDesignPlanner` or `AstroReactCompiler`;
- the command passes `push_mode=none` and no production credentials;
- browser evidence is enabled and required;
- model ID is exact and persisted;
- failure still runs mutation sentinels and retains diagnostics.

Acceptance:

- One command exercises the same design path that owner chat will use.

### Phase 7: Retire The Parallel Scaffold Test

Tasks:

- Remove the scaffold planner/compiler/runtime modules listed in the reuse map.
- Remove scaffold-specific commands, scripts, tests, package data, and docs.
- Remove multi-model UI code while preserving generic single-run preview code.
- Retain generic pinned dependency and Playwright utilities only where the
  canonical path uses them.
- Add supersession notes or consolidate historical findings into one POC report.

Focused tests:

- no production or test import references removed modules;
- package wheel contains no obsolete scaffold;
- CLI help exposes no invalid design-lab path;
- existing non-design chat, draft, journal, and approval behavior remains green.

Acceptance:

- There is one design pipeline and one review path.

### Phase 8: DeepSeek End-To-End Acceptance Run

Preconditions:

- full focused and repository verification pass;
- enough disk for source clone, worktrees, dependencies, screenshots, and wheel;
- DeepSeek screenshot evidence support proven;
- no active production mutation work;
- baseline and mutation sentinels recorded.

Execute:

1. Create the dedicated experiment workspace.
2. Resolve and record baseline SHA
   `56aa25740389f74e4499d35d528d4b2376c82369`.
3. Submit the customer-equivalent design request once.
4. Observe the durable chat-to-design handoff.
5. Let the design job complete its internal analysis, implementation, critique,
   and bounded repairs.
6. Verify all deterministic and visual evidence.
7. Inspect Original and DeepSeek one at a time on desktop, tablet, and mobile.
8. Record manual findings without changing the candidate.
9. Verify remote refs, live clone, live data, and production database sentinels.

Technical acceptance:

- exact DeepSeek model and context hash are recorded;
- native OpenCode tool and subagent evidence exists;
- candidate descends directly from the pinned base;
- no remote or live mutation occurred;
- builds and required routes pass;
- browser, accessibility, contrast, and reduced-motion gates pass;
- visual critique is `pass`, not unavailable;
- post-commit reproduction matches pre-commit evidence;
- candidate is available in the existing Design tab;
- the experiment exposes no approval action.

Product acceptance:

- result is clearly specific to OceanicVibes rather than a generic blue travel
  or wellness template;
- typography is intentional and fully loaded;
- first viewport communicates the offer and primary action clearly;
- imagery is sharp, purposeful, and well cropped;
- desktop and mobile use deliberate compositions, not simple shrinking;
- motion supports hierarchy and meaning and degrades cleanly;
- verified facts are preserved and unknown claims are not invented;
- the candidate is at least credible enough for owner review.

The engine is not accepted merely because all technical checks pass. Record a
failed product acceptance honestly and improve the engine before adding model
comparison.

## Regression And Verification Strategy

Run focused tests after every phase, then:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
git diff --check
```

Add an explicit Playwright/Chromium smoke command that uses already-installed
browsers; the normal unit suite must not download a browser from the network.

Required regression coverage:

- durable chat jobs remain inspectable after completion;
- current edit, article, social, journal, and legacy merge drafts still behave
  as documented until deliberately migrated;
- typed design runs remain durable and immutable;
- production review approves exactly the reviewed candidate SHA;
- local experiments can never create a review or approval mutation;
- `/ada/` preview rewriting remains mount-safe;
- package data includes only the canonical runtime files;
- existing instance configs continue to load with the design engine disabled.

## Rollout Boundaries

- Do not add GPT, Gemini, or model comparison until the DeepSeek path produces a
  candidate that passes technical and product acceptance.
- Do not make a model selector part of the build contract yet. The first run is
  fixed by test configuration.
- Do not migrate the live production frontend as part of this work.
- Do not publish the DeepSeek candidate.
- After the local acceptance run, revise contracts and gates from recorded
  evidence before enabling production candidates.
- Production enablement requires a separate explicit decision and the existing
  owner approval flow.

## Completion Definition

This plan is implemented only when all of the following are true:

- owner intake reaches `DesignService` through durable asynchronous jobs;
- every build uses a frozen and hash-verified Ada context;
- `NativeOpenCodeBuilder` is the only implementation path for the test;
- OpenCode performs bounded multi-agent analysis and post-build critique while
  one primary session owns edits;
- the host runs blocking deterministic, browser, and visual gates before and
  after the immutable candidate commit;
- repair occurs in the same OpenCode session;
- Original and DeepSeek are reviewable one at a time in the existing Design tab;
- the scaffold compiler and parallel design-lab pipeline are retired;
- the DeepSeek run proves zero production mutation;
- a complete failed run remains inspectable, and only a complete passing run can
  become ready for review.
