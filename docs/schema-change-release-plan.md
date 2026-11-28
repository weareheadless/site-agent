# Standardise the fleet, then a schema change travels with the code

Status: proposed. Nothing here has been implemented or deployed.
Supersedes the earlier draft of this document.

## The decision this plan implements

Owner directive, 2026-11-27:

> What I do not want is weirdness because of legacy. If any tenant has to be
> standardised to fit the package and the template, we must go that way. We
> have only a few tenants and the freedom to standardise. Make the thing the
> most standard possible, to have the most standard deployments, and avoid
> problems and exceptions.

This plan therefore standardises first and treats the schema gap as a
consequence of that standardisation, not as a special case to be tolerated.

## What the live data actually shows

Measured 2026-11-27 against each tenant's registered D1, comparing its live
`sqlite_master` to the candidate schema snapshot:

```
tenant                                   missing_tables  tables_with_missing_cols
ada-e2e-studio-intake-0aa0b1a55ae48348        0         1  (media)
atelier-harmonie                              0         1  (media)
casamigo                                      0         1  (media)
inmersion-freediving-bb2a4e404a7fcea4         0         1  (media)
oceanicvibes                                  0         1  (media)
site-be8225c72f3ba01a                         0         1  (media)
site-ff8e9af06f56201f                         0         1  (media)
--- older sandboxes, not customer sites ---
helloada-handoff-validation-20261021...      20        24
northstar-coffee-full-intake-validation...   20        24
ada-direct-admin-sso-e2e-a76df8a18...        37        18
northstar-coffee-e2e-validation-8fbf2e...    37        18
northstar-coffee-e2e-validation-long-...     37        18
northstar-coffee-house-afd6a0232bf10fd4      37        18
```

Two conclusions, both of which contradict the assumption that legacy
divergence is the problem:

1. **Every live customer tenant is already structurally identical to the
   revision-13 template.** All seven have zero missing tables and exactly one
   missing column, `media.owner_note`. Their schema is standard.
2. **The `media` delta is the only schema drift on customer sites**, and it is
   the incident, not legacy.

### The migration *ledgers* diverge while the *schemas* agree

Verified against `weareheadless/oceanicvibes`:

```
template chain   12 migrations (helloada_initial, helloada_owner_handoff, ...)
tenant chain     15 migrations (initial, payload_first_content_contract, ...)
shared names      8
template only     4
tenant only       7
```

The tenant's chain is not a prefix of the template's. But its resulting
**schema** matches the template's. So the divergence is historical bookkeeping
(name and ordering of early migrations), not structural difference. That is
what makes standardisation tractable now: the destination is already the same
for everyone.

### Two snapshot blind spots this exposes

- `20261004_090000_growth_operations.ts` creates
  `helloada_growth_candidates` and `helloada_growth_operations` with raw SQL,
  and the migration snapshot does not record them. Every live database has
  them. A structural check must therefore treat the snapshot as a floor and
  allow tables the shared chain creates with raw SQL, or it will report false
  drift on all tenants.
- Migration snapshots record the full schema (249 tables / 1,854 columns at
  revision 14), so exact comparison is available without field-name
  heuristics.

## The invariant to establish

> One standard: every tenant's database schema equals the schema the shipped
> package and template declare. A release proves it before the new code takes
> traffic.

Standardisation is the goal; the proof is what keeps it true.

## Steps

Steps 1-3 change the control plane and the registry. They rebuild nothing and
disturb no customer. Step 4 is proven on a disposable tenant. Step 5 is the
first customer-affecting change, and it is also the notes repair.

### Step 1: make the registry describe reality

The registry currently disagrees with the fleet in ways that will fail the
next API release preflight:

- three live tenants' `activate-runtime` calls timed out, so
  `deploy/payload-customers.json` still says `payloadCore 0.6.5 / rev 13`
  while those Workers report `0.6.6 / rev 14`;
- the fan-out planner currently returns `state: blocked` with
  `blocked: [oceanicvibes]`, so no batch will be queued until it is resolved:
  `oceanicvibes` is blocked because its queued request failed at
  `verify-connection`.

Do: reconcile registry fields to live Worker health for the deployed tenants;
clear `oceanicvibes`'s failed request so the planner can advance it.

**Done already (2026-11-27):** `northstar-coffee-house-afd6a0232bf10fd4` was
retired on the owner's instruction. It was registered `automatic` but was not
marked disposable, had no successful release history (so no source SHA to
rebuild), and its home page returned 500. An `automatic` registration with no
history blocks the whole fleet permanently. Its D1 export (228 tables, 3 rows,
no pages or media), tenant directory and both registry snapshots are kept under
`/SOCIAL/backups/retired-northstar-coffee-house-20261127/`, following the
`site-5fe73d3d38ff6f77` precedent. Removed from
`/SOCIAL/site-agent-api/websites/tenants.json` and
`deploy/payload-customers.json`; no queue entry existed. The planner now
blocks on `oceanicvibes` alone.

**Testable:** `plan_shared_runtime_rollout` returns a non-blocked state for the
current fingerprint; every deployed tenant's registry `payloadCore`,
`schemaRevision`, `migrationHead` and `sharedRuntimeFingerprint` equals its
live health values; `validate_queue` accepts the registry.

### Step 2: verify real structure before promotion

Add a structure check to the release gate in
`scripts/deploy-payload-customer.py`, beside `enforce_payload_migrations`.
It reads live DDL through the existing `d1_query` helper and compares it to
the candidate's schema snapshot.

It needs no new primitives: `d1_query(customer, sql, env)` already queries the
registered D1, and every migration ships a full-schema snapshot.

Rules:

- the snapshot is a **floor**: every table and column it declares must exist;
- additionally allow tables the shared chain creates with raw SQL
  (`helloada_growth_candidates`, `helloada_growth_operations`), and provider
  tables (`_cf_KV`, `d1_migrations`);
- fail closed naming the table and column, never a count.

**Testable:** with the revision-14 candidate and a revision-13 database the
check fails and names `media.owner_note`; with a revision-14 database it
passes. Both runnable against the live disposable canary read-only today,
since the canary is at revision 13.

**Definition of done:** the revision-14 candidate cannot be promoted against a
revision-13 database, and the failure names the column.

### Step 3: stop health claiming a schema it has not read

`schemaRevision` in `src/app/api/health/route.ts` is `HELLOADA_SCHEMA_REVISION`,
a package constant, and `check_health` compares it to a registry constant:
the code agreeing with itself. It reported `rev: 14, ok: true` against a
database with no `owner_note`.

Report the applied ledger head read from the tenant's own database instead, or
stop walking the gate on a schema field at all and let step 2 be the only
schema evidence.

**Testable:** a Worker whose ledger is behind its declared chain fails
`check_health`; a live canary cannot report a passing schema while its DDL
lacks a declared column.

**Definition of done:** no health field asserts a schema fact it did not read.

### Step 4: separate additive from destructive, automatically

Classify each pending migration by diffing the previous snapshot against the
new one: additive (new table, new nullable column, new index) versus
destructive (dropped table or column, narrowed type, new required column).

A tenant whose ledger is a clean prefix advances on an additive change with no
human queue edit. Destructive changes keep today's hard stop and today's
explicit `schemaMigration` request naming `fromLedgerIdentity` and
`targetMigrationHead`.

**Testable:** over real migration pairs, `media_owner_note` and
`locale_parent_indexes` classify additive; a synthesised column drop
classifies destructive.

**Definition of done:** an additive platform change needs no queue edit; a
destructive one cannot proceed without the explicit request.

### Step 5: standardise the migration ledger itself

This is the step that removes the legacy weirdness rather than living with it,
and it is only safe because the schemas already agree.

Because every live tenant's **schema** equals the template's (minus the
incident's column), a tenant's divergent ledger can be standardised to the
canonical chain **without touching its data**:

1. prove the tenant's live schema matches the canonical chain's head snapshot
   exactly (allowing the two raw-SQL tables and provider tables);
2. rewrite that tenant's stale `payload_migrations` rows to the canonical
   names, in the canonical order, in one transaction, recording the exact
   before-state first;
3. re-run the structural check to prove nothing changed;
4. only then apply the new additive migration normally.

This is a ledger identity migration, not a data migration. It must be:
scoped to one tenant, explicitly requested, reversible from the recorded
before-state, and proven on the disposable canary first.

**Testable:** on the disposable canary, rewrite the ledger, then confirm
(a) the schema is byte-identical before and after, (b) the applied chain
equals the canonical chain, (c) a subsequent additive release needs no hand
queue edit.

**Definition of done:** every customer tenant reports the canonical migration
chain, with its schema proven unchanged across the rewrite.

### Step 6: retire the non-standard sandboxes

Six registrations are old sandboxes at rev 5-8 and core 0.5.x. They are the
only remaining structural outliers, they serve no owner, and one of them
currently blocks the fleet (step 1).

Decide per tenant: bring to current, or retire. Retire is the standard-default
answer for anything nobody owns. Deleting a registration must not delete
customer data silently, so this is an explicit operator action per tenant with
its own record.

**Testable:** the fleet scan reports zero registered tenants below the current
schema revision, or every exception is explicitly retired and recorded.

**Definition of done:** the registry contains only current, owned tenants.

### Step 7: the notes update, as the acceptance test for the new process

The notes feature is deliberately left broken and becomes the proof that the
process changed. Run the exact revision-14 change through the new path:

- the structure check fails first, clearly, if the column is missing;
- the additive path carries it with no hand-edited tenant repository;
- saving a note works on a customer site afterwards.

**Testable:** on a customer site, save a note through
`/api/helloada/media/note`, reload the gallery, confirm it persists and reads
back as written; and `/api/media` no longer returns the literal `owner_note`.

**Definition of done:** notes work on customers, and arrived without a tenant
repository edit.

## Final testable status

All eight must hold before production is called current and the process is
declared standard. Numbers are the fleet scan and the release planner, not
prose.

1. The fleet scan reports **zero** registered tenants with a missing table or
   column, other than tables the shared chain creates with raw SQL.
2. Every live tenant reports the **canonical** migration chain.
3. `plan_shared_runtime_rollout` returns a non-blocked state.
4. Every deployed tenant's registry identity equals its live health identity.
5. A revision-14 candidate against a revision-13 database fails the gate
   naming `media.owner_note`, before upload.
6. No health field asserts a schema fact it did not read from that tenant's
   database.
7. The disposable canary passes the full path end to end, including the
   ledger standardisation with its schema proven unchanged.
8. On every previously affected customer site, `/api/media` returns a real
   note value or none, never the literal `owner_note`, and a note saves and
   persists.

Items 1, 2, 5 and 6 are about the absence of evidence, because that is where
this incident lived: gates that were green because they could not fail.

## Explicitly not in this plan

- A new deployment framework. One exists, documented in `deploy/README.md`,
  with a canary, bounded batches, per-tenant receipts and a disposable-only
  proof tool. The gap is one input to that machinery.
- A declarative "make the database match the schema" reconcile against live
  customer data. Step 5 standardises the ledger, not the schema, precisely
  because the schemas already agree.
- Rollback. Fan-out is fingerprint-keyed and forward-only
  (`plan_shared_runtime_rollout` skips tenants already at the target), so a
  revert queues nothing for them. Genuine rollback is separate work.
- The maintenance lock and owner warning. Wanted, separate, and only needed
  for destructive changes.

## Sequencing that keeps customers safe

1 → 2 → 3 are control-plane only and can ship without touching a tenant.
4 proves the classifier. 5 is the standardisation, proven on the disposable
canary. 6 cleans the outliers. 7 is the acceptance test on customers.

If only one thing is approved, approve step 2: it is the change that turns
this class of failure from silent into a named, blocking failure.
