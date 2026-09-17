# Brand-Led Composition and Generative Behavior System Implementation Plan

## Status

Authoritative corrective implementation contract for autonomous creative
planning, integrated realization, and experience fidelity. This plan extends
`docs/opencode-first-design-pipeline-implementation-plan.md`. Where the two
documents differ about creative planning, implementation-agent responsibility,
motion ownership, experience fidelity, or design completion, this document is
authoritative. The OpenCode-first plan remains authoritative for durable jobs,
candidate retention, Git identity, provider isolation, and approval safety.

This plan changes design planning, realization, and review without changing the
owner approval or production publishing rules.

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

## Final Contextual Creative Autonomy Plan

This section is the complete operating plan for the creative system. It makes
the distinction between generic product safety and run-specific creative
authorship explicit. It does not prescribe a visual style, page structure,
image treatment, motion recipe, or journey for any industry.

### The central rule

Ada must make one context-specific creative decision and carry it through the
whole candidate:

```text
confirmed owner context
  -> Ada understands the context and evidence
  -> Ada chooses a visual and behavioral thesis
  -> Ada plans one coherent visitor journey
  -> Ada assigns copy, assets, layout, and motion to that journey
  -> Ada implements the plan as one integrated experience
  -> Ada checks that the implemented experience still expresses the plan
```

Tools, skills, frameworks, image capabilities, and motion libraries are
available capabilities. They are not requirements and they are not a catalogue
of effects from which the host chooses. Ada may decide that an image needs a
careful frame, a crop, a transition, no treatment, or a different role entirely.
That decision must come from the current business, audience, approved media,
copy, and constraints.

The system is successful when a new business produces a new creative world
through the same safe pipeline. A future hairstylist site must not inherit a
cave-diving composition, a light/dark treatment, a scroll guide, or any other
Claro Oscuro-specific pattern merely because those tools were useful before.

### What is fixed and what remains Ada's choice

The fixed layer defines the owner's authority and the host's safety boundary:

- the confirmed intake revision and its hash;
- owner-provided business facts, audience, goals, constraints, and unknowns;
- approved assets, their stable IDs, content hashes, and provenance;
- any confirmed experience requirement expressed as an observable outcome;
- truthful copy requirements and prohibited claims;
- accessibility, keyboard, touch, responsive, no-JavaScript, and reduced-motion
  requirements;
- candidate isolation, durable state, preview integrity, and owner approval;
- the elapsed-time budget and the requirement to report incomplete work honestly.

The creative layer remains open for every run:

- the visual concept and brand grammar;
- the emotional arc and visitor journey;
- the page and section composition;
- the copy voice, hierarchy, pacing, and editorial emphasis;
- the role, placement, framing, crop, scale, and treatment of each asset;
- the signature behavior and any supporting interaction;
- the motion technology, if motion is useful at all;
- the responsive translation of the chosen concept;
- the decision to make an asset prominent, supporting, ambient, or unused;
- the trade-offs between imagery, copy, interaction, clarity, and performance.

The host may validate the fixed layer and whether Ada realized her own plan. It
must not fill the open creative layer with a default answer.

### The single accountable creative thread

Ada is the accountable creative owner of the candidate, even when she uses
specialist capabilities. The responsibilities are divided by authority, not
by a handoff that loses the idea:

1. Evidence specialists inspect the intake, brand signals, copy facts, and media.
   They return evidence and uncertainty, not a reusable visual prescription.
2. Concept specialists may develop alternatives grounded in that evidence.
3. Ada's creative director selects one concept and turns it into a complete
   locked plan. The selection includes the journey, not only a mood or hero
   direction.
4. The primary realization agent receives the complete plan and all relevant
   capabilities together. It owns composition, copy realization, asset use,
   behavior, responsive translation, and the local self-check in one integrated
   pass.
5. A fidelity specialist may close an implementation gap, but may not replace
   the concept or invent a different journey.
6. The host coordinator owns ordering, persistence, isolation, and gates. It
   does not make run-specific design decisions.
7. A visual reviewer is read-only. It confirms or rejects what Ada produced; it
   is not a second creative director.

Specialists may be separate provider sessions, but the selected plan and its
hash are the authority across every handoff. No specialist may silently
substitute a generic site pattern for a run-specific decision.

### The locked creative plan

Before source mutation, Ada must produce a complete plan composed of the
existing typed design and experience plan artifacts. It must be sufficient for
another agent to implement the selected experience without inventing the
missing creative decisions.

The plan must contain, at minimum:

- a context thesis grounded in the business, audience, copy, and approved media;
- the chosen visual grammar and the evidence that supports it;
- an ordered visitor journey with scenes, transitions, and an intended ending;
- the purpose and narrative job of each scene or major region;
- the resting state and the meaningful state change for each required scene;
- the copy hierarchy and the role of each important text block;
- asset-to-region relationships, including why an asset is prominent, supporting,
  treated, untreated, or not selected;
- image framing and focal considerations for each required viewport;
- the signature behavior and the reason it belongs to this business;
- supporting behavior only where it reinforces the chosen journey;
- desktop, tablet, mobile, keyboard, touch, no-JavaScript, and reduced-motion
  translations;
- interruption, reverse, resize, and rapid-input behavior where applicable;
- performance and legibility trade-offs;
- unknowns and claims Ada deliberately leaves unresolved;
- stable acceptance-condition IDs and evidence references;
- the plan content hash used by implementation, validation, review, and repair.

The plan must record meaningful non-use as well as use. Choosing not to animate
an image, not to crop it, or not to use a motion library is a creative decision,
not an omission. Conversely, merely listing an asset or naming an animation is
not a composition or behavior decision.

### Planning and implementation are one design decision

The implementation handoff must be lossless. Ada's realization agent receives:

- the complete locked plan;
- the complete asset evidence and approved source files;
- the confirmed copy facts and prohibited claims;
- the selected capabilities and their constraints;
- the required acceptance conditions;
- the responsive and reduced-motion translations;
- any known feasibility risks and their chosen mitigations.

The realization agent must not be asked to discover the visual hierarchy,
choose a crop, invent the journey, or add motion after the composition is
already complete. If a decision is missing, the plan is incomplete and the
pipeline stops before source mutation or returns to Ada for one bounded planning
correction.

The implementation is complete only when Ada has attempted a local build and
self-check against every planned condition. A source tree, tool list, manifest,
or provider claim cannot stand in for realization.

### Images are contextual material, not a mandatory effect

Every selected image must have a reason in the plan, but the reason can differ
by business:

- subject or credibility;
- geometry, silhouette, negative space, or optical axis;
- palette, contrast, texture, or material language;
- sequence, place, product detail, or emotional meaning;
- an interaction or transition anchor;
- an editorial pause or supporting proof;
- deliberate restraint, where the unmodified photograph is the right choice.

Image treatment is therefore selected per run and, where necessary, per asset
and per region. The system must not apply a global object-fit habit, a universal
hero treatment, a forced image effect, or a requirement to make every supplied
asset equally prominent. It must also not allow one successful image treatment
to consume the copy, behavior, or journey that gives the site its meaning.

### Copy, composition, and behavior must be reviewed as one system

Ada's plan must answer how the visitor moves through the idea, not only what
the first viewport looks like. Review must consider:

- whether the copy communicates the selected promise rather than merely naming
  the subject;
- whether the visual hierarchy gives the journey enough room to unfold;
- whether imagery clarifies, advances, or appropriately supports the copy;
- whether motion changes attention or understanding in a meaningful way;
- whether supporting interactions remain perceivable instead of being hidden by
  a dominant hero treatment;
- whether the ending gives the visitor a clear next action;
- whether responsive and reduced-motion versions preserve the same meaning.

Everything does not need to be visible at once. Integration means that each
element has a role, appears at the right moment, and reinforces the same idea.
It does not mean that the host should force every element into the first
viewport or preserve every previous animation.

### Review authority and repair semantics

The review layers have different jobs:

- **Deterministic review** checks facts such as build success, routes, safe
  assets, overflow, source integrity, and required contract coverage.
- **Runtime review** checks hydration, module and asset requests, rendered state,
  interaction, scroll behavior, responsive translation, reduced motion, and
  performance in the actual owner surface.
- **Read-only visual review** checks the rendered candidate against the locked
  Ada plan, owner context, and approved media. It may identify a hierarchy or
  integration failure, but it may not prescribe a generic aesthetic.
- **Owner review** decides whether the candidate is acceptable. It is the only
  path to approval or production change.

When a finding is returned, classify it before taking action:

1. **Delivery failure:** the preview, asset, module, or runtime is broken. Fix
   the generic host boundary and rerun evidence.
2. **Implementation-fidelity failure:** Ada's plan is valid, but the candidate
   does not realize one or more planned conditions. Send the exact condition and
   rendered evidence to Ada for one bounded plan-preserving repair.
3. **Plan failure:** Ada's selected journey is incomplete, contradictory, or
   not specific to the business. Return to Ada's planning boundary; do not patch
   the candidate into a different concept.
4. **Owner change:** the owner has changed the goal, copy, audience, assets, or
   constraints. Start a new confirmed revision and new Ada plan.
5. **Taste preference outside the plan:** do not turn a generic reviewer's
   preference into an application-wide rule. It needs owner confirmation or an
   Ada-authored plan decision.

Repairs must not combine a narrow usability correction with an unrequested
art-direction rewrite. A request to improve image framing must not silently
become a new visual system, and a request to make a concept more distinctive
must not silently remove its defining behavior. If the current candidate is
structurally wrong, the correct operation is a fresh Ada plan or an explicitly
authorized bounded repair—not a sequence of host-authored patches.

### Preventing creative cross-contamination

The host may reuse neutral infrastructure, skills, analyzers, and capability
descriptions. It may not reuse run-specific creative decisions as defaults.

For every new confirmed intake:

- begin with the new intake and approved assets as the creative source of truth;
- make the previous candidate unavailable as an implicit template;
- allow historical candidates only as explicit owner-requested references;
- require the new plan to cite its own business and asset evidence;
- run a transfer check asking whether the selected concept could be copied to an
  unrelated business unchanged;
- reject concepts whose defining behavior is generic, decorative, or detached
  from the current context;
- verify that the same pipeline can support different visual grammars without
  adding industry-specific host logic.

The transfer check is not an originality contest. It is a guard against the
application quietly choosing the same layout, motion, or image treatment for
every business.

### End-to-end completion criteria

The contextual creative system is complete for a run only when all of the
following are true:

- the intake was confirmed and frozen before creative planning;
- Ada selected a context-specific concept and complete journey;
- composition, copy, asset roles, and behavior were selected together;
- the full plan reached the realization agent without loss or truncation;
- Ada implemented the plan and performed a local self-check;
- host build and runtime evidence came from the exact candidate shown to the
  owner;
- the chosen journey is observable in the real Design surface;
- visual and temporal review evaluated the whole page, not only a hero screenshot;
- all required viewports, reduced motion, no-JavaScript, keyboard, and touch
  translations preserve the concept's meaning;
- any repair was Ada-authored, finite, and plan-bound;
- no manual candidate edit or specialist dispatch bypassed the autonomous path;
- the candidate remains isolated until explicit owner approval;
- the elapsed path meets the approximately 20-minute promise or reports a
  measured failure honestly;
- the owner can understand and evaluate the chosen experience without reading
  source code, manifests, or internal reports.

### Required acceptance fixtures

The acceptance suite must include materially different businesses and media
profiles. Claro Oscuro is one fixture, not the template for all fixtures. A
future service-business or image-led editorial fixture should be allowed to
choose a substantially different journey and to choose no special image
treatment when that is the right decision.

The fixtures must prove that:

- Ada's plans differ in their evidence, visual grammar, asset relationships,
  copy hierarchy, and behavioral thesis;
- the same neutral host pipeline can carry each plan end to end;
- the plan, candidate, and review all share the correct hashes;
- the host does not inject industry-specific scenes or animation recipes;
- a static but attractive page cannot pass when the plan requires a visible
  journey;
- a technically valid image effect cannot pass when it overwhelms the selected
  copy or behavior;
- a deliberately transferable concept is rejected;
- no fixture mutates production without owner approval.

### Immediate application to the Claro Oscuro incident

The improved image framing is useful evidence, but it is not by itself a
successful candidate. The next Ada operation must not be instructed to restore
any particular guideline, scene, or animation. It must receive the confirmed
Claro Oscuro context plus the owner observation that the image emphasis weakened
the copy and the rest of the experience, then choose a coherent journey again.

Ada may keep, replace, or reinterpret the current image treatment. The decision
belongs to her new plan. The acceptance question is whether the resulting
composition makes the selected Claro Oscuro journey legible and whole—not
whether it resembles the previous candidate or a prescribed repair.

This incident is complete only after a fresh Ada-led plan and candidate are
observed in the real owner surface. A visually improved fragment, a passing
technical gate, or a persuasive provider explanation is not completion.

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

## Claro Oscuro Acceptance Failure: What Actually Happened

This incident is the baseline failure this plan must correct. Do not treat it as
an isolated preview bug or solve it by manually improving the candidate.

### Observed facts

- The confirmed intake contained a defining adventure path.
- The specialist coordinator invoked copy, brand-source, concept, creative
  selection, transfer, implementation, motion, and review responsibilities.
- Ada's retained candidate was visually strong as a static composition.
- The candidate source contained GSAP and ScrollTrigger calls.
- The final visual-refinement candidate changed only a small part of the parent
  implementation; it did not re-establish the adventure as the organizing
  experience.
- The actual owner preview failed to hydrate its Astro island because generated
  module requests escaped the token-authenticated preview tree and were blocked
  by CORS.
- Internal reports nevertheless described browser, motion, temporal, and visual
  gates as passed.
- The owner therefore received essentially the same static experience and could
  not recognize the planned adventure path.

### Root causes

The primary failure occurred before review, at the planning-to-realization
boundary:

1. **The defining journey was represented as descriptive behavior metadata, not
   as a mandatory ordered visitor experience.** A signature behavior and scene
   graph could be satisfied by generic section reveals without proving narrative
   progression.
2. **Experience ownership was split incorrectly.** The primary site implementer
   could complete the composition without owning the full temporal experience;
   a later motion specialist was asked to add motion to an already established
   page.
3. **The motion specialist contract was advisory.** “Named or implied” motion
   did not require condition-by-condition fidelity to the locked plan.
4. **Phase completion proved artifact production, not requirement realization.**
   A provider reply, tool-call list, or motion report could be persisted without
   proving that every required journey condition existed in the source and ran.
5. **The handoff was not guaranteed lossless.** Acceptance-critical plan data
   could be summarized or truncated before reaching a realization specialist.
6. **A refinement could preserve the wrong shape of the experience.** The
   smallest-change rule protected a static parent even when the parent had
   failed the defining journey.

The owner-preview hydration defect was a second, independent failure at the
build-to-observation boundary. It explains why existing JavaScript was invisible,
but it does not explain or excuse the weak realization of the adventure path.

### Why prior work did not solve the mission

The work optimized contracts, persistence, schema normalization, candidate
retention, and review gates horizontally. Those are supporting capabilities.
They did not prove the vertical product promise:

```text
confirmed intake -> Ada plans -> Ada realizes -> candidate runs -> owner experiences the plan
```

Passing unit tests, retaining a candidate, importing GSAP, generating motion
reports, and producing attractive screenshots were mistakenly treated as
progress toward completion without requiring this whole chain to succeed.

### Errors that must not be repeated

- Do not repair Ada's candidate manually to make an acceptance run appear to
  work.
- Do not respond to a missing defining experience by adding more review layers.
- Do not let a static visual pass compensate for missing journey behavior.
- Do not let instrumentation attributes or model-authored reports prove their
  own behavior.
- Do not preserve a parent candidate during refinement when the parent never
  satisfied the locked defining experience.
- Do not broaden infrastructure work until one autonomous intake-to-review run
  passes.
- Do not describe the mission as complete unless the owner-visible Design
  surface has been exercised after hydration.

## Corrected Autonomous Agent Architecture

### Definition of Ada

For this workflow, **Ada** is the complete autonomous runtime chain that consumes
the confirmed intake: its planning specialists, creative director, primary
implementation agent, and bounded fidelity/repair agent. The coding agent
maintaining Site Agent is outside that chain. It may repair generic orchestration,
contracts, provider adapters, preview delivery, and validation, but it may not
design or polish a run-specific candidate.

### Corrected execution graph

```text
confirmed intake and approved assets
  -> Ada: brand and copy evidence
  -> Ada: independent concepts
  -> Ada creative director: locked ExperienceJourney + composition
  -> pre-realization journey-completeness gate
  -> Ada primary implementer: composition + behavior + responsive realization
  -> Ada fidelity specialist: condition-by-condition gap closure when required
  -> Ada local self-check against the locked journey
  -> immutable candidate
  -> host build and exact-owner-surface runtime checks
  -> read-only visual/temporal confirmation
  -> one Ada-authored bounded repair when implementation fidelity fails
  -> Design review
  -> explicit owner decision
```

Review confirms Ada's result. Review does not supply the concept, invent the
adventure, or become the mechanism that makes an incomplete implementation
whole.

### Mandatory trigger and handoff graph

The host state machine, not a model's discretion, triggers each required role.
Specialists do not delegate workflow stages to one another. For every new
confirmed-intake run using this capability, persist and enforce this graph:

| Trigger | Required Ada role | Required result | Failure behavior |
|---|---|---|---|
| Frozen intake, assets, and context | Copywriter and brand-source analyst | Hash-bound foundation artifacts | Stop planning; do not fall back to legacy design |
| Both foundation artifacts complete | Three independent concept designers | Three evidence-bound concepts, each with a journey thesis | Retry only the invalid phase once, then stop |
| All concepts complete | Creative director | One complete `ExperiencePlanBundle` containing `ExperienceJourney` | Stop before source mutation |
| Locked plan complete | Transfer critic and deterministic journey-completeness gate | Passed specificity and completeness decisions | One bounded director correction, then stop |
| Plan passes | Primary site implementer | Integrated source plus complete condition coverage map and local self-check | Do not finalize a candidate as implemented |
| Initial implementation exists | Experience-fidelity specialist | Condition-by-condition implementation closure | Return blocker or complete; never silently skip |
| All implementation conditions covered | Host candidate finalizer | Immutable candidate identity | Retain failures without calling them complete |
| Host runtime evidence finds a fidelity defect | Ada experience-fidelity repair agent | One plan-bound repaired child candidate | Stop after one repair; never hand-edit |

For the first vertical acceptance milestone, the experience-fidelity specialist
runs on every initial candidate, even when the primary implementer claims full
coverage. Later optimization may skip that turn only after cross-domain evidence
shows that deterministic completeness checks can make the decision safely.

Every transition must record the expected role, actual provider/session, input
artifact hashes, output artifact hash, elapsed time, and next required phase. A
run is `incomplete` when a required role was not invoked, returned the wrong
contract, consumed the wrong plan hash, or was bypassed by a legacy path.

New confirmed-intake runs must not silently use `_create_legacy_plan`, a generic
builder role, or a visual-only refinement path when the specialist capability is
required. Backward compatibility may read historical runs; it may not weaken a
new run.

### `ExperienceJourney`

Add one strict, hash-bound journey contract inside `ExperiencePlanBundle`. It is
distinct from a loose list of motion ideas and contains:

- `journey_id` and `thesis`;
- ordered `scenes`;
- the content region and narrative purpose of each scene;
- the scene's required initial state;
- visitor input or automatic trigger;
- required visible state transition;
- completion and exit conditions;
- continuity into the next scene;
- desktop, tablet, mobile, keyboard, touch, and reduced-motion translations;
- interruption, reverse, resize, and rapid-input behavior where relevant;
- stable must-pass acceptance-condition IDs;
- the evidence linking each scene to the intake, audience, copy, or assets.

The host contract remains domain-neutral. Ada derives the actual scenes from the
current intake. A journey consisting only of reusable entrance animations,
fades, parallax, or section reveals is invalid.

### Pre-realization gate

Before any repository mutation, reject the plan unless:

- its defining journey is ordered and complete;
- every scene has at least one observable outcome;
- the signature behavior changes the visitor's experience rather than merely
  decorating content;
- the full journey has mobile and reduced-motion meaning-preserving forms;
- every must-pass condition is concrete enough for an implementation agent and
  browser driver to exercise;
- the transfer critic confirms that the journey is specific to this business;
- no implementation decision required to establish the journey remains hidden
  behind “as appropriate”, “if useful”, or “named or implied”.

One bounded creative-director correction may repair an invalid journey plan.
Failure after that correction stops before source mutation.

### Primary implementer ownership

The primary implementation agent owns the complete candidate in one integrated
pass:

- composition and typography;
- asset realization;
- the complete ordered journey;
- signature and supporting behavior;
- responsive behavior;
- keyboard and touch behavior;
- no-JavaScript and reduced-motion translations;
- performance and interruption behavior;
- local build and journey self-check.

The implementer receives the relevant design and motion skills together. Motion
is not delegated away as optional post-production. The complete locked plan must
be passed losslessly; acceptance-critical artifacts may not be truncated. If a
provider context limit cannot carry them, fail before invocation or pass them as
immutable local artifacts with verified hashes.

### Fidelity specialist ownership

Replace the “add purposeful motion” contract with a condition-driven fidelity
contract. The fidelity specialist receives the same locked plan and current
worktree and must inspect every must-pass journey condition. It may only:

- implement a missing plan mapping;
- correct a broken transition or interaction;
- complete a required responsive or reduced-motion translation;
- remove contradictory generic effects;
- report a genuine blocker.

Its report must map each condition ID to implementation source, trigger, rendered
state, responsive translation, and status. A report with missing condition IDs
is invalid. The report is diagnostic evidence, not proof that behavior ran.

### Refinement semantics

The smallest-change preservation rule applies only after the parent has proven
all defining journey conditions. If the parent never satisfied the journey, a
child operation must be classified as **experience fidelity repair**, not visual
refinement, and Ada may restructure the implementation as needed without
changing the locked concept. The external coding agent still may not edit the
candidate.

### Completion semantics for specialist phases

- Planning completes only with a valid, locked journey.
- Implementation completes only with a coverage map containing every must-pass
  condition and a successful local build/self-check attempt.
- Fidelity completes only when all conditions are implemented or an explicit
  blocker is returned.
- Candidate retention records what Ada produced, but does not imply quality.
- Host reviewability requires independent runtime evidence; provider reports and
  source markers cannot promote their own candidate.

## Corrective Delivery Sequence

This sequence takes precedence over broad horizontal rollout. Implement and
prove each boundary in order.

### Corrective Phase 0: Freeze the acceptance scenario

- [ ] Retain the original confirmed Claro Oscuro intake, assets, copy,
      experience plan, and expected owner action as one immutable acceptance
      fixture.
- [ ] Record the intended adventure as Ada-authored ordered journey conditions,
      not host-authored cave-specific logic.
- [ ] Define the single start operation and final Design-surface observation.
- [ ] Define the approximately 20-minute wall-clock budget and per-stage budgets.
- [ ] Prohibit manual candidate edits and manual specialist dispatch during the
      acceptance run.

Acceptance criteria:

- one command or owner action starts from confirmed intake;
- the expected result is expressed as observable experience conditions rather
  than expected markup or a predetermined design;
- production remains isolated and unchanged.

### Corrective Phase 1: Make the journey control realization

- [ ] Add the strict `ExperienceJourney` contract and pre-realization gate.
- [ ] Make journey-condition completeness part of creative-director completion.
- [ ] Deliver the complete hash-bound plan to the primary implementer without
      truncation.
- [ ] Give the primary implementer both composition and motion responsibility and
      all required local skills.
- [ ] Replace the post-hoc motion role with the condition-driven fidelity role.
- [ ] Make missing condition coverage fail before candidate finalization.

Acceptance criteria:

- removing the journey from an otherwise valid plan prevents implementation;
- an implementer that creates only a static page cannot complete its phase;
- a fidelity report that omits one required condition is rejected;
- no host code contains Claro Oscuro-specific creative behavior.

### Corrective Phase 2: Make Ada close her own implementation gaps

- [ ] Run Ada's local build and bounded journey self-check before immutable
      candidate finalization.
- [ ] Route missing implementation conditions to the fidelity specialist in the
      same autonomous job.
- [ ] Permit one bounded experience-fidelity repair after host evidence when the
      concept is valid but its realization is defective.
- [ ] Keep planning correction, fidelity completion, visual refinement, and
      technical repair as distinct operation reasons.
- [ ] Ensure restart recovery resumes the next required autonomous stage without
      owner or developer dispatch.

Acceptance criteria:

- the normal path needs no manual agent invocation;
- Ada, not the repository-maintenance agent, authors every candidate change;
- repair receives exact failed condition IDs and does not invent a new concept;
- one failed condition cannot be hidden by an aggregate pass.

### Corrective Phase 3: Prove the generated experience reaches the owner

- [ ] Use the exact Design-tab URL, mount point, iframe sandbox, token behavior,
      candidate SHA, and generated module paths for runtime evidence.
- [ ] Treat hydration, console, module, asset, or network failure as incomplete.
- [ ] Bind every temporal record to non-empty matching candidate and plan hashes.
- [ ] Exercise the Ada-authored journey conditions at representative viewports
      and reduced-motion settings.
- [ ] Give read-only reviewers the ordered evidence sequence, not isolated static
      screenshots alone.

Acceptance criteria:

- a deliberately broken Astro island cannot pass motion or temporal gates;
- a static page with valid GSAP source but no observable state transition cannot
      pass;
- the owner and evidence runner observe the same hydrated candidate;
- review only confirms or rejects; it does not create the missing experience.

### Corrective Phase 4: Run the autonomous Claro Oscuro proof

- [ ] Start again from the original confirmed intake, not the retained candidate.
- [ ] Let the complete Ada chain plan, implement, self-check, and repair without
      manual intervention.
- [ ] Observe the defining adventure path in the real Design surface on desktop,
      tablet, mobile, and reduced motion.
- [ ] Record elapsed time and stage durations.
- [ ] Confirm no production or remote mutation occurred.

Acceptance criteria:

- the owner can identify the planned adventure without reading source, manifests,
      reports, or developer notes;
- all must-pass journey conditions are observed;
- the complete autonomous path finishes within the product time budget or is
      honestly reported as a performance failure;
- the candidate is presented only for explicit owner feedback;
- no manual candidate repair contributed to the result.

### Stop condition

Do not begin broader rollout, cross-domain tuning, additional reviewers, new UI
polish, or unrelated infrastructure work until Corrective Phase 4 passes. If it
fails, identify the earliest failed boundary, change only generic pipeline code
at that boundary, and rerun from the confirmed intake.

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

This is one integrated realization responsibility. The implementation agent
owns the locked journey, composition, behavior, responsive translations, and
reduced-motion meaning together. It may not defer the defining experience to a
later specialist or return a static composition as a complete implementation.

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

### Experience-fidelity specialist

Replace the post-hoc motion phase with a condition-driven fidelity specialist.
Change its contract from “add purposeful motion” to:

- inspect the locked journey, behavior system, and existing realization;
- account for every must-pass journey-condition ID;
- implement missing journey and behavior-law mappings;
- tune choreography and interruption handling;
- remove generic or contradictory effects;
- preserve composition and content;
- report exact behavior coverage and deviations, including source location,
  trigger, rendered state, and reduced-motion translation for each condition.

It may not introduce a second behavioral concept. Its structured report cannot
prove runtime success and cannot complete if a required condition is omitted.

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

- [ ] Pass the complete, untruncated composition, journey, and behavior contracts
      to the primary implementation agent.
- [ ] Give that agent ownership of composition, behavior, responsive translation,
      reduced motion, and local journey self-check in one pass.
- [ ] Require structured realization maps and deviations for every must-pass
      journey-condition ID.
- [ ] Convert the motion phase into the condition-driven experience-fidelity pass.
- [ ] preserve approved capability provisioning and no-network rules.
- [ ] retain a candidate only through existing immutable candidate refs and SHAs.

Acceptance criteria:

- the source contains a traceable realization of every required plan condition,
  and a static-only implementation cannot complete the phase;
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
