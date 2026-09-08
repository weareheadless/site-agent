# OceanicVibes Design POC

Status: blocked before candidate generation

Date: 2026-08-30

## Scope

The experiment used the sanitized intake in `examples/oceanicvibes.intake.json`
and the checked-in instance configuration. It ran in the disposable workspace
under `/tmp/opencode/oceanicvibes-run-20260830-retry` against the public
OceanicVibes repository.

The immutable baseline was:

```text
56aa25740389f74e4499d35d528d4b2376c82369
```

The experiment target was local-only, non-publishable, and configured with
`push_mode: none`.

## Completed

- Created a separate clone, data directory, and design database.
- Read the remote refs and pinned the experiment to the baseline SHA.
- Built the baseline site successfully with `bash build.sh`.
- Pelican processed 2 articles and produced the expected baseline output.
- Confirmed the disposable clone remained clean after the aborted generation.
- Made no GitHub push, adapter mutation, approval, or production publish call.

## Blocker

The experiment was initially invoked with an incorrect per-run provider
override. That override has been removed; the experiment now inherits the
global OpenRouter configuration:

```text
https://openrouter.ai/api/v1
deepseek/deepseek-v4-flash-0731
```

The corrected run reached OpenRouter/DeepSeek successfully, but the model
returned without making repository changes. The host no-change guard stopped
the run before candidate creation. No AI candidate, quality report, derived
page, or before/after comparison was produced, so the POC remains incomplete
and must not be treated as a design result.

## Next Run

After model access is available, rerun the same local experiment and record:

- candidate SHA and manifest hash;
- all quality-gate results and bounded repair attempts;
- one derived non-Pelican page;
- local baseline/candidate comparison;
- final remote-ref equality and live-instance immutability checks.
