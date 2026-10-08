import { NextResponse } from 'next/server'

import { runtimeValue } from '@/lib/runtime-env'

export const dynamic = 'force-dynamic'

export async function GET() {
  const issuer = runtimeValue('HELLOADA_HANDOFF_ISSUER')
  const tenantId = runtimeValue('HELLOADA_TENANT_ID')
  if (!issuer || !tenantId || !/^[a-z0-9][a-z0-9-]{0,127}$/.test(tenantId)) {
    return NextResponse.json({ error: 'workspace_identity_not_configured' }, { status: 503 })
  }

  let destination: URL
  try {
    const origin = new URL(issuer)
    if (origin.protocol !== 'https:' || origin.origin !== issuer) throw new Error('invalid issuer')
    destination = new URL(`/admin-entry/${encodeURIComponent(tenantId)}`, origin)
  } catch {
    return NextResponse.json({ error: 'workspace_identity_not_configured' }, { status: 503 })
  }

  return NextResponse.redirect(destination, {
    status: 303,
    headers: {
      'cache-control': 'no-store, max-age=0',
      'referrer-policy': 'no-referrer',
    },
  })
}
