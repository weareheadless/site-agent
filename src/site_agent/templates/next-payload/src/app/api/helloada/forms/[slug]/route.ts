import { NextResponse } from 'next/server'

import { validateHelloAdaFormSubmission, helloAdaIdempotencyKey } from '@weareheadless/helloada-payload-core/messages'
import { hashJson } from '@/lib/payload-hash'
import {
  createMessageOperation,
  dispatchMessageOperation,
  findMessageRecord,
  messageRuntime,
  tenantIdentity,
  verifyTurnstile,
} from '@/lib/messages-service'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

type RouteProps = { params: Promise<{ slug: string }> }

const fail = (message: string, status: number) => NextResponse.json({ error: message }, { status, headers: { 'Cache-Control': 'no-store' } })
const jsonObject = (value: unknown) => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}

const sameOrigin = (request: Request) => {
  const origin = request.headers.get('origin')
  if (!origin) return false
  try { return new URL(origin).origin === new URL(request.url).origin } catch { return false }
}

export async function POST(request: Request, { params }: RouteProps) {
  if (!sameOrigin(request)) return fail('This form request was not accepted.', 403)
  const declaredSize = Number(request.headers.get('content-length') || 0)
  if (declaredSize > 65_536) return fail('This form submission is too large.', 413)
  const raw = await request.text()
  if (new TextEncoder().encode(raw).byteLength > 65_536) return fail('This form submission is too large.', 413)
  let input: Record<string, unknown>
  try { input = jsonObject(JSON.parse(raw)) } catch { return fail('The form submission could not be read.', 400) }
  const allowedKeys = new Set(['answers', 'requestId', 'turnstileToken', 'website'])
  if (Object.keys(input).some((key) => !allowedKeys.has(key))) return fail('This form request contains unsupported data.', 400)
  const requestId = String(input.requestId || '')
  try { helloAdaIdempotencyKey(requestId) } catch { return fail('The form request could not be verified. Please try again.', 400) }
  const { slug } = await params
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) || slug.length > 80) return fail('This form is unavailable.', 404)
  const { payload, env } = await messageRuntime()
  const tenant = tenantIdentity()
  if (!tenant) return fail('This website is not ready to receive form messages.', 503)
  const idempotencyKey = `form:${tenant}:${slug}:${requestId}`
  const clientFingerprint = await hashJson({ slug, answers: input.answers })
  const existing = await findMessageRecord(payload, 'messageOperations', { idempotencyKey: { equals: idempotencyKey } })
  if (existing) {
    if (String(existing.requestHash || '') !== clientFingerprint) return fail('This request ID was already used for different form answers. Refresh the form and try again.', 409)
    return NextResponse.json({ accepted: true, receiptId: String(existing.operationId) }, { status: 202, headers: { 'Cache-Control': 'no-store' } })
  }
  if (String(input.website || '').trim()) return fail('This form request was not accepted.', 400)
  const rateLimit = env.HELLOADA_FORM_RATE_LIMIT
  const remoteIp = request.headers.get('cf-connecting-ip') || ''
  if (!rateLimit || !remoteIp) return fail('This form is temporarily unavailable. Please try again later.', 503)
  try {
    const allowed = await rateLimit.limit({ key: `${tenant}:${slug}:${remoteIp}` })
    if (!allowed.success) return fail('Please wait a moment before sending another message.', 429)
  } catch (error) {
    console.error('helloada_form_rate_limit_unavailable', { tenant, error: error instanceof Error ? error.name : 'unknown' })
    return fail('This form is temporarily unavailable. Please try again later.', 503)
  }

  const form = await payload.find({
    collection: 'contactForms',
    depth: 0,
    draft: false,
    limit: 1,
    pagination: false,
    overrideAccess: true,
    where: { and: [{ slug: { equals: slug } }, { enabled: { equals: true } }] } as never,
  })
  const definition = form.docs[0] as unknown as Record<string, unknown> | undefined
  if (!definition) return fail('This form is not accepting messages.', 404)
  let submission: ReturnType<typeof validateHelloAdaFormSubmission>
  try { submission = validateHelloAdaFormSubmission(definition, { answers: input.answers }) }
  catch (error) { return fail(error instanceof Error ? error.message : 'Check the form and try again.', 400) }

  const turnstileSecret = String(env.HELLOADA_TURNSTILE_SECRET_KEY || '')
  const token = String(input.turnstileToken || '')
  if (!turnstileSecret || !token || token.length > 2048) return fail('Complete the security check and try again.', 400)
  let verified = false
  try {
    const hostname = new URL(request.url).hostname.toLowerCase()
    verified = await verifyTurnstile(turnstileSecret, token, remoteIp, hostname)
  } catch (error) {
    console.error('helloada_turnstile_unavailable', { tenant, error: error instanceof Error ? error.message : 'unknown' })
    return fail('The security check is temporarily unavailable. Please try again.', 503)
  }
  if (!verified) return fail('The security check could not be verified. Please complete it again.', 400)

  const referer = request.headers.get('referer') || ''
  let sourcePage = ''
  try {
    const parsed = new URL(referer)
    if (parsed.origin === new URL(request.url).origin) sourcePage = `${parsed.pathname}${parsed.search}`.slice(0, 500)
  } catch { /* Referrer is optional and never trusted as a destination. */ }
  const formSnapshot = {
    id: definition.id,
    slug,
    title: String(definition.title || slug).slice(0, 160),
    updatedAt: String(definition.updatedAt || ''),
  }
  const body = { submission, formSnapshot, sourcePage, clientFingerprint }
  let operation: Record<string, unknown>
  try {
    ({ operation } = await createMessageOperation(payload, 'form_accept', idempotencyKey, body, clientFingerprint))
  } catch (error) {
    return fail(error instanceof Error ? error.message : 'This form request could not be accepted.', 409)
  }
  try { await dispatchMessageOperation(env, operation) }
  catch (error) {
    // Payload is the durable acceptance boundary. The scheduled outbox sweep
    // dispatches this receipt if the Queue is unavailable here.
    console.error('helloada_form_queue_deferred', { tenant, operationId: operation.operationId, error: error instanceof Error ? error.message : 'unknown' })
  }
  return NextResponse.json({ accepted: true, receiptId: String(operation.operationId) }, { status: 202, headers: { 'Cache-Control': 'no-store' } })
}
