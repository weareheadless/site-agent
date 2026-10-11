import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { cp, mkdir, mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { applyBookingIntegrationPatch } from './booking-patches.mjs'
import { applyBookingParityPatches } from './booking-parity-patches.mjs'
import { applyBookingEditorPatches } from './booking-editor-patches-clean.mjs'
import { applyBookingUiPatch } from './booking-ui-patches.mjs'

const minimumNodeVersion = [22, 22, 2]
const actualNodeVersion = process.versions.node.split('.').map(Number)
const belowMinimum = actualNodeVersion[0] < minimumNodeVersion[0]
  || (actualNodeVersion[0] === minimumNodeVersion[0] && actualNodeVersion[1] < minimumNodeVersion[1])
  || (actualNodeVersion[0] === minimumNodeVersion[0] && actualNodeVersion[1] === minimumNodeVersion[1] && actualNodeVersion[2] < minimumNodeVersion[2])
if (belowMinimum) throw new Error('Mailflare integration requires Node.js >= 22.22.2; received ' + process.versions.node)

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const upstreamRoot = path.join(packageRoot, 'upstream')
const sourceMetadata = JSON.parse(await readFile(path.join(packageRoot, 'UPSTREAM.json'), 'utf8'))
const apiReference = /(["'`])\/api(?=\/|[?#"'`])/g

export function namespaceApiReferences(source) {
  return source.replace(apiReference, '$1/mail/api')
}

function replaceExactlyOnce(source, before, after, filename) {
  const first = source.indexOf(before)
  if (first < 0 || source.indexOf(before, first + before.length) >= 0) {
    throw new Error(`Pinned Mailflare integration patch no longer applies exactly once: ${filename}`)
  }
  return source.slice(0, first) + after + source.slice(first + before.length)
}

export function applyTenantPatches(nextConfig, workerEntry, cloudflareModule) {
  return {
    nextConfig: replaceExactlyOnce(
      nextConfig,
      'const nextConfig: NextConfig = {',
      'const nextConfig: NextConfig = {\n\tbasePath: process.env.HELLOADA_MAILFLARE_BASE_PATH || undefined,',
      'next.config.ts',
    ),
    workerEntry: replaceExactlyOnce(
      workerEntry,
      'if (url.pathname === "/api/realtime") {',
      'if (url.pathname === "/mail/api/realtime") {',
      'worker.ts',
    ),
    cloudflareModule: replaceExactlyOnce(
      replaceExactlyOnce(
        cloudflareModule,
        'import { withStorage } from "@/lib/storage";',
        'import { withStorage } from "@/lib/storage";\\nimport { asMailflareEnv } from "@/lib/helloada-tenant-bindings";',
        'src/lib/cloudflare.ts binding adapter import',
      ),
      'return withStorage(getNodeEnv() ?? (env as CloudflareEnv));',
      'return withStorage(asMailflareEnv(getNodeEnv() ?? (env as CloudflareEnv)));',
      'src/lib/cloudflare.ts environment boundary',
    ),
  }
}

async function applyBookingPatches(destination) {
  const files = {
    route: 'src/app/api/public/booking/[eventId]/route.ts',
    create: 'src/lib/booking/create.ts',
    schema: 'src/db/schema/index.ts',
    envTypes: 'env.d.ts',
    bookingTypes: 'src/app/api/public/booking/[eventId]/types.d.ts',
    bookingModelTypes: 'src/lib/booking/types.d.ts',
    bookingCoreUtils: 'src/lib/booking/utils.ts',
    availability: 'src/lib/booking/availability.ts',
    bookingCreateRoute: 'src/app/api/booking/route.ts',
    bookingEditorTypes: 'src/app/(calendar)/booking/types.d.ts',
    bookingPageUtils: 'src/app/(calendar)/booking/utils.ts',
    bookingEditor: 'src/app/(calendar)/booking/booking-editor.tsx',
    bookingUpdateRoute: 'src/app/api/booking/[eventId]/route.ts',
  }
  const uiFiles = {
    turnstile: 'src/components/auth/turnstile.tsx',
    page: 'src/app/book/[userId]/[eventId]/page.tsx',
    bookingUtils: 'src/app/book/[userId]/[eventId]/utils.ts',
    i18n: 'src/lib/i18n/en.json',
  }
  const filesToPatch = { ...files, ...uiFiles }
  const sources = Object.fromEntries(await Promise.all(
    Object.entries(filesToPatch).map(async ([key, relative]) => [key, await readFile(path.join(destination, relative), 'utf8')]),
  ))
  const integrationPatched = applyBookingIntegrationPatch(sources)
  const parityPatched = applyBookingParityPatches(sources, integrationPatched)
  const patched = applyBookingEditorPatches(sources, parityPatched)
  const patchedUi = applyBookingUiPatch(sources)
  await Promise.all([
    ...Object.entries(files).map(([key, relative]) =>
    writeFile(path.join(destination, relative), patched[key]),
    ),
    ...Object.entries(uiFiles).map(([key, relative]) =>
      writeFile(path.join(destination, relative), patchedUi[key]),
    ),
  ])
}

function run(command, args, cwd, env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, stdio: 'inherit' })
    child.once('error', reject)
    child.once('exit', (code, signal) => {
      if (code === 0) resolve()
      else reject(new Error(`${path.basename(command)} exited with ${signal ?? code}`))
    })
  })
}

async function sourceFiles(directory) {
  const { readdir } = await import('node:fs/promises')
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const file = path.join(directory, entry.name)
    if (entry.isDirectory()) files.push(...await sourceFiles(file))
    else if (/\.(?:[cm]?js|jsx|ts|tsx)$/.test(entry.name)) files.push(file)
  }
  return files
}

async function prepareBuildCopy(destination) {
  await cp(upstreamRoot, destination, {
    recursive: true,
    filter(source) {
      const relative = path.relative(upstreamRoot, source)
      const first = relative.split(path.sep)[0]
      if (['node_modules', 'dist', '.next', '.vinext', '.wrangler'].includes(first)) return false
      return relative !== 'next-env.d.ts' && relative !== 'src/lib/migrations/bundle.json'
    },
  })
  const sharedBindingsPath = path.resolve(packageRoot, '../../src/site_agent/templates/next-payload/mailflare-bindings.ts')
  await cp(sharedBindingsPath, path.join(destination, 'src/lib/helloada-tenant-bindings.ts'))
  await applyBookingPatches(destination)

  const nextPath = path.join(destination, 'next.config.ts')
  const workerPath = path.join(destination, 'worker.ts')
  const cloudflarePath = path.join(destination, 'src/lib/cloudflare.ts')
  const patched = applyTenantPatches(
    await readFile(nextPath, 'utf8'),
    await readFile(workerPath, 'utf8'),
    await readFile(cloudflarePath, 'utf8'),
  )
  await writeFile(nextPath, patched.nextConfig)
  await writeFile(workerPath, patched.workerEntry)
  await writeFile(cloudflarePath, patched.cloudflareModule)

  let referencesChanged = 0
  for (const file of await sourceFiles(path.join(destination, 'src'))) {
    const source = await readFile(file, 'utf8')
    const rewritten = namespaceApiReferences(source)
    if (rewritten !== source) {
      referencesChanged += (source.match(apiReference) ?? []).length
      await writeFile(file, rewritten)
    }
  }
  if (referencesChanged === 0) throw new Error('Mailflare API routes were not namespaced under /mail/api')
  return referencesChanged
}

async function exists(file) {
  try { await stat(file); return true } catch { return false }
}

async function copyMigrations(destination) {
  const source = path.join(upstreamRoot, 'drizzle', 'migrations')
  const { readdir } = await import('node:fs/promises')
  const upstreamNames = (await readdir(source, { withFileTypes: true }))
    .filter((entry) => entry.isFile() && entry.name.endsWith('.sql'))
    .map((entry) => entry.name)
    .sort()
  if (upstreamNames.length === 0) throw new Error('Pinned Mailflare source contains no D1 migrations')

  const integrationSource = path.join(packageRoot, 'integration-migrations')
  const integrationNames = sourceMetadata.integrationMigrations
  if (!Array.isArray(integrationNames) || integrationNames.length === 0) {
    throw new Error('HelloAda Mailflare integration migrations are not pinned')
  }
  const migrationFiles = [
    ...upstreamNames.map((name) => ({ name, source: path.join(source, name) })),
    ...integrationNames.map((name) => ({ name, source: path.join(integrationSource, name) })),
  ].sort((left, right) => left.name.localeCompare(right.name))
  if (new Set(migrationFiles.map(({ name }) => name)).size !== migrationFiles.length) {
    throw new Error('HelloAda migration names collide with the pinned Mailflare chain')
  }

  const output = path.join(destination, 'migrations')
  await mkdir(output, { recursive: true })
  const digest = createHash('sha256')
  for (const { name, source: migrationSource } of migrationFiles) {
    const contents = await readFile(migrationSource)
    digest.update(name).update('\0').update(contents).update('\0')
    await writeFile(path.join(output, name), contents)
  }
  return { names: migrationFiles.map(({ name }) => name), integrationNames, sha256: digest.digest('hex') }
}

async function migrationDigest(directory) {
  const { readdir } = await import('node:fs/promises')
  const names = (await readdir(directory, { withFileTypes: true }))
    .filter((entry) => entry.isFile() && entry.name.endsWith('.sql'))
    .map((entry) => entry.name)
    .sort()
  const digest = createHash('sha256')
  for (const name of names) {
    digest.update(name).update('\0').update(await readFile(path.join(directory, name))).update('\0')
  }
  return { names, sha256: digest.digest('hex') }
}

export async function buildTenantMailflare({ tenantRoot, npmBin = 'npm' }) {
  if (!path.isAbsolute(tenantRoot)) throw new Error('Tenant build root must be an absolute path')
  const pinnedPackage = JSON.parse(await readFile(path.join(upstreamRoot, 'package.json'), 'utf8'))
  const lock = await readFile(path.join(upstreamRoot, 'package-lock.json'))
  const lockHash = createHash('sha256').update(lock).digest('hex')
  if (pinnedPackage.version !== sourceMetadata.packageVersion || lockHash !== sourceMetadata.packageLockSha256) {
    throw new Error('Vendored Mailflare source does not match UPSTREAM.json')
  }

  const publicReleaseMarker = path.join(tenantRoot, 'public', 'helloada-release.json')
  const workerOutput = path.join(tenantRoot, '.mailflare')
  if (!(await exists(publicReleaseMarker))) {
    throw new Error('Mailflare must be built from a release checkout with its exact source marker')
  }
  if (await exists(workerOutput)) {
    throw new Error('Reserved Mailflare build output already exists; refusing to overwrite it')
  }

  const temporaryRoot = await mkdtemp(path.join(path.dirname(tenantRoot), '.helloada-mailflare-build-'))
  const buildSource = path.join(temporaryRoot, 'source')
  try {
    const referencesChanged = await prepareBuildCopy(buildSource)
    const buildEnv = {
      ...process.env,
      HELLOADA_MAILFLARE_BASE_PATH: sourceMetadata.basePath,
      PATH: `${path.dirname(npmBin)}:${process.env.PATH ?? ''}`,
    }
    await run(npmBin, ['ci', '--no-audit', '--no-fund'], buildSource, buildEnv)
    await run(npmBin, ['run', 'build'], buildSource, buildEnv)

    const serverOutput = path.join(buildSource, 'dist', 'server')
    const clientAssets = path.join(buildSource, 'dist', 'client', 'mail')
    if (!(await exists(path.join(serverOutput, 'index.js')))
        || !(await exists(path.join(serverOutput, 'ssr', 'index.js')))
        || !(await exists(path.join(clientAssets, '_next', 'static')))) {
      throw new Error('Mailflare build did not emit its Worker entrypoint, SSR chunks, and namespaced client assets')
    }

    await mkdir(path.join(tenantRoot, '.mailflare'), { recursive: true })
    await cp(serverOutput, path.join(workerOutput, 'server'), { recursive: true })
    await cp(clientAssets, path.join(workerOutput, 'client'), { recursive: true })
    const migrations = await copyMigrations(workerOutput)
    await writeFile(path.join(workerOutput, 'provenance.json'), `${JSON.stringify({
      repository: sourceMetadata.repository,
      commit: sourceMetadata.commit,
      packageVersion: sourceMetadata.packageVersion,
      packageLockSha256: lockHash,
      integrationPatchSet: sourceMetadata.integrationPatchSet,
      integrationMigrations: migrations.integrationNames,
      basePath: sourceMetadata.basePath,
      namespacedApiReferences: referencesChanged,
      migrationNames: migrations.names,
      migrationsSha256: migrations.sha256,
    }, null, 2)}\n`)
    return {
      commit: sourceMetadata.commit,
      basePath: sourceMetadata.basePath,
      namespacedApiReferences: referencesChanged,
      migrationsSha256: migrations.sha256,
      integrationMigrations: migrations.integrationNames,
    }
  } finally {
    await rm(temporaryRoot, { recursive: true, force: true })
  }
}

export async function composeTenantMailflareAssets({ tenantRoot }) {
  if (!path.isAbsolute(tenantRoot)) throw new Error('Tenant build root must be an absolute path')
  const openNextAssets = path.join(tenantRoot, '.open-next', 'assets')
  const workerOutput = path.join(tenantRoot, '.mailflare')
  const provenancePath = path.join(workerOutput, 'provenance.json')
  if (!(await exists(path.join(openNextAssets, 'helloada-release.json')))
      || !(await exists(provenancePath))
      || !(await exists(path.join(workerOutput, 'client', '_next', 'static')))
      || !(await exists(path.join(workerOutput, 'migrations')))) {
    throw new Error('OpenNext and pinned Mailflare build outputs are both required before asset composition')
  }
  const provenance = JSON.parse(await readFile(provenancePath, 'utf8'))
  for (const key of ['repository', 'commit', 'packageVersion', 'packageLockSha256', 'integrationPatchSet', 'integrationMigrations', 'basePath']) {
    if (JSON.stringify(provenance[key]) !== JSON.stringify(sourceMetadata[key])) throw new Error("Mailflare provenance mismatch: " + key)
  }
  const migrations = await migrationDigest(path.join(workerOutput, 'migrations'))
  if (!sourceMetadata.integrationMigrations.every((name) => migrations.names.includes(name))) {
    throw new Error('HelloAda integration migrations are missing from the tenant build')
  }
  if (migrations.sha256 !== provenance.migrationsSha256
      || JSON.stringify(migrations.names) !== JSON.stringify(provenance.migrationNames)) {
    throw new Error('Mailflare migration files differ from the pinned build receipt')
  }
  const destination = path.join(openNextAssets, 'mail')
  if (await exists(destination)) throw new Error('Reserved /mail asset namespace already exists; refusing to overwrite it')
  await cp(path.join(workerOutput, 'client'), destination, { recursive: true })
  return { basePath: sourceMetadata.basePath }
}

function parseArgs(args) {
  const values = new Map()
  const composeAssets = args.includes('--compose-assets')
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === '--compose-assets') continue
    const key = args[index]
    const value = args[index + 1]
    if (!key?.startsWith('--') || !value) throw new Error('Usage: build.mjs --tenant-root ABSOLUTE_PATH [--npm-bin ABSOLUTE_PATH]')
    values.set(key, value)
    index += 1
  }
  const tenantRoot = values.get('--tenant-root')
  if (!tenantRoot) throw new Error('Usage: build.mjs --tenant-root ABSOLUTE_PATH [--npm-bin ABSOLUTE_PATH]')
  return { tenantRoot, npmBin: values.get('--npm-bin') ?? 'npm', composeAssets }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const options = parseArgs(process.argv.slice(2))
  if (options.composeAssets) {
    const result = await composeTenantMailflareAssets(options)
    process.stdout.write(`Mailflare static assets composed at ${result.basePath}.\n`)
  } else {
    const result = await buildTenantMailflare(options)
    process.stdout.write(`Mailflare source ${result.commit} built at ${result.basePath}; namespaced ${result.namespacedApiReferences} API references.\n`)
  }
}
