# UI-039 dialog geometry evidence

The publish confirmation, quick field editor, and full page editor use the
canonical `ReviewWorkspace` component in `WebsiteWorkspace.tsx`. Their fixed
backdrops bound the dialog to the viewport; dialog headers and action footers
remain non-shrinking while the content region scrolls independently. Viewport
height uses a `100vh` fallback followed by `100dvh` where supported.

Browser evidence is local and uses mocked API/Next boundaries. The harness
bundles the actual production component with only child/API/Next boundaries
stubbed, compiles the package's real `admin.scss`, launches Chromium and checks
footer hit-testing and viewport bounds. Publish and full page-editor screenshots
at 1440x900, 390x844 and 390x480, plus the exact run report, are in
`/tmp/opencode/ui039/`. It is not a deployed tenant or production-network proof.
Reproduce from the package with `node tests/ui039-browser.mjs` (uses the installed
Python Playwright package and cached Chromium; no install or network access).

The field popover is not included in the browser report: the mocked preview
fixture did not reach its quick-edit target. Its production source and compiled
styles are covered by package checks, but runtime geometry remains an acceptance
gap. Attachments are covered by deterministic package tests only; no browser
upload/send is claimed.
