export type QueueEvent = { queue: string; messages: unknown[] }
export type WorkerHandlerSet<Env> = {
  fetch?: (request: Request, env: Env, context: unknown) => Response | Promise<Response>
  email?: (message: unknown, env: Env, context: unknown) => void | Promise<void>
  queue?: (batch: QueueEvent, env: Env, context: unknown) => void | Promise<void>
  scheduled?: (event: unknown, env: Env, context: unknown) => void | Promise<void>
}

type ComposeOptions<SiteEnv, MailflareEnv> = {
  site: WorkerHandlerSet<SiteEnv>
  mailflare: WorkerHandlerSet<MailflareEnv>
  mailflareEnv: (env: SiteEnv) => MailflareEnv
  mailflareQueueNames: (env: SiteEnv) => string[]
  mailflareRequest: (
    request: Request,
    env: SiteEnv,
    context: unknown,
    dispatch: (authorizedRequest: Request) => Promise<Response>,
  ) => Promise<Response>
  basePath: string
}

function isWithinBasePath(pathname: string, basePath: string) {
  return pathname === basePath || pathname.startsWith(`${basePath}/`)
}

function requireMailflareQueues(names: string[]) {
  if (names.length !== 3 || names.some((name) => !name) || new Set(names).size !== names.length) {
    throw new Error('Mailflare must have three distinct configured tenant queues.')
  }
  return names
}

export function composeTenantWorker<SiteEnv, MailflareEnv>({
  site,
  mailflare,
  mailflareEnv,
  mailflareQueueNames,
  mailflareRequest,
  basePath,
}: ComposeOptions<SiteEnv, MailflareEnv>) {
  if (!basePath.startsWith('/') || basePath === '/' || basePath.endsWith('/')) {
    throw new Error('Mailflare base path must be one absolute, non-root path.')
  }

  return {
    fetch(request: Request, env: SiteEnv, context: unknown) {
      const { pathname } = new URL(request.url)
      if (isWithinBasePath(pathname, basePath)) {
        if (!mailflare.fetch) throw new Error('Mailflare HTTP handler is missing.')
        return mailflareRequest(request, env, context, (authorizedRequest) =>
          mailflare.fetch!(authorizedRequest, mailflareEnv(env), context))
      }
      if (!site.fetch) throw new Error('Site-Agent HTTP handler is missing.')
      return site.fetch(request, env, context)
    },

    email(message: unknown, env: SiteEnv, context: unknown) {
      if (!mailflare.email) throw new Error('Mailflare inbound email handler is missing.')
      return mailflare.email(message, mailflareEnv(env), context)
    },

    queue(batch: QueueEvent, env: SiteEnv, context: unknown) {
      const names = requireMailflareQueues(mailflareQueueNames(env))
      if (!names.includes(batch.queue)) throw new Error('Worker received an unregistered Mailflare queue.')
      if (!mailflare.queue) throw new Error('Mailflare Queue handler is missing.')
      return mailflare.queue(batch, mailflareEnv(env), context)
    },

    async scheduled(event: unknown, env: SiteEnv, context: unknown) {
      if (!mailflare.scheduled) throw new Error('Mailflare scheduled handler is missing.')
      await mailflare.scheduled(event, mailflareEnv(env), context)
    },
  }
}
