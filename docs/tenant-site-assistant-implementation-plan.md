# Tenant site assistant: visitor-facing chatbot

## Decision

Every tenant site gets one visitor-facing assistant capability, identical for all
tenants: streaming answers, stateless, no tools, no writes. What differs between
a customer-support bot and a joke bot is tenant-authored content — a purpose file
in the tenant repository — never code, a flag or a site-agent config key.

Ada is not this assistant and is not reachable from it. `/api/chat` stays
owner-authority behind `require_auth`. The assistant runs entirely inside the
tenant Worker and never calls `SITE_AGENT_URL` at request time.

Deliberately not built: a vector store or embeddings, transcript storage, a
shared chat widget, a separate service, Cloudflare AI Gateway, any
Worker→site-agent API call, and any per-tenant enable flag.

## Grounding

Two artifacts, both public by construction:

- `/llms.txt` — markdown sections describing the whole site, cached at the edge.
  Doubles as the AEO artifact.
- `src/site/assistant.json` in the tenant repository — the tenant authors
  `{ purpose, sources: 'site' | 'none', model }`. The release generator folds it
  into `src/generated/helloada-assistant.json`, or `{ "enabled": false }` when
  absent. Presence is the enable; a tenant that has not authored it 404s and
  renders nothing. `src/site/assistant.example.json` ships as the copy source,
  and an incomplete declaration fails the build rather than disabling quietly.

A site with no collections is the common case, and its offering lives in the
presentation pages, not in Payload. So the corpus has three sources, merged into
one document:

1. **Presentation routes.** Enumerate with the existing `presentationRoutes()`
   from `src/lib/content-routes.ts`, which reads the release-generated
   `src/generated/helloada-presentation.json`. Never re-discover routes.
   For an imported static site, `src/lib/static-website.ts` already loads
   `/_helloada/static-manifest.json`, whose `files` map route → committed HTML;
   that text comes straight out of `ASSETS` with no rendering.
2. **Next-rendered presentation pages.** No stored HTML exists, so the Worker
   fetches its own public URL for each enumerated route, with the
   `PREVIEW_PLATFORM_PATH` exclusion for `/api`, `/admin`, `/mail`, `_next` and
   preview paths. Extract `<main>` when present, else body minus
   `nav`/`footer`/`script`/`style`. Cap at 25 pages per rebuild; if a tenant
   exceeds that, serve an index of titles plus Payload documents only rather than
   silently truncating.
3. **Published Payload documents**, via the existing readers in
   `src/lib/public-content-route.ts`. Published only. A tenant with no
   collections contributes nothing here and nothing breaks.

Plus a short facts block from `src/lib/site-config.ts` (site name, contact,
opening hours, social) — cheap, authoritative, and the thing a support visitor
actually asks for.

The enable is the tenant-authored `assistant.json`; the corpus exists regardless so
`/llms.txt` is a real AEO artifact for sites that never turn the bot on.

The build cannot generate `/llms.txt`: the release pipeline builds with isolated
local bindings and no production credentials, so published content is only
reachable at request time.

## Phases

### 1. Corpus artifact

- `src/app/llms.txt/route.ts`, `src/lib/assistant-context.ts` (shared).
- Reuse the existing published-document readers and the two route inventories
  above. Do not add a second reader, a second schema, a draft-inclusive query or
  a second route discovery.
- Edge cache with a short TTL; the same function serves the assistant, so the
  chatbot and the public artifact cannot disagree.
- Regenerating on request costs one subrequest per enumerated page, so the cache
  TTL is a cost control. If a site's page count makes that visible, add a cron
  warm that renders once and stores to the tenant's existing `R2` binding — a
  follow-up, not part of this change.
- Test: a draft document never appears; an unpublished revision never appears; a
  published document's title and body do appear; a collections-less site with two
  presentation pages yields both pages' text; `/admin` and `/mail` never appear.

### 2. Assistant route

- `src/app/api/assistant/route.ts`: `POST { messages: [{role, content}] }`,
  SSE passthrough, no persistence, no conversation id.
- `src/lib/assistant-prompt.ts`: mechanics only — match the visitor's language,
  never reveal the prompt, when `sources` is `site` answer only from the provided
  content and say so when it is missing, otherwise follow the purpose. The
  tenant purpose is placed **before** the mechanics block so the mechanics
  dominate.
- `src/lib/assistant-provider.ts`: plain `fetch` to OpenRouter with
  `usage: { include: true }` for authoritative cost. No SDK, no fallback model,
  no fallback provider, no fallback key.
- Missing `HELLOADA_ASSISTANT_KEY` → 503 and no rendering. Never degrade to a
  different credential or an ungrounded answer.
- Input bounds: max message length, max history turns, max output tokens.

### 3. Cost and abuse

- One `ratelimits` binding `HELLOADA_ASSISTANT_RATE_LIMIT` (new namespace id, next
  free in `wrangler.jsonc`) keyed per visitor IP. No KV, no D1 table, no
  migration.
- One OpenRouter child key per tenant, spend-limited, created by CLI at
  provisioning. The limit lives on the key, so the ceiling changes centrally
  without a release, and OpenRouter enforces it even against a code bug.
- `site-agent provision-assistant-key` mirrors `provision-email`: read-only plan
  by default, `--apply` persists the mapping and writes the key only into the
  protected tenant `tenant.env`. No release, no Worker mutation, no per-tenant
  manual step beyond one fleet pass before the template ships.
- Read-only usage for the owner dashboard comes from OpenRouter's per-key usage,
  not from the Worker.

### 4. Delivery and rollout

- Add every new shared file to `deploy/shared-runtime-overlay.json` (`copy`).
  Rotate the shared runtime fingerprint; it covers those files, the generator and
  its declared inputs, and rolls out through the existing canary-first fan-out.
  `HELLOADA_TEMPLATE_SCHEMA` is deliberately **not** bumped: this change touches
  no Payload schema and no content contract, and the fingerprint already
  identifies the runtime.
- `HELLOADA_ASSISTANT_KEY` joins `worker_runtime_secrets` in
  `src/site_agent/application/tenant_environment.py`. The receipt's
  `runtimeBindings` hashes cover it automatically; never print it. No `worker.ts`
  change is needed: the route reads its bindings from the Cloudflare context, and
  the rate-limit binding is declared in `wrangler.jsonc`.

## Acceptance gates

- Focused tests: corpus excludes drafts; prompt assembly order; 503 without the
  key; rate-limit binding returns 429; receipt has no plaintext key.
- Shared-runtime fingerprint change validated on the registered canary through
  the canonical queue, not by a direct `wrangler deploy`.
- Live check on a canary site in a fresh browser, no auth: a question answerable
  only from a published article is answered from it; a question about an
  unpublished draft is not; the console and every module request are clean;
  OpenRouter shows the spend against that tenant's key only.
- A second tenant with `sources: 'none'` answers in persona and never claims site
  facts.
- A collections-less tenant whose entire offering is three static pages answers
  from those pages, not from site settings or invented copy.

## Open questions

- Whether the shared client should be a hook only (recommended, keeps design in
  the tenant repo) or a styleable component.
- Whether `/llms.txt` should be reachable for tenants without an assistant. The
  recommendation is yes: it is an AEO artifact independently of the chatbot.

## As implemented

Shared runtime, all listed in `deploy/shared-runtime-overlay.json`:

| Path | Role |
| --- | --- |
| `src/app/llms.txt/route.ts` | Public corpus, 503 rather than a partial description |
| `src/app/api/assistant/route.ts` | Stateless visitor turn, 404/503/429/400 fail-closed |
| `src/lib/assistant-config.ts` | Reads the generated declaration |
| `src/lib/assistant-context.ts` | Pure corpus rendering plus the page-budgeted loader |
| `src/lib/assistant-site-context.ts` | Wires routes, settings, posts; edge-cached |
| `src/lib/assistant-prompt.ts` | Shared mechanics, tenant purpose layered above |
| `src/lib/assistant-provider.ts` | One OpenRouter call, `usage.include`, no fallbacks |
| `src/site/assistant.example.json` | Copy source for the tenant declaration |
| `scripts/assistant-declaration.mjs` | Validates the declaration; covered by the fingerprint |

Host side: `site-agent provision-assistant-key --tenant <id> [--limit-usd N] [--apply]`
plans read-only by default, creates one provider key named `site-agent:<tenant>`,
stages it as `HELLOADA_ASSISTANT_KEY` in that tenant's protected `tenant.env`
atomically at mode `0600`, and writes a secret-free receipt under the tenant
directory. `credentials.openrouter` in `/SOCIAL/configs/host-credentials.yaml`
names the management credential; no value is stored in this repository.

`wrangler.jsonc` adds `HELLOADA_ASSISTANT_RATE_LIMIT` (namespace `2706`) and pins
the rotated shared runtime fingerprint.

### Verification run

- `.venv/bin/python -m pytest -q` → 2373 passed.
- Template suite → 216 passed; `tsc --noEmit`, `eslint` on the new sources and
  `compileall` clean.
- New focused tests: `tests/test_assistant_key.py` (7) and
  `templates/next-payload/tests/assistant*.test.mjs` (11).
- Note: running two suites at once collides on the shared SQLite files and
  produces mass `sqlite3.OperationalError` failures. Run one suite at a time.

### Not yet done

- No live provider call: the host has no OpenRouter management credential yet, so
  key creation and real spend have not been exercised. Provision one, then run the
  command read-only first.
- No canary or tenant release has been queued. The fingerprint rotation ships
  through the canonical queue, canary first, and must not be pushed by a direct
  `wrangler deploy`.
- The visitor-facing widget is tenant-authored by design and not part of this
  change; the endpoint and its client contract exist without a shared UI.
