# Motion Design — Purposeful Choreography

Motion should make the site's idea clearer, more physical, or more memorable.
Decide what the motion means before deciding how to implement it. CSS, native
browser APIs, GSAP, ScrollTrigger, an existing framework, or another suitable
library are all valid choices when they serve the direction.

## Direction

- Let the subject, content, imagery, and layout determine the motion language,
  never a menu of generic effects applied evenly.
- Motion has a job: entrance establishes the page, scroll-linked interest keeps
  attention, a signature interaction makes the concept physical, hover gives
  feedback. If an animation has no job, cut it.
- One signature choreographed moment per page reads authored; ten scattered
  tweens read template.
- Preserve readable text, stable layout, responsive behavior, keyboard access,
  and prefers-reduced-motion. In reduced-motion mode, content is visible at
  first paint with no running JS or CSS animations.

## The motion plan

1. Name the one concept the motion should express (light arriving, depth being
   entered, a list being measured, a product being handled).
2. Choose where it matters most: the first viewport entrance and the single
   signature interaction. Everything else stays quiet or reveals gently.
3. Choreograph, don't sprinkle: groups stagger, sequences have a rhythm,
   easing is consistent (a spring or `power3.out`, not default linear).

## Choreography rules

- GSAP 3 only: `gsap.to/from/fromTo/timeline`; never TweenMax/TimelineLite/
  Power2. Register only the plugins used (ScrollTrigger, Flip, Observer,
  Draggable).
- Animate transform and opacity only (x, y, scale, rotation, opacity). Never
  top/left/width/height/margin when a transform achieves the same result.
- Every animation has teardown: `useGSAP()`/`gsap.context()` and `revert()`,
  remove ScrollTriggers, listeners, and timers on unmount or route change.
- ScrollTrigger: be explicit about trigger/target/start/end/scrub/pin and
  `pinSpacing`. Refresh after layout changes and dynamic content. No
  hard-coded measurements.
- Content is visible at first paint before any entrance runs; `immediateRender`
  and `autoAlpha` used so a failed JS load never hides content.
- `gsap.matchMedia()` for the reduced-motion branch: create nothing in reduce,
  and revert everything when exiting the branch.
- If the runtime cannot verify pixels, do one bounded DOM/computed-style check
  and finish; do not loop on unavailable vision. Check top, middle, and bottom
  of the page, not only the first viewport.

## Available capabilities

The environment can use GSAP when it genuinely elevates the result. Approved
runtime files are provided by the host when the typed design request declares
the capability. Do not install packages, download archives, or write files
under `vendor/` yourself.

- GSAP core — timelines, tweens, easing, choreography
- ScrollTrigger — scroll-linked animation, scrubbed sections, pinned moments
- Flip — smooth layout/state transitions
- Observer — native event normalization for scroll/drag/touch
- Draggable — drag interactions

Reference the host-provided local paths (for example,
`vendor/gsap/gsap.min.js`) rather than pointing the site at a CDN. Only the
plugins your design actually uses belong in the page. Counters and meters are
content decisions: if the intake calls for one, derive its range from the real
content model, never an arbitrary cap.