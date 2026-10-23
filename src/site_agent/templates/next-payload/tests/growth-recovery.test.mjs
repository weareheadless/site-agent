import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'

test('uncertain Growth effects reconcile exact state without repeating writes', async () => {
  const source = readFileSync(new URL('../src/lib/growth-operations.ts', import.meta.url), 'utf8')
    .replace(/^import\s+[\s\S]*?from\s+['"][^'"]+['"]\s*\n/gm, '')
  // Run the real operation handlers; replace only their external adapters.
  const adapters = `
    import assert from 'node:assert/strict'
    const config = {}
    const helloAdaSite = { defaultLocale: 'en', features: { posts: true } }
    const tenantId = () => 'tenant-a'
    const asObject = (x) => x && typeof x === 'object' ? x : {}
    let hashJson = async (x) => JSON.stringify(x)
    const stableJson = (x) => JSON.stringify(x)
    const projectDocument = (doc, fields) => Object.fromEntries(fields.map(key => [key, doc[key] ?? null]))
    const withoutPayloadMetadata = (x) => { const result = {...x}; for (const key of ['id','updatedAt','createdAt','_status']) delete result[key]; return result }
    const createHelloAdaPreviewToken = async () => 'exact-token'
    const articleIndexPath = () => '/blog'
    const pathForDocument = () => '/'
    const contractCapabilities = []
    const helloAdaRuntime = () => ({token:'test'})
    const createLocalReq = async () => ({})
    const operationContext = () => {}
    const NextResponse = { json: (body, options = {}) => Response.json(body, {status:options.status || 200}) }
    let writes = 0, reconciliations = 0, saves = 0, claims = 0, previewRevision = 'candidate'
    let live = {id:'1', title:'Before', updatedAt:'base', route:'/'}
    let draft = {id:'1', title:'After', updatedAt:'candidate'}
    const payload = {
      config: {collections:[{slug:'pages',fields:[{name:'title'}]}]},
      findByID: async (options) => {
        assert.equal(options.depth, undefined, 'Candidate reads must match the canonical authoring query')
        return options.draft ? draft : live
      },
      findGlobal: async () => ({}),
      update: async () => { writes++; throw new Error('Reconciliation must never repeat a write') },
    }
    const getPayload = async () => payload
    const packageData = {tenant:'tenant-a',initiativeId:'1',collection:'pages',documentId:'1',fields:['title'],
      before:{title:'Before'}, after:{title:'After'}, changes:{title:'After'},
      baseHash:JSON.stringify({title:'Before'}),candidateHash:JSON.stringify({title:'After'}),route:'/'}
    const packageHash = JSON.stringify(packageData)
    const candidateRow = async () => ({state:'validated',package_json:JSON.stringify(packageData)})
    const operationByKey = async () => undefined
    const operationResult = () => ({ok:false,error:'previous timeout'})
    const claimOperation = async () => { claims++; return {inserted:false,row:{state:'uncertain'}} }
    const completeOperation = async () => {throw new Error('Use reconciliation, not first-write completion')}
    const reconcileOperation = async () => {reconciliations++}
    const saveCandidate = async () => {saves++}
    const failOperation = async () => {throw new Error('Do not rewrite another executor receipt')}
    const fetch = async (url) => new Response(String(url).includes('helloada-preview')
      ? '<main data-helloada-preview-hash="' + await hashJson(withoutPayloadMetadata(draft)) + '" data-helloada-preview-route="/" class="approved-custom-article" data-helloada-document-id="1" data-helloada-updated-at="' + previewRevision + '">'
      : '<main data-helloada-document-id="1" data-helloada-updated-at="' + live.updatedAt + '">',
      {headers:{'content-type':'text/html'}})
    const request = (publish = false) => new Request('https://tenant.example/api/workspace/growth',
      {method:'POST',body:JSON.stringify(publish ? {packageHash} : {packageHash,package:packageData})})
    const principal = {kind:'service',token:'test'}
  `
  const checks = `
    let response = await growthPost(request(), '/growth/apply', principal)
    assert.equal(response.status, 200)
    assert.equal((await response.json()).ok, true)
    assert.equal(reconciliations, 1)
    assert.equal(saves, 1)
    assert.equal(writes, 0)
    previewRevision = 'wrong-revision'
    response = await growthPost(request(), '/growth/apply', principal)
    assert.equal(response.status, 409)
    assert.match((await response.json()).message, /approved document and route markers/)
    assert.equal(reconciliations, 1)
    assert.equal(writes, 0)
    previewRevision = 'candidate'
    draft = {...draft,title:'Owner changed this'}
    response = await growthPost(request(), '/growth/apply', principal)
    assert.equal(response.status, 409)
    assert.equal(reconciliations, 1)
    draft = {...draft,title:'After'}
    response = await growthPost(request(true), '/growth/publish', principal)
    assert.equal(response.status, 409)
    live = {...live,title:'After',updatedAt:'published'}
    response = await growthPost(request(true), '/growth/publish', principal)
    assert.equal(response.status, 200)
    assert.equal((await response.json()).status, 'published')
    assert.equal(reconciliations, 2)
    const publicationRequest = (expectedRevision) => new Request('https://tenant.example/api/workspace/growth', {
      method:'POST', body:JSON.stringify({collection:'pages',documentId:'1',expectedRevision,locale:'en'})})
    const savedHash = hashJson
    hashJson = async (document) => document.title === 'After' ? 'sha256:' + 'a'.repeat(64) : 'sha256:' + 'b'.repeat(64)
    response = await growthPost(publicationRequest('sha256:' + 'a'.repeat(64)), '/growth/verify-publication', principal)
    assert.equal(response.status, 200)
    assert.equal((await response.json()).liveVerification.status, 'passed')
    response = await growthPost(publicationRequest('sha256:' + 'b'.repeat(64)), '/growth/verify-publication', principal)
    assert.equal(response.status, 409)
    assert.equal(writes, 0)
    hashJson = savedHash
    const previousClaims = claims
    const savedLive = live
    live = {...live,title:'A newer owner revision'}
    response = await growthPost(request(), '/growth/apply', principal)
    assert.equal(response.status, 409)
    assert.match((await response.json()).message, /fields: title/)
    assert.equal(claims, previousClaims, 'Rejected preflight must not claim a write or lock the document')
    live = savedLive
    packageData.tenant = 'another-tenant'
    response = await growthPost(request(), '/growth/apply', principal)
    assert.equal(response.status, 409)
    assert.equal(reconciliations, 2)
    assert.equal(writes, 0)
  `
  const javascript = stripTypeScriptTypes(adapters + source + checks)
  await assert.doesNotReject(import('data:text/javascript;base64,' + Buffer.from(javascript).toString('base64')))
})
