import { NextResponse } from 'next/server'
import { createLocalReq, getFieldsToSign, getPayload, jwtSign } from 'payload'
import { addSessionToUser, generatePayloadCookie } from 'payload/shared'
import type { TypedUser } from 'payload'

import config from '@payload-config'
import { decodeHandoffPublicKey, hashOwnerSubject, verifyOwnerHandoffToken } from '@/lib/helloada-handoff'
import { runtimeValue } from '@/lib/runtime-env'

export const dynamic = 'force-dynamic'

const noStoreHeaders = {
  'cache-control': 'no-store, max-age=0',
  'referrer-policy': 'no-referrer',
  'x-content-type-options': 'nosniff',
}

function response(status: number, error: string) {
  return NextResponse.json({ error }, { status, headers: noStoreHeaders })
}

function isHttpsOrigin(value: string): boolean {
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'https:' && parsed.origin === value
  } catch {
    return false
  }
}

async function readToken(request: Request): Promise<string> {
  if (!request.headers.get('content-type')?.toLowerCase().startsWith('application/x-www-form-urlencoded')) {
    throw new Error('handoff_request_invalid')
  }
  const declaredLength = Number(request.headers.get('content-length') || 0)
  if (declaredLength > 8_192) throw new Error('handoff_request_invalid')

  const reader = request.body?.getReader()
  if (!reader) throw new Error('handoff_request_invalid')
  const chunks: Uint8Array[] = []
  let size = 0
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    size += value.byteLength
    if (size > 8_192) {
      await reader.cancel()
      throw new Error('handoff_request_invalid')
    }
    chunks.push(value)
  }
  const body = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) {
    body.set(chunk, offset)
    offset += chunk.byteLength
  }
  const fields = new URLSearchParams(new TextDecoder().decode(body))
  const token = fields.get('token') || ''
  if (!token || fields.size !== 1) throw new Error('handoff_request_invalid')
  return token
}

export async function POST(request: Request) {
  const issuer = runtimeValue('HELLOADA_HANDOFF_ISSUER')
  const publicKey = runtimeValue('HELLOADA_HANDOFF_PUBLIC_KEY')
  const tenantId = runtimeValue('HELLOADA_TENANT_ID')
  const requestUrl = new URL(request.url)
  const requestOrigin = requestUrl.origin
  if (!issuer || !publicKey || !tenantId) return response(503, 'owner_handoff_not_configured')
  if (
    requestUrl.protocol !== 'https:'
    || request.headers.get('origin') !== issuer
    || !isHttpsOrigin(issuer)
  ) {
    return response(403, 'owner_handoff_origin_invalid')
  }

  let claims
  try {
    const token = await readToken(request)
    claims = await verifyOwnerHandoffToken(token, {
      issuer,
      tenantId,
      targetOrigin: requestOrigin,
      publicKey: decodeHandoffPublicKey(publicKey),
    })
  } catch {
    return response(401, 'owner_handoff_invalid_or_expired')
  }

  const payload = await getPayload({ config })
  const ownerSubjectHash = await hashOwnerSubject(claims.sub)
  try {
    await payload.create({
      collection: 'owner-handoff-grants',
      data: {
        grantId: claims.jti,
        tenantId,
        ownerSubjectHash,
        consumedAt: new Date().toISOString(),
      },
      overrideAccess: true,
    })
  } catch {
    return response(409, 'owner_handoff_already_used')
  }

  const existing = await payload.find({
    collection: 'users',
    where: { helloadaSubject: { equals: claims.sub } },
    limit: 1,
    depth: 0,
    overrideAccess: true,
  })
  const user = (existing.docs[0] || await payload.create({
    collection: 'users',
    data: {
      email: `owner-${ownerSubjectHash}@identity.helloada.invalid`,
      password: crypto.randomUUID() + crypto.randomUUID(),
      helloadaSubject: claims.sub,
    },
    overrideAccess: true,
  })) as TypedUser & { email: string; collection?: string; _strategy?: string }

  user.collection = 'users'
  user._strategy = 'local-jwt'
  const collectionConfig = payload.collections.users.config
  const session = await addSessionToUser({ collectionConfig, payload, req: await createLocalReq({}, payload), user })
  const fieldsToSign = getFieldsToSign({
    collectionConfig,
    email: user.email,
    sid: session.sid,
    user,
  })
  const { token } = await jwtSign({
    fieldsToSign,
    secret: payload.secret,
    tokenExpiration: collectionConfig.auth.tokenExpiration,
  })
  const cookie = generatePayloadCookie({
    collectionAuthConfig: collectionConfig.auth,
    cookiePrefix: payload.config.cookiePrefix || 'payload',
    token,
  })
  return new Response(null, {
    status: 303,
    headers: {
      ...noStoreHeaders,
      location: new URL('/admin', requestOrigin).toString(),
      'set-cookie': cookie,
    },
  })
}
