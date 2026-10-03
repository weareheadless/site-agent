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

## VPS-owned release automation

The only supported customer promotion is a committed request in
`deploy/desired-releases.json` on official `main`. The VPS systemd timer polls
GitHub using the existing SSH identity, snapshots the exact control commit and
executes its release script. GitHub CI validates queue changes on hosted runners;
the VPS also runs the focused contract tests before processing requests. See
[`deploy/README.md`](../deploy/README.md) for the command and service setup.

The queue accepts only a registered tenant, a full customer SHA and a release ID.
The script serializes releases, resolves the declared Cloudflare profile,
builds from a clean detached checkout, inspects one OpenNext artifact, deploys
that same artifact, verifies the tenant-specific health contract, and writes a
secret-free receipt. It rejects legacy `/api/atelier` source, stale Payload
admin markers, missing Growth contract markers, dirty checkouts, missing
credentials and failed live health checks. It never repairs, falls back to, or
reuses a stale artifact.

Production is intentionally not triggered by every push. Review and owner
approval happen before a release request is committed. A release is
complete only after both the VPS receipt and a fresh authenticated browser
verification pass. GitHub success or a public health response alone is not
evidence that the owner-visible release is live.

References: [GitHub deployment environments and concurrency](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments),
[Cloudflare builds](https://developers.cloudflare.com/workers/ci-cd/builds/),
[Cloudflare version rollbacks](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/).
