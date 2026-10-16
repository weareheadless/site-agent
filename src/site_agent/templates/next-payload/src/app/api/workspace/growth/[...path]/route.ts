import { NextResponse } from 'next/server'

import { growthGet, growthPost, serviceGrowthPrincipal } from '@/lib/growth-operations'
import { serviceAuthorized } from '@/lib/service-auth'

export const dynamic = 'force-dynamic'

type RouteProps = { params: Promise<{ path?: string[] }> }

const routePath = async (params: RouteProps['params']) => `/${(await params).path?.join('/') || ''}`.replace(/\/$/, '') || '/'
const unauthorized = () => NextResponse.json({ error: 'helloada_growth_error', message: 'service authentication required' }, { status: 401, headers: { 'Cache-Control': 'private, no-store' } })

export async function GET(request: Request, { params }: RouteProps) {
  if (!serviceAuthorized(request)) return unauthorized()
  return growthGet(request, `/growth${await routePath(params)}`, serviceGrowthPrincipal())
}

export async function POST(request: Request, { params }: RouteProps) {
  if (!serviceAuthorized(request)) return unauthorized()
  return growthPost(request, `/growth${await routePath(params)}`, serviceGrowthPrincipal())
}
