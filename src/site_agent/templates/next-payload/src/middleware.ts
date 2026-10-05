import { NextResponse, type NextRequest } from 'next/server'
import { helloAdaSite } from './helloada.config'
import { workspacePreviewPath } from './lib/workspace-preview-path'

export function middleware(request: NextRequest) {
  const path = workspacePreviewPath(request.nextUrl.pathname, helloAdaSite.routes.preview)
  if (path === undefined) return NextResponse.next()
  const destination = request.nextUrl.clone()
  destination.pathname = path
  const response = NextResponse.rewrite(destination)
  response.headers.set('X-Robots-Tag', 'noindex, nofollow')
  return response
}

export const config = { matcher: '/:path*' }
