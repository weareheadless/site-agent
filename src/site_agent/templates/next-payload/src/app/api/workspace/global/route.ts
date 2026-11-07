import { NextResponse } from 'next/server'
import { getPayload } from 'payload'

import config from '@payload-config'
import { helloAdaSite } from '@/helloada.config'
import { withRecoveredWrite } from '@/lib/growth-contract'
import { withoutPayloadMetadata } from '@/lib/payload-hash'
import { readGlobalRevision, revisionHash } from '@/lib/payload-revision'
import { latestGlobalVersionId, versionRevision } from '@/lib/payload-versions'
import { resolvePayloadLocale, type HelloAdaPayloadLocale } from '@/lib/payload-locale'
import { serviceAuthorized } from '@/lib/service-auth'
import { validateHelloAdaAuthoringData } from '@weareheadless/helloada-payload-core/schema'

const globals = ['siteSettings', 'navigation'] as const
const globalFor = (value: unknown) => globals.find((item) => item === value)
const errorResponse = (message: string, status = 400) =>
  NextResponse.json({ error: 'workspace_gateway_error', message }, { status })

const payloadFailure = (error: unknown, fallback: string) => {
  const value = error && typeof error === 'object' ? error as Record<string, unknown> : {}
  const status = Number(value.status || value.statusCode)
  if ([400, 401, 403, 404, 409, 422].includes(status)) {
    return errorResponse(error instanceof Error ? error.message : fallback, status)
  }
  console.error('helloada_workspace_payload_global_failed', {
    errorName: error instanceof Error ? error.name : 'UnknownError',
    status: Number.isFinite(status) ? status : undefined,
  })
  return errorResponse(fallback, 503)
}

export async function GET(request: Request) {
  if (!serviceAuthorized(request)) return errorResponse('service authentication required', 401)
  const params = new URL(request.url).searchParams
  const slug = globalFor(params.get('global'))
  if (!slug) return errorResponse('unsupported global')
  let locale: HelloAdaPayloadLocale | undefined
  try {
    locale = resolvePayloadLocale(params.get('locale') || helloAdaSite.defaultLocale, helloAdaSite.locales)
  } catch {
    return errorResponse('unsupported locale')
  }
  const payload = await getPayload({ config })
  const global = await readGlobalRevision(payload, { global: slug, locale, draft: params.get('draft') !== 'false' })
  return NextResponse.json({
    global,
    globalHash: await revisionHash(global),
  }, { headers: { 'Cache-Control': 'no-store' } })
}

export async function POST(request: Request) {
  if (!serviceAuthorized(request)) return errorResponse('service authentication required', 401)
  let body: Record<string, unknown>
  try {
    body = await request.json()
  } catch {
    return errorResponse('invalid json')
  }
  const operation = String(body.operation || '').trim().toLowerCase()
  if (operation !== 'update' && operation !== 'publish' && operation !== 'restore') {
    return errorResponse('only exact draft updates, restores and publication are available through the service gateway')
  }
  if (typeof body.locale !== 'string' || !body.locale.trim()) {
    return errorResponse('an explicit Payload locale is required for every global write')
  }
  const slug = globalFor(body.global)
  if (!slug) return errorResponse('unsupported global')
  const expectedHash = String(body.expectedHash || '').trim()
  if (!/^sha256:[0-9a-f]{64}$/.test(expectedHash)) {
    return errorResponse('expectedHash is required for an exact global revision', 400)
  }
  const data = body.data && typeof body.data === 'object' && !Array.isArray(body.data)
    ? body.data
    : undefined
  if (operation === 'update') {
    if (!data) return errorResponse('global data must be an object')
    try {
      validateHelloAdaAuthoringData('global', slug, data)
    } catch (error) {
      return errorResponse(error instanceof Error ? error.message : 'global data does not match the shared authoring schema')
    }
  }
  let locale: HelloAdaPayloadLocale | undefined
  try {
    locale = resolvePayloadLocale(body.locale, helloAdaSite.locales)
  } catch {
    return errorResponse('unsupported locale')
  }
  const payload = await getPayload({ config })
  try {
    const options = {
      slug,
      draft: true,
      locale,
      overrideAccess: true,
    }
    const current = await readGlobalRevision(payload, { global: slug, locale, draft: true })
    const currentHash = await revisionHash(current)
    if (operation === 'restore') {
      const versionId = String(body.versionId || '').trim()
      if (!versionId) return errorResponse('versionId is required', 400)
      const version = await payload.findGlobalVersionByID({
        slug,
        id: versionId,
        depth: 0,
        locale,
        overrideAccess: true,
      }).catch(() => undefined) as unknown as Record<string, unknown> | undefined
      if (!version) return errorResponse('version not found', 404)
      const targetHash = await versionRevision(version.version)
      // A revert is idempotent: the settings already at the selected version are done.
      if (currentHash === targetHash) {
        return NextResponse.json({
          global: current, globalHash: currentHash,
          restoredFromVersionId: versionId, alreadyRestored: true,
        }, { headers: { 'Cache-Control': 'no-store' } })
      }
      if (currentHash !== expectedHash) {
        return errorResponse('The Payload global changed after the reviewed revision. Read it again before restoring.', 409)
      }
      const baseVersionId = await latestGlobalVersionId(payload, slug)
      let restored: Record<string, unknown>
      try {
        restored = await withRecoveredWrite(payload, { kind: 'global', global: slug, locale, expectedHash }, () => payload.restoreGlobalVersion({
          slug,
          id: versionId,
          locale,
          depth: 0,
          overrideAccess: true,
        })) as unknown as Record<string, unknown>
      } catch (error) {
        return payloadFailure(error, 'Payload could not restore that global version. The current draft is unchanged.')
      }
      const globalHash = await revisionHash(restored)
      if (globalHash !== targetHash) {
        return errorResponse('The restored global does not match the selected version. Read the settings before trying again.', 409)
      }
      return NextResponse.json({
        global: restored,
        globalHash,
        restoredFromVersionId: versionId,
        baseVersionId,
      }, { headers: { 'Cache-Control': 'no-store' } })
    }
    if (currentHash !== expectedHash) {
      return errorResponse(operation === 'publish'
        ? 'The Payload draft changed after review. Review the current version before publishing.'
        : 'The Payload global changed. Read it again before updating.', 409)
    }
    if (operation === 'update') {
      // The exact version this write replaces, so a later revert restores it by id.
      const baseVersionId = await latestGlobalVersionId(payload, slug)
      const global = await withRecoveredWrite(payload, { kind: 'global', global: slug, locale, expectedHash, data }, () => payload.updateGlobal({
        ...options,
        depth: 0,
        data: data as never,
        context: { helloAdaExpectedRevision: { kind: 'global', global: slug, hash: expectedHash, locale } },
      })) as unknown as Record<string, unknown>
      return NextResponse.json({
        global,
        globalHash: await revisionHash(global),
        baseVersionId,
      }, { headers: { 'Cache-Control': 'no-store' } })
    }
    // Publication writes the exact reviewed draft into the live global row.
    // The read-back below is the only proof that the public revision matches.
    const publishData = withoutPayloadMetadata(current)
    await withRecoveredWrite(payload, { kind: 'global', global: slug, locale, expectedHash, data: publishData }, () => payload.updateGlobal({
      ...options,
      draft: false,
      data: publishData as never,
      context: { helloAdaExpectedRevision: { kind: 'global', global: slug, hash: expectedHash, locale } },
    }))
    const published = await readGlobalRevision(payload, { global: slug, locale, draft: false })
    const globalHash = await revisionHash(published)
    if (globalHash !== expectedHash) {
      return errorResponse('Payload published a different global revision than the approved one.', 409)
    }
    return NextResponse.json({ global: published, globalHash })
  } catch (error) {
    return payloadFailure(error, 'Payload could not complete the shared website settings operation. Read the current version before retrying.')
  }
}
