import { NextResponse } from 'next/server'
import { getPayload } from 'payload'

import config from '@payload-config'
import { helloAdaSite } from '@/helloada.config'
import { hashJson, withoutPayloadMetadata } from '@/lib/payload-hash'
import { resolvePayloadLocale, type HelloAdaPayloadLocale } from '@/lib/payload-locale'
import { serviceAuthorized } from '@/lib/service-auth'

const globals = ['siteSettings', 'navigation'] as const
const globalFor = (value: unknown) => globals.find((item) => item === value)
const errorResponse = (message: string, status = 400) =>
  NextResponse.json({ error: 'workspace_gateway_error', message }, { status })

export async function GET(request: Request) {
  if (!serviceAuthorized(request)) return errorResponse('service authentication required', 401)
  const params = new URL(request.url).searchParams
  const slug = globalFor(params.get('global'))
  if (!slug) return errorResponse('unsupported global')
  let locale: HelloAdaPayloadLocale | undefined
  try {
    locale = resolvePayloadLocale(params.get('locale'), helloAdaSite.locales)
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
  const slug = globalFor(body.global)
  if (!slug) return errorResponse('unsupported global')
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
      data: (body.data || {}) as never,
    }) as unknown as Record<string, unknown>
    return NextResponse.json({
      global,
      globalHash: await hashJson(withoutPayloadMetadata(global)),
    }, { headers: { 'Cache-Control': 'no-store' } })
  } catch (error) {
    return errorResponse(error instanceof Error ? error.message : 'global update failed', 400)
  }
}
