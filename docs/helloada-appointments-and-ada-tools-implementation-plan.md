# HelloAda appointments, Calendar workspace and Ada tools — implementation plan

Status: agreed product specification; implementation pending.
Date: 2026-10-11.
Repository: weareheadless/site-agent.
Audience: coding AI implementing the complete shared product.
This document contains requirements and implementation sequencing, not source code.

## 1. Goal and agreed product model

A business owner asks Ada to add appointment booking to a website. Ada reads the business's booking configuration, helps configure any missing details, and builds a website form connected to the shared appointment service. A visitor selects a booking type and an available start time. A successful submission saves one appointment, displays it in the owner's Calendar, and creates an Inbox notification linked to the visitor's Contact. Transactional email delivery follows the persisted appointment.

An appointment is an appointment. A callback, massage or consultation differs by its name and duration, not by its underlying workflow. Do not introduce callback-request modes, request-only bookings, separate lead booking flows, staff allocation or a second scheduling engine.

The owner's core configuration is:
- Booking types: name, stable identity, duration and active status.
- Business working hours and IANA timezone.
- Maximum simultaneous appointments across the business, defaulting to one.

A two-hour appointment occupies one unit of capacity for its entire interval. Capacity two permits two overlapping appointments across all booking types. It does not assign either appointment to a named staff member or promise individual staff availability.

Calendar must appear inside the main Payload workspace, preserving the same navigation and layout as Messages. Booking-type configuration belongs in Settings. The calendar is the operational view of appointments, not a landing page listing meeting templates.

## 2. Authority and existing architecture

Follow root AGENTS.md, deploy/README.md and docs/mailflare-single-worker-contract.md. This plan refines the product UX and appointment behavior in that canonical contract. The earlier docs/helloada-mailbox-calendar-contract.md is marked historical; do not revive its Payload mailbox storage model.

Current main contains:
- packages/helloada-mailflare: a pinned, pristine upstream snapshot plus integration patches applied to a disposable build copy.
- packages/helloada-payload-admin/src/components/MailflarePayloadView.tsx: the shared embedded inbox/calendar surface, currently selecting /mail/inbox or /mail/calendar.
- Native Mailflare booking configuration/editor and Calendar records, integrated through shared build patches.
- Shared runtime overlay and automatic canary-first tenant fan-out, driven by the VPS release queue.

Search the actual current main before editing. Search results or old plans may reference retired files; do not restore missing calendar.ts or old Payload booking routes merely because historical documentation mentions them.

Payload owns website content and owner authentication. Mailflare's tenant-isolated D1 owns live mailbox, Contact and Calendar records. Booking configuration must have one authoritative representation in that same appointment subsystem, editable through Settings and Ada's tools. A Payload page/form may store a stable reference to a booking type; it must not store a competing copy of availability, capacity or appointments.

Every tenant retains one Worker. Extend the existing shared integration and use its canonical service boundaries. Do not add tenant-specific implementations, provider fallbacks, a parallel calendar database, a second login or a separate application deployment.

## 3. First task: audit the real implementation

Before implementation, inventory and record the current paths for:
- Calendar, booking-type and booking-instance tables, indexes and committed migrations.
- Public availability and booking submission APIs.
- Inbox/Contact creation and transactional notifications.
- Website form/block definitions, supported renderers and public form processing.
- Ada tool registration, authenticated tenant service adapters, intake generation and later design-edit validation.
- Embedded Payload navigation, native Mailflare sidebar, Calendar routes and Settings routes.
- Calendar create/update/cancel paths that can change availability.
- Default booking templates and configuration inherited by newly provisioned tenants.

Identify which capabilities already work and the exact missing boundaries. Preserve existing reusable Mailflare services. Update conflicting active instructions and contracts with this plan's appointment model. Mark older overlapping requirements as superseded where necessary; keep historical records clearly archival.

Deliver the audit in the PR description or a short companion document. Do not turn the audit into a separate implementation that bypasses the shared system.

## 4. Settings and minimal data contract

Provide a Settings section named Bookings or Appointments in the existing Settings experience.

Booking types need:
- Immutable ID and stable reference usable by website content.
- Owner-facing name.
- Duration in whole minutes, validated within one centrally defined supported range.
- Active/inactive state.

Business booking settings need:
- Valid IANA timezone.
- Weekly working hours, supporting closed days and multiple opening intervals when the existing editor already supports them.
- Positive integer maximum simultaneous appointments.
- Any already-required operational limits, such as minimum notice and booking horizon, presented progressively rather than expanding the basic setup.

Use business-wide availability and capacity in version one. Do not copy working hours into each type as an independent authority. Retain existing useful settings only when their semantics remain consistent and they are backed by the same service.

A booking instance records the type identity, duration/name snapshot, UTC start/end, Contact identity, lifecycle state and idempotency identity. Historical appointments retain their booked interval when a type's duration changes. Editing business hours affects future availability and does not silently move or cancel appointments.

Deactivate a referenced type rather than deleting its identity. Forms referencing an inactive type display a clear unavailable state. Settings warn about published references and existing future appointments when relevant. Capacity reductions do not cancel existing appointments; explain existing overlaps and reject new appointments that exceed the reduced capacity.

Do not show automatically generated sample meetings as configured business services. Existing real booking types must be preserved through an explicit migration if needed. Newly created tenants start with a truthful unconfigured state and Ada can guide setup.

Use committed, explicit migrations for necessary data/schema changes. Inspect and reconcile the already-deployed integration extensions before adding new columns. Never generate or guess migrations during deployment.

## 5. Calendar and navigation UX

Keep the Payload outer navigation visible through Messages, Contacts, Calendar and Settings. Keep the native mailbox navigation available when moving among its internal surfaces.

Calendar is rendered inside the same main content area as Inbox. Internal navigation uses the embedded document or the parent workspace's supported view selection; it never opens a new tab/window or replaces the entire Payload page with /mail/calendar.

Audit native route-group layouts, link targets, window-opening behavior, responsive sidebar state and embedded-mode CSS. Fix the shared causes. A hardcoded Oceanic URL or customer-only CSS patch is unacceptable.

The Calendar view shows actual appointments and existing calendar events, with useful date navigation and readable event details. Booking type management moves to Settings. Remove the separate Bookings destination from primary operational navigation, and update links, menus and route entry behavior consistently. Any retained internal route serves the canonical Settings section, rather than maintaining a second editor.

Maintain HelloAda branding and use its existing logo. Preserve upstream provenance and license notices where required. Do not design a replacement mailbox or calendar from scratch.

At smaller viewports, the sidebar may collapse using the established responsive control; navigation must remain discoverable and switching to Calendar must not change that behavior unexpectedly.

## 6. Shared appointment service and capacity correctness

Expose one service used by public website booking, Settings, Ada tools and calendar mutations affecting bookable time.

Availability calculates candidate intervals from the chosen type's duration, business hours, timezone and active capacity-consuming events. Return bounded public slot data only; never expose visitor identities, private event descriptions or the owner's full calendar.

Use half-open intervals: an appointment ending at 11:00 does not overlap one starting at 11:00. Capacity must be checked at every relevant interval boundary, not by counting all events that intersect a long requested interval. Two nonoverlapping existing events within one requested interval do not by themselves consume two simultaneous units.

Save admission atomically in the authoritative database. Prefer an atomic, conditional D1 transaction/batch compatible with the existing service, where the overlap-capacity predicate and appointment insertion execute together. A separate availability read followed by an unconditional insert is forbidden.

Prove the exact admission primitive against real D1 concurrency before adopting it. If the current D1/service primitives cannot enforce the invariant, document that evidence and implement one tenant-scoped serialization boundary using the existing Worker architecture. Select and ship one correctness mechanism; do not leave two runtime paths or a silent fallback.

Use a stable client-generated submission idempotency key scoped to tenant. Repeated identical submissions return the original appointment; reusing the key with changed input fails explicitly. Calendar creation and the booking record must not be independently duplicated.

All operations that change busy intervals, including owner-created busy events and rescheduling, must obey a documented capacity policy. Active appointments consume one unit. Existing manual busy calendar entries should consume one unit unless the existing event schema explicitly marks them as nonblocking. Apply the same interpretation in slot listing and final admission.

Concurrent visitors competing for the final place produce one success and a clear slot-unavailable response. Capacity two permits exactly two concurrent appointments, including across different booking types. Canceling an appointment releases its interval. Rescheduling must preserve the original appointment if admission at the new interval fails.

Store instants in UTC; calculate working hours in the business timezone. Explicitly handle daylight-saving gaps and repeated times. Changing the business timezone does not reinterpret stored appointment instants.

## 7. Visitor booking flow, Inbox and notifications

Reuse the canonical website booking block/form and extend it only where necessary to reference the authoritative booking type.

The form presents the type, duration, available date/time, visitor contact fields and confirmation. If one type is bound, preselect it; a multi-type form can offer a configured list without duplicating type definitions. Ada controls website styling and layout within the shared content contract.

Public submission must resolve the type on the server, validate timezone-independent slot identity, recompute capacity, validate visitor fields and use existing anti-abuse/rate-limit controls. A hidden type ID or a client-supplied duration is not trusted business configuration.

Once admitted:
1. Persist the appointment and its Contact relationship.
2. Create one Inbox message/conversation notification with the type, time, visitor details and a link to the Calendar event.
3. Record transactional notification work using the existing durable processing path.
4. Return a non-identifying confirmation to the visitor.

Notification failure must not lose a saved appointment or create another appointment on retry. Show a truthful delivery state to the owner. Use existing approved transactional email infrastructure; do not add an ordinary-message sender or bypass existing mailbox provisioning.

Maintain one booking identity across Calendar, Contact and Inbox. Avoid a second independent form-submission lead for the same booking. Public responses cannot expose private Inbox URLs or authenticated owner data.

Support owner cancellation and, if already available, rescheduling through the same shared service. Do not promise visitor self-service or external Google/Outlook calendar synchronization in this version.

## 8. Ada's tools and service access

Give Ada explicit, tenant-scoped capabilities through the existing tool framework and application services:
- Read booking settings and active/inactive booking types.
- Create/update/deactivate a booking type.
- Update business working hours, timezone and simultaneous capacity.
- Read bounded availability when needed to explain configuration.
- Bind a canonical website booking form/block to existing type IDs.

Use typed inputs and results, stable IDs, revision/concurrency checks for configuration edits, and human-readable errors. Tool names can follow existing conventions. Do not give Ada raw SQL, schema editing, host credentials or unrestricted mailbox/admin endpoints.

An explicit owner instruction can authorize the corresponding supported configuration edit. When details are missing or materially ambiguous, Ada asks a concise question. Do not insert an extra approval ceremony after every simple owner-requested change. For configuration proposed by Ada, obtain the owner's agreement before applying it.

When asked to create a booking form:
1. Read the current authoritative configuration.
2. Identify an appropriate existing type.
3. Ask whether to reuse it or create a new type when the choice is ambiguous or the requested service differs.
4. Gather missing duration, hours or capacity; retain existing valid business settings.
5. Configure through tools and bind the website form to the returned type identity.
6. Generate the website change through the normal Ada design/review flow.

If required configuration is absent, surface it directly. Do not invent working hours, service duration, capacity or demonstration appointments. Ada can describe what is configured and adjust it through the same tools the UI uses.

## 9. Enforce the contract during intake and later edits

Apply the same booking capability to new sites spawned through HelloAda and to all later website changes. HelloAda remains the project selector; site-agent's shared intake/design pipeline owns generation.

Make the booking capability discoverable in the structured design/tool contract supplied to OpenCode agents. Prompts carry requirements and typed capabilities, not canned customer conversations.

Generated appointment interfaces must:
- Use the canonical schema-supported booking block/form or shared booking client.
- Reference real booking type IDs belonging to the tenant.
- Submit through the canonical public appointment API.
- Read availability from that service.
- Use the existing shared content bindings for editable copy/media.

Before a candidate reaches owner review, validate its structured booking references and integration. Reject missing/inactive/cross-tenant type references, duplicate local booking stores, hardcoded fake slots and unsupported endpoints. Use meaningful contract and integration checks; avoid fragile string-only checks that mistake decorative content for a functioning form.

Ada's creative freedom includes layout, typography, motion and presentation. Scheduling, persistence, authentication and notification semantics remain shared product code. Ada cannot change platform schemas, migrations, package pins, infrastructure or capacity enforcement.

Settings changes and website design review retain their existing distinct workflows. A new booking type can be configured while the website form remains a draft. Publishing must validate the final binding again so a stale draft cannot publish a broken booking interface.

## 10. Implementation sequence

1. Audit current main and document the authoritative paths and gaps.
2. Define the minimal booking settings/type/instance contract and needed explicit migrations.
3. Implement and prove atomic capacity admission, idempotency and timezone handling in the shared service.
4. Make website form processing use that service and preserve the Calendar/Contact/Inbox links and notification state.
5. Add Settings controls and move type management there; remove sample-template confusion.
6. Correct embedded Calendar navigation and preserve the existing workspace/sidebar.
7. Register Ada's typed booking tools and integrate them into both intake and later design work.
8. Add generation/review validation against the same booking contract.
9. Reconcile current tenant configuration/data explicitly without rebuilding customer designs.
10. Merge reviewed changes and release through the central VPS pipeline; validate the actual deployed flow.

Each stage must use the preceding authoritative service. Do not temporarily ship competing stores or an independent booking widget to demonstrate progress.

## 11. Required verification

Service tests must cover:
- Capacity one: two simultaneous requests for one interval admit exactly one.
- Capacity two: two admit, a third fails, including different type durations.
- Partial overlaps, long appointments spanning multiple shorter appointments, adjacent intervals and cross-day boundaries.
- Cancellation, rescheduling failure preservation and repeated idempotent submission.
- Concurrent calendar writes, inactive types, configuration revision conflicts and capacity reduction.
- Timezone conversion, daylight-saving transitions and bounded availability.
- Tenant isolation and public response privacy.
- Notification failure preserving one appointment and retrying only the notification operation.

UI/integration checks must cover:
- Calendar remains embedded, with Payload and mailbox navigation accessible.
- Booking types are edited in Settings using the same authoritative configuration Ada reads.
- Ada reuses an existing type and can create a new one with owner-provided details.
- A canonical website form displays only admitted availability.
- A visitor booking creates exactly one Calendar event, linked Contact and Inbox notification.
- Refresh/reconnect preserves the appointment and Inbox record.
- Two-browser submission races exercise actual D1 admission, rather than an in-memory mock.
- Intake-generated and later-edited website candidates both use the shared appointment integration.
- At representative desktop/mobile widths, labels, navigation and event details are readable.

Use controlled test appointments and recipients. Record their tenant, type and event identities. Clean up disposable fixtures through the normal product cancellation/deactivation path; do not silently purge records.

## 12. Release and acceptance

Use official weareheadless/site-agent/main as the source. Keep upstream Mailflare pristine; integration changes live in shared adapters/patches. Publish shared admin/core package versions where required by the existing release contract.

Ship API changes through deploy/desired-api-release.json and Worker changes through the canonical shared runtime fan-out/desired-release queue. Necessary existing-tenant migrations require explicit registered release requests with the exact prior ledger and committed target. New tenants inherit the same migration chain, Settings and tools automatically.

Do not deploy from a laptop checkout, edit old release directories, manually repair tenant repositories or run customer-specific Wrangler deployments. Monitor exact receipts and the VPS release journal. Failed IDs are terminal; resolve the cause and request a new ID.

Validate Oceanic as the first authenticated canary, then confirm current tenant rollout receipts for Atelier and Northstar. Browser evidence must distinguish checked UI from receipt-only deployment. Existing site designs and content bindings must continue working.

Completion requires:
- The embedded Calendar preserves workspace navigation.
- Settings contains the minimal booking configuration.
- Ada reads/configures it through tools in intake and later edits.
- Website booking forms use the single shared appointment service.
- Capacity and idempotency hold under real concurrent submissions.
- Calendar, Contact, Inbox and notification behavior are linked and durable.
- The reviewed code is on GitHub and deployed through the official pipeline.
- Fresh authenticated browser and controlled visitor-flow evidence is recorded.

A passing build or a visible Calendar alone does not prove the appointment workflow. Report any unverified boundary explicitly.
