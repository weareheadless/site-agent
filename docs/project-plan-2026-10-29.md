# Project plan — 2026-10-29

Implementation specification for the Unified Business Intelligence initiative.
Status: reviewed for staged implementation, **not cleared for unconditional
replacement, tenant activation or production release**. §12 records readiness.
This supersedes the initiative sequencing in `docs/project-plan-2026-10-27.md`
and historical `/SEO/PLAN*.md`, not repository instructions or the existing
exact-approval, CMS, source-trust and release contracts. §8 carries forward the
earlier proof and hardening work. Reconcile the current board before claiming a
task; no DS issues have been created by this document. The board is the status
ledger; §7 is the specification for the DS work.

Scope: consolidate verified, genuinely overlapping third-party collection onto
DataForSEO behind CrawlSEO; retain first-party measurements, useful free sources
and unique analysis; connect all evidence to one adaptive recommendation pipeline.
Adding a paid source is not itself proof that an existing capability is redundant.

## 1. Architecture (fixed)

```
                    ┌────────────────────────────────────────────┐
                     │ CrawlSEO — sole DataForSEO client          │
                    │ research · evidence · actions · agent tasks│
                    └───────┬───────────────────────┬────────────┘
             connector/MCP  │                       │ agent tasks
                            ▼                       ▼
                    ┌───────────────┐        ┌──────────────┐
                    │ Site-Agent    │        │ Wix connector│
                    │ engine + Ada  │        │ (existing)   │
                    └───────┬───────┘        └──────────────┘
                            ▼
                    ┌───────────────┐
                    │ HelloAda      │
                    │ Payload admin │
                    └───────────────┘
```

- **CrawlSEO** owns every DataForSEO call, cached research payload, canonical
  business/research record, finding, recommendation and visibility observation,
  and the agent-task dispatch used for Wix sites. Site-Agent retains references,
  execution/process state, exact approvals and receipts, not a second research store.
- **Site-Agent** is the engine and the owner product host. It reads CrawlSEO
  (cached), renders analytics and recommendations in the Payload admin, and Ada
  implements approved actions for HelloAda-managed sites.
- **HelloAda** (Payload admin) is the owner UI. CrawlSEO is invisible there: no
  CrawlSEO name, links, URLs or admin vocabulary in the owner-facing product.
- **Wix** sites keep their own executor. CrawlSEO dispatches the agent task to
  the Wix connector. Do not force a shared action model between Wix and HelloAda;
  they share the recommendation source, not the execution mechanism.
- **One provider transport**: CrawlSEO's HTTP client (`lib/dataforseo/client.ts`).
  The DataForSEO MCP server is not used at runtime. Its `SKILL.md` must not be
  installed into agents, because it instructs them to shell out to the CLI and
  bypass CrawlSEO.
- **No second authority.** A capability has one authoritative implementation.
  A bounded parity comparison may temporarily run two collectors without duplicate
  recommendations or effects. Each replacement names its cutover and deletion;
  complementary evidence sources are not duplicate authorities.

## 1a. Two research domains — do not merge them

The word "research" covers two capabilities with different inputs, producers and
semantics. Keep their producers and run identities distinct; share evidence
references and feed the same downstream recommendation synthesis. They may reuse
source adapters and infrastructure without merging their domain semantics.

**Business research** (CrawlSEO `ResearchRun`; existing enum: `MARKET | SEO | MIXED`)
- Question: what is true about this business, its market, customers, competitors
  and open questions.
- Inputs: a bounded question set, public web/news/social sources, the canonical
  business knowledge document.
- Producer: our own source acquisition plus LLM synthesis
  (`lib/research/runner.ts`, `synthesizer.ts`, `providers/*`).
- Output: sources, findings, question coverage and candidate insights. Today it
  also creates actions; DS-17 routes automated proposals through shared synthesis.
- DataForSEO does **not** provide this. It can supply *sources* (news SERP,
  content-analysis mentions) but never the question set, the synthesis or the
  judgement. Replacing a source adapter is allowed; replacing the capability is not.

**Search research** (CrawlSEO `SeoResearchRun`, `ArticleKeywordResearchRun`)
- Question: how does this site perform in search and answer engines, and what
  should change.
- Inputs: keywords, SERPs, backlinks, on-page signals, rank data, AI visibility.
- Producer: CrawlSEO source adapters/recipes, using DataForSEO through our client
  alongside first-party and useful free evidence; the provider does not choose strategy.
- Output: provider evidence, keyword/SERP/backlink reports and candidate insights,
  not a second autonomous recommendation stream after DS-17.

Rules:
- A task must say which domain it touches. "Unify research" without a domain is
  an invalid task.
- Business research may consume search findings as *evidence*, but it must not
  become the SEO executor.
- Search evidence may help answer a business question when explicitly sourced;
  a provider result alone is not business synthesis or an owner-confirmed fact.
- The combined synthesis records which domains informed the recommendation.
  Distinct producers must not become isolated recommendation silos.

## 1b. Recommendation synthesis — the pipeline stage that matters

All automated recommendations flow through one synthesis stage in CrawlSEO. It
considers the combined available business, keyword, technical, AEO/GEO, performance
and content context, without requiring every domain to have data for every action.
Every action must be traceable to the inputs that informed it.

**Inputs (existing records; common linkage still needs implementation)**

| Domain | Source of truth | Linkage context, always tenant/project scoped |
|---|---|---|
| Business research | knowledge revisions, `ResearchRun`, findings, `QuestionCoverage` | record IDs, question/section identity, locale, revision/hash |
| Keyword demand | verified keyword metrics; SERP is context, not volume | query, engine, country/location, language, period, device where applicable |
| Search performance | GSC `Keyword` / `Page` rows | query/page, date range, country/device dimensions actually collected |
| Technical state | current audit records; OnPage after parity | crawl/observation ID, URL, collection mode, time |
| AEO/GEO | visibility observations, business consistency and AI-access checks | provider dataset/surface, brand/domain, prompt/cohort if supplied, locale, time |
| Content inventory | canonical Payload document metadata synced via Site-Agent, published page audit | document ID, locale, URL, published/draft revision, content hash |

**Rules**

- The synthesis is the only producer of new automated recommendations. Existing generators
  (`lib/seo-opportunities.ts`, `lib/ai-seo/content-plan.ts`,
  `research/seo-actions.ts`, `research/crawl-actions.ts`) become *input
  detectors* or read projections; they must not independently publish competing
  recommendations. DS-17 inventories actual creators, including business research,
  question coverage and technical reassessment. Persistence remains in the shared
  action service; authorised lifecycle updates and explicit human proposals stay valid.
- Every action records: the domains used, the evidence rows (ids + timestamps +
  values/units and revisions), a concise decision rationale, the intended outcome,
  technical acceptance, outcome observation and reassessment conditions. Store
  the supplied context manifest and model/prompt version for audit, not hidden
  chain-of-thought. Approval binds an immutable action/candidate revision.
- A missing input is stated, never fabricated. No keyword volume means the action
  cannot claim demand; it can still be raised for a business question, labelled as
  demand-unknown.
- Deduplicate the same proposed work across producers and retries using existing
  action identity/revision contracts. Same URL does not imply same work; preserve
  independent changes, site-wide work and new content without a target URL. Related
  actions can reference shared evidence or dependencies without forced merging.
- Recommendations are advisory until approved (see DS-13). The synthesis never
  edits content.

**Judgement is adaptive; only the guardrails are fixed**

The pipeline supplies the evidence and the constraints. What to do with them is
the synthesis's judgement, made per case from the actual findings. Do not encode a
strategy in the plan, in a scoring formula, or in a signal-to-action table: the
same evidence can justify different actions, and evidence we have not anticipated
may justify something none of us listed.

Fixed (enforced in code): tenant isolation, resolvable evidence, explicit missing
inputs, deduplication/revision safety, measurable acceptance, existing approval
gates and no invented data. External source text is untrusted evidence, never
instructions or tool authority. Retrieval is bounded and scoped; truncation and
excluded inputs are recorded, and additional evidence is fetched explicitly.
Not fixed: which action, which strategy, how to weigh the factors, when to do
nothing. The synthesis records its reasoning and the evidence it used so a human
can audit the choice; it is not required to justify itself against a template.

## 2. Non-negotiable invariants

1. DataForSEO credentials and runtime calls live only in CrawlSEO. Site-Agent
   and HelloAda consume its evidence; this does not relocate Site-Agent's model,
   GitHub, CMS or release credentials.
2. No new cache outside CrawlSEO. Site-Agent may hold a short TTL read cache and
   last-known-good copy for rendering only.
3. Every number shown to an owner carries provenance and a measurement state
   (`measured`, `estimated`, `unknown`). Never render a zero for "not measured".
4. A metric has one semantic. Never substitute a first-party measurement (GSC,
   GA4, our crawl) with a third-party estimate under the same label, or vice
   versa.
5. Vendor mentions datasets, direct LLM responses and provider-collected search
   surfaces have distinct semantics. Label the actual sampling method/coverage;
   none proves what every consumer sees. No authenticated-UI-proof requirement.
6. Merged is not deployed; deployed is not verified. Verification requires the
   exact deployed SHA and an observed behaviour.
7. Every replacement PR names the survivor, removed behavior, consumers, parity
   evidence and rollback boundary. Genuine new capabilities need no invented
   deletion; temporary overlap must have an explicit owner and removal gate.
8. Destructive or spend-incurring operations need the existing budget/approval
   gates; do not add new admission policies as part of this work.
9. Provider payloads are stored before they are summarised. A summary that cannot
   be traced to a stored payload is not evidence.
10. Owner-facing copy must not expose internal infrastructure names.

## 3. Verified current state (2026-10-29)

Source inspection rechecked at CrawlSEO `ccf4d00` and Site-Agent `de0868b6`.
Standalone HelloAda was previously inspected at `5630723`; it is not the Payload
admin. No production tenant/board inventory was refreshed in this review.
The earlier provider comparison did temporarily create/delete a local crawl row;
see the corrected verification record. Deployed parity is not assumed.

**CrawlSEO**

- One provider client, five paid endpoints plus a free account check and the
  locale catalog: `lib/dataforseo/client.ts:471,501,531,618,627`.
- Separate monthly, prelaunch and article orchestration paths use the same
  provider client. Monthly/prelaunch use `SeoResearchRun`/`SeoResearchTask`;
  articles use **`ArticleKeywordResearchRun`**, with their own claim and uncertain
  effect handling. They do not already share the same persistence lifecycle.
- Labs keyword metrics, SERP, Autocomplete and GSC answer different questions.
  The keyword route already labels Autocomplete and leaves paid metrics null;
  that free discovery capability is not an invalid volume substitute.
- Monthly/prelaunch SEO reports, article results, monthly combined evidence and
  business findings are different projections, not automatically redundant models.
- Custom crawler with 16 issue types, link graph, live re-check:
  `lib/crawler/engine.ts:626`, `lib/research/crawl-live-check.ts:120`.
- AI visibility: capability matrix (`lib/research/ai-visibility-capabilities.ts`),
  one Perplexity manual-export adapter (`ai-visibility-import.ts:30-40`), **no
  production caller** — no route, job or MCP tool invokes the importer.
- Agent tasks and Wix delivery already exist: `lib/agent-tasks/*`,
  `lib/delivery/wix-*.ts`, `lib/bridge/client.ts`.

**Site-Agent**

- Fixed 19-tool CrawlSEO contract plus a REST connector
  (`src/site_agent/hands/crawlseo.py:68-88`).
- A local research engine remains executable in source: `core/memory.py:4792-5210`,
  `application/incubation_research.py`, `intake_coordinator.py:660-697`.
- Repeated domain/backlink payload extraction: `application/competitive_evidence.py`
  vs `application/growth_evidence.py`. Their output projections differ; only
  equivalent extraction should be shared, not entire modules treated as duplicates.
- Duplicate adapter methods with different idempotency keys:
  `hands/crawlseo.py:616-651` vs `application/crawlseo.py:362-407`.
- Direct `hands/crawlseo.py` wrappers have a source defect: they expect an
  `action` envelope after `connector_action` has already unwrapped it, and the
  execution wrapper later uses unimported `hashlib`. The application-service path
  handles both shapes and imports it. This is not proof that all live receipts fail.
- Visibility is hard-coded: `application/workspace.py:2769` returns
  `{"state":"unknown","surfaces":[]}`; `application/crawlseo.py:157-168` never
  reads it.
- Local and remote research paths remain in source, selectable by configuration
  and guarded by existing producer-freeze/cutover fences:
  `defaults.yaml:271-279` (`enabled: false`, `research_authority: local`).

**Frontends — distinct ownership**

- Standalone `/SOCIAL/helloada` has an outbound path to Site-Agent
  (`src/lib/website.ts:19-46`); no provider
  access. No request timeout on that path.
- Its intelligence panel renders business facts, research summary, coverage/actions
  and a visibility line that can never show a count (`room.tsx:268-295`).
- The actual owner workspace is
  `packages/helloada-payload-admin/src/` in Site-Agent, backed by existing Growth
  initiatives, candidates, approvals, publication/release and outcome records.
  Its accepted workflow must be reused, not replaced with a second executor or UI.

**DataForSEO (measured today)**

- Credentials work; `appendix/user_data` returned `20000`.
- One `on_page/instant_pages` call on `https://www.atelier-harmonie.com/`
  returned 52 boolean fields, `onpage_score 92.68`, timing fields and 6 parse
  errors, cost **$0.00045**. Field count is not actionable-check coverage.
  Counts/timings differ in scope; accuracy, sitemap membership, rendered vitals
  and full-site replacement were **not established** by this one-page comparison.
- AI Optimization API exists with AI Keyword Data (AI search volume) and LLM
  Mentions (mentions, target metrics, top pages/domains/brands, historical,
  timeseries).
- Not yet verified: task-based OnPage crawl cost/shape, backlinks list and
  intersections, Labs keyword endpoints, AI Optimization response shape and
  locale limits, per-endpoint pricing.

## 4. Capability ownership (post-consolidation)

| Capability | Single owner | Data source | Consumer |
|---|---|---|---|
| Page and link analysis | CrawlSEO | OnPage where parity passes; retain unique checks | dashboards, actions |
| Published site inventory and link graph | CrawlSEO | current crawl; OnPage Pages/Links only after parity | actions, audits |
| Canonical content/draft inventory | Payload via Site-Agent | scoped document/revision metadata | synthesis, exact preparation |
| Keyword metrics and discovery | CrawlSEO | Labs/Keywords Data plus useful free discovery | research, dashboards |
| SERP evidence | CrawlSEO | SERP API | research, article work |
| Backlinks and prospects | CrawlSEO | Backlinks API | dashboards, outreach actions |
| Search performance / sampled ranks / estimated history | CrawlSEO | separately labelled GSC / SERP / Labs series | dashboards |
| AI visibility | CrawlSEO | verified AI Optimization dataset/surface; unknown otherwise | intelligence, AEO/GEO views |
| Speed and experience | CrawlSEO | existing Vitals/field/lab sources, kept distinct | dashboards, synthesis |
| First-party performance | CrawlSEO | GSC + GA4 | research evidence, dashboards |
| Business consistency audit | CrawlSEO | our rules + canonical knowledge | actions |
| Business/market research | CrawlSEO | own sources + LLM synthesis | Site-Agent, Ada, dashboards |
| Search research orchestration | CrawlSEO | one engine + SEO recipes | Site-Agent, dashboards |
| Recommendation synthesis and actions | CrawlSEO | evidence join → `ResearchAction` | Site-Agent, Wix connector |
| Action execution (HelloAda) | Site-Agent / Ada | approved action | site repo, issues |
| Action execution (Wix) | Wix connector | CrawlSEO agent task | Wix site |
| Owner presentation | HelloAda (Payload) | Site-Agent read | owner |
| Conversation/intake/design | Site-Agent | own state | owner |

## 5. Deletion inventory

This is a behavior inventory, **not permission to delete whole named files**.
Before removal, inventory production callers, tests, jobs, tools, schema relations
and public consumers. Remove only superseded behavior after replacement acceptance;
retain unrelated functionality and historical evidence. No destructive migration
is inferred from the presence of a model here. §5a defines regression checks.

**CrawlSEO**
- `lib/dataforseo/prelaunch-runner.ts` and `lib/dataforseo/prelaunch.ts`
  orchestration (keep a domainless *recipe*) — DS-02.
- `lib/dataforseo/article-research.ts` orchestration (keep an article *recipe*) —
  DS-02.
- Route automated proposals in `lib/dataforseo/prelaunch-actions.ts` through
  synthesis; consolidate redundant projection logic in `prelaunch-report.ts`
  without breaking historical consumers — DS-17 / DS-03.
- Duplicate budget reserve/settle variants (`lib/connectors/service.ts:1136-1210`)
  — DS-08.
- Static `DATAFORSEO_LOCATION_CODES` (`lib/dataforseo/locale.ts:3-29`) — DS-07.
- Legacy **DataForSEO-specific** per-user credential resolution
  (`lib/dataforseo/readiness.ts`, `client.ts` legacy branch), after binding
  migration/readiness proof; not the entire shared `ApiKey` model — DS-07.
- Audit source semantics in `app/api/sites/[siteId]/keyword-research/route.ts`,
  `.../domain-overview/route.ts`, `.../backlinks/route.ts` and remove misleading
  substitutions where actually found — DS-05.
  Keep clearly labelled free Autocomplete discovery unless verified replacement
  is demonstrably better for that capability; do not invent volume for it.
- Redundant handlers behind report projection tools and MCP transports — DS-09.
  `mcp/server.ts` is an administrative stdio server; `mcp/project-tools.ts` backs
  project-scoped HTTP. Share applicable handlers, not their authentication scope.
  Retire old names/scripts only after consumer migration; adapt useful diagnostics.
- Independent automated proposal paths in `lib/research/{runner,seo-actions,
  crawl-actions,keyword-actions,question-coverage}.ts`,
  `lib/crawler/technical-actions.ts`, `lib/dataforseo/prelaunch-actions.ts` — DS-17.
  `seo-opportunities.ts` and `ai-seo/content-plan.ts` are read-side signal/plan
  builders, **not direct `createResearchAction` writers**. Preserve useful signals
  while removing independent recommendation authority. Keep action lifecycle updates.
- Perplexity manual-export adapter and operator-export envelope
  (`lib/research/ai-visibility-import.ts:30-40,75-77`) — DS-06; remove the
  superseded import path only after verified replacement. Failed verification
  leaves measurement unavailable/unknown, not permission to drop models or history.
- Crawler page-fetch/parse/issue detection and its 16 checks
  (`lib/crawler/engine.ts`), only for checks covered by OnPage parity — DS-04.
  Business consistency, AI-access and unique checks survive in their current owner.
- Individual business-research source adapters (`lib/research/providers/*`) only
  when a better source replaces them; the business-research producer and its
  question set are **not** deleted — DS-03.

**Site-Agent**
- Local research producers and runtime research reads: `core/memory.py` accessors
  (4792-5210), `application/incubation_research.py`, `intake_coordinator.py:660-697`
  local research path — DS-11. Archive/migrate required history first; physical
  table removal is a separate reviewed migration after retention/cutover proof.
- Local brief builders: `brain/seo.py:338-378`, `incubations.py:544-600` — DS-11.
- Local keyword/competitor derivation: `brain/seo.py:126-335`,
  `brain/seo_insights.py:107-159`, `growth_workflow.py:682-712` — DS-11.
- Ambiguous source identifiers in `application/growth_service_model.py` and its
  consumers — DS-10. Distinguish transport/authority (`crawlseo`) from upstream
  source (`gsc`, `ga4`, `dataforseo`); different names are not duplicate collectors.
- Duplicate evidence parsers: `application/competitive_evidence.py:54-113`,
  `application/growth_evidence.py:67-71` — DS-10.
- Duplicate adapter methods: SERP aliases (`hands/crawlseo.py:545-549`),
  `connector_decide`/`connector_record_execution` duplicates
  (`hands/crawlseo.py:616-651` vs `application/crawlseo.py:362-407`) — DS-10.
- Competing local research/recommendation production within
  `brain/strategist.py`, `brain/report.py`, `brain/article_research.py`,
  `brain/monthly_seo_report.py`, `brain/seo_outcomes.py` — DS-11/DS-12.
  Keep presentation, execution planning and outcome observation that already
  consume canonical evidence; do not delete whole modules by their names.

**Owner UI**
- Replace unsupported export-based copy and dead count projections in the actual
  Payload surface — DS-15. Standalone HelloAda changes require a demonstrated
  consumer need, not confusion between the selector and the owner workspace.

## 5a. Overlap removal register

Guard semantic authority and behavior, not arbitrary counts of files, exports,
callers or database writes. Shared repositories may have several legitimate
readers/writers behind one service. Keep contract/security tests and, where
appropriate, import-boundary checks; a textual grep alone is not acceptance.

| Overlap | Survivor | Removed | Task | Guard |
|---|---|---|---|---|
| Monthly/prelaunch/article dispatch | shared execution lifecycle + recipes | duplicate reserve/claim/dispatch orchestration | DS-02 | retries/concurrency preserve each request identity and do not redispatch uncertain spend |
| Repeated report normalisation | versioned evidence contract + necessary projections | redundant transformations, not distinct domains | DS-03 | golden historical/new consumer contract tests |
| Dashboard semantic substitution | explicit source/units/dimensions/state | misleading metric overlays | DS-05 | GSC, sampled ranks, estimates and discovery remain distinguishable |
| Custom collection vs OnPage | accepted collector per supported capability | only proven equivalent checks | DS-04 | parity plus unique-check/link-graph/live-recheck regression tests |
| Competing automated recommendations | shared synthesis → action service | independent auto-proposal bypasses | DS-17 | all inventoried triggers pass synthesis; lifecycle/manual APIs still work |
| Provider transport bypass | `lib/dataforseo/client.ts` at runtime | direct production fetch/CLI/MCP paths | DS-01, DS-09 | runtime network boundary and client contract tests; docs/fixtures may name the host |
| Legacy DataForSEO credentials | scoped grant → approved platform configuration | legacy provider-specific resolution | DS-07 | tenant isolation, revocation, readiness and no unsafe credential fallback |
| Budget implementation duplication | shared atomic accounting | duplicate accounting logic | DS-08 | site/project limits, settlements, concurrent claims and uncertain effects |
| MCP handler duplication | shared applicable services, scoped transports | redundant handlers/tools after migration | DS-09 | tool contracts and wrong-project denial for every retained transport |
| Local canonical research | CrawlSEO | local producers and live evidence reads | DS-11 | cold-start intake/design/Growth use remote business research; no local fallback |
| Repeated payload parsing | shared normaliser per schema/semantic | duplicate equivalent transforms | DS-10 | multiple consumers get consistent typed output; raw refs retained |
| Adapter business logic duplication | application operation + transport primitive | duplicate revision/idempotency construction | DS-10 | direct/service callers agree; transport and domain validation both retained |
| Authority selection | CrawlSEO for supported tenant lifecycle | local authority option after cutover | DS-12 | old config has actionable migration error; no local engine resumes |
| Manual visibility acquisition | verified dataset adapter(s) | superseded import code only | DS-06 | provenance, coverage, unknown vs observed-zero and historical read tests |

A replacement is not complete until its regression tests detect the retired
behavior returning. A retained unique capability must have a named owner and
test; it is not an exception allowing a parallel implementation of the same work.

## 6. Data model

- Preserve `ResearchRun` separately from `SeoResearchRun`/`SeoResearchTask`.
  `ArticleKeywordResearchRun` also exists and must keep historical readers and
  request identities during DS-02. Reuse existing `briefHash`/`requestHash` before
  adding fields. Recipe/version and canonical input identity must support weekly,
  domainless and explicit on-demand requests; the current monthly uniqueness
  constraint and nullable `siteId` cannot simply be reused unchanged.
- One evidence core with typed sections replaces redundant normalisation while
  preserving necessary domain projections and historical readers. Store raw payload beside the
  summary, scoped by project/run/request identity and provider task ID where
  supplied. IDs may be absent on uncertain calls or unsuitable as global keys.
  Keep raw payload separate from derived output so normalisation can be replayed
  without another paid call. The envelope is a shape, not a merged run.
- `AIVisibilityObservation` is kept as the visibility record; add
  `vendor`, `observedSurface`, `model`, `locale`, `prompt` if not already
  distinct. Aggregate datasets must not be coerced into fake per-prompt
  observations. Extend the current contract explicitly if needed; retain old
  rows/readers and their meaning. Unknown stays unknown.
- Site-Agent gains no research tables. It may keep one last-known-good snapshot
  per tenant with `fetched_at`, `etag`, `payload_hash` and `source_revision`, for
  short-TTL rendering and explicitly stale outage display only. Keys include
  project/site, binding generation, permissions and schema version; invalidate on
  rebinding/revocation. It is not a second research authority. Never use stale
  rendering snapshots to approve, execute or assert current evidence.
- Actions keep their existing model; findings reference the stored payload that
  produced them.
- Domainless business research is **not yet supported by `ResearchRun.siteId`**,
  which is required in the inspected schema; `ResearchAction.siteId` is also
  required. DS-16 must extend the existing business lifecycle for project-owned,
  optionally site-bound runs and audit site-dependent queries/jobs/automation.
  Do not invent placeholder domains/sites or label a keyword run business research.
  Before a real site binding exists, retain sourced findings/analysis; site-targeted
  execution actions require that binding, not a fabricated `siteId`.
- Schema changes use additive/expand → compatible reads/backfill → cutover →
  reviewed contraction. Preserve IDs, revisions, provenance, approvals, budget
  history, foreign keys and uncertain effects. Backfills are idempotent and
  reconciled with counts/hashes; destructive contraction needs explicit retention
  approval. Bounded raw retention must not orphan evidence for active/history work.

## 7. Workstreams and tasks

`depends:` lists hard completion blockers; IDs are stable, not execution order.
Waves group milestones; **same-wave dependencies still apply**. Independent
bounded work may proceed concurrently under repository coordination rules.
Each issue pins its current source/contract, consumers, deletion boundary, tests,
migration and release evidence before coding. Dependencies on DS-01 require the
relevant capability decision, not successful adoption of every unrelated endpoint.
No-go means retain the supported current capability and record the gap, not delete
it or block unrelated work. §8's existing causal/release gates also apply.
Primary repositories: DS-01–09/14/17 are CrawlSEO work (consumer changes may touch
Site-Agent); DS-10/16 span CrawlSEO and Site-Agent; DS-11/12/13/15 are Site-Agent,
including its shared Payload packages. No standalone HelloAda or Wix mutation is
implied. Cross-repository changes pin compatible contract versions and release order.

### Wave 0 — verification

**DS-01 Provider capability verification** (research sources; no production code)
`depends: none` · `deletes: none; evidence gate, not an implementation`
Use current official docs and existing approved spend controls; a plan is not new
spend authorisation. Verify the endpoint families needed for actual consumers:
Keywords Data/Labs, SERP, backlinks/referring domains/intersections, task-based
OnPage summary/pages/links and needed resource/HTML access, AI Optimization and
Content Analysis search. For AI distinguish LLM Mentions, AI Keyword Data,
LLM Responses and available scraper/search-surface products; none is assumed
equivalent or necessary solely because it exists. Verify actual account/locale
support and response semantics before choosing adapters.
Acceptance: update `docs/verification/dataforseo-capabilities-2026-10-29.md` with
endpoint/request, rendering options, status at envelope **and task** levels,
pagination/completeness, units, time/dimensions, sampling limitations, task IDs,
sanitised durable fixtures and observed costs. Record go/no-go and replacement
scope per capability. A successful empty response is not positive coverage proof;
fixtures must cover useful non-empty data, unknown/error and pagination behavior.
No production mutation; payloads must exclude credentials and private tenant data.

### Wave 1 — execution foundation

**DS-02 Unify search-research orchestration** (SEO/AEO only)
`depends: none` · `deletes: duplicate monthly/prelaunch/article dispatch lifecycle`
Extract a shared executor from existing paths, preserving typed monthly, article
and domainless recipes and their limits; new endpoints remain gated by DS-01.
Preserve historical `standard-v1`, article parent/SERP linkage, request/status
APIs, scopes and policy checks. No business-research engine merge. Keep thin
compatibility entrypoints where externally used, not parallel orchestration.
Acceptance: old stored runs still render; article/domainless/monthly request,
claim and status tests pass with intentionally versioned internal changes. Preserve
atomic reserve/claim, per-operation ceilings, raw response durability, actual-cost
settlement, partial results and replayable normalisation. Timeout after dispatch
becomes uncertain and is reconciled, **never blindly retried**; async retrieval
polls the known provider task rather than recreating it. Concurrent workers,
crash/restart and duplicated delivery do not repeat a known paid dispatch. Handle
weekly/on-demand identity without monthly uniqueness collisions (§6).

**DS-07 Credential and locale resolution** (DataForSEO only)
`depends: none` · `deletes: superseded provider-specific credential branch and static locale map`
One scoped resolution policy (project grant → approved platform configuration),
with explicit revocation/error handling and no silent bypass of an invalid grant.
Inventory affected bindings before retiring legacy per-user credentials. Use
endpoint-family-specific location/language catalogs: one cached resolver, not a
universal locale list. Supported locales differ across products.
Acceptance: migrated bindings pass readiness; wrong-project/revoked grants fail;
catalog outage/unsupported locale is explicit; no guessed location substitution.
Do not drop shared `ApiKey` data used by other integrations.

### Wave 2 — contracts and accounting

**DS-03 Evidence contract, distinct producers**
`depends: DS-01, DS-02` · `deletes: redundant normalisation; source adapters only after proven replacement`
Introduce one typed envelope for stored evidence and findings, used by both
domains, with a compatibility projection for existing rows and MCP consumers. The
domain run identities (`SeoResearchRun`, `ResearchRun`, legacy article records)
and producers stay separate. Within DS-03, business acquisition changes only replace a source
adapter with a better one (news SERP, content-analysis mentions); its question
set and synthesis remain ours. Record that decision in the task.
Acceptance: a versioned evidence core with typed sections, IDs, upstream source,
transport authority, collection/observation times, dimensions, units, freshness,
coverage and explicit unknown/error/estimated states. Compatible projections serve
historical MCP/REST/UI readers; different domain projections need not become
identical JSON. Record business-source retain/replace decisions from DS-01;
no source replacement is required just to complete the envelope. Sanitised
fixtures cover historical/new/partial and malformed payloads and schema evolution.

**DS-08 Shared budget accounting** (search execution infrastructure)
`depends: DS-02` · `deletes: duplicated site/project reserve/settle accounting logic`
Reuse existing ledgers/policies, with one shared atomic accounting implementation
and scoped adapters. Different owner scopes are not evidence of duplicate money.
Acceptance: existing connector contract, currency/micros, limits, locking,
idempotency, reconciliation and immutable receipts preserved. Tests cover concurrent
reservations, actual-cost settlement, release-before-dispatch and uncertain calls.
No reset of spent balances, history or new admission policy.

### Wave 3 — verified collection and transport consolidation

**DS-04 Replace proven crawler overlap with OnPage** (technical evidence)
`depends: DS-01, DS-03, DS-07, DS-08` · `deletes: only parity-proven collection/check implementations`
Steps, in order, each a separate merge:
1. Adapter: OnPage task-based crawl → our page/link/issue shapes, storing the raw
   payload.
2. Bounded dual-run with at least 20 pages across 3 approved sites, plus the cases
   needed to exercise existing capabilities. Cover redirects/canonicals, robots
   and sitemap discovery, rendering, locale, page/link pagination, partial/failed
   crawls, content extraction/hash and existing issue/action consumers. Sample size
   alone is not parity. No duplicate actions or writes from the comparison path.
3. Switch read paths (dashboards, actions, health score) to the adapter.
4. Migrate `AuditLink` and audit-page consumers; remove covered fetch/parse/check
   code. Preserve business-consistency/AI-access checks and required unique signals.
5. Use `instant_pages` for supported page-local rechecks only. Site-wide/link or
   sitemap claims need evidence of the matching scope; a single URL cannot prove them.
Acceptance: an explicit old-capability → provider/retained-owner mapping, resolved
disagreements, graph/content-hash consumers and action reassessment still work.
Version changed health-score semantics instead of splicing vendor/custom scores.
Keep existing speed/vitals collection; non-rendered zeros are not Core Web Vitals.
If parity fails, do not cut over that capability or keep a second competing path.
Record retained ownership and a bounded gap. All paid rechecks use existing
approval/budget controls; exact CMS/release verification remains with Site-Agent.

**DS-05 One semantic per dashboard field**
`depends: DS-01, DS-02, DS-03, DS-07, DS-08` · `deletes: misleading substitutions and verified redundant transforms`
Every field in keyword research, domain overview and backlinks declares its source
and state. Provider-sourced and first-party metrics never share a label.
Acceptance: source/units/dimensions and state are preserved on every displayed
metric. GSC average position, sampled SERP ranks and Labs history are separate
series, not interchangeable fallbacks. Inventory `RankSnapshot` writers before
retiring a redundant store; remove the unlabelled precedence overlay in
`rank-history/route.ts`, not distinct measurements or history. Preserve useful
free discovery with null volume/difficulty until demonstrably better replacement.
Competitor parameters actually affect correctly scoped results or are explicitly
unsupported. Tests cover no data, stale data, unavailable provider and dimension
mismatches without inventing zeros or issuing a paid request from GET.

**DS-06 Evidence-backed AI visibility** (AEO/GEO measurement)
`depends: DS-01, DS-03, DS-07, DS-08` · `deletes: superseded manual acquisition and unsupported capability claims`
Implement adapters for the verified products required by the existing question
set and coverage contract. Preserve raw references, actual dataset/surface,
model where supplied, locale, observation time, sampling and denominator where
meaningful. Do not manufacture per-question answers from aggregate target metrics,
or sum incompatible cohorts into a misleading visibility count. AI demand estimates
are not observed brand mentions. Keep unsupported engines/markets unknown.
Acceptance: a real stored, correctly normalised observation/dataset and safe read
projection; observed zero differs from no measurement; partial coverage is explicit;
duplicates/replays are idempotent. Register collection with DS-14, no new timer.
If verification fails, retain historical data and meaningful AEO/AI-access/coverage
features, report measurement unavailable and record the gap. Never drop the entire
capability or schema on this result. DS-15 owns end-to-end owner presentation;
coverage against multiple engines is claimed only when actually observed.

**DS-09 Shared MCP services, scoped surfaces** (transport contracts)
`depends: DS-02, DS-03` · `deletes: redundant handlers and unused tools after consumer migration`
Inventory administrative stdio and project-scoped HTTP tools, scopes and callers.
Share application handlers where semantics match; do not expose administrative
queries through a project transport or delete unique tools wholesale. Update
Site-Agent's fixed allowlist and diagnostics before removing consumed names.
Acceptance: retained tools call shared services; contract/snapshot tests cover
names, shapes, errors, paging and project isolation; authorised legacy consumers
have a documented compatible transition, without duplicate implementations.

### Wave 4 — connected evidence and cadence

**DS-10 Canonical intelligence read** (CrawlSEO → Site-Agent)
`depends: DS-03, DS-09` · `deletes: duplicate equivalent parsers and adapter business logic`
CrawlSEO exposes one canonical intelligence response (business facts, research
summary, coverage, actions, visibility, provenance and per-section availability).
Extend existing connector/application contracts rather than add a parallel API.
Use a bounded summary with authorised, paginated detail reads on demand; one
application read path does not mean every evidence row in one network response.
Acceptance: versioned fixtures pass in CrawlSEO and Site-Agent; no paid calls or
mutation on reads; one summary fetch per page load absent explicit refresh/detail
reads, with existing timeout/size limits. Cache follows §6; stale display is visibly
stale, forbidden/auth failure never serves another identity's snapshot, no empty
success disguises failure. Preserve source vs authority provenance. Reproduce and
fix the direct-wrapper envelope/hash defects through shared application semantics,
including full-payload idempotency and changed-payload conflict tests. Keep
transport shape checks and domain validation; not every repeated check is overlap.
Wire the existing CrawlSEO internal Intelligence/detail views to this same contract
for knowledge/coverage/domain provenance and truthful availability. CrawlSEO's own
admin may name its infrastructure; owner-facing Payload copy may not.

**DS-16 Complete remote business-research lifecycle** (business research)
`depends: DS-03, DS-09` · `deletes: none here; enables DS-11 producer retirement`
Inventory existing request/read contracts first. Add only missing scoped request,
status and paginated run/question/source/finding reads. Intake must request and
consume **business research**, not silently substitute the existing paid
domainless keyword recipe. Carry confirmed intake/knowledge revisions, owner
questions, source trust/exclusions, locale and publication-use restrictions.
Implement the additive project-owned business-run change in §6 and update the
runner/status/permissions/identity paths that currently require a site. Source
acquisition and finding synthesis must run without site crawl/action automation;
once bound, existing site-based behavior remains supported. Preserve historical
run IDs and relations; no new parallel business engine or placeholder site.
Acceptance: from registered domainless and existing-site projects, intake can
idempotently request real CrawlSEO business research, await completion, consume
sourced results and handle partial/failure states. Wrong-project requests fail;
reads cause no research/spend. No local fallback; a temporary outage is explicit.
Only request operations with existing approval/budget authority may create work.

**DS-14 Refresh scheduling and cache policy** (collection infrastructure)
`depends: DS-02, DS-03, DS-07, DS-08` · `deletes: duplicate timers and render-triggered collection`
Register collection in existing CrawlSEO jobs/scheduler. Default DataForSEO
refresh is weekly; heavier/on-demand-only datasets must be explicitly identified
in the dataset registry, not silently exempted. Preserve first-party GSC/GA4/Vitals
jobs with source-appropriate cadence and watermarks; hourly polling does not make
delayed source data hourly-fresh. Business research keeps its own policy.
Adapters from DS-04/05/06 register here when ready, without circular dependencies.
Explicit authorised refresh and approved-action rechecks use existing controls.
Acceptance: UI/GET reads make zero paid calls and never wake a refresh. Job leases,
duplicate delivery, restart recovery, provider task polling, rate limits and
backoff use existing infrastructure; uncertain dispatch is reconciled, not replayed.
Persist observation/fetch/refresh times separately, next due time, availability and
failure state; stale retained data is not relabelled fresh. Tests use fake time and
prove no overlapping paid refresh for the same scoped dataset/dimensions.

### Wave 5 — combined judgement and authority cutover

**DS-17 Recommendation synthesis engine**
`depends: DS-03, DS-04, DS-05, DS-06, DS-14, DS-16` · `deletes: independent automated recommendation publication across all inventoried producers`
Build the single synthesis stage described in §1b: a typed input contract, explicit
scope/dimension-aware linkage, concise rationale and stable work identity. Preserve
`ResearchAction` and its action-service/revision/lifecycle contracts. Route business
runner, coverage, technical, keyword and prelaunch proposals through this stage;
retain useful detectors/read projections. Link canonical content metadata, accepted
business facts, findings and published technical/performance evidence without
pretending URLs or question text are globally unique IDs.
Use existing jobs to reassess after relevant evidence revisions or explicit
authorised requests; coalesce triggers, record the input manifest and never run
judgement or mutate recommendations on a UI GET. Cut over producers without double
proposals. Already approved/in-flight actions retain exact revisions and history;
new evidence cannot silently rewrite an approved candidate.
Acceptance: all available domains reach synthesis; missing/stale/conflicting
evidence is explicit; replays dedupe the same work without collapsing independent
work. Referential/tenant/revision validation rejects ungrounded proposals, never
selects strategy. Open-ended analysis is retained; unsupported execution kinds
remain analysis/blocked until an existing capability can prepare an exact candidate,
not automatically executable because a new string is storable.
Evaluate grounding, contextual relevance and non-fabrication with repeatable,
sanitised recorded evidence and human review, without prescribing actions or
embedding worked strategies/weights in prompts. Record model/prompt/input versions
and review results before activation. Link later acceptance/outcome observations
through existing records; no new evaluation store or fixed strategy oracle.

**DS-11 Retire local research authority** (business/search consumers)
`depends: DS-10, DS-16, DS-17` · `deletes: superseded local producers and live research-store access`
Inventory **current** registered tenants, domainless incubations, jobs, local
evidence and in-flight/uncertain actions; do not assume there are exactly two.
Reuse existing freeze/import/cutover receipts and dispatch holds. Prove remote
request → business findings → design/Growth consumption before removing producers.
Include alternate direct analytics/SEO collection paths in that inventory where
they duplicate CrawlSEO-owned evidence. Integration provisioning, model access
and execution credentials remain with their existing owners; do not confuse
provisioning an integration with collecting its analytics through a second authority.
Migrate needed history with stable ID/provenance mapping and reconciled counts/
hashes, or retain it in an explicitly read-only archive. Preserve tenant-local
process, execution, exact approval and outcome records; those are not duplicate
research authority. Schema contraction follows §6, not a table drop on deployment.
Acceptance: cold-start/restart and outage tests cannot resume local research;
domainless intake and existing-site consumers read the correct remote business
research. Each affected tenant has an authorised cutover receipt and live read
proof, with rollback/hold conditions that never reactivate both authorities or
replay uncertain effects. Research-backed design validation uses Ada and its
existing owner review route, never a coding-agent-built substitute. No design
build/publication is triggered just by a data migration.

### Wave 6 — existing execution and owner delivery

**DS-12 Remove obsolete authority configuration** (tenant configuration)
`depends: DS-11` · `deletes: local research authority selection and obsolete branches`
Acceptance: migrate registered configuration and packaged defaults before strict
removal. Old keys produce an actionable migration error, not silent fallback;
new tenants select CrawlSEO automatically when provisioned. No local engine can
restart. Preserve existing cutover fences until their retirement is separately proven.

**DS-13 Connect recommendations to the existing Ada lifecycle** (HelloAda execution)
`depends: DS-10, DS-11, DS-17` · `deletes: competing proposal adapters only if superseded; no new executor`
Ada reads CrawlSEO recommendations, presents them with evidence, waits for owner
approval through the existing candidate/decision path, implements through the
registered site-codebase or canonical Payload path as appropriate, and records a
linked GitHub issue in the registered repository for work taken up. Reuse Growth
work IDs, jobs, approvals, CMS/source guards, exact revision checks, release queue
and immutable receipts. No new task table, scheduler, journal or deployment path.
Acceptance: trace recommendation/evidence revision → initiative/issue → exact
candidate/decision → canonical publication or source release → live verification
→ later impact observation. Code changes have their real commit/release; Payload
content changes have document/revision/publication receipts, **no fake commit**.
Rejection records the decision but causes no live site mutation; stale/revoked
approval and duplicate execution fail safely. Issue close follows technical/live
acceptance, never just merge/upload; failed work remains inspectable. Existing
readiness/permissions/target protection apply. Wix executor/lifecycle is unchanged.

**DS-15 Payload analytics enrichment**
`depends: DS-05, DS-06, DS-10, DS-13, DS-14, DS-17` · `deletes: misleading/dead owner projections, not useful analytics`
Keep existing analytics, add the provider-backed data now available, and expose
reasoning on demand: recommendation → why → evidence → source payload.
Implement in `packages/helloada-payload-admin/src/` and its existing Site-Agent
projection. Retain Growth, analytics, SEO/research/reports/activity and existing
approval controls; expose the action's domains/taxonomy, dependencies, owner role,
last/next assessment and results without adding a second workflow. Source payload
drill-down is an authorised sanitised projection, never credentials/internal URLs.
Acceptance: recommendation-first decisions and progressive evidence detail;
unknown/stale/error/partial states are distinct, unavailable is not healthy, real
visibility retains its cohort/coverage. Every number has accessible provenance,
units/dimensions and measurement state without leaking backend branding. Verify
keyboard/focus behavior, responsive views, loading/empty/error states and tenant
isolation. Exercise the existing causal approved-improvement gate before declaring
the dashboard delivered; use a fresh authenticated Payload session on the exact
released SHA/package/runtime identity. Standalone HelloAda is not a substitute.

## 8. Ongoing task adaptation

These are reconciliation instructions, **not verified current issue statuses or
authorisation to close/merge anything**. Read each live issue/PR, its linked
acceptance and deployed receipts before changing it; preserve unfinished work.

| Existing | Action |
|---|---|
| crawlseo#127 (VERIFY-AEO-001) | Reconcile with DS-01/06's verified dataset/surface; drop "authenticated UI proof" (owner decision 2026-10-29), preserve honest sampling/coverage and existing spend authority. |
| crawlseo#49 (HV-003) | Resequence after DS-06; judge the shipped source only. |
| crawlseo#25 (UI-015) | Keep deferred; re-check after DS-09. |
| crawlseo PR #4 | Recheck current diff/dependencies; no automatic merge or no-conflict claim from this plan. |
| site-agent#468 | Keep; pin identity to the DS-10 canonical call. |
| site-agent#470 | Check its exact acceptance against current deployment/receipt evidence; no assumed delivery or close directive. |
| site-agent#260-268 (growth model series) | Keep the existing growth contract; DS-10 distinguishes upstream source from transport/authority instead of flattening provenance. |
| site-agent#354 | Keep; independent verification. |
| site-agent#458 | Unchanged priority: Astrid intake recovery, ahead of this work. |
| helloada#19 | Close or rewrite: it asks for CrawlSEO links in the owner UI, which contradicts the invisible-backend decision. Replace with a Payload analytics task under DS-15 if still wanted. |

### Earlier work carried forward, not silently superseded

- **UI-026 / UI-023 / UI-024 / UI-025:** retain business-consistency and AI-access
  improvement, knowledge/question coverage, honest visibility availability, domain
  filters/counts, and knowledge revision → finding → source → coverage → action →
  outcome provenance. DS-04/06/17 cover collection/synthesis; DS-10/15 cover
  CrawlSEO internal Intelligence and owner presentation, respectively. Measurement
  gaps do not erase non-measurement AEO capabilities. Domain labels describe
  evidence/work, not a fixed menu limiting model judgement.
- **OPS-010 then OPS-003:** revalidate scope alignment on the real prelaunch path;
  preserve an approved bounded live request plus replay/no-second-spend proof.
  Historical USD 1/month and USD 0.10/operation limits are not reset by this plan.
- **OPS-004 through OPS-008:** retain deployed incubation, canonical knowledge,
  real coverage/observation and chain verification; re-read each issue's actual
  acceptance. DS-16/11 must prove business research, not keyword-only substitution.
- **OPS-012 / OPS-013 / OPS-014 / OPS-009:** preserve production-build/environment checks,
  immutable web/worker/MCP release identity and schema/client compatibility,
  site-less smoke jobs and creation/consumption of canonical business knowledge.
  Passing source tests cannot replace these live checks.
- **HV-001/002/003:** retain human review of visible correctness and research
  relevance. One engine observation is not a multi-engine market view; the earlier
  recurring two-provider coverage requirement stays open until evidenced, but
  does not prohibit a truthfully scoped first measurement.
- **Hardening:** retain a seeded disposable verification tenant/project and
  rollback rehearsal for bad API/Worker releases. Use canonical release tooling;
  rollback rehearsal must not mutate live customer content or replay spend.
- **Growth #260–268:** retain exact candidate approval, engineering-journal linkage,
  canonical publication/release, live technical acceptance and later outcomes.
  `docs/growth-owner-experience-implementation-plan.md` and its linked clarity
  update govern existing UX and workflow, not the earlier mistaken propose-only
  description. The earlier causal gate is not waived by consolidation.

## 9. Definition of done

The consolidation is done when, in production:

1. Exactly one code path calls DataForSEO, and it is CrawlSEO's client.
2. Exactly one search-research orchestrator exists, business research keeps its own
   producer, and both use one evidence envelope.
3. Each capability has one authority; every inventory item is removed after
   parity or explicitly retained as a distinct capability with owner/tests. §5a
   regression checks run in CI; no permanent duplicate path or silent fallback.
4. HelloAda shows analytics and recommendations without any CrawlSEO naming, and
   every number states its source and measurement state.
5. Ada can take an approved recommendation to an implemented, issue-linked change.
6. A UI render performs no paid provider call, and the weekly refresh is visible in
   stored payload timestamps.
7. Local canonical research production and the authority switch are retired after
   reconciled cutover; required history, execution/process state and receipts survive.
8. Business research and search research are still distinct capabilities, sharing
   one evidence/action contract and shared infrastructure where appropriate; no
   task treats DataForSEO as a replacement for business judgement/question synthesis.
9. Every automated recommendation goes through the shared synthesis with combined
   available context, evidence/rationale and reassessment. Explicit human proposals
   and authorised lifecycle updates remain supported; no competing automatic producer.
10. `hand-over`: an agent can start from this plan and the board alone, with no
   tribal knowledge or reliance on superseded plans. Required live proof, build/
   schema gates, human relevance review and rollback rehearsal in §8 are complete;
   remaining measurement limitations are explicit, not reported as delivered.

## 10. Risks and open unknowns

- **Unverified provider behaviour.** DS-01 exists because endpoint shapes, locale
  coverage, AI Optimization availability and costs are not yet measured. Tasks that
  depend on it must not assume the outcome.
- **Crawler parity.** Deleting our crawler is the largest risk. The dual-run gate in
  DS-04 is mandatory; if parity fails, keep our collection and delete only the
  overlapping analysis.
- **Dispatch uncertainty.** No client can guarantee exactly-once vendor charging
  after an ambiguous network failure. Preserve durable claims, provider IDs and
  uncertain-effect reconciliation; never promise retry-based exactly-once spend.
  Costs are not the assessment's decision criterion; existing controls still apply.
- **Evidence semantics.** Replacing GSC-derived fields with vendor estimates changes
  meaning. Invariant 4 exists for this.
- **Migration.** Source/defaults are not a current tenant inventory. DS-11 must
  reconcile active consumers, pending work and retained history before deletion.
- **Over-specifying the synthesis.** Encoding prescribed strategies, examples or
  scoring weights as synthesis decisions produces plausible actions on the cases they
  were written for and silence elsewhere. The plan deliberately stops at the
  evidence contract and the guardrails; a PR that turns judgement into a fixed
  table is rejected.
- **Conflating the research domains.** The most likely design error in this work is
  treating DataForSEO as a business-research provider, or folding `ResearchRun`
  into `SeoResearchRun`. Section 1a exists to prevent it; a PR that merges the two
  producers is rejected regardless of test results.
- **Owner-visible regressions.** Payload UI changes must be verified on the deployed
  release, not only in tests.
- **Security and privacy.** Evidence text cannot authorise tools or publish claims.
  Enforce project scopes, source trust/publication use, target/SSRF restrictions,
  bounded payloads and redaction. Raw provider evidence may contain untrusted or
  sensitive data and is not automatically suitable for owner/browser exposure.
- **Evaluation is not a guarantee.** A good pipeline enables grounded adaptive
  decisions; it cannot guarantee optimal judgement or attribute traffic changes
  causally. Pre-activation evidence review and later outcomes are complementary;
  neither fixed action fixtures nor deployment alone establish recommendation quality.

## 11. Out of scope

- New admission or budget policies; the rejected intake recovery guard stays out.
- Unrelated customer CMS/schema/presentation migration, host policy and repositories.
  Necessary research-history/binding/configuration cutover is **in scope** under
  DS-02/07/11; this plan does not authorise executing it in production.
- A second DataForSEO client or runtime dependency on the official provider MCP.
  The existing CrawlSEO-to-Site-Agent MCP transport remains supported.
- Forcing a shared action model between Wix and HelloAda.
- The Astrid intake recovery (#458), which remains the current priority and is
  tracked separately.

## 12. Implementation readiness and review record

Reviewed 2026-10-29 against the source SHAs in §3, existing Site-Agent Growth and
centralised-intelligence contracts, Prisma models/callers, and current official
DataForSEO OnPage/AI Optimization documentation. This review changed documentation
only; it did not execute paid calls, migrate tenants, deploy, change issues or
prove production behavior. The earlier capability record is corrected separately.

**Ready to start:** DS-02's behavior-preserving extraction and DS-07's scoped
inventory/refactor, following existing tests and contracts. DS-01's documentation/
fixture inventory can start; new live paid calls require the existing spend
authorisation. Astrid recovery remains higher priority. These are bounded starts,
not permission to remove working capabilities ahead of their acceptance gates.

**Gated:** new endpoint adoption needs DS-01 evidence; crawler removal needs DS-04
capability parity; AI visibility claims need DS-06 observation semantics; local
authority removal needs DS-16/17/11 lifecycle and cutover proof. Final UI delivery
needs DS-13/15 plus the carried-forward live causal/release/human gates in §8.
Other tasks start when their explicit dependencies are satisfied.

Before promoting a DS issue to implementation-ready, record its source/contract,
reconciled live issue dependencies, scoped consumer/deletion inventory, required
sanitised fixtures, concrete tests, migration/rollback boundary and release proof.
No-go capability decisions are documented retained boundaries, not forced adoption
or feature deletion. Keep tests deterministic; run concurrency/database/queue
changes twice as required by repository instructions.

Document checks: 17 unique DS tasks, each with declared dependencies, removal
boundary and acceptance; all referenced DS IDs resolve, the dependency graph is
acyclic and no dependency points to a later wave. The 14 overlap-register rows
have owning tasks and semantic regression guards. Earlier UI/proof/hardening
requirements were reconciled into §8 rather than silently dropped. These checks
validate the plan, not implementation or production readiness; no application
test-suite result is claimed for this documentation-only review.

The architecture is aligned for staged implementation. **There is no blanket
"SOTA verified" or production-ready sign-off:** unexecuted provider and tenant
verification gates remain visible and blocking for the changes they protect.
