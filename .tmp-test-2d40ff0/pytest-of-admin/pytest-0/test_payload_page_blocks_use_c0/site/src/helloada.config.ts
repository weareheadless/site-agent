import { defineHelloAdaSite, setHelloAdaSite } from '@weareheadless/helloada-payload-admin'

export const helloAdaSite = defineHelloAdaSite({
  tenantId: "north-star-studio",
  siteName: "North Star Studio",
  defaultLocale: 'en',
  locales: ['en'],
  routes: { workspaceApi: '/api/helloada', liveSite: '/' },
  content: { primaryCollections: ['pages', 'posts', 'products', 'media'], settingsGlobals: ['siteSettings', 'navigation'] },
  features: { commerce: false, posts: true, social: false },
})

setHelloAdaSite(helloAdaSite)
