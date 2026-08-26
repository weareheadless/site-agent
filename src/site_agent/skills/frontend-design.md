# Frontend Design (condensed from anthropics/skills)

Make it distinctive, purposeful, and memorable — never generic.

## Direction over decoration
- Commit to ONE clear visual idea (a mood, era, material, or motion language) and carry it through every element.
- Choose an unapologetic aesthetic: luxury/refined with whitespace and serif display type; playful/toy-like with saturated rounds; retro with vintage fonts and grain; minimalist/brutalist with monochrome and stark hierarchy; organic with hand-drawn accents.
- If you must use interlocking sans-serifs or purple-on-white gradients, you have failed the brief.

## Type
- Display faces with character for headings (Cormorant, Fraunces, Clash Display); quiet workhorses for body.
- Extreme scale contrast is drama: clamp(64px,10vw,148px) against 13px mono captions beats polite mid-sizes.

## Color
- Dominant color + sharp accent + generous neutrals. One gradient MAX, and only if it serves the idea.
- Dark themes: raise saturation slightly; light themes: deepen text contrast.

## Space & rhythm
- Whitespace is a feature. Section padding 120px+ desktop / 72px mobile; consistent 8px scale.
- Full-bleed moments alternate contained ones; asymmetry (1fr/.9fr grids, offset imagery) beats centered sameness.

## Motion
- One signature interaction (hover-lift cards, scroll-reveal stagger, magnetic buttons), 300–700ms cubic-bezier(.32,.72,0,1).
- Animate opacity+transform only. Respect prefers-reduced-motion.

## Details that signal craft
- Real content, never lorem ipsum. Real imagery (or tasteful abstract), never gray boxes.
- Micro-labels in letterspaced uppercase mono; hairline borders rgba(); one grain/noise overlay max.
