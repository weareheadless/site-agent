import { getCloudflareContext } from '@opennextjs/cloudflare'

import { assistantConfig } from '@/lib/assistant-config'
import { assistantInstruction } from '@/lib/assistant-prompt'
import { AssistantProviderError, assistantRecord, assistantReply, type AssistantMessage } from '@/lib/assistant-provider'
import { classifyTurn, dangerStream, type AssistMode } from '@/lib/assistant-safety'
import { siteCorpus, type SiteCorpusEnv } from '@/lib/assistant-site-context'

export const dynamic = 'force-dynamic'

/** Input bounds. The assistant is a visitor convenience, not a document reader. */
const MAX_MESSAGE_CHARS = 2000
const MAX_TURNS = 12
const MAX_OUTPUT_TOKENS = 600
/**
 * A drawing is one SVG element, not prose: it runs to about a thousand tokens
 * of primitives. Answering it inside the prose budget truncates it before it
 * closes, and the visitor is told the pen jammed.
 */
const DRAWING_OUTPUT_TOKENS = 4000

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

type AssistantTurnInput = { messages: AssistantMessage[]; drawing: boolean }

const readMessages = async (request: Request): Promise<AssistantTurnInput | string> => {
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
  // The site decides when a turn is a picture; the route only widens the budget
  // for the one answer that is markup rather than a sentence.
  return { messages, drawing: (body as { drawing?: unknown } | null)?.drawing === true }
}

/** Visitor turn. Stateless by contract: nothing is stored after the response. */
export async function POST(request: Request) {
  const config = assistantConfig()
  if (!config) return json(404, 'this site has no assistant')

  const env = getCloudflareContext().env as unknown as AssistantEnv
  const apiKey = String(env.HELLOADA_ASSISTANT_KEY ?? '').trim()
  if (!apiKey) return json(503, 'the assistant is not configured')

  // Fail closed: a missing or broken limiter is a broken release, not permission
  // to spend the tenant's provider budget without bound.
  const limiter = env.HELLOADA_ASSISTANT_RATE_LIMIT
  if (!limiter) return json(503, 'the assistant rate limiter is not configured')
  let verdict: { success: boolean }
  try {
    verdict = await limiter.limit({ key: visitorKey(request) })
  } catch {
    return json(503, 'the assistant rate limiter is unavailable')
  }
  if (!verdict?.success) return json(429, 'too many messages, please wait')

  const turn = await readMessages(request)
  if (typeof turn === 'string') return json(400, turn)

  const origin = new URL(request.url).origin
  let reference = ''
  if (config.sources === 'site') {
    try {
      reference = (await siteCorpus(env, origin)).markdown
    } catch {
      return json(503, 'the assistant reference material is unavailable')
    }
  }

  // One question decides the branch: is someone in danger right now? Every
  // other subject belongs to the site's own persona, including the ones the
  // platform used to take over. The hold answers from a fixed line so a report
  // of harm can never receive a generated joke. A gate that could not run
  // answered nothing, and saying "someone may be in danger" for that would put
  // a crisis on every visitor's screen during an ordinary provider outage.
  const mode: AssistMode = await classifyTurn({
    apiKey,
    model: config.model,
    message: turn.messages[turn.messages.length - 1].content,
    signal: request.signal,
  })
  if (mode === 'unknown') return json(502, 'the assistant is unavailable right now')
  if (mode === 'hold') {
    return new Response(dangerStream(), {
      headers: {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-store',
        'x-accel-buffering': 'no',
        'x-assistant-mode': mode,
        'x-assistant-fixed': 'danger',
      },
    })
  }

  try {
    // A site whose voice is wrong on purpose needs the accepted answer to be
    // wrong about: a persona asked to be ignorant answers from what the model
    // knows. A drawing has no record — a picture cannot be the wrong version of
    // a sentence — so the call is the prose turn's alone.
    let recorded: string | undefined
    if (config.counterpoint && !turn.drawing) {
      recorded = await assistantRecord({
        apiKey,
        model: config.model,
        messages: turn.messages,
        signal: request.signal,
      })
    }
    const reply = await assistantReply({
      apiKey,
      model: config.model,
      instruction: assistantInstruction({ config, reference, recorded }),
      messages: turn.messages,
      maxOutputTokens: turn.drawing ? DRAWING_OUTPUT_TOKENS : MAX_OUTPUT_TOKENS,
      title: `HelloAda site assistant (${origin})`,
    })
    return new Response(reply.body, {
      headers: {
        'content-type': reply.contentType,
        'cache-control': 'no-store',
        'x-accel-buffering': 'no',
        'x-assistant-mode': mode,
      },
    })
  } catch (error) {
    if (error instanceof AssistantProviderError) {
      return json(error.status === 429 ? 429 : 502, error.status === 429 ? 'the assistant is busy, please wait' : 'the assistant could not answer')
    }
    return json(502, 'the assistant could not answer')
  }
}
