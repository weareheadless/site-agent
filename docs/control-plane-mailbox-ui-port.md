# Mailbox UI port: complete Mailflare inside the control plane

Status: accepted direction, implementation staged. The workspace currently
shows a deliberately light Messages view; this document defines how the real
mailbox replaces it.

## Why this shape

The mailbox data layer is already complete. The tenant Worker exposes every
Mailflare API route through the `/api/helloada/mail/*` bridge, including search,
folders, drafts, sent/scheduled, starred, snoozed, spam, trash, bulk actions,
contacts, calendar, settings, and attachment download with the original
`Content-Disposition`. Only the UI is thin.

"Complete mailbox" therefore means "the real Mailflare dashboard", not a larger
hand-written one. Rebuilding folders, search, compose, drafts, contacts and
calendar in the control plane would duplicate a product that already exists and
would drift from it permanently.

The end state is the same split as the rest of the migration: the control plane
owns the owner experience, the tenant Worker owns tenant data and its API. The
dashboard UI moves to `helloada.app`; the tenant `/mail` UI is retired afterwards
so there is exactly one mailbox interface.

## Architecture

- A generated package, `@weareheadless/helloada-mailbox-ui`, is built from the
  pinned upstream in `packages/helloada-mailflare/upstream` (commit and version
  from `UPSTREAM.json`). It ships source, not a second hand-maintained copy:
  `npm pack` rebuilds it from the pinned upstream, and the release tag pins the
  exact bytes.
- The package exports `MailboxApp`, which owns the upstream route tree
  (dashboard, calendar, and later settings), the generated layout chain, the
  API base, and a stylesheet. It contains no auth: the control plane has already
  authenticated the owner and scoped the website.
- `helloada.app/<slug>/mail/<path>` renders `MailboxApp` under the
  existing control-plane navigation. Browser calls go to the existing owner
  proxy, `/api/helloada/websites/<slug>/owner/mail/<path>`, which injects the
  tenant workspace token and the owner subject. No tenant cookie and no iframe.
- The tenant Worker keeps the Mailflare API routes. `/mail` UI routes are
  removed only after every surface is verified in the control plane.

## Required adaptations, all generated and asserted

- **API base.** `authFetch` becomes the single prefixing client, and the 18 bare
  `fetch("/api/...")` call sites are rewritten to it. A build assertion fails if
  any unprefixed `/api/` fetch remains.
- **Auth.** `AuthGuard`, login redirects and the 401 `window.location.assign`
  are removed: the control plane owns authentication. A build assertion fails
  if they remain.
- **Routing.** Upstream pages and layouts become a generated route map. Internal
  `next/link`, `router.push` and `usePathname` comparisons are prefixed and
  base-stripped so navigation and active states work under `/mail/<path>`.
  `useParams` is served by a package provider, because the consumer route owns
  `[id]` and `[path]`.
- **Server pages.** Pages that were server components (`(settings)/settings/*`
  with `getServerTranslations`, `redirect()` stubs) are excluded from the first
  stages and adapted explicitly later. A client page may not import server code.
- **CSS.** Tailwind v4 utilities plus the upstream theme are scoped to the
  mailbox root. The control-plane shell keeps its unlayered SCSS so workspace
  styles are not reset by Tailwind preflight; the token bridge maps upstream
  colours and the Geist font variables onto the HelloAda surface tokens.
- **Proxy headers.** The owner proxy must forward `content-disposition` (and the
  other safe representation headers) so attachment downloads keep their
  filenames. Streaming bodies stay streaming.
- **Bridge cost.** The bridge currently creates and deletes one temporary
  `ep_session` per request. A dashboard load issues many parallel requests, so
  the bridge reuses one owner session for the tenant instead. The token never
  reaches the browser, so this removes write amplification without widening
  exposure.

## Stages

1. **Package and generator.** `packages/helloada-mailbox-ui` builds from the
   pinned upstream, applies the adaptations above, generates the route map, and
   passes contract tests. No customer-visible change.
2. **Read path live.** App pin, Tailwind, route and nav; inbox, thread,
   attachments and search verified in a real authenticated browser on an empty
   tenant and on oceanicvibes.
3. **Write path live.** Compose, reply, drafts, bulk actions, star, snooze and
   archive, with an explicit send that is verified by addressing the owner.
4. **Contacts, calendar and booking settings.**
5. **Settings surfaces, tenant `/mail` retirement, docs.**

Each stage ends with a canonical-queue release, a fresh authenticated browser
check of the real page, and a rollback path that is an ordinary app revert.

## Stage 2 record

Package: `@weareheadless/helloada-mailbox-ui@0.1.0` from the pinned upstream
`ca41c56a` (0.5.1), published as the GitHub release asset
`weareheadless-helloada-mailbox-ui-0.1.0.tgz` (21 routes, 267 files, 32 locale
catalogs) and pinned in the app by URL plus `sha512` integrity. The app release
pipeline verifies the published bytes before `npm ci`.

App release: `20261110002000-mailbox-params`, SHA
`f138fdeeee959c647ce8a46b2d2fcc59f5368a67`, deployed and verified through the
canonical queue; `/api/health` reports the same SHA.

Verified in a real authenticated browser on `oceanicvibes`:

- `/oceanicvibes/mail` redirects to `/mail/inbox`; the mailbox renders under the
  shared control-plane navigation with HelloAda branding and no vendor credit.
- Inbox lists the one real message; opening it keeps the URL under
  `/oceanicvibes/mail/inbox/<message-id>` and renders sender, recipient, date,
  the message body and both attachments.
- The attachment modal shows the filename, `application/pgp-keys` type and a
  Download control; the proxy keeps `content-disposition`.
- Search narrows to one result for `proton` and shows `0 - 0 of 0` with
  "No messages match these filters" for a term with no matches.
- `atelier-harmonie` shows the empty state (`0 - 0 of 0`, "No emails") rather
  than an error.

Notes for later stages: the in-app browser is narrow, so the mailbox sidebar is
off-canvas there — it is not a layout defect. Body text renders through a portal,
so text snapshots omit it while the captured page shows it. The bridge still
creates one `ep_session` per request; latency is tolerable, so session reuse is
deferred until it is measured as a problem.

## Acceptance

- The owner reaches every mailbox surface from the workspace navigation without
  leaving `helloada.app` and without a second login.
- Attachments keep their filename and type; uploads work through the same
  bridge.
- No `/mail` UI remains reachable as a parallel mailbox after stage 5.
- Public sites, raw Payload admin and tenant data are unchanged.
