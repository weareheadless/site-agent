# HelloAda Payload core

This package owns the shared Payload schema, server-side content readers, stable editable-field bindings, and field validators used by HelloAda sites. Tenant applications pass their tenant-specific mutation guard when constructing the canonical collection/global configs. The package does not contain tenant data, credentials, database bindings, or frontend layouts.

Every customer uses its own Payload database and media bucket. The schema is shared; tenant data is not. The canonical page/article structure supports localized titles, summaries and Lexical body content; stable-key sections with typed headings, paragraphs, rich text, images, links and item lists; featured images; canonical URL overrides; SEO title, description and social image; and shared navigation/site-settings globals. Existing product and category collections remain explicit platform-owned modules.

`./bindings` derives the owner editor inventory from the same Payload document the frontend reads. Binding identity uses collection, document ID, stable section/block/item keys and field meaning—never array indexes. Its patch function validates expected values and types before returning a changed document. It preserves Lexical structure, restricts editable properties, and validates destinations and image-reference shapes. The tenant server bridge must resolve selected media against that tenant's Payload `media` collection before saving.

Every customer consumes this contract but retains its own data and visual composition. A schema or field-meaning change is a versioned platform migration, not an Ada website edit.

Revision 10 adds typed `productAttributes`, SKU-based `productVariants`, product
options/location and integer `priceMinor` amounts. Slugs are localized and pages
support galleries. Child records have draft/version support but no standalone
public route; the service gateway uses product/key or SKU for idempotent creates.
`readHelloAdaProductCatalog` reads only published product facts and variants.

Money uses the currency's minor unit; `price` remains a legacy major-unit field
until explicitly converted. A stock count is not an order/reservation ledger.
The committed migration preserves localized content and historical revision
slugs, and refuses unmapped legacy booking content before any DDL. Existing
tenant upgrades require the explicit schema-migration release queue, a D1
backup, and a coordinated forward-only Worker cutover. A new package version
is not permission to migrate or publish an existing customer's website.

Release exact immutable package versions through the `site-agent` package-release workflow. A package release requires selected customer dependency-pin updates and a controlled schema/data migration where needed. A new package version by itself does not update customer sites or databases.
