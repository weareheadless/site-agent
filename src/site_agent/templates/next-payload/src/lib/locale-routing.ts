export const LOCALE_HEADER = 'x-helloada-locale'
export const LOCALE_COOKIE = 'helloada-locale'

export function resolveRequestLocale(explicit: readonly string[], preference: string | undefined, locales: readonly string[], defaultLocale: string): { ok: true; locale: string } | { ok: false } {
  if (explicit.length > 1) return { ok: false }
  if (explicit.length === 1) return locales.includes(explicit[0]) ? { ok: true, locale: explicit[0] } : { ok: false }
  if (preference !== undefined) return locales.includes(preference) ? { ok: true, locale: preference } : { ok: false }
  return locales.includes(defaultLocale) ? { ok: true, locale: defaultLocale } : { ok: false }
}

export function localeSwitchHref(pathAndSearch: string, locale: string): string {
  const url = new URL(pathAndSearch, 'https://helloada.invalid')
  url.searchParams.set('locale', locale)
  return `${url.pathname}${url.search}`
}
