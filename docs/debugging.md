# Debugging Runbook

Use the same sequence for every long-running design or content operation. Do
not start by rerunning the builder.

## Identify State

```text
GET /api/chat/jobs/{job_id}
GET /api/conversations/{conversation_id}
GET /api/drafts
```

The active-job endpoint, `GET /api/chat/jobs`, intentionally omits completed
jobs. A `done` job remains available by ID and in its conversation.

Editorial drafts are managed through the tenant's Payload workspace. A failed
Payload validation is an explicit task failure; there is no parallel article
file publisher.

## Verify Design

The Design tab should select the newest pending `edit`, `merge`, or `rollback`
draft. For a draft ID `N`:

```text
GET /ada/api/pages?draft_id=N
GET /ada/api/review/N/<built-page-or-asset-path>
```

All iframe assets must remain under `/ada/api/review/N/`. A request to bare
`/api/review/...` is a routing bug: on the OceanicVibes host that path belongs
to the legacy Node service.

## Verify Production Safety

- A pending draft must not change `origin/main`.
- Approve is the only operation that merges a preview draft.
- Decline must leave production unchanged and reset the preview branch when
  appropriate.
- `open live` is intentionally different from the staged Design preview.

## Server Checks

```bash
ss -ltnp | rg ':(3010|3011)'
systemctl status site-agent@oceanicvibes
systemctl status site-agent-oceanicvibes-admin
sqlite3 /SOCIAL/configs/oceanicvibes/data/memory.db 'PRAGMA integrity_check;'
```

There must be one managed Python admin process. A manually launched process
can hide service-file or deployment problems and should not be used as the
normal runtime.

## Common Misdiagnoses

- Seeing the old public page does not mean the draft failed; production stays
  old until approval.
- Seeing draft `N` instead of job `M` is expected; they use separate tables.
- An empty active-job list does not mean the completed job disappeared.
- A raw review endpoint returning authentication errors usually means the
  request went through the legacy `/api/` proxy, not the Site Agent `/ada/`
  proxy.
