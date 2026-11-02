import { cookies, headers } from 'next/headers'
import { helloAdaSite } from '@/helloada.config'
import { LOCALE_COOKIE, LOCALE_HEADER, resolveRequestLocale } from './locale-routing'
export { LOCALE_COOKIE, LOCALE_HEADER } from './locale-routing'

export async function requestLocale(): Promise<string> {
  const requestHeaders = await headers()
  const fromMiddleware = requestHeaders.get(LOCALE_HEADER)
  if (fromMiddleware && helloAdaSite.locales.includes(fromMiddleware)) return fromMiddleware
  const cookieStore = await cookies()
  const resolved = resolveRequestLocale([], cookieStore.get(LOCALE_COOKIE)?.value, helloAdaSite.locales, helloAdaSite.defaultLocale)
  if (!resolved.ok) throw new Error('The saved website locale is not enabled.')
  return resolved.locale
}
