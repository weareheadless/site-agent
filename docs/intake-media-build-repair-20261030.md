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

## Package publication

Source merged as `1fbf35e31919d4d87c3ba8e73042757949849089` (#521).
The `payload-admin-v0.10.44` workflow `41057815366` passed. The authenticated
release download matched both GitHub's digest and the source-bound manifest:

- SHA-256: `d52efc4c4ace9be4ccf82a8a615b75e326eed7edcab4ed531f2626a15f343d56`
- Integrity: `sha512-r+6ZFb061ivZlnalTCpSAfPyfSHb2WUrcmjS0IiP6x5NlN9RVlTKwFc3uHq+aWrmg6X8Dv5xL6Mzbb5+giwEQg==`

Local source checks passed 2,209 Python tests, 93 admin tests and typecheck.
Desktop/mobile fixtures exercised actual component code, real localhost XHR,
decoded existing/uploaded thumbnails, progress, tags and retained attachments.
Those fixtures mock service boundaries and do not prove production acceptance.
The runtime follow-up exercises the actual Worker upload/gallery handlers with
mocked authenticated Payload/transport boundaries, rather than source assertions.
