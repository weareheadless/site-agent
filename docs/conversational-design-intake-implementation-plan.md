# Conversational Design Intake and First-Feedback Implementation Plan

**Status:** Proposed implementation contract

**Date:** 2026-09-02

**Authority:** This plan extends the local Intake Lab defined in
`docs/intake-lab-test-ui-implementation-plan.md`. It changes the Lab from a
JSON-first test harness into a conversational design-intake prototype while
preserving the design lifecycle and production-safety invariants in
`docs/opencode-first-design-pipeline-implementation-plan.md`.

Where this plan conflicts with the Intake Lab plan on intake entry, visible run
status, visual-review severity, or the first-feedback workflow, this plan takes
precedence. The existing media implementation remains governed by
`docs/media-library-and-visual-memory-implementation-plan.md`.

## Executive Decision

Replace the Lab's prompt plus raw `SiteIntake` editor as the primary experience
with a durable conversation in which Ada acts as a web designer and business
ambassador. Ada asks focused questions, advises the owner, records confirmed
facts and reversible assumptions, incorporates owner-uploaded visual
references, and presents a concise intake summary for explicit confirmation.

Every new Lab session starts from `DesignIntakeDraft.empty()`. A configured site
may still provide the isolated build baseline, but it must not prefill the intake
or act as the conversation's business/content reference. A completed
`SiteIntake` is accepted only when explicitly supplied as a fixture or migration
seed.

The target flow is:

```text
owner starts an intake conversation
  -> Ada learns the business, audience, CTA, values, vibe, scope, and constraints
  -> owner optionally uploads 2-5 brand images or visual references
  -> Ada advises on missing decisions and proposes reversible defaults
  -> owner reviews confirmed facts, assumptions, and deferred details
  -> owner explicitly confirms "Build this"
  -> immutable SiteIntake revision is frozen
  -> isolated, non-publishable first design is generated
  -> fast preflight blocks only unacceptable errors
  -> usable candidate is shown within a target of 10 minutes
  -> owner chooses: direction fits, small improvements, or redesign
```

The first design is a conversation artifact, not a publication-ready verdict.
It succeeds when it is coherent, functional, faithful to the confirmed intake,
and safe to show for owner feedback. Missing information is represented as an
assumption or deferred detail, never silently converted into a failure.

## Product Goals

- Make the intake feel like a short strategy session with a capable designer,
  not a long form or JSON schema exercise.
- Produce a useful first design quickly enough to support owner reaction rather
  than attempting automated perfection before the owner sees anything.
- Give Ada enough context to make a distinctive design: business purpose,
  audience, conversion goal, values, vibe, brand colors, imagery, examples,
  content readiness, and constraints.
- Encourage 2-5 representative images without making images mandatory.
- Distinguish images that may be placed on the site from images that are only
  inspiration.
- Preserve every meaningful intake decision with field-level provenance.
- Require explicit owner confirmation before creating a design run.
- Keep optional visual improvements separate from unacceptable blockers.
- Build the application contracts so the same intake service can later move
  from Intake Lab into the owner-facing application without a rewrite.
- Reuse durable media and immutable intake artifacts later without creating a
  GitHub repository or Cloudflare deployment during intake.

## Non-Goals

- Do not create or connect a GitHub repository during intake.
- Do not create a Cloudflare Worker, Pages project, domain, route, or deployment
  during intake.
- Do not provision a new R2 bucket or credentials from the Lab.
- Do not publish, merge, approve, or push a design candidate.
- Do not move Intake Lab into `web/static/admin.html` in this scope.
- Do not add a frontend framework or JavaScript build step to Intake Lab.
- Do not create an open-ended autonomous research agent for intake.
- Do not crawl inspiration websites or import their images in this scope.
- Do not allow inspiration-only images to be copied into generated websites.
- Do not require final copy, final photography, testimonials, prices, exact
  contact destinations, or final brand guidelines before a first design.
- Do not implement scheduled post-launch improvement proposals in this scope.
  Define the future boundary, but leave scheduling and proposal generation for
  a separate implementation.
- Do not remove detailed internal `DesignRunStatus` values from persistence.
  Existing runs are durable and must remain inspectable.

## Locked Product Decisions

### Conversation

- Ada asks one or two high-value questions per turn, not a questionnaire dump.
- Every owner turn is persisted and queued as a durable chat job before the
  advisor is called. Closing or refreshing the browser must not lose it.
- Intake advice runs through an explicit intake job kind, not the general
  website-editor tool loop, and may not inspect or mutate the site repository.
- Ada explains why a decision matters when advising the owner.
- Ada recommends a sensible option when the owner is unsure.
- Ada accepts ordinary language and does not expose contract field names.
- Ada reflects important decisions back to the owner before treating them as
  confirmed.
- Ada may propose reversible defaults, but must label them as assumptions.
- Ada must not invent business facts, claims, credentials, testimonials,
  prices, addresses, opening hours, guarantees, or contact destinations.
- The owner can say "I do not know", "you decide", or "later" for any design
  preference. Ada records an assumption or deferred detail and continues.
- The owner may revise any decision before confirmation.
- Any change after confirmation creates a new immutable intake revision and
  requires a new explicit confirmation before another build.

### Images and visual references

- Prompt the owner to upload approximately 2-5 images that represent the brand
  or desired visual feeling.
- Images are strongly encouraged but optional. No-image intake is valid.
- Each selected image has a usage permission:
  `website`, `inspiration_only`, or `undecided`.
- Each image may also record reference aspects such as `color`, `composition`,
  `photography`, `texture`, `typography`, or `general_vibe`.
- `website` means the owner authorizes direct use when Ada judges that the image
  supports the design. It does not require Ada to place every authorized image.
- `inspiration_only` means the image may influence design decisions but its
  bytes must never be copied into the candidate repository.
- `undecided` images may inform the conversation but must not be copied into the
  candidate until permission changes to `website`.
- Uploading an image does not itself imply direct-use permission.
- Ada asks what the owner likes and dislikes about important references instead
  of blindly copying their palette or composition.
- Dominant colors from media analysis are advisory evidence only. Ada may
  propose a palette from them, but the owner either accepts it or leaves it as
  an explicit assumption.
- Only ready image assets may be used by a build. PDFs stay available as
  business context through the existing media path but do not appear in the
  visual-reference picker in this scope.

### Intake readiness

- Never label intake as globally `complete` or `incomplete`.
- Use `collecting`, `ready_to_build`, and `confirmed` for intake-session state.
- `ready_to_build` means each core design decision is resolved as confirmed,
  advised-and-accepted, assumed, or deferred, and no contradiction remains.
- Readiness does not start a build.
- Only the owner's explicit `Build this` confirmation freezes a revision and
  enables build submission.
- A missing optional field lowers confidence or becomes an assumption; it does
  not block readiness.
- A genuine contradiction or an absent safety-critical fact may pause readiness
  until the owner resolves it.

### First design and feedback

- Target less than 10 minutes from accepted `Build this` to a previewable first
  design under normal configured-provider operation.
- The UI must distinguish queue time, build time, deterministic preflight time,
  and optional visual-check time.
- The first design may use provisional copy, palette, imagery, and structure
  when those assumptions are displayed in the confirmed intake summary.
- A usable first design proceeds to owner feedback even when optional visual
  analysis is unavailable.
- The owner response is one of `fits`, `small_improvements`, or `redesign`.
- `fits` does not publish. It only records that the direction is accepted.
- `small_improvements` captures focused feedback and may create one explicit
  visual-refinement child through the existing service.
- `redesign` returns the owner to the intake conversation, highlights visual
  direction decisions, and requires a new confirmed intake revision.

### Quality

- Initial review answers only: "Is this candidate acceptable to show the owner
  for directional feedback?"
- Deterministic build, route, responsive, CTA, factual-safety, and severe
  accessibility checks remain authoritative blockers.
- Visual review searches only for unacceptable visual or usability errors.
- Ordinary opportunities to improve hierarchy, spacing, typography, imagery,
  differentiation, motion, or polish are suggestions, not failures.
- A visual provider timeout, malformed response, or missing optional review is
  `check_unavailable`, not evidence that the design is bad.
- Background or post-launch improvement analysis may later turn suggestions
  into owner-reviewable drafts, but may never mutate production automatically.

## Simple Visible Status Model

Do not migrate or collapse the durable internal state machine in
`DesignRunStatus`. Add a stable owner-facing projection and use it throughout
Intake Lab.

| Visible status | Meaning |
|---|---|
| `working` | Ada is planning, building, or checking the first design. |
| `ready_for_feedback` | A coherent candidate is available for owner reaction. |
| `blocked` | Ada could not produce a responsibly reviewable candidate. |
| `cancelled` | The operation was intentionally stopped. |

Add a separate preflight outcome:

| Preflight | Meaning |
|---|---|
| `clear` | No unacceptable problem was detected. |
| `blocked` | At least one unacceptable problem prevents useful review. |
| `check_unavailable` | An optional check could not finish; core evidence still permits feedback. |

Add a separate feedback disposition:

| Disposition | Meaning |
|---|---|
| `pending` | The owner has not evaluated the direction. |
| `fits` | The overall direction fits. |
| `small_improvements` | The direction fits but needs focused changes. |
| `redesign` | The direction is wrong and intake should be revisited. |

### Projection from existing run state

- Internal states from `created` through `validating` project to `working`.
- `ready_for_review` projects to `ready_for_feedback`.
- A deterministic pass plus visual state `repair`, `inconclusive`, or provider
  failure projects to `ready_for_feedback`; visual findings become suggestions.
- `needs_repair` caused by deterministic blockers projects to `blocked`.
- `incomplete` with no usable candidate, failed build, unavailable required
  route evidence, or unresolved severe defect projects to `blocked`.
- `incomplete` with a retained previewable candidate, passing deterministic
  core gates, and only optional visual review unavailable projects to
  `ready_for_feedback` with preflight `check_unavailable`.
- `failed` and `interrupted` project to `blocked` unless a future explicit
  recovery rule proves a candidate is reviewable. Do not infer that in v1.
- `cancelled` projects to `cancelled`.

The projection must include machine-readable `blocking_reasons`,
`suggestions`, and `unavailable_checks`. The UI must not infer these from human
messages.

## What Counts as an Unacceptable Blocker

Block owner feedback only when at least one of these is supported by evidence:

- The candidate did not build or cannot load.
- An explicitly required route is missing or broken.
- Main navigation or the primary CTA cannot be used.
- The page is materially unusable at a required viewport.
- Severe overflow, overlap, clipping, invisible content, or corrupted rendering
  prevents understanding or interaction.
- A serious accessibility defect prevents ordinary keyboard or visual use.
- Candidate content contradicts a confirmed intake fact.
- Candidate content invents a sensitive business fact or prohibited claim.
- An explicit, confirmed intake requirement is absent.
- The output is empty, unrelated to the requested business, or clearly not a
  website proposal.

Do not block solely for:

- Missing optional information already listed as assumed or deferred.
- Provisional copy or photography.
- Lack of testimonials, trust marks, prices, or social proof not supplied by the
  owner.
- Subjective spacing, typography, visual hierarchy, imagery, motion, palette,
  or differentiation improvements that do not make the result unusable.
- A visual reviewer returning suggestions.
- A visual-review provider timeout or unavailable model.

## Intake Conversation Coverage

Ada should cover these dimensions conversationally. They are guidance for the
advisor and summary, not a rigid sequence shown to the owner.

| Dimension | Ada should establish or disposition |
|---|---|
| Business | Name, offer, primary services/products, location or service area when relevant. |
| Audience | Primary customer, their situation, motivations, concerns, and desired impression. |
| Conversion | Primary CTA, optional secondary CTA, destination availability, and success outcome. |
| Positioning | Differentiators, promise, values, personality, and prohibited or risky claims. |
| Visual direction | Vibe, emotional qualities, desired level of energy, visual references, and styles to avoid. |
| Brand system | Existing colors, logo, typography guidance, or permission for Ada to propose provisional choices. |
| Imagery | Owner assets, reference images, direct-use permission, subject matter, and unsuitable imagery. |
| Content | Available copy, facts Ada may draft around, proof supplied, and information deferred until later. |
| Structure | Smallest useful page set, navigation intent, homepage priorities, and required sections. |
| Experience | Accessibility needs, motion preference, device priorities, language, and practical constraints. |

The core readiness dimensions are business identity and offer, audience,
primary CTA, minimum page scope, visual direction, and permission to use
documented assumptions. Business identity and offer must provide the values
needed by `SiteIntake`, including a usable name or explicitly provisional
working name and at least one primary service or offer. A value may be assumed
or deferred, but it may not be silently absent.

## Provenance and Assumption Model

Every material intake value must carry one of these origins:

| Origin | Meaning |
|---|---|
| `confirmed` | The owner explicitly supplied or chose the value. |
| `advised` | Ada recommended the value and the owner accepted it. |
| `assumed` | Ada selected a reversible default so work can proceed. |
| `deferred` | The owner intends to provide it later; the first pass may omit or placeholder it safely. |

Create a new typed `DesignIntakeDraft` contract rather than weakening
`SiteIntake`. The draft may be partial. It contains:

```json
{
  "schema_version": 1,
  "fields": {},
  "provenance": {
    "business.offer_summary": {
      "origin": "confirmed",
      "source_message_id": 12,
      "note": "Owner described the core offer."
    }
  },
  "assumptions": [],
  "deferred": [],
  "contradictions": [],
  "open_topics": [],
  "readiness": "collecting"
}
```

Rules:

- Store dotted paths only from an allowlist defined by the contract.
- Never accept model-supplied database IDs, timestamps, hashes, origins, or
  confirmation state as authority.
- The application service assigns message IDs and validates provenance.
- An assistant recommendation remains `assumed` until the owner explicitly
  accepts it; after acceptance it becomes `advised`.
- User-supplied statements become `confirmed` only when reflected accurately in
  the persisted turn result.
- Contradictions are explicit records containing the competing values and
  source message IDs. Ada asks the owner to resolve them.
- `DesignIntakeDraft.to_site_intake()` is the sole draft-to-final conversion.
- Conversion applies only documented safe defaults and then calls
  `SiteIntake.from_dict()` unchanged.
- The frozen `SiteIntake` stores assumptions and field provenance under its
  existing `provenance`, `unknowns`, and extensible fields without changing
  confirmed facts.

## Typed Advisor Boundary

Add a narrow `DesignIntakeAdvisor` protocol and a typed `IntakeTurnResult`.
Keep prompt policy in `brain/`, persistence and workflow in `application/`, and
provider invocation behind the existing LLM abstraction.

Suggested result shape:

```json
{
  "schema_version": 1,
  "assistant_message": "...",
  "field_updates": [
    {
      "path": "brand.values",
      "value": ["warm", "practical", "local"],
      "basis": "owner_statement"
    }
  ],
  "assumption_updates": [],
  "deferred_updates": [],
  "contradictions": [],
  "suggested_readiness": "collecting"
}
```

The application service must reject unknown keys, unbounded strings, invalid
paths, invalid origins, and invalid media references. It computes actual
readiness deterministically after applying validated updates.

Advisor behavior:

- Ask one focused question at a time when a question is genuinely useful.
- Prefer questions that materially change conversion, structure, or art
  direction.
- Avoid re-asking a resolved topic.
- Give a recommendation when asking about a decision the owner may not know.
- Explain tradeoffs briefly and in owner language.
- Ask what the owner likes about uploaded examples.
- Suggest a provisional palette when exact brand colors are absent.
- Never describe assumed information as confirmed.
- Never mark the session confirmed or start a build.
- Keep the owner-facing conversation natural; never emit or append a question
  list, checklist, or scripted sequence.
- Produce a recap rather than another question when deterministic readiness is
  `ready_to_build`.

## Persistence

At implementation time, confirm `SCHEMA_VERSION` in `core/memory.py`. It is 28
at plan creation, so the expected first migration is 29.

Add these tables through `Memory` migrations only.

### `design_intake_sessions`

- `id TEXT PRIMARY KEY`: UUID-style stable session/project ID.
- `conversation_id INTEGER NOT NULL REFERENCES conversations(id)`.
- `state TEXT NOT NULL`: `collecting`, `ready_to_build`, or `confirmed`.
- `draft_json TEXT NOT NULL`.
- `draft_hash TEXT NOT NULL`.
- `confirmed_revision_id INTEGER`.
- `created_ts TEXT NOT NULL`.
- `updated_ts TEXT NOT NULL`.
- `confirmed_ts TEXT`.

### `design_intake_revisions`

- `id INTEGER PRIMARY KEY AUTOINCREMENT`.
- `session_id TEXT NOT NULL REFERENCES design_intake_sessions(id)`.
- `revision INTEGER NOT NULL`.
- `site_intake_json TEXT NOT NULL`.
- `site_intake_hash TEXT NOT NULL`.
- `summary_json TEXT NOT NULL`.
- `confirmation_message_id INTEGER NOT NULL REFERENCES chat_messages(id)`.
- `created_ts TEXT NOT NULL`.
- Unique `(session_id, revision)`.

Revisions are immutable. Never update a stored revision.

### `design_intake_assets`

- `session_id TEXT NOT NULL REFERENCES design_intake_sessions(id)`.
- `asset_id INTEGER NOT NULL REFERENCES media_assets(id)`.
- `position INTEGER NOT NULL`.
- `usage TEXT NOT NULL`: `website`, `inspiration_only`, or `undecided`.
- `reference_aspects_json TEXT NOT NULL DEFAULT '[]'`.
- `owner_note TEXT NOT NULL DEFAULT ''`.
- `created_ts TEXT NOT NULL`.
- `updated_ts TEXT NOT NULL`.
- Primary key `(session_id, asset_id)`.

Usage belongs to the intake association, not the global media asset. The same
asset may have a different role in a future project.

### `design_feedback`

- `id INTEGER PRIMARY KEY AUTOINCREMENT`.
- `run_id TEXT NOT NULL REFERENCES design_runs(run_id)`.
- `session_id TEXT NOT NULL REFERENCES design_intake_sessions(id)`.
- `disposition TEXT NOT NULL`: `fits`, `small_improvements`, or `redesign`.
- `message TEXT NOT NULL DEFAULT ''`.
- `created_ts TEXT NOT NULL`.
- One active disposition per run; replacing it records a new row or explicit
  revision rather than silently overwriting owner history.

Add nullable `intake_session_id` and `intake_revision_id` columns to
`design_runs`. Existing rows remain valid with null values. New conversational
Intake Lab runs require both fields.

Extend `chat_jobs` with a bounded `operation_kind` whose existing/default value
is `owner_chat` and whose new value is `design_intake_advice`. Add a nullable
`intake_session_id` for the new kind. Reuse the existing queued, running, done,
error, retry, ownership, interruption, and polling behavior; do not create a
second generic job framework. An intake job must reference the exact persisted
owner message it processes.

Memory owns CRUD and transactions. Application services must not access
`Memory.conn` directly.

## Media Storage and Build Use

Reuse `MediaService` and `MediaStore`. Do not create a second upload model.

### R2 mode

- When `site.media.enabled` is true, compose the existing `R2MediaStore`.
- Reuse the configured private bucket and stable `media/<storage_id>/...` keys.
- Never persist signed URLs in intake state, messages, or design requests.
- Do not call Cloudflare provisioning APIs from Intake Lab.

### Local Lab fallback

- Add a small `FilesystemMediaStore` implementation of `MediaStore` for the
  standalone Lab when R2 is not configured.
- Root it under `<lab-workspace>/media-store`.
- Reject traversal and symlinks on every operation.
- Return only Lab-local authenticated/proxied media URLs; do not expose
  `file://` paths.
- Keep the provider choice in Lab composition, not `MediaService`.

### Processing

- Compose the existing `MediaWorker` in the Lab lifespan when media is enabled.
- Upload returns immediately with durable queued state.
- The UI displays processing state and refreshes it without blocking chat.
- Build confirmation explains when a `website` image is still processing.
- Build submission is disabled only if a selected `website` image is not ready;
  the owner may wait, remove it, or change it to inspiration/deferred.
- An inspiration image whose analysis failed does not block build. Ada can ask
  the owner to describe what matters about it.

### Candidate materialization

- Extend the typed design-build boundary to carry media asset IDs separately
  from repository paths. Do not put numeric IDs into
  `PageBuildRequest.supplied_media_paths`.
- Resolve and stage only `website` assets in a dedicated allowed input location
  inside the isolated build worktree so the implementation model can choose
  whether they support the design.
- Use canonical normalized WebP bytes from `MediaStore`, never a signed URL.
- Copy before the implementation-model turn so the model can inspect and use
  exact relative paths.
- Before finalizing the candidate, remove staged images that are not referenced
  by generated HTML, CSS, JavaScript, structured content, or the validated
  design manifest. An authorized but unused image is not a validation failure.
- Record asset ID, source hash, canonical hash, and candidate-relative path in
  the design manifest and context snapshot.
- Treat materialized files as host-provisioned allowed changes.
- Inspiration-only metadata may enter the frozen brief, but inspiration image
  bytes must not enter the repository or implementation-model filesystem.
- Preserve selected order.
- Protect media assets only when a retained candidate actually references their
  copied bytes, consistent with the existing media usage rules.

## Application Service

Add `application/design_intake.py` with a `DesignIntakeService` responsible for:

- creating a session and associated conversation;
- retrieving a session projection;
- persisting and queuing one owner message as a durable intake-advice chat job;
- applying one claimed intake job through `DesignIntakeAdvisor` without running
  the general editor or exposing repository tools;
- persisting owner and assistant messages durably;
- associating and classifying existing media assets;
- deterministically computing readiness;
- producing the recap shown for confirmation;
- freezing an immutable `SiteIntake` revision after explicit confirmation;
- submitting a build only from a confirmed revision;
- recording owner feedback on a retained run.

Use typed/documented result dictionaries at this new boundary. Include session,
conversation, revision, run, provider, model, and asset IDs in diagnostics.

Do not put this workflow in `web/intake_lab.py`, `web/server.py`, or a route
function. Do not have the service call route functions.

### Transaction and idempotency rules

- Persist the owner message before calling the advisor.
- Attach selected asset references to that exact message.
- Enqueue the intake-advice job in the same transaction as the owner message.
- If the advisor fails, retain the owner message, failed job, and bounded
  diagnostic; allow an explicit retry without duplicating the message.
- Use a client-generated idempotency token for message submission and build
  confirmation.
- Persist the assistant message and draft update in one transaction.
- Complete the claimed chat job in that same transaction so a completed job can
  never exist without its assistant reply and corresponding draft hash.
- Confirmation must compare the submitted `draft_hash` with the current draft.
- Reject stale confirmation with `409 intake_changed`.
- A repeated confirmation token returns the existing immutable revision and
  does not queue a second run.
- A confirmed revision can create at most one initial build unless the owner
  explicitly requests a new attempt.

## HTTP API for Intake Lab

Keep all routes loopback-only and same-origin protected.

### Session routes

```text
POST /api/intake-sessions
GET  /api/intake-sessions/{session_id}
POST /api/intake-sessions/{session_id}/messages
POST /api/intake-sessions/{session_id}/confirm
POST /api/intake-sessions/{session_id}/build
```

- Session creation accepts an optional seed intake for fixtures and migration,
  but normal UI creation sends no raw `SiteIntake`.
- Message submission accepts bounded text, selected asset IDs, and an
  idempotency token.
- Message submission returns `202` with the durable chat-job ID. The session GET
  projection exposes bounded job status and steps for polling.
- Confirmation accepts the current draft hash and explicit confirmation text.
- Build accepts a confirmed revision ID and returns `202` with the existing run
  projection.
- Preserve `POST /api/runs` temporarily as a diagnostic compatibility route for
  existing tests, but remove it from the primary UI and mark it deprecated in
  the Lab metadata. It must remain local-only and non-publishable.

### Asset routes

```text
POST  /api/intake-sessions/{session_id}/assets
PATCH /api/intake-sessions/{session_id}/assets/{asset_id}
DELETE /api/intake-sessions/{session_id}/assets/{asset_id}
GET   /api/intake-sessions/{session_id}/assets/{asset_id}/thumbnail
```

- Upload accepts the same bounded multipart and legacy JSON shapes as the
  existing media API, then calls `MediaService.upload()`.
- PATCH changes usage, reference aspects, owner note, or position.
- DELETE removes only the session association. It does not delete the Library
  asset.
- Thumbnail responses proxy private bytes or redirect to a short-lived signed
  URL without exposing credentials or persisting the URL.

### Feedback route

```text
POST /api/runs/{run_id}/feedback
```

- Accept only `fits`, `small_improvements`, or `redesign` plus bounded owner
  notes.
- `small_improvements` does not automatically start a refinement unless the
  request explicitly asks to create one and the existing typed refinement
  preconditions hold.
- `redesign` returns the linked intake session to `collecting`, preserving the
  prior confirmed revision and design run as immutable history.

## Intake Lab UI

Continue using `web/static/intake_lab.html` with embedded CSS and JavaScript.

Replace the primary JSON editor with three coordinated areas:

### Conversation panel

- Durable owner/Ada message history.
- One text composer.
- Multi-image upload and selection.
- Clear processing indicators.
- Short prompts and advice rather than a form wizard.
- Retry affordance for failed advisor turns.

### Live intake summary

- Business and audience.
- Primary and secondary CTA.
- Page scope.
- Values and visual vibe.
- Brand colors and whether they are confirmed or provisional.
- Website images and inspiration-only images.
- Confirmed facts, assumptions, deferred details, and contradictions.
- Readiness label: `Collecting`, `Ready to build`, or `Confirmed`.
- Edit actions should focus the conversation composer with a suggested topic,
  not expose raw field editing by default.

### First-design workspace

- Existing preview, pipeline, evidence, revision history, and model identity.
- Visible status limited to `Working`, `Ready for feedback`, `Blocked`, or
  `Cancelled`.
- Preflight shows blockers separately from suggestions and unavailable checks.
- When ready, show the question: "How close is this to the direction you want?"
- Present `The direction fits`, `It needs small improvements`, and
  `The direction is wrong` as the three primary actions.
- Keep candidate preview read-only and non-publishable.

Retain the raw intake JSON only under a diagnostic `<details>` element. It is
read-only after confirmation. A development-only import action may remain
behind progressive disclosure for fixtures, but it is not the product path.

## Readiness and Confirmation Algorithm

Implement readiness deterministically in the application layer.

1. Validate the draft contract and every field provenance record.
2. Check for unresolved contradictions.
3. Check that the six core dimensions have a value or explicit disposition:
   business identity and offer, audience, primary CTA, page scope, visual
   direction, and assumption permission.
4. Check that every `website` asset exists, is an image, is unarchived, and has
   explicit direct-use permission.
5. Mark `collecting` when a core dimension is silently absent or a contradiction
   remains.
6. Mark `ready_to_build` when the draft can deterministically convert into a
   valid `SiteIntake` using documented assumptions and deferred values.
7. On owner confirmation, recompute rather than trusting the displayed state.
8. Freeze the exact `SiteIntake`, summary, assumption ledger, asset bindings,
   message ID, and content hash as one immutable revision.
9. Mark the session `confirmed` only after the revision transaction commits.

Examples of safe defaults:

- No exact colors: provisional palette derived from values and authorized
  visual references.
- No final photography: use authorized images when available; otherwise use a
  composition that does not depend on invented photography.
- No testimonials: omit testimonials.
- No trust evidence: use no fabricated proof.
- No contact destination: show the CTA hierarchy but keep the destination
  explicitly unresolved/non-live according to existing `SiteIntake` behavior.
- No final copy: draft restrained working copy from confirmed facts.

## First-Pass Preflight Changes

Keep deterministic validation but classify findings by whether they prevent
owner feedback.

- Add a documented `feedback_blocking` boolean or equivalent typed severity to
  normalized findings.
- Existing blocker/critical/serious technical findings map to blocking unless a
  more specific policy says the check is optional.
- Warnings remain visible suggestions.
- Missing information listed in the frozen intake's assumptions or deferred
  details cannot independently produce a blocking finding.
- Required-content checks derive only from confirmed/advised fields designated
  as first-pass requirements, not every sentence in the generated brief.
- Site-specific requirements remain in instance configuration or confirmed
  intake, never generic service code.

Replace the broad visual-review instruction with a bounded unacceptable-error
review. The reviewer returns:

```json
{
  "state": "clear | blocked | check_unavailable",
  "blockers": [],
  "suggestions": [],
  "strengths": [],
  "screenshot_evidence": []
}
```

For persisted compatibility, either introduce a new versioned visual-preflight
contract or map this output into the existing `VisualCritiqueReport` at the
service boundary. Do not reinterpret old stored `repair` records as technical
failures. Old `repair` findings project as suggestions unless they meet the new
explicit unacceptable-blocker criteria.

Visual preflight constraints:

- Use a small representative screenshot set rather than all evidence by
  default: homepage desktop and mobile, plus at most one additional route when
  required by intake.
- Use one provider request when context limits allow.
- Set a total operation budget substantially below the 10-minute build target;
  recommended default is 90 seconds with a hard configurable ceiling of 180
  seconds.
- Never retry indefinitely.
- Provider failure records `check_unavailable` and preserves the candidate.
- Store provider call start/end timestamps and batch counts so wall time can be
  separated from queue time.

## Timing and Observability

Persist or project these durations independently:

- Queue wait.
- Intake-to-confirmation is owner-controlled and is not part of build SLA.
- Source preparation.
- Implementation-model execution.
- Candidate finalization.
- Deterministic build and browser checks.
- Visual preflight provider time.
- Total confirmation-to-preview time.

The UI should show `Preview available` as soon as the retained candidate and
minimum safe preview evidence exist. Optional checks may finish afterward and
update suggestions without removing the preview.

Record events containing bounded identifiers and timing, never secrets or raw
provider payloads. At minimum record session ID, intake revision ID, run ID,
candidate SHA, asset IDs, provider/model, stage, elapsed milliseconds, and
outcome.

Success metrics for the Lab prototype:

- Median confirmation-to-preview under 10 minutes.
- Percentage of runs reaching `ready_for_feedback`.
- Percentage of visual checks ending `check_unavailable`.
- Owner disposition distribution.
- Number of intake turns before confirmation.
- Count of assumptions and deferred details at confirmation.
- Percentage of uploaded references authorized and used directly.

## Target Architecture

```text
Intake Lab HTML
  -> thin Intake Lab HTTP routes
  -> DesignIntakeService
       -> Memory (session, messages, revisions, asset bindings, feedback)
       -> DesignIntakeAdvisor contract
            -> configured LLM adapter
       -> MediaService
            -> R2MediaStore when configured
            -> FilesystemMediaStore in local Lab fallback
       -> DesignService
            -> confirmed SiteIntake revision only
            -> DesignJobExecutor
            -> immutable non-publishable candidate
            -> blocker-only preflight
```

The dependency direction remains:

```text
HTTP adapter -> application service -> typed contract -> adapter/provider
```

No plugin, MCP provider, or route may access `Memory.conn` or call another route
function.

## Existing Code to Reuse

| Existing code | Intended use |
|---|---|
| `core/design_contracts.py:SiteIntake` | Final immutable validated intake; do not loosen it for drafts. |
| `brain/design_brief.py` | Compile the confirmed intake and preserve non-blocking unknowns. |
| `application/intake_lab.py` | Lab run submission and safe projection after a confirmed revision. |
| `application/designs.py` | Context freeze, planning, candidate retention, and validation. |
| `application/design_jobs.py` | Durable background design execution. |
| `application/media.py:MediaService` | Upload, deduplication, asset resolution, and storage access. |
| `core/media_worker.py` | Durable normalization and vision analysis. |
| `hands/r2_media.py:R2MediaStore` | Private configured production-like media storage. |
| `core/memory.py` chat messages | Durable conversational transcript and attachment lineage. |
| `application/conversations.py` | Conversation lifecycle where its current contract fits. |
| `web/intake_lab.py` | Loopback-only HTTP adapter and preview routes. |
| `web/static/intake_lab.html` | No-build prototype UI. |

Do not duplicate media processing, design-run execution, preview rewriting, or
candidate validation in the new intake service.

## Implementation Phases

### Phase 1: Typed intake draft and provenance

- Add `DesignIntakeDraft`, field provenance, assumption, deferred-detail,
  contradiction, asset-binding, advisor-turn, and intake-summary contracts.
- Define bounded allowlisted paths and enums.
- Implement deterministic readiness and `to_site_intake()` conversion.
- Add focused tests proving absent optional details become assumptions rather
  than failures.
- Add tests proving contradictions and silently absent core dimensions keep the
  session collecting.
- Add tests proving prohibited claims and fabricated destinations are rejected.

Acceptance:

- A sparse but explicitly dispositioned intake converts to valid `SiteIntake`.
- Every material value has valid provenance.
- The LLM cannot set confirmation state or authoritative identifiers.

### Phase 2: Durable session service

- Add migrations and `Memory` methods.
- Add `DesignIntakeService` session, message, recap, confirmation, and feedback
  methods.
- Extend the existing chat-job record and executor dispatch for
  `design_intake_advice`; do not route that job through `brain/editor.py`.
- Implement transaction and idempotency rules.
- Reuse conversation rows for transcript history.
- Link immutable intake revisions to design runs.

Acceptance:

- Restarting the Lab preserves conversation, draft, assumptions, assets,
  confirmation, and feedback.
- Stale confirmations and duplicate build submissions do not create duplicate
  revisions or runs.

### Phase 3: Advisor

- Add the narrow advisor protocol and configured implementation.
- Build the prompt from the current typed draft, bounded recent conversation,
  and selected media metadata.
- Parse the strict typed result and reject unsupported updates.
- Persist bounded provider diagnostics and support explicit retry.

Acceptance:

- Ada asks focused questions, gives useful recommendations, does not repeat
  resolved topics, and produces a recap when ready.
- Provider failure preserves all owner input and does not corrupt the draft.

### Phase 4: Intake media

- Add `FilesystemMediaStore` for Lab fallback.
- Compose `MediaService` and `MediaWorker` in Intake Lab.
- Add session asset association and permission endpoints.
- Add the upload/picker/permission UI.
- Pass media metadata to the advisor.

Acceptance:

- Duplicate uploads reuse the existing asset by content hash.
- Direct-use permission is explicit.
- Inspiration-only bytes cannot enter a candidate repository.
- R2 mode persists private objects without signed URL leakage.
- Local mode survives Lab restart under the workspace.

### Phase 5: Confirmed build handoff

- Change the primary Lab build path to require a confirmed intake revision.
- Carry session and revision IDs into the run and context snapshot.
- Add typed media ID handling and host-side materialization for `website`
  assets.
- Preserve diagnostic `POST /api/runs` compatibility without exposing it in the
  primary UI.

Acceptance:

- No conversational draft can start a build.
- The candidate is traceable to one immutable intake revision and exact asset
  hashes.
- Authorized images are available to the builder at deterministic repository
  paths.
- Authorized images that Ada does not use are absent from the finalized
  candidate and remain reusable Library assets.
- No GitHub push or Cloudflare deployment resource is created.

### Phase 6: Simplified preflight and feedback

- Add the visible run projection and separate preflight projection.
- Reclassify visual repair suggestions as non-blocking.
- Narrow visual review to unacceptable defects and enforce its time budget.
- Add the three owner feedback actions.
- Keep one explicit small-improvement refinement path and a redesign return to
  intake.

Acceptance:

- A technically valid candidate with visual suggestions is
  `ready_for_feedback`.
- An unavailable visual provider does not make a usable candidate incomplete.
- Only evidence-backed unacceptable defects project to `blocked`.
- Owner feedback is durable and never publishes.

### Phase 7: UI completion and end-to-end verification

- Replace JSON-first composition with conversation, summary, and preview areas.
- Add responsive desktop/mobile layouts and keyboard-accessible controls.
- Add clear progress, timeout, stale-state, upload, and retry messaging.
- Verify all API and preview URLs under the configured mount point.

Acceptance:

- A user can complete intake, upload references, confirm, build, preview, and
  record feedback without reading or editing JSON.
- The full flow works after a browser refresh and service restart.
- No horizontal overflow or JavaScript errors occur at mobile width.

## Expected File Changes

Prefer the smallest correct set after tests establish the final boundaries.

- `src/site_agent/core/design_contracts.py`: draft/provenance/turn contracts, or
  a focused new `core/design_intake_contracts.py` if the existing module becomes
  harder to navigate.
- `src/site_agent/core/memory.py`: migrations and persistence methods.
- `src/site_agent/application/design_intake.py`: new workflow service.
- `src/site_agent/brain/design_intake.py`: advisor prompt and decision policy.
- `src/site_agent/application/intake_lab.py`: confirmed-revision handoff and
  simplified projections.
- `src/site_agent/application/designs.py`: session/revision lineage and media
  context integration.
- `src/site_agent/hands/opencode_runner.py`: typed host-side media
  materialization for design builds.
- `src/site_agent/hands/filesystem_media.py`: local `MediaStore` adapter.
- `src/site_agent/web/intake_lab.py`: thin session, asset, confirmation, build,
  and feedback routes.
- `src/site_agent/web/static/intake_lab.html`: conversation-first Lab UI.
- `src/site_agent/runtime.py` or Intake Lab CLI composition: inject the new
  service and media provider without global state.
- Focused tests matching each boundary; do not put all scenarios in one large
  end-to-end test.

## Security and Privacy

- Preserve loopback binding and same-origin checks.
- Keep the candidate iframe sandboxed without `allow-same-origin`.
- Enforce body, message, asset-count, file-size, and string-length limits.
- Validate MIME content from bytes, not filename.
- Never send R2 credentials, GitHub credentials, Cloudflare tokens, filesystem
  roots, or unrelated environment values to the advisor or builder.
- Never persist signed media URLs.
- Do not send `website` or inspiration images to an LLM without the existing
  configured media/vision privacy boundary.
- Treat image descriptions, OCR, and dominant colors as untrusted evidence.
- Sanitize provider errors through existing safe-provider messaging.
- Include asset IDs and hashes in diagnostics, not private object URLs.
- Do not allow the advisor to select an unassociated Library asset by guessed
  ID.

## Testing Strategy

Start every phase with a failing focused test or reproducible API request.

Required focused coverage:

- Draft contract bounds and unknown-field rejection.
- Provenance transitions from owner statement, Ada recommendation, acceptance,
  assumption, and deferral.
- Deterministic readiness with sparse intake.
- Contradiction resolution.
- Advisor malformed output and retry idempotency.
- Intake chat-job recovery, interruption, exact-message binding, and atomic
  completion with assistant reply plus draft update.
- Session and immutable revision persistence across restart.
- Stale confirmation and duplicate confirmation tokens.
- Media upload, deduplication, processing, association, and permission changes.
- Filesystem store traversal and symlink rejection.
- R2 signed URL non-persistence.
- Website-only media materialization.
- Cleanup and non-protection of authorized images not referenced by the final
  candidate.
- Inspiration-only exclusion from candidate bytes and manifest paths.
- Run linkage to exact intake revision.
- Visible status and preflight mapping for every internal terminal state.
- Visual suggestions remain ready for feedback.
- Visual timeout becomes check unavailable.
- True route/build/CTA/accessibility blockers remain blocked.
- Feedback actions and redesign revision behavior.
- Loopback, origin, request-size, and preview sandbox protections.
- Static UI regression checks for required controls and no raw JSON-first path.
- Playwright desktop and mobile flow with no console errors or overflow.

Final verification:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
git diff --check
```

## End-to-End Acceptance Scenario

1. Start Intake Lab with R2 configured or the local fallback.
2. Create an intake session.
3. Tell Ada what the business offers and who it serves.
4. Upload two images, marking one `website` and one `inspiration_only`.
5. Explain what is appealing about each image.
6. Let Ada recommend a primary CTA and provisional palette.
7. Accept the CTA and allow the palette to remain an assumption.
8. Defer final testimonials and contact destination.
9. Review a recap that clearly separates confirmed, advised, assumed, and
   deferred information.
10. Confirm `Build this`.
11. Verify one immutable intake revision and one linked local design run.
12. Verify only the authorized website image is copied into the candidate.
13. Receive a previewable first pass with visible status
    `ready_for_feedback` under normal provider timing.
14. Verify visual polish suggestions do not change that status.
15. Record `small_improvements` with a focused note.
16. Verify no repository remote, Cloudflare deployment resource, draft,
    approval, push, or publication was created.
17. Restart the Lab and reopen the complete conversation, intake revision,
    assets, run, preview, suggestions, and owner feedback.

## Future Adoption Boundary

Do not implement adoption in this scope, but preserve enough identity for a
later `Adopt this design` operation to:

- create or connect a GitHub repository;
- push the existing candidate commit history without regenerating the design;
- import or reuse media by stable storage ID and content hash;
- create Cloudflare staging resources;
- configure a domain later;
- retain the original session, intake revision, assets, and owner feedback.

The portable adoption bundle should be derivable from persisted state and
contain no credentials:

- session ID;
- confirmed intake revision and hash;
- assumption/deferred ledger;
- media asset IDs, storage IDs, hashes, and usage permissions;
- candidate SHA and manifest hash;
- quality/preflight evidence hashes;
- owner feedback disposition.

This boundary, rather than early infrastructure provisioning, is what prevents
the intake and first design from being redone later.

## Definition of Done

- Intake Lab is conversation-first and raw JSON is diagnostic only.
- Ada behaves as an advisor and records field-level provenance.
- Missing optional information becomes an assumption or deferred detail.
- The owner explicitly confirms an intake summary before any build starts.
- Image references are durable, private, permissioned, and reusable.
- R2 is reused when configured; local development has a safe filesystem store.
- Only direct-use images enter candidate repositories.
- The first-design visible taxonomy is working, ready for feedback, blocked, or
  cancelled.
- Visual review blocks only evidence-backed unacceptable defects.
- Suggestions and unavailable optional checks do not fail a usable first pass.
- The owner can record fits, small improvements, or redesign.
- The confirmation-to-preview target and stage timings are observable.
- All candidates remain local, immutable, non-publishable, and inspectable.
- No GitHub or Cloudflare deployment infrastructure is provisioned.
- Focused tests, full tests, compileall, wheel build, diff check, and responsive
  browser verification pass.
