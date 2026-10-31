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

## Holding the owner's side of a conversation

A live flow cannot rubber-stamp its way through intake: if Ada asks a question and
the test answers "yes, go ahead", the run proves nothing about whether the product
can actually get a brief out of a person.

The `converse` action gives an AI owner a business brief and lets it answer Ada's
actual questions. Neither side follows a keyword table or scripted replies:

```yaml
- id: answer-ada
  action: converse
  mark: brief_ready
  reply_timeout_ms: 300000
  until:
    - kind: visible
      selector: "#confirm-panel"
  persona:
    max_turns: 10
    brief: |
      You are Mariana, owner of Atelier Sete in Lisbon. Your beginner wheel
      course is four sessions and costs 240 euros. Answer naturally from what
      you know; leave design decisions to Ada.
```

Each turn supplies the conversation history and persona to the owner model.
The loop ends when an `until` condition
holds -- never on a fixed turn count, which would either cut a real conversation
short or spin after it finished. The whole transcript goes into the evidence, so
a reviewer can see what was asked and what the owner said.

If the conversation does not settle inside `max_turns`, the step fails and says
what Ada last asked. Inspect the transcript to distinguish product failure from
an owner-agent or browser-driver defect before filing a regression.

The default is `openai/gpt-6-luna` through OpenCode's existing authenticated
OpenAI provider, the same credential path used by the project runner:

```bash
python -m site_agent.qa run flows/intake-to-preview.flow.yaml \
  --base-url "$TEST_ORIGIN" --environment test \
  --owner-backend opencode --owner-model openai/gpt-6-luna
```

The owner runs with all tools denied, does not receive credentials, and cannot
rotate host-global accounts. OpenRouter is not a fallback: a compatible API is
used only with an explicit `--owner-backend compatible-api`. The bundle records
`test_owner.backend` and `test_owner.model`, separately from Ada's target model.
Changing the test owner does not change the production product's provider.

## Measuring what it costs the owner

Steps can carry a `mark`. Marks become `timings` in the bundle: the seconds
between each consecutive mark and the total. The live flow marks
`brief_ready`, `build_requested`, `candidate_ready` and `site_live`, so
`durations_s["candidate_ready"]` is the build time the product promises to keep
near twenty minutes.

Marks are wall-clock and deliberately coarse. They answer "how long did the
owner wait", not "which function was slow".

## One live test site at a time

Provisioning is part of the flow, because a candidate that cannot be provisioned
is not a delivered site. Leaving provisioned test sites behind is not acceptable,
so the harness keeps a ledger:

```bash
python -m site_agent.qa run flows/intake-to-preview.flow.yaml \
  --base-url "$TEST_ORIGIN" --environment test \
  --ledger .qa/test-sites.json --allow-destructive
```

The current ledger records an incubation only after the run finishes and calls
incubation DELETE before the next run. This does **not** prove website resources
are deprovisioned or enforce single-flight execution. Interrupted runs can escape
registration, and a test/local flag is not proof of tenant ownership. Until the
canonical teardown, durable registration and locking are qualified, serialize
runs externally and use an explicitly owned scratch target; do not enable this
cleanup against provisioned websites. One live test website remains a requirement,
not an established safety guarantee of this ledger.

## Which model runs the target

The harness does not configure the product's model; the target does, and the
bundle records what the target reported from `/api/lab` as `target.model` and
`target.provider`. That keeps runs comparable: a run against a fallback provider
is visibly different evidence from a run against the release provider, and a
build-time comparison that mixes them is meaningless.

The owner model now uses the runner's existing OpenCode authentication by default.
The product under test still owns its own model configuration; record the actual
target provider and model before comparing timings.


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

Intended gate semantics are `status == passed` and `rubric.passed == true` on the
exact head, plus a live flow whose observed serving identity matches the released
slot for release acceptance. These gates are not installed by this branch.
The exploratory live flow is not gate-ready until canonical Payload entry,
provisioning, public-site checks, interruption-safe evidence and cleanup are proven.

## Adding a flow

Add a file under `flows/`. Nothing else is required: the loader rejects unknown
actions, unknown expectations, duplicate step ids and expectation steps that do
not exist, so a typo cannot produce a flow that silently asserts nothing.

Keep each flow to one owner journey. A flow that covers two journeys fails in a
place that does not name the journey.

## Using it to investigate

The project runner discovers these tests through
`projects/site-agent-tests.json` in `weareheadless/project-runner`:

```bash
python3 runner/test_catalog.py --project site-agent --issue 458
python3 runner/test_catalog.py --project site-agent --path src/site_agent/web/intake_lab.py
```

The runner mandate points to the catalogue. Entries give commands, prerequisites,
cost tier, relevant issues/paths, evidence and limitations. Discovery never starts
paid work. On a fix, rerun the relevant reproduction; on a failure, attach the
evidence to the existing issue or file a narrowly supported prerequisite.

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
- `intake-to-preview` (live) converses with an AI owner, marks boundaries and
  attempts provisioning. Exploratory runs reached a failed build and exposed
  scaffold reuse rejection (#481); no end-to-end provisioned success is claimed.
- `converse`, marks, timing and the ledger are covered by tests against a
  fixture app; the full live path has not been run end to end against a
  provisioned target yet.
- The model judge is a seam (`ModelJudge(complete=...)`), not a wired provider.
- Record mode -- capturing a failing run as a replayable scenario -- is designed
  but not built; the deterministic tier currently uses the real app with a
  temporary store instead of recorded provider responses.
- The harness cannot answer questions that live in the database (run identity,
  reservation state, tenant correlation). Those remain read-only operator
  checks. It complements them; it does not replace them.
