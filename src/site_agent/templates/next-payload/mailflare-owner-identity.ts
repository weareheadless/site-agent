/**
 * One tenant has one mailbox owner, and that owner is derived from the tenant.
 *
 * The first HelloAda tenants were built when a mailbox owner came from the
 * platform account that opened the website: `ha_<sha256(payloadUserId)>`. A
 * platform account can own several websites, so that identity is not exclusive
 * to a tenant — and the gate then preferred whatever row it found, which let a
 * single mailbox carry two owners with full access (one per platform account
 * that had ever touched it) and let every other tenant-scoped row drift onto a
 * shared identity.
 *
 * This module repairs that in place and is the only place that decides what a
 * tenant's owner is:
 *
 *   canonical = "ha_" + sha256("tenant:" + tenantId)
 *
 * Repair rules, in order:
 *   - no registered owner: register the canonical one;
 *   - registered owner is already canonical: nothing to do (the common case);
 *   - registered owner differs: every row that belongs to a non-service account
 *     is re-pointed to the canonical user, foreign mailbox grants are dropped,
 *     the superseded accounts are disabled (never deleted, so an audit trail
 *     survives), and the registration row is compare-and-swap updated.
 *
 * The single-owner gate makes the legacy accounts historical artifacts of the
 * same owner seat, so re-pointing their rows cannot merge two people's data.
 * There is no second human in these databases to preserve: an account that is
 * neither the owner nor the tenant service account only exists because the
 * owner identity used to be derived from something else.
 *
 * Every step is idempotent and verifies its postcondition. A run that cannot
 * finish leaves the tenant repairable by the next one rather than half-migrated;
 * the gate only accepts a canonical registration, so a partial state is visible
 * as a named failure, never as a silently preferred identity.
 */

type D1Statement = {
  bind: (...values: unknown[]) => D1Statement
  first: <T = Record<string, unknown>>() => Promise<T | null>
  all: <T = Record<string, unknown>>() => Promise<{ results?: T[] }>
  run: () => Promise<{ meta?: { changes?: number } } | unknown>
}

export type OwnerIdentityD1 = { prepare: (query: string) => D1Statement }

const digest = async (value: string) => {
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))
  return [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

/** The only derivation of a tenant's mailbox owner. */
export const tenantOwnerUserId = async (tenantId: string) => `ha_${await digest(`tenant:${tenantId}`)}`

export const SERVICE_ACCOUNT_PASSWORD = '!helloada-service-account-disabled'
export const OWNER_ACCOUNT_PASSWORD = '!helloada-payload-sso-only'

const nowSeconds = () => Math.floor(Date.now() / 1000)

/**
 * Every table that carries a person's identity.
 *
 * Generated from `packages/helloada-mailflare/upstream/src/db/schema/index.ts`:
 * each `user_id` / `created_by_user_id` / `actor_user_id` / `target_user_id` /
 * `reviewer_user_id` column in the Mailflare schema. A table that is absent is
 * skipped, so a database older than a given migration still repairs; a table
 * that exists and cannot be re-pointed is a hard failure.
 */
const OWNER_IDENTITY_COLUMNS: ReadonlyArray<readonly [table: string, column: string]> = [
  ['users', 'created_by_user_id'],
  ['domains', 'user_id'],
  ['mailboxes', 'user_id'],
  ['mailbox_access', 'user_id'],
  ['mailbox_access', 'created_by_user_id'],
  ['contacts', 'user_id'],
  ['folders', 'user_id'],
  ['api_keys', 'user_id'],
  ['messages', 'user_id'],
  ['spam_feedback', 'actor_user_id'],
  ['outbound_jobs', 'user_id'],
  ['email_templates', 'user_id'],
  ['calendar_events', 'user_id'],
  ['booking_events', 'user_id'],
  ['routing_rules', 'user_id'],
  ['webhooks', 'user_id'],
  ['sessions', 'user_id'],
  ['push_subscriptions', 'user_id'],
  ['password_reset_tokens', 'user_id'],
  ['mfa_recovery_codes', 'user_id'],
  ['login_challenges', 'user_id'],
  ['audit_logs', 'actor_user_id'],
  ['audit_logs', 'target_user_id'],
  ['backups', 'created_by_user_id'],
  ['mailbox_agent_settings', 'reviewer_user_id'],
  ['agent_conversations', 'user_id'],
  ['agent_jobs', 'reviewer_user_id'],
  ['agent_send_approvals', 'user_id'],
  ['drive_shares', 'user_id'],
  ['helloada_booking_settings', 'user_id'],
]

export type OwnerIdentityState = {
  tenantId: string
  ownerUserId: string
  changed: boolean
  /** Accounts that were re-pointed and disabled by this run. */
  repairedUserIds: string[]
  /** Grants removed because they belonged to neither the owner nor the service account. */
  revokedAccessUserIds: string[]
}

async function tableExists(database: OwnerIdentityD1, table: string): Promise<boolean> {
  const row = await database
    .prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1")
    .bind(table)
    .first<{ name: string }>()
  return Boolean(row?.name)
}

/**
 * A table can exist at an older schema revision without the column this repair
 * needs. That is not a failure: the row it would have moved does not exist yet.
 */
async function columnExists(database: OwnerIdentityD1, table: string, column: string): Promise<boolean> {
  const row = await database
    .prepare(`SELECT name FROM pragma_table_info(?) WHERE name = ? LIMIT 1`)
    .bind(table, column)
    .first<{ name: string }>()
  return Boolean(row?.name)
}

async function readRegistration(database: OwnerIdentityD1, tenantId: string) {
  return database
    .prepare('SELECT owner_user_id FROM helloada_tenant_owners WHERE tenant_id = ? LIMIT 1')
    .bind(tenantId)
    .first<{ owner_user_id: string }>()
}

async function serviceUserIds(database: OwnerIdentityD1, tenantId: string): Promise<string[]> {
  const service = `ha_service_${(await digest(tenantId)).slice(0, 32)}`
  const rows = await database
    .prepare('SELECT id FROM users WHERE id = ? OR password_hash = ?')
    .bind(service, SERVICE_ACCOUNT_PASSWORD)
    .all<{ id: string }>()
  return (rows.results ?? []).map((row) => row.id)
}

/** Every account in this database that is not the owner seat or the tenant's service account. */
async function supersededUserIds(
  database: OwnerIdentityD1,
  tenantId: string,
  ownerUserId: string,
): Promise<string[]> {
  const exempt = new Set([ownerUserId, ...(await serviceUserIds(database, tenantId))])
  const rows = await database.prepare('SELECT id FROM users').all<{ id: string }>()
  return (rows.results ?? []).map((row) => row.id).filter((id) => !exempt.has(id))
}

/**
 * Create the canonical owner account if it is missing. Mirrors the account the
 * owner gate provisions: an SSO-only identity that cannot be logged into with a
 * password, because Payload is what authenticates the person.
 */
async function ensureOwnerAccount(database: OwnerIdentityD1, ownerUserId: string) {
  const existing = await database
    .prepare('SELECT id, disabled FROM users WHERE id = ? LIMIT 1')
    .bind(ownerUserId)
    .first<{ id: string; disabled: number }>()
  if (existing?.disabled) throw new Error('mailbox_owner_identity_invalid')
  if (!existing) {
    await database
      .prepare(
        'INSERT OR IGNORE INTO users (id, email, password_hash, name, role, is_primary_admin, can_manage_mailboxes, can_manage_domains, can_manage_users, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
      )
      .bind(
        ownerUserId,
        `${ownerUserId}@identity.helloada.invalid`,
        OWNER_ACCOUNT_PASSWORD,
        'HelloAda owner',
        'user',
        0,
        0,
        0,
        0,
        nowSeconds(),
      )
      .run()
  }
  await database
    .prepare('UPDATE users SET name = ?, disabled = 0 WHERE id = ?')
    .bind('HelloAda owner', ownerUserId)
    .run()
  const confirmed = await database
    .prepare('SELECT id FROM users WHERE id = ? AND disabled = 0 LIMIT 1')
    .bind(ownerUserId)
    .first<{ id: string }>()
  if (confirmed?.id !== ownerUserId) throw new Error('mailbox_owner_identity_invalid')
}

/**
 * Move one table's owner column from the superseded accounts to the canonical
 * owner. `UPDATE OR REPLACE` resolves the schema's composite unique indexes
 * (a contact's email, a booking slug, a mailbox grant) by letting the owner's
 * row win instead of aborting the repair.
 */
async function repointTable(
  database: OwnerIdentityD1,
  table: string,
  column: string,
  superseded: string[],
  ownerUserId: string,
) {
  if (!superseded.length) return
  if (!(await tableExists(database, table))) return
  if (!(await columnExists(database, table, column))) return
  const placeholders = superseded.map(() => '?').join(', ')
  await database
    .prepare(`UPDATE OR REPLACE ${table} SET ${column} = ? WHERE ${column} IN (${placeholders})`)
    .bind(ownerUserId, ...superseded)
    .run()
}

/**
 * A grant that names an account which is neither the owner nor the service
 * account is not this mailbox's access; it is the residue of the shared
 * identity. It is removed rather than re-pointed, because re-pointing would
 * hand that account's claim to the owner.
 */
async function revokeForeignAccess(
  database: OwnerIdentityD1,
  tenantId: string,
  ownerUserId: string,
): Promise<string[]> {
  if (!(await tableExists(database, 'mailbox_access'))) return []
  const exempt = new Set([ownerUserId, ...(await serviceUserIds(database, tenantId))])
  const rows = await database
    .prepare('SELECT DISTINCT user_id FROM mailbox_access')
    .all<{ user_id: string }>()
  const foreign = (rows.results ?? [])
    .map((row) => row.user_id)
    .filter((id) => id && !exempt.has(id))
  for (const userId of foreign) {
    await database.prepare('DELETE FROM mailbox_access WHERE user_id = ?').bind(userId).run()
  }
  return foreign
}

/**
 * Resolve this tenant's mailbox owner, repairing a registration that was built
 * on a shared identity. Callers must use the returned id and nothing else: a
 * stored row is an assertion to verify, not a value to trust.
 *
 * Order matters. The registered owner's own rows move first, so the seat keeps
 * its mailbox access and history. Only then are grants that still name some
 * third account dropped: after the move they are exactly the claims this
 * mailbox never had.
 */
export async function ensureTenantOwnerIdentity(
  database: OwnerIdentityD1,
  tenantId: string,
): Promise<OwnerIdentityState> {
  const tenant = tenantId.trim()
  if (!/^[a-z0-9-]{1,63}$/.test(tenant)) throw new Error('tenant_identity_not_configured')
  const ownerUserId = await tenantOwnerUserId(tenant)
  const registered = await readRegistration(database, tenant)

  if (registered && registered.owner_user_id === ownerUserId) {
    // The common case after the fleet has converged. Still confirm the account
    // exists and is usable, because the row alone is not proof.
    await ensureOwnerAccount(database, ownerUserId)
    return { tenantId: tenant, ownerUserId, changed: false, repairedUserIds: [], revokedAccessUserIds: [] }
  }

  await ensureOwnerAccount(database, ownerUserId)

  // 1. The owner seat's own rows move to the canonical id.
  const seat = registered ? [registered.owner_user_id] : []
  for (const [table, column] of OWNER_IDENTITY_COLUMNS) {
    await repointTable(database, table, column, seat, ownerUserId)
  }

  // 2. With the seat moved, any remaining account in this database was never
  //    the owner: its mailbox claim is not this mailbox's access.
  const revokedAccessUserIds = await revokeForeignAccess(database, tenant, ownerUserId)
  const superseded = await supersededUserIds(database, tenant, ownerUserId)
  for (const [table, column] of OWNER_IDENTITY_COLUMNS) {
    if (table === 'mailbox_access') continue
    await repointTable(database, table, column, superseded, ownerUserId)
  }

  const now = nowSeconds()
  if (registered) {
    // Compare-and-swap: only the exact legacy value this run read may be
    // replaced, so a concurrent repair cannot be overwritten by a stale one.
    await database
      .prepare(
        'UPDATE helloada_tenant_owners SET owner_user_id = ? WHERE tenant_id = ? AND owner_user_id = ?',
      )
      .bind(ownerUserId, tenant, registered.owner_user_id)
      .run()
  } else {
    await database
      .prepare('INSERT OR IGNORE INTO helloada_tenant_owners (tenant_id, owner_user_id, created_at) VALUES (?, ?, ?)')
      .bind(tenant, ownerUserId, now)
      .run()
  }

  for (const userId of superseded) {
    // Disabled, never deleted: sessions and audit rows still name it.
    await database.prepare('UPDATE users SET disabled = 1 WHERE id = ?').bind(userId).run()
  }

  const confirmed = await readRegistration(database, tenant)
  if (confirmed?.owner_user_id !== ownerUserId) throw new Error('mailbox_owner_identity_invalid')
  return { tenantId: tenant, ownerUserId, changed: true, repairedUserIds: superseded, revokedAccessUserIds }
}

/**
 * The owner id a gate or booking path may use. Throws rather than falling back:
 * a mailbox whose owner cannot be proven is not a mailbox this code may serve.
 */
export async function resolveTenantOwnerUserId(database: OwnerIdentityD1, tenantId: string): Promise<string> {
  const state = await ensureTenantOwnerIdentity(database, tenantId)
  return state.ownerUserId
}
