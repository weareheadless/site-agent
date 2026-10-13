import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const replaceOnce = (source, before, after, label) => {
  const index = source.indexOf(before);
  if (index < 0 || source.indexOf(before, index + before.length) !== -1) {
    throw new Error("Calendar capacity patch did not match exactly once: " + label);
  }
  return source.slice(0, index) + after + source.slice(index + before.length);
};

const replaceRange = (source, start, end, replacement, label) => {
  const startAt = source.indexOf(start);
  const endAt = source.indexOf(end, startAt + start.length);
  if (startAt < 0 || endAt < 0 || source.indexOf(start, startAt + start.length) !== -1) {
    throw new Error("Calendar capacity range did not match exactly once: " + label);
  }
  return source.slice(0, startAt) + replacement + source.slice(endAt);
};

const helperImport = 'import { assertCalendarMutationCapacity, calendarCapacityCandidate, isCalendarCapacityConflict } from "@/lib/helloada-booking-runtime";';
const conflictResponse = `function capacityConflictResponse(error: unknown) {
  if (!isCalendarCapacityConflict(error)) return null;
  return NextResponse.json({ error: "That time conflicts with existing appointments or the calendar changed. Refresh availability and try again." }, { status: 409 });
}

`;

function patchCalendarCreate(source) {
  source = replaceOnce(source,
    'import { authorizeCalendarRequest, calendarKeyCanSendInvitations } from "@/lib/calendar/api-auth";',
    'import { authorizeCalendarRequest, calendarKeyCanSendInvitations } from "@/lib/calendar/api-auth";\n' + helperImport + '\n\n' + conflictResponse,
    "Calendar create imports");
  source = replaceOnce(source,
    'const savedEvent = { ...event, timeZone: input.timeZone ? normalizeTimeZone(input.timeZone) : getRequestTimeZone(request, user.timeZone) };\n\tawait getDb(env).insert(calendarEvents).values(savedEvent);',
    'const savedEvent = { ...event, timeZone: input.timeZone ? normalizeTimeZone(input.timeZone) : getRequestTimeZone(request, user.timeZone) };\n\ttry {\n\t\tconst revision = await assertCalendarMutationCapacity(env.DB, user.id, [calendarCapacityCandidate(savedEvent)]);\n\t\tawait getDb(env).insert(calendarEvents).values({ ...savedEvent, helloadaCapacityRevision: revision });\n\t} catch (error) {\n\t\tconst response = capacityConflictResponse(error);\n\t\tif (response) return response;\n\t\tthrow error;\n\t}',
    "Calendar create capacity admission");
  return source;
}

function patchCalendarEvent(source) {
  source = replaceOnce(source,
    'import { authorizeCalendarRequest, calendarKeyCanSendInvitations } from "@/lib/calendar/api-auth";',
    'import { authorizeCalendarRequest, calendarKeyCanSendInvitations } from "@/lib/calendar/api-auth";\n' + helperImport + '\n\n' + conflictResponse,
    "Calendar event imports");
  source = replaceOnce(source,
    'const timeZone = input.timeZone ? normalizeTimeZone(input.timeZone) : existing.timeZone ?? getRequestTimeZone(request, user.timeZone);',
    'const capacityCandidate = (row: typeof existing) => calendarCapacityCandidate(row);\n\tconst timeZone = input.timeZone ? normalizeTimeZone(input.timeZone) : existing.timeZone ?? getRequestTimeZone(request, user.timeZone);',
    "Calendar event capacity mapper");
  source = replaceOnce(source,
    'const now = new Date();\n\t\tconst moved = { ...existing, id: newId("evt"), title: input.title.trim(), description: input.description?.trim() ?? "", location: input.location?.trim() ?? "", attendees: JSON.stringify(attendees), color: normalizeCalendarColor(input.color ?? existing.color), repeat: "none" as const, repeatDays: "[]", repeatAnchorDay: null, repeatUntil: null, excludedOccurrences: "[]", startsAt, endsAt, createdAt: now, updatedAt: now };\n\t\tawait db.insert(calendarEvents).values(moved);\n\t\tawait db.update(calendarEvents).set({ excludedOccurrences: JSON.stringify([...excluded, occurrence.startsAt.getTime()]), updatedAt: now }).where(eq(calendarEvents.id, existing.id));',
    'const now = new Date();\n\t\tconst moved = { ...existing, id: newId("evt"), title: input.title.trim(), description: input.description?.trim() ?? "", location: input.location?.trim() ?? "", attendees: JSON.stringify(attendees), color: normalizeCalendarColor(input.color ?? existing.color), repeat: "none" as const, repeatDays: "[]", repeatAnchorDay: null, repeatUntil: null, excludedOccurrences: "[]", startsAt, endsAt, createdAt: now, updatedAt: now };\n\t\tconst excludedOccurrences = JSON.stringify([...excluded, occurrence.startsAt.getTime()]);\n\t\ttry {\n\t\t\tconst revision = await assertCalendarMutationCapacity(env.DB, user.id, [capacityCandidate(moved), capacityCandidate({ ...existing, excludedOccurrences })], [existing.id]);\n\t\t\tawait db.batch([\n\t\t\t\tdb.insert(calendarEvents).values({ ...moved, helloadaCapacityRevision: revision }),\n\t\t\t\tdb.update(calendarEvents).set({ excludedOccurrences, helloadaCapacityRevision: revision + 1, updatedAt: now }).where(eq(calendarEvents.id, existing.id)),\n\t\t\t]);\n\t\t} catch (error) {\n\t\t\tconst response = capacityConflictResponse(error);\n\t\t\tif (response) return response;\n\t\t\tthrow error;\n\t\t}',
    "Calendar recurrence occurrence move");
  const start = 'const splitAt = existing.repeat !== "none" ? effectiveFrom : null;';
  const end = '\n\tif (attendees.length && existing.mailboxId && input.from) { const file = createCalendarInvitation({ ...event, uid: existing.id });';
  const replacement = `const splitAt = existing.repeat !== "none" ? effectiveFrom : null;
	if (splitAt && splitAt > existing.startsAt) {
		const now = new Date();
		const newEvent = { ...event, id: newId("evt"), createdAt: now, updatedAt: now };
		try {
			const revision = await assertCalendarMutationCapacity(env.DB, user.id, [
				capacityCandidate({ ...existing, repeatUntil: splitAt }),
				capacityCandidate(newEvent),
			], [existing.id]);
			await db.batch([
				db.insert(calendarEvents).values({ ...newEvent, helloadaCapacityRevision: revision }),
				db.update(calendarEvents).set({ repeatUntil: splitAt, helloadaCapacityRevision: revision + 1, updatedAt: now }).where(eq(calendarEvents.id, existing.id)),
			]);
		} catch (error) {
			const response = capacityConflictResponse(error);
			if (response) return response;
			throw error;
		}
	} else {
		const scheduleChanged = event.startsAt.getTime() !== existing.startsAt.getTime()
			|| event.endsAt.getTime() !== existing.endsAt.getTime()
			|| event.repeat !== existing.repeat
			|| event.repeatDays !== existing.repeatDays
			|| event.repeatAnchorDay !== existing.repeatAnchorDay
			|| (event.repeatUntil?.getTime() ?? null) !== (existing.repeatUntil?.getTime() ?? null)
			|| event.timeZone !== existing.timeZone
			|| event.excludedOccurrences !== existing.excludedOccurrences;
		let revision: number | undefined;
		try {
			if (scheduleChanged) revision = await assertCalendarMutationCapacity(env.DB, user.id, [capacityCandidate(event)], [existing.id]);
			await db.update(calendarEvents).set({
				title: event.title, description: event.description, location: event.location, attendees: event.attendees,
				color: event.color, repeat: event.repeat, repeatDays: event.repeatDays, repeatAnchorDay: event.repeatAnchorDay,
				repeatUntil: event.repeatUntil, timeZone, startsAt, endsAt, updatedAt: new Date(),
				...(revision === undefined ? {} : { helloadaCapacityRevision: revision }),
			}).where(eq(calendarEvents.id, existing.id));
		} catch (error) {
			const response = capacityConflictResponse(error);
			if (response) return response;
			throw error;
		}
	}`;
  source = replaceRange(source, start, end, replacement, "Calendar reschedule and recurrence split");
  source = replaceOnce(source,
    'if (existing.repeat !== "none" && effectiveFrom && effectiveFrom > existing.startsAt) await db.update(calendarEvents).set({ repeatUntil: effectiveFrom, updatedAt: new Date() }).where(eq(calendarEvents.id, existing.id));',
    'if (existing.repeat !== "none" && effectiveFrom && effectiveFrom > existing.startsAt) {\n\t\ttry {\n\t\t\tconst revision = await assertCalendarMutationCapacity(env.DB, user.id, []);\n\t\t\tawait db.update(calendarEvents).set({ repeatUntil: effectiveFrom, helloadaCapacityRevision: revision, updatedAt: new Date() }).where(eq(calendarEvents.id, existing.id));\n\t\t} catch (error) {\n\t\t\tconst response = capacityConflictResponse(error);\n\t\t\tif (response) return response;\n\t\t\tthrow error;\n\t\t}\n\t}',
    "Calendar recurrence deletion cutoff");
  return source;
}

function patchTimeZone(source) {
  source = replaceOnce(source,
    'import { getRequestTimeZone } from "@/lib/time/utils";',
    'import { getRequestTimeZone } from "@/lib/time/utils";\n' + helperImport + '\n\n' + conflictResponse,
    "Timezone route imports");
  source = replaceOnce(source,
    `	// Legacy series have no recorded timezone. Freeze their current recurrence
	// before changing the account preference, so future instants do not move.
	await db.update(calendarEvents).set({ timeZone: getRequestTimeZone(request, user.timeZone) }).where(and(
		eq(calendarEvents.userId, user.id),
		isNull(calendarEvents.timeZone),
		ne(calendarEvents.repeat, "none"),
	));`,
    `	// Freeze legacy recurrence in the current timezone without changing the capacity contract.
	const currentTimeZone = getRequestTimeZone(request, user.timeZone);
	const legacyEvents = await db.select().from(calendarEvents).where(and(
		eq(calendarEvents.userId, user.id),
		isNull(calendarEvents.timeZone),
		ne(calendarEvents.repeat, "none"),
	));
	try {
		if (legacyEvents.length) {
			const revision = await assertCalendarMutationCapacity(env.DB, user.id,
				legacyEvents.map((event) => calendarCapacityCandidate({ ...event, timeZone: currentTimeZone })),
				legacyEvents.map((event) => event.id));
			await db.batch(legacyEvents.map((event, index) => db.update(calendarEvents)
				.set({ timeZone: currentTimeZone, helloadaCapacityRevision: revision + index, updatedAt: new Date() })
				.where(eq(calendarEvents.id, event.id))));
		}
	} catch (error) {
		const response = capacityConflictResponse(error);
		if (response) return response;
		throw error;
	}`,
    "Timezone recurrence update");
  return source;
}

function patchCalendarTools(source) {
  source = replaceOnce(source,
    'import { expandToolEvents } from "./tool-occurrences";',
    'import { expandToolEvents } from "./tool-occurrences";\n' + helperImport,
    "Ada calendar tool imports");
  source = replaceOnce(source,
    'await db.insert(calendarEvents).values(event);\n\t\treturn { eventId: event.id, status: "created" };',
    'try {\n\t\t\tconst revision = await assertCalendarMutationCapacity(context.env.DB, context.user.id, [calendarCapacityCandidate(event)]);\n\t\t\tawait db.insert(calendarEvents).values({ ...event, helloadaCapacityRevision: revision });\n\t\t} catch (error) {\n\t\t\tif (isCalendarCapacityConflict(error)) throw new Error("That time conflicts with another calendar event or booking. Refresh the schedule and try again.");\n\t\t\tthrow error;\n\t\t}\n\t\treturn { eventId: event.id, status: "created" };',
    "Ada create-event capacity admission");
  const oldUpdates = `		for (const [index, item] of updates.entries()) {
			const row = existing[index]!;
			const startsAt = item.startsAt ? new Date(item.startsAt) : row.startsAt;
			const endsAt = item.endsAt ? new Date(item.endsAt) : row.endsAt;
			const timeZone = item.timeZone ? normalizeTimeZone(item.timeZone) : normalizeTimeZone(row.timeZone);
			await db.update(calendarEvents).set({ title: item.title ?? row.title, description: item.description ?? row.description, location: item.location ?? row.location, startsAt, endsAt, timeZone, color: item.color ? normalizeCalendarColor(item.color) : row.color, repeat: item.repeat ?? row.repeat, repeatDays: item.repeatDays ? JSON.stringify(normalizeCalendarRepeatDays(item.repeatDays)) : row.repeatDays, repeatAnchorDay: (item.repeat ?? row.repeat) === "monthly" ? zonedDateFields(startsAt, timeZone).getUTCDate() : null, attendees: item.attendees ? JSON.stringify(item.attendees) : row.attendees, updatedAt: new Date() }).where(and(eq(calendarEvents.id, row.id), eq(calendarEvents.userId, context.user.id)));
		}`;
  const newUpdates = `		const planned = updates.map((item, index) => {
			const row = existing[index]!;
			const startsAt = item.startsAt ? new Date(item.startsAt) : row.startsAt;
			const endsAt = item.endsAt ? new Date(item.endsAt) : row.endsAt;
			const timeZone = item.timeZone ? normalizeTimeZone(item.timeZone) : normalizeTimeZone(row.timeZone);
			const event = {
				...row, title: item.title ?? row.title, description: item.description ?? row.description,
				location: item.location ?? row.location, startsAt, endsAt, timeZone,
				color: item.color ? normalizeCalendarColor(item.color) : row.color,
				repeat: item.repeat ?? row.repeat,
				repeatDays: item.repeatDays ? JSON.stringify(normalizeCalendarRepeatDays(item.repeatDays)) : row.repeatDays,
				repeatAnchorDay: (item.repeat ?? row.repeat) === "monthly" ? zonedDateFields(startsAt, timeZone).getUTCDate() : null,
				attendees: item.attendees ? JSON.stringify(item.attendees) : row.attendees,
			};
			const scheduleChanged = event.startsAt.getTime() !== row.startsAt.getTime()
				|| event.endsAt.getTime() !== row.endsAt.getTime()
				|| event.timeZone !== row.timeZone || event.repeat !== row.repeat
				|| event.repeatDays !== row.repeatDays || event.repeatAnchorDay !== row.repeatAnchorDay;
			return { event, row, scheduleChanged };
		});
		try {
			const revision = await assertCalendarMutationCapacity(context.env.DB, context.user.id,
				planned.filter((item) => item.scheduleChanged).map((item) => calendarCapacityCandidate(item.event)), ids);
			await db.batch(planned.map(({ event, row }, index) => db.update(calendarEvents).set({
				title: event.title, description: event.description, location: event.location, startsAt: event.startsAt,
				endsAt: event.endsAt, timeZone: event.timeZone, color: event.color, repeat: event.repeat,
				repeatDays: event.repeatDays, repeatAnchorDay: event.repeatAnchorDay, attendees: event.attendees,
				updatedAt: new Date(), helloadaCapacityRevision: revision + index,
			}).where(and(eq(calendarEvents.id, row.id), eq(calendarEvents.userId, context.user.id)))));
		} catch (error) {
			if (isCalendarCapacityConflict(error)) throw new Error("Those changes conflict with another calendar event or booking. Refresh the schedule and try again.");
			throw error;
		}`;
  source = replaceOnce(source, oldUpdates, newUpdates, "Ada batch event updates");
  return source;
}

export async function applyBookingCapacityPatches(destination) {
  const paths = {
    schema: "src/db/schema/index.ts",
    create: "src/app/api/calendar/events/route.ts",
    event: "src/app/api/calendar/events/[eventId]/route.ts",
    timeZone: "src/app/api/settings/time-zone/route.ts",
    tools: "src/lib/calendar/tools.ts",
  };
  const sources = Object.fromEntries(await Promise.all(Object.entries(paths).map(async ([key, relative]) =>
    [key, await readFile(path.join(destination, relative), "utf8")],
  )));
  sources.schema = replaceOnce(sources.schema,
    'repeatUntil: integer("repeat_until", { mode: "timestamp" }),',
    'repeatUntil: integer("repeat_until", { mode: "timestamp_ms" }),',
    "Calendar recurrence timestamp unit");
  sources.schema = replaceOnce(sources.schema,
    'startsAt: integer("starts_at", { mode: "timestamp" }).notNull(),',
    'startsAt: integer("starts_at", { mode: "timestamp_ms" }).notNull(),',
    "Calendar start timestamp unit");
  sources.schema = replaceOnce(sources.schema,
    'endsAt: integer("ends_at", { mode: "timestamp" }).notNull(),',
    'endsAt: integer("ends_at", { mode: "timestamp_ms" }).notNull(),\n\t\thelloadaCapacityRevision: integer("helloada_capacity_revision"),',
    "Calendar end timestamp unit and revision field");
  if (!sources.schema.includes("helloadaRevision") && sources.schema.includes("helloadaPayloadManaged")) sources.schema = replaceOnce(sources.schema,
    'helloadaPayloadManaged: integer("helloada_payload_managed", { mode: "boolean" }).notNull().default(false),',
    'helloadaPayloadManaged: integer("helloada_payload_managed", { mode: "boolean" }).notNull().default(false),\n\t\thelloadaRevision: integer("helloada_revision").notNull().default(1),',
    "Booking type revision field");
  sources.create = patchCalendarCreate(sources.create);
  sources.event = patchCalendarEvent(sources.event);
  sources.timeZone = patchTimeZone(sources.timeZone);
  sources.tools = patchCalendarTools(sources.tools);
  await Promise.all(Object.entries(paths).map(([key, relative]) =>
    writeFile(path.join(destination, relative), sources[key]),
  ));
}
