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

Before an API release, the same snapshot validates every ready tenant in the
single provisioned registry. Every tenant must declare its website state and
adapter. A tenant with Payload enabled must explicitly configure the canonical
gateway, token and pinned contract identity. Every customer in the release
manifest must have that gateway enabled and match its exact contract, core
version, schema revision, and schema identity. A dormant tenant with Payload
disabled does not need a Payload instance. A failure stops before tests, slot
activation, or service restart. Existing
tenant configs are migrated explicitly with
`scripts/sync-provisioned-tenant-configs.py`: run `--sync --tenant <id>` first
to inspect a dry-run, then repeat with `--apply` only for the reviewed tenant
IDs, and finish with `--validate`. The migration updates tenant runtime
metadata only; it does not change a Payload database, Worker, content document,
or schema. Keep customers on their currently deployed schema identity unless a
separate reviewed schema migration is queued.

To apply that config-only migration on the VPS, use the exact reviewed
official-main source snapshot and the configured API Python environment. Do not
edit tenant configs manually or run a mutable checkout's copy of the script.
Queue neither API nor app releases until dry-run output has been reviewed and
the explicit apply plus full-registry validation succeeds. Then queue the API
release first; the dispatcher serializes the app release behind it.

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
hashes and requires the exact uploaded version at 100% traffic. The built
workspace is not retained on the VPS; source is reproducible from the recorded
Git SHA and deployed versions remain in Cloudflare. It does not build, upload,
promote or change customer data. Prior failures remain in `verificationHistory`.
The normal gate also waits for edge convergence with bounded repetitions of
the same strict health and authenticated connection checks. A failure never
selects another endpoint, credential or Worker version.

To cancel an obsolete build, stop `helloada-release.timer` and then
`helloada-release.service`. The service stops its complete process group. Commit
the corrected source and a new release ID, then start the timer again. The next
poll records unfinished receipts as `interrupted`, including requests superseded
in the queue. Never edit the canceled source directory or resume its upload.

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
then typechecks and builds OpenNext with local bindings. The shared site-agent
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
promotes that exact uploaded version to 100% traffic, checks the live SHA and
tenant, and performs the authenticated connection gate.

Application releases use OpenNext `upload` and Wrangler `versions deploy`.
Domain routes, DNS and cron triggers are provisioned separately and are never
rewritten by an application release. This keeps the existing deployment token's
Worker permissions sufficient. See [Cloudflare's deployment permissions](https://developers.cloudflare.com/workers/authorization/workers/)
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
authenticated Payload admin ready for Ada's intake. Every ordinary website
release selects the `website` contract and still runs the unchanged full Payload
verifier, which requires the published site name, shared header/footer
navigation, and complete published home page before promotion. Release purpose
is required at the queue-to-runner boundary, and bootstrap must carry the exact
registered migration head; one release class cannot relax the other's gate.
Rollback uses the previous receipt's Cloudflare version with
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
