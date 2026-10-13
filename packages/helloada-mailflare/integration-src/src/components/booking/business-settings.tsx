"use client";

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Plus, Trash2 } from "lucide-react";
import { authFetch } from "@/lib/auth/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLanguage } from "@/components/language-provider";
import type { BookingHours, BookingSettings } from "@/lib/helloada-booking-service";

type NotificationIssue = { id: string; startsAt: string; timeZone: string; typeName: string; state: string };
type CapacityWarnings = { overlappingPeriods: number; maxConcurrentAppointments: number; horizonDays: number };

const days = [
  { value: 0, label: "Sunday" }, { value: 1, label: "Monday" }, { value: 2, label: "Tuesday" },
  { value: 3, label: "Wednesday" }, { value: 4, label: "Thursday" }, { value: 5, label: "Friday" }, { value: 6, label: "Saturday" },
];

export function BusinessBookingSettings() {
  const { t } = useLanguage();
  const [settings, setSettings] = useState<BookingSettings | null>(null);
  const [hours, setHours] = useState<BookingHours[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [notificationIssues, setNotificationIssues] = useState<NotificationIssue[]>([]);
  const [capacityWarnings, setCapacityWarnings] = useState<CapacityWarnings | null>(null);
  const [retryingId, setRetryingId] = useState("");

  useEffect(() => {
    let active = true;
    void authFetch("/api/booking").then(async (response) => {
      const data = await response.json() as { settings?: BookingSettings; notificationIssues?: NotificationIssue[]; capacityWarnings?: CapacityWarnings; error?: string };
      if (!response.ok || !data.settings) throw new Error(data.error || "Unable to load appointment settings.");
      if (active) { setSettings(data.settings); setHours(data.settings.weeklyAvailability); setNotificationIssues(data.notificationIssues ?? []); setCapacityWarnings(data.capacityWarnings ?? null); }
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Unable to load appointment settings."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const validation = useMemo(() => {
    const sorted = hours.slice().sort((a, b) => a.day - b.day || a.startTime.localeCompare(b.startTime));
    if (sorted.some((row) => !/^([01]\\d|2[0-3]):[0-5]\\d$/.test(row.startTime) || !/^([01]\\d|2[0-3]):[0-5]\\d$/.test(row.endTime) || row.startTime >= row.endTime)) return "Enter a valid opening and closing time for every period.";
    if (sorted.some((row, index) => index > 0 && row.day === sorted[index - 1].day && row.startTime < sorted[index - 1].endTime)) return "Working hours on the same day cannot overlap.";
    return "";
  }, [hours]);

  const addHours = () => {
    const day = days.find((item) => !hours.some((row) => row.day === item.value))?.value ?? 1;
    setHours((rows) => [...rows, { day, startTime: "", endTime: "" }].sort((a, b) => a.day - b.day || a.startTime.localeCompare(b.startTime)));
    setSaved(false);
  };
  const changeHours = (index: number, patch: Partial<BookingHours>) => {
    setHours((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row).sort((a, b) => a.day - b.day || a.startTime.localeCompare(b.startTime)));
    setSaved(false);
  };

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings || validation) return;
    setSaving(true); setError(""); setSaved(false);
    const form = new FormData(event.currentTarget);
    const payload = {
      enabled: form.get("enabled") === "on",
      timeZone: String(form.get("timeZone") || "").trim(),
      weeklyAvailability: hours,
      maxConcurrentAppointments: Number(form.get("capacity")),
      minimumNoticeHours: Number(form.get("notice")),
      bookingWindowDays: Number(form.get("horizon")),
      expectedRevision: settings.revision,
    };
    try {
      const response = await authFetch("/api/booking", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operation: "update_settings", settings: payload }) });
      const data = await response.json() as { settings?: BookingSettings; capacityWarnings?: CapacityWarnings; error?: string };
      if (!response.ok || !data.settings) throw new Error(data.error || "Unable to save appointment settings.");
      setSettings(data.settings); setHours(data.settings.weeklyAvailability); setCapacityWarnings(data.capacityWarnings ?? null); setSaved(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to save appointment settings."); }
    finally { setSaving(false); }
  }

  async function retryNotification(eventId: string) {
    setRetryingId(eventId); setError("");
    try {
      const response = await authFetch("/api/booking", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation: "retry_notification", eventId }),
      });
      const data = await response.json() as { error?: string };
      if (!response.ok) throw new Error(data.error || "The confirmation email could not be sent.");
      setNotificationIssues((current) => current.filter((issue) => issue.id !== eventId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The confirmation email could not be sent.");
    } finally { setRetryingId(""); }
  }

  if (loading) return <section aria-busy="true" className="rounded-2xl bg-white p-6"><p className="text-sm text-neutral-500">Loading appointment settings…</p></section>;
  if (!settings) return <section className="rounded-2xl border border-red-200 bg-red-50 p-6"><h2 className="font-semibold text-neutral-900">Appointment settings unavailable</h2><p role="alert" className="mt-2 text-sm text-red-800">{error}</p></section>;

  return <section aria-labelledby="booking-business-settings-title" className="overflow-hidden rounded-2xl bg-white shadow-[0_12px_40px_rgba(35,42,54,0.06)] ring-1 ring-neutral-200/80">
    <div className="border-b border-neutral-100 px-6 py-5">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-orange-600">Appointments</p>
      <h2 id="booking-business-settings-title" className="mt-1 text-xl font-semibold tracking-tight text-neutral-950">Business availability</h2>
      <p className="mt-1 max-w-2xl text-sm leading-6 text-neutral-600">Set when visitors can book and how many appointments your business can handle at once. Every appointment type uses these shared hours.</p>
    </div>
    <form onSubmit={(event) => void save(event)} className="space-y-6 px-6 py-5">
      <label className="flex items-center gap-3 rounded-xl bg-orange-50/70 px-4 py-3">
        <input name="enabled" type="checkbox" defaultChecked={settings.enabled} className="h-4 w-4 accent-orange-600" />
        <span><span className="block text-sm font-semibold text-neutral-900">Accept online appointments</span><span className="mt-0.5 block text-xs text-neutral-600">Turn this on after you add working hours and at least one active appointment type.</span></span>
      </label>

      <div>
        <label htmlFor="booking-time-zone" className="mb-1.5 block text-sm font-semibold text-neutral-800">Business time zone</label>
        <Input id="booking-time-zone" name="timeZone" required defaultValue={settings.timeZone} placeholder="America/Cancun" className="max-w-sm" />
        <p className="mt-1.5 text-xs text-neutral-500">Use an IANA name, such as America/Cancun or America/Mexico_City.</p>
      </div>

      <div>
        <div className="mb-3 flex items-end justify-between gap-3">
          <div><h3 className="text-sm font-semibold text-neutral-900">Weekly hours</h3><p className="mt-1 text-xs text-neutral-500">Add one row per open period. Closed days need no row.</p></div>
          <Button type="button" variant="outline" onClick={addHours} className="h-9 rounded-full px-3"><Plus className="h-4 w-4" />Add hours</Button>
        </div>
        <div className="space-y-2">
          {hours.length ? hours.map((row, index) => <div key={index} className="grid grid-cols-[minmax(110px,1fr)_minmax(90px,0.8fr)_minmax(90px,0.8fr)_36px] items-center gap-2 rounded-xl bg-neutral-50 p-2 max-sm:grid-cols-1">
            <select aria-label={`Day for hours period ${index + 1}`} value={row.day} onChange={(event) => changeHours(index, { day: Number(event.target.value) })} className="h-10 rounded-lg border-0 bg-white px-3 text-sm text-neutral-800 ring-1 ring-neutral-200">{days.map((day) => <option value={day.value} key={day.value}>{day.label}</option>)}</select>
            <Input aria-label={`Opening time for period ${index + 1}`} type="time" step={900} value={row.startTime} onChange={(event) => changeHours(index, { startTime: event.target.value })} />
            <Input aria-label={`Closing time for period ${index + 1}`} type="time" step={900} value={row.endTime} onChange={(event) => changeHours(index, { endTime: event.target.value })} />
            <button type="button" aria-label={`Remove hours period ${index + 1}`} onClick={() => { setHours((rows) => rows.filter((_, rowIndex) => rowIndex !== index)); setSaved(false); }} className="flex h-9 w-9 items-center justify-center rounded-full text-neutral-500 transition-colors duration-200 ease-[cubic-bezier(0.32,0.72,0,1)] hover:bg-red-50 hover:text-red-700"><Trash2 className="h-4 w-4" /></button>
          </div>) : <p className="rounded-xl bg-neutral-50 px-4 py-5 text-sm text-neutral-600">No working hours are configured yet. Add the days and times your business accepts appointments.</p>}
        </div>
        {validation ? <p role="alert" className="mt-2 text-sm text-red-700">{validation}</p> : null}
      </div>

      <div className="grid gap-4 rounded-xl bg-neutral-50 p-4 sm:grid-cols-3">
        <label className="block text-sm font-medium text-neutral-800">Appointments at once<input name="capacity" type="number" min={1} max={50} step={1} required defaultValue={settings.maxConcurrentAppointments} className="mt-2 h-10 w-full rounded-lg border-0 bg-white px-3 text-sm ring-1 ring-neutral-200 focus:outline-none focus:ring-2 focus:ring-orange-400" /><span className="mt-1 block text-xs font-normal text-neutral-500">Business-wide simultaneous capacity.</span></label>
        <label className="block text-sm font-medium text-neutral-800">Minimum notice (hours)<input name="notice" type="number" min={0} max={8760} step={1} required defaultValue={settings.minimumNoticeHours} className="mt-2 h-10 w-full rounded-lg border-0 bg-white px-3 text-sm ring-1 ring-neutral-200 focus:outline-none focus:ring-2 focus:ring-orange-400" /></label>
        <label className="block text-sm font-medium text-neutral-800">Booking window (days)<input name="horizon" type="number" min={1} max={365} step={1} required defaultValue={settings.bookingWindowDays} className="mt-2 h-10 w-full rounded-lg border-0 bg-white px-3 text-sm ring-1 ring-neutral-200 focus:outline-none focus:ring-2 focus:ring-orange-400" /></label>
      </div>

      {capacityWarnings && capacityWarnings.overlappingPeriods > 0 ? <p role="status" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950">Lowering capacity does not cancel existing appointments. {capacityWarnings.overlappingPeriods} time period{capacityWarnings.overlappingPeriods === 1 ? "" : "s"} in the next {capacityWarnings.horizonDays} days already exceed a capacity of {capacityWarnings.maxConcurrentAppointments}. New bookings will be accepted only when they stay within this limit.</p> : null}

      {error ? <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p> : null}
      <div className="flex items-center justify-between gap-3 border-t border-neutral-100 pt-4">
        <p role="status" aria-live="polite" className="text-sm text-emerald-700">{saved ? "Appointment settings saved." : ""}</p>
        <Button type="submit" disabled={saving || Boolean(validation)} className="h-10 rounded-full bg-orange-600 px-5 text-white hover:bg-orange-700 active:scale-[0.98] transition-transform duration-200 ease-[cubic-bezier(0.32,0.72,0,1)]">{saving ? t("common.saving") : "Save settings"}</Button>
      </div>
    </form>
    {notificationIssues.length ? <div className="border-t border-amber-200 bg-amber-50/70 px-6 py-5">
      <h3 className="text-sm font-semibold text-amber-950">Booking confirmation needs attention</h3>
      <p className="mt-1 text-sm text-amber-900/80">The appointment is saved in Calendar and its Inbox message is safe. Only the visitor confirmation email needs another attempt.</p>
      <ul className="mt-3 divide-y divide-amber-200/70">
        {notificationIssues.map((issue) => <li key={issue.id} className="flex flex-wrap items-center gap-3 py-3 first:pt-0 last:pb-0">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-neutral-900">{issue.typeName}</p>
            <p className="mt-1 text-xs text-neutral-700">{new Date(issue.startsAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: issue.timeZone })} · {issue.state === "sending" ? "Previous send did not finish" : "Confirmation not sent"}</p>
          </div>
          <Button type="button" disabled={retryingId === issue.id} onClick={() => void retryNotification(issue.id)} className="h-9 rounded-full bg-orange-600 px-4 text-white hover:bg-orange-700">{retryingId === issue.id ? "Retrying…" : "Retry email"}</Button>
        </li>)}
      </ul>
    </div> : null}
  </section>;
}
