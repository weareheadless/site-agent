import type { Payload } from 'payload'

import { findMessageRecord, nowIso } from '@/lib/messages-service'
import type { MessageRecord } from '@/lib/messages-service'

const object = (value: unknown) => value && typeof value === 'object' && !Array.isArray(value) ? value as MessageRecord : {}
const text = (value: unknown) => String(value ?? '').trim()
const formatters = new Map<string, Intl.DateTimeFormat>()
const localFormatter = (timeZone: string) => {
  let formatter = formatters.get(timeZone)
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-CA', {
      timeZone, year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'long',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    })
    formatters.set(timeZone, formatter)
  }
  return formatter
}

const localParts = (date: Date, timeZone: string) => Object.fromEntries(
  localFormatter(timeZone).formatToParts(date).map(({ type, value }) => [type, value]),
)

const offsetAt = (instant: Date, timeZone: string) => {
  const parts = localParts(instant, timeZone)
  const asUtc = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), Number(parts.hour), Number(parts.minute))
  return (asUtc - Math.floor(instant.getTime() / 60_000) * 60_000) / 60_000
}

/** Maps a wall-clock time to the valid UTC instant(s), explicitly accounting
 * for daylight-saving gaps and repeated local times. */
const localToUtc = (date: string, time: string, timeZone: string) => {
  const [year, month, day] = date.split('-').map(Number)
  const [hour, minute] = time.split(':').map(Number)
  const nominal = Date.UTC(year, month - 1, day, hour, minute)
  const offsets = new Set<number>()
  for (let delta = -36; delta <= 36; delta += 6) offsets.add(offsetAt(new Date(nominal + delta * 3_600_000), timeZone))
  const matches = [...offsets]
    .map((offset) => new Date(nominal - offset * 60_000))
    .filter((candidate) => {
      const parts = localParts(candidate, timeZone)
      return Number(parts.year) === year && Number(parts.month) === month && Number(parts.day) === day
        && Number(parts.hour) === hour && Number(parts.minute) === minute
    })
    .sort((left, right) => left.getTime() - right.getTime())
  return matches
}

const dayNames = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
const datePattern = /^\d{4}-\d{2}-\d{2}$/
const slotMinutes = 15
const reservationMinutes = 5

export const findAppointmentType = async (payload: Payload, slug: string) => {
  const result = await payload.find({
    collection: 'appointmentTypes', depth: 0, draft: false, limit: 1, pagination: false,
    overrideAccess: true,
    where: { and: [{ slug: { equals: slug } }, { enabled: { equals: true } }] } as never,
  })
  return result.docs[0] as unknown as MessageRecord | undefined
}

export const calendarSettings = async (payload: Payload) => await payload.findGlobal({
  slug: 'calendarSettings' as never, depth: 0, overrideAccess: true,
}) as unknown as MessageRecord

export const localDateForInstant = (instant: Date, timeZone: string) => {
  const parts = localParts(instant, timeZone)
  return `${parts.year}-${parts.month}-${parts.day}`
}

export const bookingSlotsForDate = async (payload: Payload, appointmentSlug: string, date: string, ignoreOperationId = '') => {
  if (!datePattern.test(date) || new Date(`${date}T00:00:00Z`).toISOString().slice(0, 10) !== date) throw new Error('Choose a valid calendar date.')
  const [settings, appointmentType] = await Promise.all([
    calendarSettings(payload), findAppointmentType(payload, appointmentSlug),
  ])
  if (settings.enabled !== true || !appointmentType) return { timeZone: text(settings.timeZone) || 'UTC', slots: [] as Array<{ startsAt: string; endsAt: string }> }
  const timeZone = text(settings.timeZone)
  const duration = Number(appointmentType.durationMinutes)
  const buffer = Number(appointmentType.bufferMinutes || 0)
  if (!timeZone || !Number.isInteger(duration) || duration < 5 || !Number.isInteger(buffer) || buffer < 0) throw new Error('The calendar configuration is incomplete.')
  const day = dayNames[new Date(`${date}T12:00:00Z`).getUTCDay()]
  const availability = Array.isArray(appointmentType.weeklyAvailability)
    ? appointmentType.weeklyAvailability.map(object).filter((period) => text(period.day) === day)
    : []
  const earliest = Date.now() + Math.max(0, Number(settings.minimumNoticeHours || 0)) * 3_600_000
  const latest = Date.now() + Math.max(1, Number(settings.bookingWindowDays || 60)) * 86_400_000
  const slots: Array<{ startsAt: string; endsAt: string }> = []
  const seen = new Set<string>()
  for (const period of availability) {
    const [startHour, startMinute] = text(period.startTime).split(':').map(Number)
    const [endHour, endMinute] = text(period.endTime).split(':').map(Number)
    if (![startHour, startMinute, endHour, endMinute].every(Number.isInteger)) continue
    const startOfWindow = startHour * 60 + startMinute
    const endOfWindow = endHour * 60 + endMinute
    for (let localMinute = startOfWindow; localMinute + duration + buffer <= endOfWindow; localMinute += slotMinutes) {
      const time = `${String(Math.floor(localMinute / 60)).padStart(2, '0')}:${String(localMinute % 60).padStart(2, '0')}`
      const instant = localToUtc(date, time, timeZone)[0]
      if (!instant || instant.getTime() < earliest || instant.getTime() > latest) continue
      const endsAt = new Date(instant.getTime() + duration * 60_000)
      if (seen.has(instant.toISOString())) continue
      seen.add(instant.toISOString())
      slots.push({ startsAt: instant.toISOString(), endsAt: endsAt.toISOString() })
    }
  }
  const dayStart = Date.parse(`${date}T00:00:00.000Z`) - 36 * 3_600_000
  const dayEnd = dayStart + 72 * 3_600_000
  const events = await payload.find({
    collection: 'calendarEvents', depth: 0, limit: 1_000, pagination: false, overrideAccess: true,
    where: { and: [
      { state: { equals: 'confirmed' } },
      { startsAt: { less_than: new Date(dayEnd).toISOString() } },
      { endsAt: { greater_than: new Date(dayStart).toISOString() } },
    ] } as never,
  })
  if (events.docs.length === 1_000) throw new Error('This calendar needs owner review before availability can be shown.')
  const eventIntervals = events.docs.map((raw) => object(raw)).map((event) => ({
    start: new Date(String(event.startsAt)).getTime(),
    end: new Date(String(event.endsAt)).getTime() + Number(event.bufferMinutes || 0) * 60_000,
  }))
  const lockKeys = [...new Set(slots.flatMap((slot) => {
    const start = new Date(slot.startsAt).getTime()
    const end = new Date(slot.endsAt).getTime() + buffer * 60_000
    const keys: string[] = []
    for (let minute = Math.floor(start / (reservationMinutes * 60_000)); minute < Math.ceil(end / (reservationMinutes * 60_000)); minute++) keys.push(String(minute))
    return keys
  }))]
  const locks = lockKeys.length ? await payload.find({
    collection: 'calendarSlotLocks', depth: 0, limit: 500, pagination: false, overrideAccess: true,
    where: { and: [
      { slotKey: { in: lockKeys } }, { expiresAt: { greater_than: nowIso() } },
      ...(ignoreOperationId ? [{ operationId: { not_equals: ignoreOperationId } }] : []),
    ] } as never,
  }) : { docs: [] }
  const lockedSlots = new Set(locks.docs.map((raw) => text(object(raw).slotKey)))
  return {
    timeZone,
    slots: slots.filter((slot) => {
      const start = new Date(slot.startsAt).getTime()
      const end = new Date(slot.endsAt).getTime() + buffer * 60_000
      if (eventIntervals.some((event) => start < event.end && end > event.start)) return false
      for (let minute = Math.floor(start / (reservationMinutes * 60_000)); minute < Math.ceil(end / (reservationMinutes * 60_000)); minute++) {
        if (lockedSlots.has(String(minute))) return false
      }
      return true
    }),
  }
}

export const reserveBookingSlot = async (payload: Payload, operationId: string, startsAt: string, endsAt: string, bufferMinutes: number) => {
  const start = new Date(startsAt).getTime()
  const end = new Date(endsAt).getTime() + bufferMinutes * 60_000
  const first = Math.floor(start / (reservationMinutes * 60_000))
  const last = Math.ceil(end / (reservationMinutes * 60_000))
  const owned: string[] = []
  try {
    for (let slot = first; slot < last; slot++) {
      const slotKey = String(slot)
      const previous = await findMessageRecord(payload, 'calendarSlotLocks', { slotKey: { equals: slotKey } })
      if (previous) {
        if (String(previous.operationId) === operationId && new Date(String(previous.expiresAt)).getTime() > Date.now()) { owned.push(String(previous.id)); continue }
        if (new Date(String(previous.expiresAt)).getTime() <= Date.now()) {
          await payload.delete({ collection: 'calendarSlotLocks', id: previous.id as string, overrideAccess: true })
        } else throw Object.assign(new Error('That time was just booked. Choose another available time.'), { permanent: true, code: 'slot_unavailable' })
      }
      try {
        const created = await payload.create({ collection: 'calendarSlotLocks', data: {
          slotKey, operationId, expiresAt: new Date(Date.now() + 15 * 60_000).toISOString(),
        } as never, overrideAccess: true }) as unknown as MessageRecord
        owned.push(String(created.id))
      } catch (error) {
        const raced = await findMessageRecord(payload, 'calendarSlotLocks', { slotKey: { equals: slotKey } })
        if (raced && String(raced.operationId) !== operationId) {
          throw Object.assign(new Error('That time was just booked. Choose another available time.'), { permanent: true, code: 'slot_unavailable' })
        }
        if (raced) owned.push(String(raced.id))
        else throw error
      }
    }
    return owned
  } catch (error) {
    await Promise.all(owned.map((id) => payload.delete({ collection: 'calendarSlotLocks', id, overrideAccess: true }).catch(() => undefined)))
    if (error && typeof error === 'object' && 'code' in error) throw error
    const raced = await payload.find({ collection: 'calendarSlotLocks', depth: 0, limit: 1, pagination: false, overrideAccess: true, where: { operationId: { equals: operationId } } as never }).catch(() => ({ docs: [] }))
    if (raced.docs.length) throw Object.assign(new Error('That time was just booked. Choose another available time.'), { permanent: true, code: 'slot_unavailable' })
    throw error
  }
}

export const releaseBookingSlots = async (payload: Payload, operationId: string) => {
  const locks = await payload.find({ collection: 'calendarSlotLocks', depth: 0, limit: 500, pagination: false, overrideAccess: true, where: { operationId: { equals: operationId } } as never })
  await Promise.all(locks.docs.map((lock) => payload.delete({ collection: 'calendarSlotLocks', id: lock.id, overrideAccess: true })))
}
