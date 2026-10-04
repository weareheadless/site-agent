import { NextResponse } from 'next/server'
import { getPayload } from 'payload'

import config from '@payload-config'
import { hashJson, withoutPayloadMetadata } from '@/lib/payload-hash'
import { serviceAuthorized } from '@/lib/service-auth'

const collections = ['pages', 'posts', 'products'] as const
const collectionFor = (value: unknown) => collections.find(item => item === value)

function errorResponse(message: string, status: number) {
  return NextResponse.json({ error: 'workspace_gateway_error', message }, { status })
}

export async function GET(request: Request) {
  if (!serviceAuthorized(request)) return errorResponse('service authentication required', 401)
  const params = new URL(request.url).searchParams
  const collection = collectionFor(params.get('collection') || 'pages')
  if (!collection) return errorResponse('unsupported collection', 400)
  const payload = await getPayload({ config })
  const draft = params.get('draft') === 'true'
  const locale = params.get('locale') || undefined
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
  const payload = await getPayload({ config })
  try {
    if (operation === 'create') {
      const document = await payload.create({ collection, data: (body.data || {}) as never, draft: true, overrideAccess: true })
      return NextResponse.json({ collection, document, documentHash: await hashJson(withoutPayloadMetadata(document as unknown as Record<string, unknown>)) }, { status: 201 })
    }
    const id = String(body.id || '').trim()
    if (!id) return errorResponse('id is required', 400)
    if (operation === 'update') {
      const expectedHash = String(body.expectedHash || '').trim()
      if (!/^sha256:[0-9a-f]{64}$/.test(expectedHash)) return errorResponse('expectedHash is required for a draft update', 400)
      const current = await payload.findByID({ collection, id, draft: true, overrideAccess: true }) as unknown as Record<string, unknown>
      if (await hashJson(withoutPayloadMetadata(current)) !== expectedHash) return errorResponse('The Payload draft changed. Read it again before updating.', 409)
      const document = await payload.update({ collection, id, data: (body.data || {}) as never, draft: true, overrideAccess: true })
      return NextResponse.json({ collection, document, documentHash: await hashJson(withoutPayloadMetadata(document as unknown as Record<string, unknown>)) })
    }
    if (operation === 'publish') {
      const expectedHash = String(body.expectedHash || '').trim()
      if (!/^sha256:[0-9a-f]{64}$/.test(expectedHash)) return errorResponse('expectedHash is required for publication', 400)
      const current = await payload.findByID({ collection, id, draft: true, overrideAccess: true }) as unknown as Record<string, unknown>
      const currentHash = await hashJson(withoutPayloadMetadata(current))
      if (currentHash !== expectedHash) return errorResponse('The Payload draft changed after review. Review the current version before publishing.', 409)
      await payload.update({ collection, id, data: withoutPayloadMetadata(current) as never, draft: false, overrideAccess: true })
      const published = await payload.findByID({ collection, id, draft: false, overrideAccess: true }) as unknown as Record<string, unknown>
      const documentHash = await hashJson(withoutPayloadMetadata(published))
      if (documentHash !== expectedHash) return errorResponse('Payload published a different document revision than the approved one.', 409)
      return NextResponse.json({ collection, document: published, documentHash })
    }
    return errorResponse('operation must be create, update, or publish', 400)
  } catch (error) {
    return errorResponse(error instanceof Error ? error.message : 'content operation failed', 400)
  }
}
