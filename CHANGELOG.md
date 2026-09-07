# Changelog

## Unreleased

### Fixed

- Canonicalized motion-plan capability aliases before validation: `GSAP` maps to `core`, `Scroll Trigger` maps to `scrolltrigger`, and `React component` maps to `react`.
- Unknown model-generated motion capabilities now fail closed to `core`, while direct contract inputs remain strictly validated. The planner prompt now lists the supported capability values explicitly.

### Verification

- Focused motion/planner tests: 31 passed.
- Full test suite: 779 passed, with one existing Starlette/httpx deprecation warning.
- `compileall`, `git diff --check`, and wheel build passed.
