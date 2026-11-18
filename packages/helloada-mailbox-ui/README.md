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
- The owner calendar and booking editor from the upstream `(calendar)` group,
  reading and writing the tenant's own calendar and booking API.
- A generated route map that preserves the upstream layout nesting, plus the
  language provider and the query client the mailbox components expect.
- 32 locale catalogs, loaded on demand instead of fetched from a tenant origin.

## What it deliberately does not contain

- Tenant authentication. The control plane authenticates the owner; the package
  never redirects to a login page and never holds a tenant session cookie.
- Server code: no `cloudflare:workers`, no Drizzle, no `next/headers`. The
  booking host parser and request shapes are generated from upstream, but the
  tenant database queries beside them stay in the tenant Worker.
- The assistant review queue and server-redirect stubs, which remain
  tenant-runtime surfaces until their own stage.
- A stylesheet that resets the control-plane shell. `styles.css` keeps the
  upstream tokens but scopes its base rules to `.helloada-mailbox`.

## Adaptations applied at build time

The generator applies and asserts these; a change in the upstream shape fails
the build instead of shipping a silent fallback:

- every `@/` alias import becomes a relative import inside the package;
- `authFetch` resolves `/api/*` against the injected owner-proxy base and no
  longer redirects to `/login`;
- bare `fetch("/api/...")` call sites use `authFetch`;
- URLs that are rendered rather than fetched, such as booking host avatars, are
  prefixed with the same owner-proxy base;
- `href`, `router.push`, `usePathname` and `useParams` go through the mailbox
  base path and route params;
- `h-dvh` becomes `h-full` so the control plane owns the viewport height;
- API/Navigation failures, unresolved imports, remaining auth guards and
  server-only modules fail the build.

## License and provenance

The package is a derivative work of Mailflare
(<https://github.com/hieunc229/mailflare>, pinned commit in `UPSTREAM.json`),
which is licensed AGPL-3.0. This generated package is therefore licensed
AGPL-3.0-only, and its complete corresponding source is this public repository:
the generator in `scripts/build.mjs`, the pinned upstream under
`packages/helloada-mailflare/upstream`, and the HelloAda app that renders it
(<https://github.com/weareheadless/helloada>). The upstream license text ships
with the pinned source and is retained there unmodified.
