import PostalMime from 'postal-mime'
import { normalizeHelloAdaEmail, validateHelloAdaRecipients } from '@weareheadless/helloada-payload-core/messages'

import {
  claimMessageOperation,
  createMessageOperation,
  createMessageOnce,
  createOrFindConversation,
  createOrUpdateContact,
  enqueueAndMark,
  findMailbox,
  findMessageRecord,
  markMessageOperation,
  retryOrFailMessageOperation,
  messageRuntime,
  nowIso,
  operationBody,
  tenantIdentity,
  updateMessageOperation,
} from '@/lib/messages-service'
import type { MessageBindings, MessageRecord } from '@/lib/messages-service'
import { hashJson } from '@/lib/payload-hash'
import { helloAdaSite } from '@/helloada.config'
import { buildOwnerMessageNotification } from '@/lib/message-notifications'
import { bookingSlotsForDate, calendarSettings, findAppointmentType, localDateForInstant, releaseBookingSlots, reserveBookingSlot } from '@/lib/calendar'
import { sendResendMessage } from '@/lib/resend-mail'

const safeHeader = (value: unknown, max = 998) => String(value || '').replace(/[\r\n\0]/g, ' ').trim().slice(0, max)
const safeSubject = (value: unknown) => safeHeader(value, 180) || 'No subject'
const cleanBody = (value: unknown, max = 50_000) => String(value || '').replace(/\0/g, '').slice(0, max)
const relationId = (value: unknown) => value && typeof value === 'object' ? String((value as MessageRecord).id || '') : String(value || '')
const referencesOf = (value: unknown) => String(value || '').split(/\s+/).map((item) => safeHeader(item, 998)).filter(Boolean).slice(-30)
const permanentOperationError = (message: string) => Object.assign(new Error(message), { permanent: true })
const cloudflareTransactionalSender = (env: MessageBindings) => {
  if (!env.EMAIL) throw new Error('The tenant transactional email binding is unavailable.')
  return env.EMAIL
}

const requireResendMailbox = (mailbox: MessageRecord, env: MessageBindings) => {
  if (mailbox.outboundProvider !== 'resend' || mailbox.outboundMode !== 'business_correspondence') {
    throw permanentOperationError('Resend business correspondence is not enabled for this mailbox.')
  }
  if (!env.RESEND_API_KEY) throw permanentOperationError('The tenant Resend sender secret is unavailable.')
  return env.RESEND_API_KEY
}

const htmlToText = (html: string) => html
  .replace(/<(script|style|head|title|svg)[^>]*>[\s\S]*?<\/\1\s*>/gi, ' ')
  .replace(/<(br|hr)\b[^>]*>/gi, '\n')
  .replace(/<\/(p|div|li|tr|h[1-6])\s*>/gi, '\n')
  .replace(/<[^>]*>/g, ' ')
  .replace(/&nbsp;|&#160;/gi, ' ')
  .replace(/&amp;/gi, '&').replace(/&lt;/gi, '<').replace(/&gt;/gi, '>')
  .replace(/&quot;/gi, '"').replace(/&#39;|&apos;/gi, "'")
  .replace(/[ \t]+/g, ' ').replace(/\n[ \t]+/g, '\n').trim()

const getRaw = async (env: MessageBindings, key: string) => {
  const object = await env.PRIVATE_EMAIL?.get(key)
  if (!object) throw new Error('The private inbound message object is missing.')
  return object.arrayBuffer()
}

const enqueueOwnerMessageNotification = async (
  operation: MessageRecord,
  payload: Awaited<ReturnType<typeof messageRuntime>>['payload'],
  env: MessageBindings,
  message: MessageRecord,
  conversation: MessageRecord,
) => {
  const body = operationBody(operation)
  const preference = body.ownerNotification && typeof body.ownerNotification === 'object'
    ? body.ownerNotification as MessageRecord
    : undefined
  if (!preference?.recipientAddress || !preference.verifiedAt) return
  const recipientAddress = normalizeHelloAdaEmail(preference.recipientAddress)
  const id = String(message.id || '')
  const conversationId = String(conversation.id || '')
  if (!id || !conversationId) throw new Error('The accepted message has no stable notification identity.')
  const idempotencyKey = `owner-notification:${tenantIdentity()}:${id}`
  const notificationPayload = { messageId: id, conversationId, recipientAddress }
  const created = await createMessageOperation(
    payload, 'owner_notification', idempotencyKey, notificationPayload, await hashJson(notificationPayload),
  )
  await enqueueAndMark(payload, env, created.operation)
}

const applyFormAcceptance = async (
  operation: MessageRecord,
  payload: Awaited<ReturnType<typeof messageRuntime>>['payload'],
  env: MessageBindings,
) => {
  const body = operationBody(operation)
  const submission = body.submission as MessageRecord
  const contact = submission.contact as MessageRecord
  const mailbox = await findMailbox(payload)
  const mailboxAddress = String(mailbox.address || '').toLowerCase()
  const email = String(contact.email || '')
  const person = await createOrUpdateContact(payload, {
    email,
    emailKey: email,
    ...(contact.name ? { name: String(contact.name) } : {}),
    ...(contact.phone ? { phone: String(contact.phone) } : {}),
    ...(contact.company ? { company: String(contact.company) } : {}),
    source: 'form',
  }) as unknown as MessageRecord
  const now = nowIso()
  const formSnapshot = body.formSnapshot as MessageRecord
  const formTitle = safeSubject(formSnapshot.title)
  const subject = safeSubject(`Website enquiry: ${formTitle}`)
  const conversation = await createOrFindConversation(payload, {
    subject,
    contact: person.id,
    participantEmail: email,
    mailboxKey: mailboxAddress || 'website-enquiries',
    threadKey: `form:${String(operation.operationId)}`,
    state: 'needs_reply',
    unread: true,
    source: 'form',
    sourcePage: safeHeader(body.sourcePage, 500),
    lastActivityAt: now,
    lastMessagePreview: String(submission.message || '').slice(0, 500),
  })
  const message = await createMessageOnce(payload, {
    conversation: conversation.id,
    direction: 'form_enquiry',
    from: email,
    ...(mailboxAddress ? { to: mailboxAddress } : {}),
    subject,
    text: cleanBody(submission.message),
    deliveryState: 'received',
    form: formSnapshot.id,
    formSnapshot: { id: formSnapshot.id, slug: formSnapshot.slug, updatedAt: formSnapshot.updatedAt, answers: submission.answers },
    receiptId: String(operation.operationId),
    operationId: String(operation.operationId),
  })
  await payload.update({ collection: 'conversations', id: conversation.id as string, data: {
    lastMessagePreview: String(submission.message || '').slice(0, 500), lastActivityAt: now,
  } as never, overrideAccess: true })
  await enqueueOwnerMessageNotification(operation, payload, env, message, conversation)
  return message
}

const findThreadConversation = async (
  payload: Awaited<ReturnType<typeof messageRuntime>>['payload'],
  referenceIds: string[],
  sender: string,
) => {
  for (const reference of referenceIds) {
    const prior = await findMessageRecord(payload, 'messages', { externalMessageId: { equals: reference } })
    if (!prior) continue
    const conversation = await findMessageRecord(payload, 'conversations', { id: { equals: relationId(prior.conversation) } })
    if (!conversation) continue
    try {
      if (normalizeHelloAdaEmail(conversation.participantEmail) === sender) return conversation
    } catch { /* Invalid stored participant cannot be used to attach an inbound sender. */ }
  }
  return undefined
}

const applyInboundEmail = async (
  operation: MessageRecord,
  payload: Awaited<ReturnType<typeof messageRuntime>>['payload'],
  env: MessageBindings,
) => {
  const body = operationBody(operation)
  const mailbox = await findMailbox(payload)
  if (mailbox.state !== 'active' || !mailbox.address) throw new Error('The tenant mailbox is not active.')
  const recipient = normalizeHelloAdaEmail(body.to)
  const mailboxAddress = normalizeHelloAdaEmail(mailbox.address)
  if (recipient !== mailboxAddress) throw new Error('Inbound email does not match the configured tenant mailbox.')
  const envelopeFrom = normalizeHelloAdaEmail(body.from)
  const parsed = await PostalMime.parse(await getRaw(env, String(body.rawObjectKey || '')))
  const parsedAddress = parsed.from?.address
  const senderName = parsedAddress && normalizeHelloAdaEmail(parsedAddress) === envelopeFrom
    ? safeHeader(parsed.from?.name, 160)
    : ''
  const text = cleanBody(parsed.text || (parsed.html ? htmlToText(parsed.html) : ''), 50_000)
  if (!text.trim()) throw new Error('This inbound message contains no supported readable text.')
  const headerMap = new Map((parsed.headers || []).map((item) => [String(item.key || '').toLowerCase(), String(item.value || '')]))
  const messageId = safeHeader(headerMap.get('message-id') || (body.headers as MessageRecord | undefined)?.['message-id'], 998)
  const inReplyTo = safeHeader(headerMap.get('in-reply-to') || (body.headers as MessageRecord | undefined)?.['in-reply-to'], 998)
  const references = referencesOf(headerMap.get('references') || (body.headers as MessageRecord | undefined)?.references)
  const ccRecipients = [...new Set((parsed.cc || []).flatMap((address) => {
    if (!address.address) return []
    try { return [normalizeHelloAdaEmail(address.address)] } catch { return [] }
  }))].filter((address) => address !== envelopeFrom && address !== mailboxAddress).slice(0, 4)
  const contact = await createOrUpdateContact(payload, {
    email: envelopeFrom,
    emailKey: envelopeFrom,
    ...(senderName ? { name: senderName } : {}),
    source: 'email',
  }) as unknown as MessageRecord
  const joined = await findThreadConversation(payload, [...references, inReplyTo].filter(Boolean), envelopeFrom)
  const timestamp = nowIso()
  const subject = safeSubject(parsed.subject || (body.headers as MessageRecord | undefined)?.subject)
  const conversation = joined || await createOrFindConversation(payload, {
    subject,
    contact: contact.id,
    participantEmail: envelopeFrom,
    mailboxKey: mailboxAddress,
    threadKey: `email:${mailboxAddress}:${String(body.rawSha256 || operation.operationId)}`,
    state: 'needs_reply',
    unread: true,
    source: 'email',
    lastActivityAt: timestamp,
    lastMessagePreview: text.slice(0, 500),
  })
  let attachmentBytes = 0
  const attachments = []
  for (const [index, attachment] of (parsed.attachments || []).slice(0, 10).entries()) {
    const content = typeof attachment.content === 'string'
      ? new TextEncoder().encode(attachment.content)
      : new Uint8Array(attachment.content)
    const mimeType = safeHeader(attachment.mimeType, 160).toLowerCase()
    const filename = safeHeader(attachment.filename || `attachment-${index + 1}`, 180)
    const allowedType = ['application/pdf', 'image/jpeg', 'image/png', 'image/webp', 'text/plain', 'text/csv'].includes(mimeType)
    const allowed = allowedType && content.byteLength > 0 && content.byteLength <= 5 * 1024 * 1024 && attachmentBytes + content.byteLength <= 10 * 1024 * 1024
    if (allowed) {
      attachmentBytes += content.byteLength
      const key = `attachments/${operation.operationId}/${index}`
      const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', content))
      const sha256 = [...digest].map((byte) => byte.toString(16).padStart(2, '0')).join('')
      if (!env.PRIVATE_EMAIL) throw new Error('Tenant private attachment storage is unavailable.')
      const attachmentBuffer = new ArrayBuffer(content.byteLength)
      new Uint8Array(attachmentBuffer).set(content)
      await env.PRIVATE_EMAIL.put(key, attachmentBuffer, {
        httpMetadata: { contentType: mimeType },
        customMetadata: { tenant: tenantIdentity(), operationId: String(operation.operationId), sha256 },
      })
      attachments.push({ index, filename, mimeType, size: content.byteLength, sha256, key, allowed: true })
    } else {
      attachments.push({ index, filename, mimeType, size: content.byteLength, allowed: false })
    }
  }
  const message = await createMessageOnce(payload, {
    conversation: conversation.id,
    direction: 'received_email',
    from: envelopeFrom,
    to: mailboxAddress,
    ccRecipients,
    subject,
    text,
    deliveryState: 'received',
    externalMessageId: messageId || undefined,
    inReplyTo: inReplyTo || undefined,
    references,
    rawObjectKey: String(body.rawObjectKey || ''),
    attachmentManifest: attachments,
    operationId: String(operation.operationId),
  })
  await payload.update({ collection: 'conversations', id: conversation.id as string, data: {
    state: 'needs_reply', unread: true, lastActivityAt: timestamp, lastMessagePreview: text.slice(0, 500),
  } as never, overrideAccess: true })
  await enqueueOwnerMessageNotification(operation, payload, env, message, conversation)
  return message
}

const sendOwnerMessageNotification = async (
  operation: MessageRecord,
  payload: Awaited<ReturnType<typeof messageRuntime>>['payload'],
  env: MessageBindings,
) => {
  const body = operationBody(operation)
  const message = await findMessageRecord(payload, 'messages', { id: { equals: body.messageId } })
  const conversation = await findMessageRecord(payload, 'conversations', { id: { equals: body.conversationId } })
  if (!message || !conversation || !['form_enquiry', 'received_email'].includes(String(message.direction))) {
    throw permanentOperationError('The source enquiry for this notification no longer exists.')
  }
  const mailbox = await findMailbox(payload)
  let recipient: string
  let verifiedRecipient: string
  try { recipient = normalizeHelloAdaEmail(body.recipientAddress) }
  catch { throw permanentOperationError('The notification recipient is no longer valid.') }
  try { verifiedRecipient = normalizeHelloAdaEmail(mailbox.notificationAddress) }
  catch { throw permanentOperationError('This notification address is no longer verified.') }
  if (mailbox.state !== 'active' || !mailbox.notificationVerifiedAt || verifiedRecipient !== recipient) {
    throw permanentOperationError('This notification address is no longer verified.')
  }
  const sender = cloudflareTransactionalSender(env)
  const content = buildOwnerMessageNotification({
    mailboxAddress: normalizeHelloAdaEmail(mailbox.address),
    domain: String(mailbox.domain || ''),
    conversationId: String(conversation.id),
    sender: String(message.from || ''),
    subject: String(message.subject || ''),
    preview: String(message.text || ''),
    locale: helloAdaSite.defaultLocale,
  })
  try {
    const result = await sender.send({
      from: normalizeHelloAdaEmail(mailbox.address), to: recipient,
      subject: content.subject, text: content.text,
    })
    const providerId = safeHeader(result.messageId, 998)
    if (!providerId) throw new Error('Email service acceptance did not include a message ID.')
    return providerId
  } catch (error) {
    // The provider may have accepted the message before a timeout. Do not retry
    // an ambiguous send and risk sending duplicate owner notifications.
    throw Object.assign(new Error('Notification delivery could not be confirmed.'), { uncertain: true, cause: error })
  }
}

const sendApprovedReply = async (
  operation: MessageRecord,
  payload: Awaited<ReturnType<typeof messageRuntime>>['payload'],
  env: MessageBindings,
) => {
  const body = operationBody(operation)
  const message = await findMessageRecord(payload, 'messages', { id: { equals: body.messageId } })
  if (!message) throw new Error('The approved reply no longer exists.')
  const mailbox = await findMailbox(payload)
  if (mailbox.state !== 'active' || normalizeHelloAdaEmail(mailbox.address) !== normalizeHelloAdaEmail(body.from)) {
    throw new Error('The approved sender is no longer the active tenant mailbox.')
  }
  const conversation = await findMessageRecord(payload, 'conversations', { id: { equals: body.conversationId } })
  if (!conversation || normalizeHelloAdaEmail(conversation.participantEmail) !== normalizeHelloAdaEmail(body.to)) {
    throw new Error('The approved recipient no longer matches this conversation participant.')
  }
  let approvedRecipients: ReturnType<typeof validateHelloAdaRecipients>
  let savedRecipients: ReturnType<typeof validateHelloAdaRecipients>
  try {
    approvedRecipients = validateHelloAdaRecipients({ to: body.to, cc: body.cc, bcc: body.bcc })
    savedRecipients = validateHelloAdaRecipients({ to: message.to || conversation.participantEmail, cc: message.ccRecipients, bcc: message.bccRecipients })
  } catch {
    throw permanentOperationError('The approved reply recipients are no longer valid. Review and save the reply again.')
  }
  if (approvedRecipients.to !== savedRecipients.to
    || JSON.stringify(approvedRecipients.cc) !== JSON.stringify(savedRecipients.cc)
    || JSON.stringify(approvedRecipients.bcc) !== JSON.stringify(savedRecipients.bcc)
    || String(message.subject || '') !== String(body.subject || '')) {
    throw permanentOperationError('The saved reply recipients or subject changed after approval. Review the reply again.')
  }
  const expectedHash = await hashJson({
    conversationId: String(conversation.id),
    messageId: String(message.id),
    revision: Number(message.draftRevision || 0),
    recipient: normalizeHelloAdaEmail(body.to),
    cc: approvedRecipients.cc,
    bcc: approvedRecipients.bcc,
    subject: String(body.subject),
    replyText: String(body.text),
  })
  if (expectedHash !== String(body.approvalHash || '') || expectedHash !== String(message.approvalHash || '')
    || Number(message.draftRevision) !== Number(body.draftRevision) || String(message.text || '') !== String(body.text || '')) {
    throw new Error('The reply changed after owner approval; review and approve it again.')
  }
  await payload.update({ collection: 'messages', id: message.id as string, data: {
    deliveryState: 'sending', from: body.from, to: body.to,
    ccRecipients: approvedRecipients.cc, bccRecipients: approvedRecipients.bcc,
  } as never, overrideAccess: true })
  const apiKey = requireResendMailbox(mailbox, env)
  const previous = await findMessageRecord(payload, 'messages', {
    conversation: { equals: body.conversationId }, direction: { in: ['received_email', 'booking_notice'] },
  }, { sort: '-createdAt' })
  const priorIds = [String(previous?.externalMessageId || ''), ...referencesOf(previous?.references)].filter(Boolean)
  const headers: Record<string, string> = {}
  if (previous?.externalMessageId) headers['In-Reply-To'] = String(previous.externalMessageId)
  if (priorIds.length) headers.References = priorIds.slice(-30).join(' ')
  let providerId: string
  try {
    providerId = await sendResendMessage(apiKey, tenantIdentity(), String(operation.operationId), {
      from: String(body.from), to: String(body.to),
      ...(approvedRecipients.cc.length ? { cc: approvedRecipients.cc } : {}),
      ...(approvedRecipients.bcc.length ? { bcc: approvedRecipients.bcc } : {}),
      subject: String(body.subject), text: String(body.text), ...(Object.keys(headers).length ? { headers } : {}),
    })
  } catch (error) {
    const uncertain = Boolean(error && typeof error === 'object' && (error as { uncertain?: unknown }).uncertain)
    await payload.update({ collection: 'messages', id: message.id as string, data: {
      deliveryState: uncertain ? 'uncertain' : 'failed',
    } as never, overrideAccess: true })
    throw error
  }
  try {
    await payload.update({ collection: 'messages', id: message.id as string, data: {
      deliveryState: 'accepted', externalMessageId: providerId, approvedBy: String(body.approvedBy), approvedAt: String(body.approvedAt),
    } as never, overrideAccess: true })
    await payload.update({ collection: 'conversations', id: conversation.id as string, data: {
      lastActivityAt: nowIso(), lastMessagePreview: String(body.text).slice(0, 500),
    } as never, overrideAccess: true })
    return providerId
  } catch (error) {
    // Resend accepted the email, but the durable receipt could not be saved.
    throw Object.assign(new Error('Resend accepted the email, but the receipt could not be saved.'), { uncertain: true, cause: error })
  }
}

const sendApprovedOwnerMessage = async (
  operation: MessageRecord,
  payload: Awaited<ReturnType<typeof messageRuntime>>['payload'],
  env: MessageBindings,
) => {
  const body = operationBody(operation)
  const message = await findMessageRecord(payload, 'messages', { id: { equals: body.messageId } })
  const conversation = await findMessageRecord(payload, 'conversations', { id: { equals: body.conversationId } })
  if (!message || !conversation || message.direction !== 'owner_message') throw permanentOperationError('The outgoing message draft no longer exists.')
  const mailbox = await findMailbox(payload)
  if (mailbox.state !== 'active' || normalizeHelloAdaEmail(mailbox.address) !== normalizeHelloAdaEmail(body.from)) {
    throw permanentOperationError('The approved sender is no longer the active tenant mailbox.')
  }
  const apiKey = requireResendMailbox(mailbox, env)
  let recipients: ReturnType<typeof validateHelloAdaRecipients>
  try { recipients = validateHelloAdaRecipients({ to: body.to, cc: body.cc, bcc: body.bcc }) }
  catch { throw permanentOperationError('The approved message recipients are no longer valid. Review the draft again.') }
  const conversationId = String(conversation.id)
  const revision = Number(message.draftRevision || 0)
  const subject = safeSubject(body.subject)
  const text = cleanBody(body.text)
  const expectedHash = await hashJson({
    messageId: String(message.id), conversationId, revision, from: normalizeHelloAdaEmail(body.from),
    to: recipients.to, cc: recipients.cc, bcc: recipients.bcc, subject, text,
  })
  if (message.deliveryState !== 'queued'
    || String(message.operationId) !== String(operation.operationId)
    || String(message.from) !== normalizeHelloAdaEmail(body.from)
    || String(message.to) !== recipients.to
    || JSON.stringify(message.ccRecipients || []) !== JSON.stringify(recipients.cc)
    || JSON.stringify(message.bccRecipients || []) !== JSON.stringify(recipients.bcc)
    || String(message.subject) !== subject
    || String(message.text || '') !== text
    || revision !== Number(body.draftRevision)
    || expectedHash !== String(body.draftHash || '')
    || expectedHash !== String(body.approvalHash || '')
    || expectedHash !== String(message.approvalHash || '')) {
    throw permanentOperationError('The outgoing message changed after approval. Review and save it again.')
  }
  await payload.update({ collection: 'messages', id: message.id as string, data: { deliveryState: 'sending' } as never, overrideAccess: true })
  let providerId: string
  try {
    providerId = await sendResendMessage(apiKey, tenantIdentity(), String(operation.operationId), {
      from: normalizeHelloAdaEmail(body.from), to: recipients.to,
      ...(recipients.cc.length ? { cc: recipients.cc } : {}),
      ...(recipients.bcc.length ? { bcc: recipients.bcc } : {}),
      subject, text,
    })
  } catch (error) {
    const uncertain = Boolean(error && typeof error === 'object' && (error as { uncertain?: unknown }).uncertain)
    await payload.update({ collection: 'messages', id: message.id as string, data: {
      deliveryState: uncertain ? 'uncertain' : 'failed',
    } as never, overrideAccess: true })
    throw error
  }
  try {
    await payload.update({ collection: 'messages', id: message.id as string, data: {
      deliveryState: 'accepted', externalMessageId: providerId,
      approvedBy: String(body.approvedBy), approvedAt: String(body.approvedAt),
    } as never, overrideAccess: true })
    await payload.update({ collection: 'conversations', id: conversation.id as string, data: {
      lastActivityAt: nowIso(), lastMessagePreview: text.slice(0, 500),
    } as never, overrideAccess: true })
    return providerId
  } catch (error) {
    throw Object.assign(new Error('Resend accepted the email, but the receipt could not be saved.'), { uncertain: true, cause: error })
  }
}

const applyBooking = async (
  operation: MessageRecord,
  payload: Awaited<ReturnType<typeof messageRuntime>>['payload'],
  env: MessageBindings,
) => {
  const body = operationBody(operation)
  const operationId = String(operation.operationId)
  if (body.consent !== true) throw permanentOperationError('The visitor did not consent to appointment processing.')
  const appointmentType = await findAppointmentType(payload, String(body.appointmentType || ''))
  const settings = await calendarSettings(payload)
  if (!appointmentType || settings.enabled !== true) throw permanentOperationError('Online bookings are no longer enabled for this appointment type.')
  if (String(settings.timeZone || '') !== String(body.timeZone || '')) throw permanentOperationError('The business time zone changed. Please choose a new time.')
  const startsAt = new Date(String(body.startsAt || ''))
  if (!Number.isFinite(startsAt.getTime())) throw permanentOperationError('The appointment time is invalid.')
  const endsAt = new Date(startsAt.getTime() + Number(appointmentType.durationMinutes) * 60_000)
  if (endsAt.toISOString() !== String(body.endsAt || '')) throw permanentOperationError('The appointment time is invalid.')
  const existingEvent = await findMessageRecord(payload, 'calendarEvents', { receiptId: { equals: operationId } })
  if (!existingEvent) {
    const date = localDateForInstant(startsAt, String(settings.timeZone))
    const availability = await bookingSlotsForDate(payload, String(body.appointmentType), date, operationId)
    if (!availability.slots.some((slot) => slot.startsAt === startsAt.toISOString())) {
      throw Object.assign(new Error('That time is no longer available. Choose another time.'), { permanent: true, code: 'slot_unavailable' })
    }
    await reserveBookingSlot(payload, operationId, startsAt.toISOString(), endsAt.toISOString(), Number(appointmentType.bufferMinutes || 0))
  }
  const email = normalizeHelloAdaEmail(body.email)
  const contact = await createOrUpdateContact(payload, {
    email, emailKey: email, name: String(body.name || ''), source: 'booking',
  }) as unknown as MessageRecord
  const title = safeSubject(appointmentType.name || 'Appointment')
  const event = existingEvent || await payload.create({ collection: 'calendarEvents', data: {
    title, appointmentType: appointmentType.id, contact: contact.id,
    startsAt: startsAt.toISOString(), endsAt: endsAt.toISOString(),
    bufferMinutes: Number(appointmentType.bufferMinutes || 0), timeZone: String(settings.timeZone),
    state: 'confirmed', sourcePage: safeHeader(body.sourcePage, 500), receiptId: operationId,
    answers: body.answers && typeof body.answers === 'object' ? body.answers : {}, consentAcceptedAt: nowIso(), notificationState: 'pending',
  } as never, overrideAccess: true }) as unknown as MessageRecord
  await releaseBookingSlots(payload, operationId)

  const mailbox = await findMailbox(payload)
  const mailboxAddress = mailbox.state === 'active' ? normalizeHelloAdaEmail(mailbox.address) : ''
  const conversation = await createOrFindConversation(payload, {
    subject: `Booking confirmed: ${title}`, contact: contact.id, participantEmail: email,
    mailboxKey: mailboxAddress || 'website-bookings', threadKey: `booking:${operationId}`,
    state: 'done', unread: false, source: 'booking', sourcePage: safeHeader(body.sourcePage, 500),
    lastActivityAt: nowIso(), lastMessagePreview: `${title} · ${startsAt.toISOString()}`,
  })
  const prettyDate = new Intl.DateTimeFormat(helloAdaSite.defaultLocale || 'en', {
    timeZone: String(settings.timeZone), dateStyle: 'long', timeStyle: 'short',
  }).format(startsAt)
  const confirmationText = `Hello ${String(body.name || '').trim()},\n\nYour ${title} appointment is confirmed for ${prettyDate} (${String(settings.timeZone)}).\n\nIf you need to change this booking, reply to this email.\n\n${String(helloAdaSite.siteName || 'The team')}`
  const existingNotice = await findMessageRecord(payload, 'messages', { operationId: { equals: `${operationId}:notice` } })
  const notice = existingNotice || await createMessageOnce(payload, {
    conversation: conversation.id, direction: 'booking_notice', ...(mailboxAddress ? { from: mailboxAddress } : {}),
    to: email, subject: `Your ${title} is confirmed`, text: confirmationText,
    deliveryState: mailboxAddress ? 'queued' : 'failed',
    operationId: `${operationId}:notice`, receiptId: `${operationId}:notice`,
  })
  await payload.update({ collection: 'calendarEvents', id: event.id as string, data: {
    notificationState: mailboxAddress ? 'pending' : 'failed',
  } as never, overrideAccess: true })
  if (mailboxAddress) {
    const idempotencyKey = `booking-notification:${tenantIdentity()}:${operationId}`
    const notification = await createMessageOperation(payload, 'booking_notification', idempotencyKey, {
      eventId: event.id, eventState: 'confirmed', messageId: notice.id, conversationId: conversation.id,
      from: mailboxAddress, to: email, subject: `Your ${title} is confirmed`, text: confirmationText,
    })
    await enqueueAndMark(payload, env, notification.operation)
  }
  return event
}

const sendBookingNotification = async (
  operation: MessageRecord,
  payload: Awaited<ReturnType<typeof messageRuntime>>['payload'],
  env: MessageBindings,
) => {
  const body = operationBody(operation)
  const event = await findMessageRecord(payload, 'calendarEvents', { id: { equals: body.eventId } })
  const message = await findMessageRecord(payload, 'messages', { id: { equals: body.messageId } })
  const mailbox = await findMailbox(payload)
  if (!event || !message || event.state !== String(body.eventState || 'confirmed')) throw permanentOperationError('The booking notification no longer matches the calendar event.')
  if (mailbox.state !== 'active' || normalizeHelloAdaEmail(mailbox.address) !== normalizeHelloAdaEmail(body.from)) {
    throw permanentOperationError('The business email address is no longer active.')
  }
  const sender = cloudflareTransactionalSender(env)
  try {
    const result = await sender.send({ from: String(body.from), to: String(body.to), subject: String(body.subject), text: String(body.text) })
    const providerId = safeHeader(result.messageId, 998)
    if (!providerId) throw new Error('Email service acceptance did not include a message ID.')
    await payload.update({ collection: 'messages', id: message.id as string, data: {
      deliveryState: 'accepted', externalMessageId: providerId,
    } as never, overrideAccess: true })
    await payload.update({ collection: 'calendarEvents', id: event.id as string, data: { notificationState: 'accepted' } as never, overrideAccess: true })
    return providerId
  } catch (error) {
    await payload.update({ collection: 'messages', id: message.id as string, data: { deliveryState: 'uncertain' } as never, overrideAccess: true })
    await payload.update({ collection: 'calendarEvents', id: event.id as string, data: { notificationState: 'uncertain' } as never, overrideAccess: true })
    throw Object.assign(new Error('Booking confirmation delivery could not be confirmed.'), { uncertain: true, cause: error })
  }
}

export async function processHelloAdaMessageOperation(operationId: string, env: MessageBindings) {
  const { payload } = await messageRuntime()
  const operation = await findMessageRecord(payload, 'messageOperations', { operationId: { equals: operationId } })
  if (!operation) throw new Error('The message operation does not exist.')
  const type = String(operation.operationType)
  if (['completed', 'failed', 'uncertain'].includes(String(operation.state))) {
    return { accepted: true, state: String(operation.state) }
  }
  if (!['form_accept', 'inbound_email', 'owner_notification', 'save_draft', 'send_reply', 'send_message', 'book_appointment', 'booking_notification'].includes(type)) throw new Error('The message operation type is unsupported.')
  const claimed = await claimMessageOperation(env, operationId, type as 'form_accept' | 'inbound_email' | 'owner_notification' | 'save_draft' | 'send_reply' | 'send_message' | 'book_appointment' | 'booking_notification')
  if (!claimed) return { accepted: true, state: String(operation.state) }
  let providerAttempted = false
  try {
    let providerReference: string | undefined
    if (type === 'form_accept') await applyFormAcceptance(operation, payload, env)
    else if (type === 'inbound_email') await applyInboundEmail(operation, payload, env)
    else if (type === 'send_reply') providerReference = await sendApprovedReply(operation, payload, env)
    else if (type === 'send_message') providerReference = await sendApprovedOwnerMessage(operation, payload, env)
    else if (type === 'book_appointment') await applyBooking(operation, payload, env)
    else if (type === 'booking_notification') {
      providerReference = await sendBookingNotification(operation, payload, env)
      providerAttempted = true
    }
    else if (type === 'owner_notification') {
      providerReference = await sendOwnerMessageNotification(operation, payload, env)
      providerAttempted = true
    }
    else if (type === 'save_draft') {
      const body = operationBody(operation)
      const target = await findMessageRecord(payload, 'messages', { id: { equals: body.messageId } })
      if (!target || Number(target.draftRevision) !== Number(body.draftRevision)) throw new Error('The saved reply draft changed before its receipt completed.')
    } else throw new Error('The message operation type is unsupported.')
    const body = operationBody(operation)
    await markMessageOperation(payload, operation, 'completed', {
      ...(providerReference ? { providerReference } : {}),
      clearPayload: true,
      redactedPayload: type === 'form_accept' && body.clientFingerprint
        ? { redacted: true, clientFingerprint: body.clientFingerprint }
        : { redacted: true },
    })
    return { accepted: true, state: 'completed' }
  } catch (error) {
    const uncertain = Boolean(error && typeof error === 'object' && (error as { uncertain?: unknown }).uncertain)
    const permanent = Boolean(error && typeof error === 'object' && (error as { permanent?: unknown }).permanent)
    if ((type === 'owner_notification' || type === 'booking_notification') && permanent) {
      await markMessageOperation(payload, operation, 'failed', { errorCode: 'notification_cancelled' })
      if (type === 'booking_notification') {
        const body = operationBody(operation)
        const event = await findMessageRecord(payload, 'calendarEvents', { id: { equals: body.eventId } })
        const message = await findMessageRecord(payload, 'messages', { id: { equals: body.messageId } })
        if (event) await payload.update({ collection: 'calendarEvents', id: event.id as string, data: { notificationState: 'failed' } as never, overrideAccess: true })
        if (message) await payload.update({ collection: 'messages', id: message.id as string, data: { deliveryState: 'failed' } as never, overrideAccess: true })
      }
      return { accepted: true, state: 'failed' }
    }
    if ((type === 'send_reply' || type === 'send_message' || type === 'owner_notification' || type === 'booking_notification') && (uncertain || providerAttempted)) {
      await markMessageOperation(payload, operation, 'uncertain', { errorCode: 'delivery_uncertain' })
      return { accepted: true, state: 'uncertain' }
    }
    if (type === 'book_appointment' && permanent) {
      await releaseBookingSlots(payload, String(operation.operationId))
      await markMessageOperation(payload, operation, 'failed', { errorCode: String((error as { code?: unknown })?.code || 'booking_unavailable'), clearPayload: true })
      return { accepted: true, state: 'failed' }
    }
    if (type === 'send_reply' || type === 'send_message') {
      const body = operationBody(operation)
      const reply = await findMessageRecord(payload, 'messages', { id: { equals: body.messageId } })
      if (reply && String(reply.deliveryState) !== 'uncertain') await payload.update({ collection: 'messages', id: reply.id as string, data: { deliveryState: 'failed' } as never, overrideAccess: true })
      await markMessageOperation(payload, operation, 'failed', { errorCode: 'send_rejected' })
      return { accepted: true, state: 'failed' }
    }
    const recovery = await retryOrFailMessageOperation(payload, env, operation, 'message_processing_retry')
    console.error('helloada_message_processing_deferred', {
      tenant: tenantIdentity(), operationId, state: recovery.state, attempts: recovery.attempts,
      error: error instanceof Error ? error.message : 'unknown',
    })
    return { accepted: true, state: recovery.state, ...(recovery.nextAttemptAt ? { nextAttemptAt: recovery.nextAttemptAt } : {}) }
  }
}

export const hasCorrectTenant = (request: Request) => {
  const tenant = request.headers.get('x-helloada-tenant') || ''
  return Boolean(tenantIdentity()) && tenant === tenantIdentity()
}
