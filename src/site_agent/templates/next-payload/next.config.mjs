import { initOpenNextCloudflareForDev } from '@opennextjs/cloudflare'
import { withPayload } from '@payloadcms/next/withPayload'

// Production artifacts must be built with isolated local bindings. The Worker
// deploy step is the only stage allowed to contact Cloudflare; otherwise a
// deploy token without remote-preview permission can make builds non-reproducible.
initOpenNextCloudflareForDev({ remoteBindings: false })

/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false,
  transpilePackages: ['@weareheadless/helloada-payload-admin'],
  experimental: { cpus: 1 },
  serverExternalPackages: ['jose', 'pg-cloudflare'],
  webpack: (webpackConfig) => {
    webpackConfig.resolve.extensionAlias = {
      '.cjs': ['.cts', '.cjs'],
      '.js': ['.ts', '.tsx', '.js', '.jsx'],
      '.mjs': ['.mts', '.mjs'],
    }
    return webpackConfig
  },
}

export default withPayload(nextConfig, { devBundleServerPackages: false })
