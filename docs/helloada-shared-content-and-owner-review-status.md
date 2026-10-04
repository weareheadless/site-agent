# HelloAda shared content and owner review — implementation status

This is the maintained architecture/status companion for
`docs/site-agent-payload-platform-consolidation-implementation-plan.md` (20
sections). Source changes are reported separately from release proof. Atelier
Harmonie and OceanicVibes are validation tenants with no production/customer
data; they must be deployed and migrated to validate the shared system. Final
acceptance additionally requires a newly spawned HelloAda site to inherit the
canonical schema and editable bindings.

## Current candidate status — 2026-10-04

This is a source candidate, not an accepted rollout. The user clarified that
Atelier Harmonie and OceanicVibes are validation tenants with no production or
real customer data. They exist to test the shared architecture. A green local
test is not validation: both tenants must first be deployed and checked, and a
new normal-flow HelloAda site must be the final proof that schema and editable
field bindings are inherited without manual repair.

- Local canonical versions: core `0.2.0`, admin `0.8.7`; the template has a
  committed lockfile, imports the shared schema, and includes a committed
  initial migration chain. Core schema identity is locale-independent; tenant
  locale/configuration identity is recorded separately.
- Bootstrap now creates from the canonical template and queues the exact source
  SHA and migration identity through the central VPS release queue. It does not
  directly deploy Wrangler or apply an existing-tenant migration.
- Exact local candidate commit: `6089cab2f19a17c1af2313c18b9e59cba101c0d8`.
  The VPS-isolated full Python suite passes **1,148 tests**. Core passes **15
  tests + typecheck**, admin **30 + typecheck**, the canonical template **6 +
  typecheck + lint**, Atelier **2 + typecheck + lint**, and OceanicVibes **1 +
  typecheck + lint**. Production Next builds pass for the template and both
  tenant sites.
- Both tenant source snapshots now import the canonical core contract, use its
  shared route resolver, and include append-only migrations to the same schema
  identity. Their historical migration ledgers remain tenant-specific and
  their D1/R2 identities are unchanged. These are local source/build results;
  neither migration has been applied to a tenant Worker yet.
- A durable, fail-closed release path exists locally. This change adds an
  explicit schema-migration queue request: the VPS verifies the exact starting
  ledger, uploads the candidate without promotion, applies only committed
  migrations, verifies Payload, and then promotes. Ordinary releases cannot
  advance an existing schema.
- The legacy FastAPI-served owner UI/commands still exist pending the plan's
  migration/parity gates; Pelican runtime, importer and build paths have been
  removed from active code. Remaining historical references need cleanup.
- No central commit has been pushed to official GitHub `main`; no package
  release for core `0.2.0` or admin `0.8.7`, tenant release receipt,
  authenticated tenant browser proof, or fresh spawn proof has been confirmed.
  Therefore the implementation remains **in progress and not accepted**.

Acceptance order: convert and deploy both validation tenants from their existing
source and migration histories; verify canonical Payload edits, frontend
bindings, globals, SEO metadata and package/schema identities independently on
both; then create a genuinely new site through normal HelloAda intake and prove
the default schema, editable page/article fields, navigation and settings are
present and rendered automatically. No DNS changes are part of acceptance.

## Locked product contract

- `site-agent` owns the canonical Payload schema, validators, readers, stable
  content bindings, admin package, default scaffold and release contract.
- Each tenant keeps its own database, media, business data, evidence and public
  design. The schema is shared; the data and frontend composition are not.
- Ada may author content and change tenant-owned frontend code. Routine site
  work may not change schema, migrations, admin, auth, platform bridges, package
  pins or runtime configuration.
- A content save creates one draft for one exact Payload document. Publishing
  requires the exact reviewed document hash and is an explicit owner action.
- Reports are read-only information. Settings have typed setting effects.
  Website code/content decisions must not be mixed into one misleading
  Publish/Discard action.
- Owner website rollback is a new selective frontend-code restoration on the
  current platform baseline. It never restores a prior Worker wholesale or
  rolls back Payload content, media, settings, schema or admin.
- All shared-source deployments use the central VPS release queue. Existing
  tenant schema migrations are explicit, ledger-pinned requests; new tenants
  use the canonical initial migration. Preserve each tenant's D1/R2 identity.

## Implemented in this local source candidate

### Shared Payload model and owner editor

- Added `packages/helloada-payload-core` as the canonical source for collections,
  globals, typed page sections, content readers, link validation and stable-key
  field bindings. The template's local collection/global copies are removed.
- Page/post content includes stable-key typed headings, paragraphs, Lexical rich
  text, images, links and lists; featured image, excerpt, SEO title/description,
  social image and canonical override remain first-class fields. Shared
  navigation and site settings remain Payload globals. Product/category modules
  remain explicit rather than being dropped during schema centralization.
- New section, block/list and navigation IDs are assigned once during Payload
  validation. Existing IDs survive edits and reordering; duplicate or missing
  IDs fail validation.
- The admin derives its owner-editable field index from canonical Payload data.
  It supports pages and article documents, uses tenant-local media IDs, and
  retains actual Lexical structure when saving rich text.
- Owner save now requires one selected document and its loaded draft hash,
  applies stable-key edits, writes only the changed allowlisted fields, verifies
  the resulting hash, and stores a destination operation receipt. Schema IDs,
  block types and editor labels are not owner-editable values.
- Publish now accepts exactly one Payload document and the exact hash shown to
  the owner. It verifies the published Payload data, and duplicate/interrupted
  requests consult the receipt instead of automatically replaying an uncertain
  write. This verifies Payload state; it is not yet proof of the full public
  route, customer-specific renderer or edge cache.
- Article workspace routes use `/articles/<slug>` and use the same Payload post
  for article content and listing-card bindings. Workspace inventory now pages
  through all Payload results rather than stopping at the first 100.
- Growth and Activity source changes from the approved plan consolidate owner
  decisions into one review-first list; separate planned/completed filters and
  execution history remain. Reports are not presented as publishable website
  content. The HelloAda light work surfaces/dark chrome, contrast rules and
  English/French/Mexican-Spanish interface changes have source tests.
- Default-template contributor instructions, package READMEs and this status
  record now describe the shared schema and separate migration boundary.

### Existing Growth/service candidate work

The current branch also contains the earlier implementation work for durable
Growth scheduling/projection, a unified task list, report details, provider
request validation, task receipts, connection/readiness checks, and release
manifest checks. Focused tests cover those source contracts. Do not infer from
those tests that provider accounts, paid research, the scheduler on the VPS, or
either customer's deployed UI has passed a live end-to-end run.

## Not complete — acceptance blockers

### Tenant conversions and deployments

The local tenant candidates import the canonical core and map their public
frontends to stable editable fields, but neither has been pushed, migrated, or
deployed. Each must retain its append-only Payload history and current D1/R2
identity. Source inspection or a build does not satisfy this gate: both must be
deployed through the release queue and independently checked in Payload and on
the public routes.

### Shared package release and central source

Core `0.2.0` and admin `0.8.7` are local candidates only. Publish exact immutable
artifacts from a committed `site-agent` SHA, verify package contents and
integrities, then consume those releases from the template and both tenant
repositories. Do not queue a tenant whose package asset or migration manifest
does not exist and match the registry.

### Fresh-site proof

No brand-new site has been created by the normal HelloAda intake from the final
template. The final proof must exercise onboarding/spawn, then verify that
Payload already contains the default editable page/article fields and shared
navigation/settings and that the generated frontend renders their edited values
without tenant-specific schema repair.

### Plan-wide functional gates

- Run authenticated browser acceptance on all three sites. Confirm the shared
  HelloAda shell, spacious chat/preview, image gallery and editing affordances,
  Payload-owned page/article/SEO/navigation/footer fields, Growth analysis and
  one review-first decision list. Validate actual changes on their public routes.
- The D1-backed conditional-write race must prove stale Ada drafts cannot
  overwrite an independent Payload Admin/REST change. Until that race passes,
  do not claim atomic compare-and-swap or enable unsafe publication paths.
- Confirm Growth scheduling has durable dates, one clear user-action/approval
  list, truthful task details and execution history; ensure provider failures
  are actionable technical diagnostics, not owner recommendations.
- Finish the plan's legacy FastAPI UI retirement only after Payload parity is
  verified. Pelican remains absent from active code; remove stale executable or
  runbook references without reintroducing a fallback.
- Prove source, candidate artifact, migration, promotion, health, authenticated
  connection and browser evidence independently for each tenant. No DNS change
  is needed or authorized by this acceptance.

## Verification recorded on this candidate

- Full Python suite on the isolated VPS candidate checkout: **1,148 passed**.
- Core **15/15**, admin **30/30**, template **6/6**, Atelier **2/2**, and
  OceanicVibes **1/1** Node contract tests pass; all five TypeScript checks and
  lints pass (existing image and generated-migration warnings remain).
- Production Next builds completed for the template, Atelier, and OceanicVibes.
  These builds used the local package source links; a clean install from the
  forthcoming immutable release tarballs is still required in the VPS release
  pipeline.
- The template has a lockfile and committed migration artifacts. These do not
  substitute for a clean package-consumer build or live tenant migration proof.
- No official central push, shared-package release, tenant deployment receipt,
  authenticated browser proof, or fresh spawn proof is recorded yet.

Test status refers only to source-level candidate evidence. It does not validate
the common Payload contract across live tenants; the release and new-site gates
above remain mandatory.

## Release order

1. Push the tested central-source candidate; publish and verify immutable
   core/admin assets from its exact SHA.
2. Push the two converted tenant candidates after confirming the package
   assets, then queue and apply their exact append-only migration heads without
   replacing either tenant's D1/R2 identity.
3. Queue and deploy each validation tenant separately; record exact source,
   artifact, migration and Worker receipts and verify Payload edits on actual
   pages, article cards/routes, SEO metadata and shared globals.
4. Run the plan-wide authenticated Payload/browser checks and finish retirement
   of the legacy FastAPI owner UI once parity is established.
5. Create a genuinely new tenant through normal HelloAda onboarding. Verify
   schema identity, package pins, default editable fields, shared globals and
   frontend bindings with no manual schema repair.
6. Update this record with exact SHAs, package integrities, migration IDs,
   release receipts, test output and authenticated browser evidence. Only then
   mark the implementation plan accepted.

Until these gates pass, this work is an unpushed source candidate—not a
production migration, customer upgrade, or completed implementation plan.
