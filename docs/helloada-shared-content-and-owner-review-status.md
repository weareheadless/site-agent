# HelloAda shared content and owner review — implementation status

This is the maintained architecture/status companion for the approved
25-section implementation plan. It records source changes separately from
release proof. It is not a declaration that customer migrations or production
deployment have happened.

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
- Production source changes use the central VPS release queue. Schema/data
  migration is a distinct reviewed operation with tenant/database identity,
  backup and restoration rehearsal, dry-run evidence and a recorded cutover.

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

## Not complete — hard release and acceptance gates

### 1. Default intake is not on the durable release path

`application/bootstrap.py` still runs `npm install`, creates/applies a Payload
migration against the configured Worker bindings, builds locally, and invokes
`wrangler deploy` directly. That contradicts the VPS-only production release
contract. It is not acceptable to claim the new-site default path complete until
bootstrap queues an exact release through the central VPS pipeline and the
initial shared-schema migration is a reviewed deterministic artifact.

The normal HelloAda intake has not been exercised from a fresh tenant through
generation, typed-content population, actual preview, refusal/revision, exact
approval and verified publication. A successful unit test or manually prepared
template is not this proof.

### 2. Payload writes are not yet proven atomic compare-and-swap

The new save/publish endpoints verify hashes before and after their Payload
effects and coordinate through the D1 operation registry. The shared Payload
hooks also reject writes while another registered operation is active. This is
useful fencing and receipts, but it does not prove a serializable CAS boundary
against every possible Payload writer: an independent Payload operation could
pass its hook immediately before a competing operation claims the D1 row. The
plan's race test (candidate B paused, independent edit C, resume B; C must
survive and B must become stale) has not been implemented/run against the pinned
D1 adapter. Growth approval/publication must remain blocked from release until
that destination boundary is solved and parameterized across native, service,
REST, global and version-restore paths.

### 3. Review preview is not the exact public site

The current Growth renderer validates a generic `PublicDocument` projection. It
does not render the tenant's complete route tree, site chrome, article index
card, customer-specific composition, candidate code, or actual edge-cache
result. Article change review therefore does not yet prove the listing card and
cover together. The admin's draft preview also has not passed an authenticated
browser test against an exact draft revision. Do not label the current renderer
hash as a full visual/publication proof.

### 4. Schema/package build and published artifact gates are missing

- The template has no committed `package-lock.json`; its `node_modules` are not
  installed. It has not passed `npm ci`, template typecheck, OpenNext build or
  packed-artifact verification.
- The template points to admin `0.8.6` and core `0.1.0` release URLs. Those
  immutable GitHub artifacts were not verified/published in this task. The
  configured customer manifest versions are not evidence that an artifact is
  live or used by the customers.
- No generated Payload/D1 initial migration is committed or rehearsed. Existing
  tenants cannot safely consume the new contract until migration data mapping,
  backup/restore rehearsal, dry runs and tenant identity checks pass.

### 5. Customer upgrades and production verification are not done

Atelier and OceanicVibes have not been migrated to this schema/content model.
Their database/media identities, counts and locale/route mappings have not been
reconfirmed in this checkout; there are no reviewed migration artifacts or
rehearsed restore evidence. No migration or live content change was performed.

No shared package asset was published, no customer release was queued or
promoted, and no fresh signed-in browser check proves both customer sites use
this candidate. GitHub/network access was unavailable during the repository
audit; local modifications are not committed or pushed production source.

### 6. Remaining product behavior needs end-to-end proof

- Ada's tool writes, builder ownership checks and review APIs need a complete
  audit proving every content/code mutation uses the shared contract and cannot
  change platform files or bypass exact approval.
- A complete review detail must include before/after, named dated evidence,
  affected routes/components, exact candidate/base/document revisions, platform
  contract version, cost/risk, validation and actual effect. Source tests do not
  prove every legacy stored record has the required detail.
- Existing task/report/voice/research history still requires the plan's
  dry-run classification and safe migration; technical errors must remain
  operator history, not owner approvals. Known provider fixtures need corrected
  end-to-end validation before paid submission.
- Scheduler ownership, default cadence, restart/DST/dual-process behavior,
  actual planned dates, paid-work reconciliation and the recent execution rail
  need production-equivalent integration tests.
- The frontend rollback UI/pipeline must produce a selective new commit from a
  supported baseline while preserving current shared packages, CMS data and
  customer design bindings. Promoting an old full Worker is not an acceptable
  rollback. This is not yet proved.
- Global navbar/footer changes need an authenticated Payload edit followed by
  all affected route checks; publication cache invalidation is not yet verified
  live.
- The existing bootstrap and generic source-deployment pathways require an
  explicit audit to ensure they cannot bypass the central release queue.

## Verification performed on this candidate

Candidate verification on 2026-10-03:

- `packages/helloada-payload-core`: **11 tests passed** and `tsc --noEmit`
  passed.
- `packages/helloada-payload-admin`: **28 tests passed** and `tsc --noEmit`
  passed.
- `npm pack --dry-run --json` succeeded for both shared packages, confirming the
  expected source files are included without producing release artifacts.
- Python syntax compilation (`compileall`) and `git diff --check` passed on the
  final local source state.
- A prior full Python-suite run reported **1,137 passed, 7 failed**. Six
  failures were in candidate ownership/design-lab tests, a removed Pelican
  profile, environment allowlisting/preview fixtures, and a sandbox-denied
  socket bind. The seventh exposed a reflection-approval fixture/contract
  mismatch; its handler and fixture were subsequently changed, but that repair
  has not been rerun in this checkout because the active Python runtime has no
  `pytest` installed.
- A prior focused Python contract run reported **127 passed** before that final
  reflection-contract adjustment. It is not evidence for the final Python
  candidate.
- Template TypeScript was syntax-parsed, not typechecked or built. The template
  has no committed lockfile or installed dependency tree, and its candidate
  GitHub package artifacts could not be fetched/verified in this network
  environment.
- Wheel packaging was attempted but not completed: isolated build dependencies
  could not be fetched because network DNS was unavailable.
- No clean packed-package integration, fresh-tenant intake acceptance,
  database migration rehearsal, official VPS receipt, production deployment,
  or fresh authenticated customer-browser verification has been produced.

These results are deliberately separated: green shared-package tests do not
prove the template, Python services, migrations, scheduler, VPS release, or
customer deployments. Missing evidence is a blocked gate, not an assumed pass.

## Release order

1. Solve the default bootstrap/release path and deterministic shared initial
   migration; commit a template lockfile.
2. Implement and test destination-level conditional writes and exact review
   rendering against the pinned Payload/D1/OpenNext runtime.
3. Run the normal intake vertical slice in an isolated tenant and complete the
   approval/refusal/article/report/scheduling/rollback acceptance scenarios.
4. Publish immutable tested core/admin artifacts. Pin the default template and
   register intended consumers to exact versions.
5. Produce tenant-specific migration mapping, backup and restore rehearsal,
   dry-run counts and reviewed migration releases for Atelier and OceanicVibes.
6. Queue customer releases through the official VPS contract; verify exact
   source/artifact/Worker/D1 migration receipts and authenticated browser
   behavior independently for both customers.
7. Update this record with exact official Git SHAs, artifact hashes, migration
   IDs, release receipts, tests and browser proof. Only then mark the plan done.

Until these gates pass, this work is an unpushed source candidate—not a
production migration, customer upgrade, or completed implementation plan.
