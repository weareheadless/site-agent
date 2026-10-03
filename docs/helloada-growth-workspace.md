# HelloAda Growth: owner decisions first, evidence one level down

## Product contract

Growth is an additional owner-workspace view, never a replacement for Ada chat
or website preview. Its default is Ada's saved, business-specific analysis and
next actions. The approved HelloAda mark is unchanged. All customers and new
Payload sites consume the same shared package; no customer-specific UI fork.

The shared `0.8.1` product system retains the homepage's dark Ada / light tool-window
relationship but uses neutral silver (`#f1f3f6`) and white rather than brown/ivory.
The exact approved logo coral-orange (`#ff6b5e`) marks active navigation, primary
actions and key indicators. Text on orange is near-black, not low-contrast white.
Analytics navigation has a near-black rail; Activity uses the same white cards,
neutral canvas, readable hierarchy and orange actions. Nested galleries, drawers,
editors and native Payload forms restore light tokens instead of inheriting chat.
AA contrast tests cover primary, secondary, caption and action roles on both palettes.

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
- **Competitors:** completed monthly own/selected-competitor domain and backlink
  benchmarks; search rivals counted once per keyword and market; top-10 organic
  result samples with real winning-page links and observed owner rank. This is
  not a full-domain keyword-gap, continuous rank tracker or backlink explorer.
  Missing research has a clear explanation and an Ada planning action, not fake figures.
- **Content:** article drafts, ideas, weekly and monthly reports, native Payload
  blog editing, and the activity history remain accessible.
- **Connections:** actual provider state and property identifiers.

Browsing this workspace is read-only. Discuss-with-Ada links prefill a request;
they do not send it, approve a change, run a paid task, or publish content.

## Evidence boundary

`Payload authenticated owner -> server-only tenant proxy -> authenticated
/workspace/seo/evidence -> CrawlSEOApplicationService -> project provider`

The evidence endpoint accepts only `research`, `health` and `competition`. It never provisions
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

## Google credential lifecycle

The retained platform client caches expiry-aware google-auth **credential objects**
per normalized scope set, never raw access-token strings indefinitely. Each request
uses `before_request`, which refreshes when necessary before applying the token.
A client lock prevents concurrent refresh races. Refresh failures raise a safe
`GooglePlatformError`; an expired token is never returned as a fallback. Scopes,
tenant bindings and credential access remain unchanged. Tests simulate expiry,
scope isolation, concurrent reads and a failed refresh, without logging secrets.
Restart the API only to load this code, not as the token-refresh mechanism.

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

This records the initial `0.7.1` workspace verification. The final native-editor
correction and current production version are recorded below as `0.7.2`.

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

### Final two-tone release `0.7.2`

- Source commit `af17592` additionally removes hard-coded dark paint from native
  Payload collection lists, field containers, tables and login forms. The final
  native collection screen was verified with `#fbf8f2` background and `#211b17`
  foreground. Navigation stays dark without changing the approved mark.
- Atelier commit `0cf3645`, Worker `f9cb8616-a2ae-4e0c-84ef-5fad1c54c1ae`;
  Oceanic commit `40e9c6f`, Worker `31800c0f-2b1d-4aff-ba37-579195d3775c`.
  Both are at 100% traffic. Canonical customer checkouts and dependencies are
  clean and synchronized to `0.7.2`. Oceanic's live health response confirms
  tenant `oceanicvibes`, Payload admin `0.7.2` and compatible workspace API.
- Shared compiled CSS `11041d0f16b5a75c.css`, SHA-256
  `34360c040afa03c5ad55ef628222c5b6ef5641d1e87ba12b6760207938267f66`, is
  byte-identical in both generated artifacts. The minifier reordered the native
  selector group; artifact checks validate each selector and its declarations,
  not assumed selector order. Logo and dependency integrity match in both.
- All 18 shared-package tests, TypeScript and Sass passed. Both clean production
  builds passed their TypeScript checks. The final wheel template pins `0.7.2`.
  Fresh authenticated documents served the correct final stylesheet and both
  Ada connections remained available. Atelier's real website preview rendered.
- **Separate unresolved backend issue found during final reporting check:**
  Both Oceanic and Atelier GA4 calls began returning Google's invalid-authentication
  error after working earlier in this session. `GooglePlatformClient.access_token` caches
  raw access-token strings indefinitely and never checks their expiry; the
  provisioning service retains that client. This code was not changed by the
  theme release. Do not describe the final live analytics check as fully passed
  or present cached earlier figures as current. A follow-up backend fix must
  retain credentials with expiry-aware refresh and regression tests; restarting
  the API alone would only temporarily clear the stale token cache.
- The final `0.7.2` document was rechecked at 390px: page width and viewport width
  both 390px, dark navigation and the correct stylesheet present. The viewport
  override was then reset; customer tabs remain open in their owner workspace.

### Contrast, competition and credential-refresh release `0.8.1`

Final verified release on 2026-10-02. This supersedes the warm two-tone palette
and resolves the expired-token defect recorded in the `0.7.2` section above.

- Shared code commit `27e4dabddf4996919221feeebc61e940a70d2dd6`; immutable package
  `payload-admin-v0.8.1`. GitHub's package-release workflow completed successfully.
  The default new-site package, manifest, Worker marker and health response pin
  this same release. The approved HelloAda SVG is unchanged (SHA-256
  `929ec100918ec19fd32319d083bb961ca60d7373da41b7622e5568a260eeaa1f`).
- Atelier commit `694ae0be15a2d71be71f3f84c7b5a80208969278`, Worker
  `3b3ec552-d6b8-4db1-ba6f-22e7d4c44160`; Oceanic commit
  `a1fd0f57e6c0c0bbce38ddcb76860708c14884bf`, Worker
  `b82dc4c4-4d5b-46fe-ba37-5f737faa8984`. Both deployments reached 100% traffic.
  Both canonical future-build customer checkouts and installed dependencies are
  synchronized to `0.8.1`; Oceanic's live health endpoint reports compatibility.
- Builds came from clean customer release checkouts. Generated artifacts were
  checked for current UI scripts, the required palette and absence of the old
  brown canvas token. Shared CSS `21291e689a69e155.css` is byte-identical in both:
  SHA-256 `abdf06b4951580d87e4bbbcea5a4fd4af733a79142c01ff569cadaff5ae4f728`.
  Both fresh authenticated production documents served that exact asset.
- Visual verification confirmed near-black navigation/chat, neutral silver
  `#f1f3f6` canvas, white work panels, `#161a23` text and brand `#ff6b5e` actions.
  Growth uses a compact 58px desktop tool rail with internal link scrolling.
  Activity, the gallery and native Payload lists use the same surface system;
  actual Activity decisions and gallery images were inspected without editing.
  Atelier's real website preview and connected Ada conversation remain visible.
- At 390px, the actual Atelier production document and page both measured 390px,
  with horizontally scrollable navigation and stacked Growth content. No page
  overflow was found. The temporary viewport override was reset. This is a
  focused responsive smoke check, not a claim of an exhaustive device audit.
- Competition is tenant-scoped and uses completed CrawlSEO/DataForSEO evidence,
  not invented ranks. Oceanic exposed two researched SERPs and 14 rival domains;
  Atelier exposed one SERP and six rival domains. The default view selects the
  existing search-rival evidence when no domain benchmark exists. Switching
  Oceanic's keyword changed the actual winning-page links and Ada analysis
  context. Market, evidence date and sample limitations are visible. Domain
  comparison can display completed monthly own/selected-competitor benchmarks,
  but neither tenant currently has that selected-competitor benchmark. An Ada
  research CTA only prepares a conversation; it does not launch paid research.
  Full-domain keyword gaps, rank tracking and a backlink explorer remain future
  work, not shipped Ahrefs parity.
- The live API backend was restarted at `764a6c157799514cd8002974a0d59d6b2ddc6762`
  after validating the authorized Google fix. `GooglePlatformClient` now retains
  expiry-aware credentials per normalized scope set and calls `before_request`
  under a lock before returning a token. It no longer caches raw tokens forever
  or serves an expired token after refresh failure. Tests cover expiry, scope
  separation, refresh failure and concurrent requests. The first expiry tests
  were demonstrated failing on the old implementation. The final UI-only commit
  did not require another API restart. Revocation and provider outages remain
  explicit errors, not hidden by a stale-token fallback.
- Real authenticated GA4 and GSC reads succeeded for both tenants after that
  restart. Atelier's live 28-day GA4 report showed 32 visitors, 35 sessions and
  38 views; its GSC report returned measured zero clicks/impressions, not a load
  error. The 90-day selection updated the report window and keyboard ArrowRight
  moved the selected chart point/caption. Oceanic's GSC missing overview remains
  missing rather than becoming fabricated traffic. Saved Ada analyses are
  explicitly labelled as saved analyses, not the current live report.
- Shared UI: 22 tests passed, TypeScript and Sass compilation passed. Backend:
  1,062 tests passed with the one known pre-existing frozen Pelican-profile
  failure; the final focused evidence/refresh checks passed 12 tests. The final
  wheel was built from an exact clean Git archive, verified to contain the
  default `0.8.1` template pin and no `node_modules`. No customer content/schema
  migration, paid provider task, chat submission or owner publish/discard action
  was performed during verification. The unrelated dirty `/SEO` tree was not
  modified or deployed.
