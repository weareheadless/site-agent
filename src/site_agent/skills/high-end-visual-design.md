# High-End Visual Design — Agency-Grade Taste

Engineer the page like it is a $150k agency build: haptic depth, cinematic
spatial rhythm, obsessive micro-interactions, and flawless motion. Expensive =
restraint, precision, and one confident gesture.

## Anti-patterns that instantly fail

- Banned fonts: Inter, Roboto, Arial, Open Sans, Helvetica as the character
  choice. Use a considered pairing (a characterful display + a quiet body).
- Banned icons: thick-stroked default sets. Use one consistent, fine,
  precise-stroke system.
- Banned borders/shadows: 1px solid gray borders; harsh dark drop shadows
  (`shadow-md`, `rgba(0,0,0,.3)`). Depth from surface layering or one soft
  large-radius shadow `(0 20px 60px rgba(0,0,0,.12))`.
- Banned layouts: edge-to-edge sticky bar glued to the top, symmetrical
  three-column grids without massive whitespace, generic centered hero stacks.
- Banned motion: default linear/ease-in-out transitions, instant state changes,
  everything animating the same way.

## Conscious direction selection

Choose one vibe and one layout archetype and commit:

- Vibe — Ethereal Glass (deep black, radial glow, heavy backdrop-blur, hairline
  white/10 borders); Editorial Luxury (warm cream, variable serif display,
  subtle grain); Soft Structuralism (silver/white, massive grotesque type,
  soft diffused shadows).
- Layout — Asymmetrical Bento (masonry grid of varied card sizes); Z-Axis
  Cascade (physical cards with slight rotation/overlap); Editorial Split
  (massive type left, interactive imagery right).
- Every archetype collapses to a single flowing column below 768px: `w-full`,
  generous gaps, no rotation or negative margins.

## The double-bezel (nested architecture)

Never place a key card, image, or container flat on the background. Wrap it in
a shell: an outer surface with a hairline border and a specific padding, an
inner core with its own background, inner highlight
`(inset 0 1px 1px rgba(255,255,255,.15))`, and a concentric radius
(`rounded-[calc(2rem-0.375rem)]` inside a `2rem` shell). It reads as machined,
not flat.

## CTA and island buttons

- Primary buttons are fully rounded pills with generous padding and a nested
  trailing-icon circle fully flush inside the right inner edge.
- Hover: the inner icon translates diagonally and scales slightly; the button
  presses (`active:scale(.98)`); borders/color shift — never a bare color swap.
- Eyebrow tags: microscopic pill badges (`10px`, `tracking .2em`, uppercase)
  before major headings.

## Spacing is the luxury

- Double the whitespace you think you need between sections; halve the number
  of elements per section. `py-24` to `py-40` sections.
- Optical alignment beats mathematical: center icons in circles optically,
  nudge caps-height to baseline, hang punctuation on display type.

## Color like money

- Near-black ink on warm off-white (or deep navy/space-black with ivory), ONE
  metallic/gem accent used <5% of the page. Never #000/#fff pairs, never
  saturated primary backgrounds behind body text.
- Grain/noise at 3–5% opacity unifies flat gradients into printed surfaces.

## Motion choreography

- Springs and custom curves, never linear/ease-in-out except by design.
- Scroll reveals: heavy fade-up (`translate-y-16 blur-md → none`) over 800ms+
  via IntersectionObserver/ScrollTrigger, staggered. Elements never appear
  statically when the concept calls for choreography.
- Animate transform+opacity only, `will-change` sparingly. `backdrop-blur`
  only on fixed/sticky chrome. No animation of top/left/width/height.
- One signature choreographed moment (entrance, scrub, or reveal) and quiet
  everywhere else.

## Imagery and texture

- Consistent treatment across photography (same filter/duotone/grain). One
  full-bleed hero image beats four thumbnails.
- Photography carries luminance — never bury it under heavy dark scrims that
  hide what the image shows.
- Letterspaced uppercase mono labels, hairline rules, one grain overlay max,
  tabular figures for numbers.

## Final pass

- One typeface pairing executed with discipline; one radius language; one
  accent; one signature gesture.
- The page reads as an authored artifact, not a template with nice fonts.