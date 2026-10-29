# UI-056 contract recovery evidence (partial)

**Status: PARTIAL source improvement, not recovery or issue completion.** The producer/consumer contract now has one required-field map and one generated description shared by the native direction agent and specialist creative-selection prompt. This aligns source instructions; it does not implement a correction attempt, prove a provider response, resume a failed plan, or deliver a candidate. The incident correlation record reports an invalid `utility_behaviors[0]` record with `id`, `trigger`, and `response`, but no `meaning`, and a narrative record also missing meaning. It rules out aliasing. No raw customer creative/intake content is reproduced here. The failure boundary remains `confirmed intake -> Ada planning -> typed experience plan`; downstream generation was not reached.

## Typed contract and producer instructions

`src/site_agent/core/design_contracts.py:BRAND_BEHAVIOR_NAMED_RECORD_FIELDS` is now used by both `BrandBehaviorSystem.from_dict` and `brand_behavior_contract_description()`. The field map preserves strict existing rules: conceptual entities, state variables, input signals, forces/relationships, utility behaviors, and narrative behaviors require non-empty string `id` and `meaning`; output channels require `id` and `property`; scene graph records require `id` and `exit_condition`. Named arrays can be empty. Signature behavior remains an object with non-empty string `id` and `meaning` plus non-empty string-array `acceptance_conditions`. The prompt description also distinguishes object, scalar, and optional string-array fields. No schema version, persisted shape, or validation rule was relaxed.

Producer A is `_write_native_direction_agent` in `hands/opencode_runner.py`; producer B is the creative-selection `selection_prompt` in `SpecialistDesignCoordinator.create_plan` (`application/design_orchestration.py`). Both now insert the same generated description. Tests assert the complete generated native prompt and capture the actual specialist `invoke` request using the existing fake invoker. Nonstructured native direction remains on its prior prose-only path. These are source/fixture checks, not live provider evidence.

## Existing validation retry and durable specialist phases

There **is** an existing validation retry in `SpecialistDesignCoordinator._invoke_phase` (`design_orchestration.py`, around lines 864–1009): it makes at most two provider attempts, adds a bounded `retry_hint` after a `ContractError`/`DesignOrchestrationError`, calls the optional `validate_artifact` callback before completion, and persists claim/complete/fail through `claim_design_phase`, `complete_design_phase`, and `fail_design_phase`. Timeout errors (`"timed out after"`) suppress that retry. `_validate_selection` calls `_strict_experience_plan` from the selection validation callback, so this strict parse is within the existing loop. Do not layer a second specialist recovery loop over it. The correction behavior still needs explicit exhausted/budget/dedup acceptance; this phase does not claim those criteria are proven.

The native path differed in the baseline. `run_opencode_turn` returned its completed result first; native `_native_direction_payload` parsing and `ExperiencePlanBundle` validation occurred after that return (around `opencode_runner.py:2601–2605`). On failure, the transcript was persisted, but no equivalent typed-plan correction attempt or durable native phase claim/completion artifact existed. The specialist loop therefore could not simply be assumed to protect native direction parsing.

## Earlier native timeout, accounting, and resume audit

- At the time of this audit native direction did not pass memory to its usage finalizer. PR464 subsequently added that accounting sink; both direction and Build now pass canonical memory. OpenCode usage/cost is logged after the turn as `origin="internal_builder"`, not as admission policy. The owner override removes any newly proposed UI-056 admission guard; unrelated existing authorization/spend checks and provider quota/failover remain unchanged.
- `DesignService.execute_build` (`application/designs.py:1643–1704`) advances PLANNING to BUILDING **before** calling the builder and persists `build_request`/`build_target`. The native structured response is parsed only after the direction turn completes; integrated composition is persisted only after successful parse. On a thrown build error, `DesignJobWorker._run` transitions the run to FAILED (`application/design_jobs.py:682–697`). Restart handling is `DesignJobWorker._recover_queued` (`design_jobs.py:392+`): it re-enqueues created/assessing/planning runs with a queued event and PLANNING runs with persisted request/target; other BUILDING runs are marked INTERRUPTED (lines 424–430). Failed runs are not selected for resume. Thus the saved request/target and composition persistence are useful existing durability boundaries, but do not checkpoint/resume failed native parsing or establish repair identity/deduplication.

## Evidence limits and remaining parent acceptance

The correlation record documents the observed incident response shape; this local source audit does not independently prove which deployment SHA executed it. No customer replay, paid provider call, tenant write, candidate generation, deployment, or live verification occurred. The owner override removes the proposed UI-056 inference/admission budget guard; unrelated existing spend/authorization gates remain unchanged. The full parent acceptance still includes later failed-run lifecycle recovery, canonical deployment and disposable live proof.

## UI-056 bounded planning/Build boundary (source slice)

The native creative direction phase uses the existing `design_run_phase_artifacts` store with `native_direction` and `build_dispatch` identities. Claims use an explicit SQLite `BEGIN IMMEDIATE`, so independent `Memory` connections serialize the claim rather than relying on a per-instance lock. Phase identities bind canonical request, target, context snapshot and supplied/frozen asset hashes. A completed direction checkpoint carries the typed plan and native direction; a matching entry hydrates those values. Identity drift fails closed.

Only a returned invalid typed plan is eligible for one correction. Its response, transcript and exact parser diagnostic are durably failed before correction is claimed; the correction reuses the frozen request and attached assets. Provider/process failures are terminal and never trigger semantic correction. A second invalid result remains failed/exhausted. A claimed provider call left running by process loss is ambiguous and is not replayed. The Build-dispatch claim is persisted before the writable turn; any existing claim blocks repeat entry, irrespective of candidate existence. Publishable entries require canonical Memory and a persisted design run. Legacy lower-level non-publishable fixture callers without Memory remain supported.

The fake-turn stage regression now crosses `NativeOpenCodeBuilder -> stage_design_build -> Memory`: it persists a completed direction/typed-plan checkpoint, closes and reopens Memory, hydrates the original direction and plan, and reaches one Build without another direction turn. Nested competing facade entries using distinct Memory connections at the direction and Build fake-provider barriers return the exact running-claim and Build-fence diagnostics; exactly one direction and one Build dispatch occur. Reopened Memory preserves the direction hashes/payload and completed Build fence. A subsequent facade entry raises `BuilderError` without another provider invocation. Changed request, context snapshot, supplied-media identity, and target are rejected against the original persisted phase hashes before any new external turn. Existing fake-turn coverage also proves corrected-valid reaches one Build, invalid-twice does not Build and stays exhausted after reopen, and provider/process failure is not semantically retried.

No paid provider call, production tenant mutation, release or owner-visible recovery has been attempted. This slice does not reopen failed runs, schedule explicit lifecycle recovery, or complete the issue's later deployment/live-intake acceptance: explicit failed-run lifecycle recovery, canonical deployment and actual Astrid intake remain parent acceptance gaps.

## Same-run lifecycle implementation draft (unverified)

The current UI-056 draft adds a narrow application recovery branch for a run
already attached to the confirmed intake session. It uses the persisted typed
request and target, records request/context/shared-intelligence identity at the
original handoff, validates the completed native-direction phase against the
runner's `_native_phase_identity`, and asks canonical Memory to compare-and-swap
only `failed`/`interrupted` to `planning`. Memory refuses missing/malformed
direction checkpoints, candidate output, or any `build_dispatch` artifact.
The handoff skips run creation, context capture, request preparation and target
re-resolution; only the CAS winner enqueues the original run. `force_new` and
unlinked prior failures keep their separate-run behavior.

This is implementation evidence only. The required real composition regression
through DesignIntakeService, DesignBuildHandoff, DesignService,
DesignJobExecutor, native builder and reopened Memory has not yet been added.
Changed-input and concurrent independent-caller coverage is incomplete, and no
actual Astrid or deployed acceptance has occurred. The new behavior must not be
treated as accepted until those gates pass.

## Composition13 worker evidence (2026-10-29; incomplete)

Added parametrized `test_composed_same_run_recovery_reopens_checkpoint_and_dispatches_build_once`
in `tests/test_design_intake.py`. It starts from a confirmed intake with real
DesignIntakeService, DesignBuildHandoff, DesignService, DesignJobExecutor,
OperationRoutingBuilder and SQLite Memory; it uses only temporary Git repos,
fake provider turns and a minimal Payload gateway boundary. It interrupts at
the runner's documented pre-Build progress boundary after a genuine completed
native-direction phase, closes/reopens Memory, recovers the same run, and
checks the persisted request/target and exactly one native-direction call.
The recovered executor reaches exactly one Build provider dispatch and leaves
the real `build_dispatch` phase fence in Memory.

This is **not a valid-completion proof**: the Build provider stub deliberately
raises immediately after recording that dispatch, and the test asserts the run
fails with that fixture diagnostic. It does not test concurrent callers or
target/tenant drift. The changed-runtime-base case is a deliberately retained
red regression: after the frozen checkpoint is persisted and reopened, the
isolated clone's HEAD is advanced. `service.resolve_base_sha()` confirms the
new SHA differs from the frozen target, but `DesignIntakeService.build()` does
not raise the expected `DesignIntakeServiceError` and proceeds to same-run
admission. This exposes that recovery admission does not compare current base
to the frozen base. No source fix was made. The initial fixture failure was the missing
canonical Payload workspace (`first-site generation is waiting for the tenant's
canonical Payload workspace`); supplying a test-only Payload boundary allowed
the composed path to reach Build. No source fix was made. Therefore the
manager's current-base drift concern remains unresolved and no full acceptance
is claimed. This local evidence is not Astrid/live acceptance.

## Admission14 correction: recovery reservation shortcut (2026-10-29)

The changed-base reproduction above failed because `DesignIntakeService.build`
returned an already-reserved run before calling `DesignBuildHandoff.submit`.
The recovery path now bypasses only that successful-duplicate shortcut and
reaches `DesignService.recover_prebuild_run`, where the current configured base
and current authorized target are checked against the frozen target before the
existing durable Memory CAS. A changed base raises a specific `base changed`
error before admission or enqueue. Ordinary successful duplicate submissions
retain their idempotent response. Only the CAS winner enqueues; a distinct
Memory caller sees the existing pending reservation and cannot enqueue again.

The composed regression closes/reopens Memory before recovery, observes the
real handoff enqueue, then starts the real executor and drains its admitted job
through exactly one fake Build provider dispatch. Native direction is not
repeated and the durable Build-dispatch fence is retained. The changed-base
variant rejects before enqueue. This remains deterministic fixture evidence;
it does not exercise production tenant authorization changes, the retained
Astrid dynamic artifact/static-out boundary, actual provider/build output,
deployment, or owner-visible review. No claim of issue completion or live
acceptance follows from this source slice.

## Matrix16 concurrent application contention (2026-10-29; failing)

The composed same-run fixture was changed to invoke two real
DesignIntakeService/DesignBuildHandoff/DesignService/DesignJobExecutor
compositions, each with its own reopened `Memory` connection, distinct
idempotency key and thread. A `threading.Barrier` sits immediately before each
connection's real `admit_prebuild_design_recovery`; it delegates unchanged to
the original method and does not hold the Memory lock. Executors are not
started before both callers finish. The losing caller is recorded as its actual
response or exception.

The first two attempts failed before either caller reached that admission
barrier. One raised `sqlite3.IntegrityError: UNIQUE constraint failed:
design_intake_operations.session_id, design_intake_operations.operation,
design_intake_operations.request_hash`; the other raised
`DesignIntakeServiceError('same-run recovery rejected: ')`. The observed result
was zero admissions and zero queued Build dispatches. This is retained as a red
regression; product source was not modified. Durable runner receipts are
recorded in the handoff and bind to the exact tested source SHA.

The fake Build provider, builder and Payload boundaries establish no candidate
completion, review, publication, authorization bypass, or live-site outcome.

## Repair17 reservation boundary progress

The first race is now serialized with SQLite `BEGIN IMMEDIATE` before the
reservation read, decision and insert. The deterministic two-connection test
starts both callers at a barrier immediately before the real reservation
method, then verifies both receive the same authoritative reservation ID/run
and only one reports creation. A conflicting request hash under the winning
idempotency token remains an error. The composed concurrency fixture now
selects the executor whose queue actually contains the admitted work instead
of assuming caller A wins, retains both Memory connections through completion,
and reopens the database to check for a failed reservation.

At this repair checkpoint the affected suites pass twice (302 passed each
run). This remains fixture evidence only. At that time the required
negative-checkpoint and identity-drift matrix (missing/running/failed
checkpoint, prior dispatch, owner request/context/tenant/authorized-target
drift), durable runner receipts, PR update and source acceptance had not yet
been established. No provider output, completed candidate, review, deployment
or live outcome is claimed.

## Checkpoint21 absent-native rejection evidence (2026-10-29)

The composed recovery regression now has a third fixture case that removes the
persisted `native_direction` artifact from the disposable SQLite database after
the interrupted run is reopened. It snapshots the run, remaining phase
artifacts and events after that deletion, then calls the real confirmed-intake
`build` path with a new idempotency key. The actual `DesignService` recovery
policy rejects with `completed native direction and no Build attempt` before
the real Memory admission CAS; an assertion-failing CAS wrapper proves the
boundary. Reopening Memory shows the run, remaining phase fences and events
unchanged, the executor queue remains empty, and the native-direction call
count does not increase. The test does not require intake diagnostics to remain
unchanged.

The existing same-base concurrent recovery control and changed-runtime-base
rejection remain in the parametrized test. On committed source
`d5b46586d4afea3003031c4c9ded578fbfd757f2`, the checkpoint21 composed selection
passed (`ui056-checkpoint21-composed-committed-4b581402d8a7417d964b6a456484d514`).
The durable `run_test.run` intake+memory receipts passed twice (105 tests each):
`ui056-checkpoint21-intake-memory-committed-55687260042f4b95add5726bc0d32734`
and
`ui056-checkpoint21-intake-memory-repeat-committed-1538d3c2de664255aac957b47319dd8f`.

This is still only one absent-native-checkpoint rejection case. Running or
failed native artifacts, a prior Build attempt, request/context/session/tenant/
authorized-target identity negatives, the broader/full suites, controlled
invalid-plan evidence, and actual Astrid dynamic owner review remain gaps.
No candidate, paid provider call, production mutation, deployment, or original
issue acceptance is claimed.
