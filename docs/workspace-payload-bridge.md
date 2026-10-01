# Workspace Payload bridge

The Workspace Payload workspace talks to site-agent through a narrow, server-to-
server API. This bridge is separate from the browser password session and does
not change Intake Lab authentication or state.

## Configuration

Every tenant has one canonical token value and one deterministic central env
name. `tenant_token_env(tenant_id)` produces
`PROVISIONED_<TENANT_ID>_TOKEN`; the registry and the tenant's Payload gateway
must use that exact name. The generated Worker always receives the same value
under the stable edge secret name `HELLOADA_SITE_AGENT_TOKEN`:

```text
Payload gateway: token_env = PROVISIONED_TENANT_EXAMPLE_TOKEN
site-agent:     api_token_env = PROVISIONED_TENANT_EXAMPLE_TOKEN
Worker secret:  HELLOADA_SITE_AGENT_TOKEN
```

The two names are intentionally different at the process boundary: the
central API needs a unique env var per tenant, while every generated Worker
uses one stable secret name. Bootstrap owns this mapping; tenant projects must
not invent names such as `ATELIER_SITE_AGENT_TOKEN`.

The shared API is one process behind Nginx. Each tenant has a separate config,
Payload credential, memory database, and token mapping:

```yaml
workspace_api:
  enabled: true
  prefix: /v1/workspace
  tenants:
    tenant-example:
      config_path: /SOCIAL/configs/tenant-example/config.yaml
      api_token_env: PROVISIONED_TENANT_EXAMPLE_TOKEN
```

Enable the optional Payload client in the tenant configuration:

```yaml
site:
  payload:
    enabled: true
    url: https://preview.example.test
    api_prefix: /api/workspace
    token_env: PROVISIONED_TENANT_EXAMPLE_TOKEN
    contract:
      # These names and fields belong to the tenant config, not the adapter.
      collections:
        pages: [sourceId, slug, title, content]
      globals: {}
      media_fields: [alt, description, tags, analysis]
```

The client can read, create drafts, update drafts, and explicitly publish the
configured collections. It can also read/update drafts and explicitly publish
configured globals. It rejects fields outside the configured contracts and does
not expose arbitrary Payload API access to Ada.

The same client exposes the declarative editable-field contract through
`GET/POST /api/workspace/editable-fields`. Ada can inspect or validate the
registered rows, define a stable dotted binding, and update an existing binding
in a draft. These operations never scan source code or rendered markup and never
publish. A field definition is intentionally separate from ordinary document
updates so a page created from scratch can define its visual editing contract
before its components bind to those IDs.

For tenants that have not completed Intake Ada yet, add a bounded
`customer_profile` section to the tenant config. Mark migrated observations as
`bootstrap_needs_owner_review` and list unknowns explicitly. Ada receives this
as evidence, not as permission to invent prices, dates, contact details, or
other business claims. The profile is a bridge for existing sites; a completed
Intake/customer context remains the canonical source when one exists.

The tenant token is accepted only as `Authorization: Bearer …` on the shared
`/v1/workspace/*` routes. It is never returned to the browser. The registry
rejects a tenant when `workspace_api.api_token_env` and
`site.payload.token_env` diverge. The same token value is used by site-agent
when calling that tenant's Payload content gateway.

## Database-only intake handoff

An existing Workspace tenant can reuse Intake Lab's typed conversation without
starting the Intake Lab build pipeline:

```yaml
intake:
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

### `POST /v1/workspace/chat`

Request:

```json
{
  "message": "Change the heading on this page.",
  "conversation_id": 12,
  "context": {
    "site": "tenant-example",
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
      "preview": {"state": "draft", "url": "https://workspace.example/workspace-preview/shop"},
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

### `GET /v1/workspace/chat/jobs/{job_id}`

Returns the same reduced job shape used by the existing admin UI: status,
steps, and the final result or error.

### `GET /v1/workspace/chat/status?conversation_id=12`

Returns the tenant-scoped phase (`intake` or `workspace`) and whether website
context is enabled for the conversation. The workspace uses this to keep page
selection and edit affordances dormant until intake has been accepted.

### `GET/POST /api/workspace/global`

The Payload Worker exposes a narrow service-authenticated gateway for the
shared `navigation` and `siteSettings` globals. Reads support published/draft
data; updates create drafts; publish is explicit. This is separate from the
conversation bridge and is consumed by Ada's global tools.

Content mutations still belong to Payload. Design requests continue through the
existing site-agent design/candidate/approval machinery; this bridge does not
create a second job system.

### Declarative editable fields

`GET /api/workspace/editable-fields` accepts the same document selectors as the
content gateway:

```text
?collection=pages&sourceId=home&draft=true
```

`POST /api/workspace/editable-fields` accepts one of these operations:

- `validate`: check IDs, duplicates, labels, and types without writing;
- `define`: create or complete one stable field binding in the document draft;
- `migrate`: apply an explicit batch of field declarations;
- `set_value`: update a field that already exists, optionally using
  `expected_value` for optimistic concurrency.

Field IDs use dotted names such as `home.hero.heading`. Image values use a
portable media source ID (or a Payload media reference), not a URL discovered
from JSX or HTML. The frontend emits controls only for rows in this registry.

## Source inventory and preview edits

The source bridge is separate from Payload content editing. It reads the
configured repository through the GitHub static adapter, runs the Workspace
repository's `scripts/source-inventory.ts`, and commits one checked source
value or validated batch per file to `site.preview_branch`.

Optional tenant settings select the local checkout and TypeScript runner used
by the inventory command:

```yaml
site:
  clone_path: /srv/site-agent/tenant-example-site
  preview_branch: preview
  source_editor:
    inventory_script: scripts/source-inventory.ts
    node_tool: npx --no-install tsx
    prefer_local_checkout: true
  source_deployment:
    clone_path: /srv/site-agent/tenant-example-site
    worker_name: tenant-example
    preview_alias_prefix: workspace-draft
    cloudflare_env_file: /srv/site-agent/tenant-example-cloudflare.env
```

`GET /v1/workspace/source/inventory?branch=main` or `POST
/v1/workspace/source/inventory` with an optional `{ "branch": "main" }` body
returns the inventory plus its source branch. `POST
/v1/workspace/source/edit` accepts an inventory field, replacement `value`,
`source_hash`, and its `valueStart`/`valueEnd` range. The edit is rejected with
`409` if the file hash or inventoried range is stale, and only editable text,
string literals, JSX text, and image URL fields are patched. The same endpoint
also accepts `{ "edits": [ ... ] }`; all fields and files are validated before
the first write, multiple edits to one file share one commit, and different
files receive one commit each. No deployment or production-branch merge is
performed by the edit route.

After a source commit, `POST /v1/workspace/source/preview` accepts its `branch`
and exact GitHub `commit` and returns a job handle. The job runs typecheck,
lint, a fresh source scan, the Next build, and the OpenNext build in an
isolated Git worktree. It then uploads the exact build as a Cloudflare Worker
version with a version-preview alias; production traffic is unchanged. Poll
`GET /v1/workspace/source/preview/{job_id}` for `preview_url`, `version_id`,
validation checks, or a safe failure. Recent job records are retained in the
tenant memory database for commit/version traceability.

`POST /v1/workspace/source/preview/{job_id}/deploy` is the explicit promotion
boundary. It sends the validated version to 100% production traffic only after
the owner chooses deployment. The Cloudflare API token/account ID remain
server-only; the browser receives only job status, URLs, and commit/version
metadata.
