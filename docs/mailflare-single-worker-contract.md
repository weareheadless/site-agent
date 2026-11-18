# Mailflare inside the tenant Worker

This is the canonical contract for the HelloAda mailbox. It supersedes the
Payload/Resend mailbox design in `helloada-messages-contacts-production-implementation-plan.md`
and the earlier `helloada-mailbox-calendar-contract.md` wherever they conflict.

## Product boundary

- The customer-facing identity is HelloAda: the mailbox title, manifest, browser/PWA icon and sidebar mark use the canonical HelloAda SVG from the Payload scaffold. The upstream product name and mark do not appear in the owner UI; upstream provenance, required license notices and internal identifiers remain intact. Tenant owners cannot customize the platform brand.
- Contacts and Calendar are native mailbox capabilities. Website enquiries create or update a Contact and appear in Inbox; a confirmed website booking creates a Calendar event linked to that Contact and its conversation. Do not add a separate CRM/calendar store or duplicate live workflow.

- Reuse Mailflare's upstream inbox, composer, mail-processing and calendar code;
  do not design a second mailbox UI or reimplement those capabilities.
- `site-agent` remains the only source of tenant application code. Its shared
  Payload package includes the pinned Mailflare integration, and every tenant
  receives it through the existing Worker release pipeline.
- Each tenant has exactly one production Worker for its website, Payload admin,
  Mailflare routes, inbound email, queue consumers and scheduled work. Do not
  deploy a central Mailflare Worker, per-customer Mailflare Worker, or service
  binding to a second application.
- Payload remains the authority for website content and owner authentication.
  Mailflare owns mailbox/calendar records using its native schema and APIs.
  Keep Mailflare records out of Payload collections; use an isolated Mailflare
  D1 database per tenant to avoid schema and identity collisions with Payload.
- Reuse the tenant's existing private email R2 bucket when it satisfies
  Mailflare's object semantics. Mailflare's database, queues, raw messages and
  attachments must remain tenant-isolated. No Cloudflare management credentials
  are copied into a customer Worker.

## Integration rules

- Pin the exact upstream Mailflare commit in the shared package and retain its
  source provenance. Integration patches and HelloAda adapters are versioned in
  `site-agent`; builds must not fetch a moving upstream branch.
- Adapt Mailflare's Cloudflare entry points to the existing OpenNext Worker;
  the Worker continues to export one `fetch`, `email`, `queue` and `scheduled`
  handler. Mailflare queue messages are explicitly discriminated and may not be
  acknowledged by the website-message processor or vice versa.
- Keep Mailflare APIs namespaced so they cannot shadow Payload's API or a
  site's CMS-backed paths. The owner's mailbox UI is served once, by the
  control plane, from the shared generated package; a page request on a tenant
  origin under `/mail/*` is handed to that entry instead of rendering a second
  mailbox. The tenant Worker keeps the mail API, the mailbox data and the
  public booking endpoints, and its build does not compile the upstream owner
  pages at all, so a page request cannot render a parallel admin even if the
  handover were misconfigured. Do not keep a bespoke composer, calendar or
  second mailbox UI as a parallel path.
- Reuse the authenticated Payload owner session for Mailflare access. There is
  no second user password, cross-site SSO service, central account store, or
  public admin API key in a tenant runtime. Every Mailflare request must resolve
  the same tenant's authenticated Payload owner before reading or mutating mail.
- Site-Agent provisions domain resources with its protected host credentials.
  Cloudflare Email Routing delivers to that tenant's single Worker. The Worker
  sends ordinary mail through Cloudflare Email Sending from the tenant's own
  mailbox address, using its `EMAIL` binding; there is no third-party sender
  account, no per-tenant sending key and no provider domain quota to exhaust.
  Cloudflare control tokens stay on the VPS.
- Platform-hosted tenants receive a unique address on `helloada.app`; when a
  custom domain is registered, Site-Agent provisions the tenant address on
  that domain before switching the active sender/recipient identity. A change
  is not complete until inbound routing and sending verification match the
  exact registered tenant and Worker.
- The domain event is the trigger. Registering or changing a tenant's custom
  domain updates the mailbox domain and wakes `email_provisioning`
  immediately; the learned local part and a mailbox domain the owner
  registered explicitly survive that change. The owner may review and set the
  mailbox name and domain in website settings, which shows whether the
  mailbox is live, pending, or blocked and why.
- Every tenant's zone must be reachable by the one protected Cloudflare Email
  credential. A credential scoped to a fixed zone list leaves each new custom
  domain on the platform sender; that is a host configuration defect and is
  reported as `action_required`, never retried as a transient failure.
- Owner Send in Mailflare is the explicit send action. Ada may read mail and
  prepare drafts only through the existing approved assistant boundary; it
  never sends or changes a message without the owner's confirmation.

## Data transition

- Historical Payload mailbox data is retained for the migration-only importer;
  the retired Payload inbox and calendar APIs and UI are not runtime fallbacks.
  Export Contacts, Conversations, Messages, drafts, operations, attachments and
  delivery receipts from each tenant. Import them idempotently into that
  tenant's Mailflare database/storage, then compare counts, addresses, thread
  links, attachment hashes and statuses.
- Keep old records readable to the explicit importer until migration evidence
  is recorded for OceanicVibes, Atelier and Northstar. Do not dual-write or
  silently discard data. The shared default runtime has one Mailflare inbox;
  Payload mailbox collections are migration input only and must not be exposed
  as a second live inbox or calendar.
- The first authorized mailbox request runs the versioned import only after
  acquiring the tenant's durable D1 lease. Concurrent requests in one Worker
  isolate share that import; requests in another isolate receive an explicit
  `migration_in_progress` response and the browser is asked to retry. The owner
  gate does not dispatch private mailbox pages or APIs until the import is
  complete. Lease contention is lifecycle state, never an uncaught Worker
  exception, and no alternate data source is served while importing.
- `helloada_import_runs` is keyed by tenant and stores that tenant's current
  import version. A completed v1 row advances in place to v2 after any active
  v1 lease ends; do not insert a second row for the same tenant or add a
  tenant-specific schema change for a version transition.
- Import booking settings before inserting imported booking types, because
  Mailflare's booking-type triggers advance the settings revision. Continue to
  use the imported settings revision for capacity-checked calendar event writes.
- Website enquiries must arrive in Mailflare's Inbox and booking events must
  use Mailflare Calendar. Do not maintain a second Payload Inbox or calendar.
  Public form/booking writes remain server-side, validated and idempotent.

## Public booking and website forms

- The public booking surface is `GET /booking/<bookingTypeId>` on the tenant
  origin, rendered by the one shared booking form. It reads the Turnstile
  sitekey from the Worker's own binding and talks only to the tenant's public
  booking API under `/mail/api/public/booking/<bookingTypeId>`. A tenant page
  may pass `?stylesheet=<same-origin path>` so the form uses that site's
  typography; it may never name another origin.
- A committed static presentation links to that page with an anchor. Its
  inventory validator treats every referenced asset as a committed file, so an
  embedded runtime route (an `iframe` source) is not presentation source. Do
  not add a second booking client to a static page; the shared form is the
  client.
- Owner booking configuration is `POST /api/workspace/booking` with
  `update_settings`, `create_type`, `read_availability`, `update_type`,
  `activate_type` and `deactivate_type`. The route is shared runtime, so every
  tenant's Worker answers it. Booking types carry immutable
  `ha_booking_<32hex>` identities derived from the workspace owner and slug;
  settings and types are Mailflare D1 data, never Payload documents.
- The workspace owner is provisioned by `ensureTenantBookingOwner`, the same
  deterministic identity the mailbox gate uses, so server-to-server booking
  configuration does not depend on an owner having opened the mailbox first. A
  registered owner is reused verbatim and a disabled owner fails closed.
- A website form is a Payload `contactForms` document owned by the site. Its
  public submission is `POST /api/helloada/forms/<slug>`: same-origin only,
  rate limited per tenant and IP, honeypot and Turnstile verified, idempotent
  per request ID, and validated against the form's own stable field keys. The
  enquiry becomes a Mailflare Inbox message with the Contact. A static page
  carries those stable field keys in its markup and posts the same contract; it
  never writes inbox records itself.

### The delivery contract

A form or booking that Ada creates is a promise that what a visitor sends
reaches the owner. Both surfaces are one write path, and that path must always
produce the same records, linked, in the mailbox the owner actually reads:

| Surface | Written by the platform, in one batch |
| --- | --- |
| Enquiry (`/api/helloada/forms/<slug>`) | Inbox message (`direction=inbound`, `helloada_delivery_state=received`) carrying `helloada_contact_id` and `helloada_source_page`, plus the Contact it points at |
| Booking (`/mail/api/public/booking/<type>`) | Calendar event with `attendees=[visitor email]` and the booking detail in its description, the Contact, and the Inbox message that shares that Contact |

Rules the implementation must keep:

- **One write path.** A page, a static file or an Agent may render a form
  surface, but it posts to the two endpoints above and never writes Mailflare
  records itself. A second delivery path is the defect.
- **Every record is attributable.** An enquiry message without its contact and
  source page, or a calendar event without the guest address, leaves the owner
  holding a record they cannot answer or match to the email in the inbox.
- **Timestamps are unix seconds.** The mailbox reads `messages`, `contacts` and
  `calendar_events` timestamps as seconds. Milliseconds render an impossible
  date and sort the record out of the inbox.
- **A form document is treated as an account of intent, not a layout.** Payload
  refuses to save a form that does not map one `email` field and one enquiry
  `message` field, so a published form is deliverable by construction. A booking
  block may only reference an active booking type whose settings are enabled.
- **The visitor stays on the page.** A successful enquiry shows the
  confirmation in place and offers any further handoff (such as WhatsApp) as an
  explicit link. An automatic redirect hides the delivery from the visitor and
  from whoever is testing it.
- **One tenant has one mailbox, at the address it is registered with.** A
  mailbox id is derived from its address, so an address change (platform domain
  to custom domain, or one custom domain to another) must move that mailbox, not
  add a second one. Provisioning folds the tenant's previous addresses into the
  registered mailbox: messages and folders move across, the old address stays an
  alias so it keeps delivering into the same inbox, and the superseded mailbox
  loses its access grants. Two mailboxes under one site is how an owner opens an
  empty inbox while site mail lands in the other one.

## Release and acceptance

- New tenant creation provisions the isolated Mailflare D1/mail resources and
  mailbox identity as part of the existing Site-Agent bootstrap. Existing
  tenants use the same shared package and migration path; no customer-specific
  mailbox implementation is allowed.
- Deploy only through the official `site-agent/main` release queue. The exact
  Mailflare source pin, package version, tenant release SHA, schema migration
  and deployed artifact identity must be in CI/receipts.
- Validate one tenant end-to-end first: authenticated Payload session opens the
  native Mailflare UI; inbound mail reaches the correct mailbox; drafts persist
  after reconnect; owner send creates a Sent copy and delivers once; reply
  threading and attachment privacy hold; calendar bookings are visible; a
  second tenant cannot access any of its records. Then run the same release and
  checks for Atelier and Northstar.
- Do not claim completion from a build or public health check. Confirm exact
  release receipts and fresh authenticated browser behavior. Do not remove old
  data or claim all tenants migrated until each tenant's checks pass.
