const replaceExactlyOnce = (source, before, after, filename) => {
  const index = source.indexOf(before)
  if (index < 0 || source.indexOf(before, index + before.length) !== -1) {
    throw new Error("Pinned Mailflare booking patch no longer applies exactly once: " + filename)
  }
  return source.slice(0, index) + after + source.slice(index + before.length)
}

const replaceTail = (source, start, replacement, filename) => {
  const index = source.indexOf(start)
  if (index < 0 || source.indexOf(start, index + start.length) !== -1) {
    throw new Error("Pinned Mailflare booking patch no longer applies exactly once: " + filename)
  }
  return source.slice(0, index) + replacement + "\n"
}

const bookingGetRoute = [
  'export async function GET(request: Request, { params }: PublicBookingRouteContext) {',
  '\tconst { eventId } = await params;',
  '\tconst found = await loadPublicBookingEvent(eventId, new URL(request.url).searchParams.get("username"));',
  '\tif (!found) return NextResponse.json({ error: "Booking event not found" }, { status: 404 });',
  '\tconst env = getEnv();',
  '\tif (!env.TURNSTILE_SITE_KEY) return NextResponse.json({ error: "Booking security is not configured" }, { status: 503 });',
  '\tconst horizon = found.event.helloadaPayloadManaged ? found.event.helloadaBookingWindowDays : 60;',
  '\tconst slots = await availableBookingSlots(env, found.event, horizon);',
  '\treturn NextResponse.json({ event: found.event, hostName: found.hostName, slots, turnstileSiteKey: env.TURNSTILE_SITE_KEY });',
  '}',
].join("\n")

const bookingPostRoute = [
  'export async function POST(request: Request, { params }: PublicBookingRouteContext) {',
  '\tconst env = getEnv();',
  '\tif (request.headers.get("origin") !== new URL(request.url).origin) return NextResponse.json({ error: "Booking request origin is invalid." }, { status: 403 });',
  '\tconst clientIp = request.headers.get("cf-connecting-ip")?.trim();',
  '\tif (!clientIp || !env.BOOKING_RATE_LIMIT || !env.TURNSTILE_SECRET_KEY || !env.TURNSTILE_SITE_KEY) return NextResponse.json({ error: "Online booking is not configured." }, { status: 503 });',
  '\ttry {',
  '\t\tconst allowed = await env.BOOKING_RATE_LIMIT.limit({ key: clientIp });',
  '\t\tif (!allowed.success) return NextResponse.json({ error: "Too many booking attempts. Please try again shortly." }, { status: 429 });',
  '\t} catch {',
  '\t\treturn NextResponse.json({ error: "Online booking is temporarily unavailable." }, { status: 503 });',
  '\t}',
  '\tconst contentType = request.headers.get("content-type")?.split(";")[0].trim().toLowerCase();',
  '\tif (contentType !== "application/json") return NextResponse.json({ error: "Booking request must be JSON." }, { status: 415 });',
  '\tconst rawBody = await request.text();',
  '\tif (rawBody.length > 8192) return NextResponse.json({ error: "Booking request is too large." }, { status: 413 });',
  '\tlet body: PublicBookingSubmission | null = null;',
  '\ttry { body = JSON.parse(rawBody) as PublicBookingSubmission; } catch { return NextResponse.json({ error: "Booking request is invalid." }, { status: 400 }); }',
  '\tif (!body || typeof body !== "object" || Array.isArray(body)) return NextResponse.json({ error: "Booking request is invalid." }, { status: 400 });',
  '\tif (typeof body.website === "string" && body.website.trim()) return NextResponse.json({ booked: true });',
  '\tif (body.website !== undefined && typeof body.website !== "string") return NextResponse.json({ error: "Booking request is invalid." }, { status: 400 });',
  '\tif (body.consent !== true) return NextResponse.json({ error: "Please confirm the booking privacy notice." }, { status: 400 });',
  '\tif (typeof body.requestId !== "string" || !/^[a-zA-Z0-9_-]{16,80}$/.test(body.requestId)) return NextResponse.json({ error: "Booking request is missing its request identifier." }, { status: 400 });',
  '\tif (!(await verifyTurnstileToken(env, request, body.turnstileToken))) return NextResponse.json({ error: "Complete the security check and try again." }, { status: 400 });',
  '\tconst { eventId } = await params;',
  '\tconst found = await loadPublicBookingEvent(eventId, new URL(request.url).searchParams.get("username"));',
  '\tif (!found) return NextResponse.json({ error: "Booking event not found" }, { status: 404 });',
  '\tconst name = typeof body.name === "string" ? body.name.trim() : "";',
  '\tconst email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";',
  '\tif (!name || name.length > 120 || !/^\\S+@\\S+\\.\\S+$/.test(email) || email.length > 254 || typeof body.startsAt !== "string") return NextResponse.json({ error: "Enter your name, email, and a time." }, { status: 400 });',
  '\tconst guestEmails = parseBookingGuestEmails(body.guestEmails, email);',
  '\tconst notes = typeof body.notes === "string" ? body.notes.trim() : "";',
  '\tif (!guestEmails || notes.length > 2000 || (body.notes !== undefined && typeof body.notes !== "string")) return NextResponse.json({ error: "Check the guest emails and meeting notes." }, { status: 400 });',
  '\tconst requestHash = await bookingRequestHash({ eventId, startsAt: body.startsAt, name, email, guestEmails, notes, consent: true });',
  '\tconst previous = await existingBookingRequest(env, found.event, body.requestId, requestHash);',
  '\tif (previous === true) return NextResponse.json({ booked: true, startsAt: body.startsAt });',
  '\tif (previous === false) return NextResponse.json({ error: "This booking request identifier was already used for different details." }, { status: 409 });',
  '\tconst horizon = found.event.helloadaPayloadManaged ? found.event.helloadaBookingWindowDays : 60;',
  '\tconst slots = await availableBookingSlots(env, found.event, horizon);',
  '\tconst slot = slots.find((item) => item.startsAt === body.startsAt);',
  '\tif (!slot) return NextResponse.json({ error: "That time is no longer available." }, { status: 409 });',
  '\tif (!(await createBookedCalendarEvents(env, found.event, name, email, slot.startsAt, slot.endsAt, body.requestId, requestHash, guestEmails, notes))) return NextResponse.json({ error: "That time is no longer available." }, { status: 409 });',
  '\treturn NextResponse.json({ booked: true, startsAt: slot.startsAt, endsAt: slot.endsAt });',
  '}',
].join("\n")

const patchedCreateFunction = [
  'export async function bookingRequestHash(value: Record<string, unknown>): Promise<string> {',
  '\tconst bytes = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(value))));',
  '\treturn [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");',
  '}',
  '',
  'export async function existingBookingRequest(env: CloudflareEnv, event: BookingEventRecord, requestId: string, requestHash: string): Promise<boolean | null> {',
  '\tconst hostIds = event.hostIds;',
  '\tconst placeholders = hostIds.map(() => "?").join(", ");',
  '\tconst result = await env.DB.prepare("SELECT user_id, booking_request_hash FROM calendar_events WHERE booking_request_id = ? AND user_id IN (" + placeholders + ")").bind(requestId, ...hostIds).all<{ user_id: string; booking_request_hash: string | null }>();',
  '\tconst rows = result.results ?? [];',
  '\tif (rows.length === 0) return null;',
  '\tconst complete = rows.length === hostIds.length && hostIds.every((id) => rows.some((row) => row.user_id === id && row.booking_request_hash === requestHash));',
  '\treturn complete;',
  '}',
  '',
  'export async function createBookedCalendarEvents(env: CloudflareEnv, event: BookingEventRecord, guestName: string, guestEmail: string, startsAt: string, endsAt: string, requestId: string, requestHash: string, guestEmails: string[] = [], notes = ""): Promise<boolean> {',
  '\tconst hostIds = event.hostIds;',
  '\tconst startSeconds = Math.floor(new Date(startsAt).getTime() / 1000);',
  '\tconst endSeconds = Math.floor(new Date(endsAt).getTime() / 1000);',
  '\tconst nowSeconds = Math.floor(Date.now() / 1000);',
  '\tconst selectedHosts = hostIds.map(() => "(?, ?)").join(", ");',
  '\tconst hostPlaceholders = hostIds.map(() => "?").join(", ");',
  '\tconst sql = "WITH requested_hosts(host_id, event_id) AS (VALUES " + selectedHosts + "), " +',
  '\t\t"conflicts AS MATERIALIZED (SELECT COUNT(*) AS total FROM calendar_events WHERE user_id IN (" + hostPlaceholders + ") AND repeat = \'none\' AND starts_at < ? AND ends_at > ?) " +',
  '\t\t"INSERT INTO calendar_events (id, user_id, mailbox_id, title, description, location, attendees, color, repeat, repeat_days, excluded_occurrences, time_zone, starts_at, ends_at, booking_request_id, booking_request_hash, booking_consent_at, created_at, updated_at) " +',
  '\t\t"SELECT requested_hosts.event_id, requested_hosts.host_id, NULL, ?, ?, ?, ?, ?, \'none\', \'[]\', \'[]\', ?, ?, ?, ?, ?, ?, ?, ? FROM requested_hosts CROSS JOIN conflicts WHERE conflicts.total = 0 " +',
  '\t\t"ON CONFLICT(user_id, booking_request_id) DO NOTHING";',
  '\tconst contactTimestamp = Date.now();',
  '\tconst contactStatements = hostIds.map((userId) => env.DB.prepare(',
  '\t\t"INSERT INTO contacts (id, user_id, email, display_name, source, last_seen_at, created_at) " +',
  '\t\t"SELECT ?, ?, ?, ?, \'inbound\', ?, ? WHERE EXISTS (SELECT 1 FROM calendar_events WHERE user_id = ? AND booking_request_id = ? AND booking_request_hash = ?) " +',
  '\t\t"ON CONFLICT(user_id, email) DO UPDATE SET display_name = CASE WHEN contacts.source = \'manual\' OR contacts.display_name IS NOT NULL THEN contacts.display_name ELSE excluded.display_name END, source = CASE WHEN contacts.source IN (\'manual\', \'outbound\') THEN contacts.source ELSE \'inbound\' END, last_seen_at = excluded.last_seen_at"',
  '\t).bind(userId + ":" + guestEmail, userId, guestEmail, guestName, contactTimestamp, contactTimestamp, userId, requestId, requestHash));',
  '\tconst results = await env.DB.batch([',
  '\t\tenv.DB.prepare(sql).bind(',
  '\t\t...hostIds.flatMap((id) => [id, newId("evt")]),',
  '\t\t...hostIds,',
  '\t\tendSeconds,',
  '\t\tstartSeconds,',
  '\t\tevent.name + " with " + guestName,',
  '\t\t["Booked by " + guestName + " (" + guestEmail + ")", notes].filter(Boolean).join("\\n\\n"),',
  '\t\tevent.location,',
  '\t\tJSON.stringify([guestEmail, ...guestEmails]),',
  '\t\tevent.color,',
  '\t\tevent.timeZone,',
  '\t\tstartSeconds,',
  '\t\tendSeconds,',
  '\t\trequestId,',
  '\t\trequestHash,',
  '\t\tnowSeconds,',
  '\t\tnowSeconds,',
  '\t\tnowSeconds,',
  '\t\t),',
  '\t\t...contactStatements,',
  '\t]);',
  '\tif (results[0]?.meta.changes === hostIds.length) return true;',
  '\treturn (await existingBookingRequest(env, event, requestId, requestHash)) === true;',
  '}',
].join("\n")

export function applyBookingIntegrationPatch(sources) {
  let route = replaceExactlyOnce(
    sources.route,
    'import { createBookedCalendarEvents } from "@/lib/booking/create";',
    'import { bookingRequestHash, createBookedCalendarEvents, existingBookingRequest } from "@/lib/booking/create";\nimport { verifyTurnstileToken } from "@/lib/auth/turnstile";',
    "public booking route imports",
  )
  route = replaceExactlyOnce(
    route,
    [
      'export async function GET(request: Request, { params }: PublicBookingRouteContext) {',
      '\tconst { eventId } = await params;',
      '\tconst found = await loadPublicBookingEvent(eventId, new URL(request.url).searchParams.get("username"));',
      '\tif (!found) return NextResponse.json({ error: "Booking event not found" }, { status: 404 });',
      '\tconst slots = await availableBookingSlots(getEnv(), found.event, 60);',
      '\treturn NextResponse.json({ event: found.event, hostName: found.hostName, slots });',
      '}',
    ].join("\n"),
    bookingGetRoute,
    "public booking GET route",
  )
  route = replaceTail(
    route,
    'export async function POST(request: Request, { params }: PublicBookingRouteContext) {',
    bookingPostRoute,
    "public booking POST route",
  )
  const create = replaceTail(
    sources.create,
    'export async function createBookedCalendarEvents(',
    patchedCreateFunction,
    "booking calendar writer",
  )
  const schema = replaceExactlyOnce(
    sources.schema,
    '\t\ttimeZone: text("time_zone"),\n\t\tstartsAt: integer("starts_at", { mode: "timestamp" }).notNull(),',
    '\t\ttimeZone: text("time_zone"),\n\t\tbookingRequestId: text("booking_request_id"),\n\t\tbookingRequestHash: text("booking_request_hash"),\n\t\tbookingConsentAt: integer("booking_consent_at", { mode: "timestamp" }),\n\t\tstartsAt: integer("starts_at", { mode: "timestamp" }).notNull(),',
    "calendar event booking consent and idempotency fields",
  )
  const envTypes = replaceExactlyOnce(
    sources.envTypes,
    '\tAGENT_RATE_LIMIT?: RateLimit;\n',
    '\tAGENT_RATE_LIMIT?: RateLimit;\n\tBOOKING_RATE_LIMIT?: RateLimit;\n\tTURNSTILE_SITE_KEY?: string;\n',
    "booking security bindings",
  )
  const bookingTypes = replaceExactlyOnce(
    sources.bookingTypes,
    'export type PublicBookingSubmission = { startsAt?: unknown; name?: unknown; email?: unknown; guestEmails?: unknown; notes?: unknown };',
    'export type PublicBookingSubmission = { startsAt?: unknown; name?: unknown; email?: unknown; guestEmails?: unknown; notes?: unknown; consent?: unknown; requestId?: unknown; turnstileToken?: unknown; website?: unknown };',
    "public booking submission contract",
  )
  return { route, create, schema, envTypes, bookingTypes }
}
