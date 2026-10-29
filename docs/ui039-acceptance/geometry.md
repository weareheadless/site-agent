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
real hover`. The quick-edit checkbox is checked, the same-origin iframe is
complete, its `field-0` exists, and all 18 editable fixture entries loaded. The
iframe target's center is at page coordinate `(945.5, 125.5)`, but the page
hit-test resolves to the `owner.editManually` button (rect `x=862.28..1080.28`,
`y=89.5..129.5`), inside the still-open `.helloada-preview-options > div`
(`x=851.28..1091.28`, `y=78.5..180.5`). This options menu overlaps the top of
the iframe (`x=488..1403`, `y=99..765`) and intercepts the pointer. Consequently
the iframe's real pointerover listener sees zero events and no edit overlay is
created. This identifies a production interaction/positioning defect in the
preview-options dropdown and its relationship to the iframe, not a missing
fixture field or same-origin routing failure. The production source is outside
this test-only authorization; no synthetic event, forced state, menu dismissal,
or altered hover target is used to bypass it. The failing regression is retained.

Reproduce from the package with `node tests/ui039-browser.mjs` (uses the installed
Python Playwright package and cached Chromium; no install or network access).
This is a local fixture, not a deployed tenant or production-network proof.
Attachments remain a separate acceptance gap: deterministic package tests only;
no browser upload/send is claimed.
