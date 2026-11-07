# Owner chat on the opencode agent

Status: implemented and live for `oceanicvibes`, behind `chat.engine`. The legacy
loop remains the default and the rollback path.

## What changed

Ada's chat used to be a hand-written tool loop in `brain/editor.py` that also
assembled the owner-facing message. Every failure on 6 November came from that
layer: `owner_message_without_unstarted_build` replaced a complete plan with one
canned sentence because the plan contained a forward-looking offer ("I can build
it once you confirm the portrait"), and that sentence then became the assistant
turn, so "state the plan again" had no plan left to restate.

The turn now runs as an opencode agent:

| piece | owner |
|---|---|
| Agent loop, tool selection, final message | opencode (`--agent chat`) |
| Repository reads | opencode, natively, in a read-only checkout |
| Content, metrics, Growth, plan, build | `application/agent_tools.py` over MCP |
| Tool contract and validators | `brain/editor.py` (`_tools_spec`, `_execute_tool`) |
| Per-turn tool state | `brain/turn_state.py`, stored against the chat job |
| Message delivery | `core/chat_jobs.py`, stored unchanged |

The host prepares the checkout and the agent contract, runs the turn, and stores
what opencode wrote. It does not filter, prefix or replace that message.

## Boundaries

- The chat checkout is `<clone>-chat`, detached at `_build_base_ref` (the pending
  preview when one exists, otherwise `origin/main`). Chat never edits it: `edit`,
  `bash`, `shell`, `task`, `external_directory`, `webfetch` and `websearch` are
  denied; read, glob, grep and list are allowed.
- The MCP process is tenant-scoped. It resolves one registered workspace from
  `--config`/`--env`, refuses any chat job it cannot find, and is pinned to the
  exact package the API is running through `PYTHONPATH`.
- `spawn_build` remains the only way to start a build, and it still requires a
  validated plan and completed Payload receipts. The model cannot talk past it.
- The opencode session id is stored per conversation, so a follow-up continues
  the same turn history. The first turn passes the recent conversation instead.

## Reply selection

`opencode_runner` used to return the prose after the last tool call. An agent
that writes between tool calls loses the middle of its answer that way: a live
turn returned three fragments totalling 218 characters instead of the plan.
Chat now uses `reply_mode="final_message"`: the last message the agent completed
without calling a tool. Builds keep the previous selection.

## Measured

Live, through `POST /v1/workspace/chat` on the deployed release:

| turn | legacy loop | opencode agent |
|---|---|---|
| advisory question | 38 s, 3,908 chars | 50–67 s, 3,457–4,161 chars |
| "state the plan again" | 141-char canned caveat | **7.1 s, 2,367 chars, full restatement** |
| greeting | — | 3.7 s |

The advisory answer is slower because the agent reads the real repository
(~20 files) instead of a whitelisted subset. A simple factual question also
explores more than it needs; that is a tuning item, not a correctness one.

## Operating it

Enable per tenant with:

```yaml
chat:
  engine: opencode
```

Rollback is setting it back to `legacy` (or removing the key) and restarting the
API through the normal release queue. No data migration is involved; the legacy
loop and its tests are intact.

## Not yet verified

- A build started from chat through the MCP tool. The tool path is wired and its
  refusal behaviour is tested, but no real build has been run through it, because
  a build would revise the owner's pending draft 68.
- Parity on five real owner questions (two are measured above).
- `_validate_website_change_plan` skips its source-path check for a tenant whose
  `design_engine.build_profile` is unset. `spawn_build` still validates paths
  against the ownership contract before delegating, so a bad path fails closed at
  build time; the plan-level check is simply looser than the build-level one.
