import crypto from 'node:crypto'

export function serviceAuthorized(request: Request) {
  const expected = process.env.HELLOADA_SITE_AGENT_TOKEN || ''
  const supplied = request.headers.get('authorization')?.replace(/^Bearer\s+/i, '') || ''
  if (!expected || !supplied) return false
  const left = Buffer.from(supplied)
  const right = Buffer.from(expected)
  return left.length === right.length && crypto.timingSafeEqual(left, right)
}
