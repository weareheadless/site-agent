import type { BookingD1 } from "@/lib/helloada-booking-service";

type Event = {
  id: string; user_id: string; mailbox_id: string | null; title: string; starts_at: number;
  time_zone: string | null; helloada_answers: string | null; helloada_booking_type_name: string | null;
  helloada_booking_duration_minutes: number | null;
};

export async function listBookingNotificationIssues(db: BookingD1, userId: string, now = Date.now()) {
  const result = await db.prepare(
    "SELECT id,title,starts_at,time_zone,helloada_booking_type_name,helloada_notification_state FROM calendar_events WHERE user_id=? AND booking_request_id IS NOT NULL AND (helloada_notification_state IN ('pending','failed') OR (helloada_notification_state='sending' AND COALESCE(helloada_notification_lease_until,0)<=?)) ORDER BY starts_at DESC LIMIT 20",
  ).bind(userId, now).all<Record<string, unknown>>();
  return (result.results ?? []).map((row) => ({
    id: String(row.id), title: String(row.title),
    startsAt: new Date(Number(row.starts_at)).toISOString(),
    timeZone: String(row.time_zone || "UTC"),
    typeName: String(row.helloada_booking_type_name || row.title),
    state: String(row.helloada_notification_state || "pending"),
  }));
}

export async function claimBookingConfirmation(db: BookingD1, userId: string, eventId: string, now = Date.now()) {
  const nowSeconds = Math.floor(now / 1000);
  const claim = await db.prepare(
    "UPDATE calendar_events SET helloada_notification_state='sending',helloada_notification_lease_until=?,updated_at=? WHERE user_id=? AND id=? AND booking_request_id IS NOT NULL AND (helloada_notification_state IN ('pending','failed') OR (helloada_notification_state='sending' AND COALESCE(helloada_notification_lease_until,0)<=?))",
  ).bind(now + 600_000, nowSeconds, userId, eventId, now).run();
  if (claim.meta?.changes !== 1) return null;
  try {
    const event = await db.prepare(
      "SELECT id,user_id,mailbox_id,title,starts_at,time_zone,helloada_answers,helloada_booking_type_name,helloada_booking_duration_minutes FROM calendar_events WHERE user_id=? AND id=? AND helloada_notification_state='sending' LIMIT 1",
    ).bind(userId, eventId).first<Event>();
  if (!event?.mailbox_id) throw new Error("booking_notification_event_invalid");
  let answers: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(String(event.helloada_answers || ""));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
    answers = parsed as Record<string, unknown>;
  } catch { throw new Error("booking_notification_details_invalid"); }
  const to = typeof answers.email === "string" ? answers.email.trim().toLowerCase() : "";
  const name = typeof answers.name === "string" ? answers.name.trim() : "";
  if (!name || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(to)) throw new Error("booking_notification_recipient_invalid");
  const mailbox = await db.prepare(
    "SELECT m.id,m.local_part,d.hostname,m.disabled,d.status FROM mailboxes m INNER JOIN domains d ON d.id=m.domain_id WHERE m.id=? AND m.user_id=? LIMIT 1",
  ).bind(event.mailbox_id, userId).first<{ id: string; local_part: string; hostname: string; disabled: number; status: string }>();
  if (!mailbox || mailbox.disabled || mailbox.status !== "active") throw new Error("booking_notification_mailbox_inactive");
  const timeZone = String(event.time_zone || "UTC");
  const startsAt = new Date(Number(event.starts_at));
  const duration = Number(event.helloada_booking_duration_minutes);
  const typeName = String(event.helloada_booking_type_name || "Appointment");
  if (!Number.isFinite(startsAt.getTime()) || !Number.isInteger(duration) || duration < 5 || duration > 480) throw new Error("booking_notification_snapshot_invalid");
  const date = new Intl.DateTimeFormat("en", { dateStyle: "full", timeStyle: "short", timeZone }).format(startsAt);
  return {
    userId, mailboxId: mailbox.id, from: mailbox.local_part + "@" + mailbox.hostname, to,
    subject: ("Appointment confirmed: " + typeName).slice(0, 180),
    text: ["Hello " + name + ",", "", "Your appointment is confirmed.", "Service: " + typeName,
      "Date and time: " + date, "Time zone: " + timeZone, "Duration: " + duration + " minutes"].join("\n"),
  };
  } catch (error) {
    try { await finishBookingConfirmation(db, userId, eventId, false); } catch {}
    throw error;
  }
}

export async function finishBookingConfirmation(db: BookingD1, userId: string, eventId: string, sent: boolean) {
  const result = await db.prepare(
    "UPDATE calendar_events SET helloada_notification_state=?,helloada_notification_lease_until=NULL,updated_at=? WHERE user_id=? AND id=? AND helloada_notification_state='sending'",
  ).bind(sent ? "sent" : "failed", Math.floor(Date.now() / 1000), userId, eventId).run();
  if (result.meta?.changes !== 1) throw new Error("booking_notification_state_conflict");
}
