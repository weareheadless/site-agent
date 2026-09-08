# CrawlSEO Connectivity Implementation Plan

## Purpose

Implement the first production-shaped connection between:

- the OceanicVibes site-agent instance;
- CrawlSEO;
- Google Search Console;
- Google Analytics 4.

OceanicVibes is the first bound project, and the implementation uses the same
tenant, credential, integration, and MCP boundaries that HelloAda provisioning
calls automatically.

This phase only moves data connectivity into place. It does not change the
site-agent's prompts, strategy logic, recommendations, or website mutation
behavior.

## Desired Result

```text
Google Search Console ─┐
                       ├──> CrawlSEO ingestion and storage
Google Analytics 4 ────┘              │
                                      │ project-scoped MCP
                                      ▼
                         OceanicVibes site-agent
                                      │
                                      ▼
                          existing metric snapshots
```

After this work:

1. CrawlSEO owns Google credentials and Google API access.
2. CrawlSEO stores OceanicVibes GSC and GA4 data.
3. OceanicVibes site-agent has no Google credential.
4. OceanicVibes receives a revocable service credential scoped to one project.
5. site-agent reads SEO and analytics through CrawlSEO's remote MCP server.
6. Existing site-agent jobs continue writing `gsc` and `ga4` snapshots in their
   current shapes so downstream intelligence does not need to change yet.
7. The OceanicVibes bootstrap and HelloAda provisioning call the same idempotent
   application service.

## Product Constraint

The future one-click experience without a customer Google account is possible
only in a platform-managed mode where HelloAda controls:

- the generated website deployment;
- the relevant DNS records or delegated hostname;
- the Google Analytics property/data stream;
- Search Console verification;
- the Google credential used by CrawlSEO.

Existing websites or customer-owned Google properties require an explicit
connection step: OAuth consent, service-account sharing, or a documented manual
grant. The data model in this plan supports both modes.

## Current State

### OceanicVibes site-agent

Runtime config:

- `/SOCIAL/configs/oceanicvibes/config.yaml`
- `ga.property_id`: `551030734`
- `seo.site_url`: `https://oceanicvibes.com/`
- Google credential: `GA4_SERVICE_ACCOUNT` in the instance environment
- site-agent services:
  - `site-agent@oceanicvibes.service`
  - `site-agent-oceanicvibes-admin.service`

Direct Google readers:

- `src/site_agent/senses/ga.py`
- `src/site_agent/senses/seo.py`

Scheduled jobs:

- `ga_snapshot` writes source `ga4`
- `seo_snapshot` writes source `gsc`
- both are registered in `src/site_agent/core/jobs.py`

`seo.py` already reserves `source: mcp`, but currently throws an error.

### CrawlSEO

- Next.js app runs under PM2 on port `3001`.
- Current MCP server in `/SEO/mcp/server.ts` is stdio-only.
- Current MCP tools have no tenant authentication and accept arbitrary site IDs.
- `User` currently acts as the tenant.
- GSC tokens are attached to `User.googleTokens`.
- No GA4 storage or GA4 client exists.
- CrawlSEO already stores GSC keyword/page rows, crawl results, vitals, and SEO
  opportunities.

The current stdio MCP server must not be exposed remotely as written.

## Non-Goals

- HelloAda signup or provisioning UI
- GitHub repository creation
- Cloudflare Pages project creation
- automatic domain purchase or DNS delegation
- changes to site-agent strategy or prompts
- automatic SEO fixes
- arbitrary MCP tool discovery by site-agent
- customer billing or entitlements
- migrating all existing CrawlSEO users/sites in one release

## Architecture Decisions

### 1. HelloAda project identity is the durable boundary

Use stable external IDs even though OceanicVibes is provisioned manually.

Initial identifiers:

```text
externalOrganizationId: helloada_test
externalProjectId: oceanicvibes
instanceName: oceanicvibes
domain: oceanicvibes.com
```

Do not use email, domain, repository name, or display name as the durable tenant
identifier.

### 2. Human login and machine access remain separate

CrawlSEO's local email/password login remains an operator interface.

site-agent uses a service credential, never:

- a browser cookie;
- the local admin password;
- a Google token;
- a platform-wide CrawlSEO token.

### 3. Provisioning uses application services, not MCP

Create an idempotent CrawlSEO project-provisioning service callable from:

- the OceanicVibes setup script now;
- a service-authenticated HelloAda endpoint later.

MCP is for runtime data access only.

### 4. Google authorization belongs to CrawlSEO

Implement a Google connection abstraction supporting:

```text
SERVICE_ACCOUNT
OAUTH
PLATFORM_MANAGED
```

Only `SERVICE_ACCOUNT` must be operational for the OceanicVibes milestone.
Do not make GSC/GA clients depend on a `User` record.

### 5. MCP authorization determines project scope

The authenticated service credential resolves the project. Read tools should
not accept a free-form `siteId` for the common one-site project case.

If a tool accepts any resource ID, it must verify that the resource belongs to
the authenticated project before querying it.

### 6. Return structured data

New remote MCP tools return `structuredContent` with a stable schema plus a
compact text fallback. Do not make site-agent parse the existing text tables in
`mcp/formatters.ts`.

## Data Model

Implement the following Prisma models or equivalent names. Preserve existing
records through nullable compatibility columns during the migration.

### Workspace

```text
id                      String primary key
externalOrganizationId  String unique
name                    String
status                  ACTIVE | SUSPENDED
createdAt
updatedAt
```

### Project

```text
id                 String primary key
workspaceId        String foreign key
externalProjectId  String
name               String
status             ACTIVE | SUSPENDED | DELETING
createdAt
updatedAt

unique(workspaceId, externalProjectId)
```

### Site changes

Add nullable `projectId` to `Site` and make `userId` nullable. Existing rows
retain their current user owner. New project-provisioned sites use `projectId`
as their authorization boundary and may optionally receive an operator
`userId` for temporary visibility in the legacy UI.

For the OceanicVibes binding, the provisioning command may accept an optional
`CRAWLSEO_OPERATOR_USER_EMAIL` and attach that user for dashboard visibility.
Future HelloAda provisioning must be able to omit it. Machine authorization
must never depend on this compatibility owner.

Add constraints/indexes:

```text
index(projectId)
unique(projectId, domain)
```

New services must scope by `projectId`. Existing browser routes may continue
using non-null `userId` until a separate workspace-membership UI migration.
Browser routes must handle project-only sites without throwing.

### GoogleConnection

```text
id                    String primary key
workspaceId           String foreign key
type                  SERVICE_ACCOUNT | OAUTH | PLATFORM_MANAGED
status                ACTIVE | NEEDS_REAUTH | REVOKED | ERROR
label                 String
encryptedCredentials  Text
scopes                Json
metadata              Json
expiresAt             DateTime nullable
lastUsedAt            DateTime nullable
createdAt
updatedAt

unique(workspaceId, type, label)
```

Credential examples:

- service account: encrypted JSON key document;
- OAuth: encrypted refresh token and refresh metadata;
- platform managed: secret reference or encrypted automation credential.

Use a dedicated `CREDENTIAL_ENCRYPTION_KEY`. Do not derive integration
encryption from the browser session secret.

### IntegrationGrant

```text
id                  String primary key
connectionId        String foreign key
projectId           String foreign key
siteId              String foreign key nullable
provider            GOOGLE_SEARCH_CONSOLE | GOOGLE_ANALYTICS
externalResourceId  String
metadata            Json
status              ACTIVE | UNVERIFIED | ERROR | REVOKED
lastValidatedAt     DateTime nullable
lastSuccessfulAt    DateTime nullable
safeErrorCode       String nullable
createdAt
updatedAt

unique(connectionId, projectId, provider, externalResourceId)
```

Connection status describes whether the credential itself is usable. Grant
status describes access to one specific GSC/GA4 resource. MCP diagnostics and
`seo_get_project` must report grant status, not infer both integrations from the
shared connection status.

OceanicVibes grants:

```text
GOOGLE_SEARCH_CONSOLE -> https://oceanicvibes.com/
GOOGLE_ANALYTICS      -> 551030734
```

### ServicePrincipal

```text
id         String primary key
projectId  String foreign key
name       String
status     ACTIVE | REVOKED
createdAt
updatedAt

unique(projectId, name)
```

### ServiceCredential

```text
id                  String primary key
servicePrincipalId  String foreign key
tokenPrefix         String
tokenHash           String unique
scopes              Json
expiresAt           DateTime nullable
lastUsedAt          DateTime nullable
revokedAt           DateTime nullable
createdAt
```

Generate at least 32 random bytes. Store only a SHA-256 hash and a non-secret
prefix. Return the plaintext token once.

OceanicVibes scopes:

```text
seo:read
analytics:read
crawl:read
crawl:run
```

Credential issuance is not safely replayable after the plaintext token has
been returned. The provisioning operation must therefore accept an
`idempotencyKey` and persist a credential-delivery state. A retry with the same
key returns the same non-secret resource result but never invents another
credential. If the caller lost the one-time secret, it must request an explicit
rotation with a new idempotency key.

### AnalyticsSnapshot

For this phase, store normalized GA4 snapshots rather than raw provider
responses:

```text
id           String primary key
siteId       String foreign key
source       GA4
periodStart  DateTime
periodEnd    DateTime
capturedAt   DateTime
data         Json
syncRunId    String nullable

index(siteId, capturedAt)
unique(siteId, source, periodStart, periodEnd)
```

`data` should preserve the shape site-agent currently expects from
`weekly_summary()`:

```json
{
  "current_week": {},
  "previous_week": {},
  "delta_pct": {},
  "top_pages": [],
  "sources": [],
  "organic_queries": []
}
```

### SyncRun

```text
id          String primary key
jobId       String foreign key
siteId      String foreign key
source      GSC | GA4 | CRAWL | VITALS
status      PENDING | RUNNING | COMPLETED | FAILED
startedAt   DateTime nullable
finishedAt  DateTime nullable
attempt     Int
errorCode   String nullable
errorText   String nullable
metadata    Json
createdAt
updatedAt

unique(jobId, attempt)
```

`SyncRun` is the durable/auditable execution record for one attempt, not the
queue itself. Its status and completion fields are updated as that attempt
progresses, but completed records are not reused for retries.

### Job

Add a durable PostgreSQL-backed queue for GSC, GA4, crawl, and vitals work:

```text
id               String primary key
projectId        String foreign key
siteId           String foreign key
kind             GSC_SYNC | GA4_SYNC | CRAWL | VITALS_SYNC
status           PENDING | RUNNING | COMPLETED | FAILED | CANCELLED
payload          Json
idempotencyKey   String
attempts         Int
maxAttempts      Int
nextAttemptAt    DateTime
leaseOwner       String nullable
leaseExpiresAt   DateTime nullable
heartbeatAt      DateTime nullable
lastErrorCode    String nullable
createdAt
updatedAt

unique(projectId, kind, idempotencyKey)
index(status, nextAttemptAt)
```

Create a separate worker process that atomically claims jobs with a lease,
heartbeats long crawls, retries with bounded backoff, and recovers expired
leases after restart. A job creates one `SyncRun` per attempt. Provisioning and
MCP mutation tools enqueue jobs; they do not execute provider work inside the
request process.

Do not persist provider credentials, access tokens, or raw private keys in
errors or metadata.

## CrawlSEO Implementation

### Step 1: Introduce tenant-scoped services

Create application services outside route handlers and MCP handlers:

```text
lib/projects/provision-project.ts
lib/projects/project-context.ts
lib/auth/service-credentials.ts
lib/integrations/google/connections.ts
lib/integrations/google/credential-provider.ts
lib/integrations/google/gsc.ts
lib/integrations/google/ga4.ts
lib/sync/gsc.ts
lib/sync/ga4.ts
lib/jobs/queue.ts
lib/jobs/worker.ts
```

Required service operations:

```ts
provisionProject(input)
createServiceCredential(projectId, scopes)
authenticateServiceToken(token)
requireProjectScope(principal, scope)
resolveProjectSite(projectId)
enqueueGscSync(siteId, idempotencyKey)
enqueueGa4Sync(siteId, idempotencyKey)
getProjectSeoSnapshot(projectId, options)
```

`provisionProject()` must be idempotent on external organization/project IDs.
Repeated execution must return the same workspace, project, and site rather
than create duplicates. Its input must include an idempotency key. Connection,
grant, principal, and job creation require natural uniqueness constraints or
idempotency keys so two concurrent provisioning calls converge on the same
resources.

Before creating a crawlable site, canonicalize the domain, run the existing
public-IP/SSRF validation, and require one of:

- HelloAda-controlled deployment/DNS evidence;
- a verified GSC property grant matching the domain;
- an explicit operator override for the OceanicVibes test binding.

Record the verification method. Do not let a future customer provision and
repeatedly crawl arbitrary third-party public domains.

### Step 2: Decouple Google clients from User

Refactor `/SEO/lib/google/gsc-client.ts` so API methods receive a credential
provider or connection context instead of `userId`.

Target interface:

```ts
interface GoogleCredentialProvider {
  getAccessToken(scopes: string[]): Promise<string>;
}
```

Implement:

```text
ServiceAccountCredentialProvider
OAuthCredentialProvider
```

Only the service-account implementation is required to pass live
OceanicVibes tests now. Add unit tests for the OAuth interface contract, but
do not build the new OAuth UI in this phase.

Use Google's supported authentication library instead of implementing JWT
signing manually.

### Step 3: Normalize GSC ingestion

Move the shared logic currently split between:

- `app/api/gsc/sync/route.ts`
- `lib/workers/gsc-sync.ts`

into one project-aware application service.

The service must:

- resolve the GSC grant for the site/project;
- obtain a token from `GoogleCredentialProvider`;
- create/update a `SyncRun`;
- fetch GSC query and page data;
- write keyword/page rows transactionally in bounded batches;
- update the sync run status;
- redact provider errors.

Fix the current data collision before importing OceanicVibes. Current GSC
queries include query, page, date, device, and country while the uniqueness key
is only `(siteId, query, date)`. Choose one of these explicit models:

1. store fully dimensional rows with a uniqueness key including every
   dimension; or
2. query/store only the dimensions represented by the uniqueness key.

For this milestone, prefer fully dimensional rows so future analysis can use
device, country, and landing page. Make every uniqueness component non-null:

```text
siteId, query, date, page, device, country
```

Normalize missing dimensions to an empty string at ingestion, backfill existing
null values, then add the compound unique constraint. PostgreSQL nullable
columns must not be used directly in this uniqueness key because multiple nulls
would defeat deterministic upserts.

### Step 4: Add GA4 ingestion

Port the normalized report behavior from
`/SOCIAL/site-agent/src/site_agent/senses/ga.py` into CrawlSEO.

Required reports:

- current seven-day totals;
- previous seven-day totals;
- percentage deltas;
- top pages;
- channel groups/traffic sources;
- organic search queries when available.

Store one normalized `AnalyticsSnapshot` per period. Provider response details
must remain behind the integration adapter.

### Step 5: Add project-scoped service authentication

Implement bearer authentication independent from local browser sessions.

Authentication result:

```ts
interface ServicePrincipalContext {
  credentialId: string;
  servicePrincipalId: string;
  workspaceId: string;
  projectId: string;
  scopes: string[];
}
```

Requirements:

- constant-time token hash comparison where applicable;
- reject missing, expired, or revoked credentials;
- reject suspended projects/workspaces;
- update `lastUsedAt` without blocking every request if possible;
- never log the token;
- return generic `401`/`403` errors;
- rate-limit by credential/project;
- include a request/correlation ID in logs.

Revalidate the bearer credential, revocation state, scopes, and project status
on every HTTP request or every tool invocation. Do not cache authorization only
at MCP session initialization. Revocation and suspension must affect existing
Streamable HTTP sessions no later than their next tool call.

### Step 6: Build a separate remote MCP process

Do not expose the existing stdio server directly.

Create a separate entry point, for example:

```text
/SEO/mcp/http-server.ts
```

Run it as a separate PM2 process on localhost port `3005` in the current
deployment (port `3004` is occupied by another local service), and
proxy it through Nginx:

```text
https://crawlseo.helloada.app/mcp
```

Use MCP Streamable HTTP from the official SDK. Require
`Authorization: Bearer ...` before creating the MCP request context.

Enforce request and response byte limits in the CrawlSEO HTTP process before
buffering/parsing complete MCP messages. The site-agent must also enforce its
configured limit at the transport-read boundary; a post-JSON-parse length check
is not sufficient.

Keep `/SEO/mcp/server.ts` as a local administrative stdio server, but clearly
label it unscoped and never route public traffic to it.

### Step 7: Implement the first remote MCP tools

Register a finite list. Do not dynamically expose every internal function.

#### `seo_get_project`

Returns:

```json
{
  "project_id": "...",
  "site": {
    "domain": "oceanicvibes.com",
    "url": "https://oceanicvibes.com/"
  },
  "connections": {
    "gsc": {"status": "active", "property": "..."},
    "ga4": {"status": "active", "property": "..."}
  }
}
```

#### `seo_get_search_summary`

Input:

```json
{"days": 28, "query_limit": 10}
```

Returns the existing site-agent GSC summary shape:

```json
{
  "period_days": 28,
  "top_queries": []
}
```

#### `seo_get_analytics_summary`

Returns the existing site-agent GA4 weekly summary shape.

#### `seo_get_crawl_summary`

Returns latest crawl status, health score, page count, issue count, and finish
time.

#### `seo_get_crawl_issues`

Inputs:

```json
{"severity": "CRITICAL", "limit": 50}
```

The latest project-owned crawl is implied unless an owned crawl ID is given.

#### `seo_run_crawl`

Requires `crawl:run`. This is the only mutation in the first MCP surface.
Enqueue a durable `Job` with an idempotency key and return its identifier. Do
not use request-local fire-and-forget promises.

### Step 8: Operational deployment

Add:

- PM2 start definition or checked-in ecosystem config;
- PM2 definition for the durable job worker;
- health endpoint for the MCP process;
- Nginx location for `/mcp` with streaming-safe proxy settings;
- startup documentation;
- structured logs without credentials;
- graceful shutdown handling.

The health endpoint must test process readiness, not Google API availability.
Expose Google connection health separately through a scoped tool or internal
status endpoint.

## OceanicVibes Binding Command

Create an idempotent command such as:

```text
npm run provision:oceanicvibes
```

Implementation should call `provisionProject()` and accept secrets/paths via
environment variables, not command-line arguments.

Inputs:

```text
HELLOADA_ORGANIZATION_ID=helloada_test
HELLOADA_PROJECT_ID=oceanicvibes
CRAWLSEO_SITE_DOMAIN=oceanicvibes.com
CRAWLSEO_GSC_PROPERTY=https://oceanicvibes.com/
CRAWLSEO_GA4_PROPERTY_ID=551030734
CRAWLSEO_GOOGLE_SERVICE_ACCOUNT_FILE=<path>
  CRAWLSEO_PROVISIONING_IDEMPOTENCY_KEY=<stable-operator-generated-id>
  CRAWLSEO_OPERATOR_USER_EMAIL=<optional-legacy-dashboard-owner>
  CRAWLSEO_DATAFORSEO_LOGIN=<platform API login, server environment only>
  CRAWLSEO_DATAFORSEO_PASSWORD=<platform API password, server environment only>
# Pilot-only alternative when no DNS/GSC evidence is available:
# CRAWLSEO_DOMAIN_VERIFICATION_METHOD=operator_override
# CRAWLSEO_ALLOW_DOMAIN_OVERRIDE=true
```

Accepted verification methods are `helloada_dns`, `verified_gsc`, and the
OceanicVibes-only `operator_override`. The override must be explicitly enabled
and is rejected for other project IDs.

Behavior:

1. Create/reuse workspace.
2. Create/reuse project.
3. Create/reuse site.
4. Import and encrypt the service-account credential.
5. Create/reuse GSC and GA4 grants.
6. Create/reuse service principal.
7. Create/reuse the encrypted platform DataForSEO credential and grant it to
   the project. Automated HelloAda provisioning fails closed unless the
   platform variables or an explicitly supplied legacy operator BYOK key exist.
8. Revoke any superseded test credential.
9. Generate one new service credential only for a new explicit credential
   issuance/rotation idempotency key.
9. Print the plaintext token once.
10. Trigger initial GSC and GA4 syncs.

Never print the Google credential or access token.

## site-agent Implementation

### Step 1: Add CrawlSEO provider configuration

Extend `defaults.yaml`:

```yaml
providers:
  crawlseo:
    enabled: false
    url: ""
    token_env: CRAWLSEO_SERVICE_TOKEN
    timeout_seconds: 30
    max_response_bytes: 2097152
```

Add environment mapping:

```yaml
env:
  crawlseo_service_token: CRAWLSEO_SERVICE_TOKEN
```

Update OceanicVibes config only after the MCP server is live:

```yaml
providers:
  crawlseo:
    enabled: true
    url: https://crawlseo.helloada.app/mcp
    token_env: CRAWLSEO_SERVICE_TOKEN
    timeout_seconds: 30
    max_response_bytes: 2097152

ga:
  enabled: true
  source: crawlseo

seo:
  enabled: true
  source: crawlseo
```

Add the generated token to:

```text
/SOCIAL/configs/oceanicvibes/.env
```

with mode `600`:

```text
CRAWLSEO_SERVICE_TOKEN=...
```

### Step 2: Implement a narrow MCP client adapter

Follow the repository's required integration direction:

```text
Sense wrapper -> CrawlSEO application service -> typed contract -> MCP adapter
```

Create modules such as:

```text
src/site_agent/core/contracts.py              # CrawlSEO read contract types
src/site_agent/hands/crawlseo.py               # MCP transport/client only
src/site_agent/application/crawlseo.py         # project read and crawl request service
src/site_agent/senses/crawlseo.py              # read-only normalized sense facade
```

Use the official MCP Python client with Streamable HTTP. Do not implement a
partial JSON-RPC protocol by hand.

The adapter owns:

- URL and token configuration;
- MCP session initialization;
- fixed tool invocation;
- timeout handling;
- response-size limits;
- structured-content validation;
- safe error translation;
- correlation IDs.

The read-only sense facade exposes typed/small functions:

```py
project(config) -> dict
search_summary(config, days=28, limit=10) -> dict
analytics_summary(config) -> dict
crawl_summary(config) -> dict
crawl_issues(config, severity=None, limit=50) -> list[dict]
```

Do not expose arbitrary MCP tool names to brain code.

`request_crawl()` belongs only on the application service and must pass through
the existing approval/idempotency boundary before it is ever exposed to agent
intelligence.

Add the official MCP package to an explicit `crawlseo` project extra (or the
base dependencies if every deployment requires it). The official client is
async while current jobs are synchronous. Create one long-lived MCP client
runtime per process with a dedicated event-loop thread and deterministic
startup/shutdown hooks. Do not call `asyncio.run()` or create a new MCP session
for every scheduled summary. Inject the application service/client through
`Runtime` composition.

### Step 3: Preserve current sense contracts

Update `senses/seo.py` and its callers to accept the injected CrawlSEO read
service while preserving a direct-provider compatibility path:

```text
source=gsc       -> existing direct behavior during migration
source=crawlseo  -> CrawlSEO MCP adapter
```

`summary()` must return the same shape for both sources.

Update `senses/ga.py` similarly:

```text
source=ga4       -> existing direct behavior during migration
source=crawlseo  -> CrawlSEO MCP adapter
```

`weekly_summary()` must return the same shape for both sources.

This preserves:

- `core/jobs.py`;
- metric snapshot source names;
- strategist/report consumers;
- current admin analytics views.

Define exact compatibility schemas.

GSC query rows always contain:

```json
{
  "query": "string",
  "clicks": 0,
  "impressions": 0,
  "ctr": 0.0,
  "position": 0.0
}
```

Correct the direct GSC reader to derive `query` from `row.keys[0]`; do not rely
on `dimensionHeaders`, which the current implementation incorrectly expects.

### Step 4: Add runtime capability declarations

Register only known CrawlSEO capabilities in
`application/capabilities.py`:

```text
crawlseo.project.read
crawlseo.search.read
crawlseo.analytics.read
crawlseo.crawl.read
crawlseo.crawl.request
```

Read capabilities are `READ`. `crawlseo.crawl.request` is an
`EXTERNAL_MUTATION` and should require owner approval when exposed to the
agent intelligence later. The scheduled data pull does not need an approval.

Do not expose these as chat tools in this phase.

### Step 5: Add diagnostics

Keep the existing offline `site-agent check` deterministic. Add an explicit
online mode, for example `site-agent check --online`, with bounded timeouts and
non-zero exit status for failed required connectivity checks:

- CrawlSEO provider enabled;
- token environment variable set;
- MCP endpoint reachable;
- credential accepted;
- project resolves to expected domain;
- GSC connection active;
- GA4 connection active;
- latest snapshot freshness.

Do not print the token or provider payloads containing credentials.

## Migration and Cutover Procedure

Perform the cutover in this order.

### Stage A: CrawlSEO setup

1. Back up the CrawlSEO PostgreSQL database.
2. Apply Prisma migrations.
3. Deploy tenant/project and Google connection services.
4. Deploy and start the durable job worker.
5. Deploy remote MCP process behind Nginx.
6. Run the OceanicVibes binding command using the existing service-account
   file as input.
7. Save the generated project token in a temporary mode-600 file.
8. Enqueue initial GSC and GA4 syncs and wait for successful completion.
9. Verify data through MCP using the project token.

### Stage B: site-agent shadow read

1. Add `CRAWLSEO_SERVICE_TOKEN` to OceanicVibes environment.
2. Configure the CrawlSEO provider.
3. Keep direct Google source configuration available temporarily.
4. Execute one CrawlSEO GSC summary and compare with direct GSC output.
5. Execute one CrawlSEO GA4 summary and compare with direct GA4 output.
6. Freeze both comparisons to the same completed UTC date range (exclude today).
7. Require identical top-query/page identities and no more than 1% numeric
   difference after documented rounding. Any larger difference fails cutover.

### Stage C: source cutover

1. Set `seo.source: crawlseo`.
2. Set `ga.source: crawlseo`.
3. Restart both OceanicVibes services.
4. Run `seo_snapshot` and `ga_snapshot` manually once.
5. Confirm new `gsc` and `ga4` metric snapshots in OceanicVibes SQLite.
6. Confirm strategist/report code can read those snapshots unchanged.

### Stage D: credential removal

Only after successful shadow comparison and scheduled runs:

1. Remove `GA4_SERVICE_ACCOUNT` from OceanicVibes `.env`.
2. Delete/quarantine the plaintext fallback file currently available at
   `/home/admin/.config/ga4-service-account.json`; merely removing the
   environment variable is insufficient because both direct readers fall back
   to that path.
3. Confirm the OceanicVibes service process cannot read any Google credential
   path and direct Google access fails.
4. Confirm CrawlSEO-backed snapshots still succeed.
5. Keep the Google credential only in CrawlSEO's encrypted connection store.

For rollback, provide a privileged CrawlSEO operator command that can export a
temporary mode-600 service-account file from the encrypted connection. Do not
leave a standing plaintext rollback copy readable by site-agent.

## Test Plan

### CrawlSEO unit tests

- service token generation stores only a hash;
- valid token resolves the expected project;
- revoked and expired tokens fail;
- scope enforcement returns `403`;
- Google credential encryption round trip;
- service-account access-token provider contract;
- GSC dimensional row uniqueness;
- GA4 provider normalization;
- provisioning is idempotent;
- provider errors redact credentials.

### CrawlSEO integration tests

- token A cannot access project B;
- arbitrary site/crawl IDs outside the project fail;
- MCP initialize and tools/list require authentication;
- every tool requires its documented scope;
- structured content matches schemas;
- MCP response limits are enforced;
- duplicate sync requests do not corrupt data;
- duplicate sync requests with the same idempotency key converge on one job;
- concurrent workers cannot claim the same job lease;
- an expired worker lease is recovered after restart;
- failed sync writes a sanitized `SyncRun`.

### site-agent unit tests

- CrawlSEO provider configuration validation;
- bearer header is attached without being logged;
- structured MCP responses are validated;
- timeout and oversized response errors are safe;
- `seo.summary()` parity between direct and CrawlSEO fixtures;
- `ga.weekly_summary()` parity between direct and CrawlSEO fixtures;
- no arbitrary tool invocation method is exposed to brain code.

### site-agent contract tests

Use a fake MCP provider for:

- successful GSC summary;
- successful GA4 summary;
- unauthorized token;
- unavailable provider;
- malformed structured content;
- stale data;
- revoked credential.

### Live OceanicVibes acceptance tests

1. `seo_get_project` returns only OceanicVibes.
2. `seo_get_search_summary` returns real GSC data.
3. `seo_get_analytics_summary` returns real GA4 data.
4. A token without `crawl:run` cannot start a crawl.
5. The OceanicVibes token cannot access any existing CrawlSEO site.
6. site-agent records fresh `gsc` and `ga4` metric snapshots.
7. Removing `GA4_SERVICE_ACCOUNT` from site-agent does not break snapshots.
8. Restarting CrawlSEO MCP and site-agent does not require reprovisioning.
9. Revoking the token stops site-agent access immediately.
10. Rotating the token restores access without changing project records.

For this test project, define "fresh" as:

- latest successful GSC sync completed within 26 hours;
- latest successful GA4 sync completed within 26 hours;
- latest technical crawl completed within 8 days.

Live data acceptance requires at least one completed sync. Zero rows may be a
valid provider result for a new property, but connection/grant validation and
sync completion must still be successful.

## Security Requirements

- Never commit service credentials, Google credentials, tokens, or generated
  instance `.env` files.
- Rotate the Google service-account key if it has ever appeared in logs or
  source control.
- Use a dedicated encryption key with documented rotation strategy.
- Hash service tokens at rest.
- Scope every query by authenticated project.
- Enforce response limits and timeouts on both MCP sides.
- Redact Google and MCP provider errors.
- Keep Nginx and MCP process bound to least privilege.
- Rate-limit failed token authentication.
- Log credential ID/prefix, project ID, tool, duration, and outcome, never the
  plaintext token.

## Observability

Each CrawlSEO MCP call should log:

```text
request_id
credential_id
project_id
tool_name
duration_ms
result_status
response_bytes
```

Each sync should expose:

```text
source
site_id
sync_run_id
started_at
finished_at
rows_read
rows_written
status
safe_error_code
```

site-agent should record a normal action when a scheduled snapshot succeeds and
a safe provider action when it fails.

## Definition of Done

The connectivity phase is complete when:

- OceanicVibes is represented by a CrawlSEO workspace/project/site;
- its Google service-account credential exists only in CrawlSEO;
- GSC and GA4 data sync successfully into CrawlSEO;
- remote MCP is authenticated and project-scoped;
- OceanicVibes site-agent pulls both summaries through MCP;
- existing site-agent metric snapshot shapes remain unchanged;
- direct Google credentials have been removed from OceanicVibes;
- token revocation and rotation are tested;
- tenant-isolation tests pass;
- CrawlSEO has a configured test runner and `npm test`, `npm run lint`, and
  `npm run build` pass;
- site-agent `.venv/bin/pytest -q`, compileall, and wheel build pass;
- deployment and rollback steps are documented.

## Rollback

If the MCP cutover fails:

1. restore `seo.source: gsc` and `ga.source: ga4`;
2. use the privileged CrawlSEO operator export command to create a temporary
   mode-600 Google credential, then restore `GA4_SERVICE_ACCOUNT`;
3. restart site-agent services;
4. leave CrawlSEO project/integration records intact for diagnosis;
5. revoke only the OceanicVibes MCP credential if compromise is suspected;
6. do not delete imported data during rollback.

## Recommended Implementation Order

1. Prisma tenant/integration/service-credential models
2. credential encryption and token authentication
3. project provisioning application service
4. durable job queue, worker, and lease recovery
5. Google credential provider abstraction
6. GSC ingestion refactor and uniqueness fix
7. GA4 ingestion and snapshot storage
8. remote authenticated MCP server
9. OceanicVibes binding command and initial sync
10. site-agent CrawlSEO MCP adapter
11. direct/CrawlSEO parity tests
12. OceanicVibes cutover
13. direct Google credential removal
14. isolation, rotation, restart, and rollback verification

Do not start by wiring the current unscoped stdio MCP server to the network.
Tenant identity and service authentication must land first.
