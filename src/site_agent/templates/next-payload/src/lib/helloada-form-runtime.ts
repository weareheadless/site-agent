import { getCloudflareContext } from "@opennextjs/cloudflare"
import { getPayload } from "payload"

import config from "@payload-config"
import type { MailflareD1 } from "../../mailflare-provisioning"

type RateLimiter = { limit: (input: { key: string }) => Promise<{ success: boolean }> }
type FormBindings = {
  HELLOADA_TENANT_ID?: string
  HELLOADA_FORM_RATE_LIMIT?: RateLimiter
  HELLOADA_TURNSTILE_SECRET_KEY?: string
  MAILFLARE_DB?: MailflareD1
  MAILFLARE_ADDRESS?: string
}

export const messageRuntime = async () => {
  const payload = await getPayload({ config })
  const context = await getCloudflareContext({ async: true }) as unknown as { env?: FormBindings }
  return { payload, env: context.env || {} }
}

export const tenantIdentity = () => String(process.env.HELLOADA_TENANT_ID || "").trim()

export const verifyTurnstile = async (
  secret: string,
  token: string,
  remoteIp: string,
  expectedHostname: string,
) => {
  const form = new URLSearchParams({ secret, response: token, idempotency_key: globalThis.crypto.randomUUID() })
  if (remoteIp) form.set("remoteip", remoteIp)
  const response = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: form,
    signal: AbortSignal.timeout(5_000),
  })
  if (!response.ok) throw new Error("Turnstile verification service is unavailable.")
  const result = await response.json() as { success?: boolean; hostname?: string }
  return result.success === true && result.hostname === expectedHostname
}
