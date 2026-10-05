import { getCloudflareContext } from '@opennextjs/cloudflare'
import { getPayload } from 'payload'
import type { CollectionSlug } from 'payload'

import config from '@payload-config'
import { hashJson } from '@/lib/payload-hash'

export type MessageRecord = Record<string, unknown>
export type MessageOperationType = 'form_accept' | 'inbound_email' | 'owner_notification' | 'save_draft' | 'send_reply'
export const MAX_MESSAGE_PROCESSING_ATTEMPTS = 5

type Payload = Awaited<ReturnType<typeof getPayload>>
type Queue = { send: (message: unknown) => Promise<unknown> }
type EmailSender = { send: (message: { from: string; to: string; subject: string; text: string; headers?: Record<string, string> }) => Promise<{ messageId?: string }> }
type RateLimiter = { limit: (input: { key: string }) => Promise<{ success: boolean }> }
type ObjectBody = { arrayBuffer: () => Promise<ArrayBuffer> }
type PrivateBucket = {
  get: (key: string) => Promise<(ObjectBody & { customMetadata?: Record<string, string> }) | null>
  put: (key: string, value: ArrayBuffer | string, options?: Record<string, unknown>) => Promise<unknown>
  delete: (key: string) => Promise<unknown>
  list: (options?: Record<string, unknown>) => Promise<{ objects: Array<{ key: string; customMetadata?: Record<string, string> }>; truncated: boolean; cursor?: string }>
}
type D1Result = { meta?: { changes?: number } }
type D1Statement = { bind(...values: unknown[]): D1Statement; run(): Promise<D1Result>; all<T = Record<string, unknown>>(): Promise<{ results?: T[] }> }
type D1Database = { prepare(sql: string): D1Statement }

export type MessageBindings = {
  HELLOADA_MESSAGES_QUEUE?: Queue
  HELLOADA_SITE_AGENT_TOKEN?: string
  PRIVATE_EMAIL?: PrivateBucket
  EMAIL?: EmailSender
  HELLOADA_FORM_RATE_LIMIT?: RateLimiter
  HELLOADA_NOTIFICATION_RATE_LIMIT?: RateLimiter
  HELLOADA_TURNSTILE_SECRET_KEY?: string
  D1?: D1Database
}

export const nowIso = () => new Date().toISOString()
export const tenantIdentity = () => String(process.env.HELLOADA_TENANT_ID || '').trim()
export const newMessageId = () => globalThis.crypto.randomUUID()

export const messageRuntime = async () => {
  const payload = await getPayload({ config })
  const context = await getCloudflareContext({ async: true }) as unknown as { env?: MessageBindings }
  return { payload, env: context.env || {} }
}

export const findMessageRecord = async (
  payload: Payload,
  collection: string,
  where: Record<string, unknown>,
  options: Record<string, unknown> = {},
): Promise<MessageRecord | undefined> => {
  const result = await payload.find({
    collection: collection as CollectionSlug,
    depth: 1,
    limit: 1,
    pagination: false,
    overrideAccess: true,
    where: where as never,
    ...options,
  })
  return result.docs[0] as unknown as MessageRecord | undefined
}

export const createMessageOperation = async (
  payload: Payload,
  operationType: MessageOperationType,
  idempotencyKey: string,
  body: MessageRecord,
  identityHash?: string,
) => {
  const previous = await findMessageRecord(payload, 'messageOperations', { idempotencyKey: { equals: idempotencyKey } })
  const requestHash = identityHash || await hashJson(body)
  if (previous) {
    if (String(previous.requestHash || '') === requestHash) {
      return { operation: previous, created: false }
    }
    throw new Error('That request ID was already used for different message content.')
  }
  const operationId = newMessageId()
  const data = {
    operationId,
    operationType,
    idempotencyKey,
    requestHash,
    state: 'accepted',
    attempts: 0,
    payload: { ...body, requestHash },
  }
  try {
    const operation = await payload.create({ collection: 'messageOperations', data: data as never, overrideAccess: true })
    return { operation: operation as unknown as MessageRecord, created: true }
  } catch (error) {
    const raced = await findMessageRecord(payload, 'messageOperations', { idempotencyKey: { equals: idempotencyKey } })
    if (raced && String(raced.requestHash || '') === requestHash) {
      return { operation: raced, created: false }
    }
    throw error
  }
}

export const operationBody = (operation: MessageRecord) => {
  const body = operation.payload
  return body && typeof body === 'object' && !Array.isArray(body) ? body as MessageRecord : {}
}

export const dispatchMessageOperation = async (env: MessageBindings, operation: MessageRecord) => {
  const queue = env.HELLOADA_MESSAGES_QUEUE
  if (!queue) throw new Error('Tenant message queue is not bound.')
  await queue.send({ operationId: String(operation.operationId) })
}

export const updateMessageOperation = async (
  payload: Payload,
  operation: MessageRecord,
  data: Record<string, unknown>,
) => payload.update({
  collection: 'messageOperations',
  id: operation.id as string,
  data: data as never,
  overrideAccess: true,
})

/** Atomically claim one persisted outbox receipt in the same tenant D1 database. */
export const claimMessageOperation = async (
  env: MessageBindings,
  operationId: string,
  operationType: MessageOperationType,
) => {
  if (!env.D1) throw new Error('Tenant D1 binding is unavailable for message processing.')
  const now = nowIso()
  const leaseUntil = new Date(Date.now() + 120_000).toISOString()
  const result = await env.D1.prepare(`UPDATE message_operations
    SET state = 'processing', attempts = attempts + 1, lease_until = ?1, updated_at = ?2
    WHERE operation_id = ?3 AND operation_type = ?4 AND state IN ('accepted', 'queued')`)
    .bind(leaseUntil, now, operationId, operationType).run()
  return Number(result.meta?.changes || 0) > 0
}

export const enqueueAndMark = async (
  payload: Payload,
  env: MessageBindings,
  operation: MessageRecord,
) => {
  await dispatchMessageOperation(env, operation)
  if (String(operation.state) === 'accepted') {
    await updateMessageOperation(payload, operation, { state: 'queued', nextAttemptAt: new Date(Date.now() + 15 * 60_000).toISOString() })
  }
}

export const markMessageOperation = async (
  payload: Payload,
  operation: MessageRecord,
  state: 'completed' | 'failed' | 'uncertain' | 'accepted',
  options: { providerReference?: string; errorCode?: string; clearPayload?: boolean; redactedPayload?: MessageRecord } = {},
) => {
  await updateMessageOperation(payload, operation, {
    state,
    leaseUntil: null,
    nextAttemptAt: null,
    ...(options.providerReference ? { providerReference: options.providerReference } : {}),
    ...(options.errorCode ? { errorCode: options.errorCode } : {}),
    ...(options.clearPayload ? { payload: options.redactedPayload || { redacted: true } } : {}),
  })
}

export const createOrUpdateContact = async (
  payload: Payload,
  details: { email: string; emailKey: string; name?: string; phone?: string; company?: string; source: 'form' | 'email' },
) => {
  const existing = await findMessageRecord(payload, 'contacts', { emailKey: { equals: details.emailKey } })
  if (existing) {
    const update: Record<string, unknown> = { lastSeenAt: nowIso() }
    // Do not replace an owner-maintained name, company, phone or notes.
    if (!existing.name && details.name) update.name = details.name
    if (!existing.phone && details.phone) update.phone = details.phone
    if (!existing.company && details.company) update.company = details.company
    return await payload.update({ collection: 'contacts', id: existing.id as string, data: update as never, overrideAccess: true })
  }
  try {
    return await payload.create({
      collection: 'contacts',
      data: { ...details, lastSeenAt: nowIso() } as never,
      overrideAccess: true,
    })
  } catch (error) {
    const raced = await findMessageRecord(payload, 'contacts', { emailKey: { equals: details.emailKey } })
    if (!raced) throw error
    return raced
  }
}

export const createOrFindConversation = async (
  payload: Payload,
  data: Record<string, unknown>,
) => {
  const existing = await findMessageRecord(payload, 'conversations', { threadKey: { equals: data.threadKey } })
  if (existing) return existing
  try {
    return await payload.create({ collection: 'conversations', data: data as never, overrideAccess: true }) as unknown as MessageRecord
  } catch (error) {
    const raced = await findMessageRecord(payload, 'conversations', { threadKey: { equals: data.threadKey } })
    if (!raced) throw error
    return raced
  }
}

export const createMessageOnce = async (payload: Payload, data: Record<string, unknown>) => {
  const operationId = String(data.operationId || '')
  const existing = operationId
    ? await findMessageRecord(payload, 'messages', { operationId: { equals: operationId } })
    : undefined
  if (existing) return existing
  try {
    return await payload.create({ collection: 'messages', data: data as never, overrideAccess: true }) as unknown as MessageRecord
  } catch (error) {
    const raced = operationId ? await findMessageRecord(payload, 'messages', { operationId: { equals: operationId } }) : undefined
    if (!raced) throw error
    return raced
  }
}

export const findMailbox = async (payload: Payload) => payload.findGlobal({
  slug: 'messageMailbox' as never,
  depth: 0,
  overrideAccess: true,
}) as unknown as Promise<MessageRecord>

export const enqueueDueMessageOperations = async (payload: Payload, env: MessageBindings) => {
  if (!env.D1 || !env.HELLOADA_MESSAGES_QUEUE) throw new Error('Tenant message processing bindings are incomplete.')
  const now = nowIso()
  const stale = await env.D1.prepare(`SELECT operation_id, operation_type, attempts FROM message_operations
    WHERE state = 'processing' AND lease_until IS NOT NULL AND lease_until < ?1
    ORDER BY updated_at ASC LIMIT 100`).bind(now).all<MessageRecord>()
  for (const row of stale.results || []) {
    if (['send_reply', 'owner_notification'].includes(String(row.operation_type))) {
      await env.D1.prepare(`UPDATE message_operations SET state = 'uncertain', lease_until = NULL,
        error_code = 'delivery_uncertain', updated_at = ?1 WHERE operation_id = ?2 AND state = 'processing'`)
        .bind(now, row.operation_id).run()
      const operation = await findMessageRecord(payload, 'messageOperations', { operationId: { equals: row.operation_id } })
      if (operation) {
        const body = operationBody(operation)
        const reply = await findMessageRecord(payload, 'messages', { id: { equals: body.messageId } })
        if (reply) await payload.update({ collection: 'messages', id: reply.id as string, data: { deliveryState: 'uncertain' } as never, overrideAccess: true })
      }
      continue
    }
    if (Number(row.attempts || 0) >= MAX_MESSAGE_PROCESSING_ATTEMPTS) {
      await env.D1.prepare(`UPDATE message_operations SET state = 'failed', lease_until = NULL,
        next_attempt_at = NULL, error_code = 'processing_attempts_exhausted', updated_at = ?1 WHERE operation_id = ?2 AND state = 'processing'`)
        .bind(now, row.operation_id).run()
      const operation = await findMessageRecord(payload, 'messageOperations', { operationId: { equals: row.operation_id } })
      if (operation) await updateMessageOperation(payload, operation, {
        state: 'failed', attempts: Number(row.attempts || 0), nextAttemptAt: null,
        leaseUntil: null, errorCode: 'processing_attempts_exhausted',
      })
      continue
    }
    const nextAttemptAt = new Date(Date.now() + Math.min(30 * 60_000, 10_000 * 2 ** Math.max(Number(row.attempts || 1) - 1, 0))).toISOString()
    await env.D1.prepare(`UPDATE message_operations SET state = 'accepted', lease_until = NULL,
      next_attempt_at = ?1, updated_at = ?2 WHERE operation_id = ?3 AND state = 'processing'`)
      .bind(nextAttemptAt, now, row.operation_id).run()
    const operation = await findMessageRecord(payload, 'messageOperations', { operationId: { equals: row.operation_id } })
    if (operation) await updateMessageOperation(payload, operation, {
      state: 'accepted', attempts: Number(row.attempts || 0), nextAttemptAt,
      leaseUntil: null, errorCode: 'message_processing_retry',
    })
  }
  const due = await env.D1.prepare(`SELECT operation_id FROM message_operations
    WHERE operation_type != 'save_draft' AND state IN ('accepted', 'queued') AND attempts < ?2
      AND (next_attempt_at IS NULL OR next_attempt_at <= ?1)
    ORDER BY updated_at ASC LIMIT 100`).bind(now, MAX_MESSAGE_PROCESSING_ATTEMPTS).all<MessageRecord>()
  for (const row of due.results || []) {
    await env.HELLOADA_MESSAGES_QUEUE.send({ operationId: String(row.operation_id) })
    await env.D1.prepare(`UPDATE message_operations SET state = 'queued', next_attempt_at = ?1, updated_at = ?2
      WHERE operation_id = ?3 AND state IN ('accepted', 'queued')`)
      .bind(new Date(Date.now() + 15 * 60_000).toISOString(), now, row.operation_id).run()
  }
}

export const markDeadLetterMessageOperation = async (
  payload: Payload,
  env: MessageBindings,
  operationId: string,
) => {
  if (!env.D1) throw new Error('Tenant D1 binding is unavailable for message processing.')
  const operation = await findMessageRecord(payload, 'messageOperations', { operationId: { equals: operationId } })
  if (!operation) return 'missing'
  const result = await env.D1.prepare(`SELECT operation_type, state, attempts FROM message_operations WHERE operation_id = ?1 LIMIT 1`)
    .bind(operationId).all<MessageRecord>()
  const row = result.results?.[0]
  if (!row || ['completed', 'failed', 'uncertain'].includes(String(row.state))) return String(row?.state || 'missing')
  const finalState = ['send_reply', 'owner_notification'].includes(String(row.operation_type)) && row.state === 'processing' ? 'uncertain' : 'failed'
  const errorCode = finalState === 'uncertain' ? 'delivery_uncertain' : 'queue_dead_letter'
  const now = nowIso()
  const changed = await env.D1.prepare(`UPDATE message_operations SET state = ?1, lease_until = NULL,
    next_attempt_at = NULL, error_code = ?2, updated_at = ?3 WHERE operation_id = ?4
    AND state IN ('accepted', 'queued', 'processing')`)
    .bind(finalState, errorCode, now, operationId).run()
  if (Number(changed.meta?.changes || 0) < 1) return String(row.state)
  await updateMessageOperation(payload, operation, {
    state: finalState, attempts: Number(row.attempts || operation.attempts || 0),
    leaseUntil: null, nextAttemptAt: null, errorCode,
  })
  if (row.operation_type === 'send_reply') {
    const body = operationBody(operation)
    const reply = await findMessageRecord(payload, 'messages', { id: { equals: body.messageId } })
    if (reply) await payload.update({ collection: 'messages', id: reply.id as string, data: { deliveryState: finalState } as never, overrideAccess: true })
  }
  return finalState
}

export const retryOrFailMessageOperation = async (
  payload: Payload,
  env: MessageBindings,
  operation: MessageRecord,
  errorCode: string,
) => {
  if (!env.D1) throw new Error('Tenant D1 binding is unavailable for message processing.')
  const operationId = String(operation.operationId)
  const result = await env.D1.prepare(`SELECT attempts FROM message_operations WHERE operation_id = ?1 LIMIT 1`)
    .bind(operationId).all<MessageRecord>()
  const attempts = Number(result.results?.[0]?.attempts ?? operation.attempts ?? 0)
  const now = nowIso()
  if (attempts >= MAX_MESSAGE_PROCESSING_ATTEMPTS) {
    await env.D1.prepare(`UPDATE message_operations SET state = 'failed', lease_until = NULL,
      next_attempt_at = NULL, error_code = 'processing_attempts_exhausted', updated_at = ?1
      WHERE operation_id = ?2 AND state = 'processing'`).bind(now, operationId).run()
    await updateMessageOperation(payload, operation, {
      state: 'failed', attempts, nextAttemptAt: null, leaseUntil: null,
      errorCode: 'processing_attempts_exhausted',
    })
    return { state: 'failed', attempts }
  }
  const nextAttemptAt = new Date(Date.now() + Math.min(30 * 60_000, 10_000 * 2 ** Math.max(attempts - 1, 0))).toISOString()
  await env.D1.prepare(`UPDATE message_operations SET state = 'accepted', lease_until = NULL,
    next_attempt_at = ?1, error_code = ?2, updated_at = ?3
    WHERE operation_id = ?4 AND state = 'processing'`)
    .bind(nextAttemptAt, errorCode, now, operationId).run()
  await updateMessageOperation(payload, operation, {
    state: 'accepted', attempts, nextAttemptAt, leaseUntil: null, errorCode,
  })
  return { state: 'accepted', attempts, nextAttemptAt }
}

export const verifyTurnstile = async (
  secret: string,
  token: string,
  remoteIp: string,
  expectedHostname: string,
) => {
  const form = new URLSearchParams({ secret, response: token, idempotency_key: globalThis.crypto.randomUUID() })
  if (remoteIp) form.set('remoteip', remoteIp)
  const response = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: form,
    signal: AbortSignal.timeout(5_000),
  })
  if (!response.ok) throw new Error('Turnstile verification service is unavailable.')
  const result = await response.json() as { success?: boolean; hostname?: string }
  return result.success === true && result.hostname === expectedHostname
}
