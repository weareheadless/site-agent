import { NextResponse } from 'next/server'
import { getCloudflareContext } from '@opennextjs/cloudflare'
import { getPayload } from 'payload'

import config from '@payload-config'
import { helloAdaSite } from '@/helloada.config'
import { hashJson, withoutPayloadMetadata } from '@/lib/payload-hash'
import { fieldMismatchDiagnostic, fieldMismatchKeys, fieldValueMatches } from '@/lib/payload-field-match'
import { resolvePayloadLocale, type HelloAdaPayloadLocale } from '@/lib/payload-locale'
import { serviceAuthorized } from '@/lib/service-auth'
import { validateHelloAdaAuthoringData } from '@weareheadless/helloada-payload-core/schema'
import type { BookingD1 } from '../../../../../mailflare-booking-service'
import { readBookingSettings, readBookingTypeById, resolveTenantBookingOwner } from '../../../../../mailflare-booking-service'

const collections = ['pages', 'posts', 'products'] as const
const collectionFor = (value: unknown) => collections.find(item => item === value)

const collectionEnabled = (collection: (typeof collections)[number]) =>
  collection === 'pages'
  || (collection === 'posts' && Boolean(helloAdaSite.features?.posts))
  || (collection === 'products' && Boolean(helloAdaSite.features?.commerce))

function errorResponse(message: string, status: number) {
  return NextResponse.json({ error: 'workspace_gateway_error', message }, { status })
}

type BookingValidationFailure = { status: number; message: string }

async function validateBookingBindings(value: unknown, requireEnabledSettings: boolean): Promise<BookingValidationFailure | null> {
  const ids = new Set<string>()
  const visit = (item: unknown): BookingValidationFailure | null => {
    if (Array.isArray(item)) {
      for (const child of item) {
        const failure = visit(child)
        if (failure) return failure
      }
      return null
    }
    if (!item || typeof item !== 'object') return null
    const row = item as Record<string, unknown>
    if (row.blockType === 'helloAdaBooking') {
      const id = String(row.bookingTypeId || '')
      if (!/^ha_booking_[a-f0-9]{32}$/.test(id)) return { status: 400, message: 'Every booking block must reference one immutable Mailflare booking type ID.' }
      ids.add(id)
    }
    for (const child of Object.values(row)) {
      const failure = visit(child)
      if (failure) return failure
    }
    return null
  }
  const malformed = visit(value)
  if (malformed) return malformed
  if (!ids.size) return null
  try {
    const env = (await getCloudflareContext({ async: true })).env as { MAILFLARE_DB?: BookingD1 }
    if (!env.MAILFLARE_DB) return { status: 503, message: 'The tenant booking service is not configured.' }
    const ownerId = await resolveTenantBookingOwner(env.MAILFLARE_DB, helloAdaSite.tenantId)
    for (const id of ids) {
      const type = await readBookingTypeById(env.MAILFLARE_DB, ownerId, id)
      if (!type.enabled) return { status: 409, message: 'A booking form references an inactive appointment type. Activate it or update the form before saving.' }
    }
    if (requireEnabledSettings) {
      const settings = await readBookingSettings(env.MAILFLARE_DB, ownerId)
      if (!settings.enabled) return { status: 409, message: 'Enable business booking settings and configure working hours before publishing a booking form.' }
    }
    return null
  } catch (error) {
    return { status: 503, message: error instanceof Error ? error.message : 'The tenant booking service could not validate the form.' }
  }
}

function payloadFailure(error: unknown, fallback: string) {
  const value = error && typeof error === 'object' ? error as Record<string, unknown> : {}
  const status = Number(value.status || value.statusCode)
  if ([400, 401, 403, 404, 409, 422].includes(status)) {
    return errorResponse(error instanceof Error ? error.message : fallback, status)
  }
  console.error('helloada_workspace_payload_operation_failed', {
    errorName: error instanceof Error ? error.name : 'UnknownError',
    status: Number.isFinite(status) ? status : undefined,
  })
  return errorResponse(fallback, 503)
}

export async function GET(request: Request) {
  if (!serviceAuthorized(request)) return errorResponse('service authentication required', 401)
  const params = new URL(request.url).searchParams
  const collection = collectionFor(params.get('collection') || 'pages')
  if (!collection) return errorResponse('unsupported collection', 400)
  if (!collectionEnabled(collection)) return errorResponse('website module is not enabled', 403)
  let locale: HelloAdaPayloadLocale | undefined
  try {
    locale = resolvePayloadLocale(params.get('locale') || helloAdaSite.defaultLocale, helloAdaSite.locales)
  } catch {
    return errorResponse('unsupported locale', 400)
  }
  const payload = await getPayload({ config })
  const draft = params.get('draft') === 'true'
  const identifier = params.get('id') || params.get('sourceId') || params.get('slug')
  if (!identifier) {
    const requestedLimit = Number(params.get('limit') || '100')
    const limit = Number.isFinite(requestedLimit) ? Math.max(1, Math.min(Math.trunc(requestedLimit), 100)) : 100
    const result = await payload.find({ collection, draft, locale, limit, depth: 1, pagination: false, overrideAccess: true, sort: '-updatedAt' })
    return NextResponse.json({ collection, documents: result.docs }, { headers: { 'Cache-Control': 'no-store' } })
  }
  const result = params.get('id')
    ? await payload.findByID({ collection, id: identifier, draft, locale, overrideAccess: true })
    : (await payload.find({ collection, where: { [params.has('sourceId') ? 'sourceId' : 'slug']: { equals: identifier } }, draft, locale, limit: 1, overrideAccess: true })).docs[0]
  if (!result) return errorResponse('document not found', 404)
  return NextResponse.json({
    collection,
    document: result,
    documentHash: await hashJson(withoutPayloadMetadata(result as unknown as Record<string, unknown>)),
  }, { headers: { 'Cache-Control': 'no-store' } })
}

export async function POST(request: Request) {
  if (!serviceAuthorized(request)) return errorResponse('service authentication required', 401)
  let body: Record<string, unknown>
  try {
    body = await request.json()
  } catch {
    return errorResponse('invalid json', 400)
  }
  const operation = String(body.operation || '').trim().toLowerCase()
  const collection = collectionFor(body.collection || 'pages')
  if (!collection) return errorResponse('unsupported collection', 400)
  if (!collectionEnabled(collection)) return errorResponse('website module is not enabled', 403)
  const data = body.data && typeof body.data === 'object' && !Array.isArray(body.data)
    ? body.data as Record<string, unknown>
    : {}
  if (operation === 'create' || operation === 'update') {
    try {
      validateHelloAdaAuthoringData('collection', collection, data, { operation })
    } catch (error) {
      return errorResponse(error instanceof Error ? error.message : 'content does not match the shared authoring schema', 400)
    }
  }
  if (['create', 'update', 'publish'].includes(operation) && (typeof body.locale !== 'string' || !body.locale.trim())) {
    return errorResponse('an explicit Payload locale is required for every content write', 400)
  }
  let locale: HelloAdaPayloadLocale | undefined
  try {
    locale = resolvePayloadLocale(body.locale || helloAdaSite.defaultLocale, helloAdaSite.locales)
  } catch {
    return errorResponse('unsupported locale', 400)
  }
  const payload = await getPayload({ config })
  try {
    if (operation === 'create') {
      const bookingFailure = await validateBookingBindings(data, false)
      if (bookingFailure) return errorResponse(bookingFailure.message, bookingFailure.status)
      const slug = String(data.slug || '').trim()
      if (!slug) return errorResponse('a stable route slug is required for an idempotent Payload draft create', 400)
      const existing = await payload.find({
        collection,
        where: { slug: { equals: slug } },
        draft: true,
        locale,
        depth: 1,
        limit: 2,
        pagination: false,
        overrideAccess: true,
      })
      if (existing.docs.length > 1) return errorResponse('the route slug is ambiguous; no draft was changed', 409)
      if (existing.docs.length === 1) {
        const document = existing.docs[0] as unknown as Record<string, unknown>
        if (!fieldValueMatches(document, data)) return errorResponse('a Payload document already uses this route; read and update that exact draft instead', 409)
        return NextResponse.json({
          collection,
          document,
          documentHash: await hashJson(withoutPayloadMetadata(document)),
          idempotent: true,
          effectKey: `${collection}:${slug}`,
        }, { headers: { 'Cache-Control': 'no-store' } })
      }
      let document: Record<string, unknown>
      try {
        document = await payload.create({ collection, data: data as never, draft: true, locale, overrideAccess: true }) as unknown as Record<string, unknown>
      } catch (error) {
        // The unique route is the destination's idempotency key. A concurrent
        // duplicate or lost create response is successful only when the exact
        // same owner data now exists at that route.
        let raced
        try {
          raced = await payload.find({
            collection,
            where: { slug: { equals: slug } },
            draft: true,
            locale,
            depth: 1,
            limit: 2,
            pagination: false,
            overrideAccess: true,
          })
        } catch (reconcileError) {
          return payloadFailure(reconcileError, 'Payload could not confirm whether the draft was saved. Read the route before retrying.')
        }
        if (raced.docs.length === 1 && fieldValueMatches(raced.docs[0] as unknown as Record<string, unknown>, data)) {
          const saved = raced.docs[0] as unknown as Record<string, unknown>
          return NextResponse.json({
            collection,
            document: saved,
            documentHash: await hashJson(withoutPayloadMetadata(saved)),
            idempotent: true,
            effectKey: `${collection}:${slug}`,
          }, { headers: { 'Cache-Control': 'no-store' } })
        }
        if (raced.docs.length > 0) return errorResponse('A Payload document already occupies this route with different content.', 409)
        return payloadFailure(error, 'Payload could not create the draft. No duplicate will be attempted automatically.')
      }
      const mismatchKeys = fieldMismatchKeys(document, data)
      if (mismatchKeys.length) return errorResponse(fieldMismatchDiagnostic(mismatchKeys), 409)
      return NextResponse.json({
        collection,
        document,
        documentHash: await hashJson(withoutPayloadMetadata(document)),
        idempotent: false,
        effectKey: `${collection}:${slug}`,
      }, { status: 201 })
    }
    const id = String(body.id || '').trim()
    if (!id) return errorResponse('id is required', 400)
    if (operation === 'update') {
      const expectedHash = String(body.expectedHash || '').trim()
      if (!/^sha256:[0-9a-f]{64}$/.test(expectedHash)) return errorResponse('expectedHash is required for a draft update', 400)
      const current = await payload.findByID({ collection, id, draft: true, locale, depth: 1, overrideAccess: true }) as unknown as Record<string, unknown>
      if (await hashJson(withoutPayloadMetadata(current)) !== expectedHash) return errorResponse('The Payload draft changed. Read it again before updating.', 409)
      const bookingFailure = await validateBookingBindings({ ...current, ...data }, false)
      if (bookingFailure) return errorResponse(bookingFailure.message, bookingFailure.status)
      let document: Record<string, unknown>
      try {
        document = await payload.update({
          collection,
          id,
          data: data as never,
          draft: true,
          locale,
          overrideAccess: true,
          context: { helloAdaExpectedRevision: { kind: 'collection', collection, id, hash: expectedHash, locale } },
        }) as unknown as Record<string, unknown>
      } catch (error) {
        const latest = await payload.findByID({ collection, id, draft: true, locale, depth: 1, overrideAccess: true }) as unknown as Record<string, unknown>
        if (!fieldValueMatches(latest, data)) {
          return errorResponse(error instanceof Error ? error.message : 'draft update failed', 409)
        }
        return NextResponse.json({
          collection,
          document: latest,
          documentHash: await hashJson(withoutPayloadMetadata(latest)),
          idempotent: true,
          effectKey: `${collection}:${id}:${expectedHash}`,
        }, { headers: { 'Cache-Control': 'no-store' } })
      }
      const mismatchKeys = fieldMismatchKeys(document, data)
      if (mismatchKeys.length) return errorResponse(fieldMismatchDiagnostic(mismatchKeys), 409)
      return NextResponse.json({
        collection,
        document,
        documentHash: await hashJson(withoutPayloadMetadata(document)),
        idempotent: false,
        effectKey: `${collection}:${id}:${expectedHash}`,
      })
    }
    if (operation === 'publish') {
      const expectedHash = String(body.expectedHash || '').trim()
      if (!/^sha256:[0-9a-f]{64}$/.test(expectedHash)) return errorResponse('expectedHash is required for publication', 400)
      const current = await payload.findByID({ collection, id, draft: true, locale, overrideAccess: true }) as unknown as Record<string, unknown>
      const currentHash = await hashJson(withoutPayloadMetadata(current))
      if (currentHash !== expectedHash) return errorResponse('The Payload draft changed after review. Review the current version before publishing.', 409)
      const bookingFailure = await validateBookingBindings(current, true)
      if (bookingFailure) return errorResponse(bookingFailure.message, bookingFailure.status)
      await payload.update({
        collection,
        id,
        data: withoutPayloadMetadata(current) as never,
        draft: false,
        locale,
        overrideAccess: true,
        context: { helloAdaExpectedRevision: { kind: 'collection', collection, id, hash: expectedHash, locale } },
      })
      const published = await payload.findByID({ collection, id, draft: false, locale, overrideAccess: true }) as unknown as Record<string, unknown>
      const documentHash = await hashJson(withoutPayloadMetadata(published))
      if (documentHash !== expectedHash) return errorResponse('Payload published a different document revision than the approved one.', 409)
      return NextResponse.json({ collection, document: published, documentHash })
    }
    return errorResponse('operation must be create, update, or publish', 400)
  } catch (error) {
    return payloadFailure(error, 'Payload could not complete the content operation. Read the current document before retrying.')
  }
}
