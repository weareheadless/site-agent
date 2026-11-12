import { helloAdaRuntime, helloAdaWorkspacePath } from '@/lib/helloada-runtime'

const UPSTREAM_TIMEOUT_MS = 25_000

/** A compiled candidate's redirect belongs to the owner's surface, not here. */
const previewRuntime = (path: string): boolean => /^\/api\/helloada\/source\/preview\/[^/]+\/runtime(?:\/|$)/.test(path)

const previewRequestHeaders = ['rsc', 'next-router-state-tree', 'next-router-prefetch', 'next-router-segment-prefetch', 'next-url', 'purpose', 'x-nextjs-data']

const upstreamBase = () => helloAdaRuntime().url
const upstreamToken = () => helloAdaRuntime().token

const upstreamPath = (path: string) => {
  const base = upstreamBase()
  if (!base || !upstreamToken()) return undefined
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

export async function fetchHelloAdaUpstream(path: string, request: Request, ownerActorId?: string): Promise<Response | undefined> {
  const mapped = helloAdaWorkspacePath(path, request.method, new URL(request.url).search)
  const url = mapped ? upstreamPath(mapped) : undefined
  if (!url) return undefined
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS)
  try {
    const headers = new Headers({ Accept: request.headers.get('accept') || 'application/json' })
    headers.set('Authorization', `Bearer ${upstreamToken()}`)
    // Only the authenticated server caller supplies this value. Never copy an
    // incoming browser actor header/body into the trusted service request.
    if (ownerActorId) headers.set('X-HelloAda-Owner-Id', ownerActorId)
    const contentType = request.headers.get('content-type')
    if (contentType) headers.set('Content-Type', contentType)
    // A compiled preview answers RSC navigation only when the flight request
    // headers survive the bridge.
    if (previewRuntime(path)) {
      for (const name of previewRequestHeaders) {
        const value = request.headers.get(name)
        if (value) headers.set(name, value)
      }
    }
    const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.arrayBuffer()
    const response = await fetch(url, {
      method: request.method,
      headers,
      body,
      cache: 'no-store',
      // Never follow a candidate redirect here: the destination is a mount on
      // the owner surface, and resolving it against this origin lands nowhere.
      redirect: previewRuntime(path) ? 'manual' : 'follow',
      signal: controller.signal,
    })
    const out = new Headers({ 'Cache-Control': 'no-store', 'Content-Type': response.headers.get('content-type') || 'application/json' })
    const location = previewRuntime(path) ? response.headers.get('location') : null
    if (location) out.set('Location', location)
    return new Response(response.body, { status: response.status, headers: out })
  } catch (error) {
    console.error('HelloAda upstream request failed', { path, message: error instanceof Error ? error.message : 'unknown error' })
    return undefined
  } finally {
    clearTimeout(timeout)
  }
}
