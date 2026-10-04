export type HelloAdaPublicContentRoutes = {
  postsIndex: string
  postDetail: string
}

export type HelloAdaEditableCollection = 'pages' | 'posts' | 'products'

const normalizeBasePath = (value: string, label: string) => {
  const path = value.trim()
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\') || path.includes('?') || path.includes('#')) {
    throw new Error(`${label} must be an absolute site path without query or fragment components.`)
  }
  const normalized = path.length > 1 ? path.replace(/\/+$/, '') : '/'
  if (normalized === '/' || normalized.split('/').some((segment) => segment === '.' || segment === '..')) {
    throw new Error(`${label} must identify a non-root path without dot segments.`)
  }
  return normalized
}

const normalizeSlug = (value: string) => {
  const slug = value.trim().replace(/^\/+|\/+$/g, '')
  const segments = slug.split('/')
  if (!slug || segments.some((segment) => !segment || segment === '.' || segment === '..' || segment.includes('\\'))) {
    throw new Error('Payload public content requires a safe, non-empty route slug.')
  }
  return segments
}

const encodeSlug = (slug: string) => normalizeSlug(slug).map(encodeURIComponent).join('/')

/** Create deterministic public paths from a tenant's explicitly declared route contract. */
export const createHelloAdaPublicRouteResolver = (routes: HelloAdaPublicContentRoutes) => {
  const postsIndex = normalizeBasePath(routes.postsIndex, 'The articles index route')
  const postDetail = normalizeBasePath(routes.postDetail, 'The article detail route')

  const pathForPost = (slug: string) => `${postDetail}/${encodeSlug(slug)}`

  const pathForDocument = (collection: HelloAdaEditableCollection | string, slug: string) => {
    if (collection === 'posts') return pathForPost(slug)
    if (collection !== 'pages' && collection !== 'products') {
      throw new Error(`Unsupported HelloAda public document collection: ${collection}`)
    }
    const normalized = normalizeSlug(slug)
    if (collection === 'pages' && normalized.length === 1 && (normalized[0] === 'home' || normalized[0] === 'index')) return '/'
    return `/${normalized.map(encodeURIComponent).join('/')}`
  }

  const postSlugForPath = (pathname: string) => {
    if (pathname === postsIndex) return { kind: 'index' as const }
    if (!pathname.startsWith(`${postDetail}/`)) return undefined
    const encodedSlug = pathname.slice(postDetail.length + 1)
    if (!encodedSlug) return undefined
    const segments = encodedSlug.split('/')
    if (segments.some((segment) => !segment)) return undefined
    return { kind: 'detail' as const, slug: segments.map(decodeURIComponent).join('/') }
  }

  return { routes: { postsIndex, postDetail } as const, pathForPost, pathForDocument, postSlugForPath }
}
