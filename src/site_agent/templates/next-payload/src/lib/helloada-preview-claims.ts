/** Pure claim contract for exact document previews.
 *
 * Kept separate from signing so the security-relevant rules — tenant, owner,
 * document hash, route, purpose and lifetime — are testable without a Worker
 * runtime. ``helloada-preview.ts`` only adds the HMAC.
 */

export type HelloAdaPreviewPurpose = 'verification' | 'workspace'

export type HelloAdaPreviewClaims = {
  version: 1
  tenantId: string
  principal: { type: 'owner'; ownerId: string } | { type: 'service' }
  collection: 'pages' | 'posts' | 'products'
  documentId: string
  documentHash: string
  locale: string
  globals: Array<{ slug: 'siteSettings' | 'navigation'; hash: string }>
  route: string
  state: 'draft' | 'published'
  purpose: HelloAdaPreviewPurpose
  expiresAt: number
}

export type HelloAdaPreviewInput = Omit<HelloAdaPreviewClaims, 'version' | 'expiresAt' | 'purpose'> & {
  purpose?: HelloAdaPreviewPurpose
}

const collections = new Set<HelloAdaPreviewClaims['collection']>(['pages', 'posts', 'products'])

/** ``verification`` tokens are short-lived approval evidence. ``workspace``
 * tokens belong to the authenticated owner's preview pane: the route still
 * re-checks that live session, so they may live long enough to browse. */
export const helloAdaPreviewLifetime = (purpose: HelloAdaPreviewPurpose) => purpose === 'workspace' ? 3600 : 180
const maximumLifetime = (purpose: HelloAdaPreviewPurpose) => helloAdaPreviewLifetime(purpose) + 1

export const validHelloAdaPreviewClaims = (
  value: unknown,
  tenantId: string,
  nowSeconds: number,
): value is HelloAdaPreviewClaims => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const claims = value as Partial<HelloAdaPreviewClaims>
  return claims.version === 1
    && claims.tenantId === tenantId
    && claims.principal !== null && typeof claims.principal === 'object'
    && ((claims.principal.type === 'owner' && typeof claims.principal.ownerId === 'string' && claims.principal.ownerId.length > 0)
      || (claims.principal.type === 'service' && !('ownerId' in claims.principal)))
    && typeof claims.collection === 'string' && collections.has(claims.collection as HelloAdaPreviewClaims['collection'])
    && typeof claims.documentId === 'string' && claims.documentId.length > 0
    && typeof claims.documentHash === 'string' && /^sha256:[0-9a-f]{64}$/.test(claims.documentHash)
    && typeof claims.locale === 'string' && /^[A-Za-z0-9-]{2,20}$/.test(claims.locale)
    && Array.isArray(claims.globals)
    && claims.globals.length === 2
    && new Set(claims.globals.map(global => global?.slug)).size === 2
    && claims.globals.every(global =>
      (global?.slug === 'siteSettings' || global?.slug === 'navigation')
      && typeof global.hash === 'string'
      && /^sha256:[0-9a-f]{64}$/.test(global.hash),
    )
    && typeof claims.route === 'string' && claims.route.startsWith('/') && !claims.route.startsWith('//')
    && (claims.state === 'draft' || claims.state === 'published')
    && (claims.purpose === 'verification' || claims.purpose === 'workspace')
    && (claims.purpose !== 'workspace' || claims.principal.type === 'owner')
    && Number.isSafeInteger(claims.expiresAt) && Number(claims.expiresAt) > nowSeconds
    && Number(claims.expiresAt) <= nowSeconds + maximumLifetime(claims.purpose)
}

export const buildHelloAdaPreviewClaims = (input: HelloAdaPreviewInput, nowSeconds: number): HelloAdaPreviewClaims => {
  const purpose = input.purpose || 'verification'
  const claims: HelloAdaPreviewClaims = {
    version: 1,
    ...input,
    purpose,
    expiresAt: nowSeconds + helloAdaPreviewLifetime(purpose),
  }
  if (!validHelloAdaPreviewClaims(claims, input.tenantId, nowSeconds)) {
    throw new Error('Exact document preview claims are invalid.')
  }
  return claims
}
