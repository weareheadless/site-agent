# UI-039 dialog geometry evidence

The publish confirmation, quick field editor, and full page editor use the
canonical `ReviewWorkspace` component in `WebsiteWorkspace.tsx`. Their fixed
backdrops bound the dialog to the viewport; dialog headers and action footers
remain non-shrinking while the content region scrolls independently. Viewport
height uses a `100vh` fallback followed by `100dvh` where supported.

Browser evidence is local and uses mocked API/Next boundaries. The harness
bundles the actual production component with only child/API/Next boundaries
stubbed and compiles the package's real `admin.scss`. Publish geometry passes at
1440x900, 390x844 and 390x480 with ordinary action clicks and closed-dialog
checks. The full page-editor was previously measured at these sizes by the
inherited harness. The updated harness attempts the quick-edit route through the
checkbox, same-origin iframe hover and actual overlay button, but it currently
fails before opening the field dialog, so this retry does not establish field
dialog geometry or full-matrix acceptance. Detailed assertion/DOM evidence is
retained in the test output; no field-dialog markup or state is fabricated.
The requested all-three-dialog overflow/click evidence remains incomplete.
The exact failing assertion is `quick-edit iframe overlay did not appear after
real hover`: diagnostics showed `checkboxChecked: true`, `pageFieldCount: 18`,
same-origin iframe field `field-0` present and loaded, `pointerEvents.count: 0`,
and `.helloada-preview-edit-overlay` count `0` after Playwright hovered the real
iframe target. Thus the feature gate and fixture record exist, but the iframe
document did not observe the hover event in this harness run.

Reproduce from the package with `node tests/ui039-browser.mjs` (uses the installed
Python Playwright package and cached Chromium; no install or network access).
This is a local fixture, not a deployed tenant or production-network proof.
Attachments remain a separate acceptance gap: deterministic package tests only;
no browser upload/send is claimed.
