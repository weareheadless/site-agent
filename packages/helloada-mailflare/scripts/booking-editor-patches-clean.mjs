const replaceExactlyOnce = (source, before, after, filename) => {
  const index = source.indexOf(before)
  if (index < 0 || source.indexOf(before, index + before.length) !== -1) {
    throw new Error("Pinned Mailflare editor patch no longer applies exactly once: " + filename)
  }
  return source.slice(0, index) + after + source.slice(index + before.length)
}

const replaceSection = (source, start, end, replacement, filename) => {
  const first = source.indexOf(start)
  const last = source.indexOf(end, first + start.length)
  if (first < 0 || last < 0 || source.indexOf(start, first + start.length) !== -1) {
    throw new Error("Pinned Mailflare editor section no longer applies exactly once: " + filename)
  }
  return source.slice(0, first) + replacement + "\n\n" + source.slice(last)
}

const eventFormFunctions = [
  "export function formFromEvent(event: BookingEvent): BookingForm {",
  "\tlet savedWeekdays: number[] = [];",
  "\ttry { savedWeekdays = JSON.parse(event.weekdays) as number[]; } catch { /* Keep malformed legacy days editable. */ }",
  "\tconst savedRanges = parseBookingTimeRanges(event.timeRanges, { startTime: event.startTime, endTime: event.endTime });",
  "\tconst importedSchedule = parseHelloAdaWeeklyAvailability(event.helloadaWeeklyAvailability);",
  "\tconst weeklyAvailability = importedSchedule.length ? importedSchedule : savedWeekdays.flatMap((day) => savedRanges.map((range) => ({ day, ...range })));",
  "\tconst normalized = weeklyAvailability.slice().sort((a, b) => a.day - b.day || a.startTime.localeCompare(b.startTime));",
  "\tconst weekdays = [...new Set(normalized.map((range) => range.day))];",
  "\tconst ranges = [...new Map(normalized.map(({ startTime, endTime }) => [JSON.stringify({ startTime, endTime }), { startTime, endTime }])).values()].sort((a, b) => a.startTime.localeCompare(b.startTime) || a.endTime.localeCompare(b.endTime));",
  "\treturn { name: event.name, slug: event.slug, description: event.description ?? \"\", color: normalizeCalendarColor(event.color), hostIds: parseBookingHostIds(event.hostIds, event.userId), durationMinutes: event.durationMinutes, location: event.location, weekdays, weeklyAvailability: normalized, startTime: ranges[0]?.startTime ?? \"09:00\", endTime: ranges[ranges.length - 1]?.endTime ?? \"17:00\", timeRanges: ranges, timeZone: event.timeZone, enabled: event.enabled };",
  "}",
  "",
  "export function formWithWeeklyAvailability(form: BookingForm, weeklyAvailability: BookingWeeklyAvailability[]): BookingForm {",
  "\tconst normalized = weeklyAvailability.slice().sort((a, b) => a.day - b.day || a.startTime.localeCompare(b.startTime));",
  "\tconst weekdays = [...new Set(normalized.map((range) => range.day))];",
  "\tconst timeRanges = [...new Map(normalized.map(({ startTime, endTime }) => [JSON.stringify({ startTime, endTime }), { startTime, endTime }])).values()].sort((a, b) => a.startTime.localeCompare(b.startTime) || a.endTime.localeCompare(b.endTime));",
  "\treturn { ...form, weeklyAvailability: normalized, weekdays, startTime: timeRanges[0]?.startTime ?? \"09:00\", endTime: timeRanges[timeRanges.length - 1]?.endTime ?? \"17:00\", timeRanges };",
  "}",
].join("\n")

const formAvailabilityLabelFunction = [
  "export function formAvailabilityLabel(form: BookingForm, t: Translator = defaultTranslator): string {",
  "\tif (!form.weekdays.length) return t(\"booking.noDays\");",
  "\treturn form.weekdays.map((day) => {",
  "\t\tconst label = t((\"calendar.weekdayShort.\" + day) as TranslationKey);",
  "\t\tconst ranges = form.weeklyAvailability.filter((range) => range.day === day).map((range) => range.startTime + \"–\" + range.endTime).join(\", \");",
  "\t\treturn label + \" \" + ranges;",
  "\t}).join(\" · \");",
  "}",
].join("\n")

const bookingAvailabilitySection = [
  '<section className={sectionClass}><button type="button" onClick={() => toggle("availability")} aria-expanded={activeSection === "availability"} className={headingClass}><span>{t("booking.editor.availability")}</span><ChevronDown className={clsx("h-5 w-5 text-neutral-500 transition-transform", activeSection === "availability" && "rotate-180")} /></button>',
  '{activeSection === "availability" ? <div className="mt-4 space-y-4">',
  '<fieldset aria-label={t("booking.editor.availableDays")}>',
  '<div className="mt-2 flex flex-wrap gap-1">{WEEKDAYS.map((day) => {',
  '\tconst ranges = form.weeklyAvailability.filter((range) => range.day === day);',
  '\tconst selectedDay = activeDay === day;',
  '\tconst label = t(("calendar.weekdayShort." + day) as TranslationKey);',
  '\treturn <span key={day} className="inline-flex items-center">',
  '\t\t<button type="button" aria-label={label} aria-pressed={selectedDay} onClick={() => { if (!ranges.length) updateRangesForDay(day, [nextBookingTimeRange([], form.durationMinutes)]); setActiveDay(day); }} className={clsx("rounded-full px-3 py-1.5 text-xs font-medium", ranges.length ? selectedDay ? "bg-blue-700 text-white" : "bg-blue-100 text-blue-800 hover:bg-blue-200" : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200")}>{label}</button>',
  '\t\t{ranges.length > 0 && <button type="button" aria-label={t("common.delete") + " " + label} disabled={form.weekdays.length <= 1} onClick={() => { updateWeeklyAvailability(form.weeklyAvailability.filter((range) => range.day !== day)); if (selectedDay) setActiveDay(form.weekdays.find((candidate) => candidate !== day) ?? day); }} className="ml-0.5 rounded-full p-1 text-neutral-500 hover:bg-red-50 hover:text-red-600 disabled:opacity-30"><Trash2 className="h-3 w-3" /></button>}',
  '\t</span>;',
  '})}</div>',
  '</fieldset>',
  '<div className="flex flex-row gap-8 mt-2"><p className="text-sm font-medium text-neutral-700 mt-3">{t("booking.editor.times")} · {t(("calendar.weekdayShort." + activeDay) as TranslationKey)}</p>',
  '<div className="space-y-2 flex flex-col items-start flex-1 min-w-0">{activeRanges.map((range, index) => <div key={index} className="flex items-end gap-2 w-full">',
  '<label className="min-w-0 flex-1 text-xs text-neutral-500">{t("calendar.from")}<Input type="time" step={900} value={range.startTime} onChange={(event) => updateRangesForDay(activeDay, activeRanges.map((item, itemIndex) => itemIndex === index ? { ...item, startTime: event.target.value } : item))} className="mt-1 flex-1 min-w-0" /></label>',
  '<label className="min-w-0 flex-1 text-xs text-neutral-500">{t("calendar.to")}<Input type="time" step={900} value={range.endTime} onChange={(event) => updateRangesForDay(activeDay, activeRanges.map((item, itemIndex) => itemIndex === index ? { ...item, endTime: event.target.value } : item))} className="mt-1 flex-1 min-w-0" /></label>',
  '<button type="button" aria-label={t("booking.editor.removeTime", { n: index + 1 })} disabled={activeRanges.length === 1} onClick={() => updateRangesForDay(activeDay, activeRanges.filter((_, itemIndex) => itemIndex !== index))} className="mb-1 rounded-full p-2 text-neutral-500 hover:bg-neutral-100 disabled:opacity-30"><Trash2 className="h-4 w-4" /></button>',
  '</div>)}',
  '<button type="button" disabled={activeRanges.length >= 12} onClick={() => updateRangesForDay(activeDay, [...activeRanges, nextBookingTimeRange(activeRanges, form.durationMinutes)])} className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-blue-700 hover:text-blue-600 disabled:opacity-50"><Plus className="h-4 w-4" />{t("booking.editor.addTime")}</button>',
  '</div></div>',
  '<p className="text-xs text-neutral-500">{t("booking.editor.timesUse", { zone: form.timeZone })}</p></div> : <button type="button" onClick={() => toggle("availability")} className="mt-2 flex w-full items-center gap-2 text-left text-sm text-neutral-500"><CalendarDays className="h-4 w-4 shrink-0" />{formAvailabilityLabel(form, t)}</button>}</section>',
].join("\n")

export function applyBookingEditorPatches(sources, patched) {
  let editorTypes = replaceExactlyOnce(sources.bookingEditorTypes,
    'import type { BookingTimeRange } from "@/lib/booking/types";',
    'import type { BookingTimeRange, BookingWeeklyAvailability } from "@/lib/booking/types";',
    "booking editor weekly type import")
  editorTypes = replaceExactlyOnce(editorTypes,
    "\ttimeRanges: string;\n\ttimeZone: string;",
    "\ttimeRanges: string;\n\thelloadaWeeklyAvailability: string;\n\thelloadaBufferMinutes: number;\n\ttimeZone: string;",
    "booking event schedule fields")
  editorTypes = replaceExactlyOnce(editorTypes,
    "\tweekdays: number[];\n\tstartTime: string;",
    "\tweekdays: number[];\n\tweeklyAvailability: BookingWeeklyAvailability[];\n\tstartTime: string;",
    "booking form schedule fields")

  let editorUtils = replaceExactlyOnce(sources.bookingPageUtils,
    'import { parseBookingTimeRanges } from "@/lib/booking/utils";',
    'import { parseBookingTimeRanges, parseHelloAdaWeeklyAvailability } from "@/lib/booking/utils";',
    "booking page schedule parser")
  editorUtils = replaceExactlyOnce(editorUtils,
    'return { name: "", slug: "", description: "", color: DEFAULT_FOLDER_COLOR, hostIds: [currentUserId], durationMinutes: 30, location: "", weekdays: [1, 2, 3, 4, 5], startTime: "09:00", endTime: "17:00", timeRanges: [{ startTime: "09:00", endTime: "17:00" }], timeZone, enabled: true };',
    'return { name: "", slug: "", description: "", color: DEFAULT_FOLDER_COLOR, hostIds: [currentUserId], durationMinutes: 30, location: "", weekdays: [1, 2, 3, 4, 5], weeklyAvailability: [1, 2, 3, 4, 5].map((day) => ({ day, startTime: "09:00", endTime: "17:00" })), startTime: "09:00", endTime: "17:00", timeRanges: [{ startTime: "09:00", endTime: "17:00" }], timeZone, enabled: true };',
    "default booking schedule")
  editorUtils = replaceSection(editorUtils, "export function formFromEvent(event: BookingEvent): BookingForm {", "export function bookingFormWithName(", eventFormFunctions, "booking form schedule mapping")
  editorUtils = replaceSection(editorUtils, "export function availabilityLabel(event: BookingEvent", "export function formAvailabilityLabel(", 'export function availabilityLabel(event: BookingEvent, t: Translator = defaultTranslator): string {\n\treturn formAvailabilityLabel(formFromEvent(event), t);\n}', "booking event availability label")
  editorUtils = replaceSection(editorUtils, "export function formAvailabilityLabel(form: BookingForm", "export function nextBookingTimeRange(", formAvailabilityLabelFunction, "per-day availability summary")

  let editor = replaceExactlyOnce(sources.bookingEditor,
    "bookingFormWithName, durationLabel, formAvailabilityLabel, matchBookingHost, nextBookingTimeRange, WEEKDAYS",
    "bookingFormWithName, durationLabel, formAvailabilityLabel, formWithWeeklyAvailability, matchBookingHost, nextBookingTimeRange, WEEKDAYS",
    "booking editor schedule helper")
  editor = replaceExactlyOnce(editor,
    'const [hostError, setHostError] = useState("");',
    'const [hostError, setHostError] = useState("");\n\tconst [activeDay, setActiveDay] = useState<number>(form.weekdays[0] ?? 1);',
    "booking editor selected weekday state")
  editor = replaceExactlyOnce(editor,
    'setHostError(""); } }, [editingId, open]);',
    'setHostError(""); setActiveDay(form.weekdays[0] ?? 1); } }, [editingId, open, form.weekdays[0]]);',
    "booking editor selected weekday reset")
  editor = replaceExactlyOnce(editor,
    "const toggle = (section: BookingEditorSection) => setActiveSection((current) => current === section ? null : section);\n\n\treturn",
    "const toggle = (section: BookingEditorSection) => setActiveSection((current) => current === section ? null : section);\n\tconst activeRanges = form.weeklyAvailability.filter((range) => range.day === activeDay).map(({ startTime, endTime }) => ({ startTime, endTime }));\n\tconst updateWeeklyAvailability = (schedule: typeof form.weeklyAvailability) => onChange(formWithWeeklyAvailability(form, schedule));\n\tconst updateRangesForDay = (day: number, ranges: typeof form.timeRanges) => updateWeeklyAvailability([...form.weeklyAvailability.filter((range) => range.day !== day), ...ranges.map((range) => ({ day, ...range }))]);\n\n\treturn",
    "booking editor daily schedule actions")
  editor = replaceSection(editor,
    '<section className={sectionClass}><button type="button" onClick={() => toggle("availability")}',
    '\n\t\t\t\t<section className={sectionClass}>\n\t\t\t\t\t<button type="button" onClick={() => toggle("host")}',
    bookingAvailabilitySection,
    "booking editor availability section")
  return { ...patched, bookingEditorTypes: editorTypes, bookingPageUtils: editorUtils, bookingEditor: editor }
}
