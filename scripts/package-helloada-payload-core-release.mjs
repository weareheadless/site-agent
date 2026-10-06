import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

export const readSchemaReleaseMetadata = schema => {
  const readString = name => {
    const match = schema.match(new RegExp(`export\\s+const\\s+${name}\\s*=\\s*(['\"])([^'\"]+)\\1\\s*;?`))
    if (!match) throw new Error(`Packed schema is missing ${name}`)
    return match[2]
  }
  const readInteger = name => {
    const match = schema.match(new RegExp(`export\\s+const\\s+${name}\\s*=\\s*(\\d+)\\s*;?`))
    if (!match) throw new Error(`Packed schema is missing ${name}`)
    return Number(match[1])
  }
  const metadata = {
    contentContract: readString('HELLOADA_CONTENT_CONTRACT_VERSION'),
    coreVersion: readString('HELLOADA_CORE_VERSION'),
    schemaRevision: readInteger('HELLOADA_SCHEMA_REVISION'),
  }
  if (!/^helloada-content-v\d+$/.test(metadata.contentContract)) throw new Error('Packed schema has an invalid content-contract version')
  if (!/^\d+\.\d+\.\d+$/.test(metadata.coreVersion)) throw new Error('Packed schema has an invalid core version')
  if (!Number.isSafeInteger(metadata.schemaRevision) || metadata.schemaRevision < 1) throw new Error('Packed schema has an invalid schema revision')
  return metadata
}

const root = fileURLToPath(new URL('../', import.meta.url))

const main = () => {
  const packageRoot = path.join(root, 'packages/helloada-payload-core')
  const pkg = JSON.parse(readFileSync(path.join(packageRoot, 'package.json'), 'utf8'))
  const sourceCommit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim()
  if (execFileSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' }).trim()) throw new Error('Release requires a clean checkout')
  const tag = process.env.RELEASE_TAG
  if (tag !== `helloada-payload-core-v${pkg.version}`) throw new Error('Release tag/version mismatch')
  if (execFileSync('git', ['rev-parse', `${tag}^{commit}`], { cwd: root, encoding: 'utf8' }).trim() !== sourceCommit) throw new Error('Release tag does not identify this checkout')

  const output = path.join(packageRoot, '.release')
  mkdirSync(output, { recursive: true })
  const packed = JSON.parse(execFileSync('npm', ['pack', '--json', '--pack-destination', output], { cwd: packageRoot, encoding: 'utf8' }))[0]
  const archive = path.join(output, packed.filename)
  const files = new Set(execFileSync('tar', ['-tzf', archive], { encoding: 'utf8' }).trim().split('\n'))
  for (const file of ['src/schema/index.ts', 'src/server.ts', 'src/routes.ts', 'src/contract.ts', 'README.md']) {
    if (!files.has(`package/${file}`)) throw new Error(`Packed artifact is missing ${file}`)
  }
  const packedText = file => execFileSync('tar', ['-xOf', archive, `package/${file}`], { encoding: 'utf8' })
  const schemaMetadata = readSchemaReleaseMetadata(packedText('src/schema/index.ts'))
  if (schemaMetadata.coreVersion !== pkg.version) throw new Error('Package and schema core versions do not match')
  const schema = packedText('src/schema/index.ts')
  if (!schema.includes('createPagesCollection') || !schema.includes('createNavigationGlobal')) throw new Error('Packed core is missing canonical collections or globals')
  const packageJson = JSON.parse(packedText('package.json'))
  if (packageJson.name !== pkg.name || packageJson.version !== pkg.version) throw new Error('Packed package identity mismatch')
  const digest = bytes => createHash('sha256').update(bytes).digest('hex')
  const manifest = {
    schemaVersion: 1, sourceCommit, releaseTag: tag, packageName: pkg.name, packageVersion: pkg.version,
    contentContract: schemaMetadata.contentContract,
    schemaRevision: schemaMetadata.schemaRevision,
    artifact: { filename: packed.filename, sha256: digest(readFileSync(archive)), integrity: packed.integrity },
    artifactInspection: 'passed', tenantMigration: 'not_performed', deployment: 'not_performed',
  }
  writeFileSync(path.join(output, 'release-manifest.json'), JSON.stringify(manifest, null, 2) + '\n')
  process.stdout.write(JSON.stringify(manifest) + '\n')
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) main()
