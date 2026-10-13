type Row = Record<string, unknown>
type D1Result<T> = { results?: T[] }
type D1Statement = {
  bind: (...values: unknown[]) => D1Statement
  first: <T = Row>() => Promise<T | null>
  all: <T = Row>() => Promise<D1Result<T>>
  run: () => Promise<unknown>
}
type Database = { prepare: (sql: string) => D1Statement }
type StoredObject = {
  arrayBuffer: () => Promise<ArrayBuffer>
  httpMetadata?: { contentType?: string }
  customMetadata?: Record<string, string>
}
type Bucket = {
  get: (key: string) => Promise<StoredObject | null>
  put: (key: string, value: ArrayBuffer, options: {
    httpMetadata: { contentType: string }
    customMetadata: Record<string, string>
  }) => Promise<unknown>
}

export type PayloadMailboxMigrationEnv = {
  D1: Database
  MAILFLARE_DB: Database
  PRIVATE_EMAIL: Bucket
  MAILFLARE_BUCKET: Bucket
  HELLOADA_TENANT_ID: string
  MAILFLARE_ADDRESS: string
}

const VERSION = 'payload-mailbox-v2'
const PAGE_SIZE = 100
const MAX_ROWS_PER_TABLE = 20_000
const REQUIRED_TABLES = [
  'contacts', 'conversations', 'messages', 'message_operations',
  'appointment_types', 'appointment_types_locales', 'appointment_types_weekly_availability',
  'calendar_events', 'calendar_settings',
] as const

const asString = (value: unknown) => typeof value === 'string' ? value.trim() : value == null ? '' : String(value)
const column = (row: Row, ...names: string[]) => {
  for (const name of names) if (row[name] !== undefined) return row[name]
  return undefined
}
const jsonValue = (value: unknown, label: string): unknown => {
  if (value == null || value === '') return null
  if (typeof value !== 'string') return value
  try { return JSON.parse(value) as unknown } catch { throw new Error('payload_migration_invalid_json:' + label) }
}
const jsonText = (value: unknown, label: string) => {
  const parsed = jsonValue(value, label)
  return parsed == null ? null : JSON.stringify(parsed)
}
const epochSeconds = (value: unknown, label: string): number => {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.floor(value > 10_000_000_000 ? value / 1000 : value)
  const parsed = Date.parse(asString(value))
  if (!Number.isFinite(parsed)) throw new Error('payload_migration_invalid_timestamp:' + label)
  return Math.floor(parsed / 1000)
}
const epochMilliseconds = (value: unknown, label: string) => epochSeconds(value, label) * 1000
const canonical = (row: Row) => JSON.stringify(Object.fromEntries(Object.entries(row).sort(([a], [b]) => a.localeCompare(b))))
const sha256 = async (value: string | ArrayBuffer) => {
  const bytes = typeof value === 'string' ? new TextEncoder().encode(value) : value
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))
  return [...digest].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}
const recordId = async (tenant: string, collection: string, sourceId: string) =>
  'ha_' + collection + '_' + (await sha256(tenant + ':' + collection + ':' + sourceId)).slice(0, 24)
const addressList = (value: unknown, label: string) => {
  const parsed = jsonValue(value, label)
  if (parsed == null) return ''
  if (Array.isArray(parsed)) return parsed.map(asString).filter(Boolean).join(', ')
  return asString(parsed)
}
const messageStatus = (delivery: string, conversationState: string, direction: string) => {
  if (direction === 'inbound' && conversationState === 'done') return 'archived'
  if (direction === 'inbound' && ['spam', 'trash', 'archived'].includes(conversationState)) return conversationState
  if (delivery === 'draft') return 'draft'
  if (delivery === 'accepted') return 'sent'
  if (delivery === 'received') return 'received'
  if (delivery === 'failed') return 'failed'
  if (['queued', 'sending', 'uncertain'].includes(delivery)) return 'failed'
  throw new Error('payload_migration_unknown_delivery_state')
}

async function readTable(database: Database, table: string): Promise<Row[]> {
  const exists = await database.prepare(
    'SELECT name FROM sqlite_master WHERE type = ? AND name = ? LIMIT 1',
  ).bind('table', table).first<{ name: string }>()
  if (!exists) throw new Error('payload_migration_source_table_missing:' + table)
  const rows: Row[] = []
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const page = await database.prepare(
      'SELECT * FROM "' + table + '" ORDER BY id LIMIT ? OFFSET ?',
    ).bind(PAGE_SIZE, offset).all<Row>()
    const values = page.results ?? []
    rows.push(...values)
    if (rows.length > MAX_ROWS_PER_TABLE) throw new Error('payload_migration_table_limit_exceeded:' + table)
    if (values.length < PAGE_SIZE) return rows
  }
}

const insertRecord = async (db: Database, sourceCollection: string, sourceId: string, sourceSha: string, targetCollection: string, targetId: string) => {
  await db.prepare(
    'INSERT OR IGNORE INTO helloada_import_records (source_collection, source_id, source_sha256, target_collection, target_id, migrated_at) VALUES (?, ?, ?, ?, ?, ?)',
  ).bind(sourceCollection, sourceId, sourceSha, targetCollection, targetId, Date.now()).run()
  const stored = await db.prepare(
    'SELECT source_sha256, target_collection, target_id FROM helloada_import_records WHERE source_collection = ? AND source_id = ? LIMIT 1',
  ).bind(sourceCollection, sourceId).first<{ source_sha256: string; target_collection: string; target_id: string }>()
  if (stored?.source_sha256 !== sourceSha || stored.target_collection !== targetCollection || stored.target_id !== targetId) {
    throw new Error('payload_migration_record_conflict')
  }
}

async function copyObject(source: Bucket, destination: Bucket, sourceKey: string, destinationKey: string, tenant: string, expectedSha?: string, expectedSize?: number) {
  const sourceObject = await source.get(sourceKey)
  if (!sourceObject) throw new Error('payload_migration_object_missing')
  const bytes = await sourceObject.arrayBuffer()
  if (bytes.byteLength > 25 * 1024 * 1024) throw new Error('payload_migration_object_too_large')
  const actualSha = await sha256(bytes)
  if ((expectedSha && actualSha !== expectedSha) || (expectedSize !== undefined && bytes.byteLength !== expectedSize)) {
    throw new Error('payload_migration_object_integrity_failed')
  }
  const existing = await destination.get(destinationKey)
  if (existing) {
    const existingBytes = await existing.arrayBuffer()
    if (await sha256(existingBytes) !== actualSha) throw new Error('payload_migration_destination_object_conflict')
    return { size: bytes.byteLength, sha256: actualSha }
  }
  await destination.put(destinationKey, bytes, {
    httpMetadata: { contentType: sourceObject.httpMetadata?.contentType || 'application/octet-stream' },
    customMetadata: { tenant, source: 'payload-mailbox-migration', sha256: actualSha },
  })
  return { size: bytes.byteLength, sha256: actualSha }
}

function bookingSchedule(availability: Row[], appointmentId: string) {
  const days = new Map<number, Array<{ startTime: string; endTime: string }>>()
  const dayNumber: Record<string, number> = { sunday: 0, monday: 1, tuesday: 2, wednesday: 3, thursday: 4, friday: 5, saturday: 6 }
  for (const row of availability.filter((item) => asString(column(item, '_parent_id', 'parent_id')) === appointmentId)) {
    const day = dayNumber[asString(row.day).toLowerCase()]
    const startTime = asString(column(row, 'start_time', 'startTime'))
    const endTime = asString(column(row, 'end_time', 'endTime'))
    if (day === undefined || !/^([01]\d|2[0-3]):[0-5]\d$/.test(startTime) || !/^([01]\d|2[0-3]):[0-5]\d$/.test(endTime) || startTime >= endTime || (Number(startTime.slice(0, 2)) * 60 + Number(startTime.slice(3))) % 15 !== 0 || (Number(endTime.slice(0, 2)) * 60 + Number(endTime.slice(3))) % 15 !== 0) {
      throw new Error('payload_migration_booking_schedule_invalid')
    }
    const periods = days.get(day) ?? []
    periods.push({ startTime, endTime })
    days.set(day, periods)
  }
  if (days.size === 0) throw new Error('payload_migration_booking_schedule_empty')
  const ranges = new Map<string, { startTime: string; endTime: string }>()
  for (const periods of days.values()) {
    periods.sort((a, b) => a.startTime.localeCompare(b.startTime))
    if (periods.some((period, index) => index > 0 && period.startTime < periods[index - 1].endTime)) {
      throw new Error('payload_migration_booking_schedule_overlap')
    }
    for (const period of periods) ranges.set(JSON.stringify(period), period)
  }
  const weekdays = [...days.keys()].sort((a, b) => a - b)
  const timeRanges = [...ranges.values()].sort((a, b) => a.startTime.localeCompare(b.startTime) || a.endTime.localeCompare(b.endTime))
  const weeklyAvailability = [...days.entries()].sort(([a], [b]) => a - b)
    .flatMap(([day, periods]) => periods.map((period) => ({ day, ...period })))
  return { timeRanges, weekdays, weeklyAvailability: JSON.stringify(weeklyAvailability) }
}

function recipientAddress(row: Row, name: string, fallback: string) {
  const value = asString(column(row, name, name.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase())))
  const address = value || fallback
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) throw new Error('payload_migration_message_address_invalid')
  return address.toLowerCase()
}

export async function migratePayloadMailbox(
  env: PayloadMailboxMigrationEnv,
  identity: { ownerUserId: string; serviceUserId: string; mailboxId: string; defaultLocale: string },
): Promise<{ state: 'complete'; counts: Record<string, number>; sourceSha256: string }> {
  const existing = await env.MAILFLARE_DB.prepare(
    'SELECT state, source_sha256, counts_json FROM helloada_import_runs WHERE tenant_id = ? AND version = ? LIMIT 1',
  ).bind(env.HELLOADA_TENANT_ID, VERSION).first<{ state: string; source_sha256: string | null; counts_json: string | null }>()
  if (existing?.state === 'complete') {
    return {
      state: 'complete',
      counts: JSON.parse(existing.counts_json || '{}') as Record<string, number>,
      sourceSha256: existing.source_sha256 || '',
    }
  }

  const leaseToken = crypto.randomUUID()
  const now = Date.now()
  const nowSeconds = Math.floor(now / 1000)
  await env.MAILFLARE_DB.prepare(
    'INSERT OR IGNORE INTO helloada_import_runs (tenant_id, version, state, started_at) VALUES (?, ?, ?, ?)',
  ).bind(env.HELLOADA_TENANT_ID, VERSION, 'failed', now).run()
  await env.MAILFLARE_DB.prepare(
    "UPDATE helloada_import_runs SET state = 'running', lease_token = ?, lease_until = ?, started_at = ?, error_code = NULL WHERE tenant_id = ? AND version = ? AND state != 'complete' AND (state != 'running' OR lease_until < ?)",
  ).bind(leaseToken, now + 5 * 60_000, now, env.HELLOADA_TENANT_ID, VERSION, now).run()
  const lease = await env.MAILFLARE_DB.prepare(
    'SELECT state, lease_token FROM helloada_import_runs WHERE tenant_id = ? AND version = ? LIMIT 1',
  ).bind(env.HELLOADA_TENANT_ID, VERSION).first<{ state: string; lease_token: string | null }>()
  if (lease?.state === 'complete') return { state: 'complete', counts: {}, sourceSha256: '' }
  if (lease?.lease_token !== leaseToken) throw new Error('payload_migration_already_running')

  const counts: Record<string, number> = {}
  const sourceDigests: string[] = []
  try {
    for (const table of REQUIRED_TABLES) {
      const rows = await readTable(env.D1, table)
      counts[table] = rows.length
      for (const row of rows) sourceDigests.push(table + ':' + asString(row.id) + ':' + await sha256(canonical(row)))
    }

    const contacts = await readTable(env.D1, 'contacts')
    const conversations = await readTable(env.D1, 'conversations')
    const messages = await readTable(env.D1, 'messages')
    const operations = await readTable(env.D1, 'message_operations')
    const appointmentTypes = await readTable(env.D1, 'appointment_types')
    const locales = await readTable(env.D1, 'appointment_types_locales')
    const availability = await readTable(env.D1, 'appointment_types_weekly_availability')
    const calendarEvents = await readTable(env.D1, 'calendar_events')
    const calendarSettings = await readTable(env.D1, 'calendar_settings')
    if (calendarSettings.length > 1) throw new Error('payload_migration_calendar_settings_cardinality_invalid')
    const settings = calendarSettings[0] ?? {}
    const timeZone = asString(column(settings, 'time_zone', 'timeZone'))
    const calendarEnabled = Number(settings.enabled ?? 0)
    const minimumNoticeHours = Number(column(settings, 'minimum_notice_hours', 'minimumNoticeHours') ?? 24)
    const bookingWindowDays = Number(column(settings, 'booking_window_days', 'bookingWindowDays') ?? 60)
    if ((appointmentTypes.length > 0 || calendarEvents.length > 0) && (calendarSettings.length !== 1 || !timeZone)) throw new Error('payload_migration_calendar_timezone_missing')
    if (![0, 1].includes(calendarEnabled)
      || !Number.isInteger(minimumNoticeHours) || minimumNoticeHours < 0 || minimumNoticeHours > 8760
      || !Number.isInteger(bookingWindowDays) || bookingWindowDays < 1 || bookingWindowDays > 365) {
      throw new Error('payload_migration_calendar_settings_invalid')
    }

    const contactsById = new Map(contacts.map((row) => [asString(row.id), row]))
    const conversationsById = new Map(conversations.map((row) => [asString(row.id), row]))
    const mailflareContactIds = new Map<string, string>()
    for (const row of contacts) {
      const sourceId = asString(row.id)
      const email = recipientAddress(row, 'email', '')
      const id = await recordId(env.HELLOADA_TENANT_ID, 'contact', sourceId)
      const source = asString(row.source)
      const nativeSource = ['email', 'form', 'booking'].includes(source) ? 'inbound' : 'manual'
      const lastSeen = column(row, 'last_seen_at', 'lastSeenAt')
      const created = column(row, 'created_at', 'createdAt')
      const displayName = asString(row.name) || null
      await env.MAILFLARE_DB.prepare(
        'INSERT INTO contacts (id, user_id, email, display_name, source, last_seen_at, created_at, helloada_phone, helloada_company, helloada_notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, email) DO UPDATE SET display_name = COALESCE(contacts.display_name, excluded.display_name), helloada_phone = COALESCE(contacts.helloada_phone, excluded.helloada_phone), helloada_company = COALESCE(contacts.helloada_company, excluded.helloada_company), helloada_notes = COALESCE(contacts.helloada_notes, excluded.helloada_notes)',
      ).bind(id, identity.serviceUserId, email, displayName, nativeSource, lastSeen ? epochSeconds(lastSeen, 'contact_last_seen') : null, created ? epochSeconds(created, 'contact_created') : nowSeconds, asString(row.phone) || null, asString(row.company) || null, asString(row.notes) || null).run()
      const stored = await env.MAILFLARE_DB.prepare('SELECT id FROM contacts WHERE user_id = ? AND email = ? LIMIT 1').bind(identity.serviceUserId, email).first<{ id: string }>()
      if (!stored) throw new Error('payload_migration_contact_not_materialized')
      mailflareContactIds.set(sourceId, stored.id)
      await insertRecord(env.MAILFLARE_DB, 'contacts', sourceId, await sha256(canonical(row)), 'contacts', stored.id)
    }

    for (const row of conversations) {
      const contactId = asString(column(row, 'contact_id', 'contact'))
      if (!contactsById.has(contactId)) throw new Error('payload_migration_conversation_contact_missing')
      if (!messages.some((message) => asString(column(message, 'conversation_id', 'conversation')) === asString(row.id))) {
        throw new Error('payload_migration_empty_conversation')
      }
    }

    const mailboxAddress = env.MAILFLARE_ADDRESS.trim().toLowerCase()
    const conversationNativeIds = new Map<string, string>()
    for (const row of messages) {
      const sourceId = asString(row.id)
      const conversationId = asString(column(row, 'conversation_id', 'conversation'))
      const conversation = conversationsById.get(conversationId)
      if (!conversation) throw new Error('payload_migration_message_conversation_missing')
      const legacyDirection = asString(row.direction)
      const direction = ['form_enquiry', 'received_email'].includes(legacyDirection) ? 'inbound'
        : ['reply', 'owner_message', 'booking_notice'].includes(legacyDirection) ? 'outbound' : null
      if (!direction) throw new Error('payload_migration_message_direction_unknown')
      const delivery = asString(column(row, 'delivery_state', 'deliveryState'))
      const conversationState = asString(conversation.state)
      const status = messageStatus(delivery, conversationState, direction)
      const nativeId = await recordId(env.HELLOADA_TENANT_ID, 'message', sourceId)
      const threadId = conversationNativeIds.get(conversationId) ?? await recordId(env.HELLOADA_TENANT_ID, 'thread', conversationId)
      conversationNativeIds.set(conversationId, threadId)
      const fromAddress = recipientAddress(row, 'from', direction === 'inbound' ? asString(column(conversation, 'participant_email', 'participantEmail')) : mailboxAddress)
      const toAddress = recipientAddress(row, 'to', direction === 'inbound' ? mailboxAddress : asString(column(conversation, 'participant_email', 'participantEmail')))
      const subject = asString(row.subject) || asString(conversation.subject)
      if (!subject) throw new Error('payload_migration_message_subject_missing')
      const body = asString(row.text) || asString(column(row, 'draft_text', 'draftText'))
      const created = column(row, 'created_at', 'createdAt')
      const timestamp = created ? epochSeconds(created, 'message_created') : nowSeconds
      const rawSourceKey = asString(column(row, 'raw_object_key', 'rawObjectKey'))
      let rawR2Key: string | null = null
      if (rawSourceKey) {
        const rawMatch = /^inbound\/\d{4}-\d{2}-\d{2}\/([a-f0-9]{64})\.eml/.exec(rawSourceKey)
        if (!rawMatch || rawMatch[0] !== rawSourceKey) throw new Error('payload_migration_raw_object_key_invalid')
        rawR2Key = 'payload-import/' + (await sha256(env.HELLOADA_TENANT_ID + ':' + rawSourceKey)).slice(0, 32) + '.eml'
        await copyObject(env.PRIVATE_EMAIL, env.MAILFLARE_BUCKET, rawSourceKey, rawR2Key, env.HELLOADA_TENANT_ID, rawMatch[1])
      }
      await env.MAILFLARE_DB.prepare(
        'INSERT OR IGNORE INTO messages (id, user_id, mailbox_id, direction, provider_message_id, from_addr, to_addr, cc_addr, bcc_addr, subject, snippet, text_body, raw_r2_key, status, read, starred, thread_id, in_reply_to, references_header, created_at, helloada_delivery_state, helloada_source_page, helloada_form_snapshot) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
      ).bind(
        nativeId, identity.serviceUserId, identity.mailboxId, direction,
        asString(column(row, 'external_message_id', 'externalMessageId')) || null,
        fromAddress, toAddress,
        addressList(column(row, 'cc_recipients', 'ccRecipients'), 'message_cc'),
        addressList(column(row, 'bcc_recipients', 'bccRecipients'), 'message_bcc'),
        subject, body.slice(0, 500), body, rawR2Key, status,
        conversation.unread ? 0 : 1, 0, threadId,
        asString(column(row, 'in_reply_to', 'inReplyTo')) || null,
        addressList(column(row, 'references', 'references_header'), 'message_references'),
        timestamp, delivery, asString(column(conversation, 'source_page', 'sourcePage')) || null,
        jsonText(column(row, 'form_snapshot', 'formSnapshot'), 'message_form_snapshot'),
      ).run()
      const manifestValue = jsonValue(column(row, 'attachment_manifest', 'attachmentManifest'), 'message_attachments')
      if (manifestValue != null && !Array.isArray(manifestValue)) throw new Error('payload_migration_attachment_manifest_invalid')
      const manifest = (manifestValue ?? []) as Row[]
      for (let index = 0; index < manifest.length; index++) {
        const item = manifest[index]
        const operationId = asString(column(row, 'operation_id', 'operationId'))
        if (!operationId) throw new Error('payload_migration_attachment_operation_missing')
        const sourceKey = 'attachments/' + operationId + '/' + index
        const attachmentId = await recordId(env.HELLOADA_TENANT_ID, 'attachment', sourceId + ':' + index)
        const targetKey = 'payload-import/attachments/' + attachmentId
        const expectedSha = asString(item.sha256)
        const expectedSize = Number(item.size)
        const copied = await copyObject(env.PRIVATE_EMAIL, env.MAILFLARE_BUCKET, sourceKey, targetKey, env.HELLOADA_TENANT_ID, expectedSha, expectedSize)
        await env.MAILFLARE_DB.prepare(
          'INSERT OR IGNORE INTO message_attachments (id, message_id, filename, content_type, size, disposition, r2_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        ).bind(attachmentId, nativeId, asString(item.filename) || 'attachment', asString(column(item, 'contentType', 'content_type')) || 'application/octet-stream', copied.size, 'attachment', targetKey, timestamp).run()
      }
      await insertRecord(env.MAILFLARE_DB, 'messages', sourceId, await sha256(canonical(row)), 'messages', nativeId)
    }

    for (const row of operations) {
      const sourceId = asString(row.id)
      const operationId = asString(column(row, 'operation_id', 'operationId'))
      const operationType = asString(column(row, 'operation_type', 'operationType'))
      const idempotencyKey = asString(column(row, 'idempotency_key', 'idempotencyKey'))
      const requestHash = asString(column(row, 'request_hash', 'requestHash'))
      if (!operationId || !operationType || !idempotencyKey || !requestHash) throw new Error('payload_migration_operation_incomplete')
      const payload = jsonText(row.payload, 'message_operation_payload') ?? '{}'
      const created = column(row, 'created_at', 'createdAt')
      await env.MAILFLARE_DB.prepare(
        'INSERT OR IGNORE INTO helloada_imported_operations (source_id, operation_id, operation_type, idempotency_key, request_hash, state, attempts, next_attempt_at, provider_reference, error_code, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
      ).bind(sourceId, operationId, operationType, idempotencyKey, requestHash, asString(row.state), Number(row.attempts ?? 0), column(row, 'next_attempt_at', 'nextAttemptAt') ? epochSeconds(column(row, 'next_attempt_at', 'nextAttemptAt'), 'operation_next_attempt') : null, asString(column(row, 'provider_reference', 'providerReference')) || null, asString(column(row, 'error_code', 'errorCode')) || null, payload, created ? epochSeconds(created, 'operation_created') : nowSeconds).run()
      await insertRecord(env.MAILFLARE_DB, 'message_operations', sourceId, await sha256(canonical(row)), 'helloada_imported_operations', sourceId)
    }

    const defaultLocale = identity.defaultLocale.trim()
    if (!defaultLocale) throw new Error('payload_migration_default_locale_missing')
    const localesByParent = new Map<string, Row[]>()
    for (const row of locales) {
      const parentId = asString(column(row, '_parent_id', 'parent_id'))
      localesByParent.set(parentId, [...(localesByParent.get(parentId) ?? []), row])
    }
    const settingsTimeZone = asString(column(settings, 'time_zone', 'timeZone'))
    const importedSchedules: string[] = []
    for (const row of appointmentTypes) {
      const sourceId = asString(row.id)
      const localized = localesByParent.get(sourceId) ?? []
      const primary = localized.find((item) => asString(column(item, '_locale', 'locale')) === defaultLocale)
      if (!primary || !asString(primary.name)) throw new Error('payload_migration_appointment_locale_missing')
      const schedule = bookingSchedule(availability, sourceId)
      importedSchedules.push(schedule.weeklyAvailability)
      const buffer = Number(column(row, 'buffer_minutes', 'bufferMinutes') ?? 0)
      const duration = Number(column(row, 'duration_minutes', 'durationMinutes'))
      const slug = asString(row.slug)
      if (!Number.isInteger(buffer) || buffer < 0 || buffer > 120 || buffer % 5 !== 0) throw new Error('payload_migration_booking_buffer_invalid')
      if (!Number.isInteger(duration) || duration < 5 || duration > 480 || duration % 5 !== 0 || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
        throw new Error('payload_migration_appointment_type_invalid')
      }
      const bookingId = await recordId(env.HELLOADA_TENANT_ID, 'booking', sourceId)
      const localesJson = Object.fromEntries(localized.map((item) => [asString(column(item, '_locale', 'locale')), { name: asString(item.name), description: asString(item.description) }]))
      const ranges = schedule.timeRanges
      const startTime = ranges[0].startTime
      const endTime = ranges[ranges.length - 1].endTime
      await env.MAILFLARE_DB.prepare(
        'INSERT OR IGNORE INTO booking_events (id, user_id, name, slug, description, color, host_ids, duration_minutes, location, weekdays, start_time, end_time, time_ranges, time_zone, enabled, created_at, updated_at, helloada_buffer_minutes, helloada_weekly_availability, helloada_locales, helloada_calendar_enabled, helloada_minimum_notice_hours, helloada_booking_window_days, helloada_payload_managed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
      ).bind(bookingId, identity.ownerUserId, asString(primary.name), slug, asString(primary.description), 'blue', JSON.stringify([identity.ownerUserId]), duration, '', JSON.stringify(schedule.weekdays), startTime, endTime, JSON.stringify(ranges), settingsTimeZone, Number(row.enabled) === 1 && asString(row._status) !== 'draft' ? 1 : 0, nowSeconds, nowSeconds, buffer, schedule.weeklyAvailability, JSON.stringify(localesJson), calendarEnabled, minimumNoticeHours, bookingWindowDays, 1).run()
      await insertRecord(env.MAILFLARE_DB, 'appointment_types', sourceId, await sha256(canonical(row)), 'booking_events', bookingId)
    }

    if (appointmentTypes.length) {
      const schedule = importedSchedules[0]
      const sharedSchedule = importedSchedules.every((value) => value === schedule)
      const weeklyAvailability = sharedSchedule ? schedule : '[]'
      const sharedTimeZone = sharedSchedule ? settingsTimeZone : ''
      const enabled = sharedSchedule && calendarEnabled === 1
        && appointmentTypes.some((row) => Number(row.enabled) === 1 && asString(row._status) !== 'draft')
      await env.MAILFLARE_DB.prepare(
        "INSERT INTO helloada_booking_settings (user_id,enabled,time_zone,weekly_availability,max_concurrent_appointments,minimum_notice_hours,booking_window_days,revision,updated_at) VALUES (?,?,?,?,1,?,?,1,?) ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,time_zone=excluded.time_zone,weekly_availability=excluded.weekly_availability,max_concurrent_appointments=1,minimum_notice_hours=excluded.minimum_notice_hours,booking_window_days=excluded.booking_window_days,revision=helloada_booking_settings.revision+1,updated_at=excluded.updated_at WHERE helloada_booking_settings.revision=1 AND helloada_booking_settings.enabled=0 AND helloada_booking_settings.time_zone='' AND helloada_booking_settings.weekly_availability='[]'",
      ).bind(identity.ownerUserId, enabled ? 1 : 0, sharedTimeZone, weeklyAvailability, minimumNoticeHours, bookingWindowDays, Date.now()).run()
    }

    const contactBySourceId = new Map(contacts.map((row) => [asString(row.id), row]))
    for (const row of calendarEvents) {
      const sourceId = asString(row.id)
      const typeId = asString(column(row, 'appointment_type_id', 'appointmentType'))
      const contactSourceId = asString(column(row, 'contact_id', 'contact'))
      const appointment = appointmentTypes.find((item) => asString(item.id) === typeId)
      const contact = contactBySourceId.get(contactSourceId)
      const mailflareContactId = mailflareContactIds.get(contactSourceId)
      if (!appointment || !contact || !mailflareContactId) throw new Error('payload_migration_calendar_relation_missing')
      const eventId = await recordId(env.HELLOADA_TENANT_ID, 'calendar_event', sourceId)
      const startsAt = epochMilliseconds(column(row, 'starts_at', 'startsAt'), 'calendar_starts')
      const endsAt = epochMilliseconds(column(row, 'ends_at', 'endsAt'), 'calendar_ends')
      if (endsAt <= startsAt) throw new Error('payload_migration_calendar_range_invalid')
      const buffer = Number(column(row, 'buffer_minutes', 'bufferMinutes') ?? 0)
      if (!Number.isInteger(buffer) || buffer < 0 || buffer > 120 || buffer % 5 !== 0) throw new Error('payload_migration_calendar_buffer_invalid')
      const title = asString(row.title)
      const attendee = recipientAddress(contact, 'email', '')
      const description = asString(row.answers)
      const appointmentLocaleRows = localesByParent.get(typeId) ?? []
      const appointmentName = asString(appointmentLocaleRows.find((item) => asString(column(item, '_locale', 'locale')) === defaultLocale)?.name)
      const appointmentDuration = Number(column(appointment, 'duration_minutes', 'durationMinutes'))
      if (!appointmentName || !Number.isInteger(appointmentDuration) || appointmentDuration < 5 || appointmentDuration > 480) throw new Error('payload_migration_appointment_snapshot_invalid')
      const bookingTypeId = await recordId(env.HELLOADA_TENANT_ID, 'booking', typeId)
      const capacitySettings = await env.MAILFLARE_DB.prepare(
        'SELECT revision FROM helloada_booking_settings WHERE user_id = ? LIMIT 1',
      ).bind(identity.ownerUserId).first<{ revision: number }>()
      if (!capacitySettings) throw new Error('payload_migration_booking_settings_missing')
      await env.MAILFLARE_DB.prepare(
        'INSERT OR IGNORE INTO calendar_events (id, user_id, mailbox_id, title, description, location, attendees, color, repeat, repeat_days, excluded_occurrences, time_zone, starts_at, ends_at, created_at, updated_at, helloada_state, helloada_receipt_id, helloada_answers, helloada_consent_accepted_at, helloada_notification_state, helloada_buffer_minutes, helloada_booking_type_id, helloada_booking_type_name, helloada_booking_duration_minutes, helloada_contact_id, helloada_capacity_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
      ).bind(eventId, identity.ownerUserId, identity.mailboxId, title, description, '', JSON.stringify([attendee]), 'blue', 'none', '[]', '[]', asString(column(row, 'time_zone', 'timeZone')), startsAt, endsAt, nowSeconds, nowSeconds, asString(row.state), asString(column(row, 'receipt_id', 'receiptId')), jsonText(row.answers, 'calendar_answers'), column(row, 'consent_accepted_at', 'consentAcceptedAt') ? epochSeconds(column(row, 'consent_accepted_at', 'consentAcceptedAt'), 'calendar_consent') : null, asString(column(row, 'notification_state', 'notificationState')), buffer, bookingTypeId, appointmentName, appointmentDuration, mailflareContactId, capacitySettings.revision).run()
      await insertRecord(env.MAILFLARE_DB, 'calendar_events', sourceId, await sha256(canonical(row)), 'calendar_events', eventId)
    }

    const sourceSha256 = await sha256(sourceDigests.sort().join('\n'))
    const countsJson = JSON.stringify(counts)
    await env.MAILFLARE_DB.prepare(
      "UPDATE helloada_import_runs SET state = 'complete', lease_token = NULL, lease_until = NULL, source_sha256 = ?, counts_json = ?, error_code = NULL, completed_at = ? WHERE tenant_id = ? AND version = ? AND lease_token = ?",
    ).bind(sourceSha256, countsJson, Date.now(), env.HELLOADA_TENANT_ID, VERSION, leaseToken).run()
    return { state: 'complete', counts, sourceSha256 }
  } catch (error) {
    await env.MAILFLARE_DB.prepare(
      "UPDATE helloada_import_runs SET state = 'failed', lease_token = NULL, lease_until = NULL, error_code = ?, completed_at = NULL WHERE tenant_id = ? AND version = ? AND lease_token = ?",
    ).bind(error instanceof Error ? error.message.slice(0, 120) : 'payload_migration_failed', env.HELLOADA_TENANT_ID, VERSION, leaseToken).run()
    throw error
  }
}
