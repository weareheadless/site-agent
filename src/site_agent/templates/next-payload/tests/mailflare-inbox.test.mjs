import assert from 'node:assert/strict'
import test from 'node:test'

import { writeMailflareFormMessage } from '../src/lib/mailflare-inbox.ts'

class MemoryMailflareD1 {
  messages = new Map()
  contacts = new Map()
  messageInserts = 0
  mailbox = { id: 'mb_test', user_id: 'user_test', disabled: 0, status: 'active', local_part: 'hello', hostname: 'example.test' }

  prepare(sql) {
    let values = []
    return {
      bind: (...bound) => { values = bound; return this.prepareStatement(sql, () => values) },
      ...this.prepareStatement(sql, () => values),
    }
  }

  prepareStatement(sql, getValues) {
    return {
      bind: (...bound) => {
        const values = bound
        return {
          first: async () => this.first(sql, values),
          run: async () => this.run(sql, values),
        }
      },
      first: async () => this.first(sql, getValues()),
      run: async () => this.run(sql, getValues()),
    }
  }

  async first(sql, values) {
    if (sql.includes('FROM mailboxes')) return this.mailbox
    if (sql.includes('FROM messages WHERE id')) return this.messages.get(values[0]) || null
    return null
  }

  async run(sql, values) {
    if (sql.includes('INSERT INTO contacts')) {
      this.contacts.set(values[2], { id: values[0], user_id: values[1], email: values[2], display_name: values[3] })
    }
    if (sql.includes('INSERT OR IGNORE INTO messages')) {
      this.messageInserts += 1
      const [id, user_id, mailbox_id, provider_message_id, from_addr, to_addr, subject, snippet, text_body, thread_id, created_at] = values
      if (!this.messages.has(id)) this.messages.set(id, {
        id, user_id, mailbox_id, direction: 'inbound', provider_message_id, from_addr, to_addr,
        subject, snippet, text_body, status: 'received', thread_id, created_at,
      })
    }
    return { meta: { changes: 1 } }
  }
}

const params = (database, overrides = {}) => ({
  database,
  tenantId: 'test-site',
  mailboxAddress: 'hello@example.test',
  formSlug: 'contact',
  formTitle: 'Contact us',
  requestId: 'request_identifier_123',
  sourcePage: '/contact',
  fields: [
    { key: 'name', label: 'Name', mapsTo: 'name', type: 'text' },
    { key: 'email', label: 'Email', mapsTo: 'email', type: 'email' },
    { key: 'message', label: 'Message', mapsTo: 'message', type: 'textarea' },
    { key: 'topic', label: 'Topic', mapsTo: 'none', type: 'select' },
    { key: 'consent', label: 'Consent', mapsTo: 'none', type: 'consent' },
  ],
  submission: {
    answers: { name: 'Maya', email: 'maya@example.net', message: 'Please call me.', topic: 'Appointments', consent: true },
    contact: { name: 'Maya', email: 'maya@example.net' },
    message: 'Please call me.',
  },
  ...overrides,
})

test('website form creates a native inbound Mailflare message and contact', async () => {
  const database = new MemoryMailflareD1()
  const result = await writeMailflareFormMessage(params(database))

  assert.equal(result.duplicate, false)
  assert.equal(database.messages.size, 1)
  const [message] = database.messages.values()
  assert.equal(message.direction, 'inbound')
  assert.equal(message.status, 'received')
  assert.equal(message.mailbox_id, 'mb_test')
  assert.equal(message.to_addr, 'hello@example.test')
  assert.equal(message.from_addr, '"Maya" <maya@example.net>')
  assert.match(message.text_body, /Please call me\./)
  assert.match(message.text_body, /Topic: Appointments/)
  assert.doesNotMatch(message.text_body, /Consent/)
  assert.equal(database.contacts.get('maya@example.net').display_name, 'Maya')
})

test('replaying the same form request is idempotent; changed answers conflict', async () => {
  const database = new MemoryMailflareD1()
  const input = params(database)
  const first = await writeMailflareFormMessage(input)
  const second = await writeMailflareFormMessage(input)
  assert.equal(second.messageId, first.messageId)
  assert.equal(second.duplicate, true)
  assert.equal(database.messageInserts, 1)

  await assert.rejects(
    writeMailflareFormMessage(params(database, {
      submission: {
        answers: { name: 'Maya', email: 'maya@example.net', message: 'Changed.', topic: 'Appointments', consent: true },
        contact: { name: 'Maya', email: 'maya@example.net' },
        message: 'Changed.',
      },
    })),
    /already used for different answers/,
  )
})

test('a form is not accepted unless its exact tenant Mailflare mailbox is active', async () => {
  const database = new MemoryMailflareD1()
  database.mailbox = null
  await assert.rejects(writeMailflareFormMessage(params(database)), /mailbox is not active/)
  assert.equal(database.messages.size, 0)
})
