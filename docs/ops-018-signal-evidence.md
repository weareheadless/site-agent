# OPS-018: historical SIGINT evidence retrieval

## Result

The recovered record identifies Astrid's job 14 on 2026-10-28, from
00:41:40Z to 01:07:23Z. Its `memory.db` row records status `error` and the
minimal error identity `opencode exited 130`. This establishes a nonzero child
exit consistent with SIGINT; it does not establish the signal sender or
condition. No direct record attributes it to a timeout, job interruption,
heartbeat, or service restart. This is the bounded evidence prerequisite only,
not completion of issue #410.

## Sources checked

- The canonical tenant registry identifies Astrid as
  `site-5fe73d3d38ff6f77`; its `config.yaml` points to
  `/SOCIAL/site-agent-api/websites/site-5fe73d3d38ff6f77/data`. The inspected
  config and database path agree.
- Using read-only SQLite access, queried only job 14's `id,status,created_ts,
  updated_ts,error`: `error`, `2026-10-28T00:41:40+00:00` through
  `2026-10-28T01:07:23+00:00`, with error identity `opencode exited 130`.
  No prompt, result, payload, cookie, credential, or database dump was read.
- Checked the tenant's design-run metadata for `chat_job_id=14` using only
  run/status/time/error and artifact path/IDs; no matching row was present.
  Listed artifact filenames under that tenant's `design-runs` and
  `design-output-artifacts`; filenames/timestamps alone did not correlate a
  run to job 14 or identify a sender. No transcript or artifact contents were
  inspected.
- Checked `site-agent-api.service` journal for 2026-10-28 00:35–01:15Z as the
  current user. It returned no entries and stated that messages from other
  users were not visible; therefore it cannot establish whether a restart
  coincided with the job.
- Listed API release receipt/deployment-log filenames for the date. The
  available Oct 28 records did not provide a directly correlated sender or
  condition for job 14. No receipt/log establishes signal delivery to this
  child.
- Issue #410 comments identify jobs 8 and 9 as well; their records are not
  needed to attribute job 14, and no claims about their cause are made here.

The record proves the job identity, interval, failed status, and child exit
code, but not who sent SIGINT or why. Sender/condition attribution remains
unavailable in the inspected durable artifacts and restricted journal view.

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

No product code or tests were changed. The first acceptance criterion remains
unproven: no source is named because no inspected artifact directly records the
signal sender or condition. Acceptance criteria 2–4 remain engineering
follow-up and are not satisfied by this document.
