import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { applyBookingIntegrationPatch } from '../scripts/booking-patches.mjs'
import { applyBookingParityPatches } from '../scripts/booking-parity-patches.mjs'
import { applyBookingEditorPatches } from '../scripts/booking-editor-patches-clean.mjs'
import { applyBookingUiPatch } from '../scripts/booking-ui-patches.mjs'
import { applyTenantPatches, composeTenantMailflareAssets, namespaceApiReferences } from '../scripts/build.mjs'
import { applyMailboxAccessPatch } from '../scripts/mailbox-access-patch.mjs'
import { asMailflareEnv } from '../../../src/site_agent/templates/next-payload/mailflare-bindings.ts'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

test('Mailflare vendor is fixed to the reviewed upstream revision and lockfile', async () => {
  const metadata = JSON.parse(await readFile(path.join(root, 'UPSTREAM.json'), 'utf8'))
  const packageJson = JSON.parse(await readFile(path.join(root, 'upstream/package.json'), 'utf8'))
  const lock = await readFile(path.join(root, 'upstream/package-lock.json'))
  assert.equal(metadata.repository, 'https://github.com/hieunc229/mailflare')
  assert.equal(metadata.commit, 'ca41c56a0781bf848b9898ddcc5615b3eacfbf8e')
  assert.equal(packageJson.version, metadata.packageVersion)
  assert.equal(createHash('sha256').update(lock).digest('hex'), metadata.packageLockSha256)
  assert.equal(metadata.basePath, '/mail')
})

test('provisioned shared mailbox access is independent of Team creation entitlement', async () => {
  const accessPath = path.join(root, 'upstream/src/lib/mailboxes/access.ts')
  const upstreamAccess = await readFile(accessPath, 'utf8')
  assert.match(upstreamAccess, /mailbox\.type !== "shared" \|\| !\(await isTeamMailboxSharingEnabled\(db\)\)/)
  assert.match(upstreamAccess, /if \(!\(await isTeamMailboxSharingEnabled\(db\)\)\) return owned;/)

  const patchedAccess = applyMailboxAccessPatch(upstreamAccess)
  assert.match(patchedAccess, /if \(mailbox\.type !== "shared"\) return null;/)
  assert.doesNotMatch(patchedAccess, /isTeamMailboxSharingEnabled/)
  assert.match(patchedAccess, /eq\(mailboxAccess\.userId, user\.id\)/)
  assert.match(patchedAccess, /eq\(mailboxAccess\.mailboxId, mailbox\.id\)/)

  const mailboxRoute = await readFile(path.join(root, 'upstream/src/app/api/mailboxes/route.ts'), 'utf8')
  assert.match(mailboxRoute, /if \(user\.role !== "admin" \|\| !entitlements\.canShareMailboxes\)/)
})

test('upstream remains pristine and HelloAda changes are explicit build patches', async () => {
  const nextConfig = await readFile(path.join(root, 'upstream/next.config.ts'), 'utf8')
  const worker = await readFile(path.join(root, 'upstream/worker.ts'), 'utf8')
  const cloudflare = await readFile(path.join(root, 'upstream/src/lib/cloudflare.ts'), 'utf8')
  assert.match(nextConfig, /const nextConfig: NextConfig = \{/)
  assert.doesNotMatch(nextConfig, /basePath:/)
  assert.match(worker, /url\.pathname === "\/api\/realtime"/)
  assert.doesNotMatch(worker, /url\.pathname === "\/mail\/api\/realtime"/)
  assert.ok(cloudflare.includes('return withStorage(getNodeEnv() ?? (env as CloudflareEnv));'))
  assert.ok(!cloudflare.includes('asMailflareEnv'))
  const patched = applyTenantPatches(nextConfig, worker, cloudflare)
  assert.match(patched.nextConfig, /basePath: process\.env\.HELLOADA_MAILFLARE_BASE_PATH/)
  assert.match(patched.workerEntry, /url\.pathname === "\/mail\/api\/realtime"/)
  assert.ok(patched.cloudflareModule.includes('import { asMailflareEnv } from "@/lib/helloada-tenant-bindings";'))
  assert.ok(patched.cloudflareModule.includes('return withStorage(asMailflareEnv(getNodeEnv() ?? (env as CloudflareEnv)));'))
})

test('tenant Mailflare adapter exposes the canonical DB binding without crossing tenant databases', () => {
  const mailDb = { name: 'tenant-mail-db' }
  const payloadDb = { name: 'tenant-payload-db' }
  const env = asMailflareEnv({ MAILFLARE_DB: mailDb, D1: payloadDb, DB: { name: 'unrelated-db' } })

  assert.equal(env.DB, mailDb)
  assert.equal(env.D1, payloadDb)
  assert.equal(asMailflareEnv({ DB: { name: 'unrelated-db' } }).DB, undefined)
})

test('booking integration patches only the disposable pinned source and require secure idempotent requests', async () => {
  const read = (relative) => readFile(path.join(root, 'upstream', relative), 'utf8')
  const sources = {
    route: await read('src/app/api/public/booking/[eventId]/route.ts'),
    create: await read('src/lib/booking/create.ts'),
    schema: await read('src/db/schema/index.ts'),
    envTypes: await read('env.d.ts'),
    bookingModelTypes: await read('src/lib/booking/types.d.ts'),
    bookingCoreUtils: await read('src/lib/booking/utils.ts'),
    availability: await read('src/lib/booking/availability.ts'),
    bookingCreateRoute: await read('src/app/api/booking/route.ts'),
    bookingUpdateRoute: await read('src/app/api/booking/[eventId]/route.ts'),
    bookingEditorTypes: await read('src/app/(calendar)/booking/types.d.ts'),
    bookingDefaultEvents: await read('src/app/(calendar)/booking/default-events.ts'),
    bookingPageUtils: await read('src/app/(calendar)/booking/utils.ts'),
    bookingEditor: await read('src/app/(calendar)/booking/booking-editor.tsx'),
    bookingTypes: await read('src/app/api/public/booking/[eventId]/types.d.ts'),
  }
  const integrationPatched = applyBookingIntegrationPatch(sources)
  const parityPatched = applyBookingParityPatches(sources, integrationPatched)
  const patched = applyBookingEditorPatches(sources, parityPatched)
  assert.match(patched.route, /verifyTurnstileToken/)
  assert.match(patched.route, /BOOKING_RATE_LIMIT\.limit/)
  assert.match(patched.route, /existingBookingRequest/)
  assert.match(patched.create, /ON CONFLICT\(user_id, booking_request_id\) DO NOTHING/)
  assert.match(patched.create, /INSERT INTO contacts \(id, user_id, email, display_name, source, last_seen_at, created_at\)/)
  assert.match(patched.create, /WHERE EXISTS \(SELECT 1 FROM calendar_events WHERE user_id = \? AND booking_request_id = \? AND booking_request_hash = \?\)/)
  assert.match(patched.create, /ON CONFLICT\(user_id, email\) DO UPDATE/)
  assert.match(patched.schema, /booking_request_hash/)
  assert.match(patched.bookingTypes, /turnstileToken\?: unknown/)

  const uiRead = (relative) => readFile(path.join(root, 'upstream', relative), 'utf8')
  assert.match(patched.availability, /helloadaPayloadManaged/)
  assert.match(patched.availability, /helloadaMinimumNoticeHours/)
  assert.match(patched.availability, /helloadaBufferMinutes/)
  assert.match(patched.availability, /parseHelloAdaWeeklyAvailability/)
  assert.match(patched.bookingCoreUtils, /booking_weekly_availability_invalid/)
  assert.match(patched.bookingPageUtils, /parseHelloAdaWeeklyAvailability/)
  assert.match(patched.bookingPageUtils, /weeklyAvailability/)
  assert.match(patched.bookingEditor, /updateRangesForDay/)
  assert.match(patched.bookingEditorTypes, /helloadaWeeklyAvailability: string/)
  assert.match(patched.bookingEditorTypes, /weeklyAvailability: BookingWeeklyAvailability\[\]/)
  assert.match(patched.bookingDefaultEvents, /helloadaWeeklyAvailability: JSON\.stringify\(\[1, 2, 3, 4, 5\]\.map/)
  assert.match(patched.bookingDefaultEvents, /helloadaBufferMinutes: 0/)
  assert.match(patched.bookingUpdateRoute, /helloadaWeeklyAvailability: JSON\.stringify\(input\.weeklyAvailability\)/)
  const uiSources = {
    page: await uiRead('src/app/book/[userId]/[eventId]/page.tsx'),
    turnstile: await uiRead('src/components/auth/turnstile.tsx'),
    bookingUtils: await uiRead('src/app/book/[userId]/[eventId]/utils.ts'),
    i18n: await uiRead('src/lib/i18n/en.json'),
  }
  const patchedUi = applyBookingUiPatch(uiSources)
  assert.match(patchedUi.page, /bookingConsent/)
  assert.match(patchedUi.page, /TurnstileField siteKey=/)
  assert.match(patchedUi.page, /bookingRequestRef/)
  assert.match(patchedUi.turnstile, /configuredSiteKey/)
  assert.match(patchedUi.bookingUtils, /turnstileToken: string/)
  assert.doesNotMatch(uiSources.page, /bookingRequestRef/)
  assert.doesNotMatch(sources.route, /verifyTurnstileToken/)

  const metadata = JSON.parse(await readFile(path.join(root, 'UPSTREAM.json'), 'utf8'))
  assert.deepEqual(metadata.integrationMigrations, ['0061_helloada_booking_idempotency.sql', '0062_helloada_payload_migration.sql'])
  const bookingMigration = await readFile(path.join(root, 'integration-migrations', metadata.integrationMigrations[0]), 'utf8')
  assert.match(bookingMigration, /CREATE UNIQUE INDEX calendar_events_booking_request_idx/)
  const payloadMigration = await readFile(path.join(root, 'integration-migrations', metadata.integrationMigrations[1]), 'utf8')
  assert.match(payloadMigration, /CREATE TABLE helloada_import_runs/)
  assert.match(payloadMigration, /helloada_payload_managed/)
})

test('all root-relative Mailflare API URLs receive the one explicit /mail namespace', () => {
  const source = `authFetch("/api/messages"); fetch('/api'); fetch(\`/api/drafts/\${id}\`); fetch("/inbox")`

  assert.equal(
    namespaceApiReferences(source),
    `authFetch("/mail/api/messages"); fetch('/mail/api'); fetch(\`/mail/api/drafts/\${id}\`); fetch("/inbox")`,
  )
})

test('Mailflare assets compose only into the reserved /mail namespace with pinned provenance', async () => {
  const tenantRoot = await mkdtemp(path.join(tmpdir(), 'helloada-mailflare-assets-'))
  try {
    const metadata = JSON.parse(await readFile(path.join(root, 'UPSTREAM.json'), 'utf8'))
    const assets = path.join(tenantRoot, '.open-next', 'assets')
    const client = path.join(tenantRoot, '.mailflare', 'client')
    await mkdir(assets, { recursive: true })
    await mkdir(path.join(client, '_next', 'static', 'chunks'), { recursive: true })
    await writeFile(path.join(assets, 'helloada-release.json'), '{}\n')
    await writeFile(path.join(client, '_next', 'static', 'chunks', 'mail.js'), 'mailflare')
    const migrationNames = metadata.integrationMigrations
    const migrations = path.join(tenantRoot, '.mailflare', 'migrations')
    await mkdir(migrations, { recursive: true })
    const migrationDigest = createHash('sha256')
    for (const migrationName of migrationNames) {
      const migrationBytes = await readFile(path.join(root, 'integration-migrations', migrationName))
      await writeFile(path.join(migrations, migrationName), migrationBytes)
      migrationDigest.update(migrationName).update('\0').update(migrationBytes).update('\0')
    }
    const migrationsSha256 = migrationDigest.digest('hex')
    await writeFile(path.join(tenantRoot, '.mailflare', 'provenance.json'), JSON.stringify({
      ...metadata,
      namespacedApiReferences: 307,
      migrationNames,
      migrationsSha256,
    }))

    await assert.rejects(
      composeTenantMailflareAssets({ tenantRoot }),
      /Canonical HelloAda mark is missing/,
    )
    const helloAdaMark = await readFile(
      path.resolve(root, '../../src/site_agent/templates/next-payload/public/brand/helloada-logo.svg'),
      'utf8',
    )
    await mkdir(path.join(assets, 'brand'), { recursive: true })
    await writeFile(path.join(assets, 'brand', 'helloada-logo.svg'), helloAdaMark)

    const result = spawnSync(process.execPath, [
      path.join(root, 'scripts', 'build.mjs'), '--tenant-root', tenantRoot, '--compose-assets',
    ], { encoding: 'utf8' })
    assert.equal(result.status, 0, result.stderr)
    assert.match(result.stdout, /static assets composed at \/mail/)
    assert.equal(
      await readFile(path.join(assets, 'mail', '_next', 'static', 'chunks', 'mail.js'), 'utf8'),
      'mailflare',
    )
    assert.equal(await readFile(path.join(assets, 'brand', 'helloada-logo.svg'), 'utf8'), helloAdaMark)
  } finally {
    await rm(tenantRoot, { recursive: true, force: true })
  }
})
