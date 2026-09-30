import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { getCloudflareContext } from '@opennextjs/cloudflare'
import { sqliteD1Adapter } from '@payloadcms/db-d1-sqlite'
import { r2Storage } from '@payloadcms/storage-r2'
import { lexicalEditor } from '@payloadcms/richtext-lexical'
import type { GetPlatformProxyOptions } from 'wrangler'
import { buildConfig } from 'payload'

import { Media } from './src/collections/Media'
import { Pages } from './src/collections/Pages'
import { Users } from './src/collections/Users'

const filename = fileURLToPath(import.meta.url)
const dirname = path.dirname(filename)
const isCLI = process.env.PAYLOAD_CLI === '1' || process.argv.some((value) => value.includes('payload'))
const isProduction = process.env.NODE_ENV === 'production'
const isNextBuild = process.env.NEXT_PHASE === 'phase-production-build'
const isLocalBuild = process.env.PAYLOAD_LOCAL_BUILD === '1'
const hasCloudflareToken = Boolean(process.env.CLOUDFLARE_API_TOKEN)

export const cloudflare =
  isCLI || !isProduction || isLocalBuild || isNextBuild
    ? await getCloudflareContextFromWrangler()
    : await getCloudflareContext({ async: true })

export default buildConfig({
  admin: { user: Users.slug },
  collections: [Users, Pages, Media],
  editor: lexicalEditor(),
  secret: process.env.PAYLOAD_SECRET || (isProduction ? '' : 'helloada-local-development-secret'),
  typescript: { outputFile: path.resolve(dirname, 'src/payload-types.ts') },
  db: sqliteD1Adapter({ binding: cloudflare.env.D1 }),
  plugins: [r2Storage({ bucket: cloudflare.env.R2, collections: { media: true } })],
})

async function getCloudflareContextFromWrangler() {
  return import(/* webpackIgnore: true */ `${'__wrangler'.replaceAll('_', '')}`).then(
    ({ getPlatformProxy }) => getPlatformProxy({
      environment: process.env.CLOUDFLARE_ENV,
      remoteBindings: isProduction && hasCloudflareToken && !isNextBuild && !isLocalBuild,
    } satisfies GetPlatformProxyOptions),
  )
}
