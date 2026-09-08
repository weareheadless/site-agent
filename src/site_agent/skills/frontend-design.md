# Frontend Design — Distinctive Visual Craft

Make it distinctive, purposeful, memorable, and correct. This is the craft
layer: how to make choices that read as authored rather than assembled.

## Direction over decoration

- Commit to ONE clear visual idea (a mood, era, material, or motion language)
  and carry it through every element. The idea comes from the brief's subject —
  a cave site and a sanitary-ware site must not share a default.
- Choose an unapologetic aesthetic and execute it completely: luxury/refined
  with whitespace and a characterful display face; playful with saturated
  shapes and weight; retro with period type and grain; brutalist with stark
  hierarchy; organic with hand-drawn accents. Half-committing reads as default.
- If you reach for interlocking sans-serifs, purple-on-white gradients, or a
  centered logo over a stock hero, you are on the default path. Stop and make
  a specific choice instead.

## Composition

- Establish an intentional layout system before styling components: a grid,
  a white-space scale, a section rhythm, a breakpoint behavior. No magic
  numbers that appear once.
- Asymmetry beats sameness: offset headers, pulled media, alternating
  densities, one deliberate full-bleed moment. Centered-stacked is the default;
  use it only when it is the idea.
- Give the first viewport a thesis: one strong opening (headline, image,
  demo, or interaction) that states what the site is about, then let the rest
  of the page earn attention in order.

## Type

- Display faces with character for headings (Cormorant, Fraunces, Clash
  Display, a subject-fitting grotesque); quiet workhorses for body. Do not mix
  two loud families.
- Extreme scale contrast is drama: `clamp(64px,10vw,148px)` display against
  13px letter-spaced mono captions beats polite mid-sizes.
- Set a real type scale with intentional weights and optical spacing; body
  measure 45–75ch; headings tight (≤1.1).

## Color

- Dominant color + sharp accent + generous neutrals. One gradient MAX, only if
  it serves the idea.
- Color is light and atmosphere, not decoration: use it to direct the eye to
  the primary action and to give surfaces depth.
- Dark themes: raise saturation slightly so color stays legible and luminous;
  light themes: deepen text contrast. Never pure #000/#fff pairs.
- Borders and hairlines are rgba() at 12–18% opacity, never solid gray.

## Space & rhythm

- Whitespace is a feature. Section padding 120px+ desktop / 72px mobile on a
  consistent 8px scale.
- Alternate full-bleed and contained moments. Vary density so the page
  breathes: a dense list after an empty hero, a quiet plate between loud
  sections.

## Motion

- One signature interaction (hover-lift cards, scroll-reveal stagger, magnetic
  buttons, a scrub) 300–700ms with a spring-like curve (`cubic-bezier(.32,.72,0,1)`
  or GSAP's `power3.out`). Motion must support the idea, not decorate it.
- Animate opacity+transform only. Staggered reveals for groups, not one
  opacity pulse on everything.
- Under prefers-reduced-motion, content shows immediately and no animation or
  transition runs.

## Details that signal craft

- Real content from the brief, never lorem ipsum. Real imagery (or a tasteful,
  subject-fitting abstract), never gray boxes.
- Micro-labels in letter-spaced uppercase; numbered or labeled structure only
  when the content is genuinely sequential.
- One consistent radial/radius language; one icon set at one stroke weight;
  hairlines where separation is needed, never heavy borders.
- Footer and small states carry the same care as the hero.

## Self-critique before finishing

- Is there a single subject-specific idea, visibly alive on desktop and mobile?
- Does the strongest element get the most contrast, size, and whitespace?
- Could swapping the copy to another business leave the layout unrecognizable?
  If not, push the concept further.