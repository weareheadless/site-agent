'use client'

import Script from 'next/script'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'

type Slot = { startsAt: string; endsAt: string }
type BookingCopy = {
  name: string; email: string; notes: string; date: string; time: string; submit: string; sending: string;
  noSlots: string; unavailable: string; success: string; confirmationSent: string; security: string; consent: string;
}

const copyByLanguage: Record<string, BookingCopy> = {
  en: { name: 'Your name', email: 'Email address', notes: 'Anything we should know? (optional)', date: 'Choose a date', time: 'Available times', submit: 'Book appointment', sending: 'Confirming…', noSlots: 'No times are available on this date.', unavailable: 'Online booking is not available right now.', success: 'Your appointment is booked. The business will contact you if anything changes.', confirmationSent: 'Your appointment is booked and a confirmation email has been sent.', security: 'Complete the security check.', consent: 'I agree that the business may use these details to manage my appointment.' },
  es: { name: 'Tu nombre', email: 'Correo electrónico', notes: '¿Algo más que debamos saber? (opcional)', date: 'Elige una fecha', time: 'Horarios disponibles', submit: 'Reservar cita', sending: 'Confirmando…', noSlots: 'No hay horarios disponibles en esta fecha.', unavailable: 'Las reservaciones en línea no están disponibles por ahora.', success: 'Tu cita quedó reservada. El negocio te contactará si hay algún cambio.', confirmationSent: 'Tu cita quedó reservada y se envió un correo de confirmación.', security: 'Completa la verificación de seguridad.', consent: 'Acepto que el negocio use estos datos para gestionar tu cita.' },
  fr: { name: 'Votre nom', email: 'Adresse e-mail', notes: 'Une précision à nous communiquer ? (facultatif)', date: 'Choisir une date', time: 'Horaires disponibles', submit: 'Réserver', sending: 'Confirmation…', noSlots: 'Aucun horaire disponible à cette date.', unavailable: 'La réservation en ligne est indisponible pour le moment.', success: 'Votre rendez-vous est réservé. L’entreprise vous contactera en cas de changement.', confirmationSent: 'Votre rendez-vous est réservé et un e-mail de confirmation a été envoyé.', security: 'Effectuez la vérification de sécurité.', consent: 'J’accepte que l’entreprise utilise ces informations pour gérer mon rendez-vous.' },
}

declare global {
  interface Window {
    turnstile?: { render: (element: HTMLElement, options: Record<string, unknown>) => string; reset: (widgetId?: string) => void }
  }
}

const dateInZone = (instant: Date, timeZone: string) => {
  const parts = new Intl.DateTimeFormat('en', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(instant)
  const value = Object.fromEntries(parts.map(({ type, value }) => [type, value]))
  return value.year + '-' + value.month + '-' + value.day
}

export default function BookingForm({ bookingTypeId, label, siteKey, locale = 'en' }: {
  bookingTypeId: string
  label: string
  siteKey: string
  locale?: string
}) {
  const copy = copyByLanguage[locale] || copyByLanguage.en
  const [timeZone, setTimeZone] = useState('')
  const [windowDays, setWindowDays] = useState(60)
  const [type, setType] = useState<{ name: string; description: string; durationMinutes: number } | null>(null)
  const [today, setToday] = useState('')
  const [date, setDate] = useState('')
  const [availability, setAvailability] = useState<{ typeId: string; date: string; slots: Slot[] } | null>(null)
  const slots = availability?.typeId === bookingTypeId && availability.date === date ? availability.slots : []
  const [selected, setSelected] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [notes, setNotes] = useState('')
  const [consent, setConsent] = useState(false)
  const [turnstileToken, setTurnstileToken] = useState('')
  const [state, setState] = useState<'loading' | 'ready' | 'sending' | 'success' | 'error'>('loading')
  const [error, setError] = useState('')
  const [confirmationSent, setConfirmationSent] = useState(false)
  const turnstileRef = useRef<HTMLDivElement>(null)
  const widgetIdRef = useRef<string | undefined>(undefined)
  const requestRef = useRef<{ fingerprint: string; requestId: string } | undefined>(undefined)
  const maxDate = useMemo(() => {
    if (!today) return ''
    const value = new Date(today + 'T12:00:00.000Z')
    value.setUTCDate(value.getUTCDate() + windowDays - 1)
    return value.toISOString().slice(0, 10)
  }, [today, windowDays])

  const endpoint = '/mail/api/public/booking/' + encodeURIComponent(bookingTypeId)

  useEffect(() => {
    let cancelled = false
    void fetch(endpoint, { cache: 'no-store' })
      .then(async (response) => {
        const body = await response.json() as {
          event?: { id?: string; name?: string; description?: string; durationMinutes?: number; timeZone?: string; bookingWindowDays?: number }
          error?: string
        }
        if (!response.ok || !body.event?.timeZone) throw new Error(body.error || copy.unavailable)
        if (cancelled) return
        const event = body.event
        const zone = event.timeZone
        setType({ name: String(event.name || label), description: String(event.description || ''), durationMinutes: Number(event.durationMinutes) })
        setWindowDays(Number(event.bookingWindowDays))
        setTimeZone(zone)
        const currentDate = dateInZone(new Date(), zone)
        setToday(currentDate)
        setDate(currentDate)
        setState('ready')
      })
      .catch((cause) => { if (!cancelled) { setState('error'); setError(cause instanceof Error ? cause.message : copy.unavailable) } })
    return () => { cancelled = true }
  }, [copy.unavailable, endpoint, label])

  useEffect(() => {
    if (!date || !timeZone) return
    let cancelled = false
    void fetch(endpoint + '?date=' + encodeURIComponent(date), { cache: 'no-store' })
      .then(async (response) => {
        const body = await response.json() as { event?: { timeZone?: string }; slots?: Array<Slot>; error?: string }
        if (!response.ok || body.event?.timeZone !== timeZone) throw new Error(body.error || copy.unavailable)
        if (cancelled) return
        setAvailability({ typeId: bookingTypeId, date, slots: body.slots || [] })
        setError('')
      })
      .catch((cause) => { if (!cancelled) { setAvailability({ typeId: bookingTypeId, date, slots: [] }); setError(cause instanceof Error ? cause.message : copy.unavailable) } })
    return () => { cancelled = true }
  }, [bookingTypeId, copy.unavailable, date, endpoint, timeZone])

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
      const response = await fetch(endpoint, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ...bookingPayload, requestId, turnstileToken, website }),
      })
      const body = await response.json() as { booked?: boolean; confirmationEmailSent?: boolean | null; error?: string }
      if (!response.ok || body.booked !== true) throw new Error(body.error || copy.unavailable)
      requestRef.current = undefined
      setConfirmationSent(body.confirmationEmailSent === true)
      setState('success'); setTurnstileToken('')
      window.turnstile?.reset(widgetIdRef.current)
    } catch (cause) {
      setState('error'); setError(cause instanceof Error ? cause.message : copy.unavailable)
      setTurnstileToken(''); window.turnstile?.reset(widgetIdRef.current)
    }
  }

  return <div className="helloada-booking">
    <div className="helloada-booking-heading"><h3>{type?.name || label}</h3>{type?.description ? <p>{type.description}</p> : null}</div>
    {type ? <p className="helloada-booking-duration">{type.durationMinutes} {locale === 'fr' ? 'minutes' : locale === 'es' ? 'minutos' : 'minutes'}</p> : null}
    {state === 'success' ? <p className="helloada-booking-success" role="status">{confirmationSent ? copy.confirmationSent : copy.success}</p> : <form onSubmit={submit}>
      <label><span>{copy.name}</span><input autoComplete="name" maxLength={120} required value={name} onChange={(event) => setName(event.target.value)} /></label>
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
      <Script id={'helloada-booking-turnstile-' + bookingTypeId} src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit" strategy="afterInteractive" onLoad={() => {
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
