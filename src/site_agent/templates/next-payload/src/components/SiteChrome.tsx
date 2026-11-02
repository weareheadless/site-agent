import type { ReactNode } from 'react'

import { getNavigation, getSiteSettings } from '@/lib/content'
import TenantChrome from '@/components/site/TenantChrome'
import { headers } from 'next/headers'
import { helloAdaSite } from '@/helloada.config'
import { LOCALE_HEADER } from '@/lib/request-locale'

export default async function SiteChrome({
  children,
  navigation: candidateNavigation,
  settings: candidateSettings,
}: {
  children: ReactNode
  navigation?: Record<string, unknown>
  settings?: Record<string, unknown>
}) {
  const requestHeaders = await headers()
  const locale = requestHeaders.get(LOCALE_HEADER) || helloAdaSite.defaultLocale
  const currentUrl = requestHeaders.get('x-helloada-current-url') || '/'
  const [navigation, settings] = candidateNavigation && candidateSettings
    ? [candidateNavigation, candidateSettings]
    : await Promise.all([
        getNavigation(locale).catch(() => ({})),
        getSiteSettings(locale).catch(() => ({})),
      ])
  // A freshly provisioned site has no Payload settings yet. Render the page
  // shell without owner chrome so the site can return a valid 200 for GSC.
  if (!settings || Object.keys(settings).length === 0) return <>{children}</>
  const languageSwitch = helloAdaSite.locales.length > 1 ? <nav aria-label="Language"><ul>{helloAdaSite.locales.map((code) => {
    const url = new URL(currentUrl, 'https://helloada.invalid')
    url.searchParams.set('locale', code)
    return <li key={code}><a href={`${url.pathname}${url.search}`} lang={code} aria-current={code === locale ? 'page' : undefined}>{code}</a></li>
  })}</ul></nav> : null
  return <TenantChrome navigation={navigation} settings={settings}>{languageSwitch}{children}</TenantChrome>
}
