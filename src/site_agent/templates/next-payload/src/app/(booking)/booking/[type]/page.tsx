import { notFound } from 'next/navigation'

import BookingForm from '@/components/site/BookingForm'
import { helloAdaSite } from '@/helloada.config'
import { runtimeValue } from '@/lib/runtime-env'

import FrameHeight from './frame-height'

export const dynamic = 'force-dynamic'

type Props = {
  params: Promise<{ type: string }>
  searchParams: Promise<Record<string, string | string[] | undefined>>
}

const one = (value: string | string[] | undefined) => Array.isArray(value) ? value[0] : value

/**
 * A tenant page may hand the booking frame its own stylesheet so the widget
 * uses that site's typography and palette. It can only name a path on this
 * origin: the booking frame never loads another site's CSS.
 */
const ownStylesheet = (value: string | undefined) => {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return ''
  try {
    const url = new URL(value, 'https://booking.invalid')
    return url.origin === 'https://booking.invalid' ? `${url.pathname}${url.search}` : ''
  } catch {
    return ''
  }
}

export default async function PublicBookingPage({ params, searchParams }: Props) {
  const { type } = await params
  if (!/^ha_booking_[a-f0-9]{32}$/.test(type) || !helloAdaSite.features.bookings) notFound()
  const siteKey = runtimeValue('HELLOADA_TURNSTILE_SITE_KEY')
  if (!siteKey) throw new Error('The booking security check is not configured for this website.')
  const query = await searchParams
  const requestedLocale = one(query.locale)
  const locales = helloAdaSite.locales as readonly string[]
  const locale = requestedLocale && locales.includes(requestedLocale)
    ? requestedLocale
    : helloAdaSite.defaultLocale
  const stylesheet = ownStylesheet(one(query.stylesheet))
  return <>
    {stylesheet ? <link rel="stylesheet" href={stylesheet} /> : null}
    <BookingForm bookingTypeId={type} label="" siteKey={siteKey} locale={locale} />
    <FrameHeight />
  </>
}
