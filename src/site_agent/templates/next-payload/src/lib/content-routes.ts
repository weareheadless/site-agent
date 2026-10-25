import { createHelloAdaPublicRouteResolver } from '@weareheadless/helloada-payload-core/routes'
import { helloAdaPublicContentRoutes } from '../helloada.config'

const resolver = createHelloAdaPublicRouteResolver(helloAdaPublicContentRoutes)

export const contentRoutes = resolver.routes
export const pathForPost = resolver.pathForPost
export const pathForDocument = resolver.pathForDocument
export const postSlugForPath = resolver.postSlugForPath
export const articleIndexPath = () => contentRoutes.postsIndex
export const articleDetailPath = () => contentRoutes.postDetail
