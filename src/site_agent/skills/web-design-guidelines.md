# Web Design Guidelines — Correctness Checklist

Interactivity, accessibility, performance — the checklist every page must pass.
Run it before finishing; a beautiful page that fails here is not done.

## Interaction & feedback

- Every clickable element: `cursor:pointer`, a visible hover state, and a
  visible focus-visible state (never `outline:none` alone).
- Active/pressed states compress (`scale(.98)`); transitions 150–300ms on
  transform/opacity/color only.
- Forms: labels bound to inputs (`for`/`id` or wrapping), inline validation,
  disabled submit while pending, success/error feedback visible without
  `alert()`.
- Links and buttons state exactly what they do, and the vocabulary is
  consistent through the flow (what says "Publish" stays "Publish").

## Typography & layout discipline

- Line-height ≥1.5 body, ≤1.1 display; measure 45–75ch; avoid justified text.
- Fluid type via `clamp()`; spacing on a consistent scale; align to a grid —
  no magic numbers that appear once.
- Fluid `type` and `space` tokens shared across sections; breakpoints
  deliberate, not incremental.

## Accessibility (non-negotiable)

- Contrast ≥4.5:1 body, ≥3:1 large text/icons — verify dark-mode and
  translucent variants too.
- Text contrast is checked against the actual painted background. If text sits
  on an image, it needs a sufficient scrim — never rely on a soft layer alone.
- `background-clip: text` gradient headlines: the visible painted color is what
  must pass contrast. Always provide a solid `color` fallback so that if the
  gradient or clip fails, the text is still legible and never
  `rgba(0,0,0,0)`.
- Hit areas ≥44×44px; keyboard order follows visual order; skip-to-content
  link on multi-section pages.
- Images need meaningful alt (decorative images `alt=""`); form errors tied
  via `aria-describedby`; dialogs trap focus and Escape closes; focus is
  visible and not only `:focus-visible` where keyboard users need it.
- `prefers-reduced-motion` disables nonessential animation and leaves content
  visible immediately.
- Landmarks (`header`, `nav`, `main`, `footer`) present; exactly one `h1`.

## Performance & resilience

- Images: `width`/`height` set (no CLS), lazy-load below fold, modern formats.
- Fonts: `font-display: swap`, ≤2 families, ≤4 weights.
- No layout shift from late-loading content; skeleton states beat spinners for
  >400ms waits.
- Mobile-first: test 360px; touch targets thumb-reachable; no hover-only
  affordance on touch.
- The real candidate build must succeed and every required route must produce
  its output before the page is considered done.

## Empty and failure states

- Empty screens are an invitation to act, not a void: one clear next step.
- Errors explain what went wrong and how to fix it in the interface's voice —
  never vague, never accusatory, never silent.