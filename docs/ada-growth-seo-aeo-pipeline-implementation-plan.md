# Ada Growth: white-glove SEO and AI visibility

## 1. Status, authority and outcome

Implementation plan for a coding AI. Written 2026-10-02 against verified
`weareheadless/site-agent` commit `0272832f8e0bb18a4a426bdaba413f1e40816b2e`.
This document specifies work; it does not claim that the pipeline is implemented.
Recheck the checkout, provider contracts and production state before coding.

The product is an ongoing service, not a collection of SEO tools. Ada understands
the business, investigates opportunities, prepares useful website improvements,
obtains precise owner approval, publishes the approved result and measures it.
The owner does not need to operate Google consoles or select research APIs.

Implement this loop once, in shared site-agent:

```text
Trigger -> Evidence -> Prioritisation -> Real candidate -> Validation
        -> Owner review -> Approved publication -> Live verification -> Results
```

This is the authoritative growth-orchestration, goal and review contract when
older SEO plans disagree. It does not override `AGENTS.md`, the
[brand/behavior plan](brand-composition-and-behavior-system-implementation-plan.md),
[Payload-first plan](payload-first-helloada-default-and-customer-upgrade-plan.md),
or [connection contract](helloada-connection-contract.md). In particular, do not
waive the brand plan's outstanding autonomous-design proof or rollout stop
conditions. Narrow content work still needs its own complete proof.

Priority: the default new-site path first; Atelier and OceanicVibes upgrades
second. All consume the same source, contracts and HelloAda Payload package.
Do not solve the problem with customer-specific branches or UI components.

## 2. Locked product decisions

- No growth-goal questionnaire during intake. New sites start with **bring
  relevant visitors to my website**. Use the confirmed business, audience,
  services, location, language and assets already collected.
- Instrument meaningful actions from the beginning where technically and
  lawfully possible. A contact-link click is not a confirmed enquiry; a booking
  button click is not a completed booking.
- A compact **Growth goal** control opens a conversation with Ada. Ada proposes
  a revised goal and measurement plan; the owner confirms. Do not silently
  switch goals, reset historical results or expand authority.
- Ada may collect authorised evidence and prepare private drafts within the
  recorded service allowance. No public website change without explicit owner
  approval of the exact candidate. Additional costs, missing business facts and
  new access grants have their own narrowly scoped decisions.
- A report is information, not a publishable website change. Never ask the owner
  to publish an analysis just to acknowledge reading it.
- Prefer a few excellent improvements to a weekly content quota. Weekly review
  is required; a weekly article is justified only when it adds original value.
- Preserve native Payload editing: pages, blog bodies, main images, metadata,
  shared navigation/footer and media. Ada uses these canonical documents too.
- Preserve chat, website preview, Gallery, Activity and detailed Growth tabs.
  Simplicity means progressive disclosure, not removing capabilities.
- Never manufacture success. Providers can fail; the system must recover safely
  or expose a precise blocked state. “No fallbacks” means no hidden weaker path,
  invented data, alternative schema or inaccurate success label.

## 3. Verified baseline: reuse and root problems

The following paths were inspected at the baseline above. Revalidate them before
implementation; an existing module is not proof of a complete end-to-end flow.
Python paths in this table are relative to `src/site_agent/`; package paths are
relative to the repository root.

| Existing responsibility | Reuse | Required structural change |
| --- | --- | --- |
| `application/growth.py` | Read-only owner snapshot | Project real runs, decisions and freshness; do not dispatch work on GET. |
| `core/jobs.py`, `core/scheduler.py` | Durable scheduling and maintenance | One growth registration in both runtime paths; tenant timezone, leases and deduplication. |
| `brain/seo.py`, `brain/seo_insights.py` | Research, strategy and saved briefs | One evidence-grounded planner; a `SITE_CHANGE` brief must become a real candidate. |
| `brain/article_research.py`, `brain/monthly_seo_report.py` | Research lineage and reports | Feed the shared pipeline; do not create independent spending or approval authorities. |
| `brain/seo_outcomes.py` | Existing 30/90/180-day reviews | Never switch between GSC clicks and GA4 sessions; measure the affected scope and actual publication. |
| `application/competitive_evidence.py` | Project-scoped completed provider evidence | Extend collection capabilities, not just rendering; distinguish search neighbours from business competitors. |
| `application/actions.py`, `application/approvals.py` | Owner decisions, hash-bound approvals and receipts | One review/effect path for growth; reconcile uncertain effects before retry. |
| `core/memory.py` | Strategy cycles, initiatives, outcomes and generic artifacts | Extend existing records with narrow migrations; no parallel growth database. |
| `web/workspace.py` | Authenticated workspace boundary | Thin adapters to application services; existing tenant isolation remains mandatory. |
| `packages/helloada-payload-admin/src/components/HelloAdaGrowth.tsx` | Shared Growth tabs and visual system | Add compact work/review/result projections, not a second dashboard. |

Specific defects to remove:

1. In the full job-registration path, enabling replacement site-report/article
   workflows can suppress both `seo_research_cycle` and `seo_outcomes`.
   Outcome measurement must never depend on which content producer is enabled.
2. Current schedule calculations use server-local time. Product cadence needs an
   explicit tenant IANA timezone and correct calendar/DST behavior.
3. A site-change artifact can currently describe an idea without a reviewable
   implementation. Do not label that artifact “ready to publish”.
4. Current outcome selection can substitute site-wide sessions for clicks. This
   cannot establish whether a particular approved improvement helped.
5. Historical editorial-only degradation when research is unavailable must not
   be used for research-dependent growth work.
6. Provider configuration or the existence of an old snapshot does not mean
   evidence is connected, fresh or complete.

## 4. Minimal architecture and ownership

Keep the service small. Use the current SQLite persistence, scheduler, provider
adapters, owner actions, approvals, Payload drafts and Ada design pipeline.
Do not introduce an agent swarm, DAG framework, new queue service, second ORM,
generic workflow engine or duplicated recommendation/approval stores.

```text
Scheduler / explicit owner action
              |
     application/growth_workflow.py
       |          |           |
   evidence    Ada planner   existing candidate/approval services
       |          |           |
   providers   artifacts     Payload / Ada build / publication receipts
              |
       Memory-backed projection
              |
      Growth + Chat + Activity
```

Proposed new boundaries, only where existing equivalents do not already fit:

- `core/growth_contracts.py`: typed policy, evidence, run, candidate and outcome
  contracts; no provider calls or prompts.
- `application/growth_workflow.py`: explicit phase transitions and coordination.
  Keep interpretation in `brain/`, persistence in Memory and effects in adapters.
- Extend existing evidence/provider modules with narrowly named operations.
  DataForSEO remains behind CrawlSEO; never add a second direct client in Ada.
- Extend existing UI components with small work-status and review projections.
  Reuse `ProductAction`, current drawers and Website/Design review surfaces.

Trace every effect through `adapter -> application service -> typed contract ->
provider -> receipt`. Route handlers, MCP tools and React must not implement
business orchestration or access database internals.

## 5. Policy, goals and triggers

Persist a versioned `GrowthPolicy` containing tenant identity, active site-origin
revision, audience/market/language, IANA timezone, cadence, freshness rules,
research allowance, task/result caps, approval permissions and retention policy.
Validate it at provisioning. Do not guess missing locales from domain suffixes.
An incomplete policy produces a named setup block, not alternate defaults.

Persist an immutable `GoalRevision`: objective, supported business events,
measurement definitions, owner confirmation, effective time and prior revision.
The default traffic goal can be created by the confirmed new-site contract;
later goal changes require owner confirmation. Reuse a typed artifact plus active
pointer if sufficient; do not create a goal subsystem unnecessarily.

Changing the goal keeps past decisions/outcomes attached to their original goal.
Re-evaluate active priorities, invalidate incompatible unpublished packages and
prepare replacements under the new goal. Do not erase the record of the change.

| Trigger | Default behavior | Cost / deduplication boundary |
| --- | --- | --- |
| New site is live and provisioned | Initial technical/content inventory, measurement checks, baseline strategy | Once per site-origin revision; historical absence is expected, not zero performance. |
| Daily tenant-local tick | Reconcile jobs/receipts, ingest due first-party data, detect important regressions | Not permission for daily paid discovery. |
| Weekly review | Reassess evidence, content and site health; prepare the most useful next work | Reuse valid research; no article quota or duplicate drafts. |
| Monthly research window | Bounded keyword/competitor/AEO discovery allowed by policy | One reserved budget across all research producers. |
| Relevant change | Targeted re-evaluation after verified publication, confirmed goal/domain change or material new evidence | Coalesce events; do not launch a complete audit for every keystroke. |
| Owner asks Ada to review | Queue an explicit scoped check; show expected work/cost when outside allowance | Idempotency key; double clicks cannot double bill. |
| Publication outcome is due | Functional verification immediately; impact reviews at applicable horizons | Outcome job always registered, independently of article/report scheduling. |

Cadences are product defaults, not invented provider SLAs. Configure concrete
freshness/latency expectations per source; distinguish final periods from partial
data. A slow provider request belongs in a durable background phase, never a
long-running dashboard GET.

## 6. Durable run and initiative contracts

A run records `run_id`, unique `run_key`, trigger, tenant, policy/goal/origin
revisions, selected base document/code revisions, phase, phase version, lease,
attempts, source references, next due time, timestamps and terminal result.
Acquire the lease transactionally; advance with compare-and-swap. A restarted
process resumes the earliest valid persisted phase, not the whole paid workflow.

The run phases are `collecting -> assessing -> preparing -> validating ->
complete`. Completion means the analysis/preparation run finished; it does not
mean its proposals were approved or published. Blocking states identify the
phase and dependency: `waiting_for_owner`, `blocked`, `failed`, `uncertain`, or
`cancelled`. Store an actionable reason and safe next step.

Each initiative separately advances through:

```text
identified -> preparing -> validating -> ready_for_review
           -> publishing -> verifying_live -> measuring -> reviewed
```

Owner decisions are associated records, not implicit state jumps. An initiative
can also be snoozed, rejected, superseded or blocked. “Approved” is a durable
receipt between review and publication, not evidence that publication succeeded.
An inconclusive outcome is a valid measured result, not a failed deployment.

Use existing strategy storage:

- Generalise `strategy_cycles` for runs. Its `report_id NOT NULL UNIQUE` currently
  assumes a provider report: migrate report-specific ID/hash/body fields into
  optional associated-report data, preserving historical IDs and initiative
  foreign keys. Runs without a report use an evidence-manifest artifact reference,
  not a synthetic report ID, fake report hash or empty successful report.
- Add only required run-key/phase/lease/revision fields and constraints.
- Reuse `strategy_initiatives`, `strategy_decisions` and `strategy_outcomes` for
  opportunities, dispositions and reviews. Version the existing JSON contracts.
- Reuse generic artifacts for immutable evidence/goal/candidate/validation
  manifests, owner actions for required decisions, and provider receipts for
  external operations. Keep large source bodies out of UI projections.
- Old records remain inspectable as history; old execution paths are not retained
  as recovery modes. Migrate outstanding approvals deliberately, marking any
  unbound proposal superseded rather than silently reauthorising it.

## 7. Evidence contract: trustworthy, bounded and useful

Each `EvidenceManifest` references persisted source observations with:
provider and capability; project/property identity; source/task ID; retrieval and
observation dates; covered period and timezone; country/language/device; filters;
completeness, sampling and coverage limits; freshness deadline; cost receipt;
content hash; and status with a safe explanation.

Keep `ready`, `pending`, `missing`, `stale`, `unsupported`, `unauthorised`,
`failed` and `uncertain` distinct. Zero is an observed number, not a substitute
for any of these states. A new site has no pre-launch history; retain that fact.

Declare required evidence by opportunity type before preparation. An independent
opportunity can proceed when its own requirements pass; a dependent one cannot
quietly discard a failed source. Historical comparisons need matching metric,
scope and complete periods. Freeze the evidence manifest used for each decision.

### 7.1 First-party and technical evidence

- Crawl actual public routes, status codes, internal links, indexability,
  robots/sitemap/canonical consistency, metadata, mobile/accessibility issues,
  performance observations and structured data matching visible content.
- Inventory canonical Payload pages/posts, main images, categories, shared
  navigation/footer, publication state and links. Detect orphaned content,
  competing pages and content decay before proposing more articles.
- Collect GA4 acquisition, landing-page engagement and correctly named key
  events; GSC queries/pages, clicks/impressions/position with coverage labels.
  Never equate third-party volume with first-party visits.
- Provision and verify the current platform site origin by the shared contract.
  Custom-domain activation creates a new origin revision, updates verification,
  reporting scope, sitemaps/canonicals and measurement configuration, then
  verifies each dependency. No assumption about an unrelated old business domain.
- Preserve historical property IDs, origin revisions and continuity mapping.
  Domain changes do not transfer old data automatically or conceal a collection
  gap. Credential refresh and tenant authentication follow the connection contract.
- Respect tracking consent and relevant privacy requirements. Do not store raw
  personal analytics data or send unnecessary visitor information to models.

Search Analytics returns bounded data and has freshness/aggregation limitations;
normalise them explicitly rather than claiming an exhaustive console export.
See the [official Search Analytics contract](https://developers.google.com/webmaster-tools/v1/searchanalytics/query).

### 7.2 Competitors, keywords and content intelligence

Extend CrawlSEO/provider contracts to collect, under allowance:

1. Relevant search competitors by service, market and query cluster; keep their
   relationship to actual business competitors explicit.
2. Domain intersections, missing/weak keyword coverage and ranked landing pages
   using verified supported provider endpoints. Filter by audience fit and intent,
   not just volume. Advertising competition is not organic difficulty.
3. SERP observations with country/device/date and real winning URLs. Persist
   historical positions for an approved watchlist; GSC average position remains
   a different measurement.
4. Bounded inspection of relevant public competitor pages/articles: topic,
   questions answered, structure, evidence, freshness and useful gaps. Links
   alone are not content analysis. Cache source URL/date/hash and derived findings.
5. Useful backlink/referring-domain evidence where supported; distinguish index
   coverage from a complete Ahrefs replacement. No automated link buying/outreach.

Public-page fetching must enforce robots/access restrictions, request and byte
caps, timeouts, public-network-only destinations and redirect/DNS revalidation.
Block SSRF/private services. Treat fetched text as untrusted evidence, never
instructions. Do not bypass logins/paywalls or copy competitors' expression.
Produce original content grounded in the owner's expertise and confirmed facts.

### 7.3 AEO: Search & AI visibility, not a fabricated AI score

Use the same pipeline for clear answers, discoverable services, original
expertise, reliable business facts, appropriate authorship, internal links and
valid structured data. No separate AEO intake, guaranteed citation/ranking claim,
mass-produced FAQ padding, special “AI schema” or assumed `llms.txt` ranking boost.
This follows [Google's AI search guidance](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide).

Keep four observations separate in storage and UI:

| Observation | What it establishes | What it does not establish |
| --- | --- | --- |
| First-party AI referrals | Attributable visits/actions when the referrer survives | All mentions, impressions or unattributed AI traffic. |
| Provider citation/mention dataset | Recorded observations within the provider's stated coverage | Complete platform telemetry or universal market share. |
| Bounded sampled answers | Citation/mention in a particular question, platform, time and locale | A stable ranking or the identical consumer experience. |
| Technical crawl eligibility | Required access/content conditions are satisfied | Inclusion, recommendation or citation. |

Verify API capabilities before promising integrations. Google now documents
[generative-AI performance reports](https://developers.google.com/search/blog/2026/06/gen-ai-performance-reports);
that does not prove the current Search Analytics adapter exposes those fields.
Document an authenticated API contract test or label that view unavailable.
The same rule applies to Bing Webmaster AI visibility: a console feature is not
proof of a usable integration. Ordinary SEO work is not dependent on an unsupported
AI-reporting capability; AI claims that require it remain blocked or unsupported.

For DataForSEO, verify the current
[LLM Mentions endpoint](https://docs.dataforseo.com/v3/ai_optimization/llm_mentions/search_mentions/live/),
supported locations/languages, cost and normalisation before adding it to CrawlSEO.
At drafting time its `chat_gpt` dataset supports US/English only. Do not silently
substitute that market for French Atelier or Mexican Spanish sites. Persist the
actual dataset/platform/locale; explicitly show unsupported coverage. Paid live
calls may be long-running and must use the durable billing protocol below.

For OpenAI search access, inspect OAI-SearchBot and verified crawler access
without disabling Cloudflare protections wholesale. GPTBot training permissions
are independent and must not be changed as an SEO tactic. ChatGPT-User is not a
search-ranking crawler. See [official OpenAI crawler documentation](https://developers.openai.com/api/docs/bots).

## 8. Paid research and permission boundaries

One tenant budget ledger covers monthly discovery, article research, competitor
inspection APIs, AI-visibility research and any other billable provider work.
Reuse existing receipts/idempotency infrastructure. If no atomic reservation
ledger exists, add the smallest persistence contract needed for it in Memory.

Before dispatch: validate capability and locale; calculate a bounded quote/cap;
reserve allowance transactionally; persist the operation/idempotency key.
After completion: record the provider task/result/cost and settle the reservation.
An ambiguous timeout stays reserved and `uncertain` until reconciled. Never
release it and blindly submit another paid live request. If the provider cannot
reconcile an ambiguous operation, stop and require an operational decision.

The existing fixed monthly research policy is not authorisation for arbitrary
new Labs/AEO tasks. Version the entitlement explicitly before enabling them.
Task count, result count, currency cap and period are separate constraints.
Dashboard reads, hover actions and reconnect attempts never buy research.

Owner decisions should be infrequent and intelligible:

| Situation | Ada handles | Owner validates |
| --- | --- | --- |
| Included analysis/private draft | Scheduling, collection, prioritisation, preparation | Nothing for individual tools/tasks. |
| Missing material business fact | Ask one concise question with its purpose | The fact; never an invented price, qualification, testimonial or guarantee. |
| Extra paid scope | Explain the incremental benefit, maximum charge and scope | That bounded spend, not open-ended research access. |
| New external access/privacy choice | Prepare instructions and exact requested permission | The specific account/security/privacy decision. |
| Ready website improvement | Full candidate, checks, affected pages and measurement plan | Publish this exact version, request changes or not now. |

The operator's authorisation to deploy product code does not imply a customer's
approval of Ada's proposed content or extra research spending.

## 9. Ada's diagnosis and preparation

Give the planner a typed brief: confirmed business/goal, current site structure,
valid evidence manifest, existing initiatives, prior outcomes, owner feedback,
allowance and required output schema. Do not build keyword-based intent routers,
industry phrase rules or canned worked conversations in prompts.

Each opportunity must include audience need, evidence references, affected
documents/routes, hypothesis, expected benefit with uncertainty, effort,
dependencies, proposed scope and a measurable success definition. Deterministic
validation checks structure/references/permissions; Ada supplies interpretation.
No unsupported financial uplift promises or invented quantitative confidence.

Prioritise business relevance, evidence strength, technical blockers, feasible
impact, originality and effort. For a new site, fix discoverability and core
service content before waiting for nonexistent traffic history. For an established
site, use actual query/page performance, decay and conversion friction.

Show at most three recommended next actions by default. Prepare at most two
active candidates per tenant initially to avoid a sprawling review backlog.
Retain the rest in history/details. Snoozes/rejections influence future planning;
do not re-propose the same rejected idea every week without material new evidence.

Preparation uses existing canonical paths:

- **Content/metadata:** create real Payload drafts against document versions;
  include main blog image, alt text, article card, full article, metadata,
  internal links and shared-component impact. Use approved media or properly
  sourced/generated assets under the service policy. No live edit to make a
  preview look correct.
- **Code/design/behavior:** Ada creates an immutable candidate through the
  existing plan/build/Design pipeline. Keep the published brand/experience for
  narrow changes; a metadata fix does not trigger a full redesign. Major design
  work must satisfy the full specialist plan and its prerequisites.
- **Combined change:** one release manifest binds code candidate and Payload
  draft versions. Render the actual combined state in the owner preview.
- **Analysis only:** save an informational report and next-step explanation;
  no publication button and no fake implementation artifact.

Maintain lineage `run -> evidence -> initiative -> candidate -> validation ->
approval -> publication receipt -> live version -> outcome`. Ada, not the coding
AI maintaining site-agent, creates tenant improvement candidates.

## 10. Validation before owner review

A recommendation is not ready for review until its required checks pass:

- Tenant/schema/document references exist; base revisions and route/mount mapping
  are correct; current production remains untouched.
- Metadata, canonical URLs, sitemap/robots behavior and internal links are valid.
  Structured data describes visible, verified content; no invented review stars.
- Articles are original, useful and faithful to confirmed facts; citations and
  media rights/provenance are recorded. Missing claims become owner questions.
- Main images appear on article listings and article pages; native Payload
  editing and shared nav/footer rendering still work.
- Candidate builds, hydrates and works in the actual owner preview sandbox;
  representative mobile/desktop, keyboard, reduced-motion and browser errors
  are checked. Run checks appropriate to the declared scope, not a dummy full-site
  “passed” badge based on a manifest or model self-report.
- Metrics/events have accurate definitions; proposed tracking respects consent.
- Security, external links and sensitive permissions pass the existing gates.

Use deterministic checks plus actual rendered/behavioral review where required.
Persist checker version, evidence, artifact hash, scope and result. Allow one
bounded, plan-preserving Ada repair for a failed candidate; validate the new
version again. Further failure is a precise block, not manual coding-agent polish,
weaker checks or publication of the previous draft.

## 11. Owner experience: calm service, visible work

Keep the approved HelloAda logo and current shared visual system: dark navigation
and Ada chat; neutral silver canvas and white work windows; exact coral-orange
`#ff6b5e` for active navigation, primary actions and restrained status emphasis.
Use near-black text on orange. State must also be written, not conveyed by color.
No large dashboard H1, marketing intro or another stacked navigation bar.

The Growth overview should fit this hierarchy:

```text
Growth   [Goal: Relevant visitors · Change]        [Ask Ada to review]
Ada status: real current task / next scheduled review / exact blocker

Recommended next       Ready for your review          Results
Why this helps         Actual change + preview        What changed
Evidence summary       Publish / Ask Ada / Not now    What is known / too early

Traffic & search | Keywords | Competition | Site health | Content | Connections
```

This is a functional hierarchy, not a requirement for three cramped equal
columns. Use responsive readable cards/rows and the existing compact tab rail.

### Background work

Show one concise status and completed/remaining named steps from persisted phases.
A details drawer exposes useful provenance: checked sources, covered dates,
findings, candidate checks, included/extra cost, blocker and next due review.
No synthetic percent, staged counter, endlessly animated “connecting” or internal
prompts/chain-of-thought. Subtle motion represents an actual running state and
respects reduced motion. If nothing is running, say so.

### Review workspace

Open the real candidate in the existing spacious Website/Design surface with
Ada alongside it. Provide before/after or changed-page navigation where useful.
An article review includes the complete article, listing card/main image and
metadata; not just a title and an “approve article” badge.

Keep a compact decision panel with:

1. **What Ada changed:** specific pages/components/content; shared/global scope.
2. **Why:** business benefit, concise evidence and important uncertainty.
3. **What you should check:** only real owner judgements, such as factual
   accuracy, tone, offer and image choice. Technical validation is Ada's job.
4. **What publication does:** exact version, public scope and any approved cost.
5. **What happens next:** live verification and when meaningful results are due.

Primary action is **Publish this version**. Secondary actions are **Ask Ada for
changes** and **Not now**. Fact/access/budget requests use their own exact action;
do not overload a generic Approve button. Minor included changes should normally
need just this final publication decision, not repeated approval of analysis,
outline, tools and draft. Group tightly related effects into one coherent package,
never bundle unrelated access or spending decisions invisibly.

Activity, chat and Growth reference the same run/action/approval IDs and status.
Keep the user's typed conversation unchanged; hidden workspace metadata remains
hidden. After a job leaves the active list, inspect its durable ID for the result.
Handle expired sessions explicitly and preserve unsent messages/review position.
One failed source does not erase healthy tools or the rest of the workspace.

Ship EN, FR and es-MX UI labels, readable focus/hover/disabled states, AA contrast,
keyboard access and narrow-screen review. Details/raw provider tables remain
available; owners should not have to understand them to receive the service.

## 12. Approval, publication and uncertainty

Reuse the existing approval service. Bind approval to a canonical review-package
hash containing tenant, affected routes/effects, code candidate SHA, Payload
draft versions, base revisions, goal/origin/policy revisions, validation manifest
and any incremental cost authorisation. The owner identity and exact decision
must be recorded. Chat enthusiasm is not a substitute for the explicit operation.

On approval, recheck the hash, current bases, permissions, required evidence
freshness and validation.
Changed candidates or conflicting edits become stale: prepare a revised package
and ask again. Do not rebuild different output after approval. A policy/origin/goal
change must not leave an incompatible package silently publishable.

Git/Cloudflare/Payload are not one atomic transaction. Reuse the existing release
mechanism with an explicit multi-surface manifest and preflight:

- stage and verify a compatible candidate against its exact Payload versions;
- preserve the prior code/content release references;
- publish in an order that avoids exposing incompatible schemas/content;
- persist each effect receipt, then verify the actual served public revision,
  routes, images, metadata and relevant interactions;
- mark `published` only after the intended combined release is live;
- if partial or ambiguous, expose that exact state and reconcile it. Recovery or
  rollback uses the known release references and existing authorised protocol,
  not a guessed older build, blind retry or synthetic transaction guarantee.

Verification failure is not “published successfully”. No outcome baseline starts
at approval time or an HTTP 200 alone. Retrying the same approved exact effect
must be idempotent; expanding/changing the effect requires a new approval.

## 13. Measurement and the next iteration

Freeze a `MetricPlan` per initiative: hypothesis, primary/secondary metrics,
source/property, page/query/event filters, market/device, aggregation, timezone,
baseline window, observation windows, data completeness and interpretation limits.
Record the verified live publication time and release/document versions.

Immediately verify function and collection. Assess search/content impact at
appropriate 30/90/180-day horizons, with earlier monitoring for breakage.
Compare like-for-like complete windows; preserve source/filter definitions.
No switching GSC clicks to GA4 sessions, division by zero, treating partial days
as decline or using a whole-site rise as proof of a page-level change.

Low volume, new sites and missing baseline produce **too early / insufficient
evidence**, not invented uplift. State absolute counts and uncertainty. Separate
association from causation, seasonality and overlapping changes. AI referrals,
sampled citations and search metrics remain distinct.

Ada explains what was learned and recommends keeping, revising or reversing the
change. Any new public revision/rollback outside an already authorised recovery
scope returns to the same candidate and owner-approval loop. Reports remain
informational. Feedback becomes evidence for the next review, not a new pipeline.

## 14. API and failure contracts

Keep authenticated `/v1/workspace` services behind Payload's server-only
`/api/helloada/*` proxy. Preserve canonical tenant token names and request-time
Cloudflare bindings in the connection contract. No credential in React or a model
brief; tenant mismatch fails closed.

- Extend existing GET `/growth` for goal, work, review and results projections.
  Existing analytics/evidence routes continue to serve saved/read-only data.
- Add a scoped POST growth-check operation only if existing owner actions cannot
  express it. It returns a durable ID and enforces permission/budget/idempotency.
- Reuse owner-action decisions and candidate approval/revision services; do not
  introduce separate Publish implementations in Chat, Growth and Content.
- Run details should reuse existing durable-job inspection where possible. New
  route names must be documented as new, not falsely described as already live.

| Failure | Required behavior | Forbidden behavior |
| --- | --- | --- |
| Expired auth/token mismatch | Explicit reconnect/auth failure; retain work and isolate tenant | Endless connecting, alias-token guesses or another tenant's data. |
| Missing/stale required evidence | Block that dependent phase; show source and safe recovery | Invent zero, label stale data live, silently write editorial-only research content. |
| Unsupported AEO market | State coverage limitation; do not claim a measurement | Substitute US/en for FR/es-MX or call it universal AI visibility. |
| Provider rate limit/transient failure | Bounded retry of the same safe operation with persisted backoff | Unbounded paid retries or changing provider without a contract. |
| Unknown paid/publication outcome | Persist uncertain, reconcile task/effect receipts | Resubmit blindly or claim completed. |
| Conflicting CMS/code edit | Invalidate package; regenerate and validate before new review | Overwrite owner edits or reuse old approval on new output. |
| Failed candidate validation | Bounded Ada repair, otherwise precise block | Lower gate, manual tenant patch or publish anyway. |
| Partial deployment | Preserve receipts/prior release, report exact state and recover | Hide it behind an API success or an older UI fallback. |

Operational logs include correlation IDs, phase/reason, duration, retries,
allowance/receipt state, review delay and verification result. Redact secrets and
personal source data. Owner notifications are limited to useful review-ready work,
material results and decisions/blockers requiring attention; not every subtask.

## 15. Implementation sequence and acceptance gates

Implement vertical slices. At each slice: failing focused tests first, a narrow
patch, artifact/contract inspection, actual review-surface proof where relevant,
and a scoped Git commit. Do not simultaneously rewrite all SEO modules or start
paid production research to discover whether the pipeline works.

### Phase 0 — Reconcile source and prerequisites

Read required instructions, inspect clean checkout/remote and current runtime
registration paths. Inventory existing pending jobs, budgets, approvals and
provider capabilities. Record known baseline test failures without disguising
them as new passes. Verify the autonomous-design prerequisite before enabling
code/design growth candidates; do not bypass its existing stop conditions.

Deliver a concrete migration map and one named first broken boundary. Inspect
separate CrawlSEO and customer repositories before modifying them; preserve
unrelated dirty changes. Never work from stale generated assets or another server.

### Phase 1 — Contracts, persistence and one scheduler

Implement typed policy/goal/run contracts, minimal migrations, transactional
leases, unique run/effect keys and the budget reservation boundary. Register one
growth tick/reconciler in both runtime paths. Preserve unrelated maintenance.
Prove new-site default goal, timezone cadence, restart recovery, duplicate-event
coalescing and independently registered outcomes with zero external mutations.

### Phase 2 — Real evidence and truthful projection

Normalise first-party/crawl/keyword/competition evidence with freshness and scope.
Fix connection/property provisioning at its root when needed. Extend CrawlSEO
capabilities only with tested provider contracts and explicit allowance versions.
Add AEO coverage reporting and paid collection only for supported markets.
Prove unsupported/missing/zero/stale states and read-only GET behavior.

### Phase 3 — First complete content improvement

Use a disposable new tenant to run one useful Payload-native improvement from
trigger to evidence to Ada-generated draft to actual preview and checks. Wire
the compact work/review UI to persisted state. Prove owner edits, article/card
images, metadata and shared-component impacts are visible and editable.
Then prove rejection leaves production unchanged and exact approval produces
the verified release with a linked measurement baseline.

### Phase 4 — Holistic strategy and code candidates

Integrate competitor content/gaps, decay, internal linking, conversion friction
and AEO observations into one planner. Route code changes through the proven Ada
design pipeline, including combined Payload/code review packages. Prove one
real combined change and stale-approval/partial-publication recovery. Do not
promote a brief-only `SITE_CHANGE` as an implementation.

### Phase 5 — Outcomes and service UX

Implement scope-correct outcome reviews and next-cycle learning. Test low-data,
new-domain and goal-change cases. Finish localized review/accessibility states,
shared Activity/Chat status, real progress drawer and useful notifications.
No fabricated metrics or backend job success substituted for visual proof.

### Phase 6 — Default onboarding and customer rollout

Prove a new tenant gets canonical schema, policy, connections, shared UI, drafts,
approvals and measurement without manual configuration or customer exceptions.
Migrate Atelier and OceanicVibes using those same contracts. Backfill history with
documented provenance, never fake pre-launch observations or approvals.

Remove superseded independent growth dispatchers/publishers/editorial degradation
after the replacement has an end-to-end proof. Keep historical readers only.
Enable the new scheduler exactly once; prevent both old and new work from running
during cutover with a controlled migration, not a permanent dual-path switch.

## 16. Mandatory test matrix

- New tenant has the traffic goal without another intake question; later confirmed
  goal revision preserves history, updates priorities and invalidates stale work.
- Both runtime registration paths retain outcomes; server restart/DST/timezone
  changes cannot double-run the same logical period.
- Concurrent ticks, owner double clicks and lease expiry cannot duplicate a
  candidate, charge or publication. A crash after dispatch reconciles receipts.
- Provider datasets with unsupported markets, missing snapshots, stale periods,
  actual zero, partial days and sampled/top-row limits remain distinguishable.
- GET Growth/analytics/evidence never provisions, buys research or publishes.
- One ledger caps all producers. Unknown paid outcomes remain reserved; rejected
  extra-spend requests have no provider side effects.
- Public competitor fetch blocks private/redirected/private-DNS endpoints,
  oversized responses, prompt injection and forbidden access.
- A research-dependent article cannot proceed without its required research.
  A genuinely independent validated fix can proceed without hiding the failure.
- An idea alone cannot be approved for publication; preview corresponds to the
  exact hash-bound code/Payload versions and required checks.
- Owner edit, domain change, goal change, revoked access or candidate repair makes
  incompatible approvals stale. Tenant identity is checked at every effect.
- Publish/retry/partial failure and recovery preserve exact effect receipts;
  verified live revision, not job disappearance, drives UI success.
- GA4/GSC expiry refresh, server-only binding and tenant-token parity regressions
  are covered; missing auth does not become another misleading “connecting”.
- Metric source/scope/window cannot change between baseline and outcome;
  small/no baseline, seasonality and zero denominator yield honest explanations.
- Real authenticated owner preview works on desktop/mobile, keyboard and reduced
  motion; no console/asset failures; correct article card/main image and metadata.
- EN/FR/es-MX, contrast, task status, review buttons and details are consistent
  across Growth, Activity, Chat, Gallery and native Payload editing.

Use provider fixtures/contract tests for ordinary development. Explicitly
authorise any live paid test and use a controlled test tenant. Public changes on
customer sites require their corresponding approval, not a test helper bypass.

## 17. Release discipline and definition of done

For product releases, build from a clean complete verified checkout and immutable
versioned shared package. Inspect the generated artifact: required new contracts,
markup/scripts present; retired execution/UI paths absent. All deployment targets
must derive from that exact release artifact, with target-specific bindings only.
Poll successful terminal deployment states, then open fresh authenticated browser
documents and verify DOM, real interactions and exact served revision per tenant.
A common package does not prove that each customer's bindings/deployment are right.
Where Site and Worker previews are in scope, publish the same artifact to both
and verify both according to the project release gate.

Record source commit, package/artifact hashes, migration version, deployed
revisions, connection proof and browser checks. Scope commits to relevant work
and push them to GitHub; never commit secrets, tenant databases or evidence dumps.
Document root causes and contract tests, not vague promises that errors can never
recur. Preserve the current published site when growth preparation fails.

The work is complete only when a new tenant and both current customers can prove:

1. Ada autonomously selects a grounded, useful improvement under the default goal.
2. Real evidence, paid permissions and background stages are inspectable and honest.
3. Ada creates a valid editable/previewable candidate without manual tenant coding.
4. The owner clearly understands and approves only the exact intended effects.
5. Rejection leaves the public site unchanged; approval publishes the reviewed
   package and verifies the actual live result.
6. Growth, Chat and Activity agree on the same durable state and decision IDs.
7. A scoped result review informs Ada's next proposal without invented uplift.
8. Missing providers, expired tokens, stale approvals and restarts expose the
   correct state and cannot activate a hidden alternate implementation.
9. Default onboarding and customer upgrades use the same site-agent architecture.

For the implementing coding AI: start at Phase 0, report the first broken boundary,
and deliver the smallest complete slice before expanding. Do not claim the
white-glove service complete because a report, a scheduler or a new card exists.
