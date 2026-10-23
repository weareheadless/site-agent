import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../', import.meta.url))
const packageRoot = path.join(root, 'packages/helloada-payload-admin')
const pkg = JSON.parse(readFileSync(path.join(packageRoot, 'package.json'), 'utf8'))
const sourceCommit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim()
const candidate = process.argv.includes('--candidate')
if (!candidate && execFileSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' }).trim()) throw new Error('Release requires a clean checkout')
const tag = candidate ? 'payload-admin-v' + pkg.version : process.env.RELEASE_TAG
if (tag !== 'payload-admin-v' + pkg.version) throw new Error('Release tag/version mismatch')
if (!candidate && execFileSync('git', ['rev-parse', tag + '^{commit}'], { cwd: root, encoding: 'utf8' }).trim() !== sourceCommit) throw new Error('Release tag does not identify this checkout')
const output = path.join(packageRoot, '.release')
mkdirSync(output, { recursive: true })
const packed = JSON.parse(execFileSync('npm', ['pack', '--json', '--pack-destination', output], { cwd: packageRoot, encoding: 'utf8' }))[0]
const archive = path.join(output, packed.filename)
const files = new Set(execFileSync('tar', ['-tzf', archive], { encoding: 'utf8' }).trim().split('\n'))
for (const file of ['src/components/GrowthTasks.tsx', 'src/components/HelloAdaGrowth.tsx', 'src/components/HelloAdaNav.tsx', 'src/components/WebsiteWorkspace.tsx', 'src/components/MailflarePayloadView.tsx', 'src/lib/growth-task-copy.ts', 'src/server/runtime-env.ts', 'src/styles/growth.scss']) {
  if (!files.has(`package/${file}`)) throw new Error(`Packed artifact is missing ${file}`)
}
const packedText = file => execFileSync('tar', ['-xOf', archive, `package/${file}`], { encoding: 'utf8' })
const growth = packedText('src/components/HelloAdaGrowth.tsx')
if (!/<GrowthTasks(?:\s|>)/.test(growth) || growth.includes('helloada-growth-sidebar') || !growth.includes('owner-decisions-v1') || !growth.includes('owner-queue-progression-v1')) throw new Error('Packed artifact has the old scattered Growth overview or lacks the supported progression contract check')
const growthTasks = packedText('src/components/GrowthTasks.tsx')
const growthData = packedText('src/lib/growth-data.ts')
if (!growth.includes('isGrowthServiceModel(body.serviceModel)')
  || !growthData.includes('growth-service-v1')
  || !growthTasks.includes('serviceModel.areas.map')
  || !growthTasks.includes('serviceModel.decisionIds')
  || !growthTasks.includes('serviceModel.preparation')
  || !growthTasks.includes('serviceModel.recentResults')
  || /task\.area|growthAreaTasks/.test(growthTasks)) {
  throw new Error('Packed admin artifact lacks the canonical Growth service dashboard or invents a parallel area model')
}
if (!growthTasks.includes('articlePayloadConflict') || !growthTasks.includes('growth.articleResolve')) throw new Error('Packed admin artifact cannot explain or resolve blocked Payload article drafts')
if (/HelloAdaMessages|HelloAdaCalendar/.test(packedText('src/index.ts'))) throw new Error('Packed admin package exposes a parallel Payload mailbox or calendar UI')
if (!packedText('src/components/HelloAdaNav.tsx').includes('href="/admin?view=messages"')
  || !packedText('src/components/WebsiteWorkspace.tsx').includes('<MailflarePayloadView />')
  || !packedText('src/components/WebsiteWorkspace.tsx').includes('<MailflarePayloadView surface="calendar" />')
  || !packedText('src/components/MailflarePayloadView.tsx').includes('src={src}')) {
  throw new Error('Packed admin package does not embed the native Mailflare app inside Payload')
}
const runtime = packedText('src/server/runtime-env.ts')
if (!runtime.includes('helloAdaWorkspacePath') || !runtime.includes('/growth/check')) throw new Error('Packed artifact lacks the shared Growth bridge')
const packedPackage = JSON.parse(packedText('package.json'))
if (packedPackage.version !== pkg.version) throw new Error('Packed package version mismatch')
if (!packedText('src/version.ts').includes(`= '${pkg.version}'`)) throw new Error('Packed admin runtime version marker mismatch')
const digest = bytes => createHash('sha256').update(bytes).digest('hex')
const manifest = {
  schemaVersion: 1, sourceCommit, releaseTag: tag, packageName: pkg.name, packageVersion: pkg.version,
  artifact: { filename: packed.filename, sha256: digest(readFileSync(archive)), integrity: packed.integrity },
  approvedLogoSourceSha256: digest(packedText('src/components/HelloAdaLogo.tsx')),
  artifactInspection: 'passed', deployment: 'not_performed', authenticatedBrowserVerification: 'required',
}
writeFileSync(path.join(output, 'release-manifest.json'), JSON.stringify(manifest, null, 2) + '\n')
process.stdout.write(JSON.stringify(manifest) + '\n')
