# GSAP with React and Astro

Scope React animation to the component lifecycle. Prefer the approved
`@gsap/react` integration when available; otherwise use a scoped GSAP context
and revert it on unmount. Do not create timelines during server rendering.

Keep refs and selectors local to the component, avoid global selectors that
can collide across islands, and tear down listeners, observers, timelines, and
ScrollTriggers when the island unmounts or its route changes.

Preserve a meaningful non-JavaScript and reduced-motion rendering state before
the island hydrates.
