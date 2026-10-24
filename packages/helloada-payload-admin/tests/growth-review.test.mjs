import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

function load(url) {
  const source = readFileSync(url, 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const sandbox = { exports: {}, require: name => load(new URL(`${name}.ts`, url)) }
  vm.runInNewContext(compiled, sandbox, { filename: url.pathname })
  return sandbox.exports
}

const reviewApi = load(new URL('../src/lib/growth-review.ts', import.meta.url))

test('recursive comparison omits unchanged SEO siblings and the unchanged article body', () => {
  const body = { root: { children: [{ type: 'paragraph', children: [{ type: 'text', text: 'Same article.' }] }] } }
  const changes = reviewApi.getReviewChanges({
    before: { seo: { image: { url: '/same.jpg', alt: 'Dive school', width: 640 }, metaDescription: 'Short' }, body },
    after: { seo: { image: { url: '/same.jpg', alt: 'Dive school', width: 640 }, metaDescription: 'More complete search description' }, body },
  })
  assert.equal(JSON.stringify(changes.map(change => change.path)), JSON.stringify(['seo.metaDescription']))
  assert.equal(changes[0].label, 'Search description')
})

test('leaf comparison records null, removed keys, and added values faithfully', () => {
  const changes = reviewApi.getReviewChanges({
    before: { description: 'Old', seo: { title: 'Existing' }, note: 'Keep' },
    after: { description: null, seo: {}, note: 'Keep', extra: false },
  })
  assert.equal(JSON.stringify(changes.map(({ path, kind, before, after }) => ({ path, kind, before, after }))), JSON.stringify([
    { path: 'description', kind: 'changed', before: 'Old', after: null },
    { path: 'extra', kind: 'added', before: undefined, after: false },
    { path: 'seo.title', kind: 'removed', before: 'Existing', after: undefined },
  ]))
})

test('arrays and rich text preserve changed leaves without repeating unchanged siblings', () => {
  const before = { sources: ['first', 'second'], body: { root: { children: [{ type: 'paragraph', children: [{ type: 'text', text: 'Same.' }] }] } } }
  const after = { sources: ['first', 'updated'], body: { root: { children: [{ type: 'paragraph', children: [{ type: 'text', text: 'Same.' }] }] } } }
  const changes = reviewApi.getReviewChanges({ before, after })
  assert.equal(JSON.stringify(changes.map(change => change.path)), JSON.stringify(['sources[1]']))
  assert.equal(changes[0].before, 'second')
  assert.equal(changes[0].after, 'updated')
  const bodyChange = reviewApi.getReviewChanges({ before: { body: before.body }, after: { body: { root: { children: [{ type: 'paragraph', children: [{ type: 'text', text: 'Changed.' }] }] } } } })
  assert.equal(bodyChange[0].path, 'body.root.children[0].children[0].text')
  assert.equal(bodyChange[0].before, 'Same.')
  assert.equal(bodyChange[0].after, 'Changed.')
})

test('target uses exact document slug or explicit route and never invents a collection route', () => {
  const { getReviewTarget } = reviewApi
  assert.equal(JSON.stringify(getReviewTarget({ before: { title: 'Article', slug: 'freedive-plateaus' }, after: { title: 'Article', slug: 'freedive-plateaus' } })), JSON.stringify({
    title: 'Article', path: 'freedive-plateaus',
  }))
  assert.equal(JSON.stringify(getReviewTarget({ route: '/about' })), JSON.stringify({ title: '/about', path: '/about' }))
  assert.equal(getReviewTarget({ before: { title: 'No path' }, after: { title: 'No path' } }).path, null)
  assert.equal(getReviewTarget({}), null)
})

test('unknown proposal keeps its authentic task title and all changed values', () => {
  const { getDecisionPresentation, getReviewChanges } = reviewApi
  const proposal = { before: { customField: { opaque: 'old' } }, after: { customField: { opaque: 'new', extra: [1, 2] } } }
  const view = getDecisionPresentation({ title: 'Rework the carefully researched page section', review: proposal }, key => key)
  assert.equal(view.heading, 'Rework the carefully researched page section')
  assert.equal(view.purpose, null)
  assert.equal(JSON.stringify(getReviewChanges(proposal).map(({ path, kind }) => ({ path, kind }))), JSON.stringify([
    { path: 'customField.extra', kind: 'added' }, { path: 'customField.opaque', kind: 'changed' },
  ]))
})

test('legacy change maps remain visible when before and after snapshots are absent', () => {
  const changes = reviewApi.getReviewChanges({ changes: { 'seo.metaDescription': null } })
  assert.equal(JSON.stringify(changes.map(({ path, label, after }) => ({ path, label, after }))), JSON.stringify([
    { path: 'seo.metaDescription', label: 'Search description', after: null },
  ]))
})

test('decision presentation requests localized copy with the canonical growth namespace', () => {
  const { getDecisionPresentation } = reviewApi
  const seen = []
  const presentation = getDecisionPresentation({ title: 'Original task', review: {
    before: { seo: { metaDescription: 'Old' } }, after: { seo: { metaDescription: 'New' } },
  } }, key => (seen.push(key), key))
  assert.equal(presentation.heading, 'growth.clarityHeadingSearchDescription')
  assert.equal(presentation.purpose, 'growth.clarityPurposeSearchDescription')
  assert.equal(seen.every(key => key.startsWith('growth.')), true)
})

test('rich text changes are reported as one readable field, not Lexical metadata', () => {
  const before = { root: { type: 'root', version: 1, children: [{ type: 'paragraph', children: [{ type: 'text', text: 'Old body' }] }] } }
  const after = { root: { type: 'root', version: 1, children: [{ type: 'paragraph', children: [{ type: 'text', text: 'New body' }] }] } }
  const [change] = reviewApi.getReviewChanges({ before: { body: before }, after: { body: after } })
  assert.equal(change.path, 'body')
  assert.equal(change.labelKey, 'growth.clarityFieldArticleText')
  assert.equal(change.before, before)
  assert.equal(change.after, after)
})

test('historical exact text operations remain reviewable', () => {
  const [change] = reviewApi.getReviewChanges({ changeOperations: [{ path: 'seo.metaDescription', find: 'Before', replace: 'After' }] })
  assert.equal(change.path, 'seo.metaDescription')
  assert.equal(change.before, 'Before')
  assert.equal(change.after, 'After')
  assert.equal(change.labelKey, 'growth.clarityFieldSearchDescription')
})

test('rich text review exposes destination-only and formatting-only changes as inert text', () => {
  const link = (url, format = 0) => ({ root: { type: 'root', children: [{ type: 'paragraph', children: [
    { type: 'link', fields: { url }, children: [{ type: 'text', text: 'Read more', format }] },
  ] }] } })
  const before = reviewApi.formatRichTextReview(link('/about'))
  const after = reviewApi.formatRichTextReview(link('javascript:alert(1)', 1))
  assert.match(before, /Read more \(link destination: \/about\)/)
  assert.match(after, /\*\*Read more\*\* \(link destination: javascript:alert\(1\)\)/)
  assert.doesNotMatch(after, /<a\b/i)
})

test('unknown rich text nodes remain inspectable in exact structured details', () => {
  const value = { root: { type: 'root', children: [{ type: 'upload', version: 2,
    fields: { relationTo: 'media', value: { id: 81, url: '/uploads/card.jpg', alt: 'Card' } } }] } }
  assert.equal(reviewApi.isRichTextReview(value), true)
  assert.equal(reviewApi.formatRichTextReview(value), '')
  const exactDetails = JSON.stringify(value, null, 2)
  assert.match(exactDetails, /"type": "upload"/)
  assert.match(exactDetails, /"id": 81/)
  assert.match(exactDetails, /\/uploads\/card\.jpg/)
  const component = readFileSync(new URL('../src/components/GrowthChangeReview.tsx', import.meta.url), 'utf8')
  assert.match(component, /growth\.clarityRichTextDetails/)
  assert.match(component, /<pre>\{JSON\.stringify\(value, null, 2\)\}<\/pre>/)
})

test('nested proposed values receive localized field keys', () => {
  const [change] = reviewApi.getReviewChanges({ changes: { seo: { metaDescription: 'Proposed' } } })
  assert.equal(change.path, 'seo.metaDescription')
  assert.equal(change.labelKey, 'growth.clarityFieldSearchDescription')
})

test('related ready payload reviews group by changed fields while keeping target and task identities separate', () => {
  const review = path => ({ route: path,
    before: { seo: { description: 'old' }, summary: 'old summary' },
    after: { seo: { description: 'new' }, summary: 'new summary' },
  })
  const rows = [
    { id: 'draft-a', kind: 'payload_content', canApprove: true, review: review('/services/a') },
    { id: 'draft-b', kind: 'payload_content', canApprove: true, review: review('/services/b') },
    { id: 'owner-question', requirement: 'owner_information' },
    { id: 'source-candidate', kind: 'code', canApprove: true, review: review('/services/c') },
    { id: 'not-ready', kind: 'payload_content', canApprove: false, review: review('/services/d') },
  ]
  const groups = reviewApi.groupReviewDecisions(rows)
  assert.equal(groups.length, 4)
  assert.deepEqual(JSON.parse(JSON.stringify(groups[0].tasks.map(task => task.id))), ['draft-a', 'draft-b'])
  assert.equal(reviewApi.getReviewTarget(groups[0].tasks[0].review).path, '/services/a')
  assert.equal(reviewApi.getReviewTarget(groups[0].tasks[1].review).path, '/services/b')
  assert.equal(groups[1].tasks[0].id, 'owner-question')
  assert.equal(groups[2].tasks[0].id, 'source-candidate')
  assert.equal(groups[3].tasks[0].id, 'not-ready')
})
