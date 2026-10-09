import { NextResponse } from 'next/server'
import { helloAdaIdempotencyKey, validateHelloAdaBookingRequest } from '@weareheadless/helloada-payload-core/messages'
import { helloAdaSite } from '@/helloada.config'
import { bookingSlotsForDate, calendarSettings, findAppointmentType, localDateForInstant } from '@/lib/calendar'
import { processHelloAdaMessageOperation } from '@/lib/message-processing'
import {
  createMessageOperation, dispatchMessageOperation, findMessageRecord, messageRuntime, tenantIdentity, verifyTurnstile,
} from '@/lib/messages-service'
import { hashJson } from '@/lib/payload-hash'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const noStore = { 'Cache-Control': 'no-store' }
const fail = (message: string, status: number) => NextResponse.json({ error: message }, { status, headers: noStore })
const object = (value: unknown) => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const text = (value: unknown) => String(value ?? '').trim()
const sameOrigin = (request: Request) => {
  const origin = request.headers.get('origin')
  if (!origin) return false
  try { return new URL(origin).origin === new URL(request.url).origin } catch { return false }
}

export async function GET(request: Request) {
  try {
    if (!helloAdaSite.features.bookings) return fail('Online booking is not enabled for this website.', 404)
    const { payload } = await messageRuntime()
    const tenant = tenantIdentity()
    if (!tenant) return fail('Online booking is not configured for this website.', 503)
    const url = new URL(request.url)
    const receipt = text(url.searchParams.get('receipt'))
    if (receipt) {
      if (!/^[a-f0-9-]{36}$/i.test(receipt)) return fail('This booking receipt is invalid.', 404)
      const operation = await findMessageRecord(payload, 'messageOperations', { operationId: { equals: receipt } })
      if (!operation || operation.operationType !== 'book_appointment') return fail('This booking receipt could not be found.', 404)
      const event = await findMessageRecord(payload, 'calendarEvents', { receiptId: { equals: receipt } })
      const state = String(operation.state || 'accepted')
      return NextResponse.json({
        state,
        confirmed: event?.state === 'confirmed',
        confirmationEmail: event ? String(event.notificationState || 'pending') : 'pending',
        ...(state === 'failed' ? { message: operation.errorCode === 'slot_unavailable' ? 'That time was just booked. Choose another time.' : 'The booking could not be confirmed. Please try again.' } : {}),
      }, { status: state === 'failed' ? 409 : 200, headers: noStore })
    }
    const appointmentType = text(url.searchParams.get('appointmentType'))
    const date = text(url.searchParams.get('date'))
    if (!/^[a-z0-9][a-z0-9-]{0,79}$/.test(appointmentType)) return fail('Choose a valid appointment type.', 400)
    if (!date) {
      const [settings, type] = await Promise.all([calendarSettings(payload), findAppointmentType(payload, appointmentType)])
      return NextResponse.json({
        enabled: settings.enabled === true && Boolean(type), timeZone: String(settings.timeZone || 'UTC'),
        bookingWindowDays: Number(settings.bookingWindowDays || 60),
      }, { headers: noStore })
    }
    const availability = await bookingSlotsForDate(payload, appointmentType, date)
    return NextResponse.json(availability, { headers: noStore })
  } catch (error) {
    return fail(error instanceof Error ? error.message : 'Availability could not be loaded.', 503)
  }
}

export async function POST(request: Request) {
  if (!helloAdaSite.features.bookings) return fail('Online booking is not enabled for this website.', 404)
  if (!sameOrigin(request)) return fail('This booking request could not be verified.', 403)
  const declaredSize = Number(request.headers.get('content-length') || 0)
  if (declaredSize > 8_192) return fail('This booking request is too large.', 413)
  const raw = await request.text()
  if (new TextEncoder().encode(raw).byteLength > 8_192) return fail('This booking request is too large.', 413)
  let input: Record<string, unknown>
  try { input = object(JSON.parse(raw)) } catch { return fail('The booking request could not be read.', 400) }
  const allowed = new Set(['name', 'email', 'appointmentType', 'startsAt', 'timeZone', 'answers', 'consent', 'requestId', 'turnstileToken', 'website'])
  if (Object.keys(input).some((key) => !allowed.has(key))) return fail('This booking request contains unsupported information.', 400)
  let booking: ReturnType<typeof validateHelloAdaBookingRequest>
  let requestId: string
  try {
    booking = validateHelloAdaBookingRequest(input)
    requestId = helloAdaIdempotencyKey(input.requestId)
  } catch (error) { return fail(error instanceof Error ? error.message : 'Review the booking details and try again.', 400) }
  if (text(input.website)) return fail('This booking request could not be verified.', 400)

  const { payload, env } = await messageRuntime()
  const tenant = tenantIdentity()
  if (!tenant) return fail('Online booking is not configured for this website.', 503)
  const rateLimit = env.HELLOADA_BOOKING_RATE_LIMIT
  const remoteIp = request.headers.get('cf-connecting-ip') || ''
  if (!rateLimit || !remoteIp) return fail('Booking is temporarily unavailable. Please try again later.', 503)
  try {
    const allowedByRateLimit = await rateLimit.limit({ key: `${tenant}:${remoteIp}` })
    if (!allowedByRateLimit.success) return fail('Please wait a moment before trying another booking.', 429)
  } catch (error) {
    console.error('helloada_booking_rate_limit_unavailable', { tenant, error: error instanceof Error ? error.name : 'unknown' })
    return fail('Booking is temporarily unavailable. Please try again later.', 503)
  }
  const turnstileSecret = String(env.HELLOADA_TURNSTILE_SECRET_KEY || '')
  const token = text(input.turnstileToken)
  if (!turnstileSecret || !token || token.length > 2_048) return fail('Complete the security check and try again.', 400)
  let verified: boolean
  try { verified = await verifyTurnstile(turnstileSecret, token, remoteIp, new URL(request.url).hostname.toLowerCase()) }
  catch (error) {
    console.error('helloada_booking_turnstile_unavailable', { tenant, error: error instanceof Error ? error.name : 'unknown' })
    return fail('The security check is temporarily unavailable. Please try again.', 503)
  }
  if (!verified) return fail('The security check could not be verified. Please complete it again.', 400)

  const settings = await calendarSettings(payload)
  const appointmentType = await findAppointmentType(payload, booking.appointmentType)
  if (settings.enabled !== true || !appointmentType) return fail('This appointment type is not accepting bookings.', 404)
  if (booking.timeZone !== String(settings.timeZone || '')) return fail('The business calendar changed. Reload the available times and try again.', 409)
  const idempotencyKey = `booking:${tenant}:${booking.appointmentType}:${requestId}`
  const identity = { ...booking, timeZone: String(settings.timeZone) }
  const requestHash = await hashJson(identity)
  const previous = await findMessageRecord(payload, 'messageOperations', { idempotencyKey: { equals: idempotencyKey } })
  if (previous) {
    if (String(previous.requestHash || '') !== requestHash) return fail('That booking request ID was already used for different details. Reload and try again.', 409)
    return NextResponse.json({ receipt: previous.operationId, state: previous.state }, { status: 202, headers: noStore })
  }
  const date = localDateForInstant(new Date(booking.startsAt), booking.timeZone)
  const availability = await bookingSlotsForDate(payload, booking.appointmentType, date)
  const slot = availability.slots.find((candidate) => candidate.startsAt === booking.startsAt)
  if (!slot) return fail('That time is no longer available. Choose another time.', 409)

  const canonicalIdentity = { ...identity, startsAt: slot.startsAt, timeZone: availability.timeZone }
  const referer = request.headers.get('referer') || ''
  let sourcePage = ''
  try {
    const parsed = new URL(referer)
    if (parsed.origin === new URL(request.url).origin) sourcePage = `${parsed.pathname}${parsed.search}`.slice(0, 500)
  } catch { /* Referrer is never trusted as a redirect or destination. */ }
  const endsAt = new Date(new Date(slot.startsAt).getTime() + Number(appointmentType.durationMinutes) * 60_000).toISOString()
  let operation: Record<string, unknown>
  try {
    ({ operation } = await createMessageOperation(payload, 'book_appointment', idempotencyKey, {
      ...canonicalIdentity, endsAt, sourcePage,
      appointmentName: String(appointmentType.name || ''),
      durationMinutes: Number(appointmentType.durationMinutes),
      bufferMinutes: Number(appointmentType.bufferMinutes || 0),
    }, requestHash))
  } catch (error) {
    const raced = await findMessageRecord(payload, 'messageOperations', { idempotencyKey: { equals: idempotencyKey } })
    if (raced && String(raced.requestHash || '') === requestHash) {
      return NextResponse.json({ receipt: raced.operationId, state: raced.state }, { status: 202, headers: noStore })
    }
    return fail(error instanceof Error ? error.message : 'This time could not be reserved.', 409)
  }
  try { await dispatchMessageOperation(env, operation) }
  catch (error) { console.error('helloada_booking_queue_deferred', { tenant, operationId: operation.operationId, error: error instanceof Error ? error.message : 'unknown' }) }
  try {
    const result = await processHelloAdaMessageOperation(String(operation.operationId), env)
    if (result.state === 'failed') return fail('That time was just booked. Choose another time.', 409)
    return NextResponse.json({ receipt: operation.operationId, state: result.state }, { status: result.state === 'completed' ? 201 : 202, headers: noStore })
  } catch (error) {
    console.error('helloada_booking_processing_deferred', { tenant, operationId: operation.operationId, error: error instanceof Error ? error.message : 'unknown' })
    return NextResponse.json({ receipt: operation.operationId, state: 'accepted' }, { status: 202, headers: noStore })
  }
}
