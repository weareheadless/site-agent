# GSAP performance

Prefer compositor-friendly transforms and opacity. Batch DOM reads before DOM
writes, avoid layout reads inside high-frequency callbacks, and do not create
per-frame work when a timeline or ScrollTrigger can express the same result.

Use will-change sparingly and remove it when the effect ends. Test real device
widths, long pages, image-heavy sections, and resize/orientation changes. A
visually impressive effect that causes overflow, jank, or inaccessible content
fails the design review.
