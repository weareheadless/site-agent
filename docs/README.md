# Documentation

Start with `AGENTS.md` (rules) and `docs/architecture.md` (how the pieces fit).
Everything in `docs/archive/` is history and must not be used as implementation
guidance.

## Platform

| Document | What it settles |
| --- | --- |
| `architecture.md` | The current shape: platform package, site half, presentation, Payload, release, Ada's role |
| `manual-intake-and-ada-as-management-interface.md` | Manual intake; Ada provisions and manages; the owner authors the design; open decisions |
| `github-website-provisioning.md` | Importing an existing GitHub site without intake; the static presentation profile |
| `platform-release-runbook.md` | One source, exact SHAs, deployment receipts |
| `private-package-deployment.md` | Shared private packages in the VPS pipeline |
| `deploy.md` | Worked release example |
| `extensions.md` | Adapter, provider and MCP extension rules |
| `debugging.md` | Job, draft and preview runbooks |

## Tenant runtime and content

| Document | What it settles |
| --- | --- |
| `workspace-preview-repair.md` | Preview mount and unpublished-revision verification |
| `customer-presentation-migration-repair.md` | Preserving approved presentation through schema migrations |
| `payload-context-repair.md` | The shared client-context boundary |
| `business-catalog-contract-status.md` | Current catalogue schema and release state |
| `helloada-owner-workspace.md` | Owner workspace surfaces |
| `helloada-connection-contract.md` | HelloAda connection and handoff |
| `helloada-project-selector-to-payload-intake-contract.md` | Selector topology only; its intake journey is superseded |

## Mail, domains and measurement

| Document | What it settles |
| --- | --- |
| `mailflare-single-worker-contract.md` | Inbox, contacts, calendar and enquiry handling inside the tenant Worker |
| `seo-provisioning-and-domain-lifecycle.md` | GA4, Search Console, CrawlSEO and domain email provisioning |
| `crawlseo-connector.md` | CrawlSEO research authority connector |
| `crawlseo-migration-operations.md` | Tenant migration operations for CrawlSEO |

## Owner experience

| Document | What it settles |
| --- | --- |
| `growth-owner-experience-implementation-plan.md` | Current owner-approved Growth contract |
| `helloada-growth-workspace.md` | Growth owner decisions and evidence |
| `centralized-intelligence-reference.md` | Shared intelligence initiative baseline |
| `persona.md` | Ada's personality contract for onboarding |
| `agent-coordination.md` | Issue claiming, review, board discipline |
| `branch-hygiene.md` | Branch and worktree rules |

## Archive

`docs/archive/` holds superseded plans: the design-generation pipeline, intake
lab, growth acceptance records, UI-047/UI-056 evidence, OceanicVibes reports and
the original `PLAN.md`. They are kept because they explain how the current
contract was reached. Do not implement from them.

If a decision in an archived document still matters, restate it in a current
document instead of pointing at the archive.
