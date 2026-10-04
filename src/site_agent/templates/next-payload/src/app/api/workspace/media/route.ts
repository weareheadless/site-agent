import { NextResponse } from 'next/server'
import { getPayload } from 'payload'

import config from '@payload-config'
import { hashJson, withoutPayloadMetadata } from '@/lib/payload-hash'
import { serviceAuthorized } from '@/lib/service-auth'

const errorResponse = (message: string, status = 400) =>
  NextResponse.json({ error: 'workspace_gateway_error', message }, { status })

export async function GET(request: Request) {
  if (!serviceAuthorized(request)) return errorResponse('service authentication required', 401)
  const params = new URL(request.url).searchParams
  const payload = await getPayload({ config })
  const identifier = params.get('id') || params.get('sourceId')
  if (identifier) {
    try {
      const media = params.has('id')
        ? await payload.findByID({ collection: 'media', id: identifier, depth: 1, overrideAccess: true })
        : (await payload.find({
          collection: 'media', depth: 1, limit: 1, overrideAccess: true,
          where: { sourceId: { equals: identifier } },
        })).docs[0]
      if (!media) return errorResponse('media document not found', 404)
      const document = media as unknown as Record<string, unknown>
      return NextResponse.json({
        media: document,
        documentHash: await hashJson(withoutPayloadMetadata(document)),
      }, { headers: { 'Cache-Control': 'no-store' } })
    } catch (error) {
      return errorResponse(error instanceof Error ? error.message : 'media read failed', 404)
    }
  }
  const requestedLimit = Number(params.get('limit') || '100')
  const limit = Number.isFinite(requestedLimit) ? Math.max(1, Math.min(Math.trunc(requestedLimit), 100)) : 100
  const result = await payload.find({
    collection: 'media', depth: 1, limit, pagination: false, overrideAccess: true, sort: '-updatedAt',
  })
  return NextResponse.json({ media: result.docs }, { headers: { 'Cache-Control': 'no-store' } })
}

export async function POST(request: Request) {
  if (!serviceAuthorized(request)) return errorResponse('service authentication required', 401)
  let body: Record<string, unknown>
  try {
    body = await request.json()
  } catch {
    return errorResponse('invalid json')
  }
  if (String(body.operation || '').trim().toLowerCase() !== 'update') {
    return errorResponse('only media metadata updates are available through the service gateway')
  }
  const id = String(body.id || '').trim()
  const expectedHash = String(body.expectedHash || '').trim()
  if (!id || !/^sha256:[0-9a-f]{64}$/.test(expectedHash)) {
    return errorResponse('media id and exact expectedHash are required')
  }
  const payload = await getPayload({ config })
  try {
    const current = await payload.findByID({ collection: 'media', id, depth: 1, overrideAccess: true }) as unknown as Record<string, unknown>
    if (await hashJson(withoutPayloadMetadata(current)) !== expectedHash) {
      return errorResponse('The media document changed. Read it again before updating.', 409)
    }
    const media = await payload.update({
      collection: 'media', id, data: (body.data || {}) as never, overrideAccess: true, depth: 1,
    }) as unknown as Record<string, unknown>
    return NextResponse.json({
      media,
      documentHash: await hashJson(withoutPayloadMetadata(media)),
    }, { headers: { 'Cache-Control': 'no-store' } })
  } catch (error) {
    return errorResponse(error instanceof Error ? error.message : 'media update failed', 400)
  }
}
