# OpenCode-First Design Pipeline Implementation Plan

**Status:** Authoritative corrective implementation contract

**Creative-execution authority:**
`docs/brand-composition-and-behavior-system-implementation-plan.md` is
authoritative for experience planning, integrated implementation ownership,
motion/fidelity specialist behavior, and the evidence required to call a design
complete. This document remains authoritative for durable execution, candidate
retention, Git/provider isolation, host build ownership, and approval safety.

**Date:** 2026-08-31

**Acceptance implementation model:** `deepseek-ai/DeepSeek-V4-Flash`

**Acceptance visual-review model:** `Qwen/Qwen3.8-27B`

**Provider:** ENTRIM, `https://api.entrim.ai/v1`

**Supersedes:**

- `docs/canonical-opencode-design-test-implementation-plan.md`
- the same-session quality-repair loop in `hands/opencode_runner.py`
- the `ReactDesignSpec -> AstroReactCompiler -> frontend_scaffold` path as a
  canonical website-design workflow
- model-authored design manifests as an acceptance boundary
- destructive failure handling that removes an implemented candidate before it
  becomes inspectable

The superseded documents remain historical evidence. They are not implementation
authority after this plan is accepted.

## Executive Decision

Build one complete product workflow around OpenCode's native strength:

```text
prompt OpenCode -> OpenCode codes -> retain candidate -> host builds
-> host captures screenshots -> Qwen reviews -> OpenCode refines once
-> retain final candidate -> Design review -> explicit approval or decline
```

The orchestration boundary must be simple. The functionality exercised through
that boundary must be comprehensive.

OpenCode owns creative direction and implementation. The host owns durable job
state, immutable Git identity, credentials, build reproduction, evidence,
preview, policy, and approval.

There is no hidden recursive repair loop. A first implementation, technical
repair, or visual refinement is a separate durable candidate-producing
operation. Every substantive safe candidate remains inspectable, even when a
later stage fails.

## Why This Plan Exists

The real provider and coding agent work:

- ENTRIM lists `deepseek-ai/DeepSeek-V4-Flash`.
- Direct ENTRIM chat completion succeeds.
- OpenCode can use the ENTRIM model and edit a disposable repository.
- Full design runs produced real HTML, CSS, JavaScript, builds, and responsive
  screenshots.

The orchestration failed after or around the implementation:

- one run returned without editing;
- one spent the entire timeout inspecting and narrating a plan;
- later runs implemented the site but lost the candidate when validation failed;
- manifest prose was interpreted as nonexistent filesystem paths;
- model-authored manifest shapes became blockers;
- browser geometry checks reported overlap without proving the header was fixed;
- build, validation, visual critique, and repair responsibilities were duplicated
  across the runner and application service;
- the worktree cleanup path destroyed useful failed work;
- raw OpenCode event transcripts were not retained with the run.

This is an architecture correction, not a prompt-tuning exercise.

## Product Goal

A nontechnical owner supplies an editable business intake and asks for a site.
Ada produces a distinctive, fully implemented website candidate using real
OpenCode, refines it from real visual evidence, and presents it in the existing
Design review flow without changing production.

The canonical acceptance run must exercise:

- real ENTRIM authentication;
- real OpenCode tool use;
- repository inspection;
- autonomous art direction;
- HTML, CSS, and JavaScript implementation;
- approved frontend capabilities such as GSAP when appropriate;
- a real host-controlled build;
- desktop, tablet, mobile, and reduced-motion browser inspection;
- Qwen screenshot critique;
- one durable OpenCode visual-refinement operation;
- immutable candidate refs;
- mount-safe preview under `/ada/`;
- durable run and artifact inspection after completion;
- owner review, decline, and isolated approval behavior;
- proof that production and remote refs remain unchanged.

## Non-Negotiable Invariants

- A site mutation is either an explicit owner action or a pending draft.
- Production changes only through explicit approval.
- A pending visual build is reviewed in the Design tab.
- Preview URLs and nested assets work under `/ada/`.
- Chat jobs and design runs remain inspectable by ID after completion.
- Every run is pinned to an exact base commit SHA.
- Local experiments use a dedicated clone, database, cache, artifact directory,
  transcript directory, and screenshot directory.
- Local experiments use `push_mode: none` and `publishable: false`.
- Test children receive only the selected model credential.
- GitHub, Cloudflare, R2, admin, CrawlSEO, and publishing credentials do not
  enter the experiment child environment.
- No experiment pushes, publishes, merges, or mutates a production adapter.
- OpenCode edits only a disposable worktree.
- The host validates changed paths before retaining a candidate ref.
- A substantive allowed diff is retained before build or visual validation.
- A failed build or quality report never erases an already retained candidate.
- Missing evidence is `incomplete`, not `passed`.
- Site-specific assumptions stay in instance configuration.
- Raw model output is untrusted and never decides whether production changes.

## Explicit Non-Goals

- Do not create another frontend compiler.
- Do not make a JSON design specification the source of website markup.
- Do not require React, Astro, or a component framework for the canonical test.
- Do not ask the model to author acceptance-critical Git or quality identities.
- Do not make an LLM score automatically approve a design.
- Do not compare many models before one complete workflow works.
- Do not publish OceanicVibes during the acceptance run.
- Do not preserve a parallel design-lab architecture merely because it exists.

## Target Architecture

```text
authenticated owner request or local acceptance command
  -> ChatJob / DesignRun persisted
  -> DesignService prepares facts-only creative brief
  -> DesignJobExecutor claims run
  -> NativeOpenCodeBuilder
       -> exact-SHA disposable worktree
       -> project-scoped OpenCode config and design skills
       -> one real OpenCode implementation session
       -> allowed-path and secret checks
       -> host-generated manifest
       -> local immutable candidate commit/ref
       -> raw transcript and receipt persisted
  -> DesignService transitions to validating
  -> host build from immutable candidate SHA
  -> host deterministic quality report
  -> Chromium screenshots and browser evidence
  -> Qwen visual critique over retained screenshots
  -> one optional durable refinement child run
       -> new exact base SHA = prior candidate SHA
       -> new candidate commit/ref
       -> new build, evidence, and critique
  -> final candidate ready for Design review
  -> explicit approve or decline
```

## Responsibility Boundaries

### `application/designs.py`

Owns the lifecycle:

- create and queue a run;
- capture immutable request identity;
- invoke the builder;
- persist candidate identity before validation;
- invoke host build and quality services;
- create a visual-refinement child run;
- expose candidates for review;
- create the existing approval-gated draft.

It does not invoke route functions, inspect screenshots itself, or execute Git
commands directly.

### `application/design_jobs.py`

Owns durable execution only:

- claim one run;
- rehydrate typed request and target;
- execute one lifecycle stage at a time;
- persist stage-specific failure diagnostics;
- recover queued work after restart.

It does not contain design policy or validation logic.

### `hands/opencode_runner.py`

Owns the OpenCode adapter and repository mutation:

- create an exact-SHA worktree;
- install project-scoped instructions, skills, and provider config;
- invoke OpenCode once per durable operation;
- stream progress while retaining raw JSONL events;
- detect and validate changed paths;
- generate host-owned candidate metadata;
- commit safe changes to a local namespaced ref;
- return a build-only candidate receipt;
- clean up only after the candidate or failure artifact is durable.

It does not run browser quality, visual critique, or hidden repair continuations.

### `hands/site_build.py`

Owns authoritative build reproduction from an immutable candidate SHA. OpenCode
may run local checks for its own feedback, but only the host build is persisted
as acceptance evidence.

### `hands/design_quality.py`

Owns deterministic post-candidate checks. It consumes an immutable candidate and
build output. It never asks OpenCode to repair anything.

### `hands/playwright_quality.py`

Owns browser inspection and screenshots. It returns evidence with route,
viewport, selector, and measured geometry for each finding.

### `core/vision.py` or a dedicated visual-review adapter

Owns the Qwen multimodal call. It receives candidate screenshots and the frozen
creative brief, returns a typed critique, and cannot mutate the repository.

### `web/preview.py` and the Design tab

Own preview rendering and review. Failed, incomplete, original, first-pass, and
refined candidates remain inspectable when their artifacts exist.

## Lifecycle Model

Add explicit candidate-preserving states:

```text
created
-> assessing_intake
-> planning
-> building
-> candidate_ready
-> validating
-> ready_for_review | needs_repair | incomplete | failed
```

Rules:

- `candidate_ready` requires a candidate SHA and local ref.
- `needs_repair` may have a valid preview and blocking findings.
- `incomplete` means infrastructure or evidence was unavailable.
- `failed` without a candidate means the implementation never produced a safe
  retainable diff.
- `failed` with a candidate is permitted only for an unrecoverable post-candidate
  system error; the candidate remains inspectable.
- `repairing` is retired as an in-place looping state.
- A technical repair or visual refinement creates a child run with
  `parent_run_id`, `operation_kind`, and the parent candidate SHA as its base.
- Parent and child candidates are immutable and independently inspectable.

Add operation kinds:

```text
initial_build
technical_repair
visual_refinement
derived_page
```

## Typed Contract Changes

### `DesignCandidateReceipt`

Make it a build-only receipt. Required fields:

- run ID;
- operation kind;
- base SHA;
- candidate SHA;
- candidate ref;
- changed paths;
- diff summary;
- OpenCode session ID;
- transcript artifact ID or relative path;
- host-generated manifest path and hash;
- provider and model identifiers;
- publishable flag.

Remove quality-report and visual-critique ownership from this receipt. Those
identities are created later against the immutable candidate.

### Host-generated manifest

Generate the manifest after allowed-path validation and before the candidate
commit. The host already knows:

- source homepage path;
- changed files;
- base SHA;
- intake hash;
- run ID;
- operation kind;
- candidate ref namespace;
- required routes;
- approved capabilities.

The model may return a short design rationale, token notes, or signature-gesture
description as optional untrusted metadata. No model-authored nested string is
interpreted as a file path.

### Run relationships

Persist:

- `parent_run_id`;
- `operation_kind`;
- `source_candidate_sha`;
- `transcript_artifact_id` or safe relative transcript path;
- `build_artifact_id`;
- `screenshot_artifact_id`;
- `visual_critique_hash`.

Use a migration in `core/memory.py`. Do not access `Memory.conn` outside Memory.

## Creative Design Contract

Do not skip design. Remove only the competing host-authored visual scaffold.

The initial OpenCode prompt contains:

- the owner's design request;
- validated business facts;
- audience and conversion goal;
- brand voice and visual preferences;
- explicit visual dislikes;
- supplied media paths and safe metadata;
- prohibited and unverified claims;
- required pages and stable URLs;
- approved frontend capabilities;
- build and mutation constraints;
- a clear high-end, subject-specific quality bar.

The prompt must say, in concise form:

```text
Act as the creative director and senior frontend engineer. Establish a
subject-specific art direction and implement it completely. Avoid interchangeable
landing-page patterns, generic centered heroes, repetitive card grids, and stock
industry aesthetics. Begin implementation after a bounded repository inspection.
Use your normal tools, run relevant checks, and leave changes uncommitted. Do not
stop at a plan.
```

Do not require the model to narrate multiple directions before editing. Design
reasoning may happen inside the coding session. Judge the implemented result from
the actual candidate and screenshots.

Install the existing design skills as project-scoped OpenCode skills:

- `design-core`;
- `frontend-design`;
- `high-end-visual-design`;
- `motion-design`;
- `web-design-guidelines`.

For an independent initial design, existing source is available for build and
runtime constraints but is not supplied as creative direction. Supplied business
assets remain available because the intake explicitly authorized them.

## OpenCode Invocation Contract

One durable operation gets one primary OpenCode session.

The adapter must:

1. Write `opencode.json` with the configured provider, endpoint, model, output
   limit, and environment interpolation.
2. Write project instructions and skills without changing tracked site files.
3. Invoke `opencode run --agent build --format json`.
4. Stream owner-safe progress.
5. Write the complete JSON event stream to the run artifact directory.
6. Record the session ID and process exit status.
7. Inspect the resulting Git diff regardless of whether the final prose reply is
   empty or the process exits after editing.
8. Reject forbidden paths and credentials.
9. Retain a substantive safe candidate before any build or browser gate.
10. Return a typed receipt.

There is no automatic “implement now” continuation and no validation-repair loop
inside the adapter. A no-diff run fails with its transcript intact. A partial safe
diff produced before a provider error may be retained as an incomplete candidate
with the provider failure recorded.

## Host Build Contract

After candidate retention:

1. Create a fresh temporary worktree at the candidate SHA.
2. Select the configured site build profile.
3. Run the build with the host-controlled dependency environment and cache.
4. Persist stdout, stderr, command, duration, exit status, and output route list.
5. Copy public output into the run's immutable artifact directory.
6. Remove the temporary build worktree only after logs and output are durable.

OpenCode is not asked to install missing host dependencies. An unavailable host
toolchain is an infrastructure failure, not a website repair request.

## Deterministic Quality Policy

Blocking gates for candidate approval:

- forbidden or unexpected changed path;
- secret or credential material;
- failed authoritative build;
- missing required output page;
- broken local asset;
- source/configuration leak into public output;
- missing title, viewport, language, or primary heading;
- severe accessibility failure;
- unreduced essential motion that hides content;
- content unavailable without JavaScript or failed animation initialization;
- invented pricing, certifications, testimonials, availability, schedules, or
  quantified outcomes when the intake marks them unknown.

Advisory findings by default:

- subjective visual hierarchy concerns;
- generic-template signals;
- low-resolution imagery where a valid image still renders;
- minor contrast uncertainty over photography;
- heuristic crop concerns;
- design-preference disagreements.

Browser checks must:

- wait for fonts and a bounded layout-settle period;
- inspect both normal and reduced-motion modes;
- confirm a header is actually `fixed` or `sticky` before testing overlap;
- report the route, selector, header position, header rectangle, target selector,
  and target rectangle;
- distinguish a hidden animation target from content intentionally below the fold;
- never infer a candidate defect from a bare boolean without evidence.

Baseline defects are recorded separately and do not become candidate defects.

## Visual Critique And Refinement

The quality workflow deliberately has two creative passes, not an unbounded loop.

### Pass 1: DeepSeek implementation

OpenCode and `deepseek-ai/DeepSeek-V4-Flash` create candidate v1.

### Evidence: host screenshots

Chromium captures every required route at desktop, tablet, mobile, and reduced
motion. Screenshots are immutable run artifacts.

### Critique: Qwen Vision

`Qwen/Qwen3.8-27B` reviews screenshots against the frozen creative brief. The
typed report covers:

- subject-specific art direction;
- hierarchy and composition;
- typography;
- image treatment;
- rhythm and density;
- generic-template signals;
- desktop-to-mobile translation;
- conversion-path integration;
- visible motion or hidden-content problems;
- strengths worth preserving;
- a concise prioritized refinement brief.

Qwen cannot approve, reject, or mutate the candidate.

### Pass 2: one durable visual refinement

When the critique contains actionable high-value changes, create a
`visual_refinement` child run based on candidate v1. Give OpenCode:

- the original creative brief;
- candidate v1 as the repository base;
- Qwen's typed findings;
- screenshot artifact paths or safe visual descriptions;
- explicit strengths to preserve.

Candidate v2 is independently committed, built, captured, and validated.
Candidate v1 remains available. There is no third automatic pass.

## Review Experience

The Design tab must show:

- Original;
- Initial candidate;
- Refined candidate when present;
- run status;
- model and provider;
- build status;
- blocking and advisory findings;
- screenshot evidence;
- candidate SHA;
- parent/child relationship;
- approve and decline controls only where policy permits them.

`needs_repair` and `incomplete` candidates remain previewable but cannot be
approved. The owner may explicitly start a technical repair run or decline.

Do not add raw public preview URLs as a substitute for the Design flow.

## Implementation Phases

### Phase 0: Freeze And Establish A Baseline

Tasks:

- stop paid canonical model runs until Phase 5;
- retain existing ENTRIM run databases and screenshots under `/tmp/opencode` as
  temporary debugging evidence;
- record the current focused-test result and current full-suite result;
- identify experimental edits made during the failed repair-loop work;
- preserve ENTRIM provider support;
- do not preserve same-session no-op nudges or manifest workarounds merely
  because they were added during diagnosis.

Acceptance:

- no production or remote mutation;
- current behavior is reproducible with a focused test;
- intended retained and replaced changes are listed in the implementation PR.

### Phase 1: Candidate-Preserving Contracts And State

Start with failing tests in:

- `tests/test_design_contracts.py`;
- `tests/test_design_memory.py`;
- `tests/test_design_service.py`;
- `tests/test_design_jobs.py`.

Implement:

- new lifecycle states;
- operation kinds;
- parent/child run identity;
- build-only `DesignCandidateReceipt`;
- transcript/build/screenshot artifact references;
- Memory migration and transition rules.

Acceptance:

- candidate identity can exist before quality identity;
- `needs_repair` retains candidate SHA/ref;
- child refinement starts from the exact parent candidate SHA;
- restart recovery does not discard candidate-bearing runs.

### Phase 2: Extract The OpenCode Candidate Adapter

Start with failing tests in:

- `tests/test_builder.py`;
- `tests/test_design_builder.py`;
- a new `tests/test_opencode_candidate.py` if separation improves clarity.

Refactor `hands/opencode_runner.py` so the typed path performs only:

- worktree setup;
- OpenCode setup and one invocation;
- transcript retention;
- diff/path/secret validation;
- host manifest generation;
- local candidate commit/ref;
- receipt creation;
- cleanup after durability.

Keep the legacy `stage_build()` path behavior-preserving until typed design
acceptance passes. Do not rewrite unrelated chat builds in this phase.

Acceptance:

- a fake OpenCode process that edits files yields a retained candidate;
- an OpenCode process that edits and exits nonzero yields an inspectable partial
  candidate when the diff is safe;
- a no-diff process yields a failed run with transcript;
- forbidden changes yield no candidate ref;
- no quality or visual call occurs in the adapter;
- no Git push command is reachable in local experiment mode.

### Phase 3: Host Build And Artifact Service

Start with failing tests in:

- `tests/test_site_build.py`;
- `tests/test_design_service.py`;
- `tests/test_preview.py`.

Implement immutable post-candidate builds and artifact persistence.

Acceptance:

- build runs from candidate SHA, not the mutable clone worktree;
- build failure retains candidate and logs;
- successful output is previewable under `/ada/`;
- every required route is listed from built output;
- no generated cache, database, or screenshot enters Git.

### Phase 4: Correct Post-Candidate Quality

Start with failing tests in:

- `tests/test_design_quality.py`;
- `tests/test_design_lab.py` only where it tests reusable browser behavior;
- new focused Playwright quality tests.

Implement:

- host-generated manifest checks;
- evidence-rich browser findings;
- layout settling;
- fixed/sticky header verification;
- content-grounding checks against intake unknowns;
- candidate/baseline finding separation;
- `needs_repair` and `incomplete` transitions.

Acceptance:

- descriptive metadata is never interpreted as a path;
- a static header cannot trigger fixed-header overlap;
- an animation failure that leaves important content hidden blocks approval;
- invented schedule/pricing/certification claims block approval;
- a failed gate cannot remove the candidate or preview.

### Phase 5: Real ENTRIM Initial Build

Run the first paid acceptance operation only after Phases 1-4 pass locally.

Use:

```text
provider: entrim
base_url: https://api.entrim.ai/v1
model: deepseek-ai/DeepSeek-V4-Flash
credential env: SITE_AGENT_VISION_API_KEY
```

Acceptance:

- real OpenCode creates a substantive candidate;
- candidate ref exists locally before validation;
- raw OpenCode transcript is retained;
- authoritative host build completes or yields an inspectable build failure;
- remote refs remain byte-for-byte unchanged;
- production paths and live data sentinels remain unchanged.

### Phase 6: Qwen Visual Critique And One Refinement

Start with adapter tests using retained fixture screenshots, then run one real
ENTRIM visual critique.

Acceptance:

- Qwen receives the frozen brief and bounded screenshot set;
- critique validates against a typed contract;
- Qwen cannot mutate Git or change run state directly;
- one refinement child run produces candidate v2;
- v1 and v2 remain independently previewable;
- no third automatic refinement is scheduled.

### Phase 7: Design Review And Durability

Start with failing tests in:

- `tests/test_design_web.py`;
- `tests/test_preview.py`;
- `tests/test_web.py` where approval compatibility is involved.

Acceptance:

- Original, v1, and v2 are visible in the Design tab;
- failed and incomplete candidates retain diagnostics;
- service restart preserves runs, refs, reports, and artifact access;
- decline changes no production state;
- approval binds to the reviewed candidate SHA and quality hash;
- local experiments cannot be approved into production.

### Phase 8: Remove The Parallel Pipeline

After the canonical acceptance run passes, remove or clearly archive:

- `application/design_lab.py`;
- `application/model_comparison.py`;
- `brain/react_design.py`;
- `core/react_design_contracts.py`;
- `hands/astro_react_compiler.py`;
- `frontend_scaffold/`;
- `web/design_lab.py`;
- model-comparison and scaffold-specific scripts;
- tests whose only purpose is the retired compiler pipeline.

Update documentation and CLI help so there is one supported design workflow.

Acceptance:

- no production code imports the retired pipeline;
- no CLI command presents it as canonical;
- full tests and package build pass after deletion;
- the OpenCode-first acceptance command remains operational.

## Test Matrix

### Unit and contract tests

- provider/model qualification for ENTRIM;
- secret mapping without secret persistence;
- run transitions and child relationships;
- build-only receipt validation;
- host manifest determinism;
- allowlist and hard-deny behavior;
- transcript artifact identity;
- candidate retention on later failure.

### Adapter integration tests

- fake OpenCode JSONL stream with file edits;
- fake OpenCode provider failure after edits;
- fake OpenCode no-diff completion;
- host build success and failure;
- browser evidence for static, sticky, and fixed headers;
- visual-review response validation.

### Full local product test

- durable design run creation;
- real OpenCode invocation;
- candidate commit/ref;
- host build;
- preview output;
- screenshots;
- Qwen critique;
- DeepSeek refinement child run;
- Design tab inspection;
- restart durability;
- decline;
- isolated explicit approval against a disposable repository;
- proof of no production or remote mutation.

### Required verification commands

```bash
.venv/bin/pytest -q <focused tests>
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
git diff --check
```

## Canonical Acceptance Evidence

The final run report must include:

- chat job ID when invoked through chat;
- initial run ID and refinement run ID;
- base SHA;
- candidate v1 and v2 SHAs and refs;
- provider and model IDs;
- OpenCode session IDs;
- transcript hashes;
- changed paths;
- host manifest hashes;
- build commands, statuses, and log hashes;
- route inventories;
- desktop, tablet, mobile, and reduced-motion screenshot hashes;
- deterministic quality reports;
- Qwen critique and hash;
- preview page list;
- live path sentinel comparison;
- before/after remote-ref comparison;
- explicit statement that production approval did not occur.

## Definition Of Done

The corrective work is complete only when all of the following are true:

1. One editable intake and owner request can produce a real website through
   ENTRIM and OpenCode.
2. OpenCode owns art direction and implementation without a host-generated
   visual scaffold.
3. Candidate v1 is retained before build and quality validation.
4. Failed build or quality checks leave v1 inspectable.
5. Host build and browser evidence are reproducible from the candidate SHA.
6. Qwen critiques real screenshots.
7. One durable DeepSeek refinement produces candidate v2 when warranted.
8. No hidden repair loop or recursive continuation exists.
9. Original, v1, and v2 can be reviewed under `/ada/`.
10. Approval is explicit and binds to an immutable candidate.
11. Local acceptance changes no production data or remote ref.
12. The parallel compiler/design-lab path is no longer canonical.
13. Focused tests, full tests, compileall, wheel build, and diff checks pass.

## Current Experimental Change Disposition

Keep or finish properly:

- ENTRIM OpenAI-compatible provider support;
- `deepseek-ai/DeepSeek-V4-Flash` design-engine configuration;
- provider endpoint and credential-name capture without secret persistence;
- focused provider tests.

Replace through this plan:

- the same-session no-op implementation nudge;
- in-builder host quality and visual critique;
- in-builder automatic validation repair;
- model-authored source-file manifest requirements;
- candidate-destructive worktree cleanup;
- bare-boolean fixed-header overlap detection.

Do not treat current focused tests as final verification. The full suite and
package smoke test must be rerun after the architecture correction.

## Implementation Order

Implement exactly in this order:

```text
candidate-preserving contracts
-> OpenCode candidate adapter
-> immutable host build
-> post-candidate quality
-> real DeepSeek build
-> Qwen visual critique
-> one durable refinement
-> Design review durability
-> parallel-pipeline cleanup
```

Do not run another paid full design attempt before candidate retention and
post-candidate validation are separated.
