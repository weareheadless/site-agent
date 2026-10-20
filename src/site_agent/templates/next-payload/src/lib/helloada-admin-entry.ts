/** Tenant login always starts at the central identity provider. */
export function helloAdaAdminEntry(issuer: string | undefined, tenantId: string | undefined): Response {
  const headers = { 'cache-control': 'no-store, max-age=0', 'referrer-policy': 'no-referrer' }
  try {
    if (!issuer || !tenantId || !/^[a-z0-9][a-z0-9-]{0,127}$/.test(tenantId)) throw new Error('invalid identity')
    const origin = new URL(issuer)
    if (origin.protocol !== 'https:' || origin.origin !== issuer) throw new Error('invalid issuer')
    return new Response(null, { status: 303, headers: {
      ...headers,
      location: new URL(`/admin-entry/${encodeURIComponent(tenantId)}`, origin).toString(),
    } })
  } catch {
    return Response.json({ error: 'workspace_identity_not_configured' }, { status: 503, headers })
  }
}
