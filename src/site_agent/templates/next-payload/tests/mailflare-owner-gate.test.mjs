import assert from 'node:assert/strict'
import { DatabaseSync } from 'node:sqlite'
import test from 'node:test'
import { createPayloadOwnerGate } from '../mailflare-owner-gate.ts'
import { provisionTenantMailflareMailbox } from '../mailflare-provisioning.ts'

function database() {
  const sqlite = new DatabaseSync(':memory:')
  sqlite.exec('CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT "user", is_primary_admin INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0, can_manage_mailboxes INTEGER NOT NULL DEFAULT 0, can_manage_domains INTEGER NOT NULL DEFAULT 0, can_manage_users INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL); CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), token_hash TEXT NOT NULL UNIQUE, expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL); CREATE TABLE domains (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), hostname TEXT NOT NULL UNIQUE, zone_id TEXT NOT NULL, status TEXT NOT NULL, routing_status TEXT, sending_provider TEXT NOT NULL, receiving_provider TEXT NOT NULL, sending_requested INTEGER NOT NULL, sending_enabled INTEGER NOT NULL, routing_enabled INTEGER NOT NULL, created_at INTEGER NOT NULL); CREATE TABLE mailboxes (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), domain_id TEXT NOT NULL REFERENCES domains(id), local_part TEXT NOT NULL, display_name TEXT, type TEXT NOT NULL, use_all_domains INTEGER NOT NULL, disabled INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, UNIQUE(domain_id, local_part)); CREATE TABLE mailbox_access (id TEXT PRIMARY KEY, mailbox_id TEXT NOT NULL REFERENCES mailboxes(id), user_id TEXT NOT NULL REFERENCES users(id), permission TEXT NOT NULL, created_by_user_id TEXT REFERENCES users(id), created_at INTEGER NOT NULL, UNIQUE(mailbox_id, user_id));')
  sqlite.exec('CREATE TABLE helloada_import_runs (tenant_id TEXT PRIMARY KEY NOT NULL, version TEXT NOT NULL, state TEXT NOT NULL, lease_token TEXT, lease_until INTEGER, source_sha256 TEXT, counts_json TEXT, error_code TEXT, started_at INTEGER NOT NULL, completed_at INTEGER); CREATE TABLE helloada_import_records (source_collection TEXT NOT NULL, source_id TEXT NOT NULL, source_sha256 TEXT NOT NULL, target_collection TEXT NOT NULL, target_id TEXT NOT NULL, migrated_at INTEGER NOT NULL, PRIMARY KEY (source_collection, source_id)); CREATE TABLE helloada_imported_operations (source_id TEXT PRIMARY KEY NOT NULL, operation_id TEXT NOT NULL, operation_type TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL, next_attempt_at INTEGER, provider_reference TEXT, error_code TEXT, payload TEXT NOT NULL, created_at INTEGER NOT NULL);')
  sqlite.exec('CREATE TABLE helloada_tenant_owners (tenant_id TEXT PRIMARY KEY NOT NULL, owner_user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE, created_at INTEGER NOT NULL); CREATE TABLE helloada_booking_settings (user_id TEXT PRIMARY KEY NOT NULL REFERENCES users(id) ON DELETE CASCADE, enabled INTEGER NOT NULL DEFAULT 0, time_zone TEXT NOT NULL DEFAULT \'\', weekly_availability TEXT NOT NULL DEFAULT \'[]\', max_concurrent_appointments INTEGER NOT NULL DEFAULT 1, minimum_notice_hours INTEGER NOT NULL DEFAULT 24, booking_window_days INTEGER NOT NULL DEFAULT 60, revision INTEGER NOT NULL DEFAULT 1, updated_at INTEGER NOT NULL);')
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
const emptyPayloadDatabase = () => ({
  prepare(sql) {
    let parameters = []
    return {
      bind(...values) { parameters = values; return this },
      async first() { return sql.includes('sqlite_master') ? { name: parameters[1] } : null },
      async all() { return { results: [] } },
      async run() { return {} },
    }
  },
})

const emptyBucket = {
  async get() { return null },
  async put() { throw new Error('unexpected empty-source bucket write') },
}

const env = (MAILFLARE_DB) => ({
  MAILFLARE_DB,
  HELLOADA_TENANT_ID: 'test-tenant',
  D1: emptyPayloadDatabase(),
  PRIVATE_EMAIL: emptyBucket,
  MAILFLARE_BUCKET: emptyBucket,
  MAILFLARE_ADDRESS: 'hello@example.test',
  MAILFLARE_ZONE_ID: 'zone-123',
  MAILFLARE_ROUTING_STATUS: 'active',
})

test('provisions one exact tenant domain and mailbox idempotently', async () => {
  const db = database()
  const options = {
    database: db.binding, tenantId: 'test-tenant', address: 'hello@example.test',
    zoneId: 'zone-123', routingStatus: 'active',
  }
  const first = await provisionTenantMailflareMailbox(options)
  const second = await provisionTenantMailflareMailbox(options)
  assert.deepEqual(second, first)
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS count FROM users').get().count, 1)
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS count FROM domains').get().count, 1)
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS count FROM mailboxes').get().count, 1)
  assert.equal(db.sqlite.prepare('SELECT status FROM domains').get().status, 'active')
  assert.equal(db.sqlite.prepare('SELECT local_part FROM mailboxes').get().local_part, 'hello')
})

test('provisions the service mailbox safely when first requests arrive concurrently', async () => {
  const db = database()
  const options = {
    database: db.binding, tenantId: 'test-tenant', address: 'hello@example.test',
    zoneId: 'zone-123', routingStatus: 'active',
  }

  const [first, second] = await Promise.all([
    provisionTenantMailflareMailbox(options),
    provisionTenantMailflareMailbox(options),
  ])

  assert.deepEqual(first, second)
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS count FROM users').get().count, 1)
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS count FROM domains').get().count, 1)
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS count FROM mailboxes').get().count, 1)
})

test('refuses to adopt an existing unlinked Mailflare account', async () => {
  const db = database()
  db.sqlite.prepare('INSERT INTO users (id,email,password_hash,name,created_at) VALUES (?,?,?,?,?)')
    .run('old-owner', 'old@example.test', 'hash', 'Old owner', Date.now())
  await assert.rejects(
    provisionTenantMailflareMailbox({
      database: db.binding, tenantId: 'test-tenant', address: 'hello@example.test',
      zoneId: 'zone-123', routingStatus: 'active',
    }),
    /unlinked account/,
  )
})

test('requires a Payload-authenticated identity for private pages and APIs', async () => {
  const db = database()
  await provisionTenantMailflareMailbox({
    database: db.binding, tenantId: 'test-tenant', address: 'hello@example.test',
    zoneId: 'zone-123', routingStatus: 'active',
  })
  let identities = 0
  const dispatched = []
  const gate = createPayloadOwnerGate({
    basePath: '/mail',
    defaultLocale: 'en',
    resolveIdentity: async () => { identities++; return { subject: 'payload-subject-1' } },
    logout: async () => new Response(null, { status: 204 }),
  })
  const dispatch = async (request) => { dispatched.push(request); return new Response('mailflare') }

  const page = await gate(new Request('https://tenant.test/mail/inbox'), env(db.binding), {}, dispatch)
  assert.equal(page.status, 302)
  assert.equal(page.headers.get('location'), 'https://tenant.test/admin/login?redirect=%2Fmail%2Finbox')
  assert.equal(identities, 0)
  assert.equal(dispatched.length, 0)

  const api = await gate(new Request('https://tenant.test/mail/api/messages'), env(db.binding), {}, dispatch)
  assert.equal(api.status, 401)
  assert.equal(dispatched.length, 0)
})

test('links Payload owner through a scoped HttpOnly Mailflare session and checks identity each request', async () => {
  const db = database()
  await provisionTenantMailflareMailbox({
    database: db.binding, tenantId: 'test-tenant', address: 'hello@example.test',
    zoneId: 'zone-123', routingStatus: 'active',
  })
  let identities = 0
  const dispatched = []
  const gate = createPayloadOwnerGate({
    basePath: '/mail',
    defaultLocale: 'en',
    resolveIdentity: async () => { identities++; return { subject: 'payload-subject-1' } },
    logout: async () => new Response(null, { status: 204 }),
  })
  const dispatch = async (request) => {
    dispatched.push(request)
    assert.match(request.headers.get('cookie') || '', /ep_session=/)
    return new Response('inbox')
  }
  const request = new Request('https://tenant.test/mail/inbox', { headers: { cookie: 'payload_session=valid' } })
  const first = await gate(request, env(db.binding), {}, dispatch)
  const setCookie = first.headers.get('set-cookie') || ''
  assert.match(setCookie, /ep_session=/)
  assert.match(setCookie, /Path=\/mail/)
  assert.match(setCookie, /HttpOnly/)
  assert.match(setCookie, /SameSite=Lax/)
  assert.match(setCookie, /Secure/)
  assert.equal(first.headers.get('cache-control'), 'private, no-store')
  assert.equal(await first.text(), 'inbox')

  const token = setCookie.match(/ep_session=([^;]+)/)?.[1]
  assert.ok(token)
  const second = await gate(
    new Request('https://tenant.test/mail/api/mailboxes', { headers: { cookie: 'payload_session=valid; ep_session=' + token } }),
    env(db.binding), {}, dispatch,
  )
  assert.equal(second.status, 200)
  assert.equal(second.headers.has('set-cookie'), false)
  assert.equal(identities, 2)
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS count FROM sessions').get().count, 1)
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS count FROM mailbox_access').get().count, 1)
  assert.equal(db.sqlite.prepare('SELECT permission FROM mailbox_access').get().permission, 'full_access')
  assert.equal(db.sqlite.prepare("SELECT name FROM pragma_table_info('users') WHERE name='booking_username'").get(), undefined)
  assert.ok(db.sqlite.prepare('SELECT created_at FROM sessions').get().created_at > 0)
})

test('serves simultaneous first inbox requests without racing owner or import setup', async () => {
  const db = database()
  const gate = createPayloadOwnerGate({
    basePath: '/mail',
    defaultLocale: 'en',
    resolveIdentity: async () => ({ subject: 'first-inbox-concurrency' }),
    logout: async () => new Response(null, { status: 204 }),
  })
  let dispatched = 0
  const dispatch = async () => { dispatched++; return new Response('inbox') }
  const request = () => new Request('https://tenant.test/mail/inbox', {
    headers: { cookie: 'payload_session=valid' },
  })

  const responses = await Promise.all([
    gate(request(), env(db.binding), {}, dispatch),
    gate(request(), env(db.binding), {}, dispatch),
  ])

  assert.deepEqual(responses.map((response) => response.status), [200, 200])
  assert.equal(dispatched, 2)
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS count FROM users').get().count, 2)
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS count FROM domains').get().count, 1)
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS count FROM mailboxes').get().count, 1)
  assert.equal(db.sqlite.prepare("SELECT COUNT(*) AS count FROM helloada_import_runs WHERE state = 'complete'").get().count, 1)
})

test('blocks Mailflare native login and register routes while allowing static assets', async () => {
  const db = database()
  await provisionTenantMailflareMailbox({
    database: db.binding, tenantId: 'test-tenant', address: 'hello@example.test',
    zoneId: 'zone-123', routingStatus: 'active',
  })
  let called = 0
  const gate = createPayloadOwnerGate({
    basePath: '/mail',
    defaultLocale: 'en',
    resolveIdentity: async () => ({ subject: 'payload-subject-1' }),
    logout: async () => new Response(null, { status: 204 }),
  })
  const dispatch = async () => { called++; return new Response('dispatched') }

  assert.equal((await gate(new Request('https://tenant.test/mail/login'), env(db.binding), {}, dispatch)).status, 302)
  assert.equal((await gate(new Request('https://tenant.test/mail/api/auth/register', { method: 'POST' }), env(db.binding), {}, dispatch)).status, 403)
  assert.equal((await gate(new Request('https://tenant.test/mail/api/public/booking?username=test-tenant'), env(db.binding), {}, dispatch)).status, 401)
  assert.equal((await gate(new Request('https://tenant.test/mail/api/public/booking/type-id'), env(db.binding), {}, dispatch)).status, 200)
  assert.equal((await gate(new Request('https://tenant.test/mail/_next/static/chunk.js'), env(db.binding), {}, dispatch)).status, 200)
  assert.equal(called, 2)
})

test('shows a HelloAda setup state instead of crashing before mailbox provisioning', async () => {
  const db = database()
  const pendingEnv = {
    ...env(db.binding),
    MAILFLARE_ADDRESS: '',
    MAILFLARE_ZONE_ID: '',
    MAILFLARE_ROUTING_STATUS: '',
  }
  let identities = 0
  let dispatched = 0
  const gate = createPayloadOwnerGate({
    basePath: '/mail',
    defaultLocale: 'en',
    resolveIdentity: async () => { identities++; return { subject: 'payload-subject-1' } },
    logout: async () => new Response(null, { status: 204 }),
  })
  const dispatch = async () => { dispatched++; return new Response('dispatched') }

  const page = await gate(
    new Request('https://tenant.test/mail/inbox', { headers: { cookie: 'payload_session=valid' } }),
    pendingEnv,
    {},
    dispatch,
  )
  assert.equal(page.status, 503)
  assert.match(page.headers.get('content-type') || '', /text\/html/)
  const body = await page.text()
  assert.match(body, /Your inbox is being prepared/)
  assert.match(body, /\/brand\/helloada-logo\.svg/)
  assert.doesNotMatch(body, /Mailflare/i)
  assert.equal(page.headers.get('retry-after'), '30')

  const api = await gate(new Request('https://tenant.test/mail/api/booking'), pendingEnv, {}, dispatch)
  assert.equal(api.status, 503)
  assert.match((await api.json()).error, /preparing your inbox and booking calendar/i)

  const asset = await gate(new Request('https://tenant.test/mail/_next/static/chunk.js'), pendingEnv, {}, dispatch)
  assert.equal(asset.status, 200)
  assert.equal(identities, 0)
  assert.equal(dispatched, 1)
})

test('keeps a competing cross-isolate migration in a clear setup state', async () => {
  const db = database()
  await provisionTenantMailflareMailbox({
    database: db.binding, tenantId: 'test-tenant', address: 'hello@example.test',
    zoneId: 'zone-123', routingStatus: 'active',
  })
  db.sqlite.prepare(
    'INSERT INTO helloada_import_runs (tenant_id, version, state, lease_token, lease_until, started_at) VALUES (?, ?, ?, ?, ?, ?)',
  ).run('test-tenant', 'payload-mailbox-v2', 'running', 'other-isolate-lease', Date.now() + 60_000, Date.now())
  const gate = createPayloadOwnerGate({
    basePath: '/mail',
    defaultLocale: 'en',
    resolveIdentity: async () => ({ subject: 'mailbox-migration-pending' }),
    logout: async () => new Response(null, { status: 204 }),
  })
  let dispatched = 0
  const dispatch = async () => { dispatched++; return new Response('mailbox') }

  const page = await gate(
    new Request('https://tenant.test/mail/inbox', { headers: { cookie: 'payload_session=valid' } }),
    env(db.binding), {}, dispatch,
  )
  assert.equal(page.status, 503)
  assert.equal(page.headers.get('retry-after'), '3')
  assert.match(await page.text(), /Preparing your inbox/)
  assert.match(page.headers.get('content-type') || '', /text\/html/)
  assert.equal(dispatched, 0)

  const api = await gate(
    new Request('https://tenant.test/mail/api/messages', { headers: { cookie: 'payload_session=valid' } }),
    env(db.binding), {}, dispatch,
  )
  assert.equal(api.status, 503)
  assert.equal((await api.json()).error, 'mailbox_migration_in_progress')
  assert.equal(dispatched, 0)
})


test('Payload logout clears only the Mailflare session cookie and invokes Payload logout', async () => {
  const db = database()
  let logoutCalls = 0
  const gate = createPayloadOwnerGate({
    basePath: '/mail',
    defaultLocale: 'en',
    resolveIdentity: async () => null,
    logout: async () => { logoutCalls++; return new Response(null, { status: 204 }) },
  })
  const response = await gate(
    new Request('https://tenant.test/mail/api/auth/logout', { method: 'POST', headers: { cookie: 'payload_session=valid; ep_session=abc' } }),
    env(db.binding), {}, async () => new Response('not called'),
  )
  assert.equal(response.status, 204)
  assert.equal(logoutCalls, 1)
  assert.match(response.headers.get('set-cookie') || '', /ep_session=; Path=\/mail; Max-Age=0/)
  assert.equal(response.headers.get('cache-control'), 'private, no-store')
})


test('redirects the Mailflare favicon to the shared HelloAda mark without an owner session', async () => {
  const db = database()
  let identities = 0
  const gate = createPayloadOwnerGate({
    basePath: '/mail',
    defaultLocale: 'en',
    resolveIdentity: async () => { identities++; return { subject: 'payload-subject-1' } },
    logout: async () => new Response(null, { status: 204 }),
  })
  let dispatched = 0
  const dispatch = async () => { dispatched++; return new Response('unexpected', { status: 200 }) }

  const favicon = await gate(new Request('https://tenant.test/mail/favicon.ico'), env(db.binding), {}, dispatch)
  assert.equal(favicon.status, 302)
  assert.equal(favicon.headers.get('location'), 'https://tenant.test/brand/helloada-logo.svg')
  assert.equal(dispatched, 0)
  assert.equal(identities, 0)
})
