# Admin moves into the shared runtime

Status: proposed, implementation starting 2026-11-05.
Owner: site-agent platform. Tenant-visible effect: none until the first release after the change.

This document retires the per-tenant `@weareheadless/helloada-payload-admin`
package pin. Admin source becomes shared runtime source, overlaid at build time
like every other centrally owned file.

## Why

One line of admin UI — the Design page selector following in-preview navigation
— required a version bump, a git tag, a GitHub release, an asset upload, a
template pin, a lockfile integrity update, contract regeneration, and then a
tenant release that also dragged a schema migration along. That chain is the
largest cost per change in this repository, and it buys nothing: admin is
platform code, not tenant content.

Current facts, verified 2026-11-05:

| fact | value |
|---|---|
| registered tenants | 14 |
| distinct admin versions pinned | 7 (`0.10.0` … `0.10.51`) |
| files referencing the package or `payloadAdmin` | 45 |
| package source | 42 TS/TSX files, 1.4 MB |
| shared overlay entries today | 42 copied files, 7 removals, 2 fingerprint trees |

The frontend route group does not import the package. Only the `(payload)`
admin routes and `src/lib/*` server helpers do, so there is no runtime coupling
to the public site today. The coupling is entirely build and release ceremony —
and the divergence between seven admin builds across fourteen sites.

## Decisions recorded here

These were decided in conversation on 2026-11-05 and are recorded so they are
not re-litigated per change.

1. **Admin leaves the package/version system.** One admin source, shipped with
   the normal tenant release. This document.
2. **No D1 Time Travel in the product.** It restores in place, it cannot be
   cloned or forked for inspection, and it rolls back the migration ledger, so
   "try an earlier state" is not possible without destroying the current one.
   It remains an operator runbook for disaster only, and only paired with the
   Worker version that matches the restored timestamp.
3. **Restore primitives.** Code and design restore by promoting an older commit
   (each promotion is a new receipt, nothing is destroyed). Content restores
   per document through Payload versions. Whole-database restore is the runbook
   above and is never a product feature.
4. **Ownership boundary.** Ada owns the tenant repository: pages, components,
   styling, motion, content, structure. The platform owns schema, admin, shared
   runtime, credentials and promotion. The check being deleted is the class that
   rejects finished work (the pending-review guard); the path sandbox, schema
   ownership and secret handling stay.
5. **Physically separating admin is deferred.** See "Deferred".

## Target state

| | before | after |
|---|---|---|
| admin source | npm package, versioned per tenant | template source, overlaid at release |
| shipping an admin change | bump, tag, release, asset, pin, contract, tenant release | one commit, next tenant release |
| identity of the live admin | `payloadAdmin` version string | `sharedRuntime` fingerprint |
| tenants on different admin builds | 7 versions across 14 sites | one source |
| admin release asset | required | none |
| frontend bundle | unaffected | unaffected |

## Non-goals

- Not moving admin out of the tenant Worker. That is the deferred project.
- Not changing Payload's admin routes, import map, authentication or session.
- Not changing tenant content, schema, migrations or presentation.
- Not un-pinning `payloadCore`. Core carries the schema contract and stays a
  versioned package with its own release asset.

## Migration steps

### Step 0 — stop the chain

No new `payload-admin-v*` release is published while this lands. The pin stays
functional until Step 5 removes it, so an interrupted migration leaves every
tenant releasable on its existing pin.

### Step 1 — move the admin UI into the template

- `packages/helloada-payload-admin/src/components/*` →
  `src/site_agent/templates/next-payload/src/components/admin/`
- `packages/helloada-payload-admin/styles/admin.scss` →
  `src/site_agent/templates/next-payload/src/styles/admin.scss`
- `packages/helloada-payload-admin/tests/*.test.mjs` → `tests/admin-ui/`

The template already has thin wrappers at
`src/components/admin/HelloAdaWorkspace.tsx`, `HelloAdaNav.tsx` and
`HelloAdaLogo.tsx` that re-export the package. The real implementations replace
them at the same module paths, so `(payload)/admin/importMap.js` and
`(payload)/custom.scss` need no edit. Keep the server/client split: the module
the import map names stays the server component that renders the client
workspace.

Acceptance: `npm run typecheck` and the Next build pass in the template with the
package still installed but unused by the admin routes.

### Step 2 — move the server helpers

The package also exports server plumbing used outside the admin:

- `src/server/runtime-env.ts` → `src/lib/helloada-runtime.ts`
- `src/config/site.tsx`, `src/config/provider.tsx` → `src/lib/helloada-site.tsx`
- `src/version.ts` → deleted; replaced by a generated
  `src/lib/shared-runtime-identity.ts` holding the shared-runtime fingerprint.

Update the importers: `src/lib/helloada-upstream.ts`, `src/lib/service-auth.ts`,
`src/lib/growth-operations.ts`, `src/helloada.config.ts`,
`src/app/api/health/route.ts`, `src/app/api/helloada/[...path]/route.ts`.

Acceptance: no template file imports `@weareheadless/helloada-payload-admin`;
the package can be removed from `node_modules` without breaking typecheck.

### Step 3 — remove the dependency and the pin

- Remove the dependency from
  `src/site_agent/templates/next-payload/package.json` and `package-lock.json`.
- Remove `payload.contract.adminVersion` from every entry in
  `deploy/payload-customers.json`.
- Remove `payloadAdmin` from the canonical contract in
  `src/site_agent/application/release_queue.py` and the identity keys in
  `src/site_agent/hands/github_release_queue.py`,
  `src/site_agent/application/runtime_resolution.py`,
  `src/site_agent/application/durable_object_reconciliation.py` and
  `src/site_agent/hands/design_experiment.py`.
- Remove the admin asset URL and pin from `scripts/generate-payload-contract.mjs`
  and the `payloadAdmin` field from `template-manifest.json`.

Acceptance: `deploy/desired-releases.json` still validates, and a queued release
for a tenant whose manifest no longer declares an admin version passes
preflight.

### Step 4 — overlay the admin tree

`deploy/shared-runtime-overlay.json` copies files, and a 42-file directory would
need 42 entries — a list someone will forget to extend, which fails open as a
stale tenant admin. Extend the manifest to schema 3 with a `copyTrees` list
(template-relative directories), and bump the contract to
`helloada-shared-runtime-v3`:

- validate each tree: directory, no symlinks, no special files, not empty;
- copy file by file, recording every path in `copiedPaths` as today;
- fingerprint tree contents in `shared_runtime_fingerprint`;
- apply the same overlay in the compiled preview path
  (`apply_preview_runtime_overlay`), so preview and release keep matching.

Acceptance: a tenant checkout that still contains the old package imports is
replaced by template admin source, `src/components/admin/` appears in
`copiedPaths`, and the preview build contains the same bytes as a release build.

### Step 5 — one identity instead of a version

`/api/health` reports `sharedRuntime` (the fingerprint) instead of
`payloadAdmin`. The queue already pins a runtime fingerprint per release and
receipts already record it, so this closes an existing loop rather than adding a
concept: the verifier compares the live Worker's `sharedRuntime` to the
candidate's fingerprint, which is strictly stronger than comparing a version
string someone remembered to bump.

Remove the `_VERSION` match for `payloadAdmin` in
`github_release_queue.py` and the `adminVersion` mapping in
`release_queue.py`. Receipts keep the fingerprint they already store.

Acceptance: a release with a mismatched fingerprint fails the live gate; a
matching one promotes.

### Step 6 — delete the packaging flow

- Delete `scripts/package-payload-admin-release.mjs`.
- Remove the admin package section from `docs/private-package-deployment.md`,
  keeping the core package procedure intact.
- Remove the `payload-admin-v*` tag convention from release notes and tooling.

### Step 7 — tests

- `tests/test_shared_runtime.py`: the overlay test asserts admin source is
  copied and that a changed admin file changes the fingerprint. The current
  pin assertion (already derived from the template lock) is deleted.
- Release queue tests: `payloadAdmin` disappears from the contract; a missing or
  mismatched `sharedRuntime` fails closed.
- Preview tests: the preview overlay copies the admin tree.
- Template test: no file imports the removed package.

## Verification gates

1. `.venv/bin/pytest -q`, `.venv/bin/python -m compileall -q src`, wheel build.
2. Template `npm run typecheck` and a full OpenNext build with local bindings.
3. One real tenant release through the canonical queue — a release with no
   schema migration, so a failure is attributable.
4. Authenticated browser check on that tenant: `/admin` loads, the Design tab
   renders the preview, the page selector follows in-preview navigation, the
   History view lists and restores a published version, and a collection record
   saves.
5. A second tenant release proves no admin pin is needed and the fingerprint
   gate passes.
6. The remaining twelve tenants converge at their next release; they are not
   in owner use, so no migration window is required.

A green unit test, a receipt or a health response is not step 4. The owner-visible
admin must be opened and used.

## Risks and rollback

| risk | mitigation | rollback |
|---|---|---|
| import map or admin registration breaks | paths stay stable; browser gate | revert the commit; no data change |
| overlay tree support is new code | fail closed on symlink, special file, empty tree | revert; schema 2 manifest still valid |
| identity change weakens the live gate | fingerprint is stronger than a version; mismatch test | revert the commit; re-pin at the prior version |
| 42-file import rewiring misses a reference | typecheck with the package removed | revert |
| first release is a runtime fan-out | expected; fingerprint change forces it | none needed |

No step touches tenant data, schema or migrations, so every rollback is a code
revert plus a release.

## Deferred: platform-hosted admin

Physically separating admin is not part of this migration, because Payload's
admin is server-rendered against the tenant database (`RootPage({ config })`)
and `/api/helloada/*` runs Payload in-process. A platform-hosted admin
therefore needs a platform-to-tenant identity and trust path, plus cross-origin
session handling. That is the riskiest change available in this codebase and it
buys no owner-visible behaviour today. With no owner using a site, migrating
later is cheap; building the second auth path now is not.

## Open questions

- Replace `payloadAdmin` in the health response outright, or keep an alias for
  one release? Recommendation: replace — two identities invite drift.
- Should admin source sit under `src/components/admin/` (path-stable, import map
  untouched) or a new `src/admin/`? Recommendation: `src/components/admin/`.
- Does any external monitoring read `payloadAdmin` from `/api/health`? Check
  before Step 5; if so, keep the alias for one release and remove it after.
