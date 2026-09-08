# GSAP ScrollTrigger

Use ScrollTrigger only when scroll position is part of the page's concept. Each
trigger must have an intentional target, start/end relationship, scrub or pin
decision, responsive behavior, and cleanup path.

Refresh after fonts, images, or layout-dependent content is ready. Avoid
permanent debug markers, unexplained pinning, scroll hijacking, or triggers that
make required content inaccessible. Test the top, middle, and bottom of every
required route at desktop and mobile widths.

Reduced-motion mode must not create or start nonessential ScrollTriggers.
