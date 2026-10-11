# HelloAda Mailflare integration source

`upstream/` is the unmodified, pinned Mailflare source snapshot recorded in
[`UPSTREAM.json`](./UPSTREAM.json). HelloAda-specific changes are applied only
to a disposable build copy by `scripts/build.mjs`; do not edit upstream files
to implement the tenant integration.

The integration build targets `/mail` on the same tenant origin. It builds the
Mailflare Worker module and client assets from the pinned lockfile, then places
them in the tenant's generated `.mailflare/` Worker module and
`.open-next/assets/mail/` static namespace. The official Site-Agent release
pipeline must hash both outputs into the single Worker receipt. No separate
Mailflare Worker or service to another application is produced.

Tenant D1, R2, queue, rate-limit and Turnstile bindings remain namespaced in the
Worker configuration. The shared `mailflare-bindings.ts` adapter translates
them to Mailflare's canonical names both for event handlers and for API routes
that read `cloudflare:workers` directly. Keep the adapter at both environment
entry points; adapting only the outer Worker handler does not reach Mailflare
route handlers. The pinned upstream source stays pristine; `scripts/build.mjs`
wires the same shared adapter into the disposable Mailflare build.

This package is the HelloAda-branded source for the tenant inbox, Contacts, Calendar and booking surfaces. Do not
deploy its upstream `wrangler.jsonc`; the tenant's Site-Agent Worker remains the
only deployment entrypoint. Payload authentication, per-tenant resource
provisioning, existing mailbox-data migration, and live tenant cutover remain
separate tracked milestones.
