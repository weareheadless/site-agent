# HelloAda managed website

This repository is generated and managed by HelloAda. Content is edited in
Payload, design changes are owner-approved, and the live Worker is deployed
from the GitHub `main` revision recorded by the control plane.

The bootstrap service binds `src/helloada.config.ts` to one non-secret tenant
identity before the first customer commit. The Payload admin is provided by
the exact `@weareheadless/helloada-payload-admin` release in `package.json`;
do not copy the package into a customer repository or replace it with the
retired FastAPI admin.

Production releases use the central VPS pipeline. Register the tenant in
`weareheadless/site-agent/deploy/payload-customers.json`, then commit its full
customer source SHA and a new release ID to `deploy/desired-releases.json` on
the official `site-agent/main`. The VPS systemd timer builds a fresh clone,
deploys the inspected artifact and records a receipt. Follow the shared
`deploy/README.md`; do not invoke local `deploy:app` or Wrangler uploads.

`npm run verify:payload` is a release gate. It exercises published, draft, and
version reads for every editable collection plus both shared globals and media.
It must pass against the tenant's remote D1 database before the Worker is
deployed; a failed query is a schema/runtime error, never an empty-content
fallback. The workspace reads both published documents and draft versions,
merging them by stable document ID so published content remains editable before
its first draft version exists, while a real draft takes precedence when one is
present.

## Shared content contract

`@weareheadless/helloada-payload-core` is the only schema/reader/binding source.
Do not add tenant-local copies under `src/collections` or `src/globals`, and do
not replace shared collections in `payload.config.ts`. Tenant configuration may
select locales and supported modules; bespoke public components and styles stay
in the customer repository.

Pages and articles use Payload's regular fields plus stable-key typed sections
where appropriate. The owner editor resolves those same values, keeps Lexical
rich-text structure, and saves one document against its exact loaded draft hash.
Save is draft-only. Publish accepts one document and its reviewed hash; it
re-reads and verifies the exact published Payload document. It never publishes
every pending draft. The review gate asks the tenant's exact Next renderer to
render the owner-authenticated document preview, then checks the published
document marker on its canonical public route (and the article index for posts).
An uncertain operation is reconciled against destination data and is not blindly
replayed. The top-level editor does not change IDs, block types or schema.

Each site declares its journal index and detail base once in
`src/helloada.config.ts`; the route resolver is part of the shared core. Posts
use the same Payload document for the article page, cover image, excerpt,
listing card and SEO metadata. Page and post metadata includes canonical URL
override and social image. Shared navigation/footer data lives in the
canonical Payload globals, not per-page JSX.

New-site bootstrap may apply only this committed migration chain, by its exact
manifest hash, to the registered tenant D1 after proving that database is empty.
An ordinary site release verifies that the applied migration ledger matches the
committed chain and never mutates the database. Existing-customer schema changes
require a deterministic tenant-specific migration artifact, protected backup,
restoration rehearsal, dry-run evidence and a separate recorded cutover. A
mismatch blocks release; it is never repaired by generating SQL against the
currently available D1 binding.

Production Workers read tenant secrets only from Cloudflare runtime bindings.
Process-variable configuration is restricted to local development/tests.
Payload CLI commands must use the package-managed scripts, which select the
Wrangler proxy explicitly; production commands require Cloudflare credentials
and cannot be redirected to local D1.

The template must ship with a committed dependency lockfile and install with
`npm ci`. A candidate package URL or local template test is not evidence that its
immutable package release exists. Production still requires the central VPS
release receipt and fresh authenticated browser verification.
