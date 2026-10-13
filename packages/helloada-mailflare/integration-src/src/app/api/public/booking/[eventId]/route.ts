import { NextResponse } from "next/server";
import { verifyTurnstileToken } from "@/lib/auth/turnstile";
import { getEnv } from "@/lib/cloudflare";
import { sendEmail } from "@/lib/email/send";
import { createPublicBooking, getPublicBookingDetails } from "@/lib/helloada-booking-runtime";
import { claimBookingConfirmation, finishBookingConfirmation } from "@/lib/helloada-booking-notifications";
import type { BookingD1 } from "@/lib/helloada-booking-service";

export const dynamic = "force-dynamic";
type BookingEnv = CloudflareEnv & { HELLOADA_TENANT_ID?: string; MAILFLARE_ADDRESS?: string; BOOKING_RATE_LIMIT?: { limit: (input: { key: string }) => Promise<{ success: boolean }> }; TURNSTILE_SITE_KEY?: string };
type RouteContext = { params: Promise<{ eventId: string }> };
const noStore = { "Cache-Control": "no-store" };
const fail = (error: string, status: number) => NextResponse.json({ error }, { status, headers: noStore });
const text = (value: unknown) => typeof value === "string" ? value.trim() : "";
const validEmail = (value: string) => {
  const at = value.indexOf("@");
  const dot = value.indexOf(".", at + 1);
  return value.length <= 254 && at > 0 && at === value.lastIndexOf("@") && dot > at + 1 && dot < value.length - 1
    && !Array.from(value).some((character) => character.charCodeAt(0) <= 32);
};
const sameOrigin = (request: Request) => {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try { return new URL(origin).origin === new URL(request.url).origin; } catch { return false; }
};

export async function GET(request: Request, { params }: RouteContext) {
  const env = getEnv() as BookingEnv;
  const tenantId = String(env.HELLOADA_TENANT_ID || "").trim();
  if (!tenantId || tenantId.startsWith("__")) return fail("tenant_identity_not_configured", 503);
  if (!env.TURNSTILE_SITE_KEY) return fail("booking_security_not_configured", 503);
  const { eventId } = await params;
  try {
    const date = new URL(request.url).searchParams.get('date') || undefined;
    const details = await getPublicBookingDetails(env.DB as unknown as BookingD1, tenantId, eventId, date, env.TURNSTILE_SITE_KEY);
    const { slots, turnstileSiteKey, ...event } = details;
    return NextResponse.json({ event, hostName: "", slots, turnstileSiteKey }, { headers: noStore });
  } catch (error) {
    const code = error instanceof Error ? error.message : "booking_unavailable";
    return fail(code, code === "booking_date_invalid" ? 400 : code === "booking_type_not_found" || code === "booking_settings_disabled" ? 404 : 503);
  }
}

export async function POST(request: Request, { params }: RouteContext) {
  const env = getEnv() as BookingEnv;
  const tenantId = String(env.HELLOADA_TENANT_ID || "").trim();
  if (!tenantId || tenantId.startsWith("__")) return fail("tenant_identity_not_configured", 503);
  if (!sameOrigin(request)) return fail("booking_origin_invalid", 403);
  const ip = request.headers.get("cf-connecting-ip")?.trim();
  if (!ip || !env.BOOKING_RATE_LIMIT || !env.TURNSTILE_SITE_KEY || !env.TURNSTILE_SECRET_KEY || !env.MAILFLARE_ADDRESS) {
    return fail("booking_security_or_mailbox_not_configured", 503);
  }
  try {
    const result = await env.BOOKING_RATE_LIMIT.limit({ key: ip });
    if (!result.success) return fail("booking_rate_limited", 429);
  } catch { return fail("booking_rate_limit_unavailable", 503); }
  if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") return fail("request_must_be_json", 415);
  const raw = await request.text();
  if (new TextEncoder().encode(raw).byteLength > 8_192) return fail("request_too_large", 413);
  let body: Record<string, unknown>;
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value)) return fail("request_invalid", 400);
    body = value as Record<string, unknown>;
  } catch { return fail("request_invalid", 400); }
  if (Object.keys(body).some((key) => !["startsAt", "name", "email", "guestEmails", "notes", "consent", "requestId", "turnstileToken", "website"].includes(key))) return fail("request_invalid", 400);
  if (typeof body.website === "string" && body.website.trim()) return NextResponse.json({ booked: true }, { headers: noStore });
  if (body.website !== undefined && typeof body.website !== "string") return fail("request_invalid", 400);
  if (body.consent !== true) return fail("booking_consent_required", 400);
  const requestId = text(body.requestId);
  const name = text(body.name);
  const email = text(body.email).toLowerCase();
  const rawNotes = text(body.notes);
  const rawGuests = body.guestEmails === undefined ? "" : body.guestEmails;
  if (typeof rawGuests !== "string" || rawGuests.length > 2_000) return fail("booking_details_invalid", 400);
  const guestEmails = rawGuests.split(",").map((value) => value.trim().toLowerCase()).filter(Boolean);
  if (guestEmails.length > 20 || guestEmails.some((value) => !validEmail(value))) return fail("booking_details_invalid", 400);
  const guests = [...new Set(guestEmails.filter((value) => value !== email))];
  const notes = [rawNotes, guests.length ? "Guests: " + guests.join(", ") : ""].filter(Boolean).join("\n\n");
  const startsAt = text(body.startsAt);
  if (!/^[a-zA-Z0-9_-]{16,80}$/.test(requestId)) return fail("booking_request_id_invalid", 400);
  if (!name || name.length > 120 || !validEmail(email)
    || notes.length > 2_000 || (body.notes !== undefined && typeof body.notes !== "string")
    || !Number.isFinite(Date.parse(startsAt)) || new Date(startsAt).toISOString() !== startsAt) return fail("booking_details_invalid", 400);
  if (!(await verifyTurnstileToken(env, request, body.turnstileToken))) return fail("booking_security_check_failed", 400);

  let sourcePage = "";
  try {
    const referer = new URL(request.headers.get("referer") || "");
    if (referer.origin === new URL(request.url).origin) sourcePage = (referer.pathname + referer.search).slice(0, 500);
  } catch { /* Referrer is optional and never used as a destination. */ }
  const { eventId } = await params;
  try {
    const result = await createPublicBooking(
      env.DB as unknown as BookingD1, tenantId, env.MAILFLARE_ADDRESS, eventId,
      { startsAt, name, email, notes, requestId, consent: true, sourcePage },
    );
    if (result.state === "unavailable") return fail("booking_slot_unavailable", 409);
    let confirmationEmailSent: boolean | null = null;
    if (result.state === "created") {
      const db = env.DB as unknown as BookingD1;
      let claimed = false;
      try {
        const confirmation = await claimBookingConfirmation(db, result.userId, result.eventId);
        if (confirmation) {
          claimed = true;
          await sendEmail(env as CloudflareEnv, { ...confirmation, publicOrigin: new URL(request.url).origin });
          await finishBookingConfirmation(db, result.userId, result.eventId, true);
          confirmationEmailSent = true;
        }
      } catch (error) {
        if (claimed) {
          try { await finishBookingConfirmation(db, result.userId, result.eventId, false); }
          catch { console.error("Website booking confirmation state could not be recorded", { eventId: result.eventId }); }
        }
        const code = error instanceof Error ? error.message.slice(0, 180) : "delivery_failed";
        console.error("Website booking confirmation email failed", { eventId: result.eventId, code });
        confirmationEmailSent = false;
      }
    }
    return NextResponse.json({ booked: true, startsAt, confirmationEmailSent }, { headers: noStore });
  } catch (error) {
    const code = error instanceof Error ? error.message : "booking_submission_failed";
    const status = code === "booking_request_id_conflict" || code === "booking_capacity_changed" ? 409
      : code === "booking_type_not_found" || code === "booking_settings_disabled" ? 404 : 503;
    return fail(code, status);
  }
}
