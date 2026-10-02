import type { ReactNode } from 'react'
import type { Metadata } from 'next'

import SiteChrome from '@/components/SiteChrome'
import { getSiteSettings, seoFor } from '@/lib/content'

import './site.css'

export const dynamic = 'force-dynamic'

export async function generateMetadata(): Promise<Metadata> {
  const settings = await getSiteSettings()
  const seo = seoFor(undefined, settings)
  return {
    title: seo.title,
    description: seo.description || undefined,
    openGraph: { title: seo.title, description: seo.description || undefined, images: seo.image ? [seo.image] : undefined },
  }
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body><SiteChrome>{children}</SiteChrome></body>
    </html>
  )
}
