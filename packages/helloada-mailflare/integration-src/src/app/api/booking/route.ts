import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth/cookies";
import { hasValidSessionMutationOrigin } from "@/lib/auth/origin";
import { getEnv } from "@/lib/cloudflare";
import { sendEmail } from "@/lib/email/send";
import { claimBookingConfirmation, finishBookingConfirmation, listBookingNotificationIssues } from "@/lib/helloada-booking-notifications";
import { getBookingCapacityWarnings } from "@/lib/helloada-booking-runtime";
import {
  createBookingType,
  deactivateBookingType,
  readBookingConfiguration,
  setBookingTypeActive,
  updateBookingSettings,
  updateBookingType,
  type BookingD1,
} from "@/lib/helloada-booking-service";

export const dynamic = "force-dynamic";
type RuntimeEnv = { DB: BookingD1 };
const noStore = { "Cache-Control": "private, no-store" };
const fail = (error: string, status: number) => NextResponse.json({ error }, { status, headers: noStore });

function statusFor(error: unknown) {
  const code = error instanceof Error ? error.message : "";
  if (code.endsWith("_conflict")) return 409;
  if (code === "booking_type_not_found") return 404;
  if (code.includes("_invalid") || code.endsWith("_required") || code.endsWith("_hours")) return 400;
  return 503;
}

export async function GET(request: Request) {
  const env = getEnv() as ReturnType<typeof getEnv> & RuntimeEnv;
  const user = await getCurrentUser(env, request);
  if (!user) return fail("unauthorized", 401);
  try {
    const [configuration, notificationIssues, capacityWarnings] = await Promise.all([
      readBookingConfiguration(env.DB, user.id),
      listBookingNotificationIssues(env.DB, user.id),
      getBookingCapacityWarnings(env.DB, user.id),
    ]);
    return NextResponse.json({ ...configuration, notificationIssues, capacityWarnings }, { headers: noStore });
  } catch (error) {
    return fail(error instanceof Error ? error.message : "booking_configuration_unavailable", statusFor(error));
  }
}

export async function POST(request: Request) {
  const env = getEnv() as ReturnType<typeof getEnv> & RuntimeEnv;
  const user = await getCurrentUser(env, request);
  if (!user) return fail("unauthorized", 401);
  if (!hasValidSessionMutationOrigin(request)) return fail("invalid_origin", 403);
  if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") return fail("request_must_be_json", 415);

  const raw = await request.text();
  if (new TextEncoder().encode(raw).byteLength > 16_384) return fail("request_too_large", 413);
  let body: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return fail("request_invalid", 400);
    body = parsed as Record<string, unknown>;
  } catch {
    return fail("request_invalid", 400);
  }

  const operation = typeof body.operation === "string" ? body.operation : "";
  try {
    if (operation === "retry_notification") {
      const eventId = typeof body.eventId === "string" ? body.eventId.trim() : "";
      if (!/^[a-zA-Z0-9_-]{1,120}$/.test(eventId)) return fail("booking_event_id_invalid", 400);
      const confirmation = await claimBookingConfirmation(env.DB, user.id, eventId);
      if (!confirmation) return fail("booking_notification_not_retryable", 409);
      try {
        await sendEmail(env as CloudflareEnv, confirmation);
        await finishBookingConfirmation(env.DB, user.id, eventId, true);
        return NextResponse.json({ state: "sent" }, { headers: noStore });
      } catch (error) {
        try { await finishBookingConfirmation(env.DB, user.id, eventId, false); }
        catch { console.error("Booking notification failure state could not be recorded", { eventId }); }
        const code = error instanceof Error ? error.message.slice(0, 180) : "delivery_failed";
        console.error("Booking notification retry failed", { eventId, code });
        return fail("booking_confirmation_delivery_failed", 502);
      }
    }
    if (operation === "update_settings") {
      const settings = await updateBookingSettings(env.DB, user.id, body.settings);
      const capacityWarnings = await getBookingCapacityWarnings(env.DB, user.id);
      return NextResponse.json({ settings, capacityWarnings }, { headers: noStore });
    }
    if (operation === "create_type") {
      return NextResponse.json({ type: await createBookingType(env.DB, user.id, body.type) }, { status: 201, headers: noStore });
    }
    if (operation === "update_type") {
      return NextResponse.json({
        type: await updateBookingType(env.DB, user.id, String(body.id || ""), Number(body.expectedRevision), body.type),
      }, { headers: noStore });
    }
    if (operation === "activate_type" || operation === "deactivate_type") {
      const updated = operation === "activate_type"
        ? await setBookingTypeActive(env.DB, user.id, String(body.id || ""), Number(body.expectedRevision), true)
        : await deactivateBookingType(env.DB, user.id, String(body.id || ""), Number(body.expectedRevision));
      return NextResponse.json({ type: updated }, { headers: noStore });
    }
    return fail("booking_operation_invalid", 400);
  } catch (error) {
    return fail(error instanceof Error ? error.message : "booking_operation_failed", statusFor(error));
  }
}
