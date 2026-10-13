import { createHash } from 'node:crypto'
import { readFileSync, readdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { createHelloAdaContractIdentity } from '../packages/helloada-payload-core/src/contract.ts'
import { createHelloAdaContentContract, HELLOADA_CAPABILITIES } from '../packages/helloada-payload-core/src/schema/index.ts'

const root = fileURLToPath(new URL('../', import.meta.url))
const siteRootArgument = process.argv.slice(2).find((value) => value.startsWith('--site-root='))
const siteRoot = path.resolve(siteRootArgument?.slice('--site-root='.length) || path.join(root, 'src/site_agent/templates/next-payload'))
const contractPath = path.join(siteRoot, 'helloada-content-contract.json')
const manifestPath = path.join(siteRoot, 'template-manifest.json')
const wranglerPath = path.join(siteRoot, 'wrangler.jsonc')
const migrationsPath = path.join(siteRoot, 'src/migrations')
const contract = createHelloAdaContentContract()
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
const corePackage = JSON.parse(readFileSync(path.join(root, 'packages/helloada-payload-core/package.json'), 'utf8'))
const adminPackage = JSON.parse(readFileSync(path.join(root, 'packages/helloada-payload-admin/package.json'), 'utf8'))
const sitePackage = JSON.parse(readFileSync(path.join(siteRoot, 'package.json'), 'utf8'))
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

if (manifest.payloadCore !== corePackage.version || contract.coreVersion !== corePackage.version) {
  throw new Error('Template core version must match the shared package version.')
}
if (manifest.payloadAdmin !== adminPackage.version) throw new Error('Template admin version must match the shared package version.')
if (!sitePackage.dependencies['@weareheadless/helloada-payload-admin']?.includes(`payload-admin-v${adminPackage.version}/`)) {
  throw new Error('Site admin artifact pin does not match the shared package version.')
}
if (!sitePackage.dependencies['@weareheadless/helloada-payload-core']?.includes(`helloada-payload-core-v${corePackage.version}/`)) {
  throw new Error('Site core artifact pin does not match the shared package version.')
}

manifest.payloadAdmin = adminPackage.version
manifest.payloadCore = corePackage.version
manifest.schemaRevision = contract.schemaRevision
manifest.contentContract = contract.contract
manifest.migrations = migrations
manifest.migrationIndexSha256 = migrationIndexSha256
manifest.migrationHead = migrationHead
manifest.schemaIdentity = createHelloAdaContractIdentity({
  locales: manifest.locales,
  defaultLocale: manifest.defaultLocale,
  collections: HELLOADA_CAPABILITIES.collections,
  globals: Object.keys(contract.globals),
}).schemaIdentity

let wrangler = readFileSync(wranglerPath, 'utf8')
const schemaIdentitySlot = /("HELLOADA_SCHEMA_IDENTITY": ")(?:__HELLOADA_SCHEMA_IDENTITY__|[0-9a-f]{64})(")/
if (!schemaIdentitySlot.test(wrangler)) {
  throw new Error('Wrangler config has no generated schema-identity slot.')
}
wrangler = wrangler.replace(schemaIdentitySlot, `$1${manifest.schemaIdentity}$2`)
const migrationHeadSlot = /(\"HELLOADA_PAYLOAD_MIGRATION_HEAD\": \")(?:__HELLOADA_PAYLOAD_MIGRATION_HEAD__|[0-9a-f]{64})(\")/
if (!migrationHeadSlot.test(wrangler)) {
  throw new Error('Wrangler config has no generated Payload-migration-head slot.')
}
wrangler = wrangler.replace(migrationHeadSlot, `$1${migrationHead}$2`)

writeFileSync(contractPath, `${JSON.stringify(contract, null, 2)}\n`)
writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`)
for (const [name, version] of Object.entries({
  HELLOADA_TEMPLATE_SCHEMA: String(manifest.templateSchema),
  HELLOADA_PAYLOAD_ADMIN_VERSION: adminPackage.version,
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
process.stdout.write(`Generated Payload contract, site identity and Wrangler pin at ${siteRoot}.\n`)
