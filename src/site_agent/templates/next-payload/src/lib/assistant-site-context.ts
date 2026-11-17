import { helloAdaSite } from '../helloada.config'
import { loadSiteCorpus, type CorpusDocument, type CorpusFact, type SiteCorpus, type SiteCorpusDeps } from './assistant-context'
import { getPublishedPosts, getSiteSettings, lexicalText } from './content'
import { presentationRoutes } from './content-routes'
import { publicRouteForDocument } from './public-content-route'
import { staticPresentationRoutes, type StaticWebsiteEnv } from './static-website'

/** Edge cache key for the assembled corpus; both consumers read the same bytes. */
const CORPUS_CACHE_KEY = 'https://assistant.internal/llms.txt'
const CORPUS_TTL_SECONDS = 3600
const PAGE_TIMEOUT_MS = 3000

export type SiteCorpusEnv = StaticWebsiteEnv & { NEXT_PUBLIC_SITE_URL?: string }

type EdgeCache = {
  match: (key: string) => Promise<Response | undefined>
  put: (key: string, response: Response) => Promise<unknown>
}

const edgeCache = (): EdgeCache | undefined => {
  const store = (globalThis as { caches?: { default?: unknown } }).caches?.default
  if (!store || typeof (store as EdgeCache).match !== 'function') return undefined
  return store as EdgeCache
}

/**
 * Facts a visitor actually asks for. These are the site settings fields the
 * shared content contract already owns; anything absent is simply omitted.
 */
const FACT_FIELDS: ReadonlyArray<readonly [string, string]> = [
  ['siteName', 'Site name'],
  ['description', 'Description'],
  ['tagline', 'Tagline'],
  ['email', 'Email'],
  ['contactEmail', 'Contact email'],
  ['phone', 'Phone'],
  ['telephone', 'Phone'],
  ['address', 'Address'],
  ['openingHours', 'Opening hours'],
  ['hours', 'Opening hours'],
  ['priceRange', 'Price range'],
]

const facts = async (): Promise<readonly CorpusFact[]> => {
  const settings = await getSiteSettings()
  const stated: CorpusFact[] = []
  for (const [field, label] of FACT_FIELDS) {
    const value = settings[field]
    if (typeof value === 'string' && value.trim()) stated.push({ label, value })
  }
  if (!stated.some(fact => fact.label === 'Site name')) {
    stated.unshift({ label: 'Site name', value: helloAdaSite.siteName })
  }
  return stated
}

/**
 * Published blog documents, the only collection whose routes are dynamic and so
 * absent from the committed route inventory. Products and catalogue documents
 * are out of scope for this corpus.
 */
const documents = async (): Promise<readonly CorpusDocument[]> => {
  // A site that declares no blog has no documents to read; that is a declared
  // absence, not a failed read.
  if (!helloAdaSite.features.posts) return []
  const posts = await getPublishedPosts()
  return posts.flatMap(post => {
    const title = String(post.title ?? '').trim()
    const body = lexicalText(post.body)
    if (!title && !body) return []
    return [{
      path: publicRouteForDocument('posts', post),
      title,
      text: body,
    }]
  })
}

const siteRoutes = async (env: SiteCorpusEnv): Promise<string[]> => {
  const [imported, presentation] = await Promise.all([
    staticPresentationRoutes(env),
    Promise.resolve(presentationRoutes()),
  ])
  return [...new Set([...presentation, ...imported])]
}

const pageHtml = (origin: string) => async (path: string): Promise<string> => {
  const response = await fetch(new URL(path, origin).toString(), {
    headers: { accept: 'text/html' },
    signal: AbortSignal.timeout(PAGE_TIMEOUT_MS),
  })
  if (!response.ok) throw new Error(`site page ${path} answered ${response.status}`)
  if (!(response.headers.get('content-type') || '').includes('text/html')) {
    throw new Error(`site page ${path} is not HTML`)
  }
  return response.text()
}

const build = async (env: SiteCorpusEnv, origin: string): Promise<SiteCorpus> => {
  const deps: SiteCorpusDeps = {
    siteName: helloAdaSite.siteName,
    routes: await siteRoutes(env),
    facts,
    documents,
    fetchHtml: pageHtml(origin),
  }
  return loadSiteCorpus(deps)
}

const cached = async (cache: EdgeCache | undefined, key: string): Promise<SiteCorpus | undefined> => {
  if (!cache) return undefined
  const hit = await cache.match(key).catch(() => undefined)
  if (!hit) return undefined
  try {
    return JSON.parse(await hit.text()) as SiteCorpus
  } catch {
    return undefined
  }
}

/**
 * The corpus for this exact site. Rendering costs one subrequest per enumerated
 * page, so the result is edge-cached; a rebuild is never triggered by a visitor
 * beyond that TTL.
 */
export const siteCorpus = async (env: SiteCorpusEnv, origin: string, options: { fresh?: boolean } = {}): Promise<SiteCorpus> => {
  const cache = edgeCache()
  const cacheKey = `${CORPUS_CACHE_KEY}?site=${encodeURIComponent(origin)}`
  if (!options.fresh) {
    const hit = await cached(cache, cacheKey)
    if (hit) return hit
  }
  const corpus = await build(env, origin)
  await cache?.put(cacheKey, new Response(JSON.stringify(corpus), {
    headers: { 'content-type': 'application/json', 'cache-control': `max-age=${CORPUS_TTL_SECONDS}` },
  })).catch(() => undefined)
  return corpus
}
