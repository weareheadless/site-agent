# site-agent

Portable AI website content manager. One installable package, one instance directory per site.

- Plan: [PLAN.md](PLAN.md)
- Positioning: [POSITIONING.md](POSITIONING.md)
- Deploy + onboarding: [docs/deploy.md](docs/deploy.md) — worked example for OceanicVibes
- Defining a new site's persona: [docs/persona.md](docs/persona.md) — the Ada personality contract for onboarding LLMs
- Architecture: [docs/architecture.md](docs/architecture.md) — runtime boundaries and approval flow
- Owner experience implementation: [docs/owner-experience-implementation-plan.md](docs/owner-experience-implementation-plan.md) — active product, UI, approval, and capability roadmap
- Debugging: [docs/debugging.md](docs/debugging.md) — job, draft, and Design preview runbook
- Extensions: [docs/extensions.md](docs/extensions.md) — adapter, builder, provider, and MCP rules
- Ready-made instance config: [examples/oceanicvibes.config.yaml](examples/oceanicvibes.config.yaml)
- Environment template: [.env.example](.env.example) — placeholders only, never production credentials
- Instance dir: `config.yaml` + `.env` + `data/` (never fork the code per site)

## Dev quickstart (Phase 0)

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/site-agent check
.venv/bin/pytest
```

Instances using CrawlSEO also install the optional client with
`.venv/bin/pip install -e '.[crawlseo]'`.

## Instance directory

Create `config.yaml` + `data/` per site. Secrets go in the environment (or a `.env` you manage yourself — not committed):

| Variable | Purpose |
|---|---|
| `SITE_AGENT_LLM_API_KEY` | OpenRouter API key for the global DeepSeek model |
| `GITHUB_TOKEN` | PAT used by the github_static / cloudflare_pages adapters to commit site changes |
| `SITE_AGENT_ADMIN_PASSWORD` | Admin UI login |
| `CLOUDFLARE_API_TOKEN` | Cloudflare Pages deployment status (cloudflare_pages adapter) |
| `GA4_SERVICE_ACCOUNT` / `GA4_PROPERTY_ID` | Google Analytics 4 read access |
| `CRAWLSEO_SERVICE_TOKEN` | Project-scoped CrawlSEO MCP bearer token |
| `SITE_AGENT_MOTION_CACHE` | Shared server cache for provisioned browser motion libraries |

Env var names are remappable via the `env:` section of `config.yaml`.

To read both metrics through CrawlSEO, enable the provider and select
`source: crawlseo` under both `ga:` and `seo:`. The runtime uses only the fixed
project, search, analytics, crawl-summary, and crawl-issues read tools.

## Schedules are a strict contract

```yaml
schedule:
  digest:        {every: daily, at: "09:00"}
  learn:         {every: daily, at: "10:00"}
  weekly_report: {every: weekly, weekday: monday, at: "08:00"}
  article:       {every: weekly, weekday: tuesday, at: "09:00"}
  reflect:       {every: monthly}
```

- Times are server-local. Anchors pin jobs to wall-clock slots; plain `{every: N}` is pure spacing.
- Each job's `next_run` persists in the memory DB. A run that happens late still waits its full interval before the next one.
- If the process was down past a job's `next_run`, it fires on the next cycle and the action log marks it `caught up, Nh late` — missed deliveries are never silently skipped.

## Publish adapters

- `github_static` — site served from a GitHub repo branch (GitHub Pages model). Every change is a commit via the Contents API.
- `cloudflare_pages` — same commit-based publishing, but the repo is connected to a Cloudflare Pages project (commercial use allowed, unlimited bandwidth). Set `site.cloudflare.account_id` + `project_name` and `CLOUDFLARE_API_TOKEN` to get live deployment status.

## Payload content contract

New generated sites use the shared Payload content contract by default. Ada
works through the same API and Payload records that the owner can edit in the
HelloAda admin, so the public frontend, articles, featured images, SEO fields,
navigation, and footer stay in sync:

```yaml
blog:
  engine: payload
  collection: posts
  pages_collection: pages
  media_collection: media
```

The AI can draft and publish through Payload, while owners retain direct control
of page content, article content, featured images, SEO metadata, and shared
navigation. Legacy Git-backed content is migration-only and is not the default
for new tenants.

## New site CMS starting point

Every new customer repository should be initialized before Ada starts design:

```bash
site-agent init-site \
  --directory /SOCIAL/sites/acme \
  --name "Acme Studio" \
  --url https://acme.example
```

This creates the standard Next.js/Payload starting point: Home, About, Contact,
the Ada-branded blog listing, article templates, editable SEO fields, shared
navigation/footer globals, media relationships, and the build dependencies.
Ada can then design over a real CMS-ready structure instead of an empty
repository.

## Conversational Intake Lab

Start a new intake conversation without a prefilled site brief:

```bash
site-agent intake-lab \
  --config /path/to/site-config.yaml \
  --workspace /tmp/site-agent/intake-lab
```

The session starts empty. `--intake <file>` is optional and is only for an
explicit completed-intake fixture or migration seed; it is not a default site
reference.

## Local design experiment

Run the OceanicVibes redesign without touching the production clone, branch, or
remote:

```bash
site-agent design-experiment \
  --config examples/oceanicvibes.config.yaml \
  --intake examples/oceanicvibes.intake.json \
  --data-dir /tmp/site-agent/oceanicvibes-design
```

The command creates a dedicated public-repository clone and SQLite database,
uses an immutable baseline SHA, stages candidates under a local ref, runs host
quality gates, and reports whether remote refs stayed unchanged. It never
pushes or publishes. The model and provider come from the global merged
configuration; this setup uses DeepSeek through OpenRouter.

For the OceanicVibes Astro/React design-lab test, use the reproducible scripts:

```bash
scripts/generate-oceanicvibes-test.sh
scripts/launch-oceanicvibes-test.sh
```

The generation script stores the simulated owner request in the retained
workspace intake, defaults to the configured LLM planner, and accepts
`DESIGN_LAB_PLANNER=deterministic` for an offline smoke test. Override the
workspace with `DESIGN_LAB_WORKSPACE=/tmp/...`; the launch script automatically
serves the newest retained run unless a run ID is supplied as its second
argument.

To compare the three planned model versions without changing the instance
configuration, run the matrix script. It creates one isolated workspace per
model, retains every run and browser report, and writes a read-only comparison
manifest. The defaults are Gemini 2.5 Pro, GPT-5.6 Luna, and DeepSeek V4 0731
(`deepseek-v4-flash-0731`):

```bash
scripts/compare-oceanicvibes-models.sh \
  /tmp/site-agent-design-lab/oceanicvibes-three-models
scripts/launch-oceanicvibes-model-comparison.sh \
  /tmp/site-agent-design-lab/oceanicvibes-three-models
```

The matrix command continues after an individual model failure and exits
nonzero if any model failed; the manifest still records the failed run and its
log. Override IDs when the configured provider uses different names:

```bash
GEMINI_MODEL=google/gemini-2.5-pro \
GPT_LUNA_MODEL=openai/gpt-5.6-luna \
DEEPSEEK_MODEL=deepseek/deepseek-v4-flash-0731 \
  scripts/compare-oceanicvibes-models.sh
```

The comparison UI shows all retained candidate pages together and keeps each
model's quality state, candidate SHA, and failure evidence visible. It never
approves, pushes, or publishes a candidate.
