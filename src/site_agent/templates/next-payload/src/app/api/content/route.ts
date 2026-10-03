import { NextResponse } from 'next/server'
import { getPayload } from 'payload'

import config from '@payload-config'
import { serviceAuthorized } from '@/lib/service-auth'

const collections = ['pages', 'posts', 'products'] as const
const collectionFor = (value: unknown) => collections.find(item => item === value)

function errorResponse(message: string, status: number) {
  return NextResponse.json({ error: 'content_gateway_error', message }, { status })
}

export async function GET(request: Request) {
  if (!serviceAuthorized(request)) return errorResponse('service authentication required', 401)
  const params = new URL(request.url).searchParams
  const collection = collectionFor(params.get('collection') || 'pages')
  if (!collection) return errorResponse('unsupported collection', 400)
  const payload = await getPayload({ config })
  const draft = params.get('draft') === 'true'
  const identifier = params.get('id') || params.get('sourceId') || params.get('slug')
  if (!identifier) {
    const requestedLimit = Number(params.get('limit') || '100')
    const limit = Number.isFinite(requestedLimit) ? Math.max(1, Math.min(Math.trunc(requestedLimit), 100)) : 100
    const result = await payload.find({ collection, draft, limit, depth: 1, pagination: false, overrideAccess: true, sort: '-updatedAt' })
    return NextResponse.json({ collection, documents: result.docs }, { headers: { 'Cache-Control': 'no-store' } })
  }
  const result = params.get('id')
    ? await payload.findByID({ collection, id: identifier, draft, overrideAccess: true })
    : (await payload.find({ collection, where: { [params.has('sourceId') ? 'sourceId' : 'slug']: { equals: identifier } }, draft, limit: 1, overrideAccess: true })).docs[0]
  if (!result) return errorResponse('document not found', 404)
  return NextResponse.json({ collection, document: result }, { headers: { 'Cache-Control': 'no-store' } })
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
      return NextResponse.json({ collection, document }, { status: 201 })
    }
    const id = String(body.id || '').trim()
    if (!id) return errorResponse('id is required', 400)
    if (operation === 'update') {
      const document = await payload.update({ collection, id, data: (body.data || {}) as never, draft: true, overrideAccess: true })
      return NextResponse.json({ collection, document })
    }
    if (operation === 'publish') {
      const document = await payload.update({ collection, id, data: { _status: 'published' } as never, draft: false, overrideAccess: true })
      return NextResponse.json({ collection, document })
    }
    return errorResponse('operation must be create, update, or publish', 400)
  } catch (error) {
    return errorResponse(error instanceof Error ? error.message : 'content operation failed', 400)
  }
}
