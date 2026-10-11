'use client'

import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'

type MailflareSurface = 'inbox' | 'calendar'

export function MailflarePayloadView({ surface = 'inbox' }: { surface?: MailflareSurface }) {
  const { t } = useHelloAdaTranslations()
  const messagesLabel = t('owner.messages')
  const src = surface === 'calendar' ? '/mail/calendar' : '/mail/inbox'
  const title = surface === 'calendar' ? `${messagesLabel} calendar` : messagesLabel

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
