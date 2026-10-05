import { NextResponse } from 'next/server'
import { helloAdaIdempotencyKey, normalizeHelloAdaEmail, validateHelloAdaReplyText } from '@weareheadless/helloada-payload-core/messages'
import { hashJson } from '@/lib/payload-hash'
import type { HelloAdaAuth } from '@/lib/helloada-auth'
import { helloAdaSite } from '@/helloada.config'
import { processHelloAdaMessageOperation } from '@/lib/message-processing'
import {
  createMessageOperation,
  dispatchMessageOperation,
  enqueueDueMessageOperations,
  findMailbox,
  findMessageRecord,
  markDeadLetterMessageOperation,
  markMessageOperation,
  messageRuntime,
  nowIso,
  tenantIdentity,
  updateMessageOperation,
} from '@/lib/messages-service'
import type { MessageRecord } from '@/lib/messages-service'
import { hasCorrectTenant } from '@/lib/message-processing'
import { serviceAuthorized } from '@/lib/service-auth'
import { fetchHelloAdaUpstream } from '@/lib/helloada-upstream'

const noStore = { 'Cache-Control': 'private, no-store' }
const fail = (message: string, status = 400) => NextResponse.json({ error: 'helloada_messages_error', message }, { status, headers: noStore })
const object = (value: unknown) => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const text = (value: unknown) => String(value ?? '').trim()
const hasOwnerOrigin = (request: Request) => {
  const origin = request.headers.get('origin')
  if (!origin) return false
  try { return new URL(origin).origin === new URL(request.url).origin } catch { return false }
}
const bodyOf = async (request: Request, max = 16_384) => {
  const length = Number(request.headers.get('content-length') || 0)
  if (length > max) throw new Error('The request is too large.')
  const raw = await request.text()
  if (new TextEncoder().encode(raw).byteLength > max) throw new Error('The request is too large.')
  try { return object(JSON.parse(raw)) } catch { throw new Error('The request could not be read.') }
}
const listConversationWhere = (state: string, query: string) => {
  const and: Record<string, unknown>[] = []
  if (['needs_reply', 'done', 'archived', 'spam'].includes(state)) and.push({ state: { equals: state } })
  if (query) and.push({ or: [
    { subject: { like: query } }, { participantEmail: { like: query } }, { lastMessagePreview: { like: query } },
  ] })
  return and.length ? { and } : {}
}

const readInbox = async (request: Request, auth: HelloAdaAuth) => {
  const url = new URL(request.url)
  const view = url.searchParams.get('view') === 'contacts' ? 'contacts' : 'inbox'
  const state = text(url.searchParams.get('state') || 'needs_reply')
  const query = text(url.searchParams.get('q')).slice(0, 120)
  const mailbox = await auth.payload.findGlobal({ slug: 'messageMailbox' as never, depth: 0, overrideAccess: false, req: auth.req, user: auth.user })
  if (view === 'contacts') {
    const where = query ? { or: [{ name: { like: query } }, { email: { like: query } }, { company: { like: query } }] } : {}
    const result = await auth.payload.find({ collection: 'contacts', depth: 0, limit: 100, pagination: false, sort: 'name', overrideAccess: false, req: auth.req, user: auth.user, where: where as never })
    return NextResponse.json({ contacts: result.docs, mailbox }, { headers: noStore })
  }
  const result = await auth.payload.find({
    collection: 'conversations', depth: 1, limit: 100, pagination: false, sort: '-lastActivityAt',
    overrideAccess: false, req: auth.req, user: auth.user,
    where: listConversationWhere(state, query) as never,
  })
  return NextResponse.json({ conversations: result.docs, mailbox }, { headers: noStore })
}

const readConversation = async (id: string, auth: HelloAdaAuth) => {
  const conversation = await auth.payload.findByID({ collection: 'conversations', id, depth: 1, overrideAccess: false, req: auth.req, user: auth.user }).catch(() => undefined)
  if (!conversation) return fail('This conversation could not be found.', 404)
  const messages = await auth.payload.find({ collection: 'messages', depth: 0, limit: 200, pagination: false, sort: 'createdAt', overrideAccess: false, req: auth.req, user: auth.user, where: { conversation: { equals: id } } as never })
  const safeMessages = messages.docs.map((raw) => {
    const item = raw as unknown as MessageRecord
    const attachmentManifest = Array.isArray(item.attachmentManifest) ? item.attachmentManifest.map((attachment) => {
      const row = object(attachment)
      return { index: Number(row.index), filename: text(row.filename), mimeType: text(row.mimeType), size: Number(row.size), allowed: row.allowed === true }
    }) : []
    return {
      id: item.id, direction: item.direction, from: item.from, to: item.to, subject: item.subject,
      text: item.text, ...(item.deliveryState === 'draft' ? { draftText: item.draftText || item.text } : {}),
      draftRevision: item.draftRevision, deliveryState: item.deliveryState, createdAt: item.createdAt,
      attachmentManifest,
    }
  })
  return NextResponse.json({ conversation, messages: safeMessages }, { headers: noStore })
}

const downloadAttachment = async (messageId: string, index: number, auth: HelloAdaAuth) => {
  const message = await auth.payload.findByID({ collection: 'messages', id: messageId, depth: 0, overrideAccess: false, req: auth.req, user: auth.user }).catch(() => undefined)
  if (!message) return fail('This attachment could not be found.', 404)
  const row = message as unknown as MessageRecord
  const manifest = Array.isArray(row.attachmentManifest) ? object(row.attachmentManifest[index]) : {}
  const key = text(manifest.key)
  const expectedKey = `attachments/${String(row.operationId || '')}/${index}`
  const allowedTypes = new Set(['application/pdf', 'image/jpeg', 'image/png', 'image/webp', 'text/plain', 'text/csv'])
  if (manifest.allowed !== true || !Number.isInteger(Number(manifest.size)) || Number(manifest.size) < 1 || Number(manifest.size) > 5 * 1024 * 1024
    || !allowedTypes.has(text(manifest.mimeType).toLowerCase())
    || key !== expectedKey) {
    return fail('This attachment is unavailable.', 404)
  }
  const { env } = await messageRuntime()
  const stored = await env.PRIVATE_EMAIL?.get(key)
  if (!stored || stored.customMetadata?.tenant !== tenantIdentity() || stored.customMetadata?.operationId !== String(row.operationId)) return fail('This attachment could not be found.', 404)
  const bytes = await stored.arrayBuffer()
  const digest = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes))
  const sha256 = [...digest].map((byte) => byte.toString(16).padStart(2, '0')).join('')
  if (bytes.byteLength !== Number(manifest.size) || sha256 !== String(manifest.sha256 || '') || sha256 !== stored.customMetadata?.sha256) return fail('This attachment could not be verified.', 409)
  const filename = text(manifest.filename).replace(/[\r\n\0"\\/]/g, '_').slice(0, 180) || 'attachment'
  const encodedFilename = encodeURIComponent(filename).replace(/['()]/g, (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`)
  return new Response(bytes, { headers: {
    'Cache-Control': 'private, no-store',
    'Content-Disposition': `attachment; filename="attachment"; filename*=UTF-8''${encodedFilename}`,
    'Content-Length': String(bytes.byteLength),
    'Content-Security-Policy': 'sandbox',
    'Content-Type': text(manifest.mimeType).toLowerCase(),
    'X-Content-Type-Options': 'nosniff',
  } })
}

const selectedDraft = async (payload: HelloAdaAuth['payload'], conversationId: string) => findMessageRecord(payload, 'messages', {
  conversation: { equals: conversationId }, direction: { equals: 'reply' }, deliveryState: { equals: 'draft' },
}, { sort: '-createdAt' })

const draftHashFor = (conversationId: string, messageId: string, revision: number, recipient: string, subject: string, replyText: string) =>
  hashJson({ conversationId, messageId, revision, recipient, subject, replyText })

const saveDraft = async (conversationId: string, request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request)
  let replyText: string
  try { replyText = validateHelloAdaReplyText(input.replyText) } catch (error) { return fail(error instanceof Error ? error.message : 'Write a reply before saving.') }
  const expectedRevision = Number(input.expectedRevision)
  if (!Number.isInteger(expectedRevision) || expectedRevision < 0) return fail('Reload this conversation before saving the reply.', 409)
  const conversation = await auth.payload.findByID({ collection: 'conversations', id: conversationId, depth: 1, overrideAccess: false, req: auth.req, user: auth.user }).catch(() => undefined)
  if (!conversation) return fail('This conversation could not be found.', 404)
  const participant = text((conversation as unknown as MessageRecord).participantEmail)
  try { normalizeHelloAdaEmail(participant) } catch { return fail('This conversation has no valid reply address.', 409) }
  const idempotencyKey = `draft:${tenantIdentity()}:${conversationId}:${expectedRevision}`
  let operationResult: Awaited<ReturnType<typeof createMessageOperation>>
  try {
    operationResult = await createMessageOperation(auth.payload, 'save_draft', idempotencyKey, { conversationId, expectedRevision, replyText })
  } catch (error) { return fail(error instanceof Error ? error.message : 'This draft revision was already used.', 409) }
  const operation = operationResult.operation
  if (String(operation.state) === 'completed') {
    const receipt = object(operation.payload)
    if (receipt.draftHash && Number.isInteger(Number(receipt.draftRevision))) {
      return NextResponse.json({ draftHash: receipt.draftHash, draftRevision: Number(receipt.draftRevision) }, { headers: noStore })
    }
  }
  if (['failed', 'uncertain'].includes(String(operation.state))) return fail('This draft revision is already closed. Reload the conversation.', 409)
  const previous = await selectedDraft(auth.payload, conversationId)
  const currentRevision = Number(previous?.draftRevision || 0)
  if (currentRevision !== expectedRevision) {
    // A lost HTTP response is safe to retry: return success only if this exact
    // text was already committed as the immediately following revision.
    if (currentRevision === expectedRevision + 1 && String(previous?.text || '') === replyText) {
      const draftHash = await draftHashFor(conversationId, String(previous?.id), currentRevision, participant, text((conversation as unknown as MessageRecord).subject), replyText)
      await updateMessageOperation(auth.payload, operation, { state: 'completed', payload: { draftHash, draftRevision: currentRevision }, leaseUntil: null })
      return NextResponse.json({ draftHash, draftRevision: currentRevision }, { headers: noStore })
    }
    await markMessageOperation(auth.payload, operation, 'failed', { errorCode: 'draft_revision_conflict', clearPayload: true })
    return fail('This reply changed in another session. Reload it before saving.', 409)
  }
  const revision = currentRevision + 1
  let draft: MessageRecord
  try {
    if (previous) {
      draft = await auth.payload.update({ collection: 'messages', id: previous.id as string, data: {
        text: replyText, draftText: replyText, draftRevision: revision, to: participant,
      } as never, overrideAccess: true }) as unknown as MessageRecord
    } else {
      draft = await auth.payload.create({ collection: 'messages', data: {
        conversation: conversationId,
        direction: 'reply',
        to: participant,
        subject: text((conversation as unknown as MessageRecord).subject) || 'Re: your message',
        text: replyText,
        draftText: replyText,
        draftRevision: revision,
        deliveryState: 'draft',
      } as never, overrideAccess: true }) as unknown as MessageRecord
    }
  } catch (error) {
    console.error('helloada_message_draft_save_failed', { tenant: helloAdaSite.tenantId, conversationId, error: error instanceof Error ? error.message : 'unknown' })
    return fail('The draft could not be saved. Your text is still in the editor.', 503)
  }
  const draftHash = await draftHashFor(conversationId, String(draft.id), revision, participant, text((conversation as unknown as MessageRecord).subject), replyText)
  await updateMessageOperation(auth.payload, operation, { state: 'completed', payload: { draftHash, draftRevision: revision }, leaseUntil: null })
  return NextResponse.json({ draftHash, draftRevision: revision }, { headers: noStore })
}

const sendDraft = async (conversationId: string, request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request)
  let requestId: string
  try { requestId = helloAdaIdempotencyKey(input.requestId) } catch { return fail('Reload the reply before sending.', 400) }
  const draftHash = text(input.draftHash)
  if (!/^[a-f0-9]{64}$/.test(draftHash)) return fail('Save and review this reply before sending.', 409)
  const idempotencyKey = `send:${tenantIdentity()}:${conversationId}:${requestId}`
  const previousOperation = await findMessageRecord(auth.payload, 'messageOperations', { idempotencyKey: { equals: idempotencyKey } })
  if (previousOperation) {
    if (String(previousOperation.requestHash || '') !== await hashJson({ draftHash })) return fail('That send request ID belongs to a different reviewed reply.', 409)
    const state = String(previousOperation.state)
    if (state === 'uncertain') return NextResponse.json({ state, message: 'The email service response is uncertain. Do not send this reply again yet.' }, { status: 409, headers: noStore })
    if (state === 'failed') return NextResponse.json({ state, message: 'This send request failed and will not be retried automatically.' }, { status: 409, headers: noStore })
    return NextResponse.json({ queued: true, operationId: previousOperation.operationId, state }, { status: 202, headers: noStore })
  }
  const conversation = await auth.payload.findByID({ collection: 'conversations', id: conversationId, depth: 1, overrideAccess: false, req: auth.req, user: auth.user }).catch(() => undefined)
  if (!conversation) return fail('This conversation could not be found.', 404)
  const row = conversation as unknown as MessageRecord
  const mailbox = await auth.payload.findGlobal({ slug: 'messageMailbox' as never, depth: 0, overrideAccess: false, req: auth.req, user: auth.user }) as unknown as MessageRecord
  if (mailbox.state !== 'active' || !mailbox.address) return fail('Domain email is not active for this website.', 409)
  const recipient = text(row.participantEmail)
  const from = text(mailbox.address)
  try { normalizeHelloAdaEmail(recipient); normalizeHelloAdaEmail(from) } catch { return fail('The sender or recipient address is not valid.', 409) }
  const draft = await selectedDraft(auth.payload, conversationId)
  if (!draft || String(draft.deliveryState) !== 'draft') return fail('This reply is no longer an editable draft.', 409)
  const draftRevision = Number(draft.draftRevision || 0)
  const replyText = String(draft.text || draft.draftText || '')
  const subject = text(draft.subject || row.subject)
  const currentHash = await draftHashFor(conversationId, String(draft.id), draftRevision, recipient, subject, replyText)
  if (currentHash !== draftHash) return fail('The reply changed after you reviewed it. Save and review it again.', 409)
  const approvedAt = nowIso()
  const approvedBy = String(auth.user.id)
  const operationBody = { messageId: draft.id, conversationId, draftHash, draftRevision, from, to: recipient, subject, text: replyText, approvedBy, approvedAt }
  let created: Awaited<ReturnType<typeof createMessageOperation>>
  try {
    created = await createMessageOperation(auth.payload, 'send_reply', idempotencyKey, operationBody, await hashJson({ draftHash }))
  } catch (error) { return fail(error instanceof Error ? error.message : 'This send request could not be accepted.', 409) }
  const operation = created.operation
  if (!created.created) {
    if (['completed', 'uncertain', 'failed'].includes(String(operation.state))) {
      return NextResponse.json({ state: operation.state, message: operation.state === 'uncertain' ? 'The email service response is uncertain. Do not send this reply again yet.' : 'This send request has already been processed.' }, { status: operation.state === 'uncertain' ? 409 : 202, headers: noStore })
    }
    return NextResponse.json({ queued: true, operationId: operation.operationId }, { status: 202, headers: noStore })
  }
  try {
    await auth.payload.update({ collection: 'messages', id: draft.id as string, data: {
      to: recipient, approvalHash: draftHash, approvedBy, approvedAt, operationId: String(operation.operationId), deliveryState: 'queued',
    } as never, overrideAccess: true })
  } catch (error) {
    await markMessageOperation(auth.payload, operation, 'failed', { errorCode: 'approval_persistence_failed', clearPayload: true })
    console.error('helloada_message_approval_persist_failed', { tenant: helloAdaSite.tenantId, operationId: operation.operationId, error: error instanceof Error ? error.message : 'unknown' })
    return fail('Your approval could not be recorded, so the reply was not sent.', 503)
  }
  try { await dispatchMessageOperation((await messageRuntime()).env, operation) }
  catch (error) { console.error('helloada_send_queue_deferred', { tenant: helloAdaSite.tenantId, operationId: operation.operationId, error: error instanceof Error ? error.message : 'unknown' }) }
  return NextResponse.json({ queued: true, operationId: operation.operationId }, { status: 202, headers: noStore })
}

const updateConversationState = async (conversationId: string, request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request, 4_096)
  const state = text(input.state)
  if (!['needs_reply', 'done', 'archived', 'spam'].includes(state)) return fail('Choose a valid conversation state.')
  try {
    await auth.payload.update({ collection: 'conversations', id: conversationId, data: { state, unread: false } as never, overrideAccess: false, req: auth.req, user: auth.user })
    return NextResponse.json({ updated: true }, { headers: noStore })
  } catch { return fail('The conversation could not be updated.', 503) }
}

const draftWithAda = async (conversationId: string, request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request, 1_024)
  if (Object.keys(input).length) return fail('The request contains unsupported data.')
  const conversation = await auth.payload.findByID({ collection: 'conversations', id: conversationId, depth: 0, overrideAccess: false, req: auth.req, user: auth.user }).catch(() => undefined)
  if (!conversation) return fail('This conversation could not be found.', 404)
  const rows = await auth.payload.find({
    collection: 'messages', depth: 0, limit: 8, pagination: false, sort: '-createdAt',
    overrideAccess: false, req: auth.req, user: auth.user,
    where: { conversation: { equals: conversationId } } as never,
  })
  const messages = rows.docs.reverse().map((item) => item as unknown as MessageRecord).map((item) => ({
    direction: String(item.direction || ''),
    from: text(item.from).slice(0, 254),
    subject: text(item.subject).slice(0, 180),
    text: text(item.text).slice(0, 4_000),
  }))
  if (!messages.some((item) => ['form_enquiry', 'received_email'].includes(item.direction))) return fail('This conversation has no customer message to reply to.', 409)
  const upstreamRequest = new Request(new URL(`/api/helloada/messages/${encodeURIComponent(conversationId)}/draft-with-ada`, request.url), {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ messages }),
  })
  const response = await fetchHelloAdaUpstream(`/api/helloada/messages/${encodeURIComponent(conversationId)}/draft-with-ada`, upstreamRequest)
  if (!response) return fail('Ada is unavailable right now. Your conversation is still here.', 503)
  const body = await response.json().catch(() => ({})) as { draft?: unknown; detail?: string }
  if (!response.ok) return fail(body.detail || 'Ada could not prepare a reply. Your conversation is still here.', response.status)
  let draft: string
  try { draft = validateHelloAdaReplyText(body.draft) } catch { return fail('Ada returned a draft that needs to be prepared again.', 502) }
  return NextResponse.json({ draft }, { headers: noStore })
}

const updateContact = async (contactId: string, request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request, 8_192)
  const allowed = ['name', 'phone', 'company', 'notes']
  if (Object.keys(input).some((key) => !allowed.includes(key))) return fail('Only contact name, phone, company and notes can be edited.')
  const data: Record<string, unknown> = {}
  for (const key of allowed) {
    if (!(key in input)) continue
    const max = key === 'notes' ? 4_000 : key === 'phone' ? 80 : 160
    const value = text(input[key])
    if (value.length > max || /[\0-\x08\x0B\x0C\x0E-\x1F\x7F]/.test(value)) return fail(`The contact ${key} is too long or contains unsupported characters.`)
    data[key] = value || null
  }
  try {
    const contact = await auth.payload.update({ collection: 'contacts', id: contactId, data: data as never, overrideAccess: false, req: auth.req, user: auth.user })
    return NextResponse.json({ contact }, { headers: noStore })
  } catch { return fail('The contact could not be updated.', 503) }
}

export async function ownerMessagesRoute(request: Request, path: string, auth: HelloAdaAuth) {
  try {
    if (request.method === 'GET' && path === '/messages') return await readInbox(request, auth)
    const attachmentRoute = path.match(/^\/messages\/([^/]+)\/attachments\/([0-9]{1,2})$/)
    if (request.method === 'GET' && attachmentRoute) return await downloadAttachment(decodeURIComponent(attachmentRoute[1]), Number(attachmentRoute[2]), auth)
    if (request.method === 'GET' && path.startsWith('/messages/')) return await readConversation(decodeURIComponent(path.slice('/messages/'.length)), auth)
    const stateRoute = path.match(/^\/messages\/([^/]+)\/state$/)
    if (request.method === 'POST' && stateRoute) return await updateConversationState(decodeURIComponent(stateRoute[1]), request, auth)
    const adaDraftRoute = path.match(/^\/messages\/([^/]+)\/draft-with-ada$/)
    if (request.method === 'POST' && adaDraftRoute) return await draftWithAda(decodeURIComponent(adaDraftRoute[1]), request, auth)
    const draftRoute = path.match(/^\/messages\/([^/]+)\/draft$/)
    if (request.method === 'POST' && draftRoute) return await saveDraft(decodeURIComponent(draftRoute[1]), request, auth)
    const sendRoute = path.match(/^\/messages\/([^/]+)\/send$/)
    if (request.method === 'POST' && sendRoute) return await sendDraft(decodeURIComponent(sendRoute[1]), request, auth)
    const contactRoute = path.match(/^\/contacts\/([^/]+)$/)
    if (request.method === 'POST' && contactRoute) return await updateContact(decodeURIComponent(contactRoute[1]), request, auth)
    return fail('The Messages route was not found.', 404)
  } catch (error) {
    console.error('helloada_owner_messages_request_failed', { tenant: helloAdaSite.tenantId, error: error instanceof Error ? error.message : 'unknown' })
    return fail('Messages could not be loaded. Your other tools are unaffected.', 503)
  }
}

const acceptInbound = async (request: Request) => {
  if (!serviceAuthorized(request) || !hasCorrectTenant(request)) return fail('service authentication required', 401)
  const input = await bodyOf(request, 8_192)
  const rawObjectKey = text(input.rawObjectKey)
  const rawSha256 = text(input.rawSha256)
  if (!/^inbound\/[0-9]{4}-[0-9]{2}-[0-9]{2}\/[a-f0-9]{64}\.eml$/.test(rawObjectKey) || !/^[a-f0-9]{64}$/.test(rawSha256) || !rawObjectKey.endsWith(`${rawSha256}.eml`)) {
    return fail('The inbound message receipt is invalid.', 400)
  }
  let from: string
  let to: string
  try { from = normalizeHelloAdaEmail(input.from); to = normalizeHelloAdaEmail(input.to) }
  catch { return fail('The inbound envelope is invalid.', 400) }
  const { payload, env } = await messageRuntime()
  const mailbox = await findMailbox(payload)
  if (mailbox.state !== 'active' || normalizeHelloAdaEmail(mailbox.address) !== to) return fail('The receiving mailbox is not active for this address.', 409)
  const headers = object(input.headers)
  const idempotencyKey = `inbound:${tenantIdentity()}:${rawSha256}`
  const data = { rawObjectKey, rawSha256, from, to, headers }
  let result: Awaited<ReturnType<typeof createMessageOperation>>
  try { result = await createMessageOperation(payload, 'inbound_email', idempotencyKey, data, await hashJson({ rawSha256, from, to })) }
  catch (error) { return fail(error instanceof Error ? error.message : 'The inbound receipt could not be accepted.', 409) }
  try { await dispatchMessageOperation(env, result.operation) }
  catch (error) { console.error('helloada_inbound_queue_deferred', { tenant: tenantIdentity(), operationId: result.operation.operationId, error: error instanceof Error ? error.message : 'unknown' }) }
  return NextResponse.json({ accepted: true, operationId: result.operation.operationId }, { status: 202, headers: noStore })
}

const processOperation = async (request: Request) => {
  if (!serviceAuthorized(request) || !hasCorrectTenant(request)) return fail('service authentication required', 401)
  const input = await bodyOf(request, 4_096)
  const operationId = text(input.operationId)
  if (!/^[a-f0-9-]{36}$/.test(operationId)) return fail('The message operation ID is invalid.', 400)
  try {
    const { env } = await messageRuntime()
    const result = await processHelloAdaMessageOperation(operationId, env)
    return NextResponse.json(result, { status: 200, headers: noStore })
  } catch (error) {
    console.error('helloada_message_operation_failed', { tenant: tenantIdentity(), operationId, error: error instanceof Error ? error.message : 'unknown' })
    return fail('The message operation could not be completed.', 503)
  }
}

const sweepOperations = async (request: Request) => {
  if (!serviceAuthorized(request) || !hasCorrectTenant(request)) return fail('service authentication required', 401)
  const { payload, env } = await messageRuntime()
  try {
    await enqueueDueMessageOperations(payload, env)
    return NextResponse.json({ swept: true }, { headers: noStore })
  } catch (error) {
    console.error('helloada_message_sweep_failed', { tenant: tenantIdentity(), error: error instanceof Error ? error.message : 'unknown' })
    return fail('Message operation recovery could not run.', 503)
  }
}

const deadLetterOperation = async (request: Request) => {
  if (!serviceAuthorized(request) || !hasCorrectTenant(request)) return fail('service authentication required', 401)
  const input = await bodyOf(request, 4_096)
  const operationId = text(input.operationId)
  if (!/^[a-f0-9-]{36}$/.test(operationId)) return fail('The message operation ID is invalid.', 400)
  try {
    const { payload, env } = await messageRuntime()
    const state = await markDeadLetterMessageOperation(payload, env, operationId)
    console.error('helloada_message_dead_letter', { tenant: tenantIdentity(), operationId, state })
    return NextResponse.json({ handled: true, state }, { headers: noStore })
  } catch (error) {
    console.error('helloada_message_dead_letter_failed', { tenant: tenantIdentity(), operationId, error: error instanceof Error ? error.message : 'unknown' })
    return fail('The failed message operation could not be recorded.', 503)
  }
}

const configureMailbox = async (request: Request) => {
  if (!serviceAuthorized(request) || !hasCorrectTenant(request)) return fail('service authentication required', 401)
  let input: Record<string, unknown>
  try { input = await bodyOf(request, 4_096) }
  catch { return fail('The mailbox configuration is invalid.', 400) }
  const domain = text(input.domain).toLowerCase().replace(/\.$/, '')
  let address: string
  try { address = normalizeHelloAdaEmail(input.address) }
  catch { return fail('The mailbox address is invalid.', 400) }
  if (!/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(domain)
    || address.split('@')[1] !== domain) return fail('The mailbox address must belong to its registered domain.', 400)
  try {
    const { payload } = await messageRuntime()
    const mailbox = await payload.updateGlobal({
      slug: 'messageMailbox' as never,
      data: { domain, address, state: 'active', statusDetail: '', activatedAt: new Date().toISOString() } as never,
      overrideAccess: true,
    }) as unknown as MessageRecord
    if (String(mailbox.state) !== 'active' || String(mailbox.address).toLowerCase() !== address) {
      throw new Error('Payload did not confirm the active mailbox')
    }
    return NextResponse.json({ state: 'active', domain, address }, { headers: noStore })
  } catch (error) {
    console.error('helloada_mailbox_configuration_failed', { tenant: tenantIdentity(), error: error instanceof Error ? error.message : 'unknown' })
    return fail('Payload could not confirm the provisioned mailbox.', 503)
  }
}

export async function internalMessagesRoute(request: Request, path: string) {
  if (request.method !== 'POST') return fail('method not allowed', 405)
  if (path === '/internal/messages/configure-mailbox') return configureMailbox(request)
  if (path === '/internal/messages/accept-inbound') return acceptInbound(request)
  if (path === '/internal/messages/process') return processOperation(request)
  if (path === '/internal/messages/sweep') return sweepOperations(request)
  if (path === '/internal/messages/dead-letter') return deadLetterOperation(request)
  return fail('The internal Messages route was not found.', 404)
}
