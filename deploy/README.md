# Canonical customer release pipeline

Customer Payload/Next.js Workers are released by the VPS-owned pipeline. A
conversation, a local checkout, a cached `.open-next` directory, or a direct
`wrangler deploy` is not a release mechanism.

## Release flow

1. Merge the reviewed customer change into its configured GitHub repository.
2. Copy the resulting **full 40-character commit SHA**.
3. Dispatch the `Payload customer release` workflow in `site-agent`, choosing
   the registered tenant and that exact SHA.
4. The self-hosted `helloada-deploy` runner executes
   `scripts/deploy-payload-customer.py` from `/SOCIAL/site-agent` on the VPS.
5. The gate resolves Cloudflare credentials through
   `/SOCIAL/configs/host-credentials.yaml`, checks the clean pinned checkout,
   installs from the lockfile, typechecks, builds one OpenNext artifact,
   rejects `/api/atelier` and stale admin markers, deploys that exact artifact,
   and verifies the tenant health contract.
6. The receipt in `/SOCIAL/site-agent-api/deploy-receipts` is the deployment
   record. A failed receipt means the release is incomplete.
7. After the workflow passes, perform the authenticated browser check with a
   fresh cache-busting URL. GitHub success or a public health response alone
   is not live verification.

## One-time VPS runner setup

The VPS must have one GitHub Actions self-hosted runner registered on the
`site-agent` repository with labels `self-hosted`, `linux`, and
`helloada-deploy`. Register it as a dedicated service account with access to
the configured customer checkouts and `/SOCIAL/configs/host-credentials.yaml`.
The registration token is short-lived and must be entered interactively; it
must never be committed here or placed in a workflow file.

The service account must have the repository's Node 22 runtime first in PATH
and the fixed Python environment at
`/home/admin/.local/share/site-agent-venv/bin/python`. The runner is allowed
to invoke only the central release script for production deployments.

Do not add a push trigger. Production promotion is an explicit exact-SHA
dispatch so code review and owner approval remain separate from deployment.

## Non-negotiable rules

- The manifest is the tenant registry; do not invent paths or Worker names in
  a command.
- The declared Cloudflare profile is the only credential source. Never source
  `/SOCIAL/site-agent/.env` for a release.
- No legacy customer admin path, repair route, fallback build, or reused
  `.open-next` artifact is allowed.
- The same source SHA and artifact inspected by the gate must be the one
  uploaded to Cloudflare.
