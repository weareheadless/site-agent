# Intake Lab Test UI Implementation Plan

**Status:** Proposed implementation contract

**Date:** 2026-09-01

**Superseded intake entry:** The conversational intake contract in
`docs/conversational-design-intake-implementation-plan.md` is now authoritative
for how an Intake Lab session starts. The Lab begins with an empty draft; a
completed intake file is an explicit fixture/migration seed only.

**Authority:** This plan defines the local Intake Lab adapter. The candidate
generation and review lifecycle remains governed by
`docs/opencode-first-design-pipeline-implementation-plan.md`.

**Default local URL:** `http://127.0.0.1:3012`

**Reference acceptance pair:** `deepseek-ai/DeepSeek-V4-Flash` for implementation
and `Qwen/Qwen3.8-27B` for read-only visual review through ENTRIM. These are
instance-configured examples, not model names hardcoded into Intake Lab.

## Executive Decision

Add a standalone, loopback-only Intake Lab that simulates the handoff from a
completed HelloAda intake into site-agent's first-design workflow:

```text
editable design prompt + validated SiteIntake
  -> isolated non-publishable DesignRun
  -> OpenCode implementation model
  -> immutable candidate SHA
  -> host build and deterministic checks
  -> browser screenshots
  -> read-only visual-review model
  -> retained original/candidate preview and findings
```

The Intake Lab is a development adapter, not another admin feature and not a
replacement for the Design review flow. It must use the same application
services and typed contracts as the product path. It must never create a draft,
approve a candidate, push a ref, publish a site, or call an admin route.

Each click on **Generate initial design** starts an independent run from the
configured source baseline. It does not continue a previous candidate and does
not automatically create a visual-refinement child. A later feature may add an
explicit refinement action, but it is outside this implementation.

## Product Goal

Give an engineer or designer one focused local screen for testing first-design
generation against OceanicVibes or another configured website without entering
the site-agent admin UI or replaying a HelloAda conversation.

The user can:

- start the lab with an instance config, a default intake JSON file, and a
  dedicated workspace;
- edit a plain-language creative request;
- inspect and edit the complete structured `SiteIntake` JSON;
- submit only after `SiteIntake.from_dict()` accepts the intake;
- follow durable run stages while OpenCode and host checks execute;
- reopen completed and failed runs after a server restart;
- compare the immutable source baseline with the immutable candidate;
- switch among required pages and desktop, tablet, and mobile frames;
- inspect deterministic findings, browser evidence, and visual-review findings;
- see exact base and candidate SHAs and the configured model identities.

## Product Boundary

### Intake Lab owns

- translating one local HTTP submission into an application-service call;
- validating the user-supplied prompt and structured intake;
- reserving an isolated run clone and exact source SHA;
- queuing the existing durable design executor;
- projecting design-run state into a small, allowlisted UI response;
- serving immutable local previews and retained evidence;
- rendering a no-build local test interface.

### Intake Lab does not own

- freeform intake extraction;
- business-fact inference;
- creative brief generation;
- OpenCode prompting or coding policy;
- candidate finalization;
- build reproduction;
- deterministic or browser quality policy;
- visual-review prompting;
- production review, approval, merge, push, or publication.

Those responsibilities stay in `SiteIntake`, `DesignService`,
`DesignJobExecutor`, and the existing hands adapters.

## Non-Negotiable Invariants

- The server binds only to a loopback address.
- Every run uses `mode: local_experiment`, `push_mode: none`, and
  `publishable: false`.
- Every run begins at an exact 40-character source commit SHA.
- Every candidate preview resolves an exact 40-character candidate SHA.
- A run cannot call `create_review_draft()`, `approve_review_draft()`, a route
  function, or any production adapter.
- A production candidate is never exposed by Intake Lab, even if the workspace
  database is replaced with another site-agent database.
- The input prompt supplies creative direction only. `SiteIntake` remains the
  authority for customer facts, required pages, conversion details, assets,
  unknowns, and prohibited claims.
- There is no prompt-to-intake LLM call. Invalid intake returns field-oriented
  validation feedback and no design run is queued.
- A candidate is retained before build, browser, or visual-review failures can
  end the run.
- Failed and incomplete runs remain inspectable by run ID.
- Preview files and nested assets remain inside the selected run and immutable
  variant.
- Candidate code runs in a sandboxed iframe without same-origin access to the
  lab API.
- The lab child environment contains only operating-system values needed to run
  local tools and the configured implementation/visual-review credentials.
- GitHub, Cloudflare, R2, CrawlSEO, Cicero, admin, publication, and unrelated
  provider credentials do not enter child processes.
- Site-specific paths, page requirements, writable patterns, commands, and
  models come from the instance config or typed intake, not generic lab code.
- Existing admin paths and production Design state transitions remain stable.

## Explicit Non-Goals

- Do not add an Intake Lab tab to `web/static/admin.html`.
- Do not extend the legacy `application/design_lab.py` compiler workflow.
- Do not use `ReactDesignSpec`, `AstroReactCompiler`, or
  `frontend_scaffold` as the generation boundary.
- Do not duplicate `DesignService.execute_build()`, `validate_run()`, or
  `visual_review_run()` in a web route.
- Do not add a frontend framework, JavaScript package manager, or asset build.
- Do not expose arbitrary filesystem paths, Git refs, repository URLs, model
  credentials, transcript contents, or raw persisted rows through the API.
- Do not add model selection to the browser in the first version.
- Do not auto-create a repair or refinement run when visual review requests
  changes.
- Do not compare candidates from different runs side by side in the first
  version.
- Do not make a visual-review result equivalent to approval.
- Do not support remote hosting or shared team access.

## Architectural Decisions

| Decision | Contract |
|---|---|
| Runtime | A separate FastAPI application started by `site-agent intake-lab`. |
| Bind address | `127.0.0.1` by default; reject non-loopback hosts. |
| Default port | `3012`, configurable by CLI to avoid local conflicts. |
| UI delivery | One package-data HTML file with embedded CSS and JavaScript; no build step. |
| Persistence | A dedicated SQLite database below the supplied lab workspace. |
| Source | Prefer a configured local `site.clone_path`; otherwise clone the configured public GitHub repository. |
| Generation | `DesignService` plus `NativeOpenCodeBuilder`; no legacy design-lab service. |
| Execution | One existing `DesignJobExecutor` worker per lab process. |
| Browser evidence | A new per-run browser-adapter factory used by the executor. |
| Preview | Existing `PreviewBuildCache` and URL rewriting, generalized for an explicit route root. |
| Variants | `original` and `candidate`; never name a variant after a specific model. |
| Polling | Bounded HTTP polling; no SSE or WebSocket in the first version. |
| Review actions | Read-only. There is no approve, decline, publish, or refine button. |

## Target Architecture

```text
site-agent intake-lab CLI
  -> load config and optional fixture seed
  -> apply isolated lab config overlay
  -> open workspace/data/intake-lab.db
  -> construct NativeOpenCodeBuilder with sanitized env
  -> construct DesignService
  -> construct DesignJobExecutor with browser_quality_factory
  -> construct IntakeLabService
  -> create standalone FastAPI app
  -> start worker in application lifespan

browser POST /api/runs
  -> IntakeLabService.submit()
       -> validate prompt and SiteIntake
       -> resolve exact source baseline
       -> create isolated run clone
       -> DesignService.create_experiment()
       -> DesignService.prepare_initial_request()
       -> DesignService.build_target_for_run()
       -> DesignService.queue_build()
       -> DesignJobExecutor.enqueue()
  -> return 202 with run projection

DesignJobExecutor
  -> DesignService.execute_build()
  -> per-run PlaywrightQualityAdapter
  -> DesignService.validate_run()
  -> DesignService.visual_review_run() when configured and eligible
  -> durable terminal run

browser GET /api/runs/{run_id}/preview/{variant}/{path}
  -> require local-experiment run
  -> choose exact base_sha or candidate_sha
  -> PreviewBuildCache.read_file()
  -> rewrite nested preview URLs under the same route root
  -> return sandboxed-preview content
```

## Existing Code To Reuse

| Existing contract | Intake Lab use |
|---|---|
| `core/design_contracts.py:SiteIntake` | Validate the edited JSON without LLM extraction. |
| `application/designs.py:DesignService.create_experiment` | Reserve non-publishable local state. |
| `DesignService.prepare_initial_request` | Compile the typed intake into the canonical request. |
| `DesignService.build_target_for_run` | Derive allowed paths and local-only target policy. |
| `DesignService.queue_build` | Persist a complete job before enqueueing. |
| `DesignService.get_run` and `list_runs` | Rehydrate durable runs and events. |
| `application/design_jobs.py:DesignJobExecutor` | Execute and recover queued work. |
| `hands/builder.py:NativeOpenCodeBuilder` | Invoke the configured OpenCode implementation model. |
| `hands/design_experiment.py` | Clone a public or local source into an isolated root. |
| `hands/playwright_quality.py:PlaywrightQualityAdapter` | Capture route/viewport evidence under a per-run directory. |
| `web/preview.py:PreviewBuildCache` | Build and cache exact Git SHAs for iframe preview. |
| `web/preview.py:rewrite_preview_html/css` | Keep links, assets, and runtime fetches inside the preview tree. |
| `main.py:AdminProcessLock` | Prevent two long-lived processes from sharing one lab workspace. |

The implementation must not import or call `web.server.create_app`, admin route
functions, or `application.design_lab.DesignLabService`.

## Runtime Workspace

For a CLI workspace of `/tmp/opencode/intake-lab`, use this layout:

```text
/tmp/opencode/intake-lab/
  intake-lab.lock
  data/
    intake-lab.db
    design-runs/<run_id>/opencode.jsonl
    builder-worktrees/...
  runs/
    <run_id>/
      repository/
  screenshots/
    <run_id>/...
```

Rules:

- Resolve the workspace to an absolute path before constructing services.
- Reject `/` and the exact home directory. Also reject a workspace that is an
  ancestor or descendant of the current repository root, configured source
  clone, or configured data directory. A dedicated directory elsewhere below
  the home directory is valid.
- Use `runs/<run_id>/repository` as the `experiment_root` recorded on the design
  run.
- Do not delete run repositories, transcripts, screenshots, or the database on
  normal shutdown.
- `PreviewBuildCache` remains process-local and disposable. Restarting may
  rebuild a preview from the retained exact SHA.
- Do not place screenshots or transcripts inside a candidate repository.
- Acquire `intake-lab.lock` before opening the database. If acquisition fails,
  print a specific error and exit with status 1.

## CLI Contract

Add this top-level command:

```text
site-agent intake-lab \
  --config <site-config.yaml> \
  --workspace /tmp/opencode/intake-lab \
  --env-file .env \
  --host 127.0.0.1 \
  --port 3012
```

Arguments:

| Argument | Requirement |
|---|---|
| `--config` | Required through the existing global/common config handling. |
| `--intake` | Optional readable completed `SiteIntake` fixture; omit it for a blank conversation. |
| `--workspace` | Required dedicated local directory. |
| `--env-file` | Optional model-credential environment file. |
| `--host` | Defaults to `127.0.0.1`; only loopback names/addresses accepted. |
| `--port` | Integer from 1 through 65535; defaults to `3012`. |

Startup must:

1. Load the environment file into the parent process map without exporting it.
2. Load instance config with integration validation disabled.
3. If `--intake` was explicitly supplied, parse that seed with
   `SiteIntake.from_dict()` and fail before binding if it is invalid. Otherwise
   create sessions from an empty `DesignIntakeDraft`.
4. Deep-copy config and point `data_dir` at `<workspace>/data`.
5. Force design engine, builder, browser evidence, and visual review on for the
   full Intake Lab path while retaining configured provider/model identities.
6. Force local experiment push/publish policy regardless of instance defaults.
7. Build the strict child environment described below.
8. Open `Memory(<workspace>/data/intake-lab.db)`.
9. Construct builder, design service, executor, lab service, and web app.
10. Start Uvicorn and print the URL, source site name, implementation model,
    visual-review model, and workspace without printing secrets.
11. Let the FastAPI lifespan stop/join the executor and clear preview cache;
    after Uvicorn returns, close memory and release the process lock in the CLI
    `finally` block.

Do not silently choose a different port when `3012` is occupied. Report the
bind failure so the caller can pass another port or stop the old process.

## Lab Configuration Overlay

The runtime deep copy may change only test-runtime settings:

- `data_dir = <workspace>/data`;
- `design_engine.enabled = true`;
- `builder.enabled = true`;
- `design_engine.quality.browser = true`;
- `design_engine.quality.visual_critic = true`;
- `design_engine.experiment_root = <workspace>/runs`;
- effective push mode is always `none`;
- effective publishable value is always `false`.

The overlay must not replace:

- `site.repository`, `site.clone_path`, `site.branch`, or site build commands;
- configured implementation provider, model, base URL, or timeout;
- configured visual-review provider, model, base URL, or timeout;
- configured writable patterns or quality thresholds;
- intake-required pages with OceanicVibes-specific defaults.

`DesignService.quality_policy_for_run()` remains responsible for deriving
required pages and content from the persisted intake and brief.

## Application Service Contract

Add `src/site_agent/application/intake_lab.py` with a narrow
`IntakeLabService`. This is the only new orchestration boundary used by the web
app.

Constructor dependencies:

```python
IntakeLabService(
    design_service: DesignService,
    executor: DesignJobExecutor,
    *,
    config: Mapping[str, Any],
    workspace: Path,
    default_intake: SiteIntake | None,
    default_prompt: str,
)
```

Public operations:

```python
describe() -> dict[str, Any]
submit(prompt: str, raw_intake: Mapping[str, Any]) -> dict[str, Any]
list_runs(limit: int = 50) -> list[dict[str, Any]]
get_run(run_id: str) -> dict[str, Any]
pages(run_id: str) -> list[str]
preview_identity(run_id: str, variant: str) -> tuple[Path, str]
```

The dictionaries are documented projections, not raw memory rows. Add one
private projector with a detail flag and use it for both list and detail
responses so status, model, quality, and event semantics cannot drift. List
responses omit the full owner request, detailed evidence, and full finding
payloads; detail responses include their sanitized forms.

### `describe()`

Return only:

- site display name;
- implementation provider and model;
- visual-review provider and model;
- default prompt;
- optional fixture intake via `SiteIntake.to_dict()` (empty by default);
- supported variant names and viewport presets;
- `publishing_enabled: false`.

Do not return source paths, workspace paths, repository credentials, resolved
API keys, or full config.

### `submit()`

Perform this sequence in the application service, not the route:

1. Require a trimmed prompt between 1 and 20,000 characters with no unsupported
   control characters.
2. Require a JSON object and validate it through `SiteIntake.from_dict()`.
3. Generate `intake-lab-<uuid hex>` and reserve
   `<workspace>/runs/<run_id>/repository`.
4. Prefer `site.clone_path` when it is a Git repository: resolve the configured
   source ref to an exact SHA, then call `clone_local_repository()`.
5. Otherwise call `clone_public_repository()` using `site.repository` and
   configured branch, resolve its exact SHA, and remove its `origin` remote once
   the clone is complete so the run cannot push or fetch.
6. Call `DesignService.create_experiment()` with the validated intake, exact
   clone, SHA, explicit run ID, and prompt as `owner_request`.
7. Add an `intake_lab` event containing only non-secret provenance: input hash,
   configured model IDs, and `source_kind` equal to `local` or `public`.
8. Call `prepare_initial_request()`, `build_target_for_run()`, and
   `queue_build()`.
9. Re-assert `target.mode == local_experiment`, `target.push_mode == none`, and
   `target.publishable is False` before enqueueing.
10. Call `executor.enqueue(run_id)` only after the complete typed request and
    target are persisted.
11. Return the projected run.

If a failure happens after the design row exists, transition the run to
`failed` when the current transition permits it and add a bounded
`intake_lab_error` event. Retain any safe diagnostic clone. Never include secret
values in an error or event.

### Run projection

Return these fields where available:

```json
{
  "run_id": "intake-lab-...",
  "status": "building",
  "terminal": false,
  "operation_kind": "initial_build",
  "business_name": "OceanicVibes",
  "owner_request": "Create a cinematic...",
  "implementation": {"provider": "entrim", "model": "deepseek-ai/DeepSeek-V4-Flash"},
  "visual_review": {"model": "Qwen/Qwen3.8-27B", "state": "pending", "findings": []},
  "base_sha": "...",
  "candidate_sha": null,
  "publishable": false,
  "push_mode": "none",
  "quality": {"state": "pending", "gates": {}, "findings": [], "evidence": {}},
  "pages": ["index.html", "articles.html"],
  "events": [],
  "error": null,
  "created_at": "...",
  "updated_at": "..."
}
```

Requirements:

- Derive `terminal` from `DesignRunStatus`, not event text.
- Label missing quality and visual review as `pending`, not `passed`.
- Preserve structured findings; do not flatten them to prose.
- Include a candidate SHA for failed/incomplete runs when one was retained.
- Limit list responses to the latest 20 events per run.
- Detail responses may return up to 500 events in persisted order.
- Never return `planning_json`, context snapshots, raw transcript content,
  absolute artifact paths, or arbitrary event detail keys.
- Project browser evidence as route, viewport, measured result, screenshot hash,
  and bounded counts. Strip filesystem fields such as `path`, `screenshot_path`,
  clone roots, worktree roots, and transcript paths.
- Treat the optional diagnostic JSON disclosure as the sanitized projection,
  never the underlying persisted report.
- Allowlist safe event detail keys such as stage, message, timestamp, worker,
  candidate SHA, model ID, state, and bounded counts.

## Design Executor Change

Modify `application/design_jobs.py` without changing existing callers.

Add optional context key:

```python
browser_quality_factory: Callable[[str, Mapping[str, Any]], BrowserQualityAdapter]
```

At validation time:

1. If the factory exists, call it once with `run_id` and the current run.
2. Otherwise retain the current `context["browser_quality"]` behavior.
3. Pass the resulting adapter only to `DesignService.validate_run()`.
4. Add a bounded event if adapter creation fails, then let normal durable error
   handling preserve the candidate.

Add a small public read-only `running` property that reports whether the worker
thread is alive and not stopping. Intake Lab uses it for `/healthz` and to
reject a submission with 503 rather than persisting work that this process
cannot execute. Do not expose or inspect `_thread` from the web adapter.

The Intake Lab factory must create:

```python
PlaywrightQualityAdapter(
    workspace / "screenshots" / run_id,
    variant="candidate",
    routes=SiteIntake.from_dict(run["intake_json"]).site["required_pages"],
)
```

Do not share one adapter across runs. Do not use the implementation model name
as the variant.

### Restart behavior

Keep restart behavior explicit and bounded:

- Re-enqueue persisted pre-build jobs only when their latest durable event is
  `queued`, as today.
- Resume `candidate_ready` at host validation without invoking OpenCode again.
- Resume `validating` at deterministic validation or visual review based on the
  persisted `visual_review_pending` event and quality report.
- Never invoke OpenCode a second time for a run that already has a
  `candidate_sha`.
- A run found in `building` after process restart is transitioned to
  `interrupted` with a restart diagnostic; the first version does not attempt
  to resume an abandoned OpenCode process.
- Terminal runs are never re-enqueued.

Implement stage dispatch inside the executor rather than duplicating it in
Intake Lab. Add focused tests before broadening recovery states.

## Web Application Contract

Add `src/site_agent/web/intake_lab.py`.

The module owns HTTP/session translation only:

- app creation and lifespan;
- loopback-origin checks;
- JSON request/response translation;
- static shell delivery;
- polling endpoints;
- preview token and immutable file responses;
- conversion of known application errors to bounded HTTP errors.

It must not clone repositories, resolve Git refs, prepare requests, queue builds,
read `Memory.conn`, run browser checks, or call model providers.

### Endpoints

| Method | Path | Result |
|---|---|---|
| `GET` | `/` | Intake Lab HTML shell. |
| `GET` | `/api/lab` | Safe metadata, default prompt, and default intake. |
| `POST` | `/api/runs` | Validate, create, persist, and enqueue one run; return 202. |
| `GET` | `/api/runs?limit=50` | Latest local Intake Lab runs. |
| `GET` | `/api/runs/{run_id}` | Durable run detail and bounded events. |
| `GET` | `/api/runs/{run_id}/preview-token` | Short-lived token scoped to that local run. |
| `GET` | `/api/runs/{run_id}/pages` | Required pages and available variant URLs. |
| `GET` | `/api/runs/{run_id}/preview/{variant}/{file_path:path}` | Immutable preview file. |
| `GET` | `/healthz` | Process and worker availability only. |

Do not add CORS for the lab API. Reject browser requests whose `Origin` header
is present and not the current loopback origin.

### Request schema

`POST /api/runs` accepts exactly:

```json
{
  "prompt": "Create the first website design from this completed intake.",
  "intake": {"schema_version": 1}
}
```

Reject unknown top-level keys. Enforce `MAX_CONTRACT_BYTES` before parsing or
validating the intake. Return errors in this shape:

```json
{
  "error": {
    "code": "invalid_intake",
    "message": "conversion.contact_destination is required or conversion.not_available must be true"
  }
}
```

HTTP semantics:

| Status | Meaning |
|---|---|
| `202` | Typed run persisted and queued. |
| `400` | Malformed JSON, invalid prompt/intake, variant, path, or limit. |
| `403` | Non-loopback origin or invalid preview token. |
| `404` | Unknown run or unavailable immutable preview file. |
| `409` | Workspace/run identity conflict or unsafe source state. |
| `413` | Request exceeds contract limit. |
| `503` | Worker is unavailable during submission. |

Do not serialize Python tracebacks to the browser.

## Immutable Preview Contract

Generalize `web/preview.py` only as much as needed to support a caller-supplied
preview route root while preserving every existing admin call.

Add an optional `preview_root` parameter to `rewrite_preview_html()` and its
injected runtime. Existing callers that omit the argument retain current route
detection. Intake Lab passes the exact route prefix:

```text
/api/runs/<run_id>/preview/<variant>/
```

Preview rules:

- `original` maps only to persisted `base_sha`.
- `candidate` maps only to persisted `candidate_sha`.
- Reject all other variants.
- Require the run mode to equal `local_experiment` and `publishable` to be false.
- Validate `run_id` through the service and `file_path` as a safe POSIX-relative
  path without empty, dot, dot-dot, or symlink traversal.
- Use `PreviewBuildCache.read_file(clone, exact_sha, file_path)`.
- Never build `HEAD`, a branch, a candidate ref, or request-provided ref.
- Apply `rewrite_preview_html()` to HTML and `rewrite_preview_css()` to CSS.
- Set an accurate content type and `Cache-Control: private, no-store` on tokenized
  preview responses.
- Permit `Access-Control-Allow-Origin: null` only on preview-file responses so
  sandboxed candidate scripts can fetch rewritten local assets. Never add that
  header to lab API responses.
- Return 404 when the baseline did not contain a required page or no candidate
  SHA exists yet; the pages response marks that variant unavailable.

Use `PreviewAccess` with scope `(run_id, "intake-lab")`. A token grants read
access only to preview files for that run and expires using the existing TTL.

The UI iframe must use:

```html
<iframe sandbox="allow-scripts" referrerpolicy="no-referrer"></iframe>
```

Do not add `allow-same-origin`, `allow-top-navigation`, `allow-popups`, or form
submission. This keeps untrusted candidate JavaScript from reading or mutating
the lab API.

## UI Contract

Add `src/site_agent/web/static/intake_lab.html` as a single no-build document.
Keep all shell JavaScript dependency-free and use text nodes or explicit HTML
escaping for persisted values.

### Information architecture

Desktop layout:

```text
+----------------------------------------------------------------------------+
| INTAKE LAB   site name   implementation model   visual-review model        |
+------------------------------+---------------------------------------------+
| Intake sheet                 | Run trace                                   |
|                              | created -> planning -> building -> review   |
| Creative request             +---------------------------------------------+
| [textarea]                   | Original | Candidate | Split   page viewport|
|                              |                                             |
| Completed intake JSON        |               sandboxed preview             |
| [editor with validation]     |                                             |
|                              +---------------------------------------------+
| [Generate initial design]    | Evidence: deterministic | browser | visual  |
+------------------------------+---------------------------------------------+
| Previous runs: status, business, candidate SHA, updated time               |
+----------------------------------------------------------------------------+
```

Mobile layout:

- Stack intake, run trace, preview, evidence, and history in that order.
- Keep controls visible above the preview rather than in a horizontal overflow.
- Render only one preview variant at a time below 760px; hide the split option.
- Use preset iframe widths inside a horizontally scrollable stage without
  shrinking the tested viewport.

### Visual direction

The page should resemble a focused test instrument, not an admin dashboard or
marketing page.

Use this compact token direction:

| Token | Value | Use |
|---|---|---|
| `--paper` | `#f3f6f5` | Main shell background. |
| `--ink` | `#152126` | Primary text and strong rules. |
| `--slate` | `#52636b` | Secondary labels. |
| `--panel` | `#ffffff` | Input and evidence surfaces. |
| `--signal` | `#087f83` | Active stage and primary action. |
| `--watch` | `#b77916` | Incomplete or needs-attention state. |
| `--fault` | `#b44747` | Failed state. |
| `--rule` | `#cbd5d5` | Structural separators. |

Use the local system sans stack for interface text and `ui-monospace` for JSON,
events, model IDs, and SHAs. Do not fetch fonts. Avoid gradients, glass effects,
large hero text, excessive cards, and decorative status icons.

The signature element is one continuous run-trace rail. Each persisted lifecycle
event attaches to the rail in order, so the structure communicates actual work
rather than decorating the page with generic numbered steps.

Keep corners from 0 through 6px, use one-pixel rules, and spend color only on
active and terminal states. Motion is limited to a subtle active-stage pulse and
must stop under `prefers-reduced-motion: reduce`.

### Initial state

- Load `/api/lab` and populate the prompt and pretty-printed default intake.
- Show the configured site and models before submission.
- Show an empty trace message: `No run selected. Generate an initial design or open a retained run.`
- Parse the JSON editor on input with a short debounce.
- Disable generation when local JSON parsing fails.
- Server validation remains authoritative; do not reproduce all `SiteIntake`
  rules in JavaScript.

### Submission state

- Button label changes to `Preparing isolated run...` while the POST is pending.
- Disable only submission inputs, not history navigation.
- On 202, select the returned run and start polling.
- On validation failure, keep the edited values and focus the error summary.
- Never clear the intake or replace it with model-produced content.

### Active run state

- Poll every second while selected status is non-terminal.
- Slow to every five seconds while the document is hidden.
- Abort stale requests when the selected run changes.
- Stop polling at a terminal status.
- Render events in persisted order with stage, message, and timestamp.
- Show `Waiting for candidate` in the candidate pane until `candidate_sha`
  exists.
- Do not infer completion from the runs list; always fetch the selected run ID.

### Preview state

- Load page availability and one short-lived token after a candidate or terminal
  state becomes previewable.
- Page control uses intake-required paths in their original order.
- Variant controls are `Original`, `Candidate`, and desktop-only `Split`.
- Viewport presets are Desktop 1440x1000, Tablet 768x1024, and Mobile 390x844.
- Candidate is the default when available; otherwise show Original.
- A missing original page is an explicit `Not present at the source SHA` state,
  not a broken blank iframe.
- Display exact SHAs above the frames with copy buttons.
- Token values never appear in visible text or browser storage.

### Evidence state

Use three compact sections:

| Section | Content |
|---|---|
| Deterministic | Overall state, gate map, and structured findings. |
| Browser | Routes, viewports, screenshot count, and browser findings. |
| Visual review | Reviewer model, state, summary, findings, and requested changes. |

Render `pending`, `passed`, `needs repair`, `incomplete`, and `failed` distinctly.
Do not collapse `incomplete` into failure or treat missing evidence as passing.
Show structured JSON in an optional disclosure for diagnostics, but default to a
human-readable finding list.

### History state

- List latest runs by updated time.
- Show business name, status, short run ID, short candidate SHA, and timestamp.
- Selecting a run replaces trace, preview, and evidence without changing editor
  input.
- A reload restores the most recently selected run from URL query `?run=<id>`.
- Do not store intake, prompt, run results, or tokens in `localStorage`.

### Accessibility

- Every editor, select, and button has a visible label.
- Use a live region for run-status transitions and submission errors.
- Use `aria-current="step"` on the active trace stage.
- Preserve visible focus rings with at least 3:1 contrast.
- Do not encode status by color alone.
- All disclosures and variant controls are keyboard operable.
- Iframes have variant/page-specific titles.
- The interface remains usable at 320px width and 200% zoom.

## Credential And Process Isolation

Do not pass the full environment produced by `load_env_file()` to the builder or
visual reviewer.

Add a lab-specific environment builder that starts empty and sets only:

- `PATH`, `USER`, `LANG`, `LC_ALL`, `TMPDIR`, and `SHELL` when present;
- `HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, and `XDG_DATA_HOME` to dedicated
  directories below `<workspace>/process-home`, never to the caller's real home;
- `SSL_CERT_FILE`, `SSL_CERT_DIR`, `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` when
  present and needed for configured providers, rejecting proxy URLs that embed
  username or password data;
- `GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_NOSYSTEM=1`,
  `GIT_CONFIG_GLOBAL=/dev/null`, and `GIT_ASKPASS=/dev/null`;
- the exact environment key referenced by the implementation provider;
- the exact environment key referenced by `design_engine.visual_review` or the
  configured vision provider.

Resolve credential variable names from config fields already used by provider
code, including `design_engine.api_key_env`,
`design_engine.visual_review.api_key_env`, `env.llm_api_key`, and
`env.vision_api_key`. If implementation and visual review share one key, include
it once.

Reject any additional copied variable whose name contains `TOKEN`, `KEY`,
`SECRET`, `PASSWORD`, or `CREDENTIAL` unless it is one of those exact selected
model credential variables. Then pass the result through
`DesignService.experiment_environment()` as a final denylist defense.

Never log environment values. Tests must use sentinel secrets and assert that
only selected model credentials reach fake builder/reviewer adapters.

For Git isolation:

- local-source clones use `clone_local_repository()`, which removes `origin`;
- public-source clones remove `origin` after resolving the baseline;
- build targets always use `push_mode: none`;
- no GitHub adapter is constructed;
- acceptance compares source `HEAD`, source status, and remote refs before and
  after a run.

## Error And State Language

Use direct, actionable messages:

| Condition | UI message |
|---|---|
| Invalid JSON | `The intake is not valid JSON. Fix the highlighted syntax before generating.` |
| Invalid typed intake | Display the exact bounded `SiteIntake` contract message. |
| Port occupied | `Intake Lab could not bind 127.0.0.1:3012. Stop the existing process or pass --port.` |
| Build active | `OpenCode is implementing the first candidate.` |
| Candidate retained | `Candidate retained at <short SHA>. Host checks are running.` |
| Visual repair requested | `Visual review retained the candidate and requested changes.` |
| Evidence incomplete | `The candidate is retained, but required evidence is incomplete.` |
| Restart interruption | `The build process ended during a restart. This run remains inspectable; generate a new run to retry.` |

Do not use vague `Something went wrong` messages when a safe persisted error is
available.

## File-Level Change Plan

### Add `src/site_agent/application/intake_lab.py`

- Validate submission input.
- Resolve and clone the configured source safely.
- Create and queue a local experiment through `DesignService`.
- Project allowlisted run, quality, visual-review, event, and page state.
- Resolve exact preview identities.
- Build the strict model-only child environment if composition belongs here;
  otherwise keep it as a pure helper called by the CLI.

### Add `src/site_agent/web/intake_lab.py`

- Create the standalone FastAPI app.
- Own lifecycle startup/shutdown for the injected executor and preview cache.
- Expose the endpoints in this plan.
- Issue and validate preview access tokens.
- Serve immutable preview files with route-root rewriting.
- Provide a `serve_intake_lab()` helper only if it keeps `main.py` small.

### Add `src/site_agent/web/static/intake_lab.html`

- Implement the dependency-free shell, editor, trace, preview, evidence, and
  history.
- Keep candidate content sandboxed.
- Use safe DOM APIs for persisted values.

### Modify `src/site_agent/application/design_jobs.py`

- Support a per-run browser adapter factory.
- Add stage-aware restart recovery without re-running a retained candidate.
- Preserve static `browser_quality` compatibility for existing admin callers.

### Modify `src/site_agent/web/preview.py`

- Add optional explicit preview-root support to the injected runtime.
- Preserve default behavior for every current admin and Design route.
- Add focused tests for the new route root and nested fetch rewriting.

### Modify `src/site_agent/main.py`

- Register `intake-lab` and its arguments.
- Compose the isolated runtime.
- Enforce loopback binding and workspace lock.
- Let app lifespan own worker/cache shutdown; close memory and lock on all CLI
  exits after the server returns.
- Do not route the command through `_cmd_serve()` or admin runtime creation.

### Add `tests/test_intake_lab_service.py`

- Test validation, isolation, queueing, projection, source selection, and secret
  filtering with fake builder/executor dependencies.

### Add `tests/test_intake_lab_web.py`

- Test HTTP schemas, run polling, restart visibility, preview isolation, shell
  safety, and loopback-origin handling with `TestClient` and temporary Git
  repositories.

### Modify focused existing tests

- `tests/test_design_jobs.py` for browser factory and restart dispatch.
- `tests/test_preview.py` for explicit preview roots.
- `tests/test_main.py` for CLI defaults, host rejection, and cleanup.

No memory migration is required. Intake Lab uses existing design-run and
design-run-event persistence in its dedicated database.

## Implementation Phases

### Phase 1: Lock focused contracts with failing tests

Add failing tests for:

- valid submission creates one local, non-publishable run and one queued event;
- invalid `SiteIntake` creates no queued run;
- the prompt is persisted as `owner_request` but does not alter intake facts;
- source and workspace overlap is rejected;
- child environment omits sentinel production credentials;
- one browser adapter is created per run;
- a retained candidate is not rebuilt during recovery;
- explicit preview roots rewrite nested HTML, CSS, and runtime fetch URLs;
- preview cannot read a production-mode run;
- CLI defaults to loopback port 3012.

Do not start UI implementation until these boundaries fail for the expected
reason.

### Phase 2: Add application orchestration

Implement `IntakeLabService`, source-clone selection, local-only assertions,
strict environment construction, and allowlisted run projection. Use a fake
executor to prove exactly one enqueue happens after typed job persistence.

Exit criterion: service tests pass without FastAPI, Playwright, provider calls,
or network access.

### Phase 3: Generalize executor and preview seams

Add `browser_quality_factory`, stage-aware recovery, and optional explicit
preview roots. Preserve all current callers and run existing design job and
preview tests.

Exit criterion: old tests remain green and new seam tests pass.

### Phase 4: Add the standalone HTTP adapter

Implement the app, bounded schemas, origin checks, preview tokens, immutable
variant resolution, and lifecycle cleanup. Use temporary Git repositories and a
fake executor in web tests.

Exit criterion: all API and preview tests pass without starting Uvicorn.

### Phase 5: Build the no-framework UI

Implement editor validation, submission, polling, run trace, previews, evidence,
history, responsive layout, keyboard behavior, and error states. Keep the UI
read-only after submission.

Exit criterion: browser snapshot has no console errors at desktop and mobile,
and untrusted iframe content cannot call `/api/runs`.

### Phase 6: Wire the CLI and package smoke test

Register the command, acquire the lock, construct isolated dependencies, and
close them reliably. Confirm `intake_lab.html` is included by the existing
`web/static/*.html` package-data pattern.

Exit criterion: the installed wheel can run `site-agent intake-lab --help` and
serve the shell from a temporary workspace.

### Phase 7: Run one real OceanicVibes acceptance

Use the configured ENTRIM implementation and visual-review models, retain all
artifacts, inspect the UI in a browser, and prove source/remote immutability.
Do not publish or create a draft.

Exit criterion: the run reaches an honest terminal state and the UI accurately
renders its candidate and evidence. The visual reviewer may legitimately return
`repair`; UI acceptance does not require the candidate design to pass critique.

## Focused Test Matrix

| Area | Required proof |
|---|---|
| Intake | Valid fixture round-trips; malformed JSON and typed-contract errors are bounded. |
| Prompt | Empty/oversized/control-character requests are rejected; valid request persists unchanged. |
| Isolation | Run clone, DB, worktrees, transcripts, and screenshots stay under workspace. |
| Git | Source clone remains clean; run clone has no push-capable remote; target cannot publish. |
| Queue | Typed request/target exist before enqueue; duplicate enqueue is suppressed. |
| Browser | Two runs receive distinct screenshot roots and adapters. |
| Restart | Queued work recovers; retained candidate resumes validation; building becomes interrupted. |
| Projection | API omits raw config, planning/context data, paths, transcripts, and secret event details. |
| Preview | Exact SHAs only; traversal and unsupported variants fail; nested assets stay in scope. |
| Sandbox | Candidate script has no same-origin lab API access. |
| UI | Polling stops at terminal state and selected run survives URL reload. |
| Accessibility | Labels, focus, live status, keyboard controls, reduced motion, and mobile layout work. |
| Compatibility | Existing admin Design previews and design executor tests remain unchanged. |

## Real Acceptance Procedure

Use a fresh workspace so old port 3012 processes and retained runs cannot be
mistaken for the new result:

```bash
workspace=/tmp/opencode/intake-lab-20260901
.venv/bin/site-agent intake-lab \
  --config src/site_agent/intake-ada.yaml \
  --workspace "$workspace" \
  --env-file .env \
  --host 127.0.0.1 \
  --port 3012
```

Check the port before launch. If 3012 belongs to an unrelated retained test
workspace, do not stop or replace that process without explicit approval; pass
another explicit port and record the actual URL in the acceptance report. The
product default remains 3012.

Before generation, record:

- source clone `HEAD`;
- source clone `git status --porcelain`;
- remote branch heads when the configured source has a remote;
- absence of drafts in the lab database;
- process environment sent to fake/logging-free child composition by key name
  only, never value.

In the browser:

1. Confirm the default neutral Intake Ada configuration is visible and valid.
2. Enter a concrete creative request and generate one run.
3. Confirm a 202 response, durable run ID, and ordered trace progress.
4. Wait for a retained candidate SHA or terminal pre-candidate failure.
5. If a candidate exists, inspect every required page at all three viewport
   presets in Candidate mode.
6. Compare Original and Candidate, including split mode on desktop.
7. Inspect deterministic, browser, and visual-review evidence.
8. Reload with `?run=<run_id>` and confirm the same run reopens.
9. Stop and restart the lab with the same workspace and confirm the run remains
   inspectable.

After generation, prove:

- source `HEAD` is unchanged;
- source worktree status is unchanged;
- remote branch heads are unchanged;
- run mode is `local_experiment`;
- run `publishable` is false;
- persisted target `push_mode` is `none`;
- no draft or approval exists;
- candidate SHA, transcript, screenshots, quality report, and visual critique are
  retained where their stages completed;
- no response, log, event, transcript projection, or HTML contains model or
  production credential values.

## Verification Commands

Run focused tests first:

```bash
.venv/bin/pytest -q \
  tests/test_intake_lab_service.py \
  tests/test_intake_lab_web.py \
  tests/test_design_jobs.py \
  tests/test_preview.py \
  tests/test_main.py
```

Then run repository verification:

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/python -m build --wheel --outdir /tmp/site-agent-wheel
```

Install or inspect the wheel in a temporary environment and confirm:

```bash
site-agent intake-lab --help
```

Also run `git diff --check` and inspect the final diff for accidental changes to
admin routes, production adapters, package credentials, databases, screenshots,
or generated workspace files.

## Definition Of Done

The Intake Lab is complete only when all of these are true:

- `site-agent intake-lab` starts a separate loopback-only UI on port 3012 by
  default.
- The default structured intake is preloaded and editable.
- The server validates with `SiteIntake.from_dict()` and performs no freeform
  extraction.
- One submission creates exactly one durable independent initial-design run.
- The run uses the canonical `DesignService` and `DesignJobExecutor` path.
- The run is pinned to an exact source SHA and can retain an exact candidate
  SHA.
- OpenCode, deterministic checks, per-run browser evidence, and visual review
  execute through existing adapters.
- Progress and terminal state remain inspectable after refresh and restart.
- Original and candidate previews work for nested CSS, images, links, and local
  runtime fetches.
- Candidate code is sandboxed from the lab API.
- Findings distinguish pending, passed, repair, incomplete, and failed states.
- Previous runs can be selected without modifying current editor input.
- The UI has no approve, decline, merge, push, publish, or hidden refinement
  operation.
- The source site, production state, remote refs, and drafts remain unchanged.
- Child processes receive only selected model credentials and safe operating
  variables.
- Focused tests, full suite, compileall, wheel build, and installed CLI smoke
  test pass.
- A retained OceanicVibes run proves the real path in the standalone UI.

## Coding-Agent Execution Order

The implementing coding AI should execute in this order:

1. Read this plan, `AGENTS.md`, and the authoritative OpenCode-first pipeline
   plan.
2. Read the current `DesignService`, `DesignJobExecutor`, preview helpers, CLI,
   and related focused tests; do not assume signatures from this document are
   already implemented.
3. Add the focused failing service, executor, preview, web, and CLI tests.
4. Implement `IntakeLabService` and strict environment/source isolation.
5. Add the smallest backward-compatible executor and preview seams.
6. Implement the standalone FastAPI adapter.
7. Implement the no-build UI exactly against the documented API.
8. Wire the CLI and lifecycle cleanup.
9. Run focused tests and fix root causes.
10. Run the full verification commands and package smoke test.
11. Run the real OceanicVibes acceptance in a fresh workspace.
12. Report exact run ID, base SHA, candidate SHA, terminal states, test results,
    source/remote immutability proof, and any residual gap.

Do not broaden scope to production review, visual refinement, model comparison,
or admin redesign while implementing this plan.
