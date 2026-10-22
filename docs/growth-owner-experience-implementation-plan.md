# Growth: an expert service with a simple owner experience

Status: active implementation contract. Shared-code implementation is underway; production acceptance remains open until CI, registered release receipts, live customer checks and backlog reconciliation are evidenced below.
Date: 2026-10-15. Revised after authenticated acceptance of admin package 0.10.17 exposed a disconnected backlog.
Canonical product repository: `weareheadless/site-agent`.
Audience: the coding AI implementing the shared Growth workflow, API projection and Payload admin experience.

## 1. Product outcome

### October 22 candidate read/claim boundary finding

The real scheduler advanced Atelier's owner-review run through inventory and
assessment and created owner question 3. Content initiatives 1/2 stopped on a
base-revision conflict. Read-only checks show both saved bases still match the
canonical gateway (pages 54/24); the unchanged Oceanic post 6 base also matches.
The existing raw-revision verifier accepts Atelier page 54 and Oceanic post 6.
Atelier page 24 additionally has a public category-route 404; do not conflate
that separate renderer issue with the revision check.

Align Growth verification/readback with the authoring gateway's configured
Payload read shape rather than forcing a separate relationship depth. Preserve
exact hash, schema, tenant, concurrent-draft and immutable-preview checks. A
revision conflict should identify differing field names only, never content.
This source correction still requires a fresh causal tenant check after rollout;
do not infer live success from query-shape alignment or a fixture.

Reject deterministic schema/base preflight failures before claiming a write
operation. Recheck inside the claim before a write, retaining existing destination
guards. A preflight rejection must not lock a document as an uncertain effect.
Existing uncertain operations remain preserved and read-only reconciled; neither
this fix nor a retry request authorises clearing them or replaying unknown writes.

### October 22 API activation and first causal analysis

API release `20261022-api-growth-service-1` activated exact source
`29b61712bf5f08d89fe3eca3a603bd1d6fc81f2a` after 1,592 passing tests,
isolated wheel installation and health verification. Both tenant source
adoptions deployed through #273. Read-only exact-revision verification passed
published detail and listing for Oceanic post 6 and Atelier post 5. Fresh
authenticated Growth loaded for both tenants; this is not candidate acceptance.

Normal POST `/growth/check` created durable owner-review runs for both tenants.
Oceanic reached preparation and stopped before content mutation because its
configured GitHub token returns 403 on repository Issues. Grant the existing
central integration Issues read/write for managed customer repositories before
retrying this stage; never substitute another credential or bypass the journal.
The owner subsequently authorised that exact scope expansion. It was saved on
the existing token without changing repository coverage, expiration or other
permissions; read-only runtime checks now return HTTP 200 for both repositories.
Its orphaned owner-information initiative 2 was reconciled to deferred behind
the actual unanswered initiative 4. No owner facts were invented.

The request boundary also exposed a scheduler omission: creating a pending run
did not wake the existing `growth_pending` job. Correct that handoff with the
existing wake helper, preserving the idempotent run key and never waking a
completed request. A focused test must reproduce the delay before the fix and
assert duplicate requests do not create runs or postpone the wake. Do not add
another executor or manually change tenant scheduler state for acceptance.
An explicit repeat may also bring forward a retry already scheduled on that
same blocked/failed run. Preserve its assessment, candidate identities, receipts,
status and phase. Do not manufacture a retry for hard stops without a due date,
reclaim a running lease, or rerun completed/cancelled work. The same scheduler
and destination idempotency/uncertain-effect guards remain execution authority.

The #266/#268 causal gate remains open. A successful model GET, old publication
read proof, or blocked real analysis is not proof of a fresh approved improvement.

### October 22 live release finding: public revision proof

PR #269 and corrective overlay PR #270 passed the full 1,592-test suite and
GitHub CI. The first canary stopped before deployment because the upstream
helper was absent from the overlay manifest; #270 adds it with a reproduced
stale-helper regression. Fresh canary `runtime-20261022010628-a512bcad` deployed
with runtime fingerprint
`c38eaef314b9f8a3e65adc3f4234c88cd63d3ac1084463046b53315c4fc0b538`.
Authenticated Oceanic Growth and embedded Inbox were freshly loaded; browser
evidence is beside the immutable receipt. This is not causal Growth acceptance.

A read-only call of the new publication verifier against existing published
Oceanic post 6 passed exact document hashing, then correctly rejected its public
HTML: it has a document-ID marker but lacks the revision timestamp marker.
No publish, unlock, DB patch or customer content change was performed.
The API queue PR #271 stays staged until that proof works on selected consumers.

Do not fix this by copying generic `PublicDocument` or the generic catch-all
router over customer files. Despite their protected classification, existing
adapters still contain approved tenant routing/composition: Atelier has locale,
cart, home, product and related-content handling, and Oceanic uses separate blog
routes. Replacing those adapters would repeat the design regressions the owner
explicitly rejected.

Required correction: one protected shared `PublicRevision` component emits the
actual supplied Payload ID and updatedAt without adding a layout wrapper. The
starter uses it for public documents and each listing document. Only this
component is added to the shared-runtime overlay. Existing adapter adoption is
an explicit, reviewed one-time source migration: add the same component around
the existing document render and existing published-post listing, preserving all
current logic, props, presentation files, locale handling and public routes.
Do not weaken the live verifier, infer revisions from HTML text, stamp an
unverified response after rendering, or add an alternate verification endpoint.
No customer schema/content migration is needed.

Validate the adoption through ordinary immutable source release requests, not
manual Worker commands. Before/after source review must prove that the adapter
only gains revision proof and that all approved frontend logic is retained.
Fresh browser checks must cover the existing home, blog listing/detail, nav,
images, motion and tenant-specific routes. The exact-publication read verifier
must then pass both detail and listing against the current canonical document.
Continue #266/#268 causal tests only after this boundary is proven. The dashboard
remains gated; no source test or healthy Worker substitutes for that acceptance.

### October 21 service-model and delivery extension

GitHub #260 and #261–#268 extend this contract. Their area-based dashboard
composition supersedes sections 4/8 where they prescribe a single recommendation
screen instead of the agreed dashboard. Existing exact-review, scheduling,
research, permission and evidence requirements remain mandatory.

The target is one linked improvement:
evidence → investigation → prioritisation → prepared candidate → owner decision
→ canonical release/publication → live verification → later impact observation.
GitHub is the engineering brief/journal, existing Growth/approval records are
execution authority, and the admin/chat/Activity are projections of those records.
Issue state, comments, labels and PR merges never constitute owner approval.

Use an existing tenant-scoped initiative ID with repository/issue identity,
candidate hash and Git/Payload revisions, decision ID, actual release/publication
operation and verification/outcome references. No second task table, scheduler,
approval service, deployment framework, event store or fallback path. Create one
issue for concrete work Ada takes up, not every finding. Customer work belongs in
its registered private repository; shared defects belong in site-agent and are
linked from affected work. Record meaningful milestones only. Payload-only work
does not require a fake commit or Worker release. Approval authorises the exact
candidate; completed means its technical acceptance and live verification passed.
Later impact measurement is distinct and may be inconclusive.

The future dashboard contains one decisions list, five area summaries (Content,
Search visibility, Website health, Audience & competitors, Speed & experience),
and compact verified results. Areas are presentation lenses, not execution kinds
or limits on Ada's judgment. One cross-area improvement has one decision. Each
area explains evidence/limitations, business reason, actual action, owner role,
last assessment and real next assessment. Unsupported/missing data is not health.
Unclassified historical work stays visible; do not infer areas from title words.

The area projection is read-only over growth_tasks/initiatives/runs; the existing
candidate validator still determines readiness. The planner can record explicit
area coverage only with supplied evidence references. Provider observation time,
assessment completion time and job-update time are separate. New/unpublished
sites remain awaiting activation. GET must never research or create GitHub issues.

### October 21 audit and implementation ledger (not live acceptance)

Source baseline: 5484c6423b426d79b841d121ab5fd74e5fe28692. Read-only tenant
inspection used registered config data_dir values, not guessed website paths.

| Boundary | Current owner | Audit finding / next work |
| --- | --- | --- |
| Evidence and assessment | growth_workflow._collect_cycle_evidence / brain.growth.assess | Atelier fails before assessment because all full documents exceed 120 KB. Replace with declared bounded inventory metadata/excerpts; retain every document identity/hash and re-read full selected documents during preparation. |
| Model / owner projection | growth_snapshot / growth_tasks / owner_queue / growth_chat_context | No shared area-coverage view. Add a read projection and evidence-bound planner coverage without another persisted task system. |
| Exact candidate | growth_candidates and article preparation/sync | Reuse current draft/package/renderer checks. Oceanic has a Payload 409 preparation conflict; diagnose its exact operation receipt before any resumption. |
| Decisions | approvals / owner actions / growth_owner_response / workspace | Real owner question exists; one earlier owner-information initiative remains preparing. Trace its action/response/job before deciding its disposition. No direct status reset. |
| Execution | source_deployment / canonical desired queue / Payload publication | Existing immutable release/publication path remains sole authority. Approval and GitHub recording must bind the reviewed contents before effects. |
| Engineering trace | existing GitHub credential/adapter plus work references | Issue/candidate/decision/release checkpoint linkage is not yet implemented. Required by #268 before full acceptance. |
| Outcomes | strategy_outcomes and existing publication verification | Link technical completion and later observation to same work; do not close an issue on merge/upload. |

Oceanic audit: six initiatives (two deferred Payload findings; one owner question
waiting; one owner-information item preparing; one blocked code candidate; one
blocked Payload candidate). Its weekly run is blocked with a historical model
404; the code candidate also retains an older provider/model error. Existing
initial/owner-review/daily/reconciliation completion is not proof that all work
is healthy. Atelier initial, weekly and six daily runs fail in inventory
collection. Records and content are preserved. These findings are not proof of
current provider failure or permission to replay uncertain effects.

Source audit subsequently reproduced a native-write guard identity defect: the
guard passed its operation key to SQL that excluded a package hash. It blocked
the same owned operation. The candidate compares operation_key instead and keeps
other writing/uncertain operations locked; SQLite execution tests reproduce the
old failures and verify the correction. Existing uncertain destination effects
still require receipt reconciliation, not a blanket lock reset or automatic retry.

The candidate's read-only live inventory check subsequently passed for both
registered tenants: Atelier has 96 documents, 1,455,893 full-document characters
and a 93,322-byte declared assessment view; Oceanic has seven documents, 71,635
characters and a 20,070-byte view. Nested SEO media relations are excluded from
assessment metadata and labelled partial; exact hashes still cover the full
canonical document. This proves inventory retrieval/scoping only, not a completed
scheduled assessment, candidate recovery, publication or deployed fix.

Further source verification: commit dcd7bd4c5a5bfaa4d2ad9e4e9c678405df3b5b5c
passed GitHub workflow 39691623539. Its executable Worker-handler regression
reproduced the former successful-HTTP response containing a saved failure.
The corrected handler reconciles an existing uncertain operation by reading the
exact destination and checking its renderer; it never repeats that write.
The Node group passed 26 tests, including the mailbox ownership contracts.
Area assessment ordering uses assessment completion rather than later execution
updates. Deferred initiatives retain their reasons/reassessment conditions.
Technical results require actual verification references; measured traffic is
separate, observational and never labelled causal attribution.

The subsequent scheduler correction keeps capacity-limited findings pending on
the existing Growth reconciliation invocation, counts queued source work toward
capacity, and preserves owner questions independently of candidate capacity.
Seven focused recovery tests cover the new boundaries. This is source evidence,
not proof that a real scheduled tenant run has crossed the repaired boundary.

A further read-only destination check found exactly one uncertain Oceanic
operation, targeting posts:6. Its saved base still matches the public document;
the current draft matches that base, not the proposed candidate. The operation
and its failure remain intact: no lock was cleared, draft invented or mutation
replayed. Atelier has no Growth operations. Oceanic initiative 2 is an
effect-free orphan question from completed work; the shared reconciliation can
defer it explicitly behind initiative 4/action 22, without creating an answer
or restarting completed research. This reconciliation has not been run live.

GitHub journal/source-publication integration is being tested in PR #269.
Do not treat helper functions, a passing subset, or these notes as acceptance of
#268 or permission to implement the dependent dashboard. Exact-source complete
tests, required checkpoint integration, scheduled causal tenant evidence and
canonical releases remain required.

Implementation order: #262 audit/model → #261 projection with #264 progression
repair → #263 decision linkage and #268 issue/delivery checkpoints → #265 results
→ #266 causal multi-tenant acceptance → #267 dashboard. This first source slice
adds the service projection, planner coverage and bounded inventory assessment;
it does not implement GitHub journal checkpoints, repair every historical record,
deploy a new dashboard, or establish end-to-end acceptance. Keep all applicable
issues open until their evidence is recorded.

For #268, persist the last proven checkpoint using existing work/job/receipt
facilities. Ambiguous GitHub writes must be reconciled before another write;
GitHub failure must never enable a memory-only approval or alternate deployment.
If deployment succeeds but completion recording fails, retain its true immutable
receipt and resume recording, not deployment. No fabricated closure, blind retry,
automatic rollback to hide a journal failure, distributed transaction, or complete
CMS/media rollback system. Mixed code/Payload effects use the existing supported
route and expose partial/unknown state; unsupported scope blocks explicitly.

The customer is a busy business owner with little knowledge of SEO, analytics or website administration. Ada investigates the website, interprets the evidence, chooses worthwhile improvements, prepares them and brings understandable decisions to the owner.

The owner must immediately understand:

1. What Ada recommends next.
2. Why it matters to this business.
3. What will change if the owner approves.
4. Whether anything else needs the owner's input.
5. What Ada is handling next.

The owner must not need to classify opportunities, inspect execution states, select keywords, decide which article to write or operate a research pipeline. Detailed data remains available for owners who want to inspect it.

The desired journey is:

**Ada investigates → Ada prioritizes → Ada prepares a specific proposal → owner reviews → owner approves, requests changes or declines → Ada executes and verifies → owner sees the result.**

An investigation finding is not automatically an owner task. A proposed article topic is not a reviewable article. A saved draft is not ready merely because it exists. A published result is not complete until its effect is verified.

## 2. Relationship to existing plans and implementation

Read these documents completely before changing code:

- The canonical repository's `AGENTS.md` and `deploy/README.md` on the VPS at `/SOCIAL/site-agent`.
- `docs/ada-growth-seo-aeo-pipeline-implementation-plan.md` and applicable implementation-status documents.
- The shared Payload content and exact owner-review contracts.
- `GROWTH-DECISION-WORKSPACE-IMPLEMENTATION-PLAN.md` in this workspace and any canonical repository copy of it.

This document supersedes the earlier Growth overview layout, task-filter navigation and supporting-rail design. Do not retain a permanent row of Needs review / With Ada / Scheduled / Needs attention / Opportunities / History tabs and add another recommendation panel above it.

The earlier plan's backend obligations remain requirements: repair article authoring against the canonical Payload schema, preserve and reconcile saved drafts, prepare actual candidates, implement exact approvals and revisions, verify scheduling and prove real publication. Those obligations are not satisfied merely by the subsequent UI release or by passing health checks. Audit their current state rather than assuming they were completed.

The observed October 15 UI displays 0 items for review, 0 with Ada, 4 scheduled, 10 needing attention and 21 opportunities. These are baseline observations, not a success criterion or a desired final count. Determine what those records represent and whether Ada has prepared the useful proposals they should produce.

Implementation is shared Site-Agent work. Oceanic, Atelier and Northstar validate the same product. No tenant-specific dashboard or manually prepared customer article may substitute for a functioning shared pipeline.

## 3. Scope and architectural constraints

Deliver the owner experience, prioritization/preparation integration and root repairs needed to produce useful decisions. Preserve existing analytics, keyword, competitor, health and content capabilities behind progressive disclosure.

Reuse the existing evidence, initiatives, drafts, owner actions, approvals, outcomes, scheduler and durable jobs. The Growth presentation is a read projection over canonical records. Do not create another task database, approval authority, publishing service, generic workflow framework or autonomous agent platform.

Payload remains the shared schema and content authority. Ada may prepare content and frontend code through supported services; she may not change schemas, auth, migrations, admin packages, package pins or tenant runtime configuration. Website code changes retain the established GitHub and release traceability.

No runtime legacy-field conversion, alternate CMS path, static article publisher, endpoint substitution, fabricated task, fake activity or successful-looking empty response may cover a missing dependency. Optional presentation polish must not expand this into a frontend redesign, analytics-platform rewrite or complete Ahrefs replacement.

## 3A. Required correction: connect the backlog to the owner's next step

### Observed failure and completion status

The authenticated Oceanic screen on package 0.10.17 shows “Nothing needs your decision right now” and “Some background work has stopped”, while Ada's work contains 10 attention items and 21 opportunities. The scheduled traffic refresh is visible, but the screen does not establish which work it will advance, why no proposal is ready, or what will recover the stopped work. These counts are observations to audit, not evidence that all 31 records are distinct, valid or actionable.

The layout release is deployed; the connected Growth service is **not accepted as complete**. Header rendering, tab navigation, shared package rollout and a healthy API cannot close the workflow obligations in this plan. The coding AI must inspect current source and records before claiming which transitions are missing.

### One service progression

Use the existing canonical records to implement this progression:

**Evidence/finding → investigation → prioritization → bounded preparation → exact reviewable proposal → owner decision → execution → verification → outcome measurement.**

These are responsibilities and transitions, not a requirement for eleven new database statuses. Map them onto the existing model and document that map. Each transition must have an existing service owner, persisted input/output references, an invocation trigger and a failure disposition. A completed research run must either advance eligible work or persist why no further action is justified. Saving an opportunity is not the terminal success of an analysis intended to produce improvements.

Scheduling must invoke the complete applicable progression, not stop after collecting metrics or writing findings. Resume after a dependency resolves through the existing durable job mechanism. Do not make opening Growth or clicking through tabs the trigger for autonomous progress.

### Every backlog item has a disposition

Audit all current attention and opportunity records, including any related drafts and owner actions. For each unique business item, retain its canonical identifiers and record:

- Evidence and freshness; relationship to the business goal; duplicate/superseded relationships.
- Current real state, last successful boundary and first failed or missing transition.
- The next service action, responsible executor and durable job/schedule reference when execution is promised.
- Dependencies and whether they affect this item, a subset of work, or the entire service.
- Whether owner input is actually necessary, and the exact question/access/authorization that would unlock progress.
- A disposition: investigate, prepare, ready for review, waiting for owner input, scheduled recovery, operator intervention, deferred with a reason and reassessment condition, rejected as unsuitable, superseded, or verified complete. Reuse equivalent canonical states where they exist.

No silent bulk dismissal, blanket status reset, synthetic approval or manual tenant proposal can satisfy this audit. Preserve bodies, media, decisions, edits and provenance. Repair the record-creation or transition boundary that produced orphaned work and reconcile existing records idempotently through shared services.

### Technical recovery is part of the service

Classify the actual failures before retrying. Deterministic schema, invalid provider field, permission, connection or code errors need their root cause corrected. Retry only failures for which the existing policy supports retry, with a bound, persisted next attempt and preserved progress. Unknown external effects require reconciliation before another attempt.

Use existing job leases/heartbeats and recovery facilities to detect abandoned execution; do not invent a second watchdog. After repair, resume from the earliest valid persisted boundary and rerun the affected validation. Prevent duplicate research charges, candidates, publications and owner tasks. Independent evidence-backed work can continue where its own dependencies are satisfied.

Escalate unrecoverable platform problems through the existing operator diagnostics/incident mechanism, with tenant, error category, affected work, last boundary and recovery ownership. The business owner receives a concise description of the practical impact. They must not be assigned an API error to approve or asked to press a generic repair button. Do not promise automatic recovery or a deadline unless it is backed by a real job and supported estimate.

### Ada owns selection and preparation

Ada assesses the opportunity backlog, investigates where necessary and prepares the strongest eligible improvement under existing concurrency, entitlement and spending policy. She can conclude that an article is inappropriate, request a missing business fact, or defer weak evidence. Every deferral records why and what evidence/event/date will cause reassessment; do not repeatedly recycle an unchanged idea.

Do not require the owner to select from 21 topics, launch keyword research or press “Run analysis” to make the included service function. Manual analysis remains a secondary capability. Prepare a small bounded set; do not generate 21 proposals at once or invent work to fill an empty inbox. When preparation has capacity, an analysis or resolved dependency must reliably dispatch the next eligible item without creating another scheduler.

### One coherent answer on the default screen

The server's existing Growth projection must derive the owner-facing next step from the same canonical relationships used by Ada's work, chat and Activity. Return enough structured references to explain the chosen next step and its execution/dependency state. Do not assemble unrelated banners and empty-state messages independently in React.

Apply these presentation rules:

| Actual situation | Default Growth response | Owner action |
| --- | --- | --- |
| Exact validated proposal is ready | Lead with the recommended change, reason and prepared result; reveal other ready decisions compactly | Review, approve, request changes or decline |
| A necessary owner answer unlocks progress | Ask the specific business question or supported access/authorization request and explain what it unlocks | Answer or authorize the bounded request |
| Eligible work is durably queued or running | Explain what Ada is preparing and why; show its real state and next update/check when known | Optional discussion; no approval chore |
| Preparation is blocked by a service failure | Explain what useful work is blocked and the actual recovery state; keep any independent ready proposals available | No technical task unless owner access/input is truly required |
| Opportunities exist but are deferred | Explain why none currently warrants preparation and the real reassessment condition/date | Optional change of goal or business input |
| No suitable work after a successful assessment | State that Ada reviewed the available evidence, give its date and the next runnable assessment | Optional discussion |
| Assessment is missing, stale or unavailable | State that the next recommendation cannot yet be established and show the actual analysis/recovery state | Only a concrete owner dependency, if one exists |

“Nothing needs your decision” may describe the approval count, but must never stand alone as the service answer while eligible work is unprepared or failures prevent analysis. A generic traffic-refresh date cannot substitute for the missing preparation/recovery step. When no reliable completion time exists, show the actual state rather than a fabricated ETA.

If useful proposals and technical failures coexist, lead with the useful owner decision and summarize the affected service separately. Avoid two competing primary cards. Preserve a stable featured selection while the owner reads a proposal.

### Supporting work view

Replace the permanent Needs review / With Ada / Scheduled / Needs attention / Opportunities / History filter strip still present inside Ada's work. It preserves the old disconnected mental model even when moved behind a tab.

Use a compact chronological explanation of what Ada is preparing, what comes next, what is paused and why, and verified recent results. Secondary disclosures can expose research findings and technical details. Counts are supplementary information, not the owner's navigation or prioritization responsibility. Keep all approval decisions in the same canonical review destination; reports remain read-only and settings use their own existing controls.

### Required causal acceptance evidence

For at least one existing Oceanic opportunity and one stopped item, demonstrate their actual transition through the repaired shared workflow. Show the canonical references before and after, dispatch/recovery evidence, validated proposal or justified disposition, and the matching default screen. Demonstrate an article and a non-article proposal through existing controlled-test approval scope; do not publish customer work merely to satisfy a screenshot.

Use a real scheduled invocation to prove analysis reaches prioritization and preparation. Verify future tenants inherit this invocation through provisioning. A timestamp, manually invoked authoring function, fixture or manually marked-ready draft cannot replace this proof.

The precise Oceanic baseline must end with every audited item accounted for and no unexplained eligible backlog. It need not end with zero errors or 31 proposals. A remaining failure requires explicit impact, recovery ownership and an honest incomplete status where it prevents acceptance.

## 4. Default Growth screen

### 4.1 One recommendation, immediately understandable

Retain the existing global admin navigation, HelloAda logo and access to Ada. Replace the current Growth tab bar and task counters with a compact Growth header and the following vertical hierarchy:

1. A primary recommendation or the most important owner dependency.
2. A short list of other ready decisions, when any exist.
3. A compact summary of Ada's preparation, next scheduled review and recent result.
4. A secondary link to detailed results, research and work history.

Avoid a decorative introduction, large hero, empty panels or metrics pushing the decision below the fold. At an ordinary laptop viewport, the recommendation, its reason and its primary action must be visible without scrolling past dashboard chrome.

Each recommendation answers, in this order:

- **What:** a concrete business-facing title describing the proposed improvement.
- **Why:** one or two short sentences grounded in actual evidence and the business goal.
- **Prepared result:** what Ada has already made and the exact scope of the intended public change.
- **Next action:** a descriptive control such as Read the draft, Review the changes or Answer Ada.

Provide a secondary Ask Ada about this action that opens the existing conversation with the canonical proposal selected. Do not create a separate chat implementation or require the owner to restate the proposal. Internal context remains hidden; the visible conversation retains the owner's own message.

The summary is not a full article excerpt, raw audit finding, score wall, provider error or list of keywords. No invented uplift, traffic promise, keyword volume or certainty is permitted. A hypothesis must be described as a hypothesis.

### 4.2 Other decisions

Show at most three additional compact rows initially, with one useful sentence and one clear action each. If more exist, provide See all decisions with the real remaining count. This opens a simple list in the same main area, not another permanent navigation strip.

The full list contains only decisions the owner can take now. It uses the same priority order, identifiers and review destination as the featured recommendation. Do not duplicate the featured item in the visible additional rows.

The owner does not have to pick which of 21 research ideas deserves attention. Ada's internal backlog stays out of this list. Additional ready proposals remain discoverable without implying all must be handled immediately.

Stable ordering matters: do not swap the featured item while the owner reads or edits a revision. Newly available work can appear after a refresh or completed decision. Keep selection and scroll position when returning from a review.

### 4.3 Ada's work, quietly summarized

Use one compact section with only available, truthful information:

- Current preparation, if a real job or durable queued preparation exists.
- Next scheduled review, with a real date, owner-local time and purpose.
- Most recent verified result, with a link to its details.

Do not reserve a large running-task window, animate a fabricated live process, show internal state counters or list every scheduled job. Omit optional lines when there is no corresponding fact. Link View Ada's work to an inspectable secondary history and schedule view.

Technical failures belong in this secondary work view and operator diagnostics. If the owner cannot resolve a technical failure, do not turn it into an approval. A persistent failure that prevents service must still produce an honest, concise service notice; never claim everything is handled while work is stopped. Promise a retry only when a bounded supported retry has actually been scheduled.

An owner-resolvable dependency, such as identifying the correct business profile or granting a supported connection, becomes a plain-language decision in the main list. Explain why the answer is needed and what it unlocks.

### 4.4 Goals, metrics and detailed tools

Keep the current business goal in a compact context line with Change goal. Reuse the existing Ada-assisted goal update flow; do not add intake questions or a new goal dashboard.

Provide a clearly secondary Explore your results entry. Inside it, retain Traffic & search, Keywords, Competitors, Site health, Content and Connections as detailed views or an equally clear compact navigation. Preserve current periods, history, filters and provider capabilities.

Keep View Ada's work distinct from Explore your results: one explains work and scheduling, the other provides evidence and performance. Both return to the main Growth screen with context intact. Neither introduces another approval inbox.

An owner can ask Ada a new business question or request a change through the existing conversation. Provide a small Ask Ada affordance; do not build an additional standalone input/backend if the shared chat already supports contextual navigation.

## 5. Review experience and decision semantics

Reviews occupy the main content area inside the current admin shell. Use a stable, authorized item address, Back to Growth and a compact action toolbar. Avoid modals, skinny article rails, nested accordions and stacks of full drafts.

### Articles

Show the complete prepared article with its title, featured image and readable body. Start with a brief explanation of why Ada selected this subject. Offer listing-card appearance, search title/description, proposed URL, image details and source evidence through secondary disclosure. The actual website preview must use the existing supported preview mechanism.

Use a comfortable reading width, approximately 65–80 characters. Keep actions available while reading without covering content or consuming a large portion of the viewport.

Actions:

- **Approve & publish:** explicitly state that this exact article will become public and where.
- **Request changes:** capture the owner's instruction, preserve the draft and lineage, and have Ada prepare a revised candidate through the same service.
- **Decline:** preserve decision history and optionally accept a reason; never publish or delete unrelated work.

A new revision invalidates the previous approval. The next review must display the revised exact candidate, not an old body with a new status label. If publication additionally requires a code/release change, explain that effect and reuse its canonical approval scope; do not secretly broaden an article approval.

### Metadata, links and other website changes

Show the affected page, the current value/context, the proposed result and the visitor/business benefit. Internal links require the relevant sentence, anchor and destination. Shared footer/navigation changes require an understandable description of all affected pages.

Actions describe the effect: Apply these changes, Request changes, Decline. Group closely related changes into one bounded package; do not bundle unrelated fixes into a broad approval.

Ada should normally prepare eligible, included improvements before asking the owner. Avoid making the owner first click Ask Ada to fix and later return to approve the same straightforward repair. If preparation genuinely requires a missing business fact or budget, request that dependency first.

### Questions, access and spending

Ask only what the owner can answer or authorize. Distinguish an unknown business fact from a technical service failure. Unknown profile existence must not be presented as proven absence.

Included research runs under existing policy without per-tool approval. Additional paid work requires the existing scoped budget/entitlement decision. A recommendation view or evidence disclosure must not trigger a charge. Unsupported external provisioning or management must never be offered as an implemented action.

Reports are read-only results. Business voice/configuration updates use the existing settings confirmation where appropriate. Neither receives a website Publish action or appears in frontend rollback history.

### After a decision

Immediately acknowledge the real outcome. If approved work is queued, say queued; mark it complete only after verification. Remove the handled decision from the ready list and show the next useful recommendation. Failure or uncertain execution must remain inspectable and cannot appear as an accomplishment.

Revision instructions survive recoverable reconnect/session expiry without automatic resubmission. Double clicks and reconnects must not duplicate decisions, jobs or publication. If a concurrent CMS/code edit invalidates the candidate, preserve the owner's input and have the supported workflow prepare a fresh review.

## 6. Ada's editorial and improvement responsibility

### 6.1 Evidence to an internal backlog

Reuse existing scheduled analysis and evidence collection. Ada may investigate traffic/search changes, business intent, technical health, existing content, competitors, internal links and relevant AEO opportunities through supported tools and policy.

Keep room for useful expert judgment. Do not reduce Ada to a fixed checklist of article templates or a hard-coded set of SEO rules. She can pursue a promising investigation, decide that content is not the best response, identify insufficient evidence or ask for a business fact. Her recommendations must still reference real evidence and use supported effect services.

No canned conversational examples or sample business recommendations belong in model prompts. Prompts define responsibilities, typed outputs, evidence expectations, supported capabilities and limits. Presentation labels belong in localized UI copy.

### 6.2 Prioritize before presenting

Reuse the strategy service to consider business relevance, evidence quality/freshness, expected practical usefulness, effort, prerequisites, current owner decisions, recent changes and duplication. Do not present a numerical SEO score as the business decision.

The output is an ordered canonical backlog plus a concise grounded rationale. Reuse existing priority and evidence fields where available; add only necessary fields. Do not create a separate ranking agent, score store or scheduler.

Prioritization must distinguish:

- A necessary owner answer that unlocks worthwhile work.
- A prepared improvement the owner can review now.
- An idea requiring further investigation/preparation.
- A technical failure requiring platform/operator handling.

Only the first two can become main-screen decisions. An urgent, actionable owner dependency may take precedence over an article; a raw provider error never does.

Declines, prior approvals, active preparation, owner constraints and existing content must inform selection. Do not repeatedly propose the same declined topic without meaningful new evidence or an explicit owner request. Do not generate overlapping articles merely to keep the inbox populated.

### 6.3 Prepare a small amount of useful work

Ada prepares the highest-priority eligible proposals under the existing limits and budget. Reuse current backlog/concurrency policy and document any necessary small cap. Do not prepare all opportunities simultaneously or keep generating because the UI has fewer than three decisions.

For articles, use the canonical Payload authoring contract, media relations, summary, body/sections, SEO and route policy. Validate listing/detail rendering and media before offering review. For technical or linking changes, use the existing exact candidate service.

Preserve the earliest valid persisted boundary on a retry. Preparation failures must be diagnosed at their source and resolved through shared code. Existing saved drafts must be reconciled through the same preparation service with identity/conflict protection, never by assigning ready status directly.

### 6.4 Presentation does not invent readiness

Generate concise owner-facing reasons from the actual evidence and prepared candidate. Persist them on the existing candidate/initiative only if required to freeze the review rationale; otherwise derive the display from canonical fields. Do not persist a second UI task model.

The canonical readiness validator determines whether the exact candidate is reviewable. A language model cannot grant publication permission, invent a review hash, declare an external effect successful or use prose to override readiness.

When nothing is ready, show the truthful next step: actual preparation, the next scheduled analysis, a necessary owner answer or a service problem. An empty ready list is not proof the system is healthy, and a healthy system does not need fake recommendations to look active.

## 7. API and data contract

Extend the current Growth read projection with the minimum shape required for this screen. Reuse existing endpoint conventions rather than creating a parallel API family.

The response must expose:

- One featured owner decision, if available.
- A bounded set of additional ready decisions and a real pagination/remaining count.
- A concise service summary with actual preparation, next schedule and recent verified result references.
- Availability/freshness information sufficient to distinguish a healthy empty list from failed or incompatible retrieval.
- Existing goal and navigation references.

Each decision retains canonical tenant/item/candidate/action/approval references as applicable, a display kind, concise purpose and reason, affected scope, permitted actions, review destination, freshness and priority. Detailed article bodies and full evidence are retrieved only on authorized detail requests.

Deduplicate by canonical relationships, not by matching titles or selecting the newest unrelated record. The same item has one identity across Growth, chat, Activity and review. Server projection owns readiness and action semantics; React must not independently infer them from status arrays.

GET requests remain side-effect-free. Selecting tabs, opening Growth or expanding a reason must not launch research, prepare a draft or incur spending. Mutating actions use existing authorized, idempotent application services with durable job/result references.

Preserve tenant isolation, safe rich-text rendering, redacted diagnostics and exact approval checks. An incompatible API response must show a truthful unavailable state and fail the release gate; it must not be rendered as zero decisions.

## 8. Visual and interaction specification

Use the approved HelloAda mark, typography and existing brand tokens. Keep dark global navigation/chat, a light neutral canvas, white reading surfaces, readable dark text and coral/orange primary actions. The design skill informs contrast, spacing and restrained polish; its marketing-scale typography, large whitespace and motion prescriptions do not override this dashboard's functional density or established identity.

Use one dominant action per recommendation. Distinguish secondary conversation and disclosure controls. Avoid a status-color collection, decorative pill overload, multiple equally prominent cards and competing orange buttons.

Use compact chrome, clear section separation and consistent alignment. The primary recommendation should feel deliberate and useful, rather than a large empty container. No full-page entrance animations, artificial activity pulses or scroll-dependent information reveal. Small state transitions must respect reduced motion and never delay a decision.

Support desktop, tablet and narrow mobile widths without horizontal page scrolling or squeezed columns. Reviews remain readable at narrow widths. All actions are keyboard accessible, focus is restored after navigation, loading states do not erase selected content and error recovery preserves unsent instructions. Use accessible contrast, readable text and touch targets.

Localize all labels, states and owner-facing failures in EN, FR and es-MX. Dates/times use the owner's configured timezone; expose it in scheduling details. Long titles and translated labels must wrap safely.

## 9. Implementation sequence

### Phase 0 — Confirm the real pipeline and remaining failures

Execute section 3A's complete item ledger first. Treat the 0.10.17 browser check as UI smoke evidence only. Produce a transition map linking the scheduler, evidence, strategy, authoring, review and recovery services; identify which invocation actually advances each boundary.

Read the canonical contracts and inspect a verified official checkout. Record current API, admin and tenant release identities. Preserve unrelated working changes.

Trace representative real records from evidence through priority, preparation, validation, review and verified execution. Specifically explain the observed empty review list, 21 opportunities, 10 attention items and saved Oceanic articles. Recheck the earlier `posts.content` versus shared body/sections failure; do not assume it is still present or already fixed.

Produce a compact ledger identifying the first broken boundary, owner-actionable dependencies, internal failures, duplicates and the proposals that should be prepared. Separate proven behavior from incomplete acceptance evidence. Audit whether current scheduling actually invokes prioritization and preparation rather than ending at evidence collection.

Exit: an evidence-backed map of existing capabilities, necessary root fixes and exact reused services. No customer publication or manual content creation during the audit.

### Phase 1 — Make Ada produce the right decisions

Implement section 3A's connected progression, disposition and recovery obligations before further layout work. Prove one existing eligible opportunity automatically advances to preparation, and one repaired stopped item resumes idempotently. Ensure an unprepared eligible backlog cannot produce an unexplained healthy-empty service response.

Repair the first broken shared boundary. Integrate prioritization and bounded preparation with the existing scheduled/manual analysis path where missing. Resolve article/schema and candidate linkage issues through the canonical authoring/reconciliation service.

Add the narrow owner projection and detail references. Test readiness, owner dependencies, blocked work, deduplication, stable prioritization and truthful empty/unavailable states. Reuse existing modules such as `growth.py`, `growth_tasks.py`, `growth_workflow.py`, `growth_candidates.py` and `core/jobs.py` according to their actual current ownership; do not perform speculative module rewrites.

Exit: a real prepared article and a real non-article improvement can reach exact owner review through Ada's normal workflow. A repaired projection alone does not satisfy this phase.

### Phase 2 — Replace the overview and review surfaces

Implement section 3A's situation table from the canonical projection. Remove the old status-counter navigation from the secondary work view too. A service-warning banner placed above an unrelated empty-decision panel does not satisfy this phase.

Implement the new composition in the shared Payload admin Growth components, copy/data contracts and styles. Reuse the review shell and exact actions wherever they already exist. Replace the permanent task-state tabs, stacked bodies, duplicate recommendation panels and dead review controls.

Provide the primary recommendation, additional decisions, concise Ada summary, full-area reviews, contextual Ada discussion and secondary results/history navigation. Keep all useful evidence capabilities available. Avoid introducing a new UI framework or a second conversation surface.

Exit: representative populated, empty, preparing and interrupted states work at desktop and mobile widths with correct actions and clear next steps.

### Phase 3 — Reconcile existing work and prove owner actions

Generate a read-only reconciliation plan for affected saved records, then apply it through the shared preparation service under the existing authorization. Preserve saved content, identities and owner changes. Repeated reconciliation must create no duplicate drafts or decisions.

Use controlled test records to exercise approval/publication, revision and decline separately. Prove no public mutation before approval, revised hashes invalidate old approvals, concurrent edits are protected and the actual public result matches the approved candidate. Verify a second meaningful improvement follows the same flow.

Exit: evidence of actual product behavior, not demonstration cards, mocked permissions or a manually edited article.

### Phase 4 — Release through the existing pipeline

Run focused regression/contract tests and the repository-required checks. Build and inspect the generated admin package: the new markup and review actions must be present, the permanent status-tab layout and list-body dumps absent. Publish the immutable shared package through the established release mechanism.

If the API projection/preparation behavior changed, queue and verify the exact supporting API SHA with its compatibility identity before the dependent admin rollout. Queue registered tenants, full customer SHAs and new release IDs on official Site-Agent main. Let `helloada-release.timer` perform canary and fanout. Never deploy via arbitrary local Wrangler/OpenNext commands or edit an old release directory.

Inspect receipts and logs at the exact failed stage. Fix the root cause and use a new release ID after a failed/interrupted attempt. Record API activation, Worker deployment, reconciliation and functional browser acceptance separately.

Reload fresh authenticated Growth documents for Oceanic, Atelier and Northstar after their receipts succeed. Confirm the correct tenant, shared package, data and actual interaction; record browser verification beside each receipt. Health checks and an attractive empty state are smoke evidence only. Do not describe unexercised approvals as end-to-end verified.

New tenants must inherit the same default schedules, schema and owner experience through the canonical scaffold/provisioning path. A fresh-site end-to-end test may use the existing intake test scope, but must not be silently substituted for the required existing-tenant repair.

## 10. Acceptance criteria

### Owner comprehension

1. A nontechnical owner can identify the recommended next action, why it matters and what approval will do without opening analytics or asking what a task state means.
2. The default Growth view contains no permanent task-state filter bar, raw opportunity queue, technical error list or stacked full article bodies.
3. One prepared recommendation leads the page; at most three additional decisions appear initially. More remain accessible without duplicate items.
4. The owner does not need to choose keywords or article topics before Ada prepares useful work under the agreed policy.
5. Actual preparation, next scheduled work and recent results are understandable without dominating the decision surface.
6. Detailed data and history remain available, and their links return cleanly to Growth.

### Workflow correctness

7. Every review action resolves a real authorized canonical candidate or owner dependency. Findings without prepared changes cannot publish.
8. Articles show full content and images; metadata/link changes show actual affected values and context. Purpose and evidence are inspectable.
9. Approve, revise and decline are exercised separately through the real services. Exact approved content becomes public only after the intended verified execution.
10. Revision and concurrent edits invalidate stale approvals, preserve user instructions and require a new exact review.
11. Internal failures never become owner approval chores or successful completed work. Service failure cannot masquerade as all caught up.
12. The real saved backlog is reconciled without duplicate records, invented readiness, lost content or overwritten owner edits.
13. Schedules persist and execute prioritization/preparation. A future timestamp without a runnable job is not accepted as a scheduled service.
14. Ada can investigate and recommend different useful improvements using real tools; the pipeline does not force every finding into an article or a canned SEO checklist.
15. Decisions, chat, Activity and results agree on canonical identity and state. Reconnect and repeated actions do not duplicate effects.

### Release and interface quality

16. Long titles, multiple drafts, no proposals, blocked preparation, missing access, stale data and incompatible API states have readable, truthful UI.
17. Desktop/mobile, keyboard, focus restoration, readable contrast, EN/FR/es-MX and owner-timezone scheduling are verified on rendered screens.
18. All three validation tenants receive the shared release through the queue. API/package compatibility and exact live identities are evidenced.
19. Fresh authenticated browser checks include a populated recommendation and its full review, not only an empty overview. Missing credentials/access remain explicitly unverified.
20. No alternate schema, publisher, approval store, tenant-specific patch or runtime fallback was introduced.

### Connected-service regression gates

21. The audited Oceanic attention/opportunity backlog has an explicit disposition per unique item, with preserved provenance and no unexplained orphan. Counts across surfaces reconcile to those canonical records.
22. A scheduled analysis advances a genuine eligible finding through investigation/selection into durable preparation and exact review, without an owner launching tools or opening the UI.
23. A deterministic technical failure is corrected at its source and resumed through shared services. Repeating recovery cannot duplicate charges, drafts, decisions or effects. Uncertain effects are reconciled before retry.
24. With zero approvals and an eligible backlog, the default view explains the actual preparation or blocker. With deferred opportunities, it explains the rationale and reassessment. With failed retrieval, it never claims the site is caught up.
25. A missing owner fact becomes a specific question; an internal provider/schema error does not. Independent ready proposals remain available when unrelated service work is blocked.
26. Every promised preparation/retry/next assessment resolves to an actual runnable job or supported scheduled invocation. No fabricated completion estimate, generic refresh date or inert status counts stand in for that link.
27. Ada's work explains progression and verified results without requiring owners to navigate the old six status buckets or choose research topics. Default and secondary views agree on what happens next.
28. Release evidence includes a populated real proposal, its exact review, a recovered item, the scheduled progression and the truthful blocked/deferred states. A successful package fanout and empty-screen screenshot cannot close these gates.

## 11. Required handoff

The implementing AI must provide the plan-to-code coverage and any remaining gaps; source commits/PRs; root-cause findings; the backlog reconciliation result; focused workflow/approval tests; API and Worker release receipts; authenticated screenshots of populated overview and full review; and evidence of approve/revise/decline plus verified outcomes on controlled records.

The final explanation should tell the product owner what changed and how to use it. Do not bury an incomplete pipeline behind a list of passed builds. Completion means Ada brings useful prepared decisions to the owner through the normal service, and the owner can understand and act on them.

## 12. Scope of this document

This is the canonical implementation contract. The owner has authorized implementation in a follow-on request. That authorization covers shared product code, tests and documentation; it does not authorize publishing customer content, approving recommendations, incurring paid research, or bypassing release gates. Each acceptance item remains open until its evidence is recorded.


## 13. Implementation and release ledger

The implementation branch applies these shared corrections: article drafts are checked and synchronized through the destination's schema-derived Payload authoring contract; blocked article review responses expose localized reason codes rather than internal exception text; Growth recommendations are limited to executable Payload changes or genuine owner-information requests; generic suggestions are excluded from owner tasks; generated unprepared findings are not converted into synthetic tasks; and the former status-filter strip is replaced by a single sectioned work list. The shared owner-queue contract reports progression from canonical tasks and actual assessment runs, distinguishing evidence refresh from recommendation assessment. Failed owner-triggered assessments are represented as service work rather than owner approvals; expired assessment leases are not presented as active; uncertain external research remains unresolved and is never represented as an automatic retry. Local CrawlSEO validation failures are recognized as pre-dispatch failures so they do not consume a paid-research reservation as if a request had reached the provider. No customer content has been approved or published.

The read-only Oceanic audit identified the immediate causes behind the disconnected screen: the visible opportunity total consists largely of legacy internal `suggestion` owner actions, not prepared decisions; the owner-review run failed because assessment evidence validation accepted inventory/source references but rejected the same supplied source IDs; and two saved article ideas have deterministic request errors (`en`/`MX` unsupported by the then-deployed provider catalog, and an invalid CrawlSEO brief summary). The shared code now admits source IDs into the validator and surfaces these article failures in localized, non-technical service states. The supported CrawlSEO adapter resolves locale against its current official catalog before dispatch; no tenant-specific locale override or paid retry is part of this change. Existing records remain intact pending idempotent reconciliation through the shared preparation service.

Remaining acceptance is open. Source commit `98655b9b87bfea81464b25b998b4da2a2ef8aad1` passed the repository validation workflow (run [38816172262](https://github.com/weareheadless/site-agent/actions/runs/38816172262)): Python tests, shared Payload core/admin tests and typechecks, admin candidate build/inspection, template and Mailflare contracts, and locked release-asset verification all passed. The immutable shared admin artifact is still a staged release, and no API or Worker release receipt has been produced. Customer deployment and fresh authenticated browser checks therefore remain outstanding. The live Oceanic backlog still requires canonical-ID reconciliation and a documented disposition for each unique record; scheduled recommendation progression and article recovery must be observed on the real tenant without unapproved paid requests. Approve, revise and decline require controlled records. Do not claim full plan acceptance from these source changes alone.
