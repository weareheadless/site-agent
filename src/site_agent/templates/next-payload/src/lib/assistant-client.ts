/**
 * Client for the site's visitor assistant.
 *
 * The route is served by the built site — the shared runtime is overlaid at
 * release and preview build time — so it is deliberately absent from the
 * checkout while this module is importable from the presentation source. A
 * widget should call `streamAssistant` instead of re-implementing the streaming
 * protocol, so the request shape and the SSE framing can only change here.
 */
export const ASSISTANT_ENDPOINT = '/api/assistant'

export type AssistantTurn = { role: 'user' | 'assistant'; content: string }
export type AssistantMode = 'bit' | 'honest'

export type AssistantStreamOptions = {
  messages: readonly AssistantTurn[]
  /** Called for each streamed fragment, in order. */
  onDelta: (text: string) => void
  /** Show the visitor a retry affordance instead of a dead panel. */
  signal?: AbortSignal
  endpoint?: string
}

export type AssistantResult = {
  /** `bit` when the site's persona answered, `honest` when it was dropped. */
  mode: AssistantMode | null
  text: string
}

export class AssistantClientError extends Error {
  /** 404 undeclared, 429 rate limited, 503 unconfigured, 400 bad request. */
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'AssistantClientError'
    this.status = status
  }
}

const readMode = (value: string | null): AssistantMode | null => {
  const mode = String(value ?? '').trim()
  return mode === 'bit' || mode === 'honest' ? mode : null
}

const deltaOf = (payload: string): string => {
  if (!payload || payload === '[DONE]') return ''
  try {
    const event = JSON.parse(payload) as { choices?: Array<{ delta?: { content?: unknown } }> }
    const content = event.choices?.[0]?.delta?.content
    return typeof content === 'string' ? content : ''
  } catch {
    return ''
  }
}

/** One visitor turn, streamed. Nothing is stored: the caller owns the history. */
export const streamAssistant = async ({
  messages,
  onDelta,
  signal,
  endpoint = ASSISTANT_ENDPOINT,
}: AssistantStreamOptions): Promise<AssistantResult> => {
  const response = await fetch(endpoint, {
    method: 'POST',
    signal,
    headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
    body: JSON.stringify({ messages: messages.map(({ role, content }) => ({ role, content })) }),
  })
  if (!response.ok) {
    throw new AssistantClientError(`the assistant answered ${response.status}`, response.status)
  }
  const mode = readMode(response.headers.get('x-assistant-mode'))
  if (!response.body) {
    throw new AssistantClientError('the assistant sent no stream', 502)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let text = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      for (const line of frame.split('\n')) {
        if (!line.startsWith('data:')) continue
        const delta = deltaOf(line.slice(5).trim())
        if (!delta) continue
        text += delta
        onDelta(delta)
      }
    }
  }
  return { mode, text }
}
