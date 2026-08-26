# Motion Design

Motion should make the site's idea clearer, more physical, or more memorable.
Decide what the motion means before deciding how to implement it. CSS, native
browser APIs, GSAP, ScrollTrigger, an existing framework, or another suitable
library are all valid choices when they serve the direction.

## Direction

- Let the subject, content, imagery, and layout determine the motion language.
- A signature interaction is an opportunity, not a quota. Use one when it makes
  the experience more distinctive; do not invent a gimmick to satisfy a rule.
- If the site already has a motion system, understand and extend it rather than
  introducing a competing abstraction.
- Preserve readable text, stable layout, responsive behavior, keyboard access,
  and prefers-reduced-motion behavior.

## Available capabilities

The environment can use GSAP when it genuinely elevates the result. Nothing is
pre-installed; you install what you need yourself — you have a shell (bash) and
can fetch files with `curl`, so self-hosting is fully in your hands.

- GSAP core — timelines, tweens, easing, choreography
- ScrollTrigger — scroll-linked animation, scrubbed sections, pinned moments
- Flip — smooth layout/state transitions
- Observer — native event normalization for scroll/drag/touch
- Draggable — drag interactions

Self-hosting pinned builds in `vendor/` is the preferred install for this
static site (no build step, `package.json` is protected). Download exactly the
files your concept uses, e.g.:

```bash
mkdir -p vendor/gsap
curl -sSL -o vendor/gsap/gsap.min.js https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js
curl -sSL -o vendor/gsap/ScrollTrigger.min.js https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/ScrollTrigger.min.js
```

Reference them locally (`vendor/gsap/gsap.min.js`) rather than pointing the
site at a CDN. Only the plugins your design actually uses belong in the page.