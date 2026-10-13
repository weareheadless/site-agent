"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { authFetch } from "@/lib/auth/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { BookingType } from "@/lib/helloada-booking-service";

const slugify = (value: string) => value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80);
const initial = { name: "", description: "", durationMinutes: 30 };

export function BusinessBookingTypes() {
  const [types, setTypes] = useState<BookingType[]>([]);
  const [form, setForm] = useState(initial);
  const [editing, setEditing] = useState<BookingType | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  async function refresh() {
    const response = await authFetch("/api/booking");
    const data = await response.json() as { types?: BookingType[]; error?: string };
    if (!response.ok || !data.types) throw new Error(data.error || "Appointment types could not be loaded.");
    setTypes(data.types);
  }

  useEffect(() => {
    let active = true;
    void authFetch("/api/booking")
      .then(async (response) => {
        const data = await response.json() as { types?: BookingType[]; error?: string };
        if (!response.ok || !data.types) throw new Error(data.error || "Appointment types could not be loaded.");
        if (active) setTypes(data.types);
      })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Appointment types could not be loaded."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  function startEdit(type: BookingType) {
    setEditing(type);
    setForm({ name: type.name, description: type.description, durationMinutes: type.durationMinutes });
    setError("");
    setSaved("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSaved("");
    try {
      const operation = editing ? "update_type" : "create_type";
      const response = await authFetch("/api/booking", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation,
          ...(editing ? { id: editing.id, expectedRevision: editing.revision, type: { ...form, slug: editing.slug } }
            : { type: { ...form, slug: slugify(form.name) } }),
        }),
      });
      const data = await response.json() as { error?: string };
      if (!response.ok) throw new Error(data.error || "Appointment type could not be saved.");
      await refresh();
      setForm(initial);
      setEditing(null);
      setSaved(editing ? "Appointment type updated." : "Appointment type added.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Appointment type could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function setActive(type: BookingType, enabled: boolean) {
    setError("");
    setSaved("");
    try {
      const response = await authFetch("/api/booking", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation: enabled ? "activate_type" : "deactivate_type",
          id: type.id,
          expectedRevision: type.revision,
        }),
      });
      const data = await response.json() as { error?: string };
      if (!response.ok) throw new Error(data.error || "Appointment type could not be updated.");
      await refresh();
      setSaved(enabled ? "Appointment type activated." : "Appointment type deactivated.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Appointment type could not be updated.");
    }
  }

  return <section aria-labelledby="booking-types-title" className="overflow-hidden rounded-2xl bg-white shadow-[0_12px_40px_rgba(35,42,54,0.06)] ring-1 ring-neutral-200/80">
    <div className="border-b border-neutral-100 px-6 py-5">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-orange-600">Appointments</p>
      <h2 id="booking-types-title" className="mt-1 text-xl font-semibold tracking-tight text-neutral-950">Appointment types</h2>
      <p className="mt-1 max-w-2xl text-sm leading-6 text-neutral-600">Name each service and set how long it takes. Working hours and booking capacity are shared above.</p>
    </div>
    <div className="space-y-4 px-6 py-5">
      {loading ? <p className="text-sm text-neutral-500">Loading appointment types...</p> : types.length === 0
        ? <p className="rounded-xl bg-neutral-50 px-4 py-5 text-sm text-neutral-600">No appointment types yet. Add a service to let Ada connect it to a booking form.</p>
        : <ul className="divide-y divide-neutral-100">
          {types.map((type) => <li key={type.id} className="flex flex-wrap items-center gap-3 py-4 first:pt-0 last:pb-0">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-neutral-900">{type.name}</p>
              <p className="mt-1 text-xs text-neutral-500">{type.durationMinutes} minutes · <span className={type.enabled ? "text-emerald-700" : "text-neutral-500"}>{type.enabled ? "Active" : "Inactive"}</span></p>
              {type.description ? <p className="mt-1 text-sm text-neutral-600">{type.description}</p> : null}
            </div>
            <Button type="button" variant="outline" onClick={() => startEdit(type)} className="h-9 rounded-full px-4">Edit</Button>
            <Button type="button" variant="outline" disabled={saving} onClick={() => void setActive(type, !type.enabled)} className="h-9 rounded-full px-4">{type.enabled ? "Deactivate" : "Activate"}</Button>
          </li>)}
        </ul>}

      <form onSubmit={(event) => void save(event)} className="grid gap-3 border-t border-neutral-100 pt-5 sm:grid-cols-[1.2fr_1fr_120px_auto]">
        <label className="text-xs font-medium text-neutral-700">Service name<Input required maxLength={120} value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} className="mt-1.5" placeholder="Consultation" /></label>
        <label className="text-xs font-medium text-neutral-700">Duration (minutes)<Input required type="number" min={10} max={480} step={5} value={form.durationMinutes} onChange={(event) => setForm((value) => ({ ...value, durationMinutes: Number(event.target.value) }))} className="mt-1.5" /></label>
        <label className="text-xs font-medium text-neutral-700 sm:col-span-2">Description (optional)<Input maxLength={2000} value={form.description} onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))} className="mt-1.5" /></label>
        <div className="flex items-end gap-2 sm:col-span-2">
          <Button type="submit" disabled={saving || !slugify(form.name)} className="h-10 rounded-full bg-orange-600 px-5 text-white hover:bg-orange-700">{saving ? "Saving..." : editing ? "Save changes" : "Add appointment type"}</Button>
          {editing ? <Button type="button" variant="outline" disabled={saving} onClick={() => { setForm(initial); setEditing(null); }} className="h-10 rounded-full">Cancel</Button> : null}
        </div>
      </form>
      {error ? <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p> : null}
      <p role="status" aria-live="polite" className="text-sm text-emerald-700">{saved}</p>
    </div>
  </section>;
}
