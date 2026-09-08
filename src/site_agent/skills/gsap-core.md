# GSAP core

Use the installed GSAP 3 package when motion needs runtime control, sequencing,
interruptibility, or coordinated transforms. Choose the tween or timeline
structure that serves the page's subject; the host does not provide motion
primitives or selectors.

Prefer transform and opacity/autoAlpha properties over layout mutation. Use
documented camelCase properties and valid GSAP 3 eases. Calculate responsive
values from the rendered layout instead of relying on brittle fixed pixels.

Every animation must have a visible static resting state, a deterministic
cleanup path, and a reduced-motion branch. Do not hide meaningful content until
JavaScript or a scroll trigger runs.
