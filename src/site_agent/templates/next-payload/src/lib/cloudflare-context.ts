import { getCloudflareContext } from '@opennextjs/cloudflare'
import type { GetPlatformProxyOptions } from 'wrangler'

type Context = Awaited<ReturnType<typeof getCloudflareContext>>
type Environment = Record<string, string | undefined>

type ContextPlan = {
  provider: 'wrangler' | 'opennext'
  remoteBindings: boolean
  configPath?: string
}

export const payloadCloudflareContextPlan = (
  env: Environment = process.env,
  argv: string[] = process.argv,
): ContextPlan => {
  const payloadCliEntrypoint = argv.some((value) => {
    const normalized = value.replaceAll('\\', '/')
    return /(?:^|\/)payload(?:\.cmd|\.js)?$/i.test(normalized) || /\/payload\/bin\.js$/i.test(normalized)
  })
  const isPayloadCli = env.PAYLOAD_CLI === '1' || payloadCliEntrypoint
  const isProduction = env.NODE_ENV === 'production'
  const isBuild = env.NEXT_PHASE === 'phase-production-build' || env.PAYLOAD_LOCAL_BUILD === '1'
  const isDatabaseMigration = argv.some((value) =>
    ['migrate', 'migrate:status', 'migrate:create', 'migrate:down'].includes(value),
  )
  const configPath = env.HELLOADA_CLOUDFLARE_CONFIG_PATH?.trim()
  const requiresRemoteMigration = isPayloadCli && isProduction && !isBuild && isDatabaseMigration
  if (requiresRemoteMigration && !env.CLOUDFLARE_API_TOKEN) {
    throw new Error('Production Payload migrations require the configured Cloudflare credential.')
  }
  if (requiresRemoteMigration && !configPath) {
    throw new Error('Production Payload migrations require the release pipeline’s exact remote-binding Wrangler config.')
  }
  const provider = isPayloadCli || !isProduction || isBuild ? 'wrangler' : 'opennext'
  return {
    provider,
    remoteBindings: provider === 'wrangler' && isProduction && Boolean(env.CLOUDFLARE_API_TOKEN) && !isBuild,
    ...(configPath ? { configPath } : {}),
  }
}

let wranglerContext: Promise<Context> | undefined

export const getPayloadCloudflareContext = async (): Promise<Context> => {
  const plan = payloadCloudflareContextPlan()
  if (plan.provider === 'opennext') return getCloudflareContext({ async: true })
  wranglerContext ??= import(/* webpackIgnore: true */ `${'__wrangler'.replaceAll('_', '')}`).then(
    ({ getPlatformProxy }) => getPlatformProxy({
      ...(plan.configPath ? { configPath: plan.configPath } : {}),
      environment: process.env.CLOUDFLARE_ENV,
      remoteBindings: plan.remoteBindings,
    } satisfies GetPlatformProxyOptions) as unknown as Context,
  )
  return wranglerContext
}
