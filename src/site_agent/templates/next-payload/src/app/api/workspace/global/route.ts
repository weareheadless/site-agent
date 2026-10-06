import { NextResponse } from 'next/server'
import { getPayload } from 'payload'

import config from '@payload-config'
import { helloAdaSite } from '@/helloada.config'
import { hashJson, withoutPayloadMetadata } from '@/lib/payload-hash'
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
  const global = await payload.findGlobal({
    slug,
    draft: params.get('draft') !== 'false',
    locale,
    depth: 2,
    overrideAccess: true,
  }) as unknown as Record<string, unknown>
  return NextResponse.json({
    global,
    globalHash: await hashJson(withoutPayloadMetadata(global)),
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
  if (String(body.operation || '').trim().toLowerCase() !== 'update') {
    return errorResponse('only draft updates are available through the service gateway')
  }
  if (typeof body.locale !== 'string' || !body.locale.trim()) {
    return errorResponse('an explicit Payload locale is required for every global write')
  }
  const slug = globalFor(body.global)
  if (!slug) return errorResponse('unsupported global')
  const data = body.data && typeof body.data === 'object' && !Array.isArray(body.data)
    ? body.data
    : undefined
  if (!data) return errorResponse('global data must be an object')
  try {
    validateHelloAdaAuthoringData('global', slug, data)
  } catch (error) {
    return errorResponse(error instanceof Error ? error.message : 'global data does not match the shared authoring schema')
  }
  let locale: HelloAdaPayloadLocale | undefined
  try {
    locale = resolvePayloadLocale(body.locale, helloAdaSite.locales)
  } catch {
    return errorResponse('unsupported locale')
  }
  const expectedHash = String(body.expectedHash || '').trim()
  if (!/^sha256:[0-9a-f]{64}$/.test(expectedHash)) return errorResponse('expectedHash is required for a draft update')
  const payload = await getPayload({ config })
  try {
    const options = {
      slug,
      draft: true,
      locale,
      overrideAccess: true,
    }
    const current = await payload.findGlobal(options) as unknown as Record<string, unknown>
    if (await hashJson(withoutPayloadMetadata(current)) !== expectedHash) {
      return errorResponse('The Payload global changed. Read it again before updating.', 409)
    }
    const global = await payload.updateGlobal({
      ...options,
      data: data as never,
      context: { helloAdaExpectedRevision: { kind: 'global', global: slug, hash: expectedHash, locale } },
    }) as unknown as Record<string, unknown>
    return NextResponse.json({
      global,
      globalHash: await hashJson(withoutPayloadMetadata(global)),
    }, { headers: { 'Cache-Control': 'no-store' } })
  } catch (error) {
    return payloadFailure(error, 'Payload could not update the shared website settings. Read the current version before retrying.')
  }
}
