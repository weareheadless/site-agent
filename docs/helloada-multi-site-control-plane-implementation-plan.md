# HelloAda Control Plane, Gated Design Operations, and Cloudflare-First Websites

**Status:** Proposed implementation contract for a coding AI
**Date:** 2026-09-29
**Scope:** HelloAda account/site portfolio, conversational intake, first-connection Cloudflare bootstrap, gated design operations shared by both interfaces, and the custom-domain launch gate.

**Reading order:** read this whole document before touching code. Section 3 describes
what exists today and what must change. Sections 4-6 are the core architecture.

## 1. Authority

This document is authoritative for the HelloAda product journey, the tool
catalog shared by HelloAda and the customer website, and the gated design loop.

It does not replace:

- `AGENTS.md` — repository invariants, credential handling, application-service
  boundaries, honest reporting.
- `docs/simplify-design-pipeline-implementation-plan.md` — replace-first
  removal of the specialist orchestration; the native design path.
- `docs/next-react-payload-correction-plan.md` — canonical customer runtime
  (Next.js + React + Payload + D1 + R2).
- The design-pipeline safety rules: immutable candidates, exact-SHA isolation,
  host-owned build evidence, no production mutation without owner action.

Where an older document assumes infrastructure is created only after a
candidate is accepted, **this document supersedes that timing**. Infrastructure
is created at website creation. The custom-domain/payment launch gate is the
later monetization boundary.

This document does not authorize any deployment, push, or Cloudflare mutation.
Existing credential and deployment rules still apply.

## 2. Executive decision

```text
HelloAda account
  -> website A   website B   website C
       each website is bootstrapped on Cloudflare at creation
       each website has one conversation, one operation queue, one revision history
```

1. **HelloAda is the front door and portfolio.** Sign-in, create website,
   conversational intake, live preview, handoff to the website workspace.
2. **Each website is a real Cloudflare/Payload runtime from the first
   connection.** Worker URL, D1, R2, Payload admin. No separate staging site.
3. **Ada uses the same tools in both interfaces.** The tool catalog is an
   application-service layer. HelloAda is a minimal frontend over a subset;
   the existing WebsiteWorkspace is the full frontend over the complete set.
4. **Design is gated by the owner, not decided autonomously.** Ada performs a
   bounded operation, reports what was done, and proposes next steps as
   recommendations. The owner approves, rejects, or redirects. The next
   operation starts only from an explicit owner action.
5. **The custom domain + payment is the launch gate.** GA4, Search Console,
   CrawlSEO, email, webhooks, and indexing activate only after it.
6. **One revision history with rollback.** No product-level candidate/live SHA
   split. A Git/deployment identity is retained internally for reproducibility.

## 3. Current implementation analysis

This section is the required analysis of the current intake and first-design
scripts and how they must interact with HelloAda and the customer website.
Read it before proposing changes.

### 3.1 Conversational intake (exists, keep)

| Component | Behavior today |
|---|---|
| `application/design_intake.py` (`DesignIntakeService`) | Owns the intake conversation: draft revisions per turn, `collecting -> ready_to_build -> confirmed`, `confirm()` bound to revision + draft hash, `build()` reservation and idempotency. |
| `brain/design_intake.py` | Intake prompting, readiness judgment, advice jobs. |
| `core/design_intake_contracts.py` | Typed draft/status/revision contracts, provenance, confirmation rules. |
| `application/incubations.py` `confirm_intake()` | Wraps confirmation, writes genesis, transitions the incubation. |

The intake already behaves like a tool: it is conversational, revisioned, and
gated by an explicit confirmation. This is kept. The interaction missing is
"what comes next", which is currently the autonomous build.

### 3.2 First design / build pipeline (exists, must be split)

| Component | Behavior today |
|---|---|
| `application/workspace.py` `ChatService.start_first_page()` | Explicit post-intake action; calls `intake_service.build()` for `index.html` only. |
| `application/design_intake.py` `build()` | Requires `CONFIRMED`; reserves an idempotent build; submits a run via `DesignLabService`. |
| `application/design_lab.py` (`DesignLabService`) | Submits/runs design candidates; quality policy; retained runs. |
| `application/design_jobs.py` | Durable executor: claims runs, retains candidates before validation, records review state. |
| `application/designs.py` (`DesignService`) | Run lifecycle `created -> assessing_intake -> planning -> building -> candidate_ready -> validating -> ready_for_review`; host build; browser evidence; one refinement child. |
| `core/design_contracts.py` | `DesignRunStatus`, `DesignOperationKind` (`initial_build`, `technical_repair`, `visual_refinement`, `derived_page`). |
| `docs/simplify-design-pipeline-implementation-plan.md` | The native path: STEP 1 read-only design direction, STEP 2 integrated build; removes the specialist phase machine. |

This pipeline is a chained autonomous flow. Inside one run, Ada selects the
design direction, implements it, validates it, and only then shows the owner a
finished candidate. Design decisions are made without an owner gate, and the
owner can only react at the end.

### 3.3 Review, feedback, acceptance (exists, partially reusable)

| Component | Behavior today |
|---|---|
| `IncubationStatus` (`core/incubation_contracts.py`) | `collecting -> researching -> ready_to_build -> building -> ready_for_feedback -> accepted -> provisioning -> provisioned`. |
| `incubations.feedback()` | Owner feedback kinds (`fits`, `small_improvements`, `redesign`); `redesign` reopens collecting. |
| `incubations.accept()` | Binds `run_id` + `candidate_sha`; requires `ready_for_feedback`; freezes a customer context snapshot. |
| `incubations.provision()` / `activate()` | Freeze a provisioning bundle; local customer config/data/media handoff; SEO provisioning; activation. |

The feedback vocabulary is a coarse end-of-run categorization. It cannot
express "build the services page next" or "apply this bounded change to the
approved direction". There is one end-of-pipeline review moment, not a
conversational sequence of gated operations.

### 3.4 Existing owner-action and approval system (exists, reuse)

| Component | Behavior today |
|---|---|
| `application/actions.py` (`OwnerActionService`) | Durable owner actions with states `open, started, waiting, completed, snoozed, dismissed, stale`, dedupe keys, job/artifact/conversation links, reconcile-after-work. |
| `application/approvals.py` (`ApprovalService`) | Artifact-hash-bound approvals. |
| Home projection (`application/home.py`) | `Needs you` / `Ada suggests` / `Ada is handling`. |
| `web/workspace.py` | Existing tool surface: chat, intake confirm, design start, runs, review, drafts, versions restore, media, source, analytics. |

This system already implements exactly the recommendation/approval semantics
HelloAda needs. The design flow currently has a **second, parallel approval
vocabulary** (feedback kinds + accept/provision). That duplication is the
simplicity problem to remove.

### 3.5 What to keep and what blocks the target

| Keep | Why |
|---|---|
| Durable conversation + revisioned intake + hash-bound confirmation | Correct safety and resumability already. |
| Idempotent build reservations and durable jobs | Required for reliable retries. |
| Immutable candidates, exact-SHA isolation, host build evidence | Non-negotiable design safety. |
| Owner action / approval system | Reuse as the single recommendation mechanism. |
| Existing routes as thin adapters | Compatibility while logic stays in services. |

| Blocking | Fix in this plan |
|---|---|
| Autonomous run decides direction + build in one chain | Split at the direction gate; each stage waits for an owner action (§5.4). |
| End-of-run feedback categories only | Typed recommendations that name a bounded next operation (§5.3). |
| Two approval vocabularies | One mechanism: recommendation = owner action; acceptance starts the operation (§5.3-5.4). |
| Pipeline only reachable through one hardcoded first-page action | Tool catalog callable from both interfaces with state gating (§4). |
| Infrastructure only at end of pipeline | Bootstrap at website creation (§8). |
| Preview is a staged internal artifact | The Worker URL is the website; the preview is that site (§8.4). |
| `provision` monolith | Custom-domain launch gate + independent integrations (§9). |

## 4. Target architecture: tools, not an assembly line

### 4.1 One rule

**Every capability is an application-service tool. Interfaces are thin. Ada
calls tools by name. The same tool catalog is available from both HelloAda and
the customer WebsiteWorkspace, gated by website state.**

```text
HelloAda (minimal UI)  ─┐
                        ├─►  website tools (application services)  ─►  durable operations
WebsiteWorkspace (full) ─┘         │
                                   ├─► design pipeline (planner/build/validate)
                                   ├─► Payload/content/media
                                   ├─► Cloudflare/GitHub/D1/R2
                                   └─► SEO/analytics/launch integrations
```

Neither interface owns pipeline logic. Neither interface may reach a provider
adapter directly. HTTP/MCP adapters translate and authorize; services decide.

### 4.2 Tool catalog

Names are indicative; align with existing service naming when implementing.
Every tool is durable where it mutates state.

| Tool | Service behind it | Effect | Gate |
|---|---|---|---|
| `intake.advise` | `DesignIntakeService` + advice job | Conversation turn; may update the draft | website in `intake` |
| `intake.confirm` | `DesignIntakeService.confirm()` | Freezes revision + hash | draft ready |
| `research.run` | existing research service | Read-only evidence | intake started |
| `design.direction` | native planner step (read-only) | Produces a readable direction; **no source mutation** | intake confirmed |
| `design.build` | `DesignLabService` / `DesignService` | First candidate: shell + homepage from the approved direction | direction approved |
| `design.change` | refinement operation | Bounded change to the current revision | approved direction; current revision exists |
| `design.page` | derived-page operation | Builds one additional page from the frozen `required_pages`, reusing the direction | direction approved; page in required inventory |
| `design.deploy` | Cloudflare deploy step | Publishes a completed revision to the website Worker | operation produced a revision |
| `version.restore` | existing versions restore | Rollback to a previous revision | revision history exists |
| `launch.integrate` | SEO/launch services | Domain + GA4/GSC/CrawlSEO/email/indexing | payment + domain gate satisfied |

`design.deploy` may run automatically at the end of a successful build/change
because the user asked for that change and the Worker URL *is* the website.
The approval is the originating owner action, not a second deploy prompt.

### 4.3 Tool availability is state-gated

Each tool declares preconditions and refuses with a named reason:

```text
design.build -> refused: direction_not_approved
design.page  -> refused: page_not_in_required_inventory
design.change-> refused: no_current_revision
launch.integrate -> refused: domain_not_connected
```

Refusals are deterministic, single-sentence, and testable. No silent fallbacks.

### 4.4 Interface parity requirement

The same operation must be reachable from both interfaces by calling the same
service. A test must prove parity for at least `design.change` and
`version.restore`: the operation initiated from HelloAda and the operation
initiated from WebsiteWorkspace produce identical recorded provenance, state
transitions, and revision output.

Difference between interfaces is presentation and scope only:

| | HelloAda | WebsiteWorkspace |
|---|---|---|
| Purpose | portfolio + intake + minimal build room | full website management |
| Tools exposed | intake, direction, build, change, launch entry | all tools + content/media/settings/diagnostics |
| Approvals shown | inline recommendations under Ada's message | full approval inbox + history |

## 5. The gated design loop (the required intake-logic change)

### 5.1 Behavior contract: do → report → recommend → wait

After **every completed operation** Ada must:

1. **Report** what was done in plain language, with the visible result
   (preview revision, page built, change applied).
2. **Recommend** the possible next steps as bounded, concrete proposals
   ("Rebuild the hero around the studio photo", "Build the services page
   next").
3. **Wait.** Ada does not start the next design stage on her own.

The owner then approves a recommendation, rejects it, or writes their own
request. Any of the three becomes the next operation with recorded provenance.

This replaces the current autonomous decision chain. Ada no longer decides
"what the site becomes next" alone; she proposes and the owner agrees. This is
the single most important behavioral change in this plan.

### 5.2 When Ada executes directly vs recommends first

Direct execution is allowed only when all are true:

- the owner explicitly asked for this exact bounded change;
- the change stays inside the current approved direction (copy, styling,
  section content, a page already in the required inventory);
- no structural decision, new page, or direction change is introduced;
- the site is not at the launch gate.

Ada must recommend first (never execute silently) when:

- the change alters direction, structure, navigation model, or scope;
- the request adds pages or features not in the confirmed intake;
- the action reaches outside the website (domain, integrations, email,
  payment, publication);
- the request is ambiguous about intent or scope.

This policy lives in Ada's tool/prompt policy. The host enforces the state
gates; the policy governs which tool Ada chooses within what is allowed.

### 5.3 Recommendation contract

Reuse the existing owner-action system; do not create a second one.

```text
Recommendation / owner action
  id
  website_id
  title                 owner-facing, one sentence
  reason                observable evidence ("your brief asks for 4 pages;
                        only the homepage exists")
  proposed_tool         design.build | design.change | design.page | ...
  proposed_scope        bounded input for that tool
  bound_state_hash      intake revision + approved direction + current revision
  state                 open | started | completed | dismissed | stale
  links                 conversation, artifact, operation, revision
```

Accepting a recommendation:

1. transitions the action to `started`;
2. creates the operation with `source_action_id` recorded;
3. the operation validates its gate against the bound state;
4. on success, records the resulting revision and completes the action.

Rejecting, snoozing, or dismissing uses the existing action transitions.
Every operation therefore has one of two origins — an owner message or an
accepted recommendation — both recorded. That is the debuggability backbone.

### 5.4 Direction gate: the pipeline split

The current pipeline is split at its first decision point:

```text
intake confirmed
  -> Ada runs design.direction (read-only)
  -> Ada reports the direction and recommends: "Build the homepage this way?"
  -> owner approves or adjusts
  -> Ada runs design.build from the approved direction
  -> Ada reports the candidate and recommends next steps
  -> owner approves / adjusts / accepts
```

Rules:

- `design.direction` never mutates source and never produces a candidate.
- `design.build` refuses without an approved direction bound to the current
  intake revision.
- The direction artifact is durable, human-readable, and shown in full; it is
  not a hidden phase of a run.
- If the owner changes the intake after direction approval, the direction is
  invalidated (`direction_outdated`) and must be re-proposed.

The native two-step path from the simplify plan remains the execution truth
inside `design.direction` and `design.build`; this plan only adds the owner
gate between them and the report/recommend behavior after them.

### 5.5 Worked flow

```text
Owner: "I run a ceramics studio."
Ada:   advice turns ... draft ready
Owner: confirm
Ada:   (tool: design.direction) "Here is the direction: warm editorial,
        portrait-led, 4 sections ... The homepage would open with the studio
        photo and the kiln story."
       Recommendation: [Build the homepage this way]
Owner: accept
Ada:   (tool: design.build) builds candidate, host build + runtime evidence,
       deploys to the Worker, preview updates
       "Homepage is live in your preview. Next steps I suggest: ..."
       Recommendations:
         [Build the services page] [Soften the hero typography] [Nothing yet]
Owner: [Soften the hero typography]
Ada:   (tool: design.change) applies, preview updates, reports, recommends next
```

## 6. Simple state machines

### 6.1 Owner-facing website phase

```text
intake -> designing -> live
              |
              +-> needs_attention
```

- `intake`: conversation + confirmation.
- `designing`: direction/build/change operations in progress or awaiting an
  owner decision.
- `live`: launched (custom domain connected).
- `needs_attention`: an operation failed and needs an owner or operator action.

No other vocabulary appears in either owner-facing UI.

### 6.2 Operation status

```text
queued -> running -> done
             |
             +-> failed
             +-> cancelled
```

One status model for every tool invocation. `failed` always carries a named
reason and a retry path.

### 6.3 Mapping internal statuses

Internal detail stays internal; the projection collapses it:

| Internal | Owner-facing |
|---|---|
| run `created/assessing_intake/planning/building/validating` | `designing` + one progress line |
| run `ready_for_review`, candidate ready | `designing` + preview updated |
| run `needs_repair` | `designing` or `needs_attention` if unrecoverable |
| run `failed/interrupted` | `needs_attention` |
| incubation `building/ready_for_feedback` | `designing` |
| incubation `accepted/provisioning/provisioned` | `designing` until domain, then `live` |

### 6.4 Debuggability requirements

- Every operation has an ID, an origin (message or accepted recommendation),
  an input hash, a status trail, and a bounded outcome.
- Every state transition is written once to the existing journal/activity
  stream with the operation ID.
- One status line in the owner UI; full detail behind `More details` in the
  full workspace only.
- Failures name the missing precondition (`direction_not_approved`), never
  "something went wrong".
- Re-running a failed operation with the same idempotency key returns the same
  result instead of duplicating work.

## 7. Interfaces

### 7.1 HelloAda (minimal)

Views: sign-in, portfolio, create website, intake/build room (chat + live
preview + one status line + inline recommendations), launch entry.

Must not contain: run/phase/provider vocabulary, separate accept/provision
buttons, a second CMS, a second recommendation system, a neural dashboard.

### 7.2 WebsiteWorkspace (full)

The existing Payload/Atelier workspace is the only full admin surface. It
exposes the complete tool catalog with the same services and the same
recommendation/approval records, plus content, media, settings, diagnostics.

Reference files (do not duplicate or fork):

- `/ATELIER/atelier-harmonie-headless/src/components/admin/WebsiteWorkspace.tsx`
- `/ATELIER/atelier-harmonie-headless/src/components/admin/WebsiteWorkspaceServer.tsx`

### 7.3 No duplicated pipeline logic

If a behavior is needed in both interfaces it belongs in a service, once.
Frontends may differ in layout and disclosure, not in logic.

## 8. First-connection bootstrap

### 8.1 Decision

Infrastructure is created when the website project is created, not when a
candidate is accepted. The owner designs against the real site from the first
preview.

### 8.2 Resources

1. GitHub repository from the canonical Next/React/Payload shell.
2. Cloudflare Worker + `workers.dev` URL.
3. D1 database.
4. R2 media storage.
5. Core runtime secrets, generated server-side.
6. Payload migrations and initial schema.
7. Payload owner identity/session binding.
8. Site-agent tenant registration.
9. Initial shell deployment.
10. Durable resource receipts and public URLs.

Reuse existing provider adapters. Credential values never enter a repository,
browser response, log, project config, or model prompt.

### 8.3 Bootstrap as a durable saga

```text
requested -> creating_repository -> creating_worker -> creating_d1
-> creating_r2 -> configuring_secrets -> migrating_payload
-> registering_site -> deploying_shell -> verifying_runtime -> ready
```

Each step stores external resource IDs, status, timestamps, a bounded
diagnostic, and is idempotent on retry. Abandoned projects have a later,
explicit cleanup policy; active state is never deleted silently.

### 8.4 Preview

The Worker URL is the website. The preview shows the actual hosted site, not a
local staged artifact. Pre-launch behavior: `noindex`, no real outbound email,
payment, or webhooks; Payload Admin stays authenticated; the public site may be
viewable at the Worker URL. If direct embedding is not possible, use a
server-side proxy or open-preview link — never a second rendered site.

## 9. Launch gate (custom domain + payment)

Before launch: website, Payload admin, D1, R2, design operations, and preview
all work; external integrations remain inactive.

After the owner completes payment + domain:

1. connect/verify the domain;
2. attach it to the existing Worker;
3. enable GA4, GSC, CrawlSEO;
4. enable email/webhooks/forms;
5. switch canonical URLs, robots, sitemap, and indexing;
6. record one independent, retryable receipt per integration.

A failed GSC verification must not take down the site or roll back the domain.

## 10. Revisions and rollback

One model:

```text
make a change -> preview it -> use it -> roll back if needed
```

Do not introduce product-level `candidate_sha` / `accepted_sha` / `live_sha`.
A revision record contains:

- website ID, operation origin, user-facing summary;
- source/deployment identity (internally);
- Payload content and media revision references;
- build/runtime evidence;
- rollback relationship and status.

Git history alone cannot restore a D1 content change or an R2 deletion;
rollback must cover code, content, and media, and must report honestly when a
piece cannot be restored.

## 11. Authentication and handoff

- Central Payload-backed authentication for HelloAda. No new auth provider.
- Website authorization is membership-based; never trust a website ID alone.
- Each customer site keeps its isolated Payload identity.
- The HelloAda to WebsiteWorkspace transition uses a short-lived, one-time,
  scoped handoff assertion that establishes a local site session. Never a
  password, never a long-lived token in a URL, never replayable.
- Site-agent, GitHub, Cloudflare, Google, and CrawlSEO credentials stay
  server-side.

## 12. Data model (minimal)

Keep it small; extend only when a feature needs it.

```text
user (central Payload)
membership (user_id, website_id, role)
website (id, name, owner_id, incubation_id, tenant_id,
         phase: intake|designing|live|needs_attention,
         worker_url, admin_url, domain_status, created/updated)
bootstrap_job (website_id, step, status, resource_receipts, retries)
operation (id, website_id, tool, origin, status, input_hash,
           source_action_id?, revision_id?, reason?, created/updated)
revision (id, website_id, operation_id, source_identity,
          content_ref, media_refs, evidence, status, rollback_of?)
recommendation = owner action row (existing table)
```

The intake draft/revision tables and design run tables already exist and are
reused. Do not rename or duplicate them; add the website/operation projection
over them.

## 13. Implementation phases

### Phase 0 — Inventory and contracts
- Locate the HelloAda frontend repository (there is currently no deployable
  `helloada.app` app; `frontend/README.md` is documentation only).
- Confirm central Payload auth boundary and WebsiteWorkspace session behavior.
- Write the tool catalog and gate rules as typed contracts.
- Add failing tests for: gate refusals, recommendation→operation provenance,
  interface parity.

**Exit:** contracts and tests exist; no speculative frontend created.

### Phase 1 — Recommendation + operation spine
- Wire recommendations to the existing owner-action system.
- Add `operation` record with origin and input hash; connect it to existing
  design runs and chat jobs.
- Implement report→recommend→wait behavior for one real path.

**Exit:** an accepted recommendation creates exactly one operation with
recorded provenance; replay is idempotent.

### Phase 2 — Direction gate
- Split the native pipeline: `design.direction` (read-only artifact) and
  `design.build` consuming an approved direction.
- Enforce `direction_not_approved` and `direction_outdated` gates.
- Update intake-lab/executor paths so no flow builds without the gate.

**Exit:** a run cannot reach source mutation without an approved direction
bound to the current intake revision.

### Phase 3 — Minimal HelloAda build room
- Portfolio, create website, intake chat, live preview, inline
  recommendations, one status line.
- Connect to existing intake services; embed the real Worker site.
- Remove internal vocabulary from this surface.

**Exit:** an owner can complete intake, approve a direction, receive a build,
ask for a change, and see updates without opening the full admin.

### Phase 4 — Bootstrap + handoff
- Durable bootstrap saga; resource receipts; Worker URL available at creation.
- Seamless one-time handoff into WebsiteWorkspace.
- Portfolio card transitions from intake to `Manage this website`.

**Exit:** a new project reaches a working Worker URL and clean handoff with no
manual provisioning step and no second login.

### Phase 5 — Launch gate + rollback
- Payment/domain gate; independent GA4/GSC/CrawlSEO/email/indexing steps.
- Revision history and rollback covering code/content/media.

**Exit:** no launch integration activates before the gate; rollback restores a
previous website state or reports what cannot be restored.

### Phase 6 — Hardening
- Cleanup/reconciliation for abandoned bootstraps; rate limits; quotas; audit
  events; live smoke tests on a non-production namespace.

## 14. Required tests

**Gates**
- `design.build` refuses without approved direction; `design.change` refuses
  without a current revision; `launch.integrate` refuses without domain gate.
- Each refusal names the missing precondition.

**Recommendations**
- accepting creates one operation with `source_action_id`;
- dismissing/snoozing never creates operations;
- a recommendation bound to an old revision goes `stale` after a newer one.

**Pipeline split**
- direction run performs no source mutation;
- build run pins the approved direction hash;
- changing the intake invalidates the direction.

**Interface parity**
- `design.change` and `version.restore` initiated from both interfaces record
  identical provenance, transitions, and output revisions.

**Bootstrap**
- duplicate creates return the same project/job;
- every step retryable and idempotent; receipts contain no secrets;
- partial failure leaves a resumable diagnostic.

**Launch**
- integrations blocked before gate; independently retryable after;
- failed verification never takes down the site.

**Rollback**
- code, content, and media restore honored or reported;
- rollback does not touch another website or account.

## 15. Verification and browser checks

Site-agent repository:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
```

Then inspect the real surfaces, not just tests:

1. HelloAda: sign-in, portfolio, create website.
2. Bootstrap progress until the Worker URL works.
3. Intake conversation and confirmation.
4. Direction report + approve.
5. First build + preview updated at the Worker URL.
6. A bounded change via recommendation.
7. Handoff into WebsiteWorkspace without a second login.
8. Portfolio card as `Manage this website`.
9. Launch gate blocks integrations; enabling them is resumable.
10. Rollback to a previous revision.

## 16. Coding-AI instructions

Before editing:

1. Read `AGENTS.md`, the simplify-plan, and this document.
2. State the first broken boundary in the real request path.
3. Inspect existing services and tests before adding abstractions.
4. Start with a focused failing test or reproducible request.
5. State which layer the change belongs to: tool/service, interface, bootstrap,
   or launch.

Never:

- create a second admin/workspace or a second recommendation system;
- add a new auth provider;
- create a staging site or duplicate data plane;
- put business logic in route functions;
- expose run/phase/SHA/provider vocabulary to owners;
- let Ada advance a design stage without an owner action;
- activate launch integrations before the domain/payment gate;
- use Atelier production as a test tenant;
- commit credentials, databases, caches, screenshots, or build output;
- claim completion without inspecting the real owner surfaces.

Complete only when:

- one account manages multiple websites;
- each website is bootstrapped on Cloudflare at creation;
- HelloAda runs intake, shows the real site, and supports gated operations;
- the existing WebsiteWorkspace is the only full admin;
- handoff is seamless;
- recommendations are the single approval mechanism;
- the launch gate controls all external integrations;
- revision history and rollback work;
- all existing design-pipeline and deployment safety rules remain intact.
