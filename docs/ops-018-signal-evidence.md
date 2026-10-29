# OPS-018: historical SIGINT evidence retrieval

## Result

The historical SIGINT sender/condition cannot be established from the evidence
available in this retrieval. Exit status 130 is consistent with SIGINT, but it
does not identify who sent it or why. No attribution to a timeout, job
interruption, heartbeat, or service restart is supported here. This document is
the bounded evidence prerequisite only; it is not completion of issue #410.

## Sources checked

- Read issue #410 and its comments through the GitHub Issues API. The issue
  names Astrid jobs 14 (reported 00:41:40–01:07:23, approximately 24 minutes),
  8 and 9, and reports `opencode exited 130`; it does not give a date, run ID,
  tenant database path, or service generation.
- Checked the authorized API journal with
  `journalctl -u site-agent-api.service --since '2026-10-28 00:30:00' --until '2026-10-28 01:20:00' --no-pager -o short-iso`.
  It returned no entries (journal access also noted that messages from other
  users were not visible). Therefore this query cannot establish whether a
  restart coincided with the reported times.
- Listed canonical API release receipts under
  `/SOCIAL/payload-releases/runs/api/*/receipt.json`; available receipts include
  releases on Oct 28–29, but none identifies the relevant run from the issue's
  incomplete date/run metadata. Receipts and deployment logs were not treated
  as evidence of a restart at an unknown date/time.
- Narrowly queried only `id,status,created_ts,updated_ts,error` from the
  candidate existing SQLite `chat_jobs` databases:
  `/SOCIAL/site-agent/data/memory.db`,
  `/SOCIAL/configs/atelier-harmonie/data/memory.db`, and
  `/SOCIAL/configs/oceanicvibes/data/memory.db`. Atelier jobs 8/9/14 show
  `done` at Sept 18/21 timestamps; Oceanic Vibes jobs 8/9/14 show `done` at
  Aug 24–25 timestamps. These do not match or identify the runs described by
  issue #410. The shared database has no rows with those IDs. No prompts,
  cookies, credentials, or full database contents were queried.

The necessary evidence is unavailable: an exact run date and tenant/run
identity, plus the corresponding canonical job/run artifact and service journal
or release receipt/deployment log. The displayed job IDs alone are not
globally unique. No minimal historical excerpt can safely name a SIGINT sender.

## Current-code context (not historical attribution)

- `src/site_agent/hands/opencode_runner.py:4242-4253` turns its watchdog timeout
  into `RunnerError("opencode timed out after …")`, and otherwise reports a
  nonzero child return code such as 130 as `opencode exited …`. This code does
  not attribute the historical signal sender.
- `src/site_agent/application/designs.py:648` passes configured
  `provider_timeout_seconds` in the design execution configuration.
- Existing test `tests/test_builder.py:177` checks timeout wording; it does not
  prove timeout failure with the last stage and does not satisfy #410's stated
  stage-specific regression acceptance.
- `tests/test_workspace_build_progress.py:64-75` checks that a failed build
  preserves its stage and error in general. It does not establish that a timeout
  path records the last stage.

No product code or tests were changed. The sender/condition criterion remains
unproven pending correctly identified historical evidence.
