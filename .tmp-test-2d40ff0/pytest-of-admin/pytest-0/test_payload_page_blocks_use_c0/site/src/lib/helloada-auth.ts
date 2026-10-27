import config from '@payload-config'
import { createLocalReq, getPayload } from 'payload'
import type { PayloadRequest, TypedUser } from 'payload'

export type HelloAdaAuth = {
  payload: Awaited<ReturnType<typeof getPayload>>
  user: TypedUser
  req: Partial<PayloadRequest>
}

/** Authenticate the existing Payload session without exposing service tokens to the browser. */
export async function authenticateHelloAdaRequest(request: Request): Promise<HelloAdaAuth | undefined> {
  const payload = await getPayload({ config })
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
