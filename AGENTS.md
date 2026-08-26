# Site Agent Contributor Guide

This repository is a small, single-instance-at-runtime Python service. Keep
changes easy to trace from an HTTP request or scheduled job to a persisted
state change.

## Invariants

- A site mutation is either an explicit owner action or a pending draft.
- A pending visual build is reviewed in the Design tab; do not add raw preview
  links as a substitute for the review flow.
- Production is changed only by an explicit approval operation.
- Chat jobs are durable. A job may disappear from the active-jobs list after it
  finishes, but it must remain inspectable by its ID and conversation.
- Preview URLs must work under the deployment mount point, currently `/ada/`.
- Site-specific assumptions belong in instance configuration, not generic
  validation or service code.
- Plugins and MCP providers must call application services and contracts. They
  must not call route functions or access `Memory.conn` directly.

## Module Ownership

- `config.py`: config loading, validation, secret resolution.
- `core/memory.py`: SQLite persistence and migrations.
- `core/chat_jobs.py`: durable owner-message execution only.
- `core/scheduler.py`: schedule calculation and execution only.
- `brain/`: decisions, prompts, and tool-loop policy.
- `hands/`: external systems and repository mutations.
- `web/server.py`: HTTP/session translation; keep business workflows out of
  route handlers when extracting or changing them.
- `web/preview.py`: staged output builds, preview URL rewriting, and preview
  cache only.
- `web/static/`: current no-build admin UI. Keep Design state transitions
  explicit and do not introduce a framework for small fixes.

## Debugging Workflow

For a design request, follow this chain in order:

1. `GET /api/chat/jobs/{job_id}`: confirm queued, running, done, or error.
2. For a completed result, read `result.merge_draft_id` or `result.proposal_id`.
3. `GET /api/drafts`: confirm the referenced draft is pending.
4. `GET /api/journal`: confirm journal setup state and draft ID when relevant.
5. `GET /api/pages?draft_id={draft_id}`: confirm the Design page list.
6. Load the iframe through `/ada/api/review/{draft_id}/{page}` and inspect
   every CSS/image request under the same `/ada` prefix.
7. Approve or decline only from the Design controls.

Do not infer completion from `GET /api/chat/jobs`; that endpoint intentionally
returns active jobs only.

## Change Rules

- Start with a failing focused test or a reproducible API request.
- Prefer one behavior-preserving extraction over a rewrite.
- Keep public API paths stable while moving business logic behind them.
- Use typed result objects or documented dictionaries at new boundaries.
- Include job, draft, conversation, provider, or adapter IDs in diagnostics.
- Never commit credentials, databases, caches, worktrees, screenshots, or
  generated OpenCode configuration.
- Run the focused tests first, then the full suite and package smoke test.

## Extension Rules

The supported extension direction is:

`HTTP/MCP adapter -> application service -> typed contract -> adapter/provider`

New integrations should first implement a narrow capability contract. Do not
add automatic Python module loading or a universal plugin base class until a
real external integration requires it. Any external mutation must create a
draft or use an explicit owner-approved service.

## Verification Commands

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
```

If the repository has no Git history, stop before creating an initial commit:
recover the original remote/history or obtain approval to create an imported
baseline.
