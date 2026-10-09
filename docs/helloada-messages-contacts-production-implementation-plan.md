# HelloAda Messages, Contacts and Website Forms — Production Implementation Plan

Date: 2026-10-04; integration status reconciled 2026-10-07

Status: implementation is in progress on an isolated feature branch; the
current-mainline integration and package CI are being completed. Tenant email
provisioning and live evidence remain incomplete. Nothing has been deployed.

Audience: the coding AI implementing the shared `weareheadless/site-agent` platform.

## 1. Decision and purpose

Build a durable production feature that reuses selected Mailflare email code inside the existing customer website/Payload Worker. Do not deploy Mailflare as a second application or a separate email Worker.

Implement and deploy the canonical product feature, not a temporary experiment. Use the current tenants for live validation; do not create another tenant, a throwaway application, a disposable database or a parallel mail system to make the checks pass.

The production feature must support this owner journey:

1. A visitor submits the website's contact form.
2. The enquiry appears in the owner's HelloAda **Messages** tab and creates or links a **Contact**.
3. Ada can propose a reply using that conversation and the business's approved context.
4. The owner reviews the exact reply, edits it if needed, and explicitly sends it from the business's custom-domain address.
5. The visitor replies using their usual email application.
6. That reply appears in the same conversation inside HelloAda.
7. An email sent directly to the business address also appears in Messages.

Success means this loop works with real email, real Cloudflare resources, the canonical shared schema, and the existing deployment pipeline. Mock screenshots and a successful build are not sufficient.

The scope is deliberately small, but the implementation must be production-quality: canonical schema, persistent records, access controls, durable processing, observability, documented operations and verified releases. Calling the work production does not establish that it is ready; completion requires the live evidence specified below.

### Required rollout targets

| Existing tenant | Required role in the rollout |
| --- | --- |
| OceanicVibes — `https://oceanicvibes.com`, admin `/admin` | First production rollout; full form → inbox → Ada draft → owner-approved domain reply → external reply roundtrip, plus direct incoming email |
| Atelier Harmonie — resolve its current registered Worker/admin identity | Second validation rollout; same schema/packages, forms, Contacts, Messages, Ada drafting and tenant isolation; use a unique address on the explicitly registered HelloAda email domain while its website remains on `workers.dev` |
| Northstar — resolve its current registered Worker/admin identity | Third validation rollout; same shared schema/packages and behavior as Atelier, with a distinct address on the same explicitly registered HelloAda email domain |

OceanicVibes's custom domain is supplied by the owner as the intended email-validation target. The owner has confirmed the domain is managed in their Cloudflare account, that the visible Mailgun setup is retired Squarespace-era configuration, and authorized temporarily disabling any personal-email forwarding rule that conflicts with the test. The signed-in Cloudflare inspection on 2026-10-04 found the OceanicVibes zone and website Worker, two apex Mailgun MX records, a Mailgun-only apex SPF record, and legacy Mailgun DMARC/DKIM values; Email Routing and Email Sending are not yet onboarded for OceanicVibes. The Email Routing account view did not show an OceanicVibes routing rule. Capture the exact live state through the provisioning script before mutation; if the script discovers a forwarding rule or DNS/provider state different from this documented legacy set, stop and preserve it rather than guessing.

Do not replace either existing tenant or rebuild its site from scratch. Preserve existing content, editable field mappings, owner access and tenant identifiers. Do not infer an external Atelier domain from its business name.

For Atelier and Northstar, phase-one provisioning uses unique addresses on the
HelloAda-owned `helloada.app` zone apex. The exact local part must be recorded
against each permanent tenant ID; do not guess it from a display name. This is
an explicit platform-owned email identity, not a fallback inferred from the
website hostname. Keep each address/local part in the registered tenant email
configuration. Do not use `inbox.helloada.app` yet: Cloudflare documents
Email Routing subdomain enablement as a dashboard flow, while the older
subdomain query on its routing-DNS API is deprecated. The shared provisioning
path currently supports the zone apex only and must reject a subdomain rather
than accidentally applying apex routing semantics. If `helloada.app` has
unexpected MX, SPF, DMARC or routing state at preflight, stop without mutation;
do not displace any existing HelloAda mail service.
For apex activation, call Cloudflare's Email Routing DNS endpoint with no body;
passing the apex as `name` is interpreted as a subdomain request and returns
HTTP 422. Subdomain onboarding remains out of scope until Cloudflare exposes a
supported API flow for it.

OceanicVibes live mail validation is mandatory. Its owner-approved first-run exception is a narrowly scoped, auditable cutover of the exact legacy Mailgun records listed above. Only the platform provisioning script may perform it. Any unrelated or unrecognized record/rule, missing Cloudflare entitlement, or missing API permission is a hard stop. Do not substitute a new tenant or different domain and declare OceanicVibes validated.

No additional site/domain is to be provisioned for acceptance in this rollout. Future-site defaults remain a required shared-platform implementation and are verified through scaffold/provisioning tests; creating a new live site is a separate future validation task.

### Non-negotiable architecture

- One customer application Worker, handling website, Payload admin, incoming email and email jobs.
- One canonical deployment pipeline and release receipt per customer application release.
- One shared implementation in `site-agent`, consumed by version-pinned customer packages.
- Each customer retains its own D1 database and private email storage. No shared cross-customer inbox database.
- Payload remains the authority for forms, contacts, conversations and messages. Do not import an independent Mailflare CMS, contact store, user directory or migration lifecycle.
- One owner login and the existing HelloAda interface. No Mailflare dashboard, embedded second application or second session.
- Ada may populate supported form configurations and draft messages. Ada may not change platform schema, authentication, provisioning, secrets or release configuration.
- No alternate email provider, compatibility CMS, hidden endpoint selection or fake successful state when a dependency fails.
- All runtime paths are durable product paths. No experimental mode, demo inbox, temporary collection, test-only send endpoint, disposable tenant or customer-specific implementation.
- Normal local fixtures, isolated automated test databases and immutable build/release directories are allowed for engineering verification; they are not deployed substitutes for the two existing tenants.

## 2. What was verified, and what must still be inspected

The original plan snapshot was written on 2026-10-04. Its initial schema and scaffold observations are historical, not the current source of truth. The integration was re-audited against official `main` at `a5938124f27af569d2cf0b8011791a6a425a0698` on 2026-10-07.

Current verified boundaries:

- `packages/helloada-payload-core` owns the shared schema and editable-content contract.
- `packages/helloada-payload-admin` owns the shared HelloAda owner workspace.
- `src/site_agent/templates/next-payload` is the canonical customer scaffold.
- `@weareheadless/helloada-payload-core` 0.5.4 already owns the canonical Messages, Contacts, forms and owner-notification schema at schema revision 5. The registered mainline migration chain is the initial migration, Growth operations migration and `20261006_061835_helloada_owner_handoff`; the last migration contains the current forms/messages/notification tables and columns.
- The canonical template already uses that shared schema. The old feature-branch migrations `20261004_232326_helloada_messages_contacts` and `20261005_173359_helloada_owner_notifications` duplicate schema history and must not be carried into the integrated tree or registered beside the mainline chain. This feature integration does not add a new schema migration unless a reviewed schema diff proves one is required.
- The canonical scaffold already has a custom Worker entry point in the integration tree. Keep its HTTP delegate and email/queue handlers in the exact artifact verified by the VPS release pipeline; do not create another Worker or a direct-deploy path.
- Immutable package releases require explicit consumer pin/lockfile updates; publishing a package does not redeploy customers.
- `deploy/desired-releases.json` and the VPS release service own customer promotion. Schema upgrades require an explicit migration request with verified ledger identities.

The earlier statements in this plan that Messages/forms were absent from the
schema and that a custom Worker wrapper still needed to be designed are
superseded by this current-mainline audit. Feature work should add only the
shared runtime, owner UI, integration tests and provisioning capability not
already present on `main`; it must not recreate completed schema or scaffold
work.

Before implementing, read the complete, current versions of:

- Applicable workspace and repository `AGENTS.md` files.
- `deploy/README.md` and `docs/platform-release-runbook.md`.
- `docs/helloada-connection-contract.md`.
- `packages/helloada-payload-core/README.md`, schema, contract, access patterns and tests.
- `packages/helloada-payload-admin` runtime/session handling and owner navigation.
- The canonical scaffold, provisioning services, tenant registry and release manifest validators.

Some contributor-guide sections retain older contextual statements. Reconcile them against the explicit current release contract; do not use an obsolete statement to introduce a second architecture or manual API restart.

Record the exact official `site-agent` commit and exact Mailflare commit used. Re-check paths and package versions instead of treating this document's authoring date as a permanent implementation baseline.

References: [site-agent contributor guide](https://github.com/weareheadless/site-agent/blob/main/AGENTS.md), [Payload core](https://github.com/weareheadless/site-agent/blob/main/packages/helloada-payload-core/README.md), [VPS deployment contract](https://github.com/weareheadless/site-agent/blob/main/deploy/README.md).

## 3. Licensing is part of the production release

Mailflare is AGPL-3.0. Preserve its licence, attribution and modification notices for reused/adapted material. Modified network software carries source-offer obligations; combining it with proprietary packages requires review of the covered work's scope. A directory or package boundary alone does not establish legal separation. Do not describe the integrated feature as entirely proprietary. [Mailflare licence](https://github.com/hieunc229/mailflare/blob/main/LICENSE).

Before a network-accessible rollout, document an approved compliance route: appropriate source availability for the covered deployment, or permission from the relevant rights holders. If required source cannot be offered, pause that deployment and ask for a decision. Production framing does not postpone licence obligations.

Later replacement must be genuinely independent, not an AI paraphrase or refactoring of copied code. Replacing code does not retroactively erase obligations for earlier deployed versions. Functional requirements may inform a new implementation; copied expression needs appropriate rights. [Copyright Office guidance](https://www.copyright.gov/circs/circ61.pdf).

Required implementation artefacts:

- A third-party provenance manifest: upstream commit, original paths, copied/adapted files, licences, dependency licences, modifications and dates.
- Preserved original notices and a complete upstream licence copy.
- The reviewed source-distribution boundary and exact deployed-source retrieval procedure, including necessary build material but excluding secrets and customer data.
- A visible source/licence link wherever the approved compliance route requires it.
- An explicit record of unresolved licensing questions. Never claim that opening only the email package necessarily resolves integration obligations.

This plan specifies production implementation on the current tenants. It does not authorize a coding AI to publish private platform source or change repository visibility without a separate owner decision.

## 4. Tight scope

### Include

- One business mailbox/address per tenant.
- One supported custom domain under the configured Cloudflare account's DNS control.
- Incoming email, owner-approved replies and sent history in the same conversation.
- Website forms delivered directly into the same inbox, without email delivery being a prerequisite for saving an enquiry.
- Basic contacts: name, email, optional phone/company, owner notes and linked conversation history.
- Unread/read, needs-reply/done, archive and spam states.
- Search and cursor pagination adequate for ordinary small-business inbox use.
- Plain-text reply composer and safe display of incoming email.
- Private incoming attachments with conservative enforced limits; no outgoing attachments or visitor file uploads in this release.
- Ada reply drafting, initiated by the owner, with explicit human send approval.
- Deterministic provisioning, durable processing, operator diagnostics and tenant isolation.

### Exclude

- Full Gmail replacement, IMAP/SMTP client hosting, JMAP, calendars, booking engines, campaigns and newsletters.
- Cold outreach, bulk sending, autonomous sending and general-purpose mail merge.
- Shared staff mailboxes, delegation, many aliases or multiple simultaneous business domains.
- Gmail/Workspace/Microsoft migration or replacement of an existing mail service.
- Mailflare's independent AI agent, MCP surface, updater, account system and dashboard.
- A heavyweight CRM with deals, sales pipelines, scoring and dashboards.
- Email/contact data in GitHub or website rollback snapshots.
- Provider switching and automated takeover of conflicting DNS.

Cloudflare currently limits Email Service to transactional use. This release targets customer-requested enquiries and service replies, not unrestricted personal/business mail or promotional conversations. Technical two-way conversation support does not remove that policy boundary. [Email Service FAQ](https://developers.cloudflare.com/email-service/reference/faq/), [email-agent example](https://developers.cloudflare.com/agents/examples/email-agent/).

## 5. Runtime and resource design

### One Worker, several event handlers

Add a small canonical Worker wrapper that delegates website/admin HTTP handling to the generated OpenNext Worker and handles incoming-email, queue and scheduled events through the shared messages module. Preserve any required generated named exports and existing handlers; do not modify generated files after building.

OpenNext documents a custom-worker extension path. Mailflare's inspected Worker also combines HTTP, email, queue and scheduled handling; this demonstrates a possible deployment shape, not drop-in compatibility with Payload. [OpenNext custom Worker](https://opennext.js.org/cloudflare/howtos/custom-worker), [Mailflare Worker](https://github.com/hieunc229/mailflare/blob/main/worker.ts).

The wrapper itself is part of the reviewed scaffold and inspected deployment artifact. Adapt the release pipeline's entry-point verification/upload step where required; do not bypass it with direct Wrangler deployment.

### Resource ownership

| Resource | Owner and purpose |
| --- | --- |
| Existing tenant Worker | Website, Payload, Messages HTTP API and event handlers |
| Existing tenant D1 | Canonical Payload records and durable processing/delivery state |
| Existing public media R2 | Website assets only; never raw email or email attachments |
| Tenant-private email R2 | Raw MIME and incoming attachments, with no public bucket exposure |
| Tenant message-processing Queue | Typed incoming-processing and approved-send jobs |
| Tenant dead-letter Queue | Failed jobs retained for operator diagnosis, not silently discarded |
| Existing VPS control plane | Provisioning/release orchestration and Ada drafting, not an SMTP server |

The email R2 bucket and Queues are additional resources, not additional application Workers. This still adds operational work; “one deployment” does not mean zero setup or shared failure isolation.

Use one processing Queue initially. Both its producer and consumer target the existing tenant Worker. Keep message bodies small: operation IDs and storage references, not full MIME, attachments, credentials or chat transcripts.

Use explicit per-tenant resource identities in the canonical registry. Resource names are derived from immutable tenant identity, not a mutable domain or business display name. The same platform code must run for all tenants.

Budget the actual combined application: bundle size, memory/CPU, parsing, D1 reads/writes, R2 storage, Queue operations and account-wide sending quotas. Low-volume email can still affect the website/admin Worker during an abusive burst. Enforce bounded job concurrency and account/tenant send limits; do not promise isolated reputation or unlimited email merely because storage is tenant-specific.

Add a short scheduled sweep in the same Worker for committed work that has not been enqueued and stale processing leases. This is one documented durable processing path, not a second email implementation. It must have bounded work and must not resend ambiguous outbound deliveries.

## 6. Reuse strategy and production integration checks

Do not copy the entire Mailflare application and then hide most of it.

At the selected upstream commit, inspect the dependency graph of:

- MIME parsing and header/address normalization.
- MIME composition and Cloudflare sending integration.
- Message-ID/References handling and conversation lookup.
- Private raw-message and attachment storage helpers.

Candidate starting points include the upstream email parsing, threading, inbound and send modules. These are inspection targets, not an instruction to transplant their complete service graphs. The inspected inbound/send services depend on upstream database, contact, notification and provider modules; adaptations must be traced and recorded. [Inbound service](https://github.com/hieunc229/mailflare/blob/main/src/lib/email/inbound.ts), [send service](https://github.com/hieunc229/mailflare/blob/main/src/lib/email/send.ts).

Create a narrowly scoped, permanently named shared module, such as `helloada-messages`; choose the final package/export arrangement to fit the existing repository. Keep the Mailflare transport adapter and its reused/adapted code explicitly attributed inside that module. Public product contracts use durable feature names, not experiment names. This is an engineering boundary, not a guaranteed licensing boundary.

Expose only a few typed operations: parse inbound MIME, build an approved outgoing message and deliver it through the supported Cloudflare service. Keep business authorization, canonical persistence and provisioning outside those low-level operations.

Do not import Mailflare's Drizzle schema/migration chain or rewrite the product around its build system. Do not introduce a universal plugin framework or multiple interchangeable live implementations. There is one active canonical implementation.

### Integration gates

Start with focused local/contract tests before larger UI work. Complete the live gates on OceanicVibes through the canonical production rollout, using persistent product resources and the real owner workflow:

1. The custom OpenNext wrapper builds and serves website/admin normally.
2. The same uploaded Worker receives an email event and consumes a Queue event.
3. The selected MIME helper parses realistic multipart mail within enforced memory/CPU limits.
4. The canonical D1/Payload path persists records with tested atomicity and deduplication.
5. The selected Cloudflare sending path can send a reply to an ordinary unverified external recipient under the account's actual entitlements.
6. A subsequent external reply can be matched using stored email identifiers.

Do not confuse the older restricted `send_email` forwarding capability with a general authenticated domain-sending service. Verify which Cloudflare API/binding the pinned upstream implementation actually uses and document the required paid-plan/domain activation steps.

If this checkpoint requires a parallel ORM, a second Worker, transplanting most of Mailflare, or bypassing the release pipeline, stop and report the concrete incompatibility. Do not silently expand the architecture or claim reuse is the cheaper path without evidence.

## 7. Canonical Payload model

Use the platform-owned schema and contract tests already on current `main`.
Reuse those canonical collections; do not create a duplicate collection or
schema migration merely because this document proposes a name. Any new schema
change must be proved necessary against the exact current shared contract and
must follow the explicit tenant migration queue.

### Forms

- Stable ID/slug, localized labels/help/success text and enabled/published state.
- Bounded fields with stable keys: short text, email, phone, textarea, select and a required acknowledgement where appropriate.
- Required/optional flags, maximum lengths and a constrained choice list.
- An explicit semantic mapping for contact name/email/phone/company and enquiry message.
- Fixed delivery destination: the tenant's Messages inbox. No arbitrary external URL, JavaScript, SMTP settings or client-provided recipient.
- An immutable form-definition revision/snapshot identifier for accepted submissions.

The shared schema already has the form-reference block/fields. Ada uses that
canonical block and the shared submit component. Frontend layout/styling remain
free, but submission and schema behavior are shared.

Forms are reviewed website configuration. Changes to the public form use the existing draft/publish journey and editable bindings, not an extra publish dashboard.

### Contacts

- Stable ID; email lookup key; name; optional phone/company; owner notes.
- Source and created/updated timestamps.
- Linked conversations; no independently editable upstream address book.
- Auto-upsert only conservative, observed contact details. An inbound display name must not overwrite an owner-maintained name or notes.

Normalize addresses conservatively. Do not globally strip dots or plus tags, or assume every provider treats local parts identically. A form-supplied email address is unverified contact information, not proof of identity or authority.

### Conversations

- Stable ID; primary contact; mailbox identity; subject/title.
- State: needs reply, done, archived or spam; unread indicator and last activity.
- Source context: direct email or originating form/page.
- Email identifier relationships for threading, including provider-assigned outbound IDs.

Separate a conversation's owner-workflow state from technical job/delivery state.

### Messages and reply drafts

- Stable ID and conversation relationship.
- Direction/source: form enquiry, received email or outgoing reply.
- Envelope sender/recipient, normalized display headers, subject and text body.
- Sanitized HTML only when safe rendering is implemented; retain raw MIME privately for diagnosis.
- Received/sent timestamps, external Message-ID, In-Reply-To and References.
- For form enquiries: form ID/revision, validated submission snapshot, source page and receipt ID.
- Private attachment metadata: storage key, filename, declared/detected type, byte size and integrity hash where useful.
- Outgoing draft revision, author/AI provenance, approval identity/time, approval hash and delivery status.

An accepted form enquiry is a canonical message. Do not maintain a second editable submissions database and synchronize copies into the inbox.

### Processing/delivery records

- Operation ID/type, message/raw-storage reference, idempotency key and immutable payload revision.
- State, bounded attempt count, next attempt time, processing lease and sanitized error category.
- Queue dispatch status, provider request/response identifier and approval reference where applicable.
- Received-message deduplication identifiers scoped to this mailbox/tenant; never trust a Message-ID alone as proof of sender identity.

These records support processing and operator diagnosis, not a second user task list.

### Mail configuration

One protected tenant configuration record/global identifies its domain, single mailbox address, Worker/resource identities and activation checks. Actual credential values remain runtime/protected-host secrets, not Payload fields exposed to the owner or Ada.

Distinguish provisioning readiness from inbox contents. Example machine states: domain required, provisioning, action required, active and failed. UI labels must explain the actual cause, not display fake connection success.

### Access and migration requirements

- All private collections, raw MIME, attachments and configuration require explicit authenticated access policies. Hidden navigation is not access control.
- Test both Payload REST/GraphQL access and the local API. Local API bypass behavior must be explicitly controlled; privileged event ingestion uses a narrow trusted service path, never a browser-supplied identity.
- Keep raw mail and personal information out of public content readers, page bindings and public health responses.
- Preserve the current shared schema/contract identity when feature code adds no schema change; publish exact package artifacts through the canonical workflow.
- Keep the mainline migration index and generated contract in exact agreement. Preserve applied migrations and upgrade only through explicit release-queue migration requests. Never restore the duplicate feature-branch migrations listed in §2.
- The selected migration must be additive and compatible with the prior serving Worker. A Worker rollback does not revert inbox data or the D1 ledger.
- Prove the pinned Payload/D1 adapter's transaction capabilities. If multi-record atomicity is not available, establish one committed canonical receipt as the acceptance boundary and a tested idempotent materialization path. Do not claim a transaction that the adapter cannot execute, or introduce a parallel database to simulate it.

## 8. Website form pipeline

1. Render only a published canonical form through the shared form component. The frontend owns appearance, not transport or security policy.
2. Submit to a narrow tenant-local public endpoint with a form ID, bounded field values, anti-spam token and stable submission idempotency token.
3. Resolve tenant and destination from server/runtime identity. Reject disabled/unpublished forms, unknown fields, invalid types, oversized requests and invalid anti-spam tokens.
4. Verify Cloudflare Turnstile server-side and enforce rate/size limits. Origin checks and a honeypot may supplement, but do not replace, the primary abuse controls.
5. Validate against the exact published form revision; record that revision and submission snapshot.
6. Commit the canonical acceptance record before returning success. A repeat of the same accepted submission returns the same receipt, not a duplicate lead.
7. Materialize the contact, conversation and message atomically if supported, otherwise through the proven durable receipt path. Preserve accepted field values even if processing fails.
8. Schedule optional internal processing through the durable outbox. Queue unavailability must not discard an already accepted enquiry.
9. Display it in Messages with contact details and source context. Do not send a self-addressed email simply to insert it into the inbox.

Public responses expose only the submission's receipt and safe status; they must not reveal contacts or conversations. Idempotency tokens must not function as public inbox-read credentials.

There is no automatic visitor acknowledgement or automatic reply. An owner may configure an external notification address in Messages; the address must be verified before use. Form and domain-email enquiries accepted after verification create an idempotent owner-notification operation in the same tenant outbox. The notification is a bounded plain-text preview with a link to the authenticated HelloAda conversation; it does not include attachments. The full message remains in the tenant inbox, and the owner replies there through the existing reviewed-send flow. Alert delivery failure or ambiguity never removes or duplicates the accepted enquiry.

Notification preference and verification state are fields on the shared `messageMailbox` global, not a second settings store. The challenge is short-lived, HMAC-protected with the tenant service token, limited to five attempts, and rate-limited by the tenant's Cloudflare binding. A replacement address does not receive alerts until verified; the previously verified address remains active until then. Turning alerts off clears the active and pending settings. Challenge hashes and codes are never returned to the UI or written to operational logs.

Forms in the ordinary design-preview surface must be visibly marked as preview and must not create real leads or send real email. Live acceptance checks submit clearly identifiable validation enquiries through OceanicVibes's published form and its canonical inbox; they do not use a separate live tenant, shadow schema or alternate ingestion path. Local tests use fixtures with the same canonical contracts.

## 9. Incoming email pipeline

1. Cloudflare Email Routing directs the configured business address to that customer's existing Worker.
2. Resolve the receiving mailbox from the trusted envelope recipient and runtime configuration. Unknown recipients are rejected; no automatic catch-all mailbox.
3. Enforce raw message limits before expensive parsing. Store raw MIME in the private email R2 bucket and commit a durable processing receipt/reference.
4. Only accept delivery after required persistence succeeds. If the required durable receipt cannot be saved, reject the incoming delivery rather than acknowledge and lose it.
5. Queue the receipt ID. A persisted but not-enqueued receipt is picked up by the same documented sweep; temporary Queue failure after successful durable acceptance must not discard it.
6. Parse MIME in the consumer under bounded limits, normalize headers and extract text/allowed attachments.
7. Apply message-level deduplication and materialize the contact/message/conversation through canonical services.
8. Match replies using stored provider Message-IDs, In-Reply-To and References within this mailbox. Never merge unrelated enquiries solely because sender or subject is similar.
9. Require appropriate participant matching before accepting a claimed thread relationship. Forged References must not attach an outsider's message to a private conversation or influence Ada's context.
10. Update unread/needs-reply state, then acknowledge the Queue message only after the processing result is committed.

Messages without trustworthy identifiers still need a supported deterministic receipt identity. Repeated processing of the same receipt must be idempotent; a genuine later message with the same text is not automatically a duplicate.

Retain unparseable accepted messages and mark a technical processing failure. Do not replace their contents with invented text or an empty successful message. Technical failure details belong to operator logs, while the owner sees a concise affected-message notice if appropriate.

Validate spam/authentication evidence from trusted delivery metadata, not attacker-supplied headers. Quarantine unsafe/suspicious content without discarding normal mail silently. No automatic replies that could create mail loops.

Incoming attachments are private downloads, not website media. Enforce allowlisted types and conservative size/count limits; no inline executable HTML/SVG display. Use authenticated download handlers and safe disposition headers. This release does not claim malware scanning or safe handling of every file type.

Document a production retention and deletion policy for messages, raw MIME and attachments, with an explicit owner-approved default rather than an experiment expiry date. Records persist across upgrades; do not automatically purge them after validation. Verify deletion across canonical records and private objects, including orphan objects from interrupted acceptance. Validation enquiries may be removed only as explicitly identified records through the ordinary authorized deletion path. Do not retain full message bodies in operational logs. Backups containing inbox records must receive the same private access controls; no public-media backup destination. Document and test restoration of the tenant's message records and their private objects without reverting or deleting unrelated website content.

Cloudflare currently documents a 25 MiB incoming raw limit and a smaller general-recipient outgoing limit. Set explicit product limits below provider/runtime limits and measure MIME encoding and memory overhead. Do not rely on an upstream UI's attachment setting as a runtime guarantee. [Cloudflare email limits](https://developers.cloudflare.com/email-service/platform/limits/).

## 10. Owner-approved reply pipeline

1. The owner opens a conversation and writes a reply or asks Ada to draft one.
2. Ada receives only authorized conversation content, relevant business facts and the owner's request. Email is untrusted source material, not an instruction channel.
3. Save the proposed reply as a draft in the canonical Messages model. Ada cannot send or approve it.
4. Show the exact sender, recipient, subject and text that will be transmitted. Do not hide a changed recipient or silently insert material after review.
5. The owner explicitly clicks Send. Validate session, permission, mailbox activation and the draft's expected revision.
6. Atomically record approval of that exact revision and create one delivery operation/idempotency identity. Double clicks or repeated requests must not create additional sends.
7. Deliver only the approved payload. Any edit to body, recipient or sender invalidates the prior approval and requires a new owner action.
8. Persist the provider's response/actual Message-ID and associate it with the internal conversation. This is particularly important for the first reply to a form enquiry, whose synthetic internal ID is not an email received by the visitor.
9. File the sent copy in the conversation. Subsequent visitor replies match the real outbound identifier and therefore join the original form enquiry.

Use the verified business sender, never the visitor's address as From. Outgoing replies go to the validated conversation participant; distrust arbitrary inbound Reply-To values and require visible confirmation for an external address change. No arbitrary multi-recipient compose surface in this release.

### Delivery state and honest failure handling

- Draft: not approved, no delivery allowed.
- Queued: approved exact payload, awaiting execution.
- Sending: an operation holds the delivery lease.
- Accepted by email service: provider acceptance recorded; this is not proof of recipient inbox delivery.
- Failed: definitive failure, shown with a useful action and operator reference.
- Delivery uncertain: request may have reached the provider, but confirmation was lost.

Queues can redeliver. Implement database uniqueness and conditional state transitions for concurrent consumers. Where the chosen provider supports documented idempotency, use a stable key and test it. Do not claim exactly-once external delivery without that guarantee.

If a crash/timeout creates an ambiguous result and the provider cannot reconcile it safely, do not automatically resend. Record uncertainty and require operator resolution; the owner sees that delivery could not be confirmed. Repeating an HTTP request must return the existing operation, not initiate another message.

Retry transient, definitive non-acceptance with bounded backoff. Never retry permanently invalid configuration forever, silently switch provider, or alter the approved content to make a send succeed.

Use a dead-letter Queue and durable failed-operation records. Retries and explicit recovery are normal processing semantics, not permission for an alternate architecture. [Cloudflare Queue retry behavior](https://developers.cloudflare.com/queues/configuration/batching-retries/).

## 11. Domain and mailbox provisioning

Extend the existing provisioning service and canonical tenant registry, not a Mailflare-specific wizard that duplicates onboarding.

### Supported route

- The tenant's website and forms can exist on a Workers domain without custom email.
- Custom-domain email activates only for a supported domain controlled by the configured Cloudflare account. It is prepared by the same idempotent, receipt-producing platform provisioning service used for GA4/GSC; it is not a dashboard checklist or a manually applied DNS recipe.
- Provision one explicitly chosen business address, such as the owner's selected contact address. Do not guess an existing company's address or take over an occupied mailbox.
- Inspect actual Email Service availability, account entitlements and API permissions. Record external/manual activation steps honestly when Cloudflare requires them; “automatic” cannot mean fabricated readiness.

### Idempotent sequence

1. Validate registered tenant, exact Worker/D1 identities, domain ownership and the approved address.
2. Inspect existing MX, SPF, DKIM, DMARC and routing configuration without changing it. In the explicit CLI apply path, persist the exact before-state (including any exact-address forwarding destination) only in a tenant-private mode-0600 receipt; summaries and logs are sanitized.
3. For ordinary tenants, if MX/provider conflicts exist, stop email activation and preserve all records; do not expose a generic force-replace control. OceanicVibes may use the owner-authorized CLI cutover flags, which accept only the exact apex Mailgun MX/SPF values approved for this test. The script must re-read the provider state immediately before destructive DNS writes and stop if it differs. It must not touch website A/AAAA/CNAME/Worker records, Google Search Console verification TXT, or unrecognized mail records. It must preserve and reconcile existing DMARC policy deliberately, not replace reporting policy as an incidental side effect. A personal-forwarding rule may be disabled only for the exact mailbox matcher after its exact rule identity and destination are captured in the protected mode-0600 before-state receipt; never disable a catch-all or unrelated mailbox rule implicitly. The receipt must include enough state to restore it and must never print the destination to logs/terminal output.
4. Create/reuse the tenant-private email bucket and Queues from registry identities, record ownership and bind the correct resources.
5. Apply the canonical committed schema upgrade/bootstrap through the release contract.
6. Release the inspected Worker with its email/queue handlers through the VPS queue.
7. Configure receiving and sending for the selected domain/address through the platform's idempotent Cloudflare Email provisioning service and protected control-plane credentials. Its read-only plan and apply operations share the same script/API contract as GA4/GSC provisioning; it records the exact Cloudflare resources, DNS mutations, forwarding-rule state, and resulting verification checks. No operator has to click through Cloudflare or manually copy DNS values.
8. Verify routing targets the exact registered Worker and sender authentication is valid. Do not create duplicate SPF records or overwrite an existing policy without review. On OceanicVibes, once the canonical inbox passes the agreed real-message check, retain the new platform route; any old forwarding behavior may be restored only if it is non-conflicting and the owner requests it. Do not leave a shadow/duplicate destination route.
9. Run inbound and outbound controlled real-email checks; record the mailbox's verified activation status.
10. Mark the mailbox active only after required gates pass. Re-running the operation must reconcile the same resource identities, not create new mailboxes or buckets.

Keep provisioning credentials on the control plane. The customer runtime gets only the minimum credentials/bindings needed for receiving, storing and sending. Never expose account-wide DNS-management credentials to browser code or Ada.

The inspected upstream has fixed deployment-name assumptions and an account API default that can grant an address across domains. Adapt all copied references to the registered tenant Worker; do not invoke upstream account provisioning unchanged or inherit an all-domains default. [Mailflare API documentation](https://github.com/hieunc229/mailflare/blob/main/docs/api.md).

Upstream's updater replaces tracked application source. Do not import it or let it rewrite `site-agent` or customer repositories. Upstream changes are pinned, reviewed dependencies in the existing pipeline. [Mailflare deployment documentation](https://github.com/hieunc229/mailflare/blob/main/docs/deployment.md).

### Domain changes

Mailbox identity is not the current public website URL. Adding a website domain must not silently replace an existing mail identity.

The shared domain-origin operation enables the default mailbox local part (initially `hello`) for a supported custom domain and reruns the idempotent provider reconciliation after the exact tenant Worker is ready. The full address is derived from the current registered domain rather than copied from an old origin. Preserve historical addresses and message identifiers; never transfer stored mail. Do not silently delete an old domain's route or change the local part. An unsupported zone, existing provider conflict or non-ready Worker produces an explicit provisioning state without a substitute route.

Existing-domain email migrations, domain renames and multiple active domains are outside this release. Explain that boundary clearly rather than adding special-case compatibility paths.

## 12. Owner UX

### Navigation and layout

Add **Messages** to the existing owner navigation, using the current HelloAda logo, typography, orange accents and contrast conventions. Reuse shared components; do not design a new brand or resurrect the old admin.

Inside Messages, provide two simple views: **Inbox** and **Contacts**. Keep the usual Ada workspace accessible, but do not add another persistent chat column that crowds the conversation.

Desktop: one compact toolbar, readable conversation list and spacious selected-conversation area. Contact details appear in a collapsible side panel. Mobile: list, conversation and contact details are separate navigable views.

No marketing H1, duplicate browser bars, large empty-state hero or service-status dashboard above the functional workspace.

### Inbox

- Default to messages needing a response, with clear unread count and last-message preview.
- Show website enquiries and direct emails together, with a small source label.
- Offer All, Archived and Spam filters without extra task boards.
- Use a chronological conversation, visibly separating received enquiries, sent replies and an unsent draft.
- Primary actions: Reply, Ask Ada to draft, Send after review, and Mark done.
- While sending, keep the pending reply visible and prevent duplicate send actions.
- Failures preserve the draft, show a plain-language explanation and expose an optional reference/details link—not raw provider exceptions.
- If email is not activated, enquiries remain readable, with a small actionable domain/email notice. Do not hide the entire inbox.

### Contacts

- Searchable simple list, compact edit panel, notes and linked conversations.
- No scorecards, invented lead scores or sales analytics.
- A contact can exist without a conversation; a conversation's contact details remain editable through the same record.

### Forms management

Make form labels/fields accessible from the existing content/settings flow and the relevant page editor. Ada can configure supported forms with owner approval. Do not require a nontechnical owner to understand Payload relations or email routing to change a label.

### Ada and approvals

Email draft review happens in the conversation next to the draft. Sending is not “Publish,” and email drafts must not pollute website publication queues, reports or Growth approvals. Configuration actions stay in Settings; technical failures stay in diagnostics. There is no new global Review button without a real destination.

Use the owner's current language and existing localization system. Supply translated UI/error labels for the supported admin locales, without hard-coded tenant-specific wording. Email content follows the owner's request; do not insert canned multilingual model examples.

### Updates and sessions

Use a single documented authenticated refresh mechanism, initially bounded polling only while the relevant view is active. Pause hidden tabs and stop polling on sign-out. Reuse the existing token-refresh behavior and preserve unsent drafts across an expired session. Do not add a realtime Durable Object/WebSocket system solely for this release.

No technical provisioning states should be mistaken for tasks the owner needs to approve. Show only an action the owner can actually take.

## 13. Ada and future-site defaults

The platform default must be implemented, not only enabled for OceanicVibes and Atelier. Do not hard-code these tenant names in application logic; they are rollout targets resolved through the existing registry.

- Add the Messages/forms capability to the canonical template and its machine-readable capabilities/schema identities.
- Register the new content form-reference block with editable binding discovery and validation.
- Extend the default site's Contact page with a canonical form configuration; do not add a handwritten mailto-only substitute when a form is requested.
- The builder's typed contracts require the shared form component/submit path for generated forms. Validation rejects an arbitrary external submission endpoint, embedded recipient, customer-local form schema or duplicate inbox implementation.
- Ada edits form data/layout within supported fields; it cannot alter transports, collection definitions, migrations, authentication or package pins.
- Add a narrow tenant-scoped Messages read/draft capability to Ada's existing application-service path. Do not give Ada a raw send API, provider secret, DNS token or unrestricted SQL.
- The send operation accepts only an owner-approved exact draft revision. General website approvals and a chat message such as “handle my leads” are not permanent sending consent.
- Test an actual Ada-produced form candidate on an existing tenant, without manually repairing its generated form to make the test pass. This is a reviewed content/design update, not permission to redesign the whole website or replace its repository.
- Cover default scaffolding, canonical schema identities, generated form references and provisioner resource mappings in automated tests. Do not provision a new live tenant as an acceptance requirement for this rollout.

Default forms and Contacts can be ready without an email domain. The provisioner adds domain email when its supported prerequisites are met. This is an explicit capability lifecycle, not a fallback transport.

## 14. Implementation sequence and completion evidence

Implement in this order. Do not spend days polishing the inbox before proving the deployment and email loop.

### Phase A — Current-tenant baseline, scope and licence record

- Resolve the official repository/branch and read applicable instructions.
- Record exact platform/upstream commits and relevant resources without secrets.
- Complete the source/licence/provenance decision for the production exposure.
- Map the existing schema, owner session, scaffold and release contracts.
- Resolve OceanicVibes and Atelier from the canonical registry/manifest; record their current source/package pins, serving Worker versions, D1 ledger identities and website/editable-content checks.
- Inspect OceanicVibes's existing MX/provider, sending entitlement, routing and domain permissions read-only. Confirm the intended business mailbox address and a controlled external recipient before activation.
- Produce a concise change inventory and upstream dependency map.

Exit evidence: written existing-tenant baselines, production rollout inventory and compliance route. Any DNS/mail-provider conflict is an explicit prerequisite, not a reason to create a substitute tenant. No infrastructure is changed merely to draft the plan.

### Phase B — Canonical schema, transport and Worker integration

- Extract/adapt the narrow Mailflare primitives and add their provenance/tests.
- Integrate the existing canonical Worker wrapper and prove the complete OpenNext artifact generation and event dispatch.
- Integrate the feature runtime against the shared forms/contacts/conversation/message/operation schema and explicit access policies already owned by current `main`.
- Keep the canonical migration index/contract unchanged unless a focused schema diff proves the feature requires an additive migration; if so, generate, test and queue exactly that new migration without replacing or replaying existing history.
- Prove canonical persistence, incoming/Queue handler dispatch and reply matching with focused automated tests and the supported D1/Payload path.
- Measure dependency/bundle size and parsing runtime; identify actual reuse cost.

Exit evidence: passing canonical schema/migration, artifact and handler contract tests. No temporary collection, alternate schema or runtime-only SQL. If incompatible with the agreed architecture, stop with the first broken boundary; do not add a second Worker.

### Phase C — Durable enquiries and owner-approved conversational mail

- Implement acceptance receipts, state transitions, deduplication, outbox recovery and private storage access.
- Implement the shared form renderer, server validation and anti-spam setup.
- Implement inbound parsing/materialization and matching.
- Implement exact-revision owner approval and outbound delivery recording.
- Add safe incoming-attachment download and honest uncertain-delivery handling.
- Keep low-level provider helpers separate from authorization and persistence.

Exit evidence: form acceptance, threading, race and failure-injection tests against the supported canonical path. No bypass send endpoint or temporary message storage.

### Phase D — HelloAda UI and Ada drafting

- Build Inbox/Contacts in the existing admin shell with spacious functional layout.
- Add useful states, accessible controls, localized errors and unsent draft persistence.
- Wire Ada's restricted read/draft operations through existing tenant connection contracts.
- Keep email, settings, website publication and reports semantically distinct.

Exit evidence: authenticated component/integration checks at desktop/mobile sizes and a complete real owner send/review path ready for the live release. No demo inbox or simulated production success state.

### Phase E — OceanicVibes production rollout and live email validation

- Add recorded, idempotent resource/domain/email provisioning with a read-only planning step.
- Publish immutable shared package artifacts and update the canonical template/pins.
- Extend the existing VPS release contract for the custom entry artifact and email capability checks.
- Queue OceanicVibes's explicit additive schema migration and exact application release using its existing registered Worker and database.
- Obtain permission for the exact domain/DNS changes and mailbox/address before modifying them; do not assume an existing business MX is disposable. Use the approved controlled external recipient for email checks.
- Preserve OceanicVibes's frontend and map its current contact form to the shared form definition/submit component. Make only the content/layout change needed for the canonical form, through the existing review/version path.
- Validate the real published form → Messages → Ada draft → owner-approved Send → external reply loop, plus direct inbound mail to the domain address.
- Verify unchanged site content, editable bindings, existing Ada connection, website health and the same tenant's authenticated owner workspace.
- Record source, artifact, migration, provisioning and live validation separately.

Exit evidence: OceanicVibes's passing release/provisioning receipts, real custom-domain roundtrip and fresh signed-in browser checks. A local fixture, different tenant or different domain is not a pass. No manual production upload.

### Phase F — Atelier production rollout and cross-tenant validation

- Upgrade Atelier through the same exact shared package versions and schema/release route, with its own existing Worker/D1 and private resource identities.
- Map an existing appropriate form to the canonical form path without rewriting the website. Verify form receipt, contact creation, Messages, Ada drafting and the no-domain readiness state when applicable.
- If Atelier already has a supported registered custom domain and activation is approved, validate its real email too. Otherwise retain the explicit inactive-mail capability; do not invent a domain or treat OceanicVibes's mailbox as Atelier's sender.
- Prove A/B isolation for sessions, messages, contacts, attachments, Queue jobs, provisioning and Ada access on the two existing tenants.
- Verify no tenant-specific implementation or copy of the schema/provider code exists.

Exit evidence: both existing tenants serve the same shared capability/package identity with passing tenant-specific migration/release and authenticated UI receipts; OceanicVibes email remains operational after Atelier's rollout.

### Phase G — Default-platform contract and operational handoff

- Update the canonical HelloAda intake/scaffold/provisioning defaults to inherit the production capability without customer-specific edits.
- Add automated generation/bootstrap tests for schema identity, form references, package pins, Worker handlers and per-tenant resource mappings. Use ordinary local test fixtures, not a third deployed site.
- Exercise an Ada-generated form on an existing tenant and verify canonical data/transport rules without a coding-agent repair.
- Finish operational monitoring, backup/restore, retention, recovery and source/licence procedures.
- Document any planned independent adapter replacement separately. It must preserve the production contracts and data through a reviewed release; it is not unfinished work that justifies a temporary implementation now.

Exit evidence: shared-default tests pass, current-tenant live validation is complete and durable operating instructions are available. A full new live site created from scratch is outside this rollout; do not claim it has been validated.

## 15. Required validation matrix

The live validation targets are OceanicVibes and Atelier, with their exact registered resource identities named in the implementation report. Local fixtures must not substitute for required live checks. Failure-injection, abusive-input and concurrency tests run locally against the canonical contracts; do not deliberately disrupt the serving tenants or send unsolicited mail to real contacts.

| Area | Required checks |
| --- | --- |
| Forms | Published form accepted; invalid/extra fields rejected; disabled form rejected; locale labels work; invalid Turnstile rejected; rate/size limits enforced |
| Acceptance | Durable save precedes success; duplicate submit returns original receipt; Queue outage preserves enquiry; restart materializes it once |
| Incoming mail | Plain text and realistic multipart/HTML email; Unicode; actual external reply; malformed MIME; unknown recipient; enforced resource limits |
| Threading | Form enquiry → first real outgoing ID → visitor reply; direct email → reply → reply; different conversations from same sender remain distinct; forged references cannot join unauthorized context |
| Contacts | Conservative deduplication; owner notes/name preserved; no public reads or cross-tenant lookup |
| Private data | Anonymous REST/GraphQL/local-adapter misuse denied; attachment/raw-MIME URLs require permission; media/gallery cannot expose mail |
| Replies | Owner approval required; edited draft invalidates approval; double click and replay do not create another operation; revoked/expired session denied |
| Delivery | Definitive failure visible; bounded retry; provider acceptance distinguished from delivery; crash/timeout uncertainty does not trigger unsafe resend |
| Jobs | Duplicate/concurrent Queue events; consumer crash after commit; lost dispatch; exhausted retries retained; terminal jobs not retried forever |
| Email safety | Header injection rejected; HTML/script/remote tracking blocked; prompt injection cannot authorize tools; unsafe attachments not rendered |
| Domain setup | No-domain forms still work; clean authorized domain activates; conflicting MX untouched; rerun does not duplicate resources; wrong tenant/zone/Worker rejected |
| Isolation | A/B sessions, endpoint IDs, storage keys, Queues, Ada access and provisioning identities cannot reach the other tenant |
| Build/release | Exact pinned packages; custom wrapper included; full supported OpenNext build; immutable inspected artifact; explicit schema ledger migration; rollback preserves data |
| UI | Signed-in desktop/mobile; readable contrast; useful empty/error states; real Send action; fresh messages appear; session expiry preserves draft |
| Platform defaults | Automated HelloAda intake/scaffold/provisioning contract tests enforce shared forms/inbox; Ada cannot change schema or create an alternate transport; no new live tenant is required |
| Existing-site regressions | Both current sites retain frontend content, mapped editable fields, working preview, owner sessions, Ada connection and existing Growth functionality |
| Operations | Durable state survives Worker upgrades; explicit retention; private backup/restore; sanitized logs; alerts for failed/uncertain sends, failed processing and increasing Queue lag |

Use OceanicVibes's approved business-domain mailbox and a controlled external mailbox not on that domain for the email roundtrip. Record timestamps, internal operation IDs, provider IDs and sanitized headers. Screenshots alone do not prove message routing or idempotency.

Do not transmit customer enquiries to Ada/model providers without the established processing consent and minimization policy. Validate on the actual tenant endpoints using clearly identified owner-controlled enquiries, not real leads' personal data. These are ordinary canonical records, not a separate test mode or schema.

## 16. Deployment and rollback contract

Read the existing runbooks; extend them minimally. Do not create a new GitHub-to-Cloudflare deploy action just for mail.

1. Commit reviewed shared source, tests, licence/provenance material and migration artifacts to the official repository.
2. Publish immutable package releases; verify their existence/integrity and clean installation.
3. Update each selected consumer's exact dependency pins, lockfile and scaffold/runtime markers.
4. Register/provision additional resources through the protected control-plane operation. Application releases must not rewrite DNS, routes or cron triggers.
5. Request the exact committed schema migration with prior ledger identity and target head through the canonical queue.
6. Build in the release environment without production secrets; inspect the complete custom Worker artifact, not just the generated HTTP delegate.
7. Upload/promote only that inspected artifact through the VPS pipeline and retain its receipt.
8. Verify runtime identity, existing Ada connection, website content access, authenticated Messages and real inbound/outbound mail.
9. Record signed-in browser evidence separately before describing the release as validated.

Roll out OceanicVibes first, validate it, then roll out Atelier with the same shared version pins. Do not release to every future tenant automatically while the first tenant's required checks remain unproven. Once validated, commit the same canonical defaults so future tenant provisioning consumes the approved capability.

Extend artifact hashing, upload and receipt handling to include the custom Worker entry and all bundled dependencies. Do not inspect one artifact and upload another. The pipeline must prove website/admin and email handlers belong to the same promoted version.

A shared package update is propagated by explicit selected-consumer release requests. Verify every selected tenant; shared source does not prove tenant-specific bindings or activation.

If reverting to a previous Worker that has no email handler, first pause/repoint the new email route under an explicit operator procedure so incoming mail is not silently routed to a fetch-only Worker. Preserve inbox D1/R2 and queued work. Never roll back data with a code rollback or purge Queues to make a health check pass.

The proof must cover additive schema compatibility with the rollback target. Domain/resource rollback is separate from application rollback and must preserve pre-existing records. Keep a record of which newly created resources may be removed; no broad cleanup of a zone/account.

References: [canonical deployment procedure](https://github.com/weareheadless/site-agent/blob/main/deploy/README.md), [platform release boundaries](https://github.com/weareheadless/site-agent/blob/main/docs/platform-release-runbook.md).

## 17. Required documentation and handoff

Update `AGENTS.md` and the appropriate platform docs so future coding AIs know:

- Messages/forms are canonical shared capabilities, not tenant-specific features.
- OceanicVibes is the required first live domain-email validation target; Atelier receives the same shared feature second. No substitute tenant or experimental runtime mode.
- Which primitives come from Mailflare, their exact provenance and current compliance route.
- One Worker is required; no independent Mailflare deploy/updater/login.
- Schema/core/admin versions, resource identity rules and the tested wrapper build path.
- Provisioning versus application-release boundaries, supported domain prerequisites and MX conflict behavior.
- Approval semantics, uncertain-delivery handling, Queue recovery and operator diagnostics.
- The exact existing queue-based release and migration procedure; no handwritten deployment commands from arbitrary checkouts.
- Ada's allowed read/draft/form-data operations and prohibited schema/send/provisioning operations.
- How to repeat a real-email validation without disclosing secrets or using personal data.

The final implementation report must include:

- Source commits and upstream commit; published package versions and integrity.
- Selected tenant release IDs, exact promoted Worker versions and migration ledger receipts.
- Resource/provisioning receipts, without credentials.
- Tests performed, including failure-injection and authenticated UI checks.
- OceanicVibes real-email roundtrip evidence, Atelier shared-feature/isolation checks and automated future-default checks. Explicitly state that a newly provisioned live website is not part of this validation.
- What was actually reused and what had to be adapted.
- A small backend-neutral behavior specification and fixture suite for any future independent implementation. Preserve protocol/data expectations without describing copied source line by line. Any later replacement requires a reviewed data migration if needed and removal of the superseded adapter, not two simultaneously selectable engines.
- Any account/manual activation, legal, provider or runtime limitations still unresolved.
- A clear implemented/validated/not-validated distinction. Do not report completion while a required evidence row remains unproven.

## 18. Definition of done

The production rollout is complete only when:

- OceanicVibes's owner can receive a website enquiry, ask Ada for a draft, approve/send it from the approved domain address and receive the external visitor's reply in the same conversation on the existing live deployment.
- Direct incoming business email works in that same OceanicVibes inbox.
- Contacts/forms/messages have one canonical Payload authority with private access.
- The selected Mailflare primitives run inside the existing customer Worker, without importing the upstream application or parallel ORM/schema/deployment system.
- OceanicVibes and Atelier consume the same canonical packages/schema and their required live feature/isolation checks pass, without replacement tenants or customer-local implementations.
- The canonical template, intake and provisioning defaults inherit the capability and pass automated contract tests. No extra live site is spawned for this rollout, and no unperformed fresh-site validation is claimed.
- The required migrations and application release pass through the established VPS pipeline with verifiable receipts.
- Tested replays/failures do not lose accepted enquiries or create preventable duplicate sends; ambiguous external delivery is reported honestly.
- Supported domain provisioning is reproducible and never takes over an existing mail provider silently.
- Reused upstream code has a recorded source commit and provenance. Licensing is not a deployment gate for this owner-authorized implementation.
- Existing website content, editable field mapping, preview, owner sessions, Ada connectivity and Growth functionality remain working on both current tenants.
- Retention, private backup/restore, failed-job monitoring and recovery are implemented and documented as durable product operations, not left for a later cleanup.
- No secrets or inbox data are committed to source; no old admin surface, unused Mailflare agent/updater or fallback provider remain in the implementation.

Do not turn this into a full email suite. Ship the useful small-business feature as canonical production code, validate it on OceanicVibes and Atelier, and keep the architecture shared and the UX simple. A later independent adapter replacement is a separate reviewed product change, not permission to ship temporary architecture now.
