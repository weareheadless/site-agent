# Brand-Led Composition and Generative Behavior System Implementation Plan

## Status

Proposed implementation plan. This plan changes design planning, realization,
and review without changing the owner approval or production publishing rules.

## Purpose

Make Ada use its control of source code as a creative advantage rather than as
a faster way to reproduce ordinary CMS layouts and entrance effects.

The implementation has two goals:

1. Treat logos and owner media as structural inputs to the composition, so the
   brand identity propagates from the supplied evidence into layout, type,
   color, image treatment, and interaction.
2. Derive and implement a business-specific behavioral world for every design
   without hardcoding industry motifs, page templates, or named animation
   recipes into the application.

The system must remain capable of designing for any legitimate business type.
Generic host code defines contracts, evidence, constraints, and review gates.
Run-specific specialists derive the visual and behavioral decisions from the
owner's context and approved media. The implementation agent writes the bespoke
source for that one candidate.

## Core Answer

### How assets become composition

An asset is integral only when the design records and realizes a relationship
between that asset and the rest of the page. Merely rendering an image does not
meet that requirement.

Each selected asset must contribute one or more of:

- geometry: silhouette, aspect ratio, optical bounds, negative space, edge
  rhythm, or focal axis;
- visual language: palette, contrast, line weight, texture, material, corner
  behavior, or typographic character;
- meaning: subject, emotion, credibility, sequence, place, product detail, or
  conversion evidence;
- behavior: how an element reveals, responds, transitions, or anchors attention.

The composition plan must state which contribution is being used and where it
appears. Every major asset assignment needs a responsive treatment and a reason
grounded in evidence.

Logos need special handling. Their file rectangle is not their optical shape.
The system must measure transparent or background whitespace, visible-mark
bounds, aspect ratio, visual mass, and safe contrast before deciding its size or
header footprint. Header composition must reserve space for the optical logo
bounds and verify its relationship to navigation and actions at every viewport.

### How brand physics remains generic

Do not hardcode cave effects, property effects, fabric effects, sanitary-product
effects, or any other industry vocabulary in Python, configuration defaults, or
global prompts.

Hardcode only a domain-neutral behavioral grammar:

- evidence sources;
- conceptual entities;
- state variables;
- forces and relationships;
- input signals;
- output channels;
- scenes and transitions;
- invariants and fallbacks;
- observable acceptance conditions.

A specialist derives values for that grammar from the current business,
audience, copy, media, owner preferences, and technical capabilities. The
implementation agent then creates ad-hoc code for the selected behavior system.
The output can use CSS, SVG, Canvas, WebGL, GSAP, browser APIs, or ordinary DOM
logic when those capabilities are approved. There is no catalogue of reusable
branded effects that the model merely selects from.

This separates:

```text
generic application architecture
        from
run-specific creative laws
        from
candidate-specific source code
```

## Product Principle

The website should not be a neutral page decorated with brand assets and motion.
It should behave as if it belongs to the business's own world.

The system therefore needs to answer three questions before source mutation:

1. What visual grammar is already present in the owner's identity and media?
2. What single behavioral law can organize attention and interaction for this
   particular business and audience?
3. Which part of the final experience proves that this law was implemented and
   could not be transferred unchanged to an unrelated business?

## Required Invariants

All invariants in `AGENTS.md` remain in force. In particular:

- A generated website remains a candidate or pending draft.
- Production changes only through explicit owner approval.
- Visual candidates are reviewed in the Design tab; no raw preview link replaces
  that flow.
- Preview paths remain correct under `/ada/`.
- Design jobs, phase artifacts, provider identities, and candidate SHAs remain
  durable and inspectable.
- Site-specific assumptions belong in captured instance context, not generic
  validators or service code.
- HTTP and MCP adapters call application services and typed contracts.
- Planning specialists are read-only.
- Only designated realization specialists receive repository write access.
- Prompts contain contracts and behavioral rules, not worked examples, canned
  replies, sample questions, or preselected creative language.
- Deterministic validation checks measurable facts. It does not pretend to
  measure taste or originality.
- A failed creative or behavioral gate cannot become reviewable.
- Automatic repair remains finite and cannot recursively invent a new direction.

Add these design invariants:

- The selected logo and media plan is frozen before implementation.
- Every selected asset is identified by stable ID and content hash.
- A logo may not share unverified layout space with navigation or a primary
  action at any required viewport.
- Critical content is complete in the resting state before JavaScript runs.
- Reduced-motion mode preserves the concept's meaning without spatial motion.
- One signature behavior is required; scattered generic effects are not a
  substitute.
- The signature behavior must cite business, audience, copy, or media evidence.
- A concept that passes unchanged under an unrelated-business counterfactual is
  rejected before implementation.

## Non-Goals

- No universal page-template library.
- No industry-to-animation lookup table.
- No host-side classifier that selects a creative style.
- No fixed set of hero effects, reveal effects, cursor effects, or scroll scenes.
- No requirement that every site use GSAP, Canvas, WebGL, or heavy motion.
- No generated motion merely to demonstrate technical capability.
- No automatic alteration of owner logos or source images.
- No generative image editing in the initial implementation.
- No subjective originality score inside deterministic validators.
- No multi-round autonomous ideation loop.
- No publication outside the existing approval service.

## Current Failure Mode

The present pipeline has useful safety and durability, but the creative boundary
is too loose:

- `MediaAnalysis` describes assets but does not describe optical logo geometry,
  compositional affordances, or page-level relationships.
- `PageBuildRequest` carries asset IDs and paths but no frozen asset-to-region
  composition plan.
- `SpecialistDesignCoordinator._brief()` exposes media paths, not normalized
  semantic and geometric evidence.
- `CreativeConcept` and `DesignPlanBundle` bind phase envelopes but accept
  unvalidated generic payload dictionaries.
- the implementation agent can silently make media-selection, crop, layout, and
  behavior decisions while writing source;
- the motion phase is asked to add purposeful motion after implementation, which
  encourages effects layered onto a composition rather than behavior that shapes
  the composition;
- screenshot review emphasizes static pages and cannot reliably assess temporal
  choreography;
- deterministic checks detect overflow but do not verify optical logo clearance,
  focal-point preservation, or fidelity to a frozen composition decision;
- `generic_template_signals` exists in visual review, but there is no mandatory
  transfer test or signature-behavior evidence.

The result can pass technical and visual gates while the logo overlaps the menu,
the images feel inserted, and the motion remains interchangeable.

## Target Architecture

```text
Validated intake + frozen context + approved media
                         |
                Asset evidence builder
             deterministic + vision evidence
                         |
                 Brand source map
        identity grammar + media affordances
                         |
               Copy and concept agents
                         |
                  Creative director
                         |
        +----------------+----------------+
        |                                 |
Composition contract              Behavior contract
asset relationships               physical law + scenes
        |                                 |
        +----------------+----------------+
                         |
                Locked experience plan
                         |
             One integrated realization pass
                         |
       Deterministic + visual + temporal evidence
                         |
          Creative, experience, technical review
                         |
              One bounded fidelity repair
                         |
                 Design-tab proposal
```

The composition and behavior contracts are selected together. Motion is not a
post-processing layer. A separate motion specialist may refine implementation,
but it must implement the locked behavior contract rather than invent effects.

## New Typed Contracts

Add provider-neutral contracts to
`src/site_agent/core/design_contracts.py`. Use strict `from_dict()` validation,
unknown-field rejection, bounded lists, safe paths, and canonical content hashes.

### `AssetVisualEvidence`

One record per approved image or logo:

- `asset_id`
- `asset_sha256`
- `relative_path`
- `media_role`: logo, identity mark, photograph, illustration, texture, document,
  or unknown
- `pixel_width`, `pixel_height`, `aspect_ratio`
- `has_alpha`
- `optical_bounds`: normalized visible-content rectangle
- `optical_center`: normalized visual center
- `visual_mass`: normalized coarse occupancy map or bounded summary
- `safe_backgrounds`: light, dark, mixed, or unknown
- `minimum_legible_size`: optional measured or conservative bound
- `dominant_colors`
- `contrast_edges`
- `focal_regions`: bounded normalized regions with confidence
- `negative_space_regions`: bounded normalized regions with confidence
- `semantic_description`
- `subjects`
- `materials_and_textures`
- `emotional_tone`
- `brand_signals`
- `quality_constraints`
- `evidence_sources`: deterministic, vision, owner note, or approved knowledge
- `confidence`

Deterministic fields must not be overwritten by vision output. Vision may enrich
semantic fields and identify likely focal or negative-space regions, with its
provider and model persisted.

### `BrandSourceMap`

The evidence-backed visual grammar inferred from selected assets and owner
context:

- `identity_assets`
- `primary_brand_signals`
- `geometry_vocabulary`
- `spacing_rhythm`
- `line_and_edge_language`
- `color_relationships`
- `type_relationship_hypotheses`
- `material_relationships`
- `image_treatment_hypotheses`
- `signals_to_preserve`
- `signals_not_safe_to_infer`
- `owner_evidence_refs`
- `asset_evidence_refs`
- `confidence_by_signal`

This is a hypothesis artifact, not authority. It may derive design direction from
approved assets, but it may not alter the logo, invent brand claims, or override
explicit owner preferences.

### `AssetCompositionPlan`

One frozen assignment for each selected asset:

- `asset_id` and `asset_sha256`
- `narrative_role`
- `page_regions`
- `relationship_to_copy`
- `relationship_to_other_assets`
- `structural_contribution`
- `crop_policy`
- `focal_region_to_preserve`
- `negative_space_usage`
- `layering_and_overlap_policy`
- `background_and_contrast_policy`
- `desktop_treatment`
- `tablet_treatment`
- `mobile_treatment`
- `loading_priority`
- `accessibility_intent`
- `prohibited_uses`
- `acceptance_conditions`
- `evidence_refs`

For logos, require an additional `LogoCompositionRule`:

- optical size rather than file-box size;
- clear-space requirement;
- allowed background states;
- relationship to navigation and actions;
- breakpoint-specific disposition;
- minimum and maximum optical size;
- collision exclusions;
- whether the logo is a quiet signature, dominant composition anchor, or both in
  different regions.

### `BrandBehaviorSystem`

This is the domain-neutral physical-law contract. It describes meaning and
relationships, not framework calls.

- `thesis`: the single behavioral idea
- `business_relevance`
- `audience_effect`
- `evidence_refs`
- `conceptual_entities`
- `state_variables`
- `input_signals`
- `forces_and_relationships`
- `output_channels`
- `scene_graph`
- `signature_behavior`
- `utility_behaviors`
- `narrative_behaviors`
- `resting_state`
- `no_javascript_translation`
- `reduced_motion_translation`
- `mobile_translation`
- `keyboard_and_focus_behavior`
- `performance_budget`
- `interruption_and_resize_behavior`
- `allowed_implementation_capabilities`
- `prohibited_generic_effects`
- `observable_acceptance_conditions`
- `transfer_test`

Nested records should remain generic:

- A state variable names a concept, range, initial value, and semantic meaning.
- An input signal names a browser or content signal and maps it to state.
- A force relates entities or states without naming a library implementation.
- An output channel identifies what may change: transform, clipping, typography,
  color, light, SVG geometry, canvas rendering, content emphasis, navigation, or
  another bounded browser-rendered property.
- A scene binds content regions, state changes, and exit conditions.
- Acceptance conditions identify evidence the host or reviewers can observe.

Do not create an executable DSL or eval arbitrary expressions. This contract is a
typed creative specification consumed by a coding agent. Any formulas are prose
or bounded numeric mappings that the implementation agent translates into safe
source.

### `ExperiencePlanBundle`

Replace the untyped creative-selection payload with a strict bundle containing:

- selected concept identity;
- final copy-deck hash;
- brand-source-map hash;
- asset-composition plan;
- brand behavior system;
- layout and typography plan;
- responsive composition plan;
- protected strengths;
- variation points;
- implementation risks;
- counterfactual transfer verdict;
- review rubric;
- all input artifact hashes.

Keep `DesignPlanBundle` as the persisted phase envelope for compatibility, but
require its `payload` to parse as `ExperiencePlanBundle` for new specialist runs.

### `TemporalExperienceEvidence`

Persist review evidence for behavior:

- candidate SHA;
- experience-plan hash;
- route and viewport;
- reduced-motion state;
- interaction script identity;
- before, intermediate, and after screenshots;
- bounded video or frame-sequence reference when available;
- computed layout shifts;
- console and network errors;
- animation/interaction state observations;
- keyboard path observations;
- resting-state observations;
- evidence hash.

Screenshots, videos, browser traces, and generated worktrees remain local runtime
artifacts and must not be committed.

## Asset Evidence Pipeline

### Deterministic extraction

Add a narrow image-evidence provider under `hands/` that receives approved local
media bytes and returns measurable facts:

- dimensions and aspect ratio;
- alpha presence;
- alpha or background-trimmed optical bounds;
- optical center and coarse visual-mass distribution;
- dominant palette and contrast distribution;
- conservative logo background compatibility where measurable;
- perceptual hash for duplicate detection;
- image sharpness and effective-resolution constraints.

The provider must not decide layout or mutate assets.

For non-transparent logos, background trimming should be conservative. If the
boundary cannot be identified confidently, mark optical bounds unknown and make
the composition specialist handle it explicitly rather than guessing.

### Semantic extraction

Extend the existing media-analysis path instead of creating another upload or
vision subsystem. Preserve existing `MediaAnalysis` compatibility while adding a
versioned design-evidence analysis that can identify:

- likely asset role;
- meaningful subjects and focal regions;
- negative-space regions;
- material and geometric signals;
- visual tone;
- likely brand-significant details;
- unsafe assumptions;
- compositional constraints.

Run this once per normalized asset and analysis version. Reuse it across design
runs. A design run freezes the exact records and hashes it consumed.

### Evidence assembly

During `DesignService.capture_context_snapshot()`:

- resolve only approved, ready assets bound to the request;
- include normalized `AssetVisualEvidence` records in the snapshot;
- record unavailable or low-confidence evidence explicitly;
- preserve owner ordering and usage restrictions;
- never persist signed URLs;
- hash the final snapshot before planning.

## Specialist Workflow

Update `SpecialistDesignCoordinator.create_plan()` so the finite graph becomes:

1. Copy deck and brand-source analysis may run in parallel after evidence is
   frozen.
2. Three independent concept agents receive the same factual brief,
   `AssetVisualEvidence`, and `BrandSourceMap`.
3. Each concept must propose both an asset composition and a behavioral law.
4. The creative director selects or synthesizes at most two concepts and emits
   one strict `ExperiencePlanBundle`.
5. A dedicated adversarial critic performs the counterfactual transfer test on
   the locked plan before repository mutation.
6. Only a plan that passes proceeds to realization.

### Concept requirements

Each `CreativeConcept` payload must include:

- central idea;
- first-viewport composition;
- exact asset assignments;
- logo integration strategy;
- asset-derived visual grammar;
- proposed behavioral thesis;
- one signature behavior;
- narrative and utility behavior separation;
- responsive and reduced-motion translations;
- feasibility and performance risks;
- evidence references;
- transfer-test prediction.

Concept agents remain independent and read-only. They may not inspect one
another's output or ask for additional concepts.

### Counterfactual transfer test

The critic asks whether the composition and behavior would remain coherent and
equally appropriate if the business facts, media, and identity were replaced by
an unrelated context.

The result is a typed judgment with:

- `state`: passed or rejected;
- transferable elements;
- evidence-specific elements;
- unsupported metaphors;
- generic interaction signals;
- required corrections;
- plan hash.

This is a creative review, not a host-side keyword heuristic. Rejection returns
the run to the creative director for one bounded correction of the existing
selection, not another concept round.

## Realization Workflow

### Integrated implementation

The implementation agent receives:

- immutable factual request;
- final copy deck;
- asset visual evidence;
- locked asset composition plan;
- locked brand behavior system;
- approved capability registry;
- current repository and build target.

Its responsibility is to invent the candidate-specific implementation. It may
create custom SVG paths, Canvas scenes, shaders, procedural layouts, animation
timelines, content-aware masks, or DOM interactions when justified and allowed.
It must not select from a host-owned set of aesthetic presets.

The agent must return an `ImplementationReport` containing:

- plan hash;
- files changed;
- asset assignment realization map;
- logo-rule realization map;
- behavior-system realization map;
- implementation deviations and reasons;
- runtime capabilities used;
- no-JS and reduced-motion implementation locations;
- checks run.

### Motion specialist

Retain the motion phase only as a fidelity specialist. Change its contract from
“add purposeful motion” to:

- inspect the locked behavior system and existing realization;
- implement missing behavior-law mappings;
- tune choreography and interruption handling;
- remove generic or contradictory effects;
- preserve composition and content;
- report exact behavior coverage and deviations.

It may not introduce a second behavioral concept.

### Complexity budget

The creative director defines a per-run complexity budget from approved
capabilities and user value. It should identify:

- one signature behavior;
- no more than two supporting narrative behaviors by default;
- required utility motion;
- performance ceiling;
- unsupported or unnecessary technologies.

Minimal sites can satisfy the system through bespoke spatial, typographic, or
state behavior without continuous animation. Technical spectacle is not a goal.

## Review and Validation

### Deterministic composition gates

Extend `hands/design_quality.py` and `hands/playwright_quality.py` only with
measurable checks:

- every planned asset exists and matches its frozen hash;
- planned assets appear in their required route and region;
- rendered images meet effective-resolution constraints;
- focal regions remain visible within the declared tolerance;
- no unapproved asset substitutions or external image requests occur;
- logos meet minimum optical size and background-contrast rules when measurable;
- logo, navigation, and primary action bounding boxes do not intersect;
- declared clear-space exclusions are respected at desktop, tablet, and mobile;
- critical content is visible before JavaScript executes;
- reduced-motion mode has no prohibited spatial or continuous motion;
- layout shift, console errors, and network failures remain within policy;
- keyboard focus reaches every required interaction;
- required behavior instrumentation markers or observable states exist.

The browser adapter should record bounding boxes and computed styles for named
composition roles. Tests should use role contracts, not site-specific selectors.

### Sighted composition review

Extend `hands/design_visual_review.py` so the reviewer receives:

- source assets;
- `BrandSourceMap`;
- frozen `AssetCompositionPlan`;
- rendered viewport evidence;
- deterministic geometry results.

The review must separately judge:

- whether identity appears to originate from the supplied brand evidence;
- whether the logo participates in the composition rather than floating in a
  reserved corner;
- whether photographs carry narrative or structural responsibility;
- crop and focal-point quality;
- responsive integrity;
- asset hierarchy and repetition;
- compositional collisions missed by mechanical checks;
- generic-template leakage.

### Temporal behavior review

Add a browser evidence pass that exercises the locked scene graph:

- initial resting state;
- scroll checkpoints;
- pointer or touch behavior where declared;
- keyboard and focus behavior;
- resize or orientation change;
- reduced motion;
- no JavaScript;
- interruption and rapid-scroll behavior.

Reviewers receive frame sequences or bounded recordings with the behavior system
and acceptance conditions. They judge:

- whether behavior communicates the thesis;
- whether the signature interaction is recognizable and coherent;
- whether supporting behavior strengthens rather than competes with it;
- whether timing and transitions feel authored;
- whether the behavior remains usable and understandable;
- whether the experience would be equally valid for an unrelated business.

Static screenshot review alone cannot pass the signature-behavior gate.

### Repair policy

Consolidate findings into one bounded repair brief. Repair may correct:

- composition-plan deviations;
- logo collisions or optical scale;
- crop/focal failures;
- behavior-system omissions;
- temporal quality defects;
- accessibility or performance defects.

Repair may not replace the selected concept, invent a new physical law, swap
approved media, or start another creative cycle. If the locked concept itself is
invalid, retain the candidate as failed evidence and require an explicit owner
request for a new design run.

## Persistence and Provenance

Use existing `design_run_phase_artifacts` persistence and canonical hashes.

Add durable phases to `DesignPhase`:

- `ASSET_EVIDENCE`
- `BRAND_SOURCE`
- `TRANSFER_REVIEW`
- `TEMPORAL_REVIEW`

Persist:

- asset-evidence version and hash;
- provider/model identity for semantic evidence;
- deterministic extractor version;
- brand-source artifact and hash;
- composition-plan and behavior-system hashes;
- creative-director session identity;
- counterfactual transfer verdict;
- implementation and motion coverage reports;
- deterministic geometry report;
- temporal evidence manifest;
- final review and sign-off.

Thread the experience-plan hash through implementation, motion, validation,
review, repair, derived-page creation, and review-draft metadata. An approved
draft must be bound to both candidate SHA and reviewed experience-plan hash.

Do not repurpose `DesignManifest` as the creative source of truth. It currently
acts as factual candidate metadata and compatibility data. Add a separate
hash-bound design-system receipt to `DesignSourceBinding` or a sibling contract
for derived pages.

## Derived Pages

Derived pages must inherit:

- brand-source-map hash;
- identity and logo rules;
- behavior-system thesis and invariants;
- signature behavior ownership;
- shared component rules;
- allowed page-level variation;
- prohibited drift.

A derived page need not repeat the homepage's signature scene. It must preserve
the same behavioral world and may express it through a page-appropriate scene
within declared variation points.

## Application and Module Changes

### Contracts

`src/site_agent/core/design_contracts.py`

- add the new strict contracts;
- add phase enum values;
- validate new specialist payloads;
- add an experience-system source binding for derived pages;
- preserve backward parsing of existing runs.

`src/site_agent/core/media_contracts.py`

- add a versioned design-evidence contract or a compatible extension boundary;
- keep existing business-knowledge analysis behavior unchanged;
- distinguish deterministic facts from model-derived semantic evidence.

### Persistence

`src/site_agent/core/memory.py`

- migrate stored media-design evidence with analyzer versions and hashes if the
  existing analysis record cannot safely contain it;
- reuse design phase artifact persistence for run-specific plans and reviews;
- add indexes only for demonstrated retrieval paths;
- keep migrations additive and backward compatible.

### Planning services

`src/site_agent/application/designs.py`

- assemble frozen asset evidence during context capture;
- require the locked experience plan before specialist realization;
- thread its hash through queueing, validation, review, repair, and draft creation;
- expose typed diagnostics with run, asset, phase, provider, and candidate IDs.

`src/site_agent/application/design_orchestration.py`

- add brand-source and transfer-review phases;
- send normalized media evidence rather than paths alone;
- validate concept and selection payloads strictly;
- update the motion phase to fidelity realization;
- add temporal review and bounded plan correction;
- preserve the finite graph and durable phase recovery.

`src/site_agent/brain/page_strategy.py`

- keep factual request creation generic;
- add references to frozen media evidence when available;
- do not select a physical law or visual motif in host code.

### Providers

Add `src/site_agent/hands/image_visual_evidence.py`

- implement deterministic optical and geometric extraction;
- expose a narrow provider-neutral result;
- perform no mutation and no layout decisions.

`src/site_agent/hands/opencode_provider.py`

- register brand-source and transfer-critic roles;
- provide strict structured contracts;
- retain provider/session/usage diagnostics;
- prohibit specialist delegation.

`src/site_agent/hands/opencode_runner.py`

- include the locked composition and behavior contracts in realization input;
- remove language that asks the implementer to rediscover those decisions;
- require implementation coverage reports;
- preserve no-network, repository-boundary, and build constraints.

`src/site_agent/hands/playwright_quality.py`

- collect role-based geometry and temporal evidence;
- support no-JS and reduced-motion capture;
- exercise only interactions declared in the locked plan;
- avoid site-specific selectors in generic code.

`src/site_agent/hands/design_quality.py`

- validate objective composition and runtime conditions;
- report condition IDs tied to the locked plan;
- never infer aesthetic quality mechanically.

`src/site_agent/hands/design_visual_review.py`

- accept source maps, composition plans, temporal evidence, and implementation
  coverage;
- separate static composition, temporal fidelity, and genericity findings;
- remain read-only.

### Web and review surfaces

`src/site_agent/web/server.py` and `src/site_agent/web/intake_lab.py`

- translate requests only;
- expose plan/review summaries through application services;
- keep raw behavior traces and internal prompts out of owner responses;
- preserve stable API paths and preview authorization.

`src/site_agent/web/static/admin.html` and
`src/site_agent/web/static/intake_lab.html`

- show a concise Design-tab explanation of the selected composition thesis and
  signature behavior;
- show which owner assets anchor the direction;
- show reduced-motion and mobile review states;
- keep approval explicit and separate from review.

## Phased Delivery Plan

### Phase 1: Strict creative contracts

- [ ] Add failing contract tests for every new record.
- [ ] Reject missing evidence references and unknown fields.
- [ ] Enforce bounded lists, normalized regions, valid hashes, and finite ranges.
- [ ] Make new `CreativeConcept` and `DesignPlanBundle` payloads strict while
      retaining legacy-read compatibility.
- [ ] Add canonical-hash round-trip tests.

Acceptance criteria:

- malformed or generic placeholder payloads cannot reach a builder;
- persisted old design runs remain readable;
- all new planning artifacts are immutable and hash-bound.

### Phase 2: Asset visual evidence

- [ ] Add fixture images for transparent logo whitespace, opaque logo background,
      portrait photography, landscape photography, and ambiguous boundaries.
- [ ] Implement deterministic optical extraction.
- [ ] Add versioned semantic design evidence through the existing media pipeline.
- [ ] Freeze selected evidence in `DesignContextSnapshot`.
- [ ] Verify signed URLs and private storage keys never enter persisted artifacts.

Acceptance criteria:

- optical bounds differ correctly from file bounds for transparent logos;
- ambiguous bounds remain explicit rather than guessed;
- evidence is reused across runs and invalidated only by analyzer version or
  content hash;
- every run can report the exact asset evidence it consumed.

### Phase 3: Brand source and composition planning

- [ ] Add the read-only brand-source specialist.
- [ ] Extend three concept artifacts with exact media and logo relationships.
- [ ] Require the creative director to produce `AssetCompositionPlan` inside the
      locked bundle.
- [ ] Add plan validation that every supplied asset is assigned, intentionally
      unused, or prohibited with a reason.
- [ ] Persist selected and rejected concept evidence.

Acceptance criteria:

- implementation receives no unresolved logo placement decision;
- each major image has a semantic, geometric, responsive, and accessibility role;
- the selected composition cites owner or asset evidence for its identity rules.

### Phase 4: Generic brand behavior system

- [ ] Add strict `BrandBehaviorSystem` parsing and validation.
- [ ] Require one signature behavior and explicit resting, mobile, reduced-motion,
      keyboard, interruption, and performance translations.
- [ ] Add the counterfactual transfer critic.
- [ ] Permit one bounded correction of the locked plan after transfer rejection.
- [ ] Persist the final plan hash before repository mutation.

Acceptance criteria:

- no industry-specific behavior is present in generic host code or defaults;
- the behavior system cites run-specific evidence;
- generic entrance-animation lists cannot satisfy the signature contract;
- an interchangeable plan is rejected before implementation.

### Phase 5: Integrated realization

- [ ] Pass composition and behavior contracts to the implementation agent.
- [ ] Require structured realization maps and deviations.
- [ ] convert the motion phase into a fidelity pass.
- [ ] preserve approved capability provisioning and no-network rules.
- [ ] retain a candidate only through existing immutable candidate refs and SHAs.

Acceptance criteria:

- the source contains a traceable realization of every required plan condition;
- the implementation may be bespoke without introducing unapproved dependencies;
- absence of JavaScript still yields complete content and conversion paths;
- reduced motion preserves the experience's conceptual hierarchy.

### Phase 6: Composition and temporal quality gates

- [ ] Add role-based geometry collection.
- [ ] Add optical logo collision and clear-space checks.
- [ ] Add focal-region and effective-resolution checks.
- [ ] Add temporal interaction scripts generated from declared acceptance
      conditions, not hardcoded business selectors.
- [ ] Capture before/intermediate/after, reduced-motion, no-JS, and keyboard
      evidence.
- [ ] Add sighted static and temporal reviews.

Acceptance criteria:

- a logo/menu collision fails before reviewability;
- a planned focal subject cropped out on mobile fails with concrete evidence;
- a static screenshot cannot by itself pass signature behavior;
- behavior defects produce a bounded, plan-linked repair brief.

### Phase 7: Design review and derived-page continuity

- [ ] Surface the brand-source thesis, anchor assets, and signature behavior in
      the Design tab.
- [ ] Bind review drafts to candidate SHA and experience-plan hash.
- [ ] extend derived-page source binding with the approved experience system.
- [ ] Verify derived pages preserve identity and behavioral invariants without
      duplicating the homepage scene.
- [ ] Keep approval and publication unchanged.

Acceptance criteria:

- the owner can understand what makes the candidate specific before approval;
- approved derived pages remain recognizably in the same world;
- no review action mutates production without explicit approval.

## Test Strategy

Follow the repository rule: start each behavior with a focused failing test or a
reproducible API request.

### Contract tests

- valid and invalid normalized regions;
- deterministic versus semantic evidence provenance;
- missing asset hashes;
- unknown payload fields;
- behavior systems without a signature behavior;
- behavior systems without reduced-motion or no-JS translations;
- transfer-review identity mismatch;
- experience-plan hash mismatch;
- legacy artifact compatibility.

### Service tests

- snapshot freezes the correct media evidence;
- planning phases resume without rerunning completed work;
- concepts receive the same immutable evidence;
- selection requires strict contracts;
- transfer rejection permits only one correction;
- builders cannot run without a locked plan;
- repair cannot alter plan identity;
- review draft binds candidate and plan hashes.

### Provider tests

- transparent-padding logo optical bounds;
- visual-mass and optical-center stability;
- conservative opaque-background behavior;
- no mutation of source bytes;
- deterministic analyzer-version invalidation;
- bounded multimodal evidence and provider failure handling.

### Browser tests

- logo/navigation/action intersections at all required viewports;
- optical clear space;
- image focal-region coverage;
- no-JS resting state;
- reduced-motion behavior;
- keyboard and focus behavior;
- resize and interrupted animation cleanup;
- layout shift and performance budgets;
- mount-aware preview asset requests under `/ada/`.

### End-to-end scenarios

Use several intentionally unrelated fixture businesses with different media
profiles. The purpose is not to encode expected aesthetics. Assert that:

- each run produces different evidence-backed source and behavior contracts;
- each plan cites its own assets and business context;
- no plan carries domain vocabulary from another fixture;
- the same generic pipeline builds, validates, reviews, and retains every run;
- an intentionally transferable concept is rejected;
- an intentionally overlapping logo fails geometry validation;
- no scenario publishes without approval.

## Observability

Every diagnostic should include relevant identifiers:

- incubation and design run ID;
- phase and artifact ID;
- asset ID and content hash;
- evidence analyzer version;
- provider, model, and session ID;
- experience-plan hash;
- candidate SHA and ref;
- route, viewport, and motion preference;
- acceptance-condition ID;
- review-draft ID where applicable.

Do not log raw private media, signed URLs, credentials, hidden model reasoning, or
entire prompts.

## Rollout

1. Implement contracts and evidence extraction behind a disabled
   `design_engine.brand_composition` capability.
2. Run shadow planning on local Intake Lab candidates without changing builder
   inputs.
3. Compare shadow plans with realized candidates and refine contract validation,
   not site-specific prompt language.
4. Enable strict composition planning for local experiments.
5. Enable the behavior contract and transfer gate for specialist orchestration.
6. Add temporal review before allowing these candidates into the Design tab.
7. Enable production-instance draft generation only after cross-domain fixtures
   and the full repository suite pass.

Do not create a permanent legacy fallback that silently skips composition or
behavior gates for new specialist runs. Existing persisted runs remain readable;
new runs either use the complete capability or clearly report that it is
unavailable.

## Repository Verification

After each phase, run focused tests. Before marking the implementation complete:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
```

Also run an Intake Lab build through the documented design-debugging chain and
inspect all required viewport, no-JS, reduced-motion, and temporal evidence in
the Design review flow.

## Definition of Done

The system is complete when:

- logos are laid out using measured optical geometry and frozen relationship
  rules, with no collisions across required viewports;
- owner media demonstrably influences composition, palette, geometry, material,
  hierarchy, or behavior through evidence-linked decisions;
- every new specialist design has one business-specific behavioral thesis and
  signature behavior;
- generic host code contains no industry-specific creative mapping;
- the coding agent remains free to produce bespoke source within approved
  capabilities and safety constraints;
- static, temporal, no-JS, reduced-motion, mobile, keyboard, and performance
  evidence are reviewed;
- interchangeable CMS-grade motion cannot satisfy the creative gate by itself;
- derived pages preserve the approved identity and behavioral world;
- all artifacts, hashes, providers, candidates, and review decisions remain
  inspectable;
- production remains unchanged until explicit owner approval.

## Decision Log

- Use assets as evidence and compositional constraints, not merely file inputs.
- Measure logo optical geometry separately from its file rectangle.
- Derive visual grammar from owner identity and media with explicit confidence
  and provenance.
- Represent brand physics as a domain-neutral typed creative specification, not
  an executable DSL and not an animation preset library.
- Let the implementation agent write bespoke behavior for each candidate.
- Select composition and behavior together before source mutation.
- Require an adversarial transfer test before implementation.
- Keep objective geometry in deterministic gates and originality in sighted,
  evidence-bound review.
- Require temporal evidence for signature behavior.
- Preserve finite orchestration, immutable candidates, Design-tab review, and
  explicit approval.
