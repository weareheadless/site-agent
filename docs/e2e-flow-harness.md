# End-to-end flow validation

A *flow* is a declarative scenario that drives the real product surface in a real
browser and records what actually happened. Flows are the evidence producers for
release gates: they emit one JSON bundle that the project runner consumes without
knowing anything about browsers.

This exists because a merged capability is not a delivered one, and because
"manager reads the worktree and writes a verdict" does not scale and is not
evidence. The run, its screenshots, its console capture and its state assertions
are evidence.

## Two tiers, deliberately separate

| Tier | Model calls | Cost | Runs on | Gates |
| --- | --- | --- | --- | --- |
| `deterministic` | none (stubbed or real app, temp store) | free | every pull request | merge |
| `live` | real generation, real build | tokens + build minutes | release candidate, nightly | release |

A tier is declared in the flow file. A `live` flow must list what it `requires`,
so it can never be run by accident, and it is never a pull-request check: paid,
nondeterministic work in a PR gate is how a gate loses its credibility.

## Layout

```
flows/<id>.flow.yaml        declarative scenarios (reviewed like code)
src/site_agent/qa/flow.py   schema; unknown actions fail at load, not at runtime
src/site_agent/qa/driver.py Playwright driver; observes, never judges
src/site_agent/qa/rubric.py deterministic gate + advisory model judge
src/site_agent/qa/evidence.py versioned bundle, content hashes, fingerprint
src/site_agent/qa/cli.py    python -m site_agent.qa
```

## Running

```bash
python -m site_agent.qa list

python -m site_agent.qa run flows/intake-surface.flow.yaml \
  --base-url http://127.0.0.1:3012 \
  --sha "$GITHUB_SHA" \
  --evidence-dir .tick/site-agent/evidence \
  --artifacts-dir .qa/artifacts
```

Exit codes are the whole interface for automation: `0` pass, `1` fail, `2` the
harness could not run. One bundle per flow is written to
`<evidence-dir>/<flow-id>.json`; screenshots are written beside it and hashed
into the bundle.

## What a flow asserts

Mechanics and contract, not taste:

- the surface renders and the owner can see the controls they need;
- each pipeline boundary was crossed (`visible`, `text`, `count`, `status`, `json`);
- the browser reported no console errors, no failed requests and no uncaught
  page errors, because `AGENTS.md` treats those as failures;
- a failed run never shows the owner raw internals such as `... is required`
  or a traceback as the only explanation.

Taste -- is the copy coherent, does the result reflect the confirmed brief -- is
`ModelJudge`. It is advisory by design and never gates a merge. It returns
`needs_review` rather than guessing when its output is unparseable.

## The gate contract

The bundle is `site-agent.qa.evidence/1`. Schema changes are additive and bump
the version. The fields the runner needs:

- `status` -- `passed`, `failed` or `error`;
- `rubric.passed` -- the deterministic verdict, `false` on any blocking check;
- `failed_step` -- the first boundary that broke;
- `fingerprint` -- a stable 16-character identity for this failure, excluding
  timestamps and generated ids, so repeated runs dedupe to one issue;
- `target.sha` / `target.deployed_sha` -- what was actually tested;
- `artifacts.files[].sha256` -- what the reviewer can inspect.

Merge requires `status == passed` and `rubric.passed == true` on the exact head.
Release requires the same from a `live` flow whose `target.deployed_sha` matches
the released slot.

## Adding a flow

Add a file under `flows/`. Nothing else is required: the loader rejects unknown
actions, unknown expectations, duplicate step ids and expectation steps that do
not exist, so a typo cannot produce a flow that silently asserts nothing.

Keep each flow to one owner journey. A flow that covers two journeys fails in a
place that does not name the journey.

## Using it to investigate

This is the half that removes the most waste. When an issue says "reproduce",
the deliverable is a red flow, not a paragraph:

1. Write or extend a flow that reaches the reported boundary.
2. Run it against the current revision. The bundle names the first failing step
   and attaches a screenshot and the console log.
3. Fix the cause, rerun the same flow. It goes green and becomes the regression
   fixture.

A reproducer and its regression test are the same artifact, so the investigation
cannot silently lose its evidence and the fix cannot silently lose its proof.

## Current state and honest gaps

- `intake-surface` (deterministic) ships and passes against the real Intake Lab
  app with a temporary store.
- `intake-to-preview` (live) encodes the UI-056 acceptance path. It cannot pass
  until the build produces the output shape the deployed validator requires, so
  it is the acceptance gate for that work rather than a green check today.
- The model judge is a seam (`ModelJudge(complete=...)`), not a wired provider.
- Record mode -- capturing a failing run as a replayable scenario -- is designed
  but not built; the deterministic tier currently uses the real app with a
  temporary store instead of recorded provider responses.
- The harness cannot answer questions that live in the database (run identity,
  reservation state, tenant correlation). Those remain read-only operator
  checks. It complements them; it does not replace them.
