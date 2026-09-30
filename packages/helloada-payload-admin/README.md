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
