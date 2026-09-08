# Changelog

## Unreleased

### Fixed

- Canonicalized motion-plan capability aliases before validation: `GSAP` maps to `core`, `Scroll Trigger` maps to `scrolltrigger`, and `React component` maps to `react`.
- Unknown model-generated motion capabilities now fail closed to `core`, while direct contract inputs remain strictly validated. The planner prompt now lists the supported capability values explicitly.
- Normalized additional provider shapes at the planner boundary, including motion page `output_path`, structured section purposes and action capabilities, and flat or structured reduced-motion fields.
- Rewrote provider-generated section IDs to host targets (`section-{index}`) and remapped action target, trigger, and bounds aliases before route validation.
- Visual review now requests structured output without DeepSeek reasoning consuming the completion budget, while safely accepting provider responses that place valid JSON in the reasoning channel.
- Local Astro visual-refinement runs now inherit the initial candidate's allowlist, build profile, approved toolchain, and manifest source mapping; failed deterministic refinement children can be retried explicitly.
- Deterministically ready candidates can now enter the explicit read-only visual review gate without a second build.

### Verification

- Focused design/planner/quality/service/builder tests: 77 passed.
- Full test suite: 789 passed, with one existing Starlette/httpx deprecation warning.
- `compileall`, `git diff --check`, and wheel build passed.
- Live refinement `design-4e3a9b5990e14df0bba536bf99fa801a` passed build, browser, content, conversion, manifest, motion, and parent-visual gates. The only deterministic finding is the existing warning for an unavailable `/articles.html` link; the explicit visual review completed and returned four repair suggestions, so the run remains `needs_repair` rather than fully review-ready.
