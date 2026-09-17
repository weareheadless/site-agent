# Atelier Payload bridge

The Atelier Payload workspace talks to site-agent through a narrow, server-to-
server API. This bridge is separate from the browser password session and does
not change Intake Lab authentication or state.

## Configuration

Set the same secret value in both services, using server-only configuration:

```text
Atelier Payload: SITE_AGENT_URL + ATELIER_SITE_AGENT_TOKEN
site-agent:     tenant-specific API token (for example ATELIER_HARMONIE_TOKEN)
```

The shared API is one process behind Nginx. Each tenant has a separate config,
Payload credential, memory database, and token mapping:

```yaml
atelier_api:
  enabled: true
  prefix: /v1/atelier
  tenants:
    atelier-harmonie:
      config_path: /SOCIAL/configs/atelier-harmonie/config.yaml
      api_token_env: ATELIER_HARMONIE_TOKEN
```

Enable the optional Payload client in the tenant configuration:

```yaml
site:
  payload:
    enabled: true
    url: https://atelier-harmonie.weareheadless.workers.dev
    token_env: ATELIER_HARMONIE_TOKEN
```

The client can read, create drafts, update drafts, and explicitly publish one of
the `pages`, `products`, or `posts` collections. It can also read/update drafts
and explicitly publish the shared `navigation` and `siteSettings` globals. It
rejects fields outside the configured contracts and does not expose arbitrary
Payload API access to Ada.

For tenants that have not completed Intake Ada yet, add a bounded
`customer_profile` section to the tenant config. Mark migrated observations as
`bootstrap_needs_owner_review` and list unknowns explicitly. Ada receives this
as evidence, not as permission to invent prices, dates, contact details, or
other business claims. The profile is a bridge for existing sites; a completed
Intake/customer context remains the canonical source when one exists.

The tenant token is accepted only as `Authorization: Bearer …` on the shared
`/v1/atelier/*` routes. It is never returned to the browser. The same tenant
token is used by site-agent when calling that tenant's Payload content gateway.

## Database-only intake handoff

An existing Atelier tenant can reuse Intake Lab's typed conversation without
starting the Intake Lab build pipeline:

```yaml
atelier_intake:
  enabled: true
  database_only: true
  research:
    enabled: true
```

When a tenant has no ready intake brief, the first shared chat turn is routed to
`DesignIntakeService`. Its durable session, field provenance, customer genesis,
research requests, bounded findings, and insights are written to that tenant's
memory database. No page target, design run, repository clone, preview build,
or publish is started. Once the owner accepts the ready brief, later chat turns
return to the post-intake workspace/design flow and receive the saved intake as
bounded context.

## Endpoints

### `POST /v1/atelier/chat`

Request:

```json
{
  "message": "Change the heading on this page.",
  "conversation_id": 12,
  "context": {
    "site": "atelier-harmonie",
    "mode": "workspace",
    "phase": "workspace",
    "scope": "selected_page",
    "route": "/shop",
    "collection": "products",
    "document": "product-source-id",
    "document_id": "42",
    "slug": "workshop",
    "state": "draft",
    "target": {
      "mode": "workspace",
      "scope": "selected_page",
      "route": {"path": "/shop", "kind": "page", "sourceId": "route-42"},
      "preview": {"state": "draft", "url": "https://atelier.example/atelier-preview/shop"},
      "payload": {"collection": "products", "id": "42", "sourceId": "product-source-id", "slug": "workshop"}
    }
  }
}
```

The response is an asynchronous `{ "job_id": 123, "conversation_id": 12 }`
handle. The post-intake context is added to the queued message so Ada can
interpret “this” without receiving a Payload cookie or direct D1 access. The
shared bridge first checks the tenant's intake phase; intake turns do not
receive or use the page target for website work.

### `GET /v1/atelier/chat/jobs/{job_id}`

Returns the same reduced job shape used by the existing admin UI: status,
steps, and the final result or error.

### `GET /v1/atelier/chat/status?conversation_id=12`

Returns the tenant-scoped phase (`intake` or `workspace`) and whether website
context is enabled for the conversation. The workspace uses this to keep page
selection and edit affordances dormant until intake has been accepted.

### `GET/POST /api/atelier/global`

The Payload Worker exposes a narrow service-authenticated gateway for the
shared `navigation` and `siteSettings` globals. Reads support published/draft
data; updates create drafts; publish is explicit. This is separate from the
conversation bridge and is consumed by Ada's global tools.

Content mutations still belong to Payload. Design requests continue through the
existing site-agent design/candidate/approval machinery; this bridge does not
create a second job system.
