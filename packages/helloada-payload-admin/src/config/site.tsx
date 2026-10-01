export type HelloAdaSiteConfig = {
  tenantId: string
  siteName: string
  defaultLocale: string
  locales: readonly string[]
  routes: {
    workspaceApi: string
    liveSite: string
    preview: string
  }
  content: {
    primaryCollections: readonly string[]
    settingsGlobals: readonly string[]
  }
  features: {
    commerce: boolean
    posts: boolean
    social: boolean
  }
}

const defaultHelloAdaSite: HelloAdaSiteConfig = {
  tenantId: 'local-site',
  siteName: 'Your website',
  defaultLocale: 'en',
  locales: ['en'],
  routes: { workspaceApi: '/api/helloada', liveSite: '/', preview: '/helloada-preview' },
  content: { primaryCollections: ['pages', 'posts', 'products', 'media'], settingsGlobals: ['siteSettings', 'navigation'] },
  features: { commerce: false, posts: true, social: false },
}

let activeHelloAdaSite = defaultHelloAdaSite

const route = (value: string, fallback: string) => {
  const normalized = String(value || '').trim()
  if (!normalized.startsWith('/') || normalized.startsWith('//')) return fallback
  return normalized.replace(/\/$/, '') || '/'
}

export const defineHelloAdaSite = (input: Partial<HelloAdaSiteConfig> & Pick<HelloAdaSiteConfig, 'tenantId' | 'siteName'>): HelloAdaSiteConfig => {
  const locales = Array.from(new Set((input.locales || [input.defaultLocale || 'en']).map((value) => String(value).trim()).filter(Boolean)))
  const defaultLocale = String(input.defaultLocale || locales[0] || 'en').trim()
  if (!locales.includes(defaultLocale)) throw new Error('HelloAda defaultLocale must be present in locales')
  const config: HelloAdaSiteConfig = {
    ...defaultHelloAdaSite,
    ...input,
    tenantId: String(input.tenantId).trim(),
    siteName: String(input.siteName).trim(),
    defaultLocale,
    locales,
    routes: {
      ...defaultHelloAdaSite.routes,
      ...input.routes,
      workspaceApi: route(input.routes?.workspaceApi || defaultHelloAdaSite.routes.workspaceApi, defaultHelloAdaSite.routes.workspaceApi),
      liveSite: route(input.routes?.liveSite || defaultHelloAdaSite.routes.liveSite, defaultHelloAdaSite.routes.liveSite),
      preview: route(input.routes?.preview || defaultHelloAdaSite.routes.preview, defaultHelloAdaSite.routes.preview),
    },
    content: { ...defaultHelloAdaSite.content, ...input.content },
    features: { ...defaultHelloAdaSite.features, ...input.features },
  }
  if (!config.tenantId || !config.siteName) throw new Error('HelloAda tenantId and siteName are required')
  activeHelloAdaSite = config
  return config
}

export const getHelloAdaSite = () => activeHelloAdaSite

export const setHelloAdaSite = (config: HelloAdaSiteConfig) => {
  activeHelloAdaSite = config
}

export const helloAdaPath = (input: string) => {
  const base = activeHelloAdaSite.routes.workspaceApi
  if (!input.startsWith('/api/helloada')) return input
  const suffix = input.slice('/api/helloada'.length)
  return `${base}${suffix}`
}
