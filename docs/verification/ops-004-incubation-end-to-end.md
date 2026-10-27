# OPS-004 — isolated Intake Lab verification

**Outcome: partial; production CrawlSEO chain not verified.** The first pass against the site-agent API was the wrong surface; incubation creation was exercised through a fresh Intake Lab, not the tenant API. No production CrawlSEO project, budget, customer, or site was mutated. The only external paid service used was two capped intake-advisor calls; the temporary config set a $0.10 daily LLM ceiling and 2,048 output-token limit. No price receipt was retained, so exact model spend is not asserted. No CrawlSEO research call was dispatched ($0 research spend).

## Isolated run

- Source: `46e779373f963602dbb79744a731b18093c2fa58`.
- Command: `PYTHONPATH=src python3 -m site_agent intake-lab --config /home/admin/releases/ops004-incubation-workspace/config.yaml --workspace /home/admin/releases/ops004-incubation-workspace --host 127.0.0.1 --port 3199 --env-file /home/admin/releases/ops004-incubation-workspace/model.env`.
- The CLI created its default incubation at startup; `GET /api/incubations` returned `200` and incubation `inc_aad1faf8b00c4e8da8914b41f491cc9f`, status `collecting`.
- The disposable config set CrawlSEO research authority to `crawlseo` (local producer fence active), disabled the provider because no disposable project binding/token was available, disabled infusion/pipeworx, and kept all data under the throwaway workspace. No production Intake Ada data directory was used.

Exact list command/response excerpt: `curl -i http://127.0.0.1:3199/api/incubations` → `200 OK`, `incubations[0].incubation_id=inc_aad1faf8b00c4e8da8914b41f491cc9f`, `status=collecting`, `current_intake_revision=0`, `current_genesis_revision=1`.

## Intake HTTP evidence

1. Exact call: `curl -i -X POST http://127.0.0.1:3199/api/incubations/inc_aad1faf8b00c4e8da8914b41f491cc9f/messages -H 'Content-Type: application/json' --data-binary @ops004-message.json`. JSON body:

   ```json
   {"message":"I'm starting Harborlight Cycle Repair, a fictional neighborhood bicycle repair shop in Portland. We handle tune-ups, flat fixes, brake adjustments, and commuter-bike maintenance. Our ideal customers are people who ride to work and families who ride locally. The main action should be to request a repair appointment by phone; we do not have online booking yet. Hours are Tuesday through Saturday, 9am–5pm. ASSUMED, not confirmed: most customers will be nearby commuters. DEFERRED: exact prices and whether we will offer same-day repairs are undecided; do not invent or publish either. Please capture the confirmed facts, keep the commuter-customer assumption labelled as an assumption, and keep price/same-day decisions deferred."}
   ```

   Response: `202 Accepted`, `job_id: 1`, session `intake-074f5a97c1d446d09ec9c8de5dc71299`, message `1`; job GET returned `done`, revision `2`, and Ada's reply explicitly preserved the assumption and deferrals.
2. Exact call: same POST endpoint, JSON body:

   ```json
   {"message":"For this disposable test, use the fictional number 503-555-0142 and show the Tuesday–Saturday, 9am–5pm hours in the footer and contact section. The feel should be warm neighborhood repair shop, practical and trustworthy rather than fancy. We have no logo or photos to provide; use a text wordmark and don't imply real shop photography. Please include Home, Services, and Contact as required pages. You may make ordinary visual-layout assumptions, but don't turn the commuter assumption into a confirmed fact; prices and same-day service remain deferred."}
   ```

   Response: `202 Accepted`, `job_id: 2`, message `4`; job GET returned `done`, revision `3`, `ready_to_build`, and no unresolved core paths. `GET http://127.0.0.1:3199/api/intake-sessions/intake-074f5a97c1d446d09ec9c8de5dc71299` returned `200`, revision `3`, draft hash `2c491a5ac60619e6a7e3e5c03f0c549e47a181ca8e3e427b5a098019c1cec578`; assumption `audience.secondary`, deferred `business.differentiators` and `conversion.success_outcome` remained labelled.

Job reads: `GET http://127.0.0.1:3199/api/incubations/inc_aad1faf8b00c4e8da8914b41f491cc9f/chat/jobs/1` and `/chat/jobs/2` each returned `200`; both jobs ended `done`, error `null`. Their results were revisions `2` and `3`; both reported `research.status=awaiting_confirmation` with reason `prelaunch_dispatch_requires_confirmed_intake`.
3. Exact call: `curl -i -X POST http://127.0.0.1:3199/api/intake-sessions/intake-074f5a97c1d446d09ec9c8de5dc71299/confirm -H 'Content-Type: application/json' --data-binary @ops004-confirm.json`. JSON body:

   ```json
   {"revision":3,"draft_hash":"2c491a5ac60619e6a7e3e5c03f0c549e47a181ca8e3e427b5a098019c1cec578","confirmation_text":"I confirm this disposable intake as recorded. This is not a request to build or publish a site.","idempotency_key":"ops004-confirm-inc_aad1faf8b00c4e8da8914b41f491cc9f-r3"}
   ```

   Response: `202 Accepted`, `confirmed: true`, `confirmed_revision: 4`, site-intake hash `90a0aae105c44e2012b1aad8cc814b577dbd75cb605241117dba7978476495e3`. The accepted snapshot retained provenance, assumption and deferred fields.

This confirmed the **intake session**, not the incubation lifecycle: `GET /api/incubations/{id}` still reported incubation status `collecting`. The application-level `POST /api/incubations/{id}/confirm-intake` was not called: source inspection shows it immediately dispatches prelaunch research and then starts a design build when the Intake Lab runtime is attached. There was no known bound test CrawlSEO project/budget to check first, and no enforceable ≤$0.10 build cap, so invoking that path would violate the paid-work guard.

## CrawlSEO/research/design-context checks

- Both completed advisor job results had `research: {"status":"awaiting_confirmation","reason":"prelaunch_dispatch_requires_confirmed_intake"}`. This is before the session-level confirmation above; it is not a dispatched request or receipt.
- `GET /api/incubations/{id}/research` returned `200` with `sources`, `findings`, `requests`, `jobs`, and `insights` all empty. Thus no prelaunch receipt/run ID exists; replay/restart idempotency is not exercised. No project/document ID or revision can be reported. The live CrawlSEO budget for a safe test target could not be read: this isolated incubation had no project binding or project-scoped credential. No project or budget was created.
- `GET /api/incubations/{id}/workspace` returned `200`, `phase: intake`, `confirmation.confirmed: true`, `confirmation.revision: 4`, and `candidate: null`; no build/design-context projection or research-finding revision was produced.
- Local research fencing: config selected CrawlSEO authority; `IncubationApplicationService` excludes local research/infusion executors under that authority. The response showed zero research requests/jobs/findings/sources, and the lab was stopped before any local producer ran. This proves the isolated fence path, not an end-to-end CrawlSEO dispatch.
- The empty research projection is an empty-success response rather than an explicit pending/blocked status. That acceptance condition failed.

Exact read calls were `curl -i http://127.0.0.1:3199/api/incubations/inc_aad1faf8b00c4e8da8914b41f491cc9f/research` and `curl -i http://127.0.0.1:3199/api/incubations/inc_aad1faf8b00c4e8da8914b41f491cc9f/workspace`; both returned `200 OK` with the response excerpts above. `curl -i http://127.0.0.1:3199/api/incubations/inc_aad1faf8b00c4e8da8914b41f491cc9f` also returned `200 OK`; incubation status remained `collecting`, session status was `confirmed`, revision `4`.

## Cleanup and remaining blockers

Exact cleanup call: `curl -i -X DELETE http://127.0.0.1:3199/api/incubations/inc_aad1faf8b00c4e8da8914b41f491cc9f` → `200 OK`, `{"deleted":true}`. The Intake Lab process on `127.0.0.1:3199` was stopped; the disposable workspace, its local registry/database and filtered model env file were removed. No customer artifacts remain.

To complete OPS-004 safely, provide/use an explicitly disposable CrawlSEO project with an already-configured readable budget and its project-scoped credential, plus a way to confirm intake without an uncontrolled paid design build (or an enforceable ≤$0.10 build cap). Then rerun the incubation-level confirmation path and verify receipt ordering, replay, knowledge/document revisions, and design-context projection. Until then, the consumer chain is incomplete; no live verification is claimed.
