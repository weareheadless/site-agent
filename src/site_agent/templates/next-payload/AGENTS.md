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

Public article URLs have one canonical contract: `/blog` is the index and
`/blog/{slug}` is an article. Both bases are declared in
`src/helloada.config.ts`; cards, previews, sitemaps and the API bridge use the
shared route resolver. Do not add `/post` or `/articles` route handlers,
redirect aliases, or tenant-specific article URL conventions.

Production deployments are owned by the central `weareheadless/site-agent`
VPS pipeline. Push reviewed customer source to official `main`, register the
tenant in its `deploy/payload-customers.json`, then commit the full customer
SHA and a new release ID to `deploy/desired-releases.json` on `site-agent/main`.
Read the shared `deploy/README.md` and `AGENTS.md` for the full contract.

The VPS `helloada-release.timer` performs the release in a fresh checkout.
Inspect its journal and `/SOCIAL/payload-releases/runs/<tenant>/<release-id>/receipt.json`.
Failed or interrupted jobs stop until a corrected request has a new release ID.
Never run ad-hoc production builds/uploads, reuse output, substitute credential
files, or add legacy APIs as a repair. Only first-site bootstrap may initialize
the exact committed migration chain against a proven-empty tenant D1; ordinary
releases verify that chain without changing the database. Existing-customer
schema conversion requires its own reviewed migration release. A receipt must
pass the authenticated browser check before reporting the owner-visible
interface verified. Content publication requires owner approval.

In a production Worker, tenant credentials come only from Cloudflare runtime
bindings; never fall back to process variables. Run Payload CLI commands through
the package-managed scripts so `PAYLOAD_CLI=1` selects Wrangler's platform
proxy explicitly. A production CLI run requires the Cloudflare API token and
must never be redirected to local D1 by an override flag.

Payload is the only runtime content authority. Missing required documents,
bindings, media, locale values, tenant identity, or contract versions are errors;
do not substitute static files, hardcoded business copy, a second reader, or a
different API. Customer schema definitions and production migration commands
do not belong in this repository. New sites must preserve this exact scaffold
and its package pins; a one-time migration must finish before any old reader is
removed.
