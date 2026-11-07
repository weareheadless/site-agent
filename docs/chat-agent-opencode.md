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
| A page the owner links | `hands/web_read.py` (`read_web_page`) |
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
- `read_web_page` is the only way out to the web. opencode's own `webfetch` and
  `websearch` are denied. The policy is http/https only, no credentials in the
  URL, every redirect hop re-validated, every resolved address must be public,
  text content only, and bounded size and time, because the agent runs beside
  the workspace API and the host's credentials.
- The opencode session id is stored per conversation, so a follow-up continues
  the same turn history. The first turn passes the recent conversation instead.
  Verified across a process restart: a follow-up answered from a new process
  restated the earlier plan, which is what an API release does to a live chat.

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
| advisory question | 38 s, 3,908 chars | 72 s, 3,702 chars |
| "state the plan again" | 141-char canned caveat | **12 s, 2,164 chars, full restatement** |
| traffic and priorities (tools) | — | 28 s, 2,138 chars |
| how many articles are published | — | 33 s, 427 chars (2 published, 5 drafts) |
| greeting | — | 3.7 s |

The advisory answer is slower because the agent reads the real repository and
queries the workspace instead of a whitelisted subset. It also produced a
better-grounded answer: it found the stale "DATES ON REQUEST" copy, the
unattributed journal voice and the absence of structured data.

## Defects found while migrating

1. `owner_message_without_unstarted_build` replaced an entire answer with one
   canned sentence. Fixed before the migration; it is the reason for it.
2. The runner returned the prose after the last tool call, losing the middle of
   an answer written between tool calls (218 characters of fragments live).
3. The MCP entry carried `"timeout": {"startup": …, "execution": …}`. A local MCP
   server takes an integer, so opencode skipped the whole entry as malformed and
   **every chat turn ran with no tools at all** while telling the owner the
   analytics connection was down. This is why `SITE_AGENT_MCP_LOG` exists.
4. The generated `opencode.json` contained the model credential in plaintext.
   The credential now travels only in the process environment, under one name,
   and the configuration interpolates it.
5. The MCP process loaded the tenant file directly, skipping the packaged
   defaults that map `env.llm_api_key`; the build path would have had no model
   credential.

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

- A build started from chat through the MCP tool. The wiring is tested end to
  end with a stubbed `stage_build` (the validated brief reaches it and its draft
  comes back into the job), but no real build has run through it, because
  `run_brief` force-pushes the preview branch and revises the owner's pending
  draft 68. That test needs the owner to publish or discard 68 first.
- Parity on five real owner questions (two are measured above).
- `_validate_website_change_plan` skips its source-path check for a tenant whose
  `design_engine.build_profile` is unset. `spawn_build` still validates paths
  against the ownership contract before delegating, so a bad path fails closed at
  build time; the plan-level check is simply looser than the build-level one.
