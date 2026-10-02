# Payload-First HelloAda Default and Customer Upgrade Plan

**Status:** Implementation plan for a coding AI  
**Date:** 2026-10-02  
**Repository:** `weareheadless/site-agent`  
**Priority order:** 1. New-site default path  2. Existing customer upgrades  3. Cleanup and enforcement

## 1. Objective

Make Payload the structural source of truth for every customer website created
through Ada and HelloAda.

The desired product behavior is:

```text
HelloAda intake
  -> site-agent provisions the canonical Next.js + Payload site
  -> Ada designs and builds against the Payload content contract
  -> Payload stores the site's content, media, SEO, and shared chrome
  -> the frontend renders Payload data
  -> the owner can edit directly in Payload without Ada
  -> Ada remains the assistant that proposes and applies approved changes
```

This is not a request to add a few CMS fields. It is a platform contract. A
new site must not be considered successfully provisioned if its blog, SEO,
navigation, footer, or other owner-managed content exists only in source files
or only inside Ada's conversation state.

## 2. Priority order

### Priority 1 — Make the default Ada / HelloAda path correct

This is the most important work. The canonical site-agent template,
provisioning flow, Ada tools, and HelloAda intake/build flow must all create
and use the same Payload-first structure by default.

Priority 1 is complete only when a newly provisioned test tenant can:

1. create and edit a page in Payload;
2. create and edit a blog post in Payload;
3. select the post's main image from Payload Media;
4. edit the page or post SEO metadata;
5. edit the shared header and footer once and see the change across routes;
6. see all of those changes in the public frontend without Ada being online;
7. ask Ada to make an equivalent change and find the result saved in Payload;
8. publish or roll back through the existing owner-approval workflow.

The new-site flow must not default to a static/Pelican article path, a
hardcoded frontend, or a second owner-facing CMS.

### Priority 2 — Upgrade the two active customers

After the central default is proven, migrate:

1. Atelier Harmonie;
2. OceanicVibes.

Both customers must use the same versioned contract and the same frontend
query/rendering patterns as newly provisioned sites. Customer-specific design
and copy remain intact; the content architecture becomes standardized.

### Priority 3 — Remove drift and legacy paths

Only after the new-site path and both migrations pass the release gate:

- remove remaining production use of static article files;
- remove obsolete Pelican/default build paths;
- remove duplicate customer-specific content adapters where the shared adapter
  is sufficient;
- make CI reject new frontend hardcoding of Payload-managed content;
- document and version the upgrade path for future tenants.

Do not begin Priority 3 by deleting compatibility code. First prove the
replacement path with real content and a rollback path.

## 3. Current baseline

### 3.1 Central `site-agent`

Already present:

- canonical Next.js/Payload template;
- Payload 3, D1, R2, Next.js, and OpenNext dependencies;
- basic `Pages`, `Posts`, `Products`, `Media`, `Navigation`, and
  `SiteSettings` definitions;
- Payload gateway and Ada content operations;
- `blog.engine: payload` in defaults;
- shared HelloAda Payload admin package.

Still missing for the required default:

- complete canonical content schema;
- page/post SEO and social-image fields;
- shared footer/navigation contract;
- dynamic Payload-driven frontend routes for pages and posts;
- dynamic blog index and article detail rendering;
- seeded default globals and starter content;
- a single typed content adapter used by both the frontend and Ada;
- provisioning checks that fail when the contract is incomplete;
- tests proving that a new site works without Ada or source-file fallbacks.

The current template frontend is still a placeholder, so the presence of
Payload collections alone does not yet make the new-site experience Payload
first.

### 3.2 Atelier Harmonie

Already close:

- Payload `Posts` has `featuredImage` and article fields;
- `Pages` already contains metadata/SEO fields;
- `Navigation` already has header and footer structures;
- `SiteSettings` already contains shared footer/site fields;
- the frontend has Payload-aware content and global helpers;
- HelloAda can edit text and featured images through Payload.

Remaining work:

- prove every public route uses the Payload resolver first;
- make the blog index and article detail use the same canonical resolver;
- ensure HTML metadata is derived from Payload fields on every page;
- validate that footer/header edits propagate across all pages;
- migrate any remaining fallback-only content into Payload;
- add idempotent migration and post-migration content checks.

### 3.3 OceanicVibes

Payload collections exist, but the public frontend still has important static
surfaces:

- hardcoded blog index articles;
- hardcoded article detail content;
- static homepage navigation and footer;
- static layout metadata;
- incomplete SEO and shared-navigation fields in the local schema.

OceanicVibes therefore requires a real frontend/content migration, not just a
schema migration.

## 4. Canonical Payload contract

The contract belongs in the central template and must be copied/versioned into
each customer repository through the normal site-agent release process.

### 4.1 `media` collection

Required capabilities:

- upload and secure tenant-scoped storage through R2;
- filename and alt text;
- optional caption/description;
- source/import identifier for idempotent migration;
- focal point or crop metadata where the design requires it;
- image analysis fields used by Ada, clearly separated from owner-editable
  fields.

Media must be selectable from Payload by both the owner and Ada. The public
frontend must receive a stable resolved URL from the media adapter rather than
constructing storage paths directly.

### 4.2 `pages` collection

Required fields:

- tenant/source identifier;
- slug and route;
- title;
- structured sections or rich content;
- featured image where relevant;
- publication status and timestamps;
- SEO title;
- meta description;
- canonical URL;
- Open Graph/social image;
- optional locale fields;
- draft/version support.

The frontend must resolve a page by route/slug through Payload. It may use a
build-time or request-time cache, but it must not use a competing hardcoded
document as the production source of truth.

### 4.3 `posts` collection

Required fields:

- title;
- slug;
- excerpt/summary;
- rich article body;
- author/byline;
- publication and modification dates;
- draft/published status;
- `featuredImage` as a relation to `media`;
- optional article gallery;
- category/tags where the site needs them;
- SEO title;
- meta description;
- canonical URL;
- Open Graph/social image;
- locale fields where enabled.

The blog index must query published posts from Payload and render each post's
`featuredImage`. The article route must query the post by slug and render the
same Payload record. No separate `articles/index.json`, markdown article tree,
or hardcoded article map may be required for a new site.

### 4.4 Shared globals

`navigation` must contain reusable, tenant-scoped structures for:

- primary/header items;
- grouped navigation where needed;
- footer items;
- footer groups;
- optional call-to-action link;
- external-link and visibility flags.

`siteSettings` must contain reusable site-wide values such as:

- site name and description;
- logo/brand media;
- contact details;
- social links;
- footer copy;
- legal links or legal-page references;
- default locale;
- default SEO/social settings.

The frontend must render these globals in one shared site-chrome component.
Pages must not duplicate footer or navigation markup unless a deliberate
per-page override is part of the contract.

### 4.5 Tenant isolation

Each customer keeps its own Payload database and media bucket. The central
site-agent control plane must never turn the shared schema into a shared
customer-content database.

Every bridge route and Ada operation must validate:

- authenticated Payload user/session;
- tenant/site identity;
- allowed collection/global;
- draft versus published scope;
- media ownership before assigning an image.

## 5. Priority 1 implementation — central default path

### Step 1: Freeze the canonical schema

Update the central template under
`src/site_agent/templates/next-payload`:

- expand `Pages.ts` and `Posts.ts` to the contract above;
- expand `Navigation.ts` with shared footer structures;
- expand `SiteSettings.ts` with site-wide/footer/SEO defaults;
- keep `Media.ts` tenant-safe and compatible with R2;
- add any required migrations;
- add a schema version to the site configuration and release manifest.

Do not make customer-specific fields mandatory in the shared package. Use
capability flags or site-level extensions for commerce and unusual content.

### Step 2: Build one shared Payload content adapter

Create a typed adapter used by all canonical frontend routes:

- `getPageBySlug`/`getPageByRoute`;
- `getPublishedPosts`;
- `getPostBySlug`;
- `getMediaUrl`;
- `getNavigation`;
- `getSiteSettings`;
- `getSeoMetadata`.

The adapter must define:

- locale and fallback behavior;
- draft versus published behavior;
- cache/revalidation policy;
- missing-content behavior;
- media relationship normalization;
- safe handling of Payload depth and relationship documents.

Ada and the frontend should use the same field names and contract, even if
they use different authenticated transport routes.

### Step 3: Make the canonical frontend Payload-driven

The central template must include working examples for:

- homepage/page route;
- blog index route;
- article detail route;
- shared header;
- shared footer;
- dynamic metadata generation;
- featured-image rendering;
- 404 behavior for missing/unpublished routes.

The starter design can stay minimal. Its purpose is to prove the architecture,
not to prescribe every customer's visual design.

### Step 4: Make Ada's default behavior Payload-first

Update Ada/site-agent provisioning, design, and editing flows so that:

- new-site bootstrap seeds Payload documents and globals;
- design/build instructions identify Payload-managed fields before writing
  frontend code;
- blog creation writes to `posts` and `media` through the Payload bridge;
- SEO recommendations write to page/post SEO fields;
- image replacement updates a media relationship, not a hardcoded URL;
- navigation/footer changes update the `navigation` global;
- Ada reads current Payload content before proposing changes;
- Ada never silently creates a parallel markdown/JSON content source for a
  Payload-enabled site.

The default Ada capability contract should explicitly expose:

```text
read_page
update_page
read_post
create_post
update_post
publish_post
read_media
attach_featured_image
read_global
update_navigation
update_site_settings
```

Operations remain owner-approved where the current product requires approval.

### Step 5: Make HelloAda intake provision the complete contract

When HelloAda creates a new site, provisioning must:

1. select the current canonical site-agent release;
2. materialize the Next/Payload template;
3. configure tenant ID, locale, Worker, D1, and R2;
4. run Payload migrations;
5. seed `siteSettings` and `navigation` globals;
6. create starter page/post records when the intake requires them;
7. register the Payload bridge and capability manifest;
8. run a contract smoke test against the provisioned site;
9. report the site as ready only after all required checks pass.

The intake/build UI must show the same architecture as the actual site. A
website must not be presented as Payload-managed while provisioning a legacy
static path behind the scenes.

### Step 6: Add central contract tests

Add tests that provision a temporary site and verify:

- required collections and globals exist;
- required fields exist;
- a post can be created with a media relationship;
- the blog index reads that post from Payload;
- the article route reads the same post by slug;
- page/post SEO reaches generated metadata;
- navigation/footer updates affect multiple routes;
- a draft is not visible in the published frontend;
- an unowned media ID cannot be attached;
- Ada operations write through Payload rather than source files.

These tests are the gate for all future new-site releases.

## 6. Priority 2 implementation — customer upgrades

### 6.1 Atelier Harmonie

Migration sequence:

1. inventory all current Payload pages, posts, media, globals, and fallback
   records;
2. map existing fields to the canonical contract without destroying source
   identifiers;
3. populate missing post SEO fields and social/featured-image relationships;
4. populate page SEO metadata;
5. normalize navigation and footer into the shared `navigation` global;
6. update frontend routes to use the central adapter;
7. remove production dependence on migration fallback records;
8. test edits in Payload with Ada offline;
9. test equivalent edits through Ada;
10. deploy only after the live release gate passes.

Atelier is the first customer migration because it already has much of the
required schema and Payload-aware frontend plumbing.

### 6.2 OceanicVibes

Migration sequence:

1. inventory the two existing articles and all homepage/footer/navigation
   content;
2. import articles into `posts` with stable slugs, excerpts, rich body,
   publication dates, and featured images;
3. extend local collections with the canonical SEO and shared-global fields;
4. move homepage and article metadata into Payload;
5. replace hardcoded article index rendering with a Payload query;
6. replace hardcoded article detail rendering with a Payload slug query;
7. replace hardcoded header/footer with shared Payload globals;
8. preserve OceanicVibes visual design while changing only the data source;
9. test owner edits without Ada;
10. test Ada-assisted updates and publishing;
11. deploy after fresh-browser and live-DOM verification.

OceanicVibes must not be marked migrated merely because its Payload admin
loads. The public frontend must demonstrably render the Payload records.

## 7. Shared admin and owner experience requirements

The HelloAda Payload admin remains the owner-facing interface, but it must
make direct Payload management discoverable:

- Gallery manages media and exposes “use with Ada”;
- Blog/Posts exposes title, body, publication status, featured image, and SEO;
- Pages exposes route, content, featured image, and SEO;
- Navigation/Site Settings expose shared site chrome;
- Ada can propose changes, but the owner can perform the same core edits
  directly in Payload;
- advanced Payload options remain available through progressive disclosure;
- all save/publish states remain explicit and tenant-scoped.

The visual workspace is not allowed to hide the underlying CMS capabilities
that are part of the customer's delivered product.

## 8. Release gates

For Priority 1 and every customer upgrade:

1. Build from a clean, complete checkout.
2. Verify generated artifacts contain the canonical Payload routes and do not
   contain removed legacy content paths.
3. Run schema, contract, typecheck, lint, and build tests.
4. Deploy the exact artifact to the preview and Cloudflare Worker targets.
5. Poll deployments to successful terminal states.
6. Fresh-load the admin and public frontend with a cache-busting query.
7. Verify live DOM for:
   - Payload-rendered blog title and featured image;
   - generated SEO metadata;
   - shared navigation and footer;
   - draft/published behavior;
   - direct Payload edit flow;
   - Ada-assisted edit flow.
8. Visually inspect the changed routes in a real browser.
9. Record the release version, tenant, migration result, and rollback point.

Production Payload CLI migrations must fail closed unless
`CLOUDFLARE_API_TOKEN` is present. Wrangler's local binding is useful for
development, but it is not an acceptable production migration target: a
successful local migration must never be mistaken for a remote schema update.
The canonical template and migrated tenants enforce this at config load time.

No release is complete based only on a successful build or API response.

## 9. Definition of done

This plan is complete when all statements are true:

- A new HelloAda site provisions the canonical Payload contract automatically.
- Ada defaults to reading and writing customer website content through Payload.
- Blog articles and featured images are directly editable in Payload.
- Page and article SEO metadata is directly editable in Payload.
- Header and footer are shared Payload-managed structures.
- The public frontend renders those structures from Payload.
- Atelier Harmonie uses the canonical contract in production.
- OceanicVibes uses the canonical contract in production.
- Both customers remain visually distinct while sharing the same content
  architecture.
- Ada can be offline while owners continue to edit and publish through Payload.
- The central contract tests fail if a future template regresses to static
  articles, hardcoded navigation/footer, or non-Payload SEO.
- Legacy paths are removed only after migration and rollback evidence exists.

## 10. Rollback and safety

- Keep customer-specific migrations idempotent and source-ID based.
- Do not overwrite existing content without a backup/export and a dry-run
  report.
- Preserve the previous Worker version until live verification passes.
- Keep a per-customer database/content snapshot before migration.
- If a frontend adapter fails, restore the prior release while retaining the
  migrated Payload records; do not reverse the database destructively.
- Production deployment, remote migrations, repository pushes, and deletion
  of legacy resources remain explicit release actions.

## 11. Implementation order summary

```text
1. Canonical schema + adapter + dynamic starter frontend
2. Ada default tools/prompts + HelloAda provisioning
3. Contract tests and new-site smoke release
4. Atelier migration and production verification
5. OceanicVibes migration and production verification
6. Fleet enforcement, legacy cleanup, and upgrade automation
```

The critical sequencing rule is simple: **make the path used by Ada to create
the next site correct before spending the second priority on upgrading the two
existing sites.**
