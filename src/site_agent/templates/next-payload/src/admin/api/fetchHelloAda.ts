import { helloAdaPath } from '../config/site'

const ADMIN_REQUEST_TIMEOUT_MS = 25_000

export const fetchHelloAda = async (
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> => {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), ADMIN_REQUEST_TIMEOUT_MS)
  const forwardAbort = () => controller.abort()

  if (init.signal?.aborted) controller.abort()
  else init.signal?.addEventListener('abort', forwardAbort, { once: true })

  try {
    const resolvedInput = typeof input === 'string' ? helloAdaPath(input) : input
    return await fetch(resolvedInput, { ...init, signal: controller.signal })
  } finally {
    clearTimeout(timeout)
    init.signal?.removeEventListener('abort', forwardAbort)
  }
}
