import { NextResponse, type NextRequest } from 'next/server'
import { helloAdaSite } from './helloada.config'
import { workspacePreviewPath } from './lib/workspace-preview-path'
import { resolveRequestLocale, LOCALE_HEADER, LOCALE_COOKIE } from './lib/request-locale'

export function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname
  const publicRoute = !/^\/(?:admin|api|_next|mail|static|helloada-preview)(?:\/|$)/.test(pathname)
  if (publicRoute && request.nextUrl.pathname !== helloAdaSite.routes.preview) {
    const resolved = resolveRequestLocale(request.nextUrl.searchParams.getAll('locale'), request.cookies.get(LOCALE_COOKIE)?.value, helloAdaSite.locales, helloAdaSite.defaultLocale)
    if (!resolved.ok) return new NextResponse('Unsupported locale', { status: 400 })
    const headers = new Headers(request.headers)
    headers.set(LOCALE_HEADER, resolved.locale)
    headers.set('x-helloada-current-url', `${pathname}${request.nextUrl.search}`)
    const path = workspacePreviewPath(pathname, helloAdaSite.routes.preview)
    if (path !== undefined) {
      const destination = request.nextUrl.clone()
      destination.pathname = path
      const response = NextResponse.rewrite(destination, { request: { headers } })
      response.headers.set('X-Robots-Tag', 'noindex, nofollow')
      response.cookies.set(LOCALE_COOKIE, resolved.locale, { path: '/', sameSite: 'lax', secure: process.env.NODE_ENV === 'production' })
      return response
    }
    const response = NextResponse.next({ request: { headers } })
    response.cookies.set(LOCALE_COOKIE, resolved.locale, { path: '/', sameSite: 'lax', secure: process.env.NODE_ENV === 'production' })
    return response
  }
  const path = workspacePreviewPath(request.nextUrl.pathname, helloAdaSite.routes.preview)
  if (path === undefined) return NextResponse.next()
  const destination = request.nextUrl.clone()
  destination.pathname = path
  const response = NextResponse.rewrite(destination)
  response.headers.set('X-Robots-Tag', 'noindex, nofollow')
  return response
}

export const config = { matcher: '/:path*' }
