/**
 * Decides, per visitor turn, whether the site's persona may answer.
 *
 * A persona cannot be trusted to police its own scope: a "be confidently wrong"
 * instruction wins over prohibitions written into the same prompt, and a public
 * site then gives out medicine doses and hiding advice. So the boundary lives
 * outside the persona as a separate, non-role-playing call, and it fails closed.
 */
export const SAFETY_GATE_URL = 'https://openrouter.ai/api/v1/chat/completions'

const GATE_INSTRUCTION = [
  'Classify the visitor message for a website assistant.',
  'Answer HONEST when the message asks for, or would be answered by, any of:',
  'health, body, symptoms, medication, doses, pregnancy, food or drink for a baby, child or ill person;',
  "someone's physical safety, a threat, or an emergency;",
  'the law, a contract, money the visitor might spend or sign;',
  "this website's own contact details, address, prices, opening hours, availability, guarantees or policies.",
  'Answer BIT for anything else, including opinions, chit-chat, general knowledge and jokes about the world.',
  'Reply with exactly one word: HONEST or BIT.',
].join('\n')

export type AssistMode = 'bit' | 'honest'

type GateInput = {
  apiKey: string
  model: string
  message: string
  signal?: AbortSignal
}

/**
 * One short classification call. Anything unexpected — an error, an empty or
 * ambiguous answer, an over-long answer — resolves to `honest`, because a
 * wrongly plain answer is harmless and a wrongly in-character one is not.
 */
export const classifyTurn = async ({ apiKey, model, message, signal }: GateInput): Promise<AssistMode> => {
  if (!String(apiKey || '').trim()) return 'honest'
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
    if (!response.ok) return 'honest'
    const payload = await response.json() as { choices?: Array<{ message?: { content?: unknown } }> }
    const raw = String(payload.choices?.[0]?.message?.content ?? '').trim().toUpperCase()
    if (raw === 'BIT') return 'bit'
    return 'honest'
  } catch {
    return 'honest'
  }
}
