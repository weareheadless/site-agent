import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { DatabaseSync } from 'node:sqlite'
import test from 'node:test'
import { migratePayloadMailbox } from '../mailflare-payload-migration.ts'

const sha256 = (value) => createHash('sha256').update(value).digest('hex')
const migrationSql = await readFile(
  new URL('../../../../../packages/helloada-mailflare/integration-migrations/0062_helloada_payload_migration.sql', import.meta.url),
  'utf8',
)

function binding(sqlite) {
  return {
    prepare(sql) {
      let parameters = []
      return {
        bind(...values) { parameters = values; return this },
        async first() { return sqlite.prepare(sql).get(...parameters) ?? null },
        async all() { return { results: sqlite.prepare(sql).all(...parameters) } },
        async run() { return sqlite.prepare(sql).run(...parameters) },
      }
    },
  }
}

function bucket(initial = {}) {
  const objects = new Map(Object.entries(initial).map(([key, value]) => [key, Buffer.from(value)]))
  return {
    objects,
    async get(key) {
      const bytes = objects.get(key)
      if (!bytes) return null
      return {
        arrayBuffer: async () => Uint8Array.from(bytes).buffer,
        httpMetadata: { contentType: 'application/octet-stream' },
      }
    },
    async put(key, value, options) {
      objects.set(key, Buffer.from(value))
      return options
    },
  }
}

function payloadSource({ invalidSchedule = false } = {}) {
  const sqlite = new DatabaseSync(':memory:')
  sqlite.exec([
    'CREATE TABLE contacts (id INTEGER PRIMARY KEY, email_key TEXT NOT NULL, email TEXT NOT NULL, name TEXT, phone TEXT, company TEXT, notes TEXT, source TEXT NOT NULL, last_seen_at TEXT, created_at TEXT NOT NULL);',
    'CREATE TABLE conversations (id INTEGER PRIMARY KEY, subject TEXT NOT NULL, contact_id INTEGER NOT NULL, participant_email TEXT NOT NULL, mailbox_key TEXT NOT NULL, thread_key TEXT NOT NULL, state TEXT NOT NULL, unread INTEGER, source TEXT NOT NULL, source_page TEXT, last_activity_at TEXT NOT NULL, last_message_preview TEXT, updated_at TEXT NOT NULL, created_at TEXT NOT NULL);',
    'CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL, direction TEXT NOT NULL, "from" TEXT, "to" TEXT, subject TEXT NOT NULL, text TEXT NOT NULL, draft_text TEXT, draft_revision INTEGER, delivery_state TEXT NOT NULL, form_id INTEGER, form_snapshot TEXT, receipt_id TEXT, external_message_id TEXT, in_reply_to TEXT, "references" TEXT, raw_object_key TEXT, attachment_manifest TEXT, approval_hash TEXT, approved_by TEXT, approved_at TEXT, operation_id TEXT, cc_recipients TEXT, bcc_recipients TEXT, created_at TEXT NOT NULL);',
    'CREATE TABLE message_operations (id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL, operation_type TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER, next_attempt_at TEXT, lease_until TEXT, payload TEXT, private_object_key TEXT, provider_reference TEXT, error_code TEXT, updated_at TEXT NOT NULL, created_at TEXT NOT NULL);',
    'CREATE TABLE appointment_types (id INTEGER PRIMARY KEY, slug TEXT, duration_minutes INTEGER, buffer_minutes INTEGER, enabled INTEGER, updated_at TEXT NOT NULL, created_at TEXT NOT NULL, _status TEXT);',
    'CREATE TABLE appointment_types_locales (name TEXT, description TEXT, id INTEGER PRIMARY KEY, _locale TEXT NOT NULL, _parent_id INTEGER NOT NULL);',
    'CREATE TABLE appointment_types_weekly_availability (_order INTEGER NOT NULL, _parent_id INTEGER NOT NULL, id TEXT PRIMARY KEY, day TEXT, start_time TEXT, end_time TEXT);',
    'CREATE TABLE calendar_events (id INTEGER PRIMARY KEY, title TEXT NOT NULL, appointment_type_id INTEGER NOT NULL, contact_id INTEGER NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, buffer_minutes INTEGER, time_zone TEXT NOT NULL, state TEXT NOT NULL, source_page TEXT, receipt_id TEXT NOT NULL, answers TEXT, consent_accepted_at TEXT, notification_state TEXT, updated_at TEXT NOT NULL, created_at TEXT NOT NULL);',
    'CREATE TABLE calendar_settings (id INTEGER PRIMARY KEY, enabled INTEGER, time_zone TEXT NOT NULL, minimum_notice_hours INTEGER, booking_window_days INTEGER, updated_at TEXT, created_at TEXT);',
  ].join('\n'))
  const raw = Buffer.from('From: customer@example.test\nSubject: Website enquiry\n\nHello from the old inbox.\n')
  const attachment = Buffer.from('sample attachment bytes')
  const rawKey = 'inbound/2026-10-09/' + sha256(raw) + '.eml'
  const attachmentManifest = JSON.stringify([{
    filename: 'brief.txt',
    contentType: 'text/plain',
    size: attachment.length,
    sha256: sha256(attachment),
  }])
  sqlite.prepare('INSERT INTO contacts (id,email_key,email,name,phone,company,notes,source,last_seen_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)')
    .run(7, 'customer@example.test', 'customer@example.test', 'Customer Name', '+521234567890', 'Customer Co', 'Prefers email', 'form', '2026-10-09T12:00:00.000Z', '2026-10-01T12:00:00.000Z')
  sqlite.prepare('INSERT INTO conversations (id,subject,contact_id,participant_email,mailbox_key,thread_key,state,unread,source,source_page,last_activity_at,last_message_preview,updated_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)')
    .run(40, 'Website enquiry', 7, 'customer@example.test', 'hello@example.test', 'legacy-thread-40', 'needs_reply', 1, 'form', '/contact', '2026-10-09T12:00:00.000Z', 'Hello from the old inbox.', '2026-10-09T12:00:00.000Z', '2026-10-09T12:00:00.000Z')
  sqlite.prepare('INSERT INTO messages (id,conversation_id,direction,"from","to",subject,text,delivery_state,form_snapshot,receipt_id,external_message_id,raw_object_key,attachment_manifest,operation_id,cc_recipients,bcc_recipients,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)')
    .run(90, 40, 'form_enquiry', 'customer@example.test', 'hello@example.test', 'Website enquiry', 'Hello from the old inbox.', 'received', JSON.stringify({ name: 'Customer Name', topic: 'Design' }), 'receipt-90', 'provider-90', rawKey, attachmentManifest, 'op-90', '[]', '[]', '2026-10-09T12:00:00.000Z')
  sqlite.prepare('INSERT INTO message_operations (id,operation_id,operation_type,idempotency_key,request_hash,state,attempts,payload,provider_reference,updated_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)')
    .run(11, 'op-90', 'inbound_receipt', 'idem-90', 'request-hash-90', 'accepted', 1, JSON.stringify({ messageId: 90 }), 'provider-90', '2026-10-09T12:00:00.000Z', '2026-10-09T12:00:00.000Z')
  sqlite.prepare('INSERT INTO appointment_types (id,slug,duration_minutes,buffer_minutes,enabled,updated_at,created_at,_status) VALUES (?,?,?,?,?,?,?,?)')
    .run(22, 'intro-call', 30, 15, 1, '2026-10-09T12:00:00.000Z', '2026-10-01T12:00:00.000Z', 'published')
  sqlite.prepare('INSERT INTO appointment_types_locales (name,description,id,_locale,_parent_id) VALUES (?,?,?,?,?)')
    .run('Introductory call', 'Talk with our team.', 22, 'en', 22)
  sqlite.prepare('INSERT INTO appointment_types_locales (name,description,id,_locale,_parent_id) VALUES (?,?,?,?,?)')
    .run('Llamada inicial', 'Conoce al equipo.', 23, 'es', 22)
  const tuesdayStart = invalidSchedule ? '09:07' : '10:00'
  sqlite.prepare('INSERT INTO appointment_types_weekly_availability (_order,_parent_id,id,day,start_time,end_time) VALUES (?,?,?,?,?,?)')
    .run(1, 22, 'avail-1', 'Monday', '09:00', '17:00')
  sqlite.prepare('INSERT INTO appointment_types_weekly_availability (_order,_parent_id,id,day,start_time,end_time) VALUES (?,?,?,?,?,?)')
    .run(2, 22, 'avail-2', 'Tuesday', tuesdayStart, '17:00')
  sqlite.prepare('INSERT INTO calendar_events (id,title,appointment_type_id,contact_id,starts_at,ends_at,buffer_minutes,time_zone,state,source_page,receipt_id,answers,consent_accepted_at,notification_state,updated_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)')
    .run(70, 'Introductory call', 22, 7, '2026-10-12T15:00:00.000Z', '2026-10-12T15:30:00.000Z', 5, 'America/Cancun', 'confirmed', '/contact', 'booking-receipt-70', JSON.stringify({ goal: 'Discuss a project' }), '2026-10-09T11:00:00.000Z', 'sent', '2026-10-09T12:00:00.000Z', '2026-10-09T11:00:00.000Z')
  sqlite.prepare('INSERT INTO calendar_settings (id,enabled,time_zone,minimum_notice_hours,booking_window_days,updated_at,created_at) VALUES (?,?,?,?,?,?,?)')
    .run(1, 1, 'America/Cancun', 12, 45, '2026-10-09T12:00:00.000Z', '2026-10-01T12:00:00.000Z')
  return { sqlite, binding: binding(sqlite), raw, attachment, rawKey }
}

function mailflareDatabase() {
  const sqlite = new DatabaseSync(':memory:')
  sqlite.exec([
    'CREATE TABLE contacts (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, email TEXT NOT NULL, display_name TEXT, source TEXT NOT NULL, last_seen_at INTEGER, created_at INTEGER NOT NULL, UNIQUE(user_id,email));',
    'CREATE TABLE messages (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mailbox_id TEXT, direction TEXT NOT NULL, provider_message_id TEXT, from_addr TEXT NOT NULL, to_addr TEXT NOT NULL, cc_addr TEXT, bcc_addr TEXT, subject TEXT, snippet TEXT, text_body TEXT, raw_r2_key TEXT, status TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0, starred INTEGER NOT NULL DEFAULT 0, thread_id TEXT, in_reply_to TEXT, references_header TEXT, created_at INTEGER NOT NULL);',
    'CREATE TABLE message_attachments (id TEXT PRIMARY KEY, message_id TEXT NOT NULL, filename TEXT NOT NULL, content_type TEXT NOT NULL, size INTEGER NOT NULL, disposition TEXT NOT NULL, r2_key TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL);',
    'CREATE TABLE booking_events (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, slug TEXT NOT NULL, description TEXT NOT NULL, color TEXT NOT NULL, host_ids TEXT NOT NULL, duration_minutes INTEGER NOT NULL, location TEXT NOT NULL, weekdays TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL, time_ranges TEXT NOT NULL, time_zone TEXT NOT NULL, enabled INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);',
    'CREATE TABLE calendar_events (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, mailbox_id TEXT, title TEXT NOT NULL, description TEXT NOT NULL, location TEXT NOT NULL, attendees TEXT NOT NULL, color TEXT NOT NULL, repeat TEXT NOT NULL, repeat_days TEXT NOT NULL, excluded_occurrences TEXT NOT NULL, time_zone TEXT, starts_at INTEGER NOT NULL, ends_at INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);',
  ].join('\n'))
  sqlite.exec(migrationSql)
  return { sqlite, binding: binding(sqlite) }
}

function migrationEnv(source, target) {
  const privateEmail = bucket({ [source.rawKey]: source.raw })
  privateEmail.objects.set('attachments/op-90/0', source.attachment)
  return {
    D1: source.binding,
    MAILFLARE_DB: target.binding,
    PRIVATE_EMAIL: privateEmail,
    MAILFLARE_BUCKET: bucket(),
    HELLOADA_TENANT_ID: 'tenant-fixture',
    MAILFLARE_ADDRESS: 'hello@example.test',
  }
}

const owner = {
  ownerUserId: 'owner-fixture',
  serviceUserId: 'service-user-fixture',
  mailboxId: 'mailbox-fixture',
  defaultLocale: 'en',
}

test('imports Payload mailbox, immutable objects, booking setup and calendar events idempotently', async () => {
  const source = payloadSource()
  const target = mailflareDatabase()
  const env = migrationEnv(source, target)
  const result = await migratePayloadMailbox(env, owner)
  assert.equal(result.state, 'complete')
  assert.equal(result.counts.contacts, 1)
  assert.equal(result.counts.messages, 1)
  assert.equal(result.counts.appointment_types, 1)
  assert.equal(result.counts.calendar_events, 1)

  const contact = target.sqlite.prepare('SELECT * FROM contacts').get()
  assert.equal(contact.email, 'customer@example.test')
  assert.equal(contact.display_name, 'Customer Name')
  assert.equal(contact.helloada_phone, '+521234567890')
  assert.equal(contact.helloada_company, 'Customer Co')
  assert.equal(contact.helloada_notes, 'Prefers email')

  const message = target.sqlite.prepare('SELECT * FROM messages').get()
  assert.equal(message.direction, 'inbound')
  assert.equal(message.status, 'received')
  assert.equal(message.read, 0)
  assert.equal(message.helloada_source_page, '/contact')
  assert.deepEqual(JSON.parse(message.helloada_form_snapshot), { name: 'Customer Name', topic: 'Design' })
  assert.ok(message.raw_r2_key)
  const attachmentRow = target.sqlite.prepare('SELECT * FROM message_attachments').get()
  const attachmentObject = await env.MAILFLARE_BUCKET.get(attachmentRow.r2_key)
  assert.ok(attachmentObject)
  assert.equal(Buffer.from(await attachmentObject.arrayBuffer()).toString(), source.attachment.toString())
  const rawObject = await env.MAILFLARE_BUCKET.get(message.raw_r2_key)
  assert.ok(rawObject)
  assert.equal(Buffer.from(await rawObject.arrayBuffer()).toString(), source.raw.toString())

  const booking = target.sqlite.prepare('SELECT * FROM booking_events').get()
  assert.equal(booking.name, 'Introductory call')
  assert.deepEqual(JSON.parse(booking.helloada_locales), {
    en: { name: 'Introductory call', description: 'Talk with our team.' },
    es: { name: 'Llamada inicial', description: 'Conoce al equipo.' },
  })
  assert.deepEqual(JSON.parse(booking.weekdays), [1, 2])
  assert.deepEqual(JSON.parse(booking.helloada_weekly_availability), [
    { day: 1, startTime: '09:00', endTime: '17:00' },
    { day: 2, startTime: '10:00', endTime: '17:00' },
  ])
  assert.equal(booking.helloada_buffer_minutes, 15)
  assert.equal(booking.helloada_calendar_enabled, 1)
  assert.equal(booking.helloada_minimum_notice_hours, 12)

  assert.equal(booking.helloada_booking_window_days, 45)
  assert.equal(booking.helloada_payload_managed, 1)
  const calendar = target.sqlite.prepare('SELECT * FROM calendar_events').get()
  assert.equal(calendar.helloada_state, 'confirmed')
  assert.equal(calendar.helloada_receipt_id, 'booking-receipt-70')
  assert.deepEqual(JSON.parse(calendar.helloada_answers), { goal: 'Discuss a project' })
  assert.equal(calendar.helloada_notification_state, 'sent')
  assert.equal(calendar.helloada_buffer_minutes, 5)

  const imported = await migratePayloadMailbox(env, owner)
  assert.deepEqual(imported, result)
  assert.equal(target.sqlite.prepare('SELECT COUNT(*) AS count FROM messages').get().count, 1)
  assert.equal(target.sqlite.prepare('SELECT COUNT(*) AS count FROM message_attachments').get().count, 1)
  assert.equal(target.sqlite.prepare('SELECT COUNT(*) AS count FROM calendar_events').get().count, 1)
})

test('rejects invalid booking schedules and resumes cleanly when the source is corrected', async () => {
  const source = payloadSource({ invalidSchedule: true })
  const target = mailflareDatabase()
  const env = migrationEnv(source, target)
  await assert.rejects(migratePayloadMailbox(env, owner), /payload_migration_booking_schedule_invalid/)
  assert.equal(target.sqlite.prepare('SELECT state FROM helloada_import_runs').get().state, 'failed')
  assert.equal(target.sqlite.prepare('SELECT COUNT(*) AS count FROM contacts').get().count, 1)
  source.sqlite.prepare("UPDATE appointment_types_weekly_availability SET start_time='10:00' WHERE id='avail-2'").run()
  const result = await migratePayloadMailbox(env, owner)
  assert.equal(result.state, 'complete')
  assert.equal(target.sqlite.prepare('SELECT COUNT(*) AS count FROM contacts').get().count, 1)
  assert.equal(target.sqlite.prepare('SELECT COUNT(*) AS count FROM messages').get().count, 1)
  assert.equal(target.sqlite.prepare('SELECT COUNT(*) AS count FROM booking_events').get().count, 1)
})
