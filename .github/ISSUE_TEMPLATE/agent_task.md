---
name: Agent implementation task
about: A bounded task with code references, dependencies and observable acceptance
labels: ''
assignees: ''
---

## Work ID and result

Manager supplies the stable work ID. Describe current behavior and the smallest useful result.

## Starting points and scope

Repository-relative code/test paths; existing services to reuse; boundaries and exclusions.

## Dependencies and contract

Link direct prerequisites and the actual reviewed contract revision. Native blocking links must agree. Deferred work requires explicit manager selection.

## Acceptance

- [ ] Observable behavior and relevant failure/retry cases.
- [ ] No duplicate data owner or new framework without a demonstrated need.

## Validation

Relevant tests/checks and any separate integration/release evidence required.

## Agent pickup and handoff

Follow docs/agent-coordination.md. Record run ID, branch, baseline, contract and bounded paths using the shared claim protocol. Open an early draft PR, report actual tests and ask the manager about scope changes. Do not merge/deploy or interpret issue closure as live verification.
