# Growth service dashboard — acceptance record

This record separates implementation, immutable artifact publication, API activation,
customer rollout and authenticated acceptance. An unfinished row is not a pass.

## Source changes

- The shared admin consumes `growth-service-v1` directly. Its five expertise areas
  use explicit primary/secondary area relationships; no title-based categorization.
- One canonical decision list joins service-model IDs to existing task review
  handlers. Area cards do not create parallel approvals.
- Preparation, evidence limitations, actual next assessment and verified results
  come from the same service projection. Unclassified history is secondary.
- Artifact inspection requires the canonical dashboard and rejects the invented
  `task.area` model. Existing exact review, hash and publication gates remain.
- Collected Growth material is checkpointed before artifact persistence. Resumption
  binds the exact saved material before assessment/preparation. Existing artifacts
  for that run must match; conflicting evidence fails closed. No database repair,
  new scheduler, re-collection, approval bypass or fallback is introduced.

## Real observations before this release

- Both registered live tenant API responses pass the new UI contract validator.
- Oceanic exposes three canonical decisions: owner-information initiative 4 and
  exact ready proposals 7 and 8. Prepared proposals retain their draft/action/hash
  lineage and pass the existing readiness projection.
- Additional Oceanic findings wait for candidate capacity; they are not reported
  as active execution. Historical unresolved effects remain unresolved.
- Atelier exposed a preparation failure (`evidenceArtifactId` missing). Its durable
  run held collected material and a completed assessment but no evidence binding.
  The shared phase correction above addresses that boundary, not a tenant patch.

## Required evidence still to record

### October 23 live checkpoint (not final acceptance)

- API release `20261023-api-growth-evidence-checkpoint-1` serves source
  `553af9e67cfe00217351f183215a24cdf4962dc8`.
- Shared admin `0.10.27` is published with SHA-256
  `cec50a0f484a32767df23cd4f4e45479b8778b53d67260afb5a8a6f38d668882`.
- Oceanic release `runtime-20261023124308-e9201db1` and Atelier release
  `runtime-20261023125035-919f680d` passed deployment gates. Authenticated fresh
  documents show the five-area overview. Oceanic shows prioritized decisions
  8, 7 and 4; Atelier's answer control opens initiative 3 with its actual question.
- Visual checking found additional-decision title overflow. The narrow wrapping
  correction is implemented in the newer source/package below; it is not yet live.
- The normal Atelier retry exposed a second root failure: the evidence artifact
  embeds the entire durable inventory and exceeds the 100,000-byte contract.
  The source correction is implemented without raising the cap or discarding
  checkpointed evidence; activation and live recovery remain pending.
- A prepared Payload candidate's revision link needed an end-to-end exact-target
  revision contract, not merely a chat link. That source correction is implemented;
  exact live review acceptance remains pending.
- Approved paid acceptance cycle `growth-b6413f1b850241b5baf8bfc30e140b78`
  selected idea 12 for `article:2026-W43`. No provider request or reservation was
  created: the exhausted allowance was incorrectly classified as uncertain.
  The typed allowance correction is committed as `f82216a`, not yet activated.
  The owner-approved monthly cap of 700,000 micros is saved in the canonical
  tenant config; the next queued API release must load it. No history was reset.
- Browser transport disconnected intermittently during deeper review checks.
  An unobserved click or transport timeout is not recorded as a product pass.

### Reviewed source and immutable admin artifact (activation pending)

- PR #297 source commit `06743d4fb89b711c721e55bf363921e77422efaa` contains the
  dashboard wrapping, bounded evidence checkpoint, exact-target revision and
  typed allowance corrections. Source implementation is recorded; API activation
  and customer-visible recovery are still pending the root release checks.
- The `payload-admin-v0.10.28` publication workflow completed successfully for
  that exact commit: workflow run `39974996739`.
- The authenticated immutable tarball is
  `weareheadless-helloada-payload-admin-0.10.28.tgz` (asset ID `669479709`). Its
  package identity is `@weareheadless/helloada-payload-admin@0.10.28`; SHA-256 is
  `95ed679fdd54e04853d4db02a6cbd39d2e331c303187b1d0d3af5b2a8484c7dc` and
  lockfile integrity is
  `sha512-BLSjJlQPniS9Lt6wpmoyxBJb1xJJ6vtXUKFn5664ursu/1clZ326AYtbGEHzlxkUlWpo2Dtc5zKhUOLu6KSIrw==`.
  The downloaded bytes, GitHub asset digest, package contents and canonical
  `site_agent.credentials` release-asset verifier agree.
- Focused release/API/queue/template/dispatcher/credential tests passed: 162.
  The shared admin package suite passed: 54. The focused template
  `payload-first-contract.test.mjs` passed. At the earlier checkpoint, before
  the held-merge review fixes below, the full backend suite passed 1,654 tests
  (three deprecation warnings); compile checks and wheel build passed. Those
  earlier results do not include the later fixes.
  A clean canonical starter install, typecheck and Next.js build passed using
  pinned Node 22.23.3/npm 11.13.0 and the authenticated immutable package bytes.
- Independent held-merge review found that an exact Growth revision request
  could race approval or decline while it was validating and placing the old
  candidate on hold. The narrow fix now serializes revision enqueue, approval
  and decline through the existing review lock; it adds no second approval
  state or lock.
- The review also found that a revision job failure after enqueue needed to
  distinguish a safe pre-dispatch refusal from a possibly attempted Payload
  write. `run_job` now invokes the shared restoration helper: safe pre-dispatch
  refusal restores the original review candidate, while an attempted or
  uncertain write remains held and uncertain for reconciliation. It is not
  reported as restored or retried automatically.
- Concurrency and job-failure regression tests reproduce the missing-lock and
  pre-dispatch recovery failures. The corrected workspace suite passed 40 tests;
  Growth/recovery/orchestration checks passed 60 tests. The final full backend
  suite passed 1,658 tests (three deprecation warnings); compile and wheel build
  passed for the corrected source.
- The scaffold now pins v0.10.28, but this publication is not a customer
  deployment. API activation, canary/fanout receipts and fresh authenticated
  review/browser evidence remain outstanding. No API-live claim is made.

- Official-main API release receipt for the implemented evidence/revision and
  allowance corrections.
- Canonical canary/fanout receipts for shared admin v0.10.28.
- Fresh authenticated populated overview and exact review screenshots.
- Normal scheduled recovery of Atelier's interrupted assessment.
- Controlled approve/revise/decline and verified outcome acceptance.
- Automatic paid-research-to-article acceptance requires explicit research approval;
  an ordinary draft chat write is not a substitute for that pipeline.

No customer recommendation is approved by this engineering record. No paid
research authorization or browser acceptance is implied by passing source tests.

The corrected API source queued by this activation is `4c0dd35fc387a44a7ed829024900cdd5dad3955e`; its regular merge must preserve that exact source commit on official `main`. It retains the verified admin v0.10.28 pins. This is a queue/source identity, not proof of activation.


## Live API and shared-runtime checkpoint after PR #298

- PR #298 merged as `ca93a0a60e8eea6899fd486bbeaaff46e2566033` after CI
  `39982246691` passed. The official timer deployed API
  `20261023-api-growth-exact-revisions-1`, exact source
  `4c0dd35fc387a44a7ed829024900cdd5dad3955e`, with `health-passed` receipt and
  wheel SHA-256 `31479855a170663b17ec71a76763136e8e00c2460fdc64908c1299f998e8b334`.
- Shared admin `0.10.28` reached all five enrolled targets with runtime
  fingerprint `4b92e52f1012eda448606f78cf810e10e8883edca19ef98d49333fb82307ba84`:
  Oceanic `runtime-20261023160538-489ce2d9`; Atelier
  `runtime-20261023161333-e1bce43e`; Northstar full-intake validation
  `runtime-20261023161333-d591c51f`; handoff validation
  `runtime-20261023161333-c1d378af`; Inmersion
  `runtime-20261023161333-3e08d411`. Each receipt is deployed and explicitly
  awaits browser verification. These are deployment passes, not visual passes.
- Atelier's normal authenticated retry reused run
  `growth-d72520e9c9dd434f9e3cbdacdf56a440`. The scheduler reused the saved
  material and assessment, persisted evidence artifact 6 with material reference
  `growth-run:growth-d72520e9c9dd434f9e3cbdacdf56a440:material` and exact material
  hash `d5e07e04181930c7a00901c7026b800bf0b5c13e7abf6f204d8bdb902caf4d12`,
  then produced ready initiative 7, draft 14, action 2 and approval 1. Its exact
  review hash is `sha256:aa7a1b05d4476a66ba07275836d77c82f909060075450cfc0f537cd651c9d5ff`.
  Another item remains preparing; the whole run is not declared complete.
- Fresh service-token GET projections passed the actual shared admin contract
  and priority checks on pinned Node 22.23.3. Oceanic's validating initiative 8
  was not approvable; independent initiative 7 remained ready. Atelier exposed
  ready initiative 7 plus owner question 3. The exact Northstar tenant is
  `northstar-coffee-full-intake-validation-5a8564dae07494ec`; its five areas
  truthfully remain awaiting activation with no registered published website.
  Service-token API checks do not substitute for owner browser acceptance.
- The owner explicitly approved the unchanged idea-12 payload to CrawlSEO for
  one keyword-overview/SERP cycle, at most US$0.20 additional and no publication.
  Keyword run `cmvl5yvca000xoy5bfmbfvn43` completed (reported provider cost
  12,240 micros). SERP run `cmvl7hglr0011oy5ba5fdtawl` failed with
  `DATAFORSEO_TASK_40101_INTERNAL_SE_SERVER_ERROR_`; no SERP provider task/cost
  was returned and no draft was created. Seven settled allowance reservations
  total 700,000 micros; that is the allowance ledger, not proof of actual
  provider billing. No second cycle, paid retry, reservation reset or publication
  is authorized or executed.
- Draft-only revision initiative 8 queued durable job 69/conversation 49 against
  draft 63 and the original exact hash. Published posts/4 stayed at canonical
  hash `sha256:0cd872a6e466c6a77b396f3a704fec65e9634a685c66361e451c106573fefc37`
  and `updatedAt=2026-10-16T01:54:14.693Z` before revision. Live execution exposed
  a false base conflict: a subset edit was hashed against a base covering the
  complete reviewed field scope. Runtime activation then interrupted the job
  before any recorded Payload write, leaving its prior review held. Shared guard
  and terminal-job recovery corrections are being validated; neither a new
  revision hash nor successful revision acceptance is claimed yet.
- The owner confirms the in-app browser is signed in. This chat currently has no
  browser inspection tool or reachable host browser/CDP session. Fresh DOM,
  screenshots, keyboard/mobile/language checks and live controlled decisions
  therefore remain unverified; sign-in itself is not the missing permission.

Issues #267 and #268 remain open. The external SERP failure and unavailable
browser inspection prevent complete end-to-end acceptance; independent source
and deployment work above is recorded separately.


### Corrective API-only release staged after live revision checks

Source `b40e7769cdac735d6a2c839309fe706a8bb6802d` corrects the base guard to
hash all reviewed fields while retaining the bounded edit subset. It also
reconciles terminal Payload revision jobs through the existing Growth pending
job: exact saved receipts finalize without a second write, a recorded attempt
without a receipt remains uncertain, and a verified pre-write interruption
restores the original review. Missing job-ID checkpoints are left alone so an
active enqueue cannot be mistaken for an abandoned job. The existing activation
wake predicate recognizes these terminal linked jobs; there is no second
scheduler or status-reset repair script.

The editor regression reproduced the false conflict before the fix. Focused
editor tests passed 32; Growth/recovery tests passed 48. The full backend suite
passed 1,663 tests (three deprecation warnings), release/dispatcher checks passed
142 tests, and compile plus corrected wheel build passed. API request
`20261023-api-growth-interrupted-revision-recovery-1` is staged for that exact
source and is not yet activated. Shared admin/runtime inputs are unchanged, so
this correction requires no new private package or Worker fan-out. A fresh
canonical read after the completed rollout still matches the saved posts/4
published baseline exactly; no customer publication was performed.


### Corrective API activation and interrupted-job recovery proof

PR #299 merged as `80ec863f96a76fc5d6c5e462ddcb874b2eddcbe5` after CI
`40010974707` succeeded. The official timer deployed
`20261023-api-growth-interrupted-revision-recovery-1`, source
`b40e7769cdac735d6a2c839309fe706a8bb6802d`, with `health-passed` receipt;
wheel SHA-256 is `8450e3eeacfbd98c098790c5322483c8477f748bc9a5e985447c737f1491e417`.
The shared runtime fingerprint stayed unchanged and the existing five Worker
receipts remain the deployed identities.

The new API's normal scheduled reconciliation restored initiative 8 from
interrupted job 69 to `ready_for_review`, retaining original draft 63/action
24/approval 2 and exact old hash. The revision hold was removed through the
shared recovery service; no database patch, direct restoration helper, or
Payload mutation was used. Initiative 7 retained draft 62/action 23/approval 1
and its original review hash. This proves the previously stopped item recovered.

After a fresh published-base check, the normal authenticated chat API queued
one draft-only retry as job 70/conversation 50. Its original approval remains
pending but held during preparation. The retry result is still being observed;
a new candidate/hash is not claimed until its exact lineage and unchanged
published base are verified.


### Final observed retry outcome: held destination operation, no acceptance pass

Job 70 reached the corrected published-base guard, then the native Payload
write boundary returned HTTP 409: an older Ada operation is still preparing the
document. The job retained `writeAttempted=true` without a persisted success
receipt, exhausted its bounded tool loop, and ended `error`. Initiative 8 remains
`validating` with revision status `uncertain`; its original approval stays held.
No write replay, lock clearing, SQL patch, fabricated receipt or approval was used.

Read-only registered D1 inspection identifies the exact pre-existing operation:
`draft:oceanicvibes:posts:4:sha256:644734dbd66755ac06c16e1203e1145d28f43c8369f398dd9ba72c48f3e03cea`,
state `uncertain`, created October 22. Posts/5 has a corresponding uncertain
operation for initiative 7's exact package. These are older destination receipts,
not newly created operations from this retry. A final canonical read shows
published posts/4 still has the saved baseline hash/timestamp and the current
draft still matches the original candidate, with
`updatedAt=2026-10-22T11:28:19.871Z`. Unchanged observations are recorded as such;
they are not substituted for an exact revision write receipt.

The next canonical repair must reconcile the matching historical preparation
receipt through the existing exact destination service before offering resumed
work as executable. Source inspection found that resumed preparation skips
`apply_growth_candidate` when the draft already equals the candidate; that can
leave the older uncertain operation behind even after candidate validation.
The existing destination `/growth/apply` path can reconcile an already-claimed
exact operation by verifying its effect/preview without replaying the content
write. Job 70 additionally requires a supported exact non-effect/receipt
reconciliation before its hold may be removed; a generic 409 or manual marker
reset is not enough. These obligations remain open, alongside the provider SERP
failure, browser inspection access, and live approve/revise/decline acceptance.

This record therefore documents successful source tests, API activation,
five-tenant package deployment and Atelier recovery, but explicitly does not
claim complete Growth or dashboard acceptance.

### Obsolete operation cleanup implementation (activation pending)

The user explicitly requested removal of obsolete operations that no longer fit
current sites. The shared cleanup contract now supports protected operator
plan/apply retirement, with exact operation/version and current document proofs.
It preserves customer content, unpublished drafts, valid approvals and historical
uncertainty. Abandoned preparations become terminal withdrawals; a failed
revision hold can be released only after verifying its exact prior candidate,
approval, published base and destination preview. The transaction retains the
failed job's attempted-write/error audit. See `growth-operation-cleanup.md`.

The two current Oceanic preparation operations (posts 4 and 5) were reconciled
through the existing canonical `growth/apply` service, without repeating their
content writes. Durable maintenance receipts record unchanged published/draft
hashes and timestamps. Four obsolete uncertain preparations and job 70's held
revision remain pending deployment of the new protected cleanup contract.
Atelier pages 48 has unpublished changes; its draft must be preserved.

The complete backend suite passed 1,670 tests (three existing Pillow deprecation
warnings). The six focused Worker contract files passed, including real SQLite
retirement compare-and-swap and draft-preservation checks. A clean canonical
starter install, typecheck and Next.js build passed, and the wheel built.
Final review corrections and official CI are recorded separately when complete.
No new paid research or customer publication was performed during cleanup.

Final review tightened both local retirement retry paths to require the same
operator attribution and plan proof. The complete workspace/gateway suites then
passed 54 tests. The Worker retirement regression is included in official
Payload release CI. No cleanup endpoints were invoked before activation.

### October 23 obsolete-operation cleanup: live resolution

PR #301 merged as `41efaecbd5cf5367f481ac118e56584c312346a4` after all
five official CI jobs passed (workflow `40023314487`; final backend suite
1,670 passed). API `20261023-api-growth-operation-cleanup-1` activated exact
source `8f5f323b79e87f3637b3d75e39f2818d2c58bec2` with a `health-passed`
receipt. Its wheel SHA-256 is
`a7809b7310a7a1b57806d3ed1f1cf370847e027905c43943b893beff4d00468c`.

Shared Worker fingerprint
`c7a3c153f4ac380416942edbf351bc8c3d567331fcc7dd2562e0b2cac9e3bc9f`
passed the Oceanic canary (`runtime-20261023210713-a32a59e3`) and deployed
to Atelier (`runtime-20261023211412-16bfc3ed`). Both have authenticated
Worker round trips and the new `obsoleteOperationRetirement` capability.
Their deployment receipts still say `awaiting-browser-verification`; this is
not a visual acceptance pass. The other three automatic fleet releases are
still being observed at this checkpoint.

The first operator plan refused to use the historical bootstrap schema as
current identity. The helper was corrected to bind the immutable deployment
receipt's schema and the live authoring contract. No cleanup call was applied
until those identities agreed.

The user's explicit cleanup request was applied through the protected shared
control plane, never SQL patches or direct Payload document writes:

- Oceanic initiative 6/posts 6 and Atelier initiatives 1/pages 54,
  2/pages 24 and 4/pages 48 are `superseded`. Their exact old destination
  operations are terminal withdrawals with `effectStatus: unknown`; history
  was retained rather than reclassified as successful content changes.
- Oceanic initiative 8/job 70's obsolete revision authority was retired after
  current published-base, exact prior candidate, approval and renderer proof.
  Initiative 8 is again `ready_for_review`. The failed job's attempted-write
  marker and error history remain recorded.
- All four affected documents retain identical published/draft content hashes
  and `updatedAt` values before and after cleanup. Atelier pages 48's distinct
  unpublished draft is preserved. Published Oceanic posts 4 also retains
  canonical hash `sha256:0cd872a6e466c6a77b396f3a704fec65e9634a685c66361e451c106573fefc37`
  and `updatedAt=2026-10-16T01:54:14.693Z`.
- All three current proposal lineages and pending approvals are preserved.
  The only changes to those review records are initiative 8's transition from
  `validating` to `ready_for_review` and removal of its obsolete draft hold.
- Read-only D1 verification across all five rollout tenants finds zero
  `writing` or `uncertain` operations. Oceanic retains three terminal rows,
  Atelier four; the other three tenants have none. No rows were deleted.
- Five completed mode-0600 operator receipts and immutable mode-0400 plans are
  retained under each affected registered tenant's
  `data/maintenance/growth-operation-cleanup-20261023`, using request ID
  `growth-operation-cleanup-20261023-current-snapshot-v1`.

Fresh Oceanic, Atelier and Northstar canonical Growth responses pass the shared
admin's `isGrowthServiceModel` validator with five areas. Oceanic decisions are
4, 7 and 8; Atelier decisions are 3 and 7. Northstar still correctly reports
`websitePresent: false` and no owner decisions. Retired preparations are
terminal history and cannot be approved or replayed.

No replacement revision, customer approval/publication, additional paid
research, spend-ledger reset or provider retry was requested during cleanup.
The already failed approved SERP cycle remains a provider failure. The current
tool session has no browser inspection capability, so visual/click-through
acceptance remains unverified despite the user's signed-in browser being open.
