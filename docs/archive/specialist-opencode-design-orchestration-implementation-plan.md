# Specialist OpenCode Design Orchestration Implementation Plan

## Status

Proposed implementation plan. This document describes a replacement for the
current single-agent design build without changing the owner approval or
production publishing rules.

## Purpose

Replace the open-ended, single-agent website build with a finite orchestration
of focused OpenCode specialists that can produce a distinctive,
proposal-quality website candidate.

The intended result is not a faster mediocre draft. Quality comes from:

- independent concept exploration before implementation;
- explicit creative selection;
- specialized copy, composition, implementation, and motion work;
- review of the rendered realization by the creative director who selected the
  concept;
- independent usability and technical review;
- one controlled polish pass;
- a durable, approval-gated proposal in the Design tab.

The orchestration must be inspectable and resumable. No stage may recursively
request another stage, restart itself, or silently create a new candidate.

## Current Problem

The current path is approximately:

1. `DesignJobExecutor._run()` reconstructs a typed build request.
2. `DesignService.execute_build()` calls `OperationRoutingBuilder`.
3. `NativeOpenCodeBuilder.build_design()` calls `stage_design_build()`.
4. `stage_design_build()` prepares one worktree and starts one generic
   `opencode run --agent build` process.
5. That agent receives copy, visual design, implementation, GSAP, validation,
   critique, and repair responsibilities in one large context.
6. A candidate is finalized only after the OpenCode process exits.

This creates several structural failures:

- Skills are loaded into one agent instead of being assigned to specialists.
- `run_opencode_turn()` is hard-coded to the built-in `build` agent.
- The model is asked to perform checks that the host performs again later.
- Creative planning and repository mutation are coupled.
- A usable worktree is not retained as a candidate when the model fails to
  produce a terminal response.
- Usage and transcripts become durable too late.
- Existing job recovery understands whole runs, not completed design phases.
- Creative review has no durable continuity with concept selection.

## Non-Goals

- Do not create a universal plugin framework.
- Do not add automatic Python module loading.
- Do not move workflows into HTTP route handlers.
- Do not let planning agents edit a customer repository.
- Do not let any specialist approve or publish production.
- Do not expose partial concepts or internal artifacts as customer proposals.
- Do not embed canned replies, worked conversations, or example questions in
  model prompts.
- Do not replace deterministic validation with LLM judgment.
- Do not introduce recursive autonomous repair.

## Required Invariants

All existing repository invariants remain in force:

- A site mutation is an explicit owner action or a pending draft.
- Production changes only through explicit approval.
- A pending visual build is reviewed in the Design tab.
- Chat and design jobs remain durable and inspectable.
- Preview URLs continue to work under `/ada/`.
- Site-specific assumptions remain in instance configuration.
- HTTP and MCP adapters call application services, not route functions or
  `Memory.conn`.
- OpenCode configuration, transcripts, worktrees, caches, databases, and
  screenshots are not committed to the application repository.

Add these orchestration invariants:

- The host owns the workflow graph and is the only dispatcher.
- Specialist agents cannot invoke the task tool or dispatch another agent.
- Phase outputs are immutable, typed, hash-bound artifacts.
- Completed successful phases are never rerun automatically.
- Creative phases cannot request additional creative rounds.
- Only designated implementation phases receive repository write access.
- A realization has at most one automatic repair pass.
- The creative director may reject a realization but may not start another
  concept or repair cycle.
- A rejected realization remains inspectable and is not shown as a proposal.

## Target Workflow

```text
Validated intake, frozen context, approved media
                    |
          +---------+----------+
          |                    |
      Copy agent        Three concept agents
          |                    |
          +---------+----------+
                    |
           Creative director
       selection and synthesis
                    |
          Locked design bundle
                    |
         Implementation agent
                    |
             Motion agent
                    |
       Deterministic host checks
                    |
          +---------+----------+
          |                    |
  Creative director      Independent critics
 realization review       UX and technical
          |                    |
          +---------+----------+
                    |
        Consolidated repair brief
                    |
        One optional repair agent
                    |
       Deterministic host recheck
                    |
    Creative director final sign-off
                    |
      Pending Design-tab proposal
```

The graph has no backward edges.

## Specialist Responsibilities

### 1. Copy Agent

Inputs:

- validated owner-confirmed business facts;
- target audience;
- primary and secondary actions;
- required visible phrases;
- prohibited claims;
- unresolved business details;
- brand voice;
- page purpose and required routes.

Output: `CopyDeck`.

Responsibilities:

- establish the message hierarchy;
- write final visible page copy;
- preserve required verbatim content;
- distinguish confirmed facts from bounded implications;
- preserve unresolved contact or conversion destinations honestly;
- provide concise accessibility text for selected media where appropriate.

Restrictions:

- read-only scratch workspace;
- no repository access;
- no contact-detail invention;
- no unsupported certifications, testimonials, statistics, prices, or safety
  guarantees;
- no visual layout decisions beyond copy hierarchy and copy intent.

### 2. Concept Agents

Run exactly three independent concept agents in parallel. They receive the same
brief and media but cannot read one another's output.

Inputs:

- compact factual creative brief;
- owner-confirmed visual preferences and dislikes;
- approved media bytes and metadata;
- audience and conversion intent;
- framework capabilities;
- relevant design skills.

Output: one `CreativeConcept` per agent.

Each concept must define:

- one central creative idea;
- first-viewport composition;
- information hierarchy;
- typography direction using approved capabilities;
- color and image-treatment direction;
- exact supplied-media assignments;
- one recognizable visual motif;
- one signature motion opportunity;
- desktop, tablet, mobile, and reduced-motion translation;
- feasibility constraints;
- why the concept is specific to this business and audience.

Restrictions:

- read-only scratch workspace;
- no HTML, CSS, React, or Astro implementation;
- no external assets or fonts;
- no generic theme or template selection;
- no additional concept requests.

### 3. Creative Director

Use one durable creative-director identity and persist its OpenCode session ID.
The same director performs concept selection, realization review, and final
sign-off.

#### Selection and synthesis

Inputs:

- all three `CreativeConcept` artifacts;
- `CopyDeck`;
- compact validated brief;
- approved media evidence.

Output: `DesignPlanBundle`.

Responsibilities:

- score all concepts against the quality rubric;
- select one concept or explicitly synthesize named strengths from at most two;
- reconcile copy and visual hierarchy;
- lock the composition, media use, typography, responsive translation, and
  signature interaction;
- identify protected strengths that later agents must not dilute;
- reject generic or interchangeable treatments before implementation.

The director cannot request more concepts.

#### Realization review

Inputs:

- its own selected `DesignPlanBundle`;
- rendered desktop, tablet, and mobile evidence;
- motion evidence;
- deterministic validation report;
- implementation deviation report.

Output: `CreativeRealizationReview`.

The review must separately assess:

- concept fidelity;
- visual impact;
- audience and offer clarity;
- protected-strength preservation;
- responsive realization;
- proposal readiness.

The director may return only:

- `proposal_ready`;
- `polish_required`, with a finite set of repair findings;
- `realization_failed`.

#### Final sign-off

After a repair, the director receives the original repair brief and refreshed
evidence. It verifies only whether those findings were resolved without
damaging protected strengths.

The final result is only:

- `proposal_ready`;
- `realization_failed`.

The final review cannot introduce a new visual direction or another repair
list.

### 4. Implementation Agent

Inputs:

- immutable `DesignPlanBundle`;
- toolchain and dependency contract;
- writable-path contract;
- materialized approved media;
- required route mapping.

Output:

- source changes in one isolated worktree;
- typed `ImplementationReport` describing changed files and any deviations.

Responsibilities:

- implement the locked design in Astro/React/CSS;
- produce semantic, responsive source;
- implement static and no-JavaScript resting states;
- preserve the copy deck;
- use only supplied media and approved dependencies.

Restrictions:

- sole primary writer;
- no Git branch, commit, push, approval, or publish operations;
- no package installation or dependency changes beyond host-provisioned files;
- no concept redesign;
- no self-critique or iterative visual repair;
- no host-quality checks beyond narrowly necessary syntax feedback.

The host runs the authoritative build and validation after this agent exits.

### 5. Motion Agent

Inputs:

- `MotionSpec` from the selected design bundle;
- implemented DOM and component structure;
- approved GSAP capabilities;
- reduced-motion requirements.

Output:

- narrowly scoped source changes;
- typed `MotionImplementationReport`.

Responsibilities:

- implement the signature motion behavior;
- use scoped GSAP lifecycle and cleanup;
- preserve a complete static resting state;
- provide responsive and reduced-motion behavior;
- prevent layout or interaction regressions.

Restrictions:

- write access only to motion-owned files and explicitly named integration
  points;
- no copy changes;
- no broad layout redesign;
- no new dependencies;
- no self-dispatched review or repair.

### 6. Independent Critics

Run critics in parallel after deterministic rendering.

#### Experience critic

Reviews:

- offer comprehension;
- audience clarity;
- CTA prominence and honesty;
- reading sequence;
- mobile usability;
- interaction clarity;
- accessibility-related visual concerns.

#### Technical critic

Reviews:

- responsive defects visible in evidence;
- clipping and overflow;
- broken media treatment;
- motion side effects;
- implementation deviations from the plan;
- likely runtime or maintainability risks not covered by deterministic gates.

Both critics are read-only. Their findings cannot directly dispatch repair.

### 7. Repair Agent

The repair agent runs at most once and only when the creative director
consolidates concrete findings.

Inputs:

- immutable candidate source;
- `ConsolidatedRepairBrief`;
- protected strengths;
- before screenshots;
- relevant deterministic evidence.

Output:

- a child candidate;
- `RepairReport` mapping each requested repair to changed files and outcome.

Restrictions:

- fix only listed findings;
- do not introduce a new concept;
- do not rewrite unrelated copy or sections;
- do not request another critique or repair;
- preserve the original candidate for comparison and inspection.

## Quality Rubric

Concept selection and realization review use the same host-owned rubric. Store
the rubric as a typed contract or versioned application configuration, not as
freeform mutable model output.

Required dimensions:

- subject specificity;
- first-viewport impact;
- immediate offer comprehension;
- intended-audience clarity;
- visual coherence;
- supplied-media integration;
- typographic hierarchy;
- composition distinctiveness;
- conversion-path clarity;
- responsive quality;
- accessibility viability;
- purposeful motion;
- technical feasibility;
- absence of generic AI/template patterns.

Include an explicit interchangeability test: a concept loses proposal
eligibility when its design could represent an unrelated business after only
changing the logo and text.

Scoring alone does not approve a proposal. Deterministic gates must pass and the
creative director must return `proposal_ready`.

## Typed Contracts

Add contracts to `src/site_agent/core/design_contracts.py`. Follow the existing
validation and canonical hashing patterns used by `ArtDirection`,
`PageBuildRequest`, `BuildTarget`, `VisualCritiqueReport`, and
`DesignCandidateReceipt`.

### `CopyDeck`

Suggested fields:

- `schema_version`
- `run_id`
- `context_snapshot_hash`
- `language`
- `page_title`
- `meta_description`
- `navigation_labels`
- `eyebrow`
- `headline`
- `offer_summary`
- `primary_action_label`
- `primary_action_state`
- `sections`
- `faq_items`
- `media_alt_text`
- `required_phrase_coverage`
- `preserved_unknowns`
- `prohibited_claims_acknowledged`
- `content_hash`

### `CreativeConcept`

Suggested fields:

- `schema_version`
- `run_id`
- `concept_id`
- `context_snapshot_hash`
- `central_idea`
- `audience_rationale`
- `first_viewport`
- `information_hierarchy`
- `composition`
- `typography`
- `color_strategy`
- `media_assignments`
- `visual_motif`
- `signature_motion`
- `responsive_strategy`
- `reduced_motion_strategy`
- `feasibility_notes`
- `interchangeability_defense`
- `content_hash`

### `DesignPlanBundle`

Suggested fields:

- `schema_version`
- `run_id`
- `context_snapshot_hash`
- `copy_deck_hash`
- `concept_hashes`
- `selected_concept_ids`
- `selection_scores`
- `selection_rationale`
- `protected_strengths`
- `copy_deck`
- `art_direction`
- `composition_spec`
- `component_map`
- `media_plan`
- `motion_spec`
- `responsive_spec`
- `accessibility_intent`
- `implementation_constraints`
- `content_hash`

### `ImplementationReport`

Suggested fields:

- `schema_version`
- `run_id`
- `design_plan_hash`
- `changed_paths`
- `implemented_routes`
- `implemented_components`
- `media_paths_used`
- `deviations`
- `content_hash`

### `CreativeRealizationReview`

Suggested fields:

- `schema_version`
- `run_id`
- `design_plan_hash`
- `candidate_sha`
- `review_round`
- `verdict`
- `concept_fidelity_score`
- `visual_impact_score`
- `protected_strengths_preserved`
- `strengths`
- `realization_gaps`
- `required_repairs`
- `rejected_nice_to_haves`
- `content_hash`

### `CriticReport`

Suggested fields:

- `schema_version`
- `run_id`
- `candidate_sha`
- `critic_role`
- `findings`
- `content_hash`

Every finding must include:

- stable finding ID;
- viewport or evidence ID;
- exact visible problem;
- severity;
- target region or element;
- concrete repair instruction;
- observable acceptance condition.

### `ConsolidatedRepairBrief`

Suggested fields:

- `schema_version`
- `run_id`
- `parent_candidate_sha`
- `design_plan_hash`
- `protected_strengths`
- `included_finding_ids`
- `excluded_finding_ids`
- `repairs`
- `content_hash`

### Contract Rules

- Reject unknown fields.
- Bound every list and string length.
- Require canonical hashes for every input dependency.
- Reject a phase artifact whose run, base SHA, context hash, or dependency hashes
  do not match the durable run.
- Keep model prose out of orchestration decisions unless represented by a
  validated field.
- Never embed worked conversational examples in prompts or contract docs used
  as prompts.

## Durable Phase Persistence

Add a migration in `src/site_agent/core/memory.py` for a
`design_run_phase_artifacts` table.

Recommended columns:

- `id`
- `run_id`
- `phase`
- `variant_key`
- `attempt`
- `status`
- `input_hashes_json`
- `output_hash`
- `artifact_id`
- `provider`
- `model`
- `session_id`
- `transcript_artifact_id`
- `prompt_tokens`
- `completion_tokens`
- `reported_cost_usd`
- `started_at`
- `finished_at`
- `error_code`
- `error_detail`
- `created_at`
- `updated_at`

Constraints:

- foreign key to the design run;
- unique `(run_id, phase, variant_key, attempt)`;
- append-only successful payload identity;
- valid explicit status values;
- no overwrite of a successful artifact with a different hash.

Use the existing `Artifact` and `Memory.create_artifact()` boundary for payload
files and transcripts. Store canonical JSON under a path such as:

```text
design-runs/{run_id}/phases/{phase}/{variant_key}/{attempt}.json
```

Add narrow `Memory` methods rather than accessing `Memory.conn` outside
`core/memory.py`:

- create/claim a phase attempt;
- complete a phase with artifact metadata;
- fail a phase attempt;
- list phase artifacts for a run;
- retrieve the latest successful phase variant;
- verify artifact hashes;
- list resumable runs and phases.

## Internal State Machine

Preserve public design-run API paths and existing top-level statuses where
possible. Track detailed orchestration through phase artifacts and events.

Recommended internal phases:

1. `copy`
2. `concept/a`
3. `concept/b`
4. `concept/c`
5. `creative_selection`
6. `implementation`
7. `motion`
8. `deterministic_validation`
9. `creative_realization_review`
10. `experience_review`
11. `technical_review`
12. `repair_brief`
13. `repair`
14. `deterministic_revalidation`
15. `creative_final_signoff`
16. `proposal_materialization`

Phase transition rules:

- Copy and concept phases may run concurrently.
- Creative selection requires successful copy and all three concept artifacts.
- Implementation requires one valid design bundle.
- Motion requires a successful implementation artifact.
- Review requires a retained candidate and deterministic evidence.
- Repair requires `polish_required` and a nonempty validated repair brief.
- Final sign-off follows either the initial realization review when no repair is
  required or deterministic revalidation after one repair.
- Proposal materialization requires deterministic pass and creative
  `proposal_ready`.
- `realization_failed` is terminal for that run.

## Loop Prevention

Implement structural limits rather than relying only on wall-clock time.

### Dispatch limits

- The application coordinator contains the only phase transition table.
- OpenCode specialists have task delegation disabled.
- Every phase has a fixed maximum attempt count.
- Concept count is exactly three.
- Creative selection runs once.
- Primary implementation runs once.
- Motion implementation runs once.
- Creative realization review runs once before repair.
- Independent critics run once per candidate generation.
- Repair runs zero or one time.
- Final sign-off runs once.

### Retry policy

Allow one retry only for a transport interruption or invalid structured output
when no valid artifact was produced. A retry:

- uses the same phase inputs;
- does not solicit new creative direction;
- is recorded as a new attempt;
- cannot occur after a successful phase artifact exists.

Do not retry for:

- low creative scores;
- a rejected concept set;
- deterministic build failure caused by authored source;
- `realization_failed`;
- unresolved owner information;
- subjective requests for further improvement.

### Repair policy

- The repair brief is frozen before the repair agent starts.
- Only finding IDs in that brief are repairable.
- Post-repair reviewers verify existing findings; they cannot add repair work.
- Failed repair validation results in `realization_failed` or
  `needs_attention`, never another repair agent.

### Work preservation

- A timeout or malformed terminal response must not automatically destroy
  authored source.
- Snapshot the changed-path state before cleanup.
- If a valid implementation report is absent but source changes exist, retain
  an internal recovery artifact.
- The host may validate a recovered worktree only under an explicit recovery
  branch in the coordinator.
- Recovery never implies proposal readiness; it only prevents loss of work and
  supports diagnosis.

## OpenCode Adapter Changes

### Extract a narrow adapter

Create `src/site_agent/hands/opencode_provider.py` or an equivalently narrow
module. Move CLI execution and JSON event parsing out of the design policy.

Define a typed invocation request containing:

- agent name;
- model and provider settings;
- prompt artifact or prompt text;
- scratch/worktree path;
- attachments;
- environment allowlist;
- tool permissions;
- output contract identifier;
- session ID;
- wall-clock limit;
- event/tool-call limit;
- output-token limit.

Define a typed invocation result containing:

- terminal state;
- validated structured payload or implementation report;
- session ID;
- transcript artifact;
- tool calls;
- incremental usage totals;
- error code and bounded detail.

Change `run_opencode_turn()` so the agent name is an explicit argument instead
of always using `build`.

### Generate specialist agent definitions

Create focused agent files under the disposable workspace's
`.opencode/agent/` directory:

- `copywriter.md`
- `concept-designer.md`
- `creative-director.md`
- `site-implementer.md`
- `motion-designer.md`
- `experience-critic.md`
- `technical-critic.md`
- `repair-implementer.md`

Store the contract and behavioral rules in these files. Do not include worked
examples, sample replies, canned phrasing, or sample customer questions.

Permission profiles:

- planning and critic agents: no write/edit/patch, no package installation, no
  Git mutation, no task delegation;
- implementation agent: repository read/write within the isolated worktree,
  bounded shell access, no task delegation, no Git mutation;
- motion agent: narrowed file-path write access and bounded shell access;
- repair agent: changed-path allowlist derived from the repair brief, no task
  delegation;
- no specialist receives publish, approval, production credentials, or MCP
  mutation capabilities.

### Prompt assembly

Move specialist prompt assembly into `src/site_agent/brain/`.

Each prompt must contain only:

- the phase role and output contract;
- canonical references to required input artifacts;
- current validated facts needed by that role;
- applicable constraints;
- completion conditions.

Do not inject the entire incubation record, duplicated canonical request,
historical resolved questions, unrelated research, or every design skill into
every phase.

Assign skills by role:

- copywriter: voice/content constraints only;
- concept designer and creative director: design-core, frontend-design,
  high-end-visual-design, relevant visual guidelines;
- implementation: frontend engineering and accessibility guidance;
- motion: GSAP core, framework, timeline/ScrollTrigger when selected, and GSAP
  performance guidance;
- critics: only their review rubric and evidence contract.

## Application Coordinator

Add `src/site_agent/application/design_orchestration.py`.

The coordinator should implement or sit behind the existing `DesignBuilder`
application boundary. It must not be an LLM agent. It is deterministic service
code responsible for:

- loading and validating durable phase dependencies;
- dispatching ready phases;
- running independent phases concurrently where safe;
- persisting each result before advancing;
- resuming from the first incomplete phase;
- creating and retaining implementation worktrees;
- invoking host validation services;
- materializing a proposal only after final sign-off;
- returning a `DesignCandidateReceipt` compatible with existing service code.

Do not put this orchestration in `web/server.py` or `web/intake_lab.py`.

### Integration point

Update `DesignService.execute_build()` to call the coordinator through a narrow
port. Keep `OperationRoutingBuilder` behavior stable while introducing the new
implementation behind it.

Suggested rollout:

- add a configuration mode such as `design_engine.orchestration: specialist`;
- retain the existing native builder as a temporary compatibility mode;
- make new initial homepage runs use specialist orchestration after tests pass;
- do not silently fall back from specialist orchestration to the old
  open-ended builder after a failed phase.

## Worktree Ownership

Planning specialists use isolated no-Git scratch directories. They exchange
only typed artifacts through the application coordinator.

The implementation worktree is created only after creative selection. It is
owned by the coordinator and used sequentially by:

1. implementation agent;
2. host source validation;
3. motion agent;
4. host finalization.

The implementation and motion agents must not run concurrently.

After host finalization:

- retain the immutable candidate SHA;
- generate deterministic evidence from the retained candidate;
- run reviews against that candidate;
- create any repair as a child run/candidate;
- never mutate the reviewed parent candidate.

## Validation and Review Integration

Reuse the existing host-owned paths:

- `DesignService.validate_run()` for deterministic/build/browser validation;
- `design_visual_review.py` concepts and evidence handling where compatible;
- `DesignService.create_visual_refinement_run()` for immutable child repair
  semantics;
- existing Design draft linking and approval controls.

Refactor visual review so that:

- creative realization review uses the persisted creative-director session;
- independent critics receive the same immutable screenshots;
- the coordinator consolidates reports through a typed rule;
- only the creative director determines creative proposal readiness;
- deterministic failure always blocks proposal readiness;
- no reviewer mutates source.

## Proposal Materialization

A proposal is created only when:

- required source routes exist;
- dependency and changed-path policies pass;
- the real site build passes;
- browser checks pass for required viewports;
- accessibility gates pass;
- media provenance checks pass;
- the creative director returns `proposal_ready`;
- any required repair has passed deterministic revalidation;
- the candidate remains local and publishable only through owner approval.

The Design tab should present:

- the review iframe under the existing `/ada/api/review/...` path;
- desktop, tablet, and mobile evidence;
- a concise creative rationale derived from the selected design bundle;
- protected signature choices and media usage;
- the conversion path;
- motion and reduced-motion notes;
- honest unresolved owner inputs;
- approve, decline, and request-change controls.

Do not expose:

- raw OpenCode sessions;
- internal concept variants;
- prompt text;
- model reasoning;
- partial worktrees;
- failed candidates as finished proposals;
- raw external preview links as a substitute for Design review.

## Recovery Behavior

Update `DesignJobExecutor._recover_queued()` and related service methods.

Required behavior:

- inspect durable phase artifacts when recovering an interrupted run;
- verify artifact hashes before reuse;
- enqueue the first incomplete eligible phase;
- never rerun successful copy, concepts, selection, implementation, or motion;
- if a candidate SHA exists, resume deterministic validation or review;
- if an implementation worktree was interrupted before candidate
  finalization, retain it as a recovery artifact and mark the run as needing
  attention unless an explicit tested recovery path can safely finalize it;
- include run, phase, attempt, provider, agent, session, candidate, and worktree
  IDs in diagnostics.

## API Compatibility

Keep existing public endpoints stable.

Enhance existing run responses with an optional orchestration block containing:

- workflow version;
- current phase;
- completed phases;
- active specialist role;
- candidate identity when available;
- deterministic state;
- creative review state;
- proposal readiness;
- bounded failure summary.

The active-job endpoint remains an active-job view. Completed jobs remain
inspectable by run/job ID and conversation through existing durable APIs.

## Implementation Sequence

Each step should begin with a focused failing test or reproducible API request.
Avoid a broad rewrite of `opencode_runner.py`.

### Phase 1: Add contracts

Files:

- `src/site_agent/core/design_contracts.py`
- `tests/test_design_contracts.py`
- `tests/test_canonical_design.py`

Tasks:

1. Add the specialist artifact contracts.
2. Add canonical serialization and content hashes.
3. Validate cross-artifact run and context identity.
4. Add bounded list/string validation.
5. Test unknown-field rejection and dependency tampering.

Exit criteria:

- contracts round-trip through canonical dictionaries;
- hash changes are deterministic;
- mismatched dependencies are rejected;
- no service behavior changes yet.

### Phase 2: Add durable phase artifacts

Files:

- `src/site_agent/core/memory.py`
- persistence-focused tests following existing migration test patterns.

Tasks:

1. Add the phase-artifact migration.
2. Add typed persistence methods.
3. Add immutable completion semantics.
4. Add retrieval and resumability queries.
5. Add artifact-path and transcript references.

Exit criteria:

- successful phases cannot be overwritten;
- incomplete phases can be identified after restart;
- concurrent phase claims cannot both win;
- no direct `Memory.conn` usage is added outside `core/memory.py`.

### Phase 3: Extract the OpenCode provider adapter

Files:

- new `src/site_agent/hands/opencode_provider.py`;
- `src/site_agent/hands/opencode_runner.py`;
- `tests/test_builder.py` or a focused provider-adapter test module.

Tasks:

1. Extract process execution and event parsing behavior-preservingly.
2. Make agent name and permission profile explicit.
3. Persist transcript and usage incrementally.
4. Add structured-output validation hooks.
5. Add process, event, and tool-call limits.
6. Preserve and report partial invocation state on interruption.

Exit criteria:

- the old builder still works through the adapter;
- a test can invoke a named fake specialist;
- process-group termination remains reliable;
- incremental artifacts survive abnormal exit;
- agent dispatch is no longer hard-coded to `build`.

### Phase 4: Generate specialist agents

Files:

- new specialist prompt modules under `src/site_agent/brain/`;
- agent-file generation code in the OpenCode adapter/setup boundary;
- `tests/test_builder.py`;
- `tests/test_canonical_design.py`.

Tasks:

1. Generate all named agent definitions.
2. Apply role-specific skills.
3. Enforce read-only and writer permission profiles.
4. Disable task delegation for specialists.
5. Build compact phase prompts from typed artifacts.
6. Ensure prompts contain contracts and rules only, with no canned language.

Exit criteria:

- read-only agents cannot edit or invoke tasks;
- writer agents cannot push, approve, or publish;
- specialist prompts omit unrelated intake history;
- all generated OpenCode files remain excluded from Git.

### Phase 5: Implement orchestration through creative selection

Files:

- new `src/site_agent/application/design_orchestration.py`;
- `src/site_agent/application/designs.py`;
- `src/site_agent/hands/builder.py`;
- `tests/test_design_service.py`;
- `tests/test_design_jobs.py`.

Tasks:

1. Dispatch copy and three concepts concurrently.
2. Persist each output independently.
3. Resume without rerunning completed outputs.
4. Dispatch the creative director only after dependencies are complete.
5. Validate and persist `DesignPlanBundle`.
6. Preserve the creative-director session ID.

Exit criteria:

- exactly three independent concepts exist;
- one failed concept does not erase other completed artifacts;
- selection cannot run with missing inputs;
- selection cannot request a fourth concept;
- restart resumes at the first incomplete phase.

### Phase 6: Implement source and motion stages

Files:

- orchestration service;
- worktree/finalization helpers extracted from
  `src/site_agent/hands/opencode_runner.py` as needed;
- `src/site_agent/hands/site_build.py`;
- `tests/test_design_builder.py`;
- `tests/test_site_build.py`.

Tasks:

1. Create one implementation worktree from the immutable base.
2. Provision the native toolchain and approved media.
3. Dispatch the implementation agent with the locked bundle.
4. Validate changed paths and package ownership.
5. Dispatch the motion agent sequentially.
6. Finalize one immutable candidate and receipt.
7. Retain partial source evidence on interruption.

Exit criteria:

- only implementation and motion agents can write;
- implementation and motion never run concurrently;
- package versions remain host-owned and exact;
- no legacy Pelican paths are changed for an Astro target;
- candidate finalization does not depend on model-authored acceptance data.

### Phase 7: Add realization review and one repair

Files:

- orchestration service;
- `src/site_agent/hands/design_visual_review.py`;
- `src/site_agent/application/designs.py`;
- `tests/test_design_visual_review.py`;
- `tests/test_design_service.py`.

Tasks:

1. Run existing deterministic validation against the retained candidate.
2. Capture immutable viewport evidence.
3. Resume the selecting creative-director session for realization review.
4. Run experience and technical critics in parallel.
5. Create one consolidated repair brief.
6. Create a child repair candidate when required.
7. Revalidate once.
8. Resume the creative director for final sign-off.

Exit criteria:

- the selecting director reviews the realization;
- critics cannot trigger source changes;
- repair is limited to one child candidate;
- post-repair sign-off cannot add new repairs;
- failed realization never appears as proposal-ready.

### Phase 8: Proposal and UI integration

Files:

- application proposal/draft service boundaries;
- `src/site_agent/web/intake_lab.py` or existing HTTP translation only;
- `src/site_agent/web/static/` Design UI;
- relevant API and UI tests.

Tasks:

1. Expose orchestration progress in the existing run representation.
2. Link only proposal-ready candidates to Design review.
3. Show concise rationale and evidence.
4. Keep approval, decline, and request-change transitions explicit.
5. Verify every preview asset uses the `/ada` mount prefix.

Exit criteria:

- customer sees one coherent proposal, not pipeline internals;
- no production mutation occurs before approval;
- Design controls remain the only approval path;
- preview URLs and assets work under `/ada/`.

### Phase 9: Remove obsolete single-agent responsibilities

Only after specialist orchestration passes end-to-end tests:

1. Remove copy, concept generation, self-critique, browser-review, and recursive
   repair instructions from the implementation prompt.
2. Remove or relocate unused quality-repair prompt helpers.
3. Consolidate duplicated quality-policy construction.
4. Reduce `stage_design_build()` to compatibility orchestration or retire it
   after all callers migrate.
5. Update architecture documentation.

Do not delete the old path until retained historical runs remain inspectable and
the new coordinator handles all supported operation kinds.

## Focused Test Matrix

### Contracts

- valid artifact round trips;
- unknown fields rejected;
- oversized payloads rejected;
- context/base/dependency hash mismatch rejected;
- invalid verdict transitions rejected.

### Orchestration

- copy and concepts dispatch concurrently;
- exactly three concepts are accepted;
- creative selection waits for all required artifacts;
- only one selection artifact can succeed;
- successful phases are reused after restart;
- terminal creative rejection stops the graph;
- no phase can dispatch itself or an upstream phase.

### Permissions

- planning agents cannot write;
- specialists cannot use task delegation;
- implementation cannot Git commit, push, publish, or approve;
- motion writes only permitted paths;
- repair writes only repair-scoped paths.

### Candidate integrity

- implementation uses one isolated worktree;
- host-owned manifest is preserved;
- changed paths are validated;
- candidate receipt binds request, target, plan, and commit hashes;
- interrupted source is retained for diagnosis without becoming reviewable.

### Review

- selecting creative-director session is reused;
- realization review sees immutable screenshots;
- independent critic reports cannot mutate source;
- only consolidated findings reach repair;
- repair creates an immutable child candidate;
- final sign-off cannot create new findings;
- deterministic failure blocks proposal readiness.

### Recovery

- restart resumes first incomplete phase;
- completed provider phases are not charged or called again;
- retained candidate resumes validation rather than implementation;
- corrupted phase artifacts block recovery with diagnostics;
- active whole-run state does not conceal completed phase state.

### UI and approval

- only proposal-ready candidate creates/links a pending Design draft;
- iframe and assets work under `/ada/`;
- decline and request-change preserve candidate history;
- approval remains explicit;
- no raw preview link substitutes for Design review.

## End-to-End Acceptance Criteria

The implementation is complete when one initial homepage request can prove all
of the following:

1. Three distinct concepts and one copy deck are generated as durable artifacts.
2. One creative director selects and locks a design bundle.
3. The same director later reviews rendered realization evidence.
4. Only implementation and motion specialists modify source.
5. The host, not the model, owns build and browser validation.
6. Independent critics provide bounded reports without editing.
7. No more than one repair candidate is created automatically.
8. The workflow reaches a terminal proposal-ready or realization-failed state
   without backward transitions.
9. A process interruption resumes from durable phase artifacts instead of
   restarting the whole design.
10. The customer sees a polished Design-tab proposal only after deterministic
    checks and creative sign-off pass.
11. The candidate cannot publish without explicit owner approval.
12. Every phase remains inspectable by run, phase, artifact, provider, model,
    session, and candidate identifiers.

## Verification Order

Run focused tests after each implementation phase. Before declaring the full
change complete, run:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
git diff --check
```

Then exercise one local Intake Lab run using the repository debugging sequence:

1. Inspect the durable job by ID.
2. Inspect all phase artifacts and transitions.
3. Confirm the retained candidate and pending draft IDs.
4. Confirm the draft is pending.
5. Confirm the Design page list.
6. Load the review iframe through `/ada/api/review/{draft_id}/{page}`.
7. Inspect all CSS, JavaScript, and image requests under `/ada`.
8. Inspect desktop, tablet, mobile, and reduced-motion behavior.
9. Do not approve or publish during pipeline verification.

## Coding-Agent Handoff Rules

A coding AI executing this plan should:

- implement one numbered phase at a time;
- start each phase with a focused failing test;
- prefer behavior-preserving extraction over rewriting existing services;
- keep public API paths stable;
- use typed contracts at every new boundary;
- persist phase output before dispatching its consumer;
- include run, phase, attempt, provider, agent, session, worktree, and candidate
  identifiers in diagnostics;
- stop and report a concrete blocker rather than inventing missing product
  policy;
- never approve, publish, or mutate production during implementation;
- never commit credentials, databases, caches, worktrees, screenshots, or
  generated OpenCode configuration.
