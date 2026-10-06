import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const ROOT = path.resolve(fileURLToPath(new URL('../../../../..', import.meta.url)))
const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')
const sourceTree = (relativePath) => {
  const root = new URL(`../${relativePath}`, import.meta.url)
  const collect = (directory) => readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(directory, entry.name)
    return entry.isDirectory() ? collect(fullPath) : /\.(?:ts|tsx|js|mjs)$/.test(entry.name) ? readFileSync(fullPath, 'utf8') : []
  })
  return collect(fileURLToPath(root)).join('\n')
}
const manifest = JSON.parse(read('template-manifest.json'))
const contract = JSON.parse(read('helloada-content-contract.json'))
const packageJson = JSON.parse(read('package.json'))
const lock = JSON.parse(read('package-lock.json'))

test('template pins the exact shared schema and admin releases it advertises', () => {
  assert.equal(contract.contract, manifest.contentContract)
  assert.equal(contract.coreVersion, manifest.payloadCore)
  assert.equal(contract.schemaRevision, manifest.schemaRevision)
  assert.match(packageJson.dependencies['@weareheadless/helloada-payload-admin'], new RegExp(`payload-admin-v${manifest.payloadAdmin}`))
  assert.match(packageJson.dependencies['@weareheadless/helloada-payload-core'], new RegExp(`helloada-payload-core-v${manifest.payloadCore}`))
  assert.equal(lock.packages[''].dependencies['@weareheadless/helloada-payload-admin'], packageJson.dependencies['@weareheadless/helloada-payload-admin'])
  assert.equal(lock.packages[''].dependencies['@weareheadless/helloada-payload-core'], packageJson.dependencies['@weareheadless/helloada-payload-core'])
  for (const [name, version] of [
    ['@weareheadless/helloada-payload-admin', manifest.payloadAdmin],
    ['@weareheadless/helloada-payload-core', manifest.payloadCore],
  ]) {
    const entry = lock.packages[`node_modules/${name}`]
    assert.equal(entry.version, version)
    assert.match(entry.integrity, /^sha512-[A-Za-z0-9+/]+={0,2}$/)
  }
  const runtime = JSON.parse(read('wrangler.jsonc')).vars
  assert.equal(runtime.HELLOADA_TEMPLATE_SCHEMA, String(manifest.templateSchema))
  assert.equal(runtime.HELLOADA_PAYLOAD_ADMIN_VERSION, manifest.payloadAdmin)
  assert.equal(runtime.HELLOADA_PAYLOAD_CORE_VERSION, manifest.payloadCore)
  assert.equal(runtime.HELLOADA_PAYLOAD_SCHEMA_REVISION, String(manifest.schemaRevision))
  assert.equal(runtime.HELLOADA_CONTENT_CONTRACT_VERSION, manifest.contentContract)
  assert.equal(runtime.HELLOADA_SCHEMA_IDENTITY, manifest.schemaIdentity)
  assert.equal(runtime.HELLOADA_PAYLOAD_MIGRATION_HEAD, manifest.migrationHead)
})

test('public page and article routes read Payload and render Payload SEO metadata', () => {
  const page = read('src/app/(frontend)/[[...slug]]/page.tsx')
  const article = read('src/app/(frontend)/[[...slug]]/page.tsx')
  const content = read('src/lib/content.ts')
  const listing = read('src/components/site/presentation/BlogListingPresentation.tsx')
  const routes = read('src/lib/content-routes.ts')
  const chrome = read('src/components/SiteChrome.tsx')
  for (const source of [page, article]) assert.match(source, /force-dynamic/)
  assert.match(page, /getPageBySlug/)
  assert.match(page, /getProductBySlug/)
  assert.match(page, /same public route to both a page and a product/)
  assert.match(content, /readHelloAdaProduct/)
  assert.match(page, /seoFor\(/)
  assert.match(article, /getPostBySlug/)
  assert.match(article, /seoFor\(/)
  assert.match(listing, /helloAdaBindingId\('posts'/)
  assert.match(routes, /helloAdaPublicContentRoutes/)
  assert.match(page, /postSlugForPath/)
  assert.match(chrome, /getNavigation/)
  assert.match(chrome, /getSiteSettings/)
})

test('Growth review renders an owner-bound exact Payload revision through Next, then checks live public routes', () => {
  const bridge = read('src/app/api/helloada/[...path]/route.ts')
  const preview = read('src/app/(frontend)/helloada-preview/[token]/page.tsx')
  const presentation = read('src/components/site/presentation/PagePresentation.tsx')
  const claims = read('src/lib/helloada-preview.ts')
  const chrome = read('src/components/SiteChrome.tsx')
  assert.doesNotMatch(bridge, /react-dom\/server|renderToStaticMarkup/)
  assert.match(bridge, /createHelloAdaPreviewToken/)
  assert.match(bridge, /fetch\(previewUrl/)
  assert.match(bridge, /cache: 'no-store'/)
  assert.match(bridge, /verifyLiveRoutes\(request, collection, published, verified\.route\)/)
  assert.match(bridge, /data-helloada-updated-at=/)
  assert.match(preview, /verifyHelloAdaPreviewToken/)
  assert.match(preview, /claims\.ownerId/)
  assert.match(preview, /claims\.documentHash/)
  assert.match(preview, /claims\.globals\.map/)
  assert.match(preview, /hashJson\(withoutPayloadMetadata\(global\)\) !== claim\.hash/)
  assert.match(preview, /locale: claims\.locale/)
  assert.match(claims, /globals: Array<\{ slug: 'siteSettings' \| 'navigation'; hash: string \}>/)
  assert.match(claims, /claims\.globals\.length === 2/)
  assert.match(chrome, /navigation: candidateNavigation/)
  assert.match(preview, /expectedPublicRoute\(claims\.collection, document\) !== claims\.route/)
  assert.match(presentation, /data-helloada-document-id/)
  assert.match(presentation, /data-helloada-updated-at/)
})

test('the default contract includes editable articles, SEO, media, navigation and footer data', () => {
  assert.ok(contract.collections.pages.includes('seo'))
  assert.ok(contract.collections.posts.includes('featuredImage'))
  assert.ok(contract.collections.posts.includes('seo'))
  assert.ok(contract.collections.media.includes('alt'))
  assert.ok(contract.globals.navigation.includes('footer'))
  assert.ok(contract.globals.siteSettings.includes('defaultSeoDescription'))
  assert.ok(contract.contentBlocks.includes('helloAdaImage'))
})

test('the canonical public runtime reads article content through Payload only', () => {
  const source = sourceTree('src').toLowerCase()
  assert.doesNotMatch(source, /articles\/index\.json|\.mdx?['"`]/)
})

test('a clean scaffold inherits Payload-bound pages, posts, settings, navigation and footer rendering', () => {
  const route = read('src/app/(frontend)/[[...slug]]/page.tsx')
  const chrome = read('src/components/site/TenantChrome.tsx')
  const siteChrome = read('src/components/SiteChrome.tsx')
  const presentation = read('src/components/site/presentation/PagePresentation.tsx')
  const listing = read('src/components/site/presentation/BlogListingPresentation.tsx')
  const scaffold = readFileSync(path.join(ROOT, 'src/site_agent/site_scaffold.py'), 'utf8')
  assert.match(scaffold, /"templates" \/ "next-payload"/)
  assert.match(route, /getPageBySlug/)
  assert.match(route, /getProductBySlug/)
  assert.match(route, /getPostBySlug/)
  assert.match(presentation, /helloAdaBindingId\(collection, documentId/)
  assert.match(presentation, /TenantSections/)
  assert.match(listing, /helloAdaBindingId\('posts'/)
  assert.match(chrome, /helloAdaGlobalBindingId\(global/)
  assert.match(chrome, /helloAdaGlobalBindingId\('siteSettings'/)
  assert.match(chrome, /footer/)
  assert.match(siteChrome, /getNavigation/)
  assert.match(siteChrome, /getSiteSettings/)
})

test('release verification rejects tenants whose shared Payload content cannot render', () => {
  const verifier = read('scripts/verify-payload-contract.ts')
  assert.match(verifier, /siteSettings publishable name/)
  assert.match(verifier, /navigation has shared header and footer links/)
  assert.match(verifier, /published home page is complete enough to render/)
  assert.match(verifier, /seo\.title/)
  assert.match(verifier, /seo\.description/)
  assert.match(verifier, /home\.summary/)
  assert.match(verifier, /home\.sections/)
})
