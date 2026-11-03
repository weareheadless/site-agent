# Business catalog contract — revision 10 draft

Status: source implementation in progress; **not release-ready**. No package
artifact, tenant pin, database, release queue, or live website has been changed.

## Source changes

- `productAttributes`: one typed text/number/boolean fact per product/key,
  localized display labels, unit/group/filterability, indexed typed values.
- `productVariants`: stable IDs/SKUs, declared product-option selections,
  unique product/selection identity, integer minor-unit prices, optional stock,
  image and ordering. These are catalog records, not a payment/order/reservation
  implementation. Variant currency is the product's currency.
- Products: structured location, option/value declarations and `priceMinor`.
  Legacy `price` is deliberately retained until an explicit currency-aware data
  conversion is reviewed. Nothing multiplies unknown currencies by 100.
- Five content collections: localized unique slugs. The real Payload D1 adapter
  generates uniqueness on `(slug, _locale)`, verified against SQLite.
- Pages: localized gallery. Astrid's four bilingual pages need neither products
  nor a new service-business schema.
- Draft/version support and the existing native-write guard cover the new
  collections. A public catalog reader excludes drafts, paginates child rows,
  and rejects published variants inconsistent with published product options.

## Required before release

1. Extend the existing workspace content gateway for the child collections.
   It currently accepts only pages/posts/products and requires a public slug
   for creation. Children need product/key or SKU idempotency, no invented
   standalone route, exact-draft publication, and conflict tests. The source
   authoring schema alone is not a working Ada integration.
2. Generate/review committed migration SQL and snapshots from each registered
   tenant's actual prior ledger. Backfill localized slugs **and historical
   versions** before removing old global columns/indexes. Preserve each live
   URL. `product_categories.slug` is currently NOT NULL, so simply leaving its
   old column behind would prevent new inserts.
3. Reconcile the existing scaffold snapshot/source drift separately. The last
   committed snapshot still has `appointment_type_id` booking relationships,
   while current source uses Mailflare `booking_type_id`. There is also an
   outbound-provider default difference. Do not let an automatic catalog diff
   rename/drop these fields or invent booking IDs. The additive migration tool
   correctly refuses the required booking column without a reviewed backfill.
4. Preserve retail presentation and migrate Atelier cart identity from product
   ID to variant ID (with product ID retained as context). Test two options of
   one product as two cart lines. No Stripe implementation is included here.
5. Pack/release the exact core artifact; update scaffold/tenant pins, lockfile
   integrities, contracts and migration identities together. The three current
   scaffold/core compatibility tests remain hard failures until this is done;
   they have not been weakened to hide the staged mismatch.
6. Use the canonical release queue with explicit prior/target migration ledger
   identities, then perform authenticated owner-edit/publish and public URL
   checks. Do not merge/deploy this draft as an ordinary runtime fan-out.

## Verification

Focused catalog, D1 schema and public-reader tests: 12 passing. Core TypeScript
check passes. Full core suite: 34 passing, 3 scaffold/core compatibility failures
because the scaffold remains pinned to released 0.5.10/revision 9 while source
stages 0.6.0/revision 10. These are release blockers, not an accepted green suite.

The SQLite test builds the actual Payload 3.88.0 D1 schema without credentials
and verifies localized slug uniqueness, product/key uniqueness, SKU and variant
selection uniqueness, and a numeric-attribute indexed query plan. This proves
schema behavior, not production migration safety or a working checkout.
