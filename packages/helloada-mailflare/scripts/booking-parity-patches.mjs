const replaceExactlyOnce = (source, before, after, filename) => {
  const index = source.indexOf(before)
  if (index < 0 || source.indexOf(before, index + before.length) !== -1) throw new Error("Pinned Mailflare parity patch no longer applies exactly once: " + filename)
  return source.slice(0, index) + after + source.slice(index + before.length)
}

const replaceSection = (source, start, end, replacement, filename) => {
  const first = source.indexOf(start)
  const last = source.indexOf(end, first + start.length)
  if (first < 0 || last < 0 || source.indexOf(start, first + start.length) !== -1) throw new Error("Pinned Mailflare parity section no longer applies exactly once: " + filename)
  return source.slice(0, first) + replacement + "\n\n" + source.slice(last)
}

const replaceTail = (source, start, replacement, filename) => {
  const index = source.indexOf(start)
  if (index < 0 || source.indexOf(start, index + start.length) !== -1) throw new Error("Pinned Mailflare parity tail no longer applies exactly once: " + filename)
  return source.slice(0, index) + replacement + "\n"
}

const weeklyInputHelpers = [
  "function normalizeHelloAdaWeeklyAvailability(value: unknown): BookingWeeklyAvailability[] | null {",
  "\tif (!Array.isArray(value) || value.length < 1 || value.length > 84) return null;",
  "\tconst schedule: BookingWeeklyAvailability[] = [];",
  "\tfor (const item of value) {",
  "\t\tif (!item || typeof item !== \"object\") return null;",
  "\t\tconst range = item as Record<string, unknown>;",
  "\t\tif (!Number.isInteger(range.day) || (range.day as number) < 0 || (range.day as number) > 6 || typeof range.startTime !== \"string\" || typeof range.endTime !== \"string\" || !timePattern.test(range.startTime) || !timePattern.test(range.endTime) || timeToMinutes(range.startTime) % 15 !== 0 || timeToMinutes(range.endTime) % 15 !== 0 || timeToMinutes(range.startTime) >= timeToMinutes(range.endTime)) return null;",
  "\t\tschedule.push({ day: range.day as number, startTime: range.startTime, endTime: range.endTime });",
  "\t}",
  "\tschedule.sort((a, b) => a.day - b.day || a.startTime.localeCompare(b.startTime));",
  "\tif (schedule.some((range, index) => index > 0 && range.day === schedule[index - 1].day && range.startTime < schedule[index - 1].endTime)) return null;",
  "\treturn schedule;",
  "}",
  "",
  "export function parseHelloAdaWeeklyAvailability(value: string): BookingWeeklyAvailability[] {",
  "\tlet parsed: unknown;",
  "\ttry { parsed = JSON.parse(value); } catch { throw new Error(\"booking_weekly_availability_invalid\"); }",
  "\tif (!Array.isArray(parsed)) throw new Error(\"booking_weekly_availability_invalid\");",
  "\tif (parsed.length === 0) return [];",
  "\tconst schedule = normalizeHelloAdaWeeklyAvailability(parsed);",
  "\tif (!schedule) throw new Error(\"booking_weekly_availability_invalid\");",
  "\treturn schedule;",
  "}",
].join("\n")

const bookingInputFunction = [
  "export function parseBookingEventInput(value: unknown): BookingEventInput | null {",
  "\tif (!value || typeof value !== \"object\") return null;",
  "\tconst input = value as Record<string, unknown>;",
  "\tconst name = typeof input.name === \"string\" ? input.name.trim() : \"\";",
  "\tconst slug = typeof input.slug === \"string\" ? input.slug.trim().toLowerCase() : slugifyBookingName(name);",
  "\tconst description = typeof input.description === \"string\" ? input.description.trim() : \"\";",
  "\tconst location = typeof input.location === \"string\" ? input.location.trim() : \"\";",
  "\tconst hostIds = input.hostIds === undefined ? [] : input.hostIds;",
  "\tif (!name || name.length > 120 || !isValidBookingSlug(slug) || description.length > 2000 || location.length > 240 || typeof input.durationMinutes !== \"number\" || !Number.isInteger(input.durationMinutes) || input.durationMinutes < 5 || input.durationMinutes > 480) return null;",
  "\tif (!Array.isArray(hostIds) || hostIds.length > 20 || hostIds.some((id) => typeof id !== \"string\" || !id) || new Set(hostIds).size !== hostIds.length) return null;",
  "\tconst weeklyAvailability = normalizeHelloAdaWeeklyAvailability(input.weeklyAvailability);",
  "\tif (!weeklyAvailability || weeklyAvailability.some((range) => timeToMinutes(range.endTime) - timeToMinutes(range.startTime) < (input.durationMinutes as number))) return null;",
  "\tconst weekdays = [...new Set(weeklyAvailability.map((range) => range.day))].sort((a, b) => a - b);",
  "\tconst normalizedRanges = [...new Map(weeklyAvailability.map(({ startTime, endTime }) => [JSON.stringify({ startTime, endTime }), { startTime, endTime }])).values()].sort((a, b) => a.startTime.localeCompare(b.startTime) || a.endTime.localeCompare(b.endTime));",
  "\tif (typeof input.timeZone !== \"string\" || !isValidTimeZone(input.timeZone) || typeof input.enabled !== \"boolean\") return null;",
  "\treturn { name, slug, description, color: normalizeCalendarColor(typeof input.color === \"string\" ? input.color : undefined), hostIds, durationMinutes: input.durationMinutes, location, weekdays, weeklyAvailability, startTime: normalizedRanges[0].startTime, endTime: normalizedRanges[normalizedRanges.length - 1].endTime, timeRanges: normalizedRanges, timeZone: input.timeZone, enabled: input.enabled };",
  "}",
].join("\n")

const slotFunction = [
  "export function slotFromLocalDate(event: BookingEventRecord, localDate: string, time: string): { startsAt: Date; endsAt: Date } | null {",
  "\tif (!/^\\d{4}-\\d{2}-\\d{2}$/.test(localDate) || !timePattern.test(time)) return null;",
  "\tconst wall = new Date(localDate + \"T\" + time + \":00Z\");",
  "\tif (Number.isNaN(wall.getTime()) || wall.toISOString().slice(0, 10) !== localDate) return null;",
  "\tconst minutes = timeToMinutes(time);",
  "\tconst weekday = wall.getUTCDay();",
  "\tconst weeklyAvailability = parseHelloAdaWeeklyAvailability(event.helloadaWeeklyAvailability);",
  "\tconst ranges = weeklyAvailability.length ? weeklyAvailability.filter((range) => range.day === weekday) : event.weekdays.includes(weekday) ? event.timeRanges : [];",
  "\tif (!ranges.some((range) => minutes >= timeToMinutes(range.startTime) && minutes + event.durationMinutes + (event.helloadaBufferMinutes ?? 0) <= timeToMinutes(range.endTime)) || minutes % 15 !== 0) return null;",
  "\tconst startsAt = dateFromZonedFields(wall, event.timeZone);",
  "\tif (zonedDateFields(startsAt, event.timeZone).toISOString().slice(0, 16) !== localDate + \"T\" + time) return null;",
  "\treturn { startsAt, endsAt: new Date(startsAt.getTime() + event.durationMinutes * 60_000) };",
  "}",
].join("\n")

const availabilityImplementation = [
  "function repeatsDuring(event: ExistingCalendarEvent, start: Date, end: Date): boolean {",
  "\tconst first = event.startsAt;",
  "\tconst buffer = Math.max(0, event.helloadaBufferMinutes ?? 0) * 60_000;",
  "\tconst duration = event.endsAt.getTime() - first.getTime() + buffer;",
  "\tif (event.repeat === \"none\") return first < end && event.endsAt.getTime() + buffer > start.getTime();",
  "\tconst zone = event.timeZone || \"UTC\";",
  "\tconst firstWall = zonedDateFields(first, zone);",
  "\tconst candidate = zonedDateFields(new Date(start.getTime() - duration), zone);",
  "\tconst excluded = new Set(parseExcludedOccurrences(event.excludedOccurrences));",
  "\tfor (let offset = 0; offset < Math.ceil(duration / 86_400_000) + 2; offset++) {",
  "\t\tconst day = new Date(candidate);",
  "\t\tday.setUTCDate(day.getUTCDate() + offset);",
  "\t\tday.setUTCHours(firstWall.getUTCHours(), firstWall.getUTCMinutes(), firstWall.getUTCSeconds(), firstWall.getUTCMilliseconds());",
  "\t\tconst days = Math.round((Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate()) - Date.UTC(firstWall.getUTCFullYear(), firstWall.getUTCMonth(), firstWall.getUTCDate())) / 86_400_000);",
  "\t\tif (days < 0) continue;",
  "\t\tconst months = (day.getUTCFullYear() - firstWall.getUTCFullYear()) * 12 + day.getUTCMonth() - firstWall.getUTCMonth();",
  "\t\tconst occurs = event.repeat === \"daily\" || (event.repeat === \"weekly\" && days % 7 === 0) || (event.repeat === \"weekdays\" && parseCalendarRepeatDays(event.repeatDays).includes(day.getUTCDay())) || (event.repeat === \"monthly\" && months >= 0 && day.getUTCDate() === Math.min(event.repeatAnchorDay ?? firstWall.getUTCDate(), new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth() + 1, 0)).getUTCDate()));",
  "\t\tif (!occurs) continue;",
  "\t\tconst occurrence = dateFromZonedFields(day, zone);",
  "\t\tif (occurrence < first || (event.repeatUntil && occurrence >= event.repeatUntil) || excluded.has(occurrence.getTime())) continue;",
  "\t\tif (occurrence < end && occurrence.getTime() + duration > start.getTime()) return true;",
  "\t}",
  "\treturn false;",
  "}",
  "",
  "export async function availableBookingSlots(env: CloudflareEnv, event: BookingEventRecord, days = 14) {",
  "\tif (event.helloadaPayloadManaged && !event.helloadaCalendarEnabled) return [];",
  "\tconst horizon = event.helloadaPayloadManaged ? Math.min(days, event.helloadaBookingWindowDays) : days;",
  "\tconst minimumNotice = event.helloadaPayloadManaged ? event.helloadaMinimumNoticeHours * 60 * 60_000 : 60 * 60_000;",
  "\tconst buffer = Math.max(0, event.helloadaBufferMinutes ?? 0);",
  "\tconst now = new Date();",
  "\tconst today = zonedDateFields(now, event.timeZone);",
  "\ttoday.setUTCHours(0, 0, 0, 0);",
  "\tconst end = new Date(now.getTime() + (horizon + 2) * 86_400_000);",
  "\tconst existingLookback = new Date(now.getTime() - 120 * 60_000);",
  "\tconst existing = await getDb(env).select().from(calendarEvents).where(and(inArray(calendarEvents.userId, event.hostIds), lt(calendarEvents.startsAt, end), or(gt(calendarEvents.endsAt, existingLookback), ne(calendarEvents.repeat, \"none\"))));",
  "\tconst slots: { startsAt: string; endsAt: string; localDate: string; time: string }[] = [];",
  "\tconst weeklyAvailability = parseHelloAdaWeeklyAvailability(event.helloadaWeeklyAvailability);",
  "\tfor (let offset = 0; offset < horizon; offset++) {",
  "\t\tconst day = new Date(today);",
  "\t\tday.setUTCDate(day.getUTCDate() + offset);",
  "\t\tconst weekday = day.getUTCDay();",
  "\t\tconst ranges = weeklyAvailability.length ? weeklyAvailability.filter((range) => range.day === weekday) : event.weekdays.includes(weekday) ? event.timeRanges.map((range) => ({ day: weekday, ...range })) : [];",
  "\t\tif (!ranges.length) continue;",
  "\t\tconst localDate = day.toISOString().slice(0, 10);",
  "\t\tfor (const range of ranges) for (let minute = timeToMinutes(range.startTime); minute + event.durationMinutes + buffer <= timeToMinutes(range.endTime); minute += 15) {",
  "\t\t\tconst hours = String(Math.floor(minute / 60)).padStart(2, \"0\");",
  "\t\t\tconst mins = String(minute % 60).padStart(2, \"0\");",
  "\t\t\tconst time = hours + \":\" + mins;",
  "\t\t\tconst slot = slotFromLocalDate(event, localDate, time);",
  "\t\t\tif (!slot || slot.startsAt.getTime() < now.getTime() + minimumNotice) continue;",
  "\t\t\tconst blockedUntil = new Date(slot.endsAt.getTime() + buffer * 60_000);",
  "\t\t\tif (existing.some((calendarEvent) => repeatsDuring(calendarEvent, slot.startsAt, blockedUntil))) continue;",
  "\t\t\tslots.push({ startsAt: slot.startsAt.toISOString(), endsAt: slot.endsAt.toISOString(), localDate, time });",
  "\t\t}",
  "\t}",
  "\treturn slots;",
  "}",
].join("\n")

export function applyBookingParityPatches(sources, patched) {
  let bookingModelTypes = replaceExactlyOnce(
    sources.bookingModelTypes,
    "export type BookingTimeRange = { startTime: string; endTime: string };",
    "export type BookingTimeRange = { startTime: string; endTime: string };\nexport type BookingWeeklyAvailability = { day: number; startTime: string; endTime: string };",
    "booking core types",
  )
  bookingModelTypes = replaceExactlyOnce(
    bookingModelTypes,
    "export type BookingEventInput = {",
    "export type BookingEventInput = {\n\tweeklyAvailability: BookingWeeklyAvailability[];",
    "booking input schedule type",
  )
  bookingModelTypes = replaceExactlyOnce(
    bookingModelTypes,
    "export type BookingEventRecord = BookingEventInput & {\n\tid: string;\n\tuserId: string;\n};",
    "export type BookingEventRecord = BookingEventInput & {\n\tid: string;\n\tuserId: string;\n\thelloadaBufferMinutes: number;\n\thelloadaWeeklyAvailability: string;\n\thelloadaPayloadManaged: boolean;\n\thelloadaCalendarEnabled: boolean;\n\thelloadaMinimumNoticeHours: number;\n\thelloadaBookingWindowDays: number;\n};",
    "booking integration data types",
  )

  let bookingCoreUtils = replaceExactlyOnce(
    sources.bookingCoreUtils,
    'import type { BookingEventInput, BookingEventRecord, BookingTimeRange } from "./types";',
    'import type { BookingEventInput, BookingEventRecord, BookingTimeRange, BookingWeeklyAvailability } from "./types";',
    "weekly schedule type import",
  )
  bookingCoreUtils = replaceExactlyOnce(
    bookingCoreUtils,
    "export function parseBookingEventInput(value: unknown): BookingEventInput | null {",
    weeklyInputHelpers + "\n\nexport function parseBookingEventInput(value: unknown): BookingEventInput | null {",
    "weekly schedule parser",
  )
  bookingCoreUtils = replaceSection(bookingCoreUtils, "export function parseBookingEventInput(value: unknown): BookingEventInput | null {", "export function timeToMinutes(value: string): number {", bookingInputFunction, "booking input parser")
  bookingCoreUtils = replaceSection(bookingCoreUtils, "export function slotFromLocalDate(event: BookingEventRecord", "export function parseBookingWeekdays(value: string): number[] {", slotFunction, "slot schedule validation")

  let schema = replaceExactlyOnce(
    patched.schema,
    '\t\tbookingConsentAt: integer("booking_consent_at", { mode: "timestamp" }),\n\t\tstartsAt: integer("starts_at", { mode: "timestamp" }).notNull(),',
    '\t\tbookingConsentAt: integer("booking_consent_at", { mode: "timestamp" }),\n\t\thelloadaBufferMinutes: integer("helloada_buffer_minutes").notNull().default(0),\n\t\tstartsAt: integer("starts_at", { mode: "timestamp" }).notNull(),',
    "calendar event buffer schema",
  )
  schema = replaceExactlyOnce(
    schema,
    '\t\tenabled: integer("enabled", { mode: "boolean" }).notNull().default(true),\n\t\tcreatedAt: integer("created_at", { mode: "timestamp" }).notNull().$defaultFn(() => new Date()),',
    '\t\tenabled: integer("enabled", { mode: "boolean" }).notNull().default(true),\n\t\thelloadaBufferMinutes: integer("helloada_buffer_minutes").notNull().default(0),\n\t\thelloadaWeeklyAvailability: text("helloada_weekly_availability").notNull().default("[]"),\n\t\thelloadaCalendarEnabled: integer("helloada_calendar_enabled", { mode: "boolean" }).notNull().default(true),\n\t\thelloadaMinimumNoticeHours: integer("helloada_minimum_notice_hours").notNull().default(24),\n\t\thelloadaBookingWindowDays: integer("helloada_booking_window_days").notNull().default(60),\n\t\thelloadaPayloadManaged: integer("helloada_payload_managed", { mode: "boolean" }).notNull().default(false),\n\t\tcreatedAt: integer("created_at", { mode: "timestamp" }).notNull().$defaultFn(() => new Date()),',
    "booking event Payload settings schema",
  )

  let create = patched.create
  create = replaceExactlyOnce(create, "AND repeat = 'none' AND starts_at < ? AND ends_at > ?", "AND repeat = 'none' AND starts_at < ? AND ends_at + helloada_buffer_minutes * 60 > ?", "booking conflict buffer")
  create = replaceExactlyOnce(create, "\t\tendSeconds,\n\t\tstartSeconds,", "\t\tendSeconds + event.helloadaBufferMinutes * 60,\n\t\tstartSeconds,", "booking candidate buffer boundary")
  create = replaceExactlyOnce(create, "booking_request_hash, booking_consent_at, created_at, updated_at)", "booking_request_hash, booking_consent_at, helloada_buffer_minutes, created_at, updated_at)", "booking buffer persistence column")
  create = replaceExactlyOnce(create, "?, ?, ?, ?, ?, ?, ?, ? FROM requested_hosts CROSS JOIN conflicts", "?, ?, ?, ?, ?, ?, ?, ?, ? FROM requested_hosts CROSS JOIN conflicts", "booking buffer persistence value")
  create = replaceExactlyOnce(create, "\t\trequestHash,\n\t\tnowSeconds,", "\t\trequestHash,\n\t\tevent.helloadaBufferMinutes,\n\t\tnowSeconds,", "booking buffer binding")

  const availability = replaceExactlyOnce(sources.availability, 'import { slotFromLocalDate, timeToMinutes } from "./utils";', 'import { parseHelloAdaWeeklyAvailability, slotFromLocalDate, timeToMinutes } from "./utils";', "availability schedule import")
  const finalAvailability = replaceTail(availability, "function repeatsDuring(", availabilityImplementation, "calendar conflict and availability policy")
  const bookingCreateRoute = replaceExactlyOnce(
    sources.bookingCreateRoute,
    "hostIds: JSON.stringify(hostIds), weekdays: JSON.stringify(input.weekdays), timeRanges: JSON.stringify(input.timeRanges) }).returning();",
    "hostIds: JSON.stringify(hostIds), weekdays: JSON.stringify(input.weekdays), timeRanges: JSON.stringify(input.timeRanges), helloadaWeeklyAvailability: JSON.stringify(input.weeklyAvailability) }).returning();",
    "booking create schedule",
  )
  const bookingUpdateRoute = replaceExactlyOnce(
    sources.bookingUpdateRoute,
    "hostIds: JSON.stringify(hostIds), weekdays: JSON.stringify(input.weekdays), timeRanges: JSON.stringify(input.timeRanges), updatedAt: new Date() }).where",
    "hostIds: JSON.stringify(hostIds), weekdays: JSON.stringify(input.weekdays), timeRanges: JSON.stringify(input.timeRanges), helloadaWeeklyAvailability: JSON.stringify(input.weeklyAvailability), updatedAt: new Date() }).where",
    "booking update schedule",
  )

  return { ...patched, bookingModelTypes, bookingCoreUtils, availability: finalAvailability, schema, create, bookingCreateRoute, bookingUpdateRoute }
}
