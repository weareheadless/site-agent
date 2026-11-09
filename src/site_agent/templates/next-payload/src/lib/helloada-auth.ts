import crypto from 'node:crypto'

import config from '@payload-config'
import { createLocalReq, getPayload } from 'payload'
import type { PayloadRequest, TypedUser } from 'payload'

import { hashOwnerSubject } from '@/lib/helloada-handoff'
import { serviceAuthorized } from '@/lib/service-auth'

export type HelloAdaAuth = {
  payload: Awaited<ReturnType<typeof getPayload>>
  user: TypedUser
  req: Partial<PayloadRequest>
}

/**
 * Resolve the Payload owner linked to a HelloAda subject.
 *
 * The signed handoff creates this row the first time an owner enters the
 * tenant. The control plane may reach the same workspace before that handoff,
 * so it gets the same durable identity here instead of a second user model.
 */
async function serviceOwner(
  payload: Awaited<ReturnType<typeof getPayload>>,
  subject: string,
): Promise<TypedUser | undefined> {
  const existing = await payload.find({
    collection: 'users',
    where: { helloadaSubject: { equals: subject } },
    limit: 1,
    depth: 0,
    overrideAccess: true,
  })
  if (existing.docs[0]) return existing.docs[0] as TypedUser
  const subjectHash = await hashOwnerSubject(subject)
  try {
    return await payload.create({
      collection: 'users',
      data: {
        email: `owner-${subjectHash}@identity.helloada.invalid`,
        password: crypto.randomUUID() + crypto.randomUUID(),
        helloadaSubject: subject,
      },
      overrideAccess: true,
    }) as TypedUser
  } catch {
    // A concurrent first request may have created the same unique subject.
    const recovered = await payload.find({
      collection: 'users',
      where: { helloadaSubject: { equals: subject } },
      limit: 1,
      depth: 0,
      overrideAccess: true,
    })
    return recovered.docs[0] as TypedUser | undefined
  }
}

/**
 * Authenticate the owner workspace request.
 *
 * A browser carries the tenant Payload session. The control plane is a
 * server-to-server caller: it presents the tenant workspace token and the
 * HelloAda subject it has already authenticated, and receives the same Payload
 * owner identity and access checks as a session request.
 */
export async function authenticateHelloAdaRequest(request: Request): Promise<HelloAdaAuth | undefined> {
  const payload = await getPayload({ config })
  if (serviceAuthorized(request)) {
    const subject = request.headers.get('x-helloada-owner-subject')?.trim() || ''
    if (!subject) return undefined
    const user = await serviceOwner(payload, subject)
    if (!user) return undefined
    const serviceRequest = await createLocalReq({
      req: { headers: request.headers, method: request.method, url: request.url },
      user,
    }, payload)
    return { payload, user, req: serviceRequest }
  }
  const localRequest = await createLocalReq({ req: { headers: request.headers, method: request.method, url: request.url } }, payload)
  try {
    const result = await payload.auth({ headers: request.headers, req: localRequest })
    if (!result.user) return undefined
    const authenticatedRequest = await createLocalReq({ req: localRequest, user: result.user }, payload)
    return { payload, user: result.user, req: authenticatedRequest }
  } catch {
    return undefined
  }
}
