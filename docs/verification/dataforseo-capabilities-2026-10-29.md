# DataForSEO capability verification — 2026-10-29

Evidence record for task **DS-01** in `docs/project-plan-2026-10-29.md`.
Only what was actually executed is listed as verified. Everything else is
explicitly unverified.

Credentials: the CrawlSEO API login from `/SEO/.env.local` (names
`CRAWLSEO_DATAFORSEO_LOGIN` / `CRAWLSEO_DATAFORSEO_PASSWORD`). Values were not
printed or stored. Calls were made through the official CLI
(`npx dataforseo-mcp-server request`) from the CrawlSEO checkout. These requests
did not mutate site content, but were paid provider operations where applicable.
The comparison also ran our crawler locally, temporarily creating then deleting
a crawl DB row. The earlier claim of entirely read-only/no CrawlSEO mutation was
incorrect. This documentation review made no additional live calls or DB changes.

## Verified

### Account

| Check | Result |
|---|---|
| `GET /v3/appendix/user_data` | `status_code 20000`, account active |

### `POST /v3/on_page/instant_pages`

Target: `https://www.atelier-harmonie.com/`, `load_resources: true`,
`validate_micromarkup: true`, standard (non-`.ai`) response.

| Field | Measured |
|---|---|
| cost | **$0.00045** for one page |
| status | `20000`, `crawl_progress: finished`, 1 item |
| `onpage_score` | 92.68 |
| boolean fields in `checks` | 52; not 52 actionable issues or parity-proven checks |
| timing | `duration_time 319 ms`, `time_to_interactive 319`, `connection_time 6`, `time_to_secure_connection 53`, `download_time 260`, `largest_contentful_paint 0` |
| size | 1,087,571 B |
| images / links | 26 images, 29 internal, 2 external |
| `resource_errors` | 6 errors, 1 warning — malformed HTML at specific line/column |
| `duplicate_content` | false |

Boolean fields present (52): `no_content_encoding, high_loading_time, from_sitemap,
is_redirect, is_4xx_code, is_5xx_code, is_broken, is_www, is_https, is_http,
high_waiting_time, has_micromarkup, has_micromarkup_errors, no_doctype,
has_html_doctype, canonical, no_encoding_meta_tag, no_h1_tag, https_to_http_links,
size_greater_than_3mb, meta_charset_consistency, has_meta_refresh_redirect,
has_render_blocking_resources, low_content_rate, high_content_rate,
low_character_count, high_character_count, small_page_size, large_page_size,
low_readability_rate, irrelevant_description, irrelevant_title,
irrelevant_meta_keywords, title_too_long, has_meta_title, title_too_short,
deprecated_html_tags, duplicate_meta_tags, duplicate_title_tag, no_image_alt,
no_image_title, no_description, no_title, no_favicon, seo_friendly_url, flash,
frame, lorem_ipsum, seo_friendly_url_characters_check,
seo_friendly_url_dynamic_check, seo_friendly_url_keywords_check,
seo_friendly_url_relative_length_check`.

**Response-shape note for implementers:** `checks` is `{name: boolean}`. The
boolean is not uniformly "problem present": facts such as `is_https`, `canonical`,
`has_html_doctype` are `true` when the condition exists, while issue flags such as
`low_content_rate`, `large_page_size`, `title_too_long`, `duplicate_meta_tags` are
`true` when the problem exists. Do not map the map wholesale to "issues". The
`.ai` response variant inspected here had a different, smaller shape (15 keys)
and omitted descriptions. Current standard-shape normalisers must use their tested
contract, not assume `.ai` is interchangeable. This is not a claim about every
endpoint's AI-optimised output.

### Parity against our crawler

Same URL, our crawler (`lib/crawler/engine.ts`, local run, DB row created then
deleted) versus OnPage above.

| Signal | Ours | OnPage | Verdict |
|---|---|---|---|
| title, description, canonical, H1 | present, correct | present, correct | agree |
| missing alt text | 0 | `no_image_alt: false` | agree |
| page in sitemap | `MISSING_SITEMAP` "not listed in sitemap" | `from_sitemap: false` | **not verified**: an Instant Pages discovery flag is not sitemap-membership proof |
| size | 1,085,027 B | 1,087,571 B | agree within ~0.2% |
| response time | 287 ms | 319 ms duration | different collectors/scope; neither parity nor rendered performance proof |
| images | 72 | 26 | **unresolved**: collection/count semantics need verification; no accuracy winner established |
| internal links | 25 | 29 | **unresolved**: parsing/normalisation scope needs verification |
| HTML validity | not checked | 6 parse errors with line/column | **OnPage only** |
| performance detail | one recorded duration | timing fields incl. TLS/download/TTI; LCP `0` | additional fields, **not** an executed waterfall/browser-vitals test |
| duplicate content, readability, deprecated tags, meta refresh, flash/frame, lorem ipsum, encoding, favicon, render-blocking | outside this comparison's local issue outputs | flags present | field availability only; trigger accuracy and full-site scope untested |
| business consistency audit | `MISSING_SCHEMA` "business consistency audit unknown" | not applicable | **ours only** |
| link graph, live re-check, issue→action pipeline | present | not applicable | **ours only** |

Conclusion: the response offers potentially useful additional diagnostics and
reported parse errors, with some basic metadata agreement. It does **not** prove
broader actionable coverage by comparing 52 mixed booleans with 16 issue types,
prove either count more accurate, verify sitemap membership, or establish crawler
replacement parity. No `enable_browser_rendering: true` was recorded; LCP `0`
must not be presented as measured Core Web Vitals. Business consistency, AI-access,
link graph, content hashes and action/live-recheck consumers require separate
capability testing. The single-page cost is not a full-site estimate.

### AI Optimization API (documented, not executed)

Documentation index (free, cached) confirms the API exists with:

- **AI Keyword Data**: `keywords_search_volume/live` — search volume inside AI tools;
  locations/languages endpoint.
- **LLM Mentions**: live mentions search, target metrics, multi-target metrics,
  top mentioned pages/domains/brands/brand categories, historical, timeseries
  delta, timeseries new/lost, target metrics lite.

No request was executed. Response shape, per-call cost, locale coverage and plan
availability are **unverified**. A vendor mentions dataset cannot be represented
as per-project prompt sampling or universal consumer visibility without evidence.
Current docs additionally list LLM Responses and ChatGPT/Gemini scraper products;
these differ from mentions and AI-demand datasets. Their existence does not prove
account access, locale suitability or output shape. DS-01 must select the product
matching the required measurement; authenticated consumer-UI proof is not required.

## Not verified (required before dependent tasks)

| Capability | Endpoint family | Why it matters |
|---|---|---|
| Task-based crawl | `on_page/task_post` + `pages` + `links` | DS-04 depends on full-site parity, not just one page |
| Backlinks list and intersections | `backlinks/backlinks`, `referring_domains`, `domain_intersection` | DS-05 prospect data |
| Labs keyword endpoints | `ranked_keywords`, `keyword_ideas`, `keyword_suggestions`, `bulk_keyword_difficulty`, `search_intent`, `historical_*` | DS-05 semantic/source decisions; free discovery survives unless demonstrably superseded |
| AI Optimization payload | `ai_optimization/*` | DS-06 go/no-go |
| AI Keyword Data | `ai_optimization/ai_keyword_data/*` | Demand signal for AI visibility work |
| Content Analysis source acquisition | `content_analysis/search/live` and required related endpoints | DS-03 source decision, not replacement of business synthesis |
| Per-endpoint pricing | pricing pages + live cost fields | DS-14 cadence and budgets |

Required new endpoint adoption needs bounded, authorised real requests and
sanitised fixtures. One call does not establish accuracy, pagination, non-empty
coverage, failure behavior or parity. Capture these for the actual supported
consumers before cutover. Documentation alone can guide design, not live verification.

## Documentation recheck and evidence durability

Read 2026-10-29 (documentation evidence only):
- https://docs.dataforseo.com/v3/on_page/instant_pages/ — browser rendering is
  disabled by default; enabling it is a separate option, unlike loading resources.
- https://docs.dataforseo.com/v3/ai_optimization/llm_mentions/overview/ — mentions
  dataset uses Live retrieval; not the same contract as LLM Responses/scrapers.
- https://docs.dataforseo.com/v3/ai_optimization/overview/ — product families and
  endpoint catalog must be checked for the measurement required.

Earlier raw comparison payloads are local scratch files
`/tmp/opencode/dfs-instant.json` and `/tmp/opencode/dfs-instant-full.json`.
They are not durable repository fixtures or a completed DS-01 handoff. Before
dependent adoption, preserve sanitised request/response fixtures with checksums,
endpoint/options, observation time and normaliser version in the owning repository;
do not commit credential/account payloads. DS-01 remains **incomplete**.
