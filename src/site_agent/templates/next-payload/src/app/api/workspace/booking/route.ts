import { getCloudflareContext } from '@opennextjs/cloudflare'
import { NextResponse } from 'next/server'

import { helloAdaSite } from '@/helloada.config'
import { serviceAuthorized } from '@/lib/service-auth'
import type { BookingD1 } from '@/lib/helloada-booking-service'
import { getPublicBookingDetails } from '@/lib/helloada-booking-runtime'
import {
  createBookingType,
  deactivateBookingType,
  setBookingTypeActive,
  readBookingConfiguration,
  resolveTenantBookingOwner,
  updateBookingSettings,
  updateBookingType,
} from '@/lib/helloada-booking-service'

export const dynamic = 'force-dynamic'

type RuntimeEnv = { MAILFLARE_DB?: BookingD1 }
const noStore = { 'Cache-Control': 'private, no-store' }
const fail = (error: string, status: number) => NextResponse.json({ error }, { status, headers: noStore })
const text = (value: unknown) => typeof value === 'string' ? value.trim() : ''

async function ownerContext() {
  const tenantId = helloAdaSite.tenantId.trim()
  if (!tenantId) throw new Error('tenant_identity_not_configured')
  const env = (await getCloudflareContext({ async: true })).env as RuntimeEnv
  if (!env.MAILFLARE_DB) throw new Error('booking_database_not_configured')
  const ownerId = await resolveTenantBookingOwner(env.MAILFLARE_DB, tenantId)
  return { db: env.MAILFLARE_DB, ownerId }
}

function errorResponse(error: unknown) {
  const code = error instanceof Error ? error.message : 'booking_operation_failed'
  const status = code.endsWith('_conflict') ? 409
    : code === 'booking_type_not_found' ? 404
    : code.includes('_invalid') || code.endsWith('_required') || code.endsWith('_hours') ? 400
    : code === 'tenant_identity_not_configured' || code === 'booking_database_not_configured' || code === 'booking_owner_not_provisioned' ? 503
    : 500
  return fail(code, status)
}

export async function GET(request: Request) {
  if (!serviceAuthorized(request)) return fail('service_authentication_required', 401)
  try {
    const { db, ownerId } = await ownerContext()
    return NextResponse.json(await readBookingConfiguration(db, ownerId), { headers: noStore })
  } catch (error) {
    return errorResponse(error)
  }
}

export async function POST(request: Request) {
  if (!serviceAuthorized(request)) return fail('service_authentication_required', 401)
  const raw = await request.text()
  if (new TextEncoder().encode(raw).byteLength > 16_384) return fail('request_too_large', 413)
  let body: Record<string, unknown>
  try {
    const value: unknown = JSON.parse(raw)
    if (!value || typeof value !== 'object' || Array.isArray(value)) return fail('request_invalid', 400)
    body = value as Record<string, unknown>
  } catch { return fail('request_invalid', 400) }
  try {
    const { db, ownerId } = await ownerContext()
    const operation = text(body.operation)
    if (operation === 'update_settings') {
      return NextResponse.json({ settings: await updateBookingSettings(db, ownerId, body.settings) }, { headers: noStore })
    }
    if (operation === 'create_type') {
      return NextResponse.json({ type: await createBookingType(db, ownerId, body.type) }, { status: 201, headers: noStore })
    }
    if (operation === 'read_availability') {
      const bookingTypeId = text(body.bookingTypeId)
      const date = text(body.date)
      const details = await getPublicBookingDetails(db, helloAdaSite.tenantId.trim(), bookingTypeId, date, '')
      return NextResponse.json({ availability: {
        bookingTypeId: details.id, date, timeZone: details.timeZone, slots: details.slots,
      } }, { headers: noStore })
    }
    if (operation === 'update_type') {
      return NextResponse.json({ type: await updateBookingType(db, ownerId, text(body.id), Number(body.expectedRevision), body.type) }, { headers: noStore })
    }
    if (operation === 'activate_type') {
      return NextResponse.json({ type: await setBookingTypeActive(db, ownerId, text(body.id), Number(body.expectedRevision), true) }, { headers: noStore })
    }
    if (operation === 'deactivate_type') {
      return NextResponse.json({ type: await deactivateBookingType(db, ownerId, text(body.id), Number(body.expectedRevision)) }, { headers: noStore })
    }
    return fail('booking_operation_invalid', 400)
  } catch (error) {
    return errorResponse(error)
  }
}
