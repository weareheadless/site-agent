# Explicit GitHub website provisioning

Owner-directed product change, 2026-11-03; tracked in Site-Agent #603 and
HelloAda #23. This narrows existing-site provisioning; it is not a universal
adoption platform. It supplements the selector contract and supersedes its
intake and all-Payload-public-content requirements **only for this explicit
source mode**. Ordinary Payload sites retain their current contracts.

## Supported source

The existing platform administrator creates a website in helloada.app with an
optional `github_repository`. Ordinary customer accounts cannot nominate an
organization repository using the host's GitHub credentials. The
server accepts only a `weareheadless/<repository>` identity (or its canonical
HTTPS GitHub URL). The source is official `main`, not a supplied ref, URL,
credential or local path. Registration freezes that identity and prevents a
second tenant owning the same repository. A retry cannot change source mode.
Registration and bootstrap echo the frozen source; the selector rejects a
missing/mismatched echo rather than letting an older backend ignore the option.

The first convention is a committed static `public/index.html`, with explicit
HTML languages and all referenced local assets committed. There is no framework
detection, server-code import or content conversion. Reserved platform paths
cannot be supplied by the frontend. Missing assets and symlinks fail closed.

## Runtime and authority

Provisioning adds the canonical version-pinned Next/Payload platform files to
that repository, preserving public presentation bytes and Git history. The
operator explicitly authorizes this platform setup when submitting the repo.
The original source SHA and public inventory remain inspectable. Platform code,
package pins, authentication and migrations remain platform-owned, not Ada
authoring surfaces. No content is synthesized into CMS documents.

One tenant Worker serves source-controlled public HTML/assets and the canonical
Payload admin/API and Mailflare. There is no second deployment target, CMS,
credential path or release system. An explicit static presentation declaration
selects the public asset handler; a missing declared page is an error, never a
fallback to a generated CMS homepage. Payload owns its collections, which may
later supply blog/shop routes through explicit frontend work. Provisioning is
not a claim that commerce/checkout is implemented.

The existing bootstrap, protected main-account credential resolver, committed
migration chain, owner handoff and exact-SHA VPS release queue remain mandatory.
The static path skips intake and design generation. It reuses the existing SEO
provisioning lifecycle; issued GA4/GSC identifiers are rendered in actual public
HTML using runtime bindings, not merely in admin HTML. Readiness must distinguish
workspace, public website, Google verification and CrawlSEO state.

## Astrid acceptance

Use `weareheadless/astrid-rincon-website`, not the old generated repository.
Deploy on the host's main Cloudflare account under its actual workers.dev
subdomain. Do not transfer `astridrincon.com`, change its current DNS/custom
routes or use the temporary other-account token. Keep the existing site's
canonical domain until its separately authorized domain cutover.

Prove an authenticated helloada.app create/retry with repository identity, no
intake, exact source admission, all eight public pages and assets, working
desktop/mobile/reduced-motion behavior, Payload owner handoff and actual SEO
state. Keep partial/blocked work explicit. A unit test or public health response
alone is not completion.
