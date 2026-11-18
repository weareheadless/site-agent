export type HelloAdaSiteConfig = {
  tenantId: string
  siteName: string
  defaultLocale: string
  locales: readonly string[]
  routes: {
    workspaceApi: string
    liveSite: string
    preview: string
    /** Control-plane handoff entry for the tenant admin, when it is remote. */
    manage?: string
    /**
     * Public paths this site's own Next source renders even when its
     * presentation is committed static HTML.
     *
     * A static presentation answers every undeclared path with its 404 page, so
     * a platform page such as the booking form has to be named here instead of
     * being mistaken for a missing static document.
     */
    managedPaths?: readonly string[]
  }
  content: {
    primaryCollections: readonly string[]
    settingsGlobals: readonly string[]
  }
  features: {
    commerce: boolean
    posts: boolean
    social: boolean
    bookings?: boolean
    /** In-preview editing requires the preview document to be same-origin. */
    inlineEditing?: boolean
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
  routes: { workspaceApi: '/api/helloada', liveSite: '/', preview: '/helloada-preview', managedPaths: [] },
  content: { primaryCollections: ['pages', 'posts', 'products', 'media'], settingsGlobals: ['siteSettings', 'navigation'] },
  features: { commerce: false, posts: true, social: false, bookings: false, inlineEditing: true },
}

let activeHelloAdaSite = defaultHelloAdaSite

const route = (value: string, fallback: string) => {
  const normalized = String(value || '').trim()
  if (/^https?:\/\//.test(normalized)) {
    try {
      return new URL(normalized).toString().replace(/\/$/, '')
    } catch {
      return fallback
    }
  }
  if (!normalized.startsWith('/') || normalized.startsWith('//')) return fallback
  return normalized.replace(/\/$/, '') || '/'
}

/**
 * Managed bases are public site paths the app renders itself. They must be
 * absolute, query-free paths; anything else is a configuration error rather
 * than a page that silently 404s.
 */
const managedBases = (value: unknown): string[] => {
  if (value === undefined) return []
  if (!Array.isArray(value)) throw new Error('HelloAda managedPaths must be a list of absolute paths')
  return Array.from(new Set(value.map((item) => {
    const base = typeof item === 'string' ? item.trim() : ''
    if (!base.startsWith('/') || base.startsWith('//') || base.includes('?') || base.includes('#')) {
      throw new Error('HelloAda managedPaths must be absolute site paths')
    }
    return base.length > 1 ? base.replace(/\/+$/, '') : base
  })))
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
      managedPaths: managedBases(input.routes?.managedPaths),
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
