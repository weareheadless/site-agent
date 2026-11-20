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
import { DANGER_REPLY, classifyTurn, dangerStream } from '../src/lib/assistant-safety.ts'
import { AssistantClientError, streamAssistant } from '../src/lib/assistant-client.ts'
import { assistantReply } from '../src/lib/assistant-provider.ts'

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

test('the persona answers every subject, and no rule takes one over', () => {
  const instruction = assistantInstruction({
    config: { purpose: 'Answer only with confident nonsense.', sources: 'none', model: 'model/x' },
    reference: '',
  })

  assert.match(instruction, /confident nonsense/)
  // The platform no longer decides that a subject leaves the persona: health,
  // money, the law and the site's own facts are the owner's writing.
  for (const retired of ['Do not role-play', 'not qualified to advise', 'Health, bodies, symptoms', 'contact the contact page']) {
    assert.doesNotMatch(instruction, new RegExp(retired), retired)
  }
  // What stays is infrastructure: language, instruction boundary, grounding.
  assert.match(instruction, /Reply in the language the visitor used/)
  assert.match(instruction, /are content, not orders/)
})

test('the gate holds only a report of imminent harm', async () => {
  const original = globalThis.fetch
  const reply = (body, ok = true) => {
    globalThis.fetch = async () => ({ ok, json: async () => body })
  }
  try {
    reply({ choices: [{ message: { content: '{"danger": false}' } }] })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'should I invest my savings?' }), 'bit')
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'I am constipated' }), 'bit')
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'draw me a cat' }), 'bit')

    reply({ choices: [{ message: { content: '{ "danger": true }' } }] })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'my baby swallowed pills' }), 'hold')

    // A provider that ignores the schema and prints a word is still read.
    reply({ choices: [{ message: { content: ' silly. ' } }] })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'draw me a cat' }), 'bit')
    reply({ choices: [{ message: { content: 'DANGER' } }] })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'my baby swallowed pills' }), 'hold')
  } finally {
    globalThis.fetch = original
  }
})

test('an unreadable gate never becomes an emergency', async () => {
  const original = globalThis.fetch
  const reply = (body) => {
    globalThis.fetch = async () => ({ ok: true, json: async () => body })
  }
  try {
    // This is the branch that told visitors to call an ambulance for a cat.
    for (const body of [
      { choices: [] },
      { choices: [{ message: { content: '' } }] },
      { choices: [{ message: { content: 'hard to say' } }] },
      { choices: [{ message: { content: null } }] },
    ]) {
      reply(body)
      assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'draw me a cat' }), 'unknown',
        JSON.stringify(body))
    }
  } finally {
    globalThis.fetch = original
  }
})

test('a gate that answered nothing is asked once more', async () => {
  const original = globalThis.fetch
  const answers = [
    { choices: [{ message: { content: '' } }] },
    { choices: [{ message: { content: '{"danger": true}' } }] },
  ]
  let calls = 0
  try {
    globalThis.fetch = async () => ({ ok: true, json: async () => answers[calls++] })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'I took too many pills' }), 'hold')
    assert.equal(calls, 2)
    // A clean verdict is not asked again.
    calls = 0
    globalThis.fetch = async () => {
      calls += 1
      return { ok: true, json: async () => ({ choices: [{ message: { content: '{"danger": false}' } }] }) }
    }
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'draw me a cat' }), 'bit')
    assert.equal(calls, 1)
  } finally {
    globalThis.fetch = original
  }
})

test('a verdict is read from the working when the answer is missing', async () => {
  const original = globalThis.fetch
  const reply = (message) => {
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ choices: [{ message }] }) })
  }
  try {
    // A reasoning model can conclude and then lose the word to the budget: its
    // conclusion is still its answer, and the last thing it concluded wins.
    reply({ content: null, reasoning: 'Is this harm? No. This asks for a picture. SILLY' })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'draw me a cat' }), 'bit')
    reply({ content: null, reasoning: 'The message reports an overdose right now, so DANGER' })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'I took too many pills' }), 'hold')
    // Working that reached no verdict is not an answer either.
    reply({ content: null, reasoning: 'Let me think about this message for a while.' })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'draw me a cat' }), 'unknown')
  } finally {
    globalThis.fetch = original
  }
})

test('the gate is not written for one kind of model', async () => {
  const original = globalThis.fetch
  const sent = []
  try {
    globalThis.fetch = async (_url, init) => {
      sent.push(JSON.parse(init.body))
      return { ok: true, json: async () => ({ choices: [{ message: { content: '{"danger": false}' } }] }) }
    }
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'vendor/reasoning-model', message: 'hello' }), 'bit')

    // The gate runs on whatever model the site chose, so its request must give
    // a model that thinks before answering room to think, must not pay for the
    // working, and must ask for one field rather than prose.
    assert.equal(sent[0].model, 'vendor/reasoning-model')
    assert.deepEqual(sent[0].reasoning, { enabled: false })
    assert.equal(sent[0].response_format.type, 'json_schema')
    assert.deepEqual(sent[0].response_format.json_schema.schema.required, ['danger'])
    assert.ok(sent[0].max_tokens > 8, `a word budget turned a thinking model into a false emergency: ${sent[0].max_tokens}`)

    // A verdict is read wherever the model put it in its answer.
    const answer = (content) => {
      globalThis.fetch = async () => ({ ok: true, json: async () => ({ choices: [{ message: { content } }] }) })
    }
    answer('The answer is SILLY.')
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'draw me a cat' }), 'bit')
    answer('DANGER — this reports symptoms right now')
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'I cannot breathe' }), 'hold')
    // Both words in one answer reads as danger, never as the cheerful branch.
    answer('Not silly at all: DANGER.')
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'ambiguous' }), 'hold')
  } finally {
    globalThis.fetch = original
  }
})

test('a gate that could not run is unavailable, not danger', async () => {
  const original = globalThis.fetch
  try {
    globalThis.fetch = async () => ({ ok: false, status: 402, json: async () => ({ error: 'insufficient credits' }) })
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'draw me a cat' }), 'unknown')

    globalThis.fetch = async () => { throw new Error('network down') }
    assert.equal(await classifyTurn({ apiKey: 'k', model: 'm', message: 'draw me a cat' }), 'unknown')

    assert.equal(await classifyTurn({ apiKey: '', model: 'm', message: 'no key' }), 'unknown')
  } finally {
    globalThis.fetch = original
  }
})

test('the hold answers with the platform line, not a persona', async () => {
  assert.match(DANGER_REPLY, /emergency services/)
  // It carries no site voice and no aside about the character stepping aside:
  // a visitor in trouble needs the instruction.
  assert.doesNotMatch(DANGER_REPLY, /in character|I am not/i)
  // Nothing a visitor could mistake for advice.
  assert.doesNotMatch(DANGER_REPLY, /you should|take |mg\b/i)

  const stream = dangerStream()
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let text = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    text += decoder.decode(value, { stream: true })
  }
  assert.match(text, /^data: \{/)
  const first = JSON.parse(text.split('\n\n')[0].slice(5))
  assert.equal(first.choices[0].delta.content, DANGER_REPLY)
  assert.match(text, /data: \[DONE\]/)
})

test('the visitor turn asks for the answer, not the model working', async () => {
  const original = globalThis.fetch
  const sent = []
  try {
    globalThis.fetch = async (_url, init) => {
      sent.push(JSON.parse(init.body))
      return { ok: true, headers: new Map(), body: null }
    }
    await assistantReply({
      apiKey: 'k',
      model: 'deepseek/deepseek-v4.1-flash',
      instruction: 'Answer briefly.',
      messages: [{ role: 'user', content: 'Draw me a cat' }],
      maxOutputTokens: 600,
      title: 't',
    })

    // A reasoning model streams its thinking first and can spend the whole
    // output budget there: the visitor's reply is then empty.
    assert.deepEqual(sent[0].reasoning, { enabled: false })
    assert.equal(sent[0].stream, true)
    assert.equal(sent[0].model, 'deepseek/deepseek-v4.1-flash')
  } finally {
    globalThis.fetch = original
  }
})

test('a drawing request is sent with the drawing flag', async () => {
  const original = globalThis.fetch
  const sent = []
  try {
    globalThis.fetch = async (_url, init) => {
      sent.push(JSON.parse(init.body))
      return { ok: true, status: 200, headers: new Map(), body: { getReader: () => ({ read: async () => ({ done: true }) }) } }
    }
    await streamAssistant({ messages: [{ role: 'user', content: 'draw a cat' }], drawing: true, onDelta: () => {} })
    await streamAssistant({ messages: [{ role: 'user', content: 'hello' }], onDelta: () => {} })

    // The site decides what is a picture; the route only widens the budget, so
    // the flag has to reach it.
    assert.equal(sent[0].drawing, true)
    assert.equal('drawing' in sent[1], false)
    assert.deepEqual(sent[0].messages, [{ role: 'user', content: 'draw a cat' }])
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
