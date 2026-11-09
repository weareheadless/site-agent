'use client'

import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'
import { useHelloAdaSite } from '../config/provider'

type MailflareSurface = 'inbox' | 'calendar' | 'booking-settings'

export function MailflarePayloadView({ surface = 'inbox' }: { surface?: MailflareSurface }) {
  const { t } = useHelloAdaTranslations()
  const site = useHelloAdaSite()
  const messagesLabel = t('owner.messages')
  const path = surface === 'calendar' ? '/mail/calendar' : surface === 'booking-settings' ? '/mail/settings/bookings' : '/mail/inbox'
  // Mailflare is served by the tenant Worker. On the control plane the live
  // site is an absolute origin, so the frame must not resolve against this app.
  const live = site.routes.liveSite
  const src = /^https?:\/\//.test(live) ? `${new URL(live).origin}${path}` : path
  const title = surface === 'calendar' ? `${messagesLabel} calendar` : surface === 'booking-settings' ? t('owner.bookingSettings') : messagesLabel

  return (
    <main className="helloada-mailflare-view">
      <iframe
        className="helloada-mailflare-frame"
        src={src}
        title={title}
        loading="eager"
        referrerPolicy="same-origin"
      />
    </main>
  )
}
