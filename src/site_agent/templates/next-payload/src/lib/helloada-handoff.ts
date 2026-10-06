const encoder = new TextEncoder()

export type OwnerHandoffClaims = {
  iss: string
  aud: string
  sub: string
  jti: string
  purpose: string
  target_origin: string
  iat: number
  exp: number
}

function decodeBase64Url(value: string): Uint8Array {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error('handoff_token_invalid')
  const base64 = value.replaceAll('-', '+').replaceAll('_', '/') + '='.repeat((4 - value.length % 4) % 4)
  const binary = atob(base64)
  return Uint8Array.from(binary, (character) => character.charCodeAt(0))
}

function decodeJson<T>(value: string): T {
  return JSON.parse(new TextDecoder().decode(decodeBase64Url(value))) as T
}

export function decodeHandoffPublicKey(value: string): Uint8Array {
  const encoded = value.trim()
  if (!encoded || encoded.length > 4096) throw new Error('handoff_key_not_configured')
  return decodeBase64Url(encoded)
}

export async function hashOwnerSubject(subject: string): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(subject)))
  return [...digest].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

export async function verifyOwnerHandoffToken(
  token: string,
  options: {
    issuer: string
    tenantId: string
    targetOrigin: string
    publicKey: Uint8Array
    nowSeconds?: number
  },
): Promise<OwnerHandoffClaims> {
  if (token.length > 6_000) throw new Error('handoff_token_invalid')
  const parts = token.split('.')
  if (parts.length !== 3) throw new Error('handoff_token_invalid')

  const header = decodeJson<{ alg?: unknown; typ?: unknown }>(parts[0])
  if (header.alg !== 'RS256' || (header.typ !== undefined && header.typ !== 'JWT')) {
    throw new Error('handoff_token_invalid')
  }

  const key = await crypto.subtle.importKey(
    'spki',
    options.publicKey,
    { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
    false,
    ['verify'],
  )
  const signatureValid = await crypto.subtle.verify(
    'RSASSA-PKCS1-v1_5',
    key,
    decodeBase64Url(parts[2]),
    encoder.encode(`${parts[0]}.${parts[1]}`),
  )
  if (!signatureValid) throw new Error('handoff_token_invalid')

  const claims = decodeJson<OwnerHandoffClaims>(parts[1])
  const now = options.nowSeconds ?? Math.floor(Date.now() / 1000)
  if (
    claims.iss !== options.issuer
    || claims.aud !== options.tenantId
    || claims.target_origin !== options.targetOrigin
    || claims.purpose !== 'payload-admin-session'
    || typeof claims.sub !== 'string'
    || !/^[^\s]{1,200}$/.test(claims.sub)
    || typeof claims.jti !== 'string'
    || !/^[A-Za-z0-9_-]{16,100}$/.test(claims.jti)
    || !Number.isInteger(claims.iat)
    || !Number.isInteger(claims.exp)
    || claims.iat > now + 30
    || claims.iat < now - 120
    || claims.exp <= now
    || claims.exp > claims.iat + 120
  ) {
    throw new Error('handoff_token_invalid')
  }
  return claims
}
