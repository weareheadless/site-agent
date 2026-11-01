# Workspace preview routing contract

The owner workspace constructs its display URL from `helloAdaSite.routes.preview`
and the selected canonical public route. A migrated tenant must retain that mount
for **all** public pages, not only its homepage.

The canonical scaffold owns `src/middleware.ts` and
`src/lib/workspace-preview-path.ts`. The mount comes directly from the tenant
configuration used by the admin. It rewrites the exact mount and child paths to
the existing public renderer, preserving query strings, cookies, locale, CSS,
images and the tenant's approved composition. It does not introduce another
content reader, retry another URL, or redirect the owner out of the workspace.
Platform paths and similarly named mounts are not aliases. Preview responses are
marked noindex. Use the supported Edge middleware convention for this OpenNext
deployment; Node-runtime proxy support is a separate platform decision.

This display alias shows published canonical content. It is **not** proof that
an unpublished revision was reviewed. Exact draft verification continues through
the authenticated, signed `/helloada-preview/[token]` route; approval must retain
its exact document/hash checks. Compiled source candidates remain a separate
existing review contract. Never substitute a public display alias for draft or
candidate approval evidence.

Atelier's migration deleted its mount. Oceanic retained a homepage-only component
that returned 404 for other routes. Both now use the scaffold implementation;
the obsolete Oceanic component is removed. No schema or tenant content changed.

Verification: run the preview routing tests and tenant typecheck; deploy immutable
tenant SHAs via the VPS queue, then inspect the actual authenticated iframe for
home, an inner page, and `/blog`, including image/CSS/motion and console errors.
Record those browser checks beside the release receipt. Tests alone do not prove
the OpenNext rewrite or iframe is working live.

## Compiled candidate validation

A retained managed design run can enter the existing source-preview job before
its owner decision exists. The tenant-scoped run supplies its immutable Git SHA
and exact Payload revision receipts; it grants no approval or publication.
The job imports only canonical website documents and referenced media into an
isolated local Payload D1 using the committed migrations, never schema push.
That import file is deleted before runtime; Payload remains the only reader.
The preview uses the website OpenNext renderer with local D1/R2, not remote
mail, AI or deployment bindings. Its generated Next mount and public-asset
transport rewrites keep SSR, client chunks and hydration under the workspace's
existing authenticated source-preview path. These are disposable compiler
inputs, not edits to Ada's retained source or a customer release.

OpenNext performs the single framework build. Its immutable output is retained
in the existing output store; browser gates inspect that exact runtime through
the existing proxy handler, including reduced motion. A missing static `out/`
must not discard those observations or require a particular animation library.
Only a candidate whose required checks pass gets the existing owner decision.
The workspace selects that decision's exact compiled SHA rather than showing
the published-content alias. Owner approval still uses the canonical draft
approval operation and production release queue.
