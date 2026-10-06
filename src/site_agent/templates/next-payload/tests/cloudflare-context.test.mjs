import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { payloadCloudflareContextPlan } from '../src/lib/cloudflare-context.ts'

const root = path.resolve(fileURLToPath(new URL('../', import.meta.url)))
const read = relative => readFileSync(path.join(root, relative), 'utf8')
const payloadConfig = ['payload.config.ts', 'src/payload.config.ts'].find(file => existsSync(path.join(root, file)))

test('Payload CLI migrations and the native-write guard use one Cloudflare context provider', () => {
  assert.ok(payloadConfig, 'Payload configuration exists')
  const config = read(payloadConfig)
  const guard = read('src/lib/growth-contract.ts')
  assert.match(config, /getPayloadCloudflareContext\(\)/)
  assert.match(read('src/lib/cloudflare-context.ts'), /configPath: plan\.configPath/)
  assert.match(guard, /getPayloadCloudflareContext\(\)/)
  assert.doesNotMatch(guard, /getCloudflareContext\s*\(/)
})

test('production Payload CLI uses Wrangler remote bindings, while Worker requests use OpenNext context', () => {
  assert.deepEqual(payloadCloudflareContextPlan({
    NODE_ENV: 'production',
    PAYLOAD_CLI: '1',
    CLOUDFLARE_API_TOKEN: 'configured',
    HELLOADA_CLOUDFLARE_CONFIG_PATH: '/release/temporary/wrangler.jsonc',
  }, ['migrate']), {
    provider: 'wrangler',
    remoteBindings: true,
    configPath: '/release/temporary/wrangler.jsonc',
  })
  assert.throws(() => payloadCloudflareContextPlan({
    NODE_ENV: 'production',
    PAYLOAD_CLI: '1',
    CLOUDFLARE_API_TOKEN: 'configured',
  }, ['migrate']), /remote-binding Wrangler config/)
  assert.throws(() => payloadCloudflareContextPlan({
    NODE_ENV: 'production',
    PAYLOAD_CLI: '1',
    HELLOADA_CLOUDFLARE_CONFIG_PATH: '/release/temporary/wrangler.jsonc',
  }, ['migrate']), /Cloudflare credential/)
  assert.deepEqual(payloadCloudflareContextPlan({ NODE_ENV: 'production' }, []), {
    provider: 'opennext', remoteBindings: false,
  })
  assert.deepEqual(payloadCloudflareContextPlan({ NODE_ENV: 'production', PAYLOAD_LOCAL_BUILD: '1', CLOUDFLARE_API_TOKEN: 'configured' }, []), {
    provider: 'wrangler', remoteBindings: false,
  })
})

test('package-managed Payload CLI entrypoints are detected even without a caller-supplied environment marker', () => {
  assert.deepEqual(payloadCloudflareContextPlan({
    NODE_ENV: 'production',
    CLOUDFLARE_API_TOKEN: 'configured',
    HELLOADA_CLOUDFLARE_CONFIG_PATH: '/release/temporary/wrangler.jsonc',
  }, ['/project/node_modules/payload/bin.js', 'migrate']), {
    provider: 'wrangler',
    remoteBindings: true,
    configPath: '/release/temporary/wrangler.jsonc',
  })
})
