# HelloAda owner workspace

## UX contract

This is product UI in the shared Payload package, not a hand-built customer
design or a substitute for Ada's autonomous design pipeline.

The owner should make three ordinary decisions: ask for a change, inspect the
result in the website window, and explicitly approve publication. Payload is
the CMS underneath, not the vocabulary or navigation the owner has to learn.

- Conversation first, website review alongside it. Same quiet windows, warm
  dark palette, typography and exact approved logo as helloada.app.
- Suggestions are editable requests, never automatically submitted jobs.
- Show progress and real connection status, not simulated activity.
- No marketing H1/banner. Compact toolbars leave the space to chat and preview.
- Growth remains first-class: analytics, keyword research, recommendations,
  schedules, article drafts and reports stay visible with progressive details.
- Only show publication for a real draft; require a page-naming confirmation.
- Keep manual page editing, collections, files, settings, account and language
  accessible. Manage reveals these without filling the primary workspace.
- Put secondary collections under Advanced options. Payload permissions still
  govern every operation; hiding controls is not access control.
- On phones, switch between the mounted Ada and Website windows without losing
  the current message or preview state. Keyboard focus and reduced motion work.
- Failed connections must explain that the existing website is unchanged and
  provide a retry; a timeout must not leave the navbar connecting indefinitely.

## Brand and release boundary

`packages/helloada-payload-admin/src/brand/helloada-mark.svg` is the unchanged
homepage asset. `HelloAdaMark` renders its exact geometry. A contract test locks
the approved asset digest.

The reusable source lives only in site-agent. Customer repositories retain thin
provider/import-map wrappers plus their own configuration, CMS, D1 and R2 data.
Both navigation and dashboard require the tenant provider.

Release an immutable package tarball, upgrade the customer lockfile, build and
deploy that exact dependency, then verify a fresh authenticated admin document.
Template versions and health metadata must match. A shared Git commit alone
does not update deployed customer Workers; each requires a verified deployment.

## Acceptance checks

Inspect 1440px, 768px and 390px layouts for overflow and readable preview/chat.
Exercise Manage, Escape/focus restoration, suggestions without submission,
mobile pane state retention, viewport controls and existing native editors.
Production content is never changed for UI QA. Chat, publication and existing
draft/review contracts stay intact; use a local fixture for destructive paths.
