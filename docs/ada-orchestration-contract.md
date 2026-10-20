# Ada orchestrates; OpenCode implements a delegated task

Tracking: #243, #244, #245, #246.

`repo_changes.source_authoring_contract` and `source_path_allowed` define the
same source boundary for the planner, handoff and final builder validation.
Managed Next/Payload source plans declare exact `source_paths` and
`acceptance_criteria` before delegation. A tenant allowlist never overrides
the platform ownership boundary. Shared routing, schema, admin, authentication
and platform SEO source require a Site-Agent release; editable SEO content
remains in the shared Payload fields. Unsupported plans are refused before
starting the builder.

Ada receives a read-only snapshot of recent jobs in this conversation, with
their real state, progress, failure boundary and draft identity. The model
interprets the owner's current request. No phrase classifier decides whether a
message is a status question; an earlier failed task is not new authorization.

OpenCode receives the explicit source brief, relevant business facts, planned
files, acceptance criteria, ownership contract and saved Payload receipts.
`source_kind` is a model-declared task property: maintenance uses focused
engineering instructions; presentation retains the design skills. General
memory, persona, full conversation and unrelated site reference dumps are not
injected into these task handoffs. Further file inspection stays available.
The existing typed intake/design snapshot pipeline remains authoritative for
initial design; it is not replaced by this maintenance handoff.

Terminal owner-job failures persist one assistant outcome and retain partial
receipts in the same transaction as the job's error state. Worker failures,
restart interruption and stale-job detection share that persistence rule.
The admin displays the saved reply immediately and restores it on reconnect.
Technical error details remain on the job; an error is never successful work.

`builder_context` timing records contain input-component byte counts, not
estimated token counts or prompt text. `builder_step` records contain each
provider-reported token measurement and the elapsed inference/tool interval.
Output and reasoning are recorded separately; provider cache counters retain
their reported meaning. Aggregate input totals include repeated context across
steps and are not the size of a single context window.

API changes use `deploy/desired-api-release.json`. The owner UI is a versioned
Payload admin package and uses the shared-runtime canary/fan-out release path.
Acceptance includes a fresh authenticated status-only conversation: it should
report the actual previous failure without launching another builder.
