import { NextResponse } from 'next/server'
import { createLocalReq, getPayload } from 'payload'
import type { CollectionSlug, GlobalSlug, TypedLocale } from 'payload'

import config from '@payload-config'
import { helloAdaRuntime } from '@weareheadless/helloada-payload-admin/server'
import { helloAdaSite } from '@/helloada.config'
import { createHelloAdaPreviewToken } from '@/lib/helloada-preview'
import { articleIndexPath, pathForDocument } from '@/lib/content-routes'
import { hashJson, stableJson, withoutPayloadMetadata } from '@/lib/payload-hash'
import {
  asObject,
  candidateRow,
  claimOperation,
  completeOperation,
  contractCapabilities,
  failOperation,
  operationResult,
  operationByKey,
  operationContext,
  projectDocument,
  reconcileOperation,
  retireObsoleteOperation,
  saveCandidate,
  tenantId,
} from '@/lib/growth-contract'
import type { HelloAdaAuth } from '@/lib/helloada-auth'

type EditableCollection = 'pages' | 'posts' | 'products'
type GrowthPrincipal =
  | { kind: 'owner'; auth: HelloAdaAuth }
  | { kind: 'service'; token: string }

type GrowthParams = { collection: EditableCollection; documentId: string; fields: string[]; live: Record<string, unknown>; draft: Record<string, unknown>; liveProjection: Record<string, unknown>; draftProjection: Record<string, unknown>; before: Record<string, unknown>; after: Record<string, unknown>; changes: Record<string, unknown>; route: string }

const collections: readonly EditableCollection[] = ['pages', 'posts', 'products']
const editable = (value: unknown): value is EditableCollection => collections.includes(String(value || '') as EditableCollection)
const text = (value: unknown) => String(value ?? '').trim()
const error = (message: string, status = 400) => NextResponse.json({ error: 'helloada_growth_error', message }, { status, headers: { 'Cache-Control': 'private, no-store' } })
const collectionEnabled = (collection: EditableCollection) =>
  collection === 'pages'
  || (collection === 'posts' && Boolean(helloAdaSite.features?.posts))
  || (collection === 'products' && Boolean(helloAdaSite.features?.commerce))

const accessFor = (principal: GrowthPrincipal) => principal.kind === 'owner'
  ? { overrideAccess: false as const, req: principal.auth.req, user: principal.auth.user }
  : { overrideAccess: true as const }

const payloadFor = async (principal: GrowthPrincipal) =>
  principal.kind === 'owner' ? principal.auth.payload : getPayload({ config })

const requestForWrite = async (request: Request, payload: Awaited<ReturnType<typeof getPayload>>, principal: GrowthPrincipal) =>
  principal.kind === 'owner'
    ? principal.auth.req
    : createLocalReq({ req: { headers: request.headers, method: request.method, url: request.url } }, payload)

const routeForDocument = (collection: EditableCollection, document: Record<string, unknown>) => {
  const route = text(document.route)
  if (route) return route === '/' ? '/' : `/${route.replace(/^\/+/, '').replace(/\/+$/, '')}`
  const slug = text(document.slug)
  if (!slug) throw new Error(`Payload ${collection} document has no route slug.`)
  return pathForDocument(collection, slug)
}

const collectionFieldNames = (payload: Awaited<ReturnType<typeof getPayload>>, collection: EditableCollection) => {
  const configured = (payload.config.collections as unknown as Array<{ slug?: string; fields?: Array<{ name?: string }> }>)
    .find((item) => item.slug === collection)
  return new Set((configured?.fields || []).map((field) => text(field.name)).filter(Boolean))
}

const verifyPackage = async (
  payload: Awaited<ReturnType<typeof getPayload>>,
  principal: GrowthPrincipal,
  packageData: Record<string, unknown>,
  packageHash: string,
  requireDraftCandidate = true,
  allowPublishedCandidate = false,
): Promise<GrowthParams> => {
  if (await hashJson(packageData) !== packageHash) throw new Error('Growth package hash does not match its contents')
  if (text(packageData.tenant) !== tenantId() || !text(packageData.initiativeId)) throw new Error('Growth package belongs to a different tenant or initiative')
  const collection = text(packageData.collection)
  if (!editable(collection) || !collectionEnabled(collection)) throw new Error('Growth package collection is not enabled for this website')
  const documentId = text(packageData.documentId)
  const fields = Array.isArray(packageData.fields) ? packageData.fields.map(text).filter(Boolean) : []
  if (!documentId || !fields.length || new Set(fields).size !== fields.length) throw new Error('Growth package fields are invalid')
  const configured = collectionFieldNames(payload, collection)
  if (fields.some((field) => !configured.has(field))) throw new Error('Growth package references fields outside the destination schema')
  const before = asObject(packageData.before)
  const after = asObject(packageData.after)
  const changes = asObject(packageData.changes)
  if (!Object.keys(after).length || Object.keys(changes).some((field) => !fields.includes(field))) throw new Error('Growth package candidate fields are invalid')
  const access = accessFor(principal)
  const locale = helloAdaSite.defaultLocale as TypedLocale
  // Match the authoring gateway's configured read shape. Forcing a separate
  // relationship depth changes the revision even when no content was edited.
  const live = await payload.findByID({ collection: collection as CollectionSlug, draft: false, id: documentId, locale, ...access }) as unknown as Record<string, unknown>
  const draft = await payload.findByID({ collection: collection as CollectionSlug, draft: true, id: documentId, locale, ...access }) as unknown as Record<string, unknown>
  const liveProjection = projectDocument(live, fields)
  const draftProjection = projectDocument(draft, fields)
  const liveHash = await hashJson(liveProjection)
  if (liveHash !== text(packageData.baseHash) && !(allowPublishedCandidate && liveHash === text(packageData.candidateHash))) {
    const changedFields = fields.filter((field) => stableJson(liveProjection[field]) !== stableJson(before[field]))
    throw new Error(`The published document changed; this Growth package is stale (fields: ${changedFields.slice(0, 8).join(', ') || 'hash serialization'}).`)
  }
  if (await hashJson(before) !== text(packageData.baseHash)) throw new Error('Growth package does not describe the published base')
  if (await hashJson(after) !== text(packageData.candidateHash)) throw new Error('Growth package candidate hash is invalid')
  const expected = { ...before, ...changes }
  if (await hashJson(after) !== await hashJson(expected)) throw new Error('Growth package after-state is not the exact base plus requested changes')
  if (requireDraftCandidate && await hashJson(draftProjection) !== text(packageData.candidateHash)) throw new Error('The exact Growth candidate is not the current Payload draft')
  const route = text(packageData.route) || routeForDocument(collection, live)
  return { collection, documentId, fields, live, draft, liveProjection, draftProjection, before, after, changes, route }
}

const verifyExactPreview = async (
  request: Request,
  payload: Awaited<ReturnType<typeof getPayload>>,
  principal: GrowthPrincipal,
  collection: EditableCollection,
  document: Record<string, unknown>,
  route: string,
) => {
  const locale = helloAdaSite.defaultLocale
  const access = accessFor(principal)
  const documentHash = await hashJson(withoutPayloadMetadata(document))
  const globals = await Promise.all((['siteSettings', 'navigation'] as const).map(async (slug) => {
    const global = await payload.findGlobal({ slug: slug as GlobalSlug, depth: 2, draft: true, locale: locale as TypedLocale, ...access }) as unknown as Record<string, unknown>
    return { slug, hash: await hashJson(withoutPayloadMetadata(global)) }
  }))
  const token = await createHelloAdaPreviewToken({
    tenantId: tenantId(),
    principal: principal.kind === 'owner'
      ? { type: 'owner', ownerId: text(principal.auth.user.id) }
      : { type: 'service' },
    collection,
    documentId: text(document.id),
    documentHash,
    locale,
    globals,
    route,
    state: 'draft',
  })
  const previewUrl = new URL(`/helloada-preview/${token}`, request.url).toString()
  const headers = new Headers({ accept: 'text/html', 'cache-control': 'no-cache' })
  if (principal.kind === 'owner') {
    const cookie = request.headers.get('cookie')
    if (!cookie) throw new Error('The authenticated Payload session is missing for exact preview verification.')
    headers.set('cookie', cookie)
  } else {
    if (!principal.token) throw new Error('The authenticated service token is unavailable for exact preview verification.')
    headers.set('authorization', `Bearer ${principal.token}`)
  }
  const response = await fetch(previewUrl, { cache: 'no-store', redirect: 'manual', headers })
  if (!response.ok) throw new Error(`The exact public page renderer returned HTTP ${response.status}.`)
  if (!(response.headers.get('content-type') || '').toLowerCase().includes('text/html')) throw new Error('The exact public page renderer did not return HTML.')
  const html = await response.text()
  const escapedRoute = route.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  const escapedId = text(document.id).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  const escapedRevision = text(document.updatedAt).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  if (!escapedRevision || [`data-helloada-preview-hash="${documentHash}"`, `data-helloada-preview-route="${escapedRoute}"`, `data-helloada-document-id="${escapedId}"`, `data-helloada-updated-at="${escapedRevision}"`].some((marker) => !html.includes(marker))) {
    throw new Error('The exact public page renderer did not return the approved document and route markers.')
  }
  return {
    status: 'passed', route, kind: collection === 'posts' ? 'post' : collection === 'products' ? 'product' : 'page',
    collection, documentId: text(document.id), documentHash, verifiedAt: new Date().toISOString(),
    ...(principal.kind === 'owner' ? { previewUrl } : {}),
    expiresAt: Math.floor(Date.now() / 1000) + 180,
  }
}

const verifyLiveRoute = async (request: Request, route: string, document: Record<string, unknown>) => {
  const response = await fetch(new URL(route, request.url), {
    cache: 'no-store', redirect: 'manual',
    headers: { accept: 'text/html', 'cache-control': 'no-cache' },
  })
  if (!response.ok) throw new Error(`The published route ${route} returned HTTP ${response.status}.`)
  if (!(response.headers.get('content-type') || '').toLowerCase().includes('text/html')) throw new Error(`The published route ${route} did not return HTML.`)
  const html = await response.text()
  const escape = (value: string) => value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  const id = escape(text(document.id))
  const updatedAt = escape(text(document.updatedAt))
  if (!updatedAt || !html.includes(`data-helloada-document-id="${id}"`) || !html.includes(`data-helloada-updated-at="${updatedAt}"`)) {
    throw new Error(`The published route ${route} does not render the exact Payload document revision.`)
  }
  return { route, status: response.status, documentId: text(document.id), updatedAt: text(document.updatedAt), verifiedAt: new Date().toISOString() }
}

const verifyLiveRoutes = async (request: Request, collection: EditableCollection, document: Record<string, unknown>, route: string) => {
  const routes = [route]
  if (collection === 'posts') routes.push(articleIndexPath())
  const checks = []
  for (const candidateRoute of routes) checks.push(await verifyLiveRoute(request, candidateRoute, document))
  return { status: 'passed', checks }
}

const retiredPreparation = async (packageData: Record<string, unknown>, packageHash: string) => {
  if (await hashJson(packageData) !== packageHash) return undefined
  const collection = text(packageData.collection)
  const documentId = text(packageData.documentId)
  if (!editable(collection) || !documentId || text(packageData.tenant) !== tenantId()) return undefined
  const documentKey = `${collection}:${documentId}`
  const operationKey = `draft:${tenantId()}:${documentKey}:${packageHash}`
  const row = await operationByKey(operationKey)
  if (!row || row.tenant_id !== tenantId() || row.document_key !== documentKey || row.package_hash !== packageHash) return undefined
  const result = operationResult(row)
  return result?.disposition === 'retired_obsolete' && result.packageHash === packageHash ? result : undefined
}

export async function growthGet(request: Request, path: string, principal: GrowthPrincipal) {
  const payload = await payloadFor(principal)
  if (path === '/growth/contract') {
    const enabled = collections.filter(collectionEnabled)
    const available = enabled.filter((collection) => collectionFieldNames(payload, collection).size)
    return NextResponse.json({ version: 1, tenant: tenantId(), capabilities: contractCapabilities, collections: available }, { headers: { 'Cache-Control': 'private, no-store' } })
  }
  if (path === '/growth/candidate') {
    const packageHash = text(new URL(request.url).searchParams.get('packageHash'))
    if (!packageHash) return error('packageHash is required')
    const candidate = await candidateRow(packageHash)
    if (!candidate) return error('Growth candidate not found', 404)
    return NextResponse.json({ packageHash, state: candidate.state, result: operationResult(candidate) }, { headers: { 'Cache-Control': 'private, no-store' } })
  }
  return error('unsupported Growth operation', 404)
}

export async function growthPost(request: Request, path: string, principal: GrowthPrincipal) {
  const payload = await payloadFor(principal)
  const body = asObject(await request.json().catch(() => ({})))
  if (path === '/growth/verify-publication') {
    const collection = text(body.collection)
    const documentId = text(body.documentId)
    const expectedRevision = text(body.expectedRevision)
    if (!editable(collection) || !collectionEnabled(collection) || !documentId || !/^sha256:[0-9a-f]{64}$/.test(expectedRevision)) return error('Exact publication identity is required')
    if (body.locale !== helloAdaSite.defaultLocale) return error('Publication verification requires the configured website locale', 409)
    try {
      const document = await payload.findByID({ collection: collection as CollectionSlug, id: documentId,
        draft: false, locale: helloAdaSite.defaultLocale as TypedLocale, ...accessFor(principal) }) as unknown as Record<string, unknown>
      if (await hashJson(withoutPayloadMetadata(document)) !== expectedRevision) throw new Error('The public document no longer matches the saved publication revision')
      const liveVerification = await verifyLiveRoutes(request, collection, document, routeForDocument(collection, document))
      return NextResponse.json({ collection, documentId, documentHash: expectedRevision, liveVerification }, { headers: { 'Cache-Control': 'private, no-store' } })
    } catch (cause) {
      return error(cause instanceof Error ? cause.message : 'Publication verification failed', 409)
    }
  }
  if (path === '/growth/retire-obsolete') {
    if (principal.kind !== 'service') return error('Obsolete operation retirement requires the operator service route', 403)
    const basis = text(body.basis) || 'exact_package'
    const mode = text(body.mode)
    if (basis === 'current_site_snapshot') {
      const operationKey = text(body.operationKey)
      const packageHash = text(body.packageHash)
      const collection = text(body.collection)
      const documentId = text(body.documentId)
      const documentKey = `${collection}:${documentId}`
      const expectedOperationKey = `draft:${tenantId()}:${documentKey}:${packageHash}`
      const expectedUpdatedAt = text(body.expectedUpdatedAt)
      const expectedResultHash = text(body.expectedResultHash)
      const expectedSnapshotProofHash = text(body.expectedSnapshotProofHash)
      const reason = text(body.reason)
      const operatorRequestId = text(body.operatorRequestId)
      if (!['plan', 'apply'].includes(mode) || !editable(collection) || !collectionEnabled(collection)
        || !documentId || !/^sha256:[0-9a-f]{64}$/.test(packageHash) || operationKey !== expectedOperationKey) {
        return error('Snapshot retirement requires the exact registered tenant operation and collection target', 409)
      }
      if (mode === 'apply' && (body.preserveExistingDraft !== true || !expectedUpdatedAt
        || !/^sha256:[0-9a-f]{64}$/.test(expectedResultHash)
        || !/^sha256:[0-9a-f]{64}$/.test(expectedSnapshotProofHash)
        || !reason || reason.length > 500 || !operatorRequestId || operatorRequestId.length > 200)) {
        return error('Snapshot apply requires explicit draft preservation, planned versions, reason (max 500 characters), and operator request ID (max 200 characters)', 409)
      }
      try {
        const row = await operationByKey(operationKey)
        if (!row || row.tenant_id !== tenantId() || row.document_key !== documentKey || row.package_hash !== packageHash) {
          throw new Error('The exact tenant Growth operation was not found')
        }
        const priorResult = operationResult(row)
        if (row.state === 'completed' && priorResult?.disposition === 'retired_obsolete'
          && priorResult.packageHash === packageHash && priorResult.basis === 'current_site_snapshot') {
          if (mode === 'apply' && body.preserveExistingDraft === true
            && priorResult.operationKey === operationKey && priorResult.collection === collection && priorResult.documentId === documentId
            && priorResult.expectedUpdatedAt === expectedUpdatedAt && priorResult.expectedResultHash === expectedResultHash
            && priorResult.snapshotProofHash === expectedSnapshotProofHash
            && priorResult.operatorRequestId === operatorRequestId && priorResult.reason === reason) {
            return NextResponse.json(priorResult, { headers: { 'Cache-Control': 'private, no-store' } })
          }
          throw new Error('This operation was already retired by a different request or plan')
        }
        if (row.state !== 'uncertain' || !priorResult || priorResult.packageHash !== packageHash) {
          throw new Error('Only an uncertain operation with a matching durable preparation result can be withdrawn')
        }
        const priorResultJson = String(row.result_json || '')
        const priorResultHash = await hashJson(JSON.parse(priorResultJson))
        const schemaIdentity = text(process.env.HELLOADA_SCHEMA_IDENTITY)
        if (!schemaIdentity) throw new Error('The registered Payload schema identity is unavailable')
        const editableFields = [...collectionFieldNames(payload, collection)].sort()
        if (!editableFields.length) throw new Error('The destination collection has no registered editable schema fields')
        const locale = helloAdaSite.defaultLocale as TypedLocale
        const access = accessFor(principal)
        const [published, draft] = await Promise.all([
          payload.findByID({ collection: collection as CollectionSlug, draft: false, id: documentId, locale, ...access }) as unknown as Promise<Record<string, unknown>>,
          payload.findByID({ collection: collection as CollectionSlug, draft: true, id: documentId, locale, ...access }) as unknown as Promise<Record<string, unknown>>,
        ])
        const snapshot = {
          schemaIdentity,
          editableFields,
          currentPublished: { updatedAt: text(published.updatedAt), canonicalHash: await hashJson(withoutPayloadMetadata(published)) },
          currentDraft: { updatedAt: text(draft.updatedAt), canonicalHash: await hashJson(withoutPayloadMetadata(draft)) },
        }
        if (!snapshot.currentPublished.updatedAt || !snapshot.currentDraft.updatedAt) throw new Error('Both current Payload revisions must have an updatedAt identity')
        const snapshotProofHash = await hashJson({
          basis, tenant: tenantId(), documentKey, operationKey, packageHash, state: row.state,
          rowUpdatedAt: String(row.updated_at), priorResultHash, ...snapshot,
        })
        if (mode === 'plan') {
          return NextResponse.json({ eligible: true, basis, operationKey, packageHash, collection, documentId,
            expectedUpdatedAt: String(row.updated_at), expectedResultHash: priorResultHash, snapshotProofHash, snapshot },
          { headers: { 'Cache-Control': 'private, no-store' } })
        }
        if (String(row.updated_at) !== expectedUpdatedAt || priorResultHash !== expectedResultHash
          || snapshotProofHash !== expectedSnapshotProofHash) {
          throw new Error('The operation, registered schema, or current Payload snapshot changed after the plan; request a fresh plan')
        }
        const receipt = {
          ok: false, disposition: 'retired_obsolete', basis, effectStatus: 'unknown', withdrawal: 'explicit',
          interpretation: 'Historical effect unknown; obsolete intent explicitly withdrawn and current draft preserved.',
          operationKey, documentKey, tenant: tenantId(), packageHash, collection, documentId,
          expectedUpdatedAt, expectedResultHash, snapshotProofHash: expectedSnapshotProofHash,
          preserveExistingDraft: true, reason, operatorRequestId, snapshot, priorResult,
        }
        if (!await retireObsoleteOperation({ operationKey, documentKey, packageHash,
          expectedUpdatedAt, expectedResultHash, priorResultJson, receipt })) {
          throw new Error('The uncertain operation changed during retirement; re-read and reconcile it')
        }
        return NextResponse.json(receipt, { headers: { 'Cache-Control': 'private, no-store' } })
      } catch (cause) {
        return error(cause instanceof Error ? cause.message : 'Current-site snapshot withdrawal failed', 409)
      }
    }
    if (basis !== 'exact_package') return error('Unsupported obsolete operation retirement basis', 400)
    const operationKey = text(body.operationKey)
    const documentKey = text(body.documentKey)
    const packageHash = text(body.packageHash)
    const expectedUpdatedAt = text(body.expectedUpdatedAt)
    const expectedResultHash = text(body.expectedResultHash)
    const reason = text(body.reason)
    const operatorRequestId = text(body.operatorRequestId)
    const packageData = asObject(body.package)
    if (!['plan', 'apply'].includes(mode) || !operationKey || !documentKey || !packageHash) {
      return error('Retirement mode and exact operation/package identity are required')
    }
    if (mode === 'apply' && (!expectedUpdatedAt || !/^sha256:[0-9a-f]{64}$/.test(expectedResultHash)
      || !reason || reason.length > 500 || !operatorRequestId || operatorRequestId.length > 200)) {
      return error('Apply requires the planned row version, prior result hash, reason (max 500 characters), and operator request ID (max 200 characters)')
    }
    try {
      if (await hashJson(packageData) !== packageHash) throw new Error('Growth package hash does not match its contents')
      const collection = text(packageData.collection)
      const documentId = text(packageData.documentId)
      const expectedDocumentKey = `${collection}:${documentId}`
      const expectedOperationKey = `draft:${tenantId()}:${expectedDocumentKey}:${packageHash}`
      if (!editable(collection) || !collectionEnabled(collection) || documentKey !== expectedDocumentKey
        || operationKey !== expectedOperationKey || text(packageData.tenant) !== tenantId()) {
        throw new Error('Retirement identity does not match the registered tenant and exact preparation package')
      }
      const row = await operationByKey(operationKey)
      if (!row || row.tenant_id !== tenantId() || row.document_key !== documentKey || row.package_hash !== packageHash) {
        throw new Error('The exact tenant Growth operation was not found')
      }
      const priorResult = operationResult(row)
      if (row.state === 'completed' && priorResult?.disposition === 'retired_obsolete' && priorResult.packageHash === packageHash) {
        if (mode === 'apply' && priorResult.basis === 'exact_package'
          && priorResult.operationKey === operationKey && priorResult.documentKey === documentKey
          && priorResult.expectedUpdatedAt === expectedUpdatedAt && priorResult.expectedResultHash === expectedResultHash
          && priorResult.operatorRequestId === operatorRequestId && priorResult.reason === reason) {
          return NextResponse.json(priorResult, { headers: { 'Cache-Control': 'private, no-store' } })
        }
        throw new Error('This operation was already retired by a different request or plan')
      }
      if (row.state !== 'uncertain') throw new Error('Only an uncertain preparation can be retired')
      const priorResultJson = String(row.result_json || '')
      const priorResultHash = await hashJson(JSON.parse(priorResultJson))
      if (!priorResult || priorResult.packageHash !== packageHash) {
        throw new Error('The uncertain operation changed or does not prove this preparation intent')
      }
      const verified = await verifyPackage(payload, principal, packageData, packageHash, false)
      if (await hashJson(verified.liveProjection) !== text(packageData.baseHash)
        || await hashJson(verified.draftProjection) !== text(packageData.baseHash)) {
        throw new Error('Published content and draft no longer match the saved preparation base')
      }
      const proof = { publishedBaseHash: text(packageData.baseHash), currentDraftHash: text(packageData.baseHash), verifiedAt: new Date().toISOString() }
      if (mode === 'plan') {
        return NextResponse.json({ eligible: true, operationKey, documentKey, packageHash, expectedUpdatedAt: String(row.updated_at), expectedResultHash: priorResultHash, proof }, { headers: { 'Cache-Control': 'private, no-store' } })
      }
      if (priorResultHash !== expectedResultHash || String(row.updated_at) !== expectedUpdatedAt) {
        throw new Error('The uncertain operation changed after the retirement plan; request a fresh plan')
      }
      const receipt = {
        ok: false, disposition: 'retired_obsolete', basis: 'exact_package', operationKey, documentKey, tenant: tenantId(), packageHash,
        expectedUpdatedAt, expectedResultHash, proof, priorResult, reason, operatorRequestId,
      }
      const retired = await retireObsoleteOperation({ operationKey, documentKey, packageHash,
        expectedUpdatedAt, expectedResultHash, priorResultJson, receipt })
      if (!retired) throw new Error('The uncertain operation changed during retirement; re-read and reconcile it')
      return NextResponse.json(receipt, { headers: { 'Cache-Control': 'private, no-store' } })
    } catch (cause) {
      return error(cause instanceof Error ? cause.message : 'Obsolete preparation could not be retired', 409)
    }
  }
  if (path === '/growth/validate') {
    const packageData = asObject(body.package)
    const packageHash = text(body.packageHash)
    if (!packageHash) return error('packageHash is required')
    try {
      if (await retiredPreparation(packageData, packageHash)) throw new Error('This Growth preparation was retired and cannot be validated again')
      const verified = await verifyPackage(payload, principal, packageData, packageHash)
      const preview = await verifyExactPreview(request, payload, principal, verified.collection, verified.draft, verified.route)
      const validation = {
        status: 'passed', packageHash, tenant: tenantId(),
        checks: { canonicalSchema: true, exactDraft: true, private: true, publicRenderer: true, approvalBoundary: true },
        preview,
      }
      await saveCandidate(packageData, packageHash, validation)
      return NextResponse.json({ validation }, { headers: { 'Cache-Control': 'private, no-store' } })
    } catch (cause) {
      return error(cause instanceof Error ? cause.message : 'Growth validation failed', 409)
    }
  }
  if (path === '/growth/apply') {
    const packageData = asObject(body.package)
    const packageHash = text(body.packageHash)
    if (!packageHash) return error('packageHash is required')
    const collection = text(packageData.collection)
    const documentId = text(packageData.documentId)
    if (!editable(collection) || !collectionEnabled(collection) || !documentId) return error('Growth package target is invalid')
    try {
      if (await retiredPreparation(packageData, packageHash)) return error('This Growth preparation was retired and cannot be replayed', 409)
    } catch (cause) {
      return error(cause instanceof Error ? cause.message : 'Growth preparation identity could not be verified', 409)
    }
    // A rejected read/schema/base check has no external write to reconcile.
    // Do not create an uncertain operation (and lock the document) for it.
    try {
      await verifyPackage(payload, principal, packageData, packageHash, false)
    } catch (cause) {
      return error(cause instanceof Error ? cause.message : 'Growth candidate preflight failed', 409)
    }
    const documentKey = `${collection}:${documentId}`
    const operationKey = `draft:${tenantId()}:${documentKey}:${packageHash}`
    const claimed = await claimOperation(operationKey, documentKey, packageHash)
    if (!claimed.row) return error('A different Growth operation is already writing this document', 409)
    const saved = operationResult(claimed.row)
    if (saved?.disposition === 'retired_obsolete') return error('This Growth preparation was retired and cannot be replayed', 409)
    if (claimed.row.state === 'completed' && saved?.ok === true) return NextResponse.json(saved, { headers: { 'Cache-Control': 'private, no-store' } })
    if (!claimed.inserted) {
      // A timeout is not permission to repeat a write. Read and verify its exact
      // effect, including the real preview, before settling the existing receipt.
      try {
        const verified = await verifyPackage(payload, principal, packageData, packageHash)
        const preview = await verifyExactPreview(request, payload, principal, verified.collection, verified.draft, verified.route)
        const proof = { ok: true, packageHash, candidateHash: packageData.candidateHash, validation: { status: 'passed', packageHash, checks: { canonicalSchema: true, exactDraft: true, private: true, publicRenderer: true, approvalBoundary: true }, preview } }
        await saveCandidate(packageData, packageHash, proof.validation)
        await reconcileOperation(operationKey, proof)
        return NextResponse.json(proof, { headers: { 'Cache-Control': 'private, no-store' } })
      } catch (cause) {
        return error(cause instanceof Error ? cause.message : 'The prior Growth preparation effect could not be verified; no write was repeated', 409)
      }
    }
    try {
      const verified = await verifyPackage(payload, principal, packageData, packageHash, false)
      const currentDraftHash = await hashJson(projectDocument(verified.draft, verified.fields))
      if (currentDraftHash !== text(packageData.baseHash) && currentDraftHash !== text(packageData.candidateHash)) throw new Error('The Payload draft changed before Ada could prepare it')
      if (currentDraftHash !== text(packageData.candidateHash)) {
        const req = await requestForWrite(request, payload, principal)
        operationContext(req as { context?: Record<string, unknown> }, operationKey)
        await payload.update({
          collection: verified.collection as CollectionSlug, data: verified.changes as never,
          draft: true, id: documentId, locale: helloAdaSite.defaultLocale as TypedLocale,
          ...(principal.kind === 'owner' ? { overrideAccess: false, user: principal.auth.user } : { overrideAccess: true }),
          req,
        })
      }
      const access = accessFor(principal)
      const afterWrite = await payload.findByID({ collection: verified.collection as CollectionSlug, draft: true, id: documentId, locale: helloAdaSite.defaultLocale as TypedLocale, ...access }) as unknown as Record<string, unknown>
      if (await hashJson(projectDocument(afterWrite, verified.fields)) !== text(packageData.candidateHash)) throw new Error('Payload did not retain the exact Growth candidate')
      const preview = await verifyExactPreview(request, payload, principal, verified.collection, afterWrite, verified.route)
      const proof = { ok: true, packageHash, candidateHash: packageData.candidateHash, validation: { status: 'passed', packageHash, checks: { canonicalSchema: true, exactDraft: true, private: true, publicRenderer: true, approvalBoundary: true }, preview } }
      await saveCandidate(packageData, packageHash, proof.validation)
      await completeOperation(operationKey, proof)
      return NextResponse.json(proof, { headers: { 'Cache-Control': 'private, no-store' } })
    } catch (cause) {
      await failOperation(operationKey, { ok: false, packageHash, error: cause instanceof Error ? cause.message : 'Growth candidate preparation failed' })
      return error(cause instanceof Error ? cause.message : 'Growth candidate preparation failed', 409)
    }
  }
  if (path === '/growth/publish') {
    const packageHash = text(body.packageHash)
    const candidate = await candidateRow(packageHash)
    if (!candidate?.package_json || candidate.state !== 'validated') return error('The exact validated Growth candidate is not registered', 409)
    let packageData: Record<string, unknown>
    try { packageData = asObject(JSON.parse(String(candidate.package_json))) } catch { return error('The stored Growth package is invalid', 409) }
    const collection = text(packageData.collection)
    const documentId = text(packageData.documentId)
    if (!editable(collection) || !collectionEnabled(collection) || !documentId) return error('Stored Growth package target is invalid', 409)
    try {
      if (await retiredPreparation(packageData, packageHash)) return error('This Growth preparation was retired and cannot be published', 409)
    } catch (cause) {
      return error(cause instanceof Error ? cause.message : 'Growth preparation identity could not be verified', 409)
    }
    const documentKey = `${collection}:${documentId}`
    const operationKey = `publish:${tenantId()}:${documentKey}:${packageHash}`
    const claimed = await claimOperation(operationKey, documentKey, packageHash)
    if (!claimed.row) return error('A different publication is already writing this document', 409)
    const saved = operationResult(claimed.row)
    if (saved?.disposition === 'retired_obsolete') return error('This Growth preparation was retired and cannot be replayed', 409)
    if (claimed.row.state === 'completed' && saved?.ok === true) return NextResponse.json(saved, { headers: { 'Cache-Control': 'private, no-store' } })
    if (!claimed.inserted) {
      try {
        const verified = await verifyPackage(payload, principal, packageData, packageHash, true, true)
        if (await hashJson(verified.liveProjection) !== text(packageData.candidateHash)) throw new Error('The prior Growth publication effect is not proven; no publication was repeated')
        const liveVerification = await verifyLiveRoutes(request, collection, verified.live, verified.route)
        const result = { ok: true, packageHash, candidateHash: packageData.candidateHash, status: 'published', published: { collection, documentId, updatedAt: text(verified.live.updatedAt) }, liveVerification }
        await reconcileOperation(operationKey, result)
        return NextResponse.json(result, { headers: { 'Cache-Control': 'private, no-store' } })
      } catch (cause) {
        return error(cause instanceof Error ? cause.message : 'The prior Growth publication effect could not be verified; no publication was repeated', 409)
      }
    }
    try {
      const verified = await verifyPackage(payload, principal, packageData, packageHash)
      const req = await requestForWrite(request, payload, principal)
      operationContext(req as { context?: Record<string, unknown> }, operationKey)
      await payload.update({
        collection: verified.collection as CollectionSlug, data: withoutPayloadMetadata(verified.after) as never,
        draft: false, id: documentId, locale: helloAdaSite.defaultLocale as TypedLocale,
        ...(principal.kind === 'owner' ? { overrideAccess: false, user: principal.auth.user } : { overrideAccess: true }),
        req,
      })
      const access = accessFor(principal)
      const published = await payload.findByID({ collection: verified.collection as CollectionSlug, draft: false, id: documentId, locale: helloAdaSite.defaultLocale as TypedLocale, ...access }) as unknown as Record<string, unknown>
      if (await hashJson(projectDocument(published, verified.fields)) !== text(packageData.candidateHash)) throw new Error('The public Payload document does not match the approved candidate')
      const liveVerification = await verifyLiveRoutes(request, collection, published, verified.route)
      const result = { ok: true, packageHash, candidateHash: packageData.candidateHash, status: 'published', published: { collection, documentId, updatedAt: text(published.updatedAt) }, liveVerification }
      await completeOperation(operationKey, result)
      return NextResponse.json(result, { headers: { 'Cache-Control': 'private, no-store' } })
    } catch (cause) {
      await failOperation(operationKey, { ok: false, packageHash, error: cause instanceof Error ? cause.message : 'Growth publication failed' })
      return error(cause instanceof Error ? cause.message : 'Growth publication failed', 409)
    }
  }
  return error('unsupported Growth operation', 404)
}

export const serviceGrowthPrincipal = (): GrowthPrincipal => ({ kind: 'service', token: helloAdaRuntime().token })
