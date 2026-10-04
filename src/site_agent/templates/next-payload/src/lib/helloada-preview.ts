import { runtimeValue } from '@/lib/runtime-env'

export type HelloAdaPreviewClaims = {
  version: 1
  tenantId: string
  ownerId: string
  collection: 'pages' | 'posts' | 'products'
  documentId: string
  documentHash: string
  route: string
  state: 'draft' | 'published'
  expiresAt: number
}

const encoder = new TextEncoder()
const decoder = new TextDecoder()
const collections = new Set<HelloAdaPreviewClaims['collection']>(['pages', 'posts', 'products'])

const base64Url = (bytes: Uint8Array) => {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

const decodeBase64Url = (value: string) => {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/')
  const binary = atob(normalized + '='.repeat((4 - normalized.length % 4) % 4))
  return Uint8Array.from(binary, (character) => character.charCodeAt(0))
}

const signingKey = async () => {
  const secret = runtimeValue('PAYLOAD_SECRET')
  if (secret.length < 32) throw new Error('The tenant Payload secret is unavailable for exact document preview.')
  return crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify'])
}

const validClaims = (value: unknown, tenantId: string): value is HelloAdaPreviewClaims => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const claims = value as Partial<HelloAdaPreviewClaims>
  return claims.version === 1
    && claims.tenantId === tenantId
    && typeof claims.ownerId === 'string' && claims.ownerId.length > 0
    && typeof claims.collection === 'string' && collections.has(claims.collection as HelloAdaPreviewClaims['collection'])
    && typeof claims.documentId === 'string' && claims.documentId.length > 0
    && typeof claims.documentHash === 'string' && /^sha256:[0-9a-f]{64}$/.test(claims.documentHash)
    && typeof claims.route === 'string' && claims.route.startsWith('/') && !claims.route.startsWith('//')
    && (claims.state === 'draft' || claims.state === 'published')
    && Number.isSafeInteger(claims.expiresAt) && Number(claims.expiresAt) > Math.floor(Date.now() / 1000)
    && Number(claims.expiresAt) <= Math.floor(Date.now() / 1000) + 181
}

export const createHelloAdaPreviewToken = async (
  input: Omit<HelloAdaPreviewClaims, 'version' | 'expiresAt'>,
) => {
  const claims: HelloAdaPreviewClaims = {
    version: 1,
    ...input,
    expiresAt: Math.floor(Date.now() / 1000) + 180,
  }
  if (!validClaims(claims, input.tenantId)) throw new Error('Exact document preview claims are invalid.')
  const payload = encoder.encode(JSON.stringify(claims))
  const signature = await crypto.subtle.sign('HMAC', await signingKey(), payload)
  return `${base64Url(payload)}.${base64Url(new Uint8Array(signature))}`
}

export const verifyHelloAdaPreviewToken = async (token: string, tenantId: string) => {
  const [payloadPart, signaturePart, extra] = token.split('.')
  if (!payloadPart || !signaturePart || extra !== undefined) return undefined
  let payload: Uint8Array
  let signature: Uint8Array
  let claims: unknown
  try {
    payload = decodeBase64Url(payloadPart)
    signature = decodeBase64Url(signaturePart)
    claims = JSON.parse(decoder.decode(payload))
  } catch {
    return undefined
  }
  if (!validClaims(claims, tenantId)) return undefined
  if (!await crypto.subtle.verify('HMAC', await signingKey(), signature, payload)) return undefined
  return claims
}
