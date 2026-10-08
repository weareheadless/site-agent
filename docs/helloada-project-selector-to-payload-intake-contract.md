# HelloAda project selector to Payload intake contract

**Status:** Active architecture contract  
**Decision:** 2026-10-06

## Product boundary

HelloAda is the authenticated multi-project selector. It is not a second
website editor, intake conversation, design room, or approval dashboard. Existing
sites open their own Payload admin. New sites are registered and bootstrapped
by the shared Site-Agent, then the owner is handed into that same Payload admin.
All Ada conversation, business intake, design, content editing, review, growth,
and publication happen in the tenant workspace.

## Owner journey

1. **Choose or create.** After sign-in, the owner selects an owned website or
   names a new one. Creation is idempotent and produces one tenant identity.
2. **Prepare the workspace.** HelloAda asks the Site-Agent API to register the
   tenant and start the canonical bootstrap. The central VPS release timer
   creates the tenant resources and deploys the exact shared template/schema.
   The new Payload D1 must be empty before the committed migration chain is
   initialized. Missing keys, mismatched schemas, or failed release checks stop
   the operation visibly; no alternate CMS, remote database, or empty success
   path is permitted.
3. **Enter Payload.** Only after Site-Agent reports the exact tenant ready,
   HelloAda issues a short-lived, single-use owner grant. The tenant Worker
   redeems it and creates the normal Payload session. A direct admin URL is not
   an authentication path. HelloAda does not collect the business brief or
   create a second intake conversation.
4. **Intake and design with Ada.** Inside Payload, Ada learns the business,
   audience, offer, goals, constraints, content, and desired customer action.
   She proposes the initial direction/report and then generates a candidate
   from the confirmed intake. The same Site-Agent design pipeline owns planning,
   generation, repair, deterministic checks, visual/behavioral verification,
   and the owner-visible preview.
5. **Review, then publish.** The owner reviews the candidate in the Payload
   workspace. A draft, bootstrap-ready admin, successful build, or preview is
   not a public launch. Public deployment requires the existing explicit owner
   approval operation and the central exact-commit release pipeline.

## Shared schema and creative freedom

- Every new tenant starts from `src/site_agent/templates/next-payload` and the
  exact versioned shared Payload admin/core packages.
- The central schema owns editable page sections, articles and their listing
  images, metadata, shared navigation/footer/settings, and media relations.
  Initial design content is authored into those canonical documents and fields.
- Ada may change a tenant's website code, layout, visual system, typography,
  interactions, and motion. She may also edit the tenant's Payload content.
  She may not change Payload schema, migrations, admin, authentication, package
  versions, or runtime configuration. A design change must preserve the
  existing editable content bindings rather than creating a parallel content
  store or hard-coding duplicate content.
- Site-Agent schema changes are shared product releases, not per-tenant Ada
  actions. A committed migration and an explicit exact-chain release request
  are required where a database migration is needed.

## Release and readiness contract

- HelloAda, the shared API, shared packages, and customer Workers are released
  from reviewed immutable Git commits through the Site-Agent VPS pipeline. No
  manual Wrangler deployment, moving branch, local checkout deployment, or
  tenant-specific release procedure is allowed.
- Each production release records a unique release ID, exact source SHA,
  verification result, and retained receipt. API and HelloAda app releases have
  exact live-SHA health gates; customer Workers also prove their tenant and
  Payload contract. A failed gate restores the exact prior Worker/API version
  where applicable and records failure rather than silently switching paths.
- A successful new-site bootstrap means **the owner's Payload admin is ready**.
  It does not mean Ada has finished the intake, a design has passed owner
  review, or the public website is live.

## End-to-end acceptance

The flow is ready to test only when all of these are true:

1. HelloAda's production project selector is the version recorded in the
   central release receipt.
2. Site-Agent API is live at the exact queued SHA and has the matched public
   handoff key; the HelloAda Worker holds the matching private key only as a
   Cloudflare secret.
3. An explicitly created test tenant completes central resource creation,
   exact committed Payload schema initialization, Worker deployment, and
   authenticated Payload owner handoff.
4. The tenant opens with the canonical shared schema and correct isolated D1
   and R2 bindings; health and authenticated admin checks pass.
5. Ada can receive and confirm intake in that Payload admin, create a candidate
   using the canonical editable fields, and expose it to the owner in the real
   preview/review surface.
6. The candidate passes the documented deterministic and visual/behavioral
   checks. It remains unpublished until the owner explicitly approves it.

Use a disposable, explicitly named test business for acceptance. Do not create
one implicitly during deployment, and do not publish its site without the
owner's explicit approval.
