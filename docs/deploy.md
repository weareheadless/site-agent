# Deploying site-agent — worked example: OceanicVibes

## Shared Ada API

Customer-facing Payload workspaces should use the shared tenant-aware API, not
one systemd process per customer. Start with the checked-in examples:

```bash
sudo mkdir -p /SOCIAL/configs/site-agent-api /SOCIAL/configs/tenant-example/data
sudo cp /SOCIAL/site-agent/examples/workspace-api.config.yaml \
   /SOCIAL/configs/site-agent-api/config.yaml
sudo cp /SOCIAL/site-agent/examples/tenant-example.config.yaml \
   /SOCIAL/configs/tenant-example/config.yaml
```

Create `/SOCIAL/configs/site-agent-api/.env` with mode `600`. It must contain
the tenant's API/Payload token and the LLM key, for example:

```ini
PROVISIONED_TENANT_EXAMPLE_TOKEN=replace-with-a-random-tenant-token
SITE_AGENT_LLM_API_KEY=server-side-model-key
```

Install one shared unit and one Nginx ingress:

```bash
sudo cp /SOCIAL/site-agent/deploy/site-agent-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now site-agent-api
sudo cp /SOCIAL/site-agent/deploy/nginx-ada-api.helloada.app.conf \
  /etc/nginx/sites-available/api.helloada.app.conf
sudo ln -sfn /etc/nginx/sites-available/api.helloada.app.conf \
  /etc/nginx/sites-enabled/api.helloada.app.conf
sudo nginx -t && sudo systemctl reload nginx
```

After `api.helloada.app` resolves to this host, provision TLS with:

```bash
sudo certbot --nginx -d api.helloada.app
```

The Workspace Worker then uses `https://api.helloada.app/v1` as
`SITE_AGENT_URL`. The bearer token is tenant-scoped; the API resolves it to the
tenant's separate config, Payload client, memory database, and job worker.

One install of the product per machine, one instance directory per site.
Code lives in `/opt/site-agent`, site instances live in `/SOCIAL/configs/<site>/`.

```
/opt/site-agent/            # the product (pip install from a pinned tag)
/SOCIAL/configs/oceanicvibes/   # THIS site: config.yaml + .env + data/
/etc/systemd/system/site-agent@.service   # one unit file, all sites
```

---

## 1. Install the product (once per VPS)

```bash
sudo mkdir -p /opt/site-agent && cd /opt/site-agent
sudo python3 -m venv venv
sudo venv/bin/pip install git+ssh://git@github.com/<you>/site-agent@v0.1.1
# For a CrawlSEO-backed instance, install the maintained MCP client extra too:
# sudo venv/bin/pip install 'site-agent[crawlseo]==0.1.1'
# upgrade later = reinstall next tag; rollback = reinstall previous tag
```

Pin tags. Never run from a moving branch on production sites.

## 2. Create the OceanicVibes instance

```bash
sudo mkdir -p /SOCIAL/configs/oceanicvibes/data
sudo chown -R admin:admin /SOCIAL/configs/oceanicvibes
cp /SOCIAL/site-agent/examples/oceanicvibes.config.yaml \
   /SOCIAL/configs/oceanicvibes/config.yaml
```

Create `/SOCIAL/configs/oceanicvibes/.env` (mode 600 — never committed):

```ini
# OpenRouter key for the global DeepSeek model
SITE_AGENT_LLM_API_KEY=sk-or-v1-...
GITHUB_TOKEN=github_pat_...
SITE_AGENT_ADMIN_PASSWORD=pick-a-long-one
GA4_SERVICE_ACCOUNT=/home/admin/.config/ga4-service-account.json
CRAWLSEO_SERVICE_TOKEN=            # only when CrawlSEO is enabled
CLOUDFLARE_API_TOKEN=            # optional, only after the CF Pages move
chmod 600 /SOCIAL/configs/oceanicvibes/.env
```

Token hygiene:

- `GITHUB_TOKEN`: fine-grained PAT → *only* `oceanicvibesfreediving/oceanicvibesfreediving.github.io`, permission **Contents: Read and write**. One token per site repo.
- `GA4_SERVICE_ACCOUNT`: create a service account in Google Cloud → enable the **Google Analytics Data API** → download JSON → put it at `/home/admin/.config/ga4-service-account.json` (600) → in GA4 Admin ▸ Property Access Management, add the SA e-mail as **Viewer**. Reuse the same key file for GSC below.
- GSC: in Search Console ▸ Settings ▸ Users and permissions ▸ Add the same service-account e-mail as **Full** (needed for the read API).
- `config.yaml` contains zero secrets by construction — safe to back up anywhere.

When the project-scoped CrawlSEO MCP endpoint is live, use the optional extra and
the following instance settings. Keep the token only in `.env`; the existing
systemd `EnvironmentFile` loads it without a service-unit change.

```yaml
providers:
  crawlseo:
    enabled: true
    url: https://crawlseo.example/mcp
    token_env: CRAWLSEO_SERVICE_TOKEN
    timeout_seconds: 30
    max_response_bytes: 2097152

ga:
  source: crawlseo
seo:
  source: crawlseo
```

## 2a. Provision a private customer media bucket

Each customer instance gets its own R2 bucket and bucket-scoped S3 credential.
The provisioning command creates both through Cloudflare's API and writes the
credential only to that instance's `.env` file. It is safe to run again after a
successful setup: the existing R2 credentials are reused.

Before running it, create a Cloudflare API token for the provisioning operator
with:

- Account: **Workers R2 Storage Write**
- Account: **Account API Tokens Edit** (required to create the customer-scoped
  token through the API)

The provisioning token is a platform bootstrap credential. Put it in the global
provisioning environment file `/SOCIAL/site-agent/.env` (mode `600`), never in a
customer instance `.env` file and never pass it to the site-agent worker:

```ini
# /SOCIAL/site-agent/.env
CLOUDFLARE_API_TOKEN=bootstrap-token
```

Run this from the customer instance directory after creating `config.yaml`:

```bash
/opt/site-agent/venv/bin/site-agent provision-r2 \
  --config /SOCIAL/configs/oceanicvibes/config.yaml \
  --instance oceanicvibes \
  --account-id '<cloudflare-account-id>'
```

The command reads `.env` from its current directory. Use
`--bootstrap-env-file /SOCIAL/site-agent/.env` when running it elsewhere.
Process environment values take precedence over values in the file.

The command creates a bucket named `helloada-oceanicvibes-media` by default,
sets `site.media.enabled: true`, `site.media.private: true`, and writes
`R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` to
`/SOCIAL/configs/oceanicvibes/.env` with mode `600`.

Use `--bucket` when the generated name does not fit the customer's naming
policy. The bucket remains private; no public URL or R2 custom domain is
required. The future HelloAda provisioning service should call the same
provider/application boundary rather than reimplementing these API calls.

## 3. Sanity-check before going live

```bash
cd /SOCIAL/configs/oceanicvibes
/opt/site-agent/venv/bin/site-agent check --config config.yaml   # merged config, masked secrets
SITE_AGENT_DATA=/SOCIAL/configs/oceanicvibes/data \
/opt/site-agent/venv/bin/site-agent once --config config.yaml    # first full cycle
sqlite3 data/memory.db 'SELECT kind,detail FROM actions ORDER BY id DESC LIMIT 10'
```

Expect `digest ok`, `learn …` (needs the LLM key), and a backup file in `data/backups/`.

## 4. Services: agent loop + admin UI

```bash
sudo cp /opt/site-agent/deploy/site-agent@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now site-agent@oceanicvibes        # the mind
sudo cp /opt/site-agent/deploy/site-agent-admin@.service /etc/systemd/system/
sudo systemctl enable --now site-agent-admin@oceanicvibes  # the face
```

The `site-agent@` unit runs scheduled jobs; it does not host the admin API or
media worker. Restart `site-agent-admin@<instance>` after changing media or
admin code/configuration. The admin unit is the process listening on port 3011.

`/etc/systemd/system/site-agent-admin@.service`:

```ini
[Unit]
Description=site-agent admin (%i)
After=network-online.target

[Service]
User=admin
Group=admin
UMask=0077
WorkingDirectory=/SOCIAL/configs/%i
EnvironmentFile=/SOCIAL/configs/%i/.env
ExecStart=/opt/site-agent/venv/bin/python -m site_agent serve --config /SOCIAL/configs/%i/config.yaml
Restart=on-failure
RestartSec=15
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Nginx (same pattern as the existing OV admin server):

```nginx
location /ada/ {
    proxy_pass http://127.0.0.1:3011/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 240s;   # her chat answers can take 1-2 minutes
    proxy_send_timeout 240s;
}
```

Open `https://api.oceanicvibes.com/ada/`, sign in with `SITE_AGENT_ADMIN_PASSWORD`.
Her weekly report lands there every Monday 08:00; journal articles land Tuesdays.

## 5. Day-2 operations

| Task | Command |
|---|---|
| What did she do? | admin UI activity feed, or query `actions` table |
| Run a cycle now | `... site-agent --config config.yaml once` |
| Change her rhythm | edit `schedule:` in config.yaml, restart unit — `next_run` recomputes |
| Change her voice | edit `persona:` (or approve a reflection draft) |
| Upgrade product | `pip install ...@vX.Y.Z` into `/opt/site-agent/venv`, restart units — migrations auto-run |
| Rollback | reinstall previous tag, restart; memory schema migrates forward only — check release notes |
| Restore memory | stop unit, copy newest `data/backups/memory-*.db` over `data/memory.db`, start |

## 6. Onboarding the next site (the 10-minute checklist)

1. `mkdir -p /SOCIAL/configs/<newsite>/data`
2. Initialize the customer repository with `site-agent init-site --directory <site-repo> --name "<business>" --url <url>`
3. Copy `examples/oceanicvibes.config.yaml`, edit persona/sources/GA ids
4. Writing the persona? Follow [docs/persona.md](persona.md) — the Ada personality
   contract (honesty rules + the five profiles every persona must fill).
5. New `.env` (fresh LLM key optional, fresh GITHUB_TOKEN scoped to that repo)
6. Run `site-agent provision-r2 --config /SOCIAL/configs/<newsite>/config.yaml --instance <newsite> --account-id <account-id>` with the platform bootstrap token
7. Sanity-check with `once`
8. `systemctl enable --now site-agent@<newsite>` + admin unit
9. Ada starts design from the generated CMS pages; no blank repository is presented.
