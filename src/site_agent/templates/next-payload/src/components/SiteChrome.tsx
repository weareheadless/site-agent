import type { ReactNode } from 'react'

import { getNavigation, getSiteSettings } from '@/lib/content'
import TenantChrome from '@/components/site/TenantChrome'

export default async function SiteChrome({ children }: { children: ReactNode }) {
  const [navigation, settings] = await Promise.all([getNavigation(), getSiteSettings()])
  return <TenantChrome navigation={navigation} settings={settings}>{children}</TenantChrome>
}
