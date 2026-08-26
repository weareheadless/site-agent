# Extension Contracts

Keep integrations narrow. A plugin should add one capability without needing
to understand the database, FastAPI, or the entire scheduler.

## Publish Adapters

Implement `hands.base.SiteAdapter` for a new publish target. The adapter owns
remote API details and should expose configuration validation, content/file
reads, commits, and deployment status. Preview, merge, and version operations
are optional capabilities until they are formalized.

Adapter rules:

- validate configuration before a mutation;
- accept an explicit branch where branch-aware behavior exists;
- return structured results with the affected path, branch, and revision;
- raise `AdapterError` for provider failures;
- never decide whether owner approval is required.

## Senses And Providers

Feed sources should normalize into feed items plus structured source errors.
Metric providers should return a named snapshot rather than leaking provider
payloads into brain code. A provider-specific MCP implementation should first
conform to one of these narrow interfaces.

## Builders

A builder receives a brief and an isolated site context. It may prepare a
preview and report progress, but it must not publish directly. A successful
changed build returns a preview revision and creates a pending merge draft.

Builder implementations must:

- use an isolated worktree;
- enforce writable paths before staging;
- keep production branch untouched;
- avoid inheriting unrelated secrets;
- return a structured outcome that includes validation and revision details.

## Tools And MCP

Internal and remote tools should eventually be registered with:

- a stable namespaced name;
- a JSON parameter schema;
- an effect class: `read`, `proposal`, or `external_mutation`;
- required capabilities;
- timeout and result-size limits;
- a handler that calls an application service.

MCP tool annotations are advisory only. A tool that can mutate a site must go
through the same draft and approval boundary as an internal tool. The first
MCP integration should be a fake-provider contract test plus one read-only
provider; do not enable arbitrary remote tool discovery by default.

## Compatibility Policy

Existing registry functions and dictionary-shaped return values are kept as
compatibility facades while a contract is introduced. New code should depend
on the contract, and tests should cover both the contract and the facade until
the old path is no longer used.
