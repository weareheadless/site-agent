# @weareheadless/helloada-mailbox-ui

The HelloAda-owned mailbox UI. It is generated from the Mailflare upstream that
is pinned in `packages/helloada-mailflare/UPSTREAM.json`; this repository does
not maintain a second copy of the pages or components.

```bash
npm run build     # regenerate dist/ from the pinned upstream
npm test          # contract tests: routes, auth removal, API base, locales
```

## What it contains

- The owner mailbox route tree from the upstream `(dashboard)` group: inbox,
  message threads, compose, drafts, scheduled, sent, starred, snoozed, archived,
  spam and trash, with custom folders and search.
- A generated route map that preserves the upstream layout nesting, plus the
  language provider and the query client the mailbox components expect.
- 32 locale catalogs, loaded on demand instead of fetched from a tenant origin.

## What it deliberately does not contain

- Tenant authentication. The control plane authenticates the owner; the package
  never redirects to a login page and never holds a tenant session cookie.
- Server code: no `cloudflare:workers`, no Drizzle, no `next/headers`.
- The booking editor, assistant review queue and server-redirect stubs, which
  remain tenant-runtime surfaces until their own stage.
- A stylesheet that resets the control-plane shell. `styles.css` keeps the
  upstream tokens but scopes its base rules to `.helloada-mailbox`.

## Adaptations applied at build time

The generator applies and asserts these; a change in the upstream shape fails
the build instead of shipping a silent fallback:

- every `@/` alias import becomes a relative import inside the package;
- `authFetch` resolves `/api/*` against the injected owner-proxy base and no
  longer redirects to `/login`;
- bare `fetch("/api/...")` call sites use `authFetch`;
- `href`, `router.push`, `usePathname` and `useParams` go through the mailbox
  base path and route params;
- `h-dvh` becomes `h-full` so the control plane owns the viewport height;
- API/Navigation failures, unresolved imports, remaining auth guards and
  server-only modules fail the build.
