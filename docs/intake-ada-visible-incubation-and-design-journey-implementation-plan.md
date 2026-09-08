# Intake Ada Visible Incubation and Design Journey Implementation Plan

**Status:** Proposed implementation contract

**Date:** 2026-09-03

**Authority:** This plan extends
`docs/ada-incubation-research-and-provisioning-implementation-plan.md` and
`docs/conversational-design-intake-implementation-plan.md`. It replaces their
owner-facing Intake Lab presentation, background activity, research-trigger,
design-skill-sharing, and post-intake transition requirements where they
conflict.

The production mutation, draft review, and explicit approval invariants in
`AGENTS.md` remain authoritative. This plan does not permit Intake Ada to
publish, merge, deploy, provision, or activate a customer instance without the
existing explicit owner operation.

## How To Use This Plan

- Implement phases in order unless a phase explicitly permits overlap.
- Start each phase with a focused failing test or a reproducible API request.
- Keep HTTP adapters thin. Workflows belong in application services.
- Keep every external provider behind a narrow typed capability contract.
- Keep the existing no-build HTML/CSS/JavaScript Intake Lab. Do not add a
  frontend framework for this work.
- Mark a phase complete only after its focused tests and acceptance criteria
  pass.
- Run the full verification matrix and a retained-workspace browser smoke test
  before declaring the plan complete.

## Executive Decision

Intake Ada is not only collecting a website brief. During the conversation she
is learning the business, looking outward into relevant public communities,
forming the initial customer-Ada personality, applying the same design judgment
that will guide the build, and preparing a continuous handoff into the
provisioned customer instance.

The owner should be able to see that work happening. The Intake Lab background
will become a persistent, provenance-aware activity field showing Ada's
observable work:

```text
conversation -> business understanding
             -> community and feed reading
             -> cross-language audience insights
             -> customer-Ada genesis revisions
             -> design implications
             -> design build and quality checks
             -> owner review
             -> explicit provisioning handoff
```

The central interaction remains a simple chat. It must not explain how to have a
conversation, show a questionnaire, expose session identifiers, or lead with
product instructions. Ada opens the conversation herself:

```text
Ada

Hi, I'm Ada. What are you working on?

[Message Ada                                      ] [Send]
```

When the brief is ready, Ada presents the next decision inside the conversation.
When the owner chooses **Create first design**, the primary surface immediately
changes from Conversation to Design. The Design surface first shows durable
build progress, then replaces that progress with the retained candidate when it
is ready for review.

## Product Principles

### Ada leads the conversation

- Remove introductory prose telling the owner what to say.
- Remove the visible `One conversation` kicker, large instructional heading,
  explanatory paragraph, site/session metadata, `Talk to Ada` label, Refresh
  control, and persistent composer help text from the normal chat surface.
- Ada's first assistant message is the invitation to begin.
- Use ordinary chat conventions. The text area placeholder is `Message Ada`.
- Use an accessible Send control. An icon-only visual treatment is acceptable
  only with `aria-label="Send message"` and a visible keyboard focus state.
- Keep image attachment available as a paperclip/plus action with an accessible
  label. Do not explain images before the owner needs the feature.
- Do not force one or two questions per turn. Ada may ask no question when a
  reflection or recommendation is more useful.
- Do not expose intake field names, core-decision counts, hashes, job IDs, run
  IDs, provider names, or developer terminology in the normal conversation.

### The background is meaningful, not decorative

- Every displayed activity comes from durable state.
- New activity appends. It does not replace prior activity on every render.
- The visible field may emphasize recent activity, but the complete retained
  history remains reachable through cursor pagination.
- Show searches, source checks, bounded reads, insights, corrections, genesis
  changes, design implications, build stages, and quality outcomes.
- Show source language and translation when cross-language evidence is used.
- Clearly distinguish owner statements, public-source observations, Ada's
  inferences, reversible recommendations, and confirmed decisions.
- Do not expose private chain-of-thought, hidden reasoning tokens, raw prompts,
  unredacted model output, secrets, credentials, filesystem paths, or another
  customer's information.
- The product phrase “see into Ada's mind” means observable activity, evidence,
  decisions, confidence, and provenance. It never means model scratch work.

### Research starts early and stays bounded

- Once the conversation contains a usable offer plus a subject, audience,
  market, or location, Ada may begin one bounded research pass automatically.
- The model may nominate likely subreddits from its general knowledge. A broad
  web search is not required merely to guess familiar community names.
- A nominated subreddit is a candidate, not a fact. Verify that it currently
  exists and is relevant before reading it.
- Read public Reddit communities through the existing read-only RSS boundary or
  another approved read-only provider. Never post, vote, authenticate, message
  users, or build user profiles.
- Research may cross languages. A French owner may benefit from current English
  specialist communities that reveal vocabulary, concerns, and expectations not
  visible in the owner's immediate market.
- Preserve source language. Translate the synthesized insight into the owner's
  language without presenting the translation as a verbatim quote.
- One-time bounded public reading may happen automatically during incubation.
- Ongoing subscriptions transferred to Customer Ada require a separate explicit
  owner choice or a future documented policy-approval mechanism.
- The owner can exclude a source, community, or topic at any time. Exclusions
  are durable and transfer during provisioning.

### Intake and build share design judgment

- Intake Ada, design planning, the implementation builder, and visual review use
  the same trusted local design skills:
  `design-core`, `frontend-design`, `high-end-visual-design`, `motion-design`,
  and `web-design-guidelines`.
- There is one canonical loader and deterministic skill order. Do not maintain a
  second hand-copied intake summary that can drift from the builder.
- Skills are judgment tools, not a prescribed visual direction or owner-facing
  checklist.
- During intake, skills help Ada notice design consequences, explain tradeoffs,
  interpret references, and ask better questions.
- During planning and building, the same skill set informs the actual candidate.
- Persist the skill-set names and content hash with design-relevant incubation
  activity and the frozen design request.
- Customer facts and owner-confirmed preferences always outrank generic skill
  advice.

### Personality develops with evidence

- Customer Ada genesis evolves throughout incubation, not only at final intake
  confirmation.
- Conversation, corrections, source choices, research insights, visual
  preferences, and design feedback may produce immutable genesis revisions.
- Reddit language can enrich audience understanding but must not cause Ada to
  imitate a community's voice or adopt unsupported claims.
- The owner remains authoritative for the business and relationship.
- Research is authoritative only for what was observed in the cited public
  source at the recorded time.
- Ada's synthesis remains an inference with confidence and evidence links until
  the owner confirms it.

## Target Owner Journey

### Phase A: Conversation

The page opens directly into a familiar chat window. There is no marketing copy
or instructional hero.

Required initial state:

```text
Ada                                           online

Ada
Hi, I'm Ada. What are you working on?

[+] [Message Ada                              ] [send]
```

The background is already alive but quiet:

```text
LISTENING    Waiting for the first detail
MEMORY       New customer-Ada genesis started
DESIGN       Shared design judgment ready
```

After the first useful owner message, conversation and background work proceed
independently. The owner never has to wait for research before continuing the
conversation.

### Phase B: Brief ready

When readiness is derived as `ready_to_build`, Ada adds an ordinary assistant
message followed by one conversation action card:

```text
Ada
I have enough to create a first direction. I understand this as a calm,
technically credible cave-diving retreat for certified divers, with local life
and the cenotes carrying the visual story.

[Create first design] [Keep refining]
```

The card may reveal a concise brief summary on request. It must not require the
owner to open Developer View.

Selecting **Create first design** is the explicit owner action that freezes the
current intake revision and requests an isolated candidate. The existing two
application operations may remain separate internally, but the owner sees one
coherent action with idempotent recovery.

### Phase C: Building

Immediately after the owner selects **Create first design**, navigate the
primary surface to the Design workspace. Do not leave the owner in the chat
while network calls or the build run execute.

Represent the route in browser history:

```text
/?incubation_id=<id>&view=design&run_id=<run_id>
```

Before the run ID exists, the Design workspace may use the incubation ID and
show `Locking the brief`. Replace the URL when the run is returned.

Required visible states use real persisted events:

```text
Brief locked
Planning the direction
Building the pages
Running quality checks
Reviewing the visual result
```

Show elapsed time and the latest meaningful activity. Do not show invented
percentages or speculative completion times. State that it is safe to leave and
return. Refreshing the page must resume the same run and polling loop.

The incubation activity field remains visible around the Design workspace, now
including design and quality events.

### Phase D: Design review

When the durable run becomes reviewable, keep the owner in the same Design
workspace and replace waiting content with the candidate preview.

Required controls:

- Page navigation for every returned candidate page.
- Responsive viewport choices when supported by retained evidence.
- `This direction works`.
- `Request changes`.
- `Start a different direction`.
- `Back to conversation`.

Preview tokens are ephemeral and must be reacquired after reload or summary
refresh. Never expose a raw filesystem or preview link as a substitute for the
review surface.

`Request changes` returns to the conversation with the reviewed run attached as
context. `Start a different direction` reopens design-direction intake and
requires a new confirmed revision. `This direction works` records feedback but
does not publish or provision.

### Phase E: Acceptance and provisioning

Website acceptance and customer provisioning remain separate explicit owner
actions. The handoff surface must preview what will transfer:

- Confirmed business understanding and provenance.
- Customer-Ada genesis and meaningful revision history.
- Owner communication preferences and boundaries.
- Approved research sources and ongoing subscriptions.
- Cross-language audience insights with source references.
- Creative principles and patterns to avoid.
- Accepted design identity and feedback lineage.
- The shared design-skill set version/hash used to create the direction.

Activation remains a separate operation after verified import.

## Visual Direction for the Intake Lab

The signature interaction is the contrast between a quiet central conversation
and a continuously accumulating field of Ada's activity around it.

Use three activity channels:

| Channel | Placement | Content |
|---|---|---|
| Discovering | Left field | Candidate communities, feed checks, bounded reads, source languages, emerging vocabulary |
| Becoming | Right field | Business understanding, corrections, genesis revisions, relationship preferences, creative principles |
| Designing | Lower field and Design workspace | Skill use, visual implications, art direction, build stages, quality checks |

The channels are conceptual, not three unrelated widgets. On wide screens they
may occupy peripheral columns behind or beside a lightly translucent chat card.
Text intended to be read must meet contrast requirements and must not sit behind
the message text itself.

New activity may enter with one restrained motion treatment. Older entries
remain in the flow, gradually becoming quieter without disappearing from the
ledger. Respect `prefers-reduced-motion` and provide a static append-only
translation.

Clicking or focusing an activity opens a concise evidence detail containing:

- Timestamp and category.
- Owner-facing summary.
- State: started, completed, needs attention, or corrected.
- Provenance type.
- Source title and language where applicable.
- Confidence where applicable.
- Correlated message, intake revision, genesis revision, source, job, or run.
- Any owner action available, such as exclude source or correct inference.

On mobile, do not place text behind the chat. Show a compact live activity strip
and an `Ada's activity` sheet containing the same cursor-paginated ledger.

## Observable Activity Contract

### Add `IncubationActivity`

Define a typed contract in `core/incubation_contracts.py`.

Required fields:

```text
schema_version
activity_id
occurred_at
category
kind
state
summary
provenance
confidence
detail
conversation_id
message_id
chat_job_id
intake_session_id
intake_revision
research_request_id
source_id
finding_ids
genesis_revision
design_run_id
provider_id
```

Allowed categories:

```text
conversation
understanding
research
translation
genesis
design
quality
feedback
provisioning
system
```

Allowed states:

```text
started
progress
completed
needs_attention
corrected
cancelled
```

Allowed provenance values:

```text
owner
public_source
model_inference
host_validation
owner_confirmation
system
```

Validation rules:

- Owner-facing summaries are required, plain text, and bounded.
- `detail` is an allowlisted JSON object, not an arbitrary provider payload.
- Confidence is required for model inferences and public-source synthesis.
- Correlation identifiers use existing validated identifier formats.
- URLs are represented through known source IDs in the normal projection.
- Redact secrets, private paths, email-like accidental content, and credentials
  before persistence and again before HTTP projection.
- Activity is append-only. Corrections append a linked event rather than editing
  history.

### Persistence

Add the next `Memory` migration after schema version 31.

Create `incubation_activity` in each per-incubation database:

```sql
CREATE TABLE incubation_activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_at TEXT NOT NULL,
  category TEXT NOT NULL,
  kind TEXT NOT NULL,
  state TEXT NOT NULL,
  summary TEXT NOT NULL,
  provenance TEXT NOT NULL,
  confidence REAL,
  detail_json TEXT NOT NULL DEFAULT '{}',
  conversation_id INTEGER,
  message_id INTEGER,
  chat_job_id INTEGER,
  intake_session_id TEXT,
  intake_revision INTEGER,
  research_request_id TEXT,
  source_id TEXT,
  finding_ids_json TEXT NOT NULL DEFAULT '[]',
  genesis_revision INTEGER,
  design_run_id TEXT,
  provider_id TEXT
);
```

Add indexes for `(id)`, `(category, id)`, `chat_job_id`, `source_id`, and
`design_run_id`.

Do not replace authoritative domain tables with this ledger. Domain services
persist their normal state first, then append the safe activity projection in
the same transaction where feasible. If atomic composition is not currently
available, add a narrow Memory transaction method rather than accessing
`Memory.conn` from an application service.

Add Memory methods:

```text
append_incubation_activity(activity)
list_incubation_activity(after_id=None, before_id=None, limit=100, categories=())
get_incubation_activity(activity_id)
```

Pagination is monotonic and cursor-based. Return `next_cursor`, `has_more`, and
`total` or an explicit `total_unavailable`. Never use ascending-order plus a
limit that permanently hides recent records.

### Activity service

Add `application/incubation_activity.py` with a narrow
`IncubationActivityService`. It owns safe event projection and redaction. Other
application services call this service; web routes do not synthesize activity.

Initially project activity from:

- Incubation creation and lifecycle transitions.
- Owner and assistant messages.
- Intake field changes and readiness changes.
- Media upload and analysis outcomes.
- Research planning, verification, reading, and synthesis.
- Genesis revisions.
- Novelty constraints selected for a build.
- Design run events and quality results.
- Owner feedback, acceptance, provisioning, and activation.

Do not use mutable `chat_jobs.steps_json` as the long-term activity source.
Existing steps may continue for job diagnostics, but meaningful steps must also
append durable activity. Retrying a job must not erase prior activity.

### HTTP projection

Add thin routes to `web/intake_lab.py`:

```text
GET /api/incubations/{incubation_id}/activity?after_id=<cursor>&limit=<n>
GET /api/incubations/{incubation_id}/activity/{activity_id}
```

The list endpoint returns the safe owner-facing projection only. Detail remains
allowlisted and never includes raw prompts, model output, private paths, or
credentials.

## Background Research Architecture

### Research request contract

Add durable `ResearchRequest` and `ResearchJob` contracts. A plain-language
research intent must never disappear when no source URL is supplied.

Required research-request concepts:

```text
request_id
created_at
updated_at
status
trigger
intake_revision
owner_language
subjects
markets
candidate_communities
query_terms_by_language
source_ids
finding_ids
error
```

Triggers include `intake_threshold`, `owner_request`, `owner_correction`, and
`design_feedback`.

Persist requests and jobs in per-incubation storage. Use a deterministic
deduplication key based on the relevant intake revision and normalized research
subjects so repeated renders or retries do not create duplicate passes.

### Research planner

Add a narrow brain policy such as `brain/incubation_research.py`.

Inputs:

- Typed intake draft and provenance.
- Owner language.
- Existing source exclusions.
- Existing request subjects and recent findings.
- Strict source/item/pass limits from configuration.

Outputs:

- Candidate subreddit names.
- Candidate RSS topics or known source URLs when justified.
- Query terms in the owner language and relevant international languages.
- Short rationale for each candidate.
- No business facts.

The model's training knowledge is permitted to nominate likely subreddit names.
The planner must label them as candidates and must not claim they exist, are
active, or are relevant until validated live.

### Community discovery capability

Introduce a narrow read-only contract rather than a universal crawler:

```text
CommunityDiscoveryProvider.propose(context) -> candidate communities
CommunityReader.verify(candidate) -> current public metadata
CommunityReader.read(candidate, limit) -> bounded public documents
```

Use the existing Reddit RSS reader for known communities after validation. Add
an adapter that:

- Normalizes `r/<name>` candidates.
- Constructs the public RSS URL.
- Distinguishes not found, private/quarantined, rate limited, unavailable, and
  readable outcomes.
- Preserves current backoff and item limits.
- Does not authenticate or mutate Reddit.
- Emits activity for candidate selection, verification, read start, read
  completion, and bounded failures.

Do not add general-purpose scraping or arbitrary model-controlled HTTP access.

### Research executor

Add a durable background executor owned by the incubation runtime. It must not
block the chat advisor response.

Flow:

```text
intake revision saved
  -> threshold policy decides whether research is useful
  -> durable request and job created idempotently
  -> activity: research started
  -> model proposes candidate communities from known niche context
  -> adapter validates candidates live
  -> adapter reads a bounded recent sample
  -> synthesis creates typed findings and insights
  -> activity: findings and cross-language insights
  -> genesis proposal created when meaningful evidence changed
  -> activity: genesis revision completed
```

Start and stop the executor through the Intake Lab lifespan in `main.py`, using
the same explicit runtime composition style as chat, design, and media workers.
Do not call route functions or access `Memory.conn`.

### Synthesis contract

Raw feed entries are untrusted evidence. Add a typed `IncubationInsight` with:

```text
insight_id
kind
summary
owner_language
source_languages
finding_ids
supports_paths
contradicts_paths
confidence
status
created_at
```

Allowed kinds:

```text
audience_language
audience_concern
audience_desire
business_context
content_opportunity
creative_implication
contradiction
```

Insight status is `observed`, `inferred`, `owner_confirmed`, `corrected`, or
`excluded`.

Synthesis rules:

- Use only the bounded sanitized documents supplied to the synthesizer.
- Preserve finding IDs and source languages.
- Translate the summary into the owner language when useful.
- Never invent testimonials, credentials, prices, safety claims, availability,
  legal conclusions, or customer outcomes.
- Never overwrite an owner-confirmed intake value.
- Surface contradictions rather than silently reconciling them.
- Do not infer personality from one post or one individual author.
- Aggregate recurring patterns and state low confidence when the sample is thin.

## Shared Design Skill Architecture

### Canonical loader

Extract `_design_skill_guidance()` from `application/design_lab.py` into a brain
module such as `brain/design_guidance.py`.

Define a typed immutable projection:

```text
DesignSkillSet
  names
  content
  content_hash
```

Load these files in deterministic order:

```text
skills/design-core.md
skills/frontend-design.md
skills/high-end-visual-design.md
skills/motion-design.md
skills/web-design-guidelines.md
```

The loader reads package-owned trusted files only. Missing required skills fail
startup or the affected design operation with a useful diagnostic; do not
silently run intake and build with different doctrine.

### Intake use

Pass the trusted skill set to `LLMDesignIntakeAdvisor` as guidance, clearly
separated from owner text, media metadata, and public research evidence.

Prompt rules:

- Apply the skills silently as professional judgment.
- Keep the owner-facing response conversational.
- Do not recite the skills or turn them into a questionnaire.
- Do not prescribe typography, color, layout, or motion before enough subject
  evidence exists.
- Explain a recommendation only when it advances the current decision.
- Record design implications as typed structured output when they are useful.

Extend `IntakeTurnResult` with an optional bounded collection such as
`creative_insights` rather than hiding design implications in free text.

Each insight contains:

```text
kind
summary
basis
related_intake_paths
related_asset_ids
confidence
```

These insights are recommendations or interpretations. They do not become
owner-confirmed fields unless the owner accepts them.

### Planning and build use

Replace direct skill loading in Design Lab with the canonical loader. Preserve
OpenCode installation of the same skill files through `install_agent_files()`.

Include the skill-set hash and a safe typed `incubated_creative_context` in the
frozen design request:

```text
genesis revision and hash
owner-confirmed visual preferences
owner-confirmed dislikes
research-backed creative implications
cross-language audience insights
novelty constraints
patterns to avoid
design skill-set names and hash
```

For `initial_homepage`, continue excluding the existing site's visual
vocabulary, markup, screenshots, stale persona, and unrelated memory. Do not
discard the typed incubated creative context merely because the broad context
snapshot is removed. Change `_design_prompt()` so the narrow validated creative
context reaches the builder while existing-site contamination remains blocked.

Update art-direction planning so it can consume this typed context. The current
three deterministic hypotheses may remain as fallback, but they must not be the
only possible directions when the incubation contains stronger subject-specific
evidence.

### Visual review use

Visual review receives the same skill-set hash and the selected direction. It
uses the skills as a quality lens while judging the actual subject-specific
intent, not as a generic style checklist.

Record safe activity such as:

```text
DESIGN  Applied subject-specificity and hierarchy guidance
DESIGN  Selected a geological-depth image strategy from owner references
QUALITY Checked mobile translation and reduced-motion behavior
```

Do not record hidden deliberation or rejected scratch ideas.

## Incremental Customer-Ada Genesis

Extend `CustomerGenesisService` with provenance-aware proposal methods for:

```text
propose_from_intake_revision(...)
propose_from_research_insights(...)
propose_from_design_feedback(...)
```

Create a revision only when normalized genesis content changes. Do not create a
new revision for every poll or duplicate job retry.

Required behavior:

- Owner statements and corrections have highest precedence.
- Research insights add evidence-linked hypotheses, not owner facts.
- Source exclusions remove future influence and append corrective evidence.
- Relationship preferences come only from owner interaction or explicit owner
  confirmation.
- Creative principles may combine owner preference with research-backed audience
  understanding, retaining separate evidence for each.
- Corrections support replacement and removal. Do not only merge stale values
  forever.
- Evidence points to the exact changed genesis path.
- Candidate feeds include current validated candidates; approved subscriptions
  remain a separate field/state.

Project owner-facing genesis changes into activity instead of dumping raw JSON:

```text
BECOMING  Learned that technical precision matters more than luxury language
BECOMING  Added a boundary: never imply uncertified access is appropriate
BECOMING  Corrected the audience from general travelers to certified cave divers
```

Keep full genesis revision data available under evidence detail and Developer
View.

## Conversation, Building, and Review State Model

Add a client-side owner view state independent from internal job status:

```text
conversation
building
review
blocked
handoff
```

Derive the initial view from URL plus durable server state. Server state wins
when the URL is stale.

| Durable state | Owner view |
|---|---|
| Collecting or no intake session | Conversation |
| Ready to build, not confirmed | Conversation with action card |
| Confirmed/build submission pending | Building |
| Design run in active internal state | Building |
| Reviewable retained candidate | Review |
| Failed/interrupted/cancelled without reviewable candidate | Blocked |
| Accepted/provisioned | Handoff |

Align incubation lifecycle handling for `needs_repair` and `incomplete`. A
retained candidate with passing core gates may remain reviewable with visible
issues. A candidate that cannot responsibly be shown becomes blocked. The UI
must consume a machine-readable owner projection rather than infer severity from
free text.

On boot:

- Load the incubation summary.
- Restore the latest unfinished chat job and resume polling.
- Restore the current design run and resume polling.
- Fetch activity after the locally held cursor.
- Reacquire preview token and page list when a candidate exists.
- Reconcile the URL view with durable state.
- Never create a new incubation merely because a saved ID is temporarily
  unavailable before retrying a bounded load.

## Intake Lab UI Changes

### Remove from the normal chat

Remove or move to Developer View:

- `You do not need the right words...` top-note copy.
- `One conversation` kicker.
- `Tell Ada what you want to make.` heading.
- `Describe it as simply as you can...` paragraph.
- Visible Site and Session metadata.
- Visible chat-job terminology.
- `Refresh` button.
- `Talk to Ada` button text.
- `A picture can help...` persistent note.
- Core-decision counters and progress bars from the owner experience.
- Build confirmation, preview, feedback, and provisioning controls from the
  hidden debug drawer.

Keep IDs, hashes, providers, raw draft provenance, and detailed diagnostics in
Developer View.

### Add to the normal chat

- Compact Ada identity bar with a truthful state such as online, replying,
  researching, designing, or needs attention.
- Messages as the dominant surface.
- Ada's initial greeting as the sole onboarding prompt.
- Compact image attachment action.
- Standard message composer and Send action.
- Inline brief-ready action card when appropriate.
- Inline retry state for a failed advice turn.
- A subtle entry point to the complete activity ledger.

When multiple background processes run, do not replace Ada's chat status with
the noisiest process. `Replying` is conversation status; `researching` and
`designing` remain visible in the activity field.

### Activity rendering

Replace `renderTrace()` and its `.slice(-9)`/`.slice(-11)` behavior with an
`ActivityStore` in the page script:

```text
itemsById
orderedIds
latestCursor
hasMoreBefore
pollTimer
connectionState
```

Poll the activity endpoint with `after_id`. Append new items by ID, do not
replace the DOM collection, and deduplicate retries. Render a bounded active DOM
window for performance while preserving cursor access to all older records.
Provide `Load earlier activity` in the full ledger.

Activity polling has explicit degraded and retry states. Do not erase existing
activity when a request fails.

### Accessibility

- Activity text intended for reading meets WCAG contrast.
- New high-priority activity is announced through a concise `aria-live` region;
  do not announce every background event.
- View transitions move focus to the new primary heading.
- The Send and attachment icon controls have accessible names.
- All activity details are keyboard reachable.
- Reduced motion receives the same information without animated entrances.
- Mobile uses an activity sheet rather than text behind chat content.

## Provisioning Handoff

Extend the typed provisioning bundle and importer to carry customer-relevant
incubation continuity:

- Confirmed intake revision and field provenance.
- Meaningful genesis revision history, not only the latest body.
- Owner-confirmed communication preferences and boundaries.
- Approved ongoing Reddit/RSS subscriptions.
- Research requests, source decisions, retained findings, and synthesized
  insights.
- Explicit source/topic exclusions.
- Accepted creative principles and patterns to avoid.
- Design-skill set names and hash.
- Accepted design direction, candidate lineage, and owner feedback.
- Safe activity events required to explain the handoff.

Do not transfer transient polling events, raw chain-of-thought, provider
payloads, debug-only paths, failed candidate implementation transcripts, or
Intake Ada's cross-customer private memory.

Map genesis into generated customer configuration deliberately:

- `creative_identity.principles` informs persona direction.
- `creative_identity.patterns_to_avoid` informs persona taboos.
- `relationship.communication_preferences` informs owner interaction style.
- `relationship.boundaries` remains an explicit runtime constraint.
- `research_identity.subjects` informs source keywords.
- Only approved ongoing sources enter configured RSS/subreddit subscriptions.

Import the accepted history before activation and verify hashes/counts in the
provisioning receipt.

## Failure and Recovery

### Conversation

- Persist the owner message and job before showing it as accepted.
- Disable Send while the current message submission is in flight.
- Permit composing the next message while Ada replies only if ordering remains
  durable; otherwise show a clear queued state rather than silently ignoring
  submission.
- Resume unfinished advice polling after reload.
- Preserve prior activity on retry.

### Research

- Reddit not found, private, rate limited, malformed, and temporarily unavailable
  are distinct safe outcomes.
- A failed candidate does not fail the intake conversation.
- Partial research results remain inspectable.
- Backoff is bounded and visible as `waiting to retry`, not an endless spinner.
- The owner can stop research for the current incubation.

### Genesis

- A synthesis failure does not corrupt the current genesis revision.
- Save revisions with optimistic expected-revision checks.
- On conflict, reload current genesis and recompute once through the application
  service. Do not merge through route code.

### Design

- Confirmation and build submission use stable idempotency keys across reload.
- The Design workspace appears before waiting on the build response.
- Polling errors expose Retry and retain the last known state.
- Preview token failures expose Retry preview without discarding the candidate.
- `needs_repair` and `incomplete` stop only after a meaningful owner state is
  projected.
- A blocked candidate offers Return to conversation and Retry build where the
  underlying contract permits it.

## Implementation Phases

### Phase 1: Simplify the chat shell

Primary file:
`src/site_agent/web/static/intake_lab.html`

Tasks:

1. Remove instructional hero and metadata from the normal chat.
2. Make Ada's greeting the only initial instruction.
3. Replace visible `Talk to Ada` with a conventional Send control.
4. Replace persistent upload explanation with an accessible attachment action.
5. Keep debug metadata in Developer View.
6. Preserve desktop/mobile layout, visible focus, and reduced-motion behavior.

Acceptance criteria:

- A fresh session reads visually as a chat application, not an intake form.
- The first meaningful sentence comes from Ada.
- There is no owner-facing session ID, core counter, or technical status.
- A new user can type and send without reading instructional copy.

### Phase 2: Durable activity ledger

Primary files:

- `src/site_agent/core/incubation_contracts.py`
- `src/site_agent/core/memory.py`
- `src/site_agent/application/incubation_activity.py`
- `src/site_agent/application/incubations.py`
- `src/site_agent/web/intake_lab.py`

Tasks:

1. Add contract, migration, indexes, and Memory methods.
2. Add safe application projection and HTTP cursor endpoints.
3. Dual-write meaningful existing intake, media, genesis, design, and lifecycle
   transitions.
4. Keep domain tables authoritative.
5. Add migration and pagination tests.

Acceptance criteria:

- Activity survives restart and job retry.
- New activity can be fetched after a cursor without duplicates.
- More than 200 activities remain inspectable.
- No activity response exposes private paths, secrets, or raw model content.

### Phase 3: Persistent visible activity field

Primary file:
`src/site_agent/web/static/intake_lab.html`

Tasks:

1. Replace transient terminal traces with the three-channel activity field.
2. Append by cursor and preserve existing items on polling failure.
3. Add evidence detail and full history access.
4. Add mobile activity strip/sheet.
5. Keep Developer View for raw operational diagnostics only.

Acceptance criteria:

- Earlier events do not disappear when a new chat turn completes.
- Research, genesis, and design activity can coexist visibly.
- Refresh restores the same activity history.
- Mobile exposes the same information without obscuring chat.

### Phase 4: Shared design skills

Primary files:

- `src/site_agent/brain/design_guidance.py`
- `src/site_agent/brain/design_intake.py`
- `src/site_agent/application/design_lab.py`
- `src/site_agent/application/designs.py`
- `src/site_agent/hands/opencode_runner.py`
- `src/site_agent/hands/design_visual_review.py`

Tasks:

1. Extract the canonical trusted skill loader.
2. Pass the same skills to intake, planning, builder installation, and review.
3. Persist names/hash in activity and frozen design context.
4. Add typed creative insights to intake output.
5. Preserve conversational behavior and owner authority.

Acceptance criteria:

- Tests prove all design stages receive the same content hash.
- Intake recommendations reflect design doctrine without reciting it.
- Missing required skill content fails explicitly.
- Owner facts cannot be overwritten by creative insight.

### Phase 5: Autonomous bounded community research

Primary files:

- `src/site_agent/brain/incubation_research.py`
- `src/site_agent/application/incubation_research.py`
- `src/site_agent/core/incubation_contracts.py`
- `src/site_agent/core/memory.py`
- `src/site_agent/senses/reddit.py`
- `src/site_agent/main.py`

Tasks:

1. Add durable request/job/insight contracts and storage.
2. Add threshold and deduplication policy after intake revisions.
3. Generate candidate subreddits from model knowledge.
4. Verify and read bounded live public RSS.
5. Add multilingual synthesis with provenance and confidence.
6. Start a dedicated research executor in incubation composition.
7. Emit complete safe activity throughout.

Acceptance criteria:

- A qualifying intake can continue chatting while research runs.
- A French intake can retain a French insight synthesized from an English
  subreddit with the source language recorded.
- A hallucinated subreddit is rejected by validation and never becomes a fact.
- Rate limiting cannot block or fail the chat turn.
- Reprocessing the same revision does not duplicate a research pass.

### Phase 6: Incremental genesis and business understanding

Primary files:

- `src/site_agent/application/customer_genesis.py`
- `src/site_agent/application/design_intake.py`
- `src/site_agent/application/incubation_research.py`
- `src/site_agent/core/incubation_contracts.py`

Tasks:

1. Propose genesis after meaningful intake and research changes.
2. Add exact field evidence and replace/remove correction semantics.
3. Add typed business-understanding and creative-identity projections.
4. Emit concise activity diffs.
5. Wire approved business knowledge into incubation design context.

Acceptance criteria:

- Genesis evolves before intake confirmation.
- Duplicate/no-op input creates no revision.
- Owner correction supersedes an external inference.
- Excluded research stops influencing later revisions.

### Phase 7: Conversation to Design transition

Primary files:

- `src/site_agent/web/static/intake_lab.html`
- `src/site_agent/application/incubations.py`
- `src/site_agent/application/intake_lab.py`
- `src/site_agent/web/intake_lab.py`

Tasks:

1. Add inline brief-ready action card.
2. Add URL-addressable owner view state.
3. Navigate to Building immediately on owner confirmation.
4. Render durable pipeline activity and elapsed time.
5. Resume chat and run polling on boot.
6. Align incomplete/repair lifecycle projections.
7. Add page navigation and durable preview recovery.
8. Add owner-facing feedback and recovery actions.

Acceptance criteria:

- The owner is never left in apparently idle chat after requesting a design.
- Reload during confirmation or build restores Building.
- A reviewable candidate appears automatically without opening Developer View.
- Preview survives summary refresh and token expiry.
- No design acceptance publishes production.

### Phase 8: Design-context and provisioning continuity

Primary files:

- `src/site_agent/application/designs.py`
- `src/site_agent/hands/opencode_runner.py`
- `src/site_agent/application/provisioning.py`
- `src/site_agent/core/incubation_contracts.py`

Tasks:

1. Add typed incubated creative context to the design request.
2. Preserve initial-homepage isolation while passing validated customer context.
3. Update art-direction policy to consume genesis and research insights.
4. Extend provisioning bundle/import with accepted incubation continuity.
5. Map relationship, creative, and research identity into customer config.
6. Verify imported hashes, counts, and subscriptions before activation.

Acceptance criteria:

- The builder receives the same accepted creative principles visible during
  intake.
- Existing-site visual context remains excluded from initial design.
- Provisioned Customer Ada retains accepted personality and research context.
- Only approved ongoing sources become customer subscriptions.
- Activation remains explicit and idempotent.

## Test Plan

### Contract tests

- Reject unknown activity categories, states, and provenance values.
- Reject invalid confidence and malformed correlation IDs.
- Round-trip activity, research request, insight, and design-skill projections.
- Prove model recommendations cannot become owner-confirmed provenance.
- Prove source language and translated owner-language summary remain distinct.

### Persistence tests

- Migrate schema 31 to the new schema without losing existing data.
- Append and paginate activity across more than 200 events.
- Preserve activity across restart and retry.
- Deduplicate research jobs by normalized revision context.
- Preserve all meaningful genesis revisions.
- Verify latest-first and cursor semantics at projection boundaries.

### Research tests

- Known candidate subreddit resolves to bounded RSS documents.
- Missing/private/rate-limited candidates produce distinct outcomes.
- English evidence can produce a French synthesized insight.
- Untrusted feed instructions cannot invoke tools or mutate state.
- Research never overwrites owner-confirmed facts.
- Owner exclusion blocks future reads and synthesis.
- Chat completion is independent from research completion.

### Design-skill tests

- Canonical loader order and hash are deterministic.
- Intake, planner, builder, and reviewer receive the same hash.
- Intake stays conversational with skill guidance present.
- The builder receives incubated creative context for `initial_homepage` while
  existing-site context remains absent.

### Application tests

- Intake revision emits understanding activity.
- Research synthesis emits insight and genesis activity.
- No-op genesis proposal creates no revision.
- Brief confirmation and build submission remain idempotent.
- `needs_repair` and `incomplete` map to explicit owner states.
- Provisioning transfers accepted context and omits unsafe activity.

### UI tests

- Fresh HTML has no instructional hero or `Talk to Ada` text.
- Fresh conversation displays Ada's greeting.
- Send and attachment controls have accessible names.
- Activity appends by cursor without deleting older items.
- Reload resumes unfinished advice, research, and design polling.
- Ready brief displays the primary design action in conversation.
- Selecting the action switches to Design immediately.
- Ready run automatically loads the candidate and page selector.
- Preview token failure is retryable.
- Mobile activity sheet and reduced-motion mode preserve information.

### Live smoke test

Use a fresh isolated Intake Lab database and synthetic business identity.

1. Open the page and confirm the first instruction is Ada's greeting.
2. Describe a French-language specialist business.
3. Continue chatting while background research starts.
4. Confirm candidate English subreddit activity appears with provenance.
5. Confirm a translated French insight and genesis revision appear.
6. Confirm previous activity remains visible after another chat turn and reload.
7. Confirm the brief and enter Design.
8. Reload during build and verify progress resumes.
9. Review every candidate page.
10. Record feedback and verify it updates genesis/activity.
11. Accept and inspect the provisioning preview without activating.
12. Provision explicitly and verify transferred personality/research/design
    context in the destination database.

## Verification Commands

Run focused tests after each phase, then:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
git diff --check
```

## Definition of Done

This work is complete only when:

- The default Intake Lab is a simple Ada-led chat without instructional clutter.
- Ada's observable work accumulates persistently around the conversation.
- Relevant public Reddit/RSS research can begin automatically during intake.
- Cross-language research is translated with original provenance retained.
- Customer Ada's personality evolves incrementally and visibly.
- Intake, planning, implementation, and review share one canonical design-skill
  set.
- Accepted incubation context materially reaches the initial design build.
- Requesting a design immediately transitions to a visible waiting workspace.
- The candidate appears automatically in the Design review workspace.
- Reloads recover conversation, research, activity, build, and preview state.
- Provisioning transfers the accepted personality, research, and design context.
- No background process publishes, provisions, subscribes, or activates without
  the required explicit owner operation.
- Focused tests, the full suite, compilation, wheel build, diff check, and the
  retained-workspace browser smoke test all pass.
