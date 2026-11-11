# Owner chat on the opencode agent

Status: implemented and the engine for every workspace that has a builder and a
checkout. The legacy loop is the explicit rollback (`chat.engine: legacy`) and
the engine for a site without a source workspace.

The engine is chosen from capability, not from a per-tenant opt-in. `inmersion`
was the first tenant to hit the difference: it had no `chat.engine` key, so it
kept the retired 24-step loop and a repository-scale request (`update the site
with these courses and excursions`) spent all 24 steps on file reads and media
searches without ever reaching a write. Falling back on a missing key is what
made a re-registered or newly provisioned config silently broken.

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
| Agent loop, tool selection, final message | opencode (`--agent build`) |
| Repository reads and edits | opencode, natively, in the turn's builder worktree |
| Content, metrics, Growth, plan, build | `application/agent_tools.py` over MCP |
| A page the owner links | `hands/web_read.py` (`read_web_page`) |
| Tool contract and validators | `brain/editor.py` (`_tools_spec`, `_execute_tool`) |
| Per-turn tool state | `brain/turn_state.py`, stored against the chat job |
| Tree validation, preview commit, review draft | `hands/opencode_runner.py` (`run_owner_turn`) |
| Message delivery | `core/chat_jobs.py`, stored unchanged |

The host prepares the builder worktree and the agent contract, runs the turn,
validates the exact tree, commits it to the preview branch and stages the
compiled preview and the one review draft. It does not filter, prefix or
replace the message opencode wrote.

## Source ownership

The agent owns the tenant's website; the platform owns its runtime. That is one
deny list, `frontend_ownership.PLATFORM_PROTECTED_PATHS`, and one decision,
`repo_changes.source_path_allowed`, shared by the chat/build sandbox, the source
editor, design candidates, the compiled-preview boundary and owner-facing
frontend restores:

- **Tenant source**: routes under `src/app/(frontend)/` (except the scaffold
  shell), `src/components/**` (except the platform set), `src/content/**`,
  styles, fonts, and `public/**` assets.
- **Platform source**: Payload schema, migrations, admin and authentication,
  `src/app/api`, the HelloAda bridge and shared runtime (`src/lib/*`,
  `mailflare-*.ts`, `worker.ts`), package pins and build/runtime configuration
  (`package.json`, `next.config.*`, `wrangler.jsonc`, `src/helloada.config.ts`,
  `.helloada-managed.json`), the shared route shell
  (`src/app/(frontend)/layout.tsx`, `[[...slug]]/page.tsx`) and every file
  `deploy/shared-runtime-overlay.json` copies. A test asserts that the overlay
  cannot drift from this list.

It was a positive allowlist of "presentation files" before. That only described
the default scaffold, and `defaults.yaml` shipped the same short list as
`site.writable_patterns`, so a tenant that replaced the scaffold with its own
routes was refused its own source: inmersion's request to add courses and
excursions produced 24 real file edits and then failed with `builder changed
files outside the writable sandbox`, and the owner saw "Ada could not complete
the request". The prompt told the agent the repository was hers while the gate
enforced the scaffold list; now the statement Ada reads (`source_authoring_contract`)
and the gate are the same decision, and the compiled-preview boundary calls the
same function instead of repeating the rule.

`SCAFFOLD_PRESENTATION_PATTERNS` is not this boundary. It is the design-run
allowlist inside a generated site whose pages render through the host-owned
Payload route shell, and it is deliberately narrower than what the tenant owns.

## Boundaries

- The owner turn runs in the builder worktree (`data/builder-worktrees/build-*`)
  created from `_build_base_ref` (the pending preview when one exists, otherwise
  `origin/main`). The agent edits it directly; the host then validates the exact
  changed paths, commits them to the preview branch and stages the review draft.
- The MCP process is tenant-scoped. It resolves one registered workspace from
  `--config`/`--env`, refuses any chat job it cannot find, and is pinned to the
  exact package the API is running through `PYTHONPATH`.
- A delegated source task narrows the agent to its planned `source_paths`; the
  unrestricted owner turn is the only writable surface, and it still cannot
  leave the platform boundary.
- `read_web_page` is the only way out to the web for a delegated task. opencode's
  own `webfetch` and `websearch` are denied there. The policy is http/https only,
  no credentials in the URL, every redirect hop re-validated, every resolved
  address must be public, text content only, and bounded size and time, because
  the agent runs beside the workspace API and the host's credentials.
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

## Content writes across more than one call

A page with many fields used to require one write carrying every planned field.
The plan is frozen after the first dispatch, so an owner without a portrait could
not create the page at all: the plan asked for `featuredImage`, the model could
not supply it, and every create was refused for the missing fields. The agent
then described the frozen plan to the owner as an "interrupted save lock", which
it is not.

With the live schema in hand the host can now tell a required field from an
optional one. A new document may be created with the required fields, then
completed by an update that writes the remaining planned fields of that same
document. An unplanned field is still refused, a dispatch whose outcome is
unknown is still never replayed, and source work still waits until every planned
field has been written.

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

No per-tenant key is needed. A tenant whose `builder.enabled` is true and whose
`site.clone_path` is set runs the opencode agent; everything else keeps the
legacy loop.

Rollback is an explicit per-tenant key and an API release through the normal
queue:

```yaml
chat:
  engine: legacy
```

No data migration is involved; the legacy loop and its tests are intact. The
explicit `opencode` key still works and is equivalent to the capability default.

## Not yet verified

- Parity on five real owner questions (two are measured above).
- `_validate_website_change_plan` skips its source-path check for a tenant whose
  `design_engine.build_profile` is unset. `spawn_build` still validates paths
  against the ownership contract before delegating, so a bad path fails closed at
  build time; the plan-level check is simply looser than the build-level one.
- A generated site's design run is still held to
  `SCAFFOLD_PRESENTATION_PATTERNS`. A bespoke tenant cannot run one, which is
  consistent with the retired intake journey: bespoke sites are authored through
  this chat and the coding agent, not through a design run.
