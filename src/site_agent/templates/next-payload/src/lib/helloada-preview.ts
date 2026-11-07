import { runtimeValue } from '@/lib/runtime-env'
import {
  buildHelloAdaPreviewClaims,
  validHelloAdaPreviewClaims,
  type HelloAdaPreviewClaims,
  type HelloAdaPreviewInput,
} from '@/lib/helloada-preview-claims'

export type { HelloAdaPreviewClaims, HelloAdaPreviewPurpose } from '@/lib/helloada-preview-claims'
export { helloAdaPreviewLifetime } from '@/lib/helloada-preview-claims'

const encoder = new TextEncoder()
const decoder = new TextDecoder()

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

export const createHelloAdaPreviewToken = async (input: HelloAdaPreviewInput) => {
  const claims = buildHelloAdaPreviewClaims(input, Math.floor(Date.now() / 1000))
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
  if (!validHelloAdaPreviewClaims(claims, tenantId, Math.floor(Date.now() / 1000))) return undefined
  if (!await crypto.subtle.verify('HMAC', await signingKey(), signature, payload)) return undefined
  return claims as HelloAdaPreviewClaims
}
