import type { ReactNode } from 'react'
import type { Metadata } from 'next'
import Script from 'next/script'

import SiteChrome from '@/components/SiteChrome'
import { getSiteSettings, seoFor } from '@/lib/content'
import { runtimeValue } from '@/lib/runtime-env'

import './site.css'

export const dynamic = 'force-dynamic'

export async function generateMetadata(): Promise<Metadata> {
  const settings = await getSiteSettings()
  const seo = seoFor(undefined, settings)
  const googleVerification = runtimeValue('GOOGLE_SITE_VERIFICATION')
  return {
    title: seo.title,
    description: seo.description || undefined,
    verification: googleVerification ? { google: googleVerification } : undefined,
    openGraph: { title: seo.title, description: seo.description || undefined, images: seo.image ? [seo.image] : undefined },
  }
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const gaMeasurementId = runtimeValue('GA_MEASUREMENT_ID')
  return (
    <html lang="en">
      <body>
        {gaMeasurementId ? <>
          <Script async src={`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(gaMeasurementId)}`} />
          <Script id="helloada-ga4">
            {`window.dataLayer = window.dataLayer || []; function gtag(){dataLayer.push(arguments);} gtag('js', new Date()); gtag('config', ${JSON.stringify(gaMeasurementId)});`}
          </Script>
        </> : null}
        <SiteChrome>{children}</SiteChrome>
      </body>
    </html>
  )
}
