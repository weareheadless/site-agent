# Manual intake and Ada as the management interface

**Status:** active product direction, 2026-11-05
**Supersedes:** the intake-and-generation owner journey in
`docs/helloada-project-selector-to-payload-intake-contract.md` (steps 4–5) and
the "Ada Designs the Site" mission lock in `AGENTS.md`, where they conflict.
**Does not change:** the tenant, release-queue, credential, Payload-admin and
approval contracts.

## What changed

Intake is no longer a product surface. The owner briefs Ada directly and Ada
provisions. Ada is the management interface for a site's lifecycle — account,
workspace, infrastructure, measurement, releases — not the tool that designs it.

The design is authored by the owner together with the coding agent in the
site-agent shell, as code in the tenant repository, and promoted through the
same canonical release queue as every other change.

Two consequences follow immediately:

- There is no owner-facing intake conversation, no intake session, no confirmed
  intake record, and no design run that consumes one. A site does not need an
  intake artifact to be provisioned or released.
- A candidate site is not evidence of a working pipeline, because no pipeline
  produces it. The authored design is the artifact; review happens on the real
  built page.

## Headless presentation, Payload for collections

This part is already built, not proposed. It is the static presentation profile:

- Presentation is committed source in the tenant repository, imported
  byte-for-byte into the platform (the `public/` convention, the
  `helloada-frontend.json` declaration, and the static manifest shipped as
  Worker assets). `HELLOADA_PRESENTATION_PROFILE=static` selects the handler;
  `docs/github-website-provisioning.md` is the contract.
- Payload serves only the route bases the tenant declares as managed
  (`managedPaths`, `src/lib/static-website.ts`). Blog, shop, listings and any
  other collection-shaped route live there; everything outside those bases is
  served from the committed presentation. There is no per-tenant Payload page
  schema for the presentation.
- The standard is the platform, not the presentation framework: the same
  `next-payload` template, runtime overlay, package pins, one release queue and
  one verifier. Presentation is preserved exactly as committed, with no
  framework detection, conversion or second build.

Every tenant is a Next/Payload app; what differs is where a page's HTML comes
from. Astrid serves a committed static presentation with no managed bases.
Casamigo serves a committed static presentation and declares `/collections` and
`/es/collections` as Payload-managed, which Next renders from CMS documents.
OceanicVibes and Atelier predate the profile and still render their pages from
Payload documents. All four build, deploy and verify through the same Next/
OpenNext pipeline.

So the split is: committed source owns pages, Payload owns collections. A
presentation page that needs a CMS-driven section is a deliberate tenant
decision expressed through `managedPaths`, not a default binding.

## One reusable package

The goal is one product package every website consumes: Payload as the admin
interface, plus the CMS for the sites that need one, and a standard frontend so
every tenant behaves the same way and has the same capabilities.

That is the consolidation contract in
`docs/archive/site-agent-payload-platform-consolidation-implementation-plan.md`
("site-agent is the central product code consumed by every customer website").
It is half done. The platform half is genuinely one package: the shared runtime
overlay (`deploy/shared-runtime-overlay.json`) plus the pinned
`@weareheadless/helloada-payload-core`, admin and mailflare packages.

The presentation half is still forked. `src/app/(frontend)/layout.tsx`,
`src/components/SiteChrome.tsx` and `src/lib/request-locale.ts` are byte-identical
between casamigo and astrid, and none of them is in the overlay, so every tenant
carries its own copy and they drift independently. That duplication is the bug
surface this goal is meant to remove.

The target split: the package owns layout, chrome, routing, locale, forms, SEO
metadata, GA4 wiring and preview. A tenant owns `site.css`/design tokens,
`helloada.config.ts`, its content (CMS documents where it has a CMS, committed
content where it does not) and its assets. A new site then differs from another
only in design and content, not in platform code.

What this removes from Ada: page authoring, section-composition planning,
content-document creation, preview-candidate generation and the repair loops
around them. What remains is provisioning, measurement, release and reporting.

## Division of responsibility

| Concern | Owner + coding agent | Ada |
| --- | --- | --- |
| Brief, positioning, courses, pricing, copy | decide | records what was decided |
| Design and frontend code | author in the tenant repo | not involved |
| HelloAda account / tenant registration | request | performs and reports |
| Workspace bootstrap, schema init, D1/R2/queues | — | performs through the queue |
| GA4, Search Console, CrawlSEO, domain email | supplies inputs | provisions and verifies |
| Cloudflare resources, Worker versions, promotion | — | performs through the release runner |
| Production approval | explicit approval | executes only after it |

Ada may still research, monitor, propose and report — that is the management
side of the interface. She does not silently take over authorship of the site.

## How an owner turn works

One opencode session answers the owner and owns its worktree. It reads the
site, changes content through the workspace tools, and changes presentation in
the repository; when the turn ends the host validates the exact working tree,
commits it to the preview branch and stages the review draft. Publication is
still the owner's approval.

The content-binding gate that the compiled preview applies also runs inside the
turn, before anything is staged, so a candidate whose visible copy is not bound
to Payload is repaired by the same agent that wrote it. If one bounded repair
does not clear the violations, the turn fails and names them instead of handing
the owner an unreviewable draft.

A preview is only called ready once every page the candidate saved actually
renders in it: the service requests each authored page and fails the candidate
on a non-success response, so a page that compiles but throws while rendering
is reported as a failure rather than shown to the owner as ready.

There is no second agent, no build tool and no channel between processes: the
agent that talks to the owner is the agent that does the work. The legacy
in-process chat engine keeps its own build tool until it is retired; it runs
inside the API, where the deployment services live.

## Still binding

- One tenant, one repository, one Worker; no second CMS, admin, credential path
  or deployment target.
- Every site builds from `src/site_agent/templates/next-payload` plus the shared
  runtime overlay and pinned packages. No framework substitution, no second
  build. Authored presentation ships as committed source through the static
  presentation profile; it is not converted, detected or regenerated.
- Provisioning and promotion go through the canonical VPS release queue with an
  exact full SHA and a secret-free receipt. No direct `wrangler deploy`, no
  hand restart, no manual Cloudflare edit.
- Production changes only by explicit owner approval. A pushed commit, a
  passing build or a live health response is not an approval.
- Payload admin remains the owner's content surface for collections and owner
  authentication entry point; HelloAda remains the project selector and
  handoff.
- Credentials are resolved through `/SOCIAL/configs/host-credentials.yaml` and
  never printed, committed or passed to a model prompt.
- Readiness must distinguish workspace, public website, Google verification and
  CrawlSEO state. A health check is not a verified website.

## Open decisions

1. **Fate of the existing pipeline.** Intake Lab (`web/intake_lab.py`,
   `static/intake_lab.html`), the design-run states and the Design-tab review
   surface are still wired in. Decide retire, freeze for existing tenants, or
   delete, and whether existing generated tenants keep their current review
   flow.
2. **Approval surface.** With no candidate, where does the owner approve a
   built design: the Design tab previewing the queued build, or an explicit
   approval attached to the release receipt.
3. **Migration of existing Payload-page tenants.** Sites whose pages are still
   Payload documents (oceanicvibes, atelier) either stay on the bound model
   until separately migrated, or move to committed presentation plus managed
   bases. Decide per tenant; do not half-bind.

## Already decided

- #603 / #604: provision an explicit GitHub website instead of intake; bounded
  `public/` convention, official `main`, preserved frontend, canonical
  Payload/admin in the same Worker, existing queue and SEO lifecycle, no
  domain cutover.
- #607 / #608: static asset routing derived during the runtime overlay, and
  static workspace preview routing.
- `12b8ed5a`: tenants declare `managedPaths`; Payload owns those bases and the
  committed presentation owns the rest.
- Authored designs ship as Next components on the shared package. The static
  import profile is the adoption path for an existing site whose frontend
  already exists (astrid, casamigo), not the default for a new design.
- Casamigo shows the mixed case in production: committed static presentation
  plus Next-rendered `/collections`, declared through `managedPaths`.
- Astrid (`weareheadless/astrid-rincon-website`) is the static-import
  acceptance case.

## Retired claims

The following statements are no longer true and must not be used to justify
work: that Ada must generate the candidate; that a manual implementation
invalidates a run; that a site cannot be provisioned without an intake; that
presentation pages must be Payload documents; that the approximately 20-minute
generation promise applies to authored designs.
