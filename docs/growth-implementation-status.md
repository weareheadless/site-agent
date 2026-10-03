# Growth implementation checkpoint — not a production release

This file distinguishes implemented source from the unfinished product pipeline.
Do not report the SEO/AEO plan complete from this checkpoint, publish its release
tag, or enable customer candidate writes without the destination proof below.

## Source implemented

- One shared Growth list joins initiatives, owner actions, drafts and outcomes
  before filtering. Related records appear once; task discussion carries the
  canonical task and conversation identity as hidden metadata, not user text.
- The same list exposes Needs you, Ada preparing, Planned and Completed views.
  Specific lifecycle labels distinguish declined/replaced work, live observation
  and reviewed outcomes. Detailed analytics/research/competition tabs remain.
- Approved effects remain with Ada instead of becoming a second owner decision.
  Running/queued/retry status lives on the scheduled row; result observations and
  earlier versions stay attached to their original improvement.
- Both job-registration entry points use one live-Payload Growth coordinator:
  initial review, daily collection, weekly assessment, calendar-month research
  slot and durable pending-work recovery. Explicit operational pauses remain.
- Outcome review and configured provisioning retry are independently registered;
  content inventory failure cannot remove their schedules.
- The coordinator stores actual evidence and Ada assessment, not phase labels
  masquerading as candidate preparation. Missing required evidence blocks the
  affected initiative rather than manufacturing success.
- Conditional run acquisition and phase writes are fenced by the execution
  lease. Due-work filtering occurs before its limit; failures have persisted
  backoff. Scheduler locking uses an OS-held inode lock on macOS/Linux.
- An approval dispatch receipt is claimed before the provider effect. Concurrent
  processes invoke once. An uncertain result is reconciled by the same provider
  operation key, never automatically redispatched.
- A crash after receipt settlement can reconcile the owner action without
  repeating the external effect. API and control-plane draft decisions require
  the saved review hash for managed candidates; missing metadata cannot bypass
  this check. This does not replace the still-missing destination contract.
- Analytics/search history has one authority: tenant Memory via workspace API.
  Successful ingestion no longer depends on nonexistent Payload SEO mirrors.
- New-site content contracts retain source IDs and page sections. Canonical
  Lexical readers traverse the root; runtime database failures are surfaced.
- The shared server bridge owns the allowed method/path mapping, including
  explicit Growth checks. The template consumes that mapping.
- Package release CI now installs a committed dependency lock, tests/typechecks,
  inspects the packed source, and generates a source/integrity/artifact manifest.
  Package version **0.8.4 is a candidate**, not an existing published release.

## First remaining broken boundary

`evidence -> Ada assessment -> canonical private candidate -> exact rendered
preview -> owner approval -> verified publication -> measurement`

The existing customer/template Payload gateways publish the latest mutable
document by ID. They do not enforce conditional draft writes, immutable review
packages or managed membership across all native/service/restore publishers.
Sending `expectedHash` alone is not compare-and-swap.

The new coordinator therefore requires a destination-managed contract **before
any draft write** and requires actual renderer/publication-boundary validation
before a review can become publishable. These endpoints are NOT implemented on
the customer Workers yet. Their absence is an explicit preparation block, not
an alternative publication route. Do not remove this requirement to make the
tests or UI appear complete.

Implement a narrow shared server/platform provider (separate from the UI
package's ownership). Retain customer-specific public renderers and schema
extensions. It must own:

1. canonical schema/field/route manifests and complete inventory pagination;
2. conditional private effects with durable provider-local operation receipts;
3. immutable full candidate projections and the actual customer renderer preview;
4. destination-resolved managed membership for native, service and REST writes,
   global writes and version restoration—missing hashes cannot bypass approval;
5. exact reviewed-version approval and verified public rendering, not ID equality.

First failing integration test: public A, prepare B, pause B's publication
preflight, edit C through another Payload connection, resume B. A remains public,
C survives, B is stale, no publication receipt or impact clock is created.
Parameterise every publisher and restoration path. Then crash after provider
success before the Memory receipt: restart must recover that same effect.

## Other required work — not implemented by this checkpoint

- Connect monthly bounded research dispatch, task polling, provider actual costs,
  allowance/quote validation and uncertain-cost reconciliation to the coordinator.
  The current monthly slot explicitly blocks; reading saved research is not a
  monthly refresh. No paid production research was started for these tests.
- Connect article research/preparation and selected/provenance-bound main media;
  unify the current canonical Lexical/localised content adapters. Connect code
  candidates only through the proven autonomous Design pipeline and its gates.
- Wire generic managed-content approval/discard to the existing approval service
  with trusted owner identity, exact package hash, recovery and rejection lineage.
  UI eligibility alone is not server publication enforcement.
- Bind source identities, final/partial observation windows and freshness to
  collection evidence; support evidence-change re-evaluation without reusing
  indefinitely stale frozen material or duplicating work across weekly cycles.
- Move measurement clocks/baselines to exact, verified publication. Complete
  goal-change/domain-change/verified-publication triggers and outcome windows.
- Complete CrawlSEO competitor intersections/gaps/article evidence and supported
  AEO dataset contracts; the existing sampled SERP view is not an Ahrefs replacement.
- Wire a deterministic consumer rollout—not just package publication—with
  immutable per-customer artifacts, migration plans, previous good Worker versions,
  terminal deployment receipts and authenticated browser checks.
- Cut over new-site defaults, Atelier and Oceanic using that one provider and
  coordinator. Customer configs and production databases have NOT been migrated
  or enabled by this checkpoint.

## Verification performed

- Focused Python contract/execution/schema-migration/API tests: **66 passed**.
- Shared UI/server package tests after installing the committed lock: **25 passed**.
- Shared package TypeScript check passed after the clean dependency install.
- Python wheel build succeeded; this is not a clean production release artifact.
- Full Python suite: **1,081 passed, 5 failed**. Known failures concern the removed
  Pelican profile/tool, preview/environment fixtures and a sandbox-denied socket
  bind. This is not a clean full-suite pass. Do not conceal or silently skip them.
- Both user-owned production admin sessions were visibly authenticated. The
  changed UI has NOT been deployed or visually verified in those documents.
- No new release tag, package asset, customer Worker or public content was deployed.

## Release order after the missing boundary is proven

Commit the complete verified source; run clean builds and packed-artifact checks.
Publish the immutable tested package plus manifest, pin consumers/template to
that asset, back up and migrate the shared backend state, and promote the exact
customer artifacts. Record source, artifact, deployment and browser verification
as separate stages. A package tag or API response is not customer release proof.
