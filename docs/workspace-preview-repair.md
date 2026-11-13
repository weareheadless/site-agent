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

The workspace pane therefore selects the signed route, not the alias, whenever
the selected page has an unpublished revision. `POST /api/helloada/preview`
authenticates the owner, reads that exact draft revision plus the draft
`siteSettings`/`navigation` globals, and returns a workspace-purpose token bound
to those hashes, the route and the owner. The token route still re-checks the
live owner session and the exact hashes, so this adds no second reader and no
public draft path. Only the canonical page renderer is shown this way; the
bespoke home composition and the article/product routes keep their published
display alias.

For an explicitly declared static presentation, the Worker serves public assets
before Next middleware runs. It therefore passes the same configured preview
mount into `staticWebsiteResponse`, which uses `workspacePreviewPath` to resolve
the display alias against the exact static inventory. Successful preview HTML
retains same-origin framing and is marked noindex; trailing-slash redirects
retain the mount. The Payload renderer and signed revision-preview route remain
platform-owned and unchanged. An unknown path remains a real 404.

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

The proxy requests a decoded request path escaped once. Next names chunks after
route segments such as `[...slug]` and answers the decoded form with a redirect
to the escaped one, so passing the decoded form through hands the browser a
redirect back to the address it just asked for. The document renders and every
client chunk loops, which is a preview the owner cannot use. The render gate
already requests the escaped form, so this only shows up in the browser.

## A review that outlived its base

A compiled preview is pinned to the exact base its review was prepared from.
When production moves, the candidate's own tree can stop compiling even though
the change under review is unchanged — OceanicVibes' favicon review failed with
a missing tenant-admin import after main removed that admin. Retrying the same
revision cannot succeed, and the draft stayed pending, so the owner's workspace
showed one retained build failure with no action that could clear it.

`POST /workspace/source/preview/rebuild` (`{ "draft_id": n }`, bridged from
`POST /api/helloada/source/preview/rebuild`) re-applies that review onto the
current production head and starts one fresh preview of it:

- the reviewed change is the exact tree difference between the review's pinned
  `base_sha` and its `head_sha`, read from both trees. It is never a file list
  supplied by the caller, and it is read from the full tree rather than the
  compare API, which stops listing after 300 files;
- every reviewed path passes the same publish allowlist the preview boundary
  enforces, and a repository too large to read as one tree is refused instead
  of half-applied;
- it refuses when the preview branch no longer carries that exact candidate, so
  a rebuild never overwrites newer staged work, and while the same revision is
  already building or has a ready preview;
- the review keeps its identity, records the replaced revisions in
  `rebased_from`, and persists the new `head_sha`/`base_sha` before the build
  starts so the compiled-preview guard binds the new commit;
- its commit is a normal commit on the preview branch. Nothing is published and
  no production branch moves.

A rebuild is not the same operation as `retry`: retry asks for the same revision
again, and is what a transient build failure needs. The workspace shows one
action for the failed preview and reports when the change was re-applied.
