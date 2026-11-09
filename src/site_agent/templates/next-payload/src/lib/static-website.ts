/** Explicit source-controlled presentation. Never a fallback for missing CMS content. */
import { workspacePreviewPath } from './workspace-preview-path.ts'

export type StaticWebsiteEnv = {
  HELLOADA_PRESENTATION_PROFILE?: string
  GA_MEASUREMENT_ID?: string
  GOOGLE_SITE_VERIFICATION?: string
  NEXT_PUBLIC_SITE_URL?: string
  ASSETS?: { fetch: (request: Request) => Promise<Response> }
}

type StaticManifest = {
  kind: 'static'
  routes: Record<string, string>
  files: Record<string, string>
  security?: Record<string, { origins?: Record<string, string[]> }>
}

/** The standard owner workspace embeds only the tenant preview alias. */
const CONTROL_PLANE_ORIGIN = 'https://helloada.app'

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

const normalizeRoutePath = (value: string): string => {
  if (value === '/') return '/'
  const path = '/' + value.split('/').filter(Boolean).join('/')
  return path === '' ? '/' : path
}

/**
 * The owner-visible routes of a static presentation.
 *
 * A static site has no committed Next page files: its real pages live in the
 * reviewed `helloada-frontend.json` inventory and ship as Worker assets. The
 * workspace must list those pages, not only the Payload documents that happen
 * to be managed by Next, or Home, Pulse and every other presentation page are
 * unreachable from the owner workspace.
 */
export async function staticPresentationRoutes(env: StaticWebsiteEnv): Promise<string[]> {
  if (env.HELLOADA_PRESENTATION_PROFILE !== 'static') return []
  if (!env.ASSETS) throw new Error('Static website declaration or asset binding is missing')
  const manifest = await loadStaticManifest(env.ASSETS)
  return [...new Set(Object.keys(manifest.routes).map(normalizeRoutePath))].sort((left, right) => {
    if (left === '/') return -1
    if (right === '/') return 1
    return left.localeCompare(right)
  })
}

/**
 * Keep a same-site navigation inside the Workspace preview mount.
 *
 * The public presentation is authored for the site root, so its links are
 * root-absolute or use the live host. The preview is a path alias on the same
 * Worker, which means those links would otherwise navigate the owner out of
 * the preview and onto the public site. This function is also serialized into
 * the preview document, so it must stay self-contained and free of imports.
 */
export function containPreviewNavigation(raw: string, mount: string, hosts: string[], baseHref: string): string {
  if (!raw) return raw
  const value = String(raw).trim()
  if (!value || value.charAt(0) === '#' || /^(?:mailto|tel|sms|javascript|data|blob):/i.test(value)) return raw
  let url: URL
  try {
    url = new URL(value, baseHref)
  } catch {
    return raw
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return raw
  if (hosts.indexOf(url.host) === -1) return raw
  const path = url.pathname
  if (path === mount || path.indexOf(`${mount}/`) === 0) return raw
  if (/^\/(?:api|admin|mail|_next|helloada-preview|_helloada)(?:\/|$)/.test(path)) return raw
  // A site script may build a URL from the mount-prefixed pathname it sees
  // (for example `/es` + `/tenant-preview/pulse`). Move that locale or prefix
  // behind the mount instead of nesting the mount inside the page path.
  const embedded = path.indexOf(`${mount}/`)
  if (embedded > 0) {
    const prefix = path.slice(0, embedded).replace(/^\/+|\/+$/g, '')
    const suffix = path.slice(embedded + mount.length).replace(/^\/+/, '')
    return `${mount}/${[prefix, suffix].filter(Boolean).join('/')}${url.search}${url.hash}`
  }
  return `${mount}${path}${url.search}${url.hash}`
}

/** Hosts whose pages belong to this tenant, including the live domain. */
const previewHosts = (env: StaticWebsiteEnv): string[] => {
  const hosts = new Set<string>()
  for (const candidate of [env.NEXT_PUBLIC_SITE_URL]) {
    if (!candidate) continue
    try {
      const url = new URL(candidate)
      if (!url.host) continue
      hosts.add(url.host)
      hosts.add(url.host.replace(/^www\./, ''))
      hosts.add(url.host.startsWith('www.') ? url.host : `www.${url.host}`)
    } catch {
      // An optional site URL that is not absolute must not disable previews.
    }
  }
  return [...hosts]
}

const previewNavigationScript = (mount: string, hosts: string[]): string => `<script>(function(){
var mount=${JSON.stringify(mount)};
var hosts=${JSON.stringify(hosts)};
if(hosts.indexOf(location.host)===-1)hosts.push(location.host);
var contain=${containPreviewNavigation.toString()};
function attribute(element){return element&&element.tagName==='FORM'?'action':'href';}
function fix(element){
  if(!element||!element.getAttribute)return;
  var name=attribute(element);
  var raw=element.getAttribute(name);
  if(raw===null)return;
  var next=contain(raw,mount,hosts,location.href);
  if(next!==raw)element.setAttribute(name,next);
}
function fixTree(root){
  if(!root||!root.querySelectorAll)return;
  var nodes=root.querySelectorAll('a[href], area[href], form[action]');
  for(var index=0;index<nodes.length;index++)fix(nodes[index]);
}
document.addEventListener('click',function(event){
  var target=event.target;
  if(!target||target.nodeType!==1||!target.closest)return;
  var anchor=target.closest('a[href], area[href]');
  if(!anchor||anchor.hasAttribute('download'))return;
  var raw=anchor.getAttribute('href');
  var next=contain(raw,mount,hosts,location.href);
  if(next===raw)return;
  event.preventDefault();
  if(anchor.target&&anchor.target!=='_self')window.open(next,anchor.target);
  else location.assign(next);
},true);
document.addEventListener('submit',function(event){
  var form=event.target;
  if(!form||form.tagName!=='FORM')return;
  var raw=form.getAttribute('action');
  if(raw===null)return;
  var next=contain(raw,mount,hosts,location.href);
  if(next!==raw)form.setAttribute('action',next);
},true);
function start(){
  fixTree(document);
  var observer=new MutationObserver(function(records){
    for(var index=0;index<records.length;index++){
      var record=records[index];
      if(record.type==='attributes')fix(record.target);
      else for(var nodeIndex=0;nodeIndex<record.addedNodes.length;nodeIndex++){
        var node=record.addedNodes[nodeIndex];
        if(node.nodeType===1){fix(node);fixTree(node);}
      }
    }
  });
  observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['href','action']});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);
else start();
})()<\/script>`

const injectPreviewNavigation = (html: string, mount: string, env: StaticWebsiteEnv): string => {
  const script = previewNavigationScript(mount, previewHosts(env))
  return /<\/body\s*>/i.test(html)
    ? html.replace(/<\/body\s*>/i, `${script}</body>`)
    : `${html}${script}`
}

/**
 * Apply the preview contract to any rendered page, whether it came from the
 * static inventory or from Next/Payload. The iframe must stay inside the
 * preview mount and must never be indexed or framed by another site.
 */
export async function previewHtmlResponse(response: Response, mount: string, env: StaticWebsiteEnv): Promise<Response> {
  const headers = new Headers(response.headers)
  headers.set('x-robots-tag', 'noindex, nofollow')
  headers.delete('x-frame-options')
  const frameAncestors = `frame-ancestors 'self' ${CONTROL_PLANE_ORIGIN}`
  const policy = headers.get('content-security-policy')
  headers.set('content-security-policy', policy
    ? /frame-ancestors/i.test(policy)
      ? policy.replace(/frame-ancestors[^;]*/i, frameAncestors)
      : `${policy}; ${frameAncestors}`
    : frameAncestors)
  const contentType = (headers.get('content-type') || '').toLowerCase()
  if (!contentType.includes('text/html') || response.body === null) {
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers })
  }
  const html = injectPreviewNavigation(await response.text(), mount, env)
  headers.delete('content-length')
  headers.delete('content-encoding')
  headers.delete('etag')
  return new Response(html, { status: response.status, statusText: response.statusText, headers })
}

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
    url.pathname = isPreview && previewMount ? previewMount + canonicalPath : canonicalPath
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
    errorHeaders.set('content-security-policy', pagePolicy(manifest, file, measurement, isPreview))
    if (isPreview) errorHeaders.delete('x-frame-options')
    const errorResponse = new Response(request.method === 'HEAD' ? null : asset.body, { status: 404, headers: errorHeaders })
    return isPreview && previewMount ? previewHtmlResponse(errorResponse, previewMount, env) : errorResponse
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
  if (isPreview) {
    headers.set('x-robots-tag', 'noindex, nofollow')
    // X-Frame-Options cannot name the control-plane origin. The preview is
    // embedded by the owner workspace; CSP frame-ancestors carries that policy.
    headers.delete('x-frame-options')
  } else {
    headers.set('x-frame-options', 'SAMEORIGIN')
  }
  headers.set('content-security-policy', pagePolicy(manifest, file, measurement, isPreview))
  const response = new Response(request.method === 'HEAD' ? null : html, { status: 200, headers })
  return isPreview && previewMount ? previewHtmlResponse(response, previewMount, env) : response
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
function pagePolicy(manifest: StaticManifest, file: string, measurement: string, preview = false): string {
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
    ['frame-ancestors', preview ? ["'self'", CONTROL_PLANE_ORIGIN] : ["'self'"]],
  ]
  return directives
    .filter(([, values]) => values.length)
    .map(([key, values]) => `${key} ${values.join(' ')}`)
    .join('; ')
}
