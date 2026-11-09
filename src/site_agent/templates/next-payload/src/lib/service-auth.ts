import crypto from 'node:crypto'
import { helloAdaRuntime } from '@/admin/server/runtime-env'

export function serviceAuthorized(request: Request) {
  const expected = helloAdaRuntime().token
  const supplied = request.headers.get('authorization')?.replace(/^Bearer\s+/i, '') || ''
  if (!expected || !supplied) return false
  const left = Buffer.from(supplied)
  const right = Buffer.from(expected)
  return left.length === right.length && crypto.timingSafeEqual(left, right)
}
