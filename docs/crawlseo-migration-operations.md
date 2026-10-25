# CrawlSEO tenant migration operations

These operations use the existing protected HelloAda control plane and the
canonical registered tenant. They never approve a candidate, publish customer
content, restore deleted owner facts, grant an allowance, or launch research.

## Read and prepare

`GET /v1/control-plane/websites/{tenant}/growth/migration-plan` returns the
current snapshot hash, registered config hash, per-phase checks, exact local
inventory, remote Action comparison, and receipt status. Keep exports private.
The temporary migration credential has only `connector:read`; capability
discovery reports actual credential scopes, separately from backend support.

Install the temporary credential through the fixed managed credential helper.
The existing MCP credential remains separate. Use
`POST .../growth/migration/configuration` with `mode: plan`, then the same exact
reviewed request with `mode: apply`. The request names the current snapshot and
config hashes, connector endpoint, fixed credential variable, stable operator
request ID and reason. This operation preserves research authority and reloads
the registered tenant. Failure after a config save remains explicitly
`config_saved_runtime_unverified`; retry that exact request after fixing its
cause rather than overwriting the checkpoint.

## Review evidence and preserve work

`POST .../growth/migration/resolutions` supports narrowly typed scoped
dispositions. Echo the current snapshot and evidence fingerprints. Every work
scope carries its exact record hash and revision. Existing owner decisions must
use `preserve_execution`; terminal history, deferred preparation and deleted
facts have distinct dispositions. These receipts never fabricate Action links,
restore facts, settle unknown costs, or create publication authority.

Current pointers are per record. Replacing one scope does not revive an older
decision for it or invalidate an unrelated current scope. New evidence makes
affected receipts stale. Monetary review is an attestation, not an authoritative
ledger import or a spending grant.

`POST .../growth/migration/verify-routes` derives the exact current published
route inventory from Payload and performs bounded robots, sitemap and route
observations. It rejects cross-origin redirects and unsafe XML. Only an actual
passing observation is persisted; a supplied hash cannot substitute for a
server observation. Proof expires after one hour and when the canonical
inventory revision changes. A missing sitemap remains a real blocker and must
be fixed through Ada's normal exact candidate and owner approval path.

## Freeze and activate

`POST .../growth/migration/freeze` first persists the producer fence, then uses
canonical tenant reload and inspects actual scheduler registrations. Old
workers must exit before replacement workers start or old Memory closes.
Bounded reconciliation of exact delivery/revision receipts remains available.
Repeated requests recheck registrations and drain evidence; a historical
verification does not conceal a reintroduced producer. Unknown provider costs
remain visible, and released reservations do not count as in-flight work.

Runtime activation requires a separate `connector:read` plus `connector:write`
credential, exact project/site identity and active HelloAda binding generation.
Use `POST .../growth/migration/activation` in plan/apply mode with exact hashes
and a stable request ID. Activation validates all preflight checks and current
server route proof, freezes duplicate producers, retires legacy research
settings and selects CrawlSEO authority. It records durable begin, config and
runtime checkpoints. Local and remote stores are not one atomic transaction.

Connector effects remain paused during startup until runtime verification is
durable. Failures keep the freeze and dispatch holds; recovery never silently
reactivates the local research engine. A crash after config replacement can
resume from the exact begin checkpoint. A successful retry still verifies live
binding, config, freeze and registrations before reporting active authority.

Paid research remains held until an authoritative, matching budget import and
policy transfer exists. Clearing a boolean or reviewing a monetary attestation
cannot grant spending. Normal approved execution changes do not erase a valid
authority activation; current migration readiness is reported separately.

## Release and acceptance

Ship API changes through the canonical full-main-SHA desired API release, then
verify the registered Oceanic tenant through the protected API. Shared UI or
Worker changes additionally require their immutable package and canary release
flows. Preserve every exact owner decision and archived body. Live acceptance
requires current authenticated owner surfaces and Ada-created candidates;
passing tests, flags, health responses and migration receipts alone do not
complete issues CrawlSEO #3 or Site-Agent #330. Follow
`crawlseo-retirement-inventory.md` for mandatory code deletion exit conditions.
