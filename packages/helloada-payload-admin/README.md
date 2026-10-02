# HelloAda Payload admin

This package is the shared owner workspace shipped with every HelloAda customer website.
It is intentionally a Payload admin extension, not a second CMS: the customer’s site
collections, globals, authentication, D1 database, R2 bucket, and deployment remain in
the customer repository.

The package owns the HelloAda navigation, workspace dashboard, Ada conversation surface,
review/history views, media picker, rich-text editor, translations, logo, and visual
system. Customer repositories provide thin Payload import-map wrappers and their
tenant-specific `/api/helloada/*` control-plane routes.

The package is released as an exact versioned tarball. A customer upgrade is a dependency
change followed by a normal site build and review; the package does not silently mutate
customer repositories or production data.

## Owner experience (0.3)

The primary workspace mirrors the HelloAda homepage: Ada conversation on the left,
website review on the right. On smaller screens, Ask Ada and Website switch between
the same mounted windows. Suggested requests populate the composer for the owner to
review; they do not start a job automatically. Publishing appears only for a real
draft and names the page before an explicit approval.

Manage opens a keyboard-accessible drawer with content, photos/files, settings,
account and language. Extra Payload collections are under Advanced options; native
Payload access controls still apply. Connection status is checked against the API.

There is no marketing banner above the working windows. Growth is a first-class
owner view for real GA4/GSC metrics, DataForSEO research, Ada recommendations,
article drafts, reports and schedules. Missing data/setup requirements are
explicit. Actions prepare requests for discussion; they do not start paid jobs.

Use the separate `@weareheadless/helloada-payload-admin/server` export for
request-time Worker bindings and authenticated tenant-readiness diagnostics.
See `docs/helloada-connection-contract.md` in site-agent for the release gate.

`src/brand/helloada-mark.svg` is the exact approved homepage mark, also rendered by
`HelloAdaMark`. Do not substitute a letter glyph or redraw the geometry.

Wrap both the dashboard and navigation in `HelloAdaSiteProvider` using the site's
configuration, so the tenant name and API base remain correct on every admin page.
