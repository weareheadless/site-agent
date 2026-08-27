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

## Instance directory

Create `config.yaml` + `data/` per site. Secrets go in the environment (or a `.env` you manage yourself — not committed):

| Variable | Purpose |
|---|---|
| `SITE_AGENT_LLM_API_KEY` | LLM provider API key |
| `GITHUB_TOKEN` | PAT used by the github_static / cloudflare_pages adapters to commit site changes |
| `SITE_AGENT_ADMIN_PASSWORD` | Admin UI login |
| `CLOUDFLARE_API_TOKEN` | Cloudflare Pages deployment status (cloudflare_pages adapter) |
| `GA4_SERVICE_ACCOUNT` / `GA4_PROPERTY_ID` | Google Analytics 4 read access |
| `SITE_AGENT_MOTION_CACHE` | Shared server cache for provisioned browser motion libraries |

Env var names are remappable via the `env:` section of `config.yaml`.

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

## Pelican blog CMS

New generated sites use the Git-backed Pelican blog engine by default:

```yaml
blog:
  engine: pelican
  articles_dir: content/articles
  site_url: https://example.com/
  build_command: pelican content -o output -s pelicanconf.py
```

The AI owns the site's Pelican theme and templates. Approved article drafts are
committed as Markdown files with frontmatter; no article index JSON is maintained.
Pelican generates the archive, categories, feeds, pagination and sitemap during
the Cloudflare Pages build. Existing instances must explicitly keep
`blog.engine: legacy` until they are migrated.

## New site CMS starting point

Every new customer repository should be initialized before Ada starts design:

```bash
site-agent init-site \
  --directory /SOCIAL/sites/acme \
  --name "Acme Studio" \
  --url https://acme.example
```

This creates the standard Pelican starting point: Home, About, Contact, the
Ada-branded blog listing, article templates, an empty article collection, and
the build dependencies. Ada can then design over a real CMS-ready structure
instead of an empty repository.
