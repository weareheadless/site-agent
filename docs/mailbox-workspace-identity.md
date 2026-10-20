# Mailbox workspace identity

Payload authenticates each person before the mailbox gate dispatches a private
request. The mailbox and calendar represent the tenant business, not the login
subject. Their persistent owner is the row in `helloada_tenant_owners` for the
registered tenant.

For an existing workspace, always use that row's owner ID. It must refer to an
enabled HelloAda SSO-only account. A different authenticated login subject must
not create a new booking owner, move records, reset settings, or lose contact
and calendar visibility. Invalid persisted ownership fails explicitly.

For a new workspace, derive the initial owner ID from the tenant ID and register
it once. Every authenticated request still validates the Payload session before
using that workspace identity. Mailflare sessions alone never authorize access.

## Incident: 2026-10-20

Oceanic's `/mail/inbox` threw Cloudflare 1101 with `Mailflare tenant owner
identity conflicts with its registered owner`. The owner gate derived mailbox
users from the login subject but required one immutable owner per tenant for
bookings. Two authenticated login identities therefore conflicted in the same
tenant. This was persisted identity coupling, not missing email configuration.

The health and API connection release gates did not exercise a real owner
mailbox session. The regression suite must cover an existing registered owner,
different subsequent authenticated subjects, retained booking settings, rejected
unauthenticated requests and simultaneous first access by distinct subjects.
Live acceptance requires opening Messages in a fresh authenticated browser,
checking Inbox, compose, Contacts and Calendar, reloading, and recording the
exact Worker version. A healthy website/API alone does not validate Messages.

The repair uses existing canonical ownership and needs no data migration. Do
not delete/reassign mailbox users or rewrite booking records to resolve login
subject changes. Releases use the shared-runtime canary and automatic tenant
fan-out through `helloada-release.timer`.
