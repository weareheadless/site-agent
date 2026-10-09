'use client'

import Link from 'next/link'
import type { FormEvent } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { fetchHelloAda } from '../api/fetchHelloAda'
import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations'

type Period = { day: string; startTime: string; endTime: string }
type AppointmentType = { id: string | number; name: string; slug: string; description?: string; durationMinutes: number; bufferMinutes?: number; weeklyAvailability?: Period[]; enabled: boolean }
type CalendarEvent = { id: string | number; title: string; startsAt: string; endsAt: string; timeZone: string; state: string; notificationState?: string; contact?: { name?: string; email?: string } | string; appointmentType?: { name?: string } | string }
type CalendarData = { settings?: { enabled?: boolean; timeZone?: string; minimumNoticeHours?: number; bookingWindowDays?: number }; appointmentTypes?: AppointmentType[]; events?: CalendarEvent[] }

const days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
const languageCopy = {
  en: { title: 'Calendar', subtitle: 'Appointments from your website, in one place.', messages: 'Messages', settings: 'Booking settings', enabled: 'Accept online bookings', zone: 'Business time zone', notice: 'Minimum notice (hours)', window: 'Booking window (days)', type: 'Appointment type', name: 'Name', slug: 'Page address', description: 'Description', duration: 'Duration (minutes)', buffer: 'Buffer (minutes)', availability: 'Weekly availability', start: 'From', end: 'To', save: 'Save changes', loading: 'Loading…', saved: 'Changes saved.', failed: 'Calendar could not be updated.', upcoming: 'Upcoming appointments', noEvents: 'No upcoming appointments yet.', noTypes: 'Create an appointment type to let visitors book from your site.', cancel: 'Cancel booking', cancelled: 'Appointment cancelled.', active: 'Active', inactive: 'Not accepting bookings' },
  fr: { title: 'Calendrier', subtitle: 'Les rendez-vous pris sur votre site, au même endroit.', messages: 'Messages', settings: 'Réglages des réservations', enabled: 'Accepter les réservations en ligne', zone: 'Fuseau horaire', notice: 'Délai minimum (heures)', window: 'Réservations jusqu’à (jours)', type: 'Type de rendez-vous', name: 'Nom', slug: 'Adresse de la page', description: 'Description', duration: 'Durée (minutes)', buffer: 'Pause (minutes)', availability: 'Disponibilités hebdomadaires', start: 'De', end: 'À', save: 'Enregistrer', loading: 'Chargement…', saved: 'Modifications enregistrées.', failed: 'Le calendrier n’a pas pu être modifié.', upcoming: 'Prochains rendez-vous', noEvents: 'Aucun rendez-vous à venir.', noTypes: 'Créez un type de rendez-vous pour permettre la réservation sur votre site.', cancel: 'Annuler le rendez-vous', cancelled: 'Rendez-vous annulé.', active: 'Actif', inactive: 'Réservations désactivées' },
  es: { title: 'Calendario', subtitle: 'Citas reservadas desde tu sitio, en un solo lugar.', messages: 'Mensajes', settings: 'Configuración de reservas', enabled: 'Aceptar reservaciones en línea', zone: 'Zona horaria del negocio', notice: 'Anticipación mínima (horas)', window: 'Reservar con hasta (días)', type: 'Tipo de cita', name: 'Nombre', slug: 'Dirección de página', description: 'Descripción', duration: 'Duración (minutos)', buffer: 'Pausa (minutos)', availability: 'Disponibilidad semanal', start: 'Desde', end: 'Hasta', save: 'Guardar cambios', loading: 'Cargando…', saved: 'Cambios guardados.', failed: 'No se pudo actualizar el calendario.', upcoming: 'Próximas citas', noEvents: 'Aún no hay citas próximas.', noTypes: 'Crea un tipo de cita para que tus visitantes reserven en tu sitio.', cancel: 'Cancelar reservación', cancelled: 'Cita cancelada.', active: 'Activo', inactive: 'No acepta reservaciones' },
}

const defaultAvailability = (): Period[] => days.slice(0, 5).map((day) => ({ day, startTime: '09:00', endTime: '17:00' }))
const bookingStatusCopy = {
  en: { accepted: 'Confirmation sent', pending: 'Confirmation pending', failed: 'Email confirmation unavailable', uncertain: 'Email status uncertain' },
  fr: { accepted: 'Confirmation envoyée', pending: 'Confirmation en attente', failed: 'E-mail de confirmation indisponible', uncertain: 'Statut de l’e-mail incertain' },
  es: { accepted: 'Confirmación enviada', pending: 'Confirmación pendiente', failed: 'No se pudo enviar el correo de confirmación', uncertain: 'Estado del correo incierto' },
}
const localizedDay = (day: string, language: string) => {
  const index = days.indexOf(day)
  return index < 0 ? day : new Intl.DateTimeFormat(language, { weekday: 'long', timeZone: 'UTC' }).format(new Date(Date.UTC(2024, 0, 1 + index)))
}

export function HelloAdaCalendar() {
  const { language, t } = useHelloAdaTranslations()
  const copy = languageCopy[language as keyof typeof languageCopy] || languageCopy.en
  const [data, setData] = useState<CalendarData>()
  const [selectedId, setSelectedId] = useState<string>('new')
  const [settings, setSettings] = useState({ enabled: false, timeZone: '', minimumNoticeHours: 24, bookingWindowDays: 60 })
  const [form, setForm] = useState({ name: '', slug: '', description: '', durationMinutes: 30, bufferMinutes: 0, enabled: false, weeklyAvailability: defaultAvailability() })
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setError('')
    try {
      const response = await fetchHelloAda('/api/helloada/calendar', { cache: 'no-store' })
      const body = await response.json() as CalendarData & { message?: string }
      if (!response.ok) throw new Error(body.message || copy.failed)
      setData(body)
      setSettings({
        enabled: body.settings?.enabled === true, timeZone: body.settings?.timeZone || '',
        minimumNoticeHours: Number(body.settings?.minimumNoticeHours ?? 24), bookingWindowDays: Number(body.settings?.bookingWindowDays ?? 60),
      })
      const first = body.appointmentTypes?.[0]
      if (first && selectedId === 'new') { setSelectedId(String(first.id)); setForm({ ...first, description: first.description || '', bufferMinutes: Number(first.bufferMinutes || 0), weeklyAvailability: first.weeklyAvailability || [] }) }
    } catch (cause) { setError(cause instanceof Error ? cause.message : copy.failed) }
  }, [copy.failed, selectedId])

  useEffect(() => { void load() }, [load])

  const chooseType = (id: string) => {
    setSelectedId(id)
    const selected = data?.appointmentTypes?.find((item) => String(item.id) === id)
    setForm(selected ? { ...selected, description: selected.description || '', bufferMinutes: Number(selected.bufferMinutes || 0), weeklyAvailability: selected.weeklyAvailability || [] } : { name: '', slug: '', description: '', durationMinutes: 30, bufferMinutes: 0, enabled: false, weeklyAvailability: defaultAvailability() })
  }

  const save = async (path: string, body: unknown) => {
    setBusy(true); setError(''); setNotice('')
    try {
      const response = await fetchHelloAda(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
      const result = await response.json() as { message?: string }
      if (!response.ok) throw new Error(result.message || copy.failed)
      setNotice(copy.saved)
      await load()
      return true
    } catch (cause) { setError(cause instanceof Error ? cause.message : copy.failed); return false }
    finally { setBusy(false) }
  }

  const saveSettings = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await save('/api/helloada/calendar/settings', settings)
  }

  const saveType = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await save('/api/helloada/calendar/appointment-types', { ...form, ...(selectedId !== 'new' ? { id: selectedId } : {}) })
  }

  const cancel = async (eventId: string | number) => {
    if (!window.confirm(copy.cancel)) return
    const response = await fetchHelloAda(`/api/helloada/calendar/events/${encodeURIComponent(String(eventId))}/cancel`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({}) })
    const result = await response.json() as { message?: string }
    if (!response.ok) { setError(result.message || copy.failed); return }
    setNotice(copy.cancelled); await load()
  }

  const upcoming = useMemo(() => (data?.events || []).filter((event) => event.state === 'confirmed').sort((a, b) => a.startsAt.localeCompare(b.startsAt)), [data?.events])

  return <main className="helloada-messages helloada-calendar" aria-label={copy.title}>
    <header className="helloada-messages-header"><div><span className="helloada-eyebrow">{copy.title}</span><h1>{copy.title}</h1><p>{copy.subtitle}</p></div><Link className="helloada-messages-manage-form" href="/admin?view=messages">{copy.messages}</Link></header>
    <nav className="helloada-messages-toolbar" aria-label={t('owner.messages')}><Link className="helloada-calendar-nav" href="/admin?view=messages">{t('owner.messagesInbox')}</Link><span className="helloada-calendar-nav is-active" aria-current="page">{copy.title}</span></nav>
    {error ? <p className="helloada-messages-error" role="alert">{error}</p> : null}{notice ? <p className="helloada-messages-notice" role="status">{notice}</p> : null}
    {!data ? <p className="helloada-messages-empty">{copy.loading}</p> : <div className="helloada-calendar-layout">
      <section className="helloada-calendar-panel"><h2>{copy.settings}</h2>
        <form onSubmit={saveSettings} className="helloada-calendar-form">
          <label className="helloada-calendar-check"><input type="checkbox" checked={settings.enabled} onChange={(event) => setSettings({ ...settings, enabled: event.target.checked })} /><span>{copy.enabled}</span></label>
          <label><span>{copy.zone}</span><input required value={settings.timeZone} onChange={(event) => setSettings({ ...settings, timeZone: event.target.value })} placeholder="America/Cancun" autoComplete="off" /></label>
          <div className="helloada-calendar-two"><label><span>{copy.notice}</span><input type="number" min="0" max="8760" value={settings.minimumNoticeHours} onChange={(event) => setSettings({ ...settings, minimumNoticeHours: Number(event.target.value) })} /></label><label><span>{copy.window}</span><input type="number" min="1" max="365" value={settings.bookingWindowDays} onChange={(event) => setSettings({ ...settings, bookingWindowDays: Number(event.target.value) })} /></label></div>
          <button type="submit" disabled={busy}>{busy ? copy.loading : copy.save}</button>
        </form>
        <div className="helloada-calendar-type-head"><h2>{copy.type}</h2><select value={selectedId} onChange={(event) => chooseType(event.target.value)}><option value="new">+ {copy.type}</option>{(data.appointmentTypes || []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
        <form onSubmit={saveType} className="helloada-calendar-form">
          <label><span>{copy.name}</span><input required maxLength={120} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value, ...(selectedId === 'new' ? { slug: event.target.value.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') } : {}) })} /></label>
          <label><span>{copy.description}</span><textarea maxLength={2000} rows={2} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
          <div className="helloada-calendar-two"><label><span>{copy.duration}</span><input type="number" min="10" max="480" step="5" value={form.durationMinutes} onChange={(event) => setForm({ ...form, durationMinutes: Number(event.target.value) })} /></label><label><span>{copy.buffer}</span><input type="number" min="0" max="120" step="5" value={form.bufferMinutes} onChange={(event) => setForm({ ...form, bufferMinutes: Number(event.target.value) })} /></label></div>
          <fieldset><legend>{copy.availability}</legend>{days.map((day) => {
            const period = form.weeklyAvailability.find((item) => item.day === day)
            return <div className="helloada-calendar-day" key={day}><label><input type="checkbox" checked={Boolean(period)} onChange={(event) => setForm({ ...form, weeklyAvailability: event.target.checked ? [...form.weeklyAvailability, { day, startTime: '09:00', endTime: '17:00' }] : form.weeklyAvailability.filter((item) => item.day !== day) })} /><span>{localizedDay(day, language)}</span></label>{period ? <><label><span className="sr-only">{copy.start}</span><input type="time" value={period.startTime} onChange={(event) => setForm({ ...form, weeklyAvailability: form.weeklyAvailability.map((item) => item.day === day ? { ...item, startTime: event.target.value } : item) })} /></label><label><span className="sr-only">{copy.end}</span><input type="time" value={period.endTime} onChange={(event) => setForm({ ...form, weeklyAvailability: form.weeklyAvailability.map((item) => item.day === day ? { ...item, endTime: event.target.value } : item) })} /></label></> : <span />}</div>
          })}</fieldset>
          <label className="helloada-calendar-check"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} /><span>{copy.active}</span></label>
          <button type="submit" disabled={busy}>{busy ? copy.loading : copy.save}</button>
        </form>
      </section>
      <section className="helloada-calendar-panel"><h2>{copy.upcoming}</h2>{upcoming.length ? <div className="helloada-calendar-events">{upcoming.map((event) => {
        const contact = typeof event.contact === 'object' ? event.contact : undefined
        const appointment = typeof event.appointmentType === 'object' ? event.appointmentType : undefined
        const status = bookingStatusCopy[language as keyof typeof bookingStatusCopy] || bookingStatusCopy.en
        return <article key={event.id}><div><strong>{event.title || appointment?.name}</strong><span>{contact?.name || contact?.email || ''}</span><time dateTime={event.startsAt}>{new Intl.DateTimeFormat(language, { timeZone: event.timeZone, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(event.startsAt))}</time><small>{event.notificationState === 'accepted' ? status.accepted : event.notificationState === 'pending' ? status.pending : event.notificationState === 'failed' ? status.failed : event.notificationState === 'uncertain' ? status.uncertain : ''}</small></div><button type="button" className="is-secondary" onClick={() => void cancel(event.id)}>{copy.cancel}</button></article>
      })}</div> : <p className="helloada-messages-empty">{data.appointmentTypes?.length ? copy.noEvents : copy.noTypes}</p>}</section>
    </div>}
  </main>
}
