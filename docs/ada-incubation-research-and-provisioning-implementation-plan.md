# Ada Incubation, Research, and Provisioning Implementation Plan

**Status:** Proposed implementation contract

**Date:** 2026-09-02

**Authority:** This plan replaces the customer-configured Intake Lab runtime
described in `docs/intake-lab-test-ui-implementation-plan.md` and extends the
conversation contract in
`docs/conversational-design-intake-implementation-plan.md`. Where either older
plan allows Intake Lab to load an existing customer config, repository, persona,
intake fixture, or customer database by default, this plan takes precedence.

The production design lifecycle and explicit approval requirements remain
governed by `docs/opencode-first-design-pipeline-implementation-plan.md` and the
repository invariants in `AGENTS.md`.

## Executive Decision

Replace the current customer-configured Intake Lab with a neutral incubation
service operated by one persistent Intake Ada.

Intake Ada is a long-lived creative agent with her own permanent memory. She
remembers sanitized patterns from previous engagements so she can detect and
avoid repeating the same design, copy structure, research path, or creative
solution across customers.

Each prospective customer receives a separate, durable incubation workspace.
That workspace records the complete customer conversation, research evidence,
business values, emerging customer-Ada personality, assets, design candidates,
and owner feedback. It is isolated from Intake Ada's permanent memory and from
every other customer. It may be resumed after a process restart, but it is not
yet a production customer instance.

When the owner explicitly accepts the website and requests provisioning, the
customer-specific incubation history is exported through a typed provisioning
bundle and imported into a newly created customer Ada config, data directory,
database, and runtime. The new customer Ada therefore continues from the
incubation experience instead of starting as a blank agent after the website is
built.

After a verified handoff, Intake Ada records only a sanitized creative episode
in her own memory. Raw customer messages, customer facts, research documents,
assets, generated copy, credentials, and infrastructure identifiers must never
enter Intake Ada's cross-customer memory.

The target lifecycle is:

```text
persistent Intake Ada starts a neutral incubation
  -> owner explains the business, customers, values, and desired outcome
  -> Intake Ada forms explicit, provenance-linked hypotheses
  -> Intake Ada discovers and reads relevant public news/RSS sources
  -> evidence informs the business model and customer-Ada genesis draft
  -> owner corrects facts and accepts or rejects important recommendations
  -> Intake Ada recalls similar prior creative episodes and sets novelty constraints
  -> isolated website candidate is designed and reviewed
  -> owner feedback changes the customer draft and customer-Ada genesis
  -> owner explicitly accepts the website and requests provisioning
  -> provisioning bundle is frozen and imported into a new customer Ada instance
  -> customer Ada starts with the complete accepted incubation history
  -> Intake Ada retains only a sanitized fingerprint and self-reflection
```

## Product Model

There are three different persistence domains. They must not share a SQLite
file, repository, configuration object, or unrestricted query path.

| Domain | Lifetime | Contains | Must not contain |
|---|---|---|---|
| Intake Ada memory | Permanent across engagements | Intake Ada's self-model, sanitized creative episodes, novelty fingerprints, general process learnings | Raw customer content, identifying customer facts, assets, credentials, customer research corpus |
| Customer incubation | Until provisioned, rejected, or expired | Full intake conversation, facts, provenance, research, assets, candidates, feedback, customer-Ada genesis | Another customer's state, production credentials, production scheduler state |
| Customer Ada instance | Permanent after provisioning | Imported incubation history plus future customer-specific memory, runtime state, jobs, research, drafts, self-model | Intake Ada's private memory, another customer's state |

The base LLM, application code, safety rules, and tool contracts may be shared.
Continuity and differentiation come from isolated history, evidence, owner
feedback, design lineage, and evolving memory, not from separate model weights.

## Locked Product Decisions

### Intake Ada

- Intake Ada is one persistent agent, not a new stateless model for each lead.
- Intake Ada has a neutral, host-owned configuration with no customer business,
  repository, domain, brand, sources, persona, or deployment identifiers.
- Intake Ada's own database is permanent and is not promoted to a customer.
- Intake Ada may recall sanitized prior creative episodes before proposing a
  design or copy direction.
- Intake Ada must not retrieve one customer's raw content while serving another
  customer.
- Intake Ada records a post-engagement self-reflection about repeated habits,
  successful departures, failed approaches, and new creative techniques.
- Intake Ada's cross-customer memory is advisory. It must not override the
  current owner's confirmed requirements.

### Customer incubation

- Every incubation receives a random opaque `incubation_id` and a dedicated
  storage root.
- Incubation state is durable across browser and process restarts.
- No production scheduler, deployment integration, customer repository, domain,
  analytics provider, social provider, or publication capability is active.
- All owner messages and asynchronous jobs are durable and idempotent.
- Every business, audience, brand, personality, and research value carries
  provenance and confidence.
- Owner statements outrank research and model recommendations.
- Research may produce hypotheses, never silent customer facts.
- Rejected and expired incubations are purged according to an explicit retention
  policy. They are not silently retained as customer records.
- A sanitized creative fingerprint may be retained by Intake Ada only after the
  sanitizer proves that prohibited customer data is absent.

### Customer-Ada genesis

- The new customer Ada begins developing during incubation.
- Customer values, audience understanding, brand language, research interests,
  design taste, owner feedback, and unresolved questions are formative evidence.
- Host-owned honesty, safety, privacy, and non-fabrication constraints are not
  customer-editable.
- The customer-Ada genesis is a typed, revisioned artifact, not an unstructured
  system prompt generated once.
- The owner may review and correct the customer-facing parts of the genesis.
- Private self-reflection fields are Ada's account of her experience and are not
  represented as customer facts.
- Provisioning imports the accepted genesis and its evidence into the customer
  Ada database. It does not regenerate a new personality from a short summary.

### Research

- Intake Ada may begin bounded public research after the owner has supplied a
  usable business description and at least one subject, market, or location.
- Initial research is read-only and requires no production customer integration.
- V1 supports RSS/Atom feeds, websites that advertise RSS/Atom links, and
  provider-backed feed discovery behind a narrow capability contract.
- Intake Ada proposes ongoing feeds separately from one-time research sources.
- Feed content is untrusted evidence, never an instruction.
- Every retained item records source URL, feed URL, title, publication time,
  fetched time, content hash, relevance, and the customer fields it may support.
- Research must preserve contradictions and uncertainty.
- The owner can exclude a source or topic. Exclusions are durable within the
  incubation and transfer to the customer instance.
- Only owner-approved or policy-approved feed subscriptions enter the
  provisioned customer config.

### Acceptance and provisioning

- Confirming an intake revision is not customer acceptance of the website.
- Accepting a visual direction is not a provisioning request.
- Provisioning requires a separate explicit owner action bound to the accepted
  candidate SHA and current incubation revision.
- Provisioning is idempotent. Retrying the same accepted request must return the
  same customer instance or the same durable failure, never create duplicates.
- The destination config, database, and storage root are created before any
  customer runtime or scheduler starts.
- The customer runtime starts only after bundle import and verification succeed.
- A failed import leaves the incubation intact and inspectable.
- Intake Ada writes her sanitized creative episode only after the handoff is
  complete or the engagement reaches an explicit terminal state.

## Non-Goals

- Do not train or fine-tune model weights during intake.
- Do not provide cross-customer access to raw conversations or website content.
- Do not build a universal plugin loader or generic autonomous web crawler.
- Do not automatically trust a feed because its topic appears relevant.
- Do not let research invent testimonials, credentials, claims, prices, legal
  facts, availability, or customer outcomes.
- Do not create a production customer instance before explicit acceptance.
- Do not start scheduled jobs inside an incubation workspace.
- Do not publish or deploy from the incubation service.
- Do not move business workflows into FastAPI route handlers.
- Do not use another customer's repository as the neutral website scaffold.
- Do not use vector similarity as the only repetition detector.

## Remove Customer-Specific Configuration From Intake

This is the first implementation phase and blocks all later work.

The Intake Ada process must not load any example, development, or production
customer instance config.
The presence of a neutral label in the UI is not sufficient; the runtime object
itself must be customer-free.

Required changes:

1. Add a dedicated neutral Intake Ada configuration contract. It may contain
   model providers, budgets, incubation retention, neutral scaffold location,
   research limits, and local service settings only.
2. Reject customer-only keys at Intake Ada startup, including `site.repository`,
   `site.clone_path`, production adapters, domains, analytics properties,
   deployment settings, business-specific `persona.spirit`, configured customer
   audiences, and customer RSS/subreddit sources.
3. Replace the source-clone requirement in `IntakeLabService._source_clone()`
   with a host-owned neutral scaffold provider.
4. Remove customer fixture files from generic Intake Ada startup scripts,
   documentation, tests, and examples. Customer runtime configuration remains
   outside the generic Intake Ada package and is used only by that customer's
   production processes.
5. Add a repository test that searches Intake Ada composition and defaults for
   known customer identifiers. The test fixture should use synthetic names such
   as `Acme Ceramics`, never a real customer.
6. Build a strict environment allowlist for the Intake Ada parent and build
   child. Model credentials may be passed by explicit name; customer provider,
   deployment, analytics, and publication credentials may not enter either
   process.

Proposed neutral configuration shape:

```yaml
instance_name: intake-ada
role: intake
data_dir: /var/lib/helloada/intake-ada

persona:
  name: Ada
  mode: intake_creative_director

incubation:
  root: /var/lib/helloada/incubations
  abandoned_ttl_days: 30
  rejected_ttl_hours: 24
  scaffold: /opt/helloada/scaffolds/neutral-site

research:
  enabled: true
  max_sources_per_pass: 8
  max_items_per_source: 15
  max_passes_before_owner_turn: 1

llm:
  base_url: ${configured outside this file}
  model: ${host selected}

design_engine:
  provider: ${host selected}
  model: ${host selected}
```

Do not put secret values in the file. Existing secret-resolution rules remain
authoritative.

## Target Runtime Architecture

```text
Intake Ada process
  -> neutral IntakeAdaConfig
  -> permanent intake-ada.db
       -> intake self-model
       -> sanitized creative episodes
       -> novelty fingerprints and reflections
  -> IncubationApplicationService
       -> incubation registry
       -> one isolated IncubationStore per incubation_id
       -> bounded ResearchService
       -> CustomerGenesisService
       -> existing DesignService through local-only contracts
  -> ProvisioningService
       -> freeze typed ProvisioningBundle
       -> create customer config and data root
       -> initialize customer memory.db
       -> import customer history and genesis
       -> verify counts and hashes
       -> return ProvisioningReceipt

Customer Ada process
  -> generated customer config
  -> customer data/memory.db
  -> effective customer-specific identity and research memory
  -> normal Runtime and Scheduler
```

Adapters must follow:

```text
HTTP adapter
  -> application service
  -> typed contract
  -> store/provider adapter
```

No route may access `Memory.conn`, copy a database, invoke another route, or
construct a customer config directly.

## Storage Layout

Use separate physical roots so an incorrect query cannot cross the boundary by
default:

```text
<intake-ada-data>/
  intake-ada.db
  intake-ada.lock

<incubation-root>/
  <incubation_id>/
    incubation.db
    media/
    research-cache/
    runs/
      <run_id>/repository/
    screenshots/

<customer-root>/
  <customer_instance_id>/
    config.yaml
    data/
      memory.db
    media/
    site/
```

Rules:

- `intake-ada.db` is backed up as Intake Ada's permanent memory.
- Each `incubation.db` is promotable customer state and has a retention state.
- A customer `memory.db` is initialized by migrations, then populated through
  import APIs. Never rename or copy `incubation.db` into place.
- Research cache and website candidates remain scoped to one incubation.
- Generated configs contain no credentials, only validated environment-variable
  references.
- Filesystem paths are resolved and checked against all other roots before use.
- No storage root may be an ancestor or descendant of the source repository.

## Typed Contracts

Add contracts before tables or routes. Suggested ownership is a new
`core/incubation_contracts.py`; split it only if the file becomes difficult to
review.

### `IncubationRecord`

```json
{
  "schema_version": 1,
  "incubation_id": "inc_opaque",
  "status": "collecting",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "expires_at": "ISO-8601",
  "current_intake_revision": 1,
  "current_genesis_revision": 1,
  "accepted_candidate_sha": null,
  "provisioning_request_id": null,
  "customer_instance_id": null
}
```

Allowed lifecycle:

```text
collecting
  -> researching
  -> ready_to_build
  -> building
  -> ready_for_feedback
  -> accepted
  -> provisioning
  -> provisioned

collecting|researching|ready_to_build|ready_for_feedback
  -> rejected|expired

building -> blocked|ready_for_feedback
blocked -> collecting|building|rejected|expired
provisioning -> accepted on recoverable failure
```

Every transition must be validated centrally and recorded as an event.

### `CustomerAdaGenesis`

This is the developing customer-specific identity artifact:

```json
{
  "schema_version": 1,
  "revision": 3,
  "business_world": {
    "purpose": "",
    "values": [],
    "customer_promises": [],
    "tensions": [],
    "language": []
  },
  "relationship": {
    "owner_preferences": [],
    "decision_style": "",
    "communication_preferences": [],
    "boundaries": []
  },
  "creative_identity": {
    "principles": [],
    "developing_tastes": [],
    "patterns_to_avoid": [],
    "open_questions": []
  },
  "research_identity": {
    "subjects": [],
    "communities": [],
    "candidate_feeds": [],
    "excluded_sources": []
  },
  "evidence": [
    {
      "field_path": "business_world.values",
      "origin": "owner_statement",
      "source_id": "message:12",
      "confidence": 1.0
    }
  ]
}
```

Origins are a closed enum:

- `owner_statement`
- `owner_correction`
- `owner_acceptance`
- `research_evidence`
- `ada_hypothesis`
- `ada_reflection`

Research evidence and Ada hypotheses cannot become owner-confirmed facts without
an owner acceptance event. A value may have multiple supporting or contradicting
evidence links.

### `ResearchSource`

```json
{
  "source_id": "src_opaque",
  "kind": "rss|atom|website|news_provider",
  "url": "https://...",
  "feed_url": "https://...",
  "title": "",
  "discovered_by": "owner|site_link|provider|ada",
  "trust_state": "candidate|allowed|excluded",
  "ongoing_subscription": "proposed|approved|rejected|not_applicable",
  "fetched_at": "ISO-8601",
  "content_hash": "sha256"
}
```

### `ResearchFinding`

```json
{
  "finding_id": "finding_opaque",
  "source_id": "src_opaque",
  "published_at": "ISO-8601 or null",
  "summary": "bounded factual excerpt or summary",
  "relevance": 0.0,
  "supports": [],
  "contradicts": [],
  "confidence": 0.0,
  "content_hash": "sha256"
}
```

### `CreativeEpisode`

This is the only engagement artifact permitted in Intake Ada's permanent
cross-customer memory:

```json
{
  "schema_version": 1,
  "episode_id": "episode_opaque",
  "created_at": "ISO-8601",
  "engagement_outcome": "accepted|rejected|expired",
  "design_fingerprint": {
    "layout_topology": [],
    "type_roles": [],
    "palette_shape": [],
    "motion_patterns": [],
    "navigation_pattern": "",
    "component_rhythm": []
  },
  "copy_fingerprint": {
    "opening_pattern": "",
    "section_rhythm": [],
    "cta_pattern": "",
    "repeated_motifs": []
  },
  "quality": {
    "accepted": false,
    "critic_categories": [],
    "revision_count": 0
  },
  "reflection": {
    "habits_repeated": [],
    "departures_that_worked": [],
    "approaches_to_avoid": [],
    "techniques_to_reuse_carefully": []
  },
  "semantic_text": "sanitized abstract description used for embedding",
  "sanitizer_version": 1
}
```

The contract must reject unknown keys, URLs, email addresses, phone numbers,
customer names, raw excerpts, asset paths, repository identifiers, domains, and
secrets. Sanitization failure means no global episode is written.

### `ProvisioningBundle`

```json
{
  "schema_version": 1,
  "bundle_id": "bundle_opaque",
  "incubation_id": "inc_opaque",
  "accepted_candidate_sha": "40-character SHA",
  "intake_revision": {},
  "genesis_revision": {},
  "conversation": [],
  "research_sources": [],
  "research_findings": [],
  "approved_feed_subscriptions": [],
  "assets": [],
  "design_history": [],
  "owner_feedback": [],
  "unknowns": [],
  "prohibited_claims": [],
  "integrity": {
    "content_hash": "sha256",
    "record_counts": {}
  }
}
```

The bundle is immutable after creation. Binary assets are referenced by content
hash and copied through a media adapter; they are not embedded in JSON.

### `ProvisioningReceipt`

```json
{
  "request_id": "provision_opaque",
  "bundle_id": "bundle_opaque",
  "customer_instance_id": "customer_opaque",
  "config_path": "validated host path",
  "database_path": "validated host path",
  "imported_counts": {},
  "bundle_hash": "sha256",
  "verified": true,
  "created_at": "ISO-8601"
}
```

## Persistence Model

### Intake Ada database

Add dedicated tables rather than mixing creative episodes into generic customer
observations:

- `creative_episodes`
- `creative_episode_vectors`
- `creative_fingerprint_terms`
- `intake_self_reflections`
- `incubation_registry`
- `provisioning_receipts`

`incubation_registry` contains only opaque IDs, lifecycle timestamps, status,
workspace path, bundle hash, and receipt ID. It must not contain customer names
or business content.

### Incubation database

The incubation store owns:

- conversations and chat messages
- durable jobs and job steps
- intake sessions and immutable revisions
- customer genesis revisions and evidence links
- research sources, findings, fetch attempts, and exclusions
- media metadata and customer asset bindings
- design runs, candidate SHAs, evidence, and feedback
- acceptance events and frozen provisioning bundles

Reuse `Memory` migrations and application methods where their semantics match,
but do not expose `Memory.conn` to incubation services. Add narrow methods for
new records. If reuse would couple Intake Ada tables to customer data, introduce
an `IncubationStore` adapter backed by a separate `Memory` instance.

### Customer database import

Provisioning must import through a `CustomerGenesisImporter` application
service. It should:

1. Initialize a new `Memory` database and run normal migrations.
2. Verify the provisioning bundle hash and accepted candidate SHA.
3. Import messages while preserving source timestamps and stable bundle-local
   references.
4. Import research as provenance-linked observations, not as trusted persona
   instructions.
5. Import approved feed subscriptions into generated config.
6. Import customer genesis as a genesis observation plus bounded initial
   self-model and work-persona state.
7. Import design lineage, owner feedback, and accepted candidate metadata.
8. Record one `provisioned_from_incubation` action with bundle and incubation IDs.
9. Verify counts and hashes before returning a receipt.
10. Start no scheduler and perform no publication during import.

## Intake Ada Memory and Novelty Retrieval

Use hybrid retrieval. The existing local deterministic embeddings in
`core/memory_store.py` may be extracted behind a reusable embedding contract,
but the new implementation must not query `Memory.conn` from an application
service.

Before a creative proposal or build:

1. Build a sanitized query from non-identifying creative requirements.
2. Retrieve the top semantic matches from `creative_episode_vectors`.
3. Retrieve structured matches for layout, typography, palette, motion,
   navigation, copy rhythm, and CTA pattern.
4. Produce a bounded `NoveltyContext` containing abstract tendencies and
   constraints, never previous customer content.
5. Include `NoveltyContext` in the design request and persist its episode IDs.
6. Require the design agent to explain any repeated high-similarity pattern from
   current customer evidence.

After a candidate is built:

1. Extract deterministic DOM/CSS/design-token fingerprints.
2. Extract copy structure and normalized phrase shingles.
3. Optionally extract screenshot perceptual hashes or visual embeddings behind a
   capability contract.
4. Compare the candidate against retrieved episodes and a bounded recent set.
5. Store similarity evidence in the incubation design run.
6. If a threshold is exceeded, create a review finding. Do not silently rebuild.
7. A repair or redesign remains an explicit application operation.

Vector similarity alone is insufficient. Semantic similarity, structured
fingerprints, exact phrase overlap, and visual similarity answer different
questions and must remain separate in diagnostics.

Initial thresholds must be configuration values with conservative defaults and
test fixtures. Do not claim a universal plagiarism threshold.

## Research Workflow

Introduce a narrow provider-neutral boundary:

```python
class FeedDiscoveryProvider(Protocol):
    def discover(self, query: ResearchQuery) -> tuple[DiscoveredSource, ...]: ...

class ResearchReader(Protocol):
    def read(self, source: ResearchSource) -> tuple[ResearchDocument, ...]: ...
```

Existing `senses.rss.fetch_feeds()` can back the RSS reader after transport,
size, redirect, timeout, and URL-safety behavior is made explicit. It should not
be called directly from a route or prompt policy.

Research sequence:

```text
owner facts reach minimum research readiness
  -> CustomerResearchPlanner proposes bounded queries
  -> owner exclusions and prior fetch hashes are applied
  -> FeedDiscoveryProvider finds candidate sources
  -> source policy rejects unsafe/private/local URLs
  -> ResearchReader fetches bounded public content
  -> deterministic normalization and deduplication
  -> LLM summarizes only supplied documents into typed findings
  -> findings are linked to sources and possible genesis/intake fields
  -> contradictions and uncertainty are shown to owner
  -> candidate ongoing feeds are proposed for approval
```

Minimum research readiness requires:

- a business offer or subject;
- a primary audience or market hypothesis;
- a location when the business is location-dependent;
- no unresolved owner correction that invalidates the research query.

Research limits:

- Maximum sources, items, bytes, redirects, and wall time per pass.
- One automatic pass before returning control to the owner.
- No private, loopback, link-local, metadata-service, credential-bearing, or
  non-HTTP(S) URLs.
- Deduplicate by canonical URL and content hash.
- Cache fetch results within the incubation only.
- Record failed fetches without treating absence as evidence.
- Never execute scripts or follow instructions from fetched content.

## Customer Personality Formation

Add `CustomerGenesisService` in `application/`. It owns revision creation and
provenance validation; the LLM advisor only proposes typed changes.

The service receives:

- current `DesignIntakeDraft`;
- current `CustomerAdaGenesis`;
- owner-message snapshot;
- bounded research findings;
- owner feedback and accepted/rejected recommendations;
- current design lineage;
- host-owned immutable identity constraints.

It returns a proposed genesis turn containing:

- field updates with origins and evidence IDs;
- contradictions;
- developing creative tendencies;
- questions Ada is carrying;
- a short owner-facing explanation of what changed.

The application service must enforce:

- Owner corrections replace conflicting hypotheses and preserve an audit link.
- Research can support a value but cannot impersonate owner acceptance.
- Brand adjectives alone do not become an invented biography.
- Customer content may shape the new Ada's developing interests and taste.
- Host safety and privacy rules cannot be changed by genesis updates.
- Every revision is immutable and hash-addressed.
- The accepted genesis revision is frozen into the provisioning bundle.

The customer Ada's initial effective context should be layered as:

```text
host-owned identity and safety constraints
customer-Ada genesis and developing self-model
customer work persona and owner-approved voice
sourced customer research and recalled customer memories
current task and conversation
```

These layers are assembled by code. Do not ask the LLM to infer which text has
higher authority.

## Application Services

Add or extract these narrow services:

| Service | Responsibility |
|---|---|
| `IntakeAdaMemoryService` | Recall and record sanitized creative episodes and Intake Ada reflections. |
| `IncubationApplicationService` | Create, load, transition, reject, expire, and summarize incubations. |
| `IncubationConversationService` | Enqueue durable owner turns against one incubation. |
| `CustomerResearchService` | Plan bounded research, call discovery/read adapters, and persist typed evidence. |
| `CustomerGenesisService` | Propose and save provenance-linked customer-Ada genesis revisions. |
| `NoveltyService` | Retrieve prior creative patterns and evaluate candidate similarity. |
| `ProvisioningBundleService` | Freeze and validate one immutable accepted bundle. |
| `CustomerProvisioningService` | Create/import/verify one customer instance idempotently. |

Existing `DesignService`, `DesignJobExecutor`, media services, preview cache, and
quality adapters remain the design implementation path. They receive an
incubation-scoped store and neutral scaffold. They must not receive Intake Ada's
database or a production customer database.

## File-Level Change Plan

Prefer behavior-preserving extraction from the current Intake Lab over a rewrite.
Keep existing public paths stable until their compatibility tests can be removed
in a separately approved cleanup.

### Add `src/site_agent/core/incubation_contracts.py`

- Define the lifecycle enums and typed contracts in this plan.
- Validate transitions, opaque IDs, content hashes, timestamps, provenance, and
  payload limits.
- Keep provider payloads and database rows out of the public contract.

### Modify `src/site_agent/config.py`

- Add a typed `IntakeAdaSettings` projection and strict intake-mode validation.
- Reject customer-only configuration when `role: intake` is active.
- Validate that Intake Ada, incubation, and customer roots are disjoint.
- Keep secret resolution centralized and return only environment-variable names
  to generated customer configs.

### Modify `src/site_agent/main.py`

- Compose Intake Ada from the neutral config only.
- Open the permanent Intake Ada store separately from incubation stores.
- Remove `--intake` and customer-config source-baseline behavior from product
  startup; retain fixture seeding only in test-only helpers if still needed.
- Construct application services and adapters explicitly.
- Keep loopback enforcement until authenticated remote hosting has its own plan.

### Add `src/site_agent/application/intake_ada_memory.py`

- Own sanitized episode recall, insertion, and Intake Ada reflection state.
- Depend on a narrow store contract rather than raw SQLite access.
- Return bounded `NoveltyContext` objects to design workflows.

### Add `src/site_agent/application/incubations.py`

- Own incubation creation, registry updates, lifecycle transitions, retention,
  and scoped store resolution.
- Refuse cross-incubation IDs at every boundary.
- Coordinate services without implementing their research or design policy.

### Modify `src/site_agent/application/design_intake.py`

- Bind every session and job to an `incubation_id`.
- Remove the concept of a configured default customer intake from product mode.
- Continue to own partial intake drafts, provenance, confirmation, and immutable
  revisions.
- Delegate customer-genesis changes instead of mixing them into `SiteIntake`.

### Add `src/site_agent/application/customer_genesis.py`

- Own genesis revisions, evidence validation, corrections, and acceptance.
- Assemble the customer-specific identity layers used by design and provisioning.
- Never write Intake Ada's permanent store.

### Add `src/site_agent/application/incubation_research.py`

- Own research readiness, query planning, source policy, deduplication,
  contradiction retention, and proposed feed subscriptions.
- Call only the `FeedDiscoveryProvider` and `ResearchReader` contracts.
- Store complete findings only in the selected incubation.

### Add `src/site_agent/application/novelty.py`

- Build sanitized retrieval queries.
- Combine semantic, structured, phrase-overlap, and optional visual comparisons.
- Persist candidate similarity evidence in the incubation design run.
- Produce the sanitized `CreativeEpisodeCandidate` after terminal engagement.

### Add `src/site_agent/application/provisioning.py`

- Freeze provisioning bundles and execute idempotent customer creation/import.
- Generate validated config through a dedicated serializer.
- Return typed receipts and leave activation as an explicit final operation.

### Modify `src/site_agent/core/memory.py`

- Add migrations and narrow methods for incubation-owned genesis and research
  records where the existing `Memory` schema is reused.
- Add import methods that preserve provenance without accepting arbitrary SQL or
  raw rows.
- Do not add Intake Ada's cross-customer tables to every customer database if a
  dedicated `IntakeAdaStore` is cleaner.

### Add `src/site_agent/core/intake_ada_store.py`

- Own Intake Ada's permanent SQLite schema and queries.
- Store only registry metadata, creative episodes, vectors, fingerprints,
  reflections, and provisioning receipts.
- Expose typed methods; keep its connection private.

### Refactor `src/site_agent/core/memory_store.py`

- Extract deterministic embedding and cosine operations behind reusable pure
  functions or an `EmbeddingProvider` contract.
- Preserve existing customer-memory behavior and stored vector compatibility.
- Do not make application services access `Memory.conn`.

### Add `src/site_agent/hands/feed_discovery.py`

- Implement candidate feed discovery behind `FeedDiscoveryProvider`.
- Apply URL and transport policy before returning normalized sources.
- Keep provider credentials and response shapes inside the adapter.

### Refactor `src/site_agent/senses/rss.py`

- Implement the bounded `ResearchReader` behavior or wrap it from a new hands
  adapter.
- Add explicit timeout, redirect, response-size, URL, and parse-error results.
- Preserve current scheduled customer RSS behavior through compatibility tests.

### Add a neutral scaffold under package data

- Provide no customer copy, palette, imagery, domain, routes, or industry cues.
- Keep the scaffold functional at desktop and mobile sizes.
- Allow `DesignService` to clone/copy it into one incubation run without a remote.
- Version and hash it so build jobs bind to an exact scaffold revision.

### Modify `src/site_agent/application/intake_lab.py`

- Reduce it to compatibility composition/projection or replace it with the new
  incubation service behind existing routes.
- Remove customer repository resolution and configured customer defaults.
- Keep all build targets non-publishable.

### Modify `src/site_agent/web/intake_lab.py`

- Translate canonical incubation routes to application calls.
- Resolve one `incubation_id` before any operation.
- Return typed projections and durable IDs without exposing storage paths.
- Keep preview routing scoped to exact incubation, run, variant, and SHA.

### Modify `src/site_agent/web/static/intake_lab.html`

- Display research evidence, genesis changes, hypotheses, provenance, feed
  approval, novelty findings, acceptance, and provisioning status.
- Never display another engagement's creative episode or Intake Ada reflection.
- Preserve the no-build frontend and responsive behavior.

### Add focused tests

- `tests/test_intake_ada_config.py`
- `tests/test_intake_ada_store.py`
- `tests/test_incubation_service.py`
- `tests/test_customer_genesis.py`
- `tests/test_incubation_research.py`
- `tests/test_intake_ada_novelty.py`
- `tests/test_customer_provisioning.py`
- `tests/test_incubation_web.py`
- `tests/test_incubation_isolation.py`

Update existing intake, design, memory, CLI, preview, and package-data tests as
each behavior moves. Do not delete regression coverage merely because a route is
temporarily implemented by a compatibility adapter.

## Job Model

Keep customer operations durable without placing them in Intake Ada's own chat
queue.

New incubation job kinds:

- `incubation_advice`
- `incubation_research`
- `incubation_genesis_update`
- `incubation_design_build`
- `incubation_novelty_check`
- `incubation_provision`

Rules:

- Every job belongs to exactly one `incubation_id`.
- Owner-message jobs bind to an immutable source message ID.
- Research jobs bind to a query hash and source-policy version.
- Build jobs bind to intake, genesis, novelty-context, and scaffold hashes.
- Provisioning jobs bind to accepted candidate SHA and bundle hash.
- Idempotency keys are unique within the incubation and operation kind.
- Interrupted reads may be retried explicitly. Website builds and provisioning
  are never replayed implicitly.
- Completed jobs remain inspectable by ID even after leaving active listings.

Intake Ada's post-engagement reflection is a separate permanent-memory job. It
receives only the already-sanitized `CreativeEpisode` candidate.

## HTTP API Contract

Keep current intake-session aliases during migration, but make incubation the
canonical resource. Routes translate HTTP only.

Proposed endpoints:

```text
POST   /api/incubations
GET    /api/incubations/{incubation_id}
POST   /api/incubations/{incubation_id}/messages
POST   /api/incubations/{incubation_id}/research
GET    /api/incubations/{incubation_id}/research
PATCH  /api/incubations/{incubation_id}/research/sources/{source_id}
GET    /api/incubations/{incubation_id}/genesis
POST   /api/incubations/{incubation_id}/confirm-intake
POST   /api/incubations/{incubation_id}/builds
POST   /api/incubations/{incubation_id}/feedback
POST   /api/incubations/{incubation_id}/accept
POST   /api/incubations/{incubation_id}/provision
POST   /api/incubations/{incubation_id}/activate
GET    /api/incubations/{incubation_id}/provisioning
DELETE /api/incubations/{incubation_id}
```

Mutation responses return the durable job, revision, bundle, or receipt ID.
They do not claim success before the application service persists the state.

The browser must display:

- current incubation status;
- confirmed owner facts versus hypotheses;
- research sources, dates, confidence, and contradictions;
- proposed ongoing feeds with approve/reject controls;
- customer-Ada genesis summary and revision;
- novelty warnings in owner-readable language;
- design candidate and feedback state;
- explicit acceptance and provisioning controls;
- retention/deletion state.

Do not expose Intake Ada's private cross-customer memory or prior episode details
in a customer browser response.

## Provisioning Workflow

Provisioning is an application workflow, not a shell script called from a route.

```text
owner accepts candidate
  -> validate candidate SHA and current revisions
  -> create immutable ProvisioningBundle
  -> reserve customer_instance_id using idempotency key
  -> create destination root with restrictive permissions
  -> generate validated config from approved bundle fields
  -> initialize destination memory.db through Memory migrations
  -> copy content-addressed approved assets
  -> import conversation, evidence, genesis, and design lineage
  -> verify bundle hash, record counts, and destination identifiers
  -> persist ProvisioningReceipt in both registries
  -> mark incubation provisioned
  -> enable normal customer runtime startup
  -> sanitize and record Intake Ada CreativeEpisode
```

Generated customer config may include:

- stable instance ID and display name;
- customer data and media paths;
- approved work persona and audience;
- approved RSS subscriptions and research keywords;
- site adapter configuration only when separately supplied and approved;
- model/provider environment-variable names selected by host policy;
- conservative default schedules, initially disabled until activation if needed.

Generated customer config must not include:

- another customer's values;
- Intake Ada's private reflections or memory;
- raw secrets;
- unapproved feeds;
- invented repository, domain, analytics, or deployment identifiers;
- an automatically enabled publication path.

## Creative Episode Sanitization

Sanitization is a security boundary and must be deterministic before any LLM
reflection is accepted.

Implement:

1. A strict allowlist serializer from design evidence into
   `CreativeEpisodeCandidate`.
2. Detection and rejection for URLs, domains, emails, phone numbers, filesystem
   paths, repository names, opaque customer IDs, and long copied phrases.
3. Normalization of business-specific nouns into abstract design categories.
4. Phrase-overlap checks against customer messages and generated website copy.
5. Maximum field and payload sizes.
6. A second typed parse after any LLM-generated reflection.
7. A final provenance-free `CreativeEpisode` hash before persistence.

If sanitization is uncertain, retain nothing globally and record a local
diagnostic in the incubation. Privacy wins over Intake Ada's desire to remember.

## Migration Strategy

### Phase 0: Safety stop

- Stop the current Intake Lab process from using any real customer config.
- Add a neutral startup config and neutral scaffold.
- Add startup validation that rejects customer-specific configuration.
- Remove real-customer fixtures from generic docs, examples, and tests.
- Verify no production customer database or repository is opened by Intake Ada.

### Phase 1: Split persistence domains

- Introduce permanent Intake Ada storage and incubation registry.
- Introduce one physical incubation store per `incubation_id`.
- Move existing intake sessions, jobs, media, and design runs behind an
  incubation-scoped application service.
- Preserve existing public routes as compatibility adapters where practical.
- Add expiration and explicit purge workflows.

### Phase 2: Customer genesis

- Add `CustomerAdaGenesis`, evidence contracts, and immutable revisions.
- Extend the intake advisor to propose genesis updates separately from business
  facts.
- Add owner correction and acceptance UI.
- Include the current genesis in design context snapshots.

### Phase 3: Bounded news and RSS research

- Add feed discovery and reader capability contracts.
- Wrap existing RSS fetching behind the research service.
- Add URL policy, limits, caching, deduplication, and source provenance.
- Add typed finding extraction and contradiction handling.
- Add feed subscription approval controls.

### Phase 4: Persistent Intake Ada novelty memory

- Add creative episode schemas and sanitization.
- Extract reusable local embedding support without direct application-level SQL.
- Add structured design and copy fingerprints.
- Recall novelty context before builds.
- Add post-build similarity checks and Intake Ada reflections.

### Phase 5: Provisioning bundle and customer import

- Add immutable bundle and receipt contracts.
- Implement idempotent destination reservation and config generation.
- Import complete customer state into a newly migrated customer database.
- Verify import before marking provisioned.
- Record sanitized Intake Ada episode only after terminal handoff.

### Phase 6: Activate the customer Ada

- Add an explicit activation operation after provisioning verification.
- Start the normal customer runtime and scheduler against the new config and DB.
- Confirm customer Ada can recall incubation conversations, research, design
  feedback, and genesis evidence.
- Confirm Intake Ada cannot retrieve that customer-specific content.

Do not implement later phases by bypassing unfinished earlier boundaries. In
particular, do not add research or novelty memory while Intake Ada still loads a
real customer configuration.

## Testing Strategy

Start each phase with a failing focused test or reproducible API request.

### Configuration isolation

- Intake Ada starts from a neutral config with no customer repository or persona.
- Startup rejects a config containing customer site, analytics, deployment, or
  business-source fields.
- The model child environment contains only explicit provider credentials.
- A known real-customer identifier does not appear in Intake Ada API metadata,
  prompts, scaffold files, or generated config fixtures.

### Persistence isolation

- Two incubations use distinct database files and cannot query each other's IDs.
- Intake Ada memory cannot resolve incubation messages, findings, or assets.
- Restart preserves Intake Ada episodes and each active incubation independently.
- Reject and expiry purge only the selected incubation.
- Purging an incubation cannot delete Intake Ada's permanent memory.

### Conversation and genesis

- An owner statement creates linked intake and genesis evidence.
- A research hypothesis is never projected as owner-confirmed.
- An owner correction supersedes but does not erase prior provenance.
- A genesis revision cannot alter host-owned safety constraints.
- Design context snapshots bind exact intake and genesis revision hashes.

### Research

- Unsafe URLs, excessive redirects, oversized feeds, and unsupported schemes are
  rejected before network access.
- Duplicate feed entries collapse by canonical URL or content hash.
- Feed instructions cannot alter system policy or invoke tools.
- Contradictory findings remain visible and linked to both sources.
- Approved subscriptions enter the bundle; proposed or rejected ones do not.
- Failed feeds record diagnostics without becoming negative evidence.

### Novelty memory

- Similar sanitized episodes are found through semantic recall.
- Structurally similar layouts are found when semantic descriptions differ.
- Reused copy phrases are detected independently of vector similarity.
- Retrieval returns abstract patterns, not prior customer text.
- Sanitizer rejects customer names, domains, URLs, emails, paths, and copied
  phrases.
- Sanitization failure produces no global write.
- Current owner requirements outrank novelty recommendations.

### Provisioning

- Provisioning requires an accepted candidate SHA and explicit owner action.
- Repeating one provisioning idempotency key creates one customer instance.
- Bundle hash or count mismatches block activation.
- Import preserves conversation, research provenance, genesis, and design history.
- The generated config includes only approved feeds and validated settings.
- No scheduler or publisher starts before import verification.
- A failed import leaves the incubation resumable.
- A successful import returns matching receipts in the registry and destination.

### End-to-end acceptance

Run a complete synthetic journey with no real customer names:

```text
create incubation
  -> discuss a fictional ceramics studio
  -> discover and read synthetic local RSS fixtures
  -> produce research-linked genesis revisions
  -> build from neutral scaffold
  -> reject one repetitive direction
  -> accept a revised candidate
  -> provision customer Ada
  -> restart customer runtime
  -> recall incubation evidence from customer DB
  -> verify Intake Ada recalls only sanitized creative pattern
  -> verify a second incubation receives novelty guidance without first-customer data
```

## Observability

Diagnostics must include the relevant opaque identifiers:

- `incubation_id`
- `job_id`
- `conversation_id`
- `intake_revision`
- `genesis_revision`
- `research_source_id`
- `design_run_id`
- `candidate_sha`
- `bundle_id`
- `customer_instance_id`
- `provisioning_request_id`
- `creative_episode_id`

Never log raw secrets, full owner messages, fetched documents, or binary asset
content in cross-customer process logs.

Add metrics for:

- active, accepted, rejected, expired, and provisioned incubations;
- research fetch success, failure, deduplication, and source exclusions;
- genesis revisions and owner corrections;
- novelty retrieval latency and similarity findings;
- sanitizer rejection reasons;
- provisioning duration, retries, failures, and verified imports.

## Security and Privacy Checklist

- [ ] Intake Ada uses a neutral config and neutral scaffold.
- [ ] No customer database is opened by the Intake Ada memory service.
- [ ] Every incubation has a separate physical storage root.
- [ ] All external URLs pass SSRF and size-limit policy before fetch.
- [ ] Research content is marked untrusted and cannot become instructions.
- [ ] Owner statements retain the highest customer-fact authority.
- [ ] Cross-customer memory accepts only validated `CreativeEpisode` records.
- [ ] Creative episodes contain no identifying or raw customer content.
- [ ] Provisioning is explicit, idempotent, hash-bound, and auditable.
- [ ] Generated configs contain environment references, never secret values.
- [ ] Customer runtimes cannot access Intake Ada or another customer database.
- [ ] Rejection and expiration have tested purge behavior.
- [ ] No incubation operation can publish or mutate production.

## Definition of Done

This plan is complete only when all of the following are true:

1. Intake Ada starts without loading any real customer configuration, database,
   repository, persona, research sources, domain, or credentials.
2. Intake Ada has permanent, restart-safe creative memory containing only
   sanitized cross-project episodes.
3. Every prospective customer has isolated, durable, resumable incubation state.
4. Intake Ada performs bounded, source-linked news and RSS research during
   incubation without converting research into owner facts.
5. Business values, customer understanding, creative taste, owner relationship,
   and research interests form an immutable, provenance-linked customer-Ada
   genesis history.
6. Novelty retrieval informs designs and copy, and post-build checks expose
   repetition without leaking previous customer material.
7. Explicit owner acceptance freezes a complete provisioning bundle.
8. Provisioning creates a new customer config and database and imports the full
   customer-specific incubation history idempotently.
9. The provisioned customer Ada resumes from incubation with her own persistent
   memory, genesis, research, design history, and owner relationship.
10. Intake Ada retains only the sanitized creative lesson and cannot retrieve
    customer-specific records after handoff.
11. Rejected and expired incubation data follows the configured purge policy.
12. Focused tests, the full suite, compileall, wheel build, and package import
    smoke test pass.

## Required Verification Commands

```bash
.venv/bin/pytest -q tests/test_intake_ada_config.py
.venv/bin/pytest -q tests/test_incubation_service.py
.venv/bin/pytest -q tests/test_customer_genesis.py
.venv/bin/pytest -q tests/test_incubation_research.py
.venv/bin/pytest -q tests/test_intake_ada_novelty.py
.venv/bin/pytest -q tests/test_customer_provisioning.py
.venv/bin/pytest -q tests/test_incubation_web.py
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
```

Also run `git diff --check` and import `site_agent` from the built wheel in a
clean temporary virtual environment. Do not commit databases, incubation
workspaces, research caches, screenshots, generated customer configs, secrets,
or build artifacts.

## Recommended First Pull Request

Keep the first change intentionally narrow:

1. Add the neutral Intake Ada config contract and startup validation.
2. Add a host-owned neutral website scaffold.
3. Remove customer-config and customer-repository use from Intake Lab startup.
4. Introduce separate permanent Intake Ada and per-incubation storage roots.
5. Route existing conversational intake through one `incubation_id` without yet
   adding research, genesis, novelty retrieval, or provisioning.
6. Add isolation and no-customer-identifier regression tests.

This establishes the security and ownership boundary before adding intelligence
that depends on it.
