# Architecture

The current supported shape of site-agent. `AGENTS.md` holds the working rules;
this document explains how the pieces fit. Historical plans are in
`docs/archive/` and are not operational guidance.

## What the product is

One reusable platform package, consumed by every website, with a per-site
repository for design and content. Payload is the owner's admin interface and,
for sites that need one, the CMS.

```text
owner
  -> helloada.app            authenticated multi-project selector, owner handoff
  -> site-agent API          provisioning, management, measurement, releases
  -> tenant Worker           Next app + Payload admin + Mailflare, one per site
  -> Cloudflare              D1, R2, queues, Worker version at 100% traffic
```

## The two halves

**Platform (shared, versioned, never forked).** `src/site_agent/templates/next-payload`
plus the files declared in `deploy/shared-runtime-overlay.json`, plus the pinned
packages `@weareheadless/helloada-payload-core`, `helloada-payload-admin` and
`helloada-mailflare`. The overlay owns the Worker, API routes, auth, handoff,
preview, forms, SEO metadata, GA4 wiring and Payload plumbing. A runtime change
is one central change fanned out by fingerprint, not N tenant edits.

**Site (per tenant).** Design and content: `site.css`/design tokens,
`helloada.config.ts`, the presentation itself, assets, and either CMS documents
or committed content. Two tenants should differ only here.

Anything a second site would copy verbatim belongs in the platform half. The
overlay currently does not yet cover `layout.tsx`, `SiteChrome.tsx` and
`request-locale.ts`, which is why those files are duplicated across tenants;
moving them is the remaining consolidation work.

## Presentation

Two supported modes, same Worker, same build, same release path:

- **Committed source (import profile).** `public/` is imported byte-for-byte and
  served by `HELLOADA_PRESENTATION_PROFILE=static`. Used to adopt an existing
  site without rewriting it, and for designs authored as static markup plus
  assets. See `docs/github-website-provisioning.md`.
- **Next components on the platform.** Page routes render from committed
  components. This is the default for a new authored design.

A tenant declares `managedPaths` in `src/helloada.config.ts` for the route bases
that Payload should serve. Everything outside those bases comes from the
tenant's own presentation. There is no per-tenant Payload page schema.

## Payload

Always: owner authentication, admin UI, media, and the workspace API.

When the site needs a CMS: articles and blog posts, products, listings and their
relations, read through the canonical gateway (`/api/workspace`) by the managed
routes. Presentation pages are not Payload documents, and presentation copy is
not mirrored into Payload.

Schema, migrations, admin and package pins are platform-owned. A tenant never
edits them, and no tenant carries a local copy of a shared collection
definition.

## Release

One path: commit to the tenant repository, then queue the exact full SHA in
`deploy/desired-releases.json`. The VPS runner clones that SHA, overlays the
pinned runtime, builds with the pinned Node/npm, uploads one Worker version,
promotes it to 100% traffic, runs the live and authenticated gates, and writes a
secret-free receipt. No direct `wrangler deploy`, no hand restart, no manual
Cloudflare edit. See `deploy/README.md` and `docs/platform-release-runbook.md`.

Production changes only by explicit owner approval.

## Ada

Ada is the management interface: provisioning, measurement (GA4, Search
Console, CrawlSEO), domain email, releases, research, monitoring and reporting.
She does not author the site's design. See
`docs/manual-intake-and-ada-as-management-interface.md`.

## Internal code shape

- `main._build_runtime()` is the composition root: config, `Memory`, LLM client,
  scheduler, then the FastAPI app.
- Dependency direction: `web` transport -> `application` workflow ->
  `core` contracts -> `hands`/`senses`. `brain` policy follows the same path.
  Core modules never import a concrete adapter to resolve a secret.
- `application/` owns workflows callable from HTTP, schedulers or adapters.
  Route handlers translate HTTP and sessions only.
- `core/contracts.py` holds provider-neutral owner actions, artifacts,
  approval requests and receipts. Approvals bind to an artifact hash.
- `web/preview.py` owns staged builds and preview URL rewriting; previews live
  under the deployment mount point (`/ada/`).
- Extension direction: `HTTP/MCP adapter -> application service -> typed
  contract -> adapter/provider`. No universal plugin base class.

## Reading order

1. `AGENTS.md` — rules and invariants.
2. `docs/manual-intake-and-ada-as-management-interface.md` — who does what.
3. `docs/github-website-provisioning.md` — the import/adoption profile.
4. `deploy/README.md` — the release queue and its gates.
5. `docs/mailflare-single-worker-contract.md`, `docs/seo-provisioning-and-domain-lifecycle.md`
   — mail and measurement lifecycles.
