const TENANT_MAILFLARE_BINDINGS: Record<string, string> = {
  DB: "MAILFLARE_DB",
  BUCKET: "MAILFLARE_BUCKET",
  INBOUND_QUEUE: "MAILFLARE_INBOUND_QUEUE",
  OUTBOUND_QUEUE: "MAILFLARE_OUTBOUND_QUEUE",
  AGENT_QUEUE: "MAILFLARE_AGENT_QUEUE",
  REALTIME: "MAILFLARE_REALTIME",
  AI: "MAILFLARE_AI",
  LOGIN_RATE_LIMIT: "MAILFLARE_LOGIN_RATE_LIMIT",
  AGENT_RATE_LIMIT: "MAILFLARE_AGENT_RATE_LIMIT",
  BOOKING_RATE_LIMIT: "MAILFLARE_BOOKING_RATE_LIMIT",
  TURNSTILE_SECRET_KEY: "HELLOADA_TURNSTILE_SECRET_KEY",
  TURNSTILE_SITE_KEY: "HELLOADA_TURNSTILE_SITE_KEY",
}

export function asMailflareEnv<Env extends object>(env: Env): Env {
  return new Proxy(env, {
    get(target, property, receiver) {
      const mapped = typeof property === "string" ? TENANT_MAILFLARE_BINDINGS[property] : undefined
      return Reflect.get(target, mapped ?? property, receiver)
    },
  })
}
