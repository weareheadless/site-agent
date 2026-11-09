import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { createPresentationInventory } from './presentation-inventory.mjs'


const templateRoot = fileURLToPath(new URL('../', import.meta.url))
const siteRootArgument = process.argv.slice(2).find((value) => value.startsWith('--site-root='))
const siteRoot = path.resolve(siteRootArgument?.slice('--site-root='.length) || templateRoot)
const coreSourceRoot = path.join(siteRoot, 'node_modules/@weareheadless/helloada-payload-core/src')
const [{ createHelloAdaContractIdentity }, { createHelloAdaContentContract, HELLOADA_CAPABILITIES }] = await Promise.all([
  import(pathToFileURL(path.join(coreSourceRoot, 'contract.ts')).href),
  import(pathToFileURL(path.join(coreSourceRoot, 'schema/index.ts')).href),
])
const contractPath = path.join(siteRoot, 'helloada-content-contract.json')
const manifestPath = path.join(siteRoot, 'template-manifest.json')
const wranglerPath = path.join(siteRoot, 'wrangler.jsonc')
const migrationsPath = path.join(siteRoot, 'src/migrations')
const presentationPath = path.join(siteRoot, 'src/generated/helloada-presentation.json')
const contract = createHelloAdaContentContract()
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
// The source used by the Worker is authoritative. A copied template manifest
// may still describe the scaffold's default rather than this tenant's locales.
const { helloAdaSite } = await import(pathToFileURL(path.join(siteRoot, 'src/helloada.config.ts')).href)
// Committed pages are owner-visible routes even when no Payload document
// backs them. Derive the inventory from the app tree so a built site cannot
// ship without its pages listed in the workspace.
const presentation = createPresentationInventory(path.join(siteRoot, 'src/app'), helloAdaSite.routes.preview)
const corePackage = JSON.parse(readFileSync(path.join(siteRoot, 'node_modules/@weareheadless/helloada-payload-core/package.json'), 'utf8'))
const sitePackage = JSON.parse(readFileSync(path.join(siteRoot, 'package.json'), 'utf8'))
const siteLock = JSON.parse(readFileSync(path.join(siteRoot, 'package-lock.json'), 'utf8'))
// The admin is shared runtime source now, identified by the exact fingerprint
// of the bytes the release runner overlaid. It is supplied from outside so the
// generated Wrangler config cannot feed back into the fingerprint.
const sharedRuntime = String(process.env.HELLOADA_SHARED_RUNTIME_FINGERPRINT || '').trim().toLowerCase()
if (!/^[0-9a-f]{64}$/.test(sharedRuntime)) {
  throw new Error('The shared runtime fingerprint must be supplied to the contract generator.')
}
if (sitePackage.dependencies['@weareheadless/helloada-payload-admin'] !== undefined
  || siteLock.packages?.['node_modules/@weareheadless/helloada-payload-admin'] !== undefined) {
  throw new Error('The retired Payload admin package is still pinned in the site scaffold.')
}
const migrationIndex = readFileSync(path.join(migrationsPath, 'index.ts'), 'utf8')
const migrationNames = [...migrationIndex.matchAll(/import\s+\*\s+as\s+migration_(\w+)\s+from\s+'\.\/([^']+)'\s*;?/g)]
if (!migrationNames.length) throw new Error('The canonical template must declare its Payload migrations.')
const declaredNames = migrationNames.map((match) => {
  if (match[1] !== match[2]) throw new Error(`Migration import identity differs: ${match[1]}`)
  return match[2]
})
if (new Set(declaredNames).size !== declaredNames.length) throw new Error('Migration index contains duplicate identities.')
const actualNames = readdirSync(migrationsPath)
  .filter((name) => name.endsWith('.ts') && name !== 'index.ts')
  .map((name) => name.slice(0, -3))
  .sort()
if (JSON.stringify([...declaredNames].sort()) !== JSON.stringify(actualNames)) {
  throw new Error('Payload migration files and the canonical migration index do not match exactly.')
}
const migrations = declaredNames.map((name) => {
  const hash = (file) => createHash('sha256').update(readFileSync(file)).digest('hex')
  const snapshotPath = path.join(migrationsPath, `${name}.json`)
  const snapshot = JSON.parse(readFileSync(snapshotPath, 'utf8'))
  if (snapshot.dialect !== 'sqlite' || !snapshot.tables || typeof snapshot.tables !== 'object') {
    throw new Error(`Payload migration snapshot is not a SQLite schema: ${name}`)
  }
  return {
    name,
    fileSha256: hash(path.join(migrationsPath, `${name}.ts`)),
    snapshotSha256: hash(snapshotPath),
  }
})
const migrationIndexSha256 = createHash('sha256').update(migrationIndex).digest('hex')
const migrationHead = createHash('sha256')
  .update(JSON.stringify({
    indexSha256: migrationIndexSha256,
    migrations: migrations.map(({ name, fileSha256, snapshotSha256 }) => ({
      fileSha256, name, snapshotSha256,
    })),
  }))
  .digest('hex')

if (contract.coreVersion !== corePackage.version) {
  throw new Error('Generated contract core version must match the shared package version.')
}
if (!sitePackage.dependencies['@weareheadless/helloada-payload-core']?.includes(`helloada-payload-core-v${corePackage.version}/`)) {
  throw new Error('Site core artifact pin does not match the shared package version.')
}

delete manifest.payloadAdmin
delete manifest.sharedRuntime
manifest.sharedRuntimeFingerprint = sharedRuntime
manifest.payloadCore = corePackage.version
manifest.schemaRevision = contract.schemaRevision
manifest.contentContract = contract.contract
manifest.migrations = migrations
manifest.migrationIndexSha256 = migrationIndexSha256
manifest.migrationHead = migrationHead
const contractIdentity = createHelloAdaContractIdentity({
  locales: helloAdaSite.locales,
  defaultLocale: helloAdaSite.defaultLocale,
  collections: HELLOADA_CAPABILITIES.collections,
  globals: Object.keys(contract.globals),
})
manifest.schemaIdentity = contractIdentity.schemaIdentity
manifest.configurationIdentity = contractIdentity.configurationIdentity
manifest.locales = contractIdentity.locales
manifest.defaultLocale = contractIdentity.defaultLocale

// The generated identity is this build's output, not a value every tenant
// repository has to pre-declare. Older tenants and stale draft branches may
// not have the slots yet; add them to the Worker vars before filling them.
const generatedSlot = (key, placeholder) =>
  new RegExp(`("${key}":\\s*")(?:${placeholder}|[0-9a-f]{64})(")`)
const ensureGeneratedSlot = (source, key, placeholder) => {
  if (generatedSlot(key, placeholder).test(source)) return source
  const vars = /"vars"\s*:\s*\{/
  if (!vars.test(source)) {
    throw new Error(`Wrangler config has no "vars" object for ${key}.`)
  }
  return source.replace(vars, (match) => `${match}\n    "${key}": "${placeholder}",`)
}

let wrangler = readFileSync(wranglerPath, 'utf8')
wrangler = ensureGeneratedSlot(wrangler, 'HELLOADA_SCHEMA_IDENTITY', '__HELLOADA_SCHEMA_IDENTITY__')
wrangler = ensureGeneratedSlot(wrangler, 'HELLOADA_SHARED_RUNTIME_FINGERPRINT', '__HELLOADA_SHARED_RUNTIME_FINGERPRINT__')
wrangler = ensureGeneratedSlot(wrangler, 'HELLOADA_PAYLOAD_MIGRATION_HEAD', '__HELLOADA_PAYLOAD_MIGRATION_HEAD__')
wrangler = wrangler.replace(
  generatedSlot('HELLOADA_SCHEMA_IDENTITY', '__HELLOADA_SCHEMA_IDENTITY__'),
  `$1${manifest.schemaIdentity}$2`,
)
wrangler = wrangler.replace(
  generatedSlot('HELLOADA_SHARED_RUNTIME_FINGERPRINT', '__HELLOADA_SHARED_RUNTIME_FINGERPRINT__'),
  `$1${sharedRuntime}$2`,
)
wrangler = wrangler.replace(
  generatedSlot('HELLOADA_PAYLOAD_MIGRATION_HEAD', '__HELLOADA_PAYLOAD_MIGRATION_HEAD__'),
  `$1${migrationHead}$2`,
)

mkdirSync(path.dirname(presentationPath), { recursive: true })
writeFileSync(presentationPath, `${JSON.stringify(presentation, null, 2)}\n`)
writeFileSync(contractPath, `${JSON.stringify(contract, null, 2)}\n`)
writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`)
for (const [name, version] of Object.entries({
  HELLOADA_TEMPLATE_SCHEMA: String(manifest.templateSchema),
  HELLOADA_SHARED_RUNTIME_FINGERPRINT: sharedRuntime,
  HELLOADA_PAYLOAD_CORE_VERSION: corePackage.version,
  HELLOADA_PAYLOAD_SCHEMA_REVISION: String(contract.schemaRevision),
  HELLOADA_CONTENT_CONTRACT_VERSION: contract.contract,
})) {
  const slot = new RegExp('("' + name + '":\\s*")[^"]+(")', 'g')
  const matches = [...wrangler.matchAll(slot)]
  if (matches.length !== 1) throw new Error(`Expected exactly one runtime package version slot: ${name}`)
  wrangler = wrangler.replace(slot, (_match, before, after) => `${before}${version}${after}`)
}
writeFileSync(wranglerPath, wrangler)
process.stdout.write(`Generated Payload contract, site identity, presentation inventory and Wrangler pin at ${siteRoot}.\n`)
