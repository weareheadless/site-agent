import assert from 'node:assert/strict'
import { DatabaseSync } from 'node:sqlite'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { webcrypto } from 'node:crypto'

const contractSource = readFileSync(new URL('../src/lib/growth-contract.ts', import.meta.url), 'utf8')
  .replace(/^import\s+[\s\S]*?from\s+['"][^'"]+['"]\s*\n/gm, '')
  .replace(/^export\s+\{\s*hashJson,\s*stableJson\s*\}\s+from\s+['"][^'"]+['"]\s*\n/m, '')
  .replace(/^const database = async \(\) => \{[\s\S]*?\n\}\n/m, `const database = async () => { const context = await getPayloadCloudflareContext(); if (!context.env?.D1) throw new Error('missing D1'); return context.env.D1 }\n`)
const operationsSource = readFileSync(new URL('../src/lib/growth-operations.ts', import.meta.url), 'utf8')
  .replace(/^import\s+[\s\S]*?from\s+['"][^'"]+['"]\s*\n/gm, '')
const payloadHashSource = readFileSync(new URL('../src/lib/payload-hash.ts', import.meta.url), 'utf8')

test('obsolete Growth retirement proves current base, uses SQL CAS, and makes the operation terminal', async () => {
  const sqlite = new DatabaseSync(':memory:')
  sqlite.exec(`CREATE TABLE helloada_growth_operations (
    operation_key TEXT PRIMARY KEY, document_key TEXT NOT NULL, tenant_id TEXT NOT NULL,
    package_hash TEXT NOT NULL, state TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
  ); CREATE TABLE helloada_growth_candidates (
    package_hash TEXT PRIMARY KEY, state TEXT, package_json TEXT
  );`)
  const db = {
    prepare(sql) {
      let parameters = []
      return {
        bind(...values) { parameters = values; return this },
        async first() { return sqlite.prepare(sql).get(...parameters) ?? null },
        async run() { return { meta: { changes: Number(sqlite.prepare(sql).run(...parameters).changes) } } },
      }
    },
  }
  // Use canonical JSON hashing in the executable adapter, matching Payload's sorted recursive serializer.
  const harness = `
    import assert from 'node:assert/strict'
    const db = globalThis.__retirementDb
    const crypto = globalThis.crypto
    const normalize = value => value === undefined ? null : value === null || typeof value !== 'object' ? value : Array.isArray(value) ? value.map(normalize) : Object.fromEntries(Object.keys(value).sort().map(key => [key,normalize(value[key])]))
    const getPayloadCloudflareContext = async () => ({env:{D1:db}})
    const getPayload = async () => payload
    const createLocalReq = async () => ({})
    const config = {}
    const helloAdaSite = {defaultLocale:'en',features:{posts:true}}
    const helloAdaRuntime = () => ({token:'test'})
    const createHelloAdaPreviewToken = async () => 'token'
    const articleIndexPath = () => '/blog'
    const pathForDocument = () => '/'
    const NextResponse = {json:(body, options={}) => Response.json(body, {status:options.status || 200})}
    let live = {id:'doc-7',title:'Base',updatedAt:'live-v1',route:'/'}
    let draft = {id:'doc-7',title:'Base',updatedAt:'draft-v1',route:'/'}
    let writes = 0
    const payload = {config:{collections:[{slug:'pages',fields:[{name:'title'}]}]},findByID:async opts => opts.draft ? draft : live,
      findGlobal:async () => ({}),update:async options => {writes++; live={...live,...options.data,updatedAt:'published-v2'}}}
    const fetch = async url => new Response(String(url).includes('helloada-preview') ? '<main data-helloada-preview-hash="x" data-helloada-preview-route="/" data-helloada-document-id="doc-7" data-helloada-updated-at="draft-v1">' : '<main data-helloada-document-id="doc-7" data-helloada-updated-at="' + live.updatedAt + '">', {headers:{'content-type':'text/html'}})
    const request = body => new Request('https://tenant.example/api/workspace/growth/retire-obsolete',{method:'POST',body:JSON.stringify(body)})
    const owner = {kind:'owner',auth:{}}
  `
  const packageData = {tenant:'tenant-a',initiativeId:'initiative-3',collection:'pages',documentId:'doc-7',fields:['title'],
    before:{title:'Base'},after:{title:'Candidate'},changes:{title:'Candidate'},baseHash:'',candidateHash:'',route:'/'}
  const normalize = value => value === undefined ? null : value === null || typeof value !== 'object' ? value : Array.isArray(value) ? value.map(normalize) : Object.fromEntries(Object.keys(value).sort().map(key => [key,normalize(value[key])]))
  const hash = async value => 'sha256:' + Array.from(new Uint8Array(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(normalize(value))))), byte => byte.toString(16).padStart(2,'0')).join('')
  packageData.baseHash = await hash(packageData.before)
  packageData.candidateHash = await hash(packageData.after)
  const packageHash = await hash(packageData)
  const documentKey = 'pages:doc-7'
  const operationKey = `draft:tenant-a:${documentKey}:${packageHash}`
  const prior = {ok:false,packageHash,error:'old preparation timed out'}
  const priorJson = JSON.stringify(prior)
  const resultHash = await hash(prior)
  const stamp = '2026-10-23T12:00:00.000Z'
  const setRow = state => {
    sqlite.prepare('DELETE FROM helloada_growth_operations').run()
    sqlite.prepare('INSERT INTO helloada_growth_operations VALUES(?,?,?,?,?,?,?,?)').run(operationKey,documentKey,'tenant-a',packageHash,state,priorJson,stamp,stamp)
  }
  globalThis.__retirementDb = db
  globalThis.__sqlite = sqlite
  globalThis.__webcrypto = webcrypto
  process.env.HELLOADA_TENANT_ID = 'tenant-a'
  setRow('uncertain')
  const source = stripTypeScriptTypes(harness + payloadHashSource + contractSource + operationsSource + `
    const packageData = globalThis.__packageData
    const packageHash = globalThis.__packageHash
    const operationKey = globalThis.__operationKey
    const documentKey = globalThis.__documentKey
    const stamp = globalThis.__stamp
    const resultHash = globalThis.__resultHash
    const prior = globalThis.__prior
    const requestBody = extra => ({mode:'plan',package:packageData,packageHash,operationKey,documentKey,...extra})
    let response = await growthPost(request(requestBody()), '/growth/retire-obsolete', {kind:'owner',auth:{}})
    assert.equal(response.status,403,'owner route cannot retire uncertain service operations')
    response = await growthPost(request(requestBody()), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,200,JSON.stringify(await response.clone().json()))
    const plan = await response.json()
    assert.equal(plan.eligible,true)
    assert.equal(plan.expectedUpdatedAt,stamp)
    assert.equal(plan.expectedResultHash,resultHash)
    assert.equal((await operationByKey(operationKey)).state,'uncertain','plan is read-only')
    const savedTenant = packageData.tenant
    packageData.tenant = 'another-tenant'
    const wrongTenantHash = await hashJson(packageData)
    response = await growthPost(request({mode:'plan',package:packageData,packageHash:wrongTenantHash,operationKey,documentKey}), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,409,'wrong tenant cannot bind to the registered operation')
    packageData.tenant = savedTenant
    response = await growthPost(request({mode:'plan',package:packageData,packageHash:'sha256:' + '0'.repeat(64),operationKey,documentKey}), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,409,'wrong package hash cannot bind to the operation')
    await db.prepare("UPDATE helloada_growth_operations SET updated_at = 'raced' WHERE operation_key = ?1").bind(operationKey).run()
    assert.equal(await retireObsoleteOperation({operationKey,documentKey,packageHash,expectedUpdatedAt:stamp,expectedResultHash:resultHash,priorResultJson:JSON.stringify(prior),receipt:{disposition:'retired_obsolete'}}),false,'SQL CAS rejects a changed row version')
    await db.prepare('UPDATE helloada_growth_operations SET updated_at = ?1 WHERE operation_key = ?2').bind(stamp,operationKey).run()
    assert.equal(await retireObsoleteOperation({operationKey,documentKey,packageHash,expectedUpdatedAt:stamp,expectedResultHash:resultHash,priorResultJson:JSON.stringify({...prior,error:'drifted'}),receipt:{disposition:'retired_obsolete'}}),false,'SQL CAS rejects changed prior result JSON')
    const applyBody = {mode:'apply',package:packageData,packageHash,operationKey,documentKey,expectedUpdatedAt:stamp,expectedResultHash:resultHash,reason:'Old scope explicitly abandoned',operatorRequestId:'cleanup-2026-10-23'}
    draft = {id:'doc-7',title:'Candidate',updatedAt:'draft-v2',route:'/'}
    response = await growthPost(request(applyBody), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,409,'candidate already present cannot be described as obsolete')
    draft = {id:'doc-7',title:'Base',updatedAt:'draft-v1',route:'/'}
    live = {...live,title:'Owner published newer content'}
    response = await growthPost(request(applyBody), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,409,'changed published base blocks retirement')
    live = {id:'doc-7',title:'Base',updatedAt:'live-v1',route:'/'}
    await db.prepare("UPDATE helloada_growth_operations SET state = 'writing' WHERE operation_key = ?1").bind(operationKey).run()
    response = await growthPost(request(applyBody), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,409,'writing operation is not eligible')
    await db.prepare("UPDATE helloada_growth_operations SET state = 'uncertain' WHERE operation_key = ?1").bind(operationKey).run()
    response = await growthPost(request(applyBody), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,200,JSON.stringify(await response.clone().json()))
    const receipt = await response.json()
    assert.equal(receipt.disposition,'retired_obsolete')
    assert.equal(receipt.ok,false)
    assert.deepEqual(receipt.priorResult,{ok:false,packageHash,error:'old preparation timed out'})
    const stored = await operationByKey(operationKey)
    assert.equal(stored.state,'completed')
    assert.equal(JSON.parse(stored.result_json).disposition,'retired_obsolete')
    assert.equal(globalThis.__sqlite.prepare('SELECT COUNT(*) AS count FROM helloada_growth_operations').get().count,1,'retirement preserves the operation row')
    response = await growthPost(request(applyBody), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,200,'same retirement request returns its saved terminal receipt')
    assert.deepEqual(await response.json(),receipt)
    response = await growthPost(request({...applyBody,operatorRequestId:'different-cleanup'}), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,409,'new operator request cannot claim an older retirement receipt')
    globalThis.__sqlite.prepare('INSERT INTO helloada_growth_candidates VALUES(?,?,?)').run(packageHash,'validated',JSON.stringify(packageData))
    response = await growthPost(request({package:packageData,packageHash}), '/growth/apply', {kind:'service',token:'test'})
    assert.equal(response.status,409,'retired operation cannot be replayed through apply')
    response = await growthPost(request({packageHash}), '/growth/publish', {kind:'service',token:'test'})
    assert.equal(response.status,409,'retired operation cannot be replayed through publish')
    assert.equal((await operationByKey(operationKey)).result_json,stored.result_json,'replay attempts preserve receipt')
    draft = {id:'doc-7',title:'Candidate',updatedAt:'draft-v2',route:'/'}
    response = await growthPost(request({package:packageData,packageHash}), '/growth/validate', {kind:'service',token:'test'})
    assert.equal(response.status,409,'retired package cannot be revalidated after its candidate appears')
    response = await growthPost(request({package:packageData,packageHash}), '/growth/apply', {kind:'service',token:'test'})
    assert.equal(response.status,409,'retired package remains blocked when its candidate appears')
    assert.match((await response.json()).message,/retired/)
    const beforePublishRows = globalThis.__sqlite.prepare("SELECT COUNT(*) AS count FROM helloada_growth_operations WHERE operation_key LIKE 'publish:%'").get().count
    response = await growthPost(request({packageHash}), '/growth/publish', {kind:'service',token:'test'})
    assert.equal(response.status,409,'publication is blocked even with the exact candidate now present')
    assert.match((await response.json()).message,/retired/)
    assert.equal(globalThis.__sqlite.prepare("SELECT COUNT(*) AS count FROM helloada_growth_operations WHERE operation_key LIKE 'publish:%'").get().count,beforePublishRows,'retired publication is rejected before claiming a publish operation')
    assert.equal(writes,0,'retirement and rejected replay never write Payload')

    const snapshotPackageHash = 'sha256:' + 'b'.repeat(64)
    const snapshotOperationKey = 'draft:tenant-a:' + documentKey + ':' + snapshotPackageHash
    const snapshotPrior = {ok:false,packageHash:snapshotPackageHash,error:'preparation did not settle'}
    globalThis.__sqlite.prepare('INSERT INTO helloada_growth_operations VALUES(?,?,?,?,?,?,?,?)')
      .run(snapshotOperationKey,documentKey,'tenant-a',snapshotPackageHash,'uncertain',JSON.stringify(snapshotPrior),stamp,stamp)
    draft = {id:'doc-7',title:'Owner unpublished work',updatedAt:'draft-owner-v4',route:'/'}
    const snapshotBody = extras => ({basis:'current_site_snapshot',mode:'plan',operationKey:snapshotOperationKey,packageHash:snapshotPackageHash,collection:'pages',documentId:'doc-7',...extras})
    await db.prepare("UPDATE helloada_growth_operations SET state = 'writing' WHERE operation_key = ?1").bind(snapshotOperationKey).run()
    response = await growthPost(request(snapshotBody()), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,409,'writing operation cannot be withdrawn')
    await db.prepare("UPDATE helloada_growth_operations SET state = 'uncertain' WHERE operation_key = ?1").bind(snapshotOperationKey).run()
    response = await growthPost(request({mode:'plan',operationKey:snapshotOperationKey,packageHash:snapshotPackageHash,collection:'pages',documentId:'doc-7'}), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,400,'snapshot basis must be explicit')
    response = await growthPost(request(snapshotBody()), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,200,JSON.stringify(await response.clone().json()))
    const snapshotPlan = await response.json()
    assert.equal(snapshotPlan.basis,'current_site_snapshot')
    assert.notEqual(snapshotPlan.snapshot.currentPublished.canonicalHash,snapshotPlan.snapshot.currentDraft.canonicalHash)
    assert.equal('content' in snapshotPlan.snapshot.currentDraft,false,'snapshot returns hashes and revision IDs only')
    response = await growthPost(request(snapshotBody({collection:'posts'})), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,409,'changed target cannot reuse the row plan')
    const applySnapshot = () => ({...snapshotBody({mode:'apply'}),expectedUpdatedAt:snapshotPlan.expectedUpdatedAt,
      expectedResultHash:snapshotPlan.expectedResultHash,expectedSnapshotProofHash:snapshotPlan.snapshotProofHash,
      preserveExistingDraft:true,reason:'Abandoned stale design scope; preserve current owner draft',operatorRequestId:'cleanup-snapshot-7'})
    const schemaFields = payload.config.collections[0].fields
    schemaFields.push({name:'schemaDrift'})
    response = await growthPost(request(applySnapshot()), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,409,'schema drift invalidates the snapshot proof')
    schemaFields.pop()
    draft = {...draft,title:'Owner edited after snapshot'}
    response = await growthPost(request(applySnapshot()), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,409,'draft drift invalidates the snapshot proof')
    draft = {id:'doc-7',title:'Owner unpublished work',updatedAt:'draft-owner-v4',route:'/'}
    response = await growthPost(request(applySnapshot()), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,200,JSON.stringify(await response.clone().json()))
    const snapshotReceipt = await response.json()
    assert.equal(snapshotReceipt.disposition,'retired_obsolete')
    assert.equal(snapshotReceipt.effectStatus,'unknown')
    assert.equal(snapshotReceipt.withdrawal,'explicit')
    assert.equal(snapshotReceipt.snapshot.currentDraft.canonicalHash,snapshotPlan.snapshot.currentDraft.canonicalHash)
    assert.deepEqual(draft,{id:'doc-7',title:'Owner unpublished work',updatedAt:'draft-owner-v4',route:'/'},'current unpublished content is preserved byte-for-byte')
    assert.equal((await operationByKey(snapshotOperationKey)).state,'completed')
    response = await growthPost(request(applySnapshot()), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,200,'same operation ID returns its saved withdrawal receipt')
    assert.deepEqual(await response.json(),snapshotReceipt)
    response = await growthPost(request({...applySnapshot(),operatorRequestId:'different-cleanup'}), '/growth/retire-obsolete', {kind:'service',token:'test'})
    assert.equal(response.status,409,'new operator request cannot claim an older snapshot withdrawal')
    assert.equal(writes,0,'snapshot retirement never writes Payload')
  `)
  globalThis.__packageData = packageData
  globalThis.__packageHash = packageHash
  globalThis.__operationKey = operationKey
  globalThis.__documentKey = documentKey
  globalThis.__stamp = stamp
  globalThis.__resultHash = resultHash
  globalThis.__prior = prior
  process.env.HELLOADA_SCHEMA_IDENTITY = 'schema-v1'
  const moduleUrl = 'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
  try {
    await import(moduleUrl)
  } finally {
    delete globalThis.__retirementDb
    delete globalThis.__sqlite
    delete globalThis.__webcrypto
    delete globalThis.__packageData
    delete globalThis.__packageHash
    delete globalThis.__operationKey
    delete globalThis.__documentKey
    delete globalThis.__stamp
    delete globalThis.__resultHash
    delete globalThis.__prior
    delete process.env.HELLOADA_TENANT_ID
    delete process.env.HELLOADA_SCHEMA_IDENTITY
    sqlite.close()
  }
})

test('retirement SQL compare-and-swap includes the exact prior row fields', () => {
  assert.match(contractSource, /state = 'uncertain' AND updated_at = \?7\s+AND result_json = \?8/)
  assert.match(contractSource, /operation_key = \?3 AND document_key = \?4 AND tenant_id = \?5\s+AND package_hash = \?6/)
  assert.match(contractSource, /meta\?\.changes[^\n]*=== 1/)
  const serviceRoute = readFileSync(new URL('../src/app/api/workspace/growth/[...path]/route.ts', import.meta.url), 'utf8')
  const ownerBridge = readFileSync(new URL('../src/app/api/helloada/[...path]/route.ts', import.meta.url), 'utf8')
  assert.match(serviceRoute, /if \(!serviceAuthorized\(request\)\) return unauthorized\(\)/)
  assert.match(ownerBridge, /growth\/retire-obsolete/)
})
