import { matchesCategoryCriteria, type CatalogCategoryCriteria } from '../schema/catalog.ts'

/**
 * Category membership is a saved search, never a curated list: the shared
 * predicate decides which products belong to a category.
 *
 * The query below narrows candidates in SQL for the fields that are not
 * localized. `availability` lives on the localized products row and is compared
 * case-insensitively, so it stays in the predicate instead of the query. The
 * predicate remains the final authority for every returned product.
 */
export type CategoryCriteria = CatalogCategoryCriteria

type Document = Record<string, unknown>
type PayloadLike = any

export const categoryCriteriaWhere = (criteria: CategoryCriteria) => {
  const and: Document[] = [
    { published: { equals: true } },
    { _status: { equals: 'published' } },
  ]
  const city = typeof criteria.city === 'string' ? criteria.city.trim() : ''
  if (city) and.push({ 'location.city': { equals: city } })
  const region = typeof criteria.region === 'string' ? criteria.region.trim() : ''
  if (region) and.push({ 'location.region': { equals: region } })
  if (typeof criteria.priceMinMinor === 'number') {
    and.push({ priceMinor: { greater_than_equal: criteria.priceMinMinor } })
  }
  if (typeof criteria.priceMaxMinor === 'number') {
    // The ceiling is exclusive, matching every rendered source grid.
    and.push({ priceMinor: { less_than: criteria.priceMaxMinor } })
  }
  return { and }
}

export type CategoryMembers = {
  total: number
  page: number
  pages: number
  documents: Document[]
}

/**
 * Read one page of a category's members.
 *
 * Ordering is alphabetical by the localized product slug: that reproduces all
 * twelve source grids exactly, and every source slug is lowercase ASCII, so a
 * plain database sort matches the source order without client-side sorting.
 */
export const readCategoryMembers = async (
  payload: PayloadLike,
  options: { criteria: CategoryCriteria; locale: string; page?: number; limit?: number },
): Promise<CategoryMembers> => {
  const limit = Math.max(1, Math.min(Math.trunc(options.limit ?? 12), 100))
  const requested = Math.trunc(options.page ?? 1)
  const page = Number.isFinite(requested) && requested > 0 ? requested : 1
  const result = await payload.find({
    collection: 'products',
    where: categoryCriteriaWhere(options.criteria),
    locale: options.locale,
    draft: false,
    depth: 1,
    sort: 'slug',
    pagination: false,
    limit: 1000,
    overrideAccess: true,
  })
  const matched = (result.docs as Document[]).filter((product) => matchesCategoryCriteria(product, options.criteria))
  const pages = Math.max(1, Math.ceil(matched.length / limit))
  const start = (page - 1) * limit
  return {
    total: matched.length,
    page,
    pages,
    documents: matched.slice(start, start + limit),
  }
}

/**
 * The locale-specific route of a category. One category document keeps one
 * localized slug per locale, so a category URL never depends on another
 * locale's slug.
 */
export const categoryRoute = (document: Document, basePath: string) => {
  const base = String(basePath || '').trim().replace(/\/+$/, '')
  if (!base.startsWith('/')) throw new Error('A category route base must be an absolute site path.')
  const slug = String(document.slug || '').trim().replace(/^\/+|\/+$/g, '')
  if (!slug) throw new Error('A published category must have a slug in every published locale.')
  return `${base}/${slug}/`
}

export { matchesCategoryCriteria }
export type { CatalogCategoryCriteria }
