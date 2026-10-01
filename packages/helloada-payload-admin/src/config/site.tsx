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

type HelloAdaSiteInput = Omit<Partial<HelloAdaSiteConfig>, 'routes'> &
  Pick<HelloAdaSiteConfig, 'tenantId' | 'siteName'> & {
    routes?: Partial<HelloAdaSiteConfig['routes']>
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

export const previewRouteForTenant = (tenantId: string) => {
  const slug = String(tenantId || 'site')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'site'
  return `/${slug}-preview`
}

export const defineHelloAdaSite = (input: HelloAdaSiteInput): HelloAdaSiteConfig => {
  const locales = Array.from(new Set((input.locales || [input.defaultLocale || 'en']).map((value) => String(value).trim()).filter(Boolean)))
  const defaultLocale = String(input.defaultLocale || locales[0] || 'en').trim()
  if (!locales.includes(defaultLocale)) throw new Error('HelloAda defaultLocale must be present in locales')
  const tenantId = String(input.tenantId).trim()
  const tenantPreviewRoute = previewRouteForTenant(tenantId)
  const config: HelloAdaSiteConfig = {
    ...defaultHelloAdaSite,
    ...input,
    tenantId,
    siteName: String(input.siteName).trim(),
    defaultLocale,
    locales,
    routes: {
      ...defaultHelloAdaSite.routes,
      ...input.routes,
      workspaceApi: route(input.routes?.workspaceApi || defaultHelloAdaSite.routes.workspaceApi, defaultHelloAdaSite.routes.workspaceApi),
      liveSite: route(input.routes?.liveSite || defaultHelloAdaSite.routes.liveSite, defaultHelloAdaSite.routes.liveSite),
      preview: route(input.routes?.preview || tenantPreviewRoute, tenantPreviewRoute),
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
