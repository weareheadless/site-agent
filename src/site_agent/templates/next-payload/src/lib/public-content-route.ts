import { pathForDocument } from './content-routes'

type PublicCollection = 'pages' | 'posts' | 'products'

const safePublicPath = (value: unknown): string => {
  const route = String(value ?? '').trim()
  if (!route.startsWith('/') || route.startsWith('//') || /[?#\\\u0000-\u001f\u007f]/.test(route)) {
    throw new Error('Payload document has no safe root-relative public route.')
  }
  let decoded = route
  for (let index = 0; index < 8; index += 1) {
    if (decoded.startsWith('//') || decoded.split('/').some(part => part === '.' || part === '..') || decoded.includes('\\')) {
      throw new Error('Payload document route contains path traversal.')
    }
    let next: string
    try {
      next = decodeURIComponent(decoded)
    } catch {
      throw new Error('Payload document route has invalid path encoding.')
    }
    if (next === decoded) return route
    decoded = next
  }
  throw new Error('Payload document route encoding is too deeply nested.')
}

/** Match the existing growth authoring route contract without persisting a derived route. */
export const publicRouteForDocument = (collection: PublicCollection, document: Record<string, unknown>): string => {
  const explicitRoute = String(document.route ?? '').trim()
  const route = explicitRoute
    ? safePublicPath(explicitRoute)
    : safePublicPath(pathForDocument(collection, String(document.slug ?? '')))
  return route === '/' ? '/' : `/${route.replace(/^\/+/, '').replace(/\/+$/, '')}`
}

export const withPublicRoute = <T extends Record<string, unknown>>(collection: PublicCollection, document: T): T & { route: string } => ({
  ...document,
  route: publicRouteForDocument(collection, document),
})
