# Shared intake media and revised-brief handoff repair

Owner-authorized maintenance tracked in #520 and PR #521. This is not a claim
that a generated candidate is ready for owner review.

## Observed boundaries

`confirmed intake -> Ada planning -> Ada generation -> build -> deterministic validation -> visual/behavioral review -> owner review`

Astrid conversation 1 had confirmed revision 35 attached to a failed run bound
to an earlier confirmed revision. Recovery correctly rejected the mismatch,
but admission incorrectly selected recovery instead of a new run for the new
owner-confirmed brief. Historical failures and their identities remain intact.
Matching-revision recovery still requires its full persisted checkpoint.

Owner image uploads already persisted in Payload. Intake binding nevertheless
looked in the retired local asset inventory. The embedded gallery did not
refresh after uploads, and the upload request exposed no byte progress. Media
analysis had no upload trigger or shared conversation-provider configuration.

## Shared repair

- Validate/bind through the tenant's canonical media service. Read selected
  build-image bytes from that same service; no second content inventory.
- Show byte-based upload progress and immediate thumbnails inside the existing
  conversation gallery. Preserve successful attachments independently of later
  failures, and refresh canonical tags/status while the gallery is open.
- Derive upload-analysis provider settings from the conversation provider when
  no dedicated vision provider is configured. Keep build-time imagery reading
  opt-in and preserve explicitly configured provider settings.
- Treat Payload pending documents as durable analysis work. Worker notification
  accelerates analysis; the existing tenant scheduler recovers pending uploads
  after interruption. Serialize notification/scheduler callers; ready or failed
  analyses are not automatically replayed. No additional database or worker.
- Start a new immutable run for a newer confirmed intake, with a stable
  replacement reservation token. Repeated requests do not admit a second active
  build. Never rewrite the failed run or its frozen context.

## Release and acceptance

Source tests, package publication, API promotion, Worker canary/fan-out and
authenticated owner-visible verification are separate gates. Use only the
canonical release queue. No tenant repository or config edits are required.

The release must retain the conversation and confirmed brief. Rerun Ada from
that confirmed boundary through the existing application service. A successful
handoff is not proof of generated-site completion: hydration, defining behavior,
desktop/mobile/reduced-motion checks and actual owner review remain required.
Do not publish the candidate without explicit owner approval.
