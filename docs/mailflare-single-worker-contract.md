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
- Keep Mailflare UI routes and APIs namespaced so they cannot shadow Payload's
  API or a site's CMS-backed paths. The Message navigation opens Mailflare's
  native mailbox. Do not keep the bespoke Payload composer as a parallel path.
- Reuse the authenticated Payload owner session for Mailflare access. There is
  no second user password, cross-site SSO service, central account store, or
  public admin API key in a tenant runtime. Every Mailflare request must resolve
  the same tenant's authenticated Payload owner before reading or mutating mail.
- Site-Agent provisions domain resources with its protected host credentials.
  Cloudflare Email Routing delivers to that tenant's single Worker. Ordinary
  sending uses only the tenant-restricted Resend key already installed for its
  verified sender domain. The full-access Resend key and Cloudflare control
  tokens stay on the VPS.
- Platform-hosted tenants receive a unique address on `helloada.app`; when a
  custom domain is registered, Site-Agent provisions the tenant address on
  that domain before switching the active sender/recipient identity. A change
  is not complete until inbound routing and sending verification match the
  exact registered tenant and Worker.
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
- Import booking settings before inserting imported booking types, because
  Mailflare's booking-type triggers advance the settings revision. Continue to
  use the imported settings revision for capacity-checked calendar event writes.
- Website enquiries must arrive in Mailflare's Inbox and booking events must
  use Mailflare Calendar. Do not maintain a second Payload Inbox or calendar.
  Public form/booking writes remain server-side, validated and idempotent.

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
