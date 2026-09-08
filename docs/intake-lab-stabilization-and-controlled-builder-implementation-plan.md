# Intake Lab Stabilization and Controlled Builder Implementation Plan

**Status:** Authoritative implementation contract

**Date:** 2026-09-06

**Audience:** Coding AI implementing and verifying the work in this repository

## Authority

This plan governs the stabilization of the neutral Intake Ada incubation design
workflow and the integration of the controlled Astro/React builder for initial
homepage candidates.

Where the following documents conflict with this plan, this plan takes
precedence for the affected behavior:

- `docs/intake-lab-test-ui-implementation-plan.md`: its Native OpenCode-only
  generation decision, its Qwen/Entrim reference pairing, and its Astro/React
  non-goal are superseded.
- `docs/react-design-creation-system-implementation-plan.md`: its reusable typed
  planner, compiler, build-profile, and local-Git implementation is restored for
  initial incubation homepage builds only. Its old standalone command and
  customer-specific assumptions remain superseded.
- `docs/opencode-first-design-pipeline-implementation-plan.md`: Native OpenCode
  remains the implementation path for explicit owner-requested visual
  refinements, but not for the first controlled homepage build.

The isolation, explicit approval, and provisioning rules in
`docs/ada-incubation-research-and-provisioning-implementation-plan.md` and
`AGENTS.md` remain authoritative everywhere.

## Instructions to the Coding AI

Implement this plan in the listed order. Start each phase with a focused failing
test or a reproducible API request. Prefer small extractions and existing typed
boundaries over rewrites.

Do not infer completion from the existence of partial classes or tests. Verify
the runtime wiring and an actual retained candidate flow. Do not revert or
overwrite unrelated work in the dirty worktree.

The required verification sequence is:

1. Run the focused tests for the phase.
2. Run the full test suite.
3. Run Python bytecode compilation.
4. Build the wheel.
5. Restart the Intake Lab service safely if runtime files changed.
6. Exercise a fresh image-led incubation build and inspect the retained result.

## Executive Decision

Initial confirmed homepage builds use a controlled generation path:

```text
confirmed SiteIntake revision
  + frozen website asset selection
  + incubated creative context
  -> LLMDesignPlanner using DeepSeek Vision through OpenRouter
  -> validated ReactDesignSpec
  -> deterministic AstroReactCompiler
  -> pinned Astro/React source tree
  -> immutable local candidate commit
  -> Astro check and static dist build
  -> deterministic and browser quality gates
  -> optional read-only DeepSeek visual critique
  -> owner review in the Design tab
```

The model chooses a bounded design specification. The host owns source
generation, dependencies, filesystem policy, build commands, immutable Git
identity, quality gates, and preview serving.

Explicit owner-requested visual refinements continue through
`NativeOpenCodeBuilder` against an immutable parent candidate. No refinement is
started automatically.

## Correct Provider Contract

There is no required Entrim dependency in the target system. Vision work uses
DeepSeek Vision through OpenRouter.

The intended Intake Ada routing is:

| Capability | Provider | Model | Credential |
|---|---|---|---|
| Main reasoning | OpenRouter | `deepseek/deepseek-v4-flash-0731` | `OPENROUTER_API_KEY` |
| Initial design planning | OpenRouter | `deepseek/deepseek-v4-flash-vision-exp` | `OPENROUTER_API_KEY` |
| Native refinement builder | OpenRouter/OpenCode | `openrouter/deepseek/deepseek-v4-flash-vision-exp` | `OPENROUTER_API_KEY` |
| Media analysis | OpenRouter | `deepseek/deepseek-v4-flash-vision-exp` | `OPENROUTER_API_KEY` |
| Read-only visual review | OpenRouter | `deepseek/deepseek-v4-flash-vision-exp` | `OPENROUTER_API_KEY` |
| Intake advisor | OpenRouter | instance-configured vision-capable model | `OPENROUTER_API_KEY` |

Model names remain instance configuration, not generic service constants. Tests
may use fake model names and fake endpoints.

Remove stale Entrim and Qwen assumptions from the Intake Ada configuration,
configuration assertions, provider metadata, comments, and docstrings touched by
this work. Do not add fallback routing to Entrim.

## Product Outcomes

The completed workflow must provide all of the following:

- one durable result for one idempotent build request;
- a deliberately new immutable candidate when the owner selects New version;
- a fast controlled initial homepage build from the confirmed revision;
- only confirmed, ready, website-designated imagery in the build;
- retained source SHA, candidate SHA, manifests, reports, screenshots, and
  provider identity;
- graph-aware progress for initial, repair, and explicit refinement runs;
- stable owner-selected revision and run views while polling;
- preview URLs that work below the deployment mount point `/ada/`;
- deterministic approval gates before an owner can approve a candidate;
- explicit owner control over every refinement and production mutation;
- irreversible workspace purge with a minimal non-reopenable audit tombstone.

Target performance for the controlled initial build:

- p50 below 90 seconds;
- p95 below 3 minutes;
- under 5 minutes is acceptable during rollout;
- UI state should reflect persisted state within 3 seconds.

Measure these values from run events. Do not weaken quality gates merely to meet
the latency target.

## Non-Negotiable Invariants

- A site mutation is either an explicit owner action or a pending draft.
- Production changes only through an explicit approval operation.
- Initial and refinement candidates are local, non-publishable, and never
  pushed.
- A candidate must be retained by exact SHA before later quality failures can
  make the operation terminal.
- Every retained candidate SHA and local candidate ref remains previewable until
  the incubation is purged.
- Pending visual work is reviewed in the Design tab. Do not expose raw preview
  links as a substitute.
- Chat and design jobs remain durable and inspectable after they leave active
  job listings.
- Preview HTML, CSS, scripts, images, fonts, and fetches remain under the same
  `/ada` mount prefix.
- Run IDs accepted by HTTP are syntax-validated, then authorized through the
  incubation-scoped application service.
- Generic code must not contain customer-specific paths, facts, pages, or
  identifiers.
- Customer incubation databases, workspaces, assets, and conversations remain
  isolated from every other incubation and from Intake Ada's permanent memory.
- Only confirmed owner facts and provenance-linked accepted context may become
  site claims.
- Invalid `conversion.primary_action` values are discarded rather than guessed.
- Research uses a confirmed location only. A missing location requires either a
  confirmed location or `business.location_not_applicable=true`.
- Plugins and MCP providers call application services and typed contracts, not
  route functions or `Memory.conn`.
- No child process receives GitHub, Cloudflare, R2, CrawlSEO, Cicero, admin,
  publishing, or unrelated model credentials.
- No automatic refinement loop is permitted.
- Purged incubations cannot be reopened or recreated from their old identity.

## Explicit Non-Goals

- Do not add deployment, push, merge, pull-request, or publication behavior.
- Do not turn the controlled compiler into a general code generator.
- Do not permit model-authored dependencies, shell commands, configuration
  files, CI files, or arbitrary source paths.
- Do not replace the no-build Intake Lab admin UI with a frontend framework.
- Do not make visual critique equivalent to approval.
- Do not make semantic image analysis a prerequisite for using normalized image
  bytes in a design.
- Do not add a universal plugin system or dynamic Python module loading.
- Do not preserve purged customer content in the central Intake Ada registry.
- Do not broaden filesystem permissions for Pelican or neutral-scaffold builds
  while adding Astro/React support.
- Do not add backward-compatibility branches unless persisted state or an
  external caller concretely requires them.

## Current Baseline and Known Defects

The repository already contains substantial reusable implementation:

- typed design contracts and durable design runs;
- `DesignBuilder.build_design(PageBuildRequest, BuildTarget)`;
- `LLMDesignPlanner` and `ReactDesignSpec` validation;
- `AstroReactCompiler` and a pinned frontend scaffold;
- `ASTRO_REACT_PROFILE` and local npm build support;
- detached worktrees, local candidate commits, and local refs;
- deterministic, browser, accessibility, and visual-review gates;
- incubation-scoped stores and runtime composition;
- local media normalization and safe materialization;
- immutable preview caching and mount-aware URL rewriting;
- explicit visual-review and refinement APIs.

The following defects must be fixed:

1. `src/site_agent/intake-ada.yaml` still routes standalone media analysis and
   visual review through Entrim/Qwen even though design generation uses
   DeepSeek Vision through OpenRouter.
2. `MediaStatus` combines derivative readiness and optional semantic analysis.
   An analyzer error can mark usable normalized imagery as failed.
3. `MediaWorker` persists `provider_id="qwen"` regardless of the configured
   provider.
4. Initial build idempotency is non-atomic. A run is created and queued before
   `design_intake_operations` records the request.
5. Intake HTTP validation accepts only root IDs matching
   `intake-lab-[0-9a-f]{32}`. Persisted `design-*` child runs therefore return
   404 through otherwise scoped endpoints.
6. `IncubationApplicationService._refresh_lifecycle()` watches only the single
   session `design_run_id` and ignores active or reviewable descendants.
7. UI polling may replace an explicit owner-selected revision with
   `preferred_run_id` and hides bounded child-fetch failures.
8. `DesignJobExecutor` automatically starts a full visual refinement after
   validation or recovery, adding avoidable latency and violating explicit
   owner control.
9. Intake Lab startup forcibly enables `quality.visual_critic` instead of
   respecting the validated instance configuration.
10. `IncubationApplicationService.purge()` deletes only the workspace and leaves
    a central registry record that can recreate or reopen the old identity.
11. Runtime composition always selects `NativeOpenCodeBuilder`, so the existing
    controlled Astro/React path is not used for initial homepage builds.
12. `PreviewBuildCache` assumes `build.sh` and `output/`; it cannot build and
    serve the controlled `dist/` artifact.

## Terminology and Run Graph

Use the following terms consistently:

- **Confirmed revision:** the immutable `design_intake_revisions` row accepted
  by the owner and identified by both revision number and row ID.
- **Initial build:** operation kind `initial_build`; a root candidate generated
  by the controlled Astro/React builder.
- **Explicit refinement:** operation kind `visual_refinement`; a child candidate
  generated by Native OpenCode only after an owner action.
- **Technical repair:** a child operation that repairs a deterministic build or
  validation defect without silently changing the confirmed brief.
- **Run graph:** all design runs for one intake session and confirmed revision,
  linked by `parent_run_id`.
- **Preferred run:** the host recommendation used only for initial UI selection.
- **Selected run:** the owner's current UI choice; polling must preserve it while
  it still exists.
- **Preview run:** the retained run whose immutable candidate can currently be
  rendered.
- **Build profile:** the host-selected source/build/output contract persisted in
  the run execution profile.
- **Purge tombstone:** minimal central metadata proving that an incubation ID was
  purged and must never be reopened.

## Target Application Boundaries

Keep the supported extension direction:

```text
HTTP adapter
  -> IncubationApplicationService / IntakeLabService / DesignIntakeService
  -> typed design and media contracts
  -> controlled planner/compiler or Native OpenCode adapter
```

Do not call route functions from services and do not access `Memory.conn`
outside persistence code.

The builder boundary remains:

```python
class DesignBuilder(Protocol):
    def build_design(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        progress: Callable[[str], None] | None = None,
    ) -> DesignCandidateReceipt: ...
```

Add one routing implementation behind this boundary:

- `initial_build` selects `AstroReactDesignBuilder`;
- `visual_refinement` selects `NativeOpenCodeBuilder`;
- existing operation-specific behavior for technical repair and derived pages
  remains explicit and covered by tests;
- unsupported operation kinds fail closed with a bounded diagnostic.

## Phase 0: Freeze Reproductions and Protect Existing Work

Before behavior changes:

1. Record `git status --short`; do not clean the worktree.
2. Add focused failing tests for every defect listed below before its fix.
3. Use temporary directories and fake providers in tests. Never use real
   credentials or network calls in the test suite.
4. Capture a read-only API reproduction for child-run access and revision
   selection where practical.
5. Confirm the existing focused suites still pass except for the deliberately
   introduced failing assertions.

Required first failures:

- a scoped persisted child run can be fetched, reviewed, and previewed;
- polling preserves an explicit selected run;
- lifecycle observes an active or reviewable descendant;
- analyzer failure leaves derivatives usable;
- concurrent identical build calls produce one run;
- a purged incubation cannot be reopened;
- initial build dispatches to the controlled builder;
- an Astro candidate previews from `dist/`;
- deterministic success does not queue an automatic refinement.

## Phase 1: Correct Vision Provider Routing

Update `src/site_agent/intake-ada.yaml` so both the standalone media analyzer and
read-only visual review use OpenRouter and the configured DeepSeek vision model.

Required configuration behavior:

- `vision.enabled` remains true;
- `vision.base_url` is `https://openrouter.ai/api/v1`;
- `vision.model` is `deepseek/deepseek-v4-flash-vision-exp`;
- `vision.api_key_env`, if present, is `OPENROUTER_API_KEY`;
- `design_engine.visual_review` explicitly resolves to OpenRouter, DeepSeek
  Vision, and `OPENROUTER_API_KEY`, or inherits exactly those values without an
  ambiguous Entrim fallback;
- `env.vision_api_key` and `env.visual_review_api_key` resolve to
  `OPENROUTER_API_KEY`;
- the child environment still includes only allowlisted credentials.

Make provider metadata truthful:

- expose a provider identity from `VisionClient`, preferably from explicit
  configuration rather than URL inference;
- persist that identity in `MediaWorker` instead of the hardcoded `qwen` value;
- keep the exact configured model in `MediaAsset.model`;
- rename Qwen/Entrim-specific comments and docstrings in generic code;
- retain provider-neutral response parsing and strict `MediaAnalysis`
  validation.

Do not create an Entrim fallback. A provider failure is a normal bounded
analysis failure and must not invalidate normalized derivatives.

Tests:

- update `tests/test_intake_ada_config.py` to assert OpenRouter routing;
- add or update `tests/test_vision.py` for configured provider/model/credential;
- update `tests/test_media_service.py` to assert dynamic provider metadata;
- keep `tests/test_design_visual_review.py` endpoint- and model-neutral;
- verify `build_intake_lab_environment()` exposes `OPENROUTER_API_KEY` and does
  not leak unrelated secrets.

## Phase 2: Separate Media Derivatives From Semantic Analysis

Use the next `Memory` schema version. The current version at the time of this
plan is 33, so this work should use migration 34. If another migration lands
first, use the next version and preserve the same semantics.

Keep `MediaStatus` as the derivative lifecycle:

- `queued`: original awaits normalization;
- `processing`: normalization is active;
- `ready`: normalized bytes and required previews are durable and usable;
- `failed`: normalization or storage failed, so the asset cannot be used.

Add an independent analysis lifecycle, using a typed enum such as
`MediaAnalysisStatus`:

- `pending`;
- `processing`;
- `ready`;
- `failed`;
- `skipped` when no analyzer is configured.

Add persistence fields sufficient to represent that lifecycle, including:

- analysis status;
- analysis attempts;
- bounded analysis error;
- analysis update timestamp;
- configured provider and model identity.

Keep normalization attempts/errors separate from analysis attempts/errors.
Extend `MediaAsset` and its serializer with documented fields. UI status should
show derivative usability separately from analysis progress.

Migration behavior for existing rows:

- rows with valid normalized and thumbnail keys become derivative `ready`;
- rows with stored analysis JSON become analysis `ready`;
- rows previously marked `failed` only because analysis failed become
  derivative `ready` and analysis `failed`, preserving a bounded diagnostic;
- rows missing required derivatives remain derivative `failed` or `queued` as
  justified by their persisted state;
- do not regenerate existing derivatives during migration;
- do not invent successful analysis for rows lacking a valid analysis object.

Refactor persistence and worker behavior:

1. Claim normalization work independently.
2. Normalize and persist the original-derived assets.
3. Mark derivative status `ready` before any provider request.
4. Claim analysis work independently for derivative-ready assets.
5. Send bounded WebP/data-URL evidence to `VisionClient`.
6. Persist valid analysis and optional knowledge proposals.
7. On provider or schema failure, mark only analysis `failed`.
8. Retry only retryable provider failures within the existing bounded policy.
9. Permit an explicit analysis retry that reuses normalized derivatives.

Build eligibility depends on derivative readiness, archival state, media kind,
and confirmed website usage. It does not depend on semantic-analysis success.

Tests:

- migration from pre-34 ready, failed-with-derivatives, and truly failed rows;
- normalization succeeds while analysis fails;
- analysis retry does not read or regenerate the original;
- no analyzer produces derivative ready plus analysis skipped;
- provider metadata reports OpenRouter and the configured DeepSeek model;
- serialized UI state exposes both lifecycles without leaking provider output.

## Phase 3: Freeze and Validate Confirmed Website Assets

At confirmation and build time, use only intake asset bindings with
`usage="website"`.

The confirmed revision must freeze the binding identity. Before queueing a
build, resolve every selected binding through the incubation's `MediaService`
and reject the request if an asset is:

- missing;
- archived;
- not an image for the initial homepage image path;
- derivative-incomplete;
- outside the current incubation;
- not present in the confirmed revision;
- duplicated under conflicting roles.

Return a bounded owner-facing error naming the affected asset ID and corrective
action. Do not silently omit an explicitly selected website asset.

Pass only the frozen approved asset set into `PageBuildRequest` and the
controlled planner. Materialize normalized files under a target-specific safe
directory. Preserve content hashes and map model-facing asset IDs to local files
without exposing arbitrary paths.

Tests:

- non-website assets never reach the planner or builder;
- ready website images are included exactly once;
- missing, archived, cross-incubation, or derivative-failed assets block before
  run submission;
- analysis-failed but derivative-ready images remain eligible;
- asset hashes and roles survive planner/compiler/manifest round trips.

## Phase 4: Make Build Reservation Atomic and Recoverable

Extend `design_intake_operations` rather than creating a second generic job
system. Add the minimum fields needed for build reservation and reconciliation:

- reserved `run_id`;
- confirmed intake revision row ID;
- operation state such as `reserved`, `submitted`, `completed`, or `failed`;
- `force_new` flag;
- bounded error;
- updated timestamp.

Retain the existing unique key on
`(session_id, operation, idempotency_key)`. Add a partial uniqueness rule or
equivalent transactional lookup preventing more than one active non-force build
reservation for the same session, confirmed revision, and request hash.
`force_new=true` is deliberately exempt from request-level reuse, but its own
idempotency key still identifies one immutable result.

Add a narrow transactional `Memory` operation that:

1. validates the session, token, request hash, revision, and proposed run ID;
2. returns an existing reservation for the same idempotency key and hash;
3. rejects reuse of an idempotency key with a different request hash;
4. reconnects to an active identical non-force reservation;
5. inserts one reservation before any run is created or queued;
6. returns whether the caller owns submission.

Generate the run ID before submission and add an optional explicit `run_id` to
`IntakeLabService.submit()`. The owner of a new reservation submits that exact
ID. Duplicate callers return or inspect the reserved run instead of creating a
second candidate.

Reconciliation rules:

- if the reservation is `reserved` and the run does not exist, one caller may
  complete submission using the reserved ID;
- if the run exists, update the reservation to `submitted` and return it;
- when the run reaches a terminal state, update the operation state without
  changing its run ID;
- the same idempotency key always resolves to the same result, including a
  failed result;
- retrying a failed build requires a new request token or explicit New version;
- process restart must not produce a duplicate run for a persisted reservation.

`force_new` semantics:

- New version creates another root candidate from the same confirmed revision;
- previous candidates stay listed and previewable;
- New version does not mutate or continue an older candidate;
- concurrent delivery of the same New version token still creates only one
  candidate.

Tests:

- concurrent identical non-force calls create and queue one run;
- duplicate delivery after restart reconnects to the same run;
- same token plus different request hash fails;
- same token plus failed result returns that failed result;
- a new token after failure may create a new run;
- `force_new` with distinct tokens creates distinct candidates;
- `force_new` with the same token remains idempotent;
- failure between reservation and submission is recoverable.

## Phase 5: Permit Scoped Child Run IDs

Replace the HTTP adapter's root-only run-ID validator with the same bounded safe
opaque syntax already used by design services:

```text
^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$
```

This is syntax validation only. Authorization must still call
`incubation_service.design_run(incubation_id, run_id)` or another scoped
application-service method before returning data, evidence, review state, or a
preview.

Do not broaden `_run_root()` or any function that converts an initial root ID
into a filesystem location. Child IDs are persisted entities inside the already
resolved incubation workspace; they must not select workspaces directly.

Apply the scoped validator consistently to:

- run detail;
- run events;
- preview preparation and files;
- visual review;
- explicit refinement;
- candidate pages;
- any other route that accepts a persisted design run ID.

Tests:

- valid `intake-lab-*` roots continue to work;
- valid persisted `design-*` children work through every scoped endpoint;
- unknown child IDs return not found;
- child IDs belonging to another incubation return not found or forbidden
  without revealing existence;
- separators, traversal, overlength input, and encoded traversal are rejected;
- root filesystem resolution remains root-only.

## Phase 6: Make Lifecycle Projection Graph-Aware

Refactor `IncubationApplicationService._refresh_lifecycle()` to inspect the run
graph for the latest intake session and relevant confirmed revision instead of
only `design_intake_sessions.design_run_id`.

Use persisted run relationships and operation timestamps. Do not infer graph
membership from ID prefixes.

Projection rules:

- any currently relevant active root or descendant keeps the incubation in
  `building`;
- a retained reviewable candidate in the graph permits
  `ready_for_feedback` when no newer explicit operation is active;
- a failed descendant does not erase an older retained reviewable candidate;
- transition to `blocked` only when the relevant operation graph has no
  reviewable candidate and its newest requested operation is terminal-failed;
- completed deterministic validation reaches review without requiring a visual
  refinement child;
- historical runs from an older confirmed revision remain visible but do not
  control the current lifecycle;
- state calculation is deterministic across process restart.

Add a small application-level graph projection result rather than embedding
this logic in the route or browser JavaScript. Include IDs in diagnostics.

Tests:

- active child keeps building;
- ready child advances to feedback;
- failed child with ready parent preserves review availability;
- all-failed graph becomes blocked;
- older revision activity does not override the current revision;
- graph state is stable after reopening stores.

## Phase 7: Stabilize Version Selection and Polling

Treat `preferred_run_id` and `preview_run_id` as server recommendations, not
commands that overwrite owner interaction.

The browser state must distinguish:

- initial selection not yet made;
- automatic initial selection;
- explicit owner selection.

Polling behavior:

1. On first load, select the URL-requested run if valid.
2. Otherwise select `preferred_run_id`, then `preview_run_id`, then the newest
   available run.
3. Once the owner selects a run, preserve it while it remains in the response.
4. If the selected run disappears, fall back once and explain the change.
5. Do not change selected revision merely because a descendant changes status.
6. Keep candidate-page preview retries bounded and cancel stale retries when the
   selection changes.

Do not silently suppress child-run fetch failures. Show a bounded sync error in
the Design area while retaining the last valid projection. Never render raw
tracebacks, provider payloads, filesystem paths, or secrets.

Tests in `tests/test_intake_lab_preview_ui.py` must cover:

- first-load recommendation;
- explicit selection surviving multiple polls;
- selection fallback when a run is truly absent;
- visible bounded sync failure;
- stale preview retry cancellation;
- candidate availability based on persisted SHA rather than a vague preview
  boolean.

## Phase 8: Remove Automatic Refinement

Delete `_self_review_refine()` and every automatic call after validation,
recovery, or visual review. If a helper remains for compatibility, it must not
be reachable from job completion and should be removed once references are
gone.

Successful initial flow:

```text
candidate retained
  -> deterministic validation
  -> browser/accessibility checks
  -> optional read-only visual critique
  -> ready_for_review
```

An inconclusive visual provider result remains a visible, separate review
diagnostic. It must not trigger a code mutation. Whether it blocks approval is
controlled by the persisted quality policy, not an automatic repair.

An owner may explicitly request refinement through the existing refinement
application service and route. That operation creates one child with
`parent_run_id`, source candidate SHA, owner feedback, and frozen context.

Tests:

- validation success queues no child;
- recovery success queues no child;
- visual findings queue no child;
- explicit refinement creates exactly one child;
- duplicate explicit refinement delivery remains idempotent;
- refinement uses Native OpenCode and never changes the parent commit.

## Phase 9: Stop Forcing Optional Quality Configuration

In Intake Lab composition, keep `quality.browser` enabled only if that is a
locked product requirement already represented in validated configuration.
Stop unconditionally writing `quality.visual_critic = True` in `main.py`.

The checked-in neutral Intake Ada config may enable visual critique explicitly,
using the OpenRouter/DeepSeek Vision route defined above. The runtime must honor
an override that disables it.

Persist the effective quality policy in the run execution profile before build
execution. Later configuration changes must not alter validation or preview
semantics for an existing immutable candidate.

Tests:

- enabled configuration runs visual review;
- disabled configuration skips it;
- persisted runs retain their original policy after config changes;
- browser and deterministic gates remain independently represented.

## Phase 10: Implement the Controlled Initial Builder

Add `AstroReactDesignBuilder` as a production-quality implementation of the
existing `DesignBuilder` protocol. Reuse narrow pieces from
`application/design_lab.py`; do not route production behavior through a CLI or
duplicate the full application lifecycle.

Responsibilities of `AstroReactDesignBuilder`:

1. Validate `PageBuildRequest` and `BuildTarget` compatibility.
2. Require `operation_kind == "initial_build"`.
3. Resolve the exact immutable base SHA inside the isolated incubation clone.
4. Create a detached worktree under the incubation run workspace.
5. Build the model input from the frozen typed request, selected direction,
   confirmed intake, novelty constraints, approved capabilities, and approved
   website assets.
6. Call `LLMDesignPlanner` using the execution profile's OpenRouter DeepSeek
   Vision model and only its credential.
7. Validate the returned `ReactDesignSpec`; bounded structured repair may occur
   only within the configured planner repair count.
8. Resolve the approved asset map without symlinks, traversal, missing files, or
   unconfirmed IDs.
9. Compile through `AstroReactCompiler` into the controlled worktree.
10. Materialize only host-approved optional frontend libraries.
11. Verify the generated source tree against `ASTRO_REACT_PROFILE`.
12. Commit the generated source locally and create a namespaced local candidate
    ref.
13. Return `DesignCandidateReceipt` with exact base/candidate SHAs, candidate
    ref, manifests, changed paths, build profile, provider/model identity, asset
    evidence, and non-publishable target identity.
14. Remove temporary worktrees on success and every failure path while retaining
    the local candidate commit/ref once created.

The builder must not run the final quality lifecycle itself. `DesignService`
retains candidate state transitions and invokes host validation against the
exact returned SHA.

Controlled source policy:

- use `ASTRO_REACT_PROFILE.writable_patterns` exactly as the starting allowlist;
- allow the pinned scaffold files, `src/**`, `public/**`, and `design/**`;
- deny `.env`, `.github`, `node_modules`, `dist`, symlinks, submodules, and
  escaped paths;
- do not reuse the broader Pelican/neutral-scaffold writable patterns;
- ignore generated `node_modules`, `.astro`, and `dist` when calculating source
  changes and candidate commits;
- reject model attempts to provide source code, package dependencies, commands,
  or paths outside `ReactDesignSpec`.

The generated site contract:

- Astro is the static compiler and route system;
- React/TypeScript is available only for controlled interactive components;
- static `dist/` is the preview artifact;
- dependencies and lockfile are copied from the pinned scaffold;
- every route is emitted from validated structured page data;
- design tokens and assets are emitted deterministically;
- the route and design manifests are part of the candidate source;
- recompiling the same spec and assets yields the same source bytes.

Add a routing builder, or equivalent minimal dispatch in composition, that sends
initial builds to `AstroReactDesignBuilder` and explicit refinements to
`NativeOpenCodeBuilder`. Keep `DesignService` unaware of concrete provider
implementations beyond the protocol and operation contract.

Tests:

- builder rejects the wrong operation kind or mismatched target;
- planner receives only frozen context and approved website assets;
- compiler output is deterministic;
- generated dependencies match the pinned allowlist;
- candidate commit excludes build output and caches;
- no remote refs change;
- live paths and databases remain unchanged;
- receipt base SHA and candidate SHA are exact and distinct when content
  changes;
- routing selects controlled initial build and Native OpenCode refinement;
- a planner or compiler failure leaves a durable bounded diagnostic.

## Phase 11: Persist and Honor Build Profiles

Add a typed or strictly validated build-profile identity to the run execution
profile and candidate receipt metadata.

Profile selection is host-owned:

- controlled initial candidates use `astro_react`;
- legacy neutral/Pelican baselines use `pelican_baseline` where comparison still
  requires them;
- refinements inherit the parent candidate's profile;
- unknown or missing profiles fail closed for new controlled runs;
- persisted legacy runs may use a narrowly documented fallback only when their
  existing source contract proves the correct profile.

Quality execution:

- use `run_quality_gates(..., build_runner=...)` with `build_site()` for
  Astro/React;
- run `npm ci --ignore-scripts`, `npm run check`, and `npm run build` from the
  pinned profile;
- use a workspace-local npm cache and sanitized build environment;
- validate `dist/`, route inventory, required content, manifest hashes,
  accessibility, browser evidence, and changed paths;
- do not accept a candidate merely because source compilation succeeded;
- preserve Pelican `build.sh` and `output/` behavior for its explicit profile.

Do not construct build commands from model output or arbitrary request values.

Tests:

- profile identity survives persistence and reload;
- Astro quality uses `dist/` and explicit commands;
- Pelican quality still uses `output/` and `build.sh`;
- one profile cannot use the other's allowed paths;
- missing manifests, routes, content, or output fail deterministically;
- npm environment excludes unrelated credentials and user-global config.

## Phase 12: Generalize Immutable Preview Building

Refactor `PreviewBuildCache` to accept or resolve an explicit persisted build
profile for the requested immutable ref.

Required behavior:

- archive the exact candidate SHA or baseline SHA into a temporary preview
  workspace;
- invoke the profile's host-owned build adapter;
- cache the profile's output directory (`dist` or `output`) by immutable
  identity;
- never execute model-provided commands;
- retain path containment, symlink, size, timeout, and cache eviction checks;
- serve nested assets with correct content types;
- rewrite local HTML and CSS URLs under the active review root;
- inject preview fetch support without granting same-origin access to the admin
  API;
- include `/ada/` correctly when deployed behind the current mount point;
- keep preview bearer capabilities scoped to one run/ref variant.

Do not require `build.sh` for an Astro candidate. Do not make a mutable worktree
the preview source.

Tests:

- Astro candidate index and nested assets serve from `dist/`;
- nested route relative URLs remain under `/ada/api/.../review/...`;
- root-relative HTML, CSS URLs, fetch, XHR, and beacon requests remain scoped;
- Pelican previews remain unchanged;
- invalid profile, ref, path, token, traversal, and symlink requests fail;
- a retained child candidate SHA is previewable after process restart.

## Phase 13: Add Purge Tombstones

Add `PURGED = "purged"` to `IncubationStatus` and make it terminal. The central
`IntakeAdaStore` registry is the tombstone authority.

A tombstone may retain only minimal audit metadata:

- incubation ID;
- original creation timestamp;
- purge timestamp;
- terminal `purged` status;
- bounded purge outcome/error needed to finish cleanup safely.

It must not retain raw messages, customer facts, research content, asset data,
design content, generated copy, provider payloads, credentials, candidate
source, or a reopenable workspace pointer.

Store API behavior:

- normal listing excludes purged rows by default;
- normal get/open/runtime operations treat purged IDs as unavailable;
- an internal `include_purged` lookup exists only for audit and idempotent purge;
- transitions out of purged are rejected;
- creating an incubation with a tombstoned ID is rejected;
- repeated purge returns success and may finish residual filesystem cleanup.

Purge sequence:

1. Resolve the central row through an internal include-purged lookup.
2. Return success immediately if already purged after attempting bounded
   residual cleanup.
3. Reject accepted, provisioning, or provisioned incubations under the existing
   policy.
4. Stop workers and executors.
5. Remove runtime/store handles and close the incubation database.
6. Mark the central identity inaccessible before any code path can reopen it.
7. Delete the isolated workspace without following symlinks or escaping the
   incubation root.
8. Persist the final purge result and timestamp.
9. Return an error if content removal failed, while keeping the identity
   non-reopenable so a retry can complete cleanup.

Use ordering or an atomic same-filesystem quarantine rename so a process crash
cannot recreate a purged identity. Do not delete the central tombstone.

Tests:

- purge removes the isolated workspace;
- normal list and get exclude the tombstone;
- open/runtime calls cannot recreate directories or databases;
- repeated purge is safe;
- transition and create reject the old ID;
- purge remains prohibited for accepted/provisioning/provisioned states;
- simulated deletion failure remains inaccessible and is retryable;
- central tombstone contains no customer payload.

## Phase 14: Version History and Owner Review

Project version history by `intake_session_id` and confirmed revision. Preserve
`parent_run_id` for refinement provenance and show operation kind explicitly.

The Design UI should present:

- each root version generated from the confirmed revision;
- child refinements grouped beneath their parent;
- current status and bounded failure reason;
- exact candidate availability;
- quality and visual-review state;
- which version is selected;
- New version as an explicit root-generation action;
- Refine as an explicit child-generation action;
- approve and decline controls only where the existing review workflow permits.

Do not infer approval from visual quality. Do not hide earlier candidates after a
new version or refinement is created.

Approval eligibility must require the persisted deterministic policy for that
exact candidate SHA to pass. If visual critique is configured as advisory, label
it advisory. If configured as a gate, an inconclusive result must remain
blocking until an explicit retry or policy-compliant resolution.

Tests:

- roots and children group correctly;
- selection and previews use the chosen immutable SHA;
- New version creates a root, not a child;
- Refine creates a child, not a replacement root;
- failed newer work does not remove an older reviewable version;
- approval cannot target a different SHA than the displayed candidate.

## Phase 15: Diagnostics, Recovery, and Performance Evidence

Every build-stage diagnostic should include the relevant identifiers when
available:

- incubation ID;
- intake session ID and confirmed revision row ID;
- build operation ID and request hash prefix;
- design run ID and parent run ID;
- base and candidate SHA;
- provider and model;
- adapter and build profile.

Keep messages bounded and sanitized. Never include credentials, raw provider
responses, full customer conversations, arbitrary file content, or external
integration secrets.

Persist stage events sufficient to measure:

- reservation latency;
- planner latency;
- compilation latency;
- candidate commit latency;
- dependency install/check/build latency;
- deterministic validation latency;
- browser/accessibility latency;
- visual-review latency;
- total time to `ready_for_review`.

Recovery on process startup must:

- retain inspectability of terminal runs;
- recover reserved/submitted build operations without duplication;
- recover retained candidate SHAs through existing candidate recovery;
- recompute lifecycle from persisted run graphs;
- never start an automatic refinement;
- never alter an immutable candidate commit.

## HTTP and UI Compatibility

Keep public API paths stable. Broaden accepted scoped run-ID syntax without
renaming endpoints.

Maintain response allowlists in `application/intake_lab.py`; do not serialize raw
database rows. New fields should be documented dictionaries or typed result
objects. Candidate and lifecycle responses should provide enough identity for
the browser to avoid guessing:

- run ID;
- parent run ID;
- operation kind;
- intake revision identity;
- status;
- candidate availability;
- preferred run ID;
- preview run ID;
- build profile;
- bounded quality state;
- bounded error state.

The UI should poll active state only. It should not treat disappearance from the
active chat-job list as completion; fetch durable job detail by ID when needed.

## Required File-Level Work

Expected primary files are listed below. Keep changes narrower if an existing
boundary already provides the required behavior.

### Configuration and composition

- `src/site_agent/intake-ada.yaml`
- `src/site_agent/config.py`
- `src/site_agent/main.py`
- `src/site_agent/runtime.py`

### Persistence and contracts

- `src/site_agent/core/memory.py`
- `src/site_agent/core/media_contracts.py`
- `src/site_agent/core/media_worker.py`
- `src/site_agent/core/incubation_contracts.py`
- `src/site_agent/core/intake_ada_store.py`
- `src/site_agent/core/design_contracts.py` only if build-profile persistence
  needs a typed field not already represented by execution profiles

### Application services

- `src/site_agent/application/design_intake.py`
- `src/site_agent/application/intake_lab.py`
- `src/site_agent/application/incubations.py`
- `src/site_agent/application/design_jobs.py`
- `src/site_agent/application/designs.py`
- `src/site_agent/application/media.py`

### Builder, compiler, quality, and preview adapters

- `src/site_agent/hands/builder.py`
- a narrowly named controlled builder module if keeping it out of `builder.py`
- `src/site_agent/brain/react_design.py`
- `src/site_agent/core/react_design_contracts.py`
- `src/site_agent/hands/astro_react_compiler.py`
- `src/site_agent/hands/design_lab_git.py`
- `src/site_agent/hands/design_quality.py`
- `src/site_agent/hands/site_build.py`
- `src/site_agent/hands/design_visual_review.py`
- `src/site_agent/hands/opencode_runner.py`
- `src/site_agent/web/preview.py`

### HTTP and browser UI

- `src/site_agent/web/intake_lab.py`
- `src/site_agent/web/static/intake_lab.html`

### Focused tests

- `tests/test_intake_ada_config.py`
- `tests/test_vision.py`
- `tests/test_media_service.py`
- `tests/test_memory.py`
- `tests/test_design_intake.py`
- `tests/test_intake_lab_service.py`
- `tests/test_intake_lab_web.py`
- `tests/test_intake_lab_preview_ui.py`
- `tests/test_incubation_service.py`
- `tests/test_incubation_web.py`
- `tests/test_intake_ada_store.py`
- `tests/test_design_jobs.py`
- `tests/test_design_builder.py`
- `tests/test_design_service.py`
- `tests/test_design_lab.py`
- `tests/test_astro_react_compiler.py`
- `tests/test_site_build.py`
- `tests/test_design_quality.py`
- `tests/test_design_visual_review.py`
- `tests/test_preview.py`

## Implementation Order

Follow this order to keep intermediate states testable:

1. Add provider-routing tests and switch Intake Ada vision to OpenRouter.
2. Add migration 34 and typed independent media-analysis state.
3. Refactor media claims, retries, serialization, and existing-row recovery.
4. Add confirmed website-asset preflight and frozen asset propagation.
5. Add transactional build reservations and explicit run-ID submission.
6. Broaden scoped run-ID syntax and complete endpoint tests.
7. Add graph-aware lifecycle projection.
8. Stabilize UI selection, polling, preview retries, and sync errors.
9. Remove automatic refinement and stop forcing visual critique.
10. Implement and unit-test `AstroReactDesignBuilder`.
11. Add operation-aware builder routing in incubation runtime composition.
12. Persist build profiles and run Astro quality through `build_site()`.
13. Generalize immutable preview caching for `dist/` and `output/`.
14. Add purge tombstones and non-reopenable cleanup.
15. Complete version-history and approval-identity tests.
16. Run the full verification and fresh runtime acceptance flow.
17. Update conflicting architecture documents to point to this plan rather than
    leaving two active contracts.

Do not combine all phases into one rewrite. Commit boundaries, if the user later
requests commits, should align with independently passing phases and contain no
unrelated worktree changes.

## Verification Commands

Run focused tests first. The exact focused command may evolve with file names,
but it should include every changed subsystem. Then run:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
git diff --check
```

Do not commit generated wheels, caches, databases, screenshots, OpenCode files,
worktrees, or runtime state.

## Runtime Acceptance Procedure

After automated verification, use a fresh incubation rather than mutating a
historical accepted candidate.

1. Restart `site-agent-intake-lab.service` safely.
2. Open the Intake Lab through its configured deployment path.
3. Create one isolated incubation.
4. Upload at least one image and designate it for website use.
5. Confirm that derivatives become ready and semantic analysis reports
   OpenRouter/DeepSeek identity.
6. Confirm the intake revision with valid location semantics and conversion
   data.
7. Trigger one initial build with a unique idempotency token.
8. Deliver the same request concurrently or immediately again and verify only
   one root run exists.
9. Observe the run through durable job detail, design run detail, and run events.
10. Verify the planner and compiler use only confirmed website assets.
11. Verify a local candidate ref and exact candidate SHA are retained.
12. Verify `npm check/build`, deterministic checks, browser checks, and the
    configured read-only visual critique complete without an automatic child.
13. Load every candidate route and asset through `/ada/api/...` preview paths at
    desktop, tablet, and mobile widths.
14. Select an older version, allow several polls, and verify the selection stays
    stable.
15. Trigger one explicit refinement and verify it appears as a child using
    Native OpenCode.
16. Verify the parent remains immutable and previewable.
17. Trigger New version and verify it creates a separate root candidate.
18. Approve or decline only through Design controls if the acceptance exercise
    intentionally tests that operation.
19. Purge a separate disposable incubation and verify it cannot be reopened.
20. Record stage timings and compare them with the latency targets.

For a design request, inspect the durable chain in this order:

1. `GET /api/chat/jobs/{job_id}`.
2. Read `result.merge_draft_id` or `result.proposal_id` for completed jobs where
   applicable.
3. `GET /api/drafts` and confirm the referenced pending draft where applicable.
4. `GET /api/journal` and confirm setup state and draft ID where applicable.
5. `GET /api/pages?draft_id={draft_id}` for Design page inventory where
   applicable.
6. Load the iframe through `/ada/api/review/{draft_id}/{page}` or the scoped
   incubation review endpoint and inspect all CSS/image requests under `/ada`.
7. Approve or decline only from Design controls.

Do not infer completion from `GET /api/chat/jobs`; it intentionally returns only
active jobs.

## Completion Criteria

The plan is complete only when all of the following are true:

- Intake Ada contains no required Entrim vision route and uses OpenRouter
  DeepSeek Vision for media and visual review.
- A semantic-analysis failure cannot make valid normalized image derivatives
  unusable.
- Confirmed website assets are frozen, validated, and traceable into the
  candidate manifest.
- Concurrent duplicate initial build requests create one durable run.
- New version intentionally creates a separate immutable root candidate.
- Persisted child runs work through scoped detail, evidence, review, refinement,
  pages, and preview endpoints.
- Incubation lifecycle follows the relevant run graph across restart.
- Owner-selected versions remain selected during polling.
- Successful initial validation creates no automatic refinement.
- Initial builds use the controlled Astro/React planner/compiler path.
- Explicit refinements use Native OpenCode and retain parent provenance.
- Astro candidates pass host-owned checks and preview from immutable `dist/`.
- Pelican behavior remains covered and unchanged outside its explicit profile.
- Approval cannot target an unvalidated or different candidate SHA.
- Purge removes customer workspace content, retains only a minimal tombstone,
  and prevents reopening.
- Full tests, compileall, wheel build, and diff checks pass.
- A fresh image-led runtime acceptance run reaches review and meets the stated
  latency target or records a specific stage-level performance defect.

## Final Safety Review

Before declaring completion, inspect the final diff for these prohibited
regressions:

- production mutation without explicit approval;
- preview links bypassing Design review;
- raw route-to-route business workflow calls;
- direct plugin/MCP access to `Memory.conn`;
- arbitrary model-authored code, dependencies, or commands in initial builds;
- broad filesystem allowlist changes affecting existing profiles;
- cross-incubation run or asset access;
- credentials in logs, child environments, tests, docs, or persisted payloads;
- automatic refinement or publication;
- purged workspace recreation;
- customer-specific assumptions in generic code;
- generated caches, databases, screenshots, worktrees, or configuration added to
  version control.
