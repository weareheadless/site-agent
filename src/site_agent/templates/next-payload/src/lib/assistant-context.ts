/**
 * The public corpus the visitor assistant answers from, and `/llms.txt` serves.
 *
 * It merges the two presentations a HelloAda site can have — committed Next
 * pages and an imported static site — with the published Payload documents, so
 * a tenant with no collections still describes its offering. Nothing here reads
 * drafts: pages and static files are committed source by definition, and the
 * documents arrive already filtered to published.
 */

/** A page fetch budget: one subrequest per page, so this is also a cost control. */
export const MAX_PAGES = 12
/** Per-page character budget; a page longer than this is marked as truncated. */
export const MAX_PAGE_CHARS = 4000

const PLATFORM_PATH = /^\/(?:api|admin|mail|_next|_helloada|helloada-preview)(?:\/|$)/

/** Routes that are infrastructure, not owner-visible content. */
export const isContentPath = (value: string): boolean => {
  const path = String(value ?? '').trim()
  if (!path.startsWith('/') || path.startsWith('//')) return false
  if (PLATFORM_PATH.test(path)) return false
  return path !== '/llms.txt'
}

const ENTITIES: Record<string, string> = {
  '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&apos;': "'", '&nbsp;': ' ',
}

/** Visible text of one HTML page, preferring the page body over site chrome. */
export const extractPageText = (html: string): string => {
  const source = String(html ?? '')
  const main = source.match(/<main\b[^>]*>([\s\S]*?)<\/main>/i)
  let body = main ? main[1] : source
  if (!main) {
    const withoutHead = body.replace(/<head\b[^>]*>[\s\S]*?<\/head>/gi, ' ')
    const inner = withoutHead.match(/<body\b[^>]*>([\s\S]*?)<\/body>/i)
    body = inner ? inner[1] : withoutHead
  }
  const text = body
    .replace(/<(script|style|noscript|svg|template|nav|footer|header|aside|form)\b[^>]*>[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<[^>]+>/g, '\n')
    .replace(/&[a-z#0-9]+;/gi, entity => ENTITIES[entity.toLowerCase()] ?? ' ')
  return text
    .split('\n')
    .map(line => line.replace(/[ \t\u00a0]+/g, ' ').trim())
    .filter(Boolean)
    .join('\n')
    .slice(0, MAX_PAGE_CHARS)
}

export type CorpusPage = { path: string; title: string; text: string; truncated: boolean }
export type CorpusDocument = { path: string; title: string; text: string }
export type CorpusFact = { label: string; value: string }

export type SiteCorpusInput = {
  siteName: string
  facts: readonly CorpusFact[]
  pages: readonly CorpusPage[]
  documents: readonly CorpusDocument[]
  /** Routes that were enumerated but could not be read, named rather than hidden. */
  unavailable?: readonly string[]
}

const oneLine = (value: string): string => String(value ?? '').replace(/\s+/g, ' ').trim()

/** Render the corpus as the markdown both consumers share. */
export const renderCorpus = ({ siteName, facts, pages, documents, unavailable = [] }: SiteCorpusInput): string => {
  const blocks: string[] = [`# ${oneLine(siteName) || 'Website'}`]
  const stated = facts.filter(fact => oneLine(fact.value))
  if (stated.length) {
    blocks.push('## Facts', stated.map(fact => `- ${oneLine(fact.label)}: ${oneLine(fact.value)}`).join('\n'))
  }
  if (pages.length) {
    blocks.push('## Pages', pages.map(page => {
      const heading = `### ${page.path}${page.title ? ` — ${oneLine(page.title)}` : ''}`
      const body = page.text.trim() || 'No readable text.'
      return `${heading}\n${body}${page.truncated ? '\n(truncated)' : ''}`
    }).join('\n\n'))
  }
  if (documents.length) {
    blocks.push('## Published documents', documents.map(document => {
      const heading = `### ${document.path}${document.title ? ` — ${oneLine(document.title)}` : ''}`
      return `${heading}\n${document.text.trim() || 'No readable text.'}`
    }).join('\n\n'))
  }
  if (unavailable.length) {
    blocks.push('## Unavailable', unavailable.map(path => `- ${path} could not be read`).join('\n'))
  }
  return `${blocks.join('\n\n')}\n`
}

export type SiteCorpusDeps = {
  siteName: string
  /** Committed Next routes and imported static routes, already deduplicated. */
  routes: readonly string[]
  facts: () => Promise<readonly CorpusFact[]>
  documents: () => Promise<readonly CorpusDocument[]>
  /** Fetch one public page of this same site as HTML. */
  fetchHtml: (path: string) => Promise<string>
  /** Text of an imported static page served from committed assets, when it exists. */
  staticText?: (path: string) => Promise<string | undefined>
}

export type SiteCorpus = { markdown: string; pageCount: number; truncatedPages: number }

export const loadSiteCorpus = async (deps: SiteCorpusDeps): Promise<SiteCorpus> => {
  const routes = [...new Set(deps.routes.filter(isContentPath))]
  const selected = routes.slice(0, MAX_PAGES)
  const unavailable: string[] = []
  const pages: CorpusPage[] = []
  for (const path of selected) {
    const title = path === '/' ? deps.siteName : path.replace(/^\/+|\/+$/g, '').replace(/[-_/]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    let text = await deps.staticText?.(path)
    if (text === undefined) {
      try {
        text = extractPageText(await deps.fetchHtml(path))
      } catch {
        unavailable.push(path)
        continue
      }
    }
    const truncated = text.length >= MAX_PAGE_CHARS
    pages.push({ path, title, text, truncated })
  }
  const [facts, documents] = await Promise.all([deps.facts(), deps.documents()])
  return {
    markdown: renderCorpus({ siteName: deps.siteName, facts, pages, documents, unavailable }),
    pageCount: pages.length,
    truncatedPages: pages.filter(page => page.truncated).length,
  }
}
