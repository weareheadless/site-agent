# Next/React + Payload Correction Plan

Status: proposed architecture correction

## Decision

Make **Next.js + React + Payload** the one canonical architecture for Ada-built
sites and for Workspace.

Astro is not a product requirement. It was selected as an implementation
choice, but it creates a second frontend/runtime path without adding design or
GSAP capabilities that React/Next cannot provide.

The final target is:

```text
Next.js + React public site
        + Payload admin/API
        + D1 database
        + R2 media
        + Ada field/design gateway
```

One site, one application runtime, one build profile, one preview path, and one
content contract.

## Goals

1. Make Workspace a correct reference implementation rather than a Next-specific
   exception.
2. Make a new site created by Ada from zero use the same Next/React/Payload
   architecture.
3. Preserve all GSAP capabilities:
   - core tweens and timelines;
   - ScrollTrigger and approved plugins;
   - `@gsap/react` and `useGSAP`;
   - scoped selectors and refs;
   - cleanup and reduced-motion behavior;
   - measured browser validation at desktop, tablet, and mobile sizes.
4. Keep Payload content management, draft values, media, authentication, and
   preview behavior in one coherent runtime.
5. Keep the implementation small enough to understand and operate without
   framework-specific fallback paths.

## Non-goals

- Do not migrate Workspace to Astro.
- Do not support Astro and Next as equal canonical targets in this correction.
- Do not introduce a second CMS, content store, or field registry.
- Do not add runtime source scanning, DOM matching, text matching, or image-URL
  discovery.
- Do not add a generic framework-detection layer.
- Do not rewrite Payload data, D1, R2, or existing content unnecessarily.
- Do not deploy or mutate production as part of the architecture correction.

## Architectural boundary

### Next/React application

Each Ada-built site is a normal Next.js application containing:

- the public React frontend;
- Payload admin through `@payloadcms/next`;
- Payload REST/GraphQL and site-specific route handlers;
- authenticated draft preview;
- the configured D1 and R2 bindings;
- the declarative editable-field registry;
- the site-specific design and content components.

This is intentionally a single deployable application for the first canonical
architecture. It keeps the existing Workspace operational model intact.

### Ada/site-agent

The site-agent remains framework-aware through one explicit
`next_react` build profile. It owns:

- intake and confirmed customer context;
- design planning and experience contracts;
- repository/build orchestration;
- dependency and capability approval;
- deterministic checks;
- browser and motion evidence;
- draft/preview/owner-approval lifecycle.

It does not own customer-specific Payload schemas or hard-coded field IDs.

### Payload contract

The portable contract remains configuration-driven:

- collections and globals are declared per site configuration;
- media fields are declared per site configuration;
- the gateway exposes only the configured contract;
- editable fields are explicit Payload rows with stable dotted IDs;
- content mutation is draft-first and owner-approved.

The current generic implementation remains the basis:

- `src/site_agent/hands/payload_gateway.py`;
- `src/site_agent/hands/payload_fields.py`;
- `PayloadGatewayClient`;
- `PayloadContract`;
- `EditableFieldGatewayMixin`.

## Editable-content contract

The existing Workspace decision remains canonical:

```text
Ada defines a field
        ↓
Payload stores its value and type
        ↓
React renders it through a typed primitive
        ↓
authenticated preview emits the field marker
        ↓
Ada/owner edits the draft by stable field ID
```

Rules:

- `define` registers a field; it does not scan source code.
- The React frontend binds the stable key explicitly.
- There is no separate dynamic `bind` operation for the current architecture.
- `EditableText`, `EditableRichText`, and `EditableImage` remain the only
  ordinary content primitives.
- Preview metadata is emitted by primitives only in authenticated preview.
- Public rendering contains no editor controls or privileged metadata.
- Unknown IDs, duplicate IDs, invalid types, and missing media fail validation.

The existing Workspace field registry, migration, APIs, and `home.ada.test.*`
proof section are retained as the reference implementation. The current
Next-specific component code may later be extracted into a small shared React
package only if a second site actually requires it; do not create that package
speculatively.

## GSAP capability contract

GSAP is a first-class approved capability in the Next profile.

The canonical scaffold pins:

- `gsap`;
- `@gsap/react`.

Ada receives the existing GSAP skills for:

- core API;
- timelines;
- ScrollTrigger;
- plugins;
- performance;
- React lifecycle and cleanup.

Every generated GSAP implementation must follow these rules:

1. Put browser animation in a React client component with `'use client'`.
2. Use `useGSAP()` with a scoped ref when `@gsap/react` is available.
3. Use refs or scoped selectors; never rely on unscoped global selectors.
4. Keep critical copy, navigation, controls, and conversion content visible in
   the server-rendered state.
5. Revert/clean up every animation, trigger, listener, and plugin instance.
6. Provide a reduced-motion path that immediately presents the complete readable
   state.
7. Exercise the behavior at desktop, tablet, mobile, and reduced-motion sizes.
8. Treat missing observable motion, hydration errors, failed modules, and
   console errors as failures.

GSAP is not allowed in server components, Payload configuration, migrations, or
editable-field helpers.

## Build-profile correction

Replace the current native Astro assumptions with one explicit profile:

```text
profile: next_react
source: Next.js + React + Payload
check: site-owned typecheck/lint command
build: site-owned Next/OpenNext build command
preview: site-owned Next/OpenNext preview command
```

The profile must be explicit and required. If a site is not configured as
`next_react`, the design run fails configuration validation. It must not silently
fall back to Astro, Pelican, or another build profile.

The profile-specific parts belong in the build/preview adapter:

- scaffold files;
- package manifest and approved versions;
- source entrypoint expectations;
- build and check commands;
- output/runtime handling;
- browser preview startup;
- allowed source paths;
- framework-specific native-source validation.

The design contracts, intake contracts, Payload gateway, field operations,
GSAP quality rules, owner review, and production approval remain framework
neutral.

## Ada authoring flow

The final flow is:

```text
confirmed intake
  → typed Next/React design request
  → Ada creates the Next/React/Payload source
  → Ada declares editable fields
  → site-owned check/build
  → authenticated Design-tab preview
  → browser, accessibility, motion, and journey evidence
  → owner review
  → explicit approval
```

Ada must create the candidate from the confirmed intake. A manual source build
or manually polished candidate is not evidence that the pipeline works.

For a new site, Ada must create at least one proof section containing:

- a text field;
- a rich-text field;
- an image field;
- a link/action field;
- one intentional GSAP behavior;
- a reduced-motion path.

The candidate is incomplete until those fields are declared, rendered, editable
in authenticated preview, and validated through the owner-facing review path.

## Workspace treatment

Workspace stays on its current Next.js foundation.

Preserve:

- `src/app/(payload)` and the Payload admin;
- D1/R2 configuration and migrations;
- current public routes and SEO behavior;
- authentication and draft preview;
- forms and store/cart behavior;
- generic Payload gateway integration;
- declarative editable-field schema and APIs;
- current dirty work and owner review boundaries.

The Workspace changes are limited to:

1. Pin `gsap` and `@gsap/react` in the site package manifest.
2. Add the Next/React build profile and approved dependency contract.
3. Make Ada's writable/build/preview paths explicit for this Next site.
4. Keep the existing editable-field implementation and complete its
   authenticated smoke test.
5. Add one owner-approved GSAP proof interaction only after the pipeline can
   build and preview Next correctly.

No Astro frontend migration is part of Workspace completion.

## Intake and design correction order

Do not use the unfinished Intake/Design flow to validate an unfinished
frontend/runtime split. Correct the boundaries in this order:

### Phase 1 — Freeze the current baseline

- Record the current Workspace Next/Payload behavior.
- Keep the existing POC changes uncommitted unless separately approved.
- Do not deploy or run remote migrations.
- Preserve the current Workspace intake configuration while the runtime target is
  corrected.

### Phase 2 — Implement the canonical Next profile

- Add the `next_react` site-build profile.
- Remove Astro assumptions from the canonical design path.
- Make check, build, preview, and source validation profile-specific.
- Make absent or invalid profile configuration fail clearly.
- Add a clean Next/React/Payload scaffold for new sites.

### Phase 3 — Prove the runtime with Workspace

- Build the current Workspace repository with the Next profile.
- Verify public rendering, admin, API auth, preview auth, media, and forms.
- Verify editable text, rich text, and images through the field registry.
- Verify the `home.ada.test.*` section in authenticated preview.
- Add and validate one GSAP client component with cleanup and reduced motion.

### Phase 4 — Repair Intake/Design

- Update the confirmed design request to target `next_react`.
- Ensure Ada's source instructions use Next App Router and React client
  boundaries.
- Keep design direction, experience plans, GSAP skills, asset evidence, and
  browser review requirements intact.
- Require the generated site to declare fields before it is considered ready.

### Phase 5 — Build one new site from zero

- Start from a clean Next/React/Payload scaffold.
- Run the real confirmed-intake → Ada-build workflow.
- Require Ada to create the full candidate, not the coding agent.
- Verify Payload creation, field declarations, draft preview, GSAP behavior,
  responsive behavior, and owner review.
- Treat any manual repair or fallback as an incomplete test.

## Simplification rules

The correction is complete only when these statements are true:

- There is one canonical frontend framework: Next.js.
- There is one canonical UI framework: React.
- There is one canonical CMS integration: Payload.
- There is one canonical editable-field contract.
- There is one canonical build profile: `next_react`.
- There is one canonical preview/review path.
- GSAP is an approved capability, not an exceptional workaround.
- Missing configuration fails loudly; nothing silently falls back.
- Site-specific names and fields stay in configuration or Payload data.
- Production remains unchanged until explicit owner approval.

## Acceptance criteria

The architecture is ready for a new Ada-built site only when all of the
following pass:

1. A clean Next/React/Payload site can be scaffolded by Ada.
2. The site builds through the canonical `next_react` profile.
3. The public page renders server-readable content before hydration.
4. Payload admin/API and D1/R2 work without a second CMS or content store.
5. Ada can create text, rich-text, image, and link field definitions.
6. Authenticated draft preview exposes only declared field markers.
7. Draft edits update the preview without a source commit or deployment.
8. A GSAP interaction works at desktop, tablet, mobile, and reduced motion.
9. GSAP cleanup, hydration, accessibility, and browser requests pass validation.
10. Ada creates the candidate from confirmed intake through the real owner
    review flow.
11. Owner approval is the only production mutation path.

Until these criteria pass, report the system as incomplete rather than relying
on unit tests, a static screenshot, generated source, or a manually repaired
candidate.

## Expected result

Workspace becomes the working Next/React/Payload reference site. Ada then uses the
same architecture to create a new site from zero, with the same Payload
management, declarative editable fields, AI design pipeline, basic builder
functionality, GSAP capability, preview, and approval lifecycle.

The system is intentionally less flexible than a multi-framework platform, but
it is coherent, testable, and fully capable for the product we are actually
building.
