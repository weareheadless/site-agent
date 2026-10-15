# Growth: from technical task list to owner decision workspace

Status: active implementation contract. PR #194 contains the shared product changes; production acceptance remains pending the canonical API/Worker release and authenticated tenant verification.
Revised: 2026-10-15, following a read-only audit of Oceanic's real records and the deployed API/UI.
Repository: `weareheadless/site-agent`.
Audited release control snapshot: `24fdb5344f196167ec0a582dc60ca3ff1110faea`.
Active API source: `700bcbdd8d6072c7ce4a657d9d8eccf2b8bbd4ac`, release `20261011-api-mailflare-reconcile-2`.
Observed Oceanic Worker release: `runtime-20261015024656-e846530b`, Payload admin `0.10.13`.

This revision replaces the earlier screen hierarchy, state classification and rollout assumptions. Implement the complete journey below before calling the Growth overhaul complete. This document changes the plan only; it does not repair, publish, delete or approve tenant content.

## 1. Outcome

Growth must answer three questions without requiring SEO knowledge:

1. What did Ada discover and prepare for my business?
2. What, exactly, needs my decision?
3. What will Ada do next, and when?

The default screen is one decision inbox, not an analytics dashboard or a queue of technical jobs. Ada owns investigation, preparation, technical validation and execution. The owner supplies missing business facts and approves specific public changes.

This is a shared Site-Agent product change. OceanicVibes is a validation tenant, not a special implementation. New tenants inherit the same behavior automatically.

## 2. Observed failures and their consequences

The October 15 audit established the following facts. These are actual records and source observations, not a hypothetical explanation of the screenshot.

| Boundary | Observed evidence | Required correction |
| --- | --- | --- |
| Coordinated release | Customer Workers run admin 0.10.13, but the API slot still points to the October 11 release. `desired-api-release.json` still requests that old API SHA. | Treat the shared API, Worker gateway and admin package as a compatible release set; prove every deployed boundary. Worker fan-out alone is insufficient. |
| Article authoring | `_mirror_article_draft_to_workspace` in both active API and audited main requires `posts.content` and constructs an array of HTML content. The shared Posts schema exposes rich-text `body`, structured `sections`, `summary` and SEO fields instead. | Repair the shared article writer and validators to use the current authoring contract. Deploying current main without this repair will still fail. Do not add a legacy `content` field or weaken schema checks. |
| Existing drafts | Pending articles 45, 49, 50, 58 and 60 each have `payload_sync.state=blocked`, reason `Payload posts contract is missing required fields: content`, no review package hash and no linked strategy initiative. | Reconcile these exact existing drafts through the repaired shared preparation service. Preserve their content and identities. Never fabricate readiness or new articles to hide the backlog. |
| Canonical records | Oceanic has 15 pending drafts of all kinds, 20 open owner actions, no strategy initiatives and no approval-request records at audit time. Its Growth run table has 13 complete runs and one pending run, with no running Growth run. | Trace each workflow's actual publication authority. An article workflow may use its existing exact draft/hash approval boundary; do not require synthetic strategy initiatives or approval rows if that canonical workflow does not use them. Check that strategy planning itself actually runs. |
| Misleading count | The screen shows 32 items in progress. The active projection groups generic open actions, unlinked drafts and blocked schedules into `preparing`. | Count business work items after deduplication. Claim active execution only with a live canonical job/run and valid lease. A blocked draft is not ongoing work. |
| False recent work | `GrowthTasks.tsx` explicitly includes `blocked` and `failed` states in its recent-work selection, then renders `task.summary` directly. The old API fills article summary with up to 2,000 body characters. | Recent work must show successful results in compact rows. Remove bodies and failures from that rail; make every result open a proper detail view. |
| Missing review actions | The old API makes all unlinked pending articles `preparing` with `canApprove=false`. The new UI's article-review fetch requires readiness, draft ID and review hash. | Fix preparation first, then prove a real article reaches a complete review and exact approve/revise/decline actions. Keep blocked draft inspection available without permitting publication. |

The five article failures have a verified root cause. The precise explanation for every one of the 32 projected items and the absence of strategy initiatives still requires the record-by-record audit in Phase 0. Do not describe all 32 as running jobs or assume every open action is stale.

The earlier deployment check verified that the page rendered, not that the service produced an actionable article or that approval worked. Rendering, passing health checks and displaying the expected labels are insufficient acceptance evidence.

### Existing implementation to reuse

The source audit found the following concrete issues:

- `HelloAdaGrowth.tsx` places a generic task list above metrics. Its Content view exposes article title/status/summary, not a complete editorial review.
- `GrowthTasks.tsx` combines findings, schedules, owner questions, settings, candidate drafts and execution states. Publication buttons are hidden inside expanded rows. Generic before/after fields are flattened into text rather than rendered as the proposed result.
- `growth_tasks.py` is already a read-only join of existing records, not another task store. Preserve this architecture. It applies strong readiness checks to initiative-linked candidates, but unlinked pending articles/design/content drafts are marked preparing and cannot be approved. Determine why such drafts lack the canonical linkage; do not make them publishable by weakening the checks.
- Failed initiatives and technical article failures can be projected into completed work. A failure is not an accomplishment. Separate completion evidence from stopped work.
- Initiative review data includes raw before/after/changes, but its owner-facing evidence list is incomplete. The owner cannot easily understand why a change matters.
- `growth.py` exposes article metadata rather than a full review document. Its chat projection is bounded and abbreviated; inspect targeted task retrieval before assuming Ada can explain every displayed candidate.
- `growth_candidates.py` already prepares exact Payload candidates, checks concurrent drafts, creates linked owner actions/artifacts/approvals and records package hashes. Reuse it; do not introduce a second publisher.

The existing `docs/ada-growth-seo-aeo-pipeline-implementation-plan.md` describes a much richer service than the current generic UI reveals. This plan replaces its competing Growth overview layout guidance with one inbox and typed review surfaces. Its evidence, permission, scheduling and exact-approval rules remain applicable. Historical implementation-status documents are not proof of current runtime behavior.

The earlier plan was written before the live record audit. The evidence above supersedes that limitation. Provider access, every backlog item, real scheduling and an entire approval/publication journey remain unverified and must be proved in the implementation.

## 3. Tight scope and non-goals

Deliver:

- One understandable owner inbox, actual review previews, revision/decline, dated planning and factual recent-work history.
- Root fixes where existing pipeline work fails to reach the inbox correctly.
- Canonical identities and consistent state across Growth, Ada chat and Activity.
- Existing research/analytics/competition details retained as secondary evidence views.

Do not deliver a new task engine, new dashboard application, new Payload schema designer, alternate publisher, tenant-specific workaround, synthetic activity feed or parallel legacy workflow. Do not redesign customer frontends. Do not rebuild GA4/GSC or promise a complete Ahrefs replacement as part of this work. Preserve the approved HelloAda logo and brand.

## 4. Screen hierarchy

This is a complete redesign of the Growth workflow surface, rather than another layer of cards added to `GrowthTasks.tsx`. Preserve the global admin sidebar, Ada access and the detailed evidence tabs. Replace the current overview composition and inline accordion reviews.

### 4.1 Overview: one list, one purpose

The main area contains a compact goal/header, one decision list, and a narrow supporting rail. Use the established HelloAda dark navigation, light canvas, white surfaces, readable dark text and orange primary actions. Preserve the logo and current typography; establish reusable spacing, contrast and selection tokens across Growth and Activity.

Conceptual layout:

```text
Existing admin navigation | Growth goal                         Ask Ada to review
                          | Decisions (N)  Ada's work  Planned  History
                          | -------------------------------------------------
                          | Compact, actionable rows          Next review
                          |                                  Actual date/time
                          | Title + one-line purpose
                          | Why now: short reason             Recently done
                          | [Review article]                  Compact results
                          |                                  [Open history]
```

Evidence navigation (Traffic & search, Keywords, Competitors, Site health, Content, Connections) remains secondary and available. Keep its current functions, but normalize spacing, table density, selected states and empty/error states. Those views link findings into the same decision/review surface; they must not create separate approval lists.

The default is **Decisions (N)**. Its count equals the unique decisions the owner can act on now. Every row has one immediately visible primary action: Review article, Review changes, Answer Ada, Connect account or Review additional research cost. Its supporting reason is normally one or two lines. Optional article thumbnails support recognition, never create a large image wall.

No full article body, markdown, JSON, provider error, implementation metadata or raw draft excerpt belongs in any overview row. The list response must contain purpose-written concise display fields; CSS truncation alone does not repair a body-as-summary API contract. Use normal wrapping and bounded excerpts on desktop and mobile; show the full title in detail and accessible labeling.

### 4.2 Review: take over the main content area

Selecting a row replaces the list with a dedicated detail/review view inside the same admin shell. It must have a stable address/selected-item identity, Back to decisions, a visible draft status and a clear primary action. The full-width main area provides a comfortable reading column of approximately 65–80 characters; images scale sensibly within it. Do not render the article inside a task accordion, skinny rail, popup or stack of neighbouring drafts.

Use a compact review toolbar for Publish/Apply, Ask for changes and Decline. Keep these actions available while reading without covering the content. Show the article first, then related search preview, listing preview and source/rationale details through readable sections or disclosure. The owner must know exactly what will become public.

Back restores filter, selected row and list position. Reload/deep link restores the selected item with current authorization and freshness checks. Unsent revision text survives a recoverable session expiry. After a confirmed action, move the item to its truthful next state and return to an updated list; do not leave duplicate stale cards behind.

### 4.3 Supporting rail and history

Next review contains one verified schedule, date, local timezone and expected purpose. Additional scheduled work is in Planned. Recently done contains at most three to five successful results, each title, date and one short outcome. Clicking opens its result/detail view. No article body, failed work, declined proposal or inert row is permitted here.

History contains publication and verified analysis results with filters. Declines and superseded proposals are available as decision history, not described as Ada accomplishments. Technical attempts and errors live in an inspectable execution log reached from the relevant work item or Activity. A single user decision appears once and is referenced consistently from Growth, chat and Activity.

On mobile the rail becomes a compact following section or disclosure. The review remains the primary full-width content view. No nested horizontal page scroll or squeezed third column is acceptable.

### 4.4 Empty, working and stopped states

An empty decision inbox can be correct. It must distinguish healthy preparation from a stopped service. Show a concise service status with actual next step: a verified next review, specific active preparation, or “Article preparation needs repair; your existing drafts are saved.” Provide View Ada's work or View draft where useful. Do not ask the owner to fix schema/provider errors, and do not promise automatic repair unless a real queued repair/retry exists.

The **Ada's work** view separates actively running, queued and stopped work using clear text and real execution evidence. Keep those statuses within this one work view instead of creating more permanent top-level counters. A stopped item can expose the saved draft and a supported retry/discussion action, while publication stays disabled until validation succeeds. A retry action must actually queue the canonical repair job, deduplicate requests and report its outcome.

Metrics move to the detailed evidence views or a small optional summary; they must not push the owner decisions below the fold. No giant decorative heading, animated activity theatre, overlapping approvals panel or permanent live-task widget.

## 5. Review surfaces and exact actions

Open a review within the current main workspace, retaining navigation and Ada access. Use a compact decision header and spacious content, not a modal. Every review answers: what changes, why, what the owner should check, and what happens after approval.

### A. Article ready

Show the complete real candidate: title, listing card and main image, image alternative text, readable article body, links, proposed URL and search title/description. Clearly label unpublished content. Provide the actual website preview and relevant mobile view through the existing preview mechanism.

Explain why Ada selected this subject using frozen evidence: relevant query/topic, observed customer need, competitor gap or owner expertise, with dates and source. No invented search volume, rankings or uplift. Distinguish a research hypothesis from measured demand.

Actions: **Publish article**, **Ask for changes**, **Decline**. Revision opens a short instruction field, with Ada conversation linked to the same initiative; retain the draft and owner request. The new version must pass validation and receive a new approval hash. Decline asks for an optional reason, does not publish or delete unrelated owner work, and informs future planning.

### B. Technical finding, such as duplicate search titles

Before preparation: show affected pages and the finding evidence. Action **Ask Ada to fix** requests preparation, not publication. Included eligible repairs may already be prepared autonomously under policy, avoiding an unnecessary extra click.

After preparation: show each page's current and proposed title/description, relevant URL and shared impact. Actions **Apply these changes**, **Ask for changes**, **Decline**. Approval covers only the displayed exact package. Explain publication effects in plain language.

### C. Internal linking

Show source article/page, proposed anchor text, destination, and sentence/paragraph in context. Explain the useful visitor connection, not just an SEO score. Validate destination existence and link semantics. Related links can form one bounded package with an explicit list; unrelated changes cannot be silently bundled.

### D. Business profile, reviews and external access

“No Google Business Profile found” is not proof none exists. Show what was checked and whether the finding is confirmed, unknown or missing access. Ask one appropriate question or offer a verified connection/setup step. Do not claim unsupported automatic account creation, verification or management.

Review-related recommendations must use genuine evidence and an appropriate owner-controlled action. Do not generate fake testimonials, ratings or automated unsolicited review campaigns. External-account changes and permissions need explicit scoped consent separate from website publication.

### E. Missing facts and extra spending

Use the same inbox for a concise question, required account access or bounded additional budget. Buttons describe that action; never call all three “Publish.” Included routine research requires no per-tool owner approval. Paid execution requires existing entitlement or an explicit cap/scope decision; opening a card never buys research.

### F. Reports and settings

Weekly reports are read-only results, not pending website publications. Put their concise conclusions in completed work/results, with full report details. Voice/business settings use the existing settings flow and exact before/after confirmation when required. They must not appear as publishable articles or GitHub frontend rollbacks.

## 6. One lifecycle and one source of truth

Reuse strategy initiatives, runs, drafts, owner actions, approvals, artifacts, outcomes and scheduler records. Extend the current read projection with a narrow typed presentation contract; do not persist a second UI task model.

Distinguish these dimensions rather than overloading one status:

- Work: identified, collecting, preparing, validating, ready, executing, verifying, completed, blocked, declined, superseded.
- Owner requirement: none, information, access, budget, review exact candidate.
- Schedule: registered next execution, waiting dependency or disabled.
- Result: published/verified, analysis completed, insufficient evidence, failed or uncertain.

Map these onto existing canonical states where possible; do not rename every backend state just to match the UI. A technical error is blocked/failed, not successful completed work or an owner approval.

Each projected decision needs canonical initiative/action/draft/approval identifiers as applicable; display kind; localized summary; evidence references; affected routes/documents; typed review reference; permitted actions; preparation/validation status; exact review hash; timestamps; and next step. Expose only fields needed by the owner. Server-only details retain correlation IDs and redacted diagnostics.

### Classification invariants

- A draft, owner action, initiative and run concerning the same proposed change project to one work item. Preserve their references rather than choosing arbitrary newest records or grouping unrelated items by title.
- Ready means the current canonical candidate exists, is privately reviewable, has passed the actual current schema/renderer validations, and carries the exact approval authority used by that workflow. Labels and draft presence alone never establish readiness.
- Active execution requires a real running job/run with a valid lease or equivalent canonical execution proof. Twenty open actions must not become twenty active jobs. Queued work has a durable job identity; waiting has a named dependency; stopped work has a recorded failure and a truthful recovery state.
- Completed requires a verified effect/result appropriate to the task. An analysis may complete without publishing anything. A failed provider call, expired approval, decline or superseded candidate is not a successful accomplishment.
- Planned requires a persisted runnable schedule, enabled policy and a genuine future execution date. An overdue unscheduled item is not labelled planned, running or completed by inference.
- Counts and row actions come from one backend projection consumed by all surfaces. Do not derive independent meanings of completed/recent/active from ad hoc arrays in React.
- Separate concise list fields from full review content. The article body is available only through the authorized review/detail request; the list and recent-work payloads must not contain it.
- Show exact inspectable content even when a saved draft is stopped. Inspection cannot enable publication or bypass invalid/missing approval hashes.

The review endpoint/projection retrieves the actual immutable candidate and its evidence on demand. Do not ship every full article in the list response, or flatten rich text into a raw JSON wall. Rich text must be safely rendered using existing canonical rendering contracts.

Growth/chat/Activity resolve the same identifiers and invoke the same effect service. A revision request, decline, approval or publication immediately updates all surfaces after reconciliation. Do not duplicate a pending item once per underlying record.

## 7. Scheduling and actual autonomous work

Audit the registered growth initial/daily/weekly/monthly/outcome jobs and persisted next-run records. Prove a newly provisioned tenant receives policy and active scheduling without manual setup. A timestamp alone does not prove a runnable job exists.

Trace Oceanic's recent runs to evidence, assessment, initiative, candidate, validation, owner action and approval. Record the first missing transition and fix that root cause in shared code. Repeat for Atelier and Northstar with their actual availability/locale; do not seed fake proposals or manually write tenant articles to make the screen look populated.

### Repair the article schema boundary before changing status labels

`src/site_agent/core/jobs.py` must prepare new and revised articles through the current shared Payload authoring contract. Reuse its established content serializer, rich-text handling, stable section IDs, media relations and SEO structure. Determine the authoritative body/sections relationship from the shared renderer and validator; document it once and use it for articles from scheduled research, chat and intake-generated content. Do not invent a second article schema, embed arbitrary HTML in a legacy field or maintain an old/new field fallback.

Validate title, unique stable slug/source identity, summary, actual body/sections, SEO, locale, featured-image reference/alt text and listing/detail rendering against that same contract. Reuse the single canonical `/post/{slug}` routing policy. Confirm the target tenant renderer supports a newly created post and the journal listing, not just already existing articles.

Freeze the exact validated candidate before review. Check the saved Payload draft/version, article source hash, base revision and media dependencies; produce review data from that same candidate. Ask-for-changes creates a new candidate/hash. Publication uses the existing exact approval/effect service. Audit whether the direct article path uses its own hash-bound decision ledger or the shared approval-request table, and keep a single canonical authority; zero strategy-initiative rows alone is not a reason to invent a parallel engine.

### Reconcile existing records through shared code

Build or extend the canonical reconciliation job with read-only planning and explicit apply modes. The plan must list tenant, draft IDs, current state, expected schema/contract and intended transitions. Reuse the saved five Oceanic article bodies, metadata and media references. Apply invokes the same preparation/validation path used for a newly generated article, not SQL that sets `ready_for_review` or forges a hash.

Use stable source identity and idempotency so repeated reconciliation cannot create duplicate Payload posts, owner decisions, jobs or approvals. Protect owner edits: compare the last synchronized revision/hash; if it differs, preserve both and require the existing conflict-resolution flow. Never overwrite a newer CMS draft or resurrect a declined/published article.

Reconcile associated open actions, superseded records and research ideas with canonical transition rules. Keep legitimate missing-information questions; do not bulk dismiss all 20 open actions. Produce before/after counts and references without logging full article bodies or secrets. Add the same automatic reconciliation boundary to normal future preparation so this is a platform repair rather than a one-off Oceanic script.

Audit why no strategy initiatives were recorded: distinguish an intentionally separate editorial workflow from a strategy stage that never ran. Prove one genuine strategy finding reaches a prepared technical/linking candidate separately from the article workflow. A daily `evidence_reconciled` result alone does not prove prioritization, preparation, review or execution.

Ada should autonomously prepare a small prioritized backlog of eligible improvements under existing policy, rather than require the owner to operate research tools. Preserve existing limits and budget protections. An owner-triggered review returns a durable run reference, deduplicates concurrent requests and states the next step without a fake countdown.

Missing one provider blocks only work depending on it. Independent work can proceed with its own valid evidence, explicitly; no silent substitution of weak research for required research. Failed provider calls require typed validation and bounded retry/reconciliation, not raw provider error strings in the decision inbox.

## 8. Approval, safety and history

Preserve exact-package approval: tenant, candidate versions, affected effects, base revisions, evidence/goal/origin/policy dependencies, validation and cost permission. Recheck on effect execution. Concurrent owner edits or revised content invalidate the old approval. Never rebuild different output after approval.

Owner actions are idempotent. Double clicks/reconnects cannot duplicate research, publishing or decisions. Unknown external outcomes remain uncertain until reconciled. An expired session preserves unsent revision instructions and selected review; reconnect is explicit.

Published means the intended effect was verified, not merely queued or HTTP 200. Completed items leave the default inbox and appear in recent work/history with actual results and release links where applicable.

Frontend code changes retain existing GitHub commit/release traceability and the dedicated frontend rollback surface. Do not build generalized admin/settings/Payload snapshot rollback here. Clearly explain that frontend rollback does not automatically revert CMS content. Keep content references and decision receipts for traceability without promising atomic multi-system rollback.

## 9. Visual and interaction requirements

Use existing typography and the approved HelloAda logo. Dark nav/chat, neutral silver canvas, white content, near-black readable text, coral-orange primary/selected actions. Avoid muddy brown surfaces and low-contrast inactive controls. Status always includes text, not color alone.

One clear primary action per item; secondary revision/decline actions visible in review. Comfortable article reading width, useful image scale, compact chrome and consistent spacing. Loading, error, empty, blocked, stale and permission states are designed states, not raw exceptions or endless spinners.

Keyboard-operable filters/reviews; focus restored on close; accessible labels and contrast; responsive layouts; reduced-motion support. Localize EN, FR and es-MX, including dates and owner-facing errors. No giant decorative heading or staged animation.

The visual-design skill informs contrast, hierarchy and restrained polish only. It must not override this functional dashboard's density or established HelloAda identity.

## 10. Implementation sequence

### Phase 0 — Evidence and contract map

Read repository AGENTS.md and deploy/README.md. Verify official SHA, clean source and current deployed revisions. Preserve the October 15 audit above and recheck changes since it. Inspect authenticated Growth and produce a read-only per-item ledger explaining the 32 displayed items: canonical references, true state, execution proof, dependencies, review readiness, recovery and intended view. Document duplicates and orphaned relationships. Record baseline screenshots without claiming the current screen passes.

Trace each of the five failed articles from research idea to saved body, Payload contract, sync failure and missing review boundary. Inspect all pending draft kinds and open owner actions. Verify active API slot/receipt separately from each Worker package and gateway identity. Identify compatibility requirements before queuing another release.

Exit: evidence-backed failure map and expected record transitions, plus a concrete layout and interaction specification for overview, article review, stopped work, history and mobile. No production data writes during this audit.

### Phase 1 — Repair lifecycle and projection

Repair the schema mismatch in `src/site_agent/core/jobs.py` and its dependent serializer/validator first, then work in `src/site_agent/application/growth.py`, `growth_tasks.py`, `growth_workflow.py`, `growth_candidates.py`, relevant owner-action/approval contracts and workspace endpoints. Correct failure/completion semantics and orphan linkage at its creator, with focused tests. Add the narrow typed list/review projection and explicit recovery boundaries needed. Keep GET routes side-effect-free and tenant-isolated. Publish a read-only backlog reconciliation plan before applying it through the shared service.

### Phase 2 — One complete article decision

Use a controlled test tenant and the actual Ada pipeline to prepare a new canonical article. Implement the full-main-area review, image/card/metadata, rationale/evidence, revision and decline. Prove no public mutation before approval; prove revised packages invalidate old approvals. Confirm the public listing and detail route render that exact article after approved publication. A body in memory, an edited existing page or mocked `canApprove=true` is not proof. Separately reconcile a real saved Oceanic draft and demonstrate review readiness without publishing it merely to fill the screen.

### Phase 3 — Technical/linking and owner dependencies

Implement typed review for metadata and internal links using existing candidate machinery. Add information/access/budget presentation using existing owner actions. Prove unsupported profile capabilities cannot be represented as completed provisioning. Keep reports/settings out of publication.

### Phase 4 — Unified interface

Rebuild the Growth overview and selected-item presentation in `packages/helloada-payload-admin/src/components/HelloAdaGrowth.tsx`, `GrowthTasks.tsx`, associated Growth widgets/data/copy/styles and preview/Activity integrations. Implement the screen hierarchy in section 4, not an accordion enlargement or CSS clamp over body dumps. Extract only reusable list-row, review-shell and status/action contracts that genuinely simplify the implementation. Centralize action/state semantics on the server.

Unify Activity and chat links with the same selected-item review route. Retain all evidence capabilities while making decisions immediately recognizable. Make recent results genuinely clickable and concise. Remove duplicate recommendation panels, dead Review links, raw body summaries and superseded inline publishing controls once their replacement works.

Review desktop and narrow layouts with realistic long titles, multiple saved drafts, provider failures, no approvals and a populated approval queue. Do not validate only a sparse happy-path fixture.

### Phase 5 — Shared rollout and proof

Run relevant backend and UI tests, contract/type checks, generated artifact inspection and visual checks. Explicitly release both parts: queue the exact shared API SHA through `deploy/desired-api-release.json`, and publish/pin the immutable admin package for the Worker rollout through the canonical shared-runtime queue. The VPS timer executes both. The currently observed omission of the API release must be impossible to overlook in this change's release checklist and compatibility validation.

Define and test the dependency order. For an API-compatible UI change, deploy and verify the supporting API before the dependent admin package. If protocol or gateway changes break the previous deployed consumer, stage a compatible evolution or explicit coordinated rollout. Do not assume multiple independent Workers and the API switch atomically, and do not introduce a permanent legacy endpoint to hide the mismatch.

Record a small compatibility identity for the Growth projection/review contract using the existing health/release manifest mechanisms where possible. The application must detect an incompatible API response and show an honest temporarily unavailable view, rather than a successful-looking empty decision inbox. The release gate must prove the expected review route and semantics on the deployed API; a health `ok` alone is insufficient.

Do not use local Wrangler, direct tenant deployment or edited old release directories. Inspect receipts and failures; use a new release ID after root fixes. Distinguish API activation, Worker deployment, record reconciliation, functional review validation and browser acceptance in the release evidence.

Use canary then standard fanout. Before broad rollout acceptance, verify the canary with a real reviewable article and exercise approve/revise/decline on controlled test records. After rollout, verify fresh authenticated Oceanic, Atelier and Northstar documents with their actual states; capture an API compatibility check and truthful backlog counts. A shared artifact does not prove tenant bindings or data are correct. Publication and paid research must remain within the existing explicit tenant/test authorization.

Rendering the header and filters is a smoke check only. It must not be recorded as successful end-to-end Growth verification. Preserve a separate record of what was actually exercised. Access problems preventing authenticated checks are recorded as blocked, not passed.

Known release-system issue #192 (out-of-band provisioning secret writes) is a separate tracked dependency. Inspect whether it affects the release and resolve through that contract if required; do not bypass production-change guards or silently broaden this UX work into arbitrary deployment changes.

## 11. Acceptance test matrix

1. A prepared article is identifiable immediately; its full body/main image/card/metadata and grounded rationale are reviewable before a single clear publication decision.
2. Request revision preserves instructions and lineage; the next version needs its own approval. Decline changes no public content and is not re-proposed without meaningful new evidence.
3. Duplicate titles show actual affected pages and before/after. An unprepared finding cannot publish. Internal links show sentence context and valid destinations.
4. Missing profile/access and unknown existence are distinct. No unsupported external account action is invented.
5. Needs-decision count matches actionable canonical records, not runs/errors. Opening/reloading causes no provider charge or mutation.
6. Planned work has a genuine future schedule and local date. Disabled/missing scheduling never displays an old date as a commitment.
7. Completed sidebar shows verified accomplishments. Failed/uncertain work remains truthful and inspectable, not falsely celebrated.
8. Reports and settings have no website Publish button. Content and code publication share canonical approval paths.
9. Growth/chat/Activity agree on identifiers and state; repeated record joins do not duplicate decisions. Persisted items survive reconnect.
10. Concurrent CMS/code changes stale the package; double approval/retry cannot duplicate effects. Partial/unknown publication is reconciled before success.
11. Low/no traffic, unsupported locale, stale/missing evidence and provider errors have truthful scoped states; healthy tools remain available.
12. Desktop/narrow-screen, keyboard, contrast, localization, session expiry and safe rich-text rendering pass actual UI checks.
13. New tenant gets the same schedules, schema, decision workflow and UI without bespoke setup. All three validation tenants run the same shared release.
14. Starting from the current five blocked Oceanic articles, canonical reconciliation preserves bodies and stable identities, prepares current-schema Payload drafts, validates their exact renderable candidates and produces real review actions. A repeated reconciliation creates no duplicates. Genuine conflicts remain explicit and protected.
15. A real new article uses `body`/`sections`, summary, SEO and media according to the shared contract. No writer, validator, fixture or renderer still requires the removed `posts.content` contract. There is no new legacy field or HTML fallback.
16. Thirty-two open/projected records with no live execution cannot produce “32 in progress.” Counts reconcile to unique business items and each active item has execution proof. Stopped and overdue work stays truthful.
17. No full article body is present in list or recent-work responses/DOM. A five-article long-body fixture remains compact; each accessible row opens a spacious single-article detail view with correct controls. The full review is loaded on demand and returning restores context.
18. Recently done includes only actual successful results; failed, blocked, declined and superseded work cannot appear as achievements. There are no inert result cards or unlocalized status keys such as `growth.taskState_failed`.
19. The deployed API source, Growth contract and Worker package versions match the planned release set. An intentionally old API cannot pass the dependent UI's release gate merely because `/healthz` returns success.
20. A successful article review exposes the exact proposed result and publication scope. Revision, decline and publication are each exercised on separate controlled records, not three destructive actions on one article. Live content matches the approved candidate; the journal card and image appear correctly. Drafts remain private before approval.
21. A genuine non-article strategy finding reaches a reviewable candidate through the shared strategy service. An unsupported open-ended investigation remains a readable analysis with an appropriate next step, rather than being forced into a fabricated publish action.

Use deterministic fixtures for routine tests, controlled live runs for integration proof, and exact receipts/screenshots for rollout. Never use demonstration cards as evidence the autonomous service works.

## 12. Definition of done and handoff

The implementation is complete only when the owner can understand the reason for a real prepared improvement, review its exact result, approve/revise/decline it, and see the verified outcome and next scheduled action without operating the backend. The current five article failures must be resolved through shared code and reconciled records, and the overview must cease displaying blocked article bodies as recent work.

The coding AI must provide: source commits and PRs; before/after contract map; first broken boundary/root fix; the read-only backlog audit and idempotent reconciliation result; schema/renderer/approval integration tests; separate API and Worker release receipts; compatibility proof; authenticated overview and full-article review evidence; approve/revise/decline outcome evidence; next runnable schedule; and precise remaining limitations. Do not declare the whole original SEO/AEO strategy implemented just because this inbox is shipped.

This plan is the implementation and acceptance contract. The current user request authorizes the shared product implementation and its release through the documented pipeline. It does not authorize publishing customer articles, running paid research outside existing policy, or bypassing owner approval.

## Implementation status — 2026-10-15

Implemented on `codex/growth-task-repair-20261015`; not yet released:

- Article preparation now serializes Markdown into Payload Lexical `body`, validates against the shared `posts` contract, reads back the exact draft, and persists a revision-bound review package. There is no `posts.content` fallback or HTML writer.
- Active Payload tenants register the shared Growth jobs independently of the retired legacy scheduler flag. Defaults enable the initial/daily/weekly/monthly/outcome pipeline; pending reconciliation rechecks article drafts through the same canonical writer.
- The task projection distinguishes actionable owner decisions, live execution, dated schedules, stopped work, opportunities and history. "With Ada" now requires an unexpired growth-run lease or a queued/running linked chat job; saved `started`, `waiting`, `publishing`, `verifying_live`, stale article-sync and unlinked/invalid research records are not presented as active. Completed research without a draft is an opportunity, not active work.
- Article summaries are concise and localized; long audience briefs stay in detail context, articles are excluded from the recent-success rail, and only the selected article detail loads its full body. Failed provider work is not reported as successful, and expired dates are omitted.
- The shared admin package provides one default decision list, focused filters, a spacious in-place review view, exact Payload revision gating, persistent review URLs, browser-back/focus restoration, and a compact schedule/success rail. EN, FR and es-MX labels are present.
- Package version is `0.10.15`. The default Payload template pins the reproducible artifact integrity generated under the release's Node 22.23.3/npm 11.13.0 toolchain.

Verified so far: the full backend suite passed (1,416 tests); 64 focused Growth/shared-runtime tests passed after the latest execution-state changes; all 39 shared-admin tests and TypeScript typechecking pass under Node 22.23.3/npm 11.13.0; `git diff --check` passes.

Not yet verified or completed: PR checks/merge; immutable package release publication; API-before-Worker rollout; canary and automatic-tenant receipts; per-item reconciliation audit of Oceanic’s saved drafts/actions; a fresh authenticated production browser check; and controlled article review/revision/decline acceptance. No tenant draft has been changed and no customer article has been published. The acceptance matrix above remains open until its live evidence is recorded.
