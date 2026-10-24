# Growth clarity and Oceanic clean-slate implementation plan

Status: implementation started; published-content decisions and rendered owner acceptance remain open.
Owner direction: October 23, 2026. The dashboard must simplify website decisions for a nontechnical owner. Oceanic's historical generated material must be audited before it becomes the foundation for further recommendations.

This update supersedes the older requirement to place the five expertise areas prominently on the Growth landing view. It preserves the existing investigation, exact candidate, approval, publication, tenant isolation, budget and official release contracts. No new task store, publisher or scheduler is introduced.

## First broken boundary

Current site evidence -> worthwhile recommendation -> prepared exact change -> understandable owner review -> explicit approval -> verified publication -> measured outcome.

The first failure is between evidence and a worthwhile, current recommendation: historical drafts, old observations and Ada's own failures compete with real decisions. The next failure is presentation: long investigation prose obscures the problem and review exposes too much document structure with insufficient contrast. Passing deployment/tests does not prove owner comprehension.

## 1. Inventory and contain historical noise

Read current canonical Payload posts/pages and registered tenant work records. Produce an item-by-item ledger with IDs, public/draft status, URLs, exact body hashes, links and proposal lineage. Distinguish exact duplicate bodies, overlapping subjects, duplicate local representations of an already published article, and unrelated abandoned drafts. A matching title alone is not evidence for deletion.

Preserve all published pages, owner edits, valid approvals, receipts, conversations and research spending history. Do not reset budgets, automatically retry paid research or regenerate the backlog. Do not claim stale issues are resolved merely because they are hidden. Active or uncertain external effects prevent archival until canonically reconciled.

Archive only explicitly reviewed obsolete unpublished work through a shared protected plan/apply service with expected state/content proof, stable request attribution, durable audit and idempotent replay. Preserve the original content and provenance. Link duplicates to their retained canonical record. Archived work must be excluded from future preparation and active decisions across Growth/chat/activity projections, while remaining inspectable in history. A UI-only filter is not cleanup.

## 2. Review published content

For every published article propose keep, improve, merge or remove, with supporting evidence. Examine subject overlap, distinct reader purpose, current links, site relevance and factual/source quality. The coding agent inventories and diagnoses; Ada remains responsible for generating proposed editorial changes through normal authoring services.

Published deletion, unpublication, replacement or redirects require a concrete reviewed owner decision. Topic overlap alone does not justify merging. An approved merge must retain useful material, choose a surviving URL, update internal links and provide a verified redirect where supported. Unsupported redirect/publication scope stops rather than improvising a second route.

Exit: a concise inventory and a specific published-content decision list, with no public changes made by cleanup.

## 3. Establish business facts and reassess

Retain the existing owner question and collect missing service facts in manageable steps: price/inclusions first, then availability and relevant instructor/booking details. Reuse the original owner action/conversation; do not manufacture answers or create another approval list. Persist confirmed facts through the established business-context contract.

Once cleanup dispositions are applied, request one fresh normal assessment using current site evidence and canonical retained work. Reuse the current scheduler and evidence pipeline. Each new recommendation must identify the current observation, affected location, credible consequence, bounded proposal, evidence timestamp and precise owner action. Separate an observed defect from an uncertain hypothesis. Group related findings for presentation while retaining each exact candidate's independent approval identity.

## 4. Redesign the owner workspace

Overview: short truthful status, the most useful next decision, a bounded set of other decisions and verified recent changes. Recommendations: current evidenced improvements with readable review. Activity: progress, provider failures and historical attempts grouped by canonical work. Keep analytics, search/research, expertise detail and reports reachable through progressive disclosure.

For Oceanic's current examples: a guided business-information request; one related group of two cut-off article-description corrections, each separately reviewable; historical technical findings waiting for current verification. This is a data example, never tenant-specific application logic.

Review shows the page/article identity, exact changed leaf fields, current and proposed text, and the effect of approval. Unchanged article bodies and object JSON are omitted from the initial comparison. Full affected article content remains available when its body changes. Preserve exact approve/revise/decline services and permissions. A historical failure cannot override the readiness of a subsequently recovered candidate.

Visual direction: existing HelloAda typography/brand, white reading surfaces, dark high-contrast body text, restrained coral primary actions, quiet dividers, and one clear action per recommendation. No marketing hero, decorative status wall or motion delaying decisions. Support narrow mobile, keyboard/focus, EN/FR/es-MX and owner timezone. Existing uncommitted review improvements are preserved and reviewed before adoption.

## 5. Results and truthfulness

A generated draft is progress. A verified live change is delivery. Later observed business metrics are outcomes, with uncertainty and no invented causal lift. Retired, declined or failed work never becomes a verified result. Internal repairs remain linked activity rather than owner recommendation chores. Missing evidence cannot become a healthy status.

## 6. Validation and release sequence

1. Capture before-state inventory, pending approvals, draft and public hashes/timestamps.
2. Test cleanup eligibility, tenant/auth isolation, proof drift, pending-approval/uncertain-effect protection, rollback and idempotency; apply only reviewed exact IDs through the shared service.
3. Verify archived work cannot be re-prepared and retained content/approvals/spend are unchanged. Save private durable receipts.
4. Test recommendation projections and changed-fields review against actual Oceanic-shaped data, including recovered proposals, overlapping titles, old failures, empty/unavailable states and translation parity.
5. Run package tests/typecheck/build and appropriate backend tests. Publish immutable admin artifact and pins through the documented release path; queue exact API source if necessary; allow canary/fleet rollout through the standard timer.
6. Test fresh authenticated rendered overview and full review on desktop/mobile: owner can identify problem, proposal and consequence; compare readable changed text; exercise answer/revise/decline and controlled approval separately. No customer publication is inferred from test authorization.
7. Run fresh normal assessment only once the retained backlog and current evidence are consistent. Observe a genuine improvement reach exact review. No extra paid-provider dispatch without existing applicable authorization.

## Acceptance ledger

- [x] Current published/draft inventory with exact duplicate/overlap distinctions.
- [ ] Canonical audited archival path; reviewed unpublished cleanup applied with receipts.
- [ ] Published-content decisions prepared for owner review.
- [ ] Current recommendations are evidence-bound and historical attempts cannot re-enter active work.
- [ ] Readable overview and exact changed-fields review implemented and tested.
- [ ] Canonical scheduling/reassessment verified against the cleaned backlog.
- [ ] Official API/package/Worker releases verified.
- [ ] Authenticated rendered owner comprehension and action acceptance observed.

Completion requires those live product checks; an inventory, a prettier screen or a passing test suite alone is insufficient.

## Initial implementation checkpoint

The live read-only inventory is in `oceanic-content-cleanup-inventory-20261023.md`.
It finds seven public article routes, including two different plateau articles
with the same title and separate URLs. No exact cross-document body duplicates
were found. Public articles are retained pending a specific editorial decision.
Five pending local attempts (#45/#49/#50/#58/#60) are proposed for explicit
withdrawal; their text and destination records remain intact.

The first UI slice implements changed-field comparison, readable light surfaces,
localized review labels and approval consequences, and expandable rationale and
expertise detail. Rich text keeps visible link/format differences plus optional
exact structured detail. Tests against the saved actual Oceanic proposal shapes
show only `seo.description` and `summary` in both reviews, omitting the unchanged
article body. Shared package tests passed 66/66 and typecheck passed. This is
source validation; the new UI has not been released or browser-accepted.

The protected local-draft archive path is implemented; 39 focused backend tests
cover authorization, proof drift, repeated requests, linked-record protection,
projection and preparation interleaving. The full backend suite is running.
It reuses the existing draft ledger, marks only eligible obsolete local intent
as discarded with operator attribution, keeps full original copy and sync
history, and records historical external effect as unknown. It is separate from
owner decline and cannot decide a current approval or mutate Payload. Final
backend tests, exact-source API activation and the reviewed live cleanup remain
required before calling Oceanic a clean testing slate.

Guided owner questions, grouping related independent approvals, fresh
recommendation quality assessment, published article consolidation and full
rendered usability acceptance remain later phases of this plan.

The initial complete backend suite passed 1,672 tests (three existing Pillow
warnings). Final review then tightened malformed-sync rejection and bound all
linked article-idea states/run/reservation identities into the archival proof;
40 focused backend tests passed after those changes. Official PR CI validates
the final immutable source. No live content cleanup has yet been applied.

## Continued release and assessment tranche

The shared admin candidate is version 0.10.29. Overview now groups related exact
field edits without joining their approvals, bounds secondary decisions, and
keeps Recommendations, Activity and Results as distinct views. Actual Oceanic
initiatives 8 and 7 share the description/summary group; initiative 4 remains a
separate owner question. Long scope/evidence remains available in disclosures.
The final package suite passes 68 tests plus typecheck.

New assessments require current source observations and canonical document
binding. Invalid or stale findings and extra owner questions are deferred
individually, preserving valid recommendations in the same assessment. Ada is
instructed to identify a concrete visitor/business problem and a bounded action,
compare retained work and current published inventory, avoid internal repair
chores as owner recommendations and distinguish hypotheses from measured
outcomes. Focused planner/workflow/recovery checks pass 36 tests.

The existing Oceanic question was already opened (action 22 is waiting, with
conversation 43/job 55). Its answer lineage is intentionally retained rather
than replacing an in-progress question or inventing business facts. New questions
follow the one-question rule; the owner can expand the existing full request.
The release queue targets exact source `0c8d87fe6c24d1bcbc7273b7a5bb7ac0e427ba95`
for the clarity assessment API. Admin publication/pins and live deployment remain
separate verified steps.

Full regression review found and corrected two assessment compatibility issues:
invalid citations keep the established diagnostic code, and unavailable required
sources use the existing candidate-blocking path rather than completing an
assessment early. The corrected focused service/planner/workflow/recovery suite
passes 70 tests. Official CI rechecks the exact queued revision.

## Verified live cleanup and rendered QA

The archival API `20261023-api-growth-clean-slate-1` is health-passed at exact
source `2aa9fbbbc93face22d3fe02a56d14e7245c8c16a`. The five audited local drafts
45/49/50/58/60 were explicitly archived through the protected plan/apply route.
All eight canonical documents and both their read revisions, both existing
approvals, and the research reservation ledger are unchanged. Each original
local title/body/sync metadata hash is preserved; only local disposition and
operator audit changed. A repeated exact request returned its saved receipt.
Private immutable plans, five receipts and before/after evidence are retained
under the registered Oceanic maintenance directory. The active task projection
fell from 20 to 15 and contains none of those five archived attempts.

The assessment API `20261023-api-growth-clarity-assessment-1` is health-passed at
`0c8d87fe6c24d1bcbc7273b7a5bb7ac0e427ba95`. Normal POST Growth check queued
`growth-1a4fc3968eb246108dad2f9bc8aa1e00`; the canonical scheduler collected fresh
inventory and produced two bounded findings (sitemap/canonical output and real
home-page link destinations). Both wait behind the two existing prepared
proposals; no duplicate proposal, new owner question or paid cycle was created.
This is an observed capacity wait, not a claim of completed preparation.

Local rendered QA uses actual GrowthTasks/SCSS with the saved Oceanic projection
and blocked network/mutations. At 1440px and 390px: no horizontal overflow,
keyboard review activation works, both exact candidate targets open separately,
and review value/label contrast is 15.51:1/7.60:1. Screenshots and report live
privately under `/tmp/growth-clarity-rendered-qa`. This remains fixture QA, not
signed-in production acceptance.

The visual review caught a real status contradiction: a retired failed revision
was displayed as a current service issue alongside a valid Publish action. The
projection now suppresses that historical error only for a genuinely ready
proposal whose retirement hash matches both initiative and draft. Uncertain or
mismatched holds remain visible. Growth task/service/workspace tests pass 104
checks. A further 0.10.30 admin candidate removes overview slugs and field-name
headings and uses a concise review heading while retaining exact target details.
Its package suite passes 68 tests plus typecheck. API activation and immutable
0.10.30 consumer adoption are the next official release steps.

Automatic article mirroring now also checks current canonical post titles before
writing. Exact NFKC/case/whitespace/apostrophe-normalized matches at another route
are a conflict requiring review, not proof that two bodies are interchangeable.
It leaves both versions untouched. Missing/malformed or capped 100-item
inventories fail closed; the exact linked document and existing same-route
reconciliation retain their guards. Article-sync/service checks pass 52 tests,
including zero-write apostrophe-variant and incomplete-inventory regressions.
The final API source is `7cbfaf5752adf129be22cdf0f1f713e90dc0b997`; official CI and
full backend tests validate that exact source before activation.

Official CI passed the duplicate-prevention/review source. A local full run
passed 1,680 tests but exposed one pre-existing sub-millisecond clock-rounding
flake in the recovery test. That test now injects a fixed clock, retaining its
assertion and production behavior; it passed three consecutive runs, with 57
Growth task/service checks passing afterward. The exact final API source is
`02359ea5599e1a89a46bfa816379bb47f8bf8a85` and CI revalidates it. The concrete
published-article decision is in
`oceanic-plateau-consolidation-review-20261024.md`; no owner choice or publication
has been inferred.
