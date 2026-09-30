# Site-Agent / Payload Platform Consolidation Plan

**Status:** Proposed implementation contract for a coding AI
**Date:** 2026-09-30
**Scope:** Make `site-agent` the central product code consumed by every customer website; make Payload the only customer administration interface; migrate Atelier Harmonie and OceanicVibes; remove the legacy human-facing FastAPI interfaces and all Pelican runtime paths.

## 1. Authority and reading order

Read this document completely before editing code.

This plan is authoritative for:

- the customer administration surface;
- the shared HelloAda Payload UI package;
- the canonical customer-site runtime and scaffold;
- removal of the legacy FastAPI-served owner interfaces;
- removal of Pelican and its compatibility paths;
- migration order for Atelier Harmonie, OceanicVibes, and new customers;
- fleet versioning and rollout.

It complements, and does not weaken:

- `AGENTS.md`;
- `docs/helloada-multi-site-control-plane-implementation-plan.md`;
- `docs/next-react-payload-correction-plan.md`;
- `docs/brand-composition-and-behavior-system-implementation-plan.md`;
- the immutable candidate, deterministic validation, owner review, and explicit production-approval rules.

Where older documents describe `src/site_agent/web/static/admin.html`, the
`site-agent serve` command, a FastAPI password session, Pelican, or a
`pelican_baseline` build profile as supported product surfaces, this plan
supersedes them.

This plan does not authorize a production deployment, remote database
migration, DNS change, repository push, or deletion of production resources.
Those remain separate owner-approved operations.

## 2. Executive decision

There will be one product architecture:

```text
                         site-agent repository
                    (central source and release train)
                                  |
              +-------------------+-------------------+
              |                                       |
      Python control plane                 HelloAda Payload package
      api.helloada.app                     + canonical site template
              |                                       |
              +-------------------+-------------------+
                                  |
                 customer Next.js + Payload Worker
                 /admin = HelloAda owner workspace
                 public site = customer-specific design
                 D1 + R2 = customer-owned data
```

Decisions:

1. **Payload is the only customer CMS and administration surface.** Every
   customer manages their website at that website's `/admin` route.
2. **`site-agent` is the central product repository.** It owns the AI/control
   plane, typed API contract, shared HelloAda Payload-admin package, canonical
   Next/Payload template, migration tooling, and release manifest.
3. **Customer sites remain independent and exportable.** Each customer keeps a
   normal Git repository, Cloudflare Worker, D1 database, and R2 bucket. The
   shared product package does not take ownership of customer content.
4. **The legacy human-facing FastAPI applications are removed.** `site-agent`
   remains an API service. FastAPI may remain the internal Python HTTP framework
   for the tenant-aware API; it must not render or own a customer UI.
5. **Pelican is removed completely.** There is one build profile,
   `next_react`; one CMS, Payload; and one deployment target, the customer's
   Next/OpenNext Cloudflare Worker.
6. **HelloAda has one visual identity.** The admin shell uses the HelloAda logo,
   coral/amber dark design system, product-window language, motion restraint,
   and progressive disclosure. A customer's identity appears as workspace
   context and inside the website preview, not as a reskin of HelloAda.
7. **Updates are versioned, tested, and rolled out.** A source change cannot
   magically alter an already-built Worker. New sites receive the current
   stable release automatically; existing sites receive an automated upgrade
   pull request and rebuild. Production still changes only after its normal
   approval gate.

## 3. Product boundaries

### 3.1 `site-agent` owns

- tenant registration and isolation;
- intake, research, customer context, and durable conversations;
- Ada planning and design operations;
- recommendation, approval, revision, and rollback workflows;
- repository/build orchestration and browser evidence;
- GitHub and Cloudflare provisioning adapters;
- SEO, analytics, media-analysis, and social workflows;
- the tenant-aware `/v1/workspace` API;
- the control-plane `/v1/control-plane/websites/{website_id}` API;
- the shared HelloAda Payload-admin React package;
- the canonical Next.js/React/Payload/D1/R2 template;
- importers and validators used to migrate legacy sites;
- a signed/versioned release manifest and customer upgrade coordinator.

### 3.2 Each customer site owns

- its public Next.js/React frontend and distinctive design;
- its Payload collections, globals, access policy, and migrations;
- its Payload users and local session;
- its D1 content database and R2 media bucket;
- its Git history and exportable source;
- thin same-origin API routes that authenticate the Payload user and proxy to
  `site-agent` without exposing service credentials;
- a small, typed customer configuration describing name, locale, collections,
  routes, and enabled capabilities.

### 3.3 HelloAda's central application owns

- account sign-in and website portfolio;
- website creation and bootstrap progress;
- the minimal intake/build room;
- membership and handoff into the customer Payload admin;
- no second full CMS and no duplicate design pipeline.

### 3.4 Explicit non-goals

- Do not make customer content multi-tenant inside one central Payload database.
- Do not put customer D1 or R2 credentials in a browser or package.
- Do not make every public website share one visual template.
- Do not copy the shared admin implementation into each site and call it shared.
- Do not use a runtime CDN script to replace package versioning.
- Do not auto-deploy every customer immediately after a package release.
- Do not replace FastAPI merely to change frameworks; remove its obsolete UI
  responsibilities and retain the API transport until there is a measured
  reason to replace it.
- Do not preserve Pelican as a hidden fallback.

## 4. Current state and first broken boundary

The intended path is:

```text
Payload owner session
  -> HelloAda workspace component
  -> same-origin authenticated route
  -> tenant-scoped site-agent API
  -> application service
  -> draft / operation / revision
  -> Payload preview
  -> owner approval
```

The first broken boundary is **the owner interface is not yet a shared product
package**.

Current evidence:

- Atelier Harmonie already has the correct runtime class: Next.js + Payload +
  D1 + R2, with custom `WebsiteWorkspace`, `StudioNav`, chat, preview, content
  editing, and history components.
- Those components and styles are hard-coded in the Atelier repository, use
  Atelier-specific API paths and labels, and carry the old WeAreHeadless brand.
- `src/site_agent/templates/next-payload` has the beginning of the canonical
  runtime but does not contain the full HelloAda admin product.
- `src/site_agent/web/static/admin.html` is a separate legacy owner interface.
- `src/site_agent/web/static/intake_lab.html` is another human-facing FastAPI
  interface.
- `src/site_agent/web/server.py` mixes obsolete UI/session routes with useful
  application behavior and preview compatibility.
- OceanicVibes still declares `site.adapter: github_static`,
  `blog.engine: pelican`, and Pelican-specific writable/build paths.
- Pelican remains in package dependencies, scaffolding, build profiles,
  prompts, preview branches, tests, documentation, and CLI commands.

Do not start by deleting files. First create the shared replacement, prove
feature parity, migrate active customers, then remove compatibility code.

## 5. Target repository layout

`site-agent` becomes a small polyglot monorepo with one release train:

```text
site-agent/
  src/site_agent/                         Python control plane
    application/                          workflows
    core/                                 contracts and persistence
    brain/                                Ada policy
    hands/                                GitHub/Cloudflare/Payload adapters
    api/                                  tenant and control-plane HTTP adapters
    templates/next-payload/               canonical customer application
    migrations/legacy/                    customer import tools

  packages/
    helloada-payload-admin/               shared Payload/React owner UI
      src/
        components/
        api/
        config/
        styles/
        brand/
      package.json
      tsconfig.json
      tests/

  contracts/
    workspace-openapi.json                generated API contract
    release-manifest.schema.json

  docs/
  tests/
```

The exact directory move from `web/` to `api/` may happen after the legacy UI
is gone. Do not perform a cosmetic module move while behavior is still being
extracted.

## 6. Shared HelloAda Payload-admin package

### 6.1 Package responsibility

Create a versioned package provisionally named
`@weareheadless/helloada-payload-admin` under
`packages/helloada-payload-admin`.

It owns:

- HelloAda logo assets and accessible graphics;
- fixed HelloAda design tokens;
- Payload `Nav`, `Icon`, `Logo`, and dashboard components;
- the full website workspace: preview, Ada conversation, recommendations,
  approvals, history, media entry points, page/content entry points, settings,
  and diagnostics disclosure;
- responsive and reduced-motion behavior;
- a typed API client for the customer site's same-origin bridge;
- reusable loading, empty, error, and disconnected states;
- localization keys for the product chrome.

It must not own:

- customer collections or globals;
- customer copy, prices, routes, or brand colors;
- service tokens;
- direct access to D1, R2, GitHub, Cloudflare, or `site-agent` credentials;
- public-site rendering;
- business logic that belongs in `site-agent` application services.

### 6.2 Configuration contract

Every site supplies one typed, non-secret configuration:

```ts
export default defineHelloAdaSite({
  tenantId: 'atelier-harmonie',
  siteName: 'Atelier Harmonie',
  defaultLocale: 'fr',
  locales: ['fr', 'en'],
  routes: {
    workspaceApi: '/api/helloada',
    liveSite: '/',
  },
  content: {
    primaryCollections: ['pages', 'posts', 'products', 'media'],
    settingsGlobals: ['siteSettings', 'navigation'],
  },
  features: {
    commerce: true,
    posts: true,
    social: false,
  },
})
```

Rules:

- Values are validated at build time.
- Unknown capability names fail the build.
- The tenant ID is never trusted as authentication.
- Site-specific labels come from configuration or Payload metadata, never from
  conditionals inside the shared package.
- Payload import-map entries point to local wrapper files. The wrappers import
  the shared package, keeping Payload's component resolution deterministic.

### 6.3 Visual contract

- The shell is always HelloAda: near-black background, warm cream text,
  coral action color, amber signal color, and the approved Ada mark.
- Customer identity is shown as `Managing <site name>` and in the live preview.
- The default screen is a calm two-window workspace: website preview and Ada.
- Primary owner language is plain: `Website`, `Ask Ada`, `Review`, `Library`,
  `History`, `Settings`.
- Provider, SHA, build-phase, and token vocabulary stays behind diagnostics.
- Technical details are collapsed by default.
- Motion communicates connection, progress, and completion. It never blocks
  reading and has a complete `prefers-reduced-motion` path.
- The UI must work at 1440×1000, 768×1024, and 390×844 without horizontal
  overflow or inaccessible controls.

### 6.4 Distribution and updates

Build an npm-compatible tarball from the `site-agent` release and attach it to
a public GitHub Release. Customer lockfiles pin an exact version and integrity
hash. Do not require a private package-registry token in customer builds.

The release manifest records:

```text
site_agent_version
workspace_api_version
payload_admin_version
template_schema_version
minimum_payload_version
minimum_node_version
artifact_url
artifact_sha256
```

New customers use the latest stable compatible manifest. Existing customers
receive an automated pull request containing only the package/config/template
upgrade and regenerated lockfile. CI must pass before deployment. This is the
meaning of a central codebase across independently owned Workers.

## 7. API and authentication architecture

### 7.1 Browser-to-site boundary

The browser talks only to the customer's same origin:

```text
Payload browser session
  -> /api/helloada/* on the customer Worker
  -> verify Payload user and site role
  -> attach server-only tenant credential
  -> site-agent /v1/workspace/*
```

The browser never receives a tenant bearer token.

### 7.2 Site-agent-to-Payload boundary

Content and media mutations flow in the opposite direction through the
existing narrow Payload gateway:

```text
site-agent application service
  -> configured Payload contract
  -> customer /api/workspace/*
  -> draft mutation
  -> explicit publish operation
```

The gateway exposes only configured collections, globals, media fields, and
editable-field operations. It is not a generic privileged Payload proxy.

### 7.3 Central control-plane boundary

HelloAda's account application uses:

```text
/v1/control-plane/websites/{website_id}/*
```

The control plane resolves account membership before selecting a tenant. The
customer workspace uses tenant-scoped `/v1/workspace/*` routes. Both call the
same application services and create identical operation provenance.

### 7.4 API compatibility rule

- Version the public service contract.
- Generate TypeScript request/response types from one checked-in OpenAPI
  artifact; do not maintain hand-written duplicate shapes indefinitely.
- Additive changes stay in `/v1`.
- Breaking changes require `/v2`, a dual-support window, and a fleet migration.
- Every request carries a correlation ID and resolves exactly one tenant.
- Cross-tenant lookup, replayed handoff assertions, and browser-supplied service
  credentials must fail closed.

## 8. Legacy FastAPI UI retirement

"Remove the FastAPI interface" means remove every product-facing UI served by
the Python service. It does **not** require replacing FastAPI as the internal
API framework.

### 8.1 Remove after parity is proven

- `src/site_agent/web/static/admin.html`;
- `src/site_agent/web/static/intake_lab.html`;
- admin-only static vendor assets;
- the `site-agent serve` command;
- the `site-agent intake-lab` browser command and production route;
- `Sessions`, `sa_session`, password login/logout/session routes;
- `SITE_AGENT_ADMIN_PASSWORD` and `env.admin_password`;
- `admin.theme`, `admin.host`, and `admin.port` configuration;
- `/api/theme` and all owner-UI-only projection endpoints after their required
  capability is available in `/v1/workspace` or Payload;
- old `/ada/` reverse-proxy and deployment instructions;
- tests whose only purpose is the removed HTML/password surface.

### 8.2 Extract before deleting

`src/site_agent/web/server.py` currently contains useful behavior mixed with
the old UI. For every route, classify it as one of:

1. **Move to an application service and `/v1/workspace`.** Chat, operations,
   recommendations, approvals, versions, history, analytics, SEO reports,
   social artifacts, media analysis, and design review capabilities.
2. **Replace with Payload native behavior.** Session/auth, collection editing,
   media CRUD, localization, account settings, and ordinary content forms.
3. **Keep as an internal preview capability.** Exact-revision preview and
   browser evidence, exposed only through authenticated workspace routes.
4. **Delete.** Theme endpoint, HTML root, password session, duplicated home
   projection, and UI-only helpers.

No route is copied wholesale into a second large server module. Business logic
must move into `application/`; the HTTP adapter remains thin.

### 8.3 Intake and design labs

The intake/design services, contracts, retained runs, and deterministic quality
tools remain. Their standalone HTML labs do not. Product intake lives in
HelloAda and Payload; test tooling should use API fixtures and Playwright
harnesses. If a comparison viewer remains useful for developers, move it to an
unshipped `devtools` extra with no production route or package data.

### 8.4 Retirement gate

Do not remove the old UI until all are true:

- Atelier Harmonie uses the shared Payload workspace in production;
- OceanicVibes uses the shared Payload workspace in production;
- a newly provisioned test tenant completes the same owner journey;
- every active legacy route has a parity test or an explicit deletion decision;
- production access logs show no owner traffic to `/ada/` for a defined
  observation window;
- rollback instructions for both migrated customers are tested.

## 9. Pelican removal

Pelican is not a compatibility mode in the target architecture. It must be
absent from active source, configuration, dependencies, tests, and generated
sites.

### 9.1 Remove runtime paths

- delete `src/site_agent/hands/pelican_blog.py`;
- delete `initialize_site()` and the Pelican portion of
  `src/site_agent/site_scaffold.py`;
- remove the `site-agent init-site` command;
- remove `PELICAN_BASELINE_PROFILE` and `pelican_baseline` inference;
- allow only `next_react` in config and design contracts;
- remove Pelican detection and branches from preview, design, journal, and
  approval code;
- remove Pelican-specific prompts from `opencode_runner.py`;
- remove `pelican` from `pyproject.toml`;
- retain `Markdown` only if non-Pelican runtime code still imports it;
- remove Pelican examples, deployment instructions, and package tests;
- replace OceanicVibes example configuration with its Payload target config.

### 9.2 Do not remove unrelated Git capabilities

The GitHub source adapter may remain because Ada still needs repository reads,
source commits, immutable SHAs, and rollback. Remove only static-site/Pelican
assumptions. Evaluate `cloudflare_pages` separately after all sites deploy as
OpenNext Workers; delete it only when no supported workflow uses it.

### 9.3 Historical records

Old design-run rows may contain `pelican_baseline`. Keep them readable as
historical evidence through a data-version decoder if required, but never make
them executable. New runs must reject the profile. Once retention expires or
records are exported, remove the decoder.

## 10. Canonical customer template

Upgrade `src/site_agent/templates/next-payload` into a complete, bootable
customer application containing:

- Next.js App Router;
- Payload admin/API;
- D1 adapter and migrations;
- R2 media storage;
- Users, Media, and baseline Pages collections;
- editable-field registry and typed primitives;
- local wrappers for the shared HelloAda admin package;
- same-origin `/api/helloada/*` bridge;
- service-authenticated `/api/workspace/*` content gateway;
- draft preview and revision support;
- OpenNext/Wrangler configuration;
- `noindex` behavior before launch;
- typecheck, lint, test, build, OpenNext build, and smoke scripts;
- a template schema marker consumed by the release/upgrade system.

The template contains no customer design beyond a safe bootstrap shell. Ada
creates the customer-facing design from confirmed intake. The shared HelloAda
admin is product code and is not regenerated by Ada.

## 11. Customer migration: Atelier Harmonie

Atelier is the first migration because it already proves the target runtime.

### 11.1 Preserve

- current public routes and frontend design;
- all Payload collections and globals;
- D1 data and Payload migrations;
- R2 objects and media relationships;
- Payload users and access controls;
- localization behavior;
- existing drafts, versions, and publication state;
- customer-specific commerce/product behavior;
- production Worker and domain.

### 11.2 Extract and replace

Use these components as behavior references, not permanent duplicated source:

- `src/components/admin/WebsiteWorkspace.tsx`;
- `src/components/admin/WebsiteWorkspaceServer.tsx`;
- `src/components/admin/StudioNav.tsx`;
- chat/history/editor helpers under `src/components/admin/`;
- `src/app/(payload)/custom.scss`;
- Payload `admin.components` entries in `src/payload.config.ts`.

Steps:

1. Write characterization tests for Atelier's current workspace behavior.
2. Extract customer-neutral behavior into the shared package.
3. Replace `/api/atelier/*` assumptions with configured `/api/helloada/*`
   wrappers; keep temporary aliases if production clients require them.
4. Replace WeAreHeadless graphics/colors with the HelloAda visual contract.
5. Keep `Atelier Harmonie` only as workspace context.
6. Point Payload `Nav`, dashboard, Icon, and Logo wrappers at the shared
   package.
7. Prove there is no Payload schema change before using an app-only deploy.
8. Build and inspect authenticated `/admin` locally and on a version-preview
   deployment.
9. Deploy the existing Worker only after explicit approval.
10. Remove temporary aliases after logs show no use.

### 11.3 Atelier acceptance

- Login and logout work.
- Review/live preview works at desktop, tablet, and mobile sizes.
- Ada conversation resumes across refreshes.
- Intake and workspace phases display correctly.
- Recommendations, approval, publication, and history work.
- Page and image editing create drafts, not silent production mutations.
- Locale switching works.
- D1 row counts and representative records are unchanged by an admin-only
  release.
- R2 media loads and no object is rewritten.
- Unauthenticated content/Ada routes return `401`.
- Browser console, network, hydration, and accessibility checks pass.

## 12. Customer migration: OceanicVibes

OceanicVibes is a data and runtime migration, not an in-place Pelican cleanup.

### 12.1 Inventory before writing

Record from the deployed and source site:

- every public URL and status code;
- page titles, descriptions, canonical tags, structured data, sitemap, robots,
  feeds, redirects, and language alternates;
- every article's slug, date, author, category, tags, summary, Markdown/body,
  and media references;
- forms, analytics, Search Console, CrawlSEO, and domain behavior;
- image files, dimensions, alt text, origin, and content hash;
- current Git SHA, deployment ID, DNS state, and rollback target.

Do not infer missing business facts during migration.

### 12.2 Build the Payload target

1. Create an isolated migration branch or owner-approved target repository from
   the canonical template.
2. Define OceanicVibes collections/globals with migrations.
3. Add the shared HelloAda admin package and OceanicVibes site configuration.
4. Implement the public Next.js frontend from the approved current design or a
   separately approved redesign; migration alone is not redesign approval.
5. Provision a target D1 database and R2 bucket in a non-production namespace.
6. Register the tenant with `site-agent` and configure the narrow Payload
   contract.

### 12.3 Write an idempotent importer

The importer must:

- parse Pelican frontmatter and Markdown without using the Pelican runtime;
- map stable source IDs to Payload documents;
- preserve slug, publication date, title, summary, category, tags, and body;
- upload media by content hash and preserve alt text;
- rewrite internal media/document links deterministically;
- support `--dry-run` and produce a bounded reconciliation report;
- be safe to rerun without duplicate documents or media;
- never publish drafts merely because they were imported;
- produce source count, target count, skipped item, and mismatch evidence.

### 12.4 URL and SEO compatibility

- Preserve existing URLs where possible.
- Add explicit permanent redirects for every changed Pelican URL.
- Preserve canonical host and trailing-slash behavior.
- Generate a sitemap and robots policy from the Payload/Next site.
- Preserve feeds only if they are currently consumed; otherwise redirect or
  retire them deliberately.
- Compare rendered titles, descriptions, canonicals, structured data, and
  status codes before cutover.

### 12.5 Cutover

1. Freeze legacy content writes for a short declared window.
2. Run final importer and reconciliation.
3. Build the exact reviewed commit.
4. Run authenticated Payload/admin and public-site smoke tests.
5. Deploy to a version-preview URL and crawl it.
6. Obtain explicit production approval.
7. Attach production traffic/domain to the new Worker.
8. Verify critical URLs, admin login, D1, R2, forms, analytics, and SEO.
9. Keep the previous deployment and source commit as rollback targets.
10. Remove Pelican service/build configuration only after the observation
    window passes.

### 12.6 OceanicVibes acceptance

- All legacy content is represented in Payload or explicitly rejected with a
  documented reason.
- Re-running the importer creates no duplicates.
- Critical public URLs return the expected status and content.
- Redirect coverage is complete.
- Media resolves from R2 with correct alt text.
- `/admin` uses the shared HelloAda workspace.
- Ada can read and prepare drafts through the configured Payload contract.
- Production remains reversible to the recorded pre-cutover deployment.

## 13. New-customer path

After both reference migrations:

```text
create website
  -> bootstrap canonical template
  -> GitHub repository
  -> Cloudflare Worker + D1 + R2
  -> Payload migrations
  -> owner identity/handoff
  -> site-agent tenant registration
  -> HelloAda admin available
  -> confirmed intake
  -> Ada-created public design
  -> deterministic/browser validation
  -> owner review
  -> explicit production approval
```

No new customer may be scaffolded as Pelican, a static GitHub Pages site, or a
legacy FastAPI-admin instance.

## 14. Implementation phases

### Phase 0 — Freeze and inventory

- Mark legacy UI and Pelican paths deprecated; block new tenant creation on
  them.
- Record active tenants, runtime versions, repositories, Workers, D1/R2
  bindings, domains, and current interface paths.
- Build a route/capability parity matrix from `web/server.py` to Payload or
  `/v1/workspace`.
- Capture Atelier and OceanicVibes baselines.
- Add architecture decision records for package distribution and API versioning.

**Exit:** every active capability and tenant has a named target; no new legacy
tenant can be created.

### Phase 1 — Contract and release spine

- Define/generate the workspace OpenAPI contract.
- Add the release-manifest schema.
- Add template/admin/backend compatibility validation.
- Add a fleet inventory command that reports versions without changing sites.
- Add failing tenant-isolation, auth, and compatibility tests.

**Exit:** one machine-readable contract and compatibility matrix exist.

### Phase 2 — Shared HelloAda Payload package

- Characterize Atelier's current component behavior.
- Create the package, config contract, styles, brand assets, API client, and
  component tests.
- Build thin Payload import-map wrappers in the template fixture.
- Package a local tarball and consume it from a clean fixture app.
- Run responsive and reduced-motion browser tests.

**Exit:** a clean Payload fixture uses the packaged UI with no copied customer
workspace source.

### Phase 3 — Complete canonical template and API parity

- Complete the Next/Payload template and same-origin bridge.
- Move required legacy route behavior into application services and
  `/v1/workspace`.
- Replace browser password auth with Payload session authorization.
- Prove HelloAda control-plane and Payload workspace interface parity for
  design change and version restore.

**Exit:** a newly bootstrapped test tenant completes intake, preview, draft,
approval, publish, and history entirely through Payload.

### Phase 4 — Migrate Atelier Harmonie

- Install the package and typed configuration.
- Replace hard-coded admin components with wrappers.
- Verify local, version-preview, then production according to Atelier's own
  contributor/deployment guide.

**Exit:** Atelier production uses the shared package and unchanged customer
data.

### Phase 5 — Migrate OceanicVibes

- Build schema, importer, public Next frontend, and preview deployment.
- Reconcile content/media/URLs.
- Perform approved cutover and observe.

**Exit:** OceanicVibes production uses Payload/D1/R2 and the shared HelloAda
workspace; Pelican is no longer part of its runtime.

### Phase 6 — Retire legacy UIs

- Remove static admin/intake HTML and UI-only vendor assets.
- Remove `serve`, browser `intake-lab`, password sessions, themes, `/ada/`
  deployment wiring, and obsolete tests/docs.
- Keep API-only preview/build utilities behind authenticated workspace routes.

**Exit:** the Python service exposes no product-facing HTML UI.

### Phase 7 — Remove Pelican and static-runtime compatibility

- Remove Pelican dependencies, profiles, scaffold, branches, prompts, tests,
  examples, and documentation.
- Make `next_react` the only accepted build profile.
- Remove executable fallback for historical Pelican runs.

**Exit:** `rg -i pelican src tests pyproject.toml README.md examples` returns no
active runtime or test references; the full suite passes without Pelican
installed.

### Phase 8 — Fleet rollout automation

- Publish a signed stable release.
- Generate upgrade PRs for compatible customer sites.
- Run each customer's CI and version-preview checks.
- Deploy only through each customer's explicit gate.
- Add drift reporting for out-of-date admin/template/API versions.

**Exit:** new tenants use the release automatically and existing tenants have a
safe, observable upgrade path.

### Phase 9 — Final cleanup

- Archive superseded operational documents or mark them historical.
- Update `AGENTS.md`, README, architecture, deployment, and onboarding docs.
- Remove compatibility aliases after their observation windows.
- Confirm no production service, proxy, scheduler, or runbook references the
  removed commands/routes.

## 15. Test strategy

### 15.1 Python control plane

- tenant selection and isolation;
- service-token authorization;
- Payload contract allowlists;
- intake/chat/operation durability;
- recommendation and approval provenance;
- preview/revision ownership;
- API contract conformance;
- legacy config rejection;
- `next_react` as the only new-run profile;
- bootstrap idempotency;
- customer upgrade manifest validation.

### 15.2 Shared admin package

- TypeScript strict typecheck;
- lint and package build;
- component tests for loading, empty, error, offline, and permission states;
- API client contract tests generated from OpenAPI;
- keyboard and screen-reader navigation;
- responsive layouts;
- reduced motion;
- no customer-specific strings or API paths in package output;
- tarball-consumer smoke test from outside the package workspace.

### 15.3 Canonical template

- clean bootstrap from an empty directory;
- Payload import-map generation;
- local D1 migration;
- R2 adapter initialization;
- authenticated admin render;
- unauthenticated route rejection;
- same-origin bridge strips browser-supplied authorization and attaches only
  the server-owned tenant credential;
- public build, OpenNext build, and Worker smoke test;
- content draft, preview, publish, and rollback.

### 15.4 Migration tests

- Atelier characterization tests pass before and after package extraction;
- OceanicVibes importer fixture preserves metadata and is idempotent;
- URL/redirect manifest is exhaustive;
- source/target counts and content hashes reconcile;
- no D1/R2 mutation occurs in dry-run mode.

### 15.5 Browser release gate

For Atelier, OceanicVibes, and one newly bootstrapped tenant:

1. Sign in to the real Payload `/admin`.
2. Verify the HelloAda logo and shell.
3. Verify customer identity is context, not shell branding.
4. Exercise preview selection at desktop, tablet, and mobile.
5. Send a message to Ada and resume it after reload.
6. Review and approve a safe fixture draft in non-production.
7. Inspect history and rollback controls.
8. Edit text and image fields through Payload draft behavior.
9. Verify Library/media behavior.
10. Verify diagnostics remain collapsed by default.
11. Check console errors, failed requests, hydration, focus order, contrast,
    reduced motion, and horizontal overflow.

## 16. CI and verification commands

The coding AI must introduce exact scripts as the package is added. The final
release gate includes at least:

```bash
# Python
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel

# Shared package
npm --prefix packages/helloada-payload-admin run typecheck
npm --prefix packages/helloada-payload-admin run lint
npm --prefix packages/helloada-payload-admin test
npm --prefix packages/helloada-payload-admin run build
npm --prefix packages/helloada-payload-admin pack -- --pack-destination /tmp

# Canonical clean consumer fixture
npm ci
npm run typecheck
npm run lint
npm test
npm run build
npx opennextjs-cloudflare build
```

Inspect generated wheel contents and npm tarball contents. Required files must
be present; source maps, secrets, caches, local databases, and unrelated build
output must be absent.

## 17. Rollout and rollback rules

- A package release is not a customer deployment.
- A Git push is not a Cloudflare deployment.
- A successful Worker upload is not proof that `/admin` works.
- Database migrations are forward-only and backed up before production.
- Admin-only releases must not run customer schema migrations.
- Every customer rollout records source commit, package version, Worker version,
  D1 migration state, and smoke-test result.
- Roll back application code to the previous Worker version when no schema
  change occurred.
- When a schema changed, use its documented compatible rollback or restore
  procedure; never point old code at an incompatible database silently.
- Never delete the previous OceanicVibes deployment or source until the
  observation window closes.
- A failed tenant upgrade must not block or roll back other tenants.

## 18. Observability

Add a safe version/status endpoint per customer that returns no secrets:

```json
{
  "tenant": "atelier-harmonie",
  "templateSchema": 2,
  "payloadAdmin": "1.0.0",
  "workspaceApi": "v1",
  "siteAgent": "0.2.0",
  "compatible": true
}
```

The fleet inventory reports:

- current/target versions;
- compatibility state;
- last successful admin smoke test;
- last deployment ID and time;
- migration required: yes/no;
- drift reason.

It must not report tokens, user data, content, environment values, or protected
credential paths.

## 19. Coding-AI execution rules

Before each phase:

1. Read `AGENTS.md` and this complete plan.
2. State the first broken boundary in the real request path.
3. Inspect the current checkout, branch, remote, and dirty state.
4. Identify the active customer and deployment guide before touching a tenant.
5. Start with a failing focused test or reproducible request.
6. List the compatibility or deletion gate for the phase.

During implementation:

- extract proven behavior before redesigning it;
- keep business logic in application services;
- use one API client and generated contract types;
- preserve customer data and public-site identity;
- make migrations idempotent and observable;
- make every mutation tenant-scoped and owner-gated;
- stage only intended files;
- never copy credentials into source, tests, logs, prompts, or screenshots;
- never use a manual customer-site repair as evidence that Ada's pipeline works;
- never claim an interface is migrated from source inspection alone.

Do not:

- continue improving `admin.html` or `intake_lab.html`;
- add another dashboard framework beside Payload;
- add a second CMS or content registry;
- leave a silent Pelican fallback;
- hard-code Atelier, OceanicVibes, or `/api/atelier` into shared package code;
- bundle a tenant token into client JavaScript;
- run a remote D1 migration for a CSS/component-only change;
- deploy one customer's build artifact to another customer's Worker;
- report a package publish as a completed fleet rollout.

After each phase, report:

- files and contracts changed;
- tests and builds run;
- generated artifacts inspected;
- customer data/deployments intentionally untouched;
- remaining compatibility paths;
- whether the phase exit criteria actually passed.

## 20. Definition of done

This consolidation is complete only when all are true:

- Atelier Harmonie runs Next.js + Payload + D1 + R2 with the shared HelloAda
  admin package.
- OceanicVibes runs Next.js + Payload + D1 + R2 with the shared HelloAda admin
  package and reconciled legacy content/URLs.
- A brand-new customer is provisioned from the canonical template and reaches
  the same admin without copied customer-specific workspace code.
- `site-agent` is the single source for control-plane code, API contracts,
  shared admin, templates, importers, and release manifests.
- The Python production service exposes APIs, not a human admin UI.
- `site-agent serve`, browser `intake-lab`, password sessions, `admin.html`,
  `intake_lab.html`, `/ada/`, and admin-theme configuration are gone.
- Pelican dependencies, profiles, scaffolds, prompts, tests, examples, and
  production services are gone.
- `next_react` is the only supported new-site build profile.
- Payload is the only CMS and owner administration interface.
- Customer content remains isolated, exportable, and recoverable.
- Package/API/template drift is visible and upgrades are repeatable.
- Owner approval remains the only production mutation boundary.
- Real authenticated browser checks pass on both migrated customers and a new
  tenant.

Until every condition passes, describe the platform as **in migration**, not
consolidated.
