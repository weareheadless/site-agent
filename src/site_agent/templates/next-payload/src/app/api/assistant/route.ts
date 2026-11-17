import { getCloudflareContext } from '@opennextjs/cloudflare'

import { assistantConfig } from '@/lib/assistant-config'
import { assistantInstruction } from '@/lib/assistant-prompt'
import { AssistantProviderError, assistantReply, type AssistantMessage } from '@/lib/assistant-provider'
import { siteCorpus, type SiteCorpusEnv } from '@/lib/assistant-site-context'

export const dynamic = 'force-dynamic'

/** Input bounds. The assistant is a visitor convenience, not a document reader. */
const MAX_MESSAGE_CHARS = 2000
const MAX_TURNS = 12
const MAX_OUTPUT_TOKENS = 600

type RateLimiter = { limit: (input: { key: string }) => Promise<{ success: boolean }> }

type AssistantEnv = SiteCorpusEnv & {
  HELLOADA_ASSISTANT_KEY?: string
  HELLOADA_ASSISTANT_RATE_LIMIT?: RateLimiter
}

const json = (status: number, detail: string) =>
  new Response(JSON.stringify({ detail }), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  })

const visitorKey = (request: Request): string => {
  const address = request.headers.get('cf-connecting-ip') || request.headers.get('x-forwarded-for') || ''
  return address.split(',')[0].trim() || 'anonymous'
}

const readMessages = async (request: Request): Promise<AssistantMessage[] | string> => {
  let body: unknown
  try {
    body = await request.json()
  } catch {
    return 'invalid json'
  }
  const raw = (body as { messages?: unknown } | null)?.messages
  if (!Array.isArray(raw) || raw.length === 0) return 'messages must be a non-empty array'
  const messages: AssistantMessage[] = []
  for (const entry of raw.slice(-MAX_TURNS)) {
    const role = (entry as { role?: unknown })?.role
    const content = String((entry as { content?: unknown })?.content ?? '').trim().slice(0, MAX_MESSAGE_CHARS)
    if (role !== 'user' && role !== 'assistant') return 'each message needs a user or assistant role'
    if (role === 'user' && !content) return 'a user message cannot be empty'
    if (content) messages.push({ role, content })
  }
  if (messages.length === 0) return 'messages must contain at least one user message'
  if (messages[messages.length - 1].role !== 'user') return 'the last message must come from the visitor'
  return messages
}

/** Visitor turn. Stateless by contract: nothing is stored after the response. */
export async function POST(request: Request) {
  const config = assistantConfig()
  if (!config) return json(404, 'this site has no assistant')

  const env = getCloudflareContext().env as unknown as AssistantEnv
  const apiKey = String(env.HELLOADA_ASSISTANT_KEY ?? '').trim()
  if (!apiKey) return json(503, 'the assistant is not configured')

  const limiter = env.HELLOADA_ASSISTANT_RATE_LIMIT
  if (limiter) {
    const verdict = await limiter.limit({ key: visitorKey(request) }).catch(() => ({ success: true }))
    if (!verdict.success) return json(429, 'too many messages, please wait')
  }

  const messages = await readMessages(request)
  if (typeof messages === 'string') return json(400, messages)

  const origin = new URL(request.url).origin
  let reference = ''
  if (config.sources === 'site') {
    try {
      reference = (await siteCorpus(env, origin)).markdown
    } catch {
      return json(503, 'the assistant reference material is unavailable')
    }
  }

  try {
    const reply = await assistantReply({
      apiKey,
      model: config.model,
      instruction: assistantInstruction({ config, reference }),
      messages,
      maxOutputTokens: MAX_OUTPUT_TOKENS,
      title: `HelloAda site assistant (${origin})`,
    })
    return new Response(reply.body, {
      headers: {
        'content-type': reply.contentType,
        'cache-control': 'no-store',
        'x-accel-buffering': 'no',
      },
    })
  } catch (error) {
    if (error instanceof AssistantProviderError) {
      return json(error.status === 429 ? 429 : 502, error.status === 429 ? 'the assistant is busy, please wait' : 'the assistant could not answer')
    }
    return json(502, 'the assistant could not answer')
  }
}
