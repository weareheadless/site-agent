# Customer Context and Website Handoff Implementation Plan

**Status:** Proposed implementation contract

**Date:** 2026-09-06

**Audience:** Coding AI implementing the next architecture phase

**Authority:** This plan corrects and supersedes the lossy customer-handoff and
runtime-context portions of
`docs/ada-incubation-research-and-provisioning-implementation-plan.md`. It does
not supersede that plan's isolation, privacy, owner-approval, retention, or
cross-customer-memory rules. The repository invariants in `AGENTS.md` remain
authoritative.

## Executive Decision

Treat customer incubation as preparation of the first durable state of a normal
`site-agent` instance.

Intake Ada is not the long-lived website manager. She creates an isolated
incubation in which customer facts, audience understanding, brand identity,
owner preferences, research, media, design decisions, and feedback become
versioned evidence. When the owner accepts a candidate, the system freezes the
exact accepted customer context and the exact accepted website commit together.
Provisioning imports both into a new customer `site-agent` instance. The new
customer Ada must be able to manage the accepted website immediately and must
continue from the complete accepted context rather than a generated persona
summary.

The required lifecycle is:

```text
owner conversation + uploads + bounded research
  -> versioned incubation evidence
  -> one canonical customer context assembled from exact revisions
  -> website design built from that context
  -> owner accepts an exact candidate and exact context
  -> immutable acceptance manifest
  -> verified provisioning of website source + customer context + media
  -> normal site-agent runtime reads that same customer context
  -> customer Ada evolves the context through later owner-approved work
```

This is an architecture correction, not a prompt-tuning task. Do not begin by
adding more planner prose, special-case design checks, or UI heuristics.

## Problem Statement

The repository currently persists much of the right data but has no single
authoritative path from incubation to the long-lived runtime.

Current behavior:

- `incubation.db` stores intake revisions, conversation, genesis, research,
  media metadata, feedback, activity, and design runs.
- The initial design pipeline receives partial and sometimes lossy projections
  of that state.
- Acceptance stores only a candidate SHA in the Intake Ada registry.
- Provisioning freezes a broad bundle, but it chooses some records by "latest"
  rather than by the accepted run's lineage.
- `CustomerGenesisImporter` does not import the confirmed intake into the
  destination intake tables.
- Research deductions and approved business knowledge are omitted.
- Media bytes may be copied, but asset roles and bindings are not preserved.
- Design history is flattened into generic observations.
- The accepted website repository and commit are not attached to the customer
  instance.
- Generated YAML contains stale projections of audience, persona, and sources.
- `Runtime` has no customer-context service.
- Normal brain modules primarily consume generated config and recent generic
  observations, not the accepted typed business state.

The result is a partially seeded generic bot, not a continuation of the
incubation.

## Locked Product Decisions

### Handoff scope

- Provision the full accepted customer context.
- Include the exact confirmed intake, genesis, media and roles, approved
  knowledge, research evidence, deductions, owner feedback, conversation, and
  design lineage.
- Keep operational job attempts, provider transcripts, temporary paths, and
  debugging noise outside Ada's active customer context.
- Preserve operational history where needed for audit, but do not inject it
  into normal model context.

### Website scope

- Provision the accepted website source and immutable candidate commit together
  with customer context.
- Configure the resulting customer instance so `site-agent` can build, preview,
  propose changes to, and publish that website through its normal approval flow.
- Do not report provisioning as verified if the accepted commit is unavailable
  to the destination instance.

### Canonicality

- The customer database is authoritative for customer business state after
  provisioning.
- YAML is operational configuration only. It may contain provider choices,
  credentials references, paths, schedules, feature switches, and deployment
  settings. It must not be the canonical store for audience, brand, approved
  sources, owner preferences, or prohibited claims.
- Generic observations are a chronological memory stream, not the canonical
  customer model.
- `CustomerAdaGenesis` remains a derived, versioned interpretation. It does not
  replace exact owner-confirmed intake facts.
- Typed research records remain canonical. Do not duplicate them into prose and
  then use the prose as authority.

### Evolution after provisioning

- The accepted context is an immutable baseline.
- Customer Ada may create later revisions as the owner corrects facts, approves
  knowledge, changes brand direction, adds assets, or learns from operation.
- Later revisions must preserve provenance back to the accepted baseline and
  the owner action or evidence that changed them.
- Host-owned safety, privacy, non-fabrication, and approval rules are not
  customer-editable context.

## Non-Goals

- Do not merge Intake Ada's database with customer databases.
- Do not give one customer access to another customer's raw history.
- Do not put complete customer context into every prompt.
- Do not replace SQLite with a new database.
- Do not rewrite `Memory` wholesale.
- Do not introduce a universal repository abstraction or plugin framework.
- Do not make model output the authority for customer facts.
- Do not automatically publish or activate a customer instance.
- Do not solve visual quality by adding customer-specific diving rules to
  generic design code.
- Do not import provider credentials, temporary build directories, screenshots,
  caches, or raw model transcripts into customer memory.

## Architectural Invariants

The implementation must preserve these invariants:

1. Every customer-context value has an origin and stable source reference.
2. Owner-confirmed values outrank model assumptions and research hypotheses.
3. An accepted website candidate is bound to exactly one immutable customer
   context hash.
4. Provisioning uses the acceptance manifest, never a collection of latest
   records.
5. The provisioned customer can reconstruct what was accepted from its own
   database without reading the source incubation database.
6. The destination can build the accepted website from the exact accepted
   commit before provisioning is marked verified.
7. Runtime services read customer state through one application service.
8. Task-specific projections are deterministic and bounded.
9. Generated config is not a second mutable copy of business truth.
10. Any cross-database operation is resumable and independently verifiable.
11. Production changes still require explicit owner approval.
12. Intake Ada retains only sanitized cross-customer learning after handoff.

## Existing Components to Preserve

Build on these existing foundations:

- `core/design_intake_contracts.py`: versioned intake draft and field
  provenance.
- `core/design_contracts.py`: `SiteIntake`, design snapshots, immutable hashes,
  build targets, and quality contracts.
- `core/incubation_contracts.py`: genesis, research, activity, provisioning
  bundle, and receipt contracts.
- `core/memory.py`: per-instance schema, migrations, intake revisions, genesis,
  research, media metadata, design runs, business knowledge, and jobs.
- `core/intake_ada_store.py`: cross-incubation registry and sanitized Intake Ada
  memory.
- `application/design_intake.py`: owner conversation to versioned intake.
- `application/customer_genesis.py`: provenance-aware derived genesis.
- `application/incubation_research.py`: typed source and finding lifecycle.
- `application/designs.py`: immutable design run and context capture.
- `application/provisioning.py`: bundle, import, receipt, and activation
  boundaries.
- `application/media.py`: provider-neutral media transfer.
- `runtime.py`: named runtime composition root.
- exact-SHA build and preview infrastructure in `hands/` and `web/preview.py`.

Do not treat the current importer or generated config as a compatibility
contract. They are the primary correction targets.

## Target Data Model

### CustomerContextSnapshot

Add a typed immutable contract named `CustomerContextSnapshot`. Place the
contract in a customer-context-owned module rather than adding more unrelated
fields to `ProvisioningBundle`.

Suggested location:

```text
src/site_agent/core/customer_context_contracts.py
```

Required top-level identity:

- `schema_version`
- `context_id`
- `context_revision`
- `created_at`
- `source_kind`
- `source_incubation_id`
- `source_intake_session_id`
- `source_intake_revision_id`
- `source_intake_revision`
- `source_intake_hash`
- `previous_context_hash`
- `content_hash`

Required sections:

- `business`: exact accepted business facts and their provenance.
- `audience`: primary and secondary audiences, motivations, concerns,
  communities, language context, and provenance.
- `conversion`: desired visitor actions and validated destinations.
- `brand`: voice, vibe, desired impression, colors, typography, visual
  preferences, styles to avoid, and provenance.
- `site`: language, required pages, navigation intent, device priority,
  accessibility needs, motion preference, prohibited claims, and unknowns.
- `relationship`: owner communication preferences, decision style, boundaries,
  and review preferences.
- `assets`: typed customer asset references and owner-approved usage.
- `knowledge`: references to approved business-knowledge records.
- `research`: references to approved sources, findings, insights, deductions,
  contradictions, and ongoing subscriptions.
- `creative_identity`: accepted genesis revision and evidence references.
- `design`: accepted run and design evidence when the context is accepted.

The snapshot should reference canonical records by stable identifiers and hashes
instead of copying every full payload. It may embed the exact accepted
`SiteIntake` because that object is the frozen owner-confirmed business brief.
Large evidence collections should be referenced through a versioned manifest.

### CustomerAssetBinding

Add a typed asset binding contract. Do not use free-form tags as the authority
for asset purpose.

Required fields:

- `asset_id`
- `content_hash`
- `role`: `logo`, `hero`, `gallery`, `content`, or `reference_only`
- `required`: boolean
- `placement`: bounded list of route or chrome targets
- `position`
- `owner_note`
- `reference_aspects`
- `analysis_hash`
- `source_kind`
- `source_id`

Rules:

- An official logo must be explicitly owner-designated or owner-confirmed.
- `reference_only` assets cannot be emitted as website media.
- A required asset must appear in generated output and survive provisioning.
- Asset identity is content-hash-backed, not filename-backed.
- Destination imports must record source-to-destination asset ID mappings.

### ResearchEvidenceManifest

Add a deterministic research manifest referenced by customer context.

It must identify:

- included source IDs and source hashes;
- finding IDs and hashes;
- insight IDs and hashes;
- deduction IDs and hashes;
- source trust and subscription states;
- contradictions and unresolved claims;
- source-language and target-language metadata;
- excluded source IDs;
- a manifest content hash.

Do not make generic observations part of this manifest.

### AcceptanceManifest

Add an immutable acceptance contract and table.

Suggested location:

```text
src/site_agent/core/customer_context_contracts.py
```

Required fields:

- `manifest_id`
- `incubation_id`
- `accepted_at`
- `accepted_by`
- `design_run_id`
- `candidate_sha`
- `base_sha`
- `customer_context_id`
- `customer_context_hash`
- `intake_session_id`
- `intake_revision_id`
- `intake_hash`
- `genesis_revision`
- `genesis_hash`
- `research_manifest_hash`
- required asset IDs and content hashes;
- approved knowledge IDs and hashes;
- `design_manifest_hash`
- `quality_report_hash`
- `planning_hash`
- `design_skill_set_hash`
- `website_build_profile`
- `repository_identity`
- `content_hash`

Acceptance must derive `candidate_sha` from the selected design run. If the HTTP
request still supplies a SHA during migration, require strict equality and
ignore it as a source of truth.

### ProvisioningBundle v2

Evolve the provisioning bundle to version 2. It should be assembled exclusively
from an `AcceptanceManifest` and its transitive dependencies.

Required additions:

- full `acceptance_manifest`;
- full accepted `customer_context`;
- exact accepted intake session and revision;
- asset bindings and complete referenced-asset closure;
- approved business knowledge;
- research deductions;
- source-to-record provenance needed after import;
- website source transfer descriptor;
- complete design lineage necessary to continue management;
- completeness metadata for every bounded collection.

Every exported collection must include:

- `total_count`
- `exported_count`
- `truncated`
- selection rule or cursor

Provisioning must fail when an accepted dependency is missing. It must not
silently omit older accepted history.

## Canonical Customer Context Service

Add an application service:

```text
src/site_agent/application/customer_context.py
```

Suggested interface:

```python
class CustomerContextService:
    def current(self) -> CustomerContextSnapshot | None: ...
    def get(self, context_id: str) -> CustomerContextSnapshot: ...
    def assemble_from_incubation(...exact revision identities...) -> CustomerContextSnapshot: ...
    def import_accepted(...bundle identities...) -> CustomerContextSnapshot: ...
    def revise(...owner action or approved evidence...) -> CustomerContextSnapshot: ...
    def task_view(self, task: str, *, limits: ContextLimits | None = None) -> CustomerContextView: ...
```

Responsibilities:

- Resolve canonical records from `Memory`.
- Validate provenance and hash consistency.
- Assemble immutable context revisions.
- Produce bounded deterministic views for consumers.
- Keep owner-confirmed facts distinct from research hypotheses.
- Surface contradictions instead of silently resolving them.
- Exclude private Ada material and operational noise from customer work views.
- Never call HTTP routes or access another customer's database.

The service should depend on narrow repository methods. Do not move SQL into the
service and do not let brain modules access `Memory.conn`.

### Required task views

Implement named projections rather than one giant prompt block:

| View | Required consumers | Contents |
|---|---|---|
| `identity` | persona and owner chat | business purpose, audience, voice, owner relationship, boundaries, language |
| `design` | design intake, planning, visual review | exact site facts, brand, audience, conversion, required assets, research implications, motion/accessibility, styles to avoid |
| `editorial` | articles, reports, social | audience needs, voice, facts, prohibited claims, approved knowledge, relevant research |
| `research` | digest and source discovery | subjects, communities, approved/excluded sources, unresolved questions, prior findings |
| `strategy` | strategist, SEO | business goals, conversion, audience, analytics context, research and accepted constraints |
| `owner_relationship` | chat and approvals | communication preferences, corrections, decision style, boundaries |

Each view must include:

- source context ID/hash;
- source record IDs/hashes;
- explicit unknowns and contradictions;
- deterministic truncation metadata;
- no generated conversational phrasing.

## Runtime Composition

Update `Runtime` in `src/site_agent/runtime.py`.

Required changes:

- Add `customer_context_service: CustomerContextService`.
- Construct it for every normal customer runtime from the customer `Memory`.
- Expose it in `Runtime.context()` during the compatibility period.
- Build `persona_prompt` from the `identity` view, not generated customer YAML.
- Keep host-owned identity and safety directions separate from customer context.
- Compute prompt context at job execution time so later context revisions are
  visible without restarting the process.
- Change capability availability to reflect actual composed services, not only
  config flags.

Do not preserve `persona_prompt` as a permanently frozen string inside Runtime
once dynamic customer context exists. Either expose a callable/context provider
or refresh it at each job boundary.

## Consumer Migration

Migrate consumers incrementally. Keep existing APIs stable while changing their
input source.

### Persona and chat

Files:

- `src/site_agent/brain/prompts.py`
- `src/site_agent/core/chat_jobs.py`
- `src/site_agent/core/jobs.py`
- `src/site_agent/core/reflect.py`

Changes:

- Build customer-facing identity from `CustomerContextService.identity`.
- Preserve `inner_identity_prompt()` as Ada-owned identity.
- Stop relying on `config.persona.audience`, `voice`, and `taboo` as canonical
  values.
- Keep recent observations as chronological context, not foundational business
  identity.

### Design

Files:

- `src/site_agent/application/design_intake.py`
- `src/site_agent/application/designs.py`
- `src/site_agent/application/incubations.py`
- `src/site_agent/brain/design_brief.py`
- `src/site_agent/brain/page_strategy.py`
- `src/site_agent/brain/react_design.py`
- `src/site_agent/hands/astro_react_builder.py`
- `src/site_agent/hands/design_visual_review.py`

Changes:

- Assemble one revision-bound customer context before creating a design run.
- Store its ID and hash on the run.
- Build the design request from the `design` view.
- Remove separate reads of current session, latest genesis, recent observations,
  and best-effort research from the same build path.
- Require planner output language to equal the accepted website language.
- Require all required assets and the official logo to be represented in the
  design manifest and rendered output.
- Pass brand, audience, research implications, motion intent, and styles to
  avoid to both generation and visual review.
- Keep repository/runtime safety gates separate from semantic-conformance gates.
- Treat missing required semantic inputs as planner/build failures, not generic
  fallback opportunities.

This phase must remove or constrain normalizers that silently replace missing
semantic content with generic sections, generic navigation, fallback marks, or
an arbitrary language.

### Editorial, SEO, strategy, and social

Files:

- `src/site_agent/brain/article.py`
- `src/site_agent/brain/article_research.py`
- `src/site_agent/brain/report.py`
- `src/site_agent/brain/monthly_seo_report.py`
- `src/site_agent/brain/seo.py`
- `src/site_agent/brain/social.py`
- `src/site_agent/brain/strategist.py`
- `src/site_agent/brain/digest.py`

Changes:

- Use task-specific customer-context views.
- Use approved business knowledge and typed research directly.
- Preserve citation and source identities through generated proposals.
- Enforce prohibited claims from customer context.
- Keep all external mutations approval-gated.

### Scheduled source collection

Files:

- `src/site_agent/core/jobs.py`
- `src/site_agent/senses/__init__.py`
- relevant RSS/source adapters

Changes:

- Query allowed and owner-approved research sources from customer memory.
- Stop treating `config.sources.rss_feeds` as canonical.
- Keep config-only sources as a migration fallback until existing instances are
  reconciled.
- Record the context revision and source disposition used by each collection
  job.

### Media and business knowledge

Files:

- `src/site_agent/runtime.py`
- `src/site_agent/application/media.py`
- `src/site_agent/application/business_knowledge.py`
- `src/site_agent/core/media_worker.py`

Changes:

- Support the provisioned media adapter explicitly.
- Do not disable access to imported media after provisioning.
- Import owner-approved business knowledge and its referenced media.
- Ensure customer-context revisions reference approved knowledge records rather
  than copying their prose.
- Allow later owner approvals to create a new context revision.

## Acceptance Workflow

Update acceptance in `application/incubations.py`.

Required sequence:

1. Load the selected design run.
2. Verify the run is ready for review and belongs to the incubation.
3. Verify its candidate SHA exists in the retained repository.
4. Resolve the exact intake session and revision stored on the run.
5. Resolve the exact context snapshot used by the run.
6. Resolve required assets, approved knowledge, research manifest, genesis, and
   design evidence by stable identity.
7. Verify all hashes.
8. Create and persist `AcceptanceManifest` atomically in the incubation DB.
9. Store the acceptance manifest ID and accepted run ID in the Intake Ada
   registry.
10. Transition the incubation to `accepted`.

After acceptance:

- Customer-context mutations that would affect the handoff must either be
  rejected or require a new design and new acceptance.
- Background processing may finish, but its results cannot silently enter the
  accepted manifest.
- Owner feedback after acceptance must explicitly reopen the incubation and
  invalidate the prior acceptance or begin a new revision lineage.

## Website Source Handoff

Provisioning must adopt the accepted website, not merely remember its SHA.

Add a narrow website-transfer capability in `hands/`. It should operate on exact
Git commits and return a typed receipt.

Required behavior:

- Verify the source repository contains `candidate_sha`.
- Create or bind a customer-owned repository/clone according to instance
  configuration.
- Materialize the accepted commit as the destination's initial `main` state.
- Preserve source lineage in a local tag/ref or receipt without retaining
  incubation paths.
- Configure the correct adapter, repository, branch, clone path, build profile,
  and deployment mode.
- Build the destination from the accepted commit.
- Compare the build manifest and required asset hashes to the acceptance
  manifest.
- Keep production unpublished until the explicit activation/publish operation.

Do not copy a mutable incubation worktree. Transfer through an exact commit
archive or a controlled Git object/ref operation.

## Provisioning Import

Replace the current broad `CustomerGenesisImporter` responsibility with an
accepted-customer import service. A compatibility wrapper may retain the old
name temporarily, but new code should reflect the wider responsibility.

Suggested name:

```text
AcceptedCustomerImporter
```

Required import behavior:

- Persist the provisioning import and bundle hash first in a resumable import
  ledger.
- Import the complete conversation selected by the acceptance manifest.
- Recreate an intake session and the exact confirmed intake revision.
- Persist the accepted `CustomerContextSnapshot` as destination revision 1,
  preserving source IDs as provenance.
- Import genesis revisions with original source metadata and hashes.
- Import research sources, findings, requests, insights, and deductions.
- Preserve trust, exclusion, and subscription state consistently.
- Import approved business knowledge.
- Transfer the dependency closure of all referenced assets.
- Recreate typed asset bindings with destination media IDs.
- Remap every conversation attachment and evidence reference.
- Import owner feedback and design lineage into their canonical tables where
  supported.
- Persist the `AcceptanceManifest` and website-transfer receipt.
- Add generic observations only for chronological recall; they must reference
  canonical record IDs and must not duplicate full truth.

The importer must never fall back to an old source asset ID when no destination
mapping exists. Missing mappings are fatal import errors.

## Resumable Provisioning Saga

Cross-store provisioning cannot be atomic, so make it explicitly resumable.

Add a provisioning operation record with these states:

```text
prepared
registry_marked
destination_created
config_written
website_transferred
media_transferred
database_imported
verified
receipt_saved
completed
failed_retryable
failed_terminal
```

Rules:

- Every stage is idempotent by request ID, bundle hash, and acceptance manifest
  hash.
- Retrying a `provisioning` incubation resumes the same operation.
- A destination initialized from another bundle is a terminal conflict.
- Partial media and database imports retain checkpoints and source-to-destination
  ID maps.
- No successful receipt is written before independent verification.
- A failed import leaves the incubation and acceptance manifest inspectable.

## Destination Verification

Replace the current KV-marker-only verification.

Verification must independently confirm:

- destination database exists and has the expected schema version;
- acceptance manifest hash matches;
- customer-context hash matches;
- exact intake hash and revision match;
- accepted genesis hash matches;
- research manifest and record hashes match;
- all required records were imported without truncation;
- approved business-knowledge records and source assets exist;
- every attachment and evidence asset reference maps to an existing destination
  asset;
- every required asset object exists and matches its content hash;
- official logo and required asset roles survived import;
- destination repository contains the accepted commit lineage;
- destination checkout builds successfully;
- built design manifest references the accepted context and required assets;
- generated config contains the correct operational paths and adapter settings;
- the runtime can instantiate `CustomerContextService` and load the accepted
  context without accessing incubation storage.

Only then may provisioning issue a verified receipt.

## Configuration Changes

Update generated customer configuration so it represents operational state.

Keep in config:

- instance identity;
- data and repository paths;
- model/provider settings and secret environment-variable names;
- schedules;
- adapter and deployment settings;
- analytics/integration identifiers;
- feature availability;
- activation state.

Remove as canonical generated state:

- persona voice;
- audience summary;
- brand directions;
- taboo/prohibited claims;
- research subjects;
- approved RSS feeds;
- owner communication preferences.

During migration, these fields may remain as read-only fallbacks for instances
without an imported customer context. New provisioned instances must not rely on
them.

## Persistence and Migrations

Add forward-only SQLite migrations in `core/memory.py` and
`core/intake_ada_store.py`.

Suggested customer database tables:

```text
customer_context_revisions
acceptance_manifests
provisioning_imports
provisioning_id_maps
website_handoff_receipts
```

Suggested `customer_context_revisions` columns:

- `context_id TEXT PRIMARY KEY`
- `revision INTEGER NOT NULL`
- `context_json TEXT NOT NULL`
- `context_hash TEXT NOT NULL UNIQUE`
- `previous_context_hash TEXT`
- `source_kind TEXT NOT NULL`
- `source_id TEXT NOT NULL`
- `accepted_baseline INTEGER NOT NULL DEFAULT 0`
- `created_ts TEXT NOT NULL`

Suggested `acceptance_manifests` columns:

- `manifest_id TEXT PRIMARY KEY`
- `manifest_json TEXT NOT NULL`
- `manifest_hash TEXT NOT NULL UNIQUE`
- `design_run_id TEXT NOT NULL`
- `candidate_sha TEXT NOT NULL`
- `customer_context_hash TEXT NOT NULL`
- `created_ts TEXT NOT NULL`

Suggested Intake Ada registry additions:

- `accepted_run_id`
- `acceptance_manifest_id`
- `acceptance_manifest_hash`

Do not store raw customer context in `IntakeAdaStore`.

Migration requirements:

- Existing databases must continue opening without manual intervention.
- Existing accepted incubations should reconstruct an acceptance manifest only
  when the candidate run, intake lineage, and hashes can be proven.
- Ambiguous records must be marked for repair rather than guessed.
- Existing provisioned instances should import a baseline context from their
  retained bundle when available.
- If only lossy KV/config projections remain, mark migration incomplete and keep
  compatibility behavior; do not fabricate canonical facts.

## Correctness Fixes Included in This Work

Address these known defects as part of the architecture work:

- Acceptance currently permits a supplied SHA that is not proven equal to the
  run's candidate SHA.
- Bundle freezing currently chooses latest intake/genesis records instead of the
  accepted run lineage.
- Approved business knowledge is not provisioned.
- Research deductions are not provisioned.
- Intake asset bindings and roles are not reconstructed in the destination.
- Unbound conversation attachments can retain invalid source asset IDs.
- Imported media is disabled in generated customer config/runtime composition.
- Runtime sources come from static YAML instead of canonical source records.
- Design lineage is reduced to generic observations.
- Customer genesis evidence may retain stale source asset/session IDs.
- Infusion constructs `GenesisEvidence` with the wrong contract fields and
  suppresses the resulting failure.
- Provisioning cannot reliably resume after a crash in the `provisioning` state.
- Destination verification trusts importer-written KV markers rather than
  independently checking imported state.

## Implementation Phases

Follow these phases in order. Do not start consumer prompt changes before the
canonical context and import path exist.

### Phase 0: Characterization and authority tests

Add failing tests that prove current gaps:

- accepted candidate and supplied SHA can diverge;
- bundle intake can differ from the accepted run intake;
- destination lacks canonical intake after import;
- destination runtime persona ignores imported genesis/intake changes;
- destination source collection ignores canonical source disposition changes;
- deductions and approved knowledge disappear during provisioning;
- official logo role is not preserved;
- accepted website source is unavailable in the destination;
- invalid attachment mappings survive import;
- a crash leaves provisioning non-resumable.

Document the canonical ownership matrix in `docs/architecture.md`.

### Phase 1: Customer context contracts and persistence

- Add `CustomerContextSnapshot`, `CustomerAssetBinding`,
  `ResearchEvidenceManifest`, and `AcceptanceManifest`.
- Add SQLite migrations and `Memory` repository methods.
- Add hash, previous-revision, and source-identity validation.
- Add round-trip and migration tests.

Acceptance criteria:

- A customer context can be reconstructed and hash-verified after restart.
- A context revision cannot mutate in place.
- Owner facts, hypotheses, and unknowns remain distinguishable.

### Phase 2: CustomerContextService

- Implement exact incubation assembly.
- Implement destination import and current-context lookup.
- Implement bounded task views.
- Add deterministic truncation metadata.
- Add service to normal Runtime and incubation runtime composition.

Acceptance criteria:

- The same accepted context hash is visible in Intake Ada's design run and the
  provisioned customer Runtime.
- Task views contain required data and exclude unrelated/private data.

### Phase 3: Revision-bound design input

- Make incubation design creation consume `CustomerContextService.design`.
- Store context identity on every design run.
- Make language, required assets/logo, audience, brand, research implications,
  accessibility, and motion explicit design acceptance dimensions.
- Give visual review the same design view.
- Reject semantic omissions instead of normalizing to generic defaults.

Acceptance criteria:

- A candidate cannot become reviewable with the wrong website language.
- A required logo or image cannot be omitted.
- Design evidence identifies which research/brand/audience constraints were
  consumed.
- Safety gates and semantic-conformance gates are separately inspectable.

### Phase 4: Acceptance manifest

- Bind acceptance to the exact run and exact context.
- Persist the complete manifest atomically.
- Freeze accepted dependencies.
- Reject or explicitly reopen post-acceptance mutations.

Acceptance criteria:

- Acceptance cannot point at an arbitrary SHA.
- Provisioning has no "latest record" reads.
- Every accepted dependency is addressable by ID and hash.

### Phase 5: Provisioning bundle v2 and complete importer

- Build bundle v2 from the acceptance manifest.
- Import canonical intake, context, genesis, research, deductions, knowledge,
  media bindings, conversation, feedback, and design lineage.
- Preserve complete asset dependency closure and ID mappings.
- Add completeness metadata.

Acceptance criteria:

- Destination can answer what the owner accepted using only its own database.
- Destination context hash equals the acceptance manifest context hash.
- No destination record references a missing source asset or session ID.

### Phase 6: Website source transfer

- Add exact-commit website handoff adapter.
- Configure destination repository and site adapter.
- Build and preview the transferred website.
- Persist and verify a website handoff receipt.

Acceptance criteria:

- Newly provisioned `site-agent` can inspect and create a pending design change
  against the accepted site.
- No production publish occurs during provisioning.

### Phase 7: Runtime consumer migration

- Migrate persona/chat first.
- Migrate design/editorial/SEO/social/strategy views.
- Migrate scheduled sources from config to canonical records.
- Enable imported media and business knowledge.
- Retain compatibility fallback only for pre-context customer instances.

Acceptance criteria:

- Changing canonical customer context changes subsequent task context without a
  process restart.
- Changing stale YAML business projections does not override canonical context.
- Existing non-provisioned instances continue functioning through compatibility
  fallback.

### Phase 8: Resumable saga and independent verification

- Add provisioning stage ledger and retries.
- Make imports transactional where possible.
- Stage media and website transfer with idempotent receipts.
- Replace KV-only verification.
- Add crash/retry tests at every stage.

Acceptance criteria:

- Every interrupted stage resumes without duplicate conversations, assets,
  genesis revisions, contexts, repositories, or receipts.
- Verification detects deliberate corruption in each imported domain.

### Phase 9: Migration and cleanup

- Reconcile retained accepted incubations.
- Backfill already provisioned customers from retained bundles.
- Mark ambiguous migrations for operator repair.
- Remove generated-YAML authority after compatibility coverage proves safe.
- Remove generic-observation duplicates that no consumer requires.
- Update architecture, deployment, debugging, and provisioning documentation.

## Test Strategy

### Contract tests

- Reject unknown fields and unsupported schema versions.
- Verify canonical hashes after serialization round trips.
- Verify provenance references and previous-context chains.
- Verify asset-role and acceptance-manifest invariants.

### Persistence tests

- Exercise every migration from an older fixture database.
- Verify immutable context and manifest rows cannot be silently replaced.
- Verify accepted baseline uniqueness.
- Verify source-to-destination mappings survive restart.

### Service tests

- Assemble a context from an exact intake revision while newer revisions exist.
- Preserve explicit owner facts over conflicting research.
- Preserve contradictions and unknowns.
- Produce deterministic bounded task views.
- Ensure private Ada memory and another incubation never enter a view.

### Design tests

- Wrong-language planner output fails.
- Missing official logo fails when logo is required.
- Missing required website image fails.
- Reference-only assets cannot be emitted.
- Audience, brand, research, motion, and accessibility acceptance dimensions are
  present in the design manifest and visual-review input.
- Generic fallback normalization cannot turn a semantic failure into a
  reviewable candidate.

### Provisioning tests

- Accepted context and candidate remain aligned when later records exist.
- Full accepted context imports into canonical destination tables.
- Research deductions and approved business knowledge survive.
- Asset IDs and evidence references are remapped correctly.
- Exact website commit builds in the destination.
- Destination Runtime loads context with incubation storage unavailable.
- Repeated provisioning is idempotent.
- Failure at each saga stage resumes correctly.
- Verification fails on modified hashes, missing blobs, broken references, or a
  missing Git commit.

### Runtime tests

- Persona uses canonical identity view.
- Chat sees owner relationship preferences and exact business context.
- Article/SEO/social/design tasks receive only their appropriate task view.
- Approved source changes affect the next collection run without YAML edits.
- Later owner-approved context revisions affect future work without restart.
- Host safety and private identity remain independent from customer context.

### End-to-end acceptance test

Create one synthetic incubation that includes:

- English owner conversation;
- explicit website language;
- primary and secondary audiences;
- brand colors and typography;
- owner-designated logo;
- required hero and gallery assets;
- approved and excluded research sources;
- research findings, insights, and deductions;
- approved business knowledge;
- owner feedback;
- an accepted immutable website candidate.

Provision it and assert:

- the destination database contains the exact accepted context hash;
- the destination repository contains and builds the accepted website;
- all required assets and roles exist;
- source approvals and exclusions match;
- the normal Runtime loads the accepted context;
- identity, design, editorial, and research views contain the expected canonical
  records;
- no Intake Ada private memory or unrelated incubation data appears;
- no production mutation occurred.

Use synthetic names and content. Do not add a real customer fixture or secrets.

## Observability

Every diagnostic related to this flow must include relevant opaque identifiers:

- incubation ID;
- context ID and hash;
- intake session/revision ID;
- design run ID;
- acceptance manifest ID/hash;
- bundle ID/hash;
- provisioning request ID;
- customer instance ID;
- source and destination asset IDs;
- website handoff receipt ID;
- provider/adapter IDs where relevant.

Do not include credentials, raw private customer content, filesystem paths in
public projections, or another customer's identifiers.

## Rollout Strategy

1. Ship new tables and contracts without changing consumers.
2. Populate context snapshots during new incubations and compare them against
   existing projections in tests and diagnostics.
3. Bind new design runs to context snapshots.
4. Enable acceptance manifests for new acceptances.
5. Provision new customers through bundle v2 and the complete importer.
6. Enable Runtime context consumption for v2 customers.
7. Backfill retained accepted/provisioned records where identities are provable.
8. Keep fallback behavior for legacy instances with an explicit diagnostic.
9. Remove fallback authority only after all supported instances have a canonical
   context baseline.

Do not dual-write silently without reconciliation. Every temporary projection
must record its source context hash so divergence is detectable.

## Required Documentation Updates

Update these documents as implementation lands:

- `docs/architecture.md`: canonical ownership and runtime context flow.
- `docs/deploy.md`: customer repository/media/context provisioning and runtime
  activation.
- `docs/debugging.md`: acceptance manifest, bundle, import, context, repository,
  and runtime verification chain.
- `docs/ada-incubation-research-and-provisioning-implementation-plan.md`: mark
  superseded handoff sections and link to this plan.
- `README.md`: describe incubation as preparation of a normal managed
  `site-agent` instance.

## Verification Commands

Run focused tests after each phase, then the repository-required verification:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
git diff --check
```

For provisioning phases, also run the synthetic end-to-end test with source
incubation storage made unavailable after import. This proves the customer
runtime is self-contained.

## Definition of Done

This architecture phase is complete only when all of the following are true:

- One canonical customer-context contract is used before and after provisioning.
- The exact accepted intake, evidence, assets, and design lineage are present in
  the customer database.
- The accepted website commit is attached and buildable by the provisioned
  customer instance.
- Acceptance binds one candidate SHA to one customer-context hash.
- Provisioning imports from that acceptance manifest and never from latest
  records.
- Normal `site-agent` Runtime composes a customer-context service.
- Persona, chat, design, editorial, SEO, social, strategy, and research obtain
  business context through bounded task views.
- YAML is no longer the canonical store of business identity or research-source
  decisions for newly provisioned customers.
- Imported media and approved business knowledge remain operationally available.
- Provisioning is resumable and independently verified.
- Existing owner approval and production safety invariants remain intact.
- Full test, compile, wheel, and diff checks pass.

Until these conditions are met, do not characterize a provisioned customer Ada
as continuing from the complete incubation experience.
