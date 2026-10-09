# HelloAda Mailbox and Booking Calendar Contract

This document defines the shared runtime boundary for the HelloAda Messages
mailbox and optional booking Calendar. It complements the production
implementation plan; it is not a separate product or a deployment procedure.

## One tenant, one source of truth

- `site-agent` owns the shared Payload schema, server routes, admin UI and
  scaffold. Each customer uses that same versioned contract in its own Worker
  and D1 database.
- Payload is the sole record store for Contacts, Conversations, Messages,
  Message Operations, Appointment Types, Calendar Events and slot reservations.
  Private R2 stores raw inbound MIME and approved attachment bytes. Public
  website media storage is never used for private mail.
- Every query, operation, idempotency key and private object path is scoped to
  the registered tenant. Do not add an independent Mailflare database, a
  second mailbox/calendar app, or tenant-specific schema copies.

## Visitor flows

### Website forms

The canonical Payload form component validates and accepts a submission into a
durable operation. Processing creates or updates one Contact and one Inbox
Conversation. Email notification is not a prerequisite for preserving the
enquiry. The owner can review it and ask Ada to draft a reply; sending remains
an explicit owner decision.

### Website bookings

Only a published page's canonical booking block renders a booking form. The
block points to a published shared Appointment Type. The public Worker API
exposes bounded availability and non-identifying receipt status only; it never
returns guest records or the private calendar. Booking submission requires
same-origin validation, the configured anti-abuse check, rate limiting,
explicit appointment-processing consent and an idempotency key.

Availability is calculated in the owner's IANA time zone and returned as UTC
instants. A unique short-lived reservation plus the confirmed Calendar Event
prevents concurrent requests from claiming the same interval. A successful
booking creates one event and links its Contact and email conversation. A
confirmation is a separate transactional operation. Replies to that email
thread back into the same Messages conversation. A booking is not duplicated
as a second inbox lead.

The owner Calendar controls its time zone, booking horizon, minimum notice,
appointment types, duration, buffers and weekly availability. Cancellation
changes the event state and queues a transactional notice. Do not claim guest
self-service rescheduling or external calendar synchronization unless those
flows are implemented and validated explicitly.

Every registered tenant receives one deterministic default address: the
tenant's immutable ID as the local part on `helloada.app` while the site uses
its platform Worker origin (for example, `northstar-coffee@helloada.app`).
When a custom site domain is registered, the mailbox domain follows it and the
default local part becomes `hello`. The existing idempotent Cloudflare
provisioner owns the DNS/routing setup; it must finish before the mailbox is
reported active. A domain change is a provisioning transition, not an owner
editable text field or a second mailbox implementation.

## Owner mailbox semantics

- Inbox, Sent, Drafts, Archive, Spam and Trash are views over canonical
  Conversations and Messages, not separate stores. Search and pagination must
  be bounded and tenant-scoped.
- Saving a draft never sends. An approval binds to the exact saved message,
  recipients and revision. Any content change invalidates approval. Provider
  acceptance, definitive failure and uncertain delivery are distinct states;
  uncertain sends are never retried automatically.
- Reply, New Message, CC/BCC and eventual attachments use the same durable
  operation and approval boundary. Resend sends plain-text replies and new
  messages with threading headers; outgoing attachments remain unavailable
  until private attachment upload and provider limits are implemented.
- Incoming email and attachments remain private. Download requires an
  authenticated owner, a tenant-matching object key and verified size/type and
  digest. Do not render incoming HTML or remote tracking content.

## Email provider contract

Resend is the single provider for ordinary one-to-one business correspondence.
The Resend API sends approved replies and owner-composed messages. Its
account-level `full_access` management key remains in the protected site-agent
credential profile because it provisions domains and tenant keys; treat it as
high-impact and never place it outside the VPS secret store. Each tenant Worker
receives only a Resend `sending_access` key restricted to that tenant's exact
verified sender domain as the encrypted `RESEND_API_KEY` secret. Never put the
management key in a Worker, tenant repository, Wrangler variable, GitHub, or
model context.

Cloudflare Email Routing remains the inbound path to the tenant Worker.
Cloudflare's `EMAIL` binding remains the path for transactional notifications
and booking confirmations; it is not a second ordinary-mail sender. The Resend
sender domain is verified through the Resend API, and its declared DNS records
are added only after an exact Cloudflare DNS conflict check. Resend open/click
tracking is disabled. Existing conflicting records stop provisioning without
being overwritten. Each tenant key is created with the verified Resend domain
identity. Key creation intent is persisted before calling Resend; an interrupted
creation is reconciled by exact key name, and a domain change installs the new
key before revoking the prior one. Domain changes are provisioned before Payload
switches the active mailbox identity.

The read-only provisioning preflight verifies the Full access credential against
Resend before it reports `ready_to_apply`. Missing or send-only credentials are
an explicit action required and stop before tenant configuration, DNS, domain,
or key writes. Do not present a Cloudflare-only plan as a complete email plan.

`outboundProvider` and `outboundMode` are service-owned. Ordinary sends are
enabled only after the exact sender domain is verified, a tenant sending-only
key is installed in the Worker, Cloudflare inbound routing is active, and
Payload confirms the mailbox. There is no provider fallback. An approved send
uses one stable Resend idempotency key derived from the durable operation ID;
network/5xx/ambiguous responses become `uncertain` and are never automatically
resent. Definitive provider rejection becomes `failed`.

### Mailflare source and licensing gate

The inspected upstream `hieunc229/mailflare` repository is licensed under
AGPL-3.0. The inspected upstream snapshot was commit
`83ade981e588bd7d693fe4a14850a844bcd8984a` (2026-10-09). No Mailflare source
has been copied into this implementation. Before incorporating or deploying
Mailflare code as part of this network-accessible SaaS, the project must choose
and document an approved AGPL compliance route, including the corresponding
source-offer/notices and customer access obligations, or implement the required
capabilities independently against its documented interfaces. Do not describe
the current implementation as Mailflare-integrated until that gate is resolved.

## Release and data safety

- Schema and runtime changes ship through the canonical customer release
  pipeline. Existing tenants receive an explicit additive migration request;
  a Worker release alone never mutates an existing D1 schema.
- New tenants inherit the same shared schema and components from the canonical
  scaffold. Ada may propose supported content or booking configuration, but
  cannot change schema, migration, provider, secrets or provisioning.
- Do not claim this feature is production-ready until the exact migration and
  artifact receipts, provider configuration, tenant isolation, authenticated
  owner UI, real controlled inbound/outbound mail and booking concurrency/time
  zone behavior have been validated. A successful typecheck or build is not
  live evidence.
- Retention, deletion and private backup/restore policy must be explicit before
  launch. Do not add cleanup that discards customer messages without an
  approved retention contract.
