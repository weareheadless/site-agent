# CrawlSEO migration inventory

`GET {control_prefix}/{website_id}/growth/migration-plan` is a control-token-
protected, read-only snapshot for migration review. The configured control
prefix defaults to `/control`; it must be generated and reviewed before a
tenant cutover or budget transfer.

Capture a point-in-time copy without printing tenant inventory or credentials
to the terminal:

```sh
python scripts/capture-crawlseo-migration-plan.py \
  --api-url https://helloada-api.example \
  --website-id oceanicvibes \
  --output ./private-migration-review/oceanicvibes-$(date -u +%Y%m%dT%H%M%SZ).json
```

After the CrawlSEO endpoint is deployed, issue the separate 30-day read-only
credential without replacing the existing MCP token. The command stores it in
a new private env file and prints only the credential ID:

```sh
python scripts/issue-crawlseo-migration-read-credential.py \
  --api-url https://crawlseo.helloada.app \
  --site-id <registered-crawlseo-site-id> \
  --idempotency-key oceanicvibes-migration-read-2026-10-25 \
  --output /SOCIAL/configs/oceanicvibes/crawlseo-migration-read.env
```

Keep that file server-side and configure its value as
`CRAWLSEO_CONNECTOR_READ_TOKEN` only for read-only inventory/comparison. It is
not a runtime authority credential and must not be used for policy writes,
event acknowledgements, preparation, or execution reporting. The capture
command cannot recover a token from an idempotent replay; a replay refuses to
overwrite a file and reports that no fresh token was returned. If issuance
response delivery is uncertain, use a new reviewed idempotency key and a new
output path; the prior read-only credential expires within 30 days. Never
overwrite or replace the MCP token as a recovery step.

The inventory capture command is read-only, verifies the returned tenant
identity and snapshot hash, stores the response in a new mode-0600 file, and
refuses to overwrite an earlier snapshot. It intentionally captures
blocker-bearing plans too: a
blocked inventory is still useful evidence and must not be edited to look
ready. Review the `snapshotHash` again immediately before any separately
authorized state-changing operation; this capture command has no apply mode.

The response includes a stable `snapshotHash`, tenant-scoped local records for
initiatives, article ideas, drafts, Growth runs, owner actions, execution
bindings, active jobs, legacy monthly SEO research requests, site-report rows,
and local budget reservations. Request briefs, report evidence and summaries
are omitted; only identities, status, timestamps, error-presence flags and the
site-report evidence hash are retained. Unresolved article ideas, nonterminal
research requests, and nonterminal site reports block cutover. Initiative rows include
the current approval status/artifact hash and draft review hash so an active
owner decision is marked exact only when all three still identify the same
candidate; mismatches block cutover. Approval feedback and candidate bodies
remain redacted. The plan also includes a read-only CrawlSEO
Action and monetary-ledger snapshot. Connector reads and event acknowledgements
are pinned to the configured CrawlSEO site ID; project credentials may serve
multiple sites without mixing their Actions, execution generations or events.
Issue #330's referenced initiatives,
owner-fact conversation, jobs and article ideas are shown by identity and
status when present. Archived drafts and CrawlSEO/DataForSEO provider receipt
identities/statuses and payload-redacted connector event receipts are included.
Draft bodies and conversation text are excluded; failure messages are
represented as presence flags rather than copied into the plan.
Initiative 4 and conversation 4 are separately identified, but the local schema
does not persist their relationship. The plan marks that relationship as
`issue_reference_only` and blocks migration until an operator confirms the exact
conversation; matching numeric IDs are not treated as proof of linkage.
An operator can record this identity-only confirmation through the protected
`POST {control_prefix}/{website_id}/growth/migration/references/initiative-4-owner-fact-conversation`
route. It requires the current `snapshotHash`, both exact IDs, a fixed
confirmation phrase, a reason and an idempotent operator request ID. The
receipt is included in the next hash-bound snapshot. This operation only
records the reviewed reference; it does not approve work or apply migration.
The receipt binds to the initiative's update timestamp and a hash of the
conversation's messages, so a later edit makes the link stale and restores the
review blocker. A stale receipt can be superseded only against a refreshed
snapshot and a new operator request ID; prior confirmation receipts remain in
the local audit record.

The endpoint does not sync Actions, acknowledge events, change scheduler
registrations, migrate reservations, prepare candidates, publish content, or
retry provider requests. Its `blockers` are required review work, not approvals.
The current robots/sitemap state must be rechecked against the canonical site
before cutover. If any local category reaches its safety limit, or CrawlSEO
Actions and budget cannot both be read, the plan explicitly reports that it is
incomplete. An incomplete or changed `snapshotHash` is not suitable for a
future apply operation.

The response also includes a read-only `migrationManifest` bound to that
`snapshotHash`. It records only identity links already present in local
initiative expectations, CrawlSEO owner-action payloads and execution bindings.
Each link is classified as `exact`, `revision_mismatch`, `remote_missing` or
`unlinked`; remote Actions without an exact local link are listed separately.
The manifest never guesses from titles, URLs or summaries, and it has no apply
operation. An operator must resolve every non-exact mapping and preserve
pending exact approvals before any future migration can be designed.
Unsupported or quarantined connector event receipts also create a cutover
blocker until their disposition is reviewed.

The hash-bound snapshot now includes the tenant's configured legacy research
switches and the SEO/Growth producer jobs actually registered in its runtime
scheduler. A registered duplicate producer, an enabled legacy research switch,
or an unavailable runtime registration inventory is an explicit cutover
blocker. This is per-tenant runtime evidence and must be reviewed with the
source-level audit below before code retirement.

## Source-level producer audit

The current branch traces the main legacy writers to these paths:

- `brain.growth.assess` is called only from the local-authority branch of
  `run_growth_cycle`; CrawlSEO-authoritative runs synchronize Actions and
  return before local assessment.
- `brain.seo.run` is reachable from the local SEO job and local monthly Growth
  research. Both job entry points now fail closed or record a skip when
  CrawlSEO is authoritative; the monthly helper also rejects that mode.
- `brain.article_research.select_and_request` and `reconcile` are reachable
  from the legacy article job, the legacy article-research job, and the local
  weekly Growth path. Scheduler registration and direct job/helper entry
  points and the producer functions themselves are fenced under CrawlSEO
  authority. Historical idea and receipt readers remain available.
- Local SEO-insight, site-report and SEO-outcome writers are not registered
  for CrawlSEO-authoritative tenants. Direct site-report and outcome entry
  points and the writer functions themselves also record a skip. Retained
  SEO-insight and research endpoints are historical readers; the
  CrawlSEO-authoritative projection does not present their local output as
  current. Direct `brain.growth.assess` calls are rejected in that mode.
- `growth_candidates` and the Payload/source publication paths remain the
  selected execution layer. They create exact private candidates and preserve
  existing approval and publication receipts; they do not choose a second
  recommendation set.

This is a caller/entry-point audit for the duplicated recommendation writers,
not a deletion receipt. Legacy implementations, prompts, schemas, historical
readers and local-mode scheduler registrations still exist for tenants that
have not migrated. They must not be deleted or their settings silently reset
until each affected tenant's hash-bound work, budget receipts, pending owner
decisions and retirement condition have been reviewed. The source audit does
not substitute for a complete dependency audit of every retained historical
reader or for runtime proof from the target tenant.

The initial implementation deliberately has no apply operation. Migration
decisions require a later explicit, exact-state operation after the protected
plan has been reviewed, outstanding provider receipts have been reconciled,
and the monetary ledgers have been compared. No production data is changed by
creating or reading the plan.

## Rollout status and remaining gates

The registered Oceanic tenant config was inspected read-only on 2026-10-25;
its sanitized result and limits are recorded in
[`oceanicvibes-crawlseo-migration-baseline-2026-10-25.md`](oceanicvibes-crawlseo-migration-baseline-2026-10-25.md).
It still resolves to local research authority, has no versioned connector URL,
and has legacy article research and site reports enabled. This is evidence
against cutover readiness. The tenant env file's credential presence does not
prove authorization or scope.

This code-only phase does not complete the customer migration or claim issue
#3/#330 as done. The local plan now reads cursor-paginated CrawlSEO Actions
with a hard page limit, rejects repeated cursors, and reports an inventory
failure rather than presenting a partial list as complete. Robots.txt and sitemap.xml are an explicit operator verification,
not queried automatically. The exact Oceanic production database, approved
owner facts, provider receipts, scheduler state, deployment identities and
current budget allowance must be captured from their registered sources before
any cutover.

On 2026-10-25, the configured Site-Agent API at `127.0.0.1:3014` returned an
OpenAPI document, but its registered paths did not include
`/v1/control-plane/websites/{website_id}/growth/migration-plan` or the
initiative-4 owner-fact reference route present in this source tree. An
authenticated read-only request for Oceanic's migration plan returned HTTP
404, and no snapshot was captured. This is a source-to-runtime release gap;
the 404 must not be interpreted as an empty inventory or as permission to
continue without the hash-bound plan. Ship the API change through the canonical
release pipeline, verify the route in the running OpenAPI document, then
capture a fresh plan before resolving any migration state.

No legacy reservation is automatically transferred. Compare every old local
reservation and provider receipt to the CrawlSEO ledger, and hold unknown
outcomes until reconciled. Do not disable or delete historical HelloAda rows,
jobs, prompts, settings or rollback history until the same exact plan has been
reviewed and the new authority path has passed its production acceptance gates.

Wix and Webflow execution adapters, owner acceptance, end-to-end
candidate/publication/outcome verification, and the central API/Worker release
receipts remain outstanding. The connector presently
declares only the implemented RSS research providers; it does not claim the
competitor, web, Wix or Webflow capabilities in the broader architecture plan.
