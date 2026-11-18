/**
 * The tenant admin's identity links all start at the central platform: login
 * there, and come back to the owner's workspace there. Both the tenant id and
 * the issuer are the Worker's own bindings, so a link never guesses an address
 * and a legacy `site-<digest>` tenant still resolves to its own site.
 */
function tenantEntryUrl(issuer: string | undefined, tenantId: string | undefined, suffix: string): string | undefined {
  try {
    if (!issuer || !tenantId || !/^[a-z0-9][a-z0-9-]{0,127}$/.test(tenantId)) throw new Error('invalid identity')
    const origin = new URL(issuer)
    if (origin.protocol !== 'https:' || origin.origin !== issuer) throw new Error('invalid issuer')
    return new URL(`/admin-entry/${encodeURIComponent(tenantId)}${suffix}`, origin).toString()
  } catch {
    return undefined
  }
}

/** Tenant login always starts at the central identity provider. */
export function helloAdaAdminEntry(issuer: string | undefined, tenantId: string | undefined): Response {
  const headers = { 'cache-control': 'no-store, max-age=0', 'referrer-policy': 'no-referrer' }
  const location = tenantEntryUrl(issuer, tenantId, '')
  if (!location) return Response.json({ error: 'workspace_identity_not_configured' }, { status: 503, headers })
  return new Response(null, { status: 303, headers: { ...headers, location } })
}

/**
 * The owner's workspace, which this admin is the advanced editor beside.
 *
 * The control plane owns the mapping from a runtime tenant to the readable
 * address its owner uses, so this asks it rather than deriving a URL from the
 * tenant id here.
 */
export function helloAdaWorkspaceHref(issuer: string | undefined, tenantId: string | undefined): string | undefined {
  return tenantEntryUrl(issuer, tenantId, '/workspace')
}

/**
 * The owner's mailbox, which the control plane serves.
 *
 * A tenant origin keeps the mail API and its data, but it is not a second
 * mailbox application: a page request there is handed to the platform entry,
 * which resolves the owner's site and opens the one mailbox UI.
 */
export function helloAdaMailboxEntry(issuer: string | undefined, tenantId: string | undefined): string | undefined {
  return tenantEntryUrl(issuer, tenantId, '/mail')
}
