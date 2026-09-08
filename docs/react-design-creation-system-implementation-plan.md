# React Design Creation System Implementation Plan

**Status:** Superseded on 2026-08-31. Do not implement this scaffold/compiler
plan. Follow `docs/canonical-opencode-design-test-implementation-plan.md`.

**Date:** 2026-08-30

**Superseded by:** `docs/canonical-opencode-design-test-implementation-plan.md`

## Purpose

Build the system that was originally intended:

1. Ada creates complete, consistent websites on a standard React-capable
   frontend instead of making unconstrained edits to whichever static files a
   repository happens to contain.
2. An operator can generate a candidate locally and compare it with the current
   site without Cloudflare, GitHub writes, production credentials, or live data.
3. Production integration happens only after creation and comparison work
   end-to-end and only through explicit owner approval.

This is an implementation contract for a coding AI. Follow the phases in order.
Do not treat the current partial design-engine code as proof that any phase is
complete.

## Product Decision

Use one frontend stack:

- **Astro** is the static site compiler and route system.
- **React with TypeScript** is the component and interaction layer.
- **CSS variables and component styles** implement the generated design system.
- **Static `dist/` output** is the only preview and deployment artifact.
- **Node and npm** are the local toolchain; dependencies are pinned in a
  committed lockfile.

Astro is selected because this is a content and marketing website system. It
produces crawlable static pages, supports multiple routes without a runtime
server, and permits React only where interaction needs it. Do not create a Vite
SPA, Next.js server, Cloudflare Worker, or separate React application.

Do not confuse these meanings of compiler:

- Astro compiles the website to static output.
- The site-agent design compiler converts a validated design specification into
  a bounded Astro/React source tree.
- React Compiler optimization is not required for the first working system. It
  may be evaluated later after correctness and browser behavior are proven.

## Simple Operator Experience

The first supported workflow must be one command:

```bash
site-agent design-lab generate \
  --config examples/oceanicvibes.config.yaml \
  --intake examples/oceanicvibes.intake.json \
  --workspace /tmp/site-agent-design-lab/oceanicvibes
```

On success, the command prints only:

- run ID;
- immutable baseline SHA;
- immutable candidate SHA;
- local comparison URL;
- quality result;
- workspace path.

The comparison URL opens a local page with:

- Baseline;
- Candidate;
- side-by-side mode;
- desktop, tablet, and mobile viewport controls;
- page selector;
- quality findings.

No deployment account or cloud service is involved. Closing the local process
must not destroy the retained run, candidate, reports, or screenshots.

## Non-Negotiable Safety Rules

- Never write to the configured live clone, live SQLite database, or live data
  directory.
- Never push, publish, merge, open a pull request, create a production draft, or
  call a production adapter in design-lab mode.
- Strip GitHub, Cloudflare, R2, admin, CrawlSEO, and publishing credentials from
  every child process. Retain only the selected model credential.
- Clone public source read-only into the supplied design-lab workspace.
- Resolve and record the baseline as a full commit SHA before generation.
- Build from detached worktrees rooted at exact SHAs.
- Store a candidate only as a local Git commit and local namespaced ref.
- Build both baseline and candidate from immutable source archives.
- Store npm cache, generated output, screenshots, reports, OpenCode files, and
  SQLite state under the design-lab workspace, never in the customer repository.
- Run remote-ref and live-path sentinel checks on success and every failure path.
- Local runs have no approve, publish, promote, or merge operation.
- Production remains unchanged until a later, explicit integration phase.

## What Exists Today

### Reusable foundations

Retain and harden these concepts rather than rewriting them:

- typed intake, build target, candidate receipt, manifest, and quality report in
  `core/design_contracts.py`;
- durable design runs and events in `core/memory.py`;
- application lifecycle coordination in `application/designs.py`;
- detached worktrees and exact-base candidate commits in
  `hands/opencode_runner.py`;
- experiment path overlap and credential filtering in
  `application/designs.py` and `hands/design_experiment.py`;
- host-owned path, secret, build, output, and basic document checks in
  `hands/design_quality.py`;
- immutable preview build/cache ideas in `web/preview.py`;
- short-lived scoped preview tokens in `web/preview.py`;
- sanitized OceanicVibes fixture in `examples/oceanicvibes.intake.json`.

### Partial or misleading implementation

Do not build new behavior on these assumptions without correcting them:

- `design-experiment` invokes an unconstrained coding-agent edit; it is not a
  React design compiler.
- The default scaffold is Pelican-only.
- Preview building assumes `bash build.sh` and `output/`.
- Candidate page inventory scans source HTML rather than compiler output.
- Browser quality has a protocol but no concrete browser implementation.
- Accessibility and visual-critic configuration do not execute real gates.
- The web review path exposes only a candidate, not baseline comparison.
- The CLI hardcodes OceanicVibes static paths and pages in generic code.
- Existing tests often use fake receipts and disabled quality gates.
- The POC report records that no candidate was generated.

### Missing system

The following does not exist yet:

- standard Astro/React customer-site scaffold;
- versioned design specification consumed by a deterministic compiler;
- bounded Astro/React source emitter;
- pinned npm dependency policy and build adapter;
- concrete Playwright browser-quality adapter;
- baseline build capture;
- baseline/candidate page and screenshot comparison;
- one real local end-to-end acceptance test;
- a successful OceanicVibes candidate run.

## Target Architecture

```text
SiteIntake
  -> deterministic brief + selected direction
  -> validated ReactDesignSpec
  -> deterministic AstroReactCompiler
  -> bounded Astro/React source tree
  -> npm ci + astro check + astro build
  -> dist/ static artifact + route manifest
  -> immutable local candidate commit
  -> deterministic + Playwright quality gates against that exact commit
  -> local baseline/candidate comparison
```

The model may propose and revise the `ReactDesignSpec`. The host owns schema
validation, source emission, dependency selection, build commands, path policy,
quality gates, candidate identity, and local-only enforcement.

The model must not directly edit `package.json`, lockfiles, Astro configuration,
build scripts, CI, deployment files, or arbitrary source paths. This is the main
consistency improvement over the current coding-agent-only approach.

## Required Boundaries

Add narrow boundaries rather than a plugin framework.

### `DesignPlanner`

Input:

- validated `SiteIntake`;
- deterministic brief;
- current-site evidence;
- available media metadata.

Output:

- validated `ReactDesignSpec` only.

The first implementation can use the existing model/provider loop. Persist raw
model output only as diagnostic evidence; never compile it before validation.

### `ReactDesignSpec`

Create a versioned typed contract. At minimum it contains:

- site identity and language;
- routes, SEO metadata, navigation, and route relationships;
- verified copy blocks and prohibited claims;
- primary and secondary actions with exact destinations or explicit unavailable
  state;
- color roles;
- typography roles and scale;
- spacing, containers, breakpoints, radii, borders, and shadows;
- header, footer, section, card, CTA, media, and form compositions;
- component props and bounded component variants;
- image references, alt intent, crop, and aspect ratio;
- motion declarations and reduced-motion behavior;
- responsive ordering and visibility rules;
- one signature visual gesture;
- explicit omissions and unresolved unknowns.

Do not permit arbitrary JavaScript, JSX, CSS, HTML, package names, URLs, file
paths, or shell commands inside the specification.

### `AstroReactCompiler`

Input:

- validated `ReactDesignSpec`;
- compiler version;
- approved local asset map.
- host-verified runtime library files selected by the dependency policy.

Output:

- a deterministic map of relative file paths to bytes;
- route manifest;
- design manifest;
- compiler receipt containing compiler version and content hashes.

### Frontend runtime dependencies

Runtime libraries remain host-owned even when Ada chooses a motion treatment.
The planner receives a sanitized catalog of enabled capabilities and records its
selection as names in `motion.libraries`. The design-lab dependency adapter
resolves those names through a small host-owned allowlist, downloads pinned npm
archives with lifecycle scripts disabled, verifies the recorded integrity hash,
and passes only named runtime files under `public/vendor/` to the compiler. The
current approved entry is GSAP 3.12.5 with ScrollTrigger; the typed design spec
cannot choose arbitrary packages, versions, URLs, or shell commands.

### Multi-model comparison

Model comparisons run the same sanitized intake through separate design-lab
workspaces. The matrix runner records the model ID, retained run ID, candidate
SHA, quality state, logs, and workspace for each entry in
`model-comparison.json`. A read-only comparison server renders the retained
candidate pages together; a failed provider remains visible as evidence and
does not prevent the other candidates from being reviewed.

The compiler owns a small, tested component vocabulary. Initial components:

- site shell;
- header and responsive navigation;
- footer;
- hero;
- editorial text section;
- image/text split;
- service or feature grid;
- proof/fact list that cannot imply unsupported testimonials;
- CTA band;
- contact/enquiry block;
- journal listing shell;
- optional React menu and low-motion interactive visual.

The compiler can compose and style these primitives from the specification. It
must fail on unsupported structures rather than inject arbitrary model code.

### `SiteBuildAdapter`

Define a typed profile with:

- source kind;
- install command;
- check command;
- build command;
- output directory;
- route-manifest source;
- writable source patterns;
- prohibited paths.

Implement two explicit profiles:

- `pelican_baseline`: read-only build of the current OceanicVibes source;
- `astro_react`: candidate build using the pinned standard scaffold.

Site-specific pages and commands belong in profile/configuration data, not
generic CLI code.

### `BrowserQualityAdapter`

Implement with Playwright Chromium. It must serve a static artifact on
`127.0.0.1` and return structured evidence for every route and viewport:

- page and console errors;
- failed local requests;
- horizontal overflow;
- element clipping and fixed-header overlap;
- heading and landmark structure;
- keyboard navigation and visible focus;
- serious/critical accessibility findings;
- reduced-motion behavior;
- screenshot path and hash.

Screenshots and browser traces stay outside the candidate repository.

### `DesignComparisonService`

Input:

- exact baseline SHA and build profile;
- exact candidate SHA and build profile;
- route manifests;
- screenshot evidence.

Output:

- normalized page pairs;
- baseline-only and candidate-only routes;
- artifact URLs scoped by run and variant;
- deterministic quality summaries;
- screenshot pairs and hashes.

It reports evidence. It does not choose a winner and cannot mutate either site.

## Expected Implementation Locations

Use these module boundaries unless a focused test demonstrates a smaller,
clearer placement:

- `core/react_design_contracts.py`: design specification and compiler receipt;
- `hands/astro_react_compiler.py`: deterministic source emitter only;
- `hands/site_build.py`: explicit Pelican and Astro/React build profiles;
- `hands/playwright_quality.py`: concrete browser adapter;
- `application/design_lab.py`: local run orchestration and safety checks;
- `web/design_lab.py`: local read-only artifact and comparison server;
- `frontend/astro-react-scaffold/`: pinned scaffold, component vocabulary, and
  frontend tests;
- `tests/fixtures/design_lab/`: local repositories and deterministic specs;
- `tests/browser/`: explicit Chromium acceptance tests.

Do not place the new orchestration in HTTP route functions, call route functions
from services, access `Memory.conn` outside persistence code, or add a universal
compiler/plugin abstraction.

## Repository Layout

Use a standard generated customer-site layout:

```text
package.json
package-lock.json
astro.config.mjs
tsconfig.json
src/
  assets/
  components/
    SiteHeader.astro
    SiteFooter.astro
    Hero.astro
    sections/
    interactive/
  layouts/
    SiteLayout.astro
  pages/
    index.astro
    journal/
  styles/
    tokens.css
    global.css
  content/
public/
design/
  ada-design-manifest.json
  ada-route-manifest.json
```

Do not put generated output, node modules, test screenshots, model configuration,
or credentials in the candidate commit.

## Implementation Phases

### Phase 0: Reconcile and quarantine the partial engine

Goal: stop false confidence before adding frontend work.

Tasks:

1. Mark the old design-engine plan superseded by this document.
2. Record the current design files and tests as partial, not complete.
3. Keep `design_engine.enabled: false` by default.
4. Rename the operator-facing experimental command only when the new command is
   ready; until then document that `design-experiment` is legacy and incomplete.
5. Add no compatibility layer for unshipped design-run behavior. Preserve only
   persisted state needed by an actual existing database.
6. Write failing acceptance tests for the compiler and local safety before
   changing implementation.

Exit criteria:

- no documentation claims the current system creates React sites;
- no local run can be mistaken for a production-ready candidate;
- focused failing tests define the next phase.

### Phase 1: Standard Astro/React scaffold

Goal: prove the frontend stack independently of AI and design runs.

Tasks:

1. Add a versioned scaffold under package data or a dedicated source directory.
2. Pin Astro, React, React DOM, TypeScript, and test dependencies with a lockfile.
3. Add the component vocabulary, token stylesheet, layouts, and two representative
   routes.
4. Implement deterministic scaffold initialization in a new empty directory.
5. Run `npm ci`, type/check, unit tests, and static build locally.
6. Verify `dist/` contains complete HTML, CSS, JS, fonts/images, and route data.
7. Ensure the scaffold works with JavaScript disabled except for explicitly
   interactive enhancements.

Required tests:

- exact scaffold file inventory;
- repeat initialization is deterministic;
- non-empty target is rejected;
- production build works from the committed lockfile;
- no external network request is required at page runtime;
- generated routes contain SEO metadata, one H1, landmarks, and local assets.

Exit criteria:

- a non-AI fixture compiles to a functional static site;
- desktop and mobile browser smoke tests pass.

### Phase 2: Typed design specification and deterministic compiler

Goal: turn structured design intent into a working site without arbitrary code
generation.

Tasks:

1. Add `ReactDesignSpec`, route, section, component, token, asset, and motion
   contracts.
2. Add strict bounds and reject unknown executable fields.
3. Implement `AstroReactCompiler` as a pure transformation.
4. Emit only allowlisted files from controlled templates.
5. Emit and validate design and route manifests.
6. Record compiler version and hashes in a compiler receipt.
7. Add semantic conformance checks between spec, emitted files, and manifests.

Required tests:

- same inputs produce byte-identical output;
- path traversal, symlinks, case collisions, arbitrary scripts, and dependencies
  are rejected;
- verified facts and exact CTA destinations are preserved;
- unknown prices, certifications, testimonials, and schedules remain absent;
- every route builds;
- every declared component and token has an emitted implementation;
- reduced-motion and mobile behavior are emitted;
- compiler output passes the real Astro build.

Exit criteria:

- a checked-in OceanicVibes design spec deterministically produces a valid
  Astro/React candidate without calling a model.

### Phase 3: Ada planning and bounded repair

Goal: let Ada create design specifications while the host retains implementation
control.

Tasks:

1. Replace direct implementation prompting with a planner prompt that returns
   `ReactDesignSpec` JSON.
2. Include sanitized business facts, existing-site digest, media metadata, and
   explicit unknowns.
3. Validate model output before compiler invocation.
4. Return validation findings to the same model session for at most two repairs.
5. After compilation, return only spec-level quality findings for bounded repair.
6. Do not allow the model to edit compiler templates or toolchain files.
7. Persist the selected direction, rejected alternatives, spec, compiler receipt,
   model/session IDs, and repair history.

Required tests:

- malformed model output never reaches the compiler;
- prompt injection in intake/media metadata cannot add executable fields;
- repairs remain bounded and durable;
- no-change and repeated-invalid responses fail clearly;
- exact facts and prohibited claims are checked after every repair;
- a deterministic fake planner completes the entire flow.

Exit criteria:

- Ada can create a candidate from intake through the typed spec and compiler;
- the host, not Ada, controls source shape and dependencies.

### Phase 4: Real quality gates

Goal: prevent broken candidates from being presented as successful designs.

Tasks:

1. Generalize current build/output checks through `SiteBuildAdapter` profiles.
2. Implement Playwright Chromium quality inspection.
3. Add accessibility checks and make serious/critical findings blocking.
4. Validate all routes at desktop, tablet, and mobile viewports.
5. Capture screenshots and hashes outside the repository.
6. Verify manifest claims against rendered/computed evidence where practical.
7. Re-run all gates after every repair.
8. Distinguish `failed` from `incomplete`; unavailable required browser evidence
   can never pass.

Required tests:

- build, console, network, overflow, clipping, focus, keyboard, accessibility,
  and reduced-motion failures block;
- missing browser dependency produces `incomplete`, not `passed`;
- screenshots correspond to the exact artifact SHA;
- fake receipts/hashes are recomputed and rejected;
- repair exhaustion retains diagnostic evidence.

Exit criteria:

- a candidate cannot become reviewable without real static and browser evidence.

### Phase 5: Local design lab and comparison

Goal: provide the one-command no-cloud test workflow.

Tasks:

1. Add `site-agent design-lab generate`.
2. Create a dedicated clone, DB, npm cache, artifact store, and report directory
   under `--workspace`.
3. Capture live-path sentinels and remote refs before any operation.
4. Build the exact baseline with `pelican_baseline`.
5. Generate and build the candidate with `astro_react`.
6. Commit the candidate to `refs/ada-design-lab/{run_id}` only.
7. Run baseline and candidate quality capture.
8. Start the local comparison server after successful generation and keep the
   command running until interrupted. Add `--no-serve` for CI and scripted runs.
   Also add `site-agent design-lab serve --workspace ... --run ...` so a retained
   run can be reopened without regenerating it.
9. Serve immutable artifacts at variant-scoped local paths.
10. Implement baseline, candidate, side-by-side, page, and viewport controls.
11. Run safety checks in `finally` so failures also prove no mutation.

Local artifact layout:

```text
workspace/
  source.git-or-clone/
  worktrees/
  data/design-lab.db
  npm-cache/
  artifacts/{run_id}/baseline/
  artifacts/{run_id}/candidate/
  reports/{run_id}/quality.json
  reports/{run_id}/comparison.json
  screenshots/{run_id}/{variant}/
```

Required tests:

- a local bare remote has identical refs before and after success and failure;
- live clone/data sentinel hashes remain unchanged;
- sanitized child processes do not receive production credentials;
- baseline and candidate assets cannot cross-contaminate cache entries;
- route inventory comes from built artifacts;
- tokens are scoped to run and variant;
- nested routes and assets work under the local comparison mount;
- local UI exposes no mutation control;
- retained runs can be served after process restart.

Exit criteria:

- one command produces a retained candidate and opens a useful local comparison;
- no Cloudflare or remote write is possible from this path.

### Phase 6: OceanicVibes proof of concept

Goal: evaluate the complete system against the real baseline.

Preconditions:

- Phases 1-5 pass with deterministic fixtures.
- Browser dependencies are explicitly installed.
- OpenRouter model access is available.
- The public baseline SHA remains
  `56aa25740389f74e4499d35d528d4b2376c82369`, or a deliberate new SHA is
  recorded before the run.

Procedure:

1. Run the one design-lab generate command.
2. Confirm baseline Pelican output builds.
3. Confirm Ada produces a valid `ReactDesignSpec`.
4. Confirm the Astro/React candidate builds.
5. Review every route and viewport locally.
6. Record candidate SHA, manifests, quality report, screenshot hashes, model ID,
   compiler version, repair attempts, and remote/live immutability evidence.
7. Have a human compare design quality; do not reduce the decision to an LLM
   score.
8. Repeat with revised intake or planner instructions only after preserving the
   previous run for comparison.

Exit criteria:

- a real candidate exists and can be compared locally with the baseline;
- all blocking quality gates pass;
- no remote ref or live path changed;
- the POC report contains actual evidence rather than intended behavior.

### Phase 7: Production integration

Do not begin this phase as part of the local POC.

Goal: make the proven Astro/React system available to new production sites and
explicit migrations.

Tasks:

1. Make the Astro/React scaffold the default for newly initialized sites.
2. Keep existing Pelican sites unchanged until an explicit migration is
   requested and reviewed.
3. Define how journal content is supplied to Astro without breaking current
   article durability and URLs.
4. Connect immutable candidate review to the existing Design tab.
5. Require explicit owner approval of the exact reviewed candidate SHA.
6. Add a deploy adapter only after local static artifacts are proven; deployment
   is not part of design creation.
7. Pilot on a non-live repository before OceanicVibes production migration.

Exit criteria:

- new sites use the standard React-capable frontend;
- existing sites remain stable;
- production changes only through exact-SHA owner approval.

## Test Strategy

### Unit tests

- contracts and canonical hashes;
- compiler determinism and file policy;
- fact/prohibited-claim handling;
- design and route manifest conformance;
- build profile validation;
- environment sanitization and path overlap.

### Integration tests

- real npm install/check/build against a pinned fixture;
- exact-base detached candidate commit;
- local ref creation with no push;
- immutable artifact extraction and route inventory;
- quality report identity recomputation;
- durable run recovery after restart.

### Browser tests

- every route at 1440x1000, 768x1024, and 390x844;
- assets, console, network, overflow, clipping, focus, keyboard, accessibility,
  and reduced motion;
- baseline/candidate isolation and side-by-side comparison;
- local comparison controls on desktop and mobile.

### One true end-to-end test

Use a local fixture repository, local bare remote, deterministic fake planner,
real compiler, real npm build, real SQLite DB, real preview server, and real
Chromium:

```text
create local experiment
-> capture baseline
-> plan spec
-> compile Astro/React source
-> build static candidate
-> run quality gates
-> commit local candidate ref
-> serve baseline and candidate
-> compare in browser
-> assert no remote/live mutation
```

The external-model OceanicVibes run is an opt-in smoke/evaluation run. It cannot
replace deterministic acceptance tests.

## Verification Commands

The coding AI must keep these exact classes of verification separate:

```bash
# Python unit and integration tests
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider

# Frontend compiler/scaffold tests
npm ci
npm run check
npm run test
npm run build

# Explicit browser setup and tests; never download browsers in the unit suite
npx playwright install chromium
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider tests/browser

# Package smoke
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
git diff --check
```

Use the actual frontend working directory once Phase 1 establishes it. Do not
run npm commands in customer repositories during normal Python unit tests.

## Definition of Done

The web design creation system is complete only when all statements are true:

- Ada produces a validated design specification, not arbitrary repository code.
- The deterministic compiler emits a standard Astro/React site.
- The pinned site compiles to complete static output locally.
- Required facts are present and unsupported claims are absent.
- Every required route works on desktop, tablet, and mobile.
- Required browser and accessibility evidence passes.
- The candidate, manifests, reports, and screenshots are bound to immutable
  identities.
- A single local command generates and retains a candidate.
- A local comparison shows baseline and candidate without cloud services.
- Success and failure both prove remote refs and live paths were unchanged.
- A real OceanicVibes candidate has been generated and reviewed locally.
- Production integration remains disabled until explicitly implemented and
  approved after the POC.

## Instructions to the Coding AI

- Start each phase with focused failing tests.
- Complete and verify one phase before starting the next.
- Prefer deletion or correction of unshipped partial behavior over compatibility
  shims.
- Preserve existing production Pelican, chat-job, review, and approval behavior
  until Phase 7 explicitly changes it.
- Keep generic policy free of OceanicVibes-specific pages and file patterns.
- Never report a fake-adapter test as end-to-end proof.
- Never report `incomplete` quality evidence as passing.
- Never use Cloudflare or a real Git remote to test design creation.
- Update this document's implementation log with completed tests, decisions, and
  exact run identities as work proceeds.

## Implementation Log

Leave empty until coding begins. For each phase record:

- starting commit and branch;
- pre-existing working-tree changes;
- tests added first;
- files changed;
- focused and full verification results;
- unresolved deviations;
- for POC runs: run ID, baseline SHA, candidate SHA, compiler version, model ID,
  manifest hashes, report hash, screenshot hashes, and immutability result.
