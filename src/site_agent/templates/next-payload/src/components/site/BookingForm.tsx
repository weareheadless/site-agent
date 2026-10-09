'use client'

import Script from 'next/script'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'

type Slot = { startsAt: string; endsAt: string }
type BookingCopy = {
  name: string; email: string; notes: string; date: string; time: string; submit: string; sending: string;
  noSlots: string; unavailable: string; success: string; successNoEmail: string; security: string; consent: string;
}

const copyByLanguage: Record<string, BookingCopy> = {
  en: { name: 'Your name', email: 'Email address', notes: 'Anything we should know? (optional)', date: 'Choose a date', time: 'Available times', submit: 'Book appointment', sending: 'Confirming…', noSlots: 'No times are available on this date.', unavailable: 'Online booking is not available right now.', success: 'Your appointment is confirmed. A confirmation email will follow.', successNoEmail: 'Your appointment is confirmed. Please contact the business if you need to make a change.', security: 'Complete the security check.', consent: 'I agree that the business may use these details to manage my appointment.' },
  es: { name: 'Tu nombre', email: 'Correo electrónico', notes: '¿Algo más que debamos saber? (opcional)', date: 'Elige una fecha', time: 'Horarios disponibles', submit: 'Reservar cita', sending: 'Confirmando…', noSlots: 'No hay horarios disponibles en esta fecha.', unavailable: 'Las reservaciones en línea no están disponibles por ahora.', success: 'Tu cita está confirmada. Recibirás un correo de confirmación.', successNoEmail: 'Tu cita está confirmada. Contacta al negocio si necesitas cambiarla.', security: 'Completa la verificación de seguridad.', consent: 'Acepto que el negocio use estos datos para gestionar mi cita.' },
  fr: { name: 'Votre nom', email: 'Adresse e-mail', notes: 'Une précision à nous communiquer ? (facultatif)', date: 'Choisir une date', time: 'Horaires disponibles', submit: 'Réserver', sending: 'Confirmation…', noSlots: 'Aucun horaire disponible à cette date.', unavailable: 'La réservation en ligne est indisponible pour le moment.', success: 'Votre rendez-vous est confirmé. Un e-mail de confirmation suivra.', successNoEmail: 'Votre rendez-vous est confirmé. Contactez l’entreprise pour toute modification.', security: 'Effectuez la vérification de sécurité.', consent: 'J’accepte que l’entreprise utilise ces informations pour gérer mon rendez-vous.' },
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

export default function BookingForm({ appointmentType, siteKey, locale = 'en' }: {
  appointmentType: { slug: string; name: string; description?: string }
  siteKey: string
  locale?: string
}) {
  const copy = copyByLanguage[locale] || copyByLanguage.en
  const [timeZone, setTimeZone] = useState('')
  const [windowDays, setWindowDays] = useState(60)
  const [today, setToday] = useState('')
  const [date, setDate] = useState('')
  const [slots, setSlots] = useState<Slot[]>([])
  const [selected, setSelected] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [notes, setNotes] = useState('')
  const [consent, setConsent] = useState(false)
  const [turnstileToken, setTurnstileToken] = useState('')
  const [state, setState] = useState<'loading' | 'ready' | 'sending' | 'success' | 'error'>('loading')
  const [successMessage, setSuccessMessage] = useState(copy.success)
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
    void fetch(`/api/helloada/bookings?appointmentType=${encodeURIComponent(appointmentType.slug)}`, { cache: 'no-store' })
      .then(async (response) => {
        const body = await response.json() as { enabled?: boolean; timeZone?: string; bookingWindowDays?: number; error?: string }
        if (!response.ok) throw new Error(body.error || copy.unavailable)
        if (cancelled) return
        if (!body.enabled || !body.timeZone) { setState('error'); setError(copy.unavailable); return }
        const businessZone = body.timeZone
        const today = dateInZone(new Date(), businessZone)
        setTimeZone(businessZone); setWindowDays(Number(body.bookingWindowDays || 60)); setToday(today); setDate(today); setState('ready')
      })
      .catch((cause) => { if (!cancelled) { setState('error'); setError(cause instanceof Error ? cause.message : copy.unavailable) } })
    return () => { cancelled = true }
  }, [appointmentType.slug, copy.unavailable])

  useEffect(() => {
    if (!date || !timeZone) return
    let cancelled = false
    setSlots([]); setSelected('')
    void fetch(`/api/helloada/bookings?appointmentType=${encodeURIComponent(appointmentType.slug)}&date=${encodeURIComponent(date)}`, { cache: 'no-store' })
      .then(async (response) => {
        const body = await response.json() as { timeZone?: string; slots?: Slot[]; error?: string }
        if (!response.ok) throw new Error(body.error || copy.unavailable)
        if (cancelled) return
        if (body.timeZone !== timeZone) throw new Error(copy.unavailable)
        setSlots(body.slots || [])
      })
      .catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : copy.unavailable) })
    return () => { cancelled = true }
  }, [appointmentType.slug, copy.unavailable, date, timeZone])

  const pollReceipt = async (receipt: string) => {
    for (let attempt = 0; attempt < 10; attempt++) {
      const response = await fetch(`/api/helloada/bookings?receipt=${encodeURIComponent(receipt)}`, { cache: 'no-store' })
      const body = await response.json() as { confirmed?: boolean; confirmationEmail?: string; message?: string; state?: string }
      if (response.status === 409 || body.state === 'failed') throw new Error(body.message || copy.unavailable)
      if (!response.ok) throw new Error(body.message || copy.unavailable)
      if (body.confirmed) {
        setSuccessMessage(body.confirmationEmail === 'accepted' || body.confirmationEmail === 'pending' ? copy.success : copy.successNoEmail)
        return
      }
      await new Promise((resolve) => window.setTimeout(resolve, 900))
    }
    throw new Error(copy.unavailable)
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (state === 'sending' || !selected) return
    if (!turnstileToken) { setError(copy.security); setState('error'); return }
    setState('sending'); setError('')
    try {
      const bookingPayload = {
        name, email, appointmentType: appointmentType.slug, startsAt: selected, timeZone, consent,
        answers: notes.trim() ? { notes: notes.trim() } : {},
      }
      const fingerprint = JSON.stringify(bookingPayload)
      const requestId = requestRef.current?.fingerprint === fingerprint
        ? requestRef.current.requestId
        : globalThis.crypto.randomUUID()
      requestRef.current = { fingerprint, requestId }
      const response = await fetch('/api/helloada/bookings', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          ...bookingPayload, requestId, turnstileToken,
          website: String(new FormData(event.currentTarget).get('website') || ''),
        }),
      })
      const body = await response.json() as { receipt?: string; error?: string }
      if (!response.ok || !body.receipt) throw new Error(body.error || copy.unavailable)
      await pollReceipt(body.receipt)
      requestRef.current = undefined
      setState('success'); setTurnstileToken('')
      window.turnstile?.reset(widgetIdRef.current)
    } catch (cause) {
      setState('error'); setError(cause instanceof Error ? cause.message : copy.unavailable)
      setTurnstileToken(''); window.turnstile?.reset(widgetIdRef.current)
    }
  }

  return <div className="helloada-booking">
    <div className="helloada-booking-heading"><h3>{appointmentType.name}</h3>{appointmentType.description ? <p>{appointmentType.description}</p> : null}</div>
    {state === 'success' ? <p className="helloada-booking-success" role="status">{successMessage}</p> : <form onSubmit={submit}>
      <label><span>{copy.name}</span><input autoComplete="name" maxLength={160} required value={name} onChange={(event) => setName(event.target.value)} /></label>
      <label><span>{copy.email}</span><input type="email" autoComplete="email" maxLength={254} required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      <label><span>{copy.notes}</span><textarea maxLength={2000} rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
      <label className="helloada-booking-consent"><input type="checkbox" required checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>{copy.consent}</span></label>
      <label><span>{copy.date}</span><input type="date" min={today || undefined} max={maxDate || undefined} value={date} onChange={(event) => setDate(event.target.value)} disabled={!timeZone || state === 'sending'} /></label>
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
