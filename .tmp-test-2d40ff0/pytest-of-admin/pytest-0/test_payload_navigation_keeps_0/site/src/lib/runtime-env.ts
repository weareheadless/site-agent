import { getCloudflareContext } from '@opennextjs/cloudflare'

/**
 * Read a request-time Worker binding, with a process environment fallback for
 * local development and build-time tooling. Secrets must never be copied into
 * public `vars` or baked into the generated site bundle.
 */
export function runtimeValue(name: string): string {
  try {
    const context = getCloudflareContext()
    const bindings = context.env as unknown as Record<string, unknown>
    const value = String(bindings?.[name] || '').trim()
    if (value) return value
  } catch {
    // Next build and local Node execution do not have Worker bindings.
  }
  return String(process.env[name] || '').trim()
}
