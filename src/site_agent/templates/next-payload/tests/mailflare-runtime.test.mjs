import assert from 'node:assert/strict'
import test from 'node:test'
import { composeTenantWorker } from '../mailflare-runtime.ts'

const queueNames = ['tenant-mailflare-inbound', 'tenant-mailflare-outbound', 'tenant-mailflare-agent']

function handlers() {
  const calls = []
  const site = {
    fetch: async (request) => { calls.push(['site.fetch', new URL(request.url).pathname]); return new Response('site') },
  }
  const mailflare = {
    fetch: async (request, env) => { calls.push(['mail.fetch', new URL(request.url).pathname, env.name]); return new Response('mail') },
    email: async (_message, env) => { calls.push(['mail.email', env.name]) },
    queue: async (batch, env) => { calls.push(['mail.queue', batch.queue, env.name]) },
    scheduled: async (event, env) => { calls.push(['mail.scheduled', event.cron, env.name]) },
  }
  const worker = composeTenantWorker({
    site,
    mailflare,
    mailflareEnv: (env) => ({ ...env, name: 'mailflare-env' }),
    mailflareQueueNames: () => [...queueNames],
    mailflareRequest: (request, _env, _context, dispatch) => dispatch(request),
    basePath: '/mail',
  })
  return { calls, worker }
}

test('HTTP dispatch is isolated to the exact Mailflare base path', async () => {
  const { calls, worker } = handlers()
  const env = { name: 'tenant' }
  assert.equal(await (await worker.fetch(new Request('https://tenant.test/mail'), env, {})).text(), 'mail')
  assert.equal(await (await worker.fetch(new Request('https://tenant.test/mail/inbox/42'), env, {})).text(), 'mail')
  assert.equal(await (await worker.fetch(new Request('https://tenant.test/mailbox'), env, {})).text(), 'site')
  assert.equal(await (await worker.fetch(new Request('https://tenant.test/admin'), env, {})).text(), 'site')
  assert.deepEqual(calls.map(([name]) => name), ['mail.fetch', 'mail.fetch', 'site.fetch', 'site.fetch'])
})

test('owner gate dispatch always receives a Promise for synchronous Mailflare handlers', async () => {
  const worker = composeTenantWorker({
    site: { fetch: () => new Response('site') },
    mailflare: { fetch: () => new Response('mail') },
    mailflareEnv: (env) => env,
    mailflareQueueNames: () => [...queueNames],
    mailflareRequest: (request, _env, _context, dispatch) => {
      const response = dispatch(request)
      assert.equal(typeof response.then, 'function')
      return response
    },
    basePath: '/mail',
  })

  const response = await worker.fetch(new Request('https://tenant.test/mail'), {}, {})

  assert.equal(await response.text(), 'mail')
})

test('inbound email has one Mailflare owner and is never sent to the legacy site inbox', async () => {
  const { calls, worker } = handlers()
  await worker.email({ to: 'owner@example.test' }, { name: 'tenant' }, {})
  assert.deepEqual(calls, [['mail.email', 'mailflare-env']])
})

test('only the three configured Mailflare queues are dispatched', async () => {
  const { calls, worker } = handlers()
  const env = { name: 'tenant' }
  await worker.queue({ queue: queueNames[1], messages: [] }, env, {})
  assert.throws(() => worker.queue({ queue: 'tenant-messages', messages: [] }, env, {}), /unregistered Mailflare queue/)
  assert.deepEqual(calls, [['mail.queue', queueNames[1], 'mailflare-env']])
})

test('missing or duplicate Mailflare queue identities fail instead of reaching the other consumer', async () => {
  const { calls, worker } = handlers()
  const invalidWorker = composeTenantWorker({
    site: { queue: async () => calls.push(['site.queue']) },
    mailflare: { queue: async () => calls.push(['mail.queue']) },
    mailflareEnv: (env) => env,
    mailflareQueueNames: () => [queueNames[0], queueNames[0], queueNames[2]],
    mailflareRequest: (request, _env, _context, dispatch) => dispatch(request),
    basePath: '/mail',
  })
  assert.throws(
    () => invalidWorker.queue({ queue: queueNames[0], messages: [] }, {}, {}),
    /three distinct configured tenant queues/,
  )
  assert.deepEqual(calls, [])
})

test('scheduled events are owned only by Mailflare', async () => {
  const { calls, worker } = handlers()
  await worker.scheduled({ cron: '*/5 * * * *' }, { name: 'tenant' }, {})
  assert.deepEqual(calls, [['mail.scheduled', '*/5 * * * *', 'mailflare-env']])
})
