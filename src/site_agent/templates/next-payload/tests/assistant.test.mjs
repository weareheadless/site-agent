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
