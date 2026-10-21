import { hashJson } from './payload-hash.ts'

type Row = Record<string, unknown>
type SnapshotPayload = {
  find(args: Row): Promise<{ docs: Row[]; totalDocs: number; totalPages: number; hasNextPage: boolean }>
  findGlobal(args: Row): Promise<Row>
}
type SnapshotOptions = {
  tenant: string
  sourceSha: string
  schemaIdentity: string
  locales: string[]
  defaultLocale: string
  collections: Record<string, readonly string[]>
  globals: Record<string, readonly string[]>
}

const websiteCollections = new Set(['pages', 'posts', 'postCategories', 'products', 'productCategories', 'media', 'contactForms', 'appointmentTypes'])
const websiteGlobals = new Set(['siteSettings', 'navigation'])
const mediaFields = ['id', 'sourceId', 'filename', 'mimeType', 'filesize', 'width', 'height', 'alt', 'url', 'thumbnailURL', 'focalX', 'focalY', 'sizes']
const identityFields = ['id', 'sourceId', 'published', '_status']

const pick = (row: Row, fields: readonly string[]): Row => Object.fromEntries(
  [...new Set(fields)].filter((key) => row[key] !== undefined).map((key) => [key, row[key]]),
)

/** A website-only, stable observed revision set, not a database transaction.
 * Two complete reads must agree. No retries, truncation or alternate data.
 * Byte capture/materialization and owner-review eligibility are separate gates.
 */
export async function captureRenderSnapshot(payload: SnapshotPayload, options: SnapshotOptions) {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(options.tenant)
    || !/^[0-9a-f]{40}$/.test(options.sourceSha) || !/^[0-9a-f]{64}$/.test(options.schemaIdentity)
    || !options.locales.length || new Set(options.locales).size !== options.locales.length
    || options.locales.some((locale) => !/^[A-Za-z0-9-]{2,20}$/.test(locale))
    || !options.locales.includes(options.defaultLocale)) throw new Error('Render snapshot identity is incomplete')
  if (Object.keys(options.collections).some((key) => !websiteCollections.has(key))
    || Object.keys(options.globals).some((key) => !websiteGlobals.has(key))
    || !options.collections.pages || !options.globals.navigation || !options.globals.siteSettings) {
    throw new Error('Render snapshot exceeds or omits required website scope')
  }

  const capture = async () => {
    const readRows = async (collection: string, locale: string, depth: number, fields: readonly string[]) => {
      const rows: Row[] = []
      const ids = new Set<string>()
      let page = 1
      let total: number | undefined
      while (true) {
        const result = await payload.find({ collection, locale, draft: false, depth, limit: 100, page, pagination: true, sort: 'id', overrideAccess: true })
        const empty = result.totalDocs === 0 && page === 1 && !result.hasNextPage && result.docs?.length === 0
        if (!Number.isSafeInteger(result.totalDocs) || result.totalDocs < 0
          || !Number.isSafeInteger(result.totalPages) || result.totalPages < (empty ? 0 : 1)
          || !Array.isArray(result.docs) || typeof result.hasNextPage !== 'boolean'
          || (total !== undefined && total !== result.totalDocs)) throw new Error('Render snapshot pagination changed or is incomplete')
        total = result.totalDocs
        for (const row of result.docs) {
          const id = String(row.id ?? '')
          if (!id || ids.has(id)) throw new Error('Render snapshot has duplicate or missing identities')
          ids.add(id)
          rows.push(pick(row, fields))
        }
        if (!result.hasNextPage) {
          if (rows.length !== total || (!empty && page !== result.totalPages) || (empty && result.totalPages > 1)) throw new Error('Render snapshot pagination is incomplete')
          return rows
        }
        if (!result.docs.length || page >= result.totalPages || rows.length >= total) throw new Error('Render snapshot pagination is inconsistent')
        page += 1
      }
    }
    const media = new Map<string, Row>()
    const sanitize = (value: unknown): unknown => {
      if (Array.isArray(value)) return value.map(sanitize)
      if (!value || typeof value !== 'object') return value
      const row = value as Row
      if (row.id !== undefined && typeof row.filename === 'string' && typeof row.mimeType === 'string') {
        const clean = pick(row, mediaFields)
        const key = String(row.id)
        const previous = media.get(key)
        // Locale-specific alt text belongs to the populated relationship. The
        // binary identity must agree independently of the locale being read.
        if (previous && ['filename', 'mimeType', 'filesize', 'width', 'height', 'url'].some((field) => previous[field] !== clean[field])) {
          throw new Error('Conflicting media revisions in render snapshot')
        }
        if (!previous) media.set(key, pick(clean, mediaFields.filter((field) => field !== 'alt')))
        return clean
      }
      return Object.fromEntries(Object.entries(row).map(([key, child]) => [key, sanitize(child)]))
    }
    const documents: Record<string, Record<string, Row[]>> = {}
    const globals: Record<string, Record<string, Row>> = {}
    const seed: { collections: Record<string, Row[]>; globals: Record<string, Row> } = { collections: {}, globals: {} }
    for (const locale of options.locales) {
      documents[locale] = {}
      globals[locale] = {}
      for (const collection of Object.keys(options.collections).sort().filter((key) => key !== 'media')) {
        documents[locale][collection] = (await readRows(collection, locale, 2, [...identityFields, ...options.collections[collection]])).map((row) => sanitize(row) as Row)
      }
      for (const slug of Object.keys(options.globals).sort()) {
        const row = await payload.findGlobal({ slug, locale, draft: false, depth: 2, overrideAccess: true })
        globals[locale][slug] = sanitize(pick(row, options.globals[slug])) as Row
      }
    }
    // Payload's native locale:'all'/depth:0 representation is the input to
    // its own database adapter. Preserve numeric relationship IDs and locale
    // maps instead of converting the site into a parallel content format.
    for (const collection of Object.keys(options.collections).sort()) {
      const rows = await readRows(collection, 'all', 0, [...identityFields, ...options.collections[collection], ...(collection === 'media' ? mediaFields : [])])
      seed.collections[collection] = rows.map((row) => collection === 'media' ? row : sanitize(row) as Row)
    }
    for (const slug of Object.keys(options.globals).sort()) {
      seed.globals[slug] = pick(await payload.findGlobal({ slug, locale: 'all', draft: false, depth: 0, overrideAccess: true }), options.globals[slug])
    }
    // Detach from Payload objects before the second read or later mutations.
    return JSON.parse(JSON.stringify({
      schema: 1, tenant: options.tenant, sourceSha: options.sourceSha,
      schemaIdentity: options.schemaIdentity, locales: options.locales,
      defaultLocale: options.defaultLocale, documents, globals, seed,
      media: [...media.values()].sort((a, b) => String(a.id).localeCompare(String(b.id))),
    })) as Row
  }
  const snapshot = await capture()
  const hash = await hashJson(snapshot)
  if (await hashJson(await capture()) !== hash) throw new Error('Website content changed during snapshot capture')
  return { snapshot, hash }
}
