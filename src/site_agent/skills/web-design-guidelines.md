# Web Design Guidelines (condensed from vercel-labs/agent-skills)

Interactivity, accessibility, performance — the checklist every page must pass.

## Interaction & feedback
- Every clickable element: cursor:pointer AND visible hover AND focus-visible state (never outline:none alone).
- Active/pressed states compress (scale .98) ; transitions 150–300ms on transform/opacity/color only.
- Forms: labels bound to inputs, inline validation messages, disabled submit while pending, success/error feedback visible without alert().

## Typography & layout discipline
- Line-height ≥1.5 body, ≤1.1 display; measure 45–75ch; avoid justified text.
- Fluid type via clamp(); spacing on a consistent scale; align to a grid — no magic numbers.

## Accessibility (non-negotiable)
- Contrast ≥4.5:1 body, ≥3:1 large text/icons — verify dark-mode variants too.
- Hit areas ≥44×44px; keyboard order follows visual order; skip-to-content link on multi-section pages.
- Images need alt; decorative images alt=""; form errors tied via aria-describedby; modals trap focus + Escape closes.
- prefers-reduced-motion disables nonessential animation.

## Performance & resilience
- Images: width/height set (no CLS), lazy-load below fold, modern formats; fonts: swap + preconnect, ≤2 families ≤4 weights.
- No layout shift from late-loading content; skeleton states beat spinners for >400ms waits.
- Mobile-first: test 360px; touch targets thumb-reachable; no hover-only affordances on touch.
