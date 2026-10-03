# Managed Payload website

Use the shared HelloAda Payload admin package and canonical `/api/helloada/*`
bridge. Preserve the customer-owned frontend, Payload globals and content schema.

Production deployments are owned by the central `weareheadless/site-agent`
VPS pipeline. Push reviewed customer source to official `main`, register the
tenant in its `deploy/payload-customers.json`, then commit the full customer
SHA and a new release ID to `deploy/desired-releases.json` on `site-agent/main`.
Read the shared `deploy/README.md` and `AGENTS.md` for the full contract.

The VPS `helloada-release.timer` performs the release in a fresh checkout.
Inspect its journal and `/SOCIAL/payload-releases/runs/<tenant>/<release-id>/receipt.json`.
Failed or interrupted jobs stop until a corrected request has a new release ID.
Never run ad-hoc production builds/uploads, reuse output, substitute credential
files, or add legacy APIs as a repair. Schema migrations are a separate reviewed
operation. A receipt must pass the authenticated browser check before reporting
the owner-visible interface verified. Content publication requires owner approval.
