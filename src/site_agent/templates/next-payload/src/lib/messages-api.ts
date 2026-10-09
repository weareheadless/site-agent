import { NextResponse } from 'next/server'
import { helloAdaIdempotencyKey, normalizeHelloAdaEmail, validateHelloAdaRecipients, validateHelloAdaReplyText, validateHelloAdaSubject } from '@weareheadless/helloada-payload-core/messages'
import { hashJson } from '@/lib/payload-hash'
import type { HelloAdaAuth } from '@/lib/helloada-auth'
import { helloAdaSite } from '@/helloada.config'
import { processHelloAdaMessageOperation } from '@/lib/message-processing'
import {
  buildNotificationVerificationEmail,
  createMessageNotificationCode,
  equalMessageNotificationCodeHash,
  hashMessageNotificationCode,
} from '@/lib/message-notifications'
import {
  createMessageOperation,
  createMessageOnce,
  createOrFindConversation,
  createOrUpdateContact,
  dispatchMessageOperation,
  enqueueDueMessageOperations,
  findMailbox,
  findMessageRecord,
  markDeadLetterMessageOperation,
  markMessageOperation,
  messageRuntime,
  nowIso,
  newMessageId,
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
const MESSAGE_PAGE_SIZE = 30
const parseCursor = (value: string) => {
  if (!value) return undefined
  const separator = value.indexOf('|')
  if (separator < 1) throw new Error('The message list cursor is invalid. Refresh the mailbox.')
  const timestamp = value.slice(0, separator)
  const id = value.slice(separator + 1)
  if (!Number.isFinite(Date.parse(timestamp)) || !/^\d+$/.test(id) || !Number.isSafeInteger(Number(id))) {
    throw new Error('The message list cursor is invalid. Refresh the mailbox.')
  }
  return { timestamp, id: Number(id) }
}
const cursorWhere = (field: 'createdAt' | 'lastActivityAt', cursor: ReturnType<typeof parseCursor>) => cursor ? ({ or: [
  { [field]: { less_than: cursor.timestamp } },
  { and: [{ [field]: { equals: cursor.timestamp } }, { id: { less_than: cursor.id } }] },
] }) : undefined
const cursorFor = (row: Record<string, unknown>, field: 'createdAt' | 'lastActivityAt') => `${String(row[field] || '')}|${String(row.id || '')}`
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
const listConversationWhere = (state: string, query: string, folder: string) => {
  const and: Record<string, unknown>[] = []
  if (['needs_reply', 'done', 'archived', 'spam', 'trash'].includes(state)) and.push({ state: { equals: state } })
  if (folder === 'inbox') and.push({ or: [
    { source: { not_in: ['owner', 'booking'] } },
    { state: { equals: 'needs_reply' } },
  ] })
  if (query) and.push({ or: [
    { subject: { like: query } }, { participantEmail: { like: query } }, { lastMessagePreview: { like: query } },
  ] })
  return and.length ? { and } : {}
}

const readInbox = async (request: Request, auth: HelloAdaAuth) => {
  const url = new URL(request.url)
  const view = url.searchParams.get('view') === 'contacts' ? 'contacts' : 'inbox'
  const state = text(url.searchParams.get('state') || 'needs_reply')
  const folder = text(url.searchParams.get('folder') || 'inbox')
  const query = text(url.searchParams.get('q')).slice(0, 120)
  const requestedConversation = text(url.searchParams.get('conversation')).slice(0, 120)
  let cursor: ReturnType<typeof parseCursor>
  try { cursor = parseCursor(text(url.searchParams.get('cursor'))) }
  catch (error) { return fail(error instanceof Error ? error.message : 'Refresh the mailbox.', 400) }
  const rawMailbox = await auth.payload.findGlobal({ slug: 'messageMailbox' as never, depth: 0, overrideAccess: false, req: auth.req, user: auth.user }) as unknown as MessageRecord
  const mailbox = {
    address: rawMailbox.address, domain: rawMailbox.domain, state: rawMailbox.state,
    outboundProvider: rawMailbox.outboundProvider, outboundMode: rawMailbox.outboundMode,
    statusDetail: rawMailbox.statusDetail,
    notificationAddress: rawMailbox.notificationAddress,
    notificationVerifiedAt: rawMailbox.notificationVerifiedAt,
    notificationPendingAddress: rawMailbox.notificationPendingAddress,
    notificationCodeExpiresAt: rawMailbox.notificationCodeExpiresAt,
  }
  if (view === 'contacts') {
    const where = query ? { or: [{ name: { like: query } }, { email: { like: query } }, { company: { like: query } }] } : {}
    const result = await auth.payload.find({ collection: 'contacts', depth: 0, limit: 100, pagination: false, sort: 'name', overrideAccess: false, req: auth.req, user: auth.user, where: where as never })
    return NextResponse.json({ contacts: result.docs, mailbox }, { headers: noStore })
  }
  if (['sent', 'drafts'].includes(folder)) {
    const messageWhere: Record<string, unknown>[] = [
      { direction: { in: ['reply', 'owner_message'] } },
      { deliveryState: { equals: folder === 'sent' ? 'accepted' : 'draft' } },
    ]
    if (query) messageWhere.push({ or: [
      { subject: { like: query } }, { text: { like: query } }, { from: { like: query } }, { to: { like: query } },
    ] })
    const pageCursor = cursorWhere('createdAt', cursor)
    if (pageCursor) messageWhere.push(pageCursor)
    const matching = await auth.payload.find({
      collection: 'messages', depth: 1, limit: MESSAGE_PAGE_SIZE + 1, pagination: false, sort: '-createdAt,-id',
      overrideAccess: false, req: auth.req, user: auth.user,
      where: { and: messageWhere } as never,
    })
    const messageRows = matching.docs.slice(0, MESSAGE_PAGE_SIZE)
    const ids = [...new Set(messageRows.map((message) => String(object(message.conversation).id || message.conversation || '')).filter(Boolean))]
    if (!ids.length) return NextResponse.json({ conversations: [], mailbox, nextCursor: null }, { headers: noStore })
    const result = await auth.payload.find({
      collection: 'conversations', depth: 1, limit: MESSAGE_PAGE_SIZE, pagination: false, sort: '-lastActivityAt,-id',
      overrideAccess: false, req: auth.req, user: auth.user,
      where: { id: { in: ids } } as never,
    })
    const byId = new Map(result.docs.map((row) => [String(row.id), row]))
    const rows = ids.map((id) => byId.get(id)).filter((row): row is NonNullable<typeof row> => Boolean(row))
    if (requestedConversation && !rows.some((item) => String(item.id) === requestedConversation)) {
      const linked = await auth.payload.findByID({ collection: 'conversations', id: requestedConversation, depth: 1, overrideAccess: false, req: auth.req, user: auth.user }).catch(() => undefined)
      if (linked) rows.unshift(linked)
    }
    const nextCursor = matching.docs.length > MESSAGE_PAGE_SIZE && messageRows.length
      ? cursorFor(object(messageRows[messageRows.length - 1]), 'createdAt') : null
    return NextResponse.json({ conversations: rows, mailbox, nextCursor }, { headers: noStore })
  }
  const conversationWhere = object(listConversationWhere(folder === 'trash' ? 'trash' : folder === 'spam' || folder === 'archived' ? folder : state, query, folder))
  const conversationFilters = Array.isArray(conversationWhere.and) ? [...conversationWhere.and as Record<string, unknown>[]] : []
  const conversationCursor = cursorWhere('lastActivityAt', cursor)
  if (conversationCursor) conversationFilters.push(conversationCursor)
  const result = await auth.payload.find({
    collection: 'conversations', depth: 1, limit: MESSAGE_PAGE_SIZE + 1, pagination: false, sort: '-lastActivityAt,-id',
    overrideAccess: false, req: auth.req, user: auth.user,
    where: { and: conversationFilters } as never,
  })
  const pageRows = result.docs.slice(0, MESSAGE_PAGE_SIZE)
  const rows = [...pageRows]
  if (requestedConversation && !rows.some((item) => String(item.id) === requestedConversation)) {
    const linked = await auth.payload.findByID({
      collection: 'conversations', id: requestedConversation, depth: 1,
      overrideAccess: false, req: auth.req, user: auth.user,
    }).catch(() => undefined)
    if (linked) rows.unshift(linked)
  }
  const nextCursor = result.docs.length > MESSAGE_PAGE_SIZE && pageRows.length
    ? cursorFor(object(pageRows[pageRows.length - 1]), 'lastActivityAt') : null
  return NextResponse.json({ conversations: rows, mailbox, nextCursor }, { headers: noStore })
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
      ccRecipients: Array.isArray(item.ccRecipients) ? item.ccRecipients : [],
      bccRecipients: Array.isArray(item.bccRecipients) ? item.bccRecipients : [],
      text: item.text, ...(item.deliveryState === 'draft' ? { draftText: item.draftText || item.text } : {}),
      draftRevision: item.draftRevision, deliveryState: item.deliveryState, createdAt: item.createdAt,
      attachmentManifest,
    }
  })
  return NextResponse.json({ conversation, messages: safeMessages }, { headers: noStore })
}

const readCalendar = async (auth: HelloAdaAuth) => {
  const [settings, appointmentTypes, events] = await Promise.all([
    auth.payload.findGlobal({ slug: 'calendarSettings' as never, depth: 0, overrideAccess: false, req: auth.req, user: auth.user }),
    auth.payload.find({ collection: 'appointmentTypes', depth: 0, draft: true, limit: 100, pagination: false, sort: 'name', overrideAccess: false, req: auth.req, user: auth.user }),
    auth.payload.find({
      collection: 'calendarEvents', depth: 1, limit: 200, pagination: false, sort: 'startsAt', overrideAccess: true,
      where: { startsAt: { greater_than_equal: new Date(Date.now() - 7 * 86_400_000).toISOString() } } as never,
    }),
  ])
  return NextResponse.json({ settings, appointmentTypes: appointmentTypes.docs, events: events.docs }, { headers: noStore })
}

const saveCalendarSettings = async (request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request, 4_096)
  if (Object.keys(input).some((key) => !['enabled', 'timeZone', 'minimumNoticeHours', 'bookingWindowDays'].includes(key))) return fail('The calendar settings contain unsupported fields.')
  const timeZone = text(input.timeZone)
  try { new Intl.DateTimeFormat('en', { timeZone }).format(new Date()) } catch { return fail('Choose a valid business time zone.') }
  const minimumNoticeHours = Number(input.minimumNoticeHours)
  const bookingWindowDays = Number(input.bookingWindowDays)
  if (typeof input.enabled !== 'boolean' || !Number.isInteger(minimumNoticeHours) || minimumNoticeHours < 0 || minimumNoticeHours > 8760
    || !Number.isInteger(bookingWindowDays) || bookingWindowDays < 1 || bookingWindowDays > 365) return fail('Review the calendar settings and try again.')
  try {
    if (input.enabled) {
      const activeTypes = await auth.payload.find({
        collection: 'appointmentTypes', depth: 0, draft: false, limit: 1, pagination: false,
        overrideAccess: false, req: auth.req, user: auth.user,
        where: { enabled: { equals: true } } as never,
      })
      if (!activeTypes.docs.length) return fail('Enable at least one appointment type before accepting online bookings.', 409)
    }
    const settings = await auth.payload.updateGlobal({ slug: 'calendarSettings' as never, data: { enabled: input.enabled, timeZone, minimumNoticeHours, bookingWindowDays } as never, overrideAccess: false, req: auth.req, user: auth.user })
    return NextResponse.json({ settings }, { headers: noStore })
  } catch { return fail('The calendar settings could not be saved.', 503) }
}

const saveAppointmentType = async (request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request, 12_000)
  const allowed = ['id', 'name', 'slug', 'description', 'durationMinutes', 'bufferMinutes', 'weeklyAvailability', 'enabled']
  if (Object.keys(input).some((key) => !allowed.includes(key))) return fail('The appointment type contains unsupported fields.')
  const name = text(input.name)
  const slug = text(input.slug)
  const durationMinutes = Number(input.durationMinutes)
  const bufferMinutes = Number(input.bufferMinutes)
  const weeklyAvailability = Array.isArray(input.weeklyAvailability) ? input.weeklyAvailability : []
  if (!name || name.length > 120 || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) || slug.length > 80
    || !Number.isInteger(durationMinutes) || durationMinutes < 10 || durationMinutes > 480 || durationMinutes % 5 !== 0
    || !Number.isInteger(bufferMinutes) || bufferMinutes < 0 || bufferMinutes > 120 || bufferMinutes % 5 !== 0
    || typeof input.enabled !== 'boolean') return fail('Review the appointment type details and try again.')
  const data = { name, slug, description: text(input.description).slice(0, 2_000), durationMinutes, bufferMinutes, weeklyAvailability, enabled: input.enabled }
  try {
    const doc = input.id
      ? await auth.payload.update({ collection: 'appointmentTypes', id: String(input.id), data: data as never, draft: false, overrideAccess: false, req: auth.req, user: auth.user })
      : await auth.payload.create({ collection: 'appointmentTypes', data: data as never, draft: false, overrideAccess: false, req: auth.req, user: auth.user })
    return NextResponse.json({ appointmentType: doc }, { status: input.id ? 200 : 201, headers: noStore })
  } catch (error) { return fail(error instanceof Error ? error.message : 'The appointment type could not be saved.', 409) }
}

const cancelCalendarEvent = async (eventId: string, request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request, 2_048)
  if (Object.keys(input).some((key) => key !== 'reason')) return fail('The cancellation contains unsupported fields.')
  const event = await auth.payload.findByID({ collection: 'calendarEvents', id: eventId, depth: 1, overrideAccess: true }).catch(() => undefined)
  if (!event || event.state !== 'confirmed') return fail('This appointment is no longer active.', 409)
  try {
    await auth.payload.update({ collection: 'calendarEvents', id: eventId, data: { state: 'cancelled' } as never, overrideAccess: true })
    const mailbox = await findMailbox(auth.payload)
    if (mailbox.state === 'active' && mailbox.address) {
      const contact = object(event.contact)
      const appointment = object(event.appointmentType)
      const email = normalizeHelloAdaEmail(contact.email)
      const sender = normalizeHelloAdaEmail(mailbox.address)
      const operationId = newMessageId()
      const conversation = await createOrFindConversation(auth.payload, {
        subject: `Booking cancelled: ${text(event.title)}`, contact: contact.id, participantEmail: email,
        mailboxKey: sender, threadKey: `booking:${text(event.receiptId)}`, state: 'done', unread: false,
        source: 'booking', sourcePage: text(event.sourcePage), lastActivityAt: nowIso(), lastMessagePreview: 'Appointment cancelled',
      })
      const when = new Intl.DateTimeFormat(helloAdaSite.defaultLocale || 'en', { timeZone: String(event.timeZone), dateStyle: 'long', timeStyle: 'short' }).format(new Date(String(event.startsAt)))
      const subject = `Your ${text(appointment.name || event.title)} appointment was cancelled`
      const messageText = `Hello ${text(contact.name)},\n\nYour ${text(appointment.name || event.title)} appointment scheduled for ${when} has been cancelled.\n\n${String(helloAdaSite.siteName || 'The team')}`
      const message = await createMessageOnce(auth.payload, {
        conversation: conversation.id, direction: 'booking_notice', from: sender, to: email,
        subject, text: messageText, deliveryState: 'queued', operationId: `${operationId}:notice`, receiptId: `${operationId}:notice`,
      })
      await auth.payload.update({ collection: 'calendarEvents', id: eventId, data: { notificationState: 'pending' } as never, overrideAccess: true })
      const notice = await createMessageOperation(auth.payload, 'booking_notification', `booking-cancel:${tenantIdentity()}:${operationId}`, {
        eventId, eventState: 'cancelled', messageId: message.id, conversationId: conversation.id,
        from: sender, to: email, subject, text: messageText,
      })
      try { await dispatchMessageOperation((await messageRuntime()).env, notice.operation) }
      catch (error) { console.error('helloada_booking_cancellation_queue_deferred', { tenant: tenantIdentity(), operationId: notice.operation.operationId, error: error instanceof Error ? error.message : 'unknown' }) }
    }
    return NextResponse.json({ cancelled: true }, { headers: noStore })
  } catch (error) { return fail(error instanceof Error ? error.message : 'The appointment could not be cancelled.', 503) }
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
  conversation: { equals: conversationId }, direction: { in: ['reply', 'owner_message'] }, deliveryState: { equals: 'draft' },
}, { sort: '-createdAt' })

const draftHashFor = (conversationId: string, messageId: string, revision: number, recipient: string, subject: string, replyText: string, cc: string[] = [], bcc: string[] = []) =>
  hashJson({ conversationId, messageId, revision, recipient, cc, bcc, subject, replyText })

const ownerMessageDraftHash = (message: MessageRecord, conversationId: string, sender: string, revision: number, subject: string, messageText: string) => hashJson({
  messageId: message.id, conversationId, revision, from: sender, to: message.to,
  cc: Array.isArray(message.ccRecipients) ? message.ccRecipients : [],
  bcc: Array.isArray(message.bccRecipients) ? message.bccRecipients : [], subject, text: messageText,
})

const saveDraft = async (conversationId: string, request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request)
  if (Object.keys(input).some((key) => !['replyText', 'cc', 'bcc', 'subject', 'expectedRevision'].includes(key))) return fail('The reply contains unsupported fields.')
  let replyText: string
  try { replyText = validateHelloAdaReplyText(input.replyText) } catch (error) { return fail(error instanceof Error ? error.message : 'Write a reply before saving.') }
  const expectedRevision = Number(input.expectedRevision)
  if (!Number.isInteger(expectedRevision) || expectedRevision < 0) return fail('Reload this conversation before saving the reply.', 409)
  const conversation = await auth.payload.findByID({ collection: 'conversations', id: conversationId, depth: 1, overrideAccess: false, req: auth.req, user: auth.user }).catch(() => undefined)
  if (!conversation) return fail('This conversation could not be found.', 404)
  const participant = text((conversation as unknown as MessageRecord).participantEmail)
  let recipients: ReturnType<typeof validateHelloAdaRecipients>
  let subject: string
  try {
    subject = validateHelloAdaSubject(input.subject ?? (text((conversation as unknown as MessageRecord).subject).startsWith('Re:')
      ? text((conversation as unknown as MessageRecord).subject)
      : `Re: ${text((conversation as unknown as MessageRecord).subject) || 'your message'}`))
    recipients = validateHelloAdaRecipients({ to: participant, cc: input.cc, bcc: input.bcc })
  } catch (error) { return fail(error instanceof Error ? error.message : 'Review the reply recipients and subject.') }
  const contentIdentity = { replyText, subject, cc: recipients.cc, bcc: recipients.bcc }
  const idempotencyKey = `draft:${tenantIdentity()}:${conversationId}:${expectedRevision}:${await hashJson(contentIdentity)}`
  let operationResult: Awaited<ReturnType<typeof createMessageOperation>>
  try {
    operationResult = await createMessageOperation(auth.payload, 'save_draft', idempotencyKey, { conversationId, expectedRevision, ...contentIdentity })
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
  if (previous?.direction === 'owner_message') return fail('This is a new-message draft. Open it in Drafts to edit recipients.', 409)
  const recipient = participant
  try { normalizeHelloAdaEmail(recipient) } catch { return fail('This conversation has no valid reply address.', 409) }
  const currentRevision = Number(previous?.draftRevision || 0)
  if (currentRevision !== expectedRevision) {
    const priorCc = Array.isArray(previous?.ccRecipients) ? previous.ccRecipients.map(String) : []
    const priorBcc = Array.isArray(previous?.bccRecipients) ? previous.bccRecipients.map(String) : []
    if (currentRevision === expectedRevision + 1 && String(previous?.text || '') === replyText
      && text(previous?.subject) === subject && JSON.stringify(priorCc) === JSON.stringify(recipients.cc)
      && JSON.stringify(priorBcc) === JSON.stringify(recipients.bcc)) {
      const draftHash = await draftHashFor(conversationId, String(previous?.id), currentRevision, recipient, subject, replyText, recipients.cc, recipients.bcc)
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
        text: replyText, draftText: replyText, draftRevision: revision, to: recipient,
        ccRecipients: recipients.cc, bccRecipients: recipients.bcc, subject,
      } as never, overrideAccess: true }) as unknown as MessageRecord
    } else {
      draft = await auth.payload.create({ collection: 'messages', data: {
        conversation: conversationId,
        direction: 'reply',
        to: participant,
        subject,
        text: replyText,
        draftText: replyText,
        ccRecipients: recipients.cc,
        bccRecipients: recipients.bcc,
        draftRevision: revision,
        deliveryState: 'draft',
      } as never, overrideAccess: true }) as unknown as MessageRecord
    }
  } catch (error) {
    console.error('helloada_message_draft_save_failed', { tenant: helloAdaSite.tenantId, conversationId, error: error instanceof Error ? error.message : 'unknown' })
    return fail('The draft could not be saved. Your text is still in the editor.', 503)
  }
  const draftHash = await draftHashFor(conversationId, String(draft.id), revision, recipient, subject, replyText, recipients.cc, recipients.bcc)
  await auth.payload.update({ collection: 'messages', id: draft.id as string, data: { approvalHash: draftHash } as never, overrideAccess: true })
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
  if (mailbox.outboundProvider !== 'resend' || mailbox.outboundMode !== 'business_correspondence') return fail('Business email sending is not configured for this website yet.', 409)
  const { env } = await messageRuntime()
  if (!env.RESEND_API_KEY) return fail('The Resend sender is not ready for this website yet.', 503)
  const recipient = text(row.participantEmail)
  const from = text(mailbox.address)
  try { normalizeHelloAdaEmail(recipient); normalizeHelloAdaEmail(from) } catch { return fail('The sender or recipient address is not valid.', 409) }
  const draft = await selectedDraft(auth.payload, conversationId)
  if (!draft || String(draft.deliveryState) !== 'draft') return fail('This reply is no longer an editable draft.', 409)
  const draftRevision = Number(draft.draftRevision || 0)
  const replyText = String(draft.text || draft.draftText || '')
  const subject = text(draft.subject || row.subject)
  let recipients: ReturnType<typeof validateHelloAdaRecipients>
  try { recipients = validateHelloAdaRecipients({ to: draft.to || recipient, cc: draft.ccRecipients, bcc: draft.bccRecipients }) }
  catch (error) { return fail(error instanceof Error ? error.message : 'Review the saved reply recipients.', 409) }
  if (recipients.to !== normalizeHelloAdaEmail(recipient)) return fail('The reply must remain addressed to the original conversation participant.', 409)
  const currentHash = await draftHashFor(conversationId, String(draft.id), draftRevision, recipient, subject, replyText, recipients.cc, recipients.bcc)
  if (currentHash !== draftHash) return fail('The reply changed after you reviewed it. Save and review it again.', 409)
  const approvedAt = nowIso()
  const approvedBy = String(auth.user.id)
  const operationBody = { messageId: draft.id, conversationId, draftHash, approvalHash: draftHash, draftRevision, from, to: recipient, cc: recipients.cc, bcc: recipients.bcc, subject, text: replyText, approvedBy, approvedAt }
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
  if (!['needs_reply', 'done', 'archived', 'spam', 'trash'].includes(state)) return fail('Choose a valid conversation state.')
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

const createOwnerMessageDraft = async (request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request, 16_384)
  let requestId: string
  let recipients: ReturnType<typeof validateHelloAdaRecipients>
  let subject: string
  let messageText: string
  try {
    requestId = helloAdaIdempotencyKey(input.requestId)
    recipients = validateHelloAdaRecipients({ to: input.to, cc: input.cc, bcc: input.bcc })
    subject = validateHelloAdaSubject(input.subject)
    messageText = validateHelloAdaReplyText(input.text)
  } catch (error) { return fail(error instanceof Error ? error.message : 'Complete the message fields before saving.') }
  const mailbox = await auth.payload.findGlobal({ slug: 'messageMailbox' as never, depth: 0, overrideAccess: false, req: auth.req, user: auth.user }) as unknown as MessageRecord
  if (mailbox.state !== 'active' || !mailbox.address) return fail('Business email is not active for this website.', 409)
  const sender = normalizeHelloAdaEmail(mailbox.address)
  const receiptId = `owner-compose:${tenantIdentity()}:${requestId}`
  const previous = await findMessageRecord(auth.payload, 'messages', { receiptId: { equals: receiptId } })
  if (previous) {
    if (previous.direction !== 'owner_message' || previous.deliveryState !== 'draft') return fail('That compose request has already been processed.', 409)
    const matches = String(previous.from) === sender && String(previous.to) === recipients.to
      && JSON.stringify(previous.ccRecipients || []) === JSON.stringify(recipients.cc)
      && JSON.stringify(previous.bccRecipients || []) === JSON.stringify(recipients.bcc)
      && String(previous.subject) === subject && String(previous.text) === messageText
    if (!matches) return fail('That compose request was already used for different content.', 409)
    const conversationId = text(typeof previous.conversation === 'object' ? object(previous.conversation).id : previous.conversation)
    const draftHash = await ownerMessageDraftHash(previous, conversationId, sender, Number(previous.draftRevision || 1), subject, messageText)
    return NextResponse.json({ messageId: previous.id, conversationId, draftHash }, { headers: noStore })
  }
  const contactEmail = recipients.to
  let contact: MessageRecord
  try {
    contact = await createOrUpdateContact(auth.payload, { email: contactEmail, emailKey: contactEmail, source: 'owner' }) as unknown as MessageRecord
  } catch (error) {
    console.error('helloada_owner_compose_contact_failed', { tenant: helloAdaSite.tenantId, error: error instanceof Error ? error.message : 'unknown' })
    return fail('The recipient could not be added to Contacts.', 503)
  }
  const operationId = await hashJson({ tenant: tenantIdentity(), requestId })
  const conversation = await createOrFindConversation(auth.payload, {
    subject, contact: contact.id, participantEmail: contactEmail, mailboxKey: sender,
    threadKey: `owner:${operationId}`, state: 'done', unread: false, source: 'owner',
    lastActivityAt: nowIso(), lastMessagePreview: messageText.slice(0, 500),
  })
  try {
    const message = await createMessageOnce(auth.payload, {
      conversation: conversation.id, direction: 'owner_message', from: sender, to: recipients.to,
      ccRecipients: recipients.cc, bccRecipients: recipients.bcc, subject, text: messageText, draftText: messageText,
      draftRevision: 1, deliveryState: 'draft', receiptId, operationId,
    })
    const draftHash = await ownerMessageDraftHash(message, String(conversation.id), sender, 1, subject, messageText)
    await auth.payload.update({ collection: 'messages', id: message.id as string, data: { approvalHash: draftHash } as never, overrideAccess: true })
    return NextResponse.json({ messageId: message.id, conversationId: conversation.id, draftHash }, { status: 201, headers: noStore })
  } catch (error) {
    console.error('helloada_owner_compose_draft_failed', { tenant: helloAdaSite.tenantId, error: error instanceof Error ? error.message : 'unknown' })
    return fail('The message could not be saved as a draft.', 503)
  }
}

const saveOwnerMessageDraft = async (messageId: string, request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request, 16_384)
  const allowed = ['to', 'cc', 'bcc', 'subject', 'text', 'expectedRevision']
  if (Object.keys(input).some((key) => !allowed.includes(key))) return fail('The draft contains unsupported fields.')
  let recipients: ReturnType<typeof validateHelloAdaRecipients>
  let subject: string
  let messageText: string
  try {
    recipients = validateHelloAdaRecipients({ to: input.to, cc: input.cc, bcc: input.bcc })
    subject = validateHelloAdaSubject(input.subject)
    messageText = validateHelloAdaReplyText(input.text)
  } catch (error) { return fail(error instanceof Error ? error.message : 'Complete the message before saving.') }
  const expectedRevision = Number(input.expectedRevision)
  if (!Number.isInteger(expectedRevision) || expectedRevision < 1) return fail('Reload this draft before saving it.', 409)
  const draft = await auth.payload.findByID({ collection: 'messages', id: messageId, depth: 0, overrideAccess: false, req: auth.req, user: auth.user }).catch(() => undefined)
  if (!draft || draft.direction !== 'owner_message' || draft.deliveryState !== 'draft') return fail('This outgoing draft is no longer editable.', 409)
  const row = draft as unknown as MessageRecord
  const revision = Number(row.draftRevision || 0)
  const conversationId = text(typeof row.conversation === 'object' ? object(row.conversation).id : row.conversation)
  if (!conversationId) return fail('This draft is not linked to a conversation.', 409)
  const mailbox = await auth.payload.findGlobal({ slug: 'messageMailbox' as never, depth: 0, overrideAccess: false, req: auth.req, user: auth.user }) as unknown as MessageRecord
  let sender: string
  try { sender = normalizeHelloAdaEmail(mailbox.address || row.from) }
  catch { return fail('The sender address is not configured for this draft.', 409) }
  const savedRecipients = validateHelloAdaRecipients({ to: row.to, cc: row.ccRecipients, bcc: row.bccRecipients })
  const alreadySaved = revision === expectedRevision + 1
    && savedRecipients.to === recipients.to
    && JSON.stringify(savedRecipients.cc) === JSON.stringify(recipients.cc)
    && JSON.stringify(savedRecipients.bcc) === JSON.stringify(recipients.bcc)
    && text(row.subject) === subject
    && String(row.text || row.draftText || '') === messageText
  if (revision !== expectedRevision && !alreadySaved) return fail('This draft changed in another session. Reload it before saving.', 409)
  if (alreadySaved) {
    try {
      const contact = await createOrUpdateContact(auth.payload, { email: recipients.to, emailKey: recipients.to, source: 'owner' }) as unknown as MessageRecord
      const draftHash = await ownerMessageDraftHash(row, conversationId, sender, revision, subject, messageText)
      await auth.payload.update({ collection: 'messages', id: messageId, data: { approvalHash: draftHash } as never, overrideAccess: true })
      await auth.payload.update({ collection: 'conversations', id: conversationId, data: {
        subject, contact: contact.id, participantEmail: recipients.to, lastActivityAt: nowIso(), lastMessagePreview: messageText.slice(0, 500),
      } as never, overrideAccess: true })
      return NextResponse.json({ draftHash, draftRevision: revision }, { headers: noStore })
    } catch (error) {
      console.error('helloada_owner_compose_draft_recovery_failed', { tenant: helloAdaSite.tenantId, messageId, error: error instanceof Error ? error.message : 'unknown' })
      return fail('The draft save is still being synchronized. Reload before making another change.', 503)
    }
  }
  const nextRevision = revision + 1
  try {
    const contact = await createOrUpdateContact(auth.payload, { email: recipients.to, emailKey: recipients.to, source: 'owner' }) as unknown as MessageRecord
    const updated = await auth.payload.update({ collection: 'messages', id: messageId, data: {
      from: sender, to: recipients.to, ccRecipients: recipients.cc, bccRecipients: recipients.bcc,
      subject, text: messageText, draftText: messageText, draftRevision: nextRevision, approvalHash: null,
    } as never, overrideAccess: true }) as unknown as MessageRecord
    const draftHash = await ownerMessageDraftHash(updated, conversationId, sender, nextRevision, subject, messageText)
    await auth.payload.update({ collection: 'messages', id: messageId, data: { approvalHash: draftHash } as never, overrideAccess: true })
    await auth.payload.update({ collection: 'conversations', id: conversationId, data: {
      subject, contact: contact.id, participantEmail: recipients.to, lastActivityAt: nowIso(), lastMessagePreview: messageText.slice(0, 500),
    } as never, overrideAccess: true })
    return NextResponse.json({ draftHash, draftRevision: nextRevision }, { headers: noStore })
  } catch (error) {
    console.error('helloada_owner_compose_draft_update_failed', { tenant: helloAdaSite.tenantId, messageId, error: error instanceof Error ? error.message : 'unknown' })
    return fail('The draft could not be saved. Reload it before continuing.', 503)
  }
}

const sendOwnerMessageDraft = async (messageId: string, request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request, 4_096)
  let requestId: string
  try { requestId = helloAdaIdempotencyKey(input.requestId) } catch { return fail('Review the saved message before sending.', 400) }
  const draftHash = text(input.draftHash)
  if (!/^[a-f0-9]{64}$/.test(draftHash)) return fail('Save and review this message before sending.', 409)
  const draft = await auth.payload.findByID({ collection: 'messages', id: messageId, depth: 0, overrideAccess: false, req: auth.req, user: auth.user }).catch(() => undefined)
  if (!draft || draft.direction !== 'owner_message' || draft.deliveryState !== 'draft') return fail('This outgoing draft is no longer available.', 409)
  const row = draft as unknown as MessageRecord
  const mailbox = await auth.payload.findGlobal({ slug: 'messageMailbox' as never, depth: 0, overrideAccess: false, req: auth.req, user: auth.user }) as unknown as MessageRecord
  if (mailbox.state !== 'active' || !mailbox.address) return fail('Business email is not active for this website.', 409)
  if (mailbox.outboundProvider !== 'resend' || mailbox.outboundMode !== 'business_correspondence') return fail('Business email sending is not configured for this website yet.', 409)
  const { env } = await messageRuntime()
  if (!env.RESEND_API_KEY) return fail('The Resend sender is not ready for this website yet.', 503)
  const recipients = validateHelloAdaRecipients({ to: row.to, cc: row.ccRecipients, bcc: row.bccRecipients })
  const conversationId = text(typeof row.conversation === 'object' ? object(row.conversation).id : row.conversation)
  const revision = Number(row.draftRevision || 0)
  const subject = validateHelloAdaSubject(row.subject)
  const messageText = validateHelloAdaReplyText(row.text)
  const from = normalizeHelloAdaEmail(mailbox.address)
  const currentHash = await ownerMessageDraftHash({ ...row, to: recipients.to, ccRecipients: recipients.cc, bccRecipients: recipients.bcc }, conversationId, from, revision, subject, messageText)
  if (currentHash !== draftHash || row.approvalHash !== draftHash) return fail('The message changed after review. Reload and review it again.', 409)
  const operationKey = `send-message:${tenantIdentity()}:${messageId}:${requestId}`
  const requestHash = await hashJson({ draftHash })
  const previous = await findMessageRecord(auth.payload, 'messageOperations', { idempotencyKey: { equals: operationKey } })
  if (previous) {
    if (String(previous.requestHash || '') !== requestHash) return fail('That send request ID belongs to a different reviewed message.', 409)
    const state = String(previous.state)
    if (['uncertain', 'failed'].includes(state)) return NextResponse.json({ state, message: state === 'uncertain' ? 'The email service response is uncertain. Do not send this message again yet.' : 'This send request failed and will not be retried automatically.' }, { status: 409, headers: noStore })
    return NextResponse.json({ queued: true, operationId: previous.operationId, state }, { status: 202, headers: noStore })
  }
  const approvedAt = nowIso()
  const approvedBy = String(auth.user.id)
  const operationBody = {
    messageId, conversationId, draftHash, approvalHash: draftHash, draftRevision: revision,
    from, to: recipients.to, cc: recipients.cc, bcc: recipients.bcc, subject, text: messageText,
    approvedBy, approvedAt,
  }
  let created: Awaited<ReturnType<typeof createMessageOperation>>
  try {
    created = await createMessageOperation(auth.payload, 'send_message', operationKey, operationBody, requestHash)
  } catch (error) { return fail(error instanceof Error ? error.message : 'This send request could not be accepted.', 409) }
  const operation = created.operation
  if (!created.created) {
    if (['uncertain', 'failed'].includes(String(operation.state))) return NextResponse.json({ state: operation.state, message: operation.state === 'uncertain' ? 'The email service response is uncertain. Do not send this message again yet.' : 'This send request failed and will not be retried automatically.' }, { status: 409, headers: noStore })
    return NextResponse.json({ queued: true, operationId: operation.operationId, state: operation.state }, { status: 202, headers: noStore })
  }
  try {
    await auth.payload.update({ collection: 'messages', id: messageId, data: {
      from, to: recipients.to, ccRecipients: recipients.cc, bccRecipients: recipients.bcc,
      approvedBy, approvedAt, operationId: String(operation.operationId), deliveryState: 'queued',
    } as never, overrideAccess: true })
  } catch (error) {
    await markMessageOperation(auth.payload, operation, 'failed', { errorCode: 'approval_persistence_failed', clearPayload: true })
    console.error('helloada_owner_message_approval_persist_failed', { tenant: helloAdaSite.tenantId, operationId: operation.operationId, error: error instanceof Error ? error.message : 'unknown' })
    return fail('Your approval could not be recorded, so the message was not sent.', 503)
  }
  try { await dispatchMessageOperation(env, operation) }
  catch (error) { console.error('helloada_owner_message_queue_deferred', { tenant: helloAdaSite.tenantId, operationId: operation.operationId, error: error instanceof Error ? error.message : 'unknown' }) }
  return NextResponse.json({ queued: true, operationId: operation.operationId }, { status: 202, headers: noStore })
}

const saveMailboxNotifications = async (
  auth: HelloAdaAuth,
  data: Record<string, unknown>,
) => auth.payload.updateGlobal({
  slug: 'messageMailbox' as never,
  data: data as never,
  overrideAccess: true,
  req: auth.req,
  user: auth.user,
})

const startNotificationVerification = async (request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request, 2_048)
  let address: string
  try { address = normalizeHelloAdaEmail(input.address) }
  catch (error) { return fail(error instanceof Error ? error.message : 'Enter a valid notification email address.') }
  const { payload, env } = await messageRuntime()
  const tenant = tenantIdentity()
  if (!tenant) return fail('This website is not ready to configure message notifications.', 503)
  const rateLimit = env.HELLOADA_NOTIFICATION_RATE_LIMIT
  if (!rateLimit) return fail('Notification verification is not configured for this website.', 503)
  try {
    const allowed = await rateLimit.limit({ key: `${tenant}:notification-start` })
    if (!allowed.success) return fail('Wait a minute before requesting another verification email.', 429)
  } catch (error) {
    console.error('helloada_notification_rate_limit_unavailable', { tenant: tenantIdentity(), error: error instanceof Error ? error.name : 'unknown' })
    return fail('Notification verification is temporarily unavailable.', 503)
  }
  const mailbox = await findMailbox(payload)
  if (mailbox.state !== 'active' || !mailbox.address) return fail('Domain email must be active before notifications can be configured.', 409)
  if (!env.EMAIL || !env.HELLOADA_SITE_AGENT_TOKEN) return fail('The tenant email service is not ready to verify this address.', 503)
  if (String(mailbox.notificationAddress || '') === address && mailbox.notificationVerifiedAt) {
    return NextResponse.json({ state: 'verified', mailbox: {
      notificationAddress: mailbox.notificationAddress, notificationVerifiedAt: mailbox.notificationVerifiedAt,
      notificationPendingAddress: mailbox.notificationPendingAddress, notificationCodeExpiresAt: mailbox.notificationCodeExpiresAt,
    } }, { headers: noStore })
  }
  const sentAt = Date.now()
  const previousSentAt = Date.parse(String(mailbox.notificationCodeSentAt || ''))
  if (Number.isFinite(previousSentAt) && sentAt - previousSentAt < 60_000) {
    return fail('Wait a minute before requesting another verification email.', 429)
  }
  const code = createMessageNotificationCode()
  const expiresAt = new Date(sentAt + 10 * 60_000).toISOString()
  const codeHash = await hashMessageNotificationCode(env.HELLOADA_SITE_AGENT_TOKEN, tenantIdentity(), address, code)
  await saveMailboxNotifications(auth, {
    notificationPendingAddress: address,
    notificationCodeHash: codeHash,
    notificationCodeExpiresAt: expiresAt,
    notificationCodeSentAt: new Date(sentAt).toISOString(),
    notificationCodeAttempts: 0,
  })
  const verification = buildNotificationVerificationEmail(address, code, helloAdaSite.defaultLocale)
  try {
    const result = await env.EMAIL.send({
      from: normalizeHelloAdaEmail(mailbox.address),
      ...verification,
    })
    if (!text(result.messageId)) throw new Error('Email service acceptance did not include a message ID.')
  } catch (error) {
    // Delivery may have been accepted before a provider timeout. Keep the
    // challenge usable and rate-limited instead of sending duplicate codes.
    console.error('helloada_notification_verification_delivery_uncertain', { tenant: tenantIdentity(), error: error instanceof Error ? error.name : 'unknown' })
    return NextResponse.json({
      error: 'helloada_messages_error',
      message: 'Delivery could not be confirmed. The code may still arrive; wait before requesting another.',
      state: 'delivery_uncertain',
      mailbox: {
        notificationAddress: mailbox.notificationAddress,
        notificationVerifiedAt: mailbox.notificationVerifiedAt,
        notificationPendingAddress: address,
        notificationCodeExpiresAt: expiresAt,
      },
    }, { status: 503, headers: noStore })
  }
  return NextResponse.json({ state: 'verification_sent', mailbox: {
    notificationAddress: mailbox.notificationAddress,
    notificationVerifiedAt: mailbox.notificationVerifiedAt,
    notificationPendingAddress: address,
    notificationCodeExpiresAt: expiresAt,
  } }, { headers: noStore })
}

const verifyNotificationAddress = async (request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const input = await bodyOf(request, 2_048)
  const code = text(input.code)
  if (!/^\d{8}$/.test(code)) return fail('Enter the eight-digit code from the verification email.')
  const { payload, env } = await messageRuntime()
  const tenant = tenantIdentity()
  if (!tenant) return fail('This website is not ready to verify message notifications.', 503)
  const rateLimit = env.HELLOADA_NOTIFICATION_RATE_LIMIT
  if (!rateLimit) return fail('Notification verification is not configured for this website.', 503)
  try {
    const allowed = await rateLimit.limit({ key: `${tenant}:notification-verify` })
    if (!allowed.success) return fail('Too many attempts. Wait a minute and try again.', 429)
  } catch (error) {
    console.error('helloada_notification_rate_limit_unavailable', { tenant: tenantIdentity(), error: error instanceof Error ? error.name : 'unknown' })
    return fail('Notification verification is temporarily unavailable.', 503)
  }
  const mailbox = await findMailbox(payload)
  const pendingAddress = String(mailbox.notificationPendingAddress || '')
  const expiresAt = Date.parse(String(mailbox.notificationCodeExpiresAt || ''))
  const attempts = Number(mailbox.notificationCodeAttempts || 0)
  const codeHash = String(mailbox.notificationCodeHash || '')
  if (!pendingAddress || !Number.isFinite(expiresAt) || expiresAt <= Date.now() || attempts >= 5 || !codeHash) {
    return fail('This code has expired or reached its attempt limit. Request a new one.', 409)
  }
  if (!env.HELLOADA_SITE_AGENT_TOKEN) return fail('The tenant verification service is not ready.', 503)
  const submittedHash = await hashMessageNotificationCode(env.HELLOADA_SITE_AGENT_TOKEN, tenantIdentity(), pendingAddress, code)
  if (!equalMessageNotificationCodeHash(submittedHash, codeHash)) {
    const nextAttempts = attempts + 1
    await saveMailboxNotifications(auth, {
      notificationCodeAttempts: nextAttempts,
      ...(nextAttempts >= 5 ? {
        notificationPendingAddress: null,
        notificationCodeHash: null,
        notificationCodeExpiresAt: null,
        notificationCodeSentAt: null,
        notificationCodeAttempts: 0,
      } : {}),
    })
    return fail(nextAttempts >= 5 ? 'The code was not accepted. Request a new verification code.' : 'That code is not correct.', 400)
  }
  const verifiedAt = nowIso()
  await saveMailboxNotifications(auth, {
    notificationAddress: pendingAddress,
    notificationVerifiedAt: verifiedAt,
    notificationPendingAddress: null,
    notificationCodeHash: null,
    notificationCodeExpiresAt: null,
    notificationCodeSentAt: null,
    notificationCodeAttempts: 0,
  })
  return NextResponse.json({ state: 'verified', mailbox: {
    notificationAddress: pendingAddress, notificationVerifiedAt: verifiedAt,
    notificationPendingAddress: null, notificationCodeExpiresAt: null,
  } }, { headers: noStore })
}

const disableMessageNotifications = async (request: Request, auth: HelloAdaAuth) => {
  if (!hasOwnerOrigin(request)) return fail('The request could not be verified.', 403)
  const mailbox = await saveMailboxNotifications(auth, {
    notificationAddress: null,
    notificationVerifiedAt: null,
    notificationPendingAddress: null,
    notificationCodeHash: null,
    notificationCodeExpiresAt: null,
    notificationCodeSentAt: null,
    notificationCodeAttempts: 0,
  }) as unknown as MessageRecord
  return NextResponse.json({ state: 'disabled', mailbox: {
    notificationAddress: mailbox.notificationAddress,
    notificationVerifiedAt: mailbox.notificationVerifiedAt,
    notificationPendingAddress: mailbox.notificationPendingAddress,
    notificationCodeExpiresAt: mailbox.notificationCodeExpiresAt,
  } }, { headers: noStore })
}

export async function ownerMessagesRoute(request: Request, path: string, auth: HelloAdaAuth) {
  try {
    if (request.method === 'GET' && path === '/calendar') return await readCalendar(auth)
    if (request.method === 'POST' && path === '/calendar/settings') return await saveCalendarSettings(request, auth)
    if (request.method === 'POST' && path === '/calendar/appointment-types') return await saveAppointmentType(request, auth)
    const calendarCancel = path.match(/^\/calendar\/events\/([^/]+)\/cancel$/)
    if (request.method === 'POST' && calendarCancel) return await cancelCalendarEvent(decodeURIComponent(calendarCancel[1]), request, auth)
    if (request.method === 'GET' && path === '/messages') return await readInbox(request, auth)
    if (request.method === 'POST' && path === '/messages/compose') return await createOwnerMessageDraft(request, auth)
    const outgoingDraftRoute = path.match(/^\/messages\/outgoing\/([^/]+)\/draft$/)
    if (request.method === 'POST' && outgoingDraftRoute) return await saveOwnerMessageDraft(decodeURIComponent(outgoingDraftRoute[1]), request, auth)
    const outgoingSendRoute = path.match(/^\/messages\/outgoing\/([^/]+)\/send$/)
    if (request.method === 'POST' && outgoingSendRoute) return await sendOwnerMessageDraft(decodeURIComponent(outgoingSendRoute[1]), request, auth)
    if (request.method === 'POST' && path === '/messages/notifications/start') return await startNotificationVerification(request, auth)
    if (request.method === 'POST' && path === '/messages/notifications/verify') return await verifyNotificationAddress(request, auth)
    if (request.method === 'POST' && path === '/messages/notifications/disable') return await disableMessageNotifications(request, auth)
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
  const notificationAddress = String(mailbox.notificationAddress || '')
  const notificationVerifiedAt = String(mailbox.notificationVerifiedAt || '')
  const ownerNotification = notificationAddress && notificationVerifiedAt
    ? { recipientAddress: notificationAddress, verifiedAt: notificationVerifiedAt }
    : undefined
  const data = { rawObjectKey, rawSha256, from, to, headers, ...(ownerNotification ? { ownerNotification } : {}) }
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
  if (input.outboundProvider !== 'resend' || input.outboundMode !== 'business_correspondence') {
    return fail('The mailbox must be provisioned with the canonical Resend sender.', 400)
  }
  let address: string
  try { address = normalizeHelloAdaEmail(input.address) }
  catch { return fail('The mailbox address is invalid.', 400) }
  if (!/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(domain)
    || address.split('@')[1] !== domain) return fail('The mailbox address must belong to its registered domain.', 400)
  try {
    const { payload, env } = await messageRuntime()
    if (!env.EMAIL || !env.RESEND_API_KEY) return fail('The tenant email services are not ready to activate business correspondence.', 503)
    const mailbox = await payload.updateGlobal({
      slug: 'messageMailbox' as never,
      data: {
        domain, address, outboundProvider: 'resend', outboundMode: 'business_correspondence',
        state: 'active', statusDetail: '', activatedAt: new Date().toISOString(),
      } as never,
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
