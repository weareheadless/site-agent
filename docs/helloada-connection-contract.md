# HelloAda connection contract and September/October regression

## Failure modes

An admin page loading successfully does **not** prove Ada is connected.
Atelier returned `ada_unconfigured` even though the active Worker had the
canonical bindings. Its bridge read only `process.env`, rather than the
request-time OpenNext Cloudflare context. OceanicVibes additionally had no
`HELLOADA_SITE_AGENT_TOKEN` binding and was absent from the shared API registry;
its VPS configuration still described the legacy static-site/media adapter.
Its existing CrawlSEO credential was in the tenant's `.env` file but that file
was not connected to the shared credential resolver. This made its enabled
legacy provider abort shared API startup. Preserve and register tenant-owned
credential files when migrating; do not solve this by deleting capabilities
or using another customer's provider token.
These are separate from the earlier Payload server-props/client-nav failure.

After fixing Atelier's request-time lookup, the authenticated gateway returned
401 with the VPS tenant token. This proved that the existing Worker secret
**value** also differed despite the correct binding name. Resynchronize the
existing canonical tenant token; secret-name presence alone cannot detect this.

## Required invariant (every tenant)

| Location | Contract |
| --- | --- |
| Worker variable | `SITE_AGENT_URL=https://api.helloada.app/v1` |
| Worker secret | `HELLOADA_SITE_AGENT_TOKEN` (tenant-specific value) |
| Shared API registry | Tenant ID, existing config path, `api_token_env` |
| VPS tenant config | `site.payload.token_env` equals that registry name |
| VPS Payload content gateway | `site.payload.api_prefix=/api` (`/api/content`) |
| Browser workspace bridge | `/api/helloada/*`, authenticated by the Payload session |
| VPS environment | That variable contains the same value as the Worker secret |
| Admin site config | `tenantId` equals the authenticated backend tenant |

`PROVISIONED_<NORMALIZED_TENANT>_TOKEN` is the canonical VPS name. The Worker
name is always `HELLOADA_SITE_AGENT_TOKEN`. These names are intentionally
different; their **values** must match. Never add fallback token aliases,
share a token between tenants, or rotate `PAYLOAD_SECRET` to repair Ada.

The shared package's **server-only** `./server` export reads
`getCloudflareContext().env` at request time. `process.env` is used only when
there is no Cloudflare context (local Node). An empty Worker binding fails
closed, even if a process-level stale token exists. Do not import this export
from a client component or export it from the UI barrel.

## Readiness and release gate

1. Run the shared package connection tests, typecheck and tenant-auth tests.
2. Validate every tenant registry entry and matching Payload token name before
   restarting the API. Preserve existing data directories/history. Keep a
   protected backup of edited operational configuration.
3. Verify authenticated `GET /v1/workspace/connection` using each tenant's own
   service token: correct `tenant`, `connected: true`, `ready: true`. This is a
   credential/configuration readiness check, **not** a paid model request.
4. Build a clean checkout with the pinned immutable admin release. Inspect the
   artifact for the connection/Growth routes, UI, and unchanged brand asset.
5. Deploy the exact artifact, wait for terminal success, reload a fresh
   authenticated admin document with a release query.
6. In that real owner session verify same-origin `/connection`, chat status,
   Growth, website preview and the connected indicator. Confirm unauthenticated
   connection/Growth requests are rejected. Do not accept a public health page,
   HTTP 200 login redirect, secret-list metadata, or a local mock as proof.

The owner-authenticated connection response exposes presence booleans,
binding source, expected tenant and a bounded failure code only. It never
returns a service token, secret URL, environment dump, or provider credentials.
`tenant_mismatch`, `runtime_unconfigured`, `backend_unreachable`,
`backend_rejected`, and `ai_unconfigured` must block a claimed successful
release. The nav retries periodically with a timeout; no indefinite spinner.

Run the server-side preflight with the protected environment on the host:
`PYTHONPATH=src .venv/bin/python scripts/check-helloada-connections.py --config /SOCIAL/configs/site-agent-api/config.yaml --env-file /SOCIAL/configs/site-agent-api/.env --api-url https://api.helloada.app/v1`.
It returns nonzero on missing credentials, a registry/Payload name mismatch,
rejected authentication or a wrong/unready tenant, without printing secrets.
It also performs a read-only authenticated Worker content request, catching a
token-value mismatch in the reverse direction without creating a chat job.
For a scoped customer release add `--tenant atelier-harmonie --tenant oceanicvibes`.
Other intake/lab tenants are not silently considered deployed customer sites.

The October 3 clean release exposed a second incomplete migration: Atelier's
VPS config still declared `/api/atelier` after the old Worker routes were removed.
The reverse content read failed with 404 although backend readiness passed.
Atelier now uses the same `/api/content` service gateway as the default template
and Oceanic. The browser workspace stays at `/api/helloada/*`; its session auth
is deliberately different from the server-to-server content gateway's token
auth. Changing Worker routes requires migrating their configured caller in the
same release; token readiness alone does not prove that path works.

## Growth behavior

Growth is a read-only tenant projection of actual analytics, insights, research,
drafts, reports and registered schedules. Missing metrics render as unavailable,
not zero or demonstration numbers. Setup and planning actions prepare editable
Ada requests; merely opening Growth never provisions Google accounts, starts
paid research, changes scheduling, or publishes content. Existing approvals
continue to govern production changes. A provider being configured is not proof
that it has collected data; show those states separately.

Tests prevent these known regressions; they cannot guarantee that external
providers, credentials or deployments will never fail. When readiness fails,
fix the first failing boundary and preserve the owner's published website.

## Chat must see the same Growth state

The October 3 configuration-check reply was misleading: chat received only a
GA4 snapshot and a GA4-only `get_metrics` tool. The Growth screen could see a
verified Search Console property and configured CrawlSEO service, but Ada could
not. This was a context boundary failure, not evidence that Google provisioning
had failed.

`application.growth.growth_chat_context` now projects the same source states as
the owner dashboard into every tool-enabled chat. `get_growth` refreshes that
read-only projection; `get_metrics` reads bounded GA4 **and** GSC snapshots with
their capture timestamps. Neither operation provisions, spends, publishes, or
enables schedules. Bound structured fields before serialization; never slice a
JSON response by character count.

Distinguish a configured research capability from approved seeds/results, and
a verified search property from available query data. Do not request owner
accounts or new setup when platform records already establish the connection.
Tests cover this boundary, missing evidence, zero-valued metrics and exclusion
of credential fields. No tenant-specific response or fallback is involved.
