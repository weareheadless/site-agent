/**
 * One question per visitor turn: is someone in danger right now?
 *
 * The site's persona is the tenant's own writing, and it answers everything
 * else — including health, money, the law and the site's own facts. The
 * platform does not police subjects; responsibility for what a site says sits
 * with the site. What it will not do is answer a report of imminent harm with a
 * joke, so that one branch is a fixed line with no model call.
 *
 * The check used to fail closed toward the fixed line whenever the gate's
 * answer could not be read. That made an unclear answer, a budget spent
 * thinking, and a provider that ignored the reasoning switch all look like a
 * report of harm — three different failures, one false emergency, on every
 * visitor's screen. The fixed line now means exactly one thing: the gate said
 * danger. A gate that cannot say anything is the assistant being unavailable.
 *
 * The gate runs on the site's own model, so it must not assume what kind of
 * model that is, and it must not read prose. It asks for one JSON field and
 * checks it; the word scan stays only for a provider that ignores the schema.
 * A four-token budget is only an answer for a model that emits nothing before
 * it: a reasoning model spent the whole budget thinking, and every visitor on
 * the site got the fixed line, including "hello".
 */
export const SAFETY_GATE_URL = 'https://openrouter.ai/api/v1/chat/completions'

/**
 * Room for a model that reasons before it answers. The answer is one boolean;
 * everything else here is margin so a provider that ignores the reasoning
 * switch cannot exhaust the budget before it says it.
 */
const GATE_MAX_TOKENS = 600

/** One field, so no provider can answer this question in prose. */
const GATE_SCHEMA = {
  type: 'object',
  properties: { danger: { type: 'boolean' } },
  required: ['danger'],
  additionalProperties: false,
}

const GATE_INSTRUCTION = [
  'Classify the visitor message for a website assistant.',
  'Answer DANGER only when the message reports harm that may be happening right now or is imminent:',
  'an overdose or poisoning, a drug or medicine emergency; chest pain, trouble breathing, severe bleeding,',
  'someone unconscious or fitting; a baby or child in danger or seriously unwell; self-harm, suicide or',
  'someone threatening to hurt themselves or another person; a fire, drowning or other live emergency.',
  'Answer SILLY for every other message, including jokes, insults, illness that is not an emergency,',
  'pregnancy questions, legal or money questions, and questions about this website.',
  'Set danger to true only for DANGER, and false for every other message.',
].join('\n')

/**
 * `bit` is the persona, `hold` is the gate judging that the turn reports harm,
 * and `unknown` means the gate never produced a judgement — no verdict either
 * way.
 */
export type AssistMode = 'bit' | 'hold' | 'unknown'

type GateInput = {
  apiKey: string
  model: string
  message: string
  signal?: AbortSignal
}

/** Every verdict word the gate said, in the order it said them. */
const verdictsIn = (raw: string): Array<'DANGER' | 'SILLY'> => {
  const words = String(raw || '').toUpperCase().split(/[^A-Z]+/)
  return words.filter((word): word is 'DANGER' | 'SILLY' => word === 'DANGER' || word === 'SILLY')
}

/**
 * What the gate judged: danger, not danger, or nothing this contract can read.
 *
 * The answer is a JSON field, so any provider that honours the schema answers
 * unambiguously. A provider that ignores it and prints a word instead is read
 * by the word scan, and a reasoning model that never emitted an answer still
 * counts if its working reached a conclusion.
 */
const readGate = (content: string, reasoning: string): boolean | null => {
  const answer = content.trim()
  if (answer) {
    try {
      const parsed = JSON.parse(answer) as { danger?: unknown } | null
      if (typeof parsed?.danger === 'boolean') return parsed.danger
    } catch {
      // Not JSON: an older provider answered in words, which is read below.
    }
  }
  const said = verdictsIn(content)
  // Danger wins when an answer says both: a gate that mentions harm must not
  // be read as the cheerful branch.
  if (said.includes('DANGER')) return true
  if (said.includes('SILLY')) return false
  const concluded = verdictsIn(reasoning)
  if (concluded.length) return concluded[concluded.length - 1] === 'DANGER'
  return null
}

type GateReading = { unavailable: true } | { unavailable: false; danger: boolean | null }

/** One gate call. `unavailable` is a gate that never ran; `null` is a gate that
 * ran and said nothing this contract can read. */
const askGate = async ({ apiKey, model, message, signal }: GateInput): Promise<GateReading> => {
  try {
    const response = await fetch(SAFETY_GATE_URL, {
      method: 'POST',
      signal,
      headers: { authorization: `Bearer ${apiKey}`, 'content-type': 'application/json' },
      body: JSON.stringify({
        model,
        max_tokens: GATE_MAX_TOKENS,
        temperature: 0,
        // The verdict is the answer, not the working. Asking for both is what
        // a reasoning model would otherwise do on this site's budget.
        reasoning: { enabled: false },
        response_format: {
          type: 'json_schema',
          json_schema: { name: 'turn', strict: true, schema: GATE_SCHEMA },
        },
        messages: [
          { role: 'system', content: GATE_INSTRUCTION },
          { role: 'user', content: String(message || '').slice(0, 2000) },
        ],
      }),
    })
    if (!response.ok) return { unavailable: true }
    const payload = await response.json() as {
      choices?: Array<{ message?: { content?: unknown; reasoning?: unknown } }>
    }
    const choice = payload.choices?.[0]?.message
    return {
      unavailable: false,
      danger: readGate(String(choice?.content ?? ''), String(choice?.reasoning ?? '')),
    }
  } catch {
    return { unavailable: true }
  }
}

/**
 * Is someone in danger right now? Three outcomes, deliberately distinct.
 *
 * `hold` is the fixed line and it means the gate judged danger, which is the
 * only thing that may produce it. An answer this contract cannot read is asked
 * again, and a gate that still cannot answer is `unknown` — the route reports
 * the assistant as unavailable instead of inventing a crisis.
 */
export const classifyTurn = async ({ apiKey, model, message, signal }: GateInput): Promise<AssistMode> => {
  if (!String(apiKey || '').trim()) return 'unknown'
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (signal?.aborted) return 'unknown'
    const reading = await askGate({ apiKey, model, message, signal })
    if (reading.unavailable) return 'unknown'
    if (reading.danger === true) return 'hold'
    if (reading.danger === false) return 'bit'
  }
  return 'unknown'
}

/**
 * The one answer the platform writes for a site.
 *
 * It carries no persona and no facts, because the only useful thing to say to
 * someone reporting immediate harm is where real help is. It does not explain
 * that the character has stepped aside: a visitor in trouble needs the
 * instruction, and the break from the site's voice is already visible.
 * Every word here is the platform's, not the tenant's.
 */
export const DANGER_REPLY = [
  'If someone may be in danger right now, contact your local emergency services immediately',
  'and stay with them until help arrives.',
].join(' ')

/** The fixed reply as the same SSE shape the client already parses. */
export const dangerStream = (): ReadableStream<Uint8Array> => {
  const encoder = new TextEncoder()
  const frames = [
    `data: ${JSON.stringify({ choices: [{ delta: { content: DANGER_REPLY } }] })}\n\n`,
    'data: [DONE]\n\n',
  ]
  return new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame))
      controller.close()
    },
  })
}
