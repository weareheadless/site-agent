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
