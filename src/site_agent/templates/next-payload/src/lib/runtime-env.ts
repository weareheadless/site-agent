import { getCloudflareContext } from '@opennextjs/cloudflare'

/** Read only the request-time binding provisioned for this tenant Worker. */
export function runtimeValue(name: string): string {
  const context = getCloudflareContext()
  const bindings = context.env as unknown as Record<string, unknown>
  const value = bindings[name]
  if (value === undefined || value === null) return ''
  if (typeof value !== 'string') throw new Error(`Worker setting ${name} must be a string binding.`)
  return value.trim()
}
