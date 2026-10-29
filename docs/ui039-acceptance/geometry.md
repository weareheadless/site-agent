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
checks. The full page-editor geometry is exercised at those sizes by the
harness, but the full three-dialog acceptance is incomplete because field
dialog interaction does not yet pass.

For the field path the harness checks the hidden quick-edit checkbox, records
the original covered-target hit test, then attempts dismissal with a normal
outside click at `(4, 4)`. That click does not close the native
`.helloada-preview-options` `<details>` menu, so the harness stops before
hovering/clicking the field. The retained exact failure is
`outside click did not dismiss preview options`. The trace reports that before
dismissal the field center `(945.5, 125.5)` hit the `owner.editManually` button
inside the open options menu; the menu remains `open` after the outside click.
The menu rect was `x=851.28..1091.28, y=78.5..180.5`, overlapping the iframe
rect `x=488..1403, y=99..765`. The trace establishes the overlap but does not
establish whether the real field is reachable after a legitimate user
dismissal. No product workaround, synthetic event, forced state, fabricated
field dialog, or forced click was used.

Reproduce from the package with `node tests/ui039-browser.mjs` (uses the installed
Python Playwright package and cached Chromium; no install or network access).
This is a local fixture, not a deployed tenant or production-network proof.
Attachment upload/send and immutable release pins remain separate unfulfilled
parent requirements; no parent completion is claimed.
