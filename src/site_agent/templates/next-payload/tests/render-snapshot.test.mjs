import assert from 'node:assert/strict'
import test from 'node:test'
import { captureRenderSnapshot } from '../src/lib/render-snapshot.ts'

const options = {
  tenant: 'alpha', sourceSha: 'a'.repeat(40), schemaIdentity: 'b'.repeat(64),
  locales: ['en'], defaultLocale: 'en',
  collections: { pages: ['title', 'slug', 'published', 'sections'], media: ['filename', 'url', 'mimeType'] },
  globals: { navigation: ['items'], siteSettings: ['siteName'] },
}

const fixture = () => ({
  async find({ collection, page }) {
    if (collection === 'media') return { docs: [], totalDocs: 0, totalPages: 1, hasNextPage: false }
    assert.equal(collection, 'pages')
    return { docs: Array.from({ length: page === 1 ? 100 : 1 }, (_, i) => ({
      id: (page - 1) * 100 + i + 1, title: `Page ${i}`, slug: `p-${(page - 1) * 100 + i}`,
      published: true, sections: [], secret: 'must-not-export',
    })), totalPages: 2, totalDocs: 101, hasNextPage: page === 1 }
  },
  async findGlobal({ slug }) { return slug === 'navigation' ? { items: [] } : { siteName: 'Alpha', secret: 'must-not-export' } },
  async findByID() { throw new Error('unexpected media lookup') },
})

test('snapshot pages all website content, freezes both passes, excludes undeclared data', async () => {
  const result = await captureRenderSnapshot(fixture(), options)
  assert.equal(result.snapshot.documents.en.pages.length, 101)
  assert.match(result.hash, /^sha256:[0-9a-f]{64}$/)
  assert.equal(JSON.stringify(result).includes('must-not-export'), false)
  assert.deepEqual(result.snapshot.media, [])
})

test('changed source data between passes fails rather than producing a mixed snapshot', async () => {
  const payload = fixture()
  let calls = 0
  payload.findGlobal = async ({ slug }) => ({ siteName: `${slug}-${calls++}` })
  await assert.rejects(captureRenderSnapshot(payload, options), /changed during snapshot capture/)
})

test('only the explicit website collection and global scopes can be exported', async () => {
  for (const key of ['users', 'messages', 'calendarEvents', 'ownerHandoffGrants']) {
    await assert.rejects(captureRenderSnapshot(fixture(), { ...options, collections: { [key]: ['id'] } }), /website scope/)
  }
  await assert.rejects(captureRenderSnapshot(fixture(), { ...options, globals: { messageMailbox: ['token'] } }), /website scope/)
})

test('incomplete pagination and missing identity are explicit failures', async () => {
  await assert.rejects(captureRenderSnapshot({ ...fixture(), find: async () => ({ docs: [], totalDocs: 101, totalPages: 2, hasNextPage: false }) }, options), /pagination/)
  await assert.rejects(captureRenderSnapshot(fixture(), { ...options, sourceSha: '' }), /identity/)
})

test('localized referenced media excludes private metadata and preserves localized alt text', async () => {
  const payload = fixture()
  payload.find = async ({ locale }) => ({
    docs: [{ id: 1, title: 'Home', sections: [{ image: {
      id: 7, filename: 'hero.png', mimeType: 'image/png', filesize: 42,
      url: '/api/media/file/hero.png', alt: locale === 'en' ? 'Ocean' : 'Océan',
      uploadedBy: { email: 'private@example.test' },
    } }] }], totalDocs: 1, totalPages: 1, hasNextPage: false,
  })
  const result = await captureRenderSnapshot(payload, { ...options, locales: ['en', 'fr'] })
  assert.equal(result.snapshot.media.length, 1)
  assert.equal(result.snapshot.media[0].alt, undefined)
  assert.equal(result.snapshot.documents.fr.pages[0].sections[0].image.alt, 'Océan')
  assert.equal(JSON.stringify(result).includes('private@example.test'), false)
})

test('conflicting media binary identities fail within a single capture', async () => {
  const payload = fixture()
  payload.find = async ({ locale }) => ({
    docs: [{ id: 1, sections: [{ image: {
      id: 7, filename: locale === 'en' ? 'before.png' : 'after.png', mimeType: 'image/png',
    } }] }], totalDocs: 1, totalPages: 1, hasNextPage: false,
  })
  await assert.rejects(captureRenderSnapshot(payload, { ...options, locales: ['en', 'fr'] }), /Conflicting media/)
})
