# Full LLM-Authored Design Pipeline

## Decision

The design engine must not contain a visual template, deterministic section
compiler, bounded layout vocabulary, host-authored CSS system, or host-authored
motion primitives. The implementation model owns the complete website source:

- information architecture and DOM;
- Astro pages, layouts, and React islands;
- CSS, typography, responsive behavior, and visual tokens;
- image placement, cropping, layering, and art direction; and
- GSAP timelines, ScrollTrigger choreography, plugins, cleanup, and reduced-motion behavior.

The host owns execution safety and lifecycle only: the immutable base commit,
the disposable worktree, approved toolchain capabilities, secrets, build and
browser execution, evidence, candidate identity, and owner approval. A
framework baseline is allowed only when it is nonvisual package/configuration
metadata. It must not contain markup, CSS, content, imagery, components, or a
default design language.

## Non-negotiable invariants

1. Every new design build uses the native OpenCode source-authoring path.
2. No initial build invokes a planner, section normalizer, visual compiler, or
   frontend scaffold.
3. The host never rewrites model-authored source or silently fills design
   tokens, fonts, colors, layout, or animation values.
4. New workspaces begin with a nonvisual framework/toolchain baseline.
5. Dependencies and fonts are exact, host-approved, and locally available;
   their use is free-form inside the source.
6. Owner media remains byte-identical and locally available to the model and
   candidate. The model decides how it is used.
7. GSAP is validated behaviorally in a browser, not by a host motion schema.
8. Visual review is grounded in the owner brief, source media, screenshots,
   runtime evidence, and the candidate source inventory.
9. Reused internal scaffold/template signatures block or return a candidate for
   repair; ordinary framework conventions do not.
10. Candidates remain immutable, local/non-publishable until explicit approval,
    and inspectable by durable run/session/transcript IDs.

## Work packages

### 1. Establish failing contract tests first

Add focused tests for native routing, nonvisual bootstrapping, arbitrary source
preservation, dependency/font policy, browser motion evidence, originality
checks, local-only candidate persistence, and approval-gated production merges.
Replace tests that require the local initial build to use the controlled
Astro/React compiler.

### 2. Remove the controlled visual implementation path

Remove the production path through:

- `hands/astro_react_builder.py`;
- `hands/astro_react_compiler.py`;
- `core/react_design_contracts.py`; and
- `frontend_scaffold/`.

Move only useful context and safety rules into the native source-authoring
path. Do not retain a configuration switch that can silently restore the fixed
compiler. Existing persisted compiler receipts remain readable for migration,
but new runs record native source-authoring evidence.

### 3. Route all design operations through OpenCode

Update `hands/builder.py`, `application/designs.py`, and
`application/design_lab.py` so initial builds, visual refinements, technical
repairs, and derived pages all use `NativeOpenCodeBuilder`. Preserve typed
request/target/receipt boundaries, durable statuses, transcripts, candidate
SHAs, preview identity, and approval behavior.

### 4. Replace the visual scaffold with a toolchain-only baseline

Replace the new-site initializer used by Intake Lab with an Astro/React
toolchain workspace containing only exact package/configuration metadata and
empty source/public/design directories. It must contain no homepage, layout,
CSS, tokens, copy, images, default fonts, placeholder pages, or decorative
components.

Keep existing customer repositories and legacy build profiles intact. Only
new from-scratch incubations use the new baseline.

### 5. Make framework and GSAP capabilities real

Retain an Astro/React build profile as a build contract, not a scaffold.
Provision exact versions of Astro, React, TypeScript, GSAP, `@gsap/react`, and
approved GSAP plugins. Let the model use normal package imports and author the
application source. No CDN or runtime network dependency is allowed.

Add an equivalent exact, self-hosted font capability for owner-supplied or
host-approved WOFF2 files. Missing requested fonts must be visible evidence,
not silently replaced by a host default.

### 6. Rewrite source-authoring instructions

Refactor `_design_prompt()` and `ADA_INSTRUCTIONS` in
`hands/opencode_runner.py`. Remove Pelican-specific homepage assumptions,
forced filenames, predetermined offsets/tokens, template references, and
worked examples. Keep only factual, safety, toolchain, accessibility,
responsive, reduced-motion, no-publish, and evidence contracts.

The coding model must inspect the supplied media, choose its own visual
direction, edit real source immediately, run the actual build, and make a
bounded evidence-driven repair pass when browser evidence exposes a concrete
problem.

### 7. Preserve visual evidence and media provenance

Materialize every approved website image as immutable local bytes, attach
bounded visual evidence to the vision-capable coding session, and provide
dimensions, focal metadata, dominant colors, and provenance as supplemental
evidence. Verify that the model did not modify owner media. Do not convert
image analysis into a replacement for the pixels.

### 8. Replace typed motion validation with behavioral validation

Remove the requirement for model-authored motion to match host-defined kinds,
selectors, or values. Keep static safety checks for approved imports,
unregistered plugins, external scripts, cleanup, and reduced-motion branches.

Extend Playwright evidence to wait for assets, inspect multiple scroll states,
exercise safe interactions, detect GSAP/ScrollTrigger activity, compare visual
state before and after interaction, and verify reduced-motion behavior. Treat
`document.getAnimations()` as CSS/WAAPI evidence only; it is not proof that
GSAP ran.

### 9. Ground visual review and detect reuse

Give visual review the original brief, approved source images, skill receipt,
all required viewport/scroll screenshots, font/image evidence, motion evidence,
and changed-source inventory. Findings must cite concrete evidence.

Add an originality gate based on internal scaffold fingerprints, normalized DOM
and CSS structure, and bounded screenshot perceptual similarity. It detects
reuse; it does not prescribe a replacement design.

### 10. Simplify the acceptance manifest

Keep the host-generated manifest factual: run/base/candidate identity, intake
hash, build profile, routes, approved capabilities, skill hash, changed source
files, owner-media hashes, and evidence hashes. Remove fields that imply the
host controls tokens, sections, shell structure, variation points, or motion
choreography.

## Implementation order

1. Add failing tests and the toolchain-only workspace contract.
2. Change routing so no new build can enter the controlled compiler.
3. Implement the nonvisual Astro/React baseline and build setup.
4. Update dependency/font capabilities and native prompt contracts.
5. Add arbitrary-source validation and factual native manifests.
6. Add behavioral GSAP/browser evidence.
7. Add originality and grounded visual-review gates.
8. Remove dead compiler/scaffold code and migrate focused tests.
9. Run the full test suite, compileall, wheel build, and one real local Intake
   Lab build with supplied media.

## Completion criteria

- `frontend_scaffold/` and the controlled design builder/compiler are no longer
  reachable from new design builds.
- A new workspace has no visual implementation before OpenCode edits it.
- The model's Astro, React, CSS, font, image, and GSAP source is preserved as
  authored, without host normalization.
- Browser evidence proves the actual interaction behavior and reduced-motion
  fallback.
- Reused internal templates cannot become reviewable candidates.
- Preview remains mounted under `/ada/`.
- Production remains unchanged until explicit owner approval.
