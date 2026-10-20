import { provisionTenantMailflareMailbox } from './mailflare-provisioning.ts'
import { migratePayloadMailbox, type PayloadMailboxMigrationEnv } from './mailflare-payload-migration.ts'

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

const mailboxRuntimeReady = (env: MailflareEnv) => Boolean(
  env.MAILFLARE_DB
  && [env.MAILFLARE_ADDRESS, env.MAILFLARE_ZONE_ID, env.MAILFLARE_ROUTING_STATUS]
    .every((value) => typeof value === 'string' && value.trim()),
)

const mailboxSetupResponse = (pathname: string, basePath: string) => {
  const message = 'HelloAda is preparing your inbox and booking calendar. They will be available as soon as setup is complete.'
  if (pathname.startsWith(`${basePath}/api/`)) return jsonError(503, message)
  return new Response(
    `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HelloAda · Preparing your inbox</title><style>html,body{min-height:100%;margin:0;background:#15161b;color:#f7f7f8;font:16px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}body{display:grid;place-items:center;padding:24px;box-sizing:border-box}main{width:min(440px,100%);text-align:center}img{width:56px;height:56px;margin-bottom:24px}h1{font-size:24px;letter-spacing:-.03em;margin:0 0 10px}p{color:#b8b8c1;margin:0 auto 24px;max-width:38ch}button{border:0;border-radius:999px;background:#ff7a18;color:#171717;font:600 14px/1.2 Inter,ui-sans-serif,system-ui,sans-serif;padding:12px 18px;cursor:pointer}button:hover{background:#ff9445}</style></head><body><main><img src="/brand/helloada-logo.svg" alt="HelloAda"><h1>Your inbox is being prepared</h1><p>${message}</p><button type="button" onclick="location.reload()">Check again</button></main></body></html>`,
    { status: 503, headers: {
      'Cache-Control': 'no-store',
      'Content-Type': 'text/html; charset=utf-8',
      'Retry-After': '30',
      'X-Content-Type-Options': 'nosniff',
    } },
  )
}

const mailboxMigrationResponse = (pathname: string, basePath: string) => {
  const message = 'A one-time inbox setup is already running. Your mailbox will open as soon as it finishes.'
  if (pathname.startsWith(`${basePath}/api/`)) {
    return Response.json({ error: 'mailbox_migration_in_progress', message }, {
      status: 503,
      headers: { 'Cache-Control': 'no-store', 'Retry-After': '3' },
    })
  }
  return new Response(
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="3"><title>HelloAda · Preparing your inbox</title><style>html,body{min-height:100%;margin:0;background:#15161b;color:#f7f7f8;font:16px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}body{display:grid;place-items:center;padding:24px;box-sizing:border-box}main{width:min(440px,100%);text-align:center}img{width:56px;height:56px;margin-bottom:24px}h1{font-size:24px;letter-spacing:-.03em;margin:0 0 10px}p{color:#b8b8c1;margin:0 auto 24px;max-width:38ch}button{border:0;border-radius:999px;background:#ff7a18;color:#171717;font:600 14px/1.2 Inter,ui-sans-serif,system-ui,sans-serif;padding:12px 18px;cursor:pointer}button:hover{background:#ff9445}</style></head><body><main><img src="/brand/helloada-logo.svg" alt="HelloAda"><h1>Preparing your inbox</h1><p>A one-time inbox setup is already running. Your mailbox will open as soon as it finishes.</p><button type="button" onclick="location.reload()">Check now</button></main></body></html>',
    { status: 503, headers: {
      'Cache-Control': 'no-store',
      'Content-Type': 'text/html; charset=utf-8',
      'Retry-After': '3',
      'X-Content-Type-Options': 'nosniff',
    } },
  )
}

const under = (pathname: string, root: string) => pathname === root || pathname.startsWith(`${root}/`)

const isStatic = (request: Request, pathname: string, basePath: string) =>
  ['GET', 'HEAD'].includes(request.method)
  && (pathname.startsWith(`${basePath}/_next/static/`)
    || [`${basePath}/favicon.ico`, `${basePath}/manifest.webmanifest`].includes(pathname))

const isPublic = (request: Request, pathname: string, basePath: string) => {
  if (isStatic(request, pathname, basePath)) return true
  if (pathname.startsWith(`${basePath}/api/inbound/`)
      || pathname.startsWith(`${basePath}/api/public/booking/`)
      || pathname.startsWith(`${basePath}/api/drive/public/`)) return true
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

async function registerTenantBookingOwner(database: D1Binding, tenantId: string, userId: string) {
  const now = Date.now()
  await database.prepare(
    'INSERT OR IGNORE INTO helloada_tenant_owners (tenant_id, owner_user_id, created_at) VALUES (?, ?, ?)',
  ).bind(tenantId, userId, now).run()
  const owner = await database.prepare(
    'SELECT owner_user_id FROM helloada_tenant_owners WHERE tenant_id = ? LIMIT 1',
  ).bind(tenantId).first<{ owner_user_id: string }>()
  if (owner?.owner_user_id !== userId) throw new Error('Mailflare tenant owner identity conflicts with its registered owner')
  await database.prepare(
    "INSERT OR IGNORE INTO helloada_booking_settings (user_id, enabled, time_zone, weekly_availability, max_concurrent_appointments, minimum_notice_hours, booking_window_days, revision, updated_at) VALUES (?, 0, '', '[]', 1, 24, 60, 1, ?)",
  ).bind(userId, now).run()
}

async function provisionOwnerSession(
  request: Request,
  env: MailflareEnv,
  defaultLocale: string,
): Promise<{ state: 'ready'; token: string; created: boolean } | { state: 'migration_in_progress' }> {
  // Payload authenticates the person; mailbox/calendar data belongs to the
  // tenant workspace. Its persisted owner survives login/subject changes.
  const registeredOwner = await env.MAILFLARE_DB.prepare(
    'SELECT owner_user_id FROM helloada_tenant_owners WHERE tenant_id = ? LIMIT 1',
  ).bind(env.HELLOADA_TENANT_ID).first<{ owner_user_id: string }>()
  const userId = registeredOwner
    ? registeredOwner.owner_user_id
    : `ha_${await digest(`tenant:${env.HELLOADA_TENANT_ID}`)}`
  if (registeredOwner) {
    const owner = await env.MAILFLARE_DB.prepare(
      'SELECT password_hash, disabled FROM users WHERE id = ? LIMIT 1',
    ).bind(userId).first<{ password_hash: string; disabled: number }>()
    if (!owner || owner.disabled || owner.password_hash !== SSO_PASSWORD_SENTINEL) {
      throw new Error('Mailflare registered workspace owner is invalid')
    }
  }
  const existingToken = cookieValue(request, SESSION_COOKIE)
  if (existingToken) {
    const tokenHash = await digest(existingToken)
    const session = await env.MAILFLARE_DB.prepare(
      'SELECT users.id AS user_id FROM sessions INNER JOIN users ON users.id = sessions.user_id WHERE sessions.token_hash = ? AND sessions.expires_at > ? AND users.id = ? AND users.disabled = 0 LIMIT 1',
    ).bind(tokenHash, Date.now(), userId).first<{ user_id: string }>()
    if (session?.user_id === userId) {
      const mailbox = await provisionTenantMailflareMailbox({ database: env.MAILFLARE_DB, tenantId: env.HELLOADA_TENANT_ID, address: env.MAILFLARE_ADDRESS, zoneId: env.MAILFLARE_ZONE_ID, routingStatus: env.MAILFLARE_ROUTING_STATUS })
      const migration = await migratePayloadMailbox(env, { ownerUserId: userId, serviceUserId: mailbox.serviceUserId, mailboxId: mailbox.mailboxId, defaultLocale })
      if (migration.state === 'in_progress') return { state: 'migration_in_progress' }
      await registerTenantBookingOwner(env.MAILFLARE_DB, env.HELLOADA_TENANT_ID, userId)
      return { state: 'ready', token: existingToken, created: false }
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
  if (!current) {
    await env.MAILFLARE_DB.prepare(
      'INSERT OR IGNORE INTO users (id, email, password_hash, name, role, is_primary_admin, can_manage_mailboxes, can_manage_domains, can_manage_users, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
    ).bind(userId, `${userId}@identity.helloada.invalid`, SSO_PASSWORD_SENTINEL, SSO_ACCOUNT_NAME, 'user', 0, 0, 0, 0, Date.now()).run()
  } else {
    await env.MAILFLARE_DB.prepare(
      'UPDATE users SET name = ? WHERE id = ? AND disabled = 0',
    ).bind(SSO_ACCOUNT_NAME, userId).run()
  }
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

  const migration = await migratePayloadMailbox(env, {
    ownerUserId: userId,
    serviceUserId: mailbox.serviceUserId,
    mailboxId: mailbox.mailboxId,
    defaultLocale,
  })
  if (migration.state === 'in_progress') return { state: 'migration_in_progress' }
  await registerTenantBookingOwner(env.MAILFLARE_DB, env.HELLOADA_TENANT_ID, userId)

  const token = randomHex(32)
  await env.MAILFLARE_DB.prepare(
    'INSERT INTO sessions (id, user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)',
  ).bind(`ha_sess_${randomHex(16)}`, userId, await digest(token), Date.now() + SESSION_MS, Date.now()).run()
  return { state: 'ready', token, created: true }
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
      return Response.redirect(new URL('/brand/helloada-logo.svg', request.url), 302)
    }

    if (pathname === `${basePath}/api/auth/logout` && request.method === 'POST') {
      const response = await logout(request, env, context)
      const secure = new URL(request.url).protocol === 'https:' ? '; Secure' : ''
      return withoutCache(response, `${SESSION_COOKIE}=; Path=${basePath}; Max-Age=0; HttpOnly; SameSite=Lax${secure}`)
    }

    if (isStandaloneAuthPage(pathname, basePath)) return redirectToPayloadLogin(request)
    if (isStandaloneAuthApi(pathname, basePath)) return jsonError(403, 'Sign in and account management are provided by the HelloAda workspace.')

    if (isStatic(request, pathname, basePath)) return dispatch(request)
    if (!mailboxRuntimeReady(env)) return mailboxSetupResponse(pathname, basePath)
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

    const session = await provisionOwnerSession(request, env, defaultLocale)
    if (session.state === 'migration_in_progress') return mailboxMigrationResponse(pathname, basePath)
    const authorizedRequest = withSessionCookie(request, session.token)
    const secure = new URL(request.url).protocol === 'https:' ? '; Secure' : ''
    const cookie = session.created
      ? `${SESSION_COOKIE}=${session.token}; Path=${basePath}; Max-Age=${Math.floor(SESSION_MS / 1000)}; HttpOnly; SameSite=Lax${secure}`
      : undefined
    const response = await dispatch(authorizedRequest)
    return withoutCache(response, cookie)
  }
}
