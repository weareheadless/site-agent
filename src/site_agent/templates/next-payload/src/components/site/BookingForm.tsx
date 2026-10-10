'use client'

import Script from 'next/script'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'

type Slot = { startsAt: string; endsAt: string }
type BookingCopy = {
  name: string; email: string; notes: string; date: string; time: string; submit: string; sending: string;
  noSlots: string; unavailable: string; success: string; security: string; consent: string;
}

const copyByLanguage: Record<string, BookingCopy> = {
  en: { name: 'Your name', email: 'Email address', notes: 'Anything we should know? (optional)', date: 'Choose a date', time: 'Available times', submit: 'Book appointment', sending: 'Confirming…', noSlots: 'No times are available on this date.', unavailable: 'Online booking is not available right now.', success: 'Your appointment is booked. The business will contact you if anything changes.', security: 'Complete the security check.', consent: 'I agree that the business may use these details to manage my appointment.' },
  es: { name: 'Tu nombre', email: 'Correo electrónico', notes: '¿Algo más que debamos saber? (opcional)', date: 'Elige una fecha', time: 'Horarios disponibles', submit: 'Reservar cita', sending: 'Confirmando…', noSlots: 'No hay horarios disponibles en esta fecha.', unavailable: 'Las reservaciones en línea no están disponibles por ahora.', success: 'Tu cita quedó reservada. El negocio te contactará si hay algún cambio.', security: 'Completa la verificación de seguridad.', consent: 'Acepto que el negocio use estos datos para gestionar mi cita.' },
  fr: { name: 'Votre nom', email: 'Adresse e-mail', notes: 'Une précision à nous communiquer ? (facultatif)', date: 'Choisir une date', time: 'Horaires disponibles', submit: 'Réserver', sending: 'Confirmation…', noSlots: 'Aucun horaire disponible à cette date.', unavailable: 'La réservation en ligne est indisponible pour le moment.', success: 'Votre rendez-vous est réservé. L’entreprise vous contactera en cas de changement.', security: 'Effectuez la vérification de sécurité.', consent: 'J’accepte que l’entreprise utilise ces informations pour gérer mon rendez-vous.' },
}

declare global {
  interface Window {
    turnstile?: { render: (element: HTMLElement, options: Record<string, unknown>) => string; reset: (widgetId?: string) => void }
  }
}

const dateInZone = (instant: Date, timeZone: string) => {
  const parts = new Intl.DateTimeFormat('en', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(instant)
  const value = Object.fromEntries(parts.map(({ type, value }) => [type, value]))
  return `${value.year}-${value.month}-${value.day}`
}

export default function BookingForm({ appointmentType, bookingUsername, siteKey, locale = 'en' }: {
  appointmentType: { slug: string; name: string; description?: string }
  bookingUsername: string
  siteKey: string
  locale?: string
}) {
  const copy = copyByLanguage[locale] || copyByLanguage.en
  const [timeZone, setTimeZone] = useState('')
  const windowDays = 60
  const [mailflareEvent, setMailflareEvent] = useState<{ name: string; description: string } | null>(null)
  const [today, setToday] = useState('')
  const [date, setDate] = useState('')
  const [availability, setAvailability] = useState<{ appointmentType: string; date: string; timeZone: string; slots: Slot[] } | null>(null)
  const slots = availability?.appointmentType === appointmentType.slug && availability.date === date && availability.timeZone === timeZone
    ? availability.slots
    : []
  const [selected, setSelected] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [notes, setNotes] = useState('')
  const [consent, setConsent] = useState(false)
  const [turnstileToken, setTurnstileToken] = useState('')
  const [state, setState] = useState<'loading' | 'ready' | 'sending' | 'success' | 'error'>('loading')
  const successMessage = copy.success
  const [error, setError] = useState('')
  const turnstileRef = useRef<HTMLDivElement>(null)
  const widgetIdRef = useRef<string | undefined>(undefined)
  const requestRef = useRef<{ fingerprint: string; requestId: string } | undefined>(undefined)
  const maxDate = useMemo(() => {
    if (!timeZone || !today) return ''
    const value = new Date(`${today}T12:00:00.000Z`)
    value.setUTCDate(value.getUTCDate() + windowDays)
    return value.toISOString().slice(0, 10)
  }, [today, timeZone, windowDays])

  useEffect(() => {
    let cancelled = false
    void fetch(`/mail/api/public/booking?username=${encodeURIComponent(bookingUsername)}`, { cache: 'no-store' })
      .then(async (response) => {
        const body = await response.json() as { events?: Array<{ slug?: string; name?: string; description?: string; timeZone?: string }>; error?: string }
        if (!response.ok) throw new Error(body.error || copy.unavailable)
        if (cancelled) return
        const configuredEvent = body.events?.find((event) => event.slug === appointmentType.slug)
        if (!configuredEvent?.timeZone) { setState('error'); setError(copy.unavailable); return }
        const businessZone = configuredEvent.timeZone
        const today = dateInZone(new Date(), businessZone)
        setMailflareEvent({ name: String(configuredEvent.name || ''), description: String(configuredEvent.description || '') })
        setTimeZone(businessZone); setToday(today); setDate(today); setState('ready')
      })
      .catch((cause) => { if (!cancelled) { setState('error'); setError(cause instanceof Error ? cause.message : copy.unavailable) } })
    return () => { cancelled = true }
  }, [appointmentType.slug, bookingUsername, copy.unavailable])

  useEffect(() => {
    if (!date || !timeZone) return
    let cancelled = false
    void fetch(`/mail/api/public/booking/${encodeURIComponent(appointmentType.slug)}?username=${encodeURIComponent(bookingUsername)}`, { cache: 'no-store' })
      .then(async (response) => {
        const body = await response.json() as { event?: { timeZone?: string }; slots?: Array<Slot & { localDate?: string }>; error?: string }
        if (!response.ok) throw new Error(body.error || copy.unavailable)
        if (cancelled) return
        if (body.event?.timeZone !== timeZone) throw new Error(copy.unavailable)
        const daySlots = (body.slots || []).filter((slot) => slot.localDate === date).map(({ startsAt, endsAt }) => ({ startsAt, endsAt }))
        setAvailability({ appointmentType: appointmentType.slug, date, timeZone, slots: daySlots })
      })
      .catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : copy.unavailable) })
    return () => { cancelled = true }
  }, [appointmentType.slug, bookingUsername, copy.unavailable, date, timeZone])


  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (state === 'sending' || !selected) return
    if (!turnstileToken) { setError(copy.security); setState('error'); return }
    setState('sending'); setError('')
    try {
      const bookingPayload = { name, email, startsAt: selected, notes: notes.trim(), consent }
      const fingerprint = JSON.stringify(bookingPayload)
      const requestId = requestRef.current?.fingerprint === fingerprint
        ? requestRef.current.requestId
        : globalThis.crypto.randomUUID()
      requestRef.current = { fingerprint, requestId }
      const website = String(new FormData(event.currentTarget).get('website') || '')
      const response = await fetch(`/mail/api/public/booking/${encodeURIComponent(appointmentType.slug)}?username=${encodeURIComponent(bookingUsername)}`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ...bookingPayload, requestId, turnstileToken, website }),
      })
      const body = await response.json() as { booked?: boolean; error?: string }
      if (!response.ok || body.booked !== true) throw new Error(body.error || copy.unavailable)
      requestRef.current = undefined
      setState('success'); setTurnstileToken('')
      window.turnstile?.reset(widgetIdRef.current)
    } catch (cause) {
      setState('error'); setError(cause instanceof Error ? cause.message : copy.unavailable)
      setTurnstileToken(''); window.turnstile?.reset(widgetIdRef.current)
    }
  }

  return <div className="helloada-booking">
    <div className="helloada-booking-heading"><h3>{mailflareEvent?.name || appointmentType.name}</h3>{(mailflareEvent?.description || appointmentType.description) ? <p>{mailflareEvent?.description || appointmentType.description}</p> : null}</div>
    {state === 'success' ? <p className="helloada-booking-success" role="status">{successMessage}</p> : <form onSubmit={submit}>
      <label><span>{copy.name}</span><input autoComplete="name" maxLength={160} required value={name} onChange={(event) => setName(event.target.value)} /></label>
      <label><span>{copy.email}</span><input type="email" autoComplete="email" maxLength={254} required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      <label><span>{copy.notes}</span><textarea maxLength={2000} rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
      <label className="helloada-booking-consent"><input type="checkbox" required checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>{copy.consent}</span></label>
      <label><span>{copy.date}</span><input type="date" min={today || undefined} max={maxDate || undefined} value={date} onChange={(event) => { setDate(event.target.value); setSelected('') }} disabled={!timeZone || state === 'sending'} /></label>
      <fieldset><legend>{copy.time} <small>({timeZone || '…'})</small></legend>
        {slots.length ? <div className="helloada-booking-slots">{slots.map((slot) => <button key={slot.startsAt} type="button" className={selected === slot.startsAt ? 'is-selected' : ''} aria-pressed={selected === slot.startsAt} onClick={() => setSelected(slot.startsAt)}>
          {new Intl.DateTimeFormat(locale, { timeZone, hour: 'numeric', minute: '2-digit' }).format(new Date(slot.startsAt))}
        </button>)}</div> : <p className="helloada-booking-empty">{state === 'loading' ? '…' : copy.noSlots}</p>}
      </fieldset>
      <label className="helloada-booking-honeypot" aria-hidden="true" tabIndex={-1}><span>Website</span><input name="website" autoComplete="off" tabIndex={-1} /></label>
      <Script id={`helloada-booking-turnstile-${appointmentType.slug}`} src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit" strategy="afterInteractive" onLoad={() => {
        if (turnstileRef.current && window.turnstile && !widgetIdRef.current) widgetIdRef.current = window.turnstile.render(turnstileRef.current, {
          sitekey: siteKey, theme: 'auto', callback: (token: string) => setTurnstileToken(token), 'expired-callback': () => setTurnstileToken(''),
        })
      }} />
      <div className="helloada-turnstile" ref={turnstileRef} />
      {error ? <p className="helloada-booking-error" role="alert">{error}</p> : null}
      <button type="submit" disabled={state === 'loading' || state === 'sending' || !selected || !turnstileToken}>{state === 'sending' ? copy.sending : copy.submit}</button>
    </form>}
  </div>
}
