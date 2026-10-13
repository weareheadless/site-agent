import { dateFromZonedFields, isValidTimeZone, zonedDateFields } from "@/lib/time/utils";
import {
  parseBookingHours,
  readBookingSettings,
  resolveTenantBookingOwner,
  settingsFromRow,
  type BookingD1,
  type BookingSettings,
  type BookingType,
} from "@/lib/helloada-booking-service";

type CalendarRow = {
  id: string;
  starts_at: number;
  ends_at: number;
  repeat: string;
  repeat_days: string;
  repeat_anchor_day: number | null;
  repeat_until: number | null;
  excluded_occurrences: string;
  time_zone: string | null;
  helloada_buffer_minutes: number;
  helloada_state: string | null;
};
type BusyInterval = { start: number; end: number };
type Snapshot = { ownerId: string; settings: BookingSettings; type: BookingType; busy: BusyInterval[] };
export type PublicBookingSlot = { startsAt: string; endsAt: string; localDate: string; time: string };
type PublicBookingDetails = { id: string; name: string; description: string; durationMinutes: number; timeZone: string; bookingWindowDays: number; slots: PublicBookingSlot[]; turnstileSiteKey: string };
type BookingInput = { startsAt: string; name: string; email: string; notes: string; requestId: string; consent: true; sourcePage: string };
type MailboxRow = { id: string; user_id: string; disabled: number; status: string; local_part: string; hostname: string };
const timePattern = /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/;
const minutes = (value: string) => Number(value.slice(0, 2)) * 60 + Number(value.slice(3));
const canceled = new Set(["cancelled", "canceled", "deleted", "declined"]);
const rowAt = <T,>(result: { results?: unknown[] }, index: number): T | null => (result.results?.[index] as T | undefined) ?? null;

function recurrenceIntervals(row: CalendarRow, rangeStart: number, rangeEnd: number): BusyInterval[] {
  const start = Number(row.starts_at);
  const end = Number(row.ends_at);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) throw new Error("booking_calendar_event_invalid");
  if (canceled.has(String(row.helloada_state || "").toLowerCase())) return [];
  const buffer = Math.max(0, Number(row.helloada_buffer_minutes) || 0) * 60_000;
  const duration = end - start;
  if (row.repeat === "none") return start < rangeEnd && end + buffer > rangeStart ? [{ start, end: end + buffer }] : [];

  const zone = String(row.time_zone || "UTC");
  if (!isValidTimeZone(zone)) throw new Error("booking_calendar_event_timezone_invalid");
  const firstWall = zonedDateFields(new Date(start), zone);
  const target = zonedDateFields(new Date(Math.max(rangeStart - duration - 172_800_000, start)), zone);
  target.setUTCHours(0, 0, 0, 0);
  const anchor = new Date(firstWall);
  anchor.setUTCHours(0, 0, 0, 0);
  const day = new Date(Math.max(target.getTime(), anchor.getTime()));
  const repeatDays = (() => { try { const v: unknown = JSON.parse(row.repeat_days || "[]"); return Array.isArray(v) ? v.filter((n): n is number => Number.isInteger(n) && n >= 0 && n <= 6) : []; } catch { throw new Error("booking_calendar_repeat_invalid"); } })();
  const excluded = (() => { try { const v: unknown = JSON.parse(row.excluded_occurrences || "[]"); return new Set(Array.isArray(v) ? v.filter((n): n is number => Number.isSafeInteger(n) && n >= 0) : []); } catch { throw new Error("booking_calendar_exclusions_invalid"); } })();
  const until = row.repeat_until == null ? Infinity : Number(row.repeat_until);
  const intervals: BusyInterval[] = [];
  for (let index = 0; day.getTime() <= rangeEnd + 172_800_000 && index < 370; index++, day.setUTCDate(day.getUTCDate() + 1)) {
    const daysFromAnchor = Math.round((day.getTime() - anchor.getTime()) / 86_400_000);
    const monthDelta = (day.getUTCFullYear() - anchor.getUTCFullYear()) * 12 + day.getUTCMonth() - anchor.getUTCMonth();
    const monthlyDay = Math.min(row.repeat_anchor_day ?? firstWall.getUTCDate(), new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth() + 1, 0)).getUTCDate());
    const occurs = row.repeat === "daily"
      || (row.repeat === "weekly" && daysFromAnchor >= 0 && daysFromAnchor % 7 === 0)
      || (row.repeat === "weekdays" && repeatDays.includes(day.getUTCDay()))
      || (row.repeat === "monthly" && monthDelta >= 0 && day.getUTCDate() === monthlyDay);
    if (!occurs) continue;
    const localFields = new Date(day);
    localFields.setUTCHours(firstWall.getUTCHours(), firstWall.getUTCMinutes(), firstWall.getUTCSeconds(), firstWall.getUTCMilliseconds());
    const occurrence = dateFromZonedFields(localFields, zone);
    if (occurrence.getTime() < start || occurrence.getTime() >= until || excluded.has(occurrence.getTime())) continue;
    const occurrenceEnd = occurrence.getTime() + duration + buffer;
    if (occurrence.getTime() < rangeEnd && occurrenceEnd > rangeStart) intervals.push({ start: occurrence.getTime(), end: occurrenceEnd });
  }
  return intervals;
}

function hasCapacity(start: number, end: number, busy: BusyInterval[], capacity: number): boolean {
  const points = [start, ...busy.filter((item) => item.start >= start && item.start < end).map((item) => item.start)];
  return points.every((point) => busy.reduce((count, item) => count + (item.start <= point && item.end > point ? 1 : 0), 0) < capacity);
}

export type CalendarCapacityCandidate = {
  id?: string;
  startsAt: number | Date;
  endsAt: number | Date;
  repeat?: string;
  repeatDays?: string;
  repeatAnchorDay?: number | null;
  repeatUntil?: number | Date | null;
  excludedOccurrences?: string;
  timeZone?: string | null;
  bufferMinutes?: number;
  state?: string | null;
};

const timestamp = (value: number | Date | null | undefined) =>
  value instanceof Date ? value.getTime() : value == null ? null : Number(value);

export function calendarCapacityCandidate(event: {
  startsAt: Date; endsAt: Date; repeat?: string; repeatDays?: string; repeatAnchorDay?: number | null;
  repeatUntil?: Date | null; excludedOccurrences?: string; timeZone?: string | null;
  helloadaBufferMinutes?: number | null; helloadaState?: string | null;
}): CalendarCapacityCandidate {
  return {
    startsAt: event.startsAt, endsAt: event.endsAt, repeat: event.repeat || "none",
    repeatDays: event.repeatDays || "[]", repeatAnchorDay: event.repeatAnchorDay ?? null,
    repeatUntil: event.repeatUntil ?? null, excludedOccurrences: event.excludedOccurrences || "[]",
    timeZone: event.timeZone || "UTC", bufferMinutes: event.helloadaBufferMinutes || 0,
    state: event.helloadaState || null,
  };
}

export function isCalendarCapacityConflict(error: unknown): boolean {
  return error instanceof Error && ["calendar_capacity_exceeded", "helloada_capacity_revision_conflict", "booking_settings_revision_conflict"].some((code) => error.message.includes(code));
}

async function loadBusyIntervals(db: BookingD1, userId: string, rangeStart: number, rangeEnd: number, excludedIds: string[] = []): Promise<BusyInterval[]> {
  const result = await db.prepare(
    "SELECT id,starts_at,ends_at,repeat,repeat_days,repeat_anchor_day,repeat_until,excluded_occurrences,time_zone,helloada_buffer_minutes,helloada_state FROM calendar_events WHERE user_id=? AND starts_at<? AND (repeat<>'none' OR ends_at+helloada_buffer_minutes*60000>?)",
  ).bind(userId, rangeEnd, rangeStart).all<CalendarRow>();
  const rows = result.results ?? [];
  if (rows.length > 5000) throw new Error("booking_calendar_event_limit_exceeded");
  const ignored = new Set(excludedIds);
  return rows.filter((row) => !ignored.has(row.id)).flatMap((row) => recurrenceIntervals(row, rangeStart, rangeEnd));
}

function countOverCapacityWindows(intervals: BusyInterval[], capacity: number): number {
  const boundaries = intervals.flatMap((interval) => [
    { at: interval.start, delta: 1 }, { at: interval.end, delta: -1 },
  ]).sort((a, b) => a.at - b.at || a.delta - b.delta);
  let active = 0;
  let previous: number | null = null;
  let inOverCapacityWindow = false;
  let windows = 0;
  for (let index = 0; index < boundaries.length;) {
    const at = boundaries[index].at;
    if (previous !== null && previous < at) {
      const overCapacity = active > capacity;
      if (overCapacity && !inOverCapacityWindow) windows++;
      inOverCapacityWindow = overCapacity;
    }
    let delta = 0;
    while (index < boundaries.length && boundaries[index].at === at) delta += boundaries[index++].delta;
    active += delta;
    previous = at;
  }
  return windows;
}

export async function getBookingCapacityWarnings(db: BookingD1, userId: string, capacity?: number) {
  const settings = await readBookingSettings(db, userId);
  const maxConcurrentAppointments = capacity ?? settings.maxConcurrentAppointments;
  if (!Number.isInteger(maxConcurrentAppointments) || maxConcurrentAppointments < 1 || maxConcurrentAppointments > 50) {
    throw new Error("booking_capacity_invalid");
  }
  const rangeStart = Date.now();
  const rangeEnd = rangeStart + settings.bookingWindowDays * 86_400_000 + 172_800_000;
  const busy = await loadBusyIntervals(db, userId, rangeStart, rangeEnd);
  return {
    overlappingPeriods: countOverCapacityWindows(busy, maxConcurrentAppointments),
    maxConcurrentAppointments,
    horizonDays: settings.bookingWindowDays,
  };
}

export async function assertCalendarMutationCapacity(
  db: BookingD1, userId: string, candidates: CalendarCapacityCandidate[], excludedIds: string[] = [],
): Promise<number> {
  const settings = await readBookingSettings(db, userId);
  if (!settings.enabled || candidates.length === 0) return settings.revision;
  const rangeStart = Date.now();
  const rangeEnd = rangeStart + settings.bookingWindowDays * 86_400_000 + 172_800_000;
  const busy = await loadBusyIntervals(db, userId, rangeStart, rangeEnd, excludedIds);
  for (const candidate of candidates) {
    const row: CalendarRow = {
      id: candidate.id || "candidate",
      starts_at: Number(timestamp(candidate.startsAt)),
      ends_at: Number(timestamp(candidate.endsAt)),
      repeat: candidate.repeat || "none",
      repeat_days: candidate.repeatDays || "[]",
      repeat_anchor_day: candidate.repeatAnchorDay ?? null,
      repeat_until: timestamp(candidate.repeatUntil),
      excluded_occurrences: candidate.excludedOccurrences || "[]",
      time_zone: candidate.timeZone || "UTC",
      helloada_buffer_minutes: candidate.bufferMinutes || 0,
      helloada_state: candidate.state || null,
    };
    const intervals = recurrenceIntervals(row, rangeStart, rangeEnd);
    for (const interval of intervals) {
      if (!hasCapacity(interval.start, interval.end, busy, settings.maxConcurrentAppointments)) {
        throw new Error("calendar_capacity_exceeded");
      }
      busy.push(interval);
    }
  }
  return settings.revision;
}

function slotsFor(settings: BookingSettings, type: BookingType, busy: BusyInterval[], localDate: string, now = new Date()): PublicBookingSlot[] {
  if (!settings.enabled || !type.enabled || !settings.timeZone || !settings.weeklyAvailability.length) return [];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(localDate)) throw new Error("booking_date_invalid");
  const target = new Date(localDate + "T00:00:00.000Z");
  if (!Number.isFinite(target.getTime()) || target.toISOString().slice(0, 10) !== localDate) throw new Error("booking_date_invalid");
  const zone = settings.timeZone;
  if (!isValidTimeZone(zone)) throw new Error("booking_settings_timezone_invalid");
  const today = zonedDateFields(now, zone);
  today.setUTCHours(0, 0, 0, 0);
  const offset = Math.round((target.getTime() - today.getTime()) / 86_400_000);
  if (offset < 0 || offset >= settings.bookingWindowDays) return [];
  const weekday = target.getUTCDay();
  const slots: PublicBookingSlot[] = [];
  for (const range of settings.weeklyAvailability.filter((item) => item.day === weekday)) {
    const close = minutes(range.endTime);
    for (let minute = minutes(range.startTime); minute + type.durationMinutes <= close; minute += 15) {
      const hh = String(Math.floor(minute / 60)).padStart(2, "0");
      const mm = String(minute % 60).padStart(2, "0");
      const time = hh + ":" + mm;
      const localFields = new Date(target);
      localFields.setUTCHours(Math.floor(minute / 60), minute % 60, 0, 0);
      const startsAt = dateFromZonedFields(localFields, zone);
      if (zonedDateFields(startsAt, zone).toISOString().slice(0, 16) !== localDate + "T" + time) continue;
      const endsAt = new Date(startsAt.getTime() + type.durationMinutes * 60_000);
      if (startsAt.getTime() < now.getTime() + settings.minimumNoticeHours * 3_600_000) continue;
      if (hasCapacity(startsAt.getTime(), endsAt.getTime(), busy, settings.maxConcurrentAppointments)) {
        slots.push({ startsAt: startsAt.toISOString(), endsAt: endsAt.toISOString(), localDate, time });
      }
    }
  }
  return slots;
}

async function loadSnapshot(db: BookingD1, tenantId: string, identifier: string, dateValue?: string): Promise<Snapshot & { localDate: string }> {
  const ownerId = await resolveTenantBookingOwner(db, tenantId);
  const results = await db.batch([
    db.prepare("SELECT enabled,time_zone,weekly_availability,max_concurrent_appointments,minimum_notice_hours,booking_window_days,revision,updated_at FROM helloada_booking_settings WHERE user_id=? LIMIT 1").bind(ownerId),
    db.prepare("SELECT id,slug,name,description,duration_minutes,enabled,helloada_revision FROM booking_events WHERE user_id=? AND id=? LIMIT 1").bind(ownerId, identifier),
  ]);
  const settingsRow = rowAt<Record<string, unknown>>(results[0], 0);
  const typeRow = rowAt<Record<string, unknown>>(results[1], 0);
  if (!settingsRow) throw new Error("booking_settings_not_provisioned");
  if (!typeRow || Number(typeRow.enabled) !== 1) throw new Error("booking_type_not_found");
  const settings = settingsFromRow(settingsRow);
  const type: BookingType = {
    id: String(typeRow.id), slug: String(typeRow.slug), name: String(typeRow.name),
    description: String(typeRow.description || ""), durationMinutes: Number(typeRow.duration_minutes),
    enabled: Number(typeRow.enabled) === 1, revision: Number(typeRow.helloada_revision),
  };
  const zone = String(settings.timeZone || "");
  if (!zone || !isValidTimeZone(zone)) throw new Error("booking_settings_timezone_invalid");
  let localDate = "";
  if (dateValue) {
    if (/^\d{4}-\d{2}-\d{2}$/.test(dateValue)) localDate = dateValue;
    else if (Number.isFinite(Date.parse(dateValue))) localDate = zonedDateFields(new Date(dateValue), zone).toISOString().slice(0, 10);
    else throw new Error("booking_date_invalid");
  }
  let busy: BusyInterval[] = [];
  if (localDate) {
    const target = new Date(localDate + "T00:00:00.000Z");
    if (!Number.isFinite(target.getTime()) || target.toISOString().slice(0, 10) !== localDate) throw new Error("booking_date_invalid");
    const nextDay = new Date(target);
    nextDay.setUTCDate(nextDay.getUTCDate() + 1);
    const localStart = dateFromZonedFields(target, zone).getTime();
    const localEnd = dateFromZonedFields(nextDay, zone).getTime();
    const eventResult = await db.prepare(
      "SELECT id,starts_at,ends_at,repeat,repeat_days,repeat_anchor_day,repeat_until,excluded_occurrences,time_zone,helloada_buffer_minutes,helloada_state FROM calendar_events WHERE user_id=? AND starts_at<? AND (repeat<>'none' OR ends_at+helloada_buffer_minutes*60000>?)",
    ).bind(ownerId, Math.ceil(localEnd), Math.floor(localStart)).all<CalendarRow>();
    const eventRows = eventResult.results ?? [];
    if (eventRows.length > 5000) throw new Error("booking_calendar_event_limit_exceeded");
    busy = eventRows.flatMap((row) => recurrenceIntervals(row, localStart, localEnd));
  }
  return { ownerId, settings, type, busy, localDate };
}

export async function getPublicBookingDetails(
  db: BookingD1, tenantId: string, identifier: string, localDate: string | undefined, turnstileSiteKey: string,
): Promise<PublicBookingDetails> {
  const snapshot = await loadSnapshot(db, tenantId, identifier, localDate);
  if (!snapshot.settings.enabled) throw new Error("booking_settings_disabled");
  const slots = localDate ? slotsFor(snapshot.settings, snapshot.type, snapshot.busy, snapshot.localDate) : [];
  return {
    id: snapshot.type.id, name: snapshot.type.name,
    description: snapshot.type.description, durationMinutes: snapshot.type.durationMinutes,
    timeZone: snapshot.settings.timeZone, bookingWindowDays: snapshot.settings.bookingWindowDays,
    slots, turnstileSiteKey,
  };
}

const sha256 = async (value: string) => {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)));
  return [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
};
const clean = (value: string) => value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "").trim();

async function existingRequest(db: BookingD1, ownerId: string, requestId: string) {
  return db.prepare("SELECT id,booking_request_hash FROM calendar_events WHERE user_id=? AND booking_request_id=? LIMIT 1")
    .bind(ownerId, requestId).first<{ id: string; booking_request_hash: string | null }>();
}

async function submitOnce(db: BookingD1, tenantId: string, mailboxAddress: string, identifier: string, input: BookingInput) {
  const ownerId = await resolveTenantBookingOwner(db, tenantId);
  const requestHash = await sha256(JSON.stringify({
    typeId: identifier, startsAt: input.startsAt, name: input.name,
    email: input.email, notes: input.notes, consent: input.consent,
  }));
  const existing = await existingRequest(db, ownerId, input.requestId);
  if (existing) {
    if (existing.booking_request_hash !== requestHash) throw new Error("booking_request_id_conflict");
    return { state: "duplicate" as const, eventId: existing.id };
  }
  const snapshot = await loadSnapshot(db, tenantId, identifier, input.startsAt);
  if (snapshot.ownerId !== ownerId) throw new Error("booking_owner_identity_changed");
  if (!snapshot.settings.enabled) throw new Error("booking_settings_disabled");
  const slot = slotsFor(snapshot.settings, snapshot.type, snapshot.busy, snapshot.localDate).find((item) => item.startsAt === input.startsAt);
  if (!slot) return { state: "unavailable" as const };
  const address = mailboxAddress.trim().toLowerCase();
  const mailbox = await db.prepare(
    "SELECT m.id,m.user_id,m.disabled,d.status,m.local_part,d.hostname FROM mailboxes m INNER JOIN domains d ON d.id=m.domain_id WHERE lower(m.local_part || '@' || d.hostname)=? LIMIT 1",
  ).bind(address).first<MailboxRow>();
  if (!mailbox || mailbox.disabled || mailbox.status !== "active") throw new Error("booking_mailbox_not_active");

  const eventId = "ha_booking_event_" + (await sha256(tenantId + ":" + input.requestId)).slice(0, 30);
  const messageId = "ha_booking_message_" + (await sha256(tenantId + ":" + input.requestId)).slice(0, 30);
  const contactId = "ha_booking_contact_" + (await sha256(mailbox.user_id + ":" + input.email)).slice(0, 30);
  const startMilliseconds = Date.parse(slot.startsAt);
  const endMilliseconds = Date.parse(slot.endsAt);
  const nowMilliseconds = Date.now();
  const nowSeconds = Math.floor(nowMilliseconds / 1000);
  const timeLabel = new Intl.DateTimeFormat("en", { dateStyle: "full", timeStyle: "short", timeZone: snapshot.settings.timeZone }).format(new Date(slot.startsAt));
  const subject = ("Website appointment: " + snapshot.type.name).slice(0, 180);
  const textBody = [
    "Appointment: " + snapshot.type.name,
    "When: " + timeLabel + " (" + snapshot.settings.timeZone + ")",
    "Duration: " + snapshot.type.durationMinutes + " minutes",
    "Name: " + input.name,
    "Email: " + input.email,
    input.notes ? "Notes: " + input.notes : "",
    input.sourcePage ? "Page: " + input.sourcePage : "",
  ].filter(Boolean).join("\n");
  const title = (snapshot.type.name + " - " + input.name).slice(0, 180);
  const bookingSql = `INSERT INTO calendar_events
    (id,user_id,mailbox_id,title,description,location,attendees,color,repeat,repeat_days,excluded_occurrences,time_zone,starts_at,ends_at,booking_request_id,booking_request_hash,booking_consent_at,helloada_state,helloada_receipt_id,helloada_answers,helloada_consent_accepted_at,helloada_notification_state,helloada_notification_lease_until,helloada_buffer_minutes,helloada_booking_type_id,helloada_booking_type_name,helloada_booking_duration_minutes,helloada_contact_id,helloada_capacity_revision,created_at,updated_at)
    SELECT ?,?,?,?,?,'','[]','#f28b55','none','[]','[]',?,?,?,?,?,?, 'confirmed',?,?,?, 'pending',NULL,0,?,?,?,NULL,?,?,?
    WHERE EXISTS (SELECT 1 FROM helloada_booking_settings WHERE user_id=? AND enabled=1 AND revision=?)
      AND EXISTS (SELECT 1 FROM booking_events WHERE user_id=? AND id=? AND enabled=1 AND helloada_revision=?)
`;
  const bookingStatement = db.prepare(bookingSql).bind(
    eventId, snapshot.ownerId, mailbox.id, title, input.notes,
    snapshot.settings.timeZone, startMilliseconds, endMilliseconds, input.requestId, requestHash, nowSeconds, eventId, JSON.stringify({ name: input.name, email: input.email, notes: input.notes, sourcePage: input.sourcePage }), nowSeconds,
    snapshot.type.id, snapshot.type.name, snapshot.type.durationMinutes, snapshot.settings.revision, nowSeconds, nowSeconds,
    snapshot.ownerId, snapshot.settings.revision,
    snapshot.ownerId, snapshot.type.id, snapshot.type.revision,
  );
  const contactStatement = db.prepare(
    `INSERT INTO contacts (id,user_id,email,display_name,source,last_seen_at,created_at)
     SELECT ?,?,?,?,'inbound',?,? WHERE EXISTS (SELECT 1 FROM calendar_events WHERE user_id=? AND booking_request_id=? AND booking_request_hash=?)
     ON CONFLICT(user_id,email) DO UPDATE SET
       display_name=CASE WHEN contacts.source='manual' OR contacts.display_name IS NOT NULL THEN contacts.display_name ELSE excluded.display_name END,
       source=CASE WHEN contacts.source IN ('manual','outbound') THEN contacts.source ELSE 'inbound' END,
       last_seen_at=excluded.last_seen_at`,
  ).bind(contactId, mailbox.user_id, input.email, input.name, nowSeconds, nowSeconds, snapshot.ownerId, input.requestId, requestHash);
  const linkStatement = db.prepare(
    "UPDATE calendar_events SET helloada_contact_id=(SELECT id FROM contacts WHERE user_id=? AND email=? LIMIT 1) WHERE user_id=? AND booking_request_id=? AND booking_request_hash=?",
  ).bind(mailbox.user_id, input.email, snapshot.ownerId, input.requestId, requestHash);
  const messageStatement = db.prepare(
    `INSERT INTO messages (id,user_id,mailbox_id,direction,provider_message_id,from_addr,to_addr,subject,snippet,text_body,status,thread_id,helloada_contact_id,helloada_delivery_state,helloada_source_page,created_at)
     SELECT ?,?,?,'inbound',?,?,?,?,?,?,'received',?,(SELECT id FROM contacts WHERE user_id=? AND email=? LIMIT 1),'received',?,?
     WHERE EXISTS (SELECT 1 FROM calendar_events WHERE user_id=? AND booking_request_id=? AND booking_request_hash=?)`,
  ).bind(
    messageId, mailbox.user_id, mailbox.id, "helloada-booking:" + tenantId + ":" + input.requestId,
    input.email, address, subject, textBody.slice(0, 240), textBody, messageId,
    mailbox.user_id, input.email, input.sourcePage || null, nowSeconds,
    snapshot.ownerId, input.requestId, requestHash,
  );
  const results = await db.batch([bookingStatement, contactStatement, linkStatement, messageStatement]);
  if (results[0]?.meta?.changes === 1) return { state: "created" as const, eventId, userId: mailbox.user_id, mailboxId: mailbox.id, fromAddress: address, typeName: snapshot.type.name, timeZone: snapshot.settings.timeZone, durationMinutes: snapshot.type.durationMinutes };
  const after = await existingRequest(db, snapshot.ownerId, input.requestId);
  if (after) {
    if (after.booking_request_hash !== requestHash) throw new Error("booking_request_id_conflict");
    return { state: "duplicate" as const, eventId: after.id };
  }
  const current = await db.prepare("SELECT revision FROM helloada_booking_settings WHERE user_id=? LIMIT 1").bind(snapshot.ownerId).first<{ revision: number }>();
  return { state: current && Number(current.revision) !== snapshot.settings.revision ? "changed" as const : "unavailable" as const };
}

export async function createPublicBooking(db: BookingD1, tenantId: string, mailboxAddress: string, identifier: string, input: BookingInput) {
  for (let attempt = 0; attempt < 4; attempt++) {
    const result = await submitOnce(db, tenantId, mailboxAddress, identifier, input);
    if (result.state === "created" || result.state === "duplicate") return result;
    if (result.state === "unavailable") return result;
  }
  throw new Error("booking_capacity_changed");
}
