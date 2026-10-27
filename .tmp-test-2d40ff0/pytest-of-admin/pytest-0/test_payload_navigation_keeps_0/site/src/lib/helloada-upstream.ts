import { helloAdaRuntime, helloAdaWorkspacePath } from '@weareheadless/helloada-payload-admin/server'

const UPSTREAM_TIMEOUT_MS = 25_000

const upstreamBase = () => helloAdaRuntime().url
const upstreamToken = () => helloAdaRuntime().token

const upstreamPath = (path: string) => {
  const base = upstreamBase()
  if (!base || !upstreamToken()) return undefined
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

export async function fetchHelloAdaUpstream(path: string, request: Request): Promise<Response | undefined> {
  const mapped = helloAdaWorkspacePath(path, request.method, new URL(request.url).search)
  const url = mapped ? upstreamPath(mapped) : undefined
  if (!url) return undefined
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS)
  try {
    const headers = new Headers({ Accept: request.headers.get('accept') || 'application/json' })
    headers.set('Authorization', `Bearer ${upstreamToken()}`)
    const contentType = request.headers.get('content-type')
    if (contentType) headers.set('Content-Type', contentType)
    const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.arrayBuffer()
    const response = await fetch(url, { method: request.method, headers, body, cache: 'no-store', signal: controller.signal })
    return new Response(response.body, { status: response.status, headers: { 'Cache-Control': 'no-store', 'Content-Type': response.headers.get('content-type') || 'application/json' } })
  } catch (error) {
    console.error('HelloAda upstream request failed', { path, message: error instanceof Error ? error.message : 'unknown error' })
    return undefined
  } finally {
    clearTimeout(timeout)
  }
}
