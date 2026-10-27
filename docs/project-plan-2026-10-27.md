# Project plan — 2026-10-27

Status of the Unified Business Intelligence initiative after the first delivery
push, the gaps that push exposed, and the workstreams that replace ad-hoc task
picking. This document supersedes the historical plan issues (crawlseo #3, #14,
site-agent #330, wix-site-bridge #3), which are closed with a pointer here.

## Where the project actually is

Delivered, merged and deployed:

| Capability | Evidence |
| --- | --- |
| Canonical business knowledge with revisions, provenance, CAS and acceptance | crawlseo `df2b92f`, `f2d1ebd` |
| Domainless project registration for prelaunch work | crawlseo `3eb5155` |
| Project-scoped research source identity and reuse | crawlseo `5a7f39d` |
| Prelaunch (domainless) bounded research | crawlseo `940bb10` |
| Confirmed/partial intake reaching canonical knowledge | site-agent `c2f90b6` |
| Incubation research dispatched to CrawlSEO, no local fallback | site-agent `4024e14` |
| Owner correction surface with revision fencing | crawlseo `3eb5155` |
| Question coverage, unresolved evidence requests, `FULFILLED` actions | crawlseo `f2d1ebd`, `ee458a1`, `48d3eaf` |
| Design context carrying accepted knowledge and research revisions | site-agent `f50e305` |
| Duplicate local knowledge producer retired | site-agent `46e7793` |
| AEO audit: published content and JSON-LD vs canonical knowledge | crawlseo `ec154a0` |
| AI visibility capability contract and observed-evidence importer | crawlseo `3f88377`, `3bd733e` |
| Disposable-fixture verification of the chain | crawlseo `13115a1` |

Deployed 2026-10-27: CrawlSEO web/worker/mcp on release slot
`13115a1-20261027032240` with the full 40-migration chain applied; site-agent API
release `20261027-api-intelligence-chain` (health-passed).

## The gaps this push exposed

1. **Backend without a surface.** Nothing in the owner's product shows any of
   it. There is no AI-visibility view, no question-coverage view, no way to tell
   an AEO action from an SEO one, and nothing in HelloAda at all. A capability
   the owner cannot see and act on is not delivered.
2. **No proven measurement.** The visibility importer accepts observed evidence,
   but no real observation exists, and one provider is not a market view. Until
   imports are routine, "AI visibility" is a contract, not a capability.
3. **Live verification is blocked, not skipped.** The paid prelaunch run cannot
   execute because the issued project credential carries `seo:research:request`
   while the endpoint requires `seo:research`.
4. **Release gates are weaker than they look.** CI runs tests and typecheck but
   never a production build, so a build-breaking change merges green and fails at
   release time. There is no rollback rehearsal and no seeded test tenant, so
   every verification run improvises its own fixture.

## Workstreams

### W1 — Surface (highest priority)

The owner-visible layer, in the order that makes the intelligence legible.

- **UI-023** CrawlSEO *Intelligence* area: AI access readiness, observed
  visibility (unknown stays unknown), question coverage, sources.
- **UI-024** Dimension taxonomy (`seo`/`aeo`/`geo`/`content`/`technical`),
  filters and counts in Work, and a provenance chain on every action detail:
  knowledge revision → finding → source → coverage → action → outcome.
- **UI-025** HelloAda owner intelligence summary, read through the existing
  service boundary, no copy of data.

Done when: an owner can open a site, see what is known, what is unknown, what is
waiting on them, and follow any action back to the evidence that produced it —
in both CrawlSEO and HelloAda.

### W2 — Proof (unblocks everything else)

- **OPS-010** Align the prelaunch research service scope so a tenant credential
  can call the endpoint it is documented to call.
- **OPS-003** then runs: one real paid request within USD 1.00/month and
  USD 0.10/operation, plus a replay proving no second spend.
- **OPS-004** incubation end to end against the deployed services.
- **OPS-005**, **OPS-006**, **OPS-007**, **OPS-008** as already scoped.
- **HV-001/002/003** owner sign-off on the visible result and on relevance.

Done when: every workstream has a live result, not a fixture, and the owner has
signed off on what they can see.

### W3 — Measurement

- Second provider adapter (the registry exists; adding one must not touch the
  importer).
- Scheduled or operator-run imports with a question set per project.
- Visibility surfaced as coverage against a stated denominator, with unknown
  kept explicit.

Done when: a site has recurring observations over at least two providers, and the
Intelligence view distinguishes observed, unobserved and not-applicable.

### W4 — Hardening

- **OPS-009** production build in CI.
- Rollback rehearsal for a bad Worker/API release.
- A seeded disposable tenant and project so verification stops improvising
  fixtures and credentials.

Done when: a deliberately broken change is caught before merge, and a bad release
can be rolled back in one documented step.

## Sequencing rule

W1 and W2 run in parallel: surfaces can be built while the paid path is being
unblocked, because they read the same data paths. W3 waits for W2's live
observation. W4 items are small and interleave with the rest.

## Standing decisions

- **CrawlSEO is the only authority** for canonical business knowledge and
  research. site-agent keeps process state and receipts that reference it. No
  shared database, no second copy of business truth.
- **No parallel producers.** Local research and knowledge producers are retired
  and fenced; a missing contract fails closed instead of silently degrading.
- **Truthfulness over completeness.** Unobserved is unknown; unreadable is
  unknown; a satisfied request is `FULFILLED`, not `DISMISSED`. Nothing may
  render a zero where nothing was measured.
- **The manager decides.** Task definition, acceptance, ordering and architecture
  belong to the coordinating manager; the owner is asked only about spending,
  production mutation, credentials, customer promises and product direction.

## Known risks

- Relevance is not provable by test. It is judged by the owner from real
  findings, which is why HV-003 exists separately.
- The paid provider path stays unverified until OPS-010 lands, so any claim about
  research quality today rests on fixtures.
- Both products can drift if a surface is built from a copy rather than a
  reference; UI-023/UI-025 must read the canonical paths.
