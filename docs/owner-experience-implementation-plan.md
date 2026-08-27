# Owner Experience And Capability Foundation

**Status:** Approved direction, implementation not started

**Purpose:** Track the product and architecture work required to make Ada a
calm, proactive assistant for non-technical small-business owners while
preserving safe approvals and preparing narrow extension points for future MCP
providers.

This is the active implementation plan for the owner experience. `PLAN.md`
remains the historical project development log.

## How To Use This Plan

- Work through phases in order unless a phase explicitly says it can overlap.
- Check an item only after its implementation and focused tests pass.
- Complete each phase's acceptance criteria before starting dependent work.
- Keep public API paths stable while moving workflows behind application
  services.
- Record material product or architecture changes in the Decision Log.
- Do not mark the overall plan complete until the full verification matrix and
  live-instance smoke test pass.

## Recorded Baseline

At plan creation on 2026-08-26:

- The repository branch is `master`.
- The worktree contains uncommitted changes in:
  - `src/site_agent/core/memory.py`
  - `src/site_agent/web/journal.py`
  - `src/site_agent/web/server.py`
  - `src/site_agent/web/static/admin.html`
  - `tests/test_web.py`
- The uncommitted work includes verified Pelican published-preview fixes and a
  partial conversation-archive/admin-UI prototype.
- SQLite migration 9 (`conversations.archived_ts`) has run on the live
  OceanicVibes instance. It is now persisted behavior and must not be removed
  or rewritten. New schema changes start at migration 10 or later.
- The last full verification completed with 238 tests passing, `compileall`
  passing, and a wheel building successfully.
- The manually managed OceanicVibes admin process was restarted against the
  current working tree. Future rollout work must account for that live state.

## Product Thesis

Ada is the operating layer for a small business owner, not a technical
dashboard. The normal interface shows only:

1. What needs the owner's attention.
2. What Ada recommends doing next.
3. A short assurance that Ada is handling everything else.

The owner should not need to understand SEO, GA4, GSC, repositories, drafts,
merge branches, build jobs, provider payloads, or MCP tools.

Technical and diagnostic information remains available under `More details`
without competing with the default experience.

## Agreed Product Decisions

- Keep one site per runtime instance. Contracts remain site-neutral; do not add
  multi-tenancy yet.
- Keep the right-side Ada conversation panel on desktop.
- Use a bright, minimal Ada interface. Customer colors appear only as accents.
- Home is an action inbox, not a weekly-report dashboard.
- Home separates required owner decisions from optional recommendations.
- A recommendation starts a focused Ada conversation with its context already
  attached.
- Ada asks at most one necessary follow-up before preparing work.
- All site production changes remain approval-gated.
- External mutations, including future social publishing, require explicit
  owner approval by default.
- Normal navigation uses owner language: `Home`, `Website`, `Review`, `Photos`,
  and `More details`.
- The default UI does not expose SEO, strategist, draft, merge, build, LLM, GA4,
  GSC, or provider terminology.
- Conversation actions operate on one selected conversation at a time.
- Conversations support archive, restore, and permanent deletion.
- Permanent deletion scrubs message content while retaining a minimal durable
  job/conversation tombstone.
- Website versions remain reversible. External actions have provider-specific
  history and must not pretend to be restorable website versions.
- Future social and advanced search integrations plug into narrow capability
  contracts. Do not build a universal plugin framework.

## Target Owner Information Architecture

### Home

Home answers one question first: **Does the owner need to do anything?**

Sections, in order:

1. `Needs you`
2. `Ada suggests`
3. `Ada is handling`
4. Optional concise business pulse when a signal is genuinely useful

Rules:

- Show no more than four required actions by default.
- Show no more than three recommendations.
- The navigation badge counts only required actions.
- Each item has one short title, one explanatory sentence, and one primary
  action.
- Optional explanation is hidden behind `Why this matters`.
- Recommendations support `Not now` and `Dismiss`.
- `Not now` snoozes for seven days by default.
- Reports never appear as approval tasks unless they contain a real owner
  decision.
- When nothing needs attention, show `Everything is handled.`

Example:

```text
Needs you

Course dates may be out of date
Ada needs the new dates before updating your website.
[Tell Ada the dates]

Review the new journal page
Nothing changes until you approve it.
[Review change]

Ada suggests

Write about equalization anxiety
People are showing interest in this subject.
[Ask Ada to draft it] [Not now]

Ada is handling

Checking your website and preparing this week's ideas.
```

### Website

- Present customer-facing content in plain business language.
- Keep direct content editing available, but do not expose repository paths or
  JSON terminology.
- Use `Save changes`, not `Save & publish to GitHub`.
- Route structural or visual changes through Ada and the Review flow.

### Review

Review is a universal approval inbox, not only a website Design tab.

Supported artifact views:

- Website change: rendered iframe preview.
- Article: rendered article preview.
- Social post: future platform-style preview.
- Business information update: clear before-and-after values.
- Search-derived improvement: proposed owner-facing website outcome.

Owner language:

- `Publish this change`, not `Approve`.
- `Keep current`, not `Reject`.
- `Preview this version`, then `Bring this version back` after review.
- Raw operations and provider details live under `More details`.

### Photos

- Keep upload and existing-photo reuse.
- Remove Cloudflare R2 terminology from the default copy.
- Explain outcomes: `Upload a photo` and `Photos already on your website`.

### More Details

This is progressive disclosure for owners who need detail or support staff who
are diagnosing a problem.

It may contain:

- Full weekly summaries.
- Visitor trends and how people found the site.
- Ada's recent activity.
- Scheduled work.
- Website health.
- Provider availability.
- Build and deployment diagnostics.
- Detailed version metadata.
- LLM cost and technical identifiers.

## Target Dependency Direction

```text
HTTP or MCP adapter
  -> application service
  -> typed owner-action / approval contract
  -> narrow provider or existing adapter
  -> persisted state
```

Rules:

- FastAPI routes translate HTTP and sessions only.
- MCP adapters call application services, never route functions.
- Providers never access `Memory.conn` directly.
- Brain policy can propose actions but cannot publish directly.
- Remote tool metadata is not trusted to classify side effects.
- Application policy owns effect classification and approval requirements.

## Domain Contracts

Define typed contracts before redesigning the UI.

### OwnerAction

Represents something Ada needs the owner to decide or something Ada recommends.

Required concepts:

- Stable action ID.
- Namespaced capability ID.
- Provider ID.
- Owner-facing title.
- Short owner-facing summary.
- Owner-facing action label.
- Priority: urgent, normal, or optional.
- Requirement: owner decision, owner information, or suggestion.
- State: open, started, waiting, completed, snoozed, dismissed, or stale.
- Source reference and deduplication key.
- Created and updated timestamps.
- Optional snooze deadline.
- Optional conversation, artifact, approval, and draft references.
- Versioned validated payload with no credentials.

### Artifact

Represents prepared work the owner can inspect.

Initial artifact kinds:

- `site_change`
- `article`
- `business_information`
- `social_post` reserved for the future provider

Required concepts:

- Immutable artifact ID and revision.
- Artifact kind.
- Owner-facing title and summary.
- Preview data or renderer reference.
- Provider and capability IDs.
- Source action ID.
- Content hash.
- Created timestamp.

### ApprovalRequest

Represents explicit permission for a known immutable side effect.

Required concepts:

- Approval ID.
- Artifact ID and immutable content hash.
- Effect class: proposal, site mutation, or external mutation.
- Owner-facing action label.
- Provider ID.
- Status: pending, approved, declined, expired, or failed.
- Decision timestamp and optional owner feedback.
- Execution job ID and provider receipt ID.

If the artifact changes after approval, create a new approval request.

### Capability

Describes one narrow operation. It is not a universal plugin object.

Initial identifiers:

- `content.article.prepare`
- `site.change.propose`
- `site.business_information.refresh`
- `search.insights.read`
- `social.post.prepare`
- `social.post.publish`

Required concepts:

- Stable namespaced identifier.
- Provider ID.
- Effect class: read, proposal, or external mutation.
- Availability: available, degraded, or unavailable.
- Input contract.
- Result contract.
- Timeout and result-size limits.
- Explicit approval requirement.

### ProviderReceipt

Records an external execution result without leaking credentials.

Required concepts:

- Receipt ID.
- Provider and capability IDs.
- Approval and action IDs.
- Idempotency key.
- External object ID and safe URL when available.
- Success, failure, or uncertain status.
- Safe provider message and timestamps.

## Persistence Direction

Do not force future external approvals into website-specific drafts.

Planned persisted concepts:

- `owner_actions`
- `artifacts`
- `approval_requests`
- `provider_receipts`
- conversation `deleted_ts` tombstone state

Migration rules:

- Preserve schema migration 9 as already applied.
- Add new schema changes only through migration 10 or later.
- Keep existing drafts and publishes readable.
- Introduce compatibility facades so existing draft/version endpoints remain
  stable during migration.
- Add indexes for action state, approval state, provider reference, and
  conversation visibility.
- Store structured payloads as versioned JSON only after validation.
- Never persist provider credentials, access tokens, or unredacted remote
  errors.

## Application Services

Create a small application workflow layer. Do not add a dependency-injection
framework.

### HomeService

Responsibilities:

- Merge required owner input, pending approvals, and optional recommendations.
- Rank required actions above suggestions.
- Exclude reports and technical jobs from the action count.
- Limit and deduplicate visible items.
- Produce one concise `Ada is handling` status.
- Return a typed/documented Home result for HTTP and future clients.

### OwnerActionService

Responsibilities:

- Create and deduplicate action candidates.
- Start an action.
- Attach a focused conversation with source context.
- Snooze, dismiss, complete, and expire actions.
- Reconcile actions when related drafts, approvals, or jobs change.
- Enforce provider availability and effect policy.

### ApprovalService

Responsibilities:

- Create immutable approval requests from artifacts.
- Return renderer-safe preview information.
- Approve or decline with optional feedback.
- Dispatch approved effects through the correct narrow provider.
- Preserve current site-draft approval behavior through a compatibility layer.
- Reject stale approvals whose artifact hash has changed.

### ConversationService

Responsibilities:

- List active or archived conversations.
- Archive one conversation.
- Restore one conversation.
- Permanently delete one conversation's content.
- Block archive/delete while a linked job is queued or running.
- Preserve minimal job/conversation tombstones after permanent deletion.
- Return explicit diagnostics containing conversation and job IDs.

## Provider And MCP Strategy

Do not implement automatic module loading or arbitrary MCP tool discovery.

For each real integration:

1. Define one narrow protocol.
2. Add a fake-provider conformance test.
3. Implement the provider adapter.
4. Register it explicitly in runtime composition.
5. Translate provider errors into safe application errors.
6. Expose capability availability through `More details`.

### Future Social Flow

Before a social publisher is connected:

1. Ada may recommend `Prepare a social post`.
2. The owner starts a focused conversation.
3. Ada prepares a `social_post` artifact.
4. Review renders the prepared copy.
5. The owner can retain or copy the prepared work.

After an MCP social publisher is connected:

1. The same Home action remains unchanged.
2. Review renders a provider-specific post preview.
3. The final action becomes `Publish to <channel>`.
4. Explicit approval binds to the immutable post content.
5. The provider publishes with an idempotency key.
6. Ada stores a safe receipt and external post reference.

### Future Search Analysis Flow

1. A read-only provider returns normalized findings.
2. Ada converts important findings into owner-language action candidates.
3. The default UI says what customers are doing and what Ada recommends.
4. Raw ranking, query, crawl, and provider detail remains under `More details`.
5. Any resulting site mutation creates an artifact and approval request.

## Implementation Phases

### Phase 0: Stabilize The Baseline

- [ ] Review the full current diff and classify every hunk as published-preview
      fix, conversation prototype, UI cleanup, or unrelated work.
- [ ] Preserve the verified Pelican `articles.html` listing and generated-output
      preview behavior.
- [ ] Preserve migration 9 and its live compatibility.
- [ ] Remove or supersede the bulk `Clear past` UI/API before building the final
      per-conversation lifecycle.
- [ ] Confirm the live and test databases migrate cleanly from schema 8 and 9.
- [ ] Run focused preview, journal, conversation, and version tests.
- [ ] Run the full test suite, `compileall`, and wheel build.
- [ ] Record the resulting clean baseline in this document.

Acceptance criteria:

- Existing published-preview behavior remains intact.
- No conversation or job data is lost.
- The baseline passes all repository verification commands.
- The next phase starts from a diff whose intent is understood file by file.

### Phase 1: Typed Contracts And Persistence

- [ ] Add typed `OwnerAction`, `Artifact`, `ApprovalRequest`, `Capability`, and
      `ProviderReceipt` contracts.
- [ ] Document effect classes and state transitions.
- [ ] Add schema migration 10+ for the minimum required persistence.
- [ ] Add Memory methods for the new records; application services must not use
      `Memory.conn` directly.
- [ ] Add transition guards for completed, dismissed, stale, and approved state.
- [ ] Add redaction rules for payloads and provider errors.
- [ ] Add migration tests from schema 8 and the deployed schema 9.
- [ ] Add round-trip and invalid-transition tests.

Acceptance criteria:

- Contracts are provider-neutral and do not import FastAPI.
- Every persisted state transition is traceable by action, approval, provider,
  conversation, draft, or job ID.
- Existing draft and publish records remain readable.

### Phase 2: Application Workflow Layer

- [ ] Add `HomeService`.
- [ ] Add `OwnerActionService`.
- [ ] Add `ApprovalService` with a website-draft compatibility adapter.
- [ ] Add `ConversationService`.
- [ ] Compose services through the existing `Runtime` boundary.
- [ ] Move new business workflows out of route handlers.
- [ ] Add service-level tests before adding new HTTP routes.
- [ ] Update `docs/architecture.md` with the application workflow layer.

Acceptance criteria:

- HTTP routes are thin session/transport adapters.
- Services can be called directly by tests and future MCP adapters.
- No provider calls a route or accesses `Memory.conn`.

### Phase 3: Persistent Proactive Actions

- [ ] Update strategist output from free-form cards to validated action
      candidates.
- [ ] Keep the weekly report as a downstream summary, not the source of Home
      actions.
- [ ] Deduplicate recommendations across scheduled runs.
- [ ] Add open, started, waiting, completed, snoozed, dismissed, and stale
      lifecycle behavior.
- [ ] Add seven-day `Not now` behavior.
- [ ] Add permanent `Dismiss` behavior unless a materially new source signal
      creates a distinct action.
- [ ] Add focused-conversation context when an action starts.
- [ ] Ensure Ada asks no more than one required follow-up before preparation.
- [ ] Add configured site-specific freshness checks for business information;
      do not hardcode OceanicVibes course fields in generic code.
- [ ] Add action reconciliation when a related draft or job completes.

Acceptance criteria:

- Recommendations do not reappear immediately after snooze or dismissal.
- Starting an action does not require the owner to repeat its context.
- Optional suggestions never inflate the required-action badge.

### Phase 4: Owner Home API And UI

- [ ] Add a documented `/api/home` response backed by `HomeService`.
- [ ] Replace the report-first Overview with Home.
- [ ] Render `Needs you`, `Ada suggests`, and `Ada is handling` in that order.
- [ ] Limit default action counts and add clear empty states.
- [ ] Add `Why this matters` progressive disclosure.
- [ ] Move full reports, detailed visitors, schedule, health, spend, and activity
      into `More details`.
- [ ] Use plain owner-facing labels throughout.
- [ ] Remove technical type tags from default task cards.
- [ ] Add loading, error, and provider-unavailable states that explain the next
      owner action.
- [ ] Add keyboard and screen-reader tests for action controls.

Acceptance criteria:

- A non-technical owner can identify required work within five seconds.
- Home contains no implementation jargon.
- The largest visual emphasis belongs to required owner action.
- The full weekly summary remains accessible but is not the default content
  block.

### Phase 5: Universal Review And Approval UI

- [ ] Rename the owner-facing Design area to `Review`.
- [ ] Preserve the internal Design iframe flow for site artifacts.
- [ ] Add a pending-approval queue.
- [ ] Add artifact renderer boundaries.
- [ ] Implement website-change, article, and business-information renderers.
- [ ] Reserve the typed renderer path for future social-post previews.
- [ ] Add a focused decision tray containing title, short summary, and effect.
- [ ] Use `Publish this change` and `Keep current` owner language.
- [ ] Replace browser `prompt()` with an accessible optional-feedback dialog.
- [ ] Hide raw operations, paths, provider IDs, and build logs by default.
- [ ] Verify stale artifact hashes cannot be approved.

Acceptance criteria:

- Every mutation has a clear immutable preview and explicit owner action.
- Site changes still use the `/ada/api/review/...` iframe path.
- Build progress appears in chat or `More details`, not beside approval buttons.

### Phase 6: History And Restore Experience

- [ ] Separate generic `Recent work` from reversible `Website versions`.
- [ ] Produce owner-facing publish summaries at write time where possible.
- [ ] Render website versions as a readable timeline.
- [ ] Emphasize the current version without exposing commit IDs.
- [ ] Use `Preview this version` before any restoration approval.
- [ ] Keep `Bring this version back` approval-gated.
- [ ] Put revision IDs, paths, provider receipts, and raw metadata under
      `More details`.
- [ ] Add tests that external actions never receive website restore controls.

Acceptance criteria:

- Owners can understand what changed and when without technical metadata.
- No restore operation changes production before explicit approval.

### Phase 7: Conversation Lifecycle

- [ ] Replace the bulk clear route and control with per-conversation actions.
- [ ] Add archive-one endpoint and service operation.
- [ ] Add archived-conversation listing and restore endpoint.
- [ ] Add permanent-delete endpoint and service operation.
- [ ] Add `deleted_ts` through migration 10+.
- [ ] Block archive and delete when a conversation has queued or running work.
- [ ] On permanent deletion, remove chat messages.
- [ ] Scrub duplicated job message, result, steps, and error content.
- [ ] Preserve minimal job ID, status, and timestamp tombstones.
- [ ] Keep deleted conversations inspectable by ID as explicit tombstones.
- [ ] Add separate confirmation language for archive and permanent deletion.
- [ ] Add conversation action diagnostics with conversation and job IDs.

Acceptance criteria:

- Archive affects exactly one selected conversation.
- Archived conversations can be restored.
- Permanent deletion removes owner/assistant message content.
- Durable jobs remain inspectable without retaining deleted conversation text.

### Phase 8: Bright Minimal Ada Shell

- [ ] Separate Ada's neutral UI tokens from the customer brand theme.
- [ ] Use customer color only for the accent, focus, and meaningful status.
- [ ] Adopt a bright off-white surface, graphite text, and restrained dividers.
- [ ] Reduce decorative cards and gradients.
- [ ] Rename navigation to `Home`, `Website`, `Review`, `Photos`, and
      `More details`.
- [ ] Build a two-row desktop chat header with a full-width conversation
      selector and compact `New chat` / `More` controls.
- [ ] Put Archive and Delete permanently in the selected conversation menu.
- [ ] Ensure flex and grid children use safe shrinking and never overflow.
- [ ] Replace the current mobile behavior that hides chat with an accessible
      chat drawer or panel.
- [ ] Make Review controls wrap cleanly at tablet widths.
- [ ] Add visible keyboard focus and `prefers-reduced-motion` handling.
- [ ] Check desktop, tablet, and mobile screenshots in the live browser panel.

Acceptance criteria:

- Chat controls remain readable without horizontal overflow.
- Chat remains available on mobile.
- Required actions are visually obvious without making the interface noisy.
- Customer branding never overwhelms Ada's product identity.

### Phase 9: Capability Readiness

- [ ] Add an explicit capability registry at runtime composition, limited to
      known narrow providers.
- [ ] Add capability availability and effect classification.
- [ ] Add fake-provider contract tests for one read provider, one proposal
      provider, and one external mutation provider.
- [ ] Add idempotency enforcement for external mutations.
- [ ] Add provider timeout, result-size, and safe-error translation tests.
- [ ] Ensure disconnected providers preserve prepared artifacts and actions.
- [ ] Ensure provider credentials never enter action payloads or API responses.
- [ ] Update `docs/extensions.md` with the proven contracts.
- [ ] Do not enable arbitrary remote MCP tool discovery.

Acceptance criteria:

- A future social or search MCP adapter can call an application service without
  changing Home or Review information architecture.
- External mutations cannot execute without a valid approval bound to an
  immutable artifact.

### Phase 10: Verification And Rollout

- [ ] Run focused service, migration, action, approval, conversation, preview,
      and provider contract tests.
- [ ] Run `.venv/bin/pytest -q`.
- [ ] Run `.venv/bin/python -m compileall -q src`.
- [ ] Run `.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel`.
- [ ] Run `git diff --check`.
- [ ] Verify no credential, database, cache, worktree, screenshot, or generated
      OpenCode configuration is tracked.
- [ ] Restart the OceanicVibes admin process with the instance environment.
- [ ] Verify Home, focused actions, Review, versions, conversations, and
      `More details` through `/ada/`.
- [ ] Verify every iframe CSS/image request keeps the `/ada` mount behavior.
- [ ] Verify no production mutation occurs during preview or before approval.
- [ ] Verify a provider failure is visible, retryable, and non-destructive.
- [ ] Record rollout date, schema version, test count, and live smoke results.

## Verification Matrix

| Area | Required checks |
|---|---|
| Home | ranking, limits, badges, empty state, snooze, dismiss, no jargon |
| Focused actions | context carried into chat, one-question limit, lifecycle reconciliation |
| Review | immutable snapshot, correct renderer, approve, keep current, stale rejection |
| Website preview | generated Pelican pages, nested assets, mount-point URLs, draft state |
| Versions | current marker, preview restore, explicit approval, no external restore |
| Conversations | archive one, restore one, delete one, active-job block, tombstone |
| Providers | availability, timeouts, redaction, idempotency, receipts, diagnostics |
| Responsive UI | desktop sidebar, tablet wrapping, mobile chat access, no overflow |
| Accessibility | labels, focus order, keyboard operation, dialog behavior, reduced motion |
| Compatibility | existing draft, journal, pages, preview, versions, and job APIs |

## Rollout Strategy

- Keep the existing owner UI functional while contracts and services are added.
- Add compatibility adapters around existing drafts and versions before cutting
  the UI over.
- Switch Home only after action lifecycle behavior is durable.
- Switch Review only after website approvals pass both old and new service
  tests.
- Deploy conversation deletion only after content-scrubbing tests prove job
  durability.
- Add real MCP providers only after the internal and fake-provider contracts
  have run in production without changing approval safety.

## Explicit Non-Goals For This Foundation

- Multi-tenant runtime or shared customer database.
- Frontend framework migration.
- Universal plugin base class.
- Automatic Python module loading.
- Arbitrary MCP tool discovery.
- Real social-provider credentials or publishing adapter.
- New advanced search MCP adapter.
- Automatic external publishing without approval.
- Rewriting the scheduler, builder, or site adapter architecture.
- Hardcoding OceanicVibes business fields into generic application services.

## Decision Log

| Date | Decision | Reason |
|---|---|---|
| 2026-08-26 | Create a separate active owner-experience implementation plan | `PLAN.md` is the historical development log |
| 2026-08-26 | Keep one site per runtime instance | Avoid premature multi-tenancy while keeping contracts portable |
| 2026-08-26 | Make Home an action inbox | Owners need decisions and next steps, not a dashboard |
| 2026-08-26 | Start recommendations through focused Ada conversations | Ada retains context and prepares work through the existing durable job flow |
| 2026-08-26 | Use bright neutral Ada UI with customer accents | Separate Ada's product identity from each customer website |
| 2026-08-26 | Support archive and permanent deletion per conversation | Owners need both reversible cleanup and true content removal |
| 2026-08-26 | Preserve minimal tombstones after deletion | Chat jobs must remain inspectable by ID and conversation |
| 2026-08-26 | Use narrow capability contracts for future MCP providers | Keep UI stable and avoid a universal plugin framework |
| 2026-08-26 | Require explicit approval for external mutations | Preserve trust, auditability, and current safety invariants |

## Completion Definition

This plan is complete when a non-technical owner can:

1. Open Home and immediately understand whether Ada needs anything.
2. Start a recommendation without repeating its context.
3. Review any prepared artifact in plain language.
4. Approve or keep the current state with confidence.
5. Understand recent work and restore a website version safely.
6. Archive, restore, or permanently delete one conversation.
7. Access technical detail only when they intentionally open `More details`.

It must also be possible to add a future social or search MCP provider through a
narrow application contract without redesigning Home, bypassing approval, or
teaching the owner provider terminology.
