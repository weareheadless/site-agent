# Ada SEO Research, Strategy, and Article Implementation Plan

## Purpose

Build a durable SEO workflow in which Ada uses her knowledge of the customer,
website, audience, current news, and previous decisions to initiate research,
produce a complete evidence-based report, recommend work, and prepare an article.

The finished workflow must combine:

- the website and its latest technical crawl;
- Google Search Console (GSC);
- Google Analytics 4 (GA4);
- a strictly bounded monthly DataForSEO research batch;
- current RSS and news observations collected by Ada;
- the customer's audience, business goals, languages, and target markets;
- prior proposals, owner feedback, implementation receipts, and measured results.

Ada owns the business reasoning and triggers the monthly research. CrawlSEO owns
provider credentials, data collection, strict paid-task enforcement, and immutable
research storage. Nothing is published or changed on a website without owner
approval.

## Desired Result

```text
Website crawl ───────────────┐
GSC ────────────────────────┤
GA4 ────────────────────────┤
                            ├──> CrawlSEO normalized evidence
Ada's research brief ───────┤              │
DataForSEO fixed batch ─────┘              │ project-scoped MCP
                                           ▼
RSS/news ───────────────────────────────> Ada
Customer config and memory ─────────────> Ada
Prior decisions and outcomes ───────────> Ada
                                           │
                                           ▼
                                  Complete SEO report
                                           │
                              ┌────────────┴────────────┐
                              ▼                         ▼
                     Ranked proposals           Article/site drafts
                              │                         │
                              └────────────┬────────────┘
                                           ▼
                                      Owner review
                                           │
                                           ▼
                                Publish/implement + measure
```

After implementation:

1. Ada decides when monthly research is due and what business questions it must
   answer.
2. Ada chooses the focus language-market and five keyword seeds, then selects a
   verified competitor when the available evidence supports one.
3. CrawlSEO executes no more than nine paid DataForSEO tasks for the customer in
   that calendar month.
4. CrawlSEO combines paid results with current GSC, GA4, and crawl evidence in an
   immutable research report.
5. Ada combines that evidence with fresh news, audience knowledge, business
   context, and historical outcomes in a customer-facing strategy report.
6. Ada prepares a grounded article from the strongest current opportunity.
7. The owner approves or rejects proposed work and can explain why.
8. Ada measures approved work after 30, 90, and 180 days and uses the results in
   future decisions.

## Locked Product Decisions

### Ada is the orchestrator

Ada initiates research because she has the customer-specific context required to
choose useful seeds, markets, competitors, and questions. CrawlSEO must not create
a generic paid report merely because a calendar date arrived.

### CrawlSEO is the collection and financial boundary

CrawlSEO owns:

- Google and DataForSEO credentials;
- tenant and project authorization;
- GSC, GA4, crawl, and DataForSEO collection;
- paid-task limits and idempotency;
- immutable source reports;
- provider-reported cost accounting;
- safe errors and provider task receipts.

Ada owns:

- customer context and business objectives;
- audience and market reasoning;
- fresh news and learned themes;
- seed and competitor selection;
- strategic hypotheses;
- proposals and drafts;
- owner decisions and feedback;
- implementation lineage and outcome learning.

### Paid research is task-bounded, not estimate-bounded

The application cannot depend on knowing the exact DataForSEO cost before a
request. The primary control is therefore a fixed provider-task allowance.

Each customer receives one standard monthly batch with at most nine paid tasks:

| Task | Count |
| --- | ---: |
| Customer domain overview in the focus market | 1 |
| Customer backlinks summary | 1 |
| Related-keyword research for five seeds in the focus market | 5 |
| Competitor domain overview in the focus market, when verified | 0-1 |
| Competitor backlinks summary, when verified | 0-1 |
| **Maximum total** | **9** |

Rules:

- One batch is allowed per customer per closed calendar month.
- A provider task is counted by DataForSEO task, not by HTTP request.
- Paid tasks are never retried automatically.
- Ambiguous timeouts are marked `UNCERTAIN`, not replayed.
- No UI `GET` request or read-only MCP tool may trigger a paid task.
- No ad hoc overflow is allowed in the first version.
- Keyword responses are limited to 50 results per seed.
- Backlink research uses summaries only and does not paginate profiles.
- Actual provider-reported cost is stored for accounting and anomaly detection,
  but it is not the pre-request authorization mechanism.

### Multilingual support does not multiply the first-version cost

All configured languages share the same fixed monthly batch. Ada selects one
focus language-market each month and rotates focus over time.

Examples of distinct language-markets are:

- English in the United States;
- English in the United Kingdom;
- French in France;
- French in Canada.

GSC and GA4 continue observing the complete website across countries and
languages. Only the new paid DataForSEO research is focused on one market each
month. Historical coverage accumulates without increasing the monthly allowance.

Adding a language does not automatically duplicate website pages, create a paid
batch, or change billing in this implementation. Additional research capacity can
be sold later as extra monthly focus-market batches without redesigning the core
workflow.

### Drafting is automatic; effects require approval

Ada may automatically prepare:

- a customer-facing strategy report;
- one article draft selected from the current evidence;
- one site-change brief when a website improvement outranks content work;
- up to five ranked strategic initiatives.

Publishing content, changing the website, or invoking another external mutation
continues to require owner approval and an implementation receipt.

## Two Report Layers

The word "report" refers to two related but separate records.

### CrawlSEO research report

This is an immutable evidence package. It contains normalized source data,
provider results, source timestamps, costs, and the exact research brief submitted
by Ada. It does not make final business decisions.

### Ada strategy report

This is the customer-facing interpretation. It combines the CrawlSEO research
report with current news, audience knowledge, previous decisions, business goals,
and outcome history. It explains what changed, what matters, and what Ada proposes
next.

Separating the layers allows the source evidence to remain reproducible while Ada
continues to improve her reasoning over time.

## Customer Configuration

Add minimal international SEO context to the site-agent configuration. Do not put
DataForSEO-specific location codes, billing limits, or credentials in customer
YAML.

```yaml
seo:
  enabled: true
  source: crawlseo
  site_url: "https://example.com/"
  research:
    enabled: true
    timezone: "Europe/Paris"
    languages:
      - code: en
        markets: [US, GB]
        primary: true
      - code: fr
        markets: [FR, CA]
    existing_locales: [en]
    competitors:
      - domain: "example-competitor.com"
        markets: [US, GB]
        services: ["International consulting"]
    business_goals:
      - "Increase qualified consultation requests"
    priority_services:
      - "International consulting"
    anchor_topics:
      - "international compliance consulting"
      - "cross-border business advisory"
```

Definitions:

- `languages` are languages Ada may understand and write in.
- `markets` are target countries used in business and search reasoning.
- `existing_locales` are languages the website can currently publish.
- `competitors` are candidates, not mandatory monthly selections.
- `anchor_topics` are business concepts, not five permanently repeated paid
  seeds.

Validation rules:

- Language codes use a small validated ISO 639-1 form.
- Market codes use a validated ISO 3166-1 alpha-2 form.
- Exactly one configured language is primary.
- The primary language must appear in `existing_locales`.
- Configuration remains valid with one language and one market.
- Missing research context creates an owner action rather than silently falling
  back to a generic keyword such as `seo`.
- CrawlSEO resolves each language-country pair against DataForSEO Labs'
  current free `locations_and_languages` catalog, scoped to country-level Google
  support, before any paid task is reserved.
- CrawlSEO stores the resolved provider language and location codes with the
  request so the exact external payload remains auditable.
- An unsupported pair is refused with the available languages for that country;
  it is never sent to a paid endpoint.

Billing entitlements and task limits stay in CrawlSEO's server-side policy and
cannot be increased by editing this file.

## Fresh News and Article Behavior

Ada's RSS and news digest remains independent from the monthly paid research
batch. Current news must not wait for another DataForSEO run.

The article planner may use:

- recent RSS/news observations with source URLs and timestamps;
- recurring audience themes;
- the latest GSC queries and landing-page performance;
- the latest GA4 pages, acquisition, engagement, and conversions;
- current and historical DataForSEO keyword research;
- the latest crawl and site structure;
- existing and previously rejected article ideas.

Freshness rules:

- News evidence must include a source URL and observed or published timestamp.
- Ada must distinguish a current event from an evergreen audience theme.
- Claims that may have changed must be grounded in the fetched source.
- Old DataForSEO data remains usable but displays its research date.
- DataForSEO data under 90 days old is current.
- DataForSEO data from 91 to 180 days old is aging.
- DataForSEO data over 180 days old is stale.
- A breaking-news article may use GSC, GA4, historical keyword evidence, and fresh
  source material without spending an additional paid task.
- If a news topic reveals a promising uncovered keyword cluster, Ada adds it to
  the seed backlog for a future monthly expansion slot.

Article output must include:

- target language and market;
- audience and search intent;
- primary topic and supporting keyword evidence;
- news sources and evidence timestamps;
- the relevant business objective;
- a rationale for why the article should exist now;
- internal-link targets;
- title, description, and structured outline;
- complete article markdown;
- an explicit review state.

Ada writes in the selected language for that audience. She must not translate an
English keyword list literally and claim it represents another market.

## Monthly Workflow

Ada runs a daily reconciliation job. It acts only when a monthly state requires
work, so downtime catch-up is safe and no exact calendar alarm is required.

Use these states:

```text
WAITING_FOR_MONTH_CLOSE
PREPARING_RESEARCH_BRIEF
REPORT_REQUESTED
WAITING_FOR_CRAWLSEO
BUILDING_STRATEGY
DRAFTED_FOR_REVIEW
MONITORING_OUTCOMES
```

### Step 1: Identify the closed month

On day 4 or later in the customer's timezone, Ada identifies the previous
calendar month. The delay allows late GSC data to settle. Ada checks durable local
state before doing any work.

The existing site-agent scheduler's `monthly` value is a 30-day interval, not a
calendar-month primitive. The research workflow must therefore use a daily
reconciliation job and an explicit `YYYY-MM` period key.

### Step 2: Gather pre-research context

Ada gathers:

- current customer configuration and effective persona;
- active business goals and priority services;
- all configured languages and target markets;
- latest GSC and GA4 summaries;
- country, query, and landing-page opportunities where available;
- latest crawl summary and technical issues;
- recent news, RSS observations, and learned themes;
- previous research reports and seed coverage;
- active strategies and measured outcomes;
- pending, approved, and rejected work;
- owner feedback and reasons;
- previous articles to avoid repetition.

### Step 3: Select the focus market

Ada selects one language-country pair using:

- business priority;
- GSC impressions, clicks, position, and growth by country;
- GA4 traffic and conversion behavior where country data is available;
- time since the market was last researched;
- whether the website can currently publish the language;
- owner instructions;
- active strategic hypotheses.

The primary market should receive regular attention, but rotation is not a blind
round-robin. Ada records why the market was selected.

If the selected language is not in `existing_locales`, Ada may research the
market, but site content becomes a localization proposal rather than an
immediately publishable article.

### Step 4: Select five seeds

Use exactly five unique seeds:

| Slot | Count | Purpose |
| --- | ---: | --- |
| Strategic | 2 | Support current business priorities |
| Expansion | 2 | Explore useful, previously uncovered clusters |
| Adaptive | 1 | Respond to GSC, audience, news, or outcome signals |

Rules:

- A seed is always associated with its language and market.
- The registry identity is `normalized seed + language + market`.
- Ada checks historical seeds and related-keyword results before spending a slot.
- Exact duplicates and obvious wording variants are rejected.
- Repeating a seed requires a freshness or strategic justification.
- A seed must map to a real audience need and business objective.
- If Ada cannot justify five seeds, she creates an owner-information action and
  does not trigger paid research.

### Step 5: Select the competitor

Competitor research is optional and never blocks the monthly report. Ada ranks
configured hints and structured competitor candidates already present in the
customer's first-party context using category, service, language, and market
signals. A candidate must have meaningful in-category evidence before it can be
used for paid domain and backlink tasks.

Ada must not invent a domain or spend a task merely to fill the allowance. If no
candidate is sufficiently supported, the brief stores `competitor: null`, the
two competitor tasks are omitted, and the report discloses insufficient
competitor evidence. An owner-provided domain remains a hint unless its category
and market fit can be supported.

### Step 6: Persist the research brief

Ada stores the brief locally before making an MCP call. The brief includes:

```json
{
  "period": "2026-08",
  "focus_market": {"language": "fr", "country": "FR"},
  "business_goal": "Increase qualified consultation requests",
  "audience": ["French companies expanding internationally"],
  "priority_services": ["Cross-border business advisory"],
  "keyword_seeds": ["five distinct seeds"],
  "competitor": null,
  "research_questions": ["What should the next article help this audience solve?"],
  "selection_rationale": {
    "market": "Why this market matters now",
    "seeds": ["One reason per seed"],
    "competitor": "Why this competitor is relevant, or why competitor research was skipped"
  },
  "package": "standard-v1"
}
```

Ada computes a stable idempotency key from project, site, period, and package
version.

### Step 7: Request and monitor CrawlSEO research

Ada invokes a project-scoped command. CrawlSEO validates the request, creates or
returns the existing research run, and queues durable work.

Later Ada reconciliation runs poll status. They do not resubmit a different brief
for the same period.

Before any paid task is attempted, CrawlSEO checks the report prerequisites:

- the latest successful GSC synchronization covers the closed reporting period;
- the latest successful GA4 synchronization covers the closed reporting period;
- a completed crawl exists and is no more than 30 days old;
- the project grants and site still belong to the authenticated project;
- the DataForSEO credential grant is active.

If a first-party source is stale, CrawlSEO queues its existing durable sync or
crawl job with a period-specific idempotency key and leaves the report in
`WAITING_FOR_SOURCES`. The report coordinator checks again after those jobs finish.
GSC, GA4, and crawl jobs do not consume the nine-task DataForSEO allowance.

Paid work begins only after the prerequisite stage reaches a terminal result. A
failed first-party refresh is recorded in the source manifest. CrawlSEO may still
produce a clearly marked partial report when enough evidence remains useful, but
it must never represent a failed or missing source as a zero value.

### Step 8: Build the strategy report

When CrawlSEO returns a completed or usable partial report, Ada builds the
customer-facing report exactly once.

The report contains:

1. Plain-language executive summary.
2. Data freshness and missing-source disclosure.
3. Website health and material crawl changes.
4. GSC search performance and opportunities.
5. GA4 traffic, engagement, and conversion behavior.
6. Focus-market and keyword findings.
7. Competitor and backlink context.
8. Current audience/news themes and why they matter.
9. Results from previously implemented strategies.
10. Ranked initiatives with evidence and expected outcomes.
11. The selected article opportunity and article brief.
12. Work requiring owner review.

Every recommendation references evidence IDs or stable report paths. Ada states
when evidence is thin and does not hide partial provider failures.

### Step 9: Prepare proposals and drafts

Per monthly strategy cycle, Ada creates at most:

- five ranked strategy initiatives;
- one complete article draft;
- one site-change brief if justified;
- one customer-facing report artifact.

Equivalent pending or recently rejected proposals are not recreated unless new
evidence directly addresses the prior rejection.

### Step 10: Measure approved work

After a successful implementation or publishing receipt, Ada captures a baseline
and evaluates the initiative after 30, 90, and 180 days.

Outcomes are classified as:

- `POSITIVE`;
- `NEUTRAL`;
- `NEGATIVE`;
- `INCONCLUSIVE`.

Ada avoids causal claims when several changes overlap or the data is insufficient.

## CrawlSEO Data Model

Extend `/SEO/prisma/schema.prisma` additively.

### `ProjectApiKeyGrant`

Purpose: bind a project explicitly to its DataForSEO credential instead of
resolving credentials through `Site.userId`.

Required fields:

- `id`;
- `projectId`;
- exactly one of `apiKeyId` (user BYOK) or `providerCredentialId`
  (platform-managed credential);
- `provider`;
- `status`;
- `lastValidatedAt`;
- `createdAt`;
- `updatedAt`.

Enforce one active grant per project and provider.

### `ProviderCredential`

DataForSEO authenticates at the account level and does not expose documented
REST project/subaccount creation. CrawlSEO therefore stores one encrypted
platform credential and grants it explicitly to each internal project. The
project, research run, task, and report boundaries provide customer isolation;
provider billing remains account-level.

### `SeoResearchPolicy`

Purpose: store server-controlled entitlements.

Required fields:

- `id`;
- `projectId`;
- `siteId`;
- `enabled`;
- `monthlyTaskLimit`, default `9`;
- `keywordSeedLimit`, default `5`;
- `competitorLimit`, default `1`;
- `packageVersion`, default `standard-v1`;
- timestamps.

This policy does not store customer business strategy.

### `SeoResearchRun`

Required fields:

- project and site references;
- calendar period start;
- client idempotency key;
- immutable research brief JSON;
- brief hash;
- package and report schema versions;
- status;
- task allowance and attempted count;
- actual cost in integer micro-dollars;
- normalized report JSON;
- source manifest JSON;
- safe error code;
- requested, started, and completed timestamps.

Enforce uniqueness for site, period, and package version. A duplicate request
returns the existing run and cannot replace its brief.

### `SeoResearchTask`

Required fields:

- research run reference;
- operation key;
- task kind;
- ordinal where relevant;
- safe normalized input JSON;
- request hash;
- status;
- provider task ID;
- provider-reported cost in micro-dollars;
- bounded normalized response JSON;
- attempted and completed timestamps;
- safe error code.

Task statuses:

```text
RESERVED
ATTEMPTING
COMPLETED
FAILED
UNCERTAIN
```

Enforce one task per operation key within a run.

Research run statuses must distinguish source preparation from paid execution:

```text
REQUESTED
WAITING_FOR_SOURCES
RUNNING_PAID_RESEARCH
COMPLETED
PARTIAL
FAILED
```

### Job extensions

Add:

- `SEO_RESEARCH` to `JobKind`;
- `DATAFORSEO` to `SyncSource`.

The batch job may be reclaimed after a worker failure, but the worker only
continues `RESERVED` tasks. It never invokes an `ATTEMPTING`, `COMPLETED`,
`FAILED`, or `UNCERTAIN` paid task again.

Add a small report coordinator around the existing durable queue rather than a
second generic dependency system. On each reconciliation pass it:

1. Enqueues missing GSC, GA4, or crawl prerequisites idempotently.
2. Waits while prerequisite jobs remain pending or running.
3. Records terminal prerequisite failures in the source manifest.
4. Queues `SEO_RESEARCH` only when the source stage is terminal.
5. Finalizes the normalized report after the paid batch is terminal.

## CrawlSEO Provider Refactor

Refactor `/SEO/lib/dataforseo/client.ts` so raw credential-backed functions are
not imported directly by pages or MCP tools.

Add a guarded research executor that:

1. Receives a persisted `SeoResearchTask`.
2. Atomically marks it `ATTEMPTING` and commits before network I/O.
3. Makes exactly one provider task.
4. Parses task ID, status, cost, and bounded result data.
5. Stores a normalized response.
6. Marks ambiguous outcomes `UNCERTAIN`.
7. Redacts credential-shaped and unexpected fields.
8. Refuses direct calls without a reserved task and research run.

Close current paid-call bypasses in:

- `/SEO/app/api/sites/[siteId]/keyword-research/route.ts`;
- `/SEO/app/api/sites/[siteId]/domain-overview/route.ts`;
- `/SEO/app/api/sites/[siteId]/backlinks/route.ts`;
- `/SEO/mcp/project-tools.ts`.

New behavior:

- Keyword UI searches the persisted keyword catalog and can fall back to Google
  Autocomplete.
- Domain UI reads the latest report and can fall back to GSC.
- Backlinks UI reads the latest report and crawl-derived external links.
- Existing DataForSEO MCP read tools return persisted results only.
- Only the durable research worker can invoke paid provider endpoints.

## CrawlSEO MCP Contract

Add project-scoped tools:

### `seo_request_research_report`

This is the only Ada-facing command that can lead to paid work.

It requires a separate scope such as `seo:research:request`, validates the
standard brief, enforces the monthly policy, and returns:

```json
{
  "report_id": "...",
  "period": "2026-08",
  "status": "requested",
  "task_limit": 9,
  "existing": false
}
```

### `seo_get_research_report_status`

Returns safe run status, source completion, partial failures, and timestamps.

### `seo_get_research_report`

Returns the immutable completed or partial evidence report by report ID.

### `seo_get_latest_research_report`

Returns the latest usable report for the authenticated project.

### `seo_list_research_reports`

Returns bounded report metadata for historical comparison.

Keep Ada's adapter finite. Do not expose arbitrary MCP tool invocation.

## Ada Persistence

Increment `SCHEMA_VERSION` in
`/SOCIAL/site-agent/src/site_agent/core/memory.py` and add an append-only
migration.

### `seo_research_requests`

Store:

- calendar period;
- idempotency key;
- research brief JSON and hash;
- CrawlSEO report ID;
- local workflow status;
- requested and completed timestamps;
- safe error code.

Enforce one request per calendar period and package version.

### `seo_seed_registry`

Store:

- normalized seed;
- language;
- market;
- coverage cluster;
- business objective;
- priority and status;
- first and last researched timestamps;
- research count;
- latest report ID;
- usefulness assessment;
- freshness state.

### `seo_seed_selections`

Link each research request to exactly five seeds and record its slot type,
rationale, and ordinal.

### `strategy_cycles`

Store one cycle per CrawlSEO report ID, including period, report hash, summary,
status, the customer-facing report artifact reference, and timestamps.

### `strategy_initiatives`

Store:

- initiative kind;
- language and target markets;
- title and concrete proposed action;
- hypothesis and rationale;
- evidence references;
- expected outcome and target metrics;
- priority and state;
- review dates;
- parent initiative when continuing earlier work;
- links to owner action, draft, artifact, approval, execution job, and receipt.

### `strategy_decisions`

Append owner approvals, declines, deferrals, revisions, and reasons. Do not rely
only on the current action state to reconstruct history.

### `strategy_outcomes`

Store initiative, horizon, baseline, observed metrics, assessment, confidence,
notes, and measurement timestamp.

## Ada Application and Adapter Changes

Update:

- `src/site_agent/core/contracts.py`;
- `src/site_agent/application/crawlseo.py`;
- `src/site_agent/hands/crawlseo.py`;
- `src/site_agent/core/jobs.py`;
- `src/site_agent/defaults.yaml`;
- `src/site_agent/config.py`;
- instance configuration examples;
- CrawlSEO adapter tests.

Preserve a clear separation between:

- fixed validated read operations;
- the explicit research-request command;
- website and publishing mutations.

Add a daily `seo_research_cycle` reconciliation job. Do not make the existing
weekly `strategist` independently invent a competing strategy. The weekly job
should monitor active initiatives, current metrics, and urgent news between
monthly cycles.

## Strategy and Article Changes

Refactor `src/site_agent/brain/strategist.py` into two modes:

### Monthly strategy mode

Consumes a completed research report and creates the durable strategy cycle,
initiatives, customer report, and selected content opportunity.

### Weekly monitoring mode

Reviews active initiatives, first-party metric changes, fresh news, and pending
owner decisions. It may flag a timely article or urgent technical issue, but it
does not spend DataForSEO tasks or replace the monthly strategy.

Refactor `src/site_agent/brain/article.py` so it can receive a structured article
brief from a strategy initiative. Preserve the existing editorial path for cases
where Ada has a strong fresh-news opportunity between monthly reports.

The article planner must always check:

- pending and published drafts;
- recent owner feedback;
- current source evidence;
- target language support;
- keyword freshness;
- business relevance;
- internal linking opportunities;
- whether the topic is materially different from prior work.

## Website Localization Boundary

Multilingual support in reasoning does not automatically create duplicate pages.

If strategy selects a language not currently published by the site, Ada creates a
localization proposal describing:

- proposed locale URL prefix;
- navigation and language selector changes;
- core pages requiring localization;
- self-referencing canonicals;
- `hreflang` relationships;
- sitemap changes;
- editorial review requirements.

The owner approves this website-level change before Ada creates or publishes the
localized site structure.

One content language may serve several target countries. Separate website variants
are only proposed when offers, terminology, legal requirements, or audience needs
materially differ. Market research and website duplication are not equivalent.

## Data Freshness and Evidence Manifest

Every CrawlSEO report includes a source manifest with:

- source name;
- source record or snapshot ID;
- covered period;
- fetched or completed timestamp;
- freshness state;
- status;
- safe error code when incomplete.

Ada's report additionally references news observation IDs and URLs. The report UI
must disclose missing and stale sources instead of rendering them as zero values.

Recommended first-party windows:

| Window | Purpose |
| --- | --- |
| 28 days | Current operating performance |
| Previous 28 days | Short-term comparison |
| 3 completed months | Trend confirmation |
| 6 completed months | Strategic direction |

For new customers, missing historical windows are explicitly marked
`INSUFFICIENT_HISTORY`.

## Outcome Measurement

Use initiative-specific primary metrics:

| Initiative | Example primary metrics |
| --- | --- |
| New article | Impressions, clicks, ranking queries, organic entrances |
| Title or description change | CTR and average position for the target page |
| Internal linking | Target-page impressions, position, and crawl depth |
| Technical repair | Issue count, indexability, and health score |
| Conversion-page revision | Organic entrances and configured GA4 conversions |

Capture baseline data at implementation time. Evaluate equivalent periods after
30, 90, and 180 days. Store raw comparisons and Ada's bounded interpretation.

## Implementation Phases

### Phase 1: Contracts and configuration

1. Add and validate multilingual research configuration in site-agent.
2. Define research brief, report, seed, initiative, and outcome contracts.
3. Define MCP command/read schemas and safe response limits.
4. Add contract and configuration tests before provider work.

### Phase 2: CrawlSEO persistence and credential binding

1. Add Prisma enums, models, relations, indexes, and migration.
2. Add project-level DataForSEO credential grants.
3. Backfill the existing OceanicVibes project binding safely.
4. Add tenant-isolation and migration tests.

### Phase 3: Strict provider executor

1. Add task reservation and one-attempt execution.
2. Capture provider task IDs and actual costs.
3. Implement normalized result schemas and size bounds.
4. Prevent retries after any attempted network operation.
5. Convert UI and MCP reads to persisted data.
6. Add architectural tests proving read paths cannot call paid endpoints.

### Phase 4: Durable research batch and MCP

1. Add `SEO_RESEARCH` worker support.
2. Add the request, status, report, latest, and list MCP tools.
3. Add the separate research-request service scope.
4. Verify idempotency, partial reports, worker recovery, and task limits.

### Phase 5: Ada memory and reconciliation

1. Add the SQLite migration and memory methods.
2. Add focus-market and seed selection.
3. Add the daily research-cycle state machine.
4. Add MCP request and polling through a finite adapter.
5. Add catch-up and duplicate-processing tests.

### Phase 6: Complete report and strategy

1. Build the immutable report ingestion path.
2. Add the customer-facing report renderer and artifact.
3. Create evidence-linked initiatives and owner actions.
4. Align the weekly strategist with the active monthly strategy.
5. Add partial-data and invalid-LLM-response handling.

### Phase 7: News-grounded article drafting

1. Add structured article briefs to strategy initiatives.
2. Combine fresh news, audience context, GSC, GA4, and accumulated keyword data.
3. Generate one complete pending article draft.
4. Add citations/source metadata to draft metadata.
5. Preserve owner approval before publishing.
6. Test stale news, unsupported languages, duplicate topics, and missing evidence.

### Phase 8: Outcomes and continuity

1. Link approvals and provider receipts to initiatives.
2. Capture implementation baselines.
3. Add 30, 90, and 180-day evaluation jobs.
4. Feed decisions and outcomes into later market, seed, and article selection.

### Phase 9: Controlled rollout

1. Run all provider behavior against fixtures first.
2. Deploy schema and application changes without enabling research.
3. Provision the OceanicVibes research policy and updated service scope.
4. Generate one Ada research brief without submitting it and inspect it.
5. Run one controlled live monthly batch.
6. Verify that no more than nine paid tasks were attempted.
7. Verify the complete report, strategy initiatives, and pending article.
8. Enable recurring reconciliation after owner review.

## Tests

### CrawlSEO

Tests must prove:

- one report per site, period, and package version;
- duplicate requests return the original report;
- exactly five unique seed tasks are accepted;
- no more than one verified competitor is accepted;
- no report exceeds nine paid tasks;
- a task is marked attempted before network I/O;
- an attempted or uncertain task is never invoked again;
- worker recovery continues only reserved tasks;
- partial reports preserve successful results;
- project credentials cannot cross tenant boundaries;
- credentials and authorization headers never enter persisted JSON;
- provider cost is captured when present;
- UI GET routes and read MCP tools cannot invoke DataForSEO;
- response size and field bounds are enforced;
- language-country inputs map only through an allowlisted provider mapping.

### Ada

Tests must prove:

- multilingual config validation and defaults;
- one primary language is required when research is enabled;
- each calendar period is requested at most once;
- downtime catch-up uses the same period idempotency key;
- focus-market selection records its rationale;
- seed selection produces two strategic, two expansion, and one adaptive seed;
- duplicate language-market seed clusters are rejected;
- each CrawlSEO report creates at most one strategy cycle;
- partial source reports are disclosed, not treated as complete;
- fresh news includes source metadata;
- an article can be drafted without an ad hoc DataForSEO request;
- unsupported site languages create localization proposals;
- automatic drafts remain pending owner approval;
- owner feedback is persisted and affects later proposals;
- outcome jobs wait for sufficient history;
- invalid LLM output cannot create unbounded actions or drafts.

### Verification commands

```bash
# /SEO
npm test
npx tsc --noEmit
npm run build
npx prisma validate
git diff --check

# /SOCIAL/site-agent
.venv/bin/pytest -q
```

## Acceptance Criteria

The first version is complete when all of the following are true:

1. Ada detects that the previous calendar month is ready for analysis.
2. Ada analyzes the customer config, website, audience, fresh news, GSC, GA4,
   previous research, owner feedback, and outcomes.
3. Ada selects and persists one justified focus language-market and five justified
   seeds, and uses one justified competitor when one can be verified.
4. Ada triggers the CrawlSEO report through an authenticated project-scoped
   command.
5. CrawlSEO executes at most nine paid tasks and never automatically retries an
   attempted task.
6. CrawlSEO returns a reproducible report containing website, GSC, GA4, crawl,
   DataForSEO, cost, and freshness evidence.
7. Ada produces a complete plain-language strategy report incorporating current
   audience/news context.
8. Ada creates evidence-linked initiatives and one complete article draft in an
   appropriate supported language.
9. No article is published and no website change is applied without owner
   approval.
10. Approved work is linked to implementation receipts and later 30, 90, and
    180-day outcomes.
11. Historical seed and market coverage grows over time while the default monthly
    paid-task allowance remains fixed.

## Non-Goals for the First Version

- Running a separate paid batch for every language or country.
- Automatically translating every article into every configured language.
- Automatically creating multilingual website structure at intake.
- Discovering competitors through additional paid calls.
- Ad hoc paid keyword research from the dashboard or chat.
- Fully automated publishing or website mutation.
- Proving causal impact from correlated SEO changes.
- Building per-language billing before real customer usage demonstrates the need.

These constraints preserve the central product value: Ada performs informed,
current, customer-specific SEO work without turning multilingual support or paid
provider accounting into a blocking system.
