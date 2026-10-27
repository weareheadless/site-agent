# Working on an agent task

Use the existing shared key, Project, issues and PRs. There is no bot service,
separate identity/credential system, automatic dispatcher or automatic merger.
The generic checker is maintained once in `site-agent/tools/agent-coordination`;
other repositories pin that version through a small reusable workflow.

## When the owner says “tackle UI-007”

1. Read that issue, repository instructions and its direct dependencies. Check
   the Project's **Ready for agents** view. Do not pick Deferred or blocked work.
2. Describe the smallest change and intended paths. Ask the manager to review
   the plan if the task leaves a consequential choice unresolved. Record the
   baseline, contract commit and your actual thread/run ID in a claim.
3. Work on the recorded branch in an isolated checkout. Open a draft PR after
   the first meaningful commit. Use the template, keeping its JSON equal to the
   active issue claim. Update Validation and Handoff with actual results.
4. Stop if dependencies, scope or assumptions change. Review the revised plan
   with the manager and explicitly release/reclaim; do not silently broaden it.
5. When ready, stop at the PR. The manager checks current CI and reviews the
   latest diff against the issue, simplicity, acceptance and contract consumers.
   A green metadata check does not certify the implementation's correctness.

Suggested instruction to an agent:

> Implement the linked Ready issue. Follow docs/agent-coordination.md. Claim it
> with your run ID, branch, baseline, contract and scope; keep an early draft PR.
> Reuse existing code, satisfy the issue's acceptance and run the relevant tests.
> Stop for a manager decision if scope changes. Hand back the PR, exact tested
> commit, evidence and remaining blockers. Do not merge or deploy.

## One plan, one active claim

Save a small JSON plan locally with these fields (replace the example values):

```json
{
  "workId": "UI-001",
  "repository": "weareheadless/crawlseo",
  "issueNumber": 15,
  "agentRun": "actual-thread-or-run-id",
  "branch": "codex/ui-001-contract",
  "baseline": "FULL_40_CHARACTER_BASELINE_SHA",
  "contract": null,
  "scope": ["contracts/**", "tests/connector-context.test.ts"]
}
```

`contract: null` is allowed only for the initial UI-001/UI-013 contract/inventory
work and OPS-001 coordination bootstrap. Implementation uses
`{"repository":"weareheadless/crawlseo","sha":"FULL_40_CHARACTER_SHA"}` pointing
to an actual reviewed commit on main, not a branch or a proposed design alone.
Scope accepts exact filenames and trailing `directory/**`, never a root wildcard.

Using the shared key already available to the manager/agent as `GH_TOKEN`:

```bash
node tools/agent-coordination/cli.mjs claim --plan /path/to/plan.json --dry-run
node tools/agent-coordination/cli.mjs claim --plan /path/to/plan.json
node tools/agent-coordination/cli.mjs check --repository weareheadless/crawlseo --pr 123
```

Run from a checkout of the pinned shared checker, including for another repo.
`claim` checks Project readiness, dependency closure, pins and competing claim
history, writes an ordinary issue comment, and moves its existing board item to
In progress. Same-plan retries are idempotent. Use one manager for assignments:
GitHub comments/assignments are a coordination log, not an atomic distributed lock.
If two claims race, the checker blocks on their conflict; reconcile explicitly.

To release or hand off, append an issue comment, retaining the original history:

```text
<!-- agent-claim
{"event":"release","agentRun":"actual-thread-or-run-id","reason":"Manager reviewed the handoff and retained the existing branch/PR"}
-->
```

Reconcile any open PR before another run reclaims the issue. Do not steal stale
work automatically. If a work package genuinely needs parallel branches, split
independently owned work first; otherwise keep coherent follow-up PRs sequential.

## Host disk hygiene

The coding host runs the production release pipeline, so filling `/` breaks
deployments, not just builds. It happened on 2026-10-27: per-release checkouts
with their own `node_modules` consumed the last free bytes, and a HelloAda release
died at `npm ci` with `ENOSPC`.

Rules:

1. **One reusable workspace per repository.** Keep at most one checkout per
   repository per purpose and reuse it (`git fetch` + `git checkout`), instead of
   cloning per task or per release. Each `node_modules` is ~1.3 GB.
2. **Delete what you create.** A verification or build checkout is temporary:
   remove it when the task ends, or state why it stays. Never leave a dozen
   checkouts of the same repo behind.
3. **Check before you build.** `df -h /` before a release or a large install. Below
   roughly 10 GB free, stop and prune first.
4. **Prune release slots.** Keep the current slot plus at most one previous for
   rollback; remove older ones after a release is verified.
5. **Never prune blind.** Only delete paths this work created, or slots and
   checkouts whose identity is known stale. Someone else's checkout, tenant data
   or a release receipt is not yours to remove.
6. **Report disk incidents.** If a build fails with `ENOSPC`, record it in the
   task evidence with the path that grew, and fix the cause rather than deleting
   whatever is largest.

The deploy path should reuse one build directory and prune old slots
automatically; until it does, this discipline is manual and belongs to whoever
runs the release.

## Tests must be green, deterministically

A failing test is a defect in the change or in the test, never a rerun. The
manager does not merge on "passed on the second attempt", and a worker may not
report a suite as passing when it failed earlier in the same run.

1. **Fix the cause.** Reproduce the failure, find why it is nondeterministic
   (timing, shared fixture, port, database state, ordering, parallelism) and make
   it deterministic. Do not add retries, sleeps or skips to hide it.
2. **A flake is a bug with an owner.** If the failure is in a test this change
   does not touch, it still blocks the merge: file it, fix it, or state
   explicitly which check was red and why the merge is safe — and expect the
   manager to refuse.
3. **Run the suite twice** for anything touching concurrency, the database, the
   queue or the filesystem. Both runs must pass.
4. **CI is the gate when it can run.** Local green does not override a red
   current-head check; a red check that cannot start (billing, runner outage) is
   recorded as unavailable, not as passing.

## Decision authority

The manager owns the project: task definition, acceptance criteria, ordering,
architecture and the trade-offs between them. Workers do not consult the owner
and the owner is not a decision queue.

When a worker raises a question, the manager answers it by reading the
repository and the constraints, then records the decision where it belongs:

1. **Revise the design first.** Re-read the issue, the affected modules and the
   existing contracts before answering. If the question reveals a real gap, fix
   the task definition or the architecture rather than pushing the ambiguity
   back to the worker.
2. **Decide once, in writing.** The answer goes into the issue, the PR, or the
   relevant plan document — not only into a chat reply — so the next worker
   inherits it instead of rediscovering it.
3. **Keep the codebase lean.** Prefer extending an existing contract over adding
   a module, table, route or field. No duplicate stores, no parallel models, no
   second workflow for the same effect, no copy of data that already has an
   owner. If two paths would compute the same thing, delete one.
4. **Escalate to the owner only for** spending, customer-facing promises,
   production mutation, credentials, or a genuine product-direction choice.
   Everything else — naming, boundaries, storage, sequencing, test strategy —
   is the manager's call and must be made without waiting.
5. **Never leave a worker idle on a question.** Answer, re-scope, or re-dispatch;
   a blocked worker that returns a question costs a round trip that the manager
   should have pre-empted with a precise brief.

## Parallel work and dependency-driven selection

The Project is the scheduler. The manager does not work through issues one at a
time: it reads every issue's **Readiness**, **Status** and native `blockedBy`
links, and dispatches **one Luna worker per issue whose blocking links are all
closed and whose Readiness is `Ready`**. Dependency data already exists, so
serialising work that is provably independent only wastes elapsed time.

Standing rules:

1. **Parallel by default, bounded by review capacity.** Up to three workers run
   concurrently. Go higher only when the scopes do not overlap. Every worker
   gets its own checkout, its own branch, its own claim and its own run label.
2. **Do not serialise on repository identity.** Several ready issues in one
   repository are normal. Serialise only on *artefact* overlap: the same file,
   the same module, the same migration chain, or the same shared fixture.
3. **Migrations stay independent.** Each worker creates only its own
   `prisma/migrations/<timestamp>_<name>/` directory. Never edit, rename or
   delete another migration directory and never rebuild migration history. The
   manager generates migrations only from the worker's already-clean chain.
4. **Shared modules stay localised.** When two in-flight issues both touch a
   shared module, keep each edit minimal and merge sequentially.
5. **Merge in dependency order, rebase between merges.** The manager merges the
   reviews that are green, then rebases the next branch onto the new `main`
   before merging it. A real conflict is resolved by the branch owner, not by
   the manager editing another worker's files.
6. **Shared disposable fixtures are reconciled deliberately.** If a fixture's
   `prisma migrate status` is not clean, the worker stops and reports. Only the
   manager resets a fixture, only with `npx prisma migrate reset --force` on the
   explicitly disposable database, and never as a silent repair.
7. **Block on questions, not on time.** A worker that hits an unresolved
   contract, credential or scope question returns immediately with the exact
   decision needed. It never idles waiting, and never invents a decision.

The manager still owns assignment, review and merge. Parallelism does not
weaken the checks in the next section, and it never authorises a merge that was
not reviewed at its exact head.

## Checks and the manager's decision

- **Agent task format** runs on PR events using the pinned checker, not task-
  branch code. It verifies the issue/claim, metadata, declared file scope, pins
  and duplicate PRs. It resets previous **Agent coordination** feedback to Pending
  on managed PR edits/pushes, so changed metadata needs another manager check.
- **Agent code checks** is actual repo CI. The manager checks current-head
  results, not an agent's checkbox. Any failed current check blocks the handoff;
  missing required code checks are Pending. Documentation-only PRs do not pretend
  to require application execution. Renamed files are checked at both paths.
- **Agent coordination** is published by the manager after live readiness,
  cross-repo dependencies, claim/scope/pins and CI checks. It does not perform code
  review or authorize publication. It never claims Verified from a merge.

After reviewing the actual diff, the manager can publish feedback and sync status:

```bash
node tools/agent-coordination/cli.mjs check --repository weareheadless/crawlseo --pr 123 --publish --sync
node tools/agent-coordination/cli.mjs sync --repository weareheadless/crawlseo --pr 123
```

`sync` reflects draft/review/merge state in the existing board; it never promotes
Deferred work or marks Verified. PM checks run on demand with the existing key;
no schedule or always-running worker is implied. There is no shared personal key
in these CI jobs; they use GitHub's built-in workflow token for repository reads
and Pending status updates.

With everyone sharing one key/account, authorship and reviewer identity are
process conventions, not an authentication boundary. An account with admin
access can bypass conventions. Keep one manager deciding assignments/merge,
and require latest-diff review plus observed tests. Do not configure a required
independent GitHub approval from the same account: GitHub cannot self-approve it.

## Adoption and merge protection

These workflows become automatic when their PRs merge. First merge the shared
checker, then consumers pinning it. Confirm a real task-format/code run and the
manager status before making **Agent coordination** a required main-branch
check. Preserve existing production release requirements. Do not require a check
that has not been registered or silently change a live deployment path.

The check applies to UI/OPS title/branch markers or an `agent-task` block;
ordinary maintenance/release PRs retain their existing process. This is a scoped
initiative rule, not a way to identify all possible AI-authored code. Agents must
retain the task marker. No check or shared key replaces manager review.
