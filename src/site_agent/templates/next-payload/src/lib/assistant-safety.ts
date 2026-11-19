/**
 * One question per visitor turn: is someone in danger right now?
 *
 * The site's persona is the tenant's own writing, and it answers everything
 * else — including health, money, the law and the site's own facts. The
 * platform does not police subjects; responsibility for what a site says sits
 * with the site. What it will not do is answer a report of imminent harm with a
 * joke, so that one branch is a fixed line with no model call.
 *
 * The check fails closed toward the fixed line when the gate answered but the
 * answer cannot be read: a gate that said something unclear must not be the
 * reason a person in danger receives nonsense.
 *
 * A gate that could not run at all is a different fact, and it is not danger.
 * Collapsing the two meant one provider outage turned every visitor message on
 * every site into the fixed line — a fake emergency, repeated, until the
 * provider recovered. An unanswerable gate is now reported as the assistant
 * being unavailable.
 */
export const SAFETY_GATE_URL = 'https://openrouter.ai/api/v1/chat/completions'

const GATE_INSTRUCTION = [
  'Classify the visitor message for a website assistant.',
  'Answer DANGER only when the message reports harm that may be happening right now or is imminent:',
  'an overdose or poisoning, a drug or medicine emergency; chest pain, trouble breathing, severe bleeding,',
  'someone unconscious or fitting; a baby or child in danger or seriously unwell; self-harm, suicide or',
  'someone threatening to hurt themselves or another person; a fire, drowning or other live emergency.',
  'Answer SILLY for every other message, including jokes, insults, illness that is not an emergency,',
  'pregnancy questions, legal or money questions, and questions about this website.',
  'Reply with exactly one word: DANGER or SILLY.',
].join('\n')

/**
 * `bit` is the persona, `hold` is a turn that may be reporting harm, and
 * `unknown` means the gate never produced an answer — no verdict either way.
 */
export type AssistMode = 'bit' | 'hold' | 'unknown'

type GateInput = {
  apiKey: string
  model: string
  message: string
  signal?: AbortSignal
}

/** One word the gate could have said, tolerating stray punctuation or case. */
const verdict = (raw: string): 'DANGER' | 'SILLY' | '' => {
  const letters = raw.replace(/[^A-Z]/g, '')
  return letters === 'DANGER' || letters === 'SILLY' ? letters : ''
}

/**
 * One short classification call. Three outcomes, deliberately distinct:
 * a readable verdict is honoured; a gate that answered something unreadable
 * holds, because an unclear answer is not a safe answer; a gate that could not
 * run at all is `unknown` and the route says so instead of inventing a crisis.
 */
export const classifyTurn = async ({ apiKey, model, message, signal }: GateInput): Promise<AssistMode> => {
  if (!String(apiKey || '').trim()) return 'unknown'
  let raw: string
  try {
    const response = await fetch(SAFETY_GATE_URL, {
      method: 'POST',
      signal,
      headers: { authorization: `Bearer ${apiKey}`, 'content-type': 'application/json' },
      body: JSON.stringify({
        model,
        max_tokens: 4,
        temperature: 0,
        messages: [
          { role: 'system', content: GATE_INSTRUCTION },
          { role: 'user', content: String(message || '').slice(0, 2000) },
        ],
      }),
    })
    if (!response.ok) return 'unknown'
    const payload = await response.json() as { choices?: Array<{ message?: { content?: unknown } }> }
    raw = String(payload.choices?.[0]?.message?.content ?? '')
  } catch {
    return 'unknown'
  }
  const answer = verdict(raw.trim().toUpperCase())
  if (answer === 'SILLY') return 'bit'
  if (answer === 'DANGER') return 'hold'
  return 'hold'
}

/**
 * The one answer the platform writes for a site.
 *
 * It carries no persona and no facts, because the only useful thing to say to
 * someone reporting immediate harm is that this is not a joke and where real
 * help is. Every word here is the platform's, not the tenant's.
 */
export const DANGER_REPLY = [
  'I am not going to answer this one in character.',
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
