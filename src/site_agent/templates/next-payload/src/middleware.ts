import { NextResponse, type NextRequest } from 'next/server'
import { helloAdaSite } from './helloada.config'
import { workspacePreviewPath } from './lib/workspace-preview-path'
import { resolveRequestLocale, LOCALE_HEADER, LOCALE_COOKIE } from './lib/locale-routing'

export function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname
  const previewPath = workspacePreviewPath(pathname, helloAdaSite.routes.preview)
  if (previewPath !== undefined) {
    const destination = request.nextUrl.clone()
    destination.pathname = previewPath
    const response = NextResponse.rewrite(destination)
    response.headers.set('X-Robots-Tag', 'noindex, nofollow')
    return response
  }
  const excludedRoute = /^\/(?:admin|api|_next|mail|static|helloada-preview)(?:\/|$)/.test(pathname)
  if (excludedRoute) {
    const headers = new Headers(request.headers)
    headers.delete(LOCALE_HEADER)
    headers.delete('x-helloada-current-url')
    return NextResponse.next({ request: { headers } })
  }
  const publicRoute = !excludedRoute
  if (publicRoute && request.nextUrl.pathname !== helloAdaSite.routes.preview) {
    const resolved = resolveRequestLocale(request.nextUrl.searchParams.getAll('locale'), request.cookies.get(LOCALE_COOKIE)?.value, helloAdaSite.locales, helloAdaSite.defaultLocale)
    if (!resolved.ok) return new NextResponse('Unsupported locale', { status: 400 })
    const headers = new Headers(request.headers)
    headers.set(LOCALE_HEADER, resolved.locale)
    headers.set('x-helloada-current-url', `${pathname}${request.nextUrl.search}`)
    const response = NextResponse.next({ request: { headers } })
    response.cookies.set(LOCALE_COOKIE, resolved.locale, { path: '/', sameSite: 'lax', secure: process.env.NODE_ENV === 'production' })
    return response
  }
  const headers = new Headers(request.headers)
  headers.delete(LOCALE_HEADER)
  headers.delete('x-helloada-current-url')
  return NextResponse.next({ request: { headers } })
}

export const config = { matcher: '/:path*' }
