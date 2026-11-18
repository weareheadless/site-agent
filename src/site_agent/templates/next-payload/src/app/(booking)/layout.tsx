import type { ReactNode } from 'react'

import { helloAdaSite } from '@/helloada.config'

import './booking.css'

/**
 * The public booking surface is its own document.
 *
 * A tenant that presents committed static pages has no React page tree to
 * render the shared booking component into, so the component is served as a
 * same-origin page that the static page embeds. It must not inherit the site
 * chrome: its frame is a single appointment, not a page of the website.
 */
export const metadata = {
  title: `Reservar cita — ${helloAdaSite.siteName}`,
  robots: { index: false, follow: false },
}

export default function PublicBookingLayout({ children }: { children: ReactNode }) {
  return (
    <html lang={helloAdaSite.defaultLocale}>
      <body className="helloada-booking-frame">{children}</body>
    </html>
  )
}
