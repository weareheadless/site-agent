# Workers for Platforms: assessment and migration gates

Status: **assessment, not an approved plan**. Nothing here authorises a
deployment, a purchase, or a change to any tenant. It records what was
measured, what is still unknown, and the order in which the unknowns have to be
cleared before a move is planned.

## The question this answers

Helloada is meant to behave like an operating system: platform code ships once,
tenants are applications. Today it does not. `deploy/shared-runtime-overlay.json`
copies 64 platform files into every tenant checkout, so a platform change is
compiled into every tenant Worker. The release pipeline then has to rebuild each
one, because a Worker is immutable once uploaded.

The question is whether Workers for Platforms (WfP) removes that, and at what
price.

## The constraint that produces the fan-out

A Worker's D1, R2 and queue bindings are fixed when the Worker is deployed. A
single shared Worker therefore cannot hold two hundred tenants' databases, and a
service binding does not pass the caller's bindings through to the callee.

Payload runs in-process against the tenant's own D1. That is why the admin, the
workspace API, mail and the publication guard must run beside the tenant's
database. **Their fan-out is not a defect; it is what per-tenant databases
mean.** Any plan that claims to remove it entirely is wrong.

What is *not* forced is platform code that needs no binding: the visitor
assistant, SEO routes, preview chrome, admin shell. Those are in the tenant
bundle because that is where a route was added, not because anything required
it. `AGENTS.md`, "Two tiers in a tenant bundle", is the rule that keeps that from
repeating.

## Where the fleet stands (measured 2026-11-20)

| measurement | value |
| --- | --- |
| registered Payload tenants | 13 |
| schema revisions in use | 4 (5, 7, 8, 13) |
| Payload cores in use | 4 (0.5.1, 0.5.7, 0.5.9, 0.6.5) |
| tenants on automatic runtime updates | 0 — every tenant is `manual` |
| Workers on the account | 20 (13 tenant, 7 platform) |
| platform commits touching the tenant template | ~150 per month |
| distinct `sharedRuntimeFingerprint` values in November | 21 |

The drift is the finding that matters. At thirteen tenants there are already
four schema revisions running, and no tenant updates itself. At two hundred it
would not be possible to say what is running where without reading the registry.

## The two lanes, and the gaps between them

`deployment_pipeline.provider` defaults to `github`: the owner approval merges
the approved commit to the tenant repository, and that repository's
`.github/workflows/release-deploy.yml` builds, uploads, promotes and verifies
it, proving itself with GitHub OIDC. The platform hands the run its material
through `POST /control-plane/websites/{tenant}/deploy-credentials`, including
`sharedRuntimeFingerprint: platform_runtime[...]` — the platform's **current**
fingerprint. A tenant therefore inherits the platform at run time; nothing has
to be pushed into its repository for a platform change.

`deployment_pipeline.provider: vps` is the legacy central queue
(`deploy/desired-releases.json`, polled by `helloada-release.timer`).

Measured gaps, all still open:

1. `application/shared_runtime_rollout.py` has no reference to GitHub or
   dispatch. It writes a batch into `desired-releases.json`, so a runtime move
   is a VPS job by construction even when the provider is `github`.
2. `scripts/reconcile-payload-releases.py` never reads `deployment_pipeline`, so
   the VPS timer processes the queue regardless of the configured provider. The
   two lanes do not gate each other, and a stale queue entry can deploy a tenant
   that its repository is also deploying.
3. Four of thirteen tenant repositories lack `.github/helloada-release.json`
   (the disposable canary among them, and three old test tenants). A run there
   fails immediately.
4. Until 2026-11-20 the workflow reported every one of those failures as an
   empty "deploy credential intake refused", because the refusal body went to a
   file nobody printed. It now names the missing identity, the HTTP status, and
   a missing OIDC token.

### Measured cost of each lane

VPS queue, from 1,144 receipts: median 6.0 minutes per tenant release, worst
33.9, one exclusive `reconcile.lock` — strictly one tenant at a time. Two
hundred tenants is about twenty hours of wall clock, and one failure holds the
queue.

GitHub lane, from the tenant repositories' own runs: 29 `Release deploy` runs
took 90.9 minutes, **3.1 minutes each**, about **1.9 cents** at the Linux
2-core rate of $0.006/minute. Every workflow across all thirteen repositories in
recent history totals 317.8 minutes, or $1.91. Two hundred tenants on one
platform change is roughly 620 minutes, about $3.72, or a fifth of a Team
plan's included monthly allowance ($18 = 3,000 minutes).

Concurrency, not money, is the GitHub limit: 20 concurrent jobs on Free, 40 on
Pro, 60 on Team, 500 on Enterprise, raisable by support request. At 60, two
hundred runs finish in about four waves — roughly thirteen minutes.

## What Workers for Platforms changes

A dispatch namespace holds user Workers with no per-account script limit. A
dispatch Worker receives every request and calls `env.DISPATCHER.get(name)`,
resolved from hostname through KV. Each user Worker carries **its own** bindings,
so per-tenant D1, R2, queues, Durable Objects and Workflows survive untouched —
isolation is not traded away.

Confirmed from Cloudflare's documentation:

- bindings supported on user Workers: `d1`, `r2_bucket`, `queue`, `service`,
  `secret_text`, `plain_text`, `durable_object_namespace`, `analytics_engine`,
  `hyperdrive`, `assets`, `version_metadata`;
- static assets are supported, including `wrangler deploy --name <worker>
  --dispatch-namespace <namespace>`, so the existing build output is usable;
- one `*/*` wildcard route replaces per-tenant routes and custom domains, which
  is itself a ceiling today;
- per-script tags allow deleting a tenant's whole footprint in one call;
- **no gradual deployment for user Workers**: a change deploys to 100% at once,
  though versions still exist;
- `trusted_workers: true` is available, and is required for `request.cf` and the
  Cache API — but it makes the cache **shared across every tenant in the
  namespace**, so cache-key isolation becomes a correctness requirement;
- in untrusted mode `caches.default` is disabled, which OpenNext may depend on.

Pricing: **$25 per account per month**, including 20 million requests, 60
million CPU-ms and 1,000 scripts; then $0.30 per additional million requests,
$0.02 per additional million CPU-ms, and $0.02 per additional script. Requests
are charged once across the dispatch → user → outbound chain. Workers Paid ($5)
is still required and is **not** replaced by it: the D1, R2, Queues and KV
entitlements that make two hundred tenant databases viable come from Workers
Paid. Budget $30/month fixed plus usage; at 200 tenants with modest traffic the
whole Cloudflare bill is around $50/month, about 25 cents per tenant.

## The three unknowns

These decide whether a move is possible, and none of them can be answered from
documentation.

1. **Inbound email.** `worker.ts` composes the site, Payload and Mailflare into
   one Worker with `fetch`, `email`, `queue` and `scheduled`. Email Routing
   rules are created with `{"type": "worker", "value": [name]}`
   (`hands/cloudflare_email.py`), and Cloudflare's Email Workers documentation
   describes no namespace form. If a namespaced script cannot receive mail, the
   composed Worker cannot move as one unit.
2. **Cron triggers and queue consumers.** WfP pricing names both, with a
   15-minute CPU cap, which implies support. How they are attached to a user
   Worker, and whether they draw on the account's 1,000 cron triggers, is not
   documented.
3. **OpenNext under trusted mode.** Whether the `.open-next` bundle with its
   assets behaves as a user Worker, and whether per-tenant cache keys survive
   Next's own cache usage, has to be built and observed.

If (1) fails, the fallback is bounded: `composeTenantWorker({ site, mailflare })`
already treats the two as separate handler sets, and the Mailflare side is
already built as its own bundle. A standalone mail Worker is a second entry
point and a second upload, not a port. Mail then stays an account-level Worker,
which costs one Worker per tenant against the 500 limit — a requestable default,
not a hard ceiling.

## Target shape, if the unknowns are cleared

- **Dispatch Worker** — all platform code that needs no tenant binding. One
  build, one deploy, one version, gradual rollout and instant rollback, because
  it is an ordinary Worker. This is where the visitor assistant belongs.
- **User Worker per tenant** — the site and the data tier: Payload, the
  workspace routes, the bridge, forms, booking, the publication guard, and mail
  if unknown (1) allows it. Rebuilt when that site changes or when the schema
  revision moves.
- **Python API** — unchanged: control plane, scheduling, integrations.
- **KV** — hostname → tenant mapping, platform configuration.

What this removes: platform changes no longer produce tenant builds at all.
What it does not remove: a site still rebuilds when its owner changes it, and a
schema revision still reaches every tenant, because every tenant has its own
database.

## Rejected alternatives, and why

**One shared database with a tenant column.** Removes the fan-out completely,
and loses exit, per-tenant restore and contract-grade isolation. It is the right
answer only if no customer ever asks where their data lives.

**A thin shell Worker per tenant forwarding to a platform Worker over a service
binding.** Rejected: the platform Worker cannot receive the tenant's D1 binding
through a service binding, so the data tier stays anyway, and the added hop
buys nothing the dispatch Worker does not.

**Moving platform code into a package.** Changes who owns the code, not when it
deploys. A version bump still rebuilds every tenant.

## Migration gates

In order. Each gate is a hard stop; none may be skipped because the previous one
felt successful.

1. **The tier rule holds through one real platform change.** A platform change
   ships without touching the data tier, and the fan-out it causes is zero.
2. **The GitHub lane is the only lane.** The runtime planner dispatches instead
   of queueing when the provider is `github`; the VPS queue refuses work under a
   `github` provider; every enrolled repository carries the release identity.
3. **The spike answers the three unknowns** on a disposable tenant, with
   output recorded next to its receipt.
4. **One disposable tenant moves whole** — site, data tier and mail — behind a
   dispatch Worker with a wildcard route, and serves its own domain, admin,
   mail and scheduled work.
5. **The canary runs a full platform change through the new shape** before any
   customer is enrolled.

## The spike

One month of Workers for Platforms ($25) buys the answers to (1) and (2), which
cannot be obtained any other way. Purchasing is a dashboard action and belongs
to the owner; it is not part of this repository's release path.

Acceptance for the spike, recorded as a document next to its receipt:

- a disposable tenant's site serves from a user Worker behind a dispatch Worker
  with a `*/*` route, at its own hostname, with its own D1 and R2;
- an inbound message to a namespaced script either arrives or is provably
  refused, with the API response quoted;
- a cron trigger and a queue consumer are either attached to a user Worker or
  provably unavailable, with the configuration path named;
- the cache is shown not to cross tenants under trusted mode, or trusted mode is
  shown to be unnecessary.

If all three come back workable, WfP is the better answer than the GitHub lane
for platform code and the queue stops being worth investing in. If inbound email
is refused, WfP still helps — it moves the site and data tier — but mail stays
where it is, and the planning has to say so.

## What this document does not authorise

No tenant is enrolled, no repository is edited, no queue entry is created, and
no purchase is made by anything written here. It is the shared record of the
measurements so the next planning step starts from evidence rather than from the
last conversation.
