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
