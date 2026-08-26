# Plan: `site-agent` — portable AI content manager

**Goal:** Extract Ada's working core (memory, reflection, senses, LLM loop) plus FYE's website-editing concept into a fresh, installable Python package. Attach it to OCEANICVIBES first. Website-only in v1; no social posting. Commercialization-ready staging from day one.

**Positioning:** see [POSITIONING.md](POSITIONING.md). Hero features in priority order: **(1) weekly plain-language report**, **(2) editor chat**. Audit/GA4 analysis feeds the report underneath.

**Proof of concept:** OceanicVibes runs live as customer #0 and doubles as the demo for approaching owner-operated businesses in freediving / water-sports communities. Validation signals: unprompted "can it run my site too?", willingness to pay ~$29+/mo, owner engages with the weekly report most weeks.

**Approved defaults for open decisions:** repo/package name `site-agent`; admin server FastAPI; first SEO source Google Search Console API (MCP stub behind it); default publish mode `ask_first` (drafts await approval).

## Product repo layout

```
site-agent/
├── pyproject.toml              # pip-installable, pinned deps
├── src/site_agent/
│   ├── main.py                 # entrypoint: scheduler loop + admin server; --once for manual run
│   ├── config.py               # layering: package defaults.yaml < instance config.yaml < .env
│   ├── core/
│   │   ├── llm.py              # direct OpenAI-compatible HTTP client (~150 lines),
│   │   │                       #   retries/timeouts, logs tokens+cost per call into memory DB
│   │   ├── memory.py           # sqlite per instance: schema_version, kv, observations,
│   │   │                       #   actions, drafts, metrics_snapshots, llm_costs
│   │   ├── scheduler.py        # interval jobs from config cadence, lockfile, jitter
│   │   └── reflect.py          # periodic voice/persona tuning from her own output history
│   ├── senses/
│   │   ├── reddit.py           # PORT (RSS-read path only; strip OAuth/commenting/ledger)
│   │   ├── rss.py              # PORT of news.py fetch+relevance scoring, source-agnostic
│   │   ├── ga.py               # PORT nearly verbatim; key path/property from config not hardcoded
│   │   └── seo.py              # Phase 5: GSC/MCP client stub
│   ├── brain/
│   │   ├── prompts.py          # per-site persona (voice/audience/taboo) from config;
│   │   │                       # article-writer + editor prompts adapted from brain.py
│   │   ├── digest.py           # daily: senses → LLM summary → memory ("what she learned")
│   │   ├── article.py          # weekly: topic ← learnings + GA signals → draft (or auto-publish)
│   │   ├── editor.py           # admin-chat → tool-calls → validated edit proposals
│   │   └── strategist.py       # monthly: GA + SEO + article perf → suggestion cards
│   ├── hands/
│   │   ├── base.py             # SiteAdapter: get_content / propose_edit / publish / preview
│   │   └── github_static.py    # GitHub Contents API commits (modeled on oceanicvibes server.js)
│   └── web/
│       ├── server.py           # FastAPI: password auth sessions, status, drafts review,
│       │                       #   chat endpoint, static admin page
│       └── static/admin.html   # single page: status · activity · metrics · drafts · CHAT
├── deploy/site-agent@.service  # systemd template: systemctl start site-agent@oceanicvibes
├── tests/
└── docs/deploy.md              # new-site onboarding (10 min) + upgrade/rollback procedure
```

## Port map (what moves, what changes)

| From | To | Change |
|---|---|---|
| `reddit.py` | `senses/reddit.py` | Read-only RSS only; delete OAuth, commenting, approval ledger |
| `news.py` | `senses/rss.py` | Generic feeds + relevance scoring, any source list |
| `ga.py` | `senses/ga.py` | Verbatim logic; config-driven credentials/property |
| `memory.py` + `memory_store.py` | `core/memory.py` | Single sqlite per instance, explicit `schema_version`, migration hooks |
| `reflect.py` | `core/reflect.py` | Same reflection prompt pattern, tuned to site persona |
| `brain.py` prompts | `brain/prompts.py` | Extract persona/article patterns; rewrite for content-manager context |
| consciousness `wake/consider` | scheduler jobs | The loop *becomes* digest/article/editor jobs — same decide→act shape |
| `llm.py` + `opencode_harness.py` | `core/llm.py` | Rewritten: one direct OpenAI-compatible API call, no harness process |
| `publish.py` | split | Writing → `brain/article.py`; committing → `hands/github_static.py`; Pelican blog output is optional per site |
| FYE admin (`admin_*`, `website.py`) | `web/` | Replaced by small server modeled on OCEANICVIBES `server.js` auth/publish model |

**Explicitly not ported:** `agent_platform/`, admin objectives/conversation/tasks, `fye_db.py`, `opencode_harness.py`, sandbox, discourse, agency, dream, scratchpad, balances, mail/notify, bluesky, lemmy, public_chat, chat servers, benchmarks, vaporware-vanguard. Ada's original stays untouched as the reference implementation.

**Blog CMS:** new sites can set `blog.engine: pelican`. Approved articles are committed as Markdown with Pelican frontmatter under `blog.articles_dir`; Pelican derives archives, feeds, categories and pagination during the Cloudflare build. Existing sites keep the legacy `articles/index.json` path until migrated.

## Phases & acceptance criteria

### Phase 0 — Bootstrap ✅ (this commit)
Repo, pyproject, config loader with layering, `.env.example`, pytest skeleton.
✅ `pip install -e . && python -m site_agent --check` prints resolved merged config.

### Phase 1 — Core runtime ✅
`core/llm.py` (direct OpenAI-compatible client, retries, cost logging), `core/memory.py` (versioned sqlite, migrations, observations/actions/drafts/metrics/costs), `core/scheduler.py`, `core/jobs.py` registry, `run`/`once` commands wired in `main.py`, systemd template in `deploy/`.
✅ Verified: `--once` completes a real cycle against an instance config; jobs recorded in instance DB; 24h LLM spend reported; manual `once` is blocked while the loop holds the lock; 30 tests green.

**Scheduler v2 (strict imperative contract):** schedules are config-owned and anchored — `{every: daily, at: "09:00"}`, `{every: weekly, weekday: monday, at: "08:00"}`, `{every: 14, weekday: tuesday}` (biweekly remains supported). `next_run` persists per job: a late run keeps its full spacing, a down process catches up overdue jobs on restart (`caught up, Nh late` marker in the action log). Defaults: digest+learn daily, report Monday 08:00, journal article Tuesday weekly, reflect monthly. Per-instance overrides live under `schedule:` in `config.yaml`.

### Phase 2 — Senses ✅
`senses/base.py` (Item model with Ada's dedupe identity: normalized-title hash + canonical link stripped of tracking params; keyword scoring), `senses/reddit.py` (RSS-only port, commenting/OAuth stripped), `senses/rss.py`, `senses/ga.py` (GA4 port, lazy google-auth behind `[ga]` extra, config-driven creds). Digest job records scored+deduped observations with links in meta; GA snapshot job writes `metrics_snapshots`. Observations schema migrated to v2 (+meta column) — migration path itself is tested.
✅ Verified live: real r/freediving fetch produced 15 linked observations; 38 tests green.

### Phase 3 — Brain + weekly report (HERO #1) ✅
`brain/prompts.py` (persona from Ada's DIRECTIONS pattern, per-site voice/audience/taboo, memory-context formatter), `brain/digest.py` (daily learning: distills the day's reading into insights + recurring themes), `brain/report.py` (**weekly plain-language report** as an approval-gated draft), `brain/article.py` (weekly article: topic chosen from learned themes + GA top pages → pending draft), `core/reflect.py` (monthly self-review proposing voice adjustments — owner approves, approved notes merge into her persona at runtime).
✅ 46 tests green. Mind is fully wired into the scheduler: learn/report/article/reflect jobs register when an LLM key is present; failures land in `actions` as `job_error` without killing the loop.

**Inner life & maintenance addendum ✅** — Ada's interior machinery ported as scheduled processes inside the strict contract:
- `brain/inner_voice.py` — **her single critical faculty, adapted to context** (unified, faithful to the original Ada): `think` keeps the scheduled private mood/thought (feeds dreams); `challenge` is her critical friend speaking about whatever she is about to act on — an article draft, an implementation plan, a build — against real context (brand, site files, memory), returning concrete problems; `answer` records her resolution and revision. There is no separate "editor" persona: editing an article and vetting a build plan are the same voice applied to different work.
- `brain/dream.py` — Sundays 05:00: associative recombination of old reading fragments + a random lure (ported lure list, config-extensible via `persona.lures`); may surface a content seed the article pass can pick up later
- `core/maintenance.health_check` — the observer, **zero tokens**: scans for repeated observations, job-error streaks, stale pending drafts, seen-index bloat, spend anomalies → findings in kv + action ledger
- `core/maintenance.compact_memory` — compaction port: raw feed observations older than retention are LLM-distilled into a ≤5-bullet archive entry, then deleted raw. Identity material (learning, inner voice, dreams, archives) is never compacted.
✅ 62 tests green; live run registers all 11 jobs with anchored next_run times.

**Unified inner voice — pre-action challenge ✅** — the one-shot guarantee lives at the planning stage: `brain/planner.py` has Ada make the implementation plan from her memory, brand, and site context; `brain/inner_voice.py` receives that plan and returns only concrete criticism in one call; Ada revises it when needed; only then does `hands/opencode_runner.py` execute the final plan. `brain/article.py` uses the same voice (replacing the old separate `EDITOR_PERSONA`) to self-edit drafts. Best-effort and bounded: empty criticism ships; a failed challenge never blocks her from acting.
✅ 120 tests green.

### Phase 4 — Editor chat + admin web (HERO #2) ✅
- `web/server.py`: FastAPI admin API — password auth w/ in-memory sessions (OceanicVibes model), status/upcoming-jobs/health/spend, drafts list+detail, approve/discard, chat endpoint, static UI. Memory DB made thread-safe (lock + check_same_thread).
- `brain/editor.py`: closed tool-loop (`get_content`, `get_metrics`, `list_drafts`, `propose_edit`) over dotted-path edits into `content.json`; unknown fields rejected; every mutation becomes a **persisted proposal draft** — nothing reaches the site from chat alone.
- Approval semantics: `edit` → applies changes and commits content file via adapter; `article` → commits `articles/<slug>.md`; `reflection` → merges approved voice notes into persona; `report` → local approval only.
- `web/static/admin.html`: single page, no build step — weekly report card front-and-center, drafts with inline edit-diffs + approve/discard, upcoming jobs strip, health findings, activity feed, chat box.
✅ Verified: live server smoke (login/bad-pw/session/status/drafts/UI); approve→commit path tested against a fake adapter; 71 tests green.

**Admin UI v2 ✅** — sidebar chat with persistent multi-conversations (`conversations`+`chat_messages` tables, schema v3; compaction never touches them), publishes ledger with one-click git **revert** (`GithubStatic.revert_commit`: restore parent blobs / delete created files), Design tab (live-site iframe now; becomes true pre-approval preview via Cloudflare Pages branch URLs after migration), thinking indicator while her tool-loop runs. Chat history per conversation feeds her context server-side. Fixed along the way: sub-path API base (proxy-safe), timestamp formatting, disabled-by-default chat input, lockfile EPERM handling, argparse order for `run --config`. GA4 live on property 551030734 (org-level SA grant); search queries flow via GA4↔GSC product link once created.

**Done early (Phase 0.5):** `hands/base.py` SiteAdapter contract + `github_static` + `cloudflare_pages` (git mode, deployment status via CF API; direct-upload mode stubbed for Phase 4). Successor sites can launch on Cloudflare Pages from day one.

### Phase 5 — SEO + strategist + hardening ✅
- `senses/seo.py`: GSC search-analytics client (top queries w/ clicks/impressions/ctr/position, 28d), service-account scoped `webmasters.readonly`, key reuses `ga.key_path` by default; `source: mcp` stub raises a clear "arrives later" error.
- `brain/strategist.py`: weekly — combines GA4 + GSC snapshots and article history into ≤3 ranked cards stored in kv; the **weekly report prompt weaves the top card in** (cards feed the report, not a dashboard).
- Spend guard: `llm.daily_budget_usd` (default $2/day) — Client.chat refuses calls once trailing-24h computed spend hits the cap; jobs fail gracefully and resume when the window clears.
- Backups: weekly consistent sqlite snapshot via the backup API into `data/backups/`, last 5 retained.
✅ Live GA4 connection verified against the real OceanicVibes property (551030734) via org-level SA grant.
**Query fallback:** once the GA4↔Search Console *product link* exists (Admin → Product links), `ga.organic_queries()` reads search queries straight from GA4 (`googleOrganicSearchQuery`) with the same credential — no separate GSC invite needed. Strategist uses native GSC data when present, falls back to the GA4-linked queries; weekly_summary degrades gracefully (no link → empty list, traffic unaffected). GSC-native impressions/CTR/position still require a Search Console invite (role: Full).
✅ 81 tests green; live run registers all 14 jobs, backup snapshot verified on disk.

**Cloudflare preview workflow ✅** — `site.preview_branch` (e.g. `preview`) turns every edit proposal into a pre-approval live preview: editor gains `propose_file_edit` (find→replace on whitelisted files like styles.css, uniqueness-enforced), Preview button pushes the proposal to the branch (`ensure_branch` + branch-scoped commits), `senses/cloudflare.latest_preview_url()` resolves the CF Pages alias via API token; Design tab links it. Approve still merges to production; Revert unchanged. Also fixed: first-publish-of-new-file crash (404 pre-read), article approvals now maintain `articles/index.json`, articles.html reader deployed to the live site.
✅ 88 tests green; articles.html verified live on oceanicvibes.com.

**Repo hands + skills + builder (v2 of the editor) ✅** — she no longer gets scripts, she gets hands: one generic `propose_changes` op over `write`/`edit`/`delete` on fnmatch-writable paths (`site.writable_patterns`; admin/CI/secrets hard-denied), plus read senses (`read_file`, `list_files`). set_field edits validate dotted paths against live content.json at proposal time. Skills layer: vendored markdown packs (frontend-design, high-end-visual-design, web-design-guidelines) injected as a digest when requests touch presentation. Optional per-instance builder: `hands/builder.py` shells out to a headless **opencode agent** inside a site clone for big creative briefs (`builder.enabled`, off by default) — chat action `spawn_build`. json_mode latency bomb removed (prompt-enforced JSON + tolerant parser); timeouts 120s.
✅ 88 tests green.

**Chat build economics ✅** — small tweaks and full builds no longer cost the same. A lightweight LLM scope decision runs before repository tools: focused edits continue through `propose_changes`, while broad visual/structural requests go directly to `spawn_build` instead of making the fast model explore files turn after turn. `spawn_build` runs the full `stage_build` cycle — prepare preview → agent → commit → push → approval-gated merge draft — and the route is active only when the builder is configured. Follow-up builds **stack**: while a merge draft is pending, `prepare_preview` starts from `origin/preview` instead of resetting to `origin/main`, so an unapproved page survives the next request (no more "I didn't approve, asked for an improvement, page disappeared"); `stage_merge_draft` marks older pending merge drafts discarded since the new preview is cumulative. The builder also gets a cached structural **site digest** (`hands/site_digest.py`, kv-cached on the origin/main commit, regenerated only when the published site changes) injected into its agent profile so it stops re-reading whole files every run.
✅ 144 tests green.

**Tweakable-parameter map ✅** — the fast tier gets reference context instead of cold whole-file reads. When she builds a page she also writes a semantic map of the knobs she made tweakable (`.opencode/tweak-map.json`, gitignored, captured into kv on every build: `{label, file, kind, selector/prop/field, current, find}` with the exact current snippet). A deterministic extractor (`hands/tweakmap.py`) backfills every page from the git ref (CSS declarations per selector with `unique` flags, HTML text nodes, content.json fields, admin files excluded) so the map exists before the first build. It's kv-cached on the origin/main commit and merged with the builder's overlay per knob (builder wins). `brain/editor.py` injects a compact "Editable parameters" block into the focused-edit path so the model knows exact snippets up front. The broad-build route deliberately bypasses that read loop and gives the full repository context to opencode. Declining a build drops its overlay.
✅ 149 tests green.

### Deferred
Webflow MCP adapter prototype, social posting, Docker/private-PyPI distribution, billing/multi-tenant polish.

## Staging process (baked in from Phase 0)

- `main` tagged semver = installable stable; develop branch for work; CI runs tests per PR.
- Sites install pinned tags: `pip install git+ssh://…/site-agent@vX.Y.Z`; instance dirs hold only `config.yaml` + `.env` + `data/`.
- Upgrade = reinstall next tag (migrations auto-run at startup); rollback = previous tag. Both documented and *tested once* before calling v0.1 done.
- New site onboarding doc: create instance dir → fill config → enable systemd unit → done.

## Staging directory convention

```
Product repo (code):     /SOCIAL/site-agent          ← this repo
Site instance (config):  /SOCIAL/configs/<site>/{config.yaml,.env,data/}
```
