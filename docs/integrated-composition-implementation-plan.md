# Minimal Integrated Composition Plan

## Purpose and authority

Make Ada design text, imagery, layout, and behavior together before writing the
site. The strength of the LLM is its ability to synthesize rich context into a
creative whole. The host should supply that context and preserve the resulting
intent, not prescribe the design through rules.

This is a focused implementation follow-up to
`brand-composition-and-behavior-system-implementation-plan.md`, which remains
authoritative. It implements its integrated-composition requirement; it does
not introduce a competing pipeline or weaken its owner-review requirements.

## Problem

The pipeline is:

`confirmed intake -> Ada planning -> Ada generation -> build -> deterministic validation -> visual/behavioral review -> owner review`

The required correction is settled: implement one context-rich composition stage
in which Ada designs imagery, actual text, layout, and behavior together. Persist
that integrated intent and carry it into generation. Reuse existing infrastructure
and remove conflicting independent planning passes.

Inspecting existing code determines what to reuse or replace, not whether this
integrated stage is necessary. That inspection is a short implementation step,
not a separate research project or a prerequisite for agreeing on the design.

A bundle containing all three subjects is not proof that they were designed
together. Oversized or destructive image crops can be the consequence of a
layout chosen without considering the actual photograph, nearby text, and
intended experience.

Downstream checks remain necessary, but they cannot substitute for design.

## The smallest useful architecture

**Shared context -> one integrated plan -> one integrated realization -> review.**

Use the existing planning and implementation calls. Replace fragmented creative
responsibilities rather than adding another layer of specialists.

### Shared context

Give the composing model these inputs together:

- confirmed owner intent, audience, business facts, constraints, and feedback;
- actual approved images, including the logo, with stable IDs and source paths;
- current usable copy, distinguishing fixed facts from editable phrasing;
- the confirmed experience requirements and technical constraints;
- the relevant existing design skills.

Use actual image attachments, not just filenames or descriptions. Reuse existing
media evidence and attachment handling. If a required image cannot be inspected,
report that missing context rather than pretending an asset-grounded plan exists.

Do not silently truncate away the copy or assets needed to compose the page. Keep
the context focused on this candidate; do not append unrelated transcripts and
duplicated specialist reports.

### One integrated plan

Ada writes a concise, free-form Markdown plan for the page as a whole and its
meaningful scenes or sections. A scene means a coherent part of the visitor
experience, not a new application entity or a mandatory animation sequence.

The plan explains how the actual words, selected images, spatial relationships,
and behavior work together to communicate the offer and lead to the next action.
It should resolve:

- the page's main idea, hierarchy, and narrative progression;
- which actual copy and assets belong together, and why;
- relative scale, image framing, subject visibility, and text/image balance;
- how interaction changes the composition over time;
- how the relationships recompose on smaller screens and with reduced motion.

These are creative responsibilities, not fields in a large mandatory schema.
Ada may use whichever explanation best communicates her design. The plan should
be specific to the available material and sufficient to guide realization, not
a generic list of design principles or a pixel-by-pixel specification.

Planning is reciprocal: Ada can tighten editable copy, choose a different approved
image, change the spatial arrangement, or simplify motion to make the whole work.
She must preserve confirmed facts and defining experience requirements. No new
claims, invented destinations, or silent changes to owner constraints.

Do not finalize layout, imagery, and motion independently and ask the builder to
resolve their conflicts later. Do not force every photograph into the same crop
or assume that either full-bleed or contained imagery is universally correct.

### One integrated realization

The existing implementation agent receives the plan and the same relevant source
context, including actual images and copy. It realizes layout, imagery, text, and
behavior together. Do not follow it with a separate creative motion pass that
reinterprets a finished layout.

The builder retains implementation judgment: exact CSS dimensions, breakpoints,
and browser details need not be fixed by the planner. Local adjustments should
serve the composition. A material departure from the plan must be reported with
its reason, not hidden behind a technically passing build.

Where the existing runner supports it, retain planning context in the same
session. Otherwise pass the plan and source material explicitly. Do not add a
session-management subsystem to achieve continuity.

### Review as a backstop

Review the hydrated candidate in the actual owner preview against the integrated
intent and the source material. Include the image-bearing sections and relevant
interaction states, not only one opening screenshot per viewport.

The reviewer judges whether the composition works as a whole. The host still owns
deterministic checks and approval safety; it does not calculate aesthetic scores.

Basic composition failures are not automatically downgraded to owner preferences.
Missing review evidence is incomplete. A bounded repair budget limits work; it
does not grant permission to expose an unresolved failed candidate as ready.

## Implementation steps

### 1. Locate the existing calls and handoff to change

Take one visibly defective section from the retained candidate and follow:

`source images + actual copy -> persisted plan -> builder context -> rendered section`

Use this short trace to locate context assembly, the planning call, persistence,
and the builder handoff. Identify the code to reuse and the independent creative
instructions to replace. Then implement the agreed integrated stage. Do not turn
this into an open-ended investigation or another cosmetic candidate rerun.

Primary inspection points:

- `application/design_orchestration.py`: creative planning and context assembly;
- `hands/opencode_runner.py`: what the implementation model actually receives;
- `core/design_contracts.py`: existing plan envelope and artifact identity;
- `application/design_jobs.py`: ordering and competing creative passes.

### 2. Make the existing planner responsible for synthesis

Modify the existing creative-planning call to receive the shared context and
produce the integrated plan. Reuse its existing artifact envelope and persistence.
Prefer a Markdown body in that envelope to new nested contracts or tables.

Keep source references and existing hashes at the boundary so the builder can
identify the exact plan and assets. Add at most the small payload field needed
to carry the plan; do not create a parallel plan store or a scene database.

Reuse useful upstream analysis as input. Remove redundant creative passes that
independently dictate final layout, image treatment, or motion. The composing
model owns the synthesis; the host does not arbitrate design decisions using
heuristics.

Prompts state responsibilities, available context, constraints, and required
outcomes. No worked designs, canned phrasing, industry recipes, or sample plans.

### 3. Carry that plan intact into realization

Adjust the existing request assembly so the builder receives the integrated plan
with its actual copy and assets, without contradictory instructions from older
passes. Keep one implementation owner for the composed result.

For owner-requested changes, include the retained candidate and plan plus the
feedback. Preserve accepted strengths instead of silently restarting creative
direction. Use existing candidate lineage and draft mechanisms.

### 4. Align review and readiness with the same intent

Reuse the existing browser capture and vision-review paths. Give review the plan,
source images, and owner-surface evidence needed to compare intent with realization.
Extend coverage only where the trace shows it is missing; no new review service.

Remove unconditional readiness promotion based on `visual_refinement` or repair
budget exhaustion, including persisted-run reclassification that bypasses a real
quality decision. An unresolved mandatory failure remains blocked. Do not use a
status migration to make this implementation appear successful.

Relevant boundaries are `application/designs.py`, `application/intake_lab.py`,
`hands/design_visual_review.py`, and the existing browser-quality adapter. Change
only the parts necessary to carry and verify integrated intent.

### 5. Prove the change through Ada

Start with focused failing tests for the integrated planning handoff. Then implement the
smallest fix and run the focused tests, full suite, compile check, and wheel build.

Rerun Ada from the confirmed intake or earliest valid persisted boundary. Do not
manually repair the generated HTML, CSS, copy, or image placement.

Inspect the resulting owner preview at desktop, tablet, and mobile sizes, including
reduced motion. Compare the original photos with their actual framing, read the
text in place, and exercise the defining interaction. Treat failed assets, modules,
hydration, and browser console errors as failures.

Measure the autonomous elapsed time from the actual starting boundary and report
it honestly. A resumed fragment is not proof of a fresh approximately 20-minute
intake-to-review journey. Production remains unchanged without owner approval.

## Focused tests and acceptance

Tests should establish the handoff, not pretend to grade design taste:

- planning receives actual asset attachments, usable copy, and experience context;
- the integrated plan is persisted and passed intact to generation;
- generation receives the same referenced material, not only a summary;
- no later creative pass independently replaces the composition;
- owner modifications retain the accepted candidate context;
- missing review evidence and unresolved failures cannot become owner-ready merely
  because the run is a final refinement.

Use existing service, orchestration, runner, and review tests. Mocked tests establish
contract behavior; they do not prove that the photographs are well composed.

The live acceptance evidence must show that Ada composed the actual images, text,
and behavior coherently in the owner surface, with no manual candidate repair.
For the current failure, that includes recognizable photographic subjects and
appropriate context at each viewport, balanced with readable copy and the retained
experience. A passing gate or model assertion alone is insufficient.

## Explicit non-goals

- No new multi-agent hierarchy or independent crop specialist.
- No new orchestration framework, database, or generalized design DSL.
- No exhaustive per-element specification or fixed section template.
- No universal crop thresholds, prescribed image sizes, or host-side taste rules.
- No extra critique loops to compensate for missing planning context.
- No requirement that every scene animate or every approved image be used.
- No manual polish to make an autonomous run appear successful.

## Completion rule

Complete only when Ada's context-rich integrated plan demonstrably governs an
Ada-generated candidate whose composition and behavior work in the owner preview.
Record whether Ada authored it, whether the defining experience was observed there,
whether any workaround bypassed the pipeline, and whether the elapsed journey is
compatible with the product promise. If those facts are unproven, report incomplete.

**Give the model the material, let it compose the whole, preserve that intent into
implementation, and verify the result. Keep the host small.**
