/** Explicit source-controlled presentation. Never a fallback for missing CMS content. */
export type StaticWebsiteEnv = {
  HELLOADA_PRESENTATION_PROFILE?: string
  HELLOADA_STATIC_MANIFEST?: string
  GA_MEASUREMENT_ID?: string
  GOOGLE_SITE_VERIFICATION?: string
  ASSETS?: { fetch: (request: Request) => Promise<Response> }
}

type StaticManifest = { kind: 'static'; routes: Record<string, string>; files: Record<string, string> }

const escapeHtml = (value: string) => value.replace(/[&<>"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[character]!)

export async function staticWebsiteResponse(request: Request, env: StaticWebsiteEnv): Promise<Response | null> {
  if (!env.HELLOADA_PRESENTATION_PROFILE || env.HELLOADA_PRESENTATION_PROFILE === 'payload') return null
  if (env.HELLOADA_PRESENTATION_PROFILE !== 'static') throw new Error('Unsupported presentation profile')
  const manifest = JSON.parse(env.HELLOADA_STATIC_MANIFEST || '') as StaticManifest
  if (manifest.kind !== 'static' || !manifest.routes?.['/'] || !manifest.files || !env.ASSETS) {
    throw new Error('Static website declaration or asset binding is missing')
  }
  const url = new URL(request.url)
  if (request.method !== 'GET' && request.method !== 'HEAD') return null
  const measurement = env.GA_MEASUREMENT_ID || ''
  if (measurement && !/^G-[A-Z0-9]+$/.test(measurement)) throw new Error('Invalid GA4 measurement identifier')
  if (url.pathname === '/_helloada/analytics.js') {
    if (!measurement) return new Response(null, { status: 404 })
    const id = JSON.stringify(measurement)
    return new Response(`window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}gtag('js',new Date());gtag('config',${id});const s=document.createElement('script');s.async=true;s.src='https://www.googletagmanager.com/gtag/js?id='+${id};document.head.appendChild(s);`,
      { headers: { 'content-type': 'application/javascript; charset=utf-8', 'cache-control': 'no-store' } })
  }
  // Platform paths always retain their canonical authentication/route handling.
  if (/^\/(admin|api|mail|_next|blog|_helloada)(\/|$)/.test(url.pathname)) return null
  const canonicalPath = url.pathname.endsWith('/') ? url.pathname : url.pathname + '/'
  if (!url.pathname.endsWith('/') && Object.hasOwn(manifest.routes, canonicalPath)) {
    url.pathname = canonicalPath
    return Response.redirect(url.toString(), 308)
  }
  const file = manifest.routes[url.pathname] || manifest.routes[canonicalPath]
    || (Object.hasOwn(manifest.files, url.pathname) ? url.pathname : null)
  if (!file) return new Response('Page not found', { status: 404 })
  if (!Object.hasOwn(manifest.files, file) || !file.startsWith('/') || file.includes('..')) {
    throw new Error('Static website route is outside its declared assets')
  }
  const assetUrl = new URL(file, url.origin)
  const asset = await env.ASSETS.fetch(new Request(assetUrl, { method: 'GET' }))
  if (!asset.ok) return new Response('Declared website asset is unavailable', { status: 503 })
  if (!file.endsWith('.html')) return request.method === 'HEAD'
    ? new Response(null, { status: asset.status, headers: asset.headers }) : asset
  let html = await asset.text()
  if (!/<\/head\s*>/i.test(html)) throw new Error('Static page has no head boundary')
  const verification = env.GOOGLE_SITE_VERIFICATION || ''
  let tags = verification ? `<meta name="google-site-verification" content="${escapeHtml(verification)}">` : ''
  if (measurement) tags += '<script src="/_helloada/analytics.js" defer></script>'
  html = html.replace(/<\/head\s*>/i, tags + '</head>')
  const headers = new Headers(asset.headers)
  headers.delete('content-length')
  headers.delete('etag')
  headers.set('content-type', 'text/html; charset=utf-8')
  headers.set('cache-control', 'no-store')
  headers.set('x-frame-options', 'SAMEORIGIN')
  let csp = headers.get('content-security-policy') || "default-src 'self'; object-src 'none'; base-uri 'self'"
  csp = csp.replace(/(?:^|;)\s*frame-ancestors\s+[^;]*/g, '') + "; frame-ancestors 'self'"
  if (measurement) {
    const directives = new Map(csp.split(';').map((part) => part.trim().split(/\s+/)).filter(([key]) => key)
      .map(([key, ...values]) => [key, values]))
    for (const [key, origins] of [
      ['script-src', ['https://www.googletagmanager.com']],
      ['connect-src', ['https://*.google-analytics.com', 'https://*.analytics.google.com', 'https://www.googletagmanager.com']],
      ['img-src', ['https://*.google-analytics.com', 'https://*.googletagmanager.com']],
    ] as const) {
      directives.set(key, [...(directives.get(key) || directives.get('default-src') || ["'self'"]), ...origins])
    }
    csp = [...directives].map(([key, values]) => [key, ...values].join(' ')).join('; ')
  }
  headers.set('content-security-policy', csp)
  return new Response(request.method === 'HEAD' ? null : html, { status: 200, headers })
}
