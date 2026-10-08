# Preserve customer presentation during schema migrations

The October 4 Atelier migration replaced its approved React presentations with
a generic renderer. Retaining the CSS did not retain the design: the original
markup, GSAP reveals, image composition and navigation grouping were removed.

The verified pre-migration reference is Atelier source
ddafd9bfce2f1e5dd6b884270379a68b68ce4830, deployed in
20261003-durable-release-5. Restore presentation from that reference while keeping
the canonical shared Payload schema, server readers, bridge and route resolver.
Do not restore the old schema, snapshot reader, captured assets directory or
static content fallback.

Customer composition is not part of a schema migration. Map its existing values
into canonical sections with stable keys and real Payload media relationships.
When an approved presentation value was formerly stored in source, import it
explicitly as data; do not retain it as a runtime fallback. Preserve existing
canonical edits. Validate array limits and globally unique navigation keys.

For a presentation-preserving migration, verify representative public pages,
their menu, images and motion against the pre-migration release. Test native
editing of the mapped fields and the authenticated admin separately. A passing
health response or unchanged CSS hashes proves neither presentation parity nor
admin availability.

Atelier's content-only restoration is the reviewed operator script
scripts/restore-approved-content.ts in its tenant repository. Run its dry-run
first through the registered Cloudflare credential resolver and pinned runtime.
Its --apply operation is explicit data migration, not Worker deployment or an
alternate runtime content path. Both Worker releases remain on the central queue.
