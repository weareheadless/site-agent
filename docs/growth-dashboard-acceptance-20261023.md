# Growth service dashboard — acceptance record

This record separates implementation, immutable artifact publication, API activation,
customer rollout and authenticated acceptance. An unfinished row is not a pass.

## Source changes

- The shared admin consumes `growth-service-v1` directly. Its five expertise areas
  use explicit primary/secondary area relationships; no title-based categorization.
- One canonical decision list joins service-model IDs to existing task review
  handlers. Area cards do not create parallel approvals.
- Preparation, evidence limitations, actual next assessment and verified results
  come from the same service projection. Unclassified history is secondary.
- Artifact inspection requires the canonical dashboard and rejects the invented
  `task.area` model. Existing exact review, hash and publication gates remain.
- Collected Growth material is checkpointed before artifact persistence. Resumption
  binds the exact saved material before assessment/preparation. Existing artifacts
  for that run must match; conflicting evidence fails closed. No database repair,
  new scheduler, re-collection, approval bypass or fallback is introduced.

## Real observations before this release

- Both registered live tenant API responses pass the new UI contract validator.
- Oceanic exposes three canonical decisions: owner-information initiative 4 and
  exact ready proposals 7 and 8. Prepared proposals retain their draft/action/hash
  lineage and pass the existing readiness projection.
- Additional Oceanic findings wait for candidate capacity; they are not reported
  as active execution. Historical unresolved effects remain unresolved.
- Atelier exposed a preparation failure (`evidenceArtifactId` missing). Its durable
  run held collected material and a completed assessment but no evidence binding.
  The shared phase correction above addresses that boundary, not a tenant patch.

## Required evidence still to record

### October 23 live checkpoint (not final acceptance)

- API release `20261023-api-growth-evidence-checkpoint-1` serves source
  `553af9e67cfe00217351f183215a24cdf4962dc8`.
- Shared admin `0.10.27` is published with SHA-256
  `cec50a0f484a32767df23cd4f4e45479b8778b53d67260afb5a8a6f38d668882`.
- Oceanic release `runtime-20261023124308-e9201db1` and Atelier release
  `runtime-20261023125035-919f680d` passed deployment gates. Authenticated fresh
  documents show the five-area overview. Oceanic shows prioritized decisions
  8, 7 and 4; Atelier's answer control opens initiative 3 with its actual question.
- Visual checking found additional-decision title overflow. A narrow wrapping
  correction is staged for the next immutable package, not yet live.
- The normal Atelier retry exposed a second root failure: the evidence artifact
  embeds the entire durable inventory and exceeds the 100,000-byte contract.
  This must be fixed without raising the cap or discarding checkpointed evidence.
- A prepared Payload candidate's revision link needs an end-to-end exact-target
  revision contract, not merely a chat link. That correction is still under test.
- Approved paid acceptance cycle `growth-b6413f1b850241b5baf8bfc30e140b78`
  selected idea 12 for `article:2026-W43`. No provider request or reservation was
  created: the exhausted allowance was incorrectly classified as uncertain.
  The typed allowance correction is committed as `f82216a`, not yet activated.
  The owner-approved monthly cap of 700,000 micros is saved in the canonical
  tenant config; the next queued API release must load it. No history was reset.
- Browser transport disconnected intermittently during deeper review checks.
  An unobserved click or transport timeout is not recorded as a product pass.

- Full test results and immutable package artifact identity.
- Official-main API release receipt for the evidence-checkpoint correction.
- Canonical canary/fanout receipts for the new shared admin package.
- Fresh authenticated populated overview and exact review screenshots.
- Normal scheduled recovery of Atelier's interrupted assessment.
- Controlled approve/revise/decline and verified outcome acceptance.
- Automatic paid-research-to-article acceptance requires explicit research approval;
  an ordinary draft chat write is not a substitute for that pipeline.

No customer recommendation is approved by this engineering record. No paid
research authorization or browser acceptance is implied by passing source tests.
