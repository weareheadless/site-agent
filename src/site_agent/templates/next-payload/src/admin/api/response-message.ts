/**
 * Owner-facing API errors arrive in two shapes: the workspace bridge returns
 * `{ message }`, while a FastAPI validation or bridge failure returns
 * `{ detail }`. Reading only `message` turns a precise refusal into a generic
 * "could not be published" banner, so both shapes resolve here.
 */
export function responseMessage(
  body: { message?: unknown; detail?: unknown } | null | undefined,
  fallback: string,
): string {
  const message = typeof body?.message === 'string' ? body.message.trim() : ''
  if (message) return message
  const detail = typeof body?.detail === 'string' ? body.detail.trim() : ''
  return detail || fallback
}
