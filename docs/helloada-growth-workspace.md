# HelloAda Growth: owner decisions first, evidence one level down

## Product contract

Growth is an additional owner-workspace view, never a replacement for Ada chat
or website preview. Its default is Ada's saved, business-specific analysis and
next actions. The approved HelloAda mark is unchanged. All customers and new
Payload sites consume the same shared package; no customer-specific UI fork.

The shared `0.7.2` surface system follows the actual helloada.app control-room
example: ivory canvas (`#eee6da`), paper tool windows and dark foregrounds,
with dark navigation and Ada conversation. Nested galleries, drawers and editors
explicitly use paper tokens rather than inheriting dark conversation colors.
Charts, statuses, controls and native Payload forms use surface-aware tokens.
Contrast tests cover primary/secondary/caption/action text on both palettes.
No data, chat, publication or approval behavior changes with this theme release.

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

### Two-tone surface release: 2026-10-02 (local time)

- Shared package `0.7.1`, source commit `a886e59`, follows the actual HelloAda
  homepage control-room palette. Dark navigation and Ada chat remain distinct
  from ivory review, Growth, gallery, management and native Payload surfaces.
  The navigation palette is bound to `.helloada-payload-nav` itself, not only
  a native Payload wrapper that standalone owner pages do not render.
- Atelier commit `b7ea530`, Worker `d337e7c3-797c-4141-85e9-508cf7f225dc`;
  Oceanic commit `a76a30d`, Worker `e90c4fd0-acca-4ceb-99dc-0075c9d5c9a2`.
  Both deployments were confirmed at 100% traffic. Both canonical future-build
  checkouts and installed dependencies were fast-forwarded to these versions.
- Clean production builds and typechecks passed; lint has only the existing
  migration/frontend warnings. The shared compiled CSS is identical in both
  artifacts (`fe148e49d5e5376e.css`, SHA-256
  `10e66503c671bd0988254ddc2f1ec9ef147fdb2fa7ee79320a30434a38d8817d`).
  The approved logo hash is unchanged. Fresh authenticated documents served
  this exact stylesheet, with dark chrome and dark text on light tool windows.
- Shared admin package: 17 tests passed, including surface scope, nested tool
  palettes and AA text contrast on both surfaces; TypeScript and Sass passed.
  The final wheel's new-site template pins the immutable `0.7.1` asset.
  The initial full backend run had 1054 passes and two failures: the known
  frozen Pelican-profile failure and an environment-only missing `pelican`
  executable. With `.venv/bin` correctly on PATH, the latter and the focused
  default-template checks passed (3 tests). No backend application code changed.
- Fresh live verification: both correct tenants connected to Ada; Atelier's
  real website preview rendered; Oceanic's measured GA4 report, gallery images
  and paper management drawer loaded. Public homepages returned 200 and
  unauthenticated owner connection endpoints returned 401. No requests were
  sent to Ada, paid tasks triggered, documents edited or changes published.
- At 390px, the final navigation and page both measure 390px with no horizontal
  page overflow. The navigation links scroll within their own row. This resolves
  the small-screen overflow noted in the `0.6.1` record, without hiding tools.
  The temporary viewport override was reset after the check.
