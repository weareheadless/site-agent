# Platform release: one source, explicit deployment receipts

This is the current Payload/Next.js release path. The static/Pelican worked
example in `deploy.md` is not the customer admin release procedure.

## Boundaries

1. Shared Python API: exact `site-agent` commit, focused/full tests and wheel
   smoke check, install/restart `site-agent-api.service`.
2. Shared Payload admin: tested immutable `payload-admin-vX.Y.Z` GitHub release
   asset from `packages/helloada-payload-admin`. New-site template pins the same
   release. Never overwrite a released tarball.
3. Customer Workers: each frontend repository pins that release in both
   `package.json` and the lockfile; the Wrangler version marker must match.
   One shared source does **not** mean a package publication redeploys consumers.
4. Owner verification: authenticated connection, Growth, chat and preview on
   each deployed tenant. Browser checks remain a distinct stage, not an
   implication of successful builds or public health responses.

No content/D1 migration is required for an admin-only update. Do not use a
combined database-and-app deployment for it.

## Deterministic Worker release

- Identify the one clean official checkout, remote, exact commit and Worker.
- Resolve the existing `cloudflare` profile from
  `/SOCIAL/configs/host-credentials.yaml` via `site_agent.credentials`.
  Load that profile's protected environment, not the R2 bootstrap environment.
  Run `wrangler whoami` and `wrangler deployments list --name <worker>` before
  spending time on a build. Never print credential values.
- Use Node 22 from the configured runtime and `npm ci` with the committed
  lockfile. Confirm the installed shared package version. Run typecheck/lint.
- Run the **full** `opennextjs-cloudflare build` with `PAYLOAD_LOCAL_BUILD=1`.
  Wait for its successful terminal state and retain the process/session ID if
  the command is asynchronous.
- Inspect `.open-next/worker.js` and `.open-next/assets`, not just `.next`.
  Confirm required changed markup/scripts and version markers. Record the
  source SHA, package integrity and Worker SHA256 in the release receipt.
- Deploy that exact `.open-next` bundle with `opennextjs-cloudflare deploy`.
  Do not rebuild between inspection and upload. Wait for terminal success,
  record the Cloudflare version ID and confirm it receives 100% traffic.
- Run the authenticated connection gate in
  `scripts/check-helloada-connections.py`. Reload fresh authenticated admin
  documents with the release ID and exercise the changed UI and chat. Record
  browser verification separately; a signed-out screen is not a pass.

`next build` alone does not produce the Cloudflare artifact. Reusing an old
`.open-next` directory or `--skipNextBuild` after an ordinary Next build is not
this release path. Missing standalone manifests must be fixed by the supported
full build, not copied from another checkout.

## October 3 diagnosis

The earlier attempt used the R2 bootstrap credential instead of the existing
deployment profile, and inspected a new `.next` build while an old `.open-next`
bundle remained. Both were operator/process errors. Do not seek a new OAuth
grant or change customer code to compensate for either mistake.

Report source, artifact, deployment and live verification stages independently.
Do not report the whole platform updated until every selected consumer has an
exact pinned release and its own deployment/verification receipt.

## Automation contract (target, not a claim that rollout CI is already wired)

Make this path a reusable GitHub Actions workflow. The coding agent prepares
source changes; CI, not conversational judgement, decides whether to promote.
Use one concurrency group per environment/tenant, protected deployment secrets,
an explicit target matrix from the tenant registry, and terminal failure receipts.
Build each customer artifact once from its pinned commit/package; promote that
artifact rather than rebuilding after approval. A shared admin release needs a
version-pin update and deployment receipt for every selected consumer.

The release manifest must bind backend commit, admin version/integrity, customer
commit, artifact hashes, schema/migration plan, target Worker, connection contract,
previous good Cloudflare version, checks and live verification. Migration is an
explicit compatible rollout phase, never part of an admin-only shortcut.
Rollback selects a known version and verifies it; code rollback is not database
rollback. Browser/tenant integration tests must fail the release on stale UI,
wrong tenant, failed chat or missing preview even when uploads succeeded.

The existing package-tag workflow publishes immutable assets. It is **not** yet
a complete tested, multi-customer rollout pipeline; a written runbook alone
does not provide that enforcement. Keep this distinction explicit in status.

References: [GitHub deployment environments and concurrency](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments),
[Cloudflare builds](https://developers.cloudflare.com/workers/ci-cd/builds/),
[Cloudflare version rollbacks](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/).
