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
    : await Promise.all([
        getNavigation().catch(() => ({})),
        getSiteSettings().catch(() => ({})),
      ])
  // A freshly provisioned site has no Payload settings yet. Render the page
  // shell without owner chrome so the site can return a valid 200 for GSC.
  if (!settings || Object.keys(settings).length === 0) return <>{children}</>
  return <TenantChrome navigation={navigation} settings={settings}>{children}</TenantChrome>
}
