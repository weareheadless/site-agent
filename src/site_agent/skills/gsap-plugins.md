# GSAP plugins

Use only plugins present in the frozen approved capability set. Register them
explicitly, use their documented GSAP 3 APIs, and keep plugin use subordinate
to the page concept rather than adding effects for decoration alone.

A plugin must degrade to a static, accessible state when it is unavailable or
when reduced motion is requested. Never load plugins from a CDN or dynamically
fetch executable code at runtime.
