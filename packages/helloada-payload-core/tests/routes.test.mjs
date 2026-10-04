import assert from 'node:assert/strict'
import test from 'node:test'

import { createHelloAdaPublicRouteResolver } from '../src/routes.ts'

test('tenant route declarations generate stable article index, details and document paths', () => {
  const routes = createHelloAdaPublicRouteResolver({ postsIndex: '/journal/', postDetail: '/journal' })
  assert.deepEqual(routes.routes, { postsIndex: '/journal', postDetail: '/journal' })
  assert.equal(routes.pathForPost('a post'), '/journal/a%20post')
  assert.equal(routes.pathForDocument('pages', 'home'), '/')
  assert.equal(routes.pathForDocument('pages', 'about/team'), '/about/team')
  assert.equal(routes.pathForDocument('products', 'light'), '/light')
  assert.deepEqual(routes.postSlugForPath('/journal'), { kind: 'index' })
  assert.deepEqual(routes.postSlugForPath('/journal/a%20post'), { kind: 'detail', slug: 'a post' })
  assert.equal(routes.postSlugForPath('/other'), undefined)
})

test('public routes reject ambiguous base paths, unsupported collections and unsafe slugs', () => {
  assert.throws(() => createHelloAdaPublicRouteResolver({ postsIndex: '/', postDetail: '/journal' }), /non-root path/)
  assert.throws(() => createHelloAdaPublicRouteResolver({ postsIndex: '//journal', postDetail: '/journal' }), /absolute site path/)
  const routes = createHelloAdaPublicRouteResolver({ postsIndex: '/journal', postDetail: '/journal' })
  assert.throws(() => routes.pathForPost('../private'), /safe, non-empty route slug/)
  assert.throws(() => routes.pathForDocument('media', 'file'), /Unsupported HelloAda public document collection/)
})
