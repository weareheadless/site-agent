import { createHelloAdaPublicRouteResolver } from '@weareheadless/helloada-payload-core/routes'
import { helloAdaPublicContentRoutes } from '../helloada.config'
import presentation from '../generated/helloada-presentation.json'

const resolver = createHelloAdaPublicRouteResolver(helloAdaPublicContentRoutes)

/**
 * Routes rendered by committed Next source instead of a Payload document.
 * The release generator writes this inventory from the app tree, so the owner
 * workspace lists every real page whether its HTML comes from Payload or from
 * committed components.
 */
export const presentationRoutes = (): string[] => {
  const declared = (presentation as { routes?: unknown }).routes
  if (!Array.isArray(declared)) return []
  return declared.flatMap((entry) => {
    const value = typeof entry === 'string'
      ? entry
      : entry && typeof entry === 'object' && typeof (entry as { path?: unknown }).path === 'string'
        ? (entry as { path: string }).path
        : ''
    if (!value.startsWith('/') || value.startsWith('//')) return []
    const path = `/${value.split('/').filter(Boolean).join('/')}`
    return [path === '/' ? '/' : path]
  })
}

export const contentRoutes = resolver.routes
export const pathForPost = resolver.pathForPost
export const pathForDocument = resolver.pathForDocument
export const postSlugForPath = resolver.postSlugForPath
export const articleIndexPath = () => contentRoutes.postsIndex
export const articleDetailPath = () => contentRoutes.postDetail
