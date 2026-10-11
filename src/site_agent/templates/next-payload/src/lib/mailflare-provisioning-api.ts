import { getCloudflareContext } from '@opennextjs/cloudflare'
import { NextResponse } from 'next/server'

import { helloAdaSite } from '@/helloada.config'
import { serviceAuthorized } from '@/lib/service-auth'
import { provisionTenantMailflareMailbox, type MailflareD1 } from '../../mailflare-provisioning'

type MailflareRuntimeEnv = {
  MAILFLARE_DB?: MailflareD1
  MAILFLARE_ADDRESS?: string
  MAILFLARE_ZONE_ID?: string
  MAILFLARE_ROUTING_STATUS?: string
  EMAIL?: unknown
  RESEND_API_KEY?: string
}

const noStore = { 'Cache-Control': 'no-store' }
const fail = (message: string, status: number) => NextResponse.json({ error: message }, { status, headers: noStore })
const text = (value: unknown) => String(value ?? '').trim()

export async function internalMailflareRoute(request: Request, path: string) {
  if (request.method !== 'POST') return fail('method_not_allowed', 405)
  if (path !== '/internal/mailflare/configure-mailbox') return fail('not_found', 404)
  if (!serviceAuthorized(request) || request.headers.get('x-helloada-tenant') !== helloAdaSite.tenantId) {
    return fail('service_authentication_required', 401)
  }

  const contentLength = Number(request.headers.get('content-length') || 0)
  if (contentLength > 4096) return fail('mailbox_configuration_invalid', 400)
  let body: Record<string, unknown>
  try {
    const value = await request.json()
    if (!value || typeof value !== 'object' || Array.isArray(value)) return fail('mailbox_configuration_invalid', 400)
    body = value as Record<string, unknown>
  } catch {
    return fail('mailbox_configuration_invalid', 400)
  }

  const address = text(body.address).toLowerCase()
  const domain = text(body.domain).toLowerCase().replace(/\.$/, '')
  const env = (await getCloudflareContext({ async: true })).env as MailflareRuntimeEnv
  if (!env.MAILFLARE_DB || !env.MAILFLARE_ADDRESS || !env.MAILFLARE_ZONE_ID || !env.MAILFLARE_ROUTING_STATUS) {
    return fail('mailflare_runtime_configuration_missing', 503)
  }
  if (!env.EMAIL || !env.RESEND_API_KEY) return fail('mail_transport_not_ready', 503)
  if (address !== env.MAILFLARE_ADDRESS.trim().toLowerCase()
    || text(body.zoneId) !== env.MAILFLARE_ZONE_ID
    || text(body.routingStatus) !== env.MAILFLARE_ROUTING_STATUS
    || address.split('@')[1] !== domain) {
    return fail('mailbox_configuration_does_not_match_provisioned_tenant', 409)
  }

  try {
    const mailbox = await provisionTenantMailflareMailbox({
      database: env.MAILFLARE_DB,
      tenantId: helloAdaSite.tenantId,
      address,
      zoneId: env.MAILFLARE_ZONE_ID,
      routingStatus: env.MAILFLARE_ROUTING_STATUS,
    })
    return NextResponse.json({ state: 'active', domain: mailbox.domain, address: mailbox.address }, { headers: noStore })
  } catch (error) {
    console.error('helloada_mailflare_provisioning_failed', {
      tenant: helloAdaSite.tenantId,
      error: error instanceof Error ? error.message : 'unknown',
    })
    return fail('mailflare_mailbox_provisioning_failed', 503)
  }
}
