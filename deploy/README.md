# HelloAda VPS deployment pipeline

## Shared API release

The shared Python API is released through the same VPS timer as tenant Workers;
it is not updated by changing the local VPS checkout or by pushing a Git commit
alone. After an API change has passed GitHub CI and is merged, set
`deploy/desired-api-release.json` to one new request containing a unique release
ID and the exact 40-character source SHA on official `main`, then commit that
queue update. For example:

```json
{
  "schema": 1,
  "release": { "id": "20261004-api-1", "sha": "<full-40-character-main-SHA>" }
}
```

The queue is deliberately separate from customer Worker requests.

For the first release that enforces the canonical tenant registry, the one-time
host adoption is a prerequisite: run `migrate-static-tenants-to-registry.py`
against the exact reviewed source in dry-run mode, obtain explicit owner
authorization for the listed tenant/config/secret changes, then apply it once
and verify the registry before queuing the API release. Do not deploy code that
rejects static host tenants while the VPS still has those declarations.

The VPS snapshots the exact source commit from its official `site-agent/main`
mirror, runs the complete Python test suite, builds one wheel, verifies that the
wheel imports from its own isolated release directory, and refuses new runtime
dependencies that are not already installed in the API environment. It verifies
that the candidate's API unit exactly matches the host unit installed by the
reviewed bootstrap, atomically switches `/SOCIAL/payload-releases/api/current`,
restarts `site-agent-api.service`, and requires
`http://127.0.0.1:3014/healthz` to return exactly `{"ok":true}`. Unit changes are
host-policy changes and must be applied by the explicit bootstrap, never by a
tenant release.
On failure the timer restores the prior immutable slot, restarts it, and writes
a sanitized receipt. No tenant Worker requests run if the API release fails.

Receipts and the built wheel live under
`/SOCIAL/payload-releases/runs/api/<release-id>/receipt.json` and
`/SOCIAL/payload-releases/api/releases/<release-id>/`. The previous API slot is
retained as the rollback target. The protected `deployment.log` beside the
receipt contains redacted build/test output for diagnosis. Failed or
interrupted IDs are terminal; correct the cause and queue a new ID. The
deployment never changes the running source checkout or prints service secrets.

The API unit uses the existing venv for runtime dependencies and loads product
code only from the current immutable release slot. If a code change requires a
new dependency, first provision and validate that dependency in the service
environment as an explicit dependency release; the API queue will not install
packages ad hoc.

Before an API release, the same snapshot validates every ready tenant in
the single provisioned registry. Every tenant must explicitly declare its
website state and adapter. Each enabled Payload tenant must use the canonical
gateway, token and complete pinned contract. Preflight reads each registered
HTTPS health endpoint, rejects redirects or malformed health, and compares the
tenant runtime config with the Worker currently serving traffic. It does not
compare runtime config with a queued target contract: the target is expected to
advance only after its Worker is verified and promoted. A dormant tenant with
Payload disabled does not need a Payload instance. Any mismatch stops before
tests, slot activation, or service restart.

The release runner crosses one authenticated `activate-runtime` boundary for
every Worker release, not only initial bootstrap. It requires the exact release
receipt, uploaded version at 100%, matching live health identity, and the
explicit `websitePresent` state. Site-Agent then synchronizes
`adminVersion`, core version, content contract, schema revision/identity,
migration head and website-present state from that verified receipt into the
registered tenant config. It preserves the tenant's locale and media settings,
reloads the mounted runtime only if its pinned config changed, and only then
runs the authenticated connection check. Thus API preflight sees the active
Worker contract, while a candidate may be newer without creating a false
mismatch. If an existing config genuinely differs from its active Worker, the
operator-only `--sync --tenant <id>` dry run reads that active health identity;
`--apply` may reconcile only the explicitly named registered tenant. It never
uses the queued candidate identity or changes a database, Worker, content
document, or schema. Finish with `--validate` before an API release.

## HelloAda project-selector release

HelloAda's own Worker uses this same timer and dispatcher; it is not deployed
from a developer checkout or a separate manual Wrangler command. After the
HelloAda change is reviewed, merged to `weareheadless/helloada/main`, and its
CI passes on the pinned Node/npm versions, queue one new ID and the exact
40-character app commit in `deploy/desired-helloada-app-release.json`:

```json
{
  "schema": 1,
  "release": { "id": "20261006-helloada-app-1", "sha": "<full-40-character-main-SHA>" }
}
```

The dispatcher verifies the app SHA is on the official `helloada/main`,
archives that exact commit into a unique mode-0700 job workspace, installs only
its lockfile with a job-scoped npm cache, runs its tests, lint, typecheck, Next
build and OpenNext Worker build with local bindings, then validates the exact
Worker, API, D1, R2 and required-secret configuration. Source, dependencies,
temporary secrets/configuration and build output stay under that one workspace
and are removed on success or failure; interrupted workspaces are swept by the
next serialized dispatch. The old persistent HelloAda source/npm caches are
removed under the queue lock. Superseded Site-Agent control snapshots are
pruned while the current exact-main snapshot remains cached for the timer.
Only the small receipt remains at
`/SOCIAL/payload-releases/runs/helloada-app/<release-id>/receipt.json`; it
records the source SHA, artifact hash, exact Cloudflare version and deployment
result. The pipeline uploads one immutable version with the exact
`HELLOADA_RELEASE_SHA`, promotes only that version to 100%, and requires
`https://helloada.app/api/health` to return that same SHA. If live verification
fails, it restores the exact previous Worker version and records a terminal
failed receipt.

The handoff private key is read from the declared mode-`0600` file at
`/SOCIAL/configs/helloada-app/secrets.json`; the release fails before upload if
it is missing, malformed, or does not cryptographically match
`HELLOADA_HANDOFF_PUBLIC_KEY` in the protected Site-Agent API environment file.
It is injected only for the immutable Worker upload, never exposed to `npm
ci`, tests, lint, typecheck or build. The HelloAda app release does not migrate
Payload data or launch a customer website. A successful receipt means only
that the project selector itself is live at the exact reviewed SHA.

Failed or interrupted app release IDs are terminal. Fix the cause and queue a
new unique ID; never edit a retained source snapshot or repurpose a receipt.

## Message data and form security resources

Every exact customer Worker release provisions the tenant's registered private
email R2 bucket, Messages Queue and dead-letter Queue before upload. The release
receipt records the exact resource names and whether each resource was created;
the pipeline never deletes or silently substitutes a resource. Site-agent also
provisions a dedicated Turnstile widget for that tenant and synchronizes its
hostname allow-list from the registered health URL, the exact public origin and
Worker custom-domain routes in the immutable customer source. Turnstile's
public sitekey is injected as a Worker variable and its secret is stored only
in the tenant's protected `tenant.env` and uploaded through a mode-0600
ephemeral secret file. Cloudflare API credentials must include Turnstile Sites Write (or Account Settings Write) in addition to the existing scoped R2 and Queues
permissions. A missing permission or mismatched existing resource fails the
release before promotion; no manual dashboard setup or test key is accepted.

## Release command

1. Review, test and push the customer source to its official GitHub `main`.
2. In `site-agent`, update `deploy/desired-releases.json` with the registered
   tenant, full customer commit SHA and a new release ID:

   ```json
   {
     "schema": 1,
     "releases": {
       "oceanicvibes": { "id": "20261003-release-1", "sha": "<full 40-character SHA>" }
     }
   }
   ```

3. Run `python -m pytest -q tests/test_payload_release.py`, then commit and push
   the queue to official `site-agent/main`.
4. The VPS discovers the request within one minute. Check it with:

   ```bash
   ssh codex-vps 'systemctl status helloada-release.service --no-pager'
   ssh codex-vps 'journalctl -u helloada-release.service -n 80 --no-pager'
   ```

5. Read `/SOCIAL/payload-releases/runs/<tenant>/<release-id>/receipt.json`.
   `deployed` means upload, exact live SHA and authenticated Ada/Payload checks
   passed. It still requires a fresh signed-in browser check. Record that check
   in `browser-verification.json` beside the receipt before reporting completion.

Keep the latest request for each tenant in the queue. Existing terminal receipts
make it idempotent: unchanged requests do no work. Failed or interrupted requests
are recorded and never rebuilt by every poll. Fix the cause, then commit a new
release ID. A release ID cannot be reused for a different source SHA.

If a version was promoted but its read-only verification failed during edge
rollout, first diagnose the failed gate. Then rerun only verification from the
reviewed VPS checkout, using the same recorded tenant, full SHA and release ID:

```bash
.venv/bin/python scripts/deploy-payload-customer.py --tenant <tenant> --ref <full-sha> --release-id <recorded-id> --release-purpose website --verify-only
```

This command takes the queue lock, validates the receipt's per-file artifact
hashes and reads the current 100%-traffic deployment directly from Cloudflare.
For adoption only, a current version created by a secret-only rotation is
accepted only when Cloudflare marks it secret-triggered and its script ETag and
non-secret binding identity exactly match the uploaded release. The verifier
rechecks the active deployment around the live health and authenticated
connection gates; it does not accept a caller-supplied Worker version. Failed
read-only verification does not rewrite the canonical release receipt. The built
workspace is not retained on the VPS; source is reproducible from the recorded
Git SHA and deployed versions remain in Cloudflare. It does not build, upload,
or promote a Worker. It may synchronize tenant runtime through the authenticated
control-plane gate. Prior failures remain in `verificationHistory`.
The normal gate also waits for edge convergence with bounded repetitions of
the same strict health and authenticated connection checks. A failure never
selects another endpoint or credential. Normal release promotion still requires
the exact uploaded version.

To cancel an obsolete build, stop `helloada-release.timer` and then
`helloada-release.service`. The service stops its complete process group. Commit
the corrected source and a new release ID, then start the timer again. The next
poll records unfinished receipts as `interrupted`, including requests superseded
in the queue. Never edit the canceled source directory or resume its upload.

## Domain email provisioning

Domain email is provisioned by the shared site-agent API from the canonical
tenant config. Workspace bootstrap enables automatic reconciliation with the
stable `hello` local part, and a registered custom website origin can supply
the email domain. A platform-hosted `workers.dev` site without an explicitly
registered email domain remains `domain_required`; automatic shared-domain
assignment for every new workspace is phase two, tracked in issue #106. For
the current validation, existing platform-hosted tenants can receive an
explicit HelloAda email domain and tenant-unique local part through the
read-only/`--apply` CLI flow below. The shared site-agent-api scheduler retries automatically
every hour after a new Worker release becomes ready; it does not need a
dashboard visit or a manual API restart. For an explicitly auto-provisioned
tenant with registered Mailflare D1 resources, the first Worker release may
omit all three mailbox runtime settings so the Worker can be deployed and pass
its exact health/authentication gates. The release then records an immediate
`next_run:email_provisioning` wake-up against that tenant's registered
`data_dir/memory.db`; this removes the first-release dependency loop without
weakening the manual-configuration gate. Partial settings remain a hard
failure, and the provisioning receipt records whether setup was already
active or scheduled. The scheduler then creates the provider resources and
installs the exact tenant Worker settings. The VPS is the provisioning control
plane, not a mail server. Its protected Cloudflare API tokens are used only to
configure Cloudflare DNS, Email Routing and transactional Email Sending. They
are never copied into tenant Worker secrets. Cloudflare Email Routing delivers
inbound messages to the tenant Worker, and the Cloudflare `EMAIL` binding sends
transactional notifications and booking confirmations. Resend is the sole
provider for ordinary owner-approved replies and new messages.
Unknown existing MX, SPF, DMARC or routing state stops before Cloudflare writes.
The provisioner uses separate protected host profiles. The `cloudflare_dns`
token needs Zone Read, DNS Read and DNS Write, restricted to the zones
site-agent manages. The `cloudflare_email` token needs Email Routing Rules
Read/Edit and Zone Settings Read/Edit, restricted to those same zones, plus
Email Sending Edit on the owning account. Do not grant broad account or global
permissions. Missing permissions, an unavailable account entitlement, or an
unsupported provider response is a hard error; the workflow never asks an
operator to finish onboarding in the dashboard or silently substitutes a
manual DNS recipe. The general Cloudflare token remains dedicated to Worker
origin/resource operations and is not reused for email provisioning. Store the
token values only in corresponding protected host environment files; the
non-secret profile in `/SOCIAL/configs/host-credentials.yaml` names those files
and environment variable names. The `resend` profile uses an account-level
`full_access` management key because provisioning creates verified domains and
tenant keys. This key is high impact and remains only on the protected VPS.
Store `RESEND_API` in
`/SOCIAL/configs/helloada-resend.env`. Each tenant receives a
`sending_access` key restricted to its exact verified Resend domain. Only that
key is stored in the tenant's mode-0600 `tenant.env` and installed as the
encrypted Worker secret `RESEND_API_KEY`. It is never added to a repo, GitHub
Actions, Wrangler variables or logs. Store `CLOUDFLARE_EMAIL_API_TOKEN` in
`/SOCIAL/configs/helloada-cloudflare-email.env`; use the existing configured
DNS-profile file for `CLOUDFLARE_DNS_API_TOKEN`. Never put token values in
tenant config, source, GitHub or issue comments.

The non-secret host profile entry is:

```yaml
resend:
  api_key_env: RESEND_API
  env_file: /SOCIAL/configs/helloada-resend.env
```

When a tenant is first provisioned, or its registered sender domain changes,
site-agent creates that exact domain in Resend if it does not already exist,
adds only Resend-declared DNS records after conflict checks, and waits for
Resend to report it verified before issuing the tenant-scoped sending key. New
sender domains must be active Cloudflare zones
managed by the configured host DNS credentials; unsupported domains fail
closed instead of silently skipping verification or asking the owner to finish
provider setup manually.

Provisioning persists a unique key-creation intent before calling Resend,
reconciles an interrupted create by deleting only the exact named orphan, and
serializes per-tenant key rotation. A sender-domain change installs a new
domain-restricted key before revoking the previous key.

For a one-time existing-tenant setup, invoke the exact active immutable API
release on the VPS using the protected host config:

```sh
PYTHONPATH=/SOCIAL/payload-releases/api/current/site-packages \
  /SOCIAL/site-agent/.venv/bin/python -m site_agent \
  --config /SOCIAL/configs/site-agent-api/config.yaml \
  provision-email --tenant <registered-tenant-id>
```

Do not use `/SOCIAL/site-agent/.venv/bin/site-agent` for provisioning: that
entrypoint can load the older package installed in the mutable source checkout
instead of the active API release.

For a tenant on a platform `workers.dev` website, include its pre-registered
HelloAda zone-apex email domain with `--email-domain helloada.app` and its
tenant-unique mailbox local part with `--local-part atelier-harmonie`. This
first validation supports zone-apex domains only. The
current Cloudflare Email Routing API's subdomain DNS query is deprecated, and
subdomain routing setup is documented as a dashboard flow; do not silently
use that legacy query. The email domain must resolve to an active zone visible
to the protected DNS profile. These values are persisted only by the matching
`--apply` after the plan is reviewed; the Worker and tenant identity still
come exclusively from the registry.

The command above is read-only and resolves the tenant only from the canonical
`provisioned_root/tenants.json`; it prints the intended mailbox and operations
without exposing a forwarding destination. After reviewing that exact plan,
repeat the exact command with the approved `--email-domain` and `--local-part`
values plus `--apply`. A legacy Mailgun transition requires the narrow
`--approve-mailgun-cutover` allowlist (only the known apex Mailgun MX pair and
standard SPF value); replacing an exact-address Cloudflare forwarding rule
additionally requires `--allow-forwarding-cutover`. Each apply writes a
mode-0600 before/after receipt beneath the tenant data directory before
provider mutations. Do not make corresponding dashboard changes by hand.

Cloudflare Email Routing delivers inbound messages to the registered tenant
Worker; Resend delivers ordinary approved replies and new messages; Cloudflare
Email Sending remains for transactional notices. This provisions an
application-managed business inbox, not a general mailbox or a Gmail
replacement. The Payload mailbox is marked active only after Cloudflare and
the exact Worker confirm the same address and Resend confirms the sender domain.

## What executes

`helloada-release.timer` starts a systemd service every minute after the previous
run finishes. Its stable dispatcher fetches official `site-agent/main` via the
existing host GitHub SSH identity and snapshots the control commit. It runs that
snapshot's tests, manifest and pipeline, so later Git changes cannot alter an
in-flight run. The dispatcher never points at the mutable `/SOCIAL/site-agent`
checkout; it validates an install manifest and synchronizes only its dispatcher
code from official-main snapshots. Its service keeps `NoNewPrivileges=true`
because customer builds execute code from tenant repositories. The reviewed bootstrap installs host systemd units and a root-owned,
fixed-function socket broker. The release dispatcher can request only a restart
of `site-agent-api.service`; it cannot select a command or another unit. The
broker socket is restricted to the deployment account. Routine release code
cannot run `sudo`, write system units, or reload systemd. Host unit changes require the explicit
bootstrap from the exact official-main snapshot. The timer persists across
SSH/chat disconnects and machine restarts. A systemd timeout kills the complete
process group; the next poll records an interrupted attempt.

Each customer gets a fresh Git clone in a unique, mode-0700 workspace under
`/SOCIAL/payload-releases/work`. The workspace has a job-scoped npm cache and
is never placed in its durable receipt directory. Before dependency
installation, build, or remote database mutation, the pipeline requires the tenant verifier command,
`tsx` runtime and lock entry, and verifier source to match the canonical
site-agent template exactly, and the declared `@payload-config` alias must
resolve to one Payload config inside the checkout. Missing or drifted
verification code stops the release before D1 can change. The pipeline then
checks its source SHA is on
official `main`, verifies the exact Node/npm versions in
`deploy/payload-customers.json`, runs `npm ci` with that absolute npm executable,
then typechecks and builds OpenNext with local bindings. The committed npm
install uses one registry connection (`--maxsockets=1`): on this pinned npm
runtime, parallel fetches can race while committing duplicate integrity objects
to the job-scoped cache. This makes the install deterministic without changing
package selection or lockfile integrity. The shared site-agent
preview builder receives the same four-value toolchain contract (`node_path`,
`node_version`, `npm_command`, `npm_version`) from the host config; tenant
registrations inherit it centrally. Missing or mismatched versions stop the
build before dependency installation. Production credentials are supplied only to Cloudflare calls,
never to dependency installation or builds. The artifact is inspected and hashed in the temporary workspace, then uploaded
directly as an immutable, unpromoted version. The pipeline checks production
did not change during the build. If the queue entry is an
explicit tenant schema migration, it verifies the exact live ledger prefix,
creates a private temporary Wrangler config from the already-validated tenant
Worker contract, and marks only that tenant's D1 and R2 bindings as remote for
the migration process. The package-managed Payload CLI receives that exact
config path; its context refuses production migrations without both the
Cloudflare credential and this explicit config. After `npm run payload -- migrate`,
the pipeline reads the ledger directly from the registered Cloudflare D1 and
requires the complete committed chain before removing the temporary config.
This keeps ordinary local development bindings local while ensuring the
production migration cannot silently succeed against Wrangler's local emulator.
The prior Worker remains active until the remote ledger and candidate Payload
contract pass. It then
promotes that exact uploaded version to 100% traffic, checks its live SHA,
tenant and complete Payload identity, then calls the authenticated runtime
activation endpoint to synchronize the central tenant config before performing
the Ada/Payload connection gate.

Application releases use OpenNext `upload` and Wrangler `versions deploy`.
Worker version promotion does not by itself prove that the live Queue consumer
registrations match the committed consumer configuration. After promotion, the
release pipeline therefore reconciles the exact two tenant consumers from the
immutable `wrangler.jsonc`: the Messages Queue consumer attached to that tenant
Worker, with its registered dead-letter Queue, and the dead-letter Queue
consumer attached to the same Worker. It resolves Queue IDs only from the
provisioning receipt, fails closed if either Queue has multiple or unrelated
consumers, applies only a missing or drifted registration, then reads both
registrations back. The final live gate repeats that read and records the
consumer IDs, settings, and verification times in the receipt. A release cannot
be called deployed if a consumer is missing or differs from the source
contract. Never attach consumers manually in the dashboard or through an
ad-hoc Wrangler command; correct the source and queue a new release ID.

The release contract also reconciles the Worker Cron Triggers declared in the
exact committed `wrangler.jsonc` after promotion, then reads them back and
records before/desired/after state in the release receipt. The shared inbox
runtime requires exactly `*/5 * * * *` to sweep durable messages; a missing or
drifted schedule is not treated as a successful deployment. DNS and domain
routes remain a separate explicit provisioning operation. The deployment token
must include Workers Scripts Read and Write for schedule reconciliation,
Queues Read and Write (or Workers Scripts Write) for consumer reconciliation,
and Workers Routes Write scoped to the Cloudflare zones managed by Site-Agent
for Wrangler's domain/route configuration. Do not widen that route permission
to the whole account. See [Cloudflare's schedule API](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/subresources/schedules/),
[Cloudflare's Queue consumer API](https://developers.cloudflare.com/api/resources/queues/subresources/consumers/),
and [OpenNext's upload command](https://opennext.js.org/cloudflare/cli).

For a `workers.dev` health target, the account subdomain is read from Cloudflare
and the registered health URL must be exactly
`https://<worker>.<account-subdomain>.workers.dev/api/health`. The release
pipeline first verifies that the exact uploaded Worker version receives 100%
of traffic, then enables that script's production workers.dev route and runs
the health and authenticated connection gates. A missing account subdomain or
URL mismatch fails closed. Custom-domain health targets do not change the
workers.dev route. Do not construct or register a bare `<worker>.workers.dev`
hostname.

The durable release record under `/SOCIAL/payload-releases/runs` contains the
receipt and small browser-verification evidence. Exact source remains in
GitHub; Cloudflare retains uploaded Worker versions for promotion and rollback.
The checkout, dependency tree, job-scoped npm cache, temporary configs and
OpenNext output live only under `/SOCIAL/payload-releases/work` during a build.
The runner deletes them on success or failure, and the next serialized
dispatcher pass cleans workspaces left by an interrupted process. The queue lock
allows one canonical Payload build at a time, and a build refuses to start
unless at least 8 GiB is free. This makes build storage depend on the one active
job, not on the number of past releases. Ordinary application releases never
mutate a Payload database. The sole exception is an explicit new-tenant bootstrap request carrying
the exact manifest migration-chain hash: the pipeline confirms the registered
D1 identity is empty, creates the same private remote-binding config from that
Worker's exact D1/R2 identities, and applies the committed migration chain
through the generated site's package-managed Payload CLI entrypoint. The
Payload context rejects production migrations without that config, and the
pipeline verifies the complete ledger against the Cloudflare D1 API before
upload; it never treats a successful local-emulator migration as production
state.
The emptiness check excludes only Cloudflare's reserved `_cf_KV` D1 system
table; any other application table makes the database non-empty and requires
the normal exact-ledger rules below.
Any non-empty or partially initialized database fails closed. Existing-tenant
schema upgrades require a separate exact queue request containing the old
migration-ledger identity and registered target head. The pipeline accepts only
a strict prefix of the committed target chain, never generates a migration or
guesses SQL, and leaves the prior Worker serving until the migrated schema and
candidate Payload contract pass. A missing ledger, drifted database or
uncommitted migration stops the release. Source deployment cannot invent or
silently apply a schema change.

The queue's exact `initializeSchema` operation selects the distinct
`workspace-bootstrap` verification contract. Before promotion, the pipeline
proves the committed template/schema identity, exact migration ledger, and
required Worker routes. After promotion, the normal live gates verify the
Worker's schema health and authenticated Payload connection. Bootstrap does
not require business content or publish a website; it only makes the
authenticated Payload admin ready for Ada's intake. Every other release selects
the `website` contract and runs the canonical Payload verifier. When the
manifest explicitly says `websitePresent: false`, the verifier requires all
schema, draft, version, media and global reads but permits an empty site. When
`websitePresent: true`, it additionally requires a publishable site name,
shared header/footer navigation and a complete published home page. The flag is
required and is never inferred from missing content. Release purpose is
required at the queue-to-runner boundary, and bootstrap must carry the exact
registered migration head; one release class cannot relax the other's gate.
Rollback uses the previous receipt's Cloudflare versionRollback uses the previous receipt's Cloudflare version with
`wrangler versions deploy <version>@100% --name <worker> --yes` through the
declared credential profile, followed by live checks. It never rolls back data.

## Install/update the service

The systemd timer invokes a stable dispatcher at
`/SOCIAL/payload-releases/bin/current/dispatch-payload-releases.py`. On an
initialized host, run the bootstrap from the exact current snapshot already
fetched by its timer:

```bash
release_sha="$(git --git-dir=/SOCIAL/payload-releases/control.git rev-parse refs/heads/main)"
/SOCIAL/site-agent/.venv/bin/python \
  "/SOCIAL/payload-releases/dispatch-control/$release_sha/scripts/bootstrap-release-pipeline.py" \
  --source-dir "/SOCIAL/payload-releases/dispatch-control/$release_sha"
```

The bootstrap fetches official `main`, verifies the dispatcher, controller and
host files against Git objects, then installs the dispatcher, API and release
systemd units, timer, fixed-function restart broker, and broker socket from that
snapshot. It removes the exact obsolete Polkit rule path used by earlier
bootstrap versions. On a new host, run the same script from a clean
`/SOCIAL/site-agent` checkout whose `main` SHA matches official `main`:

```bash
/SOCIAL/site-agent/.venv/bin/python /SOCIAL/site-agent/scripts/bootstrap-release-pipeline.py
```

The bootstrap also retires the obsolete per-tenant systemd scheduler only when
the installed template exactly matches the known legacy unit contract. It stops
and disables concrete tenant instances, renames the template to the recoverable
/etc/systemd/system/site-agent@.service.retired path, reloads systemd, and
restarts site-agent-api.service so the shared tenant scheduler can acquire its
locks. An unknown unit, conflicting recovery copy, or remaining enabled/running
instance aborts bootstrap; do not stop or replace that unit manually. All future
tenant scheduling belongs to the shared API process and its registered-tenant
runtime. The retired template is intentionally not reinstalled by releases.
Future dispatcher changes self-synchronize from official main into versioned
slots, with the active dispatcher switched atomically. Host service-unit changes
are installed only by the bootstrap and are checked against official main on
each run. The service uses
`/SOCIAL/site-agent/.venv/bin/python`; only this interpreter and the protected
host credential profile are reused from the host setup. The profile at
`/SOCIAL/configs/host-credentials.yaml` supplies GitHub SSH wiring and the
Cloudflare credential file. No GitHub PAT, runner registration, webhook secret
or inbound deployment endpoint is needed. GitHub CI validates the release
contract; the VPS performs the same validation before execution.

The shared root config and release registry pin Node.js 22.23.3 and npm 11.13.0; the Mailflare source lock requires Node.js 22.22.2 or newer.
The API's shared root config must declare the exact preview toolchain under
`source_deployment` (`node_path`, `node_version`, `npm_command`, and
`npm_version`). The release registry pins the same versions and executable
directories. Do not rely on the system `PATH`, a user-shell profile, or an
implicit Node/npm fallback; changing either version requires updating the
contract and regenerating tenant lockfiles with that version.

## Rules for coding agents

- Use this queue for every customer Worker release. Do not run direct
  `npm run deploy`, `deploy:app`, or Wrangler uploads from an arbitrary checkout.
- Register future tenants in `deploy/payload-customers.json` first. The customer
  must use `/api/helloada/*`, the shared Payload package, and the health route
  from the default template.
- The Payload workspace gateway path is exactly `/api/workspace` for every
  tenant. Before deploying an API release that enforces this contract, run
  `scripts/migrate_payload_gateway_prefix.py` from its exact official-main
  snapshot in dry-run mode, inspect the registered-tenant list, then run it with
  `--apply`. Verify every registered tenant config is canonical. The API rejects
  all other paths; there is no alternate-route fallback.
- Read the receipt and failed stage before changing source. Never use an old
  build, a different credential file, a fallback route or an automatic rollback
  to turn a failed gate into a success.
- Shared admin and core package releases require exact version-pin updates and
  queue entries for every selected consumer. Publishing a package alone cannot
  redeploy them.
- A version in `payload-customers.json` is only a requirement, not proof that
  its immutable release asset exists. Verify the exact tarball URLs/integrity
  and a clean `npm ci`/build before queuing any consumer.
- Ordinary Worker releases never generate or apply Payload migrations. A schema
  migration requires its own queue request, exact tenant/database identity, old
  ledger identity and registered target head. The live database must be an
  exact strict prefix of the committed chain; only then does the VPS apply the
  committed artifact and record the cutover. Never aim `payload migrate` at an
  unspecified binding or use deployment to generate/guess schema changes.
- New-site bootstrap records its exact canonical D1/R2 identities and requests
  the committed initial migration chain by hash through the same central queue.
  It cannot invoke Wrangler, create/apply ad hoc migrations, or declare the site
  live; the receipt only establishes workspace readiness after schema, Worker,
  health and authenticated connection checks pass.
- Source, artifact, deployment and authenticated browser verification are
  separately recorded. Report only what those records prove.


## Shared runtime changes and automatic tenant fan-out

Common Worker behavior is owned by the Site-Agent template and the explicit shared-runtime overlay manifest. Tenant repositories remain inputs for each tenant’s approved design/content and schema history; the release runner composes the common runtime into an isolated build directory. A normal shared-runtime update does not require a commit or manual inspection in each tenant repository.

Each VPS timer pass computes a SHA-256 fingerprint over the overlay contract, all centrally copied runtime files, shared package pins and the full Mailflare build source. A changed fingerprint causes the queue coordinator to request a release for the configured canary using its last successfully deployed tenant SHA. Only after that release passes the standard artifact, Cloudflare deployment and live-health gates does the coordinator enqueue automatic tenants, at most five at a time. Later timer passes continue the rollout from receipts; each request is an auditable commit to desired-releases.json.

The registry field sharedRuntimeUpdate is explicit: canary for the one rollout gate, automatic for enrolled customer sites, and manual only for intentionally excluded sandboxes. New tenant registration defaults to automatic. First-site provisioning already builds the current shared runtime, so fan-out applies to subsequent central changes.

Every fan-out release carries sharedRuntimeFingerprint. The Worker build compares it with the materialized runtime before upload, and the receipt preserves sourceSha, pipelineSha and the exact shared runtime fingerprint. A pending queue request is preserved. Failed or interrupted IDs are terminal: the coordinator does not retry that same attempt or silently replace a tenant’s failed request. A failed canary holds the fleet; an individual automatic tenant failure is recorded and does not trigger an automatic retry.

The shared-runtime build runs the canonical Payload contract generator after applying the package pins and installing dependencies. It regenerates each build workspace’s content contract, schema identity and Wrangler package variables from the pinned Site-Agent schema source, while preserving the tenant’s locale, scaffold revision and exact committed migration chain. The generated migration head must still equal the registered active tenant head; otherwise the release stops before upload and requires an explicit schema-migration request. The candidate then runs the Payload contract verifier against that tenant’s registered D1, and the live health route verifies its exact migration ledger. No customer repository is rewritten, and migration history is never silently replaced.

This does not make separate Cloudflare Workers share one deployed bundle. Each Worker must still be generated and promoted with its tenant-specific design/content, but the VPS automates that work from one Site-Agent change—there is no per-tenant repo engineering step. Do not deploy customer Workers using local Wrangler commands; use the queue and inspect the matching run receipt plus helloada-release.service journal.

## Durable Object lifecycle and rollout contract

Cloudflare Durable Object migrations are not compatible with Worker version upload. The release runner derives an identity from the exact ordered Durable Object migration config for each tenant. If no successful receipt proves that identity has already been applied, the canary/tenant release selects the explicit `atomic` mode before any deployment command. It verifies the completed build artifact, applies and verifies the exact queued Payload schema, then runs `opennextjs-cloudflare deploy` once with the same tenant secrets, release SHA, Turnstile variable and release tag used by the versioned path. This deploy is immediately live; it is not an upload retry or an automatic fallback.

The runner records the lifecycle identity and command state in the tenant receipt, then reads Cloudflare's deployment record and requires a new deployment with exactly one version at 100%. The normal live-health, runtime-fingerprint, queue, schedule and authenticated connection gates still apply. A later release for that tenant uses immutable version upload and verified promotion once a prior receipt proves the same migration identity was applied. A changed Durable Object migration chain requires its own new atomic lifecycle rollout.

An interrupted or failed atomic command is terminal. If the receipt says `applying` or `outcome-unknown`, the coordinator first performs a read-only reconciliation against Cloudflare's exact deployment/version record, the release SHA and tenant bindings, the matching Durable Object namespace, and the tenant's registered health endpoint. The health probe uses the explicit `HelloAda-ReleaseVerifier/1.0` User-Agent, which tenant Cloudflare security rules must permit for this read-only endpoint. The resulting private reconciliation record is bound to the immutable receipt hash; the receipt itself is never edited. If any proof is missing or disagrees, the tenant remains blocked and no fan-out occurs.

Lifecycle proof is deliberately not a canary pass. When the migration is proven applied, the coordinator queues a fresh release ID for the canary using the exact source SHA and runtime fingerprint. That normal versioned release must pass the complete deployment, Payload, schedule, Queue consumer, health, and authenticated connection gates before the coordinator fans out to other tenants. The original failed ID is never reused, and recovery is not a manual tenant-repo change or a silent deployment fallback.

This is a one-time platform lifecycle operation per tenant and migration identity, not per-tenant source engineering. After each tenant has crossed that boundary, normal shared-runtime releases remain centrally built and versioned through the same queue and timer.
