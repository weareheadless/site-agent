# Managed Payload website

Use the shared HelloAda Payload admin and core packages and the canonical
`/api/helloada/*` bridge. The shared core owns collections, globals, validators
and public content readers. A tenant config may select locales and platform
modules; it must not replace the shared schema with customer-local copies.
Customer frontend composition, styles and content remain tenant-owned.

Content editing uses `@weareheadless/helloada-payload-core/bindings`. Bindings
resolve by collection/document/stable section/block/item IDs, never array index
or visible text. Owner saves must remain draft-only, target one exact document
revision, preserve Lexical data and restrict fields to the declared content
contract. Publish only an explicitly reviewed single-document revision. Do not
claim a generic markup hash is proof of the full tenant route/render/cache.
Payload schema and migration files remain platform-owned, not Ada-editable.
Routine Ada website work cannot change schema, migrations, admin, auth, server
bridges, package pins or runtime configuration.

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
