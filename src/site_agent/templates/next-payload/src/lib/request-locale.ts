import { cookies, headers } from 'next/headers'
import { helloAdaSite } from '@/helloada.config'

export const LOCALE_HEADER = 'x-helloada-locale'
export const LOCALE_COOKIE = 'helloada-locale'

export function resolveRequestLocale(
  explicit: readonly string[],
  preference: string | undefined,
  locales: readonly string[],
  defaultLocale: string,
): { ok: true; locale: string } | { ok: false } {
  if (explicit.length > 1) return { ok: false }
  if (explicit.length === 1) return locales.includes(explicit[0]) ? { ok: true, locale: explicit[0] } : { ok: false }
  if (preference !== undefined) return locales.includes(preference) ? { ok: true, locale: preference } : { ok: false }
  return locales.includes(defaultLocale) ? { ok: true, locale: defaultLocale } : { ok: false }
}

export async function requestLocale(): Promise<string> {
  const requestHeaders = await headers()
  const fromMiddleware = requestHeaders.get(LOCALE_HEADER)
  if (fromMiddleware) return fromMiddleware
  const cookieStore = await cookies()
  const resolved = resolveRequestLocale([], cookieStore.get(LOCALE_COOKIE)?.value, helloAdaSite.locales, helloAdaSite.defaultLocale)
  if (!resolved.ok) throw new Error('The saved website locale is not enabled.')
  return resolved.locale
}
