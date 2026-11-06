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
6. **Ada has no Payload admin access.** The admin is the owner's interface. Ada
   reads and writes content through the workspace API with receipts
   (`/api/helloada/*`, `_completed_payload_effects`), never by driving
   `/admin`, never with an owner session, and never with admin credentials.
   Field layout and collection shape come from the shared schema package, not
   from clicking through the CMS. This is a permission and instruction change,
   not a code split: it belongs in the builder's permission set and in the
   generated project map from Step 7.

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

> Coupled to Step 5. The contract generator and the release preflight both read
> `payloadAdmin` from the pinned package, so the pin cannot disappear before the
> identity change lands. Until then the dependency stays declared and installed
> but unused by the template: an admin change no longer needs a package release,
> which is the cost this migration is removing. Steps 3 and 5 land together.


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

### Step 7 — give Ada a project map instead of a search problem

Every build currently rediscovers the repository: where pages live, where the
presentation components live, which files are tenant-owned and which are
platform-owned, what must never be touched. That is the largest avoidable cost
in a build, and it grows with the repository.

Add `src/site_agent/templates/next-payload/AGENTS.md`, generated from the real
tree and overlaid with the shared runtime, so OpenCode loads it automatically at
session start:

- the directory map: frontend routes, presentation components, styles, content
  access, the shared schema package, the workspace API;
- the ownership boundary from decision 4, stated as "what you may change" and
  "what belongs to the platform";
- the build and verification commands the host runs;
- the explicit prohibition from decision 6: no `/admin`, no owner session, no
  admin credentials, content through the workspace API only;
- where to look first for a given request, so a build starts by reading three
  files rather than grepping the tree.

Two constraints. It must be **generated from a declarative path map** that fails
if a mapped directory is missing, so it cannot silently drift from the code. And
it carries contracts and structure only — no worked examples, sample copy, canned
replies or worked conversations, per the standing prompt invariant.

Acceptance: a build's transcript shows the map being read at the start and no
full-tree exploration before the first edit.

### Step 8 — give Ada a working budget, not a window

The model advertises a one-million-token window. That is capability, not a
budget: attention quality falls and cost rises as the working set grows, and a
design task never needs more than a handful of files plus the owner's request.
Long-term memory already covers the rest, and it is injected, so recall is
cheap.

So the builder declares a **working budget well below the model's window** and
compacts against that budget:

```jsonc
{
  "compaction": {
    "auto": true,
    "keep": { "tokens": 15000 },
    "buffer": "15%"
  },
  "tool_output": { "max_lines": 600, "max_bytes": 20000 },
  "experimental": { "background_compaction": true }
}
```

- `limit.context` carries the working budget (start at 200k, measure, drop
  toward 128k while quality holds), not the model's 1M capability. Declaring
  less than the provider accepts only makes compaction earlier; it never fails a
  request. Record the real window separately so the two numbers are not
  confused.
- `auto` and `buffer` make compaction fire with room left to finish the turn.
- `background_compaction` keeps summarisation from stalling the build.
- `tool_output` caps keep one noisy command from consuming the budget.
- Sessions stay per job: a new owner request starts a new session, and a build
  never resumes another request's transcript.

Memory is the overflow, not the context. The injected memory context stays small
(twenty observations), and the project map from Step 7 says what memory holds and
when to rely on it instead of re-reading the repository. Compaction is the
backstop; the map, the output caps and recall are what keep the session short.

Measure it: median input tokens per build and time to first edit, before and
after. Acceptance: no build fails at the provider for context length, compaction
events appear only on long builds, and median input tokens drop substantially
without a rise in rework.

### Step 9 — tests

- `tests/test_shared_runtime.py`: the overlay test asserts admin source is
  copied and that a changed admin file changes the fingerprint. The current
  pin assertion (already derived from the template lock) is deleted.
- Release queue tests: `payloadAdmin` disappears from the contract; a missing or
  mismatched `sharedRuntime` fails closed.
- Preview tests: the preview overlay copies the admin tree.
- Template test: no file imports the removed package.
- Instruction test: the generated `AGENTS.md` maps only paths that exist, and it
  contains no example dialogue or canned phrasing.
- Builder config test: the declared context budget is the working budget, not the
  model's advertised window, and compaction is enabled with a buffer.

## Progress

Landed on `main`:

- [x] Steps 1–2 — admin source lives at `src/admin` in the template, the
  wrappers import it through `@/admin`, and typecheck plus a full Next build pass
  with the package still installed.
- [x] Step 4 — overlay schema 3 with `copyTrees` (`src/admin`,
  `src/components/admin`) plus `src/app/(payload)/custom.scss`; the preview path,
  the release path and the fingerprint all expand the trees, and a symlink or
  special file inside a tree fails closed.
- [x] Steps 3 and 5 — the pin is gone and the identity is
  `sharedRuntimeFingerprint`: a 64-hex hash of the overlay contract and the
  exact shared source bytes, injected into the contract generator, written to
  the Wrangler vars, reported by `/api/health`, and recorded in every release
  receipt. It is a release property, never part of the tenant contract, so no
  tenant release needs a fingerprint update first. The overlay also removes a
  leftover admin dependency from tenant manifests and rewrites the one
  platform-owned import in the tenant-owned `src/helloada.config.ts`.
  Verified: 2490 Python tests, 153 template tests, template typecheck and Next
  build, and a wheel build.
- [x] Preview parity — the preview reads the fingerprint the release activation
  recorded for the tenant, requires an exact hash, and stamps it into the
  tenant's contract manifest. The API runs from a wheel with no control
  checkout, so it cannot recompute the fingerprint; a tenant without a recorded
  activation fails with a clear message instead of a build error.
- [x] Canary release — OceanicVibes released through the queue at
  `1afb6250` with fingerprint `c99a4f0d…`, core 0.6.5, schema revision 13.
  `/api/health` reports `sharedRuntimeFingerprint` and no `payloadAdmin`; the
  admin loads, the Website tab renders the preview, the page selector lists
  every route, and the preview `/blog` stays inside the preview mount with six
  listing entries. One design warning remains in the preview console: a GSAP
  tween targets `.image-caption`, which the journal page does not render.
- [x] Publish refusal — the owner's publish failed because the candidate's
  production base (`6ae47ab`) no longer matched `main` (`1afb6250`, the revision
  13 merge), and the admin reported only "The draft could not be published."
  The admin now resolves both error shapes (`message` and FastAPI's `detail`).
  The candidate was rebased onto current main and rebuilt, then published:
  merge `e6f4516f`, release `rel-20261106121511-c4b235c7` deployed, live
  `/blog` serving the new journal with six entries.
- [ ] Follow-up from that refusal — a stale base still blocks publish with no
  owner-visible remedy. The admin needs a "refresh candidate" action that
  rebases the preview branch onto current main, rebuilds, and updates the
  draft's base and head, instead of requiring an operator.

- [ ] Step 6 — delete the packaging flow. `packages/helloada-payload-admin`
  and `.github/workflows/release-payload-admin.yml` still exist and are now dead
  weight: nothing pins or imports the package in a tenant build. Deleting them
  is the next commit, and until then the directory is a duplicate source tree
  that must not be edited.
- [ ] Step 7 — generated project map.

Code checkpoints already exist: History lists published versions and a restore
creates a revert commit on the preview branch plus an approval-gated rollback
draft, so an older frontend is reviewed and promoted like any other change. The
gap is the same post-hoc refusal this migration deletes for builds —
`restore_version` refuses while any review is pending, even though the restore
is a preview. Fix it the same way: revise the open review in place.

- [ ] Step 8 — working context budget.

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
| compaction drops a detail mid-build | map and output caps keep sessions short; the diff is the source of truth | raise `keep.tokens`; never disable compaction |
| the project map drifts from the tree | generated from a validated path map; missing path fails the build | revert the generator change |

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
