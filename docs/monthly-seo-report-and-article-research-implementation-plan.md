# Monthly SEO Report and Audience-Led Article Research Implementation Plan

## Purpose

Implement two separate, deliberately simple workflows for Ada:

1. A monthly website SEO report, based on current first-party evidence and the
   article research paid for during the month, that is available in Ada's owner
   UI.
2. An audience-led article workflow in which Ada chooses an article idea first,
   then runs one paid DataForSEO keyword task to improve that idea before she
   drafts the article.

The governing editorial rule is:

> Audience interest creates the idea. Keyword research improves Ada's
> understanding of it. Search demand never receives editorial authority.

This document supersedes the article-generation and paid-research portions of
`docs/ada-seo-research-strategy-implementation-plan.md`. The existing CrawlSEO
connectivity plan remains applicable for authentication, tenant isolation,
Google credentials, durable jobs, and MCP transport.

## Locked Product Decisions

### Monthly website report

- Ada produces one website SEO report for each closed calendar month.
- The report uses GSC, GA4, and a current technical crawl.
- It compares the report month with prior periods where data exists.
- It contains a short prioritized list of concrete, actionable improvements.
- It never triggers DataForSEO, but it summarizes relevant article research
  already paid for and completed during the report period.
- It does not include backlink metrics.
- It does not generate an article or article brief.
- It is readable in Ada's UI without requiring approval.
- Site changes recommended by the report still require owner approval before
  implementation.

### Article workflow

- Ada may brainstorm freely without making paid requests.
- Ada selects at most one article candidate every seven days.
- The idea must originate from fresh news, an audience concern, a recurring
  community question, Ada's recent learning, or another customer-relevant
  observation.
- The selected idea exists and is persisted before keyword research starts.
- Each selected idea triggers exactly one DataForSEO related-keywords task.
- A paid task may enrich or reframe the idea, but may not replace it with an
  unrelated higher-volume topic.
- Low or zero search volume does not automatically reject an article.
- A completed research note is required before Ada drafts the article.
- Ada produces at most one article draft from each selected idea.
- Publication remains owner-approved.

### Cost control

Keep cost control count-based and server-enforced:

- one paid task per selected article idea;
- at least seven days between paid article research attempts for a site;
- at most five paid article research tasks per site per calendar month;
- no automatic retries of a paid task;
- idempotency prevents duplicate submissions;
- provider task ID and actual provider-reported cost are stored;
- a single policy/configuration switch disables article research.

### Paid research history

- CrawlSEO retains every normalized paid result, provider task ID, request hash,
  market, timestamp, status, and actual cost.
- Ada retains the article idea, her compact interpretation, the resulting draft
  lineage, and eventual owner/publication outcome.
- Future idea selection receives prior research notes so Ada can avoid repeating
  an idea or paying to rediscover the same audience language.
- The monthly report summarizes research completed during that month: what Ada
  investigated, what she learned, what changed in the article, what it cost, and
  whether the article was drafted, approved, declined, or published.
- Historical keyword evidence remains dated evidence. Ada must display or reason
  about its age instead of treating it as current indefinitely.
- Reuse means informing later decisions and reports. It does not mean dumping
  every historical keyword row into every prompt.

Do not add cost forecasting, keyword scoring, multiple paid research stages,
automatic task expansion, or a general-purpose billing engine in this version.

### Explicit exclusions

- No backlink research in either workflow.
- No competitor backlink research.
- No paid domain overview in either workflow.
- No five-seed monthly package.
- No keyword-density target.
- No exact-match keyword requirement in titles or headings.
- No automatic article rejection based only on search volume.
- No article generated directly from the monthly website report.
- No paid task initiated by a monthly report, read-only endpoint, or UI page
  load.

## Target Architecture

```text
MONTHLY WEBSITE LOOP

Ada daily reconciliation
        |
        +--> CrawlSEO prepares closed-month GSC + GA4 + current crawl
        |              |
        |              +--> project-scoped first-party evidence
        |
        +--> Ada merges first-party evidence with persisted article research
        +--> Ada interprets evidence
                       |
                       +--> monthly SEO report artifact
                       +--> report visible in owner UI
                       +--> optional owner-reviewed site actions


WEEKLY EDITORIAL LOOP

News / audience concern / Ada learning
        |
        +--> Ada chooses one editorial hypothesis
                       |
                       +--> persisted article idea
                                     |
                                     +--> one paid related-keywords task
                                                   |
                                                   +--> compact research note
                                                                 |
                                                                 +--> Ada drafts article
                                                                 +--> owner review
                                                                 +--> publish + measure
```

## Repository Responsibilities

### CrawlSEO (`/SEO`)

CrawlSEO remains the collection, authorization, and paid-task boundary. It owns:

- Google and DataForSEO credentials;
- project and site authorization;
- durable GSC, GA4, crawl, and article-research jobs;
- first-party evidence preparation;
- the one-task article research limit;
- seven-day and monthly task-count enforcement;
- idempotency and provider receipts;
- durable normalized article-research history;
- actual DataForSEO cost storage;
- safe, project-scoped MCP contracts.

CrawlSEO does not decide whether an idea is worth writing and does not write the
monthly customer-facing report.

### site-agent (`/SOCIAL/site-agent`)

site-agent owns:

- the monthly report schedule and interpretation;
- the article idea and its editorial provenance;
- selecting no more than one weekly candidate;
- requesting and polling ad-hoc keyword research;
- interpreting keyword results into a compact research note;
- reusing prior research notes in future editorial decisions;
- merging the month's article-research history into the monthly report;
- drafting the article from the original idea plus that note;
- owner UI, drafts, approvals, publication, and later outcome measurement.

## Workflow A: Monthly Website SEO Report

### Report period

Use the previous closed calendar month in the configured SEO timezone. The
reconciliation job may run daily, but uniqueness guarantees one report per site
and month. Daily reconciliation is necessary because source jobs are
asynchronous; a monthly poll would leave a requested report waiting for another
month.

Example:

- On any day in September, the due report period is August 1 through August 31.
- Repeated runs prepare or poll the same August report.
- Once completed, subsequent runs are no-ops.

### Required evidence

CrawlSEO should return one bounded evidence object containing:

```json
{
  "schema_version": 1,
  "period": "2026-08",
  "status": "ready",
  "gsc": {
    "status": "ready",
    "period_start": "2026-08-01",
    "period_end": "2026-08-31",
    "clicks": 0,
    "impressions": 0,
    "ctr": 0,
    "position": null,
    "top_queries": [],
    "top_pages": [],
    "previous_period": {}
  },
  "ga4": {
    "status": "ready",
    "period_start": "2026-08-01",
    "period_end": "2026-08-31",
    "totals": {},
    "top_pages": [],
    "sources": [],
    "previous_period": {}
  },
  "crawl": {
    "status": "ready",
    "crawl_id": "...",
    "finished_at": "...",
    "health_score": 95,
    "page_count": 1,
    "issue_count": 4,
    "issues": []
  },
  "recent_content": [],
  "freshness": {
    "gsc_sync_run_id": "...",
    "ga4_snapshot_id": "...",
    "crawl_id": "..."
  }
}
```

The exact metric fields should reuse existing normalized GSC, GA4, and crawl
shapes where possible. Do not expose credentials, raw provider errors, or
unbounded page/link data.

### Ada-local article research evidence

The first-party evidence object remains free of paid-provider execution. Before
writing the report, site-agent separately reads its persisted `article_ideas`
for the report month and builds a bounded editorial-research section:

```json
{
  "article_research": {
    "attempted_count": 1,
    "completed_count": 1,
    "actual_cost_micros": 10000,
    "items": [
      {
        "idea_id": 123,
        "working_title": "...",
        "audience_need": "...",
        "research_seed": "...",
        "research_decision": "reframe",
        "key_learning": "...",
        "research_run_id": "...",
        "provider_task_id": "...",
        "researched_at": "...",
        "draft_id": 456,
        "draft_status": "approved",
        "published_at": null
      }
    ]
  }
}
```

Use compact notes and lineage in the report prompt, not all keyword rows. The
full normalized provider result remains retrievable from CrawlSEO by its run ID
for audit or focused reuse.

### CrawlSEO preparation operation

Add one idempotent MCP mutation:

`seo_prepare_monthly_site_evidence`

Arguments:

```json
{
  "period": "2026-08",
  "idempotency_key": "site-report:2026-08:v1",
  "max_crawl_pages": 200
}
```

Behavior:

1. Require project scopes for SEO read, analytics read, crawl read, and crawl
   run.
2. Resolve only the authenticated project's site.
3. Queue or reuse a GSC sync for the exact closed month.
4. Queue or reuse a GA4 sync for the exact closed month.
5. Reuse a completed crawl no older than 30 days; otherwise queue one.
6. Return source states and job IDs without waiting for completion.
7. Never invoke DataForSEO.

Add one read-only MCP tool:

`seo_get_monthly_site_evidence`

Arguments:

```json
{"period": "2026-08"}
```

Behavior:

- return `waiting_for_sources` until all required source coverage exists;
- return `ready` with the bounded evidence object when complete;
- return a safe terminal source error when a prerequisite cannot complete;
- never enqueue a job and never trigger paid work.

Prefer these two narrow tools over creating a second generic orchestration
framework. Reuse the readiness and evidence-assembly logic already present in
`lib/dataforseo/research.ts`, but move first-party helpers to a neutral module
such as `lib/reports/monthly-site-evidence.ts` so they no longer belong to a
paid-research namespace.

### Ada report state machine

Add a daily `seo_site_report_cycle` job:

```text
missing local run
    -> persist preparing row
    -> call prepare operation once

preparing/waiting
    -> call read-only evidence operation
    -> remain waiting, fail safely, or continue

ready
    -> ask Ada to interpret evidence
    -> persist report artifact and report record
    -> mark completed

completed
    -> no-op
```

The report prompt must request:

- a plain-language performance summary;
- what materially changed from the previous period;
- data quality/freshness limitations;
- technical crawl findings that are actually actionable;
- the performance of recent content where attribution is available;
- paid article research completed during the month, including total actual cost,
  useful audience-language discoveries, and the resulting article state;
- no more than three prioritized recommendations;
- no article idea or article brief;
- no backlink commentary;
- no invented numbers or URLs.

The report should connect research to editorial outcomes, but it must not rank
ideas by keyword volume or turn the research ledger into new article briefs.

If the LLM fails, retain the evidence and leave the run retryable without
re-running source collection. Do not publish a fabricated fallback narrative.

### Monthly report persistence

Add one small site-agent table, for example `seo_site_reports`:

```text
id
period                    UNIQUE
status                    preparing | waiting | completed | failed
evidence_hash
evidence_json
summary
artifact_id
created_ts
updated_ts
completed_ts
error
```

Use the existing `ArtifactKind.SEO_REPORT` and `seo_report` renderer for the
readable body. Do not require approval merely to view the report. If Ada creates
a site-change proposal from a recommendation, that proposal uses the existing
artifact and approval flow.

Calculate `evidence_hash` from the canonical first-party evidence plus the
bounded article-research section. Once a monthly report is completed, do not
rewrite it when an article is approved or published later; that later state is
historical context for the next report. This keeps each monthly report
reproducible without adding an append-only storage system.

### UI requirements

Update the existing Home > Report area in
`src/site_agent/web/static/admin.html` rather than adding a new framework or
top-level application.

Add:

- a clear "Website SEO" report view;
- report month and generation timestamp;
- source freshness badges for GSC, GA4, and crawl;
- article-research task count and actual cost for the month;
- the rendered report body;
- a compact history selector/list for prior months;
- a waiting state that explains which source is pending;
- a safe failure state with a retry/reconciliation message;
- responsive behavior consistent with the existing owner UI.

Add read-only HTTP routes in `src/site_agent/web/server.py`:

```text
GET /api/seo/site-reports/latest
GET /api/seo/site-reports?limit=12
GET /api/seo/site-reports/{report_id}
```

These routes read local persisted reports only. They must not contact CrawlSEO,
run source jobs, or make LLM calls.

Keep the existing weekly report available if it remains a product feature, but
label the two reports unambiguously. Do not let `/api/report/latest` silently
mix weekly and monthly SEO reports.

## Workflow B: Audience-Led Article With Ad-Hoc Keyword Research

### Step 1: Select and persist the idea

Refactor `src/site_agent/brain/article.py` so topic selection and article writing
are separate operations.

The free idea-selection prompt receives:

- recent sourced news;
- recent community observations and learned themes;
- Ada's fresh concerns or inner editorial context where appropriate;
- customer audience and business context;
- GA4 top pages and GSC observations as background, not commands;
- compact notes from prior paid article research, including their dates;
- previously drafted, approved, declined, and discarded article ideas.

It returns a bounded editorial hypothesis:

```json
{
  "working_title": "...",
  "audience_need": "...",
  "reader_question": "...",
  "reader_situation": "...",
  "reader_intent": "...",
  "business_relevance": "...",
  "market_context": "...",
  "expert_angle": "...",
  "expertise_basis": ["owner knowledge, approved evidence, or a named gap"],
  "technical_watchouts": ["terms, claims, or trade-offs requiring care"],
  "scope_boundaries": ["what the article must not claim"],
  "thesis": "...",
  "why_now": "...",
  "origin": "news|audience_concern|learning|community_question",
  "source_urls": ["https://..."],
  "research_seed": "...",
  "language": "en",
  "market": "MX"
}
```

Reject and do not pay for an idea when:

- the audience need is empty;
- the reader question, situation, or intent is empty;
- the business relevance, expert angle, or expertise basis is empty;
- the thesis is empty;
- it duplicates a pending, approved, or recently declined idea;
- a time-sensitive claim has no source URL;
- it exists only because a search phrase appears popular;
- the configured publication locale does not support its language.

Persist the accepted idea before any provider call.

### Ada article idea persistence

Add one small table, for example `article_ideas`:

```text
id
cycle_key                 UNIQUE, one key per seven-day selection window
idea_hash                 UNIQUE
status                    selected | research_requested | researched | drafted | failed
idea_json
research_run_id
research_result_hash
provider_task_id
research_cost_micros
research_note_json
draft_id
created_ts
updated_ts
researched_ts
drafted_ts
error
```

Do not create a general content-campaign schema. This table exists only to make
the paid boundary idempotent, the asynchronous article flow resumable, and the
editorial result reusable in later reports and idea selection.

### Step 2: Request exactly one paid task

Add a dedicated CrawlSEO model for this narrow operation, for example
`ArticleKeywordResearchRun`:

```text
id
projectId
siteId
ideaKey
idempotencyKey            UNIQUE per site
requestHash
seed
language
country
status                    REQUESTED | ATTEMPTING | COMPLETED | FAILED | UNCERTAIN
providerTaskId
costMicros
result
errorCode
requestedAt
attemptedAt
completedAt
createdAt
updatedAt
```

Use a dedicated model instead of forcing weekly ideas into the existing
closed-month `SeoResearchRun` uniqueness and five-seed assumptions. One table is
enough because there is exactly one provider task per run.

Extend `SeoResearchPolicy` with only the controls CrawlSEO must enforce:

```text
articleResearchEnabled    default true
articleTaskLimitPerMonth  default 5
articleMinIntervalDays    default 7
```

Do not make these limits client-supplied MCP arguments.

Add durable `JobKind.ARTICLE_KEYWORD_RESEARCH`. Enqueue it with
`maxAttempts: 1`.

Add MCP tools:

```text
seo_request_article_keyword_research
seo_get_article_keyword_research_status
seo_get_article_keyword_research
```

Request arguments:

```json
{
  "idea_key": "article:2026-W36:<hash>",
  "idea_summary": "Audience concern and thesis, bounded text",
  "seed": "beginner freediving equalization anxiety",
  "language": "en",
  "country": "MX",
  "idempotency_key": "article-research:<idea-hash>:v1"
}
```

Request behavior, in order:

1. Authenticate and resolve the project-owned site.
2. Validate bounded text and resolve the requested language-country pair against
   DataForSEO's current country-level Google locale catalog.
3. Return the existing run for the same idempotency key.
4. Refuse if article research is disabled.
5. Refuse if another paid article task was attempted within seven days.
6. Refuse if five paid article tasks have already been attempted in the current
   calendar month.
7. Persist the reserved run, including the exact provider language and location
   codes, before enqueueing.
8. Enqueue one durable job with one attempt.

Worker behavior:

1. Atomically transition `REQUESTED` to `ATTEMPTING` before provider dispatch.
2. Call only DataForSEO's related-keywords operation for the one seed.
3. Limit normalized results to 50 rows.
4. Store provider task ID and actual cost.
5. Mark successful responses `COMPLETED`.
6. Mark a definite pre-dispatch/provider rejection `FAILED`.
7. Mark an ambiguous timeout after possible dispatch `UNCERTAIN`.
8. Never automatically retry `FAILED` or `UNCERTAIN` runs.

The read result should include only:

- original request fields;
- normalized related keywords/questions;
- provider task ID;
- actual cost;
- status and safe error code;
- timestamps.

It must not include provider credentials or unbounded raw responses.

The completed CrawlSEO row is the durable source of truth for the full
normalized paid result. Do not overwrite or delete that result when an article
is declined or a draft is discarded.

### Step 3: Create a compact research note

Add a daily `article_research_cycle` reconciliation job in site-agent. It polls
only locally pending article ideas.

When research completes, ask Ada to produce a compact note:

```json
{
  "original_thesis": "...",
  "decision": "keep|reframe|editorial_despite_low_demand",
  "reader_question": "...",
  "market_context": "...",
  "question_fit": "...",
  "demand_interpretation": "...",
  "reader_language": ["..."],
  "related_questions": ["..."],
  "useful_terms": ["..."],
  "terminology_notes": [{"reader_term": "...", "preferred_term": "...", "distinction": "...", "basis": "owner|source|uncertain"}],
  "technical_claims_to_verify": ["..."],
  "scope_boundaries": ["..."],
  "misconceptions_to_avoid": ["..."],
  "expert_angle": "...",
  "reframed_title": "...",
  "reframed_thesis": "...",
  "reasoning": "..."
}
```

Prompt rules:

- preserve the original audience concern;
- identify the underlying reader decision, constraint, and desired outcome;
- do not select a different topic because it has more volume;
- treat volume as context, not a verdict;
- treat reader vocabulary, professional terminology, and technical truth as separate things to verify;
- flag false binaries, claims needing owner/source confirmation, and the limits of any diagnosis or procedure;
- allow `editorial_despite_low_demand`;
- do not invent source URLs or metrics;
- keep only evidence relevant to the selected idea.

Store the note, result hash, provider task ID, cost, and research timestamp on
the article idea. Do not create a large SEO strategy report. Future idea
selection and monthly reporting should use this compact note by default and
fetch the full CrawlSEO result only for a focused need.

### Step 4: Draft the article

After the note is stored, call the existing article drafting and self-editing
path with:

- the original idea;
- the compact research note;
- the business's credible expert angle and expertise basis;
- current sourced news used by the idea;
- relevant audience/customer context;
- owner feedback;
- prior article titles;
- relevant GSC/GA4 context;
- no full monthly report dump and no unrelated keyword rows.

Update the writing prompt to say explicitly:

- answer the stated reader question, situation, and thesis from the business's credible point of view;
- use research to ground the answer, not to narrate the research process;
- use research terminology only when natural;
- do not optimize for keyword density;
- do not force the seed into the title or headings;
- retain Ada's point of view;
- do not invent technical procedures, diagnoses, standards, credentials, outcomes, or first-hand experience;
- do not turn search demand into proof of truth, expertise, or reader motives;
- distinguish sourced current facts from evergreen guidance.

Save the normal pending article draft and include lineage in draft metadata:

```json
{
  "article_idea_id": 123,
  "keyword_research_run_id": "...",
  "research_decision": "keep",
  "research_cost_micros": 10000,
  "origin": "audience_concern",
  "source_urls": []
}
```

If the research run is `FAILED` or `UNCERTAIN`, do not automatically submit a
second paid task. Leave the idea inspectable, record a safe owner-visible action,
and do not silently draft an allegedly research-supported article.

### Scheduling

Use two jobs:

```yaml
schedule:
  article: {every: weekly, weekday: tuesday, at: "09:00"}
  article_research_cycle: {every: daily, at: "13:30"}
```

Responsibilities:

- `article` selects and persists at most one new candidate, then requests its
  one paid task.
- `article_research_cycle` polls existing requests, creates notes, and drafts
  completed ideas exactly once.

The weekly job must not wait synchronously for DataForSEO. The daily job makes
the asynchronous workflow resumable after process restarts.

## Changes to Existing SEO Workflow

The current `src/site_agent/brain/seo.py` flow chooses five keyword seeds and
then automatically creates an article. Replace that active behavior rather than
running both systems in parallel.

Required changes:

- stop registering `seo_research_cycle` for OceanicVibes;
- remove the automatic article block from the monthly strategy processing path;
- do not invoke `seo_request_research_report` from article scheduling;
- do not use DataForSEO domain or backlink reports in Ada's prompts;
- keep generic CrawlSEO domain/backlink dashboard features only if they serve
  other CrawlSEO users, but exclude them from Ada's fixed MCP surface and jobs;
- preserve existing completed records if another deployment has them, but no
  backward-compatibility execution path is needed for OceanicVibes because it
  currently has no SEO research runs.

Update documentation and configuration names so "monthly website report" and
"article keyword research" cannot be confused with the retired monthly paid
strategy package.

Suggested configuration:

```yaml
seo:
  enabled: true
  source: crawlseo
  site_url: "https://oceanicvibes.com/"
  site_report:
    enabled: true
    timezone: America/Cancun
    max_crawl_pages: 200
   article_research:
     enabled: true
     language: en
     market: US

schedule:
  seo_site_report_cycle: {every: daily, at: "13:00"}
  article: {every: weekly, weekday: tuesday, at: "09:00"}
  article_research_cycle: {every: daily, at: "13:30"}
```

Financial limits remain server-side in CrawlSEO policy and cannot be increased
through customer YAML.

## Concrete File Map

### CrawlSEO

Expected primary changes:

```text
prisma/schema.prisma
prisma/migrations/<timestamp>_add_article_keyword_research/
lib/reports/monthly-site-evidence.ts               # new, extracted first-party assembly
lib/dataforseo/article-research.ts                  # new, one-task workflow
lib/dataforseo/client.ts                            # factor/reuse related-keywords call
lib/jobs/queue.ts                                   # new job kind mapping as needed
scripts/job-worker.ts                               # execute article research job
mcp/project-tools.ts                                # prepare/read monthly evidence + article research tools
lib/projects/provision-project.ts                   # initialize policy defaults
tests/monthly-site-evidence.test.ts
tests/article-keyword-research.test.ts
tests/project-mcp.test.ts
```

Keep paid-task enforcement in application code and database state, not only in
MCP validation.

### site-agent

Expected primary changes:

```text
src/site_agent/core/memory.py                       # migrations and persistence methods
src/site_agent/core/contracts.py                    # bounded evidence/research contracts
src/site_agent/core/jobs.py                         # register both reconciliation jobs
src/site_agent/defaults.yaml                        # safe defaults
src/site_agent/config.py                            # validate new config sections
src/site_agent/hands/crawlseo.py                    # fixed MCP transport methods
src/site_agent/application/crawlseo.py              # validated application operations
src/site_agent/brain/monthly_seo_report.py           # new monthly interpretation flow
src/site_agent/brain/article.py                     # split idea selection from drafting
src/site_agent/brain/article_research.py             # new compact state machine
src/site_agent/application/home.py                  # expose report state/actions
src/site_agent/web/server.py                        # report read APIs
src/site_agent/web/static/admin.html                # monthly report UI/history
examples/oceanicvibes.config.yaml
docs/deploy.md
README.md
tests/test_monthly_seo_report.py
tests/test_article_research.py
tests/test_crawlseo.py
tests/test_web.py
```

If a smaller file split is clearer during implementation, keep the logic in
`brain/article.py`; do not create abstractions solely to match this suggested
map. The behavioral boundaries and tests matter more than module count.

## Implementation Order

### Phase 1: CrawlSEO monthly evidence

1. Extract first-party period readiness and evidence assembly from the existing
   paid research module.
2. Add the prepare mutation and read-only evidence MCP tools.
3. Verify exact-month GSC and GA4 coverage and 30-day crawl freshness.
4. Test that neither tool invokes DataForSEO.

### Phase 2: Ada monthly report and UI

1. Add site-agent report persistence migration.
2. Add CrawlSEO transport/application contracts.
3. Implement daily report reconciliation.
4. Implement the evidence-grounded report prompt and artifact creation.
5. Merge any persisted article-research notes and actual costs from the report
   month; an empty history is valid before Phase 4 is deployed.
6. Add report history/read APIs.
7. Render the latest monthly report and history in the existing UI.

At the end of this phase, the first end goal is complete independently of paid
article research.

### Phase 3: CrawlSEO one-task article research

1. Add the article research model and policy fields.
2. Add one-attempt durable job execution.
3. Enforce one task, seven days, five per month, and idempotency.
4. Add request/status/result MCP tools.
5. Test ambiguous failure handling and duplicate requests.

### Phase 4: Ada article orchestration

1. Add article idea persistence.
2. Split free idea selection from article drafting.
3. Add weekly candidate selection and request submission.
4. Add daily polling and compact research-note interpretation.
5. Pass the idea and note to the existing draft/self-edit path.
6. Persist full lineage and cost metadata without deleting provider results.
7. Include prior compact research notes in later idea selection.
8. Remove the old keyword-first automatic article path.

### Phase 5: Rollout and measurement

1. Enable the two workflows for OceanicVibes.
2. Produce one historical closed-month website report.
3. Run one selected article idea through the paid boundary.
4. Verify one and only one provider task was attempted.
5. Verify the report and article draft are visible in the owner UI.
6. Run weekly for four to eight articles before changing task limits or adding
   provider calls.

## Testing Requirements

### CrawlSEO unit tests

- closed-month period validation;
- GSC exact-period and previous-period aggregation;
- GA4 exact-period and previous-period selection;
- current crawl reuse and stale crawl enqueue behavior;
- monthly evidence readiness with each missing source;
- monthly evidence paths never call DataForSEO;
- article request accepts exactly one seed;
- duplicate idempotency key returns the same run;
- second idea inside seven days is refused before provider dispatch;
- sixth attempted task in a calendar month is refused;
- disabled policy is refused;
- provider response stores task ID and cost;
- results are capped at 50;
- paid job has one attempt;
- ambiguous timeout becomes `UNCERTAIN` and is not retried;
- tenant token cannot read another project's evidence or article research.

### site-agent unit tests

- previous closed month respects configured timezone;
- daily report reconciliation is idempotent;
- waiting source state creates no report;
- completed evidence creates exactly one report artifact;
- report prompt contains no article request or backlink section;
- monthly report includes bounded article-research notes and actual cost;
- monthly report generation makes no new paid request;
- a month with no article research still produces a valid report;
- article idea is persisted before provider submission;
- duplicate/recent idea is rejected without a paid call;
- missing audience need or thesis is rejected without a paid call;
- time-sensitive unsourced idea is rejected without a paid call;
- one completed research result creates one compact note and one draft;
- low-volume results may produce `editorial_despite_low_demand`;
- keyword results cannot replace the article with an unrelated topic;
- failed/uncertain research causes no retry and no unsupported draft;
- process restart resumes waiting report and article states;
- article draft metadata contains idea and research lineage.
- prior research notes are available to later idea selection without fetching an
  unbounded history;
- declining or discarding an article does not delete its paid research history.

### UI/API tests

- latest monthly report API returns only persisted local data;
- report list is ordered newest first and bounded;
- unknown report returns 404;
- UI shows no-report, waiting, completed, and failed states;
- source freshness is visible;
- report history selection works on desktop and mobile;
- loading a report page triggers no CrawlSEO, LLM, or paid calls;
- weekly report and monthly website SEO report remain clearly distinguished.

### End-to-end acceptance test

For OceanicVibes:

1. Trigger the weekly article job with a sourced audience-led idea.
2. Confirm the idea exists locally before the provider request.
3. Confirm CrawlSEO attempts exactly one related-keywords task.
4. Confirm actual provider cost and task ID are persisted.
5. Confirm Ada creates a compact note and one pending article draft.
6. Confirm a repeated scheduler run creates no second paid task or draft.
7. After that calendar month closes, run daily report reconciliation for it.
8. Confirm CrawlSEO queues/reuses GSC, GA4, and crawl only.
9. Confirm report preparation does not increase the DataForSEO task count.
10. Poll until first-party evidence is ready.
11. Confirm Ada creates one monthly report visible in the UI.
12. Confirm the report includes the completed article research, actual cost, and
    current article state without making another paid call.
13. Confirm repeated reconciliation does not mutate or duplicate the completed
    monthly report.
14. Confirm publishing still requires explicit owner approval.

## Deployment and Migration

OceanicVibes currently has CrawlSEO-backed GSC and GA4 enabled, a completed
crawl, no CrawlSEO SEO research runs, and `seo.research.enabled: false`. Its live
site-agent database was observed at schema version 14 while the current checkout
expects later migrations. Roll out deliberately:

1. Back up `/SOCIAL/configs/oceanicvibes/data/memory.db`.
2. Back up the CrawlSEO PostgreSQL database.
3. Apply and verify CrawlSEO Prisma migrations.
4. Deploy and restart CrawlSEO web, MCP, and worker processes.
5. Deploy site-agent code.
6. Restart both the `serve` and `run` site-agent processes so all SQLite
   migrations and scheduler registrations load.
7. Confirm the site-agent schema reaches the new target version.
8. Confirm the old `seo_research_cycle` is not registered.
9. Enable `seo.site_report` and `seo.article_research` for OceanicVibes.
10. Run one reconciliation manually and inspect source readiness before waiting
    for the normal schedule.

Never print service tokens or provider credentials during rollout diagnostics.

## Observability

Use existing action logs and provider receipts. Every monthly report cycle
should log:

- period;
- local report row ID;
- source readiness states;
- evidence hash;
- artifact ID on completion;
- safe error code on failure.

Every article research cycle should log:

- local article idea ID;
- CrawlSEO research run ID;
- status;
- provider task ID after dispatch;
- actual cost after completion;
- draft ID after drafting;
- safe reason when skipped or refused.

Do not log complete provider responses, credentials, bearer tokens, or article
source material that is not already owner-visible.

## Definition of Done

The work is complete when all of the following are true:

1. Ada's UI shows a monthly website SEO report with GSC, GA4, crawl freshness,
   trends, and no more than three actionable recommendations.
2. Generating or viewing that report incurs no DataForSEO task.
3. The report contains no backlink section and creates no article automatically.
4. Ada chooses an audience-led article idea before any keyword request exists.
5. One selected idea triggers exactly one paid related-keywords task.
6. CrawlSEO enforces seven days between attempts and five attempts per calendar
   month, regardless of client behavior.
7. Provider task ID and actual cost are persisted.
8. Ada stores a compact research note and uses it to support, not dictate, the
   article.
9. Full normalized paid results remain historized in CrawlSEO, while Ada retains
   reusable compact notes and article lineage.
10. The monthly report includes the month's paid research learnings, cost, and
    resulting article states without triggering new research.
11. Later idea selection can use prior dated research notes to avoid repetitive
    ideas and redundant discovery.
12. A completed idea produces at most one pending article draft.
13. Duplicate scheduler runs and process restarts create neither duplicate paid
    tasks nor duplicate drafts.
14. The owner must explicitly approve publication.
15. Focused tests, full site-agent tests, CrawlSEO tests, type checks, and builds
    pass.

## Verification Commands

Run focused tests first, then full verification.

site-agent:

```bash
.venv/bin/pytest -q tests/test_monthly_seo_report.py tests/test_article_research.py tests/test_crawlseo.py tests/test_web.py
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
```

CrawlSEO:

```bash
npm test -- --run
npm run lint
npx tsc --noEmit
npm run build
```

The coding agent must also perform the OceanicVibes end-to-end acceptance test
using the project-scoped MCP token without exposing it in command output.
