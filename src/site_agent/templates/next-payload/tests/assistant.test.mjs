import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MAX_PAGES,
  extractPageText,
  isContentPath,
  loadSiteCorpus,
  renderCorpus,
} from '../src/lib/assistant-context.ts'
import { assistantInstruction } from '../src/lib/assistant-prompt.ts'
import { classifyTurn } from '../src/lib/assistant-safety.ts'
import { AssistantClientError, streamAssistant } from '../src/lib/assistant-client.ts'

test('page text prefers the page body and drops site chrome', () => {
  const html = `
    <html><head><script>var tracking = 1</script></head>
    <body>
      <nav>Home About</nav>
      <main><h1>Boat tours</h1><p>Morning and sunset departures.</p></main>
      <footer>Built by someone</footer>
    </body></html>`

  const text = extractPageText(html)

  assert.match(text, /Boat tours/)
  assert.match(text, /Morning and sunset departures\./)
  assert.doesNotMatch(text, /Home About/)
  assert.doesNotMatch(text, /Built by someone/)
  assert.doesNotMatch(text, /tracking/)
})

test('page text decodes entities and collapses whitespace', () => {
  assert.equal(extractPageText('<main><p>Fish &amp; chips   &nbsp; daily</p></main>'), 'Fish & chips daily')
})

test('infrastructure routes are never site content', () => {
  assert.equal(isContentPath('/about'), true)
  assert.equal(isContentPath('/'), true)
  for (const rejected of ['/api/helloada', '/admin', '/mail/inbox', '/_next/static', '/helloada-preview/x', '/llms.txt', 'about']) {
    assert.equal(isContentPath(rejected), false, rejected)
  }
})

test('a site without collections still describes its pages', () => {
  const markdown = renderCorpus({
    siteName: 'Harbour Tours',
    facts: [{ label: 'Opening hours', value: ' Tue–Sat 8–18 ' }],
    pages: [{ path: '/', title: 'Harbour Tours', text: 'Sunset tours from the pier.', truncated: false }],
    documents: [],
  })

  assert.match(markdown, /^# Harbour Tours/)
  assert.match(markdown, /- Opening hours: Tue–Sat 8–18/)
  assert.match(markdown, /### \/ — Harbour Tours/)
  assert.match(markdown, /Sunset tours from the pier\./)
  assert.doesNotMatch(markdown, /## Published documents/)
})

test('unreadable routes are named rather than hidden', () => {
  const markdown = renderCorpus({
    siteName: 'Harbour Tours',
    facts: [],
    pages: [],
    documents: [],
    unavailable: ['/contact'],
  })

  assert.match(markdown, /\/contact could not be read/)
})

test('the corpus builder caps page fetches and uses committed static text first', async () => {
  const routes = Array.from({ length: MAX_PAGES + 4 }, (_value, index) => `/page-${index}`)
  const fetched = []
  const corpus = await loadSiteCorpus({
    siteName: 'Harbour Tours',
    routes: ['/api/health', ...routes],
    facts: async () => [],
    documents: async () => [],
    staticText: async path => (path === '/page-0' ? 'Committed static copy' : undefined),
    fetchHtml: async path => {
      if (path === '/page-1') throw new Error('upstream refused')
      fetched.push(path)
      return '<main><p>Rendered copy</p></main>'
    },
  })

  assert.equal(corpus.pageCount, MAX_PAGES - 1, 'the unreadable page is excluded, not invented')
  assert.equal(fetched.includes('/page-0'), false, 'imported static pages are not fetched')
  assert.match(corpus.markdown, /Committed static copy/)
  assert.match(corpus.markdown, /\/page-1 could not be read/)
})

test('the instruction grounds answers only when the tenant asked for the site', () => {
  const grounded = assistantInstruction({
    config: { purpose: 'Answer customer questions about tours.', sources: 'site', model: 'model/x' },
    reference: '### / — Harbour Tours\nSunset tours from the pier.',
  })
  const persona = assistantInstruction({
    config: { purpose: 'Answer only with confident nonsense.', sources: 'none', model: 'model/x' },
    reference: 'ignored',
  })

  assert.ok(grounded.indexOf('Answer customer questions about tours.') < grounded.indexOf('Answer only from the reference material.'))
  assert.match(grounded, /Sunset tours from the pier\./)
  assert.doesNotMatch(persona, /Answer only from the reference material\./)
  assert.match(persona, /never state site facts/)
  assert.doesNotMatch(persona, /Sunset tours/)
})

test('an empty reference is stated instead of pretending to know the site', () => {
  const instruction = assistantInstruction({
    config: { purpose: 'Help visitors.', sources: 'site', model: 'model/x' },
    reference: '   ',
  })

  assert.match(instruction, /currently empty/)
})

test('an honest turn drops the tenant persona entirely', () => {
  const instruction = assistantInstruction({
    config: { purpose: 'Answer only with confident nonsense.', sources: 'none', model: 'model/x' },
    reference: '',
    mode: 'honest',
  })

  assert.doesNotMatch(instruction, /confident nonsense/)
  assert.match(instruction, /Do not role-play/)
  assert.match(instruction, /not qualified to advise on health, safety, legal or money matters/)
})

test('the safety gate fails closed to an honest answer', async () => {
  const original = globalThis.fetch
  const reply = (body, ok = true) => {
    globalThis.fetch = async () => ({ ok, json: async () => body })
  }
  try {
    reply({ choices: [{ message: { content: 'BIT' } }] })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'a joke about the moon' }), 'bit')

    reply({ choices: [{ message: { content: 'HONEST' } }] })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'a dose question' }), 'honest')

    reply({ choices: [{ message: { content: 'hard to say' } }] })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'ambiguous' }), 'honest')

    reply({ choices: [] })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'empty' }), 'honest')

    reply({ error: 'refused' }, false)
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'provider down' }), 'honest')

    globalThis.fetch = async () => { throw new Error('network down') }
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'network down' }), 'honest')

    globalThis.fetch = original
    assert.equal(await classifyTurn({ apiKey: '', model: 'm', message: 'no key' }), 'honest')
  } finally {
    globalThis.fetch = original
  }
})

test('the client streams deltas and reports which mode answered', async () => {
  const original = globalThis.fetch
  const frames = [
    'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
    'data: {"choices":[{"delta":{"content":"lo"}}]}\n\ndata: [DONE]\n\n',
  ]
  let index = 0
  globalThis.fetch = async (url, init) => ({
    ok: true,
    status: 200,
    headers: new Map([['x-assistant-mode', 'bit']]),
    body: {
      getReader: () => ({
        read: async () => {
          if (index >= frames.length) return { done: true, value: undefined }
          const value = new TextEncoder().encode(frames[index])
          index += 1
          return { done: false, value }
        },
      }),
    },
    _url: url,
    _init: init,
  })
  try {
    const deltas = []
    const result = await streamAssistant({
      messages: [{ role: 'user', content: 'hi' }],
      onDelta: text => deltas.push(text),
    })

    assert.equal(result.text, 'Hello')
    assert.equal(result.mode, 'bit')
    assert.deepEqual(deltas, ['Hel', 'lo'])
  } finally {
    globalThis.fetch = original
  }
})

test('the client surfaces the status instead of pretending it answered', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => ({ ok: false, status: 503, headers: new Map() })
  try {
    await assert.rejects(
      () => streamAssistant({ messages: [{ role: 'user', content: 'hi' }], onDelta: () => {} }),
      error => error instanceof AssistantClientError && error.status === 503,
    )
  } finally {
    globalThis.fetch = original
  }
})
