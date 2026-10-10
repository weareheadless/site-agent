import { NextResponse } from 'next/server'

import { authenticateHelloAdaRequest } from '@/lib/helloada-auth'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  if (request.headers.has('authorization')) {
    return NextResponse.json({ error: 'A Payload owner session is required.' }, {
      status: 401,
      headers: { 'Cache-Control': 'no-store' },
    })
  }

  const auth = await authenticateHelloAdaRequest(request)
  if (!auth) {
    return NextResponse.json({ error: 'A Payload owner session is required.' }, {
      status: 401,
      headers: { 'Cache-Control': 'no-store' },
    })
  }

  const subject = String((auth.user as typeof auth.user & { helloadaSubject?: string }).helloadaSubject ?? '').trim()
  if (!subject) {
    return NextResponse.json({ error: 'The Payload owner profile is incomplete.' }, {
      status: 403,
      headers: { 'Cache-Control': 'no-store' },
    })
  }

  return NextResponse.json({ subject }, {
    headers: { 'Cache-Control': 'no-store' },
  })
}
