# OceanicVibes CrawlSEO migration baseline — 2026-10-25

This is a read-only snapshot of `/SOCIAL/configs/oceanicvibes/config.yaml` and
its environment-key presence, inspected on 2026-10-25. It records no secret
values and does not assert that the configured state matches the active
production process or the latest owner-approved budget.

## Observed configuration

| Check | Observed value | Migration implication |
|---|---|---|
| CrawlSEO provider enabled | Yes | Existing read integration is configured. |
| Research authority | `local` (default; no explicit `research_authority`) | HelloAda has not cut over to CrawlSEO as sole research authority. |
| New connector URL | Unset | The versioned Actions/findings connector is not configured here. |
| CrawlSEO credential | `CRAWLSEO_SERVICE_TOKEN` is present in the tenant env file | Presence does not prove token scope, project/site identity, or connector capability. |
| Existing CrawlSEO MCP identity read | Authenticated `seo_get_project` returned an identity for `oceanicvibes.com` and `https://oceanicvibes.com/` | The legacy MCP read path is reachable; this does not grant connector API access. |
| New connector capability read | `GET https://crawlseo.helloada.app/api/connector/v1/capabilities` returned HTTP 403 with the tenant credential | New connector capabilities and binding are unavailable to this credential; a correctly scoped connector credential and binding remain required. |
| Legacy article research | Enabled | Must be inventoried and reconciled before disabling or deleting. |
| Legacy SEO site reports | Enabled | Must be inventoried and reconciled before disabling or deleting. |
| Legacy CrawlSEO research setting | Disabled | This setting alone does not retire the local Site-Agent producers. |

The resolved config was loaded through `site_agent.config.load(...,
validate_integrations=False)` using the Oceanic tenant environment file. No
production scheduler state, current CrawlSEO Action ledger, reservation
ledger, provider receipts, owner decisions, canonical robots/sitemap state,
or authenticated owner journey was read in this audit. The configured
environment file is evidence of intended tenant configuration, not live
runtime evidence.

## Gate status

Oceanic is not ready for authority cutover on this evidence. The 403 is
direct evidence that its configured credential cannot read the new connector
contract. CrawlSEO now has a protected, additive, 30-day `connector:read`
credential endpoint and Site-Agent can keep that token separate from the
legacy MCP key; this is local source code and is not usable until the official
API release and private tenant configuration rollout are verified. Do not change
`research_authority`, disable legacy producers, transfer a monetary allowance,
or remove historical work based on this baseline. First capture the protected
HelloAda migration plan using
[`capture-crawlseo-migration-plan.py`](../scripts/capture-crawlseo-migration-plan.py)
with the control-plane credential, then reconcile every blocker against the
current runtime and the authoritative CrawlSEO ledger. Capture a fresh plan
after any state change and use its new `snapshotHash` for any separately
authorized exact-state operation.

The template in `examples/oceanicvibes.config.yaml` is not the registered
Oceanic configuration and must not be used as proof of cutover. No production
settings, approvals, reservations, content, or schedules were changed while
producing this baseline.
