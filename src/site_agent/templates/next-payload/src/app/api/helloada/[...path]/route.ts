import { NextResponse } from 'next/server'
import { getPayload } from 'payload'
import type { CollectionSlug, PayloadRequest } from 'payload'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { authenticateHelloAdaRequest } from '@/lib/helloada-auth'
import { fetchHelloAdaUpstream } from '@/lib/helloada-upstream'
import { helloAdaConnection, helloAdaRuntimeStatus } from '@weareheadless/helloada-payload-admin/server'
import { helloAdaSite } from '@/helloada.config'
import PublicDocument from '@/components/PublicDocument'
import {
  activeOperation,
  asObject as growthObject,
  candidateRow,
  claimOperation,
  completeOperation,
  contractCapabilities,
  ensureGrowthTables,
  failOperation,
  hashJson,
  operationContext,
  operationResult,
  projectDocument,
  saveCandidate,
  tenantId,
} from '@/lib/growth-contract'

export const dynamic = 'force-dynamic'

type RouteProps = { params: Promise<{ path?: string[] }> }

const errorResponse = (message: string, status = 400) => NextResponse.json({ error: 'helloada_bridge_error', message }, { status })

const editableCollections = ['pages', 'posts', 'products'] as const
type EditableCollection = (typeof editableCollections)[number]

class PayloadWorkspaceQueryError extends Error {
  constructor(public readonly collection: EditableCollection, cause: unknown) {
    super(`Payload workspace query failed for collection "${collection}"`, { cause })
    this.name = 'PayloadWorkspaceQueryError'
  }
}

const errorMessage = (cause: unknown) => cause instanceof Error ? cause.message : String(cause)

const isEditableCollection = (value: unknown): value is EditableCollection =>
  editableCollections.includes(String(value || '') as EditableCollection)

const asObject = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}

const text = (value: unknown) => String(value ?? '').trim()

const plainText = (value: unknown): string => {
  if (typeof value === 'string') return value.trim()
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  const node = value as Record<string, unknown>
  if (node.root && typeof node.root === 'object') return plainText(node.root)
  if (typeof node.text === 'string') return node.text
  if (!Array.isArray(node.children)) return ''
  return node.children.map(plainText).filter(Boolean).join('\n').trim()
}

const seoValue = (document: Record<string, unknown>) => asObject(document.seo)

const seoUpdate = (document: Record<string, unknown>, name: 'seoTitle' | 'seoDescription', value: string) => {
  const current = seoValue(document)
  const image = current.image
  return {
    title: name === 'seoTitle' ? value : text(current.title),
    description: name === 'seoDescription' ? value : text(current.description),
    ...(image && typeof image === 'object' && !Array.isArray(image)
      ? { image: asObject(image).id }
      : image
        ? { image }
        : {}),
  }
}

const lexicalDocumentFromText = (value: string) => ({
  root: {
    type: 'root',
    children: value.split(/\r?\n/).map((line) => ({
      type: 'paragraph',
      children: line ? [{ detail: 0, format: 0, mode: 'normal', style: '', text: line, type: 'text', version: 1 }] : [],
      direction: null,
      format: '',
      indent: 0,
      version: 1,
    })),
    direction: null,
    format: '',
    indent: 0,
    version: 1,
  },
})

const contentRoute = (value: string) => {
  const route = value.trim() || '/'
  return route === '/' ? '/' : `/${route.replace(/^\/+/, '').replace(/\/+$/, '')}`
}

const contentSlug = (route: string) => {
  const normalized = contentRoute(route)
  return normalized === '/' ? ['home', 'index', ''] : [normalized.slice(1)]
}

const collectionFieldNames = (payload: Awaited<ReturnType<typeof getPayload>>, collection: EditableCollection) => {
  const configured = (payload.config.collections as unknown as Array<{ slug?: string; fields?: Array<{ name?: string }> }>)
    .find((item) => item.slug === collection)
  return new Set((configured?.fields || []).map((field) => text(field.name)).filter(Boolean))
}

const equalJson = async (left: unknown, right: unknown) => (await hashJson(left)) === (await hashJson(right))

const renderCandidate = async (
  payload: Awaited<ReturnType<typeof getPayload>>,
  collection: EditableCollection,
  document: Record<string, unknown>,
  route: string,
) => {
  const settings = await payload.findGlobal({ slug: 'siteSettings', draft: false, depth: 2, overrideAccess: true }) as unknown as Record<string, unknown>
  const markup = renderToStaticMarkup(
    createElement(PublicDocument, { document, settings, kind: collection === 'posts' ? 'post' : 'page' }),
  )
  if (!markup.includes('content-page') || !markup.trim()) throw new Error('The public renderer returned no content')
  return { status: 'passed', route, kind: collection === 'posts' ? 'post' : 'page', htmlHash: await hashJson(markup), markupBytes: new TextEncoder().encode(markup).byteLength }
}

const verifyGrowthPackage = async (
  payload: Awaited<ReturnType<typeof getPayload>>,
  packageData: Record<string, unknown>,
  packageHash: string,
  request: Request,
  options: { requireDraftCandidate: boolean } = { requireDraftCandidate: true },
) => {
  if (await hashJson(packageData) !== packageHash) throw new Error('Growth package hash does not match its contents')
  if (text(packageData.tenant) !== tenantId() || !text(packageData.initiativeId)) throw new Error('Growth package belongs to a different tenant or initiative')
  const collection = text(packageData.collection)
  if (!isEditableCollection(collection)) throw new Error('Growth package collection is not editable')
  const documentId = text(packageData.documentId)
  const fields = Array.isArray(packageData.fields) ? packageData.fields.map(text).filter(Boolean) : []
  if (!documentId || !fields.length || new Set(fields).size !== fields.length) throw new Error('Growth package fields are invalid')
  const configured = collectionFieldNames(payload, collection)
  if (fields.some((field) => !configured.has(field))) throw new Error('Growth package references fields outside the destination schema')
  const before = growthObject(packageData.before)
  const after = growthObject(packageData.after)
  const changes = growthObject(packageData.changes)
  if (!Object.keys(after).length || Object.keys(changes).some((field) => !fields.includes(field))) throw new Error('Growth package candidate fields are invalid')
  const live = await payload.findByID({ collection: collection as CollectionSlug, depth: 2, draft: false, id: documentId, overrideAccess: true }) as unknown as Record<string, unknown>
  const draft = await payload.findByID({ collection: collection as CollectionSlug, depth: 2, draft: true, id: documentId, overrideAccess: true }) as unknown as Record<string, unknown>
  const liveProjection = projectDocument(live, fields)
  const draftProjection = projectDocument(draft, fields)
  if (await hashJson(liveProjection) !== text(packageData.baseHash)) throw new Error('The published document changed; this Growth package is stale')
  if (await hashJson(before) !== text(packageData.baseHash)) throw new Error('Growth package does not describe the published base')
  if (await hashJson(after) !== text(packageData.candidateHash)) throw new Error('Growth package candidate hash is invalid')
  const expected = { ...liveProjection, ...changes }
  if (!await equalJson(after, expected)) throw new Error('Growth package after-state is not the exact base plus requested changes')
  if (options.requireDraftCandidate && await hashJson(draftProjection) !== text(packageData.candidateHash)) throw new Error('The exact Growth candidate is not the current Payload draft')
  const route = contentRoute(text(packageData.route) || (text(live.slug) === 'home' ? '/' : `/${text(live.slug)}`))
  const publicRenderer = await renderCandidate(payload, collection, after, route)
  return { collection, documentId, fields, live, draft, liveProjection, draftProjection, before, after, changes, route, publicRenderer, request }
}

type EditableQueryOptions = {
  depth: number
  limit: number
  overrideAccess: boolean
  req?: Partial<PayloadRequest>
  where?: { slug: { equals: string } }
}

type EditableDocumentsResult = {
  documents: Record<string, unknown>[]
  published: number
  draft: number
}

const mergeEditableDocuments = (published: unknown[], draft: unknown[]) => {
  const documents = new Map<string, Record<string, unknown>>()
  for (const value of [...published, ...draft]) {
    const document = value as Record<string, unknown>
    const key = text(document.id) || text(document.slug)
    if (!key) throw new Error('Payload editable document has no stable id or slug')
    documents.set(key, document)
  }
  return Array.from(documents.values())
}

const findEditableDocuments = async (
  payload: Awaited<ReturnType<typeof getPayload>>,
  collection: EditableCollection,
  options: EditableQueryOptions,
) => {
  const query = {
    collection: collection as CollectionSlug,
    depth: options.depth,
    limit: options.limit,
    pagination: false as const,
    overrideAccess: options.overrideAccess,
    ...(options.req ? { req: options.req } : {}),
    ...(options.where ? { where: options.where } : {}),
  }
  const [published, draft] = await Promise.all([
    payload.find({ ...query, draft: false }),
    payload.find({ ...query, draft: true }),
  ])
  return {
    documents: mergeEditableDocuments(published.docs, draft.docs),
    published: published.docs.length,
    draft: draft.docs.length,
  }
}

const findContentDocument = async (
  payload: Awaited<ReturnType<typeof getPayload>>,
  route: string,
  collection: EditableCollection = 'pages',
  req?: Partial<PayloadRequest>,
) => {
  const slugs = contentSlug(route)
  for (const slug of slugs) {
    const documents = await findEditableDocuments(payload, collection, {
      depth: 2,
      limit: 1,
      overrideAccess: false,
      req,
      where: { slug: { equals: slug } },
    })
    if (documents.documents[0]) return documents.documents[0]
  }
  return undefined
}

const documentCollection = (body: Record<string, unknown>): EditableCollection => {
  const collection = String(body.collection || '').trim()
  if (!isEditableCollection(collection)) throw new Error('content collection is invalid')
  return collection
}

const mediaObject = (value: unknown) => {
  const media = asObject(value)
  return {
    id: media.id,
    sourceId: text(media.sourceId) || undefined,
    url: text(media.url || media.originalUrl || media.thumbnailURL),
    filename: text(media.filename) || 'Image',
    alt: text(media.alt || media.filename) || 'Image',
  }
}

const attachmentFrom = (value: Record<string, unknown>) => {
  const media = mediaObject(value)
  return {
    type: 'media_asset',
    asset_id: media.id,
    sourceId: media.sourceId || null,
    name: media.filename,
    alt_text: media.alt,
    description: text(value.description),
    width: value.width || null,
    height: value.height || null,
    url: media.url || null,
    thumbnail_url: media.url || null,
    preview_url: media.url || null,
    analysis_status: 'ready',
    analysis_error: null,
  }
}

const withoutPayloadMetadata = (value: Record<string, unknown>) => {
  const result = { ...value }
  for (const key of ['id', 'createdAt', 'updatedAt', '_status']) delete result[key]
  return result
}

const field = ({
  collection,
  document,
  name,
  label,
  type,
  value,
  route,
}: {
  collection: EditableCollection
  document: Record<string, unknown>
  name: string
  label: string
  type: 'text' | 'richText'
  value: string
  route: string
}) => ({
  id: `content-field:${collection}:${text(document.id)}:${name}`,
  key: `content-field:${collection}:${text(document.id)}:${name}`,
  label,
  section: name.startsWith('seo') ? 'SEO' : 'Page content',
  sectionOrder: name === 'title' ? 1 : name === 'summary' ? 2 : name === 'body' ? 3 : name === 'seoTitle' ? 1 : 2,
  type,
  sourceType: type,
  editorRole: name === 'title' ? 'heading' : 'paragraph',
  editorVisible: true,
  editable: true,
  status: 'editable',
  kind: 'content',
  value,
  text: value,
  route,
  routes: [route],
  contentEdit: { collection, documentId: text(document.id), field: name, expectedValue: value },
})

const contentFields = (document: Record<string, unknown>, route: string, collection: EditableCollection) => {
  const title = text(document.title)
  const summary = text(document.summary)
  const body = plainText(document.body)
  const seo = seoValue(document)
  const seoTitle = text(seo.title)
  const seoDescription = text(seo.description)
  return [
    title ? field({ collection, document, name: 'title', label: 'Title', type: 'text', value: title, route }) : undefined,
    summary ? field({ collection, document, name: 'summary', label: 'Summary', type: 'text', value: summary, route }) : undefined,
    body ? field({ collection, document, name: 'body', label: 'Body', type: 'richText', value: body, route }) : undefined,
    seoTitle ? field({ collection, document, name: 'seoTitle', label: 'SEO title', type: 'text', value: seoTitle, route }) : undefined,
    seoDescription ? field({ collection, document, name: 'seoDescription', label: 'SEO description', type: 'text', value: seoDescription, route }) : undefined,
  ].filter(Boolean)
}

const imageField = (document: Record<string, unknown>, route: string, collection: EditableCollection) => {
  const image = document.featuredImage
  if (!image) return []
  const media = mediaObject(image)
  if (!media.url && !media.id) return []
  return [{
    id: `content-image:${collection}:${text(document.id)}:featuredImage`,
    key: `content-image:${collection}:${text(document.id)}:featuredImage`,
    label: 'Featured image',
    section: 'Images',
    sectionOrder: 1,
    type: 'image',
    sourceType: 'image',
    editorRole: 'image',
    editorVisible: true,
    editable: true,
    status: 'editable',
    kind: 'content',
    value: text(media.sourceId || media.id),
    image: media,
    route,
    routes: [route],
    contentEdit: {
      collection,
      documentId: text(document.id),
      field: 'featuredImage',
      expectedValue: text(media.sourceId || media.id),
    },
  }]
}

const readEditableDocuments = async (payload: Awaited<ReturnType<typeof getPayload>>) => {
  const results = await Promise.all(editableCollections.map(async (collection) => {
    try {
      const result = await findEditableDocuments(payload, collection, { depth: 0, limit: 100, overrideAccess: true })
      return {
        collection,
        published: result.published,
        draft: result.draft,
        documents: result.documents.map((page) => {
        const item = page as unknown as Record<string, unknown>
        const slug = text(item.slug)
        return {
          id: text(item.id),
          collection,
          sourceId: text(item.sourceId) || text(item.id),
          slug,
          title: text(item.title) || slug || 'Untitled page',
          status: text(item._status) || (item.published ? 'published' : 'draft'),
        }
        }),
      }
    } catch (cause) {
      console.error('helloada_payload_workspace_query_failed', {
        tenant: helloAdaSite.tenantId,
        collection,
        error: errorMessage(cause),
      })
      throw new PayloadWorkspaceQueryError(collection, cause)
    }
  }))
  return results.flatMap((result) => result.documents)
}

const siteSnapshot = async (request: Request, payload: Awaited<ReturnType<typeof getPayload>>) => {
  const documents = await readEditableDocuments(payload)
  const routes = documents.map((document) => ({
    path: !document.slug || document.slug === 'home' || document.slug === 'index' ? '/' : `/${document.slug.replace(/^\/+/, '')}`,
    kind: 'page',
    collection: document.collection,
    sourceId: document.sourceId,
  }))
  return {
    site: { name: process.env.HELLOADA_SITE_NAME || 'Your website', url: process.env.NEXT_PUBLIC_SITE_URL || new URL(request.url).origin },
    routes,
    documents,
    ada: { configured: helloAdaRuntimeStatus().configured },
  }
}

export async function GET(request: Request, { params }: RouteProps) {
  const auth = await authenticateHelloAdaRequest(request)
  if (!auth) return errorResponse('authentication_required', 401)
  const path = `/${(await params).path?.join('/') || ''}`.replace(/\/$/, '') || '/'
  if (path === '/connection') {
    const upstream = await fetchHelloAdaUpstream('/api/helloada/connection', request)
    const result = helloAdaConnection(helloAdaSite.tenantId, upstream ? { status: upstream.status, body: await upstream.json().catch(() => ({})) } : undefined)
    return NextResponse.json(result.body, { status: result.status, headers: { 'Cache-Control': 'private, no-store' } })
  }
  if (path === '/workspace') {
    try {
      return NextResponse.json(await siteSnapshot(request, auth.payload), { headers: { 'Cache-Control': 'private, no-store' } })
    } catch (cause) {
      const collection = cause instanceof PayloadWorkspaceQueryError ? cause.collection : undefined
      return NextResponse.json({
        error: 'payload_workspace_unavailable',
        message: collection ? `Payload collection "${collection}" could not be read.` : 'Payload workspace could not be read.',
        collection,
      }, { status: 503, headers: { 'Cache-Control': 'private, no-store' } })
    }
  }
  if (path === '/growth/contract') {
    await ensureGrowthTables()
    const collections = editableCollections.filter((collection) => collectionFieldNames(auth.payload, collection).size)
    return NextResponse.json({ version: 1, tenant: tenantId(), capabilities: contractCapabilities, collections }, { headers: { 'Cache-Control': 'private, no-store' } })
  }
  if (path === '/growth/candidate') {
    await ensureGrowthTables()
    const packageHash = text(new URL(request.url).searchParams.get('packageHash'))
    if (!packageHash) return errorResponse('packageHash is required')
    const candidate = await candidateRow(packageHash)
    if (!candidate) return errorResponse('Growth candidate not found', 404)
    return NextResponse.json({ packageHash, state: candidate.state, result: operationResult(candidate) }, { headers: { 'Cache-Control': 'private, no-store' } })
  }
  if (path === '/page-fields' || path === '/page-images') {
    const route = contentRoute(new URL(request.url).searchParams.get('route') || '/')
    const document = await findContentDocument(auth.payload, route, 'pages', auth.req)
    if (!document) return errorResponse('route content not found', 404)
    const collection = 'pages' as const
    const fields = path === '/page-fields' ? contentFields(document, route, collection) : imageField(document, route, collection)
    return NextResponse.json({ route, fields, count: fields.length }, { headers: { 'Cache-Control': 'private, no-store' } })
  }
  if (path === '/media-library') {
    const search = text(new URL(request.url).searchParams.get('search')).toLowerCase()
    const rawLimit = Number(new URL(request.url).searchParams.get('limit') || '72')
    const rawPage = Number(new URL(request.url).searchParams.get('page') || '1')
    const limit = Number.isFinite(rawLimit) ? Math.max(1, Math.min(Math.trunc(rawLimit), 120)) : 72
    const page = Number.isFinite(rawPage) ? Math.max(1, Math.trunc(rawPage)) : 1
    const result = await auth.payload.find({ collection: 'media', depth: 1, limit: 500, pagination: false, overrideAccess: false, sort: '-createdAt' })
    const media = result.docs.map((item) => item as unknown as Record<string, unknown>).map((item) => ({
      ...mediaObject(item),
      mimeType: text(item.mimeType),
      portable: false,
    })).filter((item) => !search || `${item.filename} ${item.alt}`.toLowerCase().includes(search))
    const totalPages = Math.max(1, Math.ceil(media.length / limit))
    const currentPage = Math.min(page, totalPages)
    return NextResponse.json({ media: media.slice((currentPage - 1) * limit, currentPage * limit), page: currentPage, limit, totalDocs: media.length, totalPages, hasNextPage: currentPage < totalPages }, { headers: { 'Cache-Control': 'private, no-store' } })
  }
  if (path === '/content/history') {
    try {
      const versions = (await Promise.all(editableCollections.map(async (collection) => {
        const result = await auth.payload.findVersions({ collection: collection as CollectionSlug, depth: 0, limit: 40, overrideAccess: false, req: auth.req, sort: '-createdAt' })
        return result.docs.map((item) => {
          const row = item as unknown as Record<string, unknown>
          const version = asObject(row.version)
          return { id: text(row.id), parent: text(row.parent), collection, title: text(version.title) || text(version.slug) || 'Untitled content', slug: text(version.slug), status: text(version._status) || 'unknown', createdAt: text(row.createdAt), updatedAt: text(row.updatedAt), latest: row.latest === true }
        })
      }))).flat().sort((left, right) => right.createdAt.localeCompare(left.createdAt))
      return NextResponse.json({ versions: versions.slice(0, 80) }, { headers: { 'Cache-Control': 'private, no-store' } })
    } catch (cause) {
      console.error('helloada_payload_history_query_failed', { tenant: helloAdaSite.tenantId, error: errorMessage(cause) })
      return NextResponse.json({ error: 'payload_history_unavailable', message: 'Payload history could not be read.' }, { status: 503, headers: { 'Cache-Control': 'private, no-store' } })
    }
  }
  if (path === '/language') {
    const language = request.headers.get('cookie')?.match(/(?:^|;\s*)payload-lng=([^;]+)/i)?.[1] || 'en'
    return NextResponse.json({ language, defaultLanguage: 'en', supportedLanguages: ['en', 'es', 'fr'] })
  }
  const upstream = await fetchHelloAdaUpstream(`/api/helloada${path}`, request)
  return upstream || errorResponse('HelloAda service is unavailable', 503)
}

export async function POST(request: Request, { params }: RouteProps) {
  const auth = await authenticateHelloAdaRequest(request)
  if (!auth) return errorResponse('authentication_required', 401)
  const path = `/${(await params).path?.join('/') || ''}`.replace(/\/$/, '') || '/'
  if (path === '/language') {
    const body = await request.json().catch(() => ({})) as { language?: string }
    const language = ['en', 'es', 'fr'].includes(String(body.language || '')) ? String(body.language) : 'en'
    const response = NextResponse.json({ language, defaultLanguage: 'en', supportedLanguages: ['en', 'es', 'fr'] })
    response.cookies.set('payload-lng', language, { httpOnly: false, maxAge: 31_536_000, path: '/', sameSite: 'lax' })
    return response
  }
  if (path === '/growth/validate') {
    await ensureGrowthTables()
    const body = growthObject(await request.json().catch(() => ({})))
    const packageData = growthObject(body.package)
    const packageHash = text(body.packageHash)
    if (!packageHash) return errorResponse('packageHash is required')
    try {
      const verified = await verifyGrowthPackage(auth.payload, packageData, packageHash, request)
      const result = {
        status: 'passed', packageHash, tenant: tenantId(),
        checks: { canonicalSchema: true, exactDraft: true, private: true, publicRenderer: true, approvalBoundary: true },
        preview: verified.publicRenderer,
      }
      await saveCandidate(packageData, packageHash, result)
      return NextResponse.json({ validation: result }, { headers: { 'Cache-Control': 'private, no-store' } })
    } catch (cause) {
      return errorResponse(errorMessage(cause), 409)
    }
  }
  if (path === '/growth/apply') {
    await ensureGrowthTables()
    const body = growthObject(await request.json().catch(() => ({})))
    const packageData = growthObject(body.package)
    const packageHash = text(body.packageHash)
    if (!packageHash) return errorResponse('packageHash is required')
    const collection = text(packageData.collection)
    const documentId = text(packageData.documentId)
    if (!isEditableCollection(collection) || !documentId) return errorResponse('Growth package target is invalid')
    const documentKey = `${collection}:${documentId}`
    const operationKey = `draft:${tenantId()}:${documentKey}:${packageHash}`
    const claimed = await claimOperation(operationKey, documentKey, packageHash)
    if (!claimed.row) return errorResponse('A different Growth operation is already writing this document', 409)
    const saved = operationResult(claimed.row)
    if (saved) return NextResponse.json(saved, { headers: { 'Cache-Control': 'private, no-store' } })
    try {
      const verified = await verifyGrowthPackage(auth.payload, packageData, packageHash, request, { requireDraftCandidate: false })
      const currentDraftHash = await hashJson(verified.draftProjection)
      if (currentDraftHash !== text(packageData.baseHash) && currentDraftHash !== text(packageData.candidateHash)) throw new Error('The Payload draft changed before Ada could prepare it')
      if (currentDraftHash !== text(packageData.candidateHash)) {
        operationContext(auth.req as { context?: Record<string, unknown> }, operationKey)
        await auth.payload.update({ collection: collection as CollectionSlug, data: verified.changes as never, draft: true, id: documentId, overrideAccess: false, req: auth.req, user: auth.user })
      }
      const afterWrite = await auth.payload.findByID({ collection: collection as CollectionSlug, depth: 2, draft: true, id: documentId, overrideAccess: false, req: auth.req, user: auth.user }) as unknown as Record<string, unknown>
      const afterProjection = projectDocument(afterWrite, verified.fields)
      if (await hashJson(afterProjection) !== text(packageData.candidateHash)) throw new Error('Payload did not retain the exact Growth candidate')
      const proof = { ok: true, packageHash, candidateHash: packageData.candidateHash, validation: { status: 'passed', packageHash, checks: { canonicalSchema: true, exactDraft: true, private: true, publicRenderer: true, approvalBoundary: true }, preview: verified.publicRenderer } }
      await saveCandidate(packageData, packageHash, proof.validation)
      await completeOperation(operationKey, proof)
      return NextResponse.json(proof, { headers: { 'Cache-Control': 'private, no-store' } })
    } catch (cause) {
      await failOperation(operationKey, { ok: false, packageHash, error: errorMessage(cause) })
      return errorResponse(errorMessage(cause), 409)
    }
  }
  if (path === '/growth/publish') {
    await ensureGrowthTables()
    const body = growthObject(await request.json().catch(() => ({})))
    const packageHash = text(body.packageHash)
    const candidate = await candidateRow(packageHash)
    if (!candidate?.package_json) return errorResponse('The exact Growth candidate is not registered', 409)
    let packageData: Record<string, unknown>
    try { packageData = growthObject(JSON.parse(String(candidate.package_json))) } catch { return errorResponse('The stored Growth candidate is invalid', 409) }
    const collection = text(packageData.collection)
    const documentId = text(packageData.documentId)
    if (!isEditableCollection(collection) || !documentId) return errorResponse('Stored Growth package target is invalid', 409)
    const documentKey = `${collection}:${documentId}`
    const operationKey = `publish:${tenantId()}:${documentKey}:${packageHash}`
    const claimed = await claimOperation(operationKey, documentKey, packageHash)
    if (!claimed.row) return errorResponse('A different publication is already writing this document', 409)
    const saved = operationResult(claimed.row)
    if (saved) return NextResponse.json(saved, { headers: { 'Cache-Control': 'private, no-store' } })
    try {
      const verified = await verifyGrowthPackage(auth.payload, packageData, packageHash, request)
      operationContext(auth.req as { context?: Record<string, unknown> }, operationKey)
      await auth.payload.update({ collection: collection as CollectionSlug, data: withoutPayloadMetadata(verified.after) as never, draft: false, id: documentId, overrideAccess: false, req: auth.req, user: auth.user })
      const published = await auth.payload.findByID({ collection: collection as CollectionSlug, depth: 2, draft: false, id: documentId, overrideAccess: false, req: auth.req, user: auth.user }) as unknown as Record<string, unknown>
      const publicProjection = projectDocument(published, verified.fields)
      if (await hashJson(publicProjection) !== text(packageData.candidateHash)) throw new Error('The public Payload document does not match the approved candidate')
      const publicRenderer = await renderCandidate(auth.payload, collection, published, verified.route)
      const result = { ok: true, packageHash, candidateHash: packageData.candidateHash, status: 'published', published: { collection, documentId, updatedAt: text(published.updatedAt) }, liveVerification: { status: 'passed', publicRenderer } }
      await completeOperation(operationKey, result)
      return NextResponse.json(result, { headers: { 'Cache-Control': 'private, no-store' } })
    } catch (cause) {
      await failOperation(operationKey, { ok: false, packageHash, error: errorMessage(cause) })
      return errorResponse(errorMessage(cause), 409)
    }
  }
  if (path === '/page-fields') {
    const body = asObject(await request.json().catch(() => ({})))
    const edits = Array.isArray(body.edits) ? body.edits : []
    if (!edits.length) return errorResponse('edits must contain at least one item')
    const updated: Array<{ collection: string; documentId: string; fields: number }> = []
    for (const value of edits) {
      const edit = asObject(value)
      const collection = documentCollection(edit)
      const id = text(edit.documentId || edit.document_id)
      const name = text(edit.field)
      const newValue = String(edit.newValue ?? edit.new_value ?? edit.value ?? '')
      if (!id || !/^[A-Za-z][A-Za-z0-9_]*$/.test(name) || !['title', 'summary', 'body', 'seoTitle', 'seoDescription'].includes(name)) return errorResponse('content field is not directly editable')
      const current = await auth.payload.findByID({ collection: collection as CollectionSlug, depth: 1, draft: true, id, overrideAccess: false, req: auth.req, user: auth.user }) as unknown as Record<string, unknown>
      const expected = name === 'body'
        ? plainText(current[name])
        : name === 'seoTitle'
          ? text(seoValue(current).title)
          : name === 'seoDescription'
            ? text(seoValue(current).description)
            : text(current[name])
      if (edit.expectedValue !== undefined && String(edit.expectedValue) !== expected) return errorResponse('content field changed before save', 409)
      const data = name === 'body'
        ? { body: lexicalDocumentFromText(newValue) }
        : name === 'seoTitle' || name === 'seoDescription'
          ? { seo: seoUpdate(current, name, newValue) }
          : { [name]: newValue }
      await auth.payload.update({ collection: collection as CollectionSlug, data: data as never, draft: true, id, overrideAccess: false, req: auth.req, user: auth.user })
      updated.push({ collection, documentId: id, fields: 1 })
    }
    return NextResponse.json({ ok: true, updated })
  }
  if (path === '/page-images') {
    const body = asObject(await request.json().catch(() => ({})))
    const edits = Array.isArray(body.edits) ? body.edits : []
    if (!edits.length) return errorResponse('edits must contain at least one item')
    for (const value of edits) {
      const edit = asObject(value)
      const collection = documentCollection(edit)
      const id = text(edit.documentId || edit.document_id)
      const newValue = text(edit.newValue || edit.new_value || edit.value).replace(/^payload:/, '')
      if (!id || text(edit.field) !== 'featuredImage') return errorResponse('image field is not directly editable')
      const current = await auth.payload.findByID({ collection: collection as CollectionSlug, depth: 1, draft: true, id, overrideAccess: false, req: auth.req, user: auth.user }) as unknown as Record<string, unknown>
      const currentImage = mediaObject(current.featuredImage)
      const expected = text(currentImage.sourceId || currentImage.id)
      if (edit.expectedValue !== undefined && String(edit.expectedValue) !== expected) return errorResponse('image field changed before save', 409)
      if (newValue) await auth.payload.findByID({ collection: 'media', id: newValue, depth: 0, overrideAccess: false, req: auth.req, user: auth.user })
      await auth.payload.update({ collection: collection as CollectionSlug, data: { featuredImage: newValue || null } as never, draft: true, id, overrideAccess: false, req: auth.req, user: auth.user })
    }
    return NextResponse.json({ ok: true })
  }
  if (path === '/media/upload') {
    const form = await request.formData().catch(() => undefined)
    const value = form?.get('file')
    if (!(value instanceof File)) return errorResponse('file_required', 400)
    if (!value.type.startsWith('image/')) return errorResponse('image_required', 415)
    if (value.size < 1 || value.size > 25 * 1024 * 1024) return errorResponse('file_too_large', 413)
    const document = await auth.payload.create({
      collection: 'media',
      data: { alt: value.name.replace(/[^A-Za-z0-9._ -]+/g, '').trim().slice(0, 120) || 'HelloAda image' },
      draft: true,
      req: auth.req,
      user: auth.user,
      file: { data: Buffer.from(await value.arrayBuffer()), mimetype: value.type, name: `${globalThis.crypto.randomUUID()}-${value.name}`, size: value.size },
    })
    return NextResponse.json({ attachment: attachmentFrom(document as unknown as Record<string, unknown>) }, { status: 201 })
  }
  if (path === '/publish') {
    const body = asObject(await request.json().catch(() => ({})))
    const documents = Array.isArray(body.documents) ? body.documents : []
    const published: Array<{ collection: string; documentId: string }> = []
    for (const value of documents) {
      const item = asObject(value)
      const collection = documentCollection(item)
      const id = text(item.documentId || item.document_id)
      if (!id) return errorResponse('publish document id is required')
      const draft = await auth.payload.findByID({ collection: collection as CollectionSlug, depth: 0, draft: true, id, overrideAccess: false, req: auth.req, user: auth.user }) as unknown as Record<string, unknown>
      await auth.payload.update({ collection: collection as CollectionSlug, data: withoutPayloadMetadata(draft) as never, draft: false, id, overrideAccess: false, req: auth.req, user: auth.user })
      published.push({ collection, documentId: id })
    }
    return NextResponse.json({ ok: true, published })
  }
  if (path === '/content/discard') {
    const body = asObject(await request.json().catch(() => ({})))
    const collection = documentCollection(body)
    const id = text(body.documentId || body.document_id)
    if (!id) return errorResponse('discard document id is required')
    const published = await auth.payload.findByID({ collection: collection as CollectionSlug, depth: 1, draft: false, id, overrideAccess: false, req: auth.req, user: auth.user }) as unknown as Record<string, unknown>
    const document = await auth.payload.update({ collection: collection as CollectionSlug, data: withoutPayloadMetadata(published) as never, draft: true, id, overrideAccess: false, req: auth.req, user: auth.user })
    return NextResponse.json({ ok: true, collection, documentId: id, document })
  }
  if (path === '/content/history') {
    const body = asObject(await request.json().catch(() => ({})))
    const collection = documentCollection(body)
    const versionId = text(body.versionId || body.version_id)
    if (!versionId) return errorResponse('version id is required')
    const document = await auth.payload.restoreVersion({ collection: collection as CollectionSlug, draft: true, id: versionId, overrideAccess: false, req: auth.req })
    return NextResponse.json({ ok: true, collection, versionId, document })
  }
  const upstream = await fetchHelloAdaUpstream(`/api/helloada${path}`, request)
  return upstream || errorResponse('HelloAda service is unavailable', 503)
}
