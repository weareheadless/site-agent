# Canonical Growth operation cleanup

Cleanup uses the current registered tenant, shared API, and Payload gateway.
It does not delete customer content, publish a proposal, clear SQL locks by hand,
or infer that an uncertain historical write never happened. An old receipt can
be concluded while its history and the current draft remain intact.

## Current prepared proposals

Resumed preparation and revision preflight always re-enter `growth/apply` for
the exact package. An existing claimed operation is reconciled from its exact
published base, draft and renderer proof without replaying its content write.
A matching draft by itself is insufficient: the destination operation must be
settled before the proposal is offered or held for revision.

## Obsolete preparation intent

The operator control plane exposes
`POST /v1/control-plane/websites/{website_id}/growth/initiatives/{initiative_id}/retire-preparation`.
It requires the existing protected control-plane credential and a registered
blocked Payload initiative with no draft, approval, artifact or review package.
Ordinary workspace bearer authentication cannot invoke this operation.

Plan mode binds the saved preparation target, explicitly selected old operation
key/hash, current schema and full published/draft snapshot, and the exact D1 row
version/result hash. Apply requires that unchanged plan, a bounded reason and a
stable operator request ID. The service explicitly preserves the current draft,
including unpublished changes. The destination records the obsolete intent as
withdrawn with `effectStatus: unknown`, rather than claiming a historical
no-effect result. Local work becomes `superseded` only after that receipt exists.

The Worker requires the `obsoleteOperationRetirement` capability and accepts the
fixed `growth/retire-obsolete` path only for the authenticated service principal.
Exact-package retirement remains available when its immutable package survives;
`current_site_snapshot` explicitly withdraws an obsolete intent when that package
preimage is unavailable. Both require an exact uncertain preparation row, never
a currently writing row. Apply repeats the reads and uses compare-and-swap on
tenant, operation, target, package hash, prior result and row version.

Retirement retains the row and prior result in a terminal `completed` receipt
with `ok: false` and `disposition: retired_obsolete`. This is a concluded cleanup,
not a successful content change. Validate, apply and publish refuse reuse of
that retired package. Matching retries return the saved receipt only for the
same request and proof identity. A different request or changed proof conflicts.

## Obsolete failed revision request

The corresponding control-plane path ends in `retire-revision`. It binds the
terminal job ID and exact prior review hash. Plan verifies the published base,
current draft, artifact and pending approval. Apply reconciles the prior exact
preparation, verifies its preview, repeats the reads and atomically records the
retired revision audit while releasing the original review hold. The job error
and attempted-write marker are preserved; this is explicit cancellation against
verified current state, not an automatic claim that the old write had no effect.
A revision with a success receipt follows normal exact-receipt recovery instead.

## Operation and release rules

Keep mode-0600 before/after operator receipts under the registered tenant's
`data_dir/maintenance`; do not store content bodies or credentials there. Bind
runs to the deployed API SHA and shared runtime fingerprint. Keep the plan and
operator request ID for safe response-loss recovery. Proof drift stops cleanup
and requires a new reviewed plan.

Release shared API and Worker changes through official-main desired queues and
`helloada-release.timer`. Wait for the target Worker capability before using
obsolete-operation retirement. No schema migration or private admin-package
publication is needed for this contract. Verify current hashes and revisions,
terminal destination receipts, local work dispositions and remaining active
operation counts after applying cleanup. Browser and owner-decision acceptance
remain separate gates.

## Obsolete local article generation attempts

`POST /v1/control-plane/websites/{website_id}/growth/drafts/{draft_id}/archive`
is a protected operator plan/apply path for obsolete pending local article
attempts. It does not call the owner-decline service, decide approvals, delete
content, or mutate Payload. Only unlinked records are eligible: current owner
actions, initiatives, publication references, destination/candidate receipts,
and active or uncertain research prevent archival. A saved blocked sync record
may be retained only in its minimal state/validation shape, with no destination
operation or effect identity. Retirement explicitly leaves historical external
effect unknown rather than asserting that an old dispatch never occurred.

Plan returns `proofHash` and `contentHash` without body text. Apply requires
`expected_proof_hash`, bounded `reason`, and stable `operator_request_id`.
Changed copy/metadata/state or newly linked work conflicts. Matching retries
must retain the same request, reason and proof. The original title/body/meta
are preserved, with `operator_archive` attribution added; local status becomes
`discarded`. The normal active article projection and preparation loop exclude
it while the retained draft remains inspectable in history.

Article preparation, failure recording and archival share a tenant Memory
lifecycle lock in the canonical single API process. Atomic archival also
rechecks ledger relationships within its SQLite transaction. A preparation
already running must finish before cleanup can recheck its proof; an archived
record cannot dispatch a new mirror or be revived by a late failure callback.
Use the standard exact-source API release before invoking this new path.
Published article consolidation remains a separate exact owner decision.
