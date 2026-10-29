# UI-039 dialog geometry evidence

The publish confirmation, quick field editor, and full page editor use the
canonical `ReviewWorkspace` component in `WebsiteWorkspace.tsx`. Their fixed
backdrops bound the dialog to the viewport; dialog headers and action footers
remain non-shrinking while the content region scrolls independently. Viewport
height uses a `100vh` fallback followed by `100dvh` where supported.

Browser evidence is local and uses mocked API/Next boundaries. The harness
bundles the actual production component with only child/API/Next boundaries
stubbed and compiles the package's real `admin.scss`. All three dialogs are
checked at 1440x900, 390x844 and 390x480 with ordinary action clicks, visible
hit-testable footers, overflowing inner content at the short viewport, and
closed-dialog checks.

For the field path the harness enables the deliberately hidden quick-edit
checkbox, records the covered-target hit test, and ordinary-clicks the native
details summary to close `.helloada-preview-options`. It then real-hovers the
iframe field and ordinary-clicks the real overlay action to open the field
dialog. The covered-target diagnostic is retained as evidence of the menu's
initial overlap; native `<details>` does not dismiss on outside click. No
synthetic field activation, forced state, fabricated dialog, or forced click is
used.

Reproduce from the package with `node tests/ui039-browser.mjs` (uses the installed
Python Playwright package and cached Chromium; no install or network access).
This is a local fixture, not a deployed tenant or production-network proof.
Attachment upload/send and immutable release pins remain separate unfulfilled
parent requirements; no parent completion is claimed.
