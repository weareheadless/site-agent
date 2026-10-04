import { defineHelloAdaSite, setHelloAdaSite } from '@weareheadless/helloada-payload-admin'

export const helloAdaPublicContentRoutes = {
  postsIndex: '/articles',
  postDetail: '/articles',
} as const

export const helloAdaSite = defineHelloAdaSite({
  tenantId: '__HELLOADA_TENANT_ID__',
  siteName: '__HELLOADA_SITE_NAME__',
  defaultLocale: 'en',
  locales: ['en'],
  routes: { workspaceApi: '/api/helloada', liveSite: '/' },
  content: { primaryCollections: ['pages', 'posts', 'products', 'media'], settingsGlobals: ['siteSettings', 'navigation'] },
  features: { commerce: false, posts: true, social: false },
})

setHelloAdaSite(helloAdaSite)
