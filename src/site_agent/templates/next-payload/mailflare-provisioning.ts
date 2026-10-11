type D1Statement = {
  bind: (...values: unknown[]) => D1Statement
  first: <T = Record<string, unknown>>() => Promise<T | null>
  all: <T = Record<string, unknown>>() => Promise<{ results?: T[] }>
  run: () => Promise<unknown>
}

export type MailflareD1 = { prepare: (query: string) => D1Statement }

const sha256 = async (value: string) => {
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))
  return [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

const insertId = async (prefix: string, value: string) => `${prefix}_${(await sha256(value)).slice(0, 32)}`

export async function provisionTenantMailflareMailbox({
  database,
  tenantId,
  address,
  zoneId,
  routingStatus,
}: {
  database: MailflareD1
  tenantId: string
  address: string
  zoneId: string
  routingStatus: string
}) {
  const normalizedAddress = address.trim().toLowerCase()
  const separator = normalizedAddress.lastIndexOf('@')
  const localPart = normalizedAddress.slice(0, separator)
  const hostname = normalizedAddress.slice(separator + 1)
  if (!/^[a-z0-9][a-z0-9._+-]{0,63}$/.test(localPart)
    || !/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(hostname)
    || !zoneId.trim()
    || !/^[a-z0-9-]{1,63}$/.test(tenantId)
    || !routingStatus.trim()) {
    throw new Error('The Mailflare tenant mailbox configuration is invalid')
  }

  const serviceUserId = await insertId('ha_service', tenantId)
  const domainId = await insertId('ha_domain', hostname)
  const mailboxId = await insertId('ha_mailbox', normalizedAddress)
  const now = Date.now()
  const serviceEmail = `${serviceUserId}@identity.helloada.invalid`
  const existingService = await database.prepare(
    'SELECT id, email, disabled FROM users WHERE id = ? LIMIT 1',
  ).bind(serviceUserId).first<{ id: string; email: string; disabled: number }>()
  if (!existingService) {
    const existingUser = await database.prepare('SELECT id FROM users LIMIT 1').first<{ id: string }>()
    if (existingUser) throw new Error('Mailflare contains an unlinked account; explicit mailbox migration is required')
    await database.prepare(
      'INSERT INTO users (id, email, password_hash, name, role, is_primary_admin, can_manage_mailboxes, can_manage_domains, can_manage_users, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
    ).bind(serviceUserId, serviceEmail, '!helloada-service-account-disabled', 'HelloAda mailbox service', 'user', 0, 0, 0, 0, now).run()
  } else if (existingService.email !== serviceEmail || existingService.disabled) {
    throw new Error('Mailflare service account does not match the tenant identity')
  }

  const existingDomain = await database.prepare(
    'SELECT id, user_id FROM domains WHERE hostname = ? LIMIT 1',
  ).bind(hostname).first<{ id: string; user_id: string }>()
  if (existingDomain && (existingDomain.id !== domainId || existingDomain.user_id !== serviceUserId)) {
    throw new Error('Mailflare domain is already owned by a different account')
  }
  await database.prepare(
    'INSERT OR IGNORE INTO domains (id, user_id, hostname, zone_id, status, routing_status, sending_provider, receiving_provider, sending_requested, sending_enabled, routing_enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind(domainId, serviceUserId, hostname, zoneId, 'active', routingStatus, 'resend', 'cloudflare', 1, 1, 1, now).run()
  await database.prepare(
    'UPDATE domains SET zone_id = ?, status = ?, routing_status = ?, sending_provider = ?, receiving_provider = ?, sending_requested = 1, sending_enabled = 1, routing_enabled = 1 WHERE id = ? AND user_id = ?',
  ).bind(zoneId, 'active', routingStatus, 'resend', 'cloudflare', domainId, serviceUserId).run()

  const existingMailbox = await database.prepare(
    'SELECT id, user_id, domain_id, local_part FROM mailboxes WHERE domain_id = ? AND local_part = ? LIMIT 1',
  ).bind(domainId, localPart).first<{ id: string; user_id: string; domain_id: string; local_part: string }>()
  if (existingMailbox && (existingMailbox.id !== mailboxId || existingMailbox.user_id !== serviceUserId)) {
    throw new Error('Mailflare mailbox is already owned by a different account')
  }
  await database.prepare(
    'INSERT OR IGNORE INTO mailboxes (id, user_id, domain_id, local_part, display_name, type, use_all_domains, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind(mailboxId, serviceUserId, domainId, localPart, 'Business inbox', 'shared', 1, now).run()
  await database.prepare(
    'UPDATE mailboxes SET display_name = ?, type = ?, use_all_domains = 1, disabled = 0 WHERE id = ? AND user_id = ? AND domain_id = ? AND local_part = ?',
  ).bind('Business inbox', 'shared', mailboxId, serviceUserId, domainId, localPart).run()

  const [domain, mailbox] = await Promise.all([
    database.prepare('SELECT id, user_id, status, zone_id FROM domains WHERE id = ? LIMIT 1')
      .bind(domainId).first<{ id: string; user_id: string; status: string; zone_id: string }>(),
    database.prepare('SELECT id, user_id, domain_id, local_part, disabled FROM mailboxes WHERE id = ? LIMIT 1')
      .bind(mailboxId).first<{ id: string; user_id: string; domain_id: string; local_part: string; disabled: number }>(),
  ])
  if (domain?.user_id !== serviceUserId || domain.status !== 'active' || domain.zone_id !== zoneId
    || mailbox?.user_id !== serviceUserId || mailbox.domain_id !== domainId
    || mailbox.local_part !== localPart || mailbox.disabled) {
    throw new Error('Mailflare did not confirm the exact tenant mailbox configuration')
  }
  return { address: normalizedAddress, domain: hostname, domainId, mailboxId, serviceUserId }
}
