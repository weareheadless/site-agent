# Design Engine Pipeline Implementation Plan

> **Superseded on 2026-08-31.** Do not implement further phases from this
> document. The authoritative corrective plan is
> `docs/canonical-opencode-design-test-implementation-plan.md`, which reuses the
> production `DesignService -> NativeOpenCodeBuilder -> OpenCode` path and
> rejects the parallel visual-scaffold test.

**Status:** Proposed; no implementation has started

**Date:** 2026-08-30

**Purpose:** Define a safe, repeatable design engine that turns customer intake
JSON into a strong initial homepage, turns the approved homepage into a durable
design contract for later non-Pelican pages, and supports a local-only
OceanicVibes redesign experiment without changing its live site or remote
preview branch.

This document is an implementation contract for a coding AI. It is intentionally
specific about boundaries, sequencing, tests, and failure behavior. Do not skip
phases or combine the experiment path with the production approval path.

## How To Use This Plan

- Implement phases in order.
- Begin every phase with the focused failing tests listed for that phase.
- Keep existing public API paths stable unless this plan explicitly adds a new
  path.
- Keep production mutation behind the existing explicit owner approval flow.
- Treat all LLM and vision output as untrusted input that must validate against
  typed contracts.
- Do not make the design model responsible for deciding whether its own output
  is technically valid.
- Do not test the new pipeline by pushing to the OceanicVibes repository.
- Do not use `origin/preview` for the OceanicVibes experiment.
- Do not write experiment records into the live OceanicVibes SQLite database.
- Record architecture decisions and deviations in the Decision Log at the end
  of this file.
- Mark a phase complete only after its acceptance criteria and focused tests
  pass.

## Scope

### In scope

- A versioned customer intake JSON contract.
- Deterministic normalization of intake into a design brief.
- An initial-homepage design pipeline.
- A durable, versioned design manifest derived from and verified against the
  initial homepage.
- A page-intake pipeline for later non-Pelican pages that inherits the approved
  homepage design.
- Structured planning, design direction, implementation, validation, visual
  critique, and bounded repair stages.
- Immutable build inputs and outputs identified by Git commit SHA.
- Local-only design experiments with read-only before/after comparison.
- An OceanicVibes proof-of-concept run using sanitized checked-in intake and a
  separate local experiment clone.
- Framework-neutral contracts that work with the current static/Pelican site
  and a future component-based frontend.

### Out of scope

- Migrating the site frontend to React, Astro, Next.js, or another framework.
- Replacing Pelican or redesigning the Pelican journal pipeline.
- Publishing the OceanicVibes experiment.
- Automatically selecting a winning design based only on an LLM score.
- Multi-tenant runtime architecture.
- A universal plugin system.
- A general visual page builder for owners.
- Automatic production rollout after quality checks.

## Product Goal

A nontechnical owner should provide business facts and preferences once during
intake. Ada should then produce a complete first design that is:

- technically valid;
- responsive and accessible;
- grounded in the actual business and audience;
- conversion-aware without inventing claims;
- visually coherent across pages;
- recognizably original rather than a generic industry template;
- reviewable without exposing Git, branches, build systems, or JSON to the
  owner;
- harmless to production until the owner explicitly approves it.

The pipeline cannot guarantee commercial success. It must guarantee that known
technical failures do not reach owner review as successful work, and it must
make design reasoning and quality evidence inspectable.

## Current Baseline

The implementation must preserve these existing behaviors:

- `site_agent.site_scaffold.initialize_site()` creates the current Pelican
  scaffold from `site-agent init-site`.
- Broad requests route through `brain/editor.py` to
  `hands/opencode_runner.stage_build()`.
- Builder work occurs in a disposable detached Git worktree.
- A successful broad build currently pushes to the hard-coded remote `preview`
  branch.
- A successful build creates a pending `merge` draft.
- The Design/Review iframe serves generated staged output under
  `/api/review/{draft_id}/{file_path}`.
- Preview HTML and CSS assets remain valid under the `/ada/` mount point.
- Production changes only through an authenticated explicit approval.
- Declining a merge draft can reset the shared preview branch.
- Chat jobs remain durable and inspectable by ID after completion.

Relevant current code:

- `src/site_agent/site_scaffold.py`
- `src/site_agent/brain/planner.py`
- `src/site_agent/brain/editor.py`
- `src/site_agent/core/chat_jobs.py`
- `src/site_agent/hands/builder.py`
- `src/site_agent/hands/opencode_runner.py`
- `src/site_agent/hands/site_digest.py`
- `src/site_agent/hands/template_tokens.py`
- `src/site_agent/web/preview.py`
- `src/site_agent/web/server.py`
- `src/site_agent/web/static/admin.html`
- `src/site_agent/application/approvals.py`
- `src/site_agent/core/contracts.py`
- `src/site_agent/core/memory.py`

Current tests that define compatibility behavior:

- `tests/test_site_scaffold.py`
- `tests/test_builder.py`
- `tests/test_editor_tools.py`
- `tests/test_preview.py`
- `tests/test_web.py`
- `tests/test_contracts.py`
- `tests/test_memory.py`

## Problems To Solve

### 1. Intake is not a design contract

`init-site` currently accepts only a name, URL, and directory. The example
configuration contains useful persona, audience, goals, and service data, but
there is no complete or versioned design-intake schema.

### 2. The initial homepage is not an explicit pipeline stage

The scaffold says it is ready for a design pass, but provisioning does not
create a durable design run, implementation brief, quality report, or design
manifest.

### 3. Later-page consistency is prompt-only

`template_tokens.py` extracts a small text summary from source CSS and
`site_digest.py` summarizes source files. They do not provide a complete,
typed, rendered design contract. They are cached against `origin/main`, even
when a follow-up build starts from unapproved preview work.

### 4. Review is tied to a mutable branch

Merge drafts record `head: preview`, not the immutable commit that was reviewed.
The review endpoint reads `origin/preview`, and approval merges the current
preview branch. A later force-push can change what a pending draft represents.

### 5. General page validation is too weak

The host validates writable paths and has special OceanicVibes journal checks,
but general page builds do not receive systematic build, browser, responsive,
accessibility, console, network, or visual-composition validation.

### 6. The current POC cannot be safely compared in place

The broad builder always pushes to the shared remote preview branch. That is
not acceptable for a design experiment on a live customer site.

## Target Pipeline

```text
Customer intake JSON
  -> schema validation and normalization
  -> completeness/contradiction report
  -> site strategy brief
  -> multiple lightweight art-direction hypotheses
  -> Ada selects and justifies one direction
  -> inner-voice challenge and revision
  -> typed initial-homepage build request
  -> isolated candidate worktree at an immutable base SHA
  -> implementation agent
  -> deterministic build and static checks
  -> browser checks at required viewports
  -> screenshot-based visual critique
  -> bounded repair loop
  -> immutable candidate commit SHA
  -> design manifest extraction and conformance check
  -> Review iframe with evidence
  -> explicit owner approval for production-capable runs only
```

Later non-Pelican pages use this reduced pipeline:

```text
Page intake JSON
  + approved site intake
  + approved design manifest and source SHA
  -> page strategy and content hierarchy
  -> typed page build request
  -> implementation from the approved design source
  -> deterministic and visual validation
  -> immutable candidate SHA
  -> Review iframe
  -> explicit owner approval
```

## Core Design Principles

### Separate facts, decisions, and implementation

- **Intake** stores customer facts, goals, constraints, assets, and preferences.
- **Design brief** records Ada's normalized interpretation.
- **Art direction** records the chosen creative thesis and rejected alternatives.
- **Design manifest** records the implemented design system and shared page
  contract.
- **Build request** tells the implementation agent exactly what to create and
  which source revision to inherit.
- **Quality report** records objective and visual evidence.
- **Candidate receipt** records the immutable implementation result.

Never collapse these into one free-form prompt.

### Prefer constrained creativity over unrestricted regeneration

The pipeline should constrain safety properties and shared identity, not dictate
one visual template. Ada may vary composition, typography, image treatment,
surface language, rhythm, and one subject-specific signature gesture. Later
pages must inherit the shell and design grammar while allowing page-specific
composition.

### Review immutable work

Every reviewable candidate must resolve to an exact commit SHA. Page listing,
iframe rendering, quality evidence, and approval must all reference that SHA.

### Fail closed

- Invalid intake does not start a design run.
- Invalid structured model output does not reach the builder.
- A failed build or quality gate does not create a publishable approval.
- A visual critic failure is reported as unavailable evidence, not a passing
  result.
- An experiment cannot become publishable by changing a request parameter.

## Proposed Contracts

Add a narrow design-contract module rather than placing unstructured dictionaries
throughout the runner. Suggested location:

- `src/site_agent/core/design_contracts.py`

Use frozen dataclasses or equivalently strict typed objects with explicit
`from_dict()` validation and `to_dict()` serialization. Reuse payload-size and
redaction helpers from `core/contracts.py` where appropriate.

### `SiteIntake`

Required fields:

- `schema_version`
- `business.name`
- `business.offer_summary`
- `business.primary_services`
- `audience.primary`
- `conversion.primary_action`
- `conversion.contact_destination` or an explicit `not_available` state
- `brand.voice`
- `site.required_pages`

Optional fields:

- business location and service area;
- differentiators;
- verified trust evidence;
- prohibited or unverified claims;
- secondary audiences;
- secondary conversions;
- existing brand colors, fonts, and logo;
- visual preferences and dislikes;
- example sites with a reason for each preference;
- supplied assets by durable media asset ID;
- legal or accessibility constraints;
- SEO markets and languages;
- existing URLs that must remain stable;
- content facts and source provenance.

Validation rules:

- Reject unknown schema versions.
- Reject strings over documented limits.
- Reject URLs with unsupported schemes.
- Separate verified facts from preferences.
- Require provenance labels for testimonials, certifications, statistics, and
  other trust claims.
- Do not infer a claim merely because it appears in persona prose.
- Preserve explicit unknown values instead of replacing them with invented
  defaults.
- Normalize page identifiers and language codes deterministically.

### `IntakeAssessment`

Fields:

- `complete_enough`
- `blocking_questions`
- `non_blocking_unknowns`
- `contradictions`
- `safe_defaults_applied`
- `warnings`

The normal owner experience may ask at most one blocking follow-up at a time.
Non-blocking unknowns must use safe defaults and appear in the internal report.

### `DesignBrief`

Fields:

- intake hash and schema version;
- business objective;
- audience intent and anxieties;
- primary conversion;
- required information hierarchy;
- trust strategy using only verified evidence;
- content requirements;
- visual objectives;
- constraints and prohibited claims;
- required pages;
- supplied assets and intended roles;
- success hypotheses;
- unresolved non-blocking unknowns.

### `ArtDirection`

Fields:

- `name`
- `thesis`
- `business_relevance`
- `composition_strategy`
- `typography_strategy`
- `color_and_material_strategy`
- `image_strategy`
- `motion_strategy`
- `signature_gesture`
- `mobile_translation`
- `reduced_motion_translation`
- `conversion_strategy`
- `template_risk`
- `implementation_risks`

Generate two or three inexpensive textual hypotheses. Ada selects one using the
business brief and explains why the others were rejected. Do not implement
multiple websites during normal provisioning.

### `DesignManifest`

The manifest is the durable contract inherited by later pages. It should be
stored in the site repository at a configurable path such as
`design/ada-design-manifest.json`, and its content hash should also be persisted
with the design run.

Fields:

- schema version;
- source homepage path;
- design direction ID and intake hash;
- brand voice summary;
- color roles and contrast intent;
- typography families, roles, scale, line heights, and measure;
- spacing and section-rhythm scale;
- container widths and gutters;
- breakpoints;
- border, radius, shadow, and surface rules;
- shared header, navigation, footer, and CTA behavior;
- fixed/sticky chrome safe offsets;
- image aspect ratios, cropping rules, and treatments;
- motion principles and reduced-motion behavior;
- reusable region/component inventory;
- page-shell requirements;
- accessibility invariants;
- allowed variation points;
- prohibited drift;
- signature gesture and where it may or may not repeat;
- source files implementing each shared rule.

Do not put the candidate commit SHA inside the committed manifest. That creates
a circular identity problem because adding the SHA changes the commit. Persist
an external immutable binding in the design run and candidate receipt:

```text
DesignSourceBinding = candidate SHA + manifest path + manifest content hash
```

Derived pages must pin and verify all three values.

The manifest is not trusted merely because the implementation agent wrote it.
The host must compare declared values with rendered/computed evidence and reject
material contradictions.

### `PageIntake`

Required fields:

- schema version;
- page identifier and desired URL;
- page purpose;
- primary audience intent;
- primary action;
- required facts/content;
- relationship to existing navigation.

Optional fields:

- secondary action;
- supplied media IDs;
- page-specific references;
- page-specific constraints;
- SEO title/description intent;
- content that must not be changed.

Site-level brand, audience, business, and design questions are inherited from
`SiteIntake` and `DesignManifest`; they are not asked again.

### `PageBuildRequest`

Fields:

- run ID and mode (`initial_homepage` or `derived_page`);
- immutable base SHA;
- site intake hash;
- design manifest hash and source SHA for derived pages;
- target page path;
- page strategy and content hierarchy;
- required shared shell regions;
- allowed variation points;
- required and prohibited files;
- supplied media paths;
- acceptance criteria;
- required viewports;
- quality-gate policy;
- mutation target.

### `BuildTarget`

Fields:

- `mode`: `production_candidate` or `local_experiment`;
- repository identity;
- clone path;
- immutable base SHA;
- candidate ref namespace;
- `push_mode`: `shared_preview`, `isolated_remote_ref`, or `none`;
- `publishable`: boolean fixed at construction;
- optional remote destination;
- allowed path patterns.

Rules:

- `local_experiment` requires `push_mode: none` and `publishable: false`.
- The process environment for `local_experiment` must not contain GitHub or
  production adapter credentials.
- A local experiment may commit to a local namespaced ref in its own clone.
- No code path may promote an experiment by mutating `publishable`.
- Promotion, if implemented later, must create a new production candidate and a
  new approval from an explicitly selected experiment SHA.

### `QualityReport`

Fields:

- run and candidate SHA;
- build command and result;
- changed-path validation;
- generated-page inventory;
- HTML and metadata checks;
- browser console errors;
- failed network requests;
- broken internal links;
- overflow and clipping findings;
- accessibility findings grouped by severity;
- viewport screenshot artifacts;
- performance budget results when available;
- design-manifest conformance;
- visual critique findings;
- factual/content warnings;
- repair attempts;
- final state: `passed`, `failed`, or `incomplete`.

### `DesignCandidateReceipt`

Fields:

- run ID;
- base SHA;
- candidate SHA;
- local or remote ref;
- diff summary;
- changed paths;
- manifest path and hash;
- quality report ID/hash;
- preview page inventory;
- publishable flag;
- timestamps and tool/model identifiers.

## Persistence Model

Prefer explicit design-run persistence over storing the entire pipeline in chat
messages or KV blobs.

Add migrations in `core/memory.py` only after checking the latest existing
migration number. Do not reuse or reorder existing migrations.

Suggested tables:

### `design_runs`

- `id`
- `mode`
- `status`
- `intake_json`
- `intake_hash`
- `base_sha`
- `candidate_sha`
- `candidate_ref`
- `publishable`
- `design_manifest_json`
- `design_manifest_hash`
- `quality_report_json`
- `error`
- `created_ts`
- `updated_ts`

Statuses:

```text
created
-> assessing_intake
-> planning
-> building
-> validating
-> repairing
-> ready_for_review | failed | cancelled
```

Production-capable runs may subsequently link to a pending draft/approval. The
design run itself does not publish.

### `design_run_events`

- durable ordered progress entries;
- stage name;
- concise owner-safe message;
- technical detail kept separate and redacted;
- timestamp.

### Persistence rules

- Store immutable snapshots of intake, manifest, and reports.
- Compute hashes from canonical JSON serialization.
- Never store model API keys, Git tokens, cookies, or complete child-process
  environments.
- Include run, job, draft, candidate SHA, and provider IDs in diagnostics.
- A completed or failed run remains inspectable by ID.
- Experiment data uses a separate database/data directory from the live
  OceanicVibes instance.

## Application Boundaries

Add an application workflow service, suggested location:

- `src/site_agent/application/designs.py`

Responsibilities:

- accept typed intake;
- assess completeness;
- create and transition durable design runs;
- call planning and art-direction policies;
- call a builder through a typed capability;
- call deterministic and visual quality adapters;
- coordinate bounded repair;
- create a pending website draft only for publishable candidates;
- expose read models for Review and diagnostics.

It must not:

- call FastAPI route functions;
- use `Memory.conn` directly;
- run Git commands directly;
- know GitHub API details;
- publish production;
- treat an LLM pass/fail statement as objective validation.

## Builder Boundary Refactor

Keep `hands/builder.py` as the supported builder seam. Introduce a typed method
without immediately deleting the compatibility `build(brief)` method.

Target capability:

```python
class DesignBuilder(Protocol):
    def build_design(
        self,
        request: PageBuildRequest,
        target: BuildTarget,
        progress: Callable[[str], None] | None = None,
    ) -> DesignCandidateReceipt:
        ...
```

Implementation guidance:

- Extract worktree preparation, agent execution, validation, commit, and target
  finalization from `opencode_runner.py` in behavior-preserving steps.
- Resolve the base ref to a full commit SHA before creating the worktree.
- Pass the typed request to the builder as canonical JSON plus concise execution
  instructions; do not reconstruct critical constraints from owner prose.
- Keep Ada as creative lead, but make the host own paths, target mode, quality
  policy, and publication capability.
- Return the exact candidate SHA.
- Store local experiments under `refs/ada-design-lab/{run_id}` in the experiment
  clone.
- Preserve current shared-preview behavior behind the compatibility path until
  production candidates migrate to immutable draft refs.

## Design Planning Policy

Add focused policy modules under `brain/`, suggested names:

- `brain/design_brief.py`
- `brain/art_direction.py`
- `brain/page_strategy.py`
- `brain/design_critic.py`

Do not put this workflow into route handlers.

### Initial homepage planning

1. Compile customer facts into `DesignBrief`.
2. Generate two or three short art-direction hypotheses.
3. Rank hypotheses against business relevance, audience fit, trust, conversion,
   implementation risk, and template risk.
4. Select one direction.
5. Run the existing inner-voice challenge against the selected direction and
   homepage strategy.
6. Revise once when concrete criticism exists.
7. Produce a `PageBuildRequest` with one signature gesture tied to the subject.

### Creativity rules

- Do not select a direction merely because it matches the customer's industry.
- Explain how the direction connects to this customer's offer, audience, place,
  materials, process, or point of view.
- Avoid default SaaS/dashboard/card-grid composition unless the business brief
  specifically supports it.
- Require a meaningful mobile translation rather than shrinking desktop.
- Treat supplied media as compositional material, not decoration.
- Define one signature gesture; do not repeat it on every section or later page.
- Track rejected directions to reduce accidental convergence on the first idea.
- Never invent trust evidence or business facts to improve the design.

### Derived-page planning

1. Load the approved `SiteIntake` and exact approved `DesignManifest`.
2. Resolve the manifest's external `DesignSourceBinding` and fail if its source
   commit or manifest hash is unavailable.
3. Determine the new page's unique purpose and information hierarchy.
4. Reuse shared navigation, footer, typography, spacing, CTA, and accessibility
   invariants.
5. Select only the manifest's allowed variation points.
6. Decide whether the signature gesture should be absent, echoed subtly, or
   adapted; never duplicate it automatically.
7. Produce a page-specific build request and quality criteria.

## Design Manifest Extraction

Replace regex-only design inheritance with a two-source manifest process:

### Declared source

The implementation agent writes the manifest in the candidate worktree. This
captures design intent, semantic roles, variation rules, and source-file links.

### Measured source

A host-owned extractor builds the candidate and measures rendered pages in a
real browser:

- computed typography;
- resolved colors;
- container and gutter geometry;
- section spacing;
- header position and safe offset;
- breakpoint behavior;
- shared shell presence;
- focus styles;
- image dimensions and object-fit behavior;
- motion and reduced-motion behavior where observable.

### Conformance

- Reject missing required manifest fields.
- Reject source paths that do not exist at the candidate SHA.
- Reject materially false declarations.
- Allow tolerances for responsive fluid values.
- Record warnings for properties that cannot be measured reliably.
- Hash the final declared manifest and attach measured evidence to the quality
  report rather than rewriting the design intent silently.

Keep `site_digest.py` and `template_tokens.py` as compatibility inputs during
migration. Add explicit `ref`/SHA-aware cache keys before using them in the new
pipeline. Never serve a cached `origin/main` design reference to a build based
on another SHA.

## Quality Pipeline

Quality checks run in a host-owned sequence after the implementation agent
finishes and before a candidate becomes ready for review.

### Gate A: Repository safety

- Resolve changed paths against the configured allowlist.
- Apply hard-deny rules.
- Reject symlinks escaping the worktree.
- Reject secrets and credential-like content.
- Reject changes to deployment, CI, and package-management files unless the
  typed request explicitly permits them and the target policy allows them.
- Verify the persistent clone working tree was not modified.

### Gate B: Build integrity

- Run the configured build command with a timeout.
- Capture stdout/stderr with redaction and size limits.
- Verify an output directory exists.
- Verify required pages and assets exist.
- Reject leaked source templates, config files, and credentials.
- Verify all generated paths remain inside the output root.

### Gate C: Document integrity

- Validate one H1 per primary page unless an explicit exception exists.
- Validate title, description, canonical intent, language, and viewport metadata.
- Validate landmark and heading order.
- Validate local navigation targets.
- Validate required CTA and contact destinations from intake.
- Validate image alt behavior and dimensions.
- Detect placeholder text and implementation notes.
- Detect claims absent from verified intake facts.

### Gate D: Browser integrity

Use a host-controlled browser adapter, preferably Playwright/Chromium behind a
narrow contract so tests can use a fake.

Required default viewports:

- desktop: 1440 x 1000;
- tablet: 768 x 1024;
- mobile: 390 x 844.

Checks:

- uncaught page errors;
- console errors;
- failed same-site network requests;
- horizontal overflow;
- clipped or hidden primary content;
- overlapping fixed chrome;
- inaccessible focus order;
- keyboard operation for navigation and interactive controls;
- reduced-motion mode;
- forms' empty, invalid, success, and error states where testable;
- layout stability after fonts and images load.

### Gate E: Accessibility

- Run automated WCAG checks.
- Treat critical/serious findings as blockers.
- Treat moderate/minor findings according to configured policy.
- Require visible focus states.
- Require keyboard-operable navigation.
- Require contrast evidence for text over imagery.
- Do not consider an automated zero-finding report a complete accessibility
  guarantee; preserve manual-risk notes.

### Gate F: Visual critique

Provide screenshots, intake facts, art direction, and design manifest to the
vision critic. Require structured findings, not a single score.

Evaluate:

- hierarchy and first-viewport clarity;
- business and audience relevance;
- primary action clarity;
- trust placement;
- typography and legibility;
- image quality and cropping;
- spacing and visual rhythm;
- mobile intentionality;
- consistency with the chosen direction;
- generic-template signals;
- originality of the signature gesture;
- decorative excess that harms conversion or readability.

The critic may fail a candidate only through documented findings with severity
and screenshot/viewport references. A numeric aesthetic score alone is not a
blocker.

### Gate G: Design inheritance for later pages

- Compare the page against the pinned design manifest.
- Verify shared shell regions and source components.
- Verify token and typography roles.
- Verify safe offsets and responsive gutters.
- Verify allowed variation points were respected.
- Reject unapproved global design-system changes in a page-only run.

## Repair Policy

- Maximum two automated repair turns by default.
- Repair receives only concrete failed checks and relevant artifacts.
- Continue the same implementation session when possible.
- Re-run all gates after every repair, not only the previously failing gate.
- Stop when the candidate state no longer changes.
- Stop immediately for credential exposure, path escape, target-policy breach,
  or an unavailable immutable base SHA.
- Preserve every attempt in run events and the final report.
- If repair is exhausted, mark the run failed and do not create a publishable
  draft.

## Immutable Review And Approval

The production path must eventually stop reviewing mutable `origin/preview`.

### Draft metadata

For new design candidates, store:

- exact base SHA;
- exact candidate SHA;
- candidate ref;
- design run ID;
- manifest hash;
- quality report hash;
- publishable flag.

### Review behavior

- `/api/pages?draft_id=...` resolves the draft candidate SHA.
- `/api/review/{draft_id}/{file_path}` builds and serves the draft candidate SHA.
- The preview cache key includes candidate SHA and overlay hash.
- The iframe remains sandboxed and mount-safe under `/ada/`.
- The UI displays quality status in owner language and keeps technical evidence
  under progressive disclosure.

### Approval behavior

- Approval verifies the candidate SHA is unchanged and still descends from the
  recorded base according to the merge policy.
- Approval merges the exact reviewed candidate, not the current tip of a shared
  branch.
- A stale or unavailable SHA returns a conflict and requires a new candidate.
- Local experiments have no approval action.
- Existing legacy merge drafts remain supported during migration.

## Local Design Experiment Architecture

Add a read-only experiment mode before changing production broad-build behavior.
Suggested application entry point:

- `DesignService.create_experiment(site_intake, source, policy)`

Suggested CLI adapter:

```text
site-agent design-experiment \
  --config examples/oceanicvibes.config.yaml \
  --intake examples/oceanicvibes.intake.json \
  --data-dir /tmp/site-agent-design-lab/oceanicvibes
```

Exact CLI spelling may change, but these guarantees may not:

- Create or reuse a dedicated experiment clone outside the live instance clone.
- Fetch only enough to resolve the published branch SHA.
- Record the baseline as an immutable SHA.
- Remove GitHub and production adapter credentials from the builder environment.
- Use `BuildTarget(mode="local_experiment", push_mode="none",
  publishable=False)`.
- Commit the candidate only to `refs/ada-design-lab/{run_id}` in the experiment
  clone.
- Use a separate SQLite database and preview cache.
- Never invoke `SiteAdapter.commit_file()`, `MergeAdapter.merge_preview()`, or a
  Git push.
- Never create a pending production draft.
- Never reset or fetch-update the live instance's preview branch.
- Preserve the baseline and candidate long enough for local comparison.

## OceanicVibes POC Experiment

The first end-to-end experiment validates the design engine, not a production
deployment.

### Inputs

Create a sanitized checked-in fixture:

- `examples/oceanicvibes.intake.json`

The checked-in OceanicVibes config is an example, not a runnable design-lab
configuration: it does not configure a clone path or enabled builder, and some
provider values are placeholders. Build a separate experiment overlay at run
time that supplies only the dedicated experiment clone/data paths and model
credentials. Do not edit the checked-in example or hydrate it with production
mutation credentials.

Populate it only from facts already present in:

- `examples/oceanicvibes.config.yaml`;
- the published repository at the pinned baseline SHA;
- explicitly supplied customer assets and facts.

Do not turn persona imagery into factual customer claims. Preserve the existing
statements that Ada has studied the region but has no physical experience.

The fixture should include:

- business/site name;
- freediving and ocean-curious audience;
- Playa del Carmen and Bacalar focus;
- qualified training-enquiry goal;
- listed priority services;
- safety and environmental voice constraints;
- existing fonts as current-brand evidence, not mandatory future choices;
- required homepage and navigation intent inferred only from published pages;
- source/provenance labels;
- explicit unknowns for missing contact, certification, pricing, schedules, and
  testimonials.

### Baseline capture

1. Clone the public OceanicVibes repository into the experiment data directory.
2. Resolve `origin/main` to a full SHA and store it in the design run.
3. Run the existing build command in an isolated checkout.
4. Capture baseline page inventory and homepage screenshots at all required
   viewports.
5. Capture baseline quality findings without modifying the source.
6. Record the remote refs before the experiment.

### Candidate generation

1. Start from the immutable baseline SHA in a disposable worktree.
2. Run the full initial-homepage pipeline from the sanitized intake.
3. Permit homepage and shared-design files according to an experiment-specific
   allowlist.
4. Keep journal article content out of scope.
5. Build and validate the complete generated site so the homepage redesign does
   not break journal routes or existing required pages.
6. Commit locally and record the candidate SHA.
7. Create the design manifest and quality report.

### Comparison surface

Add a read-only comparison mode to the existing Review area rather than
returning raw public preview links.

It should provide:

- baseline/candidate toggle;
- optional synchronized side-by-side iframe view on desktop;
- page selector;
- desktop/tablet/mobile viewport selector;
- baseline and candidate screenshot pairs;
- concise summary of the selected art direction;
- changed page/file summary under `More details`;
- quality findings grouped into blockers, warnings, and passed checks;
- no publish, approve, merge, or promote button.

The iframe routes should resolve run-owned SHAs, for example:

```text
GET /api/design-runs/{run_id}/pages?variant=baseline|candidate
GET /api/design-runs/{run_id}/preview/{variant}/{file_path}
GET /api/design-runs/{run_id}/report
```

Require normal admin authentication and the same short-lived preview capability
model used by current review routes. Reuse `web/preview.py`; do not duplicate URL
rewriting logic.

### Safety verification after the run

- Compare remote refs before and after; they must be identical.
- Assert no `git push` command was invoked.
- Assert no production adapter mutation method was invoked.
- Assert the live config and live data directory were not written.
- Assert the live clone worktree and refs were not changed.
- Assert `https://oceanicvibes.com/` was not used as a test mutation target.
- Optionally run a read-only production smoke check after the experiment and
  record status without treating it as evidence that mutation safety passed.

### POC evaluation questions

- Did the pipeline produce a complete candidate without owner iteration?
- Did it preserve every verified business fact and avoid invented claims?
- Is the primary enquiry action clearer than the baseline?
- Is the visual direction relevant to freediving and the locations without
  becoming a generic blue travel template?
- Is mobile composition intentional?
- Does the design manifest accurately represent the candidate?
- Can a second test page inherit the candidate design without global drift?
- Did every safety assertion prove zero remote mutation?

The POC is successful only if technical and safety acceptance criteria pass.
Visual preference is recorded separately and must not override a safety failure.

## Implementation Phases

### Phase 0: Record Baseline And Protect The Live POC

Tasks:

- Record current branch, worktree status, test count, and latest migration in
  this plan's implementation log when coding begins.
- Identify the real OceanicVibes live instance paths without copying secrets
  into tests or documentation.
- Add an automated test fixture representing a forbidden live clone/data path.
- Define the experiment root outside both the repository and live instance.
- Add a command-level guard refusing an experiment data directory equal to or
  inside the configured live data directory or live clone.
- Add a guard refusing `local_experiment` with any push mode other than `none`.

Focused tests:

- experiment rejects the live clone path;
- experiment rejects the live data directory;
- experiment rejects `push_mode=shared_preview`;
- experiment environment omits GitHub token variables;
- experiment command does not require a GitHub token.

Acceptance criteria:

- A local experiment cannot be configured to write into the live instance.
- Safety errors occur before an LLM call or worktree mutation.

### Phase 1: Typed Intake And Design Contracts

Tasks:

- Add `core/design_contracts.py`.
- Implement canonical JSON hashing and bounded serialization.
- Implement `SiteIntake`, `IntakeAssessment`, `DesignBrief`, `ArtDirection`,
  `DesignManifest`, `PageIntake`, `PageBuildRequest`, `BuildTarget`,
  `QualityReport`, and `DesignCandidateReceipt`.
- Add sanitized JSON fixtures for valid, incomplete, contradictory, oversized,
  and malicious intake.
- Add `examples/oceanicvibes.intake.json` only after provenance review.

Focused tests:

- valid round trips preserve canonical values;
- unknown schema versions fail;
- oversized fields fail;
- unsupported URL schemes fail;
- unverified trust claims remain unverified;
- canonical hashes are stable across key order;
- local experiment target invariants cannot be bypassed during deserialization.

Acceptance criteria:

- No pipeline stage accepts an undocumented dictionary.
- Invalid intake cannot create a design run.

### Phase 2: Durable Design Runs

Tasks:

- Add append-only migrations for design runs/events.
- Add `Memory` methods; application services must not access `Memory.conn`.
- Implement guarded state transitions.
- Persist errors, hashes, immutable SHAs, and safe progress events.
- Add `application/designs.py` with create/get/list/cancel read workflows.

Focused tests:

- migration from a pre-design database;
- state transition matrix;
- completed and failed runs remain inspectable;
- secrets and large payloads are redacted/bounded;
- experiment and production run modes remain distinguishable.

Acceptance criteria:

- Restarting the service does not erase run state.
- Run identity is independent from chat job and draft identity.

### Phase 3: Ref-Aware Build Target

Tasks:

- Add the typed builder capability to `hands/builder.py`.
- Extract base-SHA resolution and target finalization from
  `opencode_runner.py` without changing legacy behavior.
- Add local candidate refs.
- Return exact candidate SHAs.
- Make `site_digest` and `template_tokens` accept and cache by explicit SHA.
- Add a no-push target finalizer.
- Keep compatibility `stage_build()` tests green.

Focused tests:

- worktree starts from the exact supplied SHA;
- missing SHA fails rather than falling back silently in the new path;
- local target creates a local ref and never pushes;
- persistent clone worktree remains untouched;
- ref-aware digest/token caches do not return `origin/main` data for another SHA;
- legacy shared preview builds retain existing behavior.

Acceptance criteria:

- The new design builder can produce a durable local candidate without a remote
  branch.
- Existing chat builds still work until migrated deliberately.

### Phase 4: Intake Assessment And Design Planning

Tasks:

- Implement deterministic intake completeness and contradiction checks.
- Implement structured design-brief generation.
- Implement art-direction hypothesis generation and selection.
- Integrate the existing inner-voice challenge/revision pass.
- Produce typed initial and derived page build requests.
- Store all structured planning outputs with the run.

Focused tests:

- blocking facts produce one owner question;
- non-blocking unknowns use documented defaults;
- model output missing fields is rejected or retried;
- selected art direction references customer facts;
- unsupported claims do not enter the build request;
- derived-page requests pin a manifest hash and SHA;
- planner failures mark the run failed rather than passing raw prose to the new
  builder path.

Acceptance criteria:

- The implementation agent receives a complete typed request.
- The design direction is inspectable and customer-specific.

### Phase 5: Generic Host-Owned Quality Gates

Tasks:

- Extract generic build validation from special journal logic.
- Add document and generated-output validators.
- Add a browser quality adapter with a fake for unit tests.
- Add accessibility checks.
- Add screenshot artifact storage outside the Git repository.
- Add design-manifest declared/measured conformance.
- Implement bounded repairs through the existing OpenCode session continuation.

Focused tests:

- failed build blocks readiness;
- missing output page blocks readiness;
- path escape and leaked source block readiness;
- console errors and failed local assets block readiness;
- overflow at mobile blocks readiness;
- serious accessibility findings block readiness;
- unavailable visual critic yields `incomplete`, not `passed`;
- repair reruns every gate;
- unchanged failed candidate stops repair;
- screenshots and reports are not committed to the customer repository.

Acceptance criteria:

- A design run cannot become ready while a blocking gate fails.
- Every ready candidate has reproducible evidence at required viewports.

### Phase 6: Design Manifest And Derived Page Inheritance

Tasks:

- Validate and persist the initial homepage design manifest.
- Add a generic design-source resolver by SHA and manifest hash.
- Implement derived-page conformance checks.
- Prevent page-only runs from editing shared design files unless the request is
  explicitly reclassified as a site-wide design evolution.
- Add one synthetic second-page POC after the homepage candidate passes.

Focused tests:

- missing or false manifest fails;
- stale manifest hash fails;
- shared header/footer drift fails;
- allowed page composition variation passes;
- fixed-header safe offsets are measured and enforced;
- a second page inherits typography, gutters, CTA, and responsive behavior;
- the initial signature gesture is not duplicated by default.

Acceptance criteria:

- New pages are visually related to the approved homepage without being clones.
- Site-wide design changes require a site-wide run, not an incidental page build.

### Phase 7: Read-Only Comparison In Review

Tasks:

- Add authenticated design-run read endpoints.
- Serve baseline/candidate files by immutable SHA through `PreviewBuildCache`.
- Reuse preview token, CSP, sandbox, HTML rewrite, and CSS rewrite behavior.
- Add a read-only comparison mode to the Review UI.
- Keep current draft review unchanged.
- Hide technical detail by default.

Focused tests:

- run preview requires auth/capability;
- run can serve nested CSS, fonts, images, and scripts under `/ada/`;
- baseline and candidate routes resolve different exact SHAs;
- page inventory includes generated output;
- local experiment response exposes no approval action;
- comparison UI works at desktop and mobile admin widths;
- expired preview tokens fail;
- candidate files cannot traverse outside generated output.

Acceptance criteria:

- A nontechnical owner can compare the current and candidate homepages without
  seeing branches or raw URLs.
- No comparison control can publish an experiment.

### Phase 8: OceanicVibes Local POC

Tasks:

- Review the sanitized intake fixture with the checked-in config.
- Create a separate experiment data directory and clone.
- Record remote refs and baseline SHA.
- Run baseline capture.
- Run initial-homepage design generation.
- Run all quality gates and bounded repair.
- Generate the design manifest.
- Generate one derived non-Pelican test page to test inheritance; do not include
  it in any remote branch.
- Review the before/after comparison locally.
- Record quality and design findings in a POC report under `docs/` without
  committing screenshots or generated candidate files.
- Verify remote and live-instance immutability after the run.

Focused verification:

- `git ls-remote` before/after equality;
- no recorded push calls;
- no adapter mutation calls;
- no live DB changes;
- no live clone changes;
- candidate and baseline build independently;
- required pages still resolve;
- all blocking quality gates pass or the POC is explicitly recorded failed.

Acceptance criteria:

- OceanicVibes remains live and unchanged.
- The candidate is inspectable locally by immutable SHA.
- The report states what improved, regressed, or remains subjective.
- The derived page demonstrates whether the manifest is sufficient.

### Phase 9: Production Candidate Migration

Do not begin this phase merely because the POC looks better.

Tasks:

- Review POC evidence and revise contracts/gates.
- Add immutable candidate metadata to new production drafts.
- Update review/page resolution to use candidate SHA for new drafts.
- Update merge adapters to merge the exact reviewed SHA.
- Preserve legacy mutable-preview draft compatibility until all pending legacy
  drafts are resolved.
- Add explicit owner approval from Review.
- Add rollback and stale-base handling.
- Connect provisioning so accepted intake can enqueue the first design run after
  the scaffold and repository are ready.
- Connect owner chat so a new-page request compiles a `PageIntake` and inherits
  the approved design manifest.

Focused tests:

- approval merges exactly the reviewed SHA;
- changed remote preview tip cannot alter a pending immutable draft;
- stale base returns conflict;
- decline leaves production unchanged;
- follow-up design runs stack only when explicitly linked to the same candidate
  lineage;
- initial provisioning creates a pending design, never an automatic publish;
- new-page chat uses approved manifest and creates a pending design.

Acceptance criteria:

- Production review is immutable end to end.
- Initial and later pages use the same typed engine.
- Production still changes only after explicit owner approval.

## Proposed File Map

Files likely to be added:

```text
src/site_agent/core/design_contracts.py
src/site_agent/application/designs.py
src/site_agent/brain/design_brief.py
src/site_agent/brain/art_direction.py
src/site_agent/brain/page_strategy.py
src/site_agent/brain/design_critic.py
src/site_agent/hands/design_quality.py
src/site_agent/hands/browser_quality.py
examples/oceanicvibes.intake.json
tests/test_design_contracts.py
tests/test_design_service.py
tests/test_design_builder.py
tests/test_design_quality.py
tests/test_design_web.py
```

Existing files likely to change:

```text
src/site_agent/main.py
src/site_agent/site_scaffold.py
src/site_agent/config.py
src/site_agent/core/memory.py
src/site_agent/core/chat_jobs.py
src/site_agent/hands/builder.py
src/site_agent/hands/opencode_runner.py
src/site_agent/hands/site_digest.py
src/site_agent/hands/template_tokens.py
src/site_agent/web/preview.py
src/site_agent/web/server.py
src/site_agent/web/static/admin.html
tests/test_site_scaffold.py
tests/test_builder.py
tests/test_preview.py
tests/test_web.py
```

Do not create all files up front. Add each only when its phase establishes a
real boundary.

## API Guidance

Potential new read/write endpoints after the application service exists:

```text
POST /api/design-runs
GET  /api/design-runs/{run_id}
POST /api/design-runs/{run_id}/cancel
GET  /api/design-runs/{run_id}/report
GET  /api/design-runs/{run_id}/pages
GET  /api/design-runs/{run_id}/preview/{variant}/{file_path}
```

Rules:

- Routes translate HTTP/session data and call `DesignService`.
- Routes do not execute Git, builders, or transitions directly.
- Creating a production-capable run requires owner authentication.
- Experiment creation may remain CLI-only for the POC.
- Experiment read endpoints expose no mutation action.
- Owner responses use plain language; IDs and diagnostics appear under details.

## Configuration Guidance

Add narrowly scoped settings only when implementation requires them. Suggested
shape:

```yaml
design_engine:
  enabled: false
  intake_schema_version: 1
  manifest_path: design/ada-design-manifest.json
  repair_attempts: 2
  required_viewports:
    - {name: desktop, width: 1440, height: 1000}
    - {name: tablet, width: 768, height: 1024}
    - {name: mobile, width: 390, height: 844}
  quality:
    browser: true
    accessibility: true
    visual_critic: true
  experiment:
    root: ""
```

Rules:

- Defaults keep the new engine disabled until dependencies and rollout are
  ready.
- Site-specific paths and validation assumptions belong in instance config or
  the site manifest, not generic code.
- Do not hard-code OceanicVibes theme paths in generic quality checks.
- Validate that experiment roots do not overlap live paths.

## Test Strategy

### Unit tests

- contracts and canonical hashes;
- state transitions;
- intake assessment;
- art-direction parsing;
- build-target policy;
- manifest conformance;
- quality finding severity;
- preview path and ref resolution.

### Integration tests

- fake builder creates a local candidate SHA;
- real temporary Git repository proves no-push behavior;
- generated static and Pelican output served by SHA;
- fake browser reports console/network/accessibility findings;
- repair loop continuation;
- read-only comparison endpoints and UI state;
- immutable approval behavior in Phase 9.

### Security tests

- path traversal;
- symlink escape;
- hostile intake strings;
- prompt injection in asset metadata and example-site notes;
- secret redaction;
- untrusted HTML/script behavior inside sandboxed preview;
- experiment target escalation;
- SHA/ref substitution;
- stale candidate approval.

### Regression tests

- current chat jobs remain durable;
- current edit/article/merge drafts remain reviewable;
- `/ada/` preview URL rewriting remains valid;
- Pelican journal generation remains valid;
- package data includes any new required static/schema files;
- existing instance configs load unchanged while the engine is disabled.

## Verification Commands

Run focused tests after each phase, then the complete repository verification:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
git diff --check
```

Add the browser dependency smoke command once the browser adapter is selected.
Do not make the full unit suite download browsers from the network; browser
installation belongs in explicit development/deployment setup.

## Rollout And Failure Recovery

- Keep `design_engine.enabled: false` by default through the local POC.
- Run the OceanicVibes POC with a separate config overlay, clone, DB, cache, and
  data directory.
- Do not restart or reconfigure the live OceanicVibes service for the experiment.
- If the POC fails, retain the run record and quality report, delete only the
  disposable worktree, and leave the local candidate ref for diagnosis.
- Add cleanup for expired experiment artifacts only after retention and active
  review rules are explicit.
- Enable production candidates first on a non-live test repository.
- Migrate one production instance only after immutable review/approval tests and
  a full staging smoke pass.
- Keep a feature-flag rollback to the current builder path until production
  candidate lineage is proven.

## Definition Of Done

The design engine is complete only when:

- intake JSON is versioned, validated, persisted, and provenance-aware;
- an initial homepage run produces an immutable candidate, manifest, and quality
  report;
- a later page inherits the exact approved design source;
- all ready candidates pass deterministic and browser quality gates;
- visual critique is structured and evidence-linked;
- owner review uses immutable candidate content;
- production approval merges exactly what was reviewed;
- local experiments cannot publish;
- OceanicVibes has been compared locally with zero remote or live-instance
  mutation;
- focused tests, full tests, compileall, wheel build, and diff checks pass;
- architecture and operational documentation reflect the final behavior.

## Decision Log

Record implementation decisions here rather than silently changing this plan.

| Date | Decision | Reason | Consequence |
|---|---|---|---|
| 2026-08-30 | Start with a framework-neutral design engine | The current POC must be testable without coupling the safety pipeline to a React/Astro migration | Current static/Pelican sites and future component sites can share contracts |
| 2026-08-30 | Make the OceanicVibes experiment local-only and non-publishable | The site is live and receiving traffic; a shared preview push is unnecessary risk | Requires immutable local refs and read-only comparison support first |
| 2026-08-30 | Use the homepage plus a verified manifest as the later-page design source | Regex token extraction alone cannot express shared identity or allowed variation | Requires declared and measured manifest conformance |
| 2026-08-30 | Generate several textual directions but implement one | Improves originality without multiplying implementation cost or owner decisions | Ada must record selection and rejection rationale |
| 2026-08-30 | Keep production approval explicit | Automated checks reduce error but do not constitute owner consent | No quality score can publish a site |

## Implementation Log

Leave this section empty until coding begins. At that time record:

- starting commit and branch;
- pre-existing worktree changes;
- latest SQLite migration;
- baseline test count;
- phase completion commits;
- POC run ID, baseline SHA, candidate SHA, and safety verification result;
- final verification results.
