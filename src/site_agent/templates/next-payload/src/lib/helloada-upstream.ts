const UPSTREAM_TIMEOUT_MS = 25_000

const upstreamBase = () => (process.env.SITE_AGENT_URL || '').replace(/\/$/, '')
const upstreamToken = () => process.env.HELLOADA_SITE_AGENT_TOKEN || ''

const upstreamPath = (path: string) => {
  const base = upstreamBase()
  if (!base || !upstreamToken()) return undefined
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

const remapPath = (path: string, method: string, search: string) => {
  const suffix = path.replace(/^\/api\/helloada/, '') || '/'
  if (suffix === '/ada' && method === 'POST') return `/workspace/chat${search}`
  if (suffix === '/ada' && method === 'GET') {
    const params = new URLSearchParams(search)
    const jobId = params.get('job_id')
    if (jobId) return `/workspace/chat/jobs/${encodeURIComponent(jobId)}`
    return `/workspace/chat/status${search}`
  }
  if (suffix === '/intake/confirm') return `/workspace/chat/intake/confirm${search}`
  if (suffix === '/design/start') return `/workspace/chat/design/start${search}`
  if (suffix === '/conversations') return `/workspace/chat/conversations${search}`
  const conversation = suffix.match(/^\/conversations\/([^/]+)$/)
  if (conversation) return `/workspace/chat/conversations/${encodeURIComponent(conversation[1])}${search}`
  if (suffix === '/history') return `/workspace/history${search}`
  if (suffix === '/drafts') return `/workspace/drafts${search}`
  const draft = suffix.match(/^\/drafts\/([^/]+)\/(approve|discard)$/)
  if (draft) return `/workspace/drafts/${encodeURIComponent(draft[1])}/${draft[2]}${search}`
  const version = suffix.match(/^\/versions\/([^/]+)\/restore$/)
  if (version) return `/workspace/versions/${encodeURIComponent(version[1])}/restore${search}`
  if (suffix === '/worktree/discard') return `/workspace/worktree/discard${search}`
  if (suffix === '/source/preview') return `/workspace/source/preview${search}`
  if (suffix.startsWith('/source/preview/')) return `/workspace${suffix}${search}`
  return undefined
}

export async function fetchHelloAdaUpstream(path: string, request: Request): Promise<Response | undefined> {
  const mapped = remapPath(path, request.method, new URL(request.url).search)
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
