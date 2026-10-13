import assert from 'node:assert/strict'
import test from 'node:test'

import { readSchemaReleaseMetadata } from '../../../scripts/package-helloada-payload-core-release.mjs'

test('release manifest metadata follows the packed canonical schema', () => {
  const schema = `
    export const HELLOADA_CONTENT_CONTRACT_VERSION = 'helloada-content-v4'
    export const HELLOADA_CORE_VERSION = '0.5.9'
    export const HELLOADA_SCHEMA_REVISION = 8
  `
  assert.deepEqual(readSchemaReleaseMetadata(schema), {
    contentContract: 'helloada-content-v4',
    coreVersion: '0.5.9',
    schemaRevision: 8,
  })
})

test('release metadata fails closed when a schema constant is absent or invalid', () => {
  assert.throws(() => readSchemaReleaseMetadata("export const HELLOADA_CONTENT_CONTRACT_VERSION = 'helloada-content-v4'"), /HELLOADA_CORE_VERSION/)
  assert.throws(() => readSchemaReleaseMetadata(`
    export const HELLOADA_CONTENT_CONTRACT_VERSION = 'helloada-content-v4'
    export const HELLOADA_CORE_VERSION = '0.5.9'
    export const HELLOADA_SCHEMA_REVISION = 0
  `), /invalid schema revision/)
})
