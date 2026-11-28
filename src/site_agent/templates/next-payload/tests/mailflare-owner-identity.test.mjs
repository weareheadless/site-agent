import assert from 'node:assert/strict'
import { DatabaseSync } from 'node:sqlite'
import test from 'node:test'

import {
  ensureTenantOwnerIdentity,
  OWNER_ACCOUNT_PASSWORD,
  resolveTenantOwnerUserId,
  SERVICE_ACCOUNT_PASSWORD,
  tenantOwnerUserId,
} from '../mailflare-owner-identity.ts'

/**
 * The Mailflare schema, reduced to the tables this repair touches. A repair that
 * works here works on the real database: the tables and the columns that carry
 * an owner are the contract, not the fixture's shape.
 */
const SCHEMA = `
CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user', is_primary_admin INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0, can_manage_mailboxes INTEGER NOT NULL DEFAULT 0, can_manage_domains INTEGER NOT NULL DEFAULT 0, can_manage_users INTEGER NOT NULL DEFAULT 0, created_by_user_id TEXT REFERENCES users(id), created_at INTEGER NOT NULL);
CREATE TABLE domains (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), hostname TEXT NOT NULL UNIQUE, zone_id TEXT NOT NULL, status TEXT NOT NULL, routing_status TEXT, sending_provider TEXT NOT NULL, receiving_provider TEXT NOT NULL, sending_requested INTEGER NOT NULL, sending_enabled INTEGER NOT NULL, routing_enabled INTEGER NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE mailboxes (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), domain_id TEXT NOT NULL REFERENCES domains(id), local_part TEXT NOT NULL, display_name TEXT, type TEXT NOT NULL, use_all_domains INTEGER NOT NULL, disabled INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, UNIQUE(domain_id, local_part));
CREATE TABLE mailbox_access (id TEXT PRIMARY KEY, mailbox_id TEXT NOT NULL REFERENCES mailboxes(id), user_id TEXT NOT NULL REFERENCES users(id), permission TEXT NOT NULL, created_by_user_id TEXT REFERENCES users(id), created_at INTEGER NOT NULL, UNIQUE(mailbox_id, user_id));
CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), token_hash TEXT NOT NULL UNIQUE, expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE folders (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mailbox_id TEXT NOT NULL, name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '#2563eb', created_at INTEGER NOT NULL, UNIQUE(mailbox_id, name));
CREATE TABLE messages (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mailbox_id TEXT, direction TEXT NOT NULL, folder_id TEXT, from_addr TEXT NOT NULL, to_addr TEXT NOT NULL, subject TEXT, status TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE contacts (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, email TEXT NOT NULL, name TEXT, created_at INTEGER NOT NULL, UNIQUE(user_id, email));
CREATE TABLE booking_events (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, slug TEXT NOT NULL, name TEXT NOT NULL, created_at INTEGER NOT NULL, UNIQUE(user_id, slug));
CREATE TABLE calendar_events (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE agent_conversations (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE helloada_booking_settings (user_id TEXT PRIMARY KEY NOT NULL REFERENCES users(id), enabled INTEGER NOT NULL DEFAULT 0, time_zone TEXT NOT NULL DEFAULT '', weekly_availability TEXT NOT NULL DEFAULT '[]', max_concurrent_appointments INTEGER NOT NULL DEFAULT 1, minimum_notice_hours INTEGER NOT NULL DEFAULT 24, booking_window_days INTEGER NOT NULL DEFAULT 60, revision INTEGER NOT NULL DEFAULT 1, updated_at INTEGER NOT NULL);
CREATE TABLE helloada_tenant_owners (tenant_id TEXT PRIMARY KEY NOT NULL, owner_user_id TEXT NOT NULL UNIQUE REFERENCES users(id), created_at INTEGER NOT NULL);
`

/** node:sqlite returns null-prototype rows; compare plain objects. */
const plain = (rows) => (rows ?? []).map((row) => ({ ...row }))

function database() {
  const sqlite = new DatabaseSync(':memory:')
  sqlite.exec(SCHEMA)
  return {
    sqlite,
    binding: {
      prepare(sql) {
        let parameters = []
        return {
          bind(...values) { parameters = values; return this },
          async first() { return sqlite.prepare(sql).get(...parameters) ?? null },
          async all() { return { results: sqlite.prepare(sql).all(...parameters) } },
          async run() { return sqlite.prepare(sql).run(...parameters) },
        }
      },
    },
  }
}

const sha256 = globalThis.crypto.subtle
const legacyPlatformOwner = async (platformUserId) => {
  const bytes = new Uint8Array(await sha256.digest('SHA-256', new TextEncoder().encode(platformUserId)))
  return `ha_${[...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')}`
}

const TENANT = 'oceanicvibes'

/** A tenant whose mailbox was built under the old, platform-derived identity. */
async function legacyTenant() {
  const { sqlite, binding } = database()
  const legacyOwner = await legacyPlatformOwner('6')
  const foreignOwner = await legacyPlatformOwner('8')

  sqlite.exec(`INSERT INTO users (id, email, password_hash, name, created_at) VALUES
    ('ha_service_legacy', 'svc@identity.helloada.invalid', '${SERVICE_ACCOUNT_PASSWORD}', 'HelloAda mailbox service', 1),
    ('${legacyOwner}', '${legacyOwner}@identity.helloada.invalid', '${OWNER_ACCOUNT_PASSWORD}', 'HelloAda owner', 2),
    ('${foreignOwner}', '${foreignOwner}@identity.helloada.invalid', '${OWNER_ACCOUNT_PASSWORD}', 'HelloAda owner', 3);`)
  sqlite.exec(`INSERT INTO domains VALUES ('ha_domain_x', 'ha_service_legacy', 'oceanicvibes.com', 'zone', 'active', 'ready', 'cloudflare', 'cloudflare', 1, 1, 1, 1);`)
  sqlite.exec(`INSERT INTO mailboxes VALUES ('ha_mailbox_x', 'ha_service_legacy', 'ha_domain_x', 'hello', 'Business inbox', 'shared', 1, 0, 1);`)
  // Two full-access grants, one per platform account that had touched the website.
  sqlite.exec(`INSERT INTO mailbox_access VALUES
    ('acc_1', 'ha_mailbox_x', '${legacyOwner}', 'full_access', 'ha_service_legacy', 1),
    ('acc_2', 'ha_mailbox_x', '${foreignOwner}', 'full_access', 'ha_service_legacy', 2);`)
  sqlite.exec(`INSERT INTO sessions VALUES ('sess_1', '${legacyOwner}', 'hash', 9999999999, 1);`)
  sqlite.exec(`INSERT INTO messages (id, user_id, mailbox_id, direction, from_addr, to_addr, subject, status, created_at) VALUES
    ('msg_1', '${legacyOwner}', 'ha_mailbox_x', 'inbound', 'a@b.c', 'hello@oceanicvibes.com', 'first', 'received', 1),
    ('msg_2', '${legacyOwner}', 'ha_mailbox_x', 'inbound', 'a@b.c', 'hello@oceanicvibes.com', 'second', 'received', 2);`)
  sqlite.exec(`INSERT INTO folders VALUES ('fold_1', '${legacyOwner}', 'ha_mailbox_x', 'Inbox', '#2563eb', 1);`)
  sqlite.exec(`INSERT INTO contacts VALUES ('c_1', '${legacyOwner}', 'client@example.com', 'Client', 1);`)
  sqlite.exec(`INSERT INTO booking_events VALUES ('b_1', '${legacyOwner}', 'makeup', 'Makeup', 1);`)
  sqlite.exec(`INSERT INTO calendar_events VALUES ('cal_1', '${legacyOwner}', 'Booking', 1);`)
  sqlite.exec(`INSERT INTO agent_conversations VALUES ('conv_1', '${legacyOwner}', 1);`)
  sqlite.exec(`INSERT INTO helloada_booking_settings (user_id, updated_at) VALUES ('${legacyOwner}', 1);`)
  sqlite.exec(`INSERT INTO helloada_tenant_owners VALUES ('${TENANT}', '${legacyOwner}', 1);`)
  return { sqlite, binding, legacyOwner, foreignOwner }
}

test('the owner id is derived from the tenant and nothing else', async () => {
  const owner = await tenantOwnerUserId(TENANT)
  assert.match(owner, /^ha_[0-9a-f]{64}$/)
  assert.equal(owner, await tenantOwnerUserId(TENANT), 'the derivation must be stable')
  assert.notEqual(owner, await tenantOwnerUserId('casamigo'))
  // The old derivation, for contrast: this must never be produced again.
  assert.notEqual(owner, await legacyPlatformOwner('6'))
})

test('a legacy registration is repaired onto one tenant-derived owner', async () => {
  const { sqlite, binding, legacyOwner, foreignOwner } = await legacyTenant()
  const canonical = await tenantOwnerUserId(TENANT)

  const state = await ensureTenantOwnerIdentity(binding, TENANT)
  assert.equal(state.ownerUserId, canonical)
  assert.equal(state.changed, true)
  assert.deepEqual([...state.repairedUserIds].sort(), [legacyOwner, foreignOwner].sort())
  // Exactly one account's claim was dropped, not re-pointed: whichever grant was
  // not the registered owner's belonged to another platform account.
  assert.equal(state.revokedAccessUserIds.length, 1)
  assert.ok([legacyOwner, foreignOwner].includes(state.revokedAccessUserIds[0]))

  // One registration, canonical.
  const owners = sqlite.prepare('SELECT tenant_id, owner_user_id FROM helloada_tenant_owners').all()
  assert.deepEqual(plain(owners), [{ tenant_id: TENANT, owner_user_id: canonical }])

  // Exactly one mailbox grant, and a full-access one, on the canonical owner.
  const access = sqlite.prepare('SELECT user_id, permission FROM mailbox_access').all()
  assert.deepEqual(plain(access), [{ user_id: canonical, permission: 'full_access' }])

  // Every owner-scoped row moved, including the ones behind a unique index.
  for (const [table, column] of [
    ['sessions', 'user_id'],
    ['messages', 'user_id'],
    ['folders', 'user_id'],
    ['contacts', 'user_id'],
    ['booking_events', 'user_id'],
    ['calendar_events', 'user_id'],
    ['agent_conversations', 'user_id'],
    ['helloada_booking_settings', 'user_id'],
  ]) {
    const strays = sqlite.prepare(`SELECT COUNT(*) n FROM ${table} WHERE ${column} <> ?`).get(canonical).n
    assert.equal(strays, 0, `${table}.${column} still names a superseded owner`)
    const rows = sqlite.prepare(`SELECT COUNT(*) n FROM ${table}`).get().n
    assert.ok(rows > 0, `${table} lost its rows during the repair`)
  }

  // Disabled, never deleted: the history that names them still resolves.
  for (const id of [legacyOwner, foreignOwner]) {
    const user = sqlite.prepare('SELECT disabled FROM users WHERE id = ?').get(id)
    assert.equal(user.disabled, 1, `${id} must be disabled, not deleted`)
  }
  const canonicalUser = sqlite.prepare('SELECT disabled, password_hash FROM users WHERE id = ?').get(canonical)
  assert.equal(canonicalUser.disabled, 0)
  assert.equal(canonicalUser.password_hash, OWNER_ACCOUNT_PASSWORD)
})

test('a repair is idempotent and reports no work on the second run', async () => {
  const { sqlite, binding } = await legacyTenant()
  const first = await ensureTenantOwnerIdentity(binding, TENANT)
  assert.equal(first.changed, true)
  const snapshot = plain(sqlite.prepare('SELECT * FROM mailbox_access ORDER BY id').all())

  const second = await ensureTenantOwnerIdentity(binding, TENANT)
  assert.equal(second.changed, false)
  assert.deepEqual(second.repairedUserIds, [])
  assert.deepEqual(second.revokedAccessUserIds, [])
  assert.deepEqual(plain(sqlite.prepare('SELECT * FROM mailbox_access ORDER BY id').all()), plain(snapshot))
})

test('an already-canonical tenant is left untouched', async () => {
  const { sqlite, binding } = database()
  const canonical = await tenantOwnerUserId('casamigo')
  sqlite.exec(`INSERT INTO users (id, email, password_hash, name, created_at) VALUES
    ('${canonical}', '${canonical}@identity.helloada.invalid', '${OWNER_ACCOUNT_PASSWORD}', 'HelloAda owner', 1);`)
  sqlite.exec(`INSERT INTO helloada_tenant_owners VALUES ('casamigo', '${canonical}', 1);`)

  const state = await ensureTenantOwnerIdentity(binding, 'casamigo')
  assert.equal(state.changed, false)
  assert.equal(state.ownerUserId, canonical)
})

test('a tenant that never registered gets one derived owner', async () => {
  const { sqlite, binding } = database()
  const state = await ensureTenantOwnerIdentity(binding, 'atelier-harmonie')
  assert.equal(state.changed, true)
  assert.equal(state.ownerUserId, await tenantOwnerUserId('atelier-harmonie'))
  const owners = sqlite.prepare('SELECT owner_user_id FROM helloada_tenant_owners').all()
  assert.deepEqual(plain(owners), [{ owner_user_id: state.ownerUserId }])
  const users = sqlite.prepare('SELECT id, disabled FROM users').all()
  assert.deepEqual(plain(users), [{ id: state.ownerUserId, disabled: 0 }])
})

test('the gate entry point refuses rather than trusting an unrepairable row', async () => {
  const { sqlite, binding } = database()
  const canonical = await tenantOwnerUserId('broken')
  // A registered owner that cannot be used: disabled. The repair must not
  // quietly pick a different identity, and the resolver must not return it.
  sqlite.exec(`INSERT INTO users (id, email, password_hash, name, disabled, created_at) VALUES
    ('${canonical}', '${canonical}@identity.helloada.invalid', '${OWNER_ACCOUNT_PASSWORD}', 'HelloAda owner', 1, 1);`)
  sqlite.exec(`INSERT INTO helloada_tenant_owners VALUES ('broken', '${canonical}', 1);`)
  await assert.rejects(() => resolveTenantOwnerUserId(binding, 'broken'), /mailbox_owner_identity_invalid/)
})

test('a tenant identity that is not a tenant id is refused', async () => {
  const { binding } = database()
  for (const bad of ['', '  ', 'Oceanic Vibes', '../etc', 'a'.repeat(64)]) {
    await assert.rejects(
      () => ensureTenantOwnerIdentity(binding, bad),
      /tenant_identity_not_configured/,
      `accepted ${JSON.stringify(bad)}`,
    )
  }
})

test('the gate no longer prefers a stored owner over the tenant', async () => {
  const { readFileSync } = await import('node:fs')
  const gate = readFileSync(new URL('../mailflare-owner-gate.ts', import.meta.url), 'utf8')
  // The removed shape: "use whatever row is stored, else derive".
  assert.doesNotMatch(gate, /registeredOwner\s*\n?\s*\?\s*registeredOwner\.owner_user_id/)
  // The gate may register and verify the owner, but it may not *decide* one by
  // reading the row as its primary value; that derivation belongs to one module.
  assert.doesNotMatch(gate, /const userId = registeredOwner/)
  assert.match(gate, /resolveTenantOwnerUserId/)
  // The failure shape is named by the module that owns the derivation.
  const identity = readFileSync(new URL('../mailflare-owner-identity.ts', import.meta.url), 'utf8')
  assert.match(identity, /mailbox_owner_identity_invalid/)

  const booking = readFileSync(new URL('../mailflare-booking-service.ts', import.meta.url), 'utf8')
  assert.match(booking, /resolveTenantOwnerUserId/)
  // The booking path may not read the registration row directly: one derivation.
  assert.doesNotMatch(booking, /SELECT owner_user_id FROM helloada_tenant_owners/)
})
