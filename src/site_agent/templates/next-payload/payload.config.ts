import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { sqliteD1Adapter } from '@payloadcms/db-d1-sqlite'
import { r2Storage } from '@payloadcms/storage-r2'
import { lexicalEditor } from '@payloadcms/richtext-lexical'
import { buildConfig } from 'payload'
import { createHelloAdaSchema } from '@weareheadless/helloada-payload-core/schema'

import { getPayloadCloudflareContext } from './src/lib/cloudflare-context'
import { assertNativeWriteAllowed, withWriteFailureSettlement } from './src/lib/growth-contract'
import { withCollectionRevisionGuard, withGlobalRevisionGuard } from './src/lib/payload-revision'
import { helloAdaSite } from './src/helloada.config'

const filename = fileURLToPath(import.meta.url)
const dirname = path.dirname(filename)
const payloadCliEntrypoint = process.argv.some((value) =>
  /(?:^|[\\/])payload(?:\.cmd|\.js)?$/i.test(value) || /[\\/]payload[\\/]bin\.js$/i.test(value),
)
const isCLI = process.env.PAYLOAD_CLI === '1'
const isProduction = process.env.NODE_ENV === 'production'
const schema = createHelloAdaSchema(assertNativeWriteAllowed)

if (payloadCliEntrypoint && !isCLI) {
  throw new Error('Payload CLI commands must use the package-managed scripts, which set PAYLOAD_CLI=1 explicitly.')
}

export const cloudflare = await getPayloadCloudflareContext() as unknown as {
  env: {
    D1: Parameters<typeof sqliteD1Adapter>[0]['binding']
    R2: Parameters<typeof r2Storage>[0]['bucket']
  }
}

export default buildConfig({
  admin: {
    user: 'users',
    theme: 'dark',
    meta: {
      titleSuffix: ' — HelloAda',
      applicationName: 'HelloAda',
      icons: { icon: '/brand/helloada-logo.svg' },
      description: 'The tenant Payload admin for advanced content and media work.',
    },
  },
  // A reviewed revision is compared against the revision Payload has loaded for
  // this write, inside the same shared writer lease. Passing an expected hash in
  // the request context is therefore a real compare-and-swap, not a pre-check.
  // Settle failed native writes with the real error before the schema's own
  // error hook runs, and enforce the reviewed revision inside the write lease.
  collections: withWriteFailureSettlement(withCollectionRevisionGuard(schema.collections)),
  globals: withWriteFailureSettlement(withGlobalRevisionGuard(schema.globals)),
  localization: {
    locales: [...helloAdaSite.locales],
    defaultLocale: helloAdaSite.defaultLocale,
    fallback: false,
  },
  editor: lexicalEditor(),
  secret: process.env.PAYLOAD_SECRET || (isProduction ? '' : 'helloada-local-development-secret'),
  typescript: { outputFile: path.resolve(dirname, 'src/payload-types.ts') },
  db: sqliteD1Adapter({
    binding: cloudflare.env.D1,
    migrationDir: path.resolve(dirname, 'src/migrations'),
  }),
  plugins: [r2Storage({ bucket: cloudflare.env.R2, collections: { media: true } })],
})
