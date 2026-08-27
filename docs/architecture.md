# Architecture

This document describes the current supported shape of site-agent. `PLAN.md`
is a historical development log and is not the operational contract.

## Runtime

`main._build_runtime()` is the composition root. It loads configuration,
creates `Memory`, the LLM client, and the scheduler, then registers built-in
jobs. `serve` adds the FastAPI application and one durable chat-job executor.

The current compatibility boundary still passes a dictionary containing
`config`, `memory`, `llm`, and `persona_prompt`. New code should keep that
boundary stable while introducing typed objects at individual seams; do not
add a dependency-injection framework.

## Request And Approval Flow

```text
owner request
  -> POST /api/chat or a purpose-built setup endpoint
  -> chat_jobs row (queued)
  -> single executor (running)
  -> builder/editor
  -> pending draft
  -> Design iframe review
  -> explicit approve or decline
  -> adapter mutation and publish ledger
```

Jobs and drafts are different records and IDs. A completed job must be traced
through its result to the draft ID. The active-job endpoint is not a history
endpoint.

## Owner Workflow Contracts

Owner-facing work is represented by provider-neutral contracts in
`core/contracts.py`. `OwnerAction` records required owner input or a suggestion;
`Artifact` records immutable prepared work; `ApprovalRequest` binds explicit
permission to an artifact hash; and `ProviderReceipt` records a safe external
result. `Capability` describes one explicit operation and its effect class.

Owner actions move through `open -> started|waiting|snoozed|completed|dismissed|stale`;
started and waiting work may complete or become stale, and terminal states cannot
be reopened. Approval requests move from `pending` to `approved`, `declined`,
`expired`, or `failed`; an approved request may only become failed. State changes
are guarded in `Memory` and exposed to callers through application services.

## Application Workflow Layer

`application/` owns workflows that may be called by HTTP, scheduled jobs, or
future MCP adapters. `HomeService` composes the owner-facing read model,
`OwnerActionService` owns action deduplication and lifecycle transitions,
`ApprovalService` owns artifact-hash-bound decisions and provider receipts, and
`ConversationService` owns archive, restore, and deletion rules. These services
call `Memory` methods only; the server remains a session and transport adapter.

The existing website-draft approval endpoints remain a compatibility path behind
the narrow `SiteDraftApprovalAdapter`. New artifact approval flows should use
`ApprovalService` directly and must not route through FastAPI handlers.

## Preview Boundary

`web/preview.py` owns two concerns:

- building a staged Git ref into an isolated temporary output directory;
- rewriting site-owned HTML URLs relative to the rendered page.

Relative preview URLs are required because the admin application is deployed
under `/ada/` behind a proxy. The preview service must not hardcode a host or
assume that `/api/` belongs to site-agent.

The Design iframe is the review surface. A public production URL is never a
substitute for it because production intentionally remains unchanged while a
draft is pending.

## Dependency Direction

The intended direction is:

```text
web transport -> application workflow -> core contracts -> hands/senses
brain policy  -> application workflow -> core contracts -> hands/senses
```

Core modules must not import a concrete external adapter to resolve a secret
or perform a provider operation. Generic configuration helpers live in
`config.py`; concrete adapters remain under `hands/`.

## Existing Extension Seams

- `hands.base.SiteAdapter` is the publish-target seam.
- `hands.builder` is the compatibility builder seam and delegates to the
  native OpenCode implementation.
- `senses/` contains feed and metrics integrations.
- `brain.editor` owns the current repository tool loop and draft policy.

## Inner Life Boundary

Ada's private identity and a customer's work persona are separate prompt inputs.
`brain.prompts.inner_identity_prompt()` contains stable factual self-knowledge and
the persisted `inner_self` account; it never imports a site's subject, audience, or
work directions. `work_persona_prompt()` adds those customer-specific instructions
for website work.

`brain.self_model` periodically asks Ada whether recorded inner-life evidence changed
her self-understanding. The evidence is limited to her own inner-voice notes and
awakening decisions, with the existing self-model providing continuity; a raw dream
counts only after she decides it mattered. A no-change result is valid, and a
change is persisted with evidence IDs. This path is autonomous, customer-isolated,
and cannot create a draft or bypass an approval boundary.

Dream prompts do not prescribe human or machine imagery. They preserve Ada's factual
knowledge that she is an AI while leaving dream content to emerge from her retained
experience. External site reading is optional residue, not private identity.

These seams are intentionally small and partly legacy. When extending them,
add a narrow capability or protocol first, preserve compatibility wrappers,
and add a conformance test. Do not create a universal plugin abstraction.

## Future MCP/API Integrations

An MCP or API integration should call an application service rather than a
FastAPI route. Read-only providers may return normalized snapshots. Mutating
providers must return validated repository operations or go through the draft
service. Remote tool metadata is not trusted to classify side effects.

The first external integration should prove one narrow provider contract,
timeouts, error translation, and diagnostics before general tool discovery is
introduced.
