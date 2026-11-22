# Working on an agent task

Use the existing shared key, issues and PRs. There is no bot service,
separate identity/credential system, automatic dispatcher or automatic merger.
The generic checker is maintained once in `site-agent/tools/agent-coordination`;
other repositories pin that version through a small reusable workflow.

## When the owner says “tackle UI-007”

1. Read that issue, repository instructions and its direct dependencies. Work
   only an issue whose blocking links are closed. Do not pick deferred or blocked
   work.
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
`claim` checks dependency closure, pins and competing claim history, then writes
an ordinary issue comment. Same-plan retries are idempotent. Use one manager for assignments:
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

## The issue is the status

A status report is only true if the issue says the same thing. Reconciling it is
part of the work, not a wrap-up step.

1. **Close or comment in the same action as the merge.** A merge or a deploy is
   not finished until its issue reflects it: closed with a comment naming the
   merge SHA and what remains, or kept open with the specific next step named.
2. **Never leave an issue open on delivered work.** A stale open issue makes
   every later report untrustworthy and hides what is genuinely blocked.
3. **Keep an issue open only for real remaining work,** and say what it is in the
   issue: live verification not executed, a credential missing, a defect filed
   elsewhere. An open issue with no named next step is a lie.
4. **Closing is not completion.** An issue closes when its acceptance is met; a
   merge that delivers part of it stays open, or is closed with the remainder
   moved to a named follow-up.
5. **Before reporting status, read the open issues.** If the report and the
   issues disagree, the issues are right and the report is wrong.

There is no separate board. A status field that is not updated in the same action
as the merge decays into a second, wrong source of truth: the retired
`Unified Business Intelligence` project reached 151 items with 26 holding no
status at all and 5 marked Merged while still open. Its item/status mapping is
kept as a static record in
`archive/project-3-unified-business-intelligence.json`; nothing reads it at
runtime and it is not a coordination surface.

Do not file one issue per automated test failure. Failing tests belong in CI
output and the pull request that fixes them; a per-failure issue reporter filled
the tracker with 26 near-duplicate issues in two days, none of which were
triaged. File an issue for a defect that needs a decision or outlives its PR.

## Parallel work and dependency-driven selection

The issue graph is the scheduler. The manager does not work through issues one at
a time: it reads every open issue's native `blockedBy` links, and dispatches
**one Luna worker per issue whose blocking links are all closed**. Dependency data already exists, so
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

`sync` reflects draft/review/merge state in an issue comment; it never promotes
deferred work or claims a merge is verified. PM checks run on demand with the existing key;
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
