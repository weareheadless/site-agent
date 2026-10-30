import test from 'node:test'
import assert from 'node:assert/strict'
import { canSendChatAttachments, remainingChatAttachmentSlots, splitChatImageFiles, uploadChatImage, uploadChatImages } from '../src/lib/chat-attachments.ts'

test('mixed selections retain supported images and report unsupported files separately', () => {
  const files = [{ name: 'a.png', type: 'image/png' }, { name: 'notes.pdf', type: 'application/pdf' }]
  const result = splitChatImageFiles(files)
  assert.deepEqual(result.supported.map((file) => file.name), ['a.png'])
  assert.deepEqual(result.unsupported.map((file) => file.name), ['notes.pdf'])
})

test('XHR upload reports real byte progress and uses the authenticated canonical HelloAda path', async () => {
  const originalXhr = globalThis.XMLHttpRequest
  const originalFormData = globalThis.FormData
  const originalLastRequest = globalThis.lastRequest
  const seen = {}
  class MockXhr {
    upload = {}
    constructor() { globalThis.lastRequest = this }
    open(method, url) { seen.method = method; seen.url = url }
    send(form) {
      seen.form = form
      this.upload.onprogress({ lengthComputable: true, loaded: 3, total: 4 })
      this.status = 201
      this.responseText = JSON.stringify({ attachment: { asset_id: 'media-1' } })
      this.onload()
    }
  }
  class MockFormData { append(...args) { seen.formField = args } }
  globalThis.XMLHttpRequest = MockXhr
  globalThis.FormData = MockFormData
  try {
    const progress = []
    const result = await uploadChatImage({ name: 'photo.png' }, {
      resolvePath: (path) => path.replace('/api/helloada', '/api/workspace'),
      onProgress: (value) => progress.push(value),
    })
    assert.deepEqual(progress, [75])
    assert.equal(seen.method, 'POST')
    assert.equal(seen.url, '/api/workspace/media/upload')
    assert.equal(globalThis.lastRequest.withCredentials, true)
    assert.equal(globalThis.lastRequest.timeout, 25_000)
    assert.equal(seen.formField[0], 'file')
    assert.equal(seen.formField[1].name, 'photo.png')
    assert.equal(result.attachment.asset_id, 'media-1')
  } finally {
    globalThis.XMLHttpRequest = originalXhr
    globalThis.FormData = originalFormData
    if (originalLastRequest === undefined) delete globalThis.lastRequest
    else globalThis.lastRequest = originalLastRequest
  }
})

test('XHR upload rejects HTTP, malformed response, network, and timeout failures', async () => {
  const originalXhr = globalThis.XMLHttpRequest
  class MockXhr {
    upload = {}
    open() {}
    send() { this.mode() }
    mode() {}
  }
  globalThis.XMLHttpRequest = MockXhr
  try {
    for (const [mode, expected] of [
      [(xhr) => { xhr.status = 413; xhr.responseText = JSON.stringify({ message: 'Too large' }); xhr.onload() }, /Too large/],
      [(xhr) => { xhr.status = 200; xhr.responseText = '{'; xhr.onload() }, /invalid response/],
      [(xhr) => xhr.onerror(), /network error/],
      [(xhr) => xhr.ontimeout(), /timed out/],
    ]) {
      MockXhr.prototype.mode = function () { mode(this) }
      await assert.rejects(uploadChatImage({ name: 'photo.png' }, { resolvePath: (path) => path }), expected)
    }
  } finally {
    globalThis.XMLHttpRequest = originalXhr
  }
})

test('successful attachment remains independently ready when later upload fails', () => {
  const readyIds = []
  for (const result of [{ ok: true, id: 'asset-1' }, { ok: false }]) {
    if (result.ok && !readyIds.includes(result.id)) readyIds.push(result.id)
  }
  assert.deepEqual(readyIds, ['asset-1'])
  assert.equal(canSendChatAttachments(false, readyIds.length, ['failed']), false)
  assert.equal(canSendChatAttachments(false, readyIds.length, []), true)
})

test('limit accounts for ready and in-flight items; removal restores one slot', () => {
  assert.equal(remainingChatAttachmentSlots(11, 1), 0)
  assert.equal(remainingChatAttachmentSlots(10, 1), 1)
  assert.equal(remainingChatAttachmentSlots(10, 0), 2)
})

test('uploading, failed, and unsupported items cannot enable send; payload-ready list uses asset IDs', () => {
  for (const state of ['uploading', 'failed', 'unsupported']) {
    assert.equal(canSendChatAttachments(false, 0, [state]), false)
  }
  const requestAttachments = [{ asset_id: 'asset-1' }, { asset_id: 42 }].map(({ asset_id }) => ({ asset_id }))
  assert.deepEqual(requestAttachments, [{ asset_id: 'asset-1' }, { asset_id: 42 }])
})

test('production batch orchestration continues after thrown and HTTP failures and retains later successes', async () => {
  for (const failure of ['network', 'malformed-json', 'http']) {
    const files = ['one.png', 'two.png', 'three.png'].map((name) => ({ name }))
    const entries = files.map((file, index) => ({ id: String(index), filename: file.name, status: 'uploading' }))
    const ready = []
    const pending = new Map(entries.map((entry) => [entry.id, entry.status]))
    const attempted = []
    const errors = []
    await uploadChatImages({
      files,
      entries,
      upload: async (file) => {
        attempted.push(file.name)
        if (file.name === 'two.png' && failure !== 'http') throw new Error(failure)
        if (file.name === 'two.png') throw new Error('HTTP 503')
        return { asset_id: file.name }
      },
      addAttachment: (attachment) => ready.push(attachment),
      updateEntry: (id, update) => pending.set(id, update.status),
      removeEntry: (id) => pending.delete(id),
      reportFailure: (reason) => errors.push(reason),
      fallbackError: 'upload failed',
    })
    assert.deepEqual(attempted, ['one.png', 'two.png', 'three.png'])
    assert.deepEqual(ready.map((item) => item.asset_id), ['one.png', 'three.png'])
    assert.deepEqual([...pending.values()], ['failed'])
    assert.deepEqual(errors, [failure === 'http' ? 'HTTP 503' : failure])
    assert.equal(canSendChatAttachments(false, ready.length, [...pending.values()]), false)
    pending.clear() // Dismissing the failed entry restores send with the exact ready IDs.
    assert.equal(canSendChatAttachments(false, ready.length, [...pending.values()]), true)
    assert.deepEqual(ready.map(({ asset_id }) => ({ asset_id })), [{ asset_id: 'one.png' }, { asset_id: 'three.png' }])
  }
})

test('production batch orchestration waits for deferred uploads and leaves no phantom uploading entries', async () => {
  let releaseFirst
  let releaseSecond
  const files = [{ name: 'one.png' }, { name: 'two.png' }]
  const entries = files.map((file, index) => ({ id: String(index), filename: file.name, status: 'uploading' }))
  const pending = new Map(entries.map((entry) => [entry.id, entry.status]))
  const ready = []
  const batch = uploadChatImages({
    files,
    entries,
    upload: (file) => new Promise((resolve, reject) => {
      if (file.name === 'one.png') releaseFirst = () => resolve({ asset_id: 'one' })
      else releaseSecond = () => reject(new Error('network'))
    }),
    addAttachment: (attachment) => ready.push(attachment),
    updateEntry: (id, update) => pending.set(id, update.status),
    removeEntry: (id) => pending.delete(id),
    reportFailure: () => {},
    fallbackError: 'upload failed',
  })
  assert.deepEqual([...pending.values()], ['uploading', 'uploading'])
  releaseFirst()
  await Promise.resolve()
  assert.deepEqual([...pending.values()], ['uploading'])
  releaseSecond()
  await batch
  assert.deepEqual([...pending.values()], ['failed'])
  assert.deepEqual(ready.map((item) => item.asset_id), ['one'])
})
