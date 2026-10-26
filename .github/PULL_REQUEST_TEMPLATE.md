<!-- UI/OPS agent work: complete the JSON and retain the task marker. For ordinary non-agent maintenance, remove this block and use normal repository review. Never remove the marker to bypass a task check. -->
<!-- agent-task
{
  "workId": "UI-000",
  "repository": "REPLACE_WITH_OWNER_REPOSITORY",
  "issueNumber": 0,
  "agentRun": "REPLACE_WITH_ACTUAL_RUN_ID",
  "branch": "codex/ui-000-task",
  "baseline": "REPLACE_WITH_FULL_BASELINE_SHA",
  "contract": {"repository": "weareheadless/crawlseo", "sha": "REPLACE_WITH_REVIEWED_CONTRACT_SHA"},
  "scope": ["REPLACE_WITH_EXACT_FILE_OR_DIRECTORY/**"]
}
-->

## Plan

TODO link the issue, explain the bounded change and existing code reused. Match the active issue claim. UI-001/UI-013 and OPS-001 bootstrap may use contract: null.

## Validation

TODO record commands, actual results and the exact tested commit. Distinguish local tests, current CI and remaining integration/production proof.

## Handoff

TODO explain acceptance coverage, contract/consumer impact, remaining blockers and what the manager should review. Stop before merge/deploy.
