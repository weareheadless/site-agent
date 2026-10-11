import { provisionTenantMailflareMailbox } from './mailflare-provisioning'
import { migratePayloadMailbox, type PayloadMailboxMigrationEnv } from './mailflare-payload-migration'

type D1Statement = {
  bind: (...values: unknown[]) => D1Statement
  first: <T = Record<string, unknown>>() => Promise<T | null>
  all: <T = Record<string, unknown>>() => Promise<{ results?: T[] }>
  run: () => Promise<unknown>
}

type D1Binding = { prepare: (query: string) => D1Statement }

export type PayloadOwnerIdentity = { subject: string }

type MailflareEnv = PayloadMailboxMigrationEnv & {
  MAILFLARE_DB: D1Binding
  HELLOADA_TENANT_ID: string
  MAILFLARE_ADDRESS: string
  MAILFLARE_ZONE_ID: string
  MAILFLARE_ROUTING_STATUS: string
}
type LogoutHandler<Env, Context> = (request: Request, env: Env, context: Context) => Promise<Response>
type IdentityResolver<Env, Context> = (request: Request, env: Env, context: Context) => Promise<PayloadOwnerIdentity | null>

type OwnerGateOptions<Env extends MailflareEnv, Context> = {
  basePath: string
  defaultLocale: string
  resolveIdentity: IdentityResolver<Env, Context>
  logout: LogoutHandler<Env, Context>
}

const SESSION_COOKIE = 'ep_session'
const SESSION_MS = 30 * 24 * 60 * 60 * 1000
const SSO_PASSWORD_SENTINEL = '!helloada-payload-sso-only'
const SSO_ACCOUNT_NAME = 'HelloAda owner'

const digest = async (value: string) => {
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))
  return [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

const randomHex = (length = 32) => {
  const bytes = crypto.getRandomValues(new Uint8Array(length))
  return [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

const cookieValue = (request: Request, name: string) => {
  const prefix = `${name}=`
  for (const part of (request.headers.get('cookie') || '').split(';')) {
    const cookie = part.trim()
    if (cookie.startsWith(prefix)) return cookie.slice(prefix.length)
  }
  return ''
}

const withSessionCookie = (request: Request, token: string) => {
  const headers = new Headers(request.headers)
  const cookies = (headers.get('cookie') || '').split(';').map((part) => part.trim()).filter(Boolean)
    .filter((part) => !part.startsWith(`${SESSION_COOKIE}=`))
  cookies.push(`${SESSION_COOKIE}=${token}`)
  headers.set('cookie', cookies.join('; '))
  return new Request(request, { headers })
}

const withoutCache = (response: Response, cookie?: string) => {
  const headers = new Headers(response.headers)
  headers.set('Cache-Control', 'private, no-store')
  if (cookie) headers.append('Set-Cookie', cookie)
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers })
}

const jsonError = (status: number, error: string) => Response.json({ error }, {
  status,
  headers: { 'Cache-Control': 'no-store' },
})

const under = (pathname: string, root: string) => pathname === root || pathname.startsWith(`${root}/`)

const isStatic = (request: Request, pathname: string, basePath: string) =>
  ['GET', 'HEAD'].includes(request.method)
  && (pathname.startsWith(`${basePath}/_next/static/`)
    || [`${basePath}/favicon.ico`, `${basePath}/manifest.webmanifest`, `${basePath}/helloada-logo.svg`].includes(pathname))

const isPublic = (request: Request, pathname: string, basePath: string) => {
  if (isStatic(request, pathname, basePath)) return true
  if (pathname.startsWith(`${basePath}/api/inbound/`)
      || pathname === `${basePath}/api/public/booking`
      || pathname.startsWith(`${basePath}/api/public/booking/`)
      || pathname.startsWith(`${basePath}/api/drive/public/`)
      || pathname.startsWith(`${basePath}/book/`)
      || pathname.startsWith(`${basePath}/c/`)) return true
  return false
}

const isStandaloneAuthPage = (pathname: string, basePath: string) =>
  ['/login', '/register', '/setup', '/onboarding', '/forgot-password', '/reset-password']
    .some((route) => under(pathname, `${basePath}${route}`))

const isStandaloneAuthApi = (pathname: string, basePath: string) =>
  ['/api/auth/login', '/api/auth/register', '/api/auth/password-reset', '/api/auth/mfa',
    '/api/auth/switch', '/api/setup', '/api/seed', '/api/settings/password', '/api/settings/mfa']
    .some((route) => under(pathname, `${basePath}${route}`))

const redirectToPayloadLogin = (request: Request) => {
  const target = new URL('/admin/login', request.url)
  target.searchParams.set('redirect', '/mail/inbox')
  return Response.redirect(target, 302)
}

async function provisionOwnerSession(
  request: Request,
  env: MailflareEnv,
  identity: PayloadOwnerIdentity,
  defaultLocale: string,
): Promise<{ token: string; created: boolean }> {
  const userId = `ha_${await digest(identity.subject)}`
  const existingToken = cookieValue(request, SESSION_COOKIE)
  if (existingToken) {
    const tokenHash = await digest(existingToken)
    const session = await env.MAILFLARE_DB.prepare(
      'SELECT users.id AS user_id FROM sessions INNER JOIN users ON users.id = sessions.user_id WHERE sessions.token_hash = ? AND sessions.expires_at > ? AND users.id = ? AND users.disabled = 0 LIMIT 1',
    ).bind(tokenHash, Date.now(), userId).first<{ user_id: string }>()
    if (session?.user_id === userId) {
      const mailbox = await provisionTenantMailflareMailbox({ database: env.MAILFLARE_DB, tenantId: env.HELLOADA_TENANT_ID, address: env.MAILFLARE_ADDRESS, zoneId: env.MAILFLARE_ZONE_ID, routingStatus: env.MAILFLARE_ROUTING_STATUS })
      await migratePayloadMailbox(env, { ownerUserId: userId, serviceUserId: mailbox.serviceUserId, mailboxId: mailbox.mailboxId, defaultLocale })
      return { token: existingToken, created: false }
    }
  }

  const current = await env.MAILFLARE_DB.prepare(
    'SELECT id, disabled FROM users WHERE id = ? LIMIT 1',
  ).bind(userId).first<{ id: string; disabled: number }>()
  if (current?.disabled) throw new Error('Mailflare owner account is disabled')
  const mailbox = await provisionTenantMailflareMailbox({
    database: env.MAILFLARE_DB,
    tenantId: env.HELLOADA_TENANT_ID,
    address: env.MAILFLARE_ADDRESS,
    zoneId: env.MAILFLARE_ZONE_ID,
    routingStatus: env.MAILFLARE_ROUTING_STATUS,
  })
  const bookingUsername = env.HELLOADA_TENANT_ID.toLowerCase()
  if (!/^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/.test(bookingUsername)) {
    throw new Error('Tenant identity cannot be used as a Mailflare booking username')
  }
  if (!current) {
    await env.MAILFLARE_DB.prepare(
      'INSERT INTO users (id, email, password_hash, name, role, is_primary_admin, can_manage_mailboxes, can_manage_domains, can_manage_users, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
    ).bind(userId, `${userId}@identity.helloada.invalid`, SSO_PASSWORD_SENTINEL, SSO_ACCOUNT_NAME, 'user', 0, 0, 0, 0, Date.now()).run()
  } else {
    await env.MAILFLARE_DB.prepare(
      'UPDATE users SET name = ? WHERE id = ? AND disabled = 0',
    ).bind(SSO_ACCOUNT_NAME, userId).run()
  }
  await env.MAILFLARE_DB.prepare(
    'UPDATE users SET booking_username = ? WHERE id = ? AND disabled = 0',
  ).bind(bookingUsername, userId).run()

  const enabled = await env.MAILFLARE_DB.prepare(
    'SELECT id FROM users WHERE id = ? AND disabled = 0 LIMIT 1',
  ).bind(userId).first<{ id: string }>()
  if (!enabled) throw new Error('Mailflare owner account could not be provisioned')

  const accessId = `ha_access_${(await digest(`${mailbox.mailboxId}:${userId}`)).slice(0, 32)}`
  await env.MAILFLARE_DB.prepare(
    'INSERT OR IGNORE INTO mailbox_access (id, mailbox_id, user_id, permission, created_by_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?)',
  ).bind(accessId, mailbox.mailboxId, userId, 'full_access', mailbox.serviceUserId, Date.now()).run()
  const access = await env.MAILFLARE_DB.prepare(
    'SELECT id FROM mailbox_access WHERE mailbox_id = ? AND user_id = ? AND permission = ? LIMIT 1',
  ).bind(mailbox.mailboxId, userId, 'full_access').first<{ id: string }>()
  if (access?.id !== accessId) throw new Error('Mailflare owner mailbox access could not be provisioned')

  await migratePayloadMailbox(env, {
    ownerUserId: userId,
    serviceUserId: mailbox.serviceUserId,
    mailboxId: mailbox.mailboxId,
    defaultLocale,
  })

  const token = randomHex(32)
  await env.MAILFLARE_DB.prepare(
    'INSERT INTO sessions (id, user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)',
  ).bind(`ha_sess_${randomHex(16)}`, userId, await digest(token), Date.now() + SESSION_MS, Date.now()).run()
  return { token, created: true }
}

export function createPayloadOwnerGate<Env extends MailflareEnv, Context>({
  basePath,
  defaultLocale,
  resolveIdentity,
  logout,
}: OwnerGateOptions<Env, Context>) {
  if (!basePath.startsWith('/') || basePath === '/' || basePath.endsWith('/')) {
    throw new Error('Mailflare owner gate requires one absolute non-root base path')
  }

  return async (
    request: Request,
    env: Env,
    context: Context,
    dispatch: (request: Request) => Promise<Response>,
  ): Promise<Response> => {
    const { pathname } = new URL(request.url)
    if (!under(pathname, basePath)) throw new Error('Mailflare owner gate received a request outside its namespace')

    if (pathname === `${basePath}/favicon.ico` && ['GET', 'HEAD'].includes(request.method)) {
      return Response.redirect(new URL(`${basePath}/helloada-logo.svg`, request.url), 302)
    }

    if (pathname === `${basePath}/api/auth/logout` && request.method === 'POST') {
      const response = await logout(request, env, context)
      const secure = new URL(request.url).protocol === 'https:' ? '; Secure' : ''
      return withoutCache(response, `${SESSION_COOKIE}=; Path=${basePath}; Max-Age=0; HttpOnly; SameSite=Lax${secure}`)
    }

    if (isStandaloneAuthPage(pathname, basePath)) return redirectToPayloadLogin(request)
    if (isStandaloneAuthApi(pathname, basePath)) return jsonError(403, 'Sign in and account management are provided by the HelloAda workspace.')

    if (isPublic(request, pathname, basePath)) return dispatch(request)

    if (!request.headers.get('cookie')) {
      return pathname.startsWith(`${basePath}/api/`)
        ? jsonError(401, 'The authenticated HelloAda owner session is required.')
        : redirectToPayloadLogin(request)
    }

    const identity = await resolveIdentity(request, env, context)
    if (!identity) {
      return pathname.startsWith(`${basePath}/api/`)
        ? jsonError(401, 'The authenticated HelloAda owner session is required.')
        : redirectToPayloadLogin(request)
    }
    if (typeof identity.subject !== 'string' || !identity.subject.trim()) {
      throw new Error('Payload owner identity is incomplete')
    }

    const session = await provisionOwnerSession(request, env, identity, defaultLocale)
    const authorizedRequest = withSessionCookie(request, session.token)
    const secure = new URL(request.url).protocol === 'https:' ? '; Secure' : ''
    const cookie = session.created
      ? `${SESSION_COOKIE}=${session.token}; Path=${basePath}; Max-Age=${Math.floor(SESSION_MS / 1000)}; HttpOnly; SameSite=Lax${secure}`
      : undefined
    const response = await dispatch(authorizedRequest)
    return withoutCache(response, cookie)
  }
}
