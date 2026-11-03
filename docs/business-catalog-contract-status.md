# Business catalog contract — revision 10 release candidate

Status: implementation complete; final release validation in progress. Core
0.6.0, scaffold pins, committed migration and contract identities are staged
together. No existing tenant database, release queue or live site has changed.

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

## Completed release work

- The existing content gateway supports child identity, idempotent retries,
  exact-draft updates/publication and conflict rejection. Children have no
  fabricated route. Ada's client and bounded planning use the same product/key
  and SKU identities. The authoring validator excludes server-derived fields.
- The append-only migration chain bootstraps a new database and backfills all
  existing locale rows and historical versions before retiring global slugs.
  New category inserts no longer depend on an obsolete NOT NULL global slug.
- Legacy booking tables are replaced only after **all** preflight checks pass
  and only if they contain no rows. Retained booking content requires an
  explicit operator-owned Mailflare mapping; no IDs or content are invented.
  Existing mailbox provider values and historical SQL defaults are preserved.
- Native Payload/D1 tests cover real drafts, publication, localization, typed
  facts, variant option/currency consistency and stock validation. Public reads
  require `_status=published` as well as the visibility flag. New catalog rows
  default to visible after explicit publication, not while drafted.
- Publication no longer treats an identical unpublished base-row hash as a
  publication receipt. The service gateway explicitly publishes the reviewed
  `_status` and verifies it on read-back.
- The staged exact artifact, scaffold lockfile integrity, contracts, Wrangler
  identity, verifier and migration manifest agree; compatibility gates remain
  enabled rather than being relaxed for the new schema.

## Release and existing-customer boundary

Final full-suite/build checks and the official versioned package release must
pass before this is marked release-ready. No tenant rollout is implicit.
Casamigo can start from the new scaffold on an empty dedicated D1/R2 deployment
after that package is available. Existing tenants need a separately reviewed
prior/target ledger migration, D1 backup and coordinated forward-only cutover:
the old Worker cannot read retired global slug columns. Ordinary runtime fan-out
must not apply this schema change.

Atelier's cart/presentation has not changed. Legacy `price` remains available,
so it is not silently converted to cents. Adopting its new variant catalog in
the storefront is separate work: cart lines must use variant ID with product ID
as context, and two variants must remain separate lines. Payments, orders,
stock reservations, and Stripe are not supplied by this schema release.

## Verification

Core suite: 44 passing, including the previous three compatibility gates; core
TypeScript passes. The template suite passed 123 tests and the scaffold passed
typecheck/lint (warnings only) and an OpenNext build. The final clean build/full
Python rerun remains pending after the shared `/tmp` volume filled. The cause was
a test fixture copying installed template dependencies/build output; it now uses
the canonical source-only ignore function. Task-only temporary output was removed,
and subsequent builds/tests use disk-backed temporary storage.

The SQLite test builds the actual Payload 3.88.0 D1 schema without credentials
and verifies localized slug uniqueness, product/key uniqueness, SKU and variant
selection uniqueness, and a numeric-attribute indexed query plan. This proves
schema behavior, not production migration safety or a working checkout.
