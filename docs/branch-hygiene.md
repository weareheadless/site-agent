# Branch hygiene

The release runner only reads `main`. `deploy/desired-api-release.json` names a
commit, the host timer tests that commit, and `deploy/desired-releases.json`
rolls tenants. Nothing in that path can see a branch.

That makes one failure mode structural: work committed to a branch, with no
open pull request, is work that will never ship and that nothing reports. It
does not matter how good the code is.

## Check what is stranded

```bash
git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*'
python scripts/branch_drift.py                 # report
python scripts/branch_drift.py --json          # machine-readable
python scripts/branch_drift.py --list-merged   # branches safe to delete
```

`.github/workflows/branch-drift.yml` runs the same report daily and fails while
an orphaned branch is older than seven days, so the condition surfaces instead
of sitting quietly.

A branch is *orphaned* when it has commits `main` does not have and no open pull
request points at its head. Merged branches are clutter, not risk; the report
lists them separately.

## Controls that keep it from recurring

1. **Protect `main`.** Require a pull request and the two checks for every push,
   including maintainers. A direct push skips the task-format gate and, because
   the runner queues releases on merge, skips the automatic release queue too —
   it has to be queued by hand.
2. **Let the runner queue on any `main` push**, not only on pull-request merges.
   Today a direct push deploys nothing until someone writes
   `deploy/desired-api-release.json`.
3. **Delete the branch on merge.** 190 of the branches in this repository are
   already fully contained in `main`; they exist only as noise that makes the
   206 orphaned ones hard to see.
4. **Run the drift check in the release path.** Before the timer queues a
   release, the same report can note orphaned work in the receipt, so a release
   never looks complete while older work is stranded.

## What a clean state looks like

- Every branch with commits outside `main` has an open pull request.
- Every merged branch is deleted.
- `python scripts/branch_drift.py --max-age 7` exits zero.
