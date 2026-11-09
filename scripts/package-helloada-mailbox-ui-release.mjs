import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

/**
 * Packages the generated mailbox UI from the pinned Mailflare upstream.
 *
 * The package is not hand-maintained: `npm pack` runs the generator, which
 * rebuilds `dist/` from packages/helloada-mailflare/upstream. This script
 * asserts the exact artifact, its upstream pin and its contract before an
 * operator publishes it as a GitHub release asset.
 */

const root = fileURLToPath(new URL('../', import.meta.url))
const packageRoot = path.join(root, 'packages/helloada-mailbox-ui')

const assertTarEntry = (archive, file) => {
  const entries = new Set(execFileSync('tar', ['-tzf', archive], { encoding: 'utf8' }).trim().split('\n'))
  if (!entries.has(`package/${file}`)) throw new Error(`Packed artifact is missing ${file}`)
}

const main = () => {
  const pkg = JSON.parse(readFileSync(path.join(packageRoot, 'package.json'), 'utf8'))
  const sourceCommit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim()
  if (execFileSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' }).trim()) {
    throw new Error('Release requires a clean checkout')
  }
  const tag = process.env.RELEASE_TAG
  if (tag !== `helloada-mailbox-ui-v${pkg.version}`) throw new Error('Release tag/version mismatch')
  if (execFileSync('git', ['rev-parse', `${tag}^{commit}`], { cwd: root, encoding: 'utf8' }).trim() !== sourceCommit) {
    throw new Error('Release tag does not identify this checkout')
  }

  const upstreamPin = JSON.parse(readFileSync(path.join(root, 'packages/helloada-mailflare/UPSTREAM.json'), 'utf8'))
  const output = path.join(packageRoot, '.release')
  mkdirSync(output, { recursive: true })
  // Build once with visible output, then pack the exact built tree without
  // letting the build's stdout corrupt npm's JSON report.
  execFileSync('node', ['scripts/build.mjs'], { cwd: packageRoot, stdio: 'inherit' })
  const packed = JSON.parse(execFileSync('npm', ['pack', '--json', '--ignore-scripts', '--pack-destination', output], { cwd: packageRoot, encoding: 'utf8' }))[0]
  const archive = path.join(output, packed.filename)

  for (const file of ['dist/index.tsx', 'dist/base.tsx', 'dist/routes.generated.tsx', 'dist/styles.css', 'dist/build.json', 'README.md']) {
    assertTarEntry(archive, file)
  }
  const build = JSON.parse(execFileSync('tar', ['-xOf', archive, 'package/dist/build.json'], { encoding: 'utf8' }))
  if (build.upstreamCommit !== upstreamPin.commit || build.upstreamPackageVersion !== upstreamPin.packageVersion) {
    throw new Error('Packed mailbox UI is not built from the pinned upstream')
  }
  if (build.integrationPatchSet !== 'helloada-mailbox-ui-v1') throw new Error('Packed mailbox UI has an unknown patch set')
  if (!(build.pages >= 20) || !(build.files >= 200) || !(build.locales >= 30)) {
    throw new Error('Packed mailbox UI is missing routes, sources or locale catalogs')
  }
  const base = execFileSync('tar', ['-xOf', archive, 'package/dist/base.tsx'], { encoding: 'utf8' })
  if (!base.includes('resolveApiInput') || !base.includes('useMailboxParams')) {
    throw new Error('Packed mailbox UI is missing its control-plane adapters')
  }
  const packedPackage = JSON.parse(execFileSync('tar', ['-xOf', archive, 'package/package.json'], { encoding: 'utf8' }))
  if (packedPackage.name !== pkg.name || packedPackage.version !== pkg.version) throw new Error('Packed package identity mismatch')

  const digest = (bytes) => createHash('sha256').update(bytes).digest('hex')
  const manifest = {
    schemaVersion: 1,
    sourceCommit,
    releaseTag: tag,
    packageName: pkg.name,
    packageVersion: pkg.version,
    upstream: { repository: upstreamPin.repository, commit: upstreamPin.commit, packageVersion: upstreamPin.packageVersion },
    mailbox: { patchSet: build.integrationPatchSet, pages: build.pages, files: build.files, locales: build.locales },
    artifact: {
      filename: packed.filename,
      sha256: digest(readFileSync(archive)),
      integrity: packed.integrity,
      size: packed.size,
    },
    artifactInspection: 'passed',
    deployment: 'not_performed',
  }
  writeFileSync(path.join(output, 'release-manifest.json'), JSON.stringify(manifest, null, 2) + '\n')
  process.stdout.write(JSON.stringify(manifest) + '\n')
}

main()
