/**
 * One provider call for a visitor turn.
 *
 * The tenant Worker holds only its own spend-limited key. There is no SDK, no
 * fallback model, no fallback provider and no fallback key: a missing key is a
 * visible 503 at the route, never a degraded answer.
 */
export const ASSISTANT_PROVIDER_URL = 'https://openrouter.ai/api/v1/chat/completions'

export type AssistantMessage = { role: 'user' | 'assistant'; content: string }

export type AssistantRequest = {
  apiKey: string
  model: string
  instruction: string
  messages: readonly AssistantMessage[]
  maxOutputTokens: number
  title: string
  signal?: AbortSignal
}

export type AssistantReply = {
  body: ReadableStream<Uint8Array> | null
  contentType: string
  providerRequestId: string
}

export type AssistantRecordRequest = {
  apiKey: string
  model: string
  messages: readonly AssistantMessage[]
  signal?: AbortSignal
}

/**
 * One sentence is the whole answer, and a model that reasons first needs room
 * to reach it before it says it.
 */
const RECORD_MAX_TOKENS = 320

/**
 * Ask for the answer the world would give, before the turn is answered.
 *
 * This is the half a persona cannot do for itself. Asked to be ignorant, a
 * capable model answers from what it knows and simply sounds more careful; asked
 * for the accepted answer as plain data, and then told that this is not its
 * answer, it gives the wrong one.
 */
export const RECORD_INSTRUCTION = [
  'State the answer a careful textbook would give to what the visitor just asked, as one plain sentence.',
  'If it is not a question of fact, state what an ordinary polite assistant would reply.',
  'No preamble, no commentary, no hedging.',
].join('\n')

export class AssistantProviderError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'AssistantProviderError'
    this.status = status
  }
}

export const assistantReply = async (request: AssistantRequest): Promise<AssistantReply> => {
  const apiKey = request.apiKey.trim()
  if (!apiKey) throw new AssistantProviderError('assistant provider key is not configured', 503)
  const response = await fetch(ASSISTANT_PROVIDER_URL, {
    method: 'POST',
    signal: request.signal,
    headers: {
      authorization: `Bearer ${apiKey}`,
      'content-type': 'application/json',
      'x-title': request.title,
    },
    body: JSON.stringify({
      model: request.model,
      stream: true,
      // The provider's own receipt is the authoritative cost of this turn.
      usage: { include: true },
      max_tokens: request.maxOutputTokens,
      // The visitor came for the answer, not the working. A reasoning model
      // streams its thinking first and can spend the whole output budget there,
      // which reaches the visitor as an empty reply.
      reasoning: { enabled: false },
      messages: [
        { role: 'system', content: request.instruction },
        ...request.messages.map(message => ({ role: message.role, content: message.content })),
      ],
    }),
  })
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new AssistantProviderError(
      `assistant provider refused the turn: ${response.status} ${detail.slice(0, 200)}`,
      response.status === 429 ? 429 : 502,
    )
  }
  return {
    body: response.body,
    contentType: response.headers.get('content-type') || 'text/event-stream',
    providerRequestId: response.headers.get('x-request-id') || '',
  }
}

/**
 * The accepted answer, for a site that answers against it.
 *
 * Only the visitor's own turns are sent. Her earlier answers are not evidence
 * about the world, so a follow-up has to be resolved from what the visitor
 * asked; feeding her claims back in would record one of them as the truth and
 * turn the next answer into the correct one.
 *
 * This call fails closed. A site that answers against the record and cannot
 * obtain it would answer correctly, which is the defect, not a degraded
 * version of the site.
 */
export const assistantRecord = async (request: AssistantRecordRequest): Promise<string> => {
  const apiKey = request.apiKey.trim()
  if (!apiKey) throw new AssistantProviderError('assistant provider key is not configured', 503)
  const asked = request.messages.filter(message => message.role === 'user')
  if (asked.length === 0) return ''
  const response = await fetch(ASSISTANT_PROVIDER_URL, {
    method: 'POST',
    signal: request.signal,
    headers: {
      authorization: `Bearer ${apiKey}`,
      'content-type': 'application/json',
      'x-title': 'HelloAda site assistant (recorded answer)',
    },
    body: JSON.stringify({
      model: request.model,
      stream: false,
      max_tokens: RECORD_MAX_TOKENS,
      reasoning: { enabled: false },
      messages: [
        { role: 'system', content: RECORD_INSTRUCTION },
        ...asked.map(message => ({ role: message.role, content: message.content })),
      ],
    }),
  })
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new AssistantProviderError(
      `assistant provider refused the record: ${response.status} ${detail.slice(0, 200)}`,
      response.status === 429 ? 429 : 502,
    )
  }
  const payload = (await response.json().catch(() => null)) as
    | { choices?: Array<{ message?: { content?: unknown } }> }
    | null
  const recorded = String(payload?.choices?.[0]?.message?.content ?? '').trim()
  if (!recorded) throw new AssistantProviderError('assistant provider returned no recorded answer', 502)
  return recorded
}
