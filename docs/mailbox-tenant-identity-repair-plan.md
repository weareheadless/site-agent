# Mailbox tenant identity repair

Status: phases 1, 2 and 4 implemented and tested; phase 5 is operator work
through existing lanes. Author: investigation session, 2026-11-27. All
Cloudflare calls during the investigation and verification were read-only.

This plan repairs one structural defect with four surfaces: the HelloAda
mailbox is still a single-tenant application wearing a multi-tenant
deployment. It is written for a coding AI to execute phase by phase. Every
phase is fleet-wide by construction (template, generator, adapter, shared
package); nothing in it is a per-tenant case, flag or rollout list.

## Structural cause

Tenancy stops at the Cloudflare resource boundary. Below it (Worker, D1, R2,
queues, routing) isolation is per tenant and was verified correct. Above it
and inside it, every key the application uses is derived from non-tenant
inputs, exactly as in upstream single-deployment Mailflare:

- the browser client keys its caches and storage on mailbox ids, message ids
  and query params — never on the tenant — while all tenants are served from
  one origin, `helloada.app`;
- the mailbox owner identity is resolved from a stored
  `helloada_tenant_owners` row that is accepted without validation, and was
  historically derived from the **global platform user id**
  (`ha_<sha256(payloadUserId)>`), an identity that spans tenants;
- mailbox record ids are derived from hostname/address alone
  (`ha_domain_<sha256(hostname)>` is byte-identical in every tenant DB on
  `helloada.app`);
- email routing rules reference worker **names** and are never reconciled when
  a worker is renamed or a mailbox address is folded.

Wherever two tenants meet through one of those keys — the shared browser
origin, the shared platform-account namespace, the shared `helloada.app`
hostname, the routing table — their mailboxes mix. This is why the mixing is
fleet-wide and not an oceanicvibes incident.

The one-sentence version for the issue tracker: **the port kept upstream
Mailflare's "one deployment = one origin = one owner" identity model, so every
tenant-scoped decision (client cache keys, owner id, record ids, routing
targets) is keyed on inputs that are not tenant-exclusive.**

## Fleet state (investigated 2026-11-27; re-verified after the validation-fleet retirement)

Verified live, read-only. Five disposable validation tenants were retired from
`deploy/payload-customers.json` during implementation
(`ada-direct-admin-sso-e2e-…`, `helloada-handoff-validation-…`,
`northstar-coffee-e2e-validation-…` ×2, `northstar-coffee-full-intake-…`), so
the fleet below is the current seven. Rows for retired tenants are kept at the
end with their historical finding, because that is what the analysis was based
on.

| Tenant | Mailbox DB state | Owner id | Defects present |
| --- | --- | --- | --- |
| casamigo | 1 mailbox `casamigo@helloada.app`, 0 msgs | tenant-derived | client-plane only |
| atelier-harmonie | 1 mailbox, 0 msgs | tenant-derived | client-plane only |
| inmersion-freediving-… | 1 mailbox, 4 msgs | tenant-derived | client-plane only |
| **oceanicvibes** | 1 mailbox, **4 msgs** | **sha256("6")** = platform user 6 | **the one remaining legacy owner id**, and a **second full-access grant** for sha256("8"). This is the only real repair left in the fleet, and therefore the canary. |
| site-be8225c72f3ba01a (superincompetence) | folded: platform mailbox disabled + alias, custom `hello@superincompetence.com`, 0 msgs | tenant-derived | none after the fold |
| site-ff8e9af06f56201f (astridrincon) | folded: platform mailbox disabled + alias (2026-11-18 20:11 UTC), custom `hello@astridrincon.com`, 8 msgs | tenant-derived | **alias routing rule `site-ff8e9af06f56201f@helloada.app` targets nonexistent worker `helloada-site-ff8e9af06f56201f`** (worker was renamed to `helloada-site-astridrincon`); alias mail is lost |
| ada-e2e-studio-intake-… (disposable) | **DB completely empty** despite worker bindings, tenant.env address and enabled routing rule | — | provisioning stalled before its first write; the only disposable left, so it is the disposable proof for first-open, not for repair |
| *orphan* | routing rule `site-5fe73d3d38ff6f77@helloada.app` targets a nonexistent worker; the tenant is in no manifest | — | reported by the reconcile plan; deletion belongs to retirement, not to this work |

Retired during this work (historical findings, no action):

| Tenant | Finding at investigation time |
| --- | --- |
| northstar-coffee-full-intake-validation-… | legacy owner id `sha256("5")` — was the named Phase 2 proof tenant until it was retired |
| northstar-coffee-house-… | worker had no MAILFLARE bindings at all |
| ada-direct-admin-sso-e2e-…, northstar-coffee-e2e-validation-… ×2, helloada-handoff-validation-… | disposable shells, no complete mailbox |

Client-plane defects affect **every** tenant pair visited in one browser
session; they are not per-tenant rows in the table.

### Client-plane mechanism (why "all tenants look mixed up")

All tenants' mailboxes render from one origin (`helloada.app/<site>/mail`) via
the generated package `packages/helloada-mailbox-ui` (generated by
`scripts/build.mjs` from pinned upstream; `dist/` is regenerated, never
hand-edited):

1. `fetchMailboxOptions()` (`dist/src/components/mailbox-provider-utils.ts`)
   caches the mailbox list in a module-level variable invalidated by
   `mailboxesCacheSessionToken === getClientSessionToken()`. The generator
   patched `authFetch` to a plain fetch — the mailbox "never holds a tenant
   session" — so `getClientSessionToken()` is **always null** and the cache,
   once filled by tenant A, is served to tenant B, C, … forever. This is the
   "mixed up configs" symptom: the header, address list and sender identities
   of a previously visited tenant.
2. `messageListCache` / `messageCountsCache` (`dist/src/hooks/utils.ts:~167`)
   are keyed by `params.toString()`. The all-mailboxes view omits `mailboxId`
   from params, so tenant A's and tenant B's inbox keys are byte-identical
   (`direction=inbound&status=received&timeZone=…`). Tenant B's inbox renders
   tenant A's cached messages and unread counts. This is the "mixed up
   content" symptom.
3. `selected-mailbox-id` and ~15 further storage keys (sidebar, column widths,
   conversation view, assistant conversation `mailflare-assistant-conversation:<mailboxId>`,
   dashboard state, time zone, `mailflare-navigation-opened-unread`) are
   origin-global. Record ids are tenant-less derivations (surface 3 above), so
   even id-keyed storage collides conceptually across tenants.
4. `MailboxProvider`'s load effect ends in `.catch(() => {})`: a 503
   "mailbox is being prepared" response (unprovisioned tenants) is swallowed,
   and the stale state from the previous tenant remains on screen.
5. `MailboxApp` (`base.tsx`/`index.tsx`) keeps module-global `active` config
   and a `QueryClient` created once per mount; the control plane
   (`/SOCIAL/helloada/src/app/[site]/mail/[[...path]]/page.tsx`) renders it
   without `key={tenantId}`, and module-level caches survive any remount
   regardless.

Server-side request scoping was verified correct end to end:
`ownedWebsite → tenantId → proxyTenantWorkspace` (helloada), `require_control_tenant`
+ tenant token (site-agent `workspace.py:1988`), `no-store` responses, per-tenant
Worker/D1/queue bindings, per-address routing rules to the correct worker
(except the astrid alias and the orphan above), each mail queue consumed by its
own script. **No fix is needed in the request path.**

## Out of scope / explicitly not broken

- Cloudflare resource isolation (D1/R2/queues/consumers/bindings): verified
  per tenant, correct.
- `tenant.env` `MAILFLARE_*` values: verified consistent with registered
  addresses and worker secret bindings (`MAILFLARE_ADDRESS`, `MAILFLARE_ZONE_ID`,
  `MAILFLARE_ROUTING_STATUS` are `secret_text`; values unreadable but names
  present on every provisioned worker).
- Astrid's outbound messages showing `From: site-ff8e9af06f56201f@helloada.app`
  on 2026-11-18 17:38 UTC are **not** a defect: the fold to the custom domain
  happened 2026-11-18 20:11 UTC, after those sends.
- Record-id rewrite (surface 3): see phase 3 — the invariant is enforced, the
  ids are not migrated.

---

## Implementation plan

Ground rules for the coding AI (from `AGENTS.md`, binding on every phase):

- Start each phase with a failing focused test; fix the cause, delete the dead
  mechanism in the same change, leave no fallback or compatibility switch.
- Both repos are dirty with unrelated uncommitted work
  (`/SOCIAL/site-agent`: payload-core/chat_jobs/media-owner-note;
  `/SOCIAL/helloada`: branch `fix/readable-addresses-and-stale-builds`).
  Branch from official `main`; do not entangle or commit that work.
- Never hand-edit `packages/helloada-mailbox-ui/dist`; change
  `scripts/build.mjs` (and its patch functions) and regenerate.
- Prove every lane change on a `disposable: true` tenant before any customer.
  **Fleet note (2026-11-27, later the same day):** the five disposable
  validation tenants were retired from `deploy/payload-customers.json` while
  this plan was being implemented, including
  `northstar-coffee-full-intake-validation-5a8564dae07494ec`, which was the
  named proof tenant for Phase 2. The fleet is now seven tenants and exactly one
  is `disposable`: `ada-e2e-studio-intake-0aa0b1a55ae48348`, whose mailbox
  database is completely empty — it can prove the *first-open* path but not a
  *repair*, because it has no legacy identity to repair. Phase 2's proof
  therefore changes shape (see Phase 2, step 6).
- Release lanes: shared package + helloada app →
  `deploy/desired-helloada-app-release.json`; template/overlay change →
  shared-runtime fingerprint fan-out (canary first, batches of five);
  site-agent API change → `deploy/desired-api-release.json`. No tenant
  repository is edited in any phase.
- The issue is the status: one GitHub issue per phase, closed with merge SHA.

### Phase 1 — Tenant-scoped mailbox client

Repos: `site-agent` (generator + regenerated dist), `helloada` (mount).
No tenant worker rebuild; this ships as a helloada app release only.

1. `MailboxConfig` gains a required `tenantKey: string`. `base.tsx`
   (`writeBase` in `build.mjs`): `configureMailbox` compares the incoming
   `tenantKey` with the active one and, on change, clears **all** module
   caches (message list/counts + in-flight request maps, bumping their
   generations, mailbox options cache) and resets the `QueryClient`.
2. `helloada`: `src/app/[site]/mail/[[...path]]/page.tsx` passes
   `tenantKey: tenantId` (already destructured from `loadSiteView`) and adds
   `key={tenantId}` to `<MailboxApp>` as a hard remount boundary.
3. Replace the dead session-token invalidation with tenant-key invalidation:
   `mailbox-provider-utils.ts` caches become `Map<string, …>` keyed by
   `tenantKey`; delete the `mailboxesCacheSessionToken` /
   `mailboxesRequestSessionToken` mechanism and the unreachable
   `setClientSessionToken`/`persistAuthSession` writers if the generator's
   closure allows (do not keep a dead invalidation path "just in case").
4. Message caches: key = `${tenantKey}|${params.toString()}` in
   `hooks/utils.ts` for both list and counts caches and their request maps.
5. Storage: one generated helper, e.g. `mailboxStorageKey(name) =>
   "helloada-mailbox:" + tenantKey + ":" + name`, and every
   `localStorage`/`sessionStorage` call in the generated output goes through
   it (selected mailbox, assistant conversation, sidebar, column widths,
   reorderable lists, reading preferences, dashboard state, time zone,
   opened-unread). Old unprefixed keys: on first run under a tenant, remove
   matching legacy global keys (bounded list, one-time) instead of migrating
   values — these are UI preferences, not data.
6. Fail loud: `MailboxProvider` keeps an explicit `error` state; a non-OK
   `/api/mailboxes` response (including the 503 setup JSON) renders a
   "HelloAda is preparing your inbox" panel and never a stale list. Remove
   `.catch(() => {})`.
7. Tests (class-level, not instance-level):
   - generator scan test: no `localStorage`/`sessionStorage` call in `dist`
     outside the tenant-keyed helper; no module-level `Map`/cache whose key
     expression lacks the tenant key; no cache invalidation keyed on
     `getClientSessionToken`.
   - behavior test: two configs with different `tenantKey` against a mocked
     fetch; assert tenant B never receives tenant A's mailbox list, message
     list or counts, and that switching tenants clears storage-scoped state.
   - helloada: extend `tests/mailbox-ui.test.mjs` /
     `tests/mail-workspace.test.mjs` with the `key`/`tenantKey` contract.
8. Acceptance: authenticated browser session on production helloada.app,
   visit two tenants' inboxes alternately (client-side navigation and hard
   reload), each shows only its own address, messages and counts; an
   unprovisioned tenant shows the preparing panel; zero console errors and
   zero failed requests.

### Phase 2 — Tenant-exclusive owner identity

Repo: `site-agent` template (`src/site_agent/templates/next-payload/`). Ships
as a shared-runtime fan-out (canary → batches of five).

1. Canonical derivation, single definition:
   `tenantOwnerUserId(tenantId) = "ha_" + sha256("tenant:" + tenantId)`.
2. Idempotent repair in the provisioning path (same pattern and location as
   `foldSupersededTenantMailboxes`; runs from `ensureOwnerSession` and
   `ensureTenantBookingOwner` before use):
   - no stored owner row → insert canonical;
   - stored owner == canonical → no-op;
   - stored owner != canonical (legacy platform-derived) → repair:
     a. create/confirm the canonical `users` row;
     b. re-point every owner-scoped row from **each** non-service legacy user
        to the canonical id: `sessions`, `helloada_booking_settings`,
        `booking_events`, `calendar_events`, `contacts`, `mailbox_access`
        (dedupe on the unique mailbox/user index), `agent_conversations`,
        `agent_send_approvals`, `agent_jobs`, `agent_draft_metadata`,
        `outbound_jobs`, `email_templates`, `push_subscriptions`,
        `audit_logs` (actor/target), `routing_rules`, `webhooks`. Enumerate
        from `upstream/src/db/schema/index.ts` at implementation time; the
        list above is the investigation snapshot, the schema is the source of
        truth. Rationale: the single-owner gate means every non-service user
        in these DBs is a historical artifact of the same owner seat; there
        is no second human to preserve.
     c. delete `mailbox_access` grants for any user that is neither the
        canonical owner nor the tenant service account (this revokes
        oceanicvibes' sha256("8") grant);
     d. disable (do not delete) legacy `users` rows;
     e. CAS-update `helloada_tenant_owners` from the exact legacy value to
        the canonical one; re-read and verify.
   - fail closed with a named error (no partial write; the repair is
     re-runnable) if any step cannot verify its postcondition.
3. Strict gate: `ownerUserId()` and `resolveTenantBookingOwner()` accept only
   the canonical id. A stored row that disagrees *after* repair is a hard
   error (`mailbox_owner_identity_invalid`), never a silently preferred value.
   Delete the "prefer whatever is stored" branch.
4. Bridge subject contract: `createMailflareMailBridge` keeps requiring
   `x-helloada-owner-subject` for audit, and the code comment states plainly
   that authorization is the tenant token + control-plane website scoping;
   the subject must never re-enter identity derivation. Update
   `docs/mailflare-single-worker-contract.md` accordingly.
5. Tests (template test suite): fixture DB with (a) legacy stored owner +
   data rows, (b) a second full_access platform user, (c) already-canonical
   tenant. Assert postconditions: exactly one enabled non-service user
   (canonical); all owner-scoped rows re-pointed; foreign grants gone;
   `helloada_tenant_owners` canonical; second run is a no-op; a simulated
   mid-repair failure leaves the next run able to complete.
6. Rollout order (hard requirement): the repair and the strict gate ship in
   the **same** runtime release — repair runs before validation on every
   request path, so no tenant can fail closed merely by being legacy.

   The original proof route (a disposable tenant that already carried the
   legacy identity) was retired with the validation fleet. The proof is now
   layered, because no disposable tenant can carry a real legacy registration:

   a. **Unit proof of the repair itself** — already in place and green:
      `tests/mailflare-owner-identity.test.mjs` runs the repair against a real
      SQLite schema with a legacy registration, a foreign full-access grant,
      rows behind every unique index, and asserts the postconditions, the
      idempotent second run, the disabled-not-deleted rule and the fail-closed
      path. This is the layer that proves the *migration logic*.
   b. **Disposable proof of the shipped bytes** — `ada-e2e-studio-intake-…`
      (the only `disposable: true` tenant, mailbox D1 empty) proves that the
      released runtime provisions a first-open owner correctly through the new
      resolver: hit the gate, verify one canonical owner, one service account
      and one grant appear, and that a second request is a no-op. It also
      proves the release/config path end to end.
   c. **Canary on the one real legacy tenant** — `oceanicvibes` is the only
      remaining tenant whose registration is platform-derived
      (`ha_<sha256("6")>`) and whose mailbox carries a second full-access
      grant (`ha_<sha256("8")>`). It is a customer, so it is the canary only
      because canary is the smallest possible exposure and the repair is
      already proven at (a) and (b). Record the read-only before-snapshot
      (owner row, users, grants, message count — 4 messages), release, then
      assert the after-snapshot: one enabled non-service user, one
      `full_access` grant, the same message count, the same visible inbox.
      If the after-snapshot does not match, the fix is reverted forward with a
      new release id and the tenant is reported, never hand-edited.

   Then the remaining tenants receive it by inheritance in batches of five. No
   bespoke migration, no manual D1 writes anywhere.
7. Acceptance: post-rollout D1 snapshot (read-only, secret-free, recorded in
   the issue): oceanicvibes has one enabled non-service user
   `ha_<sha256("tenant:oceanicvibes")>`, one full_access grant, the same 4
   messages as the pre-migration snapshot in this doc; northstar-full-intake
   likewise; every other tenant's owner row unchanged. Owner opens
   oceanicvibes mailbox in an authenticated browser session and sees the same
   inbox as before.

### Phase 3 — Tenant-less record ids: invariant, not migration

Decision: do **not** rewrite `ha_domain_*` / `ha_mailbox_*` / message ids.
They are internally consistent inside each per-tenant DB, and a fleet-wide
id rewrite touches every foreign key for zero behavioral gain once phases 1–2
make the tenant the root of every cross-boundary key. Instead:

1. Record the invariant in `docs/mailflare-single-worker-contract.md`:
   mailbox record ids are tenant-local; any surface that carries them across
   tenants (client caches, future aggregation, telemetry, support tooling)
   must key on `(tenant, id)`.
2. The phase-1 generator scan test is the enforcement for the only surface
   that exists today (the client).

### Phase 4 — Email routing reconciliation (adapter-owned)

Repo: `site-agent` (Python API + adapter). Ships as an API release
(`deploy/desired-api-release.json`); mutations only through the existing
`provision-email` adapter lane — never ad-hoc Cloudflare calls.

1. Add a reconcile step to the email provisioning adapter. For every
   registered tenant, plan (read-only) then apply:
   - every address the tenant owns — its registered `MAILFLARE_ADDRESS` plus
     every alias in its mailbox DB (`mailbox_aliases` joined to `domains`,
     read via Cloudflare D1 query API using the registered
     `mailflareD1DatabaseId`) — has exactly one **enabled** routing rule in
     the correct zone targeting the tenant's **current** worker name;
   - rules targeting a nonexistent worker, or a stale worker name of a
     registered tenant, are re-pointed (enabled) — this repairs
     `site-ff8e9af06f56201f@helloada.app → helloada-site-astridrincon`;
   - rules matching no registered tenant are reported and, with the operator
     running `--apply`, deleted — this removes the `site-5fe73d3d38ff6f77`
     orphan;
   - unknown zone/credential state stays a hard stop (`action_required`),
     per the existing email-token contract.
2. The reconcile is part of the mechanism, not a one-off script: it runs on
   every `provision-email` invocation and inside the scheduler-driven
   `email_provisioning` job, so a future worker rename self-heals.
3. Tests: plan-logic unit tests over fixture rule/tenant/alias sets
   (rename, orphan, missing rule, duplicate rule, disabled rule); the
   disposable-tenant proof: break a rule on
   `ada-e2e-studio-intake-0aa0b1a55ae48348` (enabled, live routing today),
   watch the adapter plan and repair it.
4. Acceptance: after the operator run, live routing table shows
   `site-ff8e9af06f56201f@helloada.app → helloada-site-astridrincon`
   (enabled), the orphan gone, and a test message sent to the astrid alias
   arrives in the `hello@astridrincon.com` mailbox (the fold's delivery
   promise, verified end to end).

### Phase 5 — Stalled provisioning convergence (ops, existing lanes)

No new code. The validation fleet was retired on 2026-11-27, which closed most
of this phase; what remains is one tenant.

1. `ada-e2e-studio-intake-0aa0b1a55ae48348` (the only `disposable: true`
   tenant): worker bindings, a registered address in `tenant.env` and an
   enabled routing rule exist, but its mailbox D1 is completely empty. It is
   also Phase 2's disposable proof of the first-open path. Do not leave it
   half-provisioned with a live routing rule pointing at an empty database:
   either drive the gate once to prove provisioning and keep it, or retire it
   through the same lane that retired the other validation tenants. Reporting
   only — its routing rule is included in the reconcile plan as `orphan` and is
   **not** deleted, because retirement owns that deletion.
2. Orchestrating tenants with no custom email domain stay `domain_required`.
   That is a legitimate waiting state, not a failure, and Phase 1 makes it
   visible as the preparing panel rather than another tenant's inbox. Nothing
   to do until an owner registers a domain.

### Implementation status (2026-11-27)

### Deployed state (2026-11-28)

**Phase 1 is live in production.** Contract

- `site-agent` `main` `dff4e550` (PR #638, squash-merged).
- `helloada-mailbox-ui-v0.4.2` published, sha256
  `74c37aa3778559f0993d5b075af1b13927e1122c132e66cbf0da212a1dde22b8`.
- `helloada` `main` `ff8adb50` (PR #46), released as
  `20261128-mailbox-tenant-key`; Worker version `01310a82` at 100% traffic;
  `/api/health` reports `releaseSha=ff8adb500ab33dfe9f28772f9f2b49e3a772aa37`.
- Phase 2 shipped by the ordinary fan-out at fingerprint `fc48b8a28d40` after
  the grant-identity hotfix (PR #641, merged `821e18f9`). The canary
  `ada-e2e-studio-intake-…` passed; the batch delivered every registered
  automatic tenant.

Verified in an authenticated production browser session, not from the receipt:

| Check | Result |
| --- | --- |
| casamigo inbox | renders its own (empty) inbox, `total: 0` |
| oceanicvibes inbox | renders its own 4 messages, `total: 4`, no casamigo data |
| cross-tenant | one identity, one mailbox per site; the UI drops the previous tenant's state on switch |
| own address | each tenant's header and message rows name its own mailbox |
| console/module errors | none observed |

**Phase 2 is fanning out by inheritance**, not by a hand-queued list: the timer
saw the new fingerprint (`3b7ccb8c…`) on its own and queued the canary
`ada-e2e-studio-intake-0aa0b1a55ae48348`. oceanicvibes is repaired in its batch.

Before-snapshot for oceanicvibes (the one real legacy tenant), read-only:

```
canonical owner : ha_99503793d7ed139d501db3ed9f617d7e613f5832e1781122c1453bb3d8e6ff43
registered owner: ha_e7f6c011776e8db7cd330b54174fd76f7d0216b612387a5ffcfb81e6f0919683  (legacy)
users           : service, ha_e7f6c011…, ha_2c624232… (all enabled)
mailbox_access  : ha_e7f6c011… full_access, ha_2c624232… full_access
messages        : 4
```

After the batch the expectation is: the registration is the canonical id, both
legacy accounts are disabled but still present, one `full_access` grant, the
same 4 messages, and the same visible inbox.

| Phase | State | Landed in | Tests |
| --- | --- | --- | --- |
| 1 client scoping | **deployed** | `packages/helloada-mailbox-ui/scripts/build.mjs` (`writeScope`, `patchTenantScopedCaches`, `patchTenantScopedStorage`, `patchMailboxProvider`, `patchMailboxSelector`, `removeDeadSessionModules`), generated `dist/scope.ts`, `helloada` mount `key`/`tenantKey` | `packages/helloada-mailbox-ui/tests/contract.test.mjs` (6 new tests, 20 total) |
| 2 identity repair | **deployed and verified on the one legacy tenant** | `templates/next-payload/mailflare-owner-identity.ts` (added to the shared-runtime overlay); gate repairs (`mailflare-owner-gate.ts`), public booking path resolves read-only (`mailflare-booking-service.ts`) | `mailflare-owner-identity.test.mjs` (9), rewritten `booking-owner.test.mjs`, updated `booking-runtime.test.mjs`, `build-contract.test.mjs` (13) |
| 3 id invariant | documented | this document; enforced by the phase-1 generator scan test | — |
| 4 routing reconcile | implemented | `application/email_routing_reconcile.py` (pure plan + apply), `application/email_routing_fleet.py` (fleet gather), `site-agent reconcile-email-routing` CLI | `tests/test_email_routing_reconcile.py` (12), `tests/test_email_routing_fleet.py` (6) |
| 5 ops convergence | operator | existing `provision-email` lane; the new CLI reports the rest as `actionRequired` | — |

### Release ordering for phase 1

The mailbox UI is a package the app installs by release URL, so the two halves
ship in one order and not the other:

1. `packages/helloada-mailbox-ui/package.json` is at `0.4.2`; cut
   `helloada-mailbox-ui-v0.4.2` from the reviewed `site-agent` commit with
   `scripts/package-helloada-mailbox-ui-release.mjs`. **Done:** published,
   sha256 `74c37aa3778559f0993d5b075af1b13927e1122c132e66cbf0da212a1dde22b8`,
   from `3012fe25`. The app must not consume 0.4.0 or 0.4.1 (see below).
2. `helloada/package.json` and `package-lock.json` name
   `helloada-mailbox-ui-v0.4.2`. Until the release exists, `npm ci` in a fresh
   `helloada` checkout cannot resolve the package. That is the intended ordering
   constraint, not a broken lock: the app must not ship a mount that passes
   `tenantKey` to a package that ignores it.
3. Then release `helloada` through `deploy/desired-helloada-app-release.json`.

### A production incident the repair caused, and the boundary it exposed

The repair worked. The next mailbox request for the tenant it repaired returned
an error page, and the reason is worth keeping.

`ensureOwnerSession` inserted the owner's `full_access` grant with
`INSERT OR IGNORE`, then required the stored id to equal the id it had just
generated. The repair *re-points* a legacy grant rather than recreating it, so
the grant it kept carried the old id. `INSERT OR IGNORE` correctly did nothing,
and the id check read a valid grant as a provisioning failure — on every mailbox
request, so the whole mailbox was down for that owner.

The table already declared its identity: `mailbox_access_mailbox_user_idx` is
unique on `(mailbox_id, user_id)`. The grant is now found on that pair and its
permission verified, which is what "the owner has access" actually means.

Two things this says:

1. **The defect predates this work.** The id comparison could only ever fail on
   a grant that already existed under another id, which nothing produced before
   the repair existed. It was invisible because the path was never exercised.
2. **A migration that preserves rows exposes every assumption that they are
   recreated.** The write paths that consume repaired state are part of the
   migration's contract, not a separate concern to be verified later.

Verified after the fix, in the live tenant: registration canonical, both legacy
accounts disabled (not deleted), exactly one `full_access` grant, 4 messages
before and after, and the inbox rendering them.

### Two boundary errors CI caught before merge, and what they were

Both were mine, both were invisible locally, and both are worth keeping because
each names a different way the same mistake can hide.

1. **A public request was running the repair.** `resolveTenantOwnerUserId` ran
   `ensureTenantOwnerIdentity`, and the public booking runtime calls it on every
   anonymous page load and enquiry. One stranger visiting a booking page could
   have rewritten thirty owner-scoped tables on a tenant whose registration was
   still legacy. Resolving an owner is a read; repairing one is a migration, and
   a migration belongs to the authenticated owner path.
   - `resolveTenantOwnerUserId` now resolves and verifies only, and fails closed
     with `mailbox_owner_identity_invalid` on a non-canonical registration.
   - `resolveOrRepairTenantOwnerUserId` is the repair, used by the gate and the
     authenticated `/api/workspace/booking` route.
   - The test asserts both directions: a public resolve on a legacy registration
     writes nothing, and repair-then-resolve serves.

2. **The module was in neither place that ships it.** Adding
   `mailflare-owner-identity.ts` to the template without adding it to
   `deploy/shared-runtime-overlay.json` broke the tenant build
   (`UNRESOLVED_IMPORT` in `mailflare-integration`); the vendored Mailflare build
   had the same gap in `packages/helloada-mailflare/scripts/build.mjs`, which
   copies `mailflare-booking-service.ts` without what it imports. Local tests
   passed both times because the file sits next to its importer in this checkout.
   - Both copy paths now carry the module, and the overlay's packaged twin is
     byte-identical.
   - `tests/test_shared_runtime.py` asserts that every relative import between
     modules the overlay copies resolves inside the copied set.
   - `build-contract.test.mjs` asserts the same for the vendored tree *and* that
     `scripts/build.mjs` actually performs each copy.

Both changes are inside the shared-runtime boundary, so the fingerprint moved
twice more (`5dcab068…`, then `3b7ccb8c…`); both were restamped with
`stamp_declared_runtime`.

### Three release defects this work produced and now guards against

Only the consuming app's `tsc` caught these; every build assertion and grep
passed on both broken artifacts. They are recorded because the same class will
be attempted again.

1. **0.4.0 shipped an entry point that does not parse.** A template-literal
   escape in the generator lost its backslash, emitting
   `path.replace(//+$/, "")` instead of `/\/+$/` — `TS1135` in every consumer.
   The guard compiles and *runs* the emitted expression rather than matching its
   text, because a text assertion on something that looks like a regex passes on
   the broken output.
2. **0.4.1 additionally deleted a constant the sidebar still uses.**
   `removeDeadSidebarBootstrap` removed `SIDEBAR_MINIMAL_STORAGE_KEY` along with
   the dead inline bootstrap, while `readInitialSidebarMinimal`,
   `saveInitialSidebarMinimal` and `syncInitialSidebarWidth` still reference it —
   `TS2304` in every consumer. The pass now fails the build if an ALL_CAPS
   identifier survives its removal without a declaration in that file.
3. **The release gate could not see either.** It asserted text only. It now
   compiles the packed tree with the package's own pinned TypeScript
   (`typescript` is a devDependency, so the gate is self-contained) and fails on
   any diagnostic. It extracts inside the package tree, because a temp directory
   outside the package's module resolution reports every dependency as missing
   and rejects a healthy artifact.

Published tags are never rewritten; 0.4.2 is the first consumable artifact.

### Fingerprint consequence

Phase 2 changes files inside the shared-runtime boundary, so
`shared_runtime_fingerprint` moves. The declaration in `template-manifest.json`
and `wrangler.jsonc` was re-stamped with the canonical
`stamp_declared_runtime`, not by hand (`a40da57b…`). Phase 2 therefore ships by
the ordinary fan-out — canary, then batches of five, with a new immutable
release id. No tenant edit and no hand-queued runtime fingerprint.

Two findings the implementation produced that the analysis had not:

- **A forwarding rule is not an orphan.** `admin@helloada.app → ben@jamin.io`
  has no Worker destination; it is a person's mail. Orphan removal now skips
  any rule without a Worker action and reports it as `forwarding: true`.
- **`deploy/payload-customers.json` nests tenants under `customers`.** Reading
  it one level shallower silently disabled mailbox-alias lookup, which is the
  input that finds a folded address like astrid's. The CLI now reports
  `mailflareD1DatabaseId` per tenant from that shape.

Live read-only plan run against the fleet (2026-11-27) finds exactly the defect
in this document — one repoint, `site-ff8e9af06f56201f@helloada.app` still
targeting `helloada-site-ff8e9af06f56201f` — plus 9 rules already correct and
4 tenants needing operator attention (2 with no registered Worker, 2 with no
registered address). It does not touch the forwarding rule.

### Sequencing summary
| Order | Phase | Lane | Proof | Customer effect |
| --- | --- | --- | --- | --- |
| 1 | Phase 1 client scoping | package + helloada app release | — (UI verified in an authenticated production session) | stops all visible mixing immediately |
| 2 | Phase 2 identity repair + strict gate | shared-runtime fan-out, canary → batches of 5 | unit repair tests + `ada-e2e-studio-intake` first-open + `oceanicvibes` canary | the one real legacy tenant repaired, no second owner anywhere |
| 3 | Phase 4 routing reconcile | API release + operator `--apply` | `ada-e2e-studio-intake` (break a rule, watch it repair) | the astrid alias delivers again |
| 4 | Phase 5 ops convergence | existing CLI lanes | same disposable tenant | honest state for the one stalled tenant |
| — | Phase 3 invariant | docs + phase-1 test | — | prevents regression of the class |

Phases 1 and 2 are independent and may be built in parallel; phase 1 ships
first because it is the surface every tenant is bleeding through today and
needs no worker fan-out. Phase 4 depends on nothing but ships after phase 1
so the astrid acceptance check (alias mail visible in the UI) is meaningful.

### Definition of done (all phases)

The five mission-lock questions answered yes with evidence: released artifacts
match what was approved; each behavior observed on the real owner-visible
pages in an authenticated browser session (two-tenant alternation, reduced
console to zero errors); no step bypassed the provisioning/queue/approval
contracts (all mutations via adapter and release lanes, receipts recorded);
reported state matches live workspace state (D1 snapshots, routing table
export in the issues); result honestly ready for owner feedback. Failed work
is reported as failed, with its receipt.
