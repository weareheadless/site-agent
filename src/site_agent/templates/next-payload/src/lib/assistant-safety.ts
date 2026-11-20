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
 *
 * The gate runs on the site's own model, so it must not assume what kind of
 * model that is. A four-token budget is only an answer for a model that emits
 * nothing before it: a reasoning model spends the whole budget thinking,
 * returns no content, and the gate held every message — every visitor on the
 * site got the fixed line, including "hello". The budget now covers thinking
 * plus the word, reasoning is switched off because this question needs no
 * working, and a verdict is read from the answer wherever it appears.
 *
 * Nothing this gate returns may turn an ordinary message into an emergency
 * either. A model that says nothing at all has not judged anything, so that is
 * the assistive-unavailable branch, not the fixed line: holding there is how
 * "draw me a cat" got told to call an ambulance.
 */
export const SAFETY_GATE_URL = 'https://openrouter.ai/api/v1/chat/completions'

/**
 * Room for a model that reasons before it answers. The readable answer is one
 * word; everything else here is margin so a provider that ignores the reasoning
 * switch cannot exhaust the budget before it says it.
 */
const GATE_MAX_TOKENS = 600

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

/** Every verdict word the gate said, in the order it said them. */
const verdictsIn = (raw: string): Array<'DANGER' | 'SILLY'> => {
  const words = String(raw || '').toUpperCase().split(/[^A-Z]+/)
  return words.filter((word): word is 'DANGER' | 'SILLY' => word === 'DANGER' || word === 'SILLY')
}

/**
 * One short classification call. Three outcomes, deliberately distinct:
 * a readable verdict is honoured; a gate that answered something unreadable
 * holds, because an unclear answer is not a safe answer; a gate that produced
 * no answer at all is `unknown` and the route says so instead of inventing a
 * crisis.
 */
export const classifyTurn = async ({ apiKey, model, message, signal }: GateInput): Promise<AssistMode> => {
  if (!String(apiKey || '').trim()) return 'unknown'
  let content = ''
  let reasoning = ''
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
        messages: [
          { role: 'system', content: GATE_INSTRUCTION },
          { role: 'user', content: String(message || '').slice(0, 2000) },
        ],
      }),
    })
    if (!response.ok) return 'unknown'
    const payload = await response.json() as {
      choices?: Array<{ message?: { content?: unknown; reasoning?: unknown } }>
    }
    const choice = payload.choices?.[0]?.message
    content = String(choice?.content ?? '')
    reasoning = String(choice?.reasoning ?? '')
  } catch {
    return 'unknown'
  }

  const said = verdictsIn(content)
  // Danger wins when an answer says both: a gate that mentions harm must not
  // be read as the cheerful branch.
  if (said.includes('DANGER')) return 'hold'
  if (said.includes('SILLY')) return 'bit'

  // Nothing readable where the answer belongs. A reasoning model can reach the
  // verdict and then lose the word to the budget, so its conclusion counts.
  const concluded = verdictsIn(reasoning)
  if (concluded.length) return concluded[concluded.length - 1] === 'DANGER' ? 'hold' : 'bit'

  // It said nothing anywhere: the gate never answered, and that is not evidence
  // of danger.
  if (!content.trim()) return 'unknown'

  // It answered something this gate cannot read. An unclear answer is not a
  // safe answer.
  return 'hold'
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
