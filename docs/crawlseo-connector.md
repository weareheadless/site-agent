# CrawlSEO research authority connector

Site-Agent can use CrawlSEO as the single research authority for one tenant.
The active CrawlSEO project binding must name `helloada` as its executor for
HelloAda-managed sites. The currently implemented executor set is `helloada`
and `crawlseo-agent`; new Wix and Webflow bindings are rejected until their
platform-specific preparation, review, receipt and verification paths have
passed their pilots. In HelloAda mode, CrawlSEO owns research collection,
evidence and Action state; HelloAda projects Actions into its existing owner
workspace and owns exact candidate preparation, owner approval, Payload
publication and receipts.

```yaml
providers:
  crawlseo:
    enabled: true
    url: https://crawlseo.example/mcp
    token_env: CRAWLSEO_SERVICE_TOKEN
    connector_url: https://crawlseo.example/api/connector/v1
    connector_token_env: CRAWLSEO_CONNECTOR_TOKEN # optional; defaults to token_env
    research_authority: crawlseo
```

`connector_url` may include the application's explicit Next.js mount prefix,
for example `https://crawlseo.helloada.app/crawlseo/api/connector/v1`. Keep the
complete versioned endpoint in configuration; Site-Agent does not probe or
guess alternate endpoint paths. The endpoint URL cannot contain credentials,
query data or a fragment, and mount path segments must not traverse directories.

The legacy MCP and connector API can use separate environment credentials.
`connector_token_env` defaults to `token_env`; configure it separately to add
connector access without replacing a working MCP credential. Authority mode's
runtime connector credential must have `connector:read` and `connector:write`.
The temporary migration inventory credential has only `connector:read` and
must not be selected for authority mode. Keep credentials and the project
binding in managed tenant provisioning state; never put tokens in browser
configuration. The optional read-only MCP interface remains separate from the
versioned connector API.

Authority mode requires a provisioned Payload gateway and a CrawlSEO connector
site ID. Startup fails closed if either is missing. It suppresses the local
SEO/article research producers and their duplicate dispatch paths. The normal
HelloAda Growth scheduler remains the only scheduler for owner-facing
preparation and outcome progression. Switching executor requires an explicit
binding transfer with a new generation; a stale worker cannot prepare or
publish against the new generation.

Each sync sends current Payload inventory, document hashes, canonical origin,
owner-confirmed business facts and the authenticated admin origin. An accepted
`content.prepare` Action with fresh linked evidence and an exact current route
uses the existing Payload candidate flow. When the Next.js source builder is
available, the connector also declares only exact paths from
`frontend_ownership.CRAWL_METADATA_PATTERNS` with the separate
`site_metadata.robots` and `site_metadata.sitemap` capabilities. Those Actions
must identify the matching source path and canonical `/robots.txt` or
`/sitemap.xml` URL. HelloAda queues its existing private source-candidate job
and rejects any candidate that changes a second path. Both candidate types use
the existing authenticated owner review; neither publishes during preparation.
Approval and decline are sent against the exact candidate reference.
Publication is held until CrawlSEO durably records approval, then verified
publication is reported with the exact target, candidate hash and destination
receipt.

The versioned client also exposes `connector_findings(site_id, run_id, since,
limit, cursor)` for project-scoped finding and evidence-lineage reads. It checks
the advertised `findings.read` capability and verifies the response's project,
site and schema identities. Findings stay evidence detail; the Action remains
the single recommendation and execution identity shown in owner work.

Actions and execution reports are replayed from durable local bindings after
transient connector failures. An owner must explicitly re-accept a blocked
preparation before it is retried. Connector reads do not start research,
prepare candidates or publish. Production activation and customer history
reconciliation remain subject to the registered rollout gates.

The shared Growth workspace exposes the CrawlSEO research policy, including
goals, topic/source exclusions, evidence recency, audience, language, market,
providers, cadence and task limits, alongside the project allowance, current
period spend, reservations and remaining balance. An authenticated owner must
set the monthly allowance and per-operation reservation ceiling before paid
research can run. The UI does not convert a legacy HelloAda cap into a grant.
Budget updates include the owner-selected IANA timezone and use the observed
policy revision; a stale edit must be refreshed before retrying. The timezone
sets the authoritative budget period and research cadence. Task-count,
result-count, per-operation and monthly monetary caps remain separate controls.
The DataForSEO worker requires a USD budget policy so recorded provider costs
are not silently compared across currencies.

## Implementation and cutover limits

The connector and authority-mode code are an implementation foundation, not
proof that the full CrawlSEO architecture plan or Oceanic migration is
complete. The protected migration inventory is documented in
[`crawlseo-migration-operations.md`](crawlseo-migration-operations.md). It is
read-only and consumes cursor-paginated remote Actions with a hard page limit;
live robots/sitemap review, provider-receipt reconciliation, and exact budget
transfer comparison are required before migration.

The first connector release supports Reddit RSS and Google News RSS
collection. Unsupported web and competitor providers are reported as
unsupported. Wix/Webflow execution adapters are not implemented. CrawlSEO
provides an operator-only binding transfer that requires the current executor
and generation, a reason and idempotency key, drained events and budget
reservations, and no candidate awaiting an owner decision before incrementing
the generation fence. Do not remove legacy HelloAda history, settings, prompts,
jobs, or rollback records until an exact tenant migration has passed review and
the replacement has passed owner and production acceptance. Central API/Worker
release receipts and authenticated live verification are also required; unit
tests and a local fixture are not release evidence.

Connector v1 does not expose GA4/Search Console analytics reports. Under
CrawlSEO authority, the HelloAda analytics endpoint reports that limitation
and does not query the legacy HelloAda Google integration as a fallback. The
legacy SEO-insights endpoint likewise omits local recommendations from its
current view and labels retained local results as historical.

When CrawlSEO authority is active, the HelloAda Growth projection shows
current CrawlSEO Action revisions and their saved CrawlSEO evidence. It suppresses
unlinked local assessment recommendations, local SEO schedules, keyword seeds
and article research ideas. Exact local candidates already bound to the same
pending or approved review hash, and owner-information questions, stay visible
so migration work and owner-confirmed facts are preserved.

Preparation retries use a new idempotency key for each deliberate owner action
and reuse that key only when replaying the same request. CrawlSEO returns that
key as the preparation request identity; ready and blocked callbacks echo it so
reports from an earlier retry cannot replace the current attempt.
