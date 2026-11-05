/** Explicit source-controlled presentation. Never a fallback for missing CMS content. */
import { workspacePreviewPath } from './workspace-preview-path.ts'

export type StaticWebsiteEnv = {
  HELLOADA_PRESENTATION_PROFILE?: string
  GA_MEASUREMENT_ID?: string
  GOOGLE_SITE_VERIFICATION?: string
  ASSETS?: { fetch: (request: Request) => Promise<Response> }
}

type StaticManifest = {
  kind: 'static'
  routes: Record<string, string>
  files: Record<string, string>
  security?: Record<string, { origins?: Record<string, string[]> }>
}

/**
 * The committed inventory of the imported static site. It ships with the
 * Worker assets because Cloudflare caps a text binding at 5.1 kB and a real
 * site has one route per page. The binding is loaded once per isolate.
 */
const STATIC_MANIFEST_PATH = '/_helloada/static-manifest.json'
const manifestCache = new WeakMap<object, Promise<StaticManifest>>()

function loadStaticManifest(assets: NonNullable<StaticWebsiteEnv['ASSETS']>): Promise<StaticManifest> {
  const cached = manifestCache.get(assets)
  if (cached) return cached
  const pending = (async () => {
    const response = await assets.fetch(new Request('https://static-manifest.internal' + STATIC_MANIFEST_PATH))
    if (!response.ok) throw new Error('Static website declaration is unavailable')
    const manifest = await response.json() as StaticManifest
    if (manifest?.kind !== 'static' || !manifest.routes?.['/'] || !manifest.files) {
      throw new Error('Static website declaration is invalid')
    }
    return manifest
  })()
  manifestCache.set(assets, pending)
  pending.catch(() => manifestCache.delete(assets))
  return pending
}

const escapeHtml = (value: string) => value.replace(/[&<>"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[character]!)

/**
 * Bases the tenant serves from Payload instead of the static inventory.
 *
 * The handler runs before Next, so a managed base must be excluded here or the
 * stored snapshot would always win. The declaration belongs to the tenant: a
 * hardcoded list would silently take pages away from other static sites.
 */
const managedBases = (value: unknown): string[] => {
  if (value === undefined) return []
  if (!Array.isArray(value)) throw new Error('Managed presentation paths must be an array')
  return value.map((item) => {
    const base = typeof item === 'string' ? item.trim() : ''
    if (!base.startsWith('/') || base.startsWith('//') || base.includes('?') || base.includes('#')) {
      throw new Error('A managed presentation path must be an absolute site path')
    }
    return base.length > 1 ? base.replace(/\/+$/, '') : base
  })
}

/**
 * The internal path for a managed URL published with a trailing slash.
 *
 * Next normalises trailing slashes before middleware runs, so a managed page
 * would answer 308. The Worker rewrites the request internally instead, which
 * keeps the published URL serving the managed page.
 */
export const managedPathRewrite = (pathname: string, managedPaths?: unknown): string | undefined => {
  if (!pathname || pathname === '/' || !pathname.endsWith('/')) return undefined
  const trimmed = pathname.replace(/\/+$/, '')
  if (!trimmed) return undefined
  return managedBases(managedPaths).some((base) => trimmed === base || trimmed.startsWith(`${base}/`))
    ? trimmed
    : undefined
}

export async function staticWebsiteResponse(request: Request, env: StaticWebsiteEnv, previewMount?: string, managedPaths?: unknown): Promise<Response | null> {
  if (!env.HELLOADA_PRESENTATION_PROFILE || env.HELLOADA_PRESENTATION_PROFILE === 'payload') return null
  if (env.HELLOADA_PRESENTATION_PROFILE !== 'static') throw new Error('Unsupported presentation profile')
  if (!env.ASSETS) throw new Error('Static website declaration or asset binding is missing')
  const manifest = await loadStaticManifest(env.ASSETS)
  if (!manifest.routes?.['/'] || !manifest.files) {
    throw new Error('Static website declaration or asset binding is missing')
  }
  const url = new URL(request.url)
  if (request.method !== 'GET' && request.method !== 'HEAD') return null
  // This handler precedes Next middleware. Resolve the existing Workspace
  // display alias here too, through the same public renderer and inventory.
  const previewPath = previewMount ? workspacePreviewPath(url.pathname, previewMount) : undefined
  const isPreview = previewPath !== undefined
  if (isPreview) url.pathname = previewPath
  const measurement = env.GA_MEASUREMENT_ID || ''
  if (measurement && !/^G-[A-Z0-9]+$/.test(measurement)) throw new Error('Invalid GA4 measurement identifier')
  if (url.pathname === '/_helloada/analytics.js') {
    if (!measurement) return new Response(null, { status: 404 })
    const id = JSON.stringify(measurement)
    return new Response(request.method === 'HEAD' ? null : `window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}gtag('js',new Date());gtag('config',${id});const s=document.createElement('script');s.async=true;s.src='https://www.googletagmanager.com/gtag/js?id='+${id};document.head.appendChild(s);`,
      { headers: { 'content-type': 'application/javascript; charset=utf-8', 'cache-control': 'no-store' } })
  }
  // The reviewed route inventory is platform state, not a public document.
  if (url.pathname === STATIC_MANIFEST_PATH) return new Response('Page not found', { status: 404 })
  // Platform paths always retain their canonical authentication/route handling.
  if (url.pathname === '/helloada-release.json') return null
  if (managedBases(managedPaths).some((base) => url.pathname === base || url.pathname.startsWith(`${base}/`))) return null
  if (/^\/(admin|api|mail|_next|blog|_helloada|helloada-preview)(\/|$)/.test(url.pathname)) return null
  const canonicalPath = url.pathname.endsWith('/') ? url.pathname : url.pathname + '/'
  if (!url.pathname.endsWith('/') && Object.hasOwn(manifest.routes, canonicalPath)) {
    url.pathname = isPreview ? previewMount + canonicalPath : canonicalPath
    return new Response(null, { status: 308, headers: {
      location: url.toString(), ...(isPreview ? { 'x-robots-tag': 'noindex, nofollow' } : {}),
    } })
  }
  const file = manifest.routes[url.pathname] || manifest.routes[canonicalPath]
    || (Object.hasOwn(manifest.files, url.pathname) ? url.pathname : null)
    || (Object.hasOwn(manifest.files, '/404.html') ? '/404.html' : null)
  if (!file) return new Response('Page not found', { status: 404 })
  if (!Object.hasOwn(manifest.files, file) || !file.startsWith('/') || file.includes('..')) {
    throw new Error('Static website route is outside its declared assets')
  }
  const assetUrl = new URL(file, url.origin)
  const asset = await env.ASSETS.fetch(new Request(assetUrl, { method: 'GET' }))
  if (!asset.ok) return new Response('Declared website asset is unavailable', { status: 503 })
  // Preserve the operator's error document, including valid optional-head HTML.
  // It is not a publishable page and receives no indexing/tracking injection.
  if (file === '/404.html') {
    const errorHeaders = new Headers(asset.headers)
    errorHeaders.set('content-security-policy', pagePolicy(manifest, file, measurement))
    return new Response(request.method === 'HEAD' ? null : asset.body, { status: 404, headers: errorHeaders })
  }
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
  if (isPreview) headers.set('x-robots-tag', 'noindex, nofollow')
  headers.set('x-frame-options', 'SAMEORIGIN')
  headers.set('content-security-policy', pagePolicy(manifest, file, measurement))
  return new Response(request.method === 'HEAD' ? null : html, { status: 200, headers })
}

type PageSecurity = { origins?: Record<string, string[]> }

/** Origins the presentation declares for every page of the site. */
type SiteOrigins = Record<string, string[]>

/** Google measurement endpoints the site's own tag manager calls. */
const MEASUREMENT_SCRIPT = ['https://www.googletagmanager.com']
const MEASUREMENT_CONNECT = [
  'https://www.google-analytics.com',
  'https://analytics.google.com',
  'https://*.analytics.google.com',
  'https://www.googletagmanager.com',
  'https://stats.g.doubleclick.net',
  'https://www.google.com',
]
/** Google WebFont Loader injects its stylesheet and font files at runtime. */
const WEBFONT_STYLE = ['https://fonts.googleapis.com']
const WEBFONT_FONT = ['https://fonts.gstatic.com']
const MEASUREMENT_IMG = [
  'https://www.google-analytics.com',
  'https://www.googletagmanager.com',
  'https://www.google.com',
  'https://*.google.com',
  'https://*.google.com.mx',
]

/**
 * Build the policy from the reviewed declaration for this exact page: the
 * external origins its markup references. Inline execution stays allowed
 * because the export generates inline code at runtime; external script
 * sources are limited to the declaration.
 */
function pagePolicy(manifest: StaticManifest, file: string, measurement: string): string {
  const declared: PageSecurity = (manifest.security || {})[file] || {}
  // The inventory can declare origins the exported markup cannot reveal, such
  // as images or map tiles fetched at runtime by the site's own scripts.
  const siteOrigins: SiteOrigins = (manifest as StaticManifest & { origins?: SiteOrigins }).origins || {}
  const merge = (...lists: (string[] | undefined)[]) => [...new Set(lists.flatMap((list) => list || []))]
  const origins: Record<string, string[]> = {}
  for (const directive of new Set([...Object.keys(siteOrigins), ...Object.keys(declared.origins || {})])) {
    origins[directive] = merge(siteOrigins[directive], (declared.origins || {})[directive])
  }
  const ownMeasurement = (origins.script || []).some((origin) => origin === 'https://www.googletagmanager.com')
  const analytics = measurement || ownMeasurement
  const webfont = (origins.script || []).some((origin) => origin === 'https://ajax.googleapis.com')
  const directives: [string, string[]][] = [
    ['default-src', ["'self'"]],
    ['script-src', merge(["'self'", "'unsafe-inline'"], origins.script, analytics ? MEASUREMENT_SCRIPT : [])],
    ['script-src-attr', ["'unsafe-inline'"]],
    ['worker-src', ["'self'", 'blob:']],
    ['style-src', merge(["'self'", "'unsafe-inline'"], origins.style, webfont ? WEBFONT_STYLE : [])],
    ['img-src', merge(["'self'", 'data:'], origins.img, analytics ? MEASUREMENT_IMG : [])],
    ['font-src', merge(["'self'", 'data:'], origins.font, webfont ? WEBFONT_FONT : [])],
    ['media-src', merge(["'self'"], origins.media)],
    ['connect-src', merge(["'self'"], origins.script, origins.connect, analytics ? MEASUREMENT_CONNECT : [])],
    ['frame-src', merge(origins.frame)],
    ['object-src', ["'none'"]],
    ['base-uri', ["'self'"]],
    ['frame-ancestors', ["'self'"]],
  ]
  return directives
    .filter(([, values]) => values.length)
    .map(([key, values]) => `${key} ${values.join(' ')}`)
    .join('; ')
}
