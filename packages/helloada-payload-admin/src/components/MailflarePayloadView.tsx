'use client'

import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'

type MailflareSurface = 'inbox' | 'calendar' | 'booking-settings'

export function MailflarePayloadView({ surface = 'inbox' }: { surface?: MailflareSurface }) {
  const { t } = useHelloAdaTranslations()
  const messagesLabel = t('owner.messages')
  const src = surface === 'calendar' ? '/mail/calendar' : surface === 'booking-settings' ? '/mail/settings/bookings' : '/mail/inbox'
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
