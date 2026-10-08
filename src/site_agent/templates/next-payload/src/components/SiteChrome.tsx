import type { ReactNode } from 'react'

import { getNavigation, getSiteSettings } from '@/lib/content'
import TenantChrome from '@/components/site/TenantChrome'

export default async function SiteChrome({
  children,
  navigation: candidateNavigation,
  settings: candidateSettings,
}: {
  children: ReactNode
  navigation?: Record<string, unknown>
  settings?: Record<string, unknown>
}) {
  const [navigation, settings] = candidateNavigation && candidateSettings
    ? [candidateNavigation, candidateSettings]
    : await Promise.all([getNavigation(), getSiteSettings()])
  return <TenantChrome navigation={navigation} settings={settings}>{children}</TenantChrome>
}
