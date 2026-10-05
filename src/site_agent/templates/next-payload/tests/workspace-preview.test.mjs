import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { workspacePreviewPath } from '../src/lib/workspace-preview-path.ts'

test('configured preview mounts resolve every public page without a second renderer', () => {
  for (const mount of ['/atelier-harmonie-preview', '/oceanicvibes-preview', '/new-business-preview']) {
    assert.equal(workspacePreviewPath(mount, mount), '/')
    assert.equal(workspacePreviewPath(`${mount}/`, mount), '/')
    assert.equal(workspacePreviewPath(`${mount}/blog`, mount), '/blog')
    assert.equal(workspacePreviewPath(`${mount}/blog/article`, mount), '/blog/article')
    assert.equal(workspacePreviewPath(`${mount}/category/lampes%20a%20poser`, mount), '/category/lampes%20a%20poser')
    assert.equal(workspacePreviewPath(`${mount}-other/blog`, mount), undefined)
    assert.equal(workspacePreviewPath('/helloada-preview/signed-token', mount), undefined)
    assert.equal(workspacePreviewPath('/admin', mount), undefined)
    for (const restricted of ['api/helloada', 'admin', '_next/static/file.js', 'helloada-preview/token']) {
      assert.equal(workspacePreviewPath(`${mount}/${restricted}`, mount), undefined)
    }
  }
  assert.throws(() => workspacePreviewPath('/', '/'), /explicit absolute mount/)
})

test('preview routing preserves query, locale cookies and the approved renderer', () => {
  const source = readFileSync('src/middleware.ts', 'utf8')
  assert.match(source, /helloAdaSite\.routes\.preview/)
  assert.match(source, /request\.nextUrl\.clone\(\)/)
  assert.match(source, /NextResponse\.rewrite\(destination\)/)
  assert.match(source, /X-Robots-Tag/)
  assert.doesNotMatch(source, /fetch\(|getPayload|draft:\s*true|redirect\(/)
})
