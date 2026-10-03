import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../', import.meta.url))
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
for (const file of ['src/schema/index.ts', 'src/server.ts', 'README.md']) {
  if (!files.has(`package/${file}`)) throw new Error(`Packed artifact is missing ${file}`)
}
const packedText = file => execFileSync('tar', ['-xOf', archive, `package/${file}`], { encoding: 'utf8' })
const schema = packedText('src/schema/index.ts')
if (!schema.includes('helloAdaContentContractVersion') && !schema.includes('HELLOADA_CONTENT_CONTRACT_VERSION')) {
  if (!schema.includes("'helloada-content-v1'")) throw new Error('Packed schema has no content-contract version')
}
if (!schema.includes('createPagesCollection') || !schema.includes('createNavigationGlobal')) throw new Error('Packed core is missing canonical collections or globals')
const packageJson = JSON.parse(packedText('package.json'))
if (packageJson.name !== pkg.name || packageJson.version !== pkg.version) throw new Error('Packed package identity mismatch')
const digest = bytes => createHash('sha256').update(bytes).digest('hex')
const manifest = {
  schemaVersion: 1, sourceCommit, releaseTag: tag, packageName: pkg.name, packageVersion: pkg.version,
  contentContract: 'helloada-content-v1',
  artifact: { filename: packed.filename, sha256: digest(readFileSync(archive)), integrity: packed.integrity },
  artifactInspection: 'passed', tenantMigration: 'not_performed', deployment: 'not_performed',
}
writeFileSync(path.join(output, 'release-manifest.json'), JSON.stringify(manifest, null, 2) + '\n')
process.stdout.write(JSON.stringify(manifest) + '\n')
