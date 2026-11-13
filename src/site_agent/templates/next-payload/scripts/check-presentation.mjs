#!/usr/bin/env node
/**
 * One presentation check for every tenant, run before a release can see it.
 *
 * A static presentation commits `helloada-frontend.json`: every public file by
 * digest, the routes those files define and the locales they speak. The release
 * refuses a tree whose declaration drifted, but it only finds out after the
 * owner approved and the change merged. This check runs on every push to the
 * branches the workspace uses, so the drift fails a build instead.
 *
 * It mirrors the platform's import validator exactly, no more: the files, the
 * routes, the locales, the reserved paths and the assets the markup actually
 * loads. A tenant's own editorial rules belong to that tenant, not here. A
 * Next/Payload tenant has no such inventory; the check says so and exits 0. The
 * workflow is identical in every tenant repository.
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

const root = process.cwd()
const publicDir = path.join(root, 'public')
const manifestPath = path.join(root, 'helloada-frontend.json')
const RESERVED = ['admin', 'api', '_next', 'mail', 'blog', '_helloada']
const MAX_ASSET_BYTES = 25 * 1024 * 1024

if (!fs.existsSync(manifestPath)) {
  console.log('Not a static presentation (no helloada-frontend.json); nothing to check.')
  process.exit(0)
}

const problems = []
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b)
// Inventories are maps, not documents: the platform looks entries up, so a
// reordered declaration is not drift.
const sameEntries = (a, b) => {
  const left = a && typeof a === 'object' ? a : {}
  const right = b && typeof b === 'object' ? b : {}
  const keys = Object.keys(left)
  return keys.length === Object.keys(right).length && keys.every((key) => left[key] === right[key])
}

/** Parse a start tag into its attributes, as the platform's HTML parser does. */
const attributes = (source) => {
  const found = {}
  for (const match of source.matchAll(/([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g)) {
    found[match[1].toLowerCase()] = match[2] ?? match[3] ?? match[4] ?? ''
  }
  return found
}

/** The assets one page loads; anchors are the tenant's own editorial concern. */
const pageReferences = (html) => {
  const references = []
  // Script and style bodies are data to an HTML parser, not markup: an inline
  // template literal that builds an <img> is not a reference from this page.
  const markup = html
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '')
  for (const [, name, rest] of markup.matchAll(/<([a-zA-Z][\w:-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>/g)) {
    const attrs = attributes(rest)
    const tag = name.toLowerCase()
    for (const key of ['src', 'poster']) if (attrs[key]) references.push(attrs[key])
    if (tag === 'link' && ['stylesheet', 'icon', 'preload'].includes(attrs.rel) && attrs.href) references.push(attrs.href)
    if (attrs.srcset) {
      for (const item of attrs.srcset.split(',')) {
        const candidate = item.trim().split(/\s+/)[0]
        if (candidate) references.push(candidate)
      }
    }
  }
  return references
}

/** Resolve a reference the way the platform does; return its path or ''. */
const localPath = (reference, relative) => {
  let parsed
  try {
    parsed = new URL(reference, `https://static.invalid${relative}`)
  } catch {
    return ''
  }
  if (parsed.origin !== 'https://static.invalid' || !parsed.pathname) return ''
  try {
    return decodeURIComponent(parsed.pathname)
  } catch {
    return ''
  }
}

const walk = (directory) => fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
  const full = path.join(directory, entry.name)
  if (entry.isSymbolicLink()) throw new Error(`Static website files must not contain a symlink: ${path.relative(root, full)}`)
  return entry.isDirectory() ? walk(full) : [full]
})

if (!fs.existsSync(path.join(publicDir, 'index.html'))) {
  throw new Error('The static presentation needs a committed public/index.html.')
}

const files = {}
const routes = {}
const locales = new Set()
let defaultLocale = ''
for (const file of walk(publicDir).sort()) {
  const relative = '/' + path.relative(publicDir, file).split(path.sep).join('/')
  // Written by the canonical build as provenance, not customer presentation.
  if (relative === '/helloada-release.json') continue
  if (RESERVED.includes(relative.split('/')[1])) {
    throw new Error(`Static website uses a reserved platform path: ${relative}`)
  }
  if (fs.statSync(file).size > MAX_ASSET_BYTES) {
    throw new Error(`Static asset exceeds the supported limit: ${relative}`)
  }
  const bytes = fs.readFileSync(file)
  files[relative] = crypto.createHash('sha256').update(bytes).digest('hex')

  let references = []
  if (file.endsWith('.html')) {
    const html = bytes.toString('utf8')
    if (relative !== '/404.html' && !/<\/head\s*>/i.test(html)) {
      throw new Error(`An explicit HTML head boundary is required: ${relative}`)
    }
    const language = (html.match(/<html[^>]*\slang="([^"]+)"/i)?.[1] || '').split('-')[0].toLowerCase()
    if (!/^[a-z]{2,3}$/.test(language)) {
      throw new Error(`An explicit HTML language is required: ${relative}`)
    }
    locales.add(language)
    if (relative === '/index.html') defaultLocale = language
    if (path.basename(file) === 'index.html') routes[relative.slice(0, -'index.html'.length)] = relative
    references = pageReferences(html)
  } else if (file.endsWith('.css')) {
    references = [...bytes.toString('utf8').matchAll(/url\(\s*['"]?([^\s)'";]+)/g)].map((match) => match[1])
  }
  for (const reference of references) {
    const resolved = localPath(reference, relative)
    if (!resolved) continue
    const target = path.resolve(publicDir, resolved.replace(/^\//, ''))
    if (target !== publicDir && !target.startsWith(publicDir + path.sep)) {
      problems.push(`${relative} references a file outside the website: ${reference}`)
    } else if (!fs.existsSync(target) || !fs.statSync(target).isFile()) {
      problems.push(`${relative} references a missing local file: ${reference}`)
    }
  }
}

const declared = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
if (declared.kind !== 'static') problems.push(`kind is ${JSON.stringify(declared.kind)}, expected "static"`)
if (declared.defaultLocale !== defaultLocale) {
  problems.push(`defaultLocale is ${JSON.stringify(declared.defaultLocale)}, the home page declares ${JSON.stringify(defaultLocale)}`)
}
const expectedLocales = [defaultLocale, ...[...locales].filter((value) => value !== defaultLocale).sort()]
if (!same(declared.locales, expectedLocales)) {
  problems.push(`locales are ${JSON.stringify(declared.locales)}, the files declare ${JSON.stringify(expectedLocales)}`)
}
if (!sameEntries(declared.routes, routes)) problems.push('routes no longer match the committed index.html files')
if (!sameEntries(declared.files, files)) {
  const declaredFiles = declared.files && typeof declared.files === 'object' ? declared.files : {}
  const added = Object.keys(files).filter((key) => !(key in declaredFiles))
  const removed = Object.keys(declaredFiles).filter((key) => !(key in files))
  const changed = Object.keys(files).filter((key) => key in declaredFiles && files[key] !== declaredFiles[key])
  problems.push(
    `files no longer match: ${added.length} added, ${removed.length} removed, ${changed.length} changed`
    + (added.length ? ` (added ${added.slice(0, 4).join(', ')})` : '')
    + (removed.length ? ` (removed ${removed.slice(0, 4).join(', ')})` : '')
    + (changed.length ? ` (changed ${changed.slice(0, 4).join(', ')})` : ''),
  )
}

if (problems.length) {
  console.error('The static presentation does not match the committed website files:')
  for (const problem of problems.slice(0, 40)) console.error(`  - ${problem}`)
  if (problems.length > 40) console.error(`  … and ${problems.length - 40} more`)
  console.error('Regenerate helloada-frontend.json in the same commit that changes public/.')
  process.exit(1)
}

console.log(`Static presentation matches ${Object.keys(files).length} public file(s) across ${Object.keys(routes).length} route(s).`)
