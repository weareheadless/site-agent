# Ada Experience-Fidelity Corrective Follow-up

## Status

Implementation follow-up for the Claro Oscuro acceptance failure. This document
is a bounded generic pipeline correction, not a run-specific design brief. It
must not be used to manually edit or polish a generated candidate.

## Failure boundary

```text
confirmed intake -> Ada planning -> Ada generation -> build
  -> deterministic validation -X-> visual/behavioral review -> owner review
```

The first broken boundary was Ada generation: the locked six-scene experience
was reduced to a hero-only beam plus generic section reveals. Host validation
then accepted weak evidence, and owner-readiness exposed a candidate whose
visual review was still in `repair`.

## Evidence from the incident

- The locked plan required one beam to progress through six ordered scenes and
  settle on the waitlist CTA.
- Ada's candidate marked only the hero beam as the signature behavior and used
  unrelated hairlines and generic reveals for later sections.
- The creative orchestration path marked the plan as integrated and bypassed
  the mandatory implementation/fidelity closure.
- Journey transition detection counted viewport-relative geometry changes from
  scrolling as behavioral transitions.
- Signature detection accepted any fingerprint change, including an offscreen
  looping hero drift during unrelated interaction probes.
- Signature absence was advisory, not blocking.
- Composition evidence did not reject extreme rendered media height or empty
  scroll/rhythm collapse.
- The one bounded repair was consumed before the complete visual and behavioral
  evidence was consolidated.
- `needs_repair` and `incomplete` candidates could still be projected as ready
  for owner feedback.

## Corrective objectives

1. Make Ada's experience-fidelity phase mandatory for every initial creative
   candidate.
2. Make browser evidence prove the declared trigger and ordered scene behavior,
   not merely any rendered change.
3. Separate scroll-induced viewport movement from element animation.
4. Make a missing required signature or scene transition a blocking gate.
5. Add domain-neutral rendered-media geometry guardrails, configurable through
   quality policy rather than hardcoded site assumptions.
6. Consolidate deterministic, behavioral, and visual findings before the one
   autonomous repair is spent.
7. Prevent repair, incomplete, or visually unresolved candidates from becoming
   owner-ready.

## Implementation scope

### A. Mandatory Ada fidelity closure

- Keep the complete locked plan hash-bound through the creative build.
- Run source coverage, local build/self-check, and the condition-driven
  experience-fidelity specialist on every initial creative candidate.
- Reject missing, blocked, wrong-hash, or incomplete fidelity reports before
  immutable candidate finalization.
- Preserve the one bounded Ada-authored repair, but classify a parent that never
  proved the defining journey as experience-fidelity repair rather than visual
  refinement.

### B. Host-owned browser evidence

- Probe each ordered scene with progressive scroll and controlled before,
  during, and after samples.
- Restore scroll and interaction state between probes.
- Normalize viewport-relative coordinates when comparing rendered fingerprints.
- Require a meaningful target/style trajectory during the declared trigger,
  while the target is visible, followed by a stable completion state.
- Do not accept candidate-authored state, source markers, animation-engine
  counts, unrelated controls, or offscreen ambient loops as proof.
- Exercise desktop, tablet, mobile, and reduced-motion translations.

### C. Composition guardrails

Record intrinsic and rendered image dimensions, aspect ratios, object-fit,
object-position, containing section size, and viewport-relative height. Add
configurable blockers for pathological media sizing or excessive empty scroll;
allow intentional exceptions only when the locked plan explicitly declares the
immersive treatment.

### D. Repair and readiness

- Consolidate all host findings before dispatching the single repair.
- Rerun the same complete evidence sequence after repair.
- Keep `needs_repair`, `incomplete`, visual `repair`, and visual `inconclusive`
  blocked from owner feedback.
- Retain all candidates and evidence for diagnosis; do not mutate production.

## Focused regression cases

- A bounding-box `y` change caused only by scrolling is not a journey transition.
- An unchanged signature with a candidate-authored observed claim remains
  unobserved.
- An offscreen or unrelated loop cannot satisfy a declared scene trigger.
- Hero-only motion does not satisfy a six-scene journey.
- Missing one required scene transition blocks the experience gate.
- Mobile continuous motion fails a static reduced-motion/translation contract.
- Oversized rendered media fails the composition gate.
- Creative orchestration invokes fidelity closure and does not swallow its
  failure.
- A visually unresolved or incomplete run is not owner-ready.

## Acceptance rerun

After the generic fixes, rerun Ada from the confirmed intake, not the retained
Claro Oscuro candidate. Verify the actual Design-tab iframe at desktop, tablet,
mobile, and reduced motion. Confirm hydration, module and asset requests,
ordered scene behavior, stable completion, visual review, elapsed time near the
20-minute target, and unchanged production. No manual candidate edit is valid
evidence.

## Mission checklist

1. Did Ada—not the coding agent—create the candidate from the intake?
2. Did the candidate visibly follow the defining experience/adventure path?
3. Was that behavior observed in the real owner review surface?
4. Did any workaround bypass the autonomous pipeline?
5. Is the result honestly ready for owner feedback within the intended journey?

Any `no` means the mission remains incomplete.
