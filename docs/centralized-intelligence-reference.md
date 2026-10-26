# Centralized intelligence architecture reference

Status: reviewed design baseline v0.2, 2026-10-25. This pointer contains no independent copy of the specification.

- [Canonical architecture at reviewed baseline](https://github.com/weareheadless/crawlseo/blob/a3c4d58c8ae7fd40e7c17341fd15b9c41d72042c/docs/architecture/centralized-intelligence/spec.md)
- [Implementation plan](https://github.com/weareheadless/crawlseo/blob/a3c4d58c8ae7fd40e7c17341fd15b9c41d72042c/docs/architecture/centralized-intelligence/implementation-plan.md)
- [Coding-agent workflow](https://github.com/weareheadless/crawlseo/blob/a3c4d58c8ae7fd40e7c17341fd15b9c41d72042c/docs/architecture/centralized-intelligence/agent-workflow.md)
- [Architecture review PR](https://github.com/weareheadless/crawlseo/pull/27)
- [Cross-repository Project](https://github.com/users/weareheadless/projects/3)
- [Parent initiative](https://github.com/weareheadless/crawlseo/issues/3)

Repository work: [UI-004 #336](https://github.com/weareheadless/site-agent/issues/336), [UI-006 #337](https://github.com/weareheadless/site-agent/issues/337), [UI-012 #338](https://github.com/weareheadless/site-agent/issues/338), [UI-016 #339](https://github.com/weareheadless/site-agent/issues/339). Existing migration workstream: #330.

Read the current issue, prerequisites and active PRs before implementation. UI-001 (shared contracts) and UI-013 (bridge inventory) are initially ready for bounded design work; dependent implementation remains blocked until contracts are reviewed. Do not assume the pinned design is an implemented API. Check for a newer approved spec revision in the initiative before coding, and pin the consumed contract fixtures in the PR.

CrawlSEO is proposed as the shared business/research/SEO/AI intelligence authority. Existing conversation, CMS, design, exact owner approval, platform credentials and release authorities retain their contracts. Business-knowledge transfer requires explicit import and cutover; a snapshot alone does not transfer authority. Existing source trust controls, target restrictions and publication rules remain binding.

Agents need repository access to the canonical private CrawlSEO reference; do not copy private evidence or credentials into public issues. This documentation change does not activate a tenant, authorize paid research, broaden permissions, or publish a website.

Reviewed delivery boundary: first prove one correctable business document, one sourced question and one supported HelloAda content improvement using the existing exact review path. The logical model is not a table-per-entity mandate; reuse current application services/infrastructure and a typed document with revisions first. Advanced schema, AI monitoring, Wix and Webflow work is explicitly Deferred and does not block the first HelloAda content proof. Source-maintenance effects require their own proven review capability (Site-Agent #252); do not use that limitation to redesign or block unrelated content work.

Bootstrap: UI-001 produces the first contract and UI-013 inventories bridge capabilities; both use `contract: null`. Claims are per issue, so these tasks may proceed independently. The manager can submit a worker’s claim and handle GitHub fetch/push/PR operations with the existing shared key when its environment has no token or network. Do not require a second credential setup for each worker.
