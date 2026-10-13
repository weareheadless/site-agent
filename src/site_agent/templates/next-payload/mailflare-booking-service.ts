export type BookingD1Result<T> = { results?: T[]; meta?: { changes?: number } }
export type BookingD1Statement = {
  bind: (...values: unknown[]) => BookingD1Statement
  first: <T = Record<string, unknown>>() => Promise<T | null>
  all: <T = Record<string, unknown>>() => Promise<BookingD1Result<T>>
  run: () => Promise<BookingD1Result<unknown>>
}
export type BookingD1 = {
  prepare: (query: string) => BookingD1Statement
  batch: (statements: BookingD1Statement[]) => Promise<BookingD1Result<unknown>[]>
}
export type BookingHours = { day: number; startTime: string; endTime: string }
export type BookingSettings = {
  enabled: boolean
  timeZone: string
  weeklyAvailability: BookingHours[]
  maxConcurrentAppointments: number
  minimumNoticeHours: number
  bookingWindowDays: number
  revision: number
  updatedAt: number
}
export type BookingType = {
  id: string
  slug: string
  name: string
  description: string
  durationMinutes: number
  enabled: boolean
  revision: number
}

const time = /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/
const minutes = (value: string) => Number(value.slice(0, 2)) * 60 + Number(value.slice(3))
const validZone = (value: string) => {
  try { new Intl.DateTimeFormat('en', { timeZone: value }).format(0); return true } catch { return false }
}

export function parseBookingHours(value: unknown): BookingHours[] | null {
  if (!Array.isArray(value) || value.length > 84) return null
  const rows: BookingHours[] = []
  for (const raw of value) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
    const row = raw as Record<string, unknown>
    if (!Number.isInteger(row.day) || Number(row.day) < 0 || Number(row.day) > 6
      || typeof row.startTime !== 'string' || !time.test(row.startTime)
      || typeof row.endTime !== 'string' || !time.test(row.endTime)
      || row.startTime >= row.endTime || minutes(row.startTime) % 15 || minutes(row.endTime) % 15) return null
    rows.push({ day: Number(row.day), startTime: row.startTime, endTime: row.endTime })
  }
  rows.sort((a, b) => a.day - b.day || a.startTime.localeCompare(b.startTime))
  if (rows.some((row, i) => i > 0 && row.day === rows[i - 1].day && row.startTime < rows[i - 1].endTime)) return null
  return rows
}

export const settingsFromRow = (row: Record<string, unknown>): BookingSettings => {
  let schedule: unknown
  try { schedule = JSON.parse(String(row.weekly_availability)) } catch { throw new Error('booking_settings_schedule_invalid') }
  const weeklyAvailability = parseBookingHours(schedule)
  const enabled = Number(row.enabled) === 1
  const timeZone = String(row.time_zone || '')
  const capacity = Number(row.max_concurrent_appointments)
  const notice = Number(row.minimum_notice_hours)
  const horizon = Number(row.booking_window_days)
  const revision = Number(row.revision)
  if (!weeklyAvailability || (timeZone && !validZone(timeZone))
    || (!timeZone && (enabled || weeklyAvailability.length))
    || !Number.isInteger(capacity) || capacity < 1 || capacity > 50
    || !Number.isInteger(notice) || notice < 0 || notice > 8760
    || !Number.isInteger(horizon) || horizon < 1 || horizon > 365
    || !Number.isInteger(revision) || revision < 1) throw new Error('booking_settings_invalid')
  return { enabled, timeZone, weeklyAvailability, maxConcurrentAppointments: capacity, minimumNoticeHours: notice, bookingWindowDays: horizon, revision, updatedAt: Number(row.updated_at) }
}

export async function readBookingSettings(db: BookingD1, userId: string): Promise<BookingSettings> {
  const row = await db.prepare(
    'SELECT enabled,time_zone,weekly_availability,max_concurrent_appointments,minimum_notice_hours,booking_window_days,revision,updated_at FROM helloada_booking_settings WHERE user_id=? LIMIT 1',
  ).bind(userId).first<Record<string, unknown>>()
  if (!row) throw new Error('booking_settings_not_provisioned')
  return settingsFromRow(row)
}

const typeFromRow = (row: Record<string, unknown>): BookingType => ({
  id: String(row.id),
  slug: String(row.slug),
  name: String(row.name),
  description: String(row.description || ''),
  durationMinutes: Number(row.duration_minutes),
  enabled: Number(row.enabled) === 1,
  revision: Number(row.helloada_revision),
})

export async function readBookingTypeById(db: BookingD1, userId: string, id: string): Promise<BookingType> {
  const row = await db.prepare(
    'SELECT id,slug,name,description,duration_minutes,enabled,helloada_revision FROM booking_events WHERE user_id=? AND id=? LIMIT 1',
  ).bind(userId, id).first<Record<string, unknown>>()
  if (!row) throw new Error('booking_type_not_found')
  return typeFromRow(row)
}

export async function readBookingTypeBySlug(db: BookingD1, userId: string, slug: string): Promise<BookingType> {
  const row = await db.prepare(
    'SELECT id,slug,name,description,duration_minutes,enabled,helloada_revision FROM booking_events WHERE user_id=? AND slug=? LIMIT 1',
  ).bind(userId, slug).first<Record<string, unknown>>()
  if (!row) throw new Error('booking_type_not_found')
  return typeFromRow(row)
}

export async function readBookingConfiguration(db: BookingD1, userId: string) {
  const [settings, result] = await Promise.all([
    readBookingSettings(db, userId),
    db.prepare('SELECT id,slug,name,description,duration_minutes,enabled,helloada_revision FROM booking_events WHERE user_id=? ORDER BY name COLLATE NOCASE,id')
      .bind(userId).all<Record<string, unknown>>(),
  ])
  const types = (result.results || []).map(typeFromRow)
  return { settings, types }
}

export async function updateBookingSettings(db: BookingD1, userId: string, input: unknown) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('booking_settings_invalid')
  const value = input as Record<string, unknown>
  const weeklyAvailability = parseBookingHours(value.weeklyAvailability)
  const timeZone = typeof value.timeZone === 'string' ? value.timeZone.trim() : ''
  const capacity = Number(value.maxConcurrentAppointments)
  const minimumNoticeHours = Number(value.minimumNoticeHours)
  const bookingWindowDays = Number(value.bookingWindowDays)
  const expectedRevision = Number(value.expectedRevision)
  if (!weeklyAvailability) throw new Error('booking_settings_hours_invalid')
  if ((timeZone && !validZone(timeZone)) || (!timeZone && (value.enabled === true || weeklyAvailability.length > 0))) {
    throw new Error('booking_settings_timezone_invalid')
  }
  if (!Number.isInteger(capacity) || capacity < 1 || capacity > 50
    || !Number.isInteger(minimumNoticeHours) || minimumNoticeHours < 0 || minimumNoticeHours > 8760
    || !Number.isInteger(bookingWindowDays) || bookingWindowDays < 1 || bookingWindowDays > 365
    || !Number.isInteger(expectedRevision) || expectedRevision < 1
    || typeof value.enabled !== 'boolean') throw new Error('booking_settings_values_invalid')
  if (value.enabled && weeklyAvailability.length === 0) throw new Error('booking_settings_hours_required')
  if (value.enabled) {
    const active = await db.prepare('SELECT name,duration_minutes FROM booking_events WHERE user_id=? AND enabled=1')
      .bind(userId).all<{ name: string; duration_minutes: number }>()
    if (!active.results?.length) throw new Error('booking_settings_type_required')
    if (active.results.some((type) => !weeklyAvailability.some((range) => minutes(range.endTime) - minutes(range.startTime) >= Number(type.duration_minutes)))) {
      throw new Error('booking_settings_hours_too_short')
    }
  }
  const result = await db.prepare(
    'UPDATE helloada_booking_settings SET enabled=?,time_zone=?,weekly_availability=?,max_concurrent_appointments=?,minimum_notice_hours=?,booking_window_days=?,revision=revision+1,updated_at=? WHERE user_id=? AND revision=?',
  ).bind(value.enabled ? 1 : 0, timeZone, JSON.stringify(weeklyAvailability), capacity, minimumNoticeHours, bookingWindowDays, Date.now(), userId, expectedRevision).run()
  if (result.meta?.changes !== 1) throw new Error('booking_settings_revision_conflict')
  return readBookingSettings(db, userId)
}

const normalizedType = (input: unknown, requiredSlug?: string) => {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('booking_type_invalid')
  const value = input as Record<string, unknown>
  const name = typeof value.name === 'string' ? value.name.trim() : ''
  const slug = requiredSlug ?? (typeof value.slug === 'string' ? value.slug.trim().toLowerCase() : '')
  const description = typeof value.description === 'string' ? value.description.trim() : ''
  const durationMinutes = Number(value.durationMinutes)
  if (!name || name.length > 120 || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) || slug.length > 80
    || description.length > 2000 || !Number.isInteger(durationMinutes) || durationMinutes < 10
    || durationMinutes > 480 || durationMinutes % 5) throw new Error('booking_type_values_invalid')
  return { name, slug, description, durationMinutes }
}

const stableTypeId = async (userId: string, slug: string) => {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(userId + ':' + slug)))
  return 'ha_booking_' + [...digest].map((byte) => byte.toString(16).padStart(2, '0')).join('').slice(0, 32)
}

export async function createBookingType(db: BookingD1, userId: string, input: unknown) {
  const value = normalizedType(input)
  const id = await stableTypeId(userId, value.slug)
  const now = Math.floor(Date.now() / 1000)
  try {
    await db.prepare(
      'INSERT INTO booking_events (id,user_id,name,slug,description,color,host_ids,duration_minutes,location,weekdays,start_time,end_time,time_ranges,time_zone,enabled,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)',
    ).bind(id, userId, value.name, value.slug, value.description, '#f28b55', JSON.stringify([userId]), value.durationMinutes, '', '[]', '', '', '[]', '', now, now).run()
  } catch (error) {
    if (error instanceof Error && /UNIQUE constraint failed/i.test(error.message)) {
      const existing = await readBookingTypeBySlug(db, userId, value.slug)
      if (existing.id === id && existing.name === value.name && existing.description === value.description
        && existing.durationMinutes === value.durationMinutes && existing.enabled) return existing
      throw new Error('booking_type_slug_conflict')
    }
    throw error
  }
  return readBookingTypeById(db, userId, id)
}

export async function updateBookingType(db: BookingD1, userId: string, id: string, expectedRevision: number, input: unknown) {
  if (!Number.isInteger(expectedRevision) || expectedRevision < 1) throw new Error('booking_type_revision_required')
  const existing = await readBookingTypeById(db, userId, id)
  const value = normalizedType(input, existing.slug)
  if (typeof (input as Record<string, unknown>).slug === 'string' && (input as Record<string, unknown>).slug !== existing.slug) {
    throw new Error('booking_type_identity_immutable')
  }
  const result = await db.prepare(
    'UPDATE booking_events SET name=?,description=?,duration_minutes=?,updated_at=?,helloada_revision=helloada_revision+1 WHERE user_id=? AND id=? AND helloada_revision=?',
  ).bind(value.name, value.description, value.durationMinutes, Math.floor(Date.now() / 1000), userId, id, expectedRevision).run()
  if (result.meta?.changes !== 1) throw new Error('booking_type_revision_conflict')
  return readBookingTypeById(db, userId, id)
}

export async function setBookingTypeActive(db: BookingD1, userId: string, id: string, expectedRevision: number, enabled: boolean) {
  if (!Number.isInteger(expectedRevision) || expectedRevision < 1) throw new Error('booking_type_revision_required')
  const result = await db.prepare(
    'UPDATE booking_events SET enabled=?,updated_at=?,helloada_revision=helloada_revision+1 WHERE user_id=? AND id=? AND helloada_revision=?',
  ).bind(enabled ? 1 : 0, Math.floor(Date.now() / 1000), userId, id, expectedRevision).run()
  if (result.meta?.changes !== 1) throw new Error('booking_type_revision_conflict')
  return readBookingTypeById(db, userId, id)
}

export async function deactivateBookingType(db: BookingD1, userId: string, id: string, expectedRevision: number) {
  return setBookingTypeActive(db, userId, id, expectedRevision, false)
}

export async function resolveTenantBookingOwner(db: BookingD1, tenantId: string): Promise<string> {
  if (!tenantId.trim()) throw new Error('tenant_identity_not_configured')
  const row = await db.prepare(
    'SELECT owner_user_id FROM helloada_tenant_owners WHERE tenant_id=? LIMIT 1',
  ).bind(tenantId).first<{ owner_user_id: string }>()
  if (!row?.owner_user_id) throw new Error('booking_owner_not_provisioned')
  return row.owner_user_id
}
