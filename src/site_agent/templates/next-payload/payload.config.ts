import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { sqliteD1Adapter } from '@payloadcms/db-d1-sqlite'
import { r2Storage } from '@payloadcms/storage-r2'
import { lexicalEditor } from '@payloadcms/richtext-lexical'
import { buildConfig } from 'payload'
import { createHelloAdaSchema } from '@weareheadless/helloada-payload-core/schema'

import { getPayloadCloudflareContext } from './src/lib/cloudflare-context'
import { assertNativeWriteAllowed } from './src/lib/growth-contract'
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
      description: 'A calm control room for shaping, reviewing, and publishing your website with Ada.',
    },
    components: {
      beforeLogin: ['@/components/admin/HelloAdaLoginRedirect#HelloAdaLoginRedirect'],
      views: {
        dashboard: {
          Component: {
            exportName: 'WebsiteWorkspace',
            path: '@/components/admin/HelloAdaWorkspace',
          },
          exact: true,
        },
      },
      Nav: {
        exportName: 'HelloAdaNav',
        path: '@/components/admin/HelloAdaNav',
      },
      graphics: {
        Icon: {
          exportName: 'HelloAdaIcon',
          path: '@/components/admin/HelloAdaLogo',
        },
        Logo: {
          exportName: 'HelloAdaLogo',
          path: '@/components/admin/HelloAdaLogo',
        },
      },
    },
  },
  collections: schema.collections,
  globals: schema.globals,
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
