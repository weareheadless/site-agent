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

This package is an implementation source, not yet a production release. Do not
deploy its upstream `wrangler.jsonc`; the tenant's Site-Agent Worker remains the
only deployment entrypoint. Payload authentication, per-tenant resource
provisioning, existing mailbox-data migration, and live tenant cutover remain
separate tracked milestones.
