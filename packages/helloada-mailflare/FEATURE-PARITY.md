# Mailflare feature parity and tenant boundary

Pinned to upstream `ca41c56a0781bf848b9898ddcc5615b3eacfbf8e`. “Built” means present in the single-Worker artifact, not live or customer-verified.

| Surface | HelloAda disposition | Acceptance boundary |
| --- | --- | --- |
| Inbox, threads, search, folders, spam, trash, snooze, archive, drafts, compose, reply, scheduled send, sent history, contacts, rules, templates, import/export | Native Mailflare UI and API at `/mail` | Owner access uses the authenticated Payload identity and Mailflare mailbox authorization. |
| Attachments, Drive, sharing | Native Mailflare UI and API | Objects remain tenant-isolated; public links are capability-scoped. |
| Inbound, outbound, queues, scheduled work | Native Worker `email`, `queue`, and `scheduled` handlers composed with OpenNext | One Worker handles all events. Resend key is tenant-restricted; owner send is explicit and never blindly retried. |
| Calendar and public booking | Native Mailflare Calendar and booking routes | Booking requires same-origin, rate-limit, Turnstile, consent and idempotency checks. |
| Mailflare agent and approvals | Native feature is included | Must not replace Ada or bypass owner approval; tenant AI bindings and user-visible flow still need live verification. |
| Mailflare login, registration, setup, password reset and account switch | Replaced by Payload SSO; native auth APIs are denied | Payload remains the sole owner identity provider. |
| Mailflare admin/account, users, domains/DNS, licenses, backups, migration controls, branding, webhooks and platform-update settings | Not tenant-owner features; keep inaccessible | Synthetic SSO account is non-admin. API authorization must enforce this, not just hide navigation. |
| Password, app-password and unscoped API-key settings | Disabled for synthetic SSO identity | No second password or cross-tenant credential is created. |
| Existing Payload mailbox/calendar data | Migration and retirement remain incomplete | Do not hide/delete source until row/reference/object-hash reconciliation and tenant UI checks pass. |

## Release gates

1. CI builds the pinned source with release Node/npm, verifies `/mail`, static assets, the full upstream migration chain and every HelloAda patch.
2. Owner-gate tests cover private pages/APIs, Payload redirects, denied standalone auth and the exact public-route allowlist.
3. Each tenant receives isolated Mailflare D1, R2, queues and sender credentials. No central Worker, cross-tenant database or Cloudflare management token enters tenant runtime.
4. Verify inbound delivery, a draft surviving reconnect, exactly one owner-authorized send, threading, private attachments, calendar booking and cross-tenant denial.
5. A build receipt is not acceptance. Customer-ready means no required Payload record or object is lost or changed in meaning during migration.
