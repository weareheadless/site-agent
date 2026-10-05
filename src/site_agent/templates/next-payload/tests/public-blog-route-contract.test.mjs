import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = path.resolve(fileURLToPath(new URL('../', import.meta.url)))
const read = relative => readFileSync(path.join(root, relative), 'utf8')

test('new sites use one canonical /blog route family through the shared resolver', () => {
  const config = read('src/helloada.config.ts')
  const routes = read('src/lib/content-routes.ts')
  const route = read('src/app/(frontend)/[[...slug]]/page.tsx')
  assert.match(config, /postsIndex:\s*'\/blog'/)
  assert.match(config, /postDetail:\s*'\/blog'/)
  assert.match(routes, /createHelloAdaPublicRouteResolver/)
  assert.match(route, /postSlugForPath/)
  assert.match(route, /pathForDocument\(collection/)
  assert.equal(existsSync(path.join(root, 'src/app/(frontend)/post/[slug]/page.tsx')), false)
  assert.equal(existsSync(path.join(root, 'src/app/(frontend)/articles/[slug]/page.tsx')), false)
  assert.equal(existsSync(path.join(root, 'src/app/(frontend)/articles.html/page.tsx')), false)
})
