# HelloAda Growth: owner decisions first, evidence one level down

## Product contract

Growth is an additional owner-workspace view, never a replacement for Ada chat
or website preview. Its default is Ada's saved, business-specific analysis and
next actions. The approved HelloAda mark is unchanged. All customers and new
Payload sites consume the same shared package; no customer-specific UI fork.

- **Ada's brief:** recommendations, automation schedules, review queue, then a
  compact current performance snapshot. A saved brief is labelled as such: its
  period is not silently rewritten when a live reporting range changes.
- **Traffic & search:** GA4 or GSC, not both long reports stacked together.
  Select metric and dimension, explore dated charts, search/sort/paginate tables,
  export raw values to CSV. Zero remains zero; unavailable stays unavailable.
- **Keywords:** project-scoped cached monthly and article research; market and
  language preserved. Distinguish demand, organic difficulty, advertising
  competition, intent and CPC. Domain and backlink summaries are estimates,
  never confused with measured GA4 visits.
- **Site health:** latest completed crawl and severity-filtered issues. A
  missing audit does not produce a perfect score.
- **Content:** article drafts, ideas, weekly and monthly reports, native Payload
  blog editing, and the activity history remain accessible.
- **Connections:** actual provider state and property identifiers.

Browsing this workspace is read-only. Discuss-with-Ada links prefill a request;
they do not send it, approve a change, run a paid task, or publish content.

## Evidence boundary

`Payload authenticated owner -> server-only tenant proxy -> authenticated
/workspace/seo/evidence -> CrawlSEOApplicationService -> project provider`

The evidence endpoint accepts only `research` and `health`. It never provisions
or initiates work. Each unavailable source is represented in `errors`, not an
empty success. Research deduplication uses keyword + language + country, keeping
the most recent observation. Only completed metric runs (`keyword_overview`,
`related_keywords`) become keyword rows; `organic_serp` is not a metric array.
Monthly report history and domain/backlink summaries come from the completed
project report. Secret fields are not included in these projections.

GA4/GSC dimension reports return up to 250 rows; daily history uses a date-bound
limit and chronological ordering. The UI explicitly states that these selected
reports are **not** exhaustive Google exports. Search Console can suppress
low-volume queries; historical availability depends on the property.

Atelier's compatibility proxy must preserve the requested 7–540-day range and
map its route to the canonical workspace API. All new sites use the canonical
proxy by default. Customer credentials never reach the browser.

## Replacing the need for Ahrefs: next capability work, not cosmetic parity

The goal is helping an owner win relevant customers, not reproducing every
professional SEO console. This release exposes evidence we already store. The
following are separate collection/application contracts, **not shipped claims**:

1. **Opportunity workbench:** owner-approved competitor set, country-specific
   domain intersections and keyword gaps, SERP competitors, intent and local
   relevance. Every recommendation identifies its evidence date, market and
   uncertainty; do not rank unrelated high-volume keywords as business value.
2. **Position monitoring:** approved watchlist, scheduled country/device-aware
   SERP observations, durable daily history and new/lost/moved rankings.
   GSC average position and third-party SERP positions remain distinct measures.
3. **Backlink drill-down:** referring pages/domains, new/lost links, target pages
   and anchor text. Current summaries are not a link explorer. Provider coverage
   and estimates must be visible, not labelled equivalent to Ahrefs' index.
4. **Content feedback loop:** link each opportunity to a Payload page/post and
   its publication date. Review drafts with Ada; measure subsequent GSC queries,
   GA4 engagement and configured business conversions. An event count is not
   automatically a sale or lead. Track updates/decay/cannibalisation over time.
5. **Reporting depth:** durable historical snapshots, explicit report pagination,
   reusable filters and dimensions, conversion attribution, geography/device
   comparisons and freshness/coverage details. Avoid implying every native
   Google console feature has been replicated.

DataForSEO Labs supports several of the planned evidence types, but availability
is not integration. See the official [Labs API overview](https://docs.dataforseo.com/v3/dataforseo_labs-google-overview/).
Every paid capability needs tenant isolation, idempotency, retention, cost
budgets, caching and owner approval before we add it to the interface.

## Release verification

Run focused evidence/authentication/normalization tests, shared package tests,
typecheck, full backend suite and wheel smoke. Package the exact verified source,
pin both customer repositories and the new-site template to the same immutable
release asset. Rebuild each customer's independent frontend without schema or
content mutations. Inspect compiled scripts/styles, deploy those artifacts and
verify an authenticated fresh production session for the correct tenant.
Exercise analytics source/range/dimension, search, research, health, content,
connections, responsive layout and the preserved chat/preview surface.

### Verified release: 2026-10-02

- Shared package `0.6.1`, code commit `9dc34e1`; GitHub release workflow succeeded.
  The new-site template uses the same immutable asset.
- Atelier commit `c6002a2`, Worker `f7e5d3e4-7536-4bd1-9dce-2edd25f216b7`.
  Oceanic commit `1cd71d5`, Worker `3dbf2b01-09be-42eb-919e-63cd7d980d4e`.
  Both versions were confirmed at 100% traffic after deployment.
- Clean builds, typechecks and compiled-asset inspections passed. Both customers
  have identical package integrity, approved logo hash and shared CSS asset
  `a2f1b345f4b61fe5.css`. Canonical customer source/dependencies were synchronized.
- Authenticated, cache-busted live documents verified correct tenant, Ada
  connection, real GA4/GSC data, 28/90-day ranges, search/pagination, keyboard
  chart interaction, keyword detail, crawl issues, content and connections.
  Chat and the actual website preview remain accessible. No chat was sent and
  no paid research, content change or publication was triggered by testing.
- Shared package: 12 tests passed. Focused backend tests: 20 passed; final
  evidence/template check: 5 passed. Full backend suite: 1055 passed, one
  pre-existing frozen Pelican-profile test failed; the same failure was reproduced
  on the untouched baseline. Wheel contents were smoke-checked.
- A 390px responsive check confirmed stacked Growth cards. The existing owner
  toolbar still causes approximately 14px horizontal overflow at that width;
  this is a known small-screen limitation, not a fully passed mobile audit.

One thorough shared UI test is sufficient for its layout and interactions.
Each tenant still needs a deployment/authentication/data-routing smoke check:
independent Worker bindings, proxy routes and credentials are not shared UI code.
